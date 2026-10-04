import os
from dotenv import load_dotenv

# Ensure the backend/.env is loaded for tests (e.g., GROQ_API_KEY)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
