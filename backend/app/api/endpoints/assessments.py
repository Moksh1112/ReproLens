from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.db.models import Assessment, StageRun, Artifact
from app.db.session import get_db
from app.schemas.api import AssessmentSummary, SourceSubmitRequest, StageProgress, AssessmentRunResponse, ArtifactResponse, StageRunResponse, AssessmentLogsResponse, LogEntry
from app.schemas.artifacts import AssessmentCreate
from app.storage.object_store import ObjectStore
from datetime import datetime
import uuid

router = APIRouter()

@router.post("/", response_model=AssessmentSummary)
def create_assessment(assessment_in: AssessmentCreate = None, db: Session = Depends(get_db)):
    """ Create a new empty assessment or one with initial sources. """
    new_id = str(uuid.uuid4())
    assessment = Assessment(
        id=new_id,
        paper_input_type=assessment_in.paper_input_type if assessment_in else "none",
        paper_source=assessment_in.paper_source if assessment_in else "none",
        repository_input_type=assessment_in.repository_input_type if assessment_in else "none",
        repository_source=assessment_in.repository_source if assessment_in else "none",
        status="pending"
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return AssessmentSummary(
        id=assessment.id,
        status=assessment.status,
        paper_source=assessment.paper_source,
        repository_source=assessment.repository_source,
        created_at=assessment.created_at.isoformat() if assessment.created_at else datetime.utcnow().isoformat()
    )

@router.get("/{assessment_id}", response_model=AssessmentSummary)
def get_assessment(assessment_id: str, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return AssessmentSummary(
        id=assessment.id,
        status=assessment.status,
        paper_source=assessment.paper_source,
        repository_source=assessment.repository_source,
        created_at=assessment.created_at.isoformat() if assessment.created_at else ""
    )

@router.post("/{assessment_id}/sources", response_model=AssessmentSummary)
def submit_source(assessment_id: str, source_req: SourceSubmitRequest, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    
    if source_req.source_type == "paper":
        assessment.paper_input_type = source_req.input_type
        assessment.paper_source = source_req.source
    elif source_req.source_type == "repository":
        assessment.repository_input_type = source_req.input_type
        assessment.repository_source = source_req.source
    else:
        raise HTTPException(status_code=400, detail="Invalid source_type. Must be 'paper' or 'repository'.")

    db.commit()
    db.refresh(assessment)
    return AssessmentSummary(
        id=assessment.id,
        status=assessment.status,
        paper_source=assessment.paper_source,
        repository_source=assessment.repository_source,
        created_at=assessment.created_at.isoformat() if assessment.created_at else ""
    )

@router.post("/{assessment_id}/run", response_model=AssessmentRunResponse)
def run_assessment(assessment_id: str, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status in ["running", "queued"]:
        raise HTTPException(status_code=400, detail="Assessment is already running or queued.")
    
    assessment.status = "queued"
    db.commit()
    
    from app.pipeline.orchestrator import run_pipeline
    task = run_pipeline.delay(assessment_id)
    
    return AssessmentRunResponse(message="Assessment queued", task_id=task.id)

@router.get("/{assessment_id}/progress", response_model=list[StageProgress])
def get_progress(assessment_id: str, db: Session = Depends(get_db)):
    runs = db.query(StageRun).filter(StageRun.assessment_id == assessment_id).all()
    # If no runs exist, we might return empty or standard stages depending on implementation
    return [StageProgress(stage_name=run.stage_name, status=run.status, error=run.error) for run in runs]

@router.get("/{assessment_id}/stages", response_model=list[StageRunResponse])
def get_stages(assessment_id: str, db: Session = Depends(get_db)):
    runs = db.query(StageRun).filter(StageRun.assessment_id == assessment_id).all()
    return [StageRunResponse(id=run.id, stage_name=run.stage_name, status=run.status, error=run.error) for run in runs]

@router.get("/{assessment_id}/artifacts", response_model=list[ArtifactResponse])
def get_artifacts(assessment_id: str, db: Session = Depends(get_db)):
    artifacts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id).all()
    res = []
    for art in artifacts:
        try:
            data = ObjectStore.load(art.object_path)
        except Exception:
            data = None
        res.append(ArtifactResponse(
            id=art.id,
            stage=art.stage,
            type=art.type,
            content_hash=art.content_hash,
            data=data
        ))
    return res

@router.get("/{assessment_id}/logs", response_model=AssessmentLogsResponse)
def get_logs(assessment_id: str, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
        
    runs = db.query(StageRun).filter(StageRun.assessment_id == assessment_id).order_by(StageRun.id).all()
    
    logs = []
    for run in runs:
        # Create synthetic logs from stage status since we don't have a real streaming log engine yet
        ts = run.started_at.isoformat() if run.started_at else datetime.utcnow().isoformat()
        
        logs.append(LogEntry(
            timestamp=ts,
            level="INFO",
            message=f"Stage '{run.stage_name}' started."
        ))
        
        if run.status == "completed":
            end_ts = run.completed_at.isoformat() if run.completed_at else datetime.utcnow().isoformat()
            logs.append(LogEntry(
                timestamp=end_ts,
                level="INFO",
                message=f"Stage '{run.stage_name}' completed successfully."
            ))
        elif run.status == "failed":
            end_ts = run.completed_at.isoformat() if run.completed_at else datetime.utcnow().isoformat()
            logs.append(LogEntry(
                timestamp=end_ts,
                level="ERROR",
                message=f"Stage '{run.stage_name}' failed: {run.error}"
            ))
            
    # Include live execution logs from stdout/stderr files if available
    import os
    logs_dir = f"/tmp/reprolens_logs_{assessment_id}"
    if os.path.exists(logs_dir):
        for log_file in sorted(os.listdir(logs_dir)):
            if log_file.endswith(".log"):
                try:
                    with open(os.path.join(logs_dir, log_file), "r") as f:
                        lines = f.readlines()
                        for line in lines:
                            if line.strip():
                                logs.append(LogEntry(
                                    timestamp=datetime.utcnow().isoformat(),
                                    level="ERROR" if "stderr" in log_file else "INFO",
                                    message=f"[{log_file}] {line.strip()}"
                                ))
                except Exception:
                    pass
            
    return AssessmentLogsResponse(logs=logs)

@router.get("/{assessment_id}/report")
def get_report_metadata(assessment_id: str, db: Session = Depends(get_db)):
    art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ReportArtifact").first()
    if not art:
        raise HTTPException(status_code=404, detail="Report not generated yet.")
    return ObjectStore.load(art.object_path)

@router.get("/{assessment_id}/report/markdown")
def get_report_markdown(assessment_id: str, db: Session = Depends(get_db)):
    art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ReportArtifact").first()
    if not art:
        raise HTTPException(status_code=404, detail="Report not generated yet.")
    meta = ObjectStore.load(art.object_path)
    from app.core.config import settings
    import os
    abs_path = os.path.join(settings.STORAGE_DIR, meta["markdown_path"])
    return FileResponse(abs_path, media_type="text/markdown")

@router.get("/{assessment_id}/report/pdf")
def get_report_pdf(assessment_id: str, db: Session = Depends(get_db)):
    art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ReportArtifact").first()
    if not art:
        raise HTTPException(status_code=404, detail="Report not generated yet.")
    meta = ObjectStore.load(art.object_path)
    from app.core.config import settings
    import os
    abs_path = os.path.join(settings.STORAGE_DIR, meta["pdf_path"])
    return FileResponse(abs_path, media_type="application/pdf")

@router.get("/{assessment_id}/repro-card")
def get_repro_card(assessment_id: str, db: Session = Depends(get_db)):
    art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ReproCardArtifact").first()
    if not art:
        raise HTTPException(status_code=404, detail="Repro Card not generated yet.")
    return ObjectStore.load(art.object_path)

@router.get("/{assessment_id}/graph")
def get_graph(assessment_id: str, db: Session = Depends(get_db)):
    art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimGraphArtifact").first()
    if not art:
        raise HTTPException(status_code=404, detail="Graph not generated yet.")
    return ObjectStore.load(art.object_path)

