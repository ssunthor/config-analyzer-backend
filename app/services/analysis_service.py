import time
import asyncio
import httpx
from app.core.config import settings
from app.services.vllm_service import call_vllm_api
from app.prompts import analysis_prompts
from app.utils.text_processing import chunk_text

async def analyze_configuration_files(files_content: str, framework: str) -> dict:
    """
    Performs a deep security analysis of configuration files.
    """
    total_start_time = time.time()
    print(f"Starting analysis. Text length: {len(files_content)} chars.")

    # --- PASS 1: PARALLEL EXTRACTION & FILTERING (Bypassed due to 128k context window) ---
    extracted_content = files_content

    # Limit to roughly 120k characters to be safe for a 128k token window
    # (assuming ~1 token per 3-4 characters)
    max_chars = 400000 
    if len(extracted_content) > max_chars:
        print(f"Warning: Configuration is extremely large ({len(extracted_content)} chars). Truncating to fit within large context window limits.")
        extracted_content = extracted_content[:max_chars] + "\n...[TRUNCATED DUE TO CONTEXT LIMITS]..."

    # --- PASS 2: DEEP SECURITY ANALYSIS ---
    pass2_start = time.time()
    print("Initiating Deep Security Analysis.")
    prompt = analysis_prompts.ANALYZE_CONFIG_PROMPT.format(framework=framework)
    prompt += f"\n\nConfiguration Files to Analyze:\n{extracted_content}\n"
    payload = {
        "model": settings.MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 8192,
    }
    try:
        # Increase timeout significantly for large context window queries
        response_json = await call_vllm_api(payload)
        print(f"Pass 2 complete in {time.time() - pass2_start:.2f}s.")
        print(f"Total pipeline finished in {time.time() - total_start_time:.2f}s.")
        return {"status": "completed", "analysis": response_json["choices"][0]["message"]["content"]}
    except Exception as e:
        details = getattr(e, 'response', {}).text if isinstance(e, httpx.HTTPStatusError) else ""
        print(f"Pass 2 failed: {e}")
        return {"status": "error", "message": f"{e} | Details: {details}"}
