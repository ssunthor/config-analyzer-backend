import asyncio
import json
import logging
import re
import time
import httpx
from app.core.config import settings
from app.services.vllm_service import call_vllm_api
from app.prompts import analysis_prompts
from app.utils.text_processing import split_concatenated_files, chunk_config_text

logger = logging.getLogger(__name__)

ANALYSIS_MAX_TOKENS = 8192
# Conservative chars-per-token for config text (dense punctuation tokenizes
# poorly), plus headroom for the prompt template and chunk preamble.
CHARS_PER_TOKEN = 3
PROMPT_OVERHEAD_TOKENS = 2000


def _max_input_chars() -> int:
    """Largest config payload (in chars) that fits one LLM call, derived from
    the model context window unless CHUNK_SIZE explicitly overrides it."""
    if settings.CHUNK_SIZE > 0:
        return settings.CHUNK_SIZE
    budget_tokens = settings.LLM_NUM_CTX - ANALYSIS_MAX_TOKENS - PROMPT_OVERHEAD_TOKENS
    return max(budget_tokens, 1000) * CHARS_PER_TOKEN


def _parse_llm_json(raw: str):
    """Parses the model's JSON reply, tolerating markdown code fences."""
    text = raw.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _build_payload(prompt: str) -> dict:
    return {
        "model": settings.VLLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": ANALYSIS_MAX_TOKENS,
    }


async def _analyze_chunk(semaphore: asyncio.Semaphore, framework: str,
                         filename: str, part: int, total: int,
                         start_line: int, chunk: str):
    prompt = analysis_prompts.ANALYZE_CONFIG_PROMPT.format(framework=framework)
    prompt += analysis_prompts.CHUNK_CONTEXT_NOTE.format(
        part=part, total=total, filename=filename or "uploaded configuration")
    prompt += f"\nConfiguration Files to Analyze:\n--- File: {filename} ---\n{chunk}\n"
    async with semaphore:
        chunk_start = time.time()
        logger.info(f"Analyzing chunk {part}/{total} of '{filename}' ({len(chunk)} chars)")
        response_json = await call_vllm_api(_build_payload(prompt))
        logger.info(f"Chunk {part}/{total} of '{filename}' done in {time.time() - chunk_start:.2f}s")
    return response_json["choices"][0]["message"]["content"], start_line


def _merge_chunk_results(results, filename_by_index) -> dict:
    """Merges per-chunk JSON replies into the single object the frontend
    expects, re-offsetting line numbers and deduplicating."""
    merged = {"file_metadata": [], "issues": []}
    seen_files = set()
    seen_issues = set()
    parse_failures = 0

    for idx, (raw, start_line) in enumerate(results):
        parsed = _parse_llm_json(raw)
        if parsed is None:
            parse_failures += 1
            logger.warning(f"Chunk result {idx} was not valid JSON; skipping")
            continue

        filename = filename_by_index[idx]
        for meta in parsed.get("file_metadata", []):
            if not isinstance(meta, dict):
                continue
            meta.setdefault("file", filename)
            if meta["file"] not in seen_files:
                seen_files.add(meta["file"])
                merged["file_metadata"].append(meta)

        for issue in parsed.get("issues", []):
            if not isinstance(issue, dict):
                continue
            issue.setdefault("file", filename)
            if isinstance(issue.get("line"), int):
                issue["line"] = issue["line"] + start_line - 1
            key = (issue.get("file"), issue.get("line"), issue.get("title"))
            if key in seen_issues:
                continue
            seen_issues.add(key)
            issue["id"] = f"vuln-{len(merged['issues']) + 1:03d}"
            merged["issues"].append(issue)

    if parse_failures:
        logger.warning(f"{parse_failures}/{len(results)} chunk results failed to parse")
    return merged


async def analyze_configuration_files(files_content: str, framework: str) -> dict:
    """
    Performs a deep security analysis of configuration files. Inputs that fit
    the model context window are analyzed in a single call; larger inputs are
    split per file at config-section boundaries, analyzed concurrently, and
    the structured results are merged back into one report.
    """
    total_start_time = time.time()
    max_chars = _max_input_chars()
    logger.info(
        f"Starting analysis: framework={framework} input_len={len(files_content)} chars "
        f"single_call_budget={max_chars} chars"
    )

    try:
        if len(files_content) <= max_chars:
            logger.info("Input fits context window; single analysis pass")
            prompt = analysis_prompts.ANALYZE_CONFIG_PROMPT.format(framework=framework)
            prompt += f"\n\nConfiguration Files to Analyze:\n{files_content}\n"
            response_json = await call_vllm_api(_build_payload(prompt))
            analysis = response_json["choices"][0]["message"]["content"]
        else:
            tasks = []
            filename_by_index = []
            semaphore = asyncio.Semaphore(settings.CONCURRENT_REQUESTS)
            for filename, file_text in split_concatenated_files(files_content):
                chunks = chunk_config_text(file_text, max_chars)
                logger.info(f"File '{filename}': {len(file_text)} chars -> {len(chunks)} chunk(s)")
                for part, (start_line, chunk) in enumerate(chunks, start=1):
                    filename_by_index.append(filename)
                    tasks.append(_analyze_chunk(
                        semaphore, framework, filename, part, len(chunks), start_line, chunk))

            logger.info(f"Input exceeds context window; analyzing {len(tasks)} chunks "
                        f"(concurrency={settings.CONCURRENT_REQUESTS})")
            results = await asyncio.gather(*tasks)
            merged = _merge_chunk_results(results, filename_by_index)
            if not merged["file_metadata"] and not merged["issues"]:
                return {"status": "error",
                        "message": "No chunk produced a parseable analysis result"}
            analysis = json.dumps(merged)

        logger.info(f"Analysis complete: total={time.time() - total_start_time:.2f}s")
        return {"status": "completed", "analysis": analysis}
    except Exception as e:
        details = getattr(e, 'response', {}).text if isinstance(e, httpx.HTTPStatusError) else ""
        logger.error(f"Analysis failed: {e}{' | ' + details if details else ''}")
        return {"status": "error", "message": f"{e} | Details: {details}"}
