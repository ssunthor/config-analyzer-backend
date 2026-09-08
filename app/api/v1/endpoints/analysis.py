from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List
from app.services import analysis_service, analysis_jobs, report_service

router = APIRouter()


class ReportRequest(BaseModel):
    """Analysis results (as parsed by the frontend) to render into a PDF."""
    framework: str = "Default Best Practices"
    issues: List[dict] = Field(default_factory=list)
    file_metadata: List[dict] = Field(default_factory=list)


async def _read_files(files: List[UploadFile]) -> str:
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
    return combined_content


@router.post("/analyze")
async def analyze_configs(
    files: List[UploadFile] = File(...),
    framework: str = Form("Default Best Practices")
):
    """
    Synchronous analysis: holds the request open until the analysis finishes.
    Kept for compatibility — long inputs can outlive proxy timeouts, so the
    frontend uses the job endpoints below instead.
    """
    combined_content = await _read_files(files)
    return await analysis_service.analyze_configuration_files(combined_content, framework)


@router.post("/analyze/jobs")
async def start_analysis_job(
    files: List[UploadFile] = File(...),
    framework: str = Form("Default Best Practices")
):
    """
    Starts an analysis in the background and returns immediately with a job
    id. Poll GET /analyze/jobs/{job_id} for progress and the final result.
    """
    combined_content = await _read_files(files)
    job_id = analysis_jobs.start_job(combined_content, framework)
    return {"job_id": job_id, "status": "running"}


@router.get("/analyze/jobs/{job_id}")
async def get_analysis_job(job_id: str):
    """
    Returns {job_id, status, progress} while running; once finished the
    analysis result (or error message) is merged into the payload.
    """
    job = analysis_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job id")
    return job


@router.post("/report")
async def generate_report(request: ReportRequest):
    """
    Renders a PDF audit report from a completed analysis: an LLM-written
    executive summary, overall rating, and recommended actions, followed by
    the detailed findings. Returns the PDF bytes as an attachment.
    """
    pdf = await report_service.generate_report(
        request.issues, request.file_metadata, request.framework)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="security-audit-report.pdf"'},
    )
