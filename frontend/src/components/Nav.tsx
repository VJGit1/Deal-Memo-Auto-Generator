import { usePipeline } from "../context/PipelineContext";
import type { PageName } from "../types";

const PAGES: { id: PageName; label: string }[] = [
  { id: "deal-room", label: "Deal Room" },
  { id: "pipeline", label: "Pipeline" },
  { id: "review", label: "Review" },
  { id: "export", label: "Export" },
];

export function Nav() {
  const { page, setPage, result, running } = usePipeline();

  return (
    <nav className="nav">
      <div className="nav-logo">
        ◆ DMAG <span>Deal Memo Auto Generator</span>
      </div>
      <div className="nav-links">
        {PAGES.map((p) => (
          <button
            key={p.id}
            className={`nav-btn ${page === p.id ? "active" : ""}`}
            onClick={() => setPage(p.id)}
            disabled={(p.id === "review" || p.id === "export") && !result && !running}
          >
            {p.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
