import type { PipelineResult, ProgressEvent } from "./types";

export async function startPipeline(
  files: File[],
  template?: File | null
): Promise<{ job_id: string }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  if (template) form.append("template", template);

  const res = await fetch("/api/pipeline/run", { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Upload failed");
  }
  return res.json();
}

export function subscribeToEvents(
  jobId: string,
  onEvent: (evt: ProgressEvent) => void,
  onComplete: () => void,
  onError: (msg: string) => void
): () => void {
  const source = new EventSource(`/api/pipeline/${jobId}/events`);

  source.addEventListener("progress", (e) => {
    const data = JSON.parse(e.data) as ProgressEvent;
    onEvent(data);
  });

  source.addEventListener("complete", () => {
    source.close();
    onComplete();
  });

  source.addEventListener("failed", (e) => {
    const data = JSON.parse((e as MessageEvent).data) as { message?: string };
    source.close();
    onError(data.message || "Pipeline failed");
  });

  return () => source.close();
}

export async function fetchResult(jobId: string): Promise<PipelineResult> {
  const res = await fetch(`/api/pipeline/${jobId}/result`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Failed to fetch result");
  }
  return res.json();
}
