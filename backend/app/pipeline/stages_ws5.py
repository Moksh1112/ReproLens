from typing import List, Dict, Any, Optional
import os
import shutil
import uuid
import time
from app.pipeline.base import BaseStage
from app.schemas.artifacts import (
    ArtifactSchema, 
    EnvironmentArtifact, 
    ExperimentRunArtifact,
    RepositoryIndexArtifact,
    ClaimMappingsArtifact,
    ClaimExtractionArtifact
)
from app.pipeline.stages_ws4 import WS4BaseStage
from app.db.models import Artifact
from app.execution.docker_manager import DockerManager

class EnvironmentStage(WS4BaseStage):
    @property
    def stage_name(self) -> str:
        return "environment_creation"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        try:
            repo_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "RepositoryIndexArtifact").first()
            if not repo_art:
                db.close()
                return []
            
            paper_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "PaperDocumentArtifact").first()
            
            repo_index_dict = self.load_artifact_data(ArtifactSchema.model_validate(repo_art))
            target_date_str = repo_index_dict.get("repository_date")
            
            if not target_date_str and paper_art:
                paper_dict = self.load_artifact_data(ArtifactSchema.model_validate(paper_art))
                target_date_str = paper_dict.get("paper_date")
                
            target_date = None
            if target_date_str:
                from datetime import datetime
                try:
                    target_date = datetime.fromisoformat(target_date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            run = self._start_run(db, assessment_id, [repo_art.id])
            repo_index = RepositoryIndexArtifact(**self.load_artifact_data(ArtifactSchema.model_validate(repo_art)))
            
            # Download or use a mock repo path for now
            temp_repo_path = f"/tmp/reprolens_repo_{assessment_id}"
            os.makedirs(temp_repo_path, exist_ok=True)
            
            for dep in repo_index.dependencies:
                dep_path = os.path.join(temp_repo_path, dep)
                os.makedirs(os.path.dirname(dep_path), exist_ok=True)
                if not os.path.exists(dep_path):
                    with open(dep_path, "w") as f:
                        f.write("# dummy dependency\n")

            image_name, digest, dockerfile, lockfile = DockerManager.build_environment(
                assessment_id=assessment_id,
                repo_path=temp_repo_path,
                dependencies=repo_index.dependencies,
                target_date=target_date
            )

            env_artifact = EnvironmentArtifact(
                assessment_id=assessment_id,
                image_name=image_name,
                image_digest=digest,
                dependencies=repo_index.dependencies,
                lockfile=lockfile,
                dockerfile=dockerfile
            )

            try:
                shutil.rmtree(temp_repo_path)
            except Exception:
                pass

            saved = self.save_artifact(db, assessment_id, "EnvironmentArtifact", env_artifact.model_dump())
            self._end_run(db, run, "completed", [saved.id])
            return [saved]
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()


class ExecutionStage(WS4BaseStage):
    @property
    def stage_name(self) -> str:
        return "experiment_execution"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        try:
            env_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "EnvironmentArtifact").first()
            mapping_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimMappingsArtifact").first()
            extraction_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimExtractionArtifact").first()
            repo_art = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "RepositoryIndexArtifact").first()

            if not env_art or not mapping_art or not extraction_art or not repo_art:
                db.close()
                return []

            run = self._start_run(db, assessment_id, [env_art.id, mapping_art.id, extraction_art.id, repo_art.id])

            env_data = EnvironmentArtifact(**self.load_artifact_data(ArtifactSchema.model_validate(env_art)))
            mappings_data = ClaimMappingsArtifact(**self.load_artifact_data(ArtifactSchema.model_validate(mapping_art)))
            extraction_data = ClaimExtractionArtifact(**self.load_artifact_data(ArtifactSchema.model_validate(extraction_art)))
            repo_index = RepositoryIndexArtifact(**self.load_artifact_data(ArtifactSchema.model_validate(repo_art)))

            seeds = extraction_data.settings.seeds
            if not seeds:
                seeds = [42, 43, 44]  # PRD default 3 seeds
                
            limits = {
                "cpus": 4,
                "memory": "8g",
                "timeout": 1200 # 20 mins
            }

            output_artifacts = []
            logs_dir = f"/tmp/reprolens_logs_{assessment_id}"
            os.makedirs(logs_dir, exist_ok=True)

            for mapping in mappings_data.mappings:
                if not mapping.command:
                    run_art = ExperimentRunArtifact(
                        assessment_id=assessment_id,
                        run_id=str(uuid.uuid4()),
                        claim_id=mapping.claim_id,
                        status="NOT_EXECUTABLE",
                        exit_code=None,
                        environment_digest=env_data.image_digest,
                        command="",
                        config="",
                        seed=0,
                        resource_limits=limits,
                        start_time="",
                        end_time="",
                        stdout_log_path="",
                        stderr_log_path=""
                    )
                    saved = self.save_artifact(db, assessment_id, "ExperimentRunArtifact", run_art.model_dump())
                    output_artifacts.append(saved)
                    continue

                for seed in seeds:
                    exec_cmd = mapping.command
                    argparse_iface = repo_index.argparse_interfaces.get(mapping.script, [])
                    if "--seed" not in exec_cmd and "--seed" in argparse_iface:
                        exec_cmd += f" --seed {seed}"
                    
                    res = DockerManager.run_experiment(
                        image_name=env_data.image_name,
                        command=exec_cmd,
                        seed=seed,
                        limits=limits,
                        work_dir=logs_dir
                    )
                    
                    status = "SUCCESS" if res["exit_code"] == 0 else "FAILED"
                    if res["exit_code"] == 124:
                        status = "TIMEOUT"
                        
                    run_art = ExperimentRunArtifact(
                        assessment_id=assessment_id,
                        run_id=str(uuid.uuid4()),
                        claim_id=mapping.claim_id,
                        status=status,
                        exit_code=res["exit_code"],
                        environment_digest=env_data.image_digest,
                        command=exec_cmd,
                        config=mapping.config,
                        seed=seed,
                        resource_limits=limits,
                        start_time=res["start_time"],
                        end_time=res["end_time"],
                        stdout_log_path=res["stdout_path"],
                        stderr_log_path=res["stderr_path"]
                    )
                    
                    saved = self.save_artifact(db, assessment_id, "ExperimentRunArtifact", run_art.model_dump())
                    output_artifacts.append(saved)
                    
            self._end_run(db, run, "completed", [a.id for a in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()
