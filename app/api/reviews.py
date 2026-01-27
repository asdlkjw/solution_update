import json
import sqlite3
from typing import Dict, Any, List

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db.sqlite import get_connection
from app.core.updater import update_problems_from_results
from app.models.schemas import ApplyResponse

router = APIRouter()

IMAGE_RENDER_API = "https://class.day/img-conv/api/render"


class ImageRenderRequest(BaseModel):
    problem_ids: List[int]
    deduplicate: bool = True


class ImageRenderResult(BaseModel):
    problem_id: int
    job_id: str | None = None
    success: bool
    error: str | None = None


@router.post("/render-images")
async def render_images(request: ImageRenderRequest):
    results = []

    for problem_id in request.problem_ids:
        try:
            response = requests.post(
                IMAGE_RENDER_API,
                json={"problem_id": problem_id, "deduplicate": request.deduplicate},
                headers={
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            results.append(
                ImageRenderResult(
                    problem_id=problem_id, job_id=data.get("job_id"), success=True
                )
            )
        except Exception as e:
            results.append(
                ImageRenderResult(problem_id=problem_id, success=False, error=str(e))
            )

    success_count = sum(1 for r in results if r.success)
    return {
        "results": [r.model_dump() for r in results],
        "success_count": success_count,
        "fail_count": len(results) - success_count,
    }


@router.post("/jobs/{job_id}/apply")
async def apply_job_results(job_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT status FROM jobs WHERE id = ?",
            (job_id,),
        )
        job_row = cursor.fetchone()

        if not job_row:
            raise HTTPException(status_code=404, detail="Job not found")

        if job_row["status"] != "done":
            raise HTTPException(status_code=400, detail="Job is not completed yet")

        cursor.execute(
            """
            SELECT id, original_id, fixed_json, human_review
            FROM results
            WHERE job_id = ? AND human_review = 'GOOD'
            ORDER BY id ASC
            """,
            (job_id,),
        )
        results = cursor.fetchall()

        updated_count, skipped_count = update_problems_from_results(results)

        return {
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "message": f"Applied {updated_count} results to production DB (skipped {skipped_count})",
        }
    finally:
        conn.close()
