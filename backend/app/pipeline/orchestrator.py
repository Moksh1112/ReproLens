from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import Assessment, StageRun
from app.pipeline.base import BaseStage
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)

# We will maintain a registry of stages here. Downstream WS will add to this.
# For P0, we just orchestrate registered stages sequentially.
from app.pipeline.stages_ws4 import PaperParsingStage, ClaimExtractionStage, RepoIndexingStage, ClaimMappingStage
from app.pipeline.stages_ws5 import EnvironmentStage, ExecutionStage
from app.pipeline.stages_ws6 import MetricExtractionStage, VerdictCalculationStage, DiscrepancyDiagnosisStage, AuditChecklistStage
from app.pipeline.stages_ws7 import ReportGenerationStage, GraphGenerationStage, ReproCardGenerationStage

REGISTERED_STAGES = [
    PaperParsingStage(),
    ClaimExtractionStage(),
    RepoIndexingStage(),
    ClaimMappingStage(),
    EnvironmentStage(),
    ExecutionStage(),
    MetricExtractionStage(),
    VerdictCalculationStage(),
    DiscrepancyDiagnosisStage(),
    AuditChecklistStage(),
    ReportGenerationStage(),
    GraphGenerationStage(),
    ReproCardGenerationStage()
]

def get_stage_by_name(name: str) -> BaseStage:
    for stage in REGISTERED_STAGES:
        if stage.stage_name == name:
            return stage
    return None

@celery_app.task(bind=True)
def run_pipeline(self, assessment_id: str):
    db: Session = SessionLocal()
    try:
        assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
        if not assessment:
            logger.error(f"Assessment {assessment_id} not found.")
            return

        assessment.status = "running"
        db.commit()

        # Execute registered stages sequentially
        for stage in REGISTERED_STAGES:
            # Check if stage already completed successfully (idempotency)
            existing_run = db.query(StageRun).filter(
                StageRun.assessment_id == assessment_id,
                StageRun.stage_name == stage.stage_name,
                StageRun.status == "completed"
            ).first()

            if existing_run:
                logger.info(f"Stage {stage.stage_name} already completed for {assessment_id}. Skipping.")
                continue

            logger.info(f"Executing stage {stage.stage_name} for {assessment_id}")
            try:
                # BaseStage execute creates StageRun and handles errors if implemented correctly,
                # but orchestrator handles the high-level calling.
                # In WS1 we saw MockIngestionStage created its own StageRun. We will just call execute.
                # We fetch input artifacts based on stage needs, but for now we pass all previous artifacts or let the stage fetch them.
                # BaseStage signature: execute(assessment_id: str, input_artifacts: list) -> list
                # For simplicity, pass empty list as input artifacts, stages will query DB for specific artifacts.
                stage.execute(assessment_id, [])
            except Exception as e:
                logger.error(f"Stage {stage.stage_name} failed: {e}")
                assessment.status = "failed"
                db.commit()
                return

        assessment.status = "completed"
        db.commit()
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
        if assessment:
            assessment.status = "failed"
            db.commit()
    finally:
        db.close()
