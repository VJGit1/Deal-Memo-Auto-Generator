import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { fetchResult, startPipeline, subscribeToEvents } from "../api";
import type { PageName, PipelineResult, ProgressEvent } from "../types";

interface PipelineContextValue {
  page: PageName;
  setPage: (p: PageName) => void;
  jobId: string | null;
  currentStep: number;
  log: string[];
  running: boolean;
  error: string | null;
  result: PipelineResult | null;
  launchPipeline: (files: File[], template?: File | null) => Promise<void>;
  reset: () => void;
}

const PipelineContext = createContext<PipelineContextValue | null>(null);

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageName>("deal-room");
  const [jobId, setJobId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [log, setLog] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);

  const reset = useCallback(() => {
    setJobId(null);
    setCurrentStep(0);
    setLog([]);
    setRunning(false);
    setError(null);
    setResult(null);
    setPage("deal-room");
  }, []);

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
      launchPipeline,
      reset,
    }),
    [page, jobId, currentStep, log, running, error, result, launchPipeline, reset]
  );

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>;
}

export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error("usePipeline must be used within PipelineProvider");
  return ctx;
}
