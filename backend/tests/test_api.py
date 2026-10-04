import os
import sys

# Add backend to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Override database URL to use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.db.models import Base
from app.api.main import app
from app.db.session import get_db
import tempfile
from app.core.config import settings

from sqlalchemy.pool import StaticPool

# Setup isolated storage and db for testing
test_storage_dir = tempfile.mkdtemp()
settings.STORAGE_DIR = test_storage_dir

engine = create_engine(
    os.environ["DATABASE_URL"], 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
Base.metadata.create_all(bind=engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

# 1. Assessment Creation and Retrieval
def test_create_and_get_assessment():
    response = client.post("/api/v1/assessments/", json={
        "paper_input_type": "none",
        "paper_source": "none",
        "repository_input_type": "none",
        "repository_source": "none"
    })
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"
    
    assessment_id = data["id"]
    
    res_get = client.get(f"/api/v1/assessments/{assessment_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == assessment_id

# Port Consistency Validation
def test_port_consistency():
    import json
    
    # 1. Frontend dev port is 3000
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
    package_json_path = os.path.join(frontend_dir, "package.json")
    with open(package_json_path, "r") as f:
        pkg = json.load(f)
    assert pkg["scripts"]["dev"] == "next dev -p 3000", "Frontend must explicitly use port 3000"
    
    # 2. Frontend API base is 127.0.0.1:8000
    client_ts_path = os.path.join(frontend_dir, "lib", "api", "client.ts")
    with open(client_ts_path, "r") as f:
        client_ts_content = f.read()
    assert "'http://127.0.0.1:8000/api/v1'" in client_ts_content, "Frontend API_BASE must point to 127.0.0.1:8000"
    assert "3001" not in client_ts_content, "No production code should depend on 3001"
    
    # 3. CORS includes exactly localhost:3000
    # We can check CORS via the TestClient by sending an OPTIONS request
    res_3000 = client.options("/api/v1/assessments/", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST"
    })
    assert res_3000.status_code == 200
    assert res_3000.headers.get("access-control-allow-origin") == "http://localhost:3000"
    
    res_3001 = client.options("/api/v1/assessments/", headers={
        "Origin": "http://localhost:3001",
        "Access-Control-Request-Method": "POST"
    })
    # CORS middleware will either return 400 or not set the allow-origin header for disallowed origins
    assert res_3001.headers.get("access-control-allow-origin") != "http://localhost:3001"

# 2. Source Submission
def test_submit_source():
    # Create
    res_create = client.post("/api/v1/assessments/", json={
        "paper_input_type": "none",
        "paper_source": "none",
        "repository_input_type": "none",
        "repository_source": "none"
    })
    assessment_id = res_create.json()["id"]
    
    # Submit Paper
    res_paper = client.post(f"/api/v1/assessments/{assessment_id}/sources", json={
        "source_type": "paper",
        "input_type": "arxiv",
        "source": "1803.03635"
    })
    assert res_paper.status_code == 200
    assert res_paper.json()["paper_source"] == "1803.03635"
    
    # Submit Repo
    res_repo = client.post(f"/api/v1/assessments/{assessment_id}/sources", json={
        "source_type": "repository",
        "input_type": "github",
        "source": "https://github.com/google/repo"
    })
    assert res_repo.status_code == 200
    assert res_repo.json()["repository_source"] == "https://github.com/google/repo"

# 3. Assessment Run Endpoint
def test_run_assessment_endpoint():
    res_create = client.post("/api/v1/assessments/", json={
        "paper_input_type": "none",
        "paper_source": "none",
        "repository_input_type": "none",
        "repository_source": "none"
    })
    assessment_id = res_create.json()["id"]

    import unittest.mock as mock
    with mock.patch("app.pipeline.orchestrator.run_pipeline.delay") as mock_delay:
        mock_delay.return_value.id = "mock_task_id"
        res_run = client.post(f"/api/v1/assessments/{assessment_id}/run")
        
        assert res_run.status_code == 200
        assert res_run.json()["task_id"] == "mock_task_id"
        
        # Verify that run_pipeline.delay was called with the assessment_id
        mock_delay.assert_called_once_with(assessment_id)
        
    db = TestingSessionLocal()
    from app.db.models import Assessment
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    assert a.status == "queued"
    db.close()

# 4. Pipeline Run / Idempotency Test via Orchestrator
def test_orchestration_idempotency():
    res_create = client.post("/api/v1/assessments/", json={
        "paper_input_type": "none",
        "paper_source": "none",
        "repository_input_type": "none",
        "repository_source": "none"
    })
    assessment_id = res_create.json()["id"]
    
    from app.pipeline.orchestrator import REGISTERED_STAGES, run_pipeline
    from tests.test_foundation import MockIngestionStage
    import unittest.mock as mock
    
    # Register the mock stage for WS3 testing
    REGISTERED_STAGES.clear()
    stage = MockIngestionStage()
    REGISTERED_STAGES.append(stage)
    
    with mock.patch("app.pipeline.orchestrator.SessionLocal", TestingSessionLocal), \
         mock.patch("app.db.session.SessionLocal", TestingSessionLocal):
        # Instead of client.post("/api/v1/assessments/{assessment_id}/run") which invokes Celery via delay(),
        # we directly call the synchronous worker function to simulate Celery running the task inline.
        # This avoids needing a real Redis instance in the tests.
        
        run_pipeline(assessment_id)
    
    # Verify DB status
    db = TestingSessionLocal()
    from app.db.models import Assessment, StageRun
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    assert a.status == "completed"
    
    runs = db.query(StageRun).filter(StageRun.assessment_id == assessment_id).all()
    assert len(runs) == 1
    assert runs[0].stage_name == "mock_ingestion_stage"
    assert runs[0].status == "completed"
    
    # Rerun the pipeline to test idempotency (should skip)
    with mock.patch("app.pipeline.orchestrator.SessionLocal", TestingSessionLocal), \
         mock.patch("app.db.session.SessionLocal", TestingSessionLocal):
        run_pipeline(assessment_id)
    runs_after = db.query(StageRun).filter(StageRun.assessment_id == assessment_id).all()
    # Number of runs should still be 1 because the orchestrator checks existing successful runs
    assert len(runs_after) == 1
    
    # 4. Check Progress / Stages API
    res_progress = client.get(f"/api/v1/assessments/{assessment_id}/progress")
    assert res_progress.status_code == 200
    assert len(res_progress.json()) == 1
    
    res_stages = client.get(f"/api/v1/assessments/{assessment_id}/stages")
    assert res_stages.status_code == 200
    assert res_stages.json()[0]["stage_name"] == "mock_ingestion_stage"
    
    res_artifacts = client.get(f"/api/v1/assessments/{assessment_id}/artifacts")
    assert res_artifacts.status_code == 200
    assert len(res_artifacts.json()) == 1
    assert res_artifacts.json()[0]["type"] == "PaperDocumentArtifact"
    assert "data" in res_artifacts.json()[0]

    REGISTERED_STAGES.clear()

def test_logs_api():
    # 1. Unknown assessment
    res_404 = client.get("/api/v1/assessments/unknown-123/logs")
    assert res_404.status_code == 404
    
    # 2. No logs
    res_create = client.post("/api/v1/assessments/", json={
        "paper_input_type": "none",
        "paper_source": "none",
        "repository_input_type": "none",
        "repository_source": "none"
    })
    assessment_id = res_create.json()["id"]
    
    res_empty = client.get(f"/api/v1/assessments/{assessment_id}/logs")
    assert res_empty.status_code == 200
    assert "logs" in res_empty.json()
    assert len(res_empty.json()["logs"]) == 0
    
    # 3. Valid logs after running
    from app.pipeline.orchestrator import REGISTERED_STAGES, run_pipeline
    from tests.test_foundation import MockIngestionStage
    import unittest.mock as mock
    
    REGISTERED_STAGES.clear()
    stage = MockIngestionStage()
    REGISTERED_STAGES.append(stage)
    
    with mock.patch("app.pipeline.orchestrator.SessionLocal", TestingSessionLocal), \
         mock.patch("app.db.session.SessionLocal", TestingSessionLocal):
        run_pipeline(assessment_id)
        
    res_logs = client.get(f"/api/v1/assessments/{assessment_id}/logs")
    assert res_logs.status_code == 200
    logs = res_logs.json()["logs"]
    assert len(logs) > 0
    assert logs[0]["level"] == "INFO"
    
    REGISTERED_STAGES.clear()
    
def test_ws7_api_routes():
    res_create = client.post("/api/v1/assessments/", json={
        "paper_input_type": "none",
        "paper_source": "none",
        "repository_input_type": "none",
        "repository_source": "none"
    })
    assessment_id = res_create.json()["id"]
    
    db = TestingSessionLocal()
    from app.db.models import Artifact
    import json
    
    # Insert WS7 artifacts
    db.add(Artifact(assessment_id=assessment_id, stage="report_generation", type="ReportArtifact", object_path=f"{assessment_id}/report.json", content_hash="1"))
    db.add(Artifact(assessment_id=assessment_id, stage="graph_generation", type="ClaimGraphArtifact", object_path=f"{assessment_id}/graph.json", content_hash="2"))
    db.add(Artifact(assessment_id=assessment_id, stage="repro_card_generation", type="ReproCardArtifact", object_path=f"{assessment_id}/card.json", content_hash="3"))
    db.commit()
    
    from app.storage.object_store import ObjectStore
    import unittest.mock as mock
    
    original_load = ObjectStore.load
    def mock_load(path):
        if path == f"{assessment_id}/report.json":
            return {"markdown_path": f"{assessment_id}/report.md", "pdf_path": f"{assessment_id}/report.pdf"}
        elif path == f"{assessment_id}/graph.json":
            return {"nodes": [], "edges": []}
        elif path == f"{assessment_id}/card.json":
            return {"assessment_id": assessment_id, "paper_title": "Fake Title", "environment_lockfile": "reqs", "top_discrepancies": [], "repro_score": 100.0, "coverage": 1.0}
        return original_load(path)
        
    # Write the fake files to disk so FileResponse finds them
    import os
    os.makedirs(os.path.join(settings.STORAGE_DIR, assessment_id), exist_ok=True)
    with open(os.path.join(settings.STORAGE_DIR, assessment_id, "report.md"), "wb") as f:
        f.write(b"# Report MD")
    with open(os.path.join(settings.STORAGE_DIR, assessment_id, "report.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 Fake")
        
    with mock.patch("app.api.endpoints.assessments.ObjectStore.load", side_effect=mock_load):
         
        # test report metadata
        res = client.get(f"/api/v1/assessments/{assessment_id}/report")
        assert res.status_code == 200
        assert "markdown_path" in res.json()
        
        # test markdown
        res_md = client.get(f"/api/v1/assessments/{assessment_id}/report/markdown")
        assert res_md.status_code == 200
        assert res_md.content == b"# Report MD"
        
        # test pdf
        res_pdf = client.get(f"/api/v1/assessments/{assessment_id}/report/pdf")
        assert res_pdf.status_code == 200
        assert res_pdf.content == b"%PDF-1.4 Fake"
        
        # test graph
        res_graph = client.get(f"/api/v1/assessments/{assessment_id}/graph")
        assert res_graph.status_code == 200
        assert "nodes" in res_graph.json()
        
        # test repro card
        res_card = client.get(f"/api/v1/assessments/{assessment_id}/repro-card")
        assert res_card.status_code == 200
        card_data = res_card.json()
        assert "paper_title" in card_data
        assert "repro_score" in card_data
        assert "coverage" in card_data

def test_cors_preflight():
    """Verify CORS preflight accepts requests from local frontend."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type",
    }
    res = client.options("/api/v1/assessments/", headers=headers)
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in res.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" in res.headers

def test_celery_task_registration():
    """Verify importing Celery app registers run_pipeline and it exposes the task."""
    from app.core.celery_app import celery_app
    
    # 1. The task should be registered in celery_app.tasks
    task_name = "app.pipeline.orchestrator.run_pipeline"
    assert task_name in celery_app.tasks, f"Task {task_name} is not registered in Celery app."
    
    # 2. We should be able to call .delay without error
    task = celery_app.tasks[task_name]
    assert hasattr(task, "delay"), "Task does not have a 'delay' method."
    try:
        # Enqueue with a dummy ID to verify it doesn't error out
        task.delay("test-assessment-id-123")
    except Exception as e:
        import pytest
        pytest.fail(f"Calling .delay() raised an error: {e}")

# Run them directly for quick execution without pytest CLI
if __name__ == "__main__":
    test_create_and_get_assessment()
    print("✅ test_create_and_get_assessment passed")
    test_submit_source()
    print("✅ test_submit_source passed")
    test_orchestration_idempotency()
    print("✅ test_orchestration_idempotency passed")
    test_logs_api()
    print("✅ test_logs_api passed")
    test_ws7_api_routes()
    print("✅ test_ws7_api_routes passed")
    test_cors_preflight()
    print("✅ test_cors_preflight passed")
    print("🚀 ALL VALIDATIONS PASSED")
