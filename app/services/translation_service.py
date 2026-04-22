import httpx
from app.core.config import settings
from app.services.vllm_service import call_vllm_api
from app.prompts import translation_prompts

async def translate_configuration_file(file_content: str, target_vendor: str) -> dict:
    """
    Translates a configuration file to a target vendor's format.
    """
    print(f"Starting translation to {target_vendor}. Length: {len(file_content)} chars.")
    prompt = translation_prompts.TRANSLATE_CONFIG_PROMPT.format(
        target_vendor=target_vendor,
        source_config=file_content
    )
    payload = {
        "model": settings.MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 8192,
    }
    try:
        response_json = await call_vllm_api(payload)
        return {"status": "completed", "translated_config": response_json["choices"][0]["message"]["content"]}
    except Exception as e:
        details = getattr(e, 'response', {}).text if isinstance(e, httpx.HTTPStatusError) else ""
        print(f"Translation failed: {e}")
        return {"status": "error", "message": f"{e} | Details: {details}"}
