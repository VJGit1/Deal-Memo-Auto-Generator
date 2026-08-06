import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { usePipeline } from "../context/PipelineContext";
import { MetricCards } from "../components/MetricCards";
import {
  CONFIDENCE_THRESHOLD,
  type Claim,
  type ClaimStatus,
  type EvidenceChunk,
  type MemoSection,
  type SectionReviewState,
} from "../types";

function claimQuotes(claim: Claim, evidence: EvidenceChunk[]): string {
  const byId = Object.fromEntries(evidence.map((e) => [e.id, e]));
  const quotes = claim.citation_ids
    .map((id) => byId[id])
    .filter(Boolean)
    .map((e) => `[${e.doc} p.${e.page}] “${e.quote.slice(0, 180)}${e.quote.length > 180 ? "…" : ""}”`);
  return quotes.length ? quotes.join("\n\n") : "No cited quotes";
}

function ClaimChip({ claim, evidence }: { claim: Claim; evidence: EvidenceChunk[] }) {
  const label: Record<ClaimStatus, string> = {
    supported: "Supported",
    unsupported: "Unsupported",
    contradicted: "Contradicted",
    insufficient: "Insufficient",
  };
  return (
    <span className={`claim-chip claim-${claim.status}`} title={claimQuotes(claim, evidence)}>
      <span className="claim-chip-status">{label[claim.status]}</span>
      <span className="claim-chip-text">{claim.text}</span>
    </span>
  );
}

function SectionEditor({
  sec,
  index,
  review,
  disabled,
  onSave,
  onReverify,
  onApprove,
}: {
  sec: MemoSection;
  index: number;
  review?: SectionReviewState;
  disabled: boolean;
  onSave: (content: string, claims: Claim[]) => Promise<void>;
  onReverify: () => Promise<void>;
  onApprove: (overrideReason?: string) => Promise<void>;
}) {
  const high = sec.confidence_score >= CONFIDENCE_THRESHOLD;
  const [content, setContent] = useState(sec.content);
  const [claims, setClaims] = useState<Claim[]>(sec.claims ?? []);
  const [overrideReason, setOverrideReason] = useState("");
  const [dirty, setDirty] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setContent(sec.content);
    setClaims(sec.claims ?? []);
    setDirty(false);
  }, [sec.content, sec.claims, sec.confidence_score, sec.title]);

  const evidence = sec.evidence_chunks ?? [];
  const rate = sec.verification_summary?.supported_claim_rate;
  const approved = Boolean(review?.approved);
  const needsReview = !high && !approved;

  const updateClaimText = (id: string, text: string) => {
    setClaims((prev) => prev.map((c) => (c.id === id ? { ...c, text } : c)));
    setDirty(true);
  };

  const handleSave = async () => {
    setLocalError(null);
    try {
      await onSave(content, claims);
      setDirty(false);
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : "Save failed");
    }
  };

  const handleReverify = async () => {
    setLocalError(null);
    try {
      if (dirty) await onSave(content, claims);
      await onReverify();
      setDirty(false);
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : "Re-verify failed");
    }
  };

  const handleApprove = async (withOverride: boolean) => {
    setLocalError(null);
    try {
      if (dirty) await onSave(content, claims);
      const reason = withOverride ? overrideReason.trim() : undefined;
      if (withOverride && !reason) {
        setLocalError("Override requires a reason");
        return;
      }
      await onApprove(reason);
      setDirty(false);
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : "Approve failed");
    }
  };

  return (
    <motion.div
      className={`section-card ${needsReview ? "section-needs-review" : ""} ${approved ? "section-approved" : ""}`}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08 }}
    >
      <div className="section-card-header">
        <strong>{sec.title}</strong>
        <span className={`ribbon ${high ? "ribbon-high" : "ribbon-low"}`}>
          {high ? "Verified" : "Review Required"} · {(sec.confidence_score * 100).toFixed(0)}%
          {rate != null ? ` · claims ${(rate * 100).toFixed(0)}%` : ""}
        </span>
        {approved && (
          <span className="ribbon ribbon-approved">
            Approved{review?.override_reason ? " · override" : ""}
          </span>
        )}
      </div>

      <label className="field-label" htmlFor={`sec-content-${index}`}>
        Section content
      </label>
      <textarea
        id={`sec-content-${index}`}
        className="section-textarea"
        value={content}
        disabled={disabled}
        onChange={(e) => {
          setContent(e.target.value);
          setDirty(true);
        }}
        rows={6}
      />

      {claims.length > 0 && (
        <div className="claim-edit-list">
          <div className="field-label">Claims</div>
          {claims.map((c) => (
            <div key={c.id} className="claim-edit-row">
              <span className={`claim-chip claim-${c.status}`} title={claimQuotes(c, evidence)}>
                <span className="claim-chip-status">{c.status}</span>
              </span>
              <input
                className="claim-edit-input"
                value={c.text}
                disabled={disabled}
                onChange={(e) => updateClaimText(c.id, e.target.value)}
              />
            </div>
          ))}
        </div>
      )}

      <div className="hitl-actions">
        <button type="button" className="hitl-btn" disabled={disabled || !dirty} onClick={handleSave}>
          Save
        </button>
        <button type="button" className="hitl-btn" disabled={disabled} onClick={handleReverify}>
          Re-verify
        </button>
        <button
          type="button"
          className="hitl-btn hitl-btn-primary"
          disabled={disabled || approved}
          onClick={() => handleApprove(false)}
        >
          Approve
        </button>
      </div>

      {!high && (
        <div className="override-row">
          <input
            className="override-input"
            placeholder="Override reason (optional with Approve; required for Override)"
            value={overrideReason}
            disabled={disabled || approved}
            onChange={(e) => setOverrideReason(e.target.value)}
          />
          <button
            type="button"
            className="hitl-btn hitl-btn-amber"
            disabled={disabled || approved}
            onClick={() => handleApprove(true)}
          >
            Override
          </button>
        </div>
      )}

      {localError && <p className="hitl-inline-error">{localError}</p>}

      <div className="citation-row">
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
  const { result, busy, error, saveSection, reverify, approve } = usePipeline();
  const [tab, setTab] = useState<"sections" | "financial" | "flags">("sections");
  const [traceIdx, setTraceIdx] = useState(0);

  if (!result) {
    return <p style={{ color: "var(--muted)" }}>No memo generated yet.</p>;
  }

  const { memo, stats } = result;
  const threshold = result.confidence_threshold ?? CONFIDENCE_THRESHOLD;
  const pending = result.pending_sections ?? memo.sections
    .filter((s) => s.confidence_score < threshold)
    .filter((s) => !result.review_state?.sections?.[s.title]?.approved)
    .map((s) => s.title);
  const allEvidence = memo.sections.flatMap((s) => s.financial_evidence);
  const traceSec = memo.sections[traceIdx];
  const traceClaims = traceSec?.claims ?? [];
  const traceChunks = traceSec?.evidence_chunks ?? [];

  return (
    <div>
      <h2>Review — {memo.company_name}</h2>

      {pending.length > 0 ? (
        <div className="hitl-banner">
          <strong>Mandatory Review Required</strong>
          <br />
          Approve or override before export: {pending.join(", ")}
        </div>
      ) : (
        <div className="hitl-banner hitl-banner-ok">
          <strong>Export gate clear</strong>
          <br />
          All low-confidence sections are approved or overridden.
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

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
              <SectionEditor
                key={sec.title}
                sec={sec}
                index={i}
                review={result.review_state?.sections?.[sec.title]}
                disabled={busy}
                onSave={(content, claims) => saveSection(sec.title, content, claims)}
                onReverify={() => reverify(sec.title)}
                onApprove={(reason) =>
                  approve([{ title: sec.title, override_reason: reason ?? null }])
                }
              />
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
                {traceClaims.length > 0 &&
                  traceClaims.map((c) => (
                    <div key={c.id} style={{ marginBottom: "0.75rem" }}>
                      <ClaimChip claim={c} evidence={traceChunks} />
                      {c.citation_ids.map((eid) => {
                        const ev = traceChunks.find((e) => e.id === eid);
                        if (!ev) return null;
                        return (
                          <div key={eid}>
                            <span className="citation-chip">
                              {ev.doc} p.{ev.page}
                            </span>
                            <div className="quote-block">&ldquo;{ev.quote.slice(0, 300)}&rdquo;</div>
                          </div>
                        );
                      })}
                    </div>
                  ))}
                {!traceClaims.length &&
                  traceSec.financial_evidence.slice(0, 5).map((ev, i) => (
                    <div key={i}>
                      <span className="citation-chip">
                        {ev.doc_name} p.{ev.page_number}
                      </span>
                      <div className="quote-block">&ldquo;{ev.source_quote.slice(0, 300)}&rdquo;</div>
                    </div>
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
            <p style={{ color: "var(--green)" }}>No cross-document discrepancies detected.</p>
          ) : (
            memo.flags.map((f, i) => (
              <div key={i} className="flag-card">
                {f}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
