try:
    import openai
    import instructor
except ImportError:
    openai = None
    instructor = None
from typing import Type, Any, Optional
from pydantic import BaseModel
import hashlib
import json
import os

# Using a simple in-memory cache for paper extraction during tests/runs to satisfy F1 cache requirement.
# In a real environment, this might be Redis or Postgres.
_LLM_CACHE = {}

def get_llm_client():
    from app.core.config import settings
    # Fallback for testing when GROQ_API_KEY is not set
    api_key = settings.GROQ_API_KEY if settings.GROQ_API_KEY else "dummy_key_for_testing"
    
    # Configure instructor to use OpenAI client connected to Groq
    if openai is None or instructor is None:
        raise ImportError("openai and instructor are required")
        
    client = instructor.from_openai(openai.OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
        max_retries=5
    ))
    return client

class RateLimitTooLongException(Exception):
    pass

def generate_structured_extraction(
    prompt: str,
    response_model: Type[BaseModel],
    cache_key: Optional[str] = None
) -> Any:
    """
    Calls the LLM to extract information matching the response_model schema.
    If cache_key is provided, uses caching to prevent repeated identical LLM calls.
    """
    if cache_key and cache_key in _LLM_CACHE:
        # Deserialize from dict back to model
        return response_model(**_LLM_CACHE[cache_key])
        
    client = get_llm_client()
    
    # Actually call the LLM
    from app.core.config import settings
    import openai
    import time
    import re
    import logging
    
    max_api_retries = 10
    for attempt in range(max_api_retries):
        try:
            response = client.chat.completions.create(
                model=settings.LLM_MODEL,
                response_model=response_model,
                max_retries=3,
                messages=[
                    {"role": "system", "content": "You are a precise extraction assistant. You only extract facts backed by the provided text. Never invent information. Strictly output valid JSON matching the schema."},
                    {"role": "user", "content": prompt}
                ]
            )
            break
        except Exception as e:
            err_str = str(e)
            if "Rate limit" in err_str or "rate_limit" in err_str or "429" in err_str:
                if attempt == max_api_retries - 1:
                    raise
                wait_time = 60
                match = re.search(r'try again in (\d+)m(\d+(?:\.\d+)?)s', err_str)
                if match:
                    m = int(match.group(1))
                    s = float(match.group(2))
                    wait_time = m * 60 + s + 2
                else:
                    match_s = re.search(r'try again in (\d+(?:\.\d+)?)s', err_str)
                    if match_s:
                        wait_time = float(match_s.group(1)) + 2
                
                if wait_time > 60:
                    logging.warning(f"Rate limit delay {wait_time}s is too long. Failing extraction cleanly.")
                    raise RateLimitTooLongException(f"Rate limit reached. Required wait is {wait_time} seconds, which exceeds the threshold.")
                    
                logging.warning(f"Rate limit reached. Waiting for {wait_time} seconds before retrying...")
                time.sleep(wait_time)
            else:
                raise
            
    if cache_key:
        _LLM_CACHE[cache_key] = response.model_dump()
        
    return response

import time

def extract_claims(sections: list, content_hash: str):
    from app.schemas.artifacts import ClaimExtractionArtifact, ClaimData, ExperimentSettings
    
    cache_key = f"claims_{content_hash}"
    if cache_key in _LLM_CACHE:
        return ClaimExtractionArtifact(**_LLM_CACHE[cache_key])
        
    all_claims = {}
    final_settings = ExperimentSettings(evidence={})
    
    chunks = []
    current_chunk = ""
    current_length = 0
    MAX_CHARS = 8000 # Roughly 2000 tokens to comfortably stay under 8000 TPM with pacing
    
    for sec in sections:
        title = sec.get("title", "")
        text = sec.get("text", "")
        page = sec.get("page", 1)
        
        # If the section text itself is too large, we split it by paragraphs/newlines
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            para_text = f"--- Title: {title} | Page: {page} ---\n{para.strip()}\n\n"
            if current_length + len(para_text) > MAX_CHARS and current_chunk:
                chunks.append(current_chunk)
                current_chunk = para_text
                current_length = len(para_text)
            else:
                current_chunk += para_text
                current_length += len(para_text)
                
    if current_chunk:
        chunks.append(current_chunk)
        
    for i, chunk_text in enumerate(chunks):
        chunk_cache_key = f"{cache_key}_chunk_{i}"
        
        prompt = (
            f"Extract experiment claims and settings from the following text portion (Part {i+1} of {len(chunks)}):\n"
            f"You MUST strictly adhere to the ClaimExtractionArtifact schema.\n"
            f"- Every claim MUST include 'claim_id', 'experiment', 'dataset', 'metric', 'value' (MUST be a number, not a string), 'page', and 'evidence'.\n"
            f"- 'evidence' for a claim MUST be a dictionary where each key is a string and the value is exactly: {{\"quote\": \"...\", \"page\": <int>}}.\n"
            f"- 'settings.evidence' MUST ALSO be a dictionary where each key is a string and the value is exactly: {{\"quote\": \"...\", \"page\": <int>}}.\n"
            f"- Missing values must remain null in JSON, do NOT omit them.\n\n"
            f"{chunk_text}"
        )
        
        if i > 0 and chunk_cache_key not in _LLM_CACHE:
            time.sleep(25)  # increased pacing to 25s to avoid 429
            
        chunk_result = generate_structured_extraction(
            prompt=prompt,
            response_model=ClaimExtractionArtifact,
            cache_key=chunk_cache_key
        )
            
        for claim in chunk_result.claims:
            key = f"{claim.experiment}_{claim.dataset}_{claim.split}_{claim.metric}"
            if key not in all_claims:
                all_claims[key] = claim
                
        if chunk_result.settings.hyperparameters and not final_settings.hyperparameters:
            final_settings.hyperparameters = chunk_result.settings.hyperparameters
        if chunk_result.settings.epochs and not final_settings.epochs:
            final_settings.epochs = chunk_result.settings.epochs
        if chunk_result.settings.seeds and not final_settings.seeds:
            final_settings.seeds = chunk_result.settings.seeds
        if chunk_result.settings.preprocessing and not final_settings.preprocessing:
            final_settings.preprocessing = chunk_result.settings.preprocessing
        if chunk_result.settings.hardware and not final_settings.hardware:
            final_settings.hardware = chunk_result.settings.hardware
            
        for k, v in chunk_result.settings.evidence.items():
            if k not in final_settings.evidence:
                final_settings.evidence[k] = v

    final_artifact = ClaimExtractionArtifact(
        assessment_id="",
        claims=list(all_claims.values()),
        settings=final_settings
    )
    
    _LLM_CACHE[cache_key] = final_artifact.model_dump()
    return final_artifact

def map_claims_to_repo(claims: list, repo_index: dict):
    from app.schemas.artifacts import ClaimMappingsArtifact
    
    claims_json = json.dumps(claims)
    repo_json = json.dumps(repo_index)
    
    prompt = f"Map the following claims to the repository configurations:\\nClaims:\\n{claims_json}\\n\\nRepository Index:\\n{repo_json}"
    # Calculate a hash for the combined input for caching
    cache_str = claims_json + repo_json
    cache_key = "mapping_" + hashlib.sha256(cache_str.encode('utf-8')).hexdigest()
    
    return generate_structured_extraction(
        prompt=prompt,
        response_model=ClaimMappingsArtifact,
        cache_key=cache_key
    )
