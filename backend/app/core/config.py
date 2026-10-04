from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "ReproLens"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost/reprolens"
    
    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Object Storage (Local for now)
    STORAGE_DIR: str = "./reprolens_storage"
    
    # LLM Provider
    GROQ_API_KEY: str | None = None
    LLM_MODEL: str = "openai/gpt-oss-120b"

    class Config:
        env_file = ".env"

settings = Settings()
