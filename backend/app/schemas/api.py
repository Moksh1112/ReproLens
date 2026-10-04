from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import datetime

class AssessmentSummary(BaseModel):
    id: str
    status: str
    paper_source: Optional[str]
    repository_source: Optional[str]
    created_at: str

class SourceSubmitRequest(BaseModel):
    source_type: str  # 'paper' or 'repository'
    input_type: str   # 'pdf', 'arxiv', 'github', 'zip'
    source: str

class StageProgress(BaseModel):
    stage_name: str
    status: str
    error: Optional[str] = None

class AssessmentRunResponse(BaseModel):
    message: str
    task_id: str

class ArtifactResponse(BaseModel):
    id: str
    stage: str
    type: str
    content_hash: str
    data: Optional[Dict[str, Any]] = None

class StageRunResponse(BaseModel):
    id: str
    stage_name: str
    status: str
    error: Optional[str]

class LogEntry(BaseModel):
    timestamp: str
    level: str
    message: str

class AssessmentLogsResponse(BaseModel):
    logs: List[LogEntry]

