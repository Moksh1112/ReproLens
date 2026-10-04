from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime

# Base Models
class AssessmentBase(BaseModel):
    paper_input_type: str
    paper_source: str
    repository_input_type: str
    repository_source: str

class AssessmentCreate(AssessmentBase):
    pass

class AssessmentResponse(AssessmentBase):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Stage & Artifact metadata schemas
class ArtifactSchema(BaseModel):
    id: str
    assessment_id: str
    stage: str
    type: str
    object_path: str
    content_hash: str
    created_at: datetime

    class Config:
        from_attributes = True

class StageRunSchema(BaseModel):
    id: str
    stage_name: str
    status: str
    error: Optional[str] = None
    input_artifact_ids: List[str]
    output_artifact_ids: List[str]

    class Config:
        from_attributes = True

# -------------------------------------------------------------
# Specific Artifact Data Contracts 
# These define the JSON shapes stored in local object storage.
# -------------------------------------------------------------

class PaperDocumentArtifact(BaseModel):
    assessment_id: str
    content_hash: str
    paper_date: Optional[str] = None
    sections: List[Dict[str, Any]]
    tables: List[Dict[str, Any]]

class RepositorySnapshotArtifact(BaseModel):
    repo_hash: str
    commit_ref: str
    files: List[str]

class Evidence(BaseModel):
    quote: str
    page: int

class ClaimData(BaseModel):
    claim_id: str
    experiment: str
    dataset: Optional[str] = None
    split: Optional[str] = None
    metric: str
    value: float
    standard_deviation: Optional[float] = None
    table_figure_ref: Optional[str] = None
    page: int
    evidence: Dict[str, Evidence] = Field(
        ...,
        description="A dictionary where keys are string labels and values are Evidence objects."
    )

class ExperimentSettings(BaseModel):
    hyperparameters: Optional[Dict[str, Any]] = None
    epochs: Optional[int] = None
    seeds: Optional[List[int]] = None
    preprocessing: Optional[str] = None
    hardware: Optional[str] = None
    evidence: Dict[str, Evidence] = Field(
        default_factory=dict,
        description="A dictionary where keys are setting names and values are Evidence objects."
    )

class ClaimExtractionArtifact(BaseModel):
    assessment_id: str
    claims: List[ClaimData]
    settings: ExperimentSettings

class RepositoryIndexArtifact(BaseModel):
    assessment_id: str
    repo_hash: str
    repository_date: Optional[str] = None
    entry_scripts: List[str]
    argparse_interfaces: Dict[str, Any]
    yaml_configs: List[str]
    readme_commands: List[str]
    dependencies: List[str]

class ClaimMapping(BaseModel):
    claim_id: str
    script: str
    command: str
    config: Optional[str] = None
    confidence: float
    evidence: str

class ClaimMappingsArtifact(BaseModel):
    assessment_id: str
    mappings: List[ClaimMapping]

class EnvironmentArtifact(BaseModel):
    assessment_id: str
    image_name: str
    image_digest: str
    dependencies: List[str]
    lockfile: str
    dockerfile: str

class ExperimentRunArtifact(BaseModel):
    assessment_id: str
    run_id: str
    claim_id: str
    status: str
    exit_code: Optional[int]
    environment_digest: str
    command: str
    config: Optional[str]
    seed: int
    resource_limits: Dict[str, Any]
    start_time: str
    end_time: str
    stdout_log_path: str
    stderr_log_path: str

class MetricObservation(BaseModel):
    run_id: str
    metric_name: str
    raw_value: float
    normalized_value: float
    seed: int
    source_log: str
    evidence: Optional[str]

class MetricAggregationArtifact(BaseModel):
    assessment_id: str
    claim_id: str
    observations: List[MetricObservation]

class VerdictArtifact(BaseModel):
    assessment_id: str
    claim_id: str
    verdict: str  # Reproduced, Within noise, Partially reproduced, Not reproduced, Not testable
    reported_value: float
    reported_std: Optional[float]
    reproduced_mean: Optional[float]
    reproduced_std: Optional[float]
    tolerance: Optional[float]
    gap: Optional[float]
    seed_range: Optional[List[float]]
    observations: List[MetricObservation]
    reason: str

class DiscrepancyCause(BaseModel):
    category: str # hyperparameters, epochs, seeds, preprocessing, hardware, command, environment
    suspected: bool
    confirmed: bool
    paper_evidence: Optional[str]
    actual_evidence: Optional[str]
    explanation: str

class DiscrepancyDiagnosisArtifact(BaseModel):
    assessment_id: str
    claim_id: str
    metric_gap: Optional[float]
    causes: List[DiscrepancyCause]
    
class AuditItem(BaseModel):
    category: str
    state: str # Stated, Ambiguous, Missing
    evidence: Optional[str]

class AuditChecklistArtifact(BaseModel):
    assessment_id: str
    claim_id: Optional[str]
    items: List[AuditItem]
