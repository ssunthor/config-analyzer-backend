import logging
import time
import httpx
from app.core.config import settings
from app.services.vllm_service import call_vllm_api
from app.prompts import analysis_prompts
from app.utils.text_processing import chunk_text

logger = logging.getLogger(__name__)


async def analyze_configuration_files(files_content: str, framework: str) -> dict:
    """
    Performs a deep security analysis of configuration files.
    """
    total_start_time = time.time()
    logger.info(f"Starting analysis: framework={framework} input_len={len(files_content)} chars")

    extracted_content = files_content
    max_chars = 400000
    if len(extracted_content) > max_chars:
        logger.warning(
            f"Configuration is extremely large ({len(extracted_content)} chars) — "
            f"truncating to {max_chars} chars"
        )
        extracted_content = extracted_content[:max_chars] + "\n...[TRUNCATED DUE TO CONTEXT LIMITS]..."

    pass2_start = time.time()
    logger.info("Initiating deep security analysis pass")
    prompt = analysis_prompts.ANALYZE_CONFIG_PROMPT.format(framework=framework)
    prompt += f"\n\nConfiguration Files to Analyze:\n{extracted_content}\n"
    payload = {
        "model": settings.VLLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 8192,
    }
    try:
        response_json = await call_vllm_api(payload)
        pass2_elapsed = time.time() - pass2_start
        total_elapsed = time.time() - total_start_time
        logger.info(f"Analysis complete: pass={pass2_elapsed:.2f}s total={total_elapsed:.2f}s")
        return {"status": "completed", "analysis": response_json["choices"][0]["message"]["content"]}
    except Exception as e:
        details = getattr(e, 'response', {}).text if isinstance(e, httpx.HTTPStatusError) else ""
        logger.error(f"Analysis failed: {e}{' | ' + details if details else ''}")
        return {"status": "error", "message": f"{e} | Details: {details}"}
