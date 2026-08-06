import { useState } from "react";
import { usePipeline } from "../context/PipelineContext";
import { CONFIDENCE_THRESHOLD } from "../types";

export function ExportPage() {
  const { result, busy, error, runExport, setPage } = usePipeline();
  const [exportMsg, setExportMsg] = useState<string | null>(null);

  if (!result) {
    return <p style={{ color: "var(--muted)" }}>No memo generated yet.</p>;
  }

  const { memo, download_urls } = result;
  const threshold = result.confidence_threshold ?? CONFIDENCE_THRESHOLD;
  const pending =
    result.pending_sections ??
    memo.sections
      .filter((s) => s.confidence_score < threshold)
      .filter((s) => !result.review_state?.sections?.[s.title]?.approved)
      .map((s) => s.title);
  const allowed = result.export_allowed ?? pending.length === 0;
  const version = result.export_version ?? 0;
  const history = result.review_state?.export_history ?? [];

  const handleExport = async () => {
    setExportMsg(null);
    try {
      await runExport();
      setExportMsg("Versioned export created.");
    } catch (e) {
      setExportMsg(e instanceof Error ? e.message : "Export failed");
    }
  };

  return (
    <div>
      <h2>Export — {memo.company_name}</h2>

      {!allowed ? (
        <div className="hitl-banner">
          <strong>Export blocked</strong>
          <br />
          Approve or override low-confidence sections first: {pending.join(", ")}
          <div style={{ marginTop: "0.75rem" }}>
            <button type="button" className="hitl-btn hitl-btn-primary" onClick={() => setPage("review")}>
              Go to Review
            </button>
          </div>
        </div>
      ) : (
        <div className="hitl-banner hitl-banner-ok">
          <strong>Ready to export</strong>
          <br />
          {version > 0
            ? `Latest approved package: v${version}. Re-export creates v${version + 1}.`
            : "Create v1 to generate the approved memo package."}
        </div>
      )}

      {error && <div className="error-box">{error}</div>}
      {exportMsg && !error && (
        <div className={allowed ? "warning-box" : "error-box"} style={{ color: "var(--text)" }}>
          {exportMsg}
        </div>
      )}

      <div className="export-dock">
        <div className="export-version-row">
          <span className="export-version-badge">
            {version > 0 ? `v${version}` : "No versioned export yet"}
          </span>
          <button
            type="button"
            className="hitl-btn hitl-btn-primary"
            disabled={!allowed || busy}
            onClick={handleExport}
          >
            {busy ? "Exporting…" : version > 0 ? `Re-export as v${version + 1}` : "Export v1"}
          </button>
        </div>

        <p style={{ color: "var(--muted)", marginTop: "1rem" }}>
          Downloads require the approval gate to be clear
          {version > 0 ? ` and serve final_memo_v${version}.*` : " (draft after first versioned export)"}.
        </p>

        <div className="export-links">
          {allowed && version > 0 ? (
            <>
              <a href={download_urls.docx} download>
                Download DOCX {version > 0 ? `(v${version})` : ""}
              </a>
              <a href={download_urls.json} download>
                Download JSON {version > 0 ? `(v${version})` : ""}
              </a>
            </>
          ) : (
            <>
              <span className="export-link-disabled">Download DOCX</span>
              <span className="export-link-disabled">Download JSON</span>
            </>
          )}
        </div>

        {history.length > 0 && (
          <div className="export-history">
            <div className="field-label">Export history</div>
            <ul>
              {history
                .slice()
                .reverse()
                .map((h) => (
                  <li key={h.version}>
                    <strong>v{h.version}</strong> — {h.docx}
                    <span style={{ color: "var(--muted)" }}> · {h.exported_at}</span>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </div>

      <details style={{ marginTop: "1.5rem", color: "var(--muted)" }}>
        <summary style={{ cursor: "pointer", color: "var(--gold)" }}>Raw JSON metadata</summary>
        <pre
          style={{
            background: "var(--surface)",
            padding: "1rem",
            borderRadius: "8px",
            overflow: "auto",
            fontSize: "0.75rem",
            marginTop: "0.5rem",
          }}
        >
          {JSON.stringify(memo, null, 2)}
        </pre>
      </details>
    </div>
  );
}
