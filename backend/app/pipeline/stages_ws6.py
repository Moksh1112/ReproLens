import uuid
import math
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.pipeline.base import BaseStage
from app.db.models import StageRun, Assessment, Artifact
from app.schemas.artifacts import (
    ArtifactSchema, 
    ClaimExtractionArtifact, 
    ExperimentRunArtifact,
    MetricObservation,
    MetricAggregationArtifact,
    VerdictArtifact,
    DiscrepancyDiagnosisArtifact,
    DiscrepancyCause,
    AuditChecklistArtifact,
    AuditItem
)
from app.intelligence.llm import get_llm_client

class WS6BaseStage(BaseStage):
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

class MetricExtractionStage(WS6BaseStage):
    @property
    def stage_name(self) -> str:
        return "metric_extraction"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [a.id for a in input_artifacts])
        output_artifacts = []
        try:
            # Get claims to know what metrics to look for
            claim_arts = db.query(Artifact).filter(
                Artifact.assessment_id == assessment_id, 
                Artifact.type == "ClaimExtractionArtifact"
            ).all()
            
            run_arts = db.query(Artifact).filter(
                Artifact.assessment_id == assessment_id,
                Artifact.type == "ExperimentRunArtifact"
            ).all()
            
            if not claim_arts:
                self._end_run(db, run, "completed", [])
                db.close()
                return []
                
            claim_data_list = []
            for ca in claim_arts:
                ca_data = self.load_artifact_data(ArtifactSchema.model_validate(ca))
                claim_data_list.extend(ca_data.get("claims", []))
            
            # Map claims by ID
            claims_by_id = {c["claim_id"]: c for c in claim_data_list}
            
            # Group runs by claim ID
            runs_by_claim = {}
            for ra in run_arts:
                ra_data = self.load_artifact_data(ArtifactSchema.model_validate(ra))
                cid = ra_data["claim_id"]
                if cid not in runs_by_claim:
                    runs_by_claim[cid] = []
                runs_by_claim[cid].append(ra_data)
                
            for claim_id, runs in runs_by_claim.items():
                claim = claims_by_id.get(claim_id)
                if not claim:
                    continue
                
                target_metric = claim.get("metric", "").lower()
                observations = []
                
                for run_data in runs:
                    if run_data["status"] != "completed" or run_data["exit_code"] != 0:
                        continue
                        
                    # Parse metric from stdout log
                    stdout_path = run_data.get("stdout_log_path")
                    if not stdout_path:
                        continue
                        
                    try:
                        with open(stdout_path, "r", encoding="utf-8", errors="ignore") as f:
                            stdout_content = f.read()
                    except Exception:
                        continue
                        
                    # Simple regex extraction for metric:
                    # Look for things like "Accuracy: 0.95" or "accuracy=95.0"
                    # In a real app we'd use more robust matching or an LLM
                    raw_val = None
                    norm_val = None
                    
                    # We look for the metric name in the log, followed by a number
                    pattern = re.compile(rf"{re.escape(target_metric)}[^\d]+(\d+\.?\d*)", re.IGNORECASE)
                    matches = pattern.findall(stdout_content)
                    
                    if matches:
                        # take the last one typically
                        raw_val = float(matches[-1])
                        
                        # Normalize to 0-1 if it's > 1 but reported as <= 1, etc.
                        # Wait, the instruction says: "Normalize units so paper-reported and reproduced values can be compared correctly."
                        # If paper value is 0.95 and raw_val is 95.0, we divide by 100.
                        paper_val = claim.get("value", 0.0)
                        
                        if paper_val <= 1.0 and raw_val > 1.0 and raw_val <= 100.0:
                            norm_val = raw_val / 100.0
                        elif paper_val > 1.0 and raw_val <= 1.0:
                            norm_val = raw_val * 100.0
                        else:
                            norm_val = raw_val
                            
                        observations.append(MetricObservation(
                            run_id=run_data["run_id"],
                            metric_name=target_metric,
                            raw_value=raw_val,
                            normalized_value=norm_val,
                            seed=run_data["seed"],
                            source_log=stdout_path,
                            evidence=f"Matched {target_metric} = {raw_val} in logs"
                        ))
                
                agg = MetricAggregationArtifact(
                    assessment_id=assessment_id,
                    claim_id=claim_id,
                    observations=observations
                )
                
                out_schema = self.save_artifact(db, assessment_id, "MetricAggregationArtifact", agg.model_dump())
                output_artifacts.append(out_schema)
                
            self._end_run(db, run, "completed", [o.id for o in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class VerdictCalculationStage(WS6BaseStage):
    @property
    def stage_name(self) -> str:
        return "verdict_calculation"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [a.id for a in input_artifacts])
        output_artifacts = []
        try:
            agg_arts = db.query(Artifact).filter(
                Artifact.assessment_id == assessment_id,
                Artifact.type == "MetricAggregationArtifact"
            ).all()
            
            claim_arts = db.query(Artifact).filter(
                Artifact.assessment_id == assessment_id, 
                Artifact.type == "ClaimExtractionArtifact"
            ).all()
            
            claims_by_id = {}
            for ca in claim_arts:
                ca_data = self.load_artifact_data(ArtifactSchema.model_validate(ca))
                for c in ca_data.get("claims", []):
                    claims_by_id[c["claim_id"]] = c
                    
            for agg_art in agg_arts:
                agg_data = self.load_artifact_data(ArtifactSchema.model_validate(agg_art))
                claim_id = agg_data["claim_id"]
                claim = claims_by_id.get(claim_id)
                if not claim:
                    continue
                    
                obs = agg_data.get("observations", [])
                
                paper_val = claim.get("value", 0.0)
                paper_std = claim.get("standard_deviation", 0.0) or 0.0
                
                if not obs:
                    verdict = VerdictArtifact(
                        assessment_id=assessment_id,
                        claim_id=claim_id,
                        verdict="Not testable",
                        reported_value=paper_val,
                        reported_std=paper_std,
                        reproduced_mean=None,
                        reproduced_std=None,
                        tolerance=None,
                        gap=None,
                        seed_range=None,
                        observations=[],
                        reason="No valid metric observations found from runs."
                    )
                else:
                    norm_vals = [o["normalized_value"] for o in obs]
                    mean = sum(norm_vals) / len(norm_vals)
                    std = 0.0
                    if len(norm_vals) > 1:
                        var = sum((x - mean) ** 2 for x in norm_vals) / (len(norm_vals) - 1)
                        std = math.sqrt(var)
                        
                    metric = claim.get("metric", "").lower()
                    
                    # floor: 1 percentage point for accuracy/f1
                    floor = 0.0
                    if any(x in metric for x in ["acc", "f1", "precision", "recall"]):
                        # If values are in 0-1 range, floor is 0.01, otherwise 1.0
                        floor = 0.01 if paper_val <= 1.0 else 1.0
                        
                    tolerance = max(paper_std, std, floor)
                    gap = abs(paper_val - mean)
                    
                    paper_min = paper_val - paper_std
                    paper_max = paper_val + paper_std
                    rep_min = min(norm_vals)
                    rep_max = max(norm_vals)
                    
                    overlaps = not (rep_max < paper_min or rep_min > paper_max)
                    
                    if gap <= tolerance:
                        v_str = "Reproduced"
                    elif gap <= 2 * tolerance and overlaps:
                        v_str = "Within noise"
                    else:
                        # Implement an explicit check of paper conclusion vs reproduced conclusion.
                        # We require an explicit 'baseline' object from WS4 that contains the comparison target and evidence.
                        baseline_dict = claim.get("baseline")
                        if baseline_dict and "value" in baseline_dict:
                            paper_baseline = baseline_dict["value"]
                            paper_diff = paper_val - paper_baseline
                            rep_diff = mean - paper_baseline
                            # Conclusion flips if the direction of difference compared to baseline changes
                            flips_conclusion = (paper_diff > 0 and rep_diff <= 0) or (paper_diff < 0 and rep_diff >= 0)
                            
                            if flips_conclusion:
                                v_str = "Not reproduced"
                            else:
                                v_str = "Partially reproduced"
                        else:
                            # Without established ranking/conclusion from the paper to compare against,
                            # we cannot distinguish Partially reproduced from Not reproduced.
                            v_str = "Not testable"
                        
                    verdict = VerdictArtifact(
                        assessment_id=assessment_id,
                        claim_id=claim_id,
                        verdict=v_str,
                        reported_value=paper_val,
                        reported_std=paper_std,
                        reproduced_mean=mean,
                        reproduced_std=std,
                        tolerance=tolerance,
                        gap=gap,
                        seed_range=[rep_min, rep_max],
                        observations=[MetricObservation(**o) for o in obs],
                        reason=f"Calculated gap {gap:.4f} with tolerance {tolerance:.4f}"
                    )
                    
                out_schema = self.save_artifact(db, assessment_id, "VerdictArtifact", verdict.model_dump())
                output_artifacts.append(out_schema)
                
            self._end_run(db, run, "completed", [o.id for o in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class DiscrepancyDiagnosisStage(WS6BaseStage):
    @property
    def stage_name(self) -> str:
        return "discrepancy_diagnosis"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [a.id for a in input_artifacts])
        output_artifacts = []
        try:
            verdict_arts = db.query(Artifact).filter(
                Artifact.assessment_id == assessment_id,
                Artifact.type == "VerdictArtifact"
            ).all()
            
            claim_arts = db.query(Artifact).filter(
                Artifact.assessment_id == assessment_id, 
                Artifact.type == "ClaimExtractionArtifact"
            ).all()
            
            run_arts = db.query(Artifact).filter(
                Artifact.assessment_id == assessment_id,
                Artifact.type == "ExperimentRunArtifact"
            ).all()
            
            claims_by_id = {}
            settings_by_claim = {}
            for ca in claim_arts:
                ca_data = self.load_artifact_data(ArtifactSchema.model_validate(ca))
                settings = ca_data.get("settings", {})
                for c in ca_data.get("claims", []):
                    claims_by_id[c["claim_id"]] = c
                    settings_by_claim[c["claim_id"]] = settings
                    
            runs_by_claim = {}
            for ra in run_arts:
                ra_data = self.load_artifact_data(ArtifactSchema.model_validate(ra))
                cid = ra_data["claim_id"]
                if cid not in runs_by_claim:
                    runs_by_claim[cid] = []
                runs_by_claim[cid].append(ra_data)
            
            for va in verdict_arts:
                va_data = self.load_artifact_data(ArtifactSchema.model_validate(va))
                claim_id = va_data["claim_id"]
                
                # If there's a discrepancy
                if va_data["verdict"] not in ["Reproduced", "Not testable"]:
                    paper_settings = settings_by_claim.get(claim_id, {})
                    runs = runs_by_claim.get(claim_id, [])
                    
                    causes = []
                    
                    # 1. Compare Epochs
                    paper_epochs = paper_settings.get("epochs")
                    paper_evidence_dict = paper_settings.get("evidence", {})
                    
                    if paper_epochs and runs:
                        epochs_ev = paper_evidence_dict.get("epochs", {})
                        epochs_quote = epochs_ev.get("quote", "Unknown")
                        epochs_page = epochs_ev.get("page", "Unknown")
                        
                        causes.append(DiscrepancyCause(
                            category="epochs",
                            suspected=True,
                            confirmed=False,
                            paper_evidence=f"Quote: '{epochs_quote}' (Page {epochs_page})",
                            actual_evidence=f"Run command: {runs[0].get('command')}",
                            explanation="Differences in training duration may cause performance gaps."
                        ))
                    
                    # 2. Compare Seeds
                    paper_seeds = paper_settings.get("seeds")
                    run_seeds = [r.get("seed") for r in runs if r.get("seed") is not None]
                    if paper_seeds and run_seeds:
                        seeds_ev = paper_evidence_dict.get("seeds", {})
                        seeds_quote = seeds_ev.get("quote", "Unknown")
                        seeds_page = seeds_ev.get("page", "Unknown")
                        
                        if set(paper_seeds) != set(run_seeds):
                            # A cause must not become confirmed merely because a value appears in execution logs.
                            # It is confirmed ONLY if we explicitly have both paper seeds and run seeds and they differ.
                            # Since we have both here, and they differ, we confirm it.
                            causes.append(DiscrepancyCause(
                                category="seeds",
                                suspected=False,
                                confirmed=True, 
                                paper_evidence=f"Quote: '{seeds_quote}' (Page {seeds_page})",
                                actual_evidence=f"Run command configs/seeds: {run_seeds}",
                                explanation="Using different random seeds can lead to performance variation outside noise limits."
                            ))
                            
                    if not causes:
                        causes.append(DiscrepancyCause(
                            category="environment",
                            suspected=True,
                            confirmed=False,
                            paper_evidence="No specific settings evidence available to compare.",
                            actual_evidence=f"Environment digest: {runs[0].get('environment_digest', 'Unknown')}" if runs else "No run data",
                            explanation="General environment or unknown differences."
                        ))

                    diag = DiscrepancyDiagnosisArtifact(
                        assessment_id=assessment_id,
                        claim_id=claim_id,
                        metric_gap=va_data.get("gap"),
                        causes=causes
                    )
                    out_schema = self.save_artifact(db, assessment_id, "DiscrepancyDiagnosisArtifact", diag.model_dump())
                    output_artifacts.append(out_schema)
                    
            self._end_run(db, run, "completed", [o.id for o in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class AuditChecklistStage(WS6BaseStage):
    @property
    def stage_name(self) -> str:
        return "audit_checklist"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [a.id for a in input_artifacts])
        output_artifacts = []
        try:
            # Audit the claim
            # Fetch artifacts for audit
            claim_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimExtractionArtifact").all()
            run_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ExperimentRunArtifact").all()
            env_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "EnvironmentArtifact").all()
            mapping_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimMappingsArtifact").all()
            
            has_env = len(env_arts) > 0
            has_mappings = len(mapping_arts) > 0
            
            runs_by_claim = {}
            for ra in run_arts:
                ra_data = self.load_artifact_data(ArtifactSchema.model_validate(ra))
                cid = ra_data["claim_id"]
                if cid not in runs_by_claim:
                    runs_by_claim[cid] = []
                runs_by_claim[cid].append(ra_data)

            for ca in claim_arts:
                ca_data = self.load_artifact_data(ArtifactSchema.model_validate(ca))
                settings = ca_data.get("settings", {})
                
                for c in ca_data.get("claims", []):
                    cid = c["claim_id"]
                    runs = runs_by_claim.get(cid, [])
                    
                    def eval_state(val):
                        if val is None or val == "":
                            return "Missing"
                        return "Stated"
                        
                    items = [
                        AuditItem(category="dataset", state=eval_state(c.get("dataset")), evidence=f"Dataset: {c.get('dataset')}"),
                        AuditItem(category="split", state=eval_state(c.get("split")), evidence=f"Split: {c.get('split')}"),
                        AuditItem(category="metric", state=eval_state(c.get("metric")), evidence=f"Metric: {c.get('metric')}"),
                        AuditItem(category="hyperparameters/settings", state="Stated" if settings else "Missing", evidence=f"Settings present: {bool(settings)}"),
                        AuditItem(category="epochs", state=eval_state(settings.get("epochs")), evidence=f"Epochs: {settings.get('epochs')}"),
                        AuditItem(category="seeds", state=eval_state(settings.get("seeds")), evidence=f"Seeds: {settings.get('seeds')}"),
                        AuditItem(category="preprocessing", state=eval_state(settings.get("preprocessing")), evidence=f"Preprocessing: {settings.get('preprocessing')}"),
                        AuditItem(category="hardware", state=eval_state(settings.get("hardware")), evidence=f"Hardware: {settings.get('hardware')}"),
                        AuditItem(category="run mapping", state="Stated" if has_mappings else "Missing", evidence=f"Has Mappings: {has_mappings}"),
                        AuditItem(category="environment", state="Stated" if has_env else "Missing", evidence=f"Has Environment: {has_env}"),
                        AuditItem(category="execution outcome", state="Stated" if runs else "Missing", evidence=f"Total runs: {len(runs)}")
                    ]
                    
                    audit = AuditChecklistArtifact(
                        assessment_id=assessment_id,
                        claim_id=cid,
                        items=items
                    )
                    out_schema = self.save_artifact(db, assessment_id, "AuditChecklistArtifact", audit.model_dump())
                    output_artifacts.append(out_schema)
                    
            self._end_run(db, run, "completed", [o.id for o in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()
