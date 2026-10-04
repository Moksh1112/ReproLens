import uuid
from typing import List
from datetime import datetime

from app.pipeline.base import BaseStage
from app.db.models import StageRun, Assessment, Artifact
from app.schemas.artifacts import ArtifactSchema, PaperDocumentArtifact, ClaimExtractionArtifact, RepositoryIndexArtifact, ClaimMappingsArtifact
from app.intelligence.parser import parse_pdf
from app.intelligence.llm import extract_claims, map_claims_to_repo
from app.intelligence.repo_indexer import index_repository

class WS4BaseStage(BaseStage):
    def _create_db_session(self):
        from app.db.session import SessionLocal
        return SessionLocal()

    def _start_run(self, db, assessment_id, input_artifact_ids):
        run = StageRun(
            id=str(uuid.uuid4()),
            assessment_id=assessment_id,
            stage_name=self.stage_name,
            status="running",
            started_at=datetime.utcnow(),
            input_artifact_ids=input_artifact_ids
        )
        db.add(run)
        db.commit()
        return run

    def _end_run(self, db, run, status, output_artifact_ids, error=None):
        run.status = status
        run.completed_at = datetime.utcnow()
        run.output_artifact_ids = output_artifact_ids
        run.error = error
        db.commit()

class PaperParsingStage(WS4BaseStage):
    @property
    def stage_name(self) -> str:
        return "paper_parsing"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [])
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment or assessment.paper_input_type == "none":
                self._end_run(db, run, "completed", [])
                db.close()
                return []

            # In a real system we download from source, here we just use the path
            from app.intelligence.parser import resolve_paper_source
            from app.core.config import settings
            import os
            
            cache_dir = os.path.join(settings.STORAGE_DIR, "_arxiv_cache")
            file_path = resolve_paper_source(assessment.paper_source, cache_dir)
            
            # Use parser
            parsed_data = parse_pdf(file_path)
            
            # Save artifact
            paper_data = PaperDocumentArtifact(
                assessment_id=assessment_id,
                content_hash=parsed_data["content_hash"],
                paper_date=parsed_data.get("paper_date"),
                sections=parsed_data["sections"],
                tables=parsed_data["tables"]
            )
            
            out_schema = self.save_artifact(db, assessment_id, "PaperDocumentArtifact", paper_data.model_dump())
            self._end_run(db, run, "completed", [out_schema.id])
            return [out_schema]
        except Exception as e:
            self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class ClaimExtractionStage(WS4BaseStage):
    @property
    def stage_name(self) -> str:
        return "claim_extraction"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        try:
            # Find input
            paper_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "PaperDocumentArtifact").first()
            if not paper_art:
                db.close()
                return []
            
            run = self._start_run(db, assessment_id, [paper_art.id])
            
            # Load paper data
            paper_data_dict = self.load_artifact_data(ArtifactSchema.model_validate(paper_art))
            paper_doc = PaperDocumentArtifact(**paper_data_dict)
            
            # Extract claims
            claims_artifact = extract_claims(paper_doc.sections, paper_doc.content_hash)
            claims_artifact.assessment_id = assessment_id
            
            out_schema = self.save_artifact(db, assessment_id, "ClaimExtractionArtifact", claims_artifact.model_dump())
            self._end_run(db, run, "completed", [out_schema.id])
            return [out_schema]
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class RepoIndexingStage(WS4BaseStage):
    @property
    def stage_name(self) -> str:
        return "repo_indexing"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [])
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment or assessment.repository_input_type == "none":
                self._end_run(db, run, "completed", [])
                db.close()
                return []
                
            repo_path = assessment.repository_source
            
            index_data = index_repository(repo_path)
            
            repo_artifact = RepositoryIndexArtifact(
                assessment_id=assessment_id,
                repo_hash=index_data["repo_hash"],
                repository_date=index_data.get("repository_date"),
                entry_scripts=index_data["entry_scripts"],
                argparse_interfaces=index_data["argparse_interfaces"],
                yaml_configs=index_data["yaml_configs"],
                readme_commands=index_data["readme_commands"],
                dependencies=index_data["dependencies"]
            )
            
            out_schema = self.save_artifact(db, assessment_id, "RepositoryIndexArtifact", repo_artifact.model_dump())
            self._end_run(db, run, "completed", [out_schema.id])
            return [out_schema]
        except Exception as e:
            self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class ClaimMappingStage(WS4BaseStage):
    @property
    def stage_name(self) -> str:
        return "claim_mapping"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        try:
            claims_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimExtractionArtifact").first()
            repo_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "RepositoryIndexArtifact").first()
            
            if not claims_art or not repo_art:
                db.close()
                return []
                
            run = self._start_run(db, assessment_id, [claims_art.id, repo_art.id])
            
            claims_data = self.load_artifact_data(ArtifactSchema.model_validate(claims_art))
            repo_data = self.load_artifact_data(ArtifactSchema.model_validate(repo_art))
            
            mapping_artifact = map_claims_to_repo(claims_data.get("claims", []), repo_data)
            mapping_artifact.assessment_id = assessment_id
            
            out_schema = self.save_artifact(db, assessment_id, "ClaimMappingsArtifact", mapping_artifact.model_dump())
            self._end_run(db, run, "completed", [out_schema.id])
            return [out_schema]
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

