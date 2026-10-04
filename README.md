# ReproLens

ReproLens is an AI-powered Machine Learning paper reproducibility platform. It automates the process of analyzing a research paper, extracting its claims and metrics, running the code from the associated GitHub repository in a sandboxed environment, and determining if the paper's claims are reproducible.

**Repository:** [https://github.com/Moksh1112/ReproLens.git](https://github.com/Moksh1112/ReproLens.git)

## 1. Overview

ReproLens addresses the ML reproducibility crisis by providing a deterministic, auditable, and automated reproducibility pipeline. 

Given an arXiv paper ID (or URL/PDF) and its source code repository, ReproLens:
- Parses the paper content and extracts quantifiable claims (experiments, metrics, values, split).
- Indexes the source repository to map extracted claims to executable scripts.
- Prepares a sandboxed, isolated environment using Docker.
- Executes the code safely and captures the runtime metrics.
- Normalizes and compares the extracted metrics against the paper's claims.
- Generates a final deterministic reproducibility verdict (Reproduced, Within noise, Partially reproduced, Not reproduced, Not testable).
- Discovers discrepancy causes when claims do not match the runtime metrics.
- Emits a comprehensive Markdown report and Repro Card.

## 2. Core Workflow

The ReproLens pipeline runs as a Celery-backed state machine with the following stages:

1. **Paper + Repository Input**: User submits a paper (arXiv ID/URL) and a GitHub repository URL via the frontend.
2. **Paper Parsing**: Downloads the arXiv PDF, uses PyMuPDF to extract text, and parses sections and dates.
3. **Claim Extraction**: Uses a Groq-hosted LLM (OpenAI-compatible) and Pydantic (Instructor) to extract structured claims, mapping each to a specific page and quote. This is chunk-processed with strict rate-limit handling.
4. **Repository Indexing**: Clones the GitHub repository and indexes its AST, Python files, and commit date.
5. **Claim-to-Experiment Mapping**: Currently a mock implementation mapping claims to an executable target in the repository. (P1: Full AST search)
6. **Environment Preparation**: Generates a Docker container and pins requirements for execution.
7. **Sandboxed Experiment Execution**: Runs the target script inside an isolated Docker container with strict CPU, RAM, PID, and network limits. Captures logs.
8. **Metric Extraction/Normalization**: Extracts the JSON-formatted metrics produced by the sandboxed run.
9. **Verdict Calculation**: Deterministically compares the runtime metric against the claimed metric with a configured tolerance.
10. **Discrepancy Diagnosis**: If a discrepancy is found, generates a ranked list of possible causes (e.g., missing seeds, hyperparameters).
11. **Audit**: Computes an audit state (clean/flagged) based on execution and parsing flags.
12. **Report Generation**: Emits a detailed `report.md` artifact. (PDF generation is deferred).
13. **Claim Graph**: Produces a node-edge schema of the reproducibility mapping.
14. **Repro Card**: Summarizes the coverage and final reproducibility score.

## 3. Implementation Phases / Workstreams

### Workstream 1 — Foundation + Shared Architecture
- Implemented backend foundation using FastAPI.
- Defined all artifact schemas in `backend/app/schemas/artifacts.py` using Pydantic.
- Implemented local SQLite database and `reprolens_storage` object storage paths.
- Setup `BaseStage` pattern for Celery execution.

### Workstream 2 — Frontend + User Workflow
- Built the Next.js frontend using Tailwind CSS.
- Implemented the upload flow, assessment dashboard, progress updates, logs, verdict, and discrepancy views.
- Includes a React Flow claim graph and Repro Card summary page.

### Workstream 3 — Backend + API + Job Infrastructure
- FastAPI routes in `backend/app/api/endpoints/assessments.py`.
- Celery orchestrator (`app.pipeline.orchestrator`) backing the pipeline execution.
- Redis handles Celery task brokering and backend.
- Assessment lifecycle state transitions are fully supported.

### Workstream 4 — Paper/Repo Intelligence + AI Agent
- Paper parsing implemented with `PyMuPDF` (`fitz`) and `pdfplumber`.
- arXiv paper fetching with built-in SSL support.
- Groq/OpenAI-compatible integration via the `instructor` library.
- Structured Claim Extraction returns `ClaimExtractionArtifact` containing precise quotes and pages.
- Large papers are chunked and cached. Rate limits are handled gracefully with a maximum wait time (fails cleanly if the wait exceeds 60 seconds).
- Repository Git date and basic Python file indexing is implemented.

### Workstream 5 — Environment + Sandbox + Experiment Execution
- Docker-based sandboxed execution implemented in `docker_manager.py`.
- Enforces strict security bounds: read-only mounts, network disabled (after setup), CPU/RAM/PID limits, timeout, and a non-root user.
- Emits `ExperimentRunArtifact` capturing stdout/stderr and parsed execution metrics.

### Workstream 6 — Comparison + Verdict + Discrepancy + Audit
- Deterministic, rule-based verdict logic (LLM is NOT used for final verdicts).
- Evaluates metrics within noise tolerances and assigns standard verdicts (Reproduced, Partially reproduced, Not reproduced, etc.).
- Generates `DiscrepancyDiagnosisArtifact` with ranked causes.
- Flags the pipeline in the `AuditChecklistArtifact` if execution is abnormal.

### Workstream 7 — Reporting + Claim Graph + Repro Card
- Aggregates results into a final `report.md` artifact.
- PDF generation using WeasyPrint is currently deferred (stubbed).
- Calculates the overall Repro Score and Coverage.

### Workstream 8 — Integration + Testing + Demo
- Integration tests cover all stages in `test_ws4.py`, `test_ws5.py`, `test_ws6.py`, `test_ws7.py`, and E2E in `test_ws8_integration.py`.
- Frontend builds cleanly and integrates directly with the FastAPI backend.

## 4. Architecture

```text
+-----------------------+      +-----------------------+
|   Frontend (Next.js)  | <--> |   Backend (FastAPI)   |
|   React, Tailwind     |      |   Uvicorn, Pydantic   |
+-----------------------+      +-----------------------+
                                           |
+-----------------------+      +-----------------------+
|   Redis (Broker)      | <--> |   Celery (Workers)    |
|   localhost:6379      |      |   Orchestrator        |
+-----------------------+      +-----------------------+
                                           |
+-----------------------+      +-----------------------+
|   Storage & DB        |      |   Execution Engine    |
|   SQLite, File System |      |   Docker Sandbox      |
+-----------------------+      +-----------------------+
```

## 5. Repository Structure

```text
ReproLens/
├── backend/                  # FastAPI & Celery Python backend
│   ├── app/                  # Application code
│   │   ├── api/              # FastAPI endpoints
│   │   ├── core/             # Configuration & Celery app
│   │   ├── db/               # SQLite database models
│   │   ├── execution/        # Docker Sandbox Manager
│   │   ├── intelligence/     # LLM integration, parsing, repo indexer
│   │   ├── pipeline/         # Celery tasks and Stage definitions
│   │   └── schemas/          # Pydantic data and artifact schemas
│   ├── tests/                # Pytest unit and integration tests
│   ├── requirements.txt      # Python dependencies
│   └── .env.example          # Example environment variables
├── frontend/                 # Next.js React frontend
│   ├── app/                  # Next.js App Router (Pages & Layout)
│   ├── components/           # Reusable UI and ClaimGraph
│   ├── lib/                  # API clients and contracts
│   ├── package.json          # Node dependencies
│   └── tailwind.config.ts    # Tailwind styles
├── reprolens_storage/        # Runtime storage for generated artifacts
├── .gitignore                # Global git ignore configuration
└── README.md                 # Project documentation (this file)
```

## 6. Technology Stack

| Category      | Technology       | Purpose                               |
|---------------|------------------|---------------------------------------|
| Frontend      | Next.js (14.x)   | App framework and routing             |
| Frontend      | React (18.x)     | UI components                         |
| Frontend      | Tailwind CSS     | Styling                               |
| Frontend      | React Flow       | Claim Graph visualization             |
| Backend       | FastAPI (0.104.1)| REST API                              |
| Backend       | Celery (5.3.6)   | Background job orchestration          |
| Backend DB    | SQLite           | Local metadata store                  |
| Messaging     | Redis (5.0.1)    | Celery Broker & Result Backend        |
| Intelligence  | PyMuPDF, OpenAI  | Paper Parsing and Groq LLM extraction |
| Execution     | Docker           | Sandboxed script execution            |

## 7. Prerequisites

### Required software
- **Git**
- **Python 3.11+**
- **Node.js (v18+)** and npm
- **Docker Desktop** (Must be running with Linux containers)
- **Redis**

### Required accounts/credentials
- **Groq API Key** (or an OpenAI-compatible API key for `instructor`)

## 8. Installation

### Step 1 — Clone repository
```bash
git clone https://github.com/Moksh1112/ReproLens.git
cd ReproLens
```

### Step 2 — Backend setup
```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
```

### Step 3 — Environment configuration
```bash
cp backend/.env.example backend/.env
```
Edit `backend/.env` and insert your API keys. Do **NOT** commit this file.
```env
# backend/.env
HOST=127.0.0.1
PORT=8000
GROQ_API_KEY=your_real_groq_api_key_here
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///./reprolens.db
STORAGE_BASE_DIR=./reprolens_storage
```

### Step 4 — Redis
If Redis is not installed on your host, you can run it via Docker:
```bash
docker run -d -p 6379:6379 redis
```

### Step 5 — Database
By default, the backend uses a local SQLite database (`reprolens.db`). No specific PostgreSQL setup is required for the local demo.

### Step 6 — Docker
Ensure Docker Desktop is running. Verify via:
```bash
docker info
```

### Step 7 — Frontend dependencies
```bash
cd ../frontend
npm install
```

## 9. Running ReproLens

Open 4 separate terminal windows.

**Terminal 1 — Redis (if using Docker)**
```bash
docker run -d -p 6379:6379 redis
```

**Terminal 2 — FastAPI Backend**
```bash
cd backend
# Activate venv
uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 3 — Celery Worker**
```bash
cd backend
# Activate venv
# Note: On Windows, use --pool=solo. On Linux/Mac, you can omit it.
celery -A app.core.celery_app worker --loglevel=info --pool=solo
```

**Terminal 4 — Next.js Frontend**
```bash
cd frontend
npm run dev
```

**Expected URLs:**
- Frontend: `http://localhost:3000`
- Backend API Docs (Swagger): `http://127.0.0.1:8000/docs`

## 10. First-Time Demo / Evaluator Walkthrough

1. Open `http://localhost:3000` in your browser.
2. Click **Start New Assessment**.
3. **Paper Input**: Enter an arXiv ID (e.g., `1803.03635`).
4. **Repository Input**: Enter a valid GitHub repository URL.
5. Click **Start Assessment**.
6. You will be redirected to the Assessment Dashboard.
7. Watch the Celery-backed stages progress in real-time (Paper Parsing → Claim Extraction → Repo Indexing...).
8. View the live execution logs during the Sandboxed Experiment Execution stage.
9. Inspect the **Verdict** and **Discrepancy** results.
10. Review the **Claim Graph** and final **Repro Card**.

## 11. API Endpoints

The API is mounted at `http://127.0.0.1:8000/api/v1`.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST   | `/assessments` | Create a new assessment with paper & repo URLs. Returns `assessment_id`. |
| POST   | `/assessments/{id}/run` | Triggers the asynchronous Celery pipeline execution. |
| GET    | `/assessments/{id}` | Retrieves the assessment status and current stages. |
| GET    | `/assessments/{id}/logs` | Retrieves real-time pipeline and Docker execution logs. |
| GET    | `/assessments/{id}/artifacts/{artifact_type}` | Fetches a specific JSON artifact generated by a stage. |

## 12. Configuration

Important configurable variables in `backend/.env`:
- `GROQ_API_KEY`: Required for LLM claim extraction.
- `STORAGE_BASE_DIR`: Path to save `reprolens_storage` artifacts.
- Docker Sandbox Limits: Configured directly in `docker_manager.py` (e.g., 1024MB RAM, network disabled after install).

## 13. Testing

### Backend Unit & Integration Tests
```bash
cd backend
# Activate venv
pytest tests/ -v
```
These tests cover parsing, extraction chunking, Docker generation, deterministic verdicts, discrepancy diagnosis, and a complete E2E pipeline mock (`test_ws8_integration.py`).

### Frontend Build
```bash
cd frontend
npm run build
```

## 14. Security / Sandbox Model

ReproLens protects the host machine from malicious or buggy repository code using Docker:
- **Non-root execution**: The container runs as an unprivileged user.
- **Read-only Filesystem**: The source repository is mounted read-only. Output is captured via stdout/stderr and a dedicated JSON metrics mount.
- **Network Isolation**: The network is disabled after `pip install` to prevent data exfiltration.
- **Resource Limits**: CPU/RAM (e.g., 1GB) and PID limits are strictly enforced.
- **Timeout**: The container will automatically be killed if it hangs.

## 15. Reproducibility Rules

Final verdicts are calculated deterministically by comparing the parsed `ClaimExtractionArtifact` (from the LLM) against the `ExperimentRunArtifact` (from Docker):

- **Reproduced**: Metric within configured noise tolerance (e.g., ±0.01).
- **Within noise**: Metric matches but with a loose statistical variance.
- **Partially reproduced**: Some metrics match, others do not.
- **Not reproduced**: Metrics significantly diverge.
- **Not testable**: Code crashed or no metrics were generated.

## 16. Artifacts

The system produces standard Pydantic models at the end of each stage. These are written to disk as JSON inside `reprolens_storage/{assessment_id}/`:
- `PaperDocumentArtifact.json`
- `ClaimExtractionArtifact.json`
- `RepositoryIndexArtifact.json`
- `ClaimMappingsArtifact.json`
- `EnvironmentArtifact.json`
- `ExperimentRunArtifact.json`
- `MetricAggregationArtifact.json`
- `VerdictArtifact.json`
- `DiscrepancyDiagnosisArtifact.json`
- `AuditChecklistArtifact.json`
- `ClaimGraphArtifact.json`
- `ReproCardArtifact.json`
- `ReportArtifact.json` (and `report.md`)

## 17. Known Limitations

- **PDF Generation**: WeasyPrint PDF generation is currently deferred (stubbed) in WS7. The Markdown report is fully functional.
- **Ast-based Claim Mapping**: WS4 claim-to-script mapping is using a basic implementation. Advanced AST fuzzy-search and alignment is deferred (P1).
- **LLM Rate Limits**: Large papers are chunk-processed. If Groq's retry-after limit exceeds 60 seconds, the pipeline currently intentionally fails to prevent hanging Celery workers for 15+ minutes. Cached successful chunks will be reused upon a retry.
- **Environment Repair**: P1 automatic environment dependency repair (e.g., fixing conflicting versions) is deferred.

## 18. Troubleshooting

- **Celery worker not starting (Windows)**: You must use the `--pool=solo` flag on Windows.
- **FastAPI database lock / missing tables**: Ensure you delete `reprolens.db` and let Alembic/SQLAlchemy recreate it if the schema changes.
- **Docker unavailable**: If WS5 fails immediately, ensure Docker Desktop is running and using Linux containers.
- **Frontend/Backend port mismatch**: The frontend makes API calls to `127.0.0.1:8000`. Do not run FastAPI on a different port without updating `frontend/lib/api/client.ts`.
- **Groq rate limits**: If the `ClaimExtractionStage` fails with a `RateLimitTooLongException`, wait a few minutes and click "Run" again. ReproLens caches successfully extracted chunks.

## 19. Development Workflow

- Backend changes require restarting Uvicorn and Celery.
- Always add new artifact schemas to `app/schemas/artifacts.py`.
- Do not commit `.env` or files inside `reprolens_storage/`.
- Run `pytest` locally before committing backend changes.

## 20. Current Project Status

| Workstream | Status | Notes |
|------------|--------|-------|
| WS1 (Foundation) | ✅ Implemented | Artifact schemas, SQLite DB, Storage API |
| WS2 (Frontend) | ✅ Implemented | Next.js Dashboard, Reports, Claim Graph |
| WS3 (Infrastructure) | ✅ Implemented | FastAPI, Celery, Redis Orchestration |
| WS4 (Intelligence) | ✅ Implemented | Groq LLM Extraction, Rate-limit Chunk Caching |
| WS5 (Sandbox) | ✅ Implemented | Docker Execution, Security Limits |
| WS6 (Verdict) | ✅ Implemented | Deterministic Metrics, Discrepancy Diagnosis |
| WS7 (Reporting) | ✅ Implemented | Markdown Report, Repro Card (PDF deferred) |
| WS8 (Integration) | ✅ Implemented | Complete E2E integration and tests |

## 21. Future / Deferred Work

- PDF rendering for reports (WeasyPrint).
- Advanced AST structural claim mapping.
- Automatic dependency resolution / environment repair.
- Support for distributed cloud execution beyond local Docker.

## 22. License / Credits

No license is currently specified for this repository.
