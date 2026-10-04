import unittest
import os
import shutil
import uuid
import json
import time

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.db.session import SessionLocal, engine
from app.db.models import Base, Assessment, Artifact, StageRun
from app.execution.docker_manager import DockerManager
from app.pipeline.stages_ws5 import EnvironmentStage, ExecutionStage
from app.schemas.artifacts import (
    ArtifactSchema, RepositoryIndexArtifact, ClaimMappingsArtifact, 
    ClaimExtractionArtifact, ClaimData, ExperimentSettings, ClaimMapping,
    EnvironmentArtifact, ExperimentRunArtifact
)
from app.storage.object_store import ObjectStore

class TestWS5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        os.environ["REPROLENS_STORAGE_DIR"] = "/tmp/reprolens_test_storage_ws5"
        ObjectStore.storage_dir = "/tmp/reprolens_test_storage_ws5"
        os.makedirs(ObjectStore.storage_dir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        if os.path.exists(ObjectStore.storage_dir):
            shutil.rmtree(ObjectStore.storage_dir)

    def setUp(self):
        self.db = SessionLocal()
        self.assessment_id = str(uuid.uuid4())
        assessment = Assessment(
            id=self.assessment_id,
            paper_input_type="pdf",
            paper_source="dummy",
            repository_input_type="github",
            repository_source="dummy",
            status="running"
        )
        self.db.add(assessment)
        self.db.commit()

        # Create dummy artifacts from WS4
        
        # 1. Repo Index
        repo_data = RepositoryIndexArtifact(
            assessment_id=self.assessment_id,
            repo_hash="dummy_hash",
            entry_scripts=["main.py"],
            argparse_interfaces={"main.py": ["--seed", "--learning-rate"]},
            yaml_configs=[],
            readme_commands=[],
            dependencies=["requirements.txt"]
        )
        meta = ObjectStore.save(self.assessment_id, "RepositoryIndexArtifact", repo_data.model_dump())
        repo_art = Artifact(
            id=str(uuid.uuid4()),
            assessment_id=self.assessment_id,
            stage="repo_indexing",
            type="RepositoryIndexArtifact",
            object_path=meta["object_path"],
            content_hash=meta["content_hash"]
        )
        self.db.add(repo_art)
        
        # 2. Claim Extraction
        settings = ExperimentSettings(seeds=None, evidence={"hyperparameters": {"quote":"", "page":0}})
        claims_data = ClaimExtractionArtifact(
            assessment_id=self.assessment_id,
            claims=[],
            settings=settings
        )
        meta = ObjectStore.save(self.assessment_id, "ClaimExtractionArtifact", claims_data.model_dump())
        claims_art = Artifact(
            id=str(uuid.uuid4()),
            assessment_id=self.assessment_id,
            stage="claim_extraction",
            type="ClaimExtractionArtifact",
            object_path=meta["object_path"],
            content_hash=meta["content_hash"]
        )
        self.db.add(claims_art)

        # 3. Claim Mapping
        mapping = ClaimMapping(
            claim_id="claim_1",
            script="main.py",
            command="python main.py",
            confidence=0.9,
            evidence="looks good"
        )
        mapping2 = ClaimMapping(
            claim_id="claim_2",
            script="main.py",
            command="python main.py --seed 99",
            confidence=0.9,
            evidence="looks good"
        )
        mappings_data = ClaimMappingsArtifact(
            assessment_id=self.assessment_id,
            mappings=[mapping, mapping2]
        )
        meta = ObjectStore.save(self.assessment_id, "ClaimMappingsArtifact", mappings_data.model_dump())
        mappings_art = Artifact(
            id=str(uuid.uuid4()),
            assessment_id=self.assessment_id,
            stage="claim_mapping",
            type="ClaimMappingsArtifact",
            object_path=meta["object_path"],
            content_hash=meta["content_hash"]
        )
        self.db.add(mappings_art)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_environment_stage(self):
        stage = EnvironmentStage()
        output = stage.execute(self.assessment_id, [])
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0].type, "EnvironmentArtifact")
        
        # Check that Environment metadata is deterministic/pinned
        env_data = ObjectStore.load(output[0].object_path)
        self.assertEqual(env_data["dependencies"], ["requirements.txt"])
        self.assertIn("FROM python:3.10-slim", env_data["dockerfile"])
        self.assertIn("RUN useradd -m repro", env_data["dockerfile"]) # Non-root test
        self.assertTrue(env_data["image_digest"].startswith("sha256:"))

    def test_execution_stage(self):
        # Run env stage first
        env_stage = EnvironmentStage()
        env_stage.execute(self.assessment_id, [])
        
        exec_stage = ExecutionStage()
        output = exec_stage.execute(self.assessment_id, [])
        
        # We mapped 2 claims, 3 default seeds, so 6 output artifacts
        self.assertEqual(len(output), 6)
        
        claim_1_runs = [a for a in output if ObjectStore.load(a.object_path)["claim_id"] == "claim_1"]
        claim_2_runs = [a for a in output if ObjectStore.load(a.object_path)["claim_id"] == "claim_2"]
        
        for i, art in enumerate(claim_1_runs):
            self.assertEqual(art.type, "ExperimentRunArtifact")
            data = ObjectStore.load(art.object_path)
            self.assertIn(data["seed"], [42, 43, 44]) # Explicit seed recording
            self.assertIn(f"--seed {data['seed']}", data["command"])
            self.assertEqual(data["resource_limits"]["cpus"], 4) # CPU limits
            self.assertEqual(data["resource_limits"]["memory"], "8g") # RAM limits
            self.assertIn("exit_code", data)
            self.assertTrue(os.path.exists(data["stdout_log_path"]))
            self.assertTrue(os.path.exists(data["stderr_log_path"]))
            
        for i, art in enumerate(claim_2_runs):
            data = ObjectStore.load(art.object_path)
            self.assertIn(data["seed"], [42, 43, 44])
            # Command already had --seed 99, so it should not append another --seed 42
            self.assertEqual(data["command"], "python main.py --seed 99")

    def test_docker_command_construction(self):
        # Check how docker manager builds the run command
        # Network disabled, non-root run, read-only
        limits = {"cpus": 4, "memory": "8g"}
        import unittest.mock as mock
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            # Need to patch is_docker_available to pretend it's real so it goes into real branch
            with mock.patch.object(DockerManager, 'is_docker_available', return_value=True):
                DockerManager.run_experiment("test_image", "python main.py", 42, limits, "/tmp")
                
            cmd = mock_run.call_args[0][0]
            self.assertIn("docker", cmd)
            self.assertIn("--network", cmd)
            self.assertIn("none", cmd) # Network disabled
            self.assertIn("--read-only", cmd) # Read-only source
            self.assertIn("--cpus", cmd)
            self.assertIn("--memory", cmd)
            self.assertIn("--pids-limit", cmd)

    def test_real_docker_execution(self):
        if not DockerManager.is_docker_available():
            self.skipTest("Docker is not available on the host")
            
        repo_path = "/tmp/reprolens_test_repo_real"
        os.makedirs(repo_path, exist_ok=True)
        with open(os.path.join(repo_path, "main.py"), "w") as f:
            f.write("print('Hello from Docker!')\n")
            
        image_name, digest, doc, lck = DockerManager.build_environment(
            assessment_id="test1234",
            repo_path=repo_path,
            dependencies=[]
        )
        
        limits = {"cpus": 4, "memory": "8g", "timeout": 20}
        res = DockerManager.run_experiment(image_name, "python main.py", 42, limits, repo_path)
        
        self.assertEqual(res["exit_code"], 0)
        with open(res["stdout_path"], "r") as f:
            output = f.read()
            
        self.assertIn("Hello from Docker!", output)
        
        # Test timeout handling
        res_timeout = DockerManager.run_experiment(image_name, "sleep 10", 42, {"timeout": 1}, repo_path)
        self.assertEqual(res_timeout["exit_code"], 124)

    def test_dependency_inference(self):
        import unittest.mock as mock
        from datetime import datetime
        import json
        
        # Mock PyPI response for numpy
        mock_pypi_data = {
            "releases": {
                "1.21.0": [{"upload_time": "2021-06-22T10:00:00"}],
                "1.22.0": [{"upload_time": "2022-01-01T10:00:00"}],
                "1.23.0": [{"upload_time": "2022-06-22T10:00:00"}],
            }
        }
        
        target_date = datetime(2022, 2, 1)
        
        # Test unit function
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.read.return_value = json.dumps(mock_pypi_data).encode("utf-8")
            mock_response.__enter__.return_value = mock_response
            mock_urlopen.return_value = mock_response
            
            pin = DockerManager.infer_dependency_pin("numpy", target_date)
            self.assertEqual(pin, "1.22.0")
            
            # Test unresolvable dependency (no releases before date)
            early_date = datetime(2020, 1, 1)
            pin_unresolved = DockerManager.infer_dependency_pin("numpy", early_date)
            self.assertIsNone(pin_unresolved)
            
        # Test environment preparation fails on unresolvable dependency when no date provided
        repo_path = "/tmp/reprolens_test_repo_inference"
        os.makedirs(repo_path, exist_ok=True)
        with open(os.path.join(repo_path, "requirements.txt"), "w") as f:
            f.write("unknown_package\n")
            
        with self.assertRaises(ValueError) as ctx:
            DockerManager.build_environment(
                assessment_id="test1234",
                repo_path=repo_path,
                dependencies=["requirements.txt"],
                target_date=None
            )
        self.assertIn("No paper/repository date available", str(ctx.exception))
        
        # Test full stage extraction from paper_date
        db = SessionLocal()
        try:
            assessment = Assessment(
                id="test_inference_123",
                paper_input_type="pdf",
                paper_source="test.pdf",
                repository_input_type="github",
                repository_source="repo"
            )
            db.add(assessment)
            
            # Repo art with an unpinned dependency
            repo_art = Artifact(
                assessment_id="test_inference_123",
                stage="repo_indexing",
                type="RepositoryIndexArtifact",
                object_path="repo.json",
                content_hash="123"
            )
            db.add(repo_art)
            
            paper_art = Artifact(
                assessment_id="test_inference_123",
                stage="paper_parsing",
                type="PaperDocumentArtifact",
                object_path="paper.json",
                content_hash="456"
            )
            db.add(paper_art)
            db.commit()
            
            # Mock object store
            from app.pipeline.base import ObjectStore
            original_load = ObjectStore.load
            
            def mock_load(path):
                if path == "repo.json":
                    return {
                        "assessment_id": "test_inference_123",
                        "repo_hash": "123",
                        "entry_scripts": [],
                        "argparse_interfaces": {},
                        "yaml_configs": [],
                        "readme_commands": [],
                        "dependencies": ["requirements.txt"]
                    }
                elif path == "paper.json":
                    return {
                        "assessment_id": "test_inference_123",
                        "content_hash": "456",
                        "sections": [],
                        "tables": [],
                        "paper_date": "2022-02-01T00:00:00Z"
                    }
                return original_load(path)
                
            with mock.patch("app.pipeline.base.ObjectStore.load", side_effect=mock_load):
                stage = EnvironmentStage()
                with mock.patch("app.execution.docker_manager.DockerManager.build_environment") as mock_build:
                    mock_build.return_value = ("img", "dig", "dockerfile", "lockfile")
                    stage.execute("test_inference_123", [])
                    
                    # Verify that build_environment was called with the date extracted from the artifact
                    mock_build.assert_called_once()
                    called_kwargs = mock_build.call_args.kwargs
                    self.assertIsNotNone(called_kwargs.get("target_date"))
                    self.assertEqual(called_kwargs["target_date"].year, 2022)
                    self.assertEqual(called_kwargs["target_date"].month, 2)
        finally:
            db.close()

if __name__ == "__main__":
    unittest.main()
