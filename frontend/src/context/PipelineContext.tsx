import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  approveSections,
  exportMemo,
  fetchResult,
  patchSection,
  reverifySection,
  startPipeline,
  subscribeToEvents,
} from "../api";
import type {
  Claim,
  PageName,
  PipelineResult,
  ProgressEvent,
  ReviewPayload,
  SectionApprovalBody,
} from "../types";

function mergeReview(result: PipelineResult, review: ReviewPayload): PipelineResult {
  return {
    ...result,
    review_state: review.review_state,
    pending_sections: review.pending_sections,
    export_allowed: review.export_allowed,
    export_version: review.export_version,
    confidence_threshold: review.confidence_threshold,
  };
}

interface PipelineContextValue {
  page: PageName;
  setPage: (p: PageName) => void;
  jobId: string | null;
  currentStep: number;
  log: string[];
  running: boolean;
  error: string | null;
  result: PipelineResult | null;
  busy: boolean;
  launchPipeline: (files: File[], template?: File | null) => Promise<void>;
  refreshResult: () => Promise<void>;
  saveSection: (title: string, content: string, claims: Claim[]) => Promise<void>;
  reverify: (title: string) => Promise<void>;
  approve: (approvals: SectionApprovalBody[]) => Promise<void>;
  runExport: () => Promise<void>;
  reset: () => void;
}

const PipelineContext = createContext<PipelineContextValue | null>(null);

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageName>("deal-room");
  const [jobId, setJobId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [log, setLog] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);

  const reset = useCallback(() => {
    setJobId(null);
    setCurrentStep(0);
    setLog([]);
    setRunning(false);
    setBusy(false);
    setError(null);
    setResult(null);
    setPage("deal-room");
  }, []);

  const refreshResult = useCallback(async () => {
    if (!jobId) return;
    const res = await fetchResult(jobId);
    setResult(res);
  }, [jobId]);

  const launchPipeline = useCallback(async (files: File[], template?: File | null) => {
    setError(null);
    setResult(null);
    setLog([]);
    setCurrentStep(1);
    setRunning(true);
    setPage("pipeline");

    try {
      const { job_id } = await startPipeline(files, template);
      setJobId(job_id);

      await new Promise<void>((resolve, reject) => {
        const unsub = subscribeToEvents(
          job_id,
          (evt: ProgressEvent) => {
            if (evt.step > 0) setCurrentStep(evt.step);
            setLog((prev) => [...prev, evt.message]);
          },
          async () => {
            unsub();
            try {
              const res = await fetchResult(job_id);
              setResult(res);
              setCurrentStep(8);
              setRunning(false);
              resolve();
            } catch (e) {
              reject(e);
            }
          },
          (msg: string) => {
            unsub();
            setError(msg);
            setRunning(false);
            reject(new Error(msg));
          }
        );
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pipeline failed");
      setRunning(false);
    }
  }, []);

  const saveSection = useCallback(
    async (title: string, content: string, claims: Claim[]) => {
      if (!jobId || !result) return;
      setBusy(true);
      setError(null);
      try {
        const res = await patchSection(jobId, title, { content, claims });
        const sections = result.memo.sections.map((s) =>
          s.title === title ? res.section : s
        );
        setResult(
          mergeReview(
            { ...result, memo: { ...result.memo, sections } },
            res
          )
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : "Save failed");
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [jobId, result]
  );

  const reverify = useCallback(
    async (title: string) => {
      if (!jobId || !result) return;
      setBusy(true);
      setError(null);
      try {
        const res = await reverifySection(jobId, title);
        const sections = result.memo.sections.map((s) =>
          s.title === title ? res.section : s
        );
        const supported = sections.reduce((n, s) => {
          const vs = s.verification_summary;
          return n + (vs?.supported ?? s.claims?.filter((c) => c.status === "supported").length ?? 0);
        }, 0);
        const total = sections.reduce((n, s) => {
          const vs = s.verification_summary;
          return n + (vs?.total_claims ?? s.claims?.length ?? 0);
        }, 0);
        setResult(
          mergeReview(
            {
              ...result,
              memo: { ...result.memo, sections },
              stats: {
                ...result.stats,
                supported_claim_rate: supported / Math.max(total, 1),
              },
            },
            res
          )
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : "Re-verify failed");
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [jobId, result]
  );

  const approve = useCallback(
    async (approvals: SectionApprovalBody[]) => {
      if (!jobId || !result) return;
      setBusy(true);
      setError(null);
      try {
        const res = await approveSections(jobId, approvals);
        setResult(mergeReview(result, res));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Approve failed");
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [jobId, result]
  );

  const runExport = useCallback(async () => {
    if (!jobId || !result) return;
    setBusy(true);
    setError(null);
    try {
      const res = await exportMemo(jobId);
      setResult(
        mergeReview(
          {
            ...result,
            download_urls: res.download_urls,
            export_version: res.export_version,
          },
          res
        )
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
      throw e;
    } finally {
      setBusy(false);
    }
  }, [jobId, result]);

  const value = useMemo(
    () => ({
      page,
      setPage,
      jobId,
      currentStep,
      log,
      running,
      error,
      result,
      busy,
      launchPipeline,
      refreshResult,
      saveSection,
      reverify,
      approve,
      runExport,
      reset,
    }),
    [
      page,
      jobId,
      currentStep,
      log,
      running,
      error,
      result,
      busy,
      launchPipeline,
      refreshResult,
      saveSection,
      reverify,
      approve,
      runExport,
      reset,
    ]
  );

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>;
}

export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error("usePipeline must be used within PipelineProvider");
  return ctx;
}
