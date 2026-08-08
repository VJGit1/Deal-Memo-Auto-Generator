# Interview narrative — DMAG

## Problem

PE associates spend hours turning a messy due diligence packet (CIM, financials, tax returns, meeting notes) into a structured memo with citations. The draft must be **auditable** (every number traceable) and **safe** (no invented facts, no silent contradictions). The tool should accelerate drafting—not replace analyst judgment.

## v1 failure modes

What a naive “RAG + write paragraphs” pipeline got wrong:

1. **Ungrounded prose** — Sections looked fluent but sentences were not claim-traceable; confidence was a retrieval heuristic, not verification.
2. **Brittle retrieval** — Fixed char chunks + dense-only search missed financial jargon; embed failures could degrade silently.
3. **False reconcile flags** — `"52.9B"` vs `"$52,900,000"` or `FY24` vs `FY2024` looked like discrepancies.
4. **Toy job runner** — In-memory threads, no health checks, weak error typing—hard to defend as “production-shaped.”
5. **HITL as a banner** — UI said “review required” but export was not gated; no edit → re-verify → approve workflow.

## What was built

| Capability | Engineering point |
|------------|-------------------|
| **Claim-level grounding** | Extract atomic claims, judge only against cited quotes (closed-book), calibrate section confidence from support rate. |
| **Agent loop** | Generate → verify → re-retrieve on gaps (≤2 rounds); bracket unsupported text. |
| **Hybrid retrieval** | Semantic chunks + Chroma + BM25 fusion; fail loud on embeddings. |
| **Numeric reconciliation** | Normalize currency/multipliers/periods; relative-tolerance compare on canonical (metric, period). |
| **Eval harness** | `gold_deal` fixtures + cassette offline path; live eval behind `RUN_LIVE_EVAL=1`. |
| **Redis + RQ** | Enqueued jobs, TTL/cleanup, structlog with `job_id` / latency, typed SSE errors, `/api/health`. |
| **Real HITL** | PATCH / reverify / approve / versioned export; downloads blocked until low-confidence sections clear. |

Out of scope (and said so): multi-tenant auth, LinkedIn/G2 enrichment, K8s deploy, fine-tuning.

## Metrics (how you prove it)

Offline (CI-friendly):

- **Supported claim rate** — fraction of claims judged `supported` against citations.
- **Unsupported / contradicted rate** — residual hallucination / conflict surface.
- **Reconcile flag precision & recall** — vs golden expected flags on `gold_deal`.
- **Latency / cost counters** — log-based approx for demo honesty.

Commands:

```bash
cd backend && pip install -e ".[dev]"
python -m pytest tests/ -q
python -m evals.run_eval
```

Talking point: “We didn’t optimize for prettier prose—we measured whether claims are supported, whether numeric flags are real, and whether a human can block a bad export.”
