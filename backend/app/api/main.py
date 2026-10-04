from fastapi import FastAPI
from app.core.config import settings
from app.api.endpoints import assessments
from app.db.session import engine
from app.db.models import Base

# Create tables for demonstration/foundation purposes
Base.metadata.create_all(bind=engine)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assessments.router, prefix=f"{settings.API_V1_STR}/assessments", tags=["assessments"])

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "ReproLens API Foundation is running"}
