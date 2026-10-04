from abc import ABC, abstractmethod
from typing import List, Any
from app.schemas.artifacts import ArtifactSchema
from app.storage.object_store import ObjectStore
from app.db.models import Artifact
import uuid
from datetime import datetime

class BaseStage(ABC):
    """
    Base class for all ReproLens pipeline stages.
    Enforces the contract: Input Artifacts -> Stage Execution -> Output Artifacts
    """
    
    @property
    @abstractmethod
    def stage_name(self) -> str:
        pass

    @abstractmethod
    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        """
        Executes the pipeline stage.
        Must be idempotent and resumable.
        """
        pass
    
    def load_artifact_data(self, artifact: ArtifactSchema) -> Any:
        """Load artifact JSON data from local object storage."""
        return ObjectStore.load(artifact.object_path)
    
    def save_artifact(self, db_session, assessment_id: str, artifact_type: str, data: Any) -> ArtifactSchema:
        """
        Save output data as an artifact to local object storage and create DB record.
        """
        # Save to object store
        store_meta = ObjectStore.save(assessment_id, artifact_type, data)
        
        # Create DB record
        db_artifact = Artifact(
            id=str(uuid.uuid4()),
            assessment_id=assessment_id,
            stage=self.stage_name,
            type=artifact_type,
            object_path=store_meta["object_path"],
            content_hash=store_meta["content_hash"],
            created_at=datetime.utcnow()
        )
        db_session.add(db_artifact)
        db_session.commit()
        db_session.refresh(db_artifact)
        
        # Return Pydantic schema
        return ArtifactSchema.model_validate(db_artifact)
