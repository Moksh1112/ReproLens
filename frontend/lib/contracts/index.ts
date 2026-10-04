export interface AssessmentSummary {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  paper_source: string;
  repository_source: string;
  created_at: string;
}

export interface StageProgress {
  stage_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  error?: string;
}

export interface Claim {
  id: string;
  description: string;
  metric: string;
  reported_value: number;
  reported_std?: number;
  page: number;
}

export interface ClaimMapping {
  claim_id: string;
  script: string;
  command: string;
  config?: string;
  confidence: number;
}

export interface Run {
  run_id: string;
  claim_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'timeout';
  exit_code?: number;
  environment_digest: string;
}

export interface MetricObservation {
  claim_id: string;
  metric_name: string;
  seed_values: number[];
  reproduced_mean: number;
  reproduced_std: number;
  normalized_unit: string;
}

export interface Verdict {
  claim_id: string;
  verdict: 'Reproduced' | 'Within noise' | 'Partially reproduced' | 'Not reproduced' | 'Not testable';
  reported_value: number;
  reproduced_mean: number;
  reproduced_std: number;
  tolerance: number;
  gap: number;
  reason?: string;
}

export interface DiscrepancyCause {
  setting_name: string;
  paper_value: string;
  actual_value: string;
  status: 'suspected' | 'confirmed';
}

export interface Discrepancy {
  claim_id: string;
  gap: number;
  causes: DiscrepancyCause[];
}

export interface AuditItem {
  item_id: string;
  topic: string;
  status: 'Stated' | 'Ambiguous' | 'Missing';
  evidence?: string;
  explanation: string;
}

export interface GraphNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: any;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

export interface ReportMetadata {
  assessment_id: string;
  generated_at: string;
  pdf_url?: string;
  markdown_url?: string;
}

export interface ReproCard {
  assessment_id: string;
  paper_title: string;
  environment_lockfile: string;
  top_discrepancies: Discrepancy[];
  repro_score?: number;
  coverage?: number;
}
