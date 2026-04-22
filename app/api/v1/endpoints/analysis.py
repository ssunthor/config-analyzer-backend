from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List
from app.services import analysis_service

router = APIRouter()

@router.post("/analyze")
async def analyze_configs(
    files: List[UploadFile] = File(...),
    framework: str = Form("Default Best Practices")
):
    """
    Endpoint to receive configuration files and an analysis framework.
    Passes the files to the AI logic for parsing and generating issues.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    combined_content = ""
    for file in files:
        content_bytes = await file.read()
        try:
            content_str = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            content_str = content_bytes.decode('latin-1') # fallback

        combined_content += f"--- File: {file.filename} ---\n"
        combined_content += content_str + "\n\n"

    return await analysis_service.analyze_configuration_files(combined_content, framework)