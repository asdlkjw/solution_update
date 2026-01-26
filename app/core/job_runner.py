import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, List

from app.core.fixer import fetch_problems, process_single_problem
from app.db.sqlite import get_connection


class JobRunner:
    def __init__(self, job_workers: int = 2, item_workers: int = 32) -> None:
        self.executor = ThreadPoolExecutor(max_workers=job_workers)
        self.item_workers = item_workers

    def submit_job(self, job_id: int, input_type: str, input_value: str) -> None:
        parsed_ids = [int(x.strip()) for x in input_value.split(",") if x.strip()]
        self.executor.submit(self._run_job, job_id, input_type, parsed_ids)

    def _run_job(self, job_id: int, input_type: str, input_value: List[int]) -> None:
        try:
            self._update_job_status(job_id, "running")
            problems = self._fetch_problem_data(input_type, input_value)
            total_count = len(problems)
            self._update_job_counts(job_id, total_count=total_count)

            if not problems:
                self._update_job_status(job_id, "done")
                return

            with ThreadPoolExecutor(max_workers=self.item_workers) as executor:
                future_to_problem = {
                    executor.submit(process_single_problem, problem): problem
                    for problem in problems
                }

                for future in as_completed(future_to_problem):
                    problem = future_to_problem[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {
                            "original_id": problem.get("id"),
                            "original": json.loads(json.dumps(problem, default=str)),
                            "fixed": {
                                "error": str(exc),
                                "original_id": problem.get("id"),
                            },
                        }

                    error_flag = 1 if "error" in result.get("fixed", {}) else 0
                    self._insert_result(job_id, result)
                    self._increment_job_counts(job_id, error_flag)

            self._update_job_status(job_id, "done")
        except Exception:
            self._update_job_status(job_id, "failed")

    def _fetch_problem_data(self, input_type: str, input_value: List[int]):
        if input_type == "id":
            return fetch_problems(ids=input_value, mode="id")
        return fetch_problems(group_ids=input_value, mode="group_id")

    def _update_job_status(self, job_id: int, status: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, job_id),
            )
            conn.commit()

    def _update_job_counts(self, job_id: int, total_count: int) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET total_count = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (total_count, job_id),
            )
            conn.commit()

    def _increment_job_counts(self, job_id: int, error_flag: int) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET processed_count = processed_count + 1,
                    error_count = error_count + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_flag, job_id),
            )
            conn.commit()

    def _insert_result(self, job_id: int, result: dict) -> None:
        original = result.get("original")
        fixed = result.get("fixed")
        original_id = result.get("original_id")
        group_id = None
        if isinstance(original, dict):
            group_id = original.get("group_id")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO results (
                    job_id,
                    original_id,
                    group_id,
                    original_json,
                    fixed_json,
                    human_review
                ) VALUES (?, ?, ?, ?, ?, 'GOOD')
                """,
                (
                    job_id,
                    original_id,
                    group_id,
                    json.dumps(original, ensure_ascii=False),
                    json.dumps(fixed, ensure_ascii=False)
                    if fixed is not None
                    else None,
                ),
            )
            conn.commit()


job_runner = JobRunner()
