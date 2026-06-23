"""
DMAG FastAPI backend — wraps src/pipeline.py for React frontend.

Dev run from backend/:
  uvicorn api.main:app --reload --port 8000
Frontend: cd ../frontend && npm run dev
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from config import TEMPLATE_PATH  # noqa: E402
from pipeline import run_pipeline  # noqa: E402

from api.jobs import Job, create_job, get_job  # noqa: E402

ALLOWED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".docx", ".txt"}

app = FastAPI(title="DMAG API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_job(job: Job) -> None:
    """Execute pipeline in background thread."""
    job.set_running()
    job.push_event(0, 8, "Pipeline started", "running")

    def on_progress(step: int, total: int, message: str) -> None:
        job.push_event(step, total, message, "running")

    try:
        if not os.getenv("GEMINI_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY not set in .env")

        template = job.template_path if job.template_path and job.template_path.exists() else TEMPLATE_PATH
        result = run_pipeline(
            raw_dir=job.raw_dir,
            template_path=template,
            output_dir=job.output_dir,
            on_progress=on_progress,
        )
        job.set_complete(result)
    except Exception as exc:
        job.set_error(str(exc))


@app.post("/api/pipeline/run")
async def start_pipeline(
    files: list[UploadFile] = File(...),
    template: UploadFile | None = File(None),
) -> dict[str, str]:
    """Upload DD files and start pipeline. Returns job_id."""
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one document.")

    raw_dir = Path(tempfile.mkdtemp(prefix="dmag_api_raw_"))
    output_dir = Path(tempfile.mkdtemp(prefix="dmag_api_out_"))
    template_path: Path | None = None

    saved = 0
    for uf in files:
        ext = Path(uf.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue
        dest = raw_dir / (uf.filename or f"file{ext}")
        dest.write_bytes(await uf.read())
        saved += 1

    if saved == 0:
        shutil.rmtree(raw_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No valid file types uploaded.")

    if template and template.filename:
        template_path = raw_dir / "memo_template.docx"
        template_path.write_bytes(await template.read())

    job = create_job(raw_dir, output_dir, template_path)
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return {"job_id": job.job_id}


@app.get("/api/pipeline/{job_id}/events")
async def pipeline_events(job_id: str) -> EventSourceResponse:
    """SSE stream of pipeline progress events."""

    async def event_generator():
        job = get_job(job_id)
        if not job:
            yield {"event": "failed", "data": json.dumps({"message": "Job not found"})}
            return

        last = 0
        while True:
            with job.lock:
                while last < len(job.events):
                    evt = job.events[last]
                    last += 1
                    yield {"event": "progress", "data": json.dumps(evt)}

                status = job.status

            if status == "complete":
                yield {
                    "event": "complete",
                    "data": json.dumps({"step": 8, "total": 8, "message": "Done", "status": "complete"}),
                }
                return
            if status == "error":
                yield {
                    "event": "failed",
                    "data": json.dumps({"message": job.error or "Pipeline failed", "status": "error"}),
                }
                return

            await asyncio.sleep(0.4)

    return EventSourceResponse(event_generator())


@app.get("/api/pipeline/{job_id}/result")
async def pipeline_result(job_id: str) -> dict:
    """MemoOutput JSON and download paths when job is complete."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "running" or job.status == "pending":
        raise HTTPException(status_code=202, detail="Pipeline still running")
    if job.status == "error":
        raise HTTPException(status_code=500, detail=job.error or "Pipeline failed")
    if not job.result:
        raise HTTPException(status_code=500, detail="No result available")

    result = job.result
    return {
        "job_id": job_id,
        "status": "complete",
        "memo": result.memo.model_dump(),
        "stats": {
            "doc_count": result.doc_count,
            "chunk_count": result.chunk_count,
            "section_count": result.section_count,
            "flag_count": result.flag_count,
        },
        "download_urls": {
            "docx": f"/api/pipeline/{job_id}/download/docx",
            "json": f"/api/pipeline/{job_id}/download/json",
        },
    }


@app.get("/api/pipeline/{job_id}/download/docx")
async def download_docx(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Job or file not found")
    path = job.result.output_docx
    if not path.exists():
        raise HTTPException(status_code=404, detail="DOCX not found")
    return FileResponse(path, filename="final_memo.docx", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/api/pipeline/{job_id}/download/json")
async def download_json(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Job or file not found")
    path = job.result.output_json
    if not path.exists():
        raise HTTPException(status_code=404, detail="JSON not found")
    return FileResponse(path, filename="final_memo_metadata.json", media_type="application/json")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
