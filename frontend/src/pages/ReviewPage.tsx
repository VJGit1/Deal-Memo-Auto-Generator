import { motion } from "framer-motion";
import { useState } from "react";
import { usePipeline } from "../context/PipelineContext";
import { MetricCards } from "../components/MetricCards";
import { CONFIDENCE_THRESHOLD, type MemoSection } from "../types";

function SectionCard({ sec, index }: { sec: MemoSection; index: number }) {
  const high = sec.confidence_score >= CONFIDENCE_THRESHOLD;
  return (
    <motion.div
      className="section-card"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08 }}
    >
      <strong>{sec.title}</strong>
      <span className={`ribbon ${high ? "ribbon-high" : "ribbon-low"}`}>
        {high ? "Verified" : "Review Required"} · {(sec.confidence_score * 100).toFixed(0)}%
      </span>
      <p style={{ margin: "0.75rem 0", lineHeight: 1.6, color: "var(--text)" }}>{sec.content}</p>
      <div>
        {sec.citations.map((c, i) => (
          <span key={i} className="citation-chip">
            {c.doc} p.{c.page}
          </span>
        ))}
      </div>
    </motion.div>
  );
}

export function ReviewPage() {
  const { result } = usePipeline();
  const [tab, setTab] = useState<"sections" | "financial" | "flags">("sections");
  const [traceIdx, setTraceIdx] = useState(0);

  if (!result) {
    return <p style={{ color: "var(--muted)" }}>No memo generated yet.</p>;
  }

  const { memo, stats } = result;
  const low = memo.sections.filter((s) => s.confidence_score < CONFIDENCE_THRESHOLD);
  const allEvidence = memo.sections.flatMap((s) => s.financial_evidence);
  const traceSec = memo.sections[traceIdx];

  return (
    <div>
      <h2>Review — {memo.company_name}</h2>

      {low.length > 0 && (
        <div className="hitl-banner">
          <strong>⚠ Mandatory Review Required</strong>
          <br />
          Sections: {low.map((s) => s.title).join(", ")}
        </div>
      )}

      <MetricCards stats={stats} />

      <div className="tabs">
        {(["sections", "financial", "flags"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "sections" ? "Memo Sections" : t === "financial" ? "Financial Evidence" : "Flags"}
          </button>
        ))}
      </div>

      {tab === "sections" && (
        <div className="split">
          <div>
            {memo.sections.map((sec, i) => (
              <SectionCard key={sec.title} sec={sec} index={i} />
            ))}
          </div>
          <div className="trace-panel">
            <h4 style={{ color: "var(--gold)" }}>Source Traceability</h4>
            <select
              value={traceIdx}
              onChange={(e) => setTraceIdx(Number(e.target.value))}
              style={{
                width: "100%",
                margin: "0.75rem 0",
                background: "var(--bg)",
                color: "var(--text)",
                border: "1px solid rgba(212,175,55,0.3)",
                padding: "0.5rem",
                borderRadius: "6px",
              }}
            >
              {memo.sections.map((s, i) => (
                <option key={s.title} value={i}>
                  {s.title}
                </option>
              ))}
            </select>
            {traceSec && (
              <>
                <p style={{ color: "var(--muted)", fontSize: "0.85rem" }}>{traceSec.title}</p>
                {traceSec.financial_evidence.slice(0, 5).map((ev, i) => (
                  <div key={i}>
                    <span className="citation-chip">
                      {ev.doc_name} p.{ev.page_number}
                    </span>
                    <div className="quote-block">&ldquo;{ev.source_quote.slice(0, 300)}&rdquo;</div>
                  </div>
                ))}
                {!traceSec.financial_evidence.length &&
                  traceSec.citations.map((c, i) => (
                    <span key={i} className="citation-chip">
                      {c.doc} p.{c.page}
                    </span>
                  ))}
              </>
            )}
          </div>
        </div>
      )}

      {tab === "financial" && (
        <table className="fin-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
              <th>FY</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {allEvidence.map((ev, i) => (
              <tr key={i}>
                <td>{ev.metric_name}</td>
                <td>{ev.value}</td>
                <td>{ev.fiscal_year}</td>
                <td>
                  {ev.doc_name} p.{ev.page_number}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "flags" && (
        <div>
          {memo.flags.length === 0 ? (
            <p style={{ color: "var(--green)" }}>✓ No cross-document discrepancies detected.</p>
          ) : (
            memo.flags.map((f, i) => (
              <div key={i} className="flag-card">
                ⚖ {f}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
