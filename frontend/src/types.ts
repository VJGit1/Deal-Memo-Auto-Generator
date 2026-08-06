export interface Citation {
  doc: string;
  page: number;
}

export type ClaimStatus = "supported" | "unsupported" | "contradicted" | "insufficient";

export interface Claim {
  id: string;
  text: string;
  citation_ids: string[];
  status: ClaimStatus;
}

export interface EvidenceChunk {
  id: string;
  doc: string;
  page: number;
  quote: string;
}

export interface VerificationSummary {
  total_claims: number;
  supported: number;
  unsupported: number;
  contradicted: number;
  insufficient: number;
  supported_claim_rate: number;
}

export interface FinancialEvidence {
  metric_name: string;
  value: string | number;
  fiscal_year: string;
  source_quote: string;
  page_number: number;
  doc_name: string;
}

export interface MemoSection {
  title: string;
  content: string;
  citations: Citation[];
  confidence_score: number;
  financial_evidence: FinancialEvidence[];
  claims?: Claim[];
  evidence_chunks?: EvidenceChunk[];
  verification_summary?: VerificationSummary | null;
}

export interface MemoOutput {
  output_type: string;
  company_name: string;
  sections: MemoSection[];
  flags: string[];
  evidence_appendix: Array<{
    doc: string;
    page: number;
    metric: string;
    quote: string;
    claim_id?: string;
    claim_text?: string;
    claim_status?: ClaimStatus;
    evidence_id?: string | null;
  }>;
}

export interface PipelineStats {
  doc_count: number;
  chunk_count: number;
  section_count: number;
  flag_count: number;
  supported_claim_rate?: number;
}

export interface SectionReviewState {
  approved: boolean;
  override_reason: string | null;
  approved_at: string | null;
}

export interface ReviewState {
  export_version: number;
  sections: Record<string, SectionReviewState>;
  export_history: Array<{
    version: number;
    exported_at: string;
    docx: string;
    json: string;
    decisions?: Record<string, SectionReviewState>;
  }>;
  updated_at?: string;
}

export interface ReviewPayload {
  review_state: ReviewState;
  pending_sections: string[];
  export_allowed: boolean;
  export_version: number;
  confidence_threshold: number;
}

export interface PipelineResult {
  job_id: string;
  status: string;
  memo: MemoOutput;
  stats: PipelineStats;
  download_urls: {
    docx: string;
    json: string;
  };
  review_state?: ReviewState;
  pending_sections?: string[];
  export_allowed?: boolean;
  export_version?: number;
  confidence_threshold?: number;
}

export interface SectionPatchBody {
  content?: string;
  claims?: Claim[];
}

export interface SectionApprovalBody {
  title: string;
  override_reason?: string | null;
}

export interface ProgressEvent {
  step: number;
  total: number;
  message: string;
  status: "pending" | "running" | "complete" | "error";
}

export type PageName = "deal-room" | "pipeline" | "review" | "export";

export const STEP_LABELS = [
  "Ingest",
  "Chunk",
  "Template",
  "Grounded",
  "Financial",
  "Reconcile",
  "Appendix",
  "Export",
];

export const STEP_ICONS = ["📁", "🧩", "📋", "✍️", "📊", "⚖️", "🔗", "📤"];

export const CONFIDENCE_THRESHOLD = 0.7;
