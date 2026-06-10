from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.services import translation_service

router = APIRouter()

@router.post("/translate")
async def translate_config(
    file: UploadFile = File(...),
    target_vendor: str = Form(...)
):
    """
    Endpoint to receive a configuration file and a target vendor.
    Passes the file to the AI logic for translation.
    """
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")

    content_bytes = await file.read()
    try:
        content_str = content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        content_str = content_bytes.decode('latin-1') # fallback

    return await translation_service.translate_configuration_file(content_str, target_vendor)
