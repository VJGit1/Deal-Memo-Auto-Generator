"""
Human-in-the-loop review API.

Edit sections, re-verify claims via grounding, approve/override low-confidence
sections, and produce versioned exports after the approval gate clears.

Works with Redis-backed ``JobRecord`` from ``api.jobs`` (memo stored as JSON dict).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException
from google import genai
from pydantic import BaseModel, Field

from dmag.config import CONFIDENCE_THRESHOLD, TEMPLATE_PATH
from dmag.exporter import Exporter
from dmag.grounding import GroundingService
from dmag.pipeline import _aggregate_supported_claim_rate
from dmag.schema import MemoOutput, MemoSection

from api.jobs import JobRecord, get_job, save_result

router = APIRouter(prefix="/api/pipeline", tags=["review"])

REVIEW_STATE_FILE = "review_state.json"


# --- Request / response models ---


class ClaimEdit(BaseModel):
    id: str
    text: str
    citation_ids: list[str] = Field(default_factory=list)
    status: str = "insufficient"


class SectionPatch(BaseModel):
    content: str | None = None
    claims: list[ClaimEdit] | None = None


class SectionApproval(BaseModel):
    title: str
    override_reason: str | None = None


class ApproveRequest(BaseModel):
    approvals: list[SectionApproval]


# --- Job / memo helpers (Redis result is a dict) ---


def _require_job(job_id: str) -> JobRecord:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("pending", "running"):
        raise HTTPException(status_code=202, detail="Pipeline still running")
    if job.status == "error":
        raise HTTPException(status_code=500, detail=job.error or "Pipeline failed")
    if not job.result or "memo" not in job.result:
        raise HTTPException(status_code=500, detail="No result available")
    return job


def get_memo(job: JobRecord) -> MemoOutput:
    assert job.result is not None
    return MemoOutput.model_validate(job.result["memo"])


def set_memo(job: JobRecord, memo: MemoOutput, *, supported_claim_rate: float | None = None) -> None:
    """Persist memo (and optional claim-rate) back into Redis result payload."""
    assert job.result is not None
    job.result["memo"] = memo.model_dump()
    if supported_claim_rate is not None:
        stats = job.result.setdefault("stats", {})
        stats["supported_claim_rate"] = supported_claim_rate
    save_result(job.job_id, job.result)


def _review_path(job: JobRecord) -> Path:
    return Path(job.output_dir) / REVIEW_STATE_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_section_state() -> dict[str, Any]:
    return {
        "approved": False,
        "override_reason": None,
        "approved_at": None,
    }


def _build_initial_state(job: JobRecord) -> dict[str, Any]:
    memo = get_memo(job)
    return {
        "export_version": 0,
        "sections": {sec.title: _default_section_state() for sec in memo.sections},
        "export_history": [],
        "updated_at": _utc_now(),
    }


def load_review_state(job: JobRecord) -> dict[str, Any]:
    path = _review_path(job)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = _build_initial_state(job)

    memo_titles = {sec.title for sec in get_memo(job).sections}
    sections = data.setdefault("sections", {})
    for title in memo_titles:
        if title not in sections:
            sections[title] = _default_section_state()
    for orphan in list(sections.keys()):
        if orphan not in memo_titles:
            del sections[orphan]

    data.setdefault("export_version", 0)
    data.setdefault("export_history", [])
    return data


def save_review_state(job: JobRecord, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    path = _review_path(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def seed_review_state(job_id: str) -> None:
    """Create review_state.json after pipeline complete (called from RQ worker)."""
    job = get_job(job_id)
    if not job or not job.result:
        return
    state = load_review_state(job)
    save_review_state(job, state)


def _find_section(job: JobRecord, title: str) -> tuple[int, MemoSection, MemoOutput]:
    decoded = unquote(title)
    memo = get_memo(job)
    for i, sec in enumerate(memo.sections):
        if sec.title == decoded or sec.title == title:
            return i, sec, memo
    raise HTTPException(status_code=404, detail=f"Section not found: {decoded}")


def section_needs_review(sec: MemoSection, threshold: float = CONFIDENCE_THRESHOLD) -> bool:
    return sec.confidence_score < threshold


def pending_review_titles(job: JobRecord, state: dict[str, Any] | None = None) -> list[str]:
    state = state or load_review_state(job)
    pending: list[str] = []
    for sec in get_memo(job).sections:
        if not section_needs_review(sec):
            continue
        st = state.get("sections", {}).get(sec.title) or _default_section_state()
        if st.get("approved") or st.get("override_reason"):
            continue
        pending.append(sec.title)
    return pending


def export_allowed(job: JobRecord, state: dict[str, Any] | None = None) -> bool:
    return len(pending_review_titles(job, state)) == 0


def assert_export_allowed(job: JobRecord, state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or load_review_state(job)
    pending = pending_review_titles(job, state)
    if pending:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Export blocked until low-confidence sections are approved or overridden",
                "pending_sections": pending,
            },
        )
    return state


def review_payload(job: JobRecord, state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or load_review_state(job)
    pending = pending_review_titles(job, state)
    return {
        "review_state": state,
        "pending_sections": pending,
        "export_allowed": len(pending) == 0,
        "export_version": state.get("export_version", 0),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
    }


def _persist_memo(job: JobRecord, memo: MemoOutput, *, supported_claim_rate: float | None = None) -> None:
    """Keep Redis memo and on-disk metadata JSON in sync."""
    exporter = Exporter(
        template_path=_template_for(job),
        output_dir=job.output_dir,
        confidence_threshold=CONFIDENCE_THRESHOLD,
    )
    memo.evidence_appendix = exporter.build_appendix(list(memo.sections))
    set_memo(job, memo, supported_claim_rate=supported_claim_rate)

    meta_path = Path(job.result["output_json"])  # type: ignore[index]
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(memo.model_dump(), indent=2, default=str), encoding="utf-8")


def _template_for(job: JobRecord) -> Path:
    if job.template_path and Path(job.template_path).exists():
        return Path(job.template_path)
    return TEMPLATE_PATH


def _gemini_client():
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


# --- Endpoints ---


@router.get("/{job_id}/review")
async def get_review(job_id: str) -> dict[str, Any]:
    job = _require_job(job_id)
    state = load_review_state(job)
    save_review_state(job, state)
    return review_payload(job, state)


@router.patch("/{job_id}/sections/{title}")
async def patch_section(job_id: str, title: str, body: SectionPatch) -> dict[str, Any]:
    """Edit section content and/or claims. Clears approval for that section."""
    job = _require_job(job_id)
    idx, sec, memo = _find_section(job, title)

    if body.content is None and body.claims is None:
        raise HTTPException(status_code=400, detail="Provide content and/or claims to update")

    data = sec.model_dump()
    if body.content is not None:
        data["content"] = body.content
    if body.claims is not None:
        data["claims"] = [c.model_dump() for c in body.claims]

    updated = MemoSection.model_validate(data)
    sections = list(memo.sections)
    sections[idx] = updated
    memo.sections = sections

    state = load_review_state(job)
    st = state["sections"].setdefault(updated.title, _default_section_state())
    st["approved"] = False
    st["override_reason"] = None
    st["approved_at"] = None
    save_review_state(job, state)
    _persist_memo(job, memo)

    return {
        "section": updated.model_dump(),
        **review_payload(job, state),
    }


@router.post("/{job_id}/sections/{title}/reverify")
async def reverify_section(job_id: str, title: str) -> dict[str, Any]:
    """Re-run claim grounding only (extract if needed + verify against evidence quotes)."""
    job = _require_job(job_id)
    idx, sec, memo = _find_section(job, title)

    client = _gemini_client()
    grounding = GroundingService(client)

    existing = sec.claims if sec.claims else None
    claims = grounding.extract_claims(sec.content, sec.evidence_chunks, existing=existing)
    claims = grounding.verify_claims(claims, sec.evidence_chunks)
    summary = grounding.build_summary(claims)
    confidence = grounding.confidence_from_claims(claims)
    content = grounding.bracket_unsupported(sec.content, claims)

    data = sec.model_dump()
    data["content"] = content
    data["claims"] = [c.model_dump() for c in claims]
    data["verification_summary"] = summary.model_dump()
    data["confidence_score"] = confidence
    updated = MemoSection.model_validate(data)

    sections = list(memo.sections)
    sections[idx] = updated
    memo.sections = sections
    rate = _aggregate_supported_claim_rate(sections)

    state = load_review_state(job)
    st = state["sections"].setdefault(updated.title, _default_section_state())
    st["approved"] = False
    st["override_reason"] = None
    st["approved_at"] = None
    save_review_state(job, state)
    _persist_memo(job, memo, supported_claim_rate=rate)

    return {
        "section": updated.model_dump(),
        **review_payload(job, state),
    }


@router.post("/{job_id}/approve")
async def approve_sections(job_id: str, body: ApproveRequest) -> dict[str, Any]:
    """
    Mark sections approved. Low-confidence sections clear the export gate when
    approved, or when overridden with a non-empty override_reason.
    """
    job = _require_job(job_id)
    if not body.approvals:
        raise HTTPException(status_code=400, detail="approvals list is required")

    state = load_review_state(job)
    memo_by_title = {sec.title: sec for sec in get_memo(job).sections}

    for item in body.approvals:
        title = item.title
        if title not in memo_by_title:
            raise HTTPException(status_code=404, detail=f"Section not found: {title}")
        reason = (item.override_reason or "").strip() or None

        st = state["sections"].setdefault(title, _default_section_state())
        st["approved"] = True
        st["override_reason"] = reason
        st["approved_at"] = _utc_now()

    save_review_state(job, state)
    return review_payload(job, state)


@router.post("/{job_id}/export")
async def export_versioned(job_id: str) -> dict[str, Any]:
    """Produce next versioned export when the approval gate is clear."""
    job = _require_job(job_id)
    state = assert_export_allowed(job)
    memo = get_memo(job)

    next_version = int(state.get("export_version", 0) or 0) + 1
    exporter = Exporter(
        template_path=_template_for(job),
        output_dir=job.output_dir,
        confidence_threshold=CONFIDENCE_THRESHOLD,
    )
    paths = exporter.export(
        memo,
        version=next_version,
        review_state=state,
    )

    state["export_version"] = next_version
    state.setdefault("export_history", []).append(
        {
            "version": next_version,
            "exported_at": _utc_now(),
            "docx": paths["docx"].name,
            "json": paths["json"].name,
            "decisions": {
                title: dict(st) for title, st in state.get("sections", {}).items()
            },
        }
    )
    save_review_state(job, state)

    assert job.result is not None
    job.result["output_docx"] = str(paths["docx"])
    job.result["output_json"] = str(paths["json"])
    save_result(job.job_id, job.result)

    return {
        "export_version": next_version,
        "docx": paths["docx"].name,
        "json": paths["json"].name,
        "download_urls": {
            "docx": f"/api/pipeline/{job.job_id}/download/docx?version={next_version}",
            "json": f"/api/pipeline/{job.job_id}/download/json?version={next_version}",
        },
        **review_payload(job, state),
    }


def resolve_download_path(job: JobRecord, kind: str, version: int | None = None) -> Path:
    """Resolve docx/json path for download. kind: 'docx' | 'json'. Enforces approval gate."""
    state = load_review_state(job)
    assert_export_allowed(job, state)

    out = Path(job.output_dir)
    ver = version if version is not None else int(state.get("export_version", 0) or 0)

    if ver > 0:
        if kind == "docx":
            path = out / f"final_memo_v{ver}.docx"
        else:
            path = out / f"final_memo_v{ver}_metadata.json"
        if path.exists():
            return path

    assert job.result is not None
    if kind == "docx":
        draft = out / "final_memo.docx"
        if draft.exists():
            return draft
        return Path(job.result["output_docx"])
    draft_json = out / "final_memo_metadata.json"
    if draft_json.exists():
        return draft_json
    return Path(job.result["output_json"])
