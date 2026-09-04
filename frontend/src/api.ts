import type {
  PipelineResult,
  ProgressEvent,
  ReviewPayload,
  SectionApprovalBody,
  SectionPatchBody,
  MemoSection,
} from "./types";

async function readError(res: Response): Promise<string> {
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  const detail = err.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") {
    const pending = Array.isArray(detail.pending_sections)
      ? `: ${detail.pending_sections.join(", ")}`
      : "";
    return `${detail.message}${pending}`;
  }
  return "Request failed";
}

export async function startPipeline(
  files: File[],
  template?: File | null
): Promise<{ job_id: string }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  if (template) form.append("template", template);

  const res = await fetch("/api/pipeline/run", { method: "POST", body: form });
  if (!res.ok) throw new Error(await readError(res));
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

  source.onerror = () => {
    source.close();
    onError("Connection to event stream lost. Check backend server and Redis.");
  };

  return () => source.close();
}

export async function fetchResult(jobId: string): Promise<PipelineResult> {
  const res = await fetch(`/api/pipeline/${jobId}/result`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchReview(jobId: string): Promise<ReviewPayload> {
  const res = await fetch(`/api/pipeline/${jobId}/review`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function patchSection(
  jobId: string,
  title: string,
  body: SectionPatchBody
): Promise<{ section: MemoSection } & ReviewPayload> {
  const res = await fetch(
    `/api/pipeline/${jobId}/sections/${encodeURIComponent(title)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function reverifySection(
  jobId: string,
  title: string
): Promise<{ section: MemoSection } & ReviewPayload> {
  const res = await fetch(
    `/api/pipeline/${jobId}/sections/${encodeURIComponent(title)}/reverify`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function approveSections(
  jobId: string,
  approvals: SectionApprovalBody[]
): Promise<ReviewPayload> {
  const res = await fetch(`/api/pipeline/${jobId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approvals }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function exportMemo(
  jobId: string
): Promise<
  ReviewPayload & {
    export_version: number;
    docx: string;
    json: string;
    download_urls: { docx: string; json: string };
  }
> {
  const res = await fetch(`/api/pipeline/${jobId}/export`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}
