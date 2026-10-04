from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import uuid

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(String, primary_key=True, default=generate_uuid)
    paper_input_type = Column(String, nullable=False) # 'pdf' or 'arxiv'
    paper_source = Column(String, nullable=False)
    repository_input_type = Column(String, nullable=False) # 'github' or 'zip'
    repository_source = Column(String, nullable=False)
    status = Column(String, default="pending") # pending, running, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stage_runs = relationship("StageRun", back_populates="assessment")
    artifacts = relationship("Artifact", back_populates="assessment")

class StageRun(Base):
    __tablename__ = "stage_runs"

    id = Column(String, primary_key=True, default=generate_uuid)
    assessment_id = Column(String, ForeignKey("assessments.id"))
    stage_name = Column(String, nullable=False)
    status = Column(String, default="pending")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    
    input_artifact_ids = Column(JSON, default=list)
    output_artifact_ids = Column(JSON, default=list)

    assessment = relationship("Assessment", back_populates="stage_runs")

class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=generate_uuid)
    assessment_id = Column(String, ForeignKey("assessments.id"))
    stage = Column(String, nullable=False)
    type = Column(String, nullable=False) # e.g. PaperDocument, RepositorySnapshot
    object_path = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    assessment = relationship("Assessment", back_populates="artifacts")
