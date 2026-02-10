import json
import os

from fastapi import APIRouter, HTTPException

from app.core.job_runner import job_runner
from app.db.sqlite import get_connection
from app.models.schemas import JobCreateRequest, JobResponse

router = APIRouter()


def _row_to_job(row) -> JobResponse:
    return JobResponse(
        job_id=row["id"],
        input_type=row["input_type"],
        input_value=row["input_value"],
        pipeline_version=row["pipeline_version"]
        if "pipeline_version" in row.keys()
        else "v1",
        status=row["status"],
        total_count=row["total_count"],
        processed_count=row["processed_count"],
        error_count=row["error_count"],
        judge_processed_count=row["judge_processed_count"],
        judge_retry_count=row["judge_retry_count"],
        judge_fail_count=row["judge_fail_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/jobs", response_model=JobResponse)
def create_job(payload: JobCreateRequest) -> JobResponse:
    if payload.pipeline_version == "v2":
        expected_password = os.getenv("V2_PIPELINE_PASSWORD")
        if not expected_password:
            raise HTTPException(status_code=500, detail="V2 password not configured")
        if payload.v2_password != expected_password:
            raise HTTPException(status_code=403, detail="Invalid v2 password")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs (
                input_type,
                input_value,
                pipeline_version,
                status,
                total_count,
                processed_count,
                error_count
            ) VALUES (?, ?, ?, 'queued', 0, 0, 0)
            """,
            (payload.input_type, payload.input_value, payload.pipeline_version),
        )
        job_id = cursor.lastrowid
        conn.commit()

    if job_id is None:
        raise HTTPException(status_code=500, detail="Failed to create job")

    job_runner.submit_job(
        job_id, payload.input_type, payload.input_value, payload.pipeline_version
    )
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int) -> JobResponse:
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return _row_to_job(row)
