import { 
  AssessmentSummary, 
  StageProgress, 
  Claim, 
  ClaimMapping, 
  Run, 
  Verdict, 
  Discrepancy, 
  AuditItem, 
  GraphNode, 
  GraphEdge, 
  ReportMetadata, 
  ReproCard 
} from '../contracts';

export const mockAssessment: AssessmentSummary = {
  id: 'a1b2c3d4',
  status: 'completed',
  paper_source: 'arxiv:1803.03635',
  repository_source: 'https://github.com/google-research/lottery-ticket-hypothesis',
  created_at: new Date().toISOString(),
};

export const mockStageProgress: StageProgress[] = [
  { stage_name: 'Ingestion', status: 'completed' },
  { stage_name: 'Extraction', status: 'completed' },
  { stage_name: 'Mapping', status: 'completed' },
  { stage_name: 'Environment', status: 'completed' },
  { stage_name: 'Execution', status: 'completed' },
  { stage_name: 'Verdict', status: 'completed' },
];

export const mockClaims: Claim[] = [
  {
    id: 'claim-1',
    description: 'Lenet architecture pruned by 90% retains original accuracy',
    metric: 'Accuracy',
    reported_value: 98.5,
    page: 4
  }
];

export const mockMappings: ClaimMapping[] = [
  {
    claim_id: 'claim-1',
    script: 'train.py',
    command: 'python train.py --arch lenet --prune_percent 90',
    confidence: 0.95
  }
];

export const mockRuns: Run[] = [
  { run_id: 'run-1', claim_id: 'claim-1', status: 'completed', environment_digest: 'sha256:abcd1234efgh5678' },
  { run_id: 'run-2', claim_id: 'claim-1', status: 'completed', environment_digest: 'sha256:abcd1234efgh5678' },
  { run_id: 'run-3', claim_id: 'claim-1', status: 'completed', environment_digest: 'sha256:abcd1234efgh5678' }
];

export const mockVerdicts: Verdict[] = [
  {
    claim_id: 'claim-1',
    verdict: 'Reproduced',
    reported_value: 98.5,
    reproduced_mean: 98.4,
    reproduced_std: 0.1,
    tolerance: 0.2,
    gap: 0.1
  }
];

export const mockDiscrepancies: Discrepancy[] = [];

export const mockAuditItems: AuditItem[] = [
  {
    item_id: 'audit-1',
    topic: 'Hyperparameters',
    status: 'Stated',
    evidence: 'Learning rate 0.001 (Page 5)',
    explanation: 'All hyperparams are clearly listed.'
  },
  {
    item_id: 'audit-2',
    topic: 'Seeds',
    status: 'Missing',
    explanation: 'No random seeds are documented in the paper.'
  }
];

export const mockGraphNodes: GraphNode[] = [
  { id: '1', type: 'default', position: { x: 250, y: 5 }, data: { label: 'Paper Claim: Accuracy 98.5' } },
  { id: '2', type: 'default', position: { x: 100, y: 100 }, data: { label: 'train.py (Mapper)' } },
  { id: '3', type: 'default', position: { x: 250, y: 200 }, data: { label: 'Run 1, 2, 3' } },
  { id: '4', type: 'default', position: { x: 250, y: 300 }, data: { label: 'Verdict: Reproduced' } }
];

export const mockGraphEdges: GraphEdge[] = [
  { id: 'e1-2', source: '1', target: '2' },
  { id: 'e2-3', source: '2', target: '3' },
  { id: 'e3-4', source: '3', target: '4' }
];

export const mockReport: ReportMetadata = {
  assessment_id: 'a1b2c3d4',
  generated_at: new Date().toISOString(),
  pdf_url: '/dummy/report.pdf',
  markdown_url: '/dummy/report.md'
};

export const mockReproCard: ReproCard = {
  assessment_id: 'a1b2c3d4',
  paper_title: 'The Lottery Ticket Hypothesis',
  environment_lockfile: 'requirements.txt\ntorch==1.0.0\ntorchvision==0.2.1',
  top_discrepancies: [],
  repro_score: 100,
  coverage: 1.0
};
