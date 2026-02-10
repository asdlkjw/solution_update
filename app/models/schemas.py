from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    input_type: Literal["id", "group_id"]
    input_value: str
    pipeline_version: str = "v1"
    v2_password: Optional[str] = None


class JobResponse(BaseModel):
    job_id: int
    input_type: str
    input_value: str
    pipeline_version: str
    status: str
    total_count: int
    processed_count: int
    error_count: int
    judge_processed_count: int
    judge_retry_count: int
    judge_fail_count: int
    created_at: str
    updated_at: str


class ResultResponse(BaseModel):
    result_id: int
    job_id: int
    original_id: int
    group_id: Optional[int]
    original: Dict[str, Any]
    fixed: Dict[str, Any]
    human_review: str
    created_at: str
    updated_at: str


class ResultUpdateRequest(BaseModel):
    human_review: Literal["GOOD", "BAD", "UNVERIFIED"]


class ApplyResponse(BaseModel):
    updated_count: int
    skipped_count: int
    message: str


class ApplyRequest(BaseModel):
    update_fields: Optional[List[str]] = None
    update_fields_map: Optional[Dict[int, List[str]]] = None
