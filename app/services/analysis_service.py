import time
import asyncio
import httpx
from app.core.config import settings
from app.services.vllm_service import call_vllm_api
from app.prompts import analysis_prompts
from app.utils.text_processing import chunk_text

async def extract_chunk_parallel(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, chunk: str, idx: int, total: int) -> str:
    """
    Helper function to extract security rules from a chunk with concurrency.
    """
    async with semaphore:
        print(f"  [Pass 1] Processing chunk {idx + 1}/{total}...")
        prompt = f"""{analysis_prompts.EXTRACT_CONFIG_PROMPT}

Raw Text Chunk:
{chunk}
"""
        payload = {
            "model": settings.MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 8192,
        }
        
        try:
            response_json = await call_vllm_api(payload, client=client)
            return response_json["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Extraction chunk {idx+1} failed: {e}")
            return ""


async def analyze_configuration_files(files_content: str, framework: str) -> dict:
    """
    Performs a deep security analysis of configuration files.
    """
    total_start_time = time.time()
    print(f"Starting analysis. Text length: {len(files_content)} chars.")

    # --- PASS 1: PARALLEL EXTRACTION & FILTERING ---
    extracted_content = files_content
    if len(files_content) > settings.CHUNK_SIZE:
        pass1_start = time.time()
        print(f"File exceeds {settings.CHUNK_SIZE} chars, starting parallel extraction.")
        chunks = chunk_text(files_content, settings.CHUNK_SIZE)
        semaphore = asyncio.Semaphore(settings.CONCURRENT_REQUESTS)
        async with httpx.AsyncClient(timeout=300.0, verify=False) as client:
            tasks = [extract_chunk_parallel(client, semaphore, chunk, i, len(chunks)) for i, chunk in enumerate(chunks)]
            results = await asyncio.gather(*tasks)
            extracted_content = "\n\n".join(filter(None, results))
        print(f"Pass 1 complete in {time.time() - pass1_start:.2f}s. Reduced to {len(extracted_content)} chars.")

    # --- PASS 2: DEEP SECURITY ANALYSIS ---
    pass2_start = time.time()
    print("Initiating Pass 2: Deep Security Analysis.")
    prompt = analysis_prompts.ANALYZE_CONFIG_PROMPT.format(framework=framework)
    prompt += f"\n\nConfiguration Files to Analyze:\n{extracted_content}\n"
    payload = {
        "model": settings.MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 8192,
    }
    try:
        response_json = await call_vllm_api(payload)
        print(f"Pass 2 complete in {time.time() - pass2_start:.2f}s.")
        print(f"Total pipeline finished in {time.time() - total_start_time:.2f}s.")
        return {"status": "completed", "analysis": response_json["choices"][0]["message"]["content"]}
    except Exception as e:
        details = getattr(e, 'response', {}).text if isinstance(e, httpx.HTTPStatusError) else ""
        print(f"Pass 2 failed: {e}")
        return {"status": "error", "message": f"{e} | Details: {details}"}
