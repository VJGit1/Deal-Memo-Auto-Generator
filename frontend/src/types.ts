export interface Citation {
  doc: string;
  page: number;
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
  }>;
}

export interface PipelineStats {
  doc_count: number;
  chunk_count: number;
  section_count: number;
  flag_count: number;
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
  "Synthesis",
  "Financial",
  "Reconcile",
  "Appendix",
  "Export",
];

export const STEP_ICONS = ["📁", "🧩", "📋", "✍️", "📊", "⚖️", "🔗", "📤"];

export const CONFIDENCE_THRESHOLD = 0.7;
