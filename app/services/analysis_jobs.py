import asyncio
import logging
import time
import uuid

from app.services import analysis_service

logger = logging.getLogger(__name__)

# Finished jobs are kept for one hour so the frontend can fetch the result
# after a slow poll or a page reload, then purged lazily on the next access.
JOB_TTL_SECONDS = 3600

_jobs: dict = {}


def _purge_expired() -> None:
    now = time.time()
    expired = [job_id for job_id, job in _jobs.items()
               if job["status"] != "running"
               and now - job["finished_at"] > JOB_TTL_SECONDS]
    for job_id in expired:
        del _jobs[job_id]


def start_job(files_content: str, framework: str) -> str:
    """Kicks off an analysis in the background and returns its job id."""
    _purge_expired()
    job_id = uuid.uuid4().hex
    job = {
        "status": "running",
        "progress": {"done": 0, "total": None},
        "result": None,
        "created_at": time.time(),
        "finished_at": None,
    }
    _jobs[job_id] = job
    # The reference on the job keeps the task from being garbage-collected.
    job["task"] = asyncio.create_task(_run(job_id, files_content, framework))
    logger.info(f"Analysis job {job_id} started: framework={framework} "
                f"input_len={len(files_content)} chars")
    return job_id


async def _run(job_id: str, files_content: str, framework: str) -> None:
    job = _jobs[job_id]

    def on_progress(done: int, total: int) -> None:
        job["progress"] = {"done": done, "total": total}

    try:
        result = await analysis_service.analyze_configuration_files(
            files_content, framework, progress_cb=on_progress)
        job["status"] = "error" if result.get("status") == "error" else "completed"
        job["result"] = result
    except Exception as e:
        logger.error(f"Analysis job {job_id} crashed: {e}")
        job["status"] = "error"
        job["result"] = {"status": "error", "message": str(e)}
    finally:
        job["finished_at"] = time.time()
        job.pop("task", None)
        logger.info(f"Analysis job {job_id} finished: status={job['status']} "
                    f"elapsed={job['finished_at'] - job['created_at']:.2f}s")


def get_job(job_id: str):
    """Returns the poll payload for a job, or None if unknown/expired.

    While running: {job_id, status, progress}. Once finished, the service
    result (analysis or message) is merged in — its "status" key matches.
    """
    _purge_expired()
    job = _jobs.get(job_id)
    if job is None:
        return None
    payload = {"job_id": job_id, "status": job["status"], "progress": job["progress"]}
    if job["status"] != "running" and job["result"]:
        payload.update(job["result"])
    return payload
