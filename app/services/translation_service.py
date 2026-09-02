import asyncio
import logging
import re
import time
import httpx
from app.core.config import settings
from app.services.vllm_service import call_vllm_api
from app.prompts import translation_prompts
from app.utils.text_processing import chunk_config_text

logger = logging.getLogger(__name__)

PROMPT_OVERHEAD_TOKENS = 2000
MIN_OUTPUT_TOKENS = 8192


def _est_tokens(chars: int) -> int:
    """Deliberately high token estimate (2.5 chars/token): base64 blobs and
    dense config text tokenize at ~3 chars/token, and a 1-token miss is a
    hard 400 from vLLM."""
    return chars * 2 // 5


def _max_chunk_chars() -> int:
    """Largest source-config chunk (in chars) that can be translated in one
    call. Unlike analysis, the output is roughly as large as the input, so
    the context window must hold the prompt AND a same-sized translation."""
    budget_tokens = settings.LLM_NUM_CTX - PROMPT_OVERHEAD_TOKENS
    return budget_tokens * 5 // 4  # input + equal-sized output, at 2.5 chars/token


def _output_budget(chunk_len: int) -> int:
    """max_tokens for a chunk: whatever the context window still allows after
    the prompt, never less than the historical 8192 floor."""
    input_tokens = _est_tokens(chunk_len) + PROMPT_OVERHEAD_TOKENS
    return max(settings.LLM_NUM_CTX - input_tokens, MIN_OUTPUT_TOKENS)


def _strip_fences(text: str) -> str:
    """Removes markdown fence-marker lines anywhere in the reply (each chunk
    tends to wrap its own output in a fresh fence)."""
    lines = [l for l in text.strip().split('\n') if not re.fullmatch(r'```[a-zA-Z]*\s*', l)]
    return '\n'.join(lines).strip()


async def _translate_chunk(semaphore: asyncio.Semaphore, target_vendor: str,
                           chunk: str, part: int, total: int) -> str:
    prompt = translation_prompts.TRANSLATE_CONFIG_PROMPT.format(
        target_vendor=target_vendor,
        vendor_specific_rules=translation_prompts.get_vendor_rules(target_vendor),
        source_config=chunk
    )
    if total > 1:
        prompt = translation_prompts.TRANSLATE_CHUNK_NOTE.format(part=part, total=total) + prompt
    payload = {
        "model": settings.VLLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": _output_budget(len(chunk)),
    }
    async with semaphore:
        chunk_start = time.time()
        logger.info(f"Translating chunk {part}/{total} ({len(chunk)} chars, "
                    f"max_tokens={payload['max_tokens']})")
        response_json = await call_vllm_api(payload)
        logger.info(f"Chunk {part}/{total} translated in {time.time() - chunk_start:.2f}s")
    return _strip_fences(response_json["choices"][0]["message"]["content"])


async def translate_configuration_file(file_content: str, target_vendor: str) -> dict:
    """
    Translates a configuration file to a target vendor's format. Files that
    exceed the model context window are split at top-level config-section
    boundaries, translated concurrently, and the translated parts are
    concatenated in source order.
    """
    total_start = time.time()
    max_chars = _max_chunk_chars()
    logger.info(f"Starting translation: target_vendor={target_vendor} "
                f"input_len={len(file_content)} chars chunk_budget={max_chars} chars")
    try:
        if len(file_content) <= max_chars:
            chunks = [(1, file_content)]
        else:
            chunks = chunk_config_text(file_content, max_chars)
            logger.info(f"Input exceeds context window; translating {len(chunks)} chunks "
                        f"(concurrency={settings.CONCURRENT_REQUESTS})")

        semaphore = asyncio.Semaphore(settings.CONCURRENT_REQUESTS)
        parts = await asyncio.gather(*[
            _translate_chunk(semaphore, target_vendor, chunk, part, len(chunks))
            for part, (_, chunk) in enumerate(chunks, start=1)
        ])
        translated = "\n\n".join(parts) if len(parts) > 1 else parts[0]
        logger.info(f"Translation complete: target_vendor={target_vendor} "
                    f"chunks={len(chunks)} total={time.time() - total_start:.2f}s")
        return {"status": "completed", "translated_config": translated}
    except Exception as e:
        details = getattr(e, 'response', {}).text if isinstance(e, httpx.HTTPStatusError) else ""
        logger.error(f"Translation failed: {e}{' | ' + details if details else ''}")
        return {"status": "error", "message": f"{e} | Details: {details}"}
