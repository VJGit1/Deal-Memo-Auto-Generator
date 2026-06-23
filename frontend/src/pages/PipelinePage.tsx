import { usePipeline } from "../context/PipelineContext";
import { MetricCards } from "../components/MetricCards";
import { Stepper } from "../components/Stepper";

export function PipelinePage() {
  const { currentStep, log, running, error, result, setPage } = usePipeline();
  const completed = !!result && !running;

  return (
    <div>
      <h2 style={{ marginBottom: "0.5rem" }}>Pipeline Execution</h2>

      <Stepper currentStep={currentStep || 1} completed={completed} />

      {running && (
        <div className="warning-box">
          Processing… Live updates below. Do not close this tab.
        </div>
      )}

      {log.length > 0 && (
        <>
          <div className="ticker-wrap">
            <div className="ticker">
              {log.slice(-8).map((m) => `> ${m}`).join("  ·  ")}
            </div>
          </div>
          <div className="log-panel">
            {log.map((m, i) => (
              <div key={i}>{m}</div>
            ))}
          </div>
        </>
      )}

      {error && <div className="error-box">{error}</div>}

      {result && (
        <>
          <div style={{ color: "var(--green)", textAlign: "center", fontSize: "1.5rem", margin: "1rem 0" }}>
            ✓ Pipeline Complete — {result.memo.company_name}
          </div>
          <MetricCards stats={result.stats} />
          <div style={{ display: "flex", gap: "1rem", marginTop: "1rem" }}>
            <button className="btn-primary" onClick={() => setPage("review")}>
              Review Memo →
            </button>
            <button className="btn-secondary" onClick={() => setPage("export")}>
              Export →
            </button>
          </div>
        </>
      )}

      {!running && !result && !error && (
        <p style={{ color: "var(--muted)" }}>Launch a pipeline from Deal Room.</p>
      )}
    </div>
  );
}
