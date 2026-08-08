"""
DMAG FastAPI backend — wraps dmag.pipeline for React frontend.

Dev run (from backend/, after ``pip install -e .`` and Redis + RQ worker):
  uvicorn api.main:app --reload --port 8000
Frontend: cd ../frontend && npm run dev
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from dmag.gemini_client import configure_logging

from api.jobs import (
    ErrorCode,
    create_job,
    enqueue_pipeline,
    gemini_key_present,
    get_job,
    redis_healthy,
)
from api.review import (
    load_review_state,
    resolve_download_path,
    review_payload,
    router as review_router,
)

configure_logging()

ALLOWED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".docx", ".txt"}

app = FastAPI(title="DMAG API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review_router)


@app.post("/api/pipeline/run")
async def start_pipeline(
    files: list[UploadFile] = File(...),
    template: UploadFile | None = File(None),
) -> dict[str, str]:
    """Upload DD files and enqueue pipeline on RQ. Returns job_id."""
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one document.")

    if not redis_healthy():
        raise HTTPException(
            status_code=503,
            detail={"message": "Redis unavailable", "error_code": ErrorCode.REDIS_UNAVAILABLE.value},
        )

    raw_dir = Path(tempfile.mkdtemp(prefix="dmag_api_raw_"))
    output_dir = Path(tempfile.mkdtemp(prefix="dmag_api_out_"))
    template_path: Path | None = None

    saved = 0
    try:
        for uf in files:
            ext = Path(uf.filename or "").suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            dest = raw_dir / (uf.filename or f"file{ext}")
            dest.write_bytes(await uf.read())
            saved += 1

        if saved == 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "No valid file types uploaded.",
                    "error_code": ErrorCode.INVALID_UPLOAD.value,
                },
            )

        if template and template.filename:
            template_path = raw_dir / "memo_template.docx"
            template_path.write_bytes(await template.read())

        job = create_job(raw_dir, output_dir, template_path)
        enqueue_pipeline(job.job_id)
        return {"job_id": job.job_id}
    except HTTPException:
        shutil.rmtree(raw_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(raw_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/pipeline/{job_id}/events")
async def pipeline_events(job_id: str) -> EventSourceResponse:
    """SSE stream of pipeline progress events."""

    async def event_generator():
        job = get_job(job_id)
        if not job:
            yield {
                "event": "failed",
                "data": json.dumps(
                    {
                        "message": "Job not found",
                        "status": "error",
                        "error_code": ErrorCode.JOB_NOT_FOUND.value,
                    }
                ),
            }
            return

        last = 0
        while True:
            job = get_job(job_id)
            if not job:
                yield {
                    "event": "failed",
                    "data": json.dumps(
                        {
                            "message": "Job expired or missing",
                            "status": "error",
                            "error_code": ErrorCode.JOB_NOT_FOUND.value,
                        }
                    ),
                }
                return

            events = job.events
            while last < len(events):
                evt = events[last]
                last += 1
                yield {"event": "progress", "data": json.dumps(evt)}

            if job.status == "complete":
                yield {
                    "event": "complete",
                    "data": json.dumps(
                        {"step": 8, "total": 8, "message": "Done", "status": "complete"}
                    ),
                }
                return
            if job.status == "error":
                yield {
                    "event": "failed",
                    "data": json.dumps(
                        {
                            "message": job.error or "Pipeline failed",
                            "status": "error",
                            "error_code": job.error_code or ErrorCode.PIPELINE_ERROR.value,
                        }
                    ),
                }
                return

            await asyncio.sleep(0.4)

    return EventSourceResponse(event_generator())


@app.get("/api/pipeline/{job_id}/result")
async def pipeline_result(job_id: str) -> dict:
    """MemoOutput JSON, HITL review fields, and download paths when job is complete."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("running", "pending"):
        raise HTTPException(status_code=202, detail="Pipeline still running")
    if job.status == "error":
        raise HTTPException(
            status_code=500,
            detail={
                "message": job.error or "Pipeline failed",
                "error_code": job.error_code or ErrorCode.PIPELINE_ERROR.value,
            },
        )
    if not job.result:
        raise HTTPException(status_code=500, detail="No result available")

    result = job.result
    state = load_review_state(job)
    version = int(state.get("export_version", 0) or 0)
    download_urls = {
        "docx": f"/api/pipeline/{job_id}/download/docx",
        "json": f"/api/pipeline/{job_id}/download/json",
    }
    if version > 0:
        download_urls = {
            "docx": f"/api/pipeline/{job_id}/download/docx?version={version}",
            "json": f"/api/pipeline/{job_id}/download/json?version={version}",
        }
    return {
        "job_id": job_id,
        "status": "complete",
        "memo": result["memo"],
        "stats": result["stats"],
        "download_urls": download_urls,
        **review_payload(job, state),
    }


@app.get("/api/pipeline/{job_id}/download/docx")
async def download_docx(
    job_id: str,
    version: int | None = Query(default=None),
) -> FileResponse:
    job = get_job(job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Job or file not found")
    path = resolve_download_path(job, "docx", version)
    if not path.exists():
        raise HTTPException(status_code=404, detail="DOCX not found")
    fname = path.name if path.name.startswith("final_memo_v") else "final_memo.docx"
    return FileResponse(
        path,
        filename=fname,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/pipeline/{job_id}/download/json")
async def download_json(
    job_id: str,
    version: int | None = Query(default=None),
) -> FileResponse:
    job = get_job(job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Job or file not found")
    path = resolve_download_path(job, "json", version)
    if not path.exists():
        raise HTTPException(status_code=404, detail="JSON not found")
    fname = path.name if "final_memo_v" in path.name else "final_memo_metadata.json"
    return FileResponse(
        path,
        filename=fname,
        media_type="application/json",
    )


@app.get("/api/health")
async def health() -> dict:
    """Liveness + dependency checks (Redis ping, GEMINI_API_KEY presence)."""
    redis_ok = redis_healthy()
    gemini_ok = gemini_key_present()
    status = "ok" if redis_ok and gemini_ok else "degraded"
    return {
        "status": status,
        "redis": "ok" if redis_ok else "unavailable",
        "gemini_api_key": "present" if gemini_ok else "missing",
    }
