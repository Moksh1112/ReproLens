import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import math

import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.db.session import SessionLocal
from app.db.models import Base, Assessment, Artifact
from app.pipeline.stages_ws6 import (
    MetricExtractionStage, 
    VerdictCalculationStage,
    DiscrepancyDiagnosisStage,
    AuditChecklistStage
)

class TestWS6(unittest.TestCase):
    def setUp(self):
        from app.db.session import engine
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()
        
        # Create Assessment
        self.assessment_id = "ws6_test_123"
        asm = Assessment(
            id=self.assessment_id,
            paper_input_type="pdf",
            paper_source="test.pdf",
            repository_input_type="github",
            repository_source="repo"
        )
        self.db.add(asm)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        from app.db.session import engine
        Base.metadata.drop_all(bind=engine)

    def test_metric_extraction(self):
        # Create fake Claim
        claim_art = Artifact(
            assessment_id=self.assessment_id,
            stage="claim_extraction",
            type="ClaimExtractionArtifact",
            object_path="claims.json",
            content_hash="111"
        )
        self.db.add(claim_art)
        
        # Create fake Run
        run_art = Artifact(
            assessment_id=self.assessment_id,
            stage="experiment_execution",
            type="ExperimentRunArtifact",
            object_path="run1.json",
            content_hash="222"
        )
        self.db.add(run_art)
        self.db.commit()
        
        from app.pipeline.base import ObjectStore
        original_load = ObjectStore.load
        
        def mock_load(path):
            if path == "claims.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [
                        {
                            "claim_id": "claim_1",
                            "experiment": "exp1",
                            "dataset": "ds1",
                            "metric": "Accuracy",
                            "value": 0.95,
                            "page": 1,
                            "evidence": {}
                        }
                    ],
                    "settings": {"evidence": {}}
                }
            elif path == "run1.json":
                return {
                    "assessment_id": self.assessment_id,
                    "run_id": "run_1",
                    "claim_id": "claim_1",
                    "status": "completed",
                    "exit_code": 0,
                    "environment_digest": "sha256:123",
                    "command": "python main.py",
                    "config": None,
                    "seed": 42,
                    "resource_limits": {},
                    "start_time": "2021",
                    "end_time": "2021",
                    "stdout_log_path": "stdout.log",
                    "stderr_log_path": "stderr.log"
                }
            return original_load(path)
            
        import os
        with open("stdout.log", "w", encoding="utf-8") as f:
            f.write("Training started...\\nAccuracy: 94.5\\nDone.")
            
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = MetricExtractionStage()
            results = stage.execute(self.assessment_id, [])
            
            self.assertEqual(len(results), 1)
            
            art_id = results[0].id
            agg = self.db.query(Artifact).filter_by(id=art_id).first()
            
            # Read normally
            real_agg_data = ObjectStore.load(agg.object_path)
            self.assertEqual(real_agg_data["claim_id"], "claim_1")
            self.assertEqual(len(real_agg_data["observations"]), 1)
            obs = real_agg_data["observations"][0]
            self.assertEqual(obs["raw_value"], 94.5)
            self.assertEqual(obs["normalized_value"], 0.945)
            self.assertEqual(obs["seed"], 42)
            
        if os.path.exists("stdout.log"):
            os.remove("stdout.log")

    def _create_verdict_test_data(self, claim_val, claim_std, obs_vals):
        claim_art = Artifact(
            assessment_id=self.assessment_id,
            stage="claim_extraction",
            type="ClaimExtractionArtifact",
            object_path="claims_verdict.json",
            content_hash="111"
        )
        self.db.add(claim_art)
        
        agg_art = Artifact(
            assessment_id=self.assessment_id,
            stage="metric_extraction",
            type="MetricAggregationArtifact",
            object_path="agg_verdict.json",
            content_hash="222"
        )
        self.db.add(agg_art)
        self.db.commit()
        
        observations = []
        for i, v in enumerate(obs_vals):
            observations.append({
                "run_id": f"run_{i}",
                "metric_name": "Accuracy",
                "raw_value": v * 100,
                "normalized_value": v,
                "seed": i,
                "source_log": "stdout.log",
                "evidence": None
            })
            
        return claim_art, agg_art, observations

    def test_verdict_reproduced(self):
        # claim=0.95, std=0.01. obs = 0.95, 0.955, 0.945. mean=0.95
        _, agg_art, obs = self._create_verdict_test_data(0.95, 0.01, [0.95, 0.955, 0.945])
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1", "metric": "Accuracy", "value": 0.95, "standard_deviation": 0.01, "page":1, "dataset":"", "experiment":"", "evidence":{}}],
                    "settings": {"evidence": {}}
                }
            elif path == "agg_verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "claim_1", "observations": obs}
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = VerdictCalculationStage()
            results = stage.execute(self.assessment_id, [])
            v_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(v_data["verdict"], "Reproduced")

    def test_verdict_within_noise(self):
        # claim=0.95, std=0.01. obs = 0.935, 0.94. mean=0.9375. gap=0.0125. 
        # tolerance = 0.01. gap <= 2 * tolerance (0.02).
        # paper min = 0.94, rep max = 0.94. overlap = True!
        _, agg_art, obs = self._create_verdict_test_data(0.95, 0.01, [0.935, 0.94])
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1", "metric": "Accuracy", "value": 0.95, "standard_deviation": 0.01, "page":1, "dataset":"", "experiment":"", "evidence":{}}],
                    "settings": {"evidence": {}}
                }
            elif path == "agg_verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "claim_1", "observations": obs}
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = VerdictCalculationStage()
            results = stage.execute(self.assessment_id, [])
            v_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(v_data["verdict"], "Within noise")

    def test_verdict_partially_reproduced(self):
        # claim=0.95, std=0.01. obs = 0.925. mean=0.925. gap=0.025.
        # tolerance=0.01. gap > 2 * tolerance (0.02). gap <= 3 * tolerance (0.03).
        # This simulates "gap > 2*tolerance with same conclusion/ranking".
        _, agg_art, obs = self._create_verdict_test_data(0.95, 0.01, [0.925, 0.925])
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1", "metric": "Accuracy", "value": 0.95, "standard_deviation": 0.01, "page":1, "dataset":"", "experiment":"", "evidence":{}, "baseline": {"value": 0.90, "quote": "Baseline is 90", "page": 2}}],
                    "settings": {"evidence": {}}
                }
            elif path == "agg_verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "claim_1", "observations": obs}
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = VerdictCalculationStage()
            results = stage.execute(self.assessment_id, [])
            v_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(v_data["verdict"], "Partially reproduced")
            
    def test_verdict_not_reproduced(self):
        # gap > 3 * tolerance -> simulates flipped conclusion
        _, agg_art, obs = self._create_verdict_test_data(0.95, 0.01, [0.80, 0.80])
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1", "metric": "Accuracy", "value": 0.95, "standard_deviation": 0.01, "page":1, "dataset":"", "experiment":"", "evidence":{}, "baseline": {"value": 0.90, "quote": "Baseline is 90", "page": 2}}],
                    "settings": {"evidence": {}}
                }
            elif path == "agg_verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "claim_1", "observations": obs}
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = VerdictCalculationStage()
            results = stage.execute(self.assessment_id, [])
            v_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(v_data["verdict"], "Not reproduced")

    def test_verdict_large_gap_no_flip(self):
        # gap is huge (0.95 -> 0.10) but no baseline provided. Should be Not testable because we cannot verify ranking direction.
        _, agg_art, obs = self._create_verdict_test_data(0.95, 0.01, [0.10, 0.10])
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1", "metric": "Accuracy", "value": 0.95, "standard_deviation": 0.01, "page":1, "dataset":"", "experiment":"", "evidence":{}}],
                    "settings": {"evidence": {}}
                }
            elif path == "agg_verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "claim_1", "observations": obs}
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = VerdictCalculationStage()
            results = stage.execute(self.assessment_id, [])
            v_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(v_data["verdict"], "Not testable")

    def test_verdict_sign_change_no_flip(self):
        # Value changes from 0.5 to -0.5, crossing 0, but no baseline is provided.
        # This is a large gap with no established direction/ranking, so Not testable.
        _, agg_art, obs = self._create_verdict_test_data(0.50, 0.01, [-0.50, -0.50])
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1", "metric": "SomeScore", "value": 0.50, "standard_deviation": 0.01, "page":1, "dataset":"", "experiment":"", "evidence":{}}],
                    "settings": {"evidence": {}}
                }
            elif path == "agg_verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "claim_1", "observations": obs}
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = VerdictCalculationStage()
            results = stage.execute(self.assessment_id, [])
            v_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(v_data["verdict"], "Not testable")

    def test_verdict_not_testable(self):
        _, agg_art, obs = self._create_verdict_test_data(0.95, 0.01, [])
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1", "metric": "Accuracy", "value": 0.95, "standard_deviation": 0.01, "page":1, "dataset":"", "experiment":"", "evidence":{}}],
                    "settings": {"evidence": {}}
                }
            elif path == "agg_verdict.json":
                return {"assessment_id": self.assessment_id, "claim_id": "claim_1", "observations": []}
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = VerdictCalculationStage()
            results = stage.execute(self.assessment_id, [])
            v_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(v_data["verdict"], "Not testable")

    def test_discrepancy_diagnosis(self):
        # Create artifacts
        v_art = Artifact(
            assessment_id=self.assessment_id,
            stage="verdict_calculation",
            type="VerdictArtifact",
            object_path="verdict.json",
            content_hash="333"
        )
        self.db.add(v_art)
        
        claim_art = Artifact(
            assessment_id=self.assessment_id,
            stage="claim_extraction",
            type="ClaimExtractionArtifact",
            object_path="claims_diag.json",
            content_hash="111"
        )
        self.db.add(claim_art)
        
        run_art = Artifact(
            assessment_id=self.assessment_id,
            stage="experiment_execution",
            type="ExperimentRunArtifact",
            object_path="run_diag.json",
            content_hash="222"
        )
        self.db.add(run_art)
        self.db.commit()
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "verdict.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claim_id": "claim_1",
                    "verdict": "Not reproduced",
                    "reported_value": 0.95,
                    "reported_std": None,
                    "reproduced_mean": 0.8,
                    "reproduced_std": None,
                    "tolerance": 0.01,
                    "gap": 0.15,
                    "seed_range": [0.8, 0.8],
                    "observations": [],
                    "reason": ""
                }
            elif path == "claims_diag.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1"}],
                    "settings": {
                        "epochs": 100, 
                        "seeds": [1, 2, 3],
                        "evidence": {
                            "epochs": {"quote": "We train for 100 epochs", "page": 2},
                            "seeds": {"quote": "Random seeds 1, 2, 3", "page": 3}
                        }
                    }
                }
            elif path == "run_diag.json":
                return {
                    "assessment_id": self.assessment_id,
                    "run_id": "r1",
                    "claim_id": "claim_1",
                    "seed": 42,
                    "command": "python train.py --epochs 50"
                }
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = DiscrepancyDiagnosisStage()
            results = stage.execute(self.assessment_id, [])
            d_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            
            self.assertEqual(len(d_data["causes"]), 2)
            categories = [c["category"] for c in d_data["causes"]]
            self.assertIn("epochs", categories)
            self.assertIn("seeds", categories)
            
            # Epochs should remain suspected (not confirmed just because we see epochs in run log)
            epoch_cause = next(c for c in d_data["causes"] if c["category"] == "epochs")
            self.assertTrue(epoch_cause["suspected"])
            self.assertFalse(epoch_cause["confirmed"])
            self.assertIn("We train for 100 epochs", epoch_cause["paper_evidence"])
            self.assertIn("Page 2", epoch_cause["paper_evidence"])
            self.assertIn("--epochs 50", epoch_cause["actual_evidence"])
            
            # Seed diff should be confirmed (run log explicitly gives 42, paper gave [1,2,3])
            seed_cause = next(c for c in d_data["causes"] if c["category"] == "seeds")
            self.assertTrue(seed_cause["confirmed"])
            self.assertFalse(seed_cause["suspected"])
            self.assertIn("Random seeds 1, 2, 3", seed_cause["paper_evidence"])
            self.assertIn("Page 3", seed_cause["paper_evidence"])
            self.assertIn("42", seed_cause["actual_evidence"])

    def test_audit_checklist(self):
        claim_art = Artifact(
            assessment_id=self.assessment_id,
            stage="claim_extraction",
            type="ClaimExtractionArtifact",
            object_path="claims_audit.json",
            content_hash="111"
        )
        self.db.add(claim_art)
        self.db.commit()
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_audit.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [{"claim_id": "claim_1"}],
                    "settings": {}
                }
            return ObjectStore._real_load(path)
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            stage = AuditChecklistStage()
            results = stage.execute(self.assessment_id, [])
            a_data = ObjectStore._real_load(self.db.query(Artifact).filter_by(id=results[0].id).first().object_path)
            self.assertEqual(len(a_data["items"]), 11)
            categories = [i["category"] for i in a_data["items"]]
            self.assertIn("dataset", categories)
            self.assertIn("seeds", categories)
            self.assertIn("execution outcome", categories)
            
            # Since settings were empty and no env artifact provided, it should say Missing
            hw_item = next(i for i in a_data["items"] if i["category"] == "hardware")
            self.assertEqual(hw_item["state"], "Missing")
            
            run_item = next(i for i in a_data["items"] if i["category"] == "execution outcome")
            self.assertEqual(run_item["state"], "Missing")

    def test_pipeline_integration_and_idempotency(self):
        # We need an assessment
        # Create minimal WS4/WS5 artifacts
        claim_art = Artifact(
            assessment_id=self.assessment_id,
            stage="claim_extraction",
            type="ClaimExtractionArtifact",
            object_path="claims_integration.json",
            content_hash="111"
        )
        self.db.add(claim_art)
        
        run_art = Artifact(
            assessment_id=self.assessment_id,
            stage="experiment_execution",
            type="ExperimentRunArtifact",
            object_path="run_integration.json",
            content_hash="222"
        )
        self.db.add(run_art)
        self.db.commit()
        
        from app.pipeline.orchestrator import run_pipeline, REGISTERED_STAGES
        
        from app.pipeline.base import ObjectStore
        def mock_load(path):
            if path == "claims_integration.json":
                return {
                    "assessment_id": self.assessment_id,
                    "claims": [
                        {"claim_id": "c1", "metric": "Accuracy", "value": 0.95, "standard_deviation": 0.01, "baseline": {"value": 0.90, "quote": "Base", "page": 1}}
                    ],
                    "settings": {}
                }
            elif path == "run_integration.json":
                return {
                    "assessment_id": self.assessment_id,
                    "run_id": "r1",
                    "claim_id": "c1",
                    "stdout_log_path": "stdout.log",
                    "status": "completed",
                    "exit_code": 0,
                    "seed": 42
                }
            return ObjectStore._real_load(path)
            
        import os
        with open("stdout.log", "w", encoding="utf-8") as f:
            f.write("Accuracy: 80.0\\n")
            
        ObjectStore._real_load = ObjectStore.load
        with patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
            # Run the entire pipeline (WS1-WS6). Since WS1-WS5 won't have inputs/mocks here, they might fail or do nothing.
            # Actually, to avoid running WS1-WS5, we can just run WS6 stages directly:
            from app.pipeline.stages_ws6 import (
                MetricExtractionStage, VerdictCalculationStage, DiscrepancyDiagnosisStage, AuditChecklistStage
            )
            stages = [
                MetricExtractionStage(),
                VerdictCalculationStage(),
                DiscrepancyDiagnosisStage(),
                AuditChecklistStage()
            ]
            
            for stage in stages:
                stage.execute(self.assessment_id, [])
                
            # Verify outputs
            arts = self.db.query(Artifact).filter(Artifact.assessment_id == self.assessment_id).all()
            types = [a.type for a in arts]
            self.assertIn("MetricAggregationArtifact", types)
            self.assertIn("VerdictArtifact", types)
            self.assertIn("DiscrepancyDiagnosisArtifact", types)
            self.assertIn("AuditChecklistArtifact", types)
            
            # Idempotency check: run them again and ensure artifact count doesn't increase for these stages
            count_before = len(arts)
            
            # The orchestrator is supposed to skip completed stages.
            # Let's test the orchestrator idempotency logic.
            # Register ONLY ws6 stages to avoid missing dependencies from WS1-5
            old_registered = REGISTERED_STAGES[:]
            REGISTERED_STAGES.clear()
            REGISTERED_STAGES.extend(stages)
            
            try:
                run_pipeline(self.assessment_id)
                # Count should remain the same because orchestrator skips completed stages
                arts_after = self.db.query(Artifact).filter(Artifact.assessment_id == self.assessment_id).all()
                self.assertEqual(len(arts_after), count_before)
            finally:
                REGISTERED_STAGES.clear()
                REGISTERED_STAGES.extend(old_registered)
                if os.path.exists("stdout.log"):
                    os.remove("stdout.log")

if __name__ == "__main__":
    unittest.main()
