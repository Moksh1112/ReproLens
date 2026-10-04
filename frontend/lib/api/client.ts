import { 
  AssessmentSummary, StageProgress, Claim, Verdict, Discrepancy, 
  AuditItem, GraphNode, GraphEdge, ReportMetadata, ReproCard 
} from '../contracts';
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';

export const apiClient = {
  async createAssessment(paperSource: string, repoSource: string): Promise<AssessmentSummary> {
    const res = await fetch(`${API_BASE}/assessments/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_source: paperSource, repository_source: repoSource, paper_input_type: 'url', repository_input_type: 'url' })
    });
    return res.json();
  },
  
  async runAssessment(id: string): Promise<void> {
    await fetch(`${API_BASE}/assessments/${id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
  },
  
  async getAssessment(id: string): Promise<AssessmentSummary> {
    const res = await fetch(`${API_BASE}/assessments/${id}`);
    return res.json();
  },

  async getStageProgress(id: string): Promise<StageProgress[]> {
    const res = await fetch(`${API_BASE}/assessments/${id}/progress`);
    return res.json();
  },

  async getArtifacts(id: string): Promise<any[]> {
    const res = await fetch(`${API_BASE}/assessments/${id}/artifacts`);
    return res.json();
  },

  async getClaims(id: string): Promise<Claim[]> {
    const artifacts = await this.getArtifacts(id);
    const claimArt = artifacts.find((a: any) => a.type === 'ClaimExtractionArtifact');
    return claimArt && claimArt.data ? claimArt.data.claims : [];
  },

  async getVerdicts(id: string): Promise<Verdict[]> {
    const artifacts = await this.getArtifacts(id);
    return artifacts.filter((a: any) => a.type === 'VerdictArtifact' && a.data).map((a: any) => a.data);
  },

  async getDiscrepancies(id: string): Promise<Discrepancy[]> {
    const artifacts = await this.getArtifacts(id);
    return artifacts.filter((a: any) => a.type === 'DiscrepancyDiagnosisArtifact' && a.data).map((a: any) => a.data);
  },

  async getAudit(id: string): Promise<AuditItem[]> {
    const artifacts = await this.getArtifacts(id);
    const auditArts = artifacts.filter((a: any) => a.type === 'AuditChecklistArtifact' && a.data);
    if (auditArts.length > 0) {
        return auditArts[0].data.items || [];
    }
    return [];
  },

  async getClaimGraph(id: string): Promise<{ nodes: GraphNode[], edges: GraphEdge[] }> {
    const res = await fetch(`${API_BASE}/assessments/${id}/graph`);
    if (!res.ok) return { nodes: [], edges: [] };
    return res.json();
  },

  async getReport(id: string): Promise<ReportMetadata> {
    const res = await fetch(`${API_BASE}/assessments/${id}/report`);
    if (!res.ok) throw new Error('Report not found');
    const data = await res.json();
    return {
       assessment_id: data.assessment_id,
       generated_at: data.generation_timestamp,
       pdf_url: `${API_BASE}/assessments/${id}/report/pdf`,
       markdown_url: `${API_BASE}/assessments/${id}/report/markdown`
    };
  },

  async getReproCard(id: string): Promise<ReproCard> {
    const res = await fetch(`${API_BASE}/assessments/${id}/repro-card`);
    if (!res.ok) throw new Error('Repro Card not found');
    return res.json();
  }
};
