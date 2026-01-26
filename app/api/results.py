import json
import sqlite3
from typing import List

from fastapi import APIRouter, HTTPException
from app.db.sqlite import get_connection
from app.models.schemas import ResultResponse, ResultUpdateRequest

router = APIRouter()


@router.get("/jobs/{job_id}/results")
async def get_job_results(job_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, job_id, original_id, group_id, original_json, fixed_json, human_review, created_at, updated_at
            FROM results
            WHERE job_id = ?
            ORDER BY group_id ASC
            """,
            (job_id,),
        )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "result_id": row["id"],
                    "job_id": row["job_id"],
                    "original_id": row["original_id"],
                    "group_id": row["group_id"],
                    "original": json.loads(row["original_json"]),
                    "fixed": json.loads(row["fixed_json"]),
                    "human_review": row["human_review"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )

        return {"results": results}
    finally:
        conn.close()


@router.patch("/results/{result_id}")
async def update_result(result_id: int, request: ResultUpdateRequest):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE results
            SET human_review = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (request.human_review, result_id),
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Result not found")

        conn.commit()

        cursor.execute(
            "SELECT id, job_id, original_id, group_id, original_json, fixed_json, human_review, created_at, updated_at FROM results WHERE id = ?",
            (result_id,),
        )
        row = cursor.fetchone()

        return {
            "result_id": row["id"],
            "job_id": row["job_id"],
            "original_id": row["original_id"],
            "group_id": row["group_id"],
            "original": json.loads(row["original_json"]),
            "fixed": json.loads(row["fixed_json"]),
            "human_review": row["human_review"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()
