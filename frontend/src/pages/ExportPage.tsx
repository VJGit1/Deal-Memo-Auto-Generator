import { usePipeline } from "../context/PipelineContext";
import { CONFIDENCE_THRESHOLD } from "../types";

export function ExportPage() {
  const { result } = usePipeline();

  if (!result) {
    return <p style={{ color: "var(--muted)" }}>No memo generated yet.</p>;
  }

  const { memo, download_urls } = result;
  const low = memo.sections.filter((s) => s.confidence_score < CONFIDENCE_THRESHOLD);

  return (
    <div>
      <h2>Export — {memo.company_name}</h2>

      {low.length > 0 && (
        <div className="hitl-banner">
          <strong>⚠ Mandatory Review Required</strong>
          <br />
          Verify: {low.map((s) => s.title).join(", ")}
        </div>
      )}

      <div className="export-dock">
        <p style={{ color: "var(--muted)" }}>
          Download editable memo and CRM-ready JSON metadata.
        </p>
        <div className="export-links">
          <a href={download_urls.docx} download>
            📄 Download DOCX
          </a>
          <a href={download_urls.json} download>
            📋 Download JSON
          </a>
        </div>
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
