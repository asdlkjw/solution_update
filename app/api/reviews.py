import json
import sqlite3
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from app.db.sqlite import get_connection
from app.core.updater import update_problems_from_results
from app.models.schemas import ApplyResponse

router = APIRouter()


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
