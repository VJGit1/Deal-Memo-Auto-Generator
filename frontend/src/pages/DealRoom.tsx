import { useCallback, useState } from "react";
import { usePipeline } from "../context/PipelineContext";

export function DealRoom() {
  const { launchPipeline, error, reset } = usePipeline();
  const [files, setFiles] = useState<File[]>([]);
  const [template, setTemplate] = useState<File | null>(null);
  const [launching, setLaunching] = useState(false);

  const onFiles = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setFiles(Array.from(e.target.files ?? []));
  }, []);

  const onTemplate = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setTemplate(e.target.files?.[0] ?? null);
  }, []);

  const handleLaunch = async () => {
    if (!files.length) return;
    setLaunching(true);
    await launchPipeline(files, template);
    setLaunching(false);
  };

  return (
    <div>
      <div className="hero">
        <h1>Private Equity Deal Room</h1>
        <p>Upload due diligence materials and generate citation-backed investment memos.</p>
        <div className="tagline">
          Evidence-gated · Citation-backed · Human review below 0.7 confidence
        </div>
      </div>

      <div className="dropzone">
        <div style={{ fontSize: "2.5rem" }}>📂</div>
        <p style={{ color: "var(--muted)", marginTop: "0.5rem" }}>
          Drop PDF, CSV, Excel, Word, or transcript files
        </p>
        <input type="file" multiple accept=".pdf,.csv,.xlsx,.docx,.txt" onChange={onFiles} />
        {files.length > 0 && (
          <p style={{ color: "var(--gold)", marginTop: "0.75rem", fontSize: "0.85rem" }}>
            {files.length} file(s): {files.map((f) => f.name).join(", ")}
          </p>
        )}
      </div>

      <div className="dropzone" style={{ padding: "1rem" }}>
        <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>Optional memo template (.docx)</p>
        <input type="file" accept=".docx" onChange={onTemplate} />
      </div>

      <div className="warning-box">
        Pipeline may take several minutes depending on document count and API rate limits.
      </div>

      {error && <div className="error-box">{error}</div>}

      <div style={{ display: "flex", gap: "1rem", marginTop: "1rem" }}>
        <button
          className="btn-primary"
          disabled={!files.length || launching}
          onClick={handleLaunch}
        >
          {launching ? "Launching…" : "🚀 Launch Pipeline"}
        </button>
        <button className="btn-secondary" onClick={reset}>
          New Deal
        </button>
      </div>
    </div>
  );
}
