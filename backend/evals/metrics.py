"""
Offline quality metrics for claim grounding and financial reconciliation.

Used by unit/eval tests and by ``run_eval.py``.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any


def claim_support_rate(claims: Sequence[Any]) -> float:
    """supported_claims / max(total_claims, 1)."""
    total = len(claims)
    if total == 0:
        return 0.0
    supported = sum(1 for c in claims if _status(c) == "supported")
    return supported / total


def unsupported_claim_rate(claims: Sequence[Any]) -> float:
    """
    Rate of claims that failed closed-book verification.

    Counts ``unsupported`` and ``contradicted`` (not ``insufficient``).
    """
    total = len(claims)
    if total == 0:
        return 0.0
    bad = sum(1 for c in claims if _status(c) in ("unsupported", "contradicted"))
    return bad / total


def _status(claim: Any) -> str:
    if isinstance(claim, dict):
        return str(claim.get("status", "insufficient"))
    return str(getattr(claim, "status", "insufficient"))


def _normalize_flag(flag: str) -> str:
    """Lowercase + collapse whitespace for fuzzy flag matching."""
    return re.sub(r"\s+", " ", flag.strip().lower())


_DISCREPANCY_RE = re.compile(
    r"(?P<label>.+?)\s+discrepancy\s+\((?P<period>[^)]+)\)",
    re.IGNORECASE,
)


def _flag_signature(flag: str) -> tuple[str, str]:
    """
    Core identity of a reconciliation flag: (metric_label, period).

    Lets golden short forms match Phase-4 enriched messages that append
    normalized values and delta %.
    """
    m = _DISCREPANCY_RE.search(flag)
    if m:
        label = re.sub(r"\s+", " ", m.group("label").strip().lower())
        period = re.sub(r"\s+", "", m.group("period").strip().lower())
        return (label, period)
    return (_normalize_flag(flag), "")


def _flags_match(predicted: str, expected: str) -> bool:
    p_sig, e_sig = _flag_signature(predicted), _flag_signature(expected)
    if p_sig[0] and e_sig[0] and p_sig == e_sig:
        return True
    p, e = _normalize_flag(predicted), _normalize_flag(expected)
    return p == e or p in e or e in p


def reconciliation_precision_recall(
    predicted_flags: Sequence[str],
    expected_flags: Sequence[str],
) -> dict[str, float]:
    """
    Precision/recall of reconciliation flags vs golden expected flags.

    Matching uses (metric, period) signatures so enriched Phase-4 flag text
    still hits short golden expectations, with substring fallback.
    """
    pred = list(predicted_flags)
    exp = list(expected_flags)

    if not exp and not pred:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0}

    matched_exp: set[int] = set()
    tp = 0
    for p in pred:
        hit = False
        for i, e in enumerate(exp):
            if i in matched_exp:
                continue
            if _flags_match(p, e):
                matched_exp.add(i)
                hit = True
                break
        if hit:
            tp += 1

    fp = len(pred) - tp
    fn = len(exp) - len(matched_exp)
    precision = tp / max(len(pred), 1) if pred else (1.0 if not exp else 0.0)
    recall = tp / max(len(exp), 1) if exp else (1.0 if not pred else 0.0)
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
    }


@dataclass
class LatencyCostCounters:
    """
    Simple log-based latency / approx cost counters.

    Token counts are approximate (chars/4) when exact usage is unavailable.
    Cost uses a configurable USD-per-1k-tokens rate (default flash-ish).
    """

    usd_per_1k_tokens: float = 0.00015
    events: list[dict[str, Any]] = field(default_factory=list)
    _open: dict[str, float] = field(default_factory=dict, repr=False)

    def start(self, name: str) -> None:
        self._open[name] = time.perf_counter()

    def stop(
        self,
        name: str,
        *,
        prompt_chars: int = 0,
        completion_chars: int = 0,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        model: str = "",
    ) -> dict[str, Any]:
        started = self._open.pop(name, None)
        latency_ms = (time.perf_counter() - started) * 1000.0 if started is not None else 0.0
        p_tok = prompt_tokens if prompt_tokens is not None else max(prompt_chars, 0) // 4
        c_tok = (
            completion_tokens
            if completion_tokens is not None
            else max(completion_chars, 0) // 4
        )
        total_tok = p_tok + c_tok
        cost_usd = (total_tok / 1000.0) * self.usd_per_1k_tokens
        event = {
            "name": name,
            "latency_ms": round(latency_ms, 3),
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": total_tok,
            "approx_cost_usd": round(cost_usd, 8),
            "model": model,
        }
        self.events.append(event)
        return event

    def summary(self) -> dict[str, Any]:
        if not self.events:
            return {
                "calls": 0,
                "total_latency_ms": 0.0,
                "total_tokens": 0,
                "approx_cost_usd": 0.0,
            }
        return {
            "calls": len(self.events),
            "total_latency_ms": round(sum(e["latency_ms"] for e in self.events), 3),
            "total_tokens": sum(e["total_tokens"] for e in self.events),
            "approx_cost_usd": round(sum(e["approx_cost_usd"] for e in self.events), 8),
            "by_name": {
                e["name"]: {
                    "latency_ms": e["latency_ms"],
                    "total_tokens": e["total_tokens"],
                    "approx_cost_usd": e["approx_cost_usd"],
                }
                for e in self.events
            },
        }

    def log_lines(self) -> list[str]:
        lines = []
        for e in self.events:
            lines.append(
                f"[eval] {e['name']} latency_ms={e['latency_ms']:.1f} "
                f"tokens={e['total_tokens']} cost_usd≈{e['approx_cost_usd']:.6f}"
            )
        s = self.summary()
        lines.append(
            f"[eval] TOTAL calls={s['calls']} latency_ms={s['total_latency_ms']:.1f} "
            f"tokens={s['total_tokens']} cost_usd≈{s['approx_cost_usd']:.6f}"
        )
        return lines


def aggregate_claims_from_sections(sections: Iterable[Any]) -> list[Any]:
    """Flatten claims from MemoSection objects or dicts."""
    out: list[Any] = []
    for sec in sections:
        if isinstance(sec, dict):
            out.extend(sec.get("claims") or [])
        else:
            out.extend(getattr(sec, "claims", None) or [])
    return out


def score_memo_against_expected(
    *,
    claims: Sequence[Any],
    predicted_flags: Sequence[str],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Compute the Phase-3 metric bundle against a golden ``expected.json``."""
    support = claim_support_rate(claims)
    unsup = unsupported_claim_rate(claims)
    recon = reconciliation_precision_recall(
        list(predicted_flags),
        list(expected.get("reconciliation_flags") or []),
    )
    min_support = float(expected.get("min_supported_claim_rate", 0.0))
    max_unsup = float(expected.get("max_unsupported_claim_rate", 1.0))
    min_recon_f1 = float(expected.get("min_reconciliation_f1", 0.0))

    return {
        "claim_support_rate": support,
        "unsupported_claim_rate": unsup,
        "reconciliation": recon,
        "pass_support": support >= min_support,
        "pass_unsupported": unsup <= max_unsup,
        "pass_reconciliation": recon["f1"] >= min_recon_f1,
        "passed": (
            support >= min_support
            and unsup <= max_unsup
            and recon["f1"] >= min_recon_f1
        ),
    }
