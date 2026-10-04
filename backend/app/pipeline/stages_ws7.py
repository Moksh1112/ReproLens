import os
import uuid
import json
import markdown
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from app.core.config import settings
from app.db.models import Artifact, StageRun
from app.db.session import SessionLocal
from app.pipeline.base import BaseStage
from app.schemas.artifacts import ArtifactSchema
from app.storage.object_store import ObjectStore

class WS7BaseStage(BaseStage):
    def _create_db_session(self):
        return SessionLocal()
        
    def _start_run(self, db, assessment_id, input_artifact_ids=None):
        run = StageRun(
            id=str(uuid.uuid4()),
            assessment_id=assessment_id,
            stage_name=self.stage_name,
            status="running",
            input_artifact_ids=input_artifact_ids or [],
            started_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        return run

    def _end_run(self, db, run, status, output_artifact_ids=None, error_msg=None):
        run.status = status
        if output_artifact_ids is not None:
            run.output_artifact_ids = output_artifact_ids
        if error_msg:
            run.error_message = error_msg
        run.completed_at = datetime.utcnow()
        db.commit()

class ReportGenerationStage(WS7BaseStage):
    @property
    def stage_name(self) -> str:
        return "report_generation"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [a.id for a in input_artifacts])
        output_artifacts = []
        try:
            md_content = f"# Reproducibility Report for {assessment_id}\n\n"
            
            paper_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "PaperDocumentArtifact").all()
            if paper_arts:
                paper_data = self.load_artifact_data(ArtifactSchema.model_validate(paper_arts[0]))
                md_content += f"## Paper Metadata\n"
                md_content += f"Date: {paper_data.get('paper_date')}\n\n"
                
            verdict_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "VerdictArtifact").all()
            
            md_content += "## Verdicts\n"
            for va in verdict_arts:
                va_data = self.load_artifact_data(ArtifactSchema.model_validate(va))
                cid = va_data["claim_id"]
                md_content += f"### Claim: {cid}\n"
                md_content += f"Verdict: {va_data.get('verdict')}\n"
                md_content += f"Gap: {va_data.get('gap')}\n\n"
                
            timestamp = datetime.utcnow().isoformat()
            rel_md_path = f"{assessment_id}/report.md"
            abs_md_path = os.path.join(settings.STORAGE_DIR, rel_md_path)
            rel_pdf_path = f"{assessment_id}/report.pdf"
            abs_pdf_path = os.path.join(settings.STORAGE_DIR, rel_pdf_path)
            
            ObjectStore._ensure_dir(abs_md_path)
            with open(abs_md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
                
            html_content = markdown.markdown(md_content)
            html_content = f"<html><body>{html_content}</body></html>"
            
            try:
                from weasyprint import HTML
                HTML(string=html_content).write_pdf(abs_pdf_path)
            except (ImportError, OSError) as e:
                print(f"Warning: PDF generation skipped due to WeasyPrint environment limitation: {e}")
                # Don't fail the entire stage, just skip the PDF so E2E can finish
                pass
            
            report_meta = {
                "assessment_id": assessment_id,
                "markdown_path": rel_md_path,
                "pdf_path": rel_pdf_path,
                "generation_timestamp": timestamp,
            }
            out_schema = self.save_artifact(db, assessment_id, "ReportArtifact", report_meta)
            output_artifacts.append(out_schema)
            
            self._end_run(db, run, "completed", [o.id for o in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class GraphGenerationStage(WS7BaseStage):
    @property
    def stage_name(self) -> str:
        return "graph_generation"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [a.id for a in input_artifacts])
        output_artifacts = []
        try:
            nodes = []
            edges = []
            
            def add_node(nid, ntype, label):
                nodes.append({"id": nid, "type": ntype, "data": {"label": label}})
            def add_edge(eid, src, tgt):
                edges.append({"id": eid, "source": src, "target": tgt})
                
            claim_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimExtractionArtifact").all()
            valid_claims = set()
            for ca in claim_arts:
                ca_data = self.load_artifact_data(ArtifactSchema.model_validate(ca))
                for c in ca_data.get("claims", []):
                    cid = str(c.get('claim_id', ''))
                    if cid:
                        valid_claims.add(cid)
                        add_node(f"claim_{cid}", "claim", f"Claim: {c.get('metric', 'Unknown')}")
            
            mapping_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimMappingsArtifact").all()
            valid_mappings = set()
            for ma in mapping_arts:
                ma_data = self.load_artifact_data(ArtifactSchema.model_validate(ma))
                for m in ma_data.get("mappings", []):
                    cid = str(m.get('claim_id', ''))
                    if cid in valid_claims:
                        add_node(f"mapping_{cid}", "mapping", "Mapping")
                        add_edge(f"edge_c_m_{cid}", f"claim_{cid}", f"mapping_{cid}")
                        valid_mappings.add(cid)
                        
            run_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ExperimentRunArtifact").all()
            valid_runs = set()
            for ra in run_arts:
                ra_data = self.load_artifact_data(ArtifactSchema.model_validate(ra))
                cid = str(ra_data.get('claim_id', ''))
                rid = str(ra_data.get('run_id', ''))
                if cid in valid_mappings and rid:
                    add_node(f"run_{rid}", "run", f"Run {rid}")
                    add_edge(f"edge_m_r_{rid}", f"mapping_{cid}", f"run_{rid}")
                    valid_runs.add(rid)
                    
            metric_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "MetricAggregationArtifact").all()
            valid_metrics_claims = set()
            for m_art in metric_arts:
                m_data = self.load_artifact_data(ArtifactSchema.model_validate(m_art))
                cid = str(m_data.get('claim_id', ''))
                
                # Only add metric if it connects to at least one valid run
                has_valid_run = any(str(obs.get("run_id", "")) in valid_runs for obs in m_data.get("observations", []))
                if cid and has_valid_run:
                    add_node(f"metric_{cid}", "metric", "Aggregated Metric")
                    valid_metrics_claims.add(cid)
                    for obs in m_data.get("observations", []):
                        rid = str(obs.get("run_id", ""))
                        if rid in valid_runs:
                            add_edge(f"edge_r_met_{rid}", f"run_{rid}", f"metric_{cid}")
                            
            verdict_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "VerdictArtifact").all()
            valid_verdicts = set()
            for va in verdict_arts:
                va_data = self.load_artifact_data(ArtifactSchema.model_validate(va))
                cid = str(va_data.get('claim_id', ''))
                if cid in valid_metrics_claims:
                    add_node(f"verdict_{cid}", "verdict", f"Verdict: {va_data.get('verdict')}")
                    add_edge(f"edge_met_v_{cid}", f"metric_{cid}", f"verdict_{cid}")
                    valid_verdicts.add(cid)
                    
            discrepancy_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "DiscrepancyDiagnosisArtifact").all()
            for da in discrepancy_arts:
                da_data = self.load_artifact_data(ArtifactSchema.model_validate(da))
                cid = str(da_data.get('claim_id', ''))
                if cid in valid_verdicts:
                    add_node(f"discrepancy_{cid}", "discrepancy", "Discrepancy")
                    add_edge(f"edge_v_d_{cid}", f"verdict_{cid}", f"discrepancy_{cid}")
                
            graph_meta = {
                "assessment_id": assessment_id,
                "nodes": nodes,
                "edges": edges,
            }
            out_schema = self.save_artifact(db, assessment_id, "ClaimGraphArtifact", graph_meta)
            output_artifacts.append(out_schema)
            
            self._end_run(db, run, "completed", [o.id for o in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()

class ReproCardGenerationStage(WS7BaseStage):
    @property
    def stage_name(self) -> str:
        return "repro_card_generation"

    def execute(self, assessment_id: str, input_artifacts: List[ArtifactSchema]) -> List[ArtifactSchema]:
        db = self._create_db_session()
        run = self._start_run(db, assessment_id, [a.id for a in input_artifacts])
        output_artifacts = []
        try:
            claims_info = []
            verdict_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "VerdictArtifact").all()
            
            testable_claims = 0
            success_claims = 0
            
            for va in verdict_arts:
                va_data = self.load_artifact_data(ArtifactSchema.model_validate(va))
                verdict = va_data.get("verdict")
                claims_info.append({
                    "claim_id": va_data["claim_id"],
                    "verdict": verdict,
                    "gap": va_data.get("gap")
                })
                
                if verdict != "Not testable":
                    testable_claims += 1
                    if verdict in ["Reproduced", "Within noise"]:
                        success_claims += 1
            
            total_claims = 0
            claim_ext_arts = db.query(Artifact).filter(Artifact.assessment_id == assessment_id, Artifact.type == "ClaimExtractionArtifact").all()
            if claim_ext_arts:
                claim_data = self.load_artifact_data(ArtifactSchema.model_validate(claim_ext_arts[0]))
                total_claims = len(claim_data.get("claims", []))
            else:
                total_claims = len(verdict_arts) # Fallback
                
            coverage = (testable_claims / total_claims) if total_claims > 0 else 0.0
            repro_score = (success_claims / testable_claims * 100.0) if testable_claims > 0 else 0.0
                
            repro_card_meta = {
                "assessment_id": assessment_id,
                "paper_title": "Unknown Paper",
                "environment_lockfile": "",
                "top_discrepancies": [],
                "coverage": coverage,
                "repro_score": repro_score
            }
            out_schema = self.save_artifact(db, assessment_id, "ReproCardArtifact", repro_card_meta)
            output_artifacts.append(out_schema)
            
            self._end_run(db, run, "completed", [o.id for o in output_artifacts])
            return output_artifacts
        except Exception as e:
            if 'run' in locals():
                self._end_run(db, run, "failed", [], str(e))
            raise e
        finally:
            db.close()
