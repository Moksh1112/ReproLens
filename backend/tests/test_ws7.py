import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import os
import json

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import sys
from app.db.session import SessionLocal
from app.db.models import Base, Assessment, Artifact
from app.pipeline.stages_ws7 import (
    ReportGenerationStage,
    GraphGenerationStage,
    ReproCardGenerationStage
)
from app.pipeline.orchestrator import run_pipeline, REGISTERED_STAGES
from app.storage.object_store import ObjectStore
from app.core.config import settings

class TestWS7(unittest.TestCase):
    def setUp(self):
        from app.db.session import engine
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        
        self.assessment_id = "ws7_test_123"
        asm = Assessment(
            id=self.assessment_id,
            paper_input_type="pdf",
            paper_source="test.pdf",
            repository_input_type="github",
            repository_source="repo",
            status="pending"
        )
        self.db.add(asm)
        self.db.commit()

        # Add mock artifacts for WS7 stages to consume
        arts = [
            Artifact(assessment_id=self.assessment_id, stage="claim_extraction", type="ClaimExtractionArtifact", object_path="claims.json", content_hash="11"),
            Artifact(assessment_id=self.assessment_id, stage="verdict_calculation", type="VerdictArtifact", object_path="verdict.json", content_hash="22"),
            Artifact(assessment_id=self.assessment_id, stage="paper_parsing", type="PaperDocumentArtifact", object_path="paper.json", content_hash="33")
        ]
        self.db.add_all(arts)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        from app.db.session import engine
        Base.metadata.drop_all(bind=engine)

    def test_report_generation(self):
        original_load = ObjectStore.load
        
        def mock_load(path):
            if path == "claims.json":
                return {"assessment_id": self.assessment_id, "claims": [{"claim_id": "c1", "metric": "Accuracy"}]}
            elif path == "verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "verdict": "Reproduced", "gap": 0.001}
            elif path == "paper.json":
                return {"assessment_id": self.assessment_id, "paper_date": "2023-01-01"}
            return original_load(path)
            
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = ReportGenerationStage()
            results = stage.execute(self.assessment_id, [])
            
            self.assertEqual(len(results), 1)
            report_meta = original_load(results[0].object_path)
            
            md_path = os.path.join(settings.STORAGE_DIR, report_meta["markdown_path"])
            pdf_path = os.path.join(settings.STORAGE_DIR, report_meta["pdf_path"])
            
            self.assertTrue(os.path.exists(md_path))
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            self.assertIn("Reproduced", md_content)
            self.assertIn("c1", md_content)
            self.assertIn("2023-01-01", md_content)
            
            os.remove(md_path)

    def test_graph_generation(self):
        original_load = ObjectStore.load
        
        def mock_load(path):
            if path == "claims.json":
                return {"assessment_id": self.assessment_id, "claims": [{"claim_id": "c1", "metric": "Accuracy"}]}
            elif path == "mapping.json":
                return {"assessment_id": self.assessment_id, "mappings": [{"claim_id": "c1", "script": "run.py"}]}
            elif path == "run.json":
                return {"assessment_id": self.assessment_id, "run_id": "r1", "claim_id": "c1"}
            elif path == "metric.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "observations": [{"run_id": "r1"}]}
            elif path == "verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "verdict": "Reproduced"}
            elif path == "discrepancy.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "gap": 0}
            return original_load(path)
            
        arts = [
            Artifact(assessment_id=self.assessment_id, stage="claim_mapping", type="ClaimMappingsArtifact", object_path="mapping.json", content_hash="map"),
            Artifact(assessment_id=self.assessment_id, stage="experiment_execution", type="ExperimentRunArtifact", object_path="run.json", content_hash="run"),
            Artifact(assessment_id=self.assessment_id, stage="metric_extraction", type="MetricAggregationArtifact", object_path="metric.json", content_hash="met"),
            Artifact(assessment_id=self.assessment_id, stage="discrepancy_diagnosis", type="DiscrepancyDiagnosisArtifact", object_path="discrepancy.json", content_hash="disc"),
        ]
        self.db.add_all(arts)
        self.db.commit()

        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = GraphGenerationStage()
            results = stage.execute(self.assessment_id, [])
            
            graph_meta = original_load(results[0].object_path)
            nodes = graph_meta["nodes"]
            edges = graph_meta["edges"]
            
            node_ids = [n["id"] for n in nodes]
            self.assertIn("claim_c1", node_ids)
            self.assertIn("mapping_c1", node_ids)
            self.assertIn("run_r1", node_ids)
            self.assertIn("metric_c1", node_ids)
            self.assertIn("verdict_c1", node_ids)
            self.assertIn("discrepancy_c1", node_ids)
            
            # verify edges link properly
            edge_ids = [e["id"] for e in edges]
            self.assertIn("edge_c_m_c1", edge_ids)
            self.assertIn("edge_m_r_r1", edge_ids)
            self.assertIn("edge_r_met_r1", edge_ids)
            self.assertIn("edge_met_v_c1", edge_ids)
            self.assertIn("edge_v_d_c1", edge_ids)

    def test_graph_missing_relations(self):
        original_load = ObjectStore.load
        
        def mock_load(path):
            if path == "claims.json":
                return {"assessment_id": self.assessment_id, "claims": [{"claim_id": "c1", "metric": "Accuracy"}]}
            elif path == "mapping.json":
                # mapping missing claim_id
                return {"assessment_id": self.assessment_id, "mappings": []}
            elif path == "run.json":
                return {"assessment_id": self.assessment_id, "run_id": "r1", "claim_id": "c1"}
            elif path == "metric.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "observations": [{"run_id": "r1"}]}
            elif path == "verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "verdict": "Reproduced"}
            return original_load(path)

        arts = [
            Artifact(assessment_id=self.assessment_id, stage="claim_mapping", type="ClaimMappingsArtifact", object_path="mapping.json", content_hash="map"),
            Artifact(assessment_id=self.assessment_id, stage="experiment_execution", type="ExperimentRunArtifact", object_path="run.json", content_hash="run"),
            Artifact(assessment_id=self.assessment_id, stage="metric_extraction", type="MetricAggregationArtifact", object_path="metric.json", content_hash="met"),
        ]
        self.db.add_all(arts)
        self.db.commit()

        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = GraphGenerationStage()
            results = stage.execute(self.assessment_id, [])
            graph_meta = original_load(results[0].object_path)
            
            nodes = graph_meta["nodes"]
            node_ids = [n["id"] for n in nodes]
            
            self.assertIn("claim_c1", node_ids)
            # mapping absent -> breaks chain -> run, metric, verdict shouldn't be added!
            self.assertNotIn("run_r1", node_ids)
            self.assertNotIn("metric_c1", node_ids)
            self.assertNotIn("verdict_c1", node_ids)


    def test_repro_card_generation(self):
        original_load = ObjectStore.load
        
        def mock_load(path):
            if path == "verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "verdict": "Reproduced", "gap": 0.001}
            elif path == "claims.json":
                return {"assessment_id": self.assessment_id, "claims": [{"claim_id": "c1", "metric": "Accuracy"}]}
            return original_load(path)
            
        arts = [
            Artifact(assessment_id=self.assessment_id, stage="claim_extraction", type="ClaimExtractionArtifact", object_path="claims.json", content_hash="ext"),
            Artifact(assessment_id=self.assessment_id, stage="verdict_calculation", type="VerdictArtifact", object_path="verdict.json", content_hash="verd")
        ]
        self.db.add_all(arts)
        self.db.commit()
            
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = ReproCardGenerationStage()
            results = stage.execute(self.assessment_id, [])
            
            card_meta = original_load(results[0].object_path)
            self.assertEqual(card_meta["paper_title"], "Unknown Paper")
            self.assertEqual(card_meta["top_discrepancies"], [])
            self.assertIn("coverage", card_meta)
            self.assertIn("repro_score", card_meta)

    def test_pipeline_integration_and_idempotency(self):
        original_load = ObjectStore.load
        
        def mock_load(path):
            if path == "claims.json":
                return {"assessment_id": self.assessment_id, "claims": [{"claim_id": "c1", "metric": "Accuracy"}]}
            elif path == "verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "c1", "verdict": "Reproduced", "gap": 0.001}
            elif path == "paper.json":
                return {"assessment_id": self.assessment_id, "paper_date": "2023-01-01"}
            return original_load(path)
            
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stages = [
                ReportGenerationStage(),
                GraphGenerationStage(),
                ReproCardGenerationStage()
            ]
            
            for stage in stages:
                stage.execute(self.assessment_id, [])
                
            arts = self.db.query(Artifact).filter(Artifact.assessment_id == self.assessment_id).all()
            types = [a.type for a in arts]
            self.assertIn("ReportArtifact", types)
            self.assertIn("ClaimGraphArtifact", types)
            self.assertIn("ReproCardArtifact", types)
            
            count_before = len(arts)
            
            old_registered = REGISTERED_STAGES[:]
            REGISTERED_STAGES.clear()
            REGISTERED_STAGES.extend(stages)
            
            try:
                run_pipeline(self.assessment_id)
                arts_after = self.db.query(Artifact).filter(Artifact.assessment_id == self.assessment_id).all()
                self.assertEqual(len(arts_after), count_before)
            finally:
                REGISTERED_STAGES.clear()
                REGISTERED_STAGES.extend(old_registered)

if __name__ == "__main__":
    unittest.main()
