# Plan: Pipeline Version Selector

## Context

### Original Request
사용자가 기존 v1 파이프라인은 유지한 채로 다른 방식의 파이프라인(v2)도 실험할 수 있도록, 홈 화면에서 라디오 버튼으로 파이프라인 버전을 선택하는 기능을 추가하고 싶다.

### Interview Summary
- 기존 v1 코드는 최소한으로만 변경 (비파괴적 확장)
- v2의 구체적인 로직은 아직 미정 -- 인프라/라우팅 구조에 집중
- v2는 placeholder로 두되, 나중에 쉽게 채울 수 있는 구조
- v3, v4 등 확장이 쉬운 구조 설계

### Research Findings (Codebase Analysis)

**현재 데이터 흐름:**
```
index.html (group_ids 입력)
  → POST /jobs { input_type: "group_id", input_value: "128126,128127" }
  → jobs.py: create_job() → DB INSERT → job_runner.submit_job(job_id, input_type, input_value)
  → job_runner.py: _run_job() → fetch_problems() → process_single_problem() [x32 parallel]
    → fixer.py: fix_content_with_llm() → 후처리 체인(18개 함수) → judge_fixed_output()
  → results 저장 → status.html → review.html
```

**핵심 터치포인트:**
1. `app/models/schemas.py` - `JobCreateRequest` (input_type, input_value만 존재)
2. `app/api/jobs.py` - `create_job()` endpoint, DB INSERT, `job_runner.submit_job()` 호출
3. `app/core/job_runner.py` - `JobRunner.submit_job()`, `_run_job()` 내부에서 `process_single_problem` 직접 호출
4. `app/core/fixer.py` - `process_single_problem()` 함수 (후처리 체인 하드코딩)
5. `app/db/schema.sql` - jobs 테이블 (pipeline_version 컬럼 없음)
6. `app/db/sqlite.py` - `init_db()` (마이그레이션 패턴 존재: ALTER TABLE로 컬럼 추가)
7. `app/templates/index.html` - 폼 (group_ids 입력만 존재, JS에서 POST body 구성)
8. `app/templates/status.html` - 진행률 모니터링 (pipeline 버전 표시 없음)

---

## Work Objectives

### Core Objective
홈 화면에서 파이프라인 버전(v1/v2/...)을 선택할 수 있게 하고, 선택된 버전에 따라 다른 처리 로직을 라우팅하는 확장 가능한 인프라를 구축한다.

### Deliverables
1. 홈 화면에 파이프라인 버전 선택 라디오 버튼 UI
2. API/DB에 `pipeline_version` 필드 추가
3. `JobRunner`에 파이프라인 버전 기반 라우팅 메커니즘
4. v2 파이프라인 placeholder (쉽게 채울 수 있는 구조)
5. status.html에 현재 파이프라인 버전 표시

### Definition of Done
- v1 라디오 선택 시 기존 동작과 100% 동일하게 작동
- v2 라디오 선택 시 placeholder 파이프라인이 실행됨 (v1과 동일 로직의 복사본)
- job 테이블에 pipeline_version이 기록됨
- 기존 데이터(pipeline_version=NULL)가 자동으로 v1으로 취급됨
- v3 추가 시 새 파일 1개 + 레지스트리 등록 1줄이면 충분한 구조

---

## Must Have / Must NOT Have (Guardrails)

### Must Have
- v1 파이프라인의 기존 코드 경로가 깨지지 않아야 함
- pipeline_version이 NULL인 기존 job은 v1으로 취급
- DB 마이그레이션이 기존 데이터를 보존해야 함
- 라디오 버튼 기본 선택값은 v1

### Must NOT Have
- fixer.py의 기존 함수(process_single_problem, 후처리 체인 등)를 직접 수정하지 않음
- 기존 v1 로직의 동작 변경 없음
- v2의 실제 차별화된 로직 구현 (placeholder만)
- 복잡한 설정 시스템이나 별도의 config 파일

---

## Architecture Decision: Strategy Pattern + Pipeline Registry

### 선택한 패턴: Pipeline Registry + Strategy Pattern

```python
# app/core/pipelines/__init__.py
# 새로운 파이프라인 모듈 패키지

# app/core/pipelines/registry.py
PIPELINE_REGISTRY = {
    "v1": "app.core.pipelines.v1",
    "v2": "app.core.pipelines.v2",
}

# 각 파이프라인 모듈은 동일한 인터페이스를 구현:
# def process_single_problem(problem: Dict[str, Any]) -> Dict[str, Any]
```

### 왜 이 패턴인가
1. **기존 코드 비파괴**: v1 파이프라인은 기존 `fixer.py`의 `process_single_problem`을 그대로 re-export
2. **확장 용이**: v3 추가 = 새 파일 + registry 한 줄
3. **단순함**: 복잡한 추상 클래스 없이 함수 레벨 인터페이스
4. **테스트 용이**: 각 파이프라인을 독립적으로 테스트 가능

### 대안 검토
- **ABC 클래스 상속**: 오버엔지니어링. 현재는 함수 1개(`process_single_problem`)만 분기하면 됨
- **if/elif 분기**: 확장성 부족, 코드 오염
- **설정 파일 기반**: 불필요한 복잡성. 코드 내 레지스트리가 더 명확

---

## Task Flow and Dependencies

```
[Task 1: DB 스키마 + 마이그레이션]
    ↓
[Task 2: Pydantic 모델 확장]
    ↓
[Task 3: Pipeline Registry 모듈 생성]
    ↓
[Task 4: JobRunner 라우팅 로직 추가]
    ↓
[Task 5: API 엔드포인트 수정]
    ↓
[Task 6: 홈 화면 UI (라디오 버튼)]
    ↓
[Task 7: Status 화면에 버전 표시]
    ↓
[Task 8: 검증]
```

---

## Detailed TODOs

### Task 1: DB 스키마 + 마이그레이션
**File:** `app/db/schema.sql`, `app/db/sqlite.py`

**Changes to `app/db/schema.sql`:**
- jobs 테이블에 `pipeline_version` 컬럼 추가

```sql
-- schema.sql 내 jobs 테이블에 추가:
-- input_value 뒤에 추가
pipeline_version TEXT NOT NULL DEFAULT 'v1',
```

**Changes to `app/db/sqlite.py`:**
- `init_db()` 내 마이그레이션 로직에 `pipeline_version` 컬럼 추가 (기존 패턴 따라감)

```python
# 기존 마이그레이션 패턴을 따름:
columns_to_add = [
    "judge_processed_count",
    "judge_retry_count",
    "judge_fail_count",
]
# 여기에 추가:
# pipeline_version 컬럼 마이그레이션도 동일 패턴으로 추가
if "pipeline_version" not in columns:
    conn.execute(
        "ALTER TABLE jobs ADD COLUMN pipeline_version TEXT NOT NULL DEFAULT 'v1'"
    )
```

**Acceptance Criteria:**
- [x] 기존 DB에 pipeline_version 컬럼이 자동 추가됨
- [x] 기존 row들은 DEFAULT 'v1' 값을 가짐
- [x] 새 schema.sql에 pipeline_version이 포함됨

---

### Task 2: Pydantic 모델 확장
**File:** `app/models/schemas.py`

**Changes:**

```python
# JobCreateRequest에 pipeline_version 추가
class JobCreateRequest(BaseModel):
    input_type: Literal["id", "group_id"]
    input_value: str
    pipeline_version: str = "v1"  # 기본값 v1, 하위 호환

# JobResponse에 pipeline_version 추가
class JobResponse(BaseModel):
    job_id: int
    input_type: str
    input_value: str
    pipeline_version: str  # 추가
    status: str
    total_count: int
    processed_count: int
    error_count: int
    judge_processed_count: int
    judge_retry_count: int
    judge_fail_count: int
    created_at: str
    updated_at: str
```

**Acceptance Criteria:**
- [x] `JobCreateRequest`에 `pipeline_version` 필드 추가 (기본값 "v1")
- [x] `JobResponse`에 `pipeline_version` 필드 추가
- [x] 기존 API 호출(pipeline_version 없이)도 하위 호환됨

---

### Task 3: Pipeline Registry 모듈 생성
**Files:** 새로 생성
- `app/core/pipelines/__init__.py`
- `app/core/pipelines/registry.py`
- `app/core/pipelines/v1.py`
- `app/core/pipelines/v2.py`

**`app/core/pipelines/__init__.py`:**
```python
# Pipeline package
```

**`app/core/pipelines/registry.py`:**
```python
from typing import Any, Callable, Dict

# 파이프라인 레지스트리: version -> process function
_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def register_pipeline(version: str, process_fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    _REGISTRY[version] = process_fn


def get_pipeline(version: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    if version not in _REGISTRY:
        raise ValueError(f"Unknown pipeline version: {version}. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[version]


def available_versions() -> list[str]:
    return list(_REGISTRY.keys())
```

**`app/core/pipelines/v1.py`:**
```python
"""v1 파이프라인 - 기존 fixer.py의 process_single_problem을 그대로 사용"""
from app.core.fixer import process_single_problem
from app.core.pipelines.registry import register_pipeline

# v1은 기존 로직을 그대로 re-export
register_pipeline("v1", process_single_problem)
```

**`app/core/pipelines/v2.py`:**
```python
"""v2 파이프라인 - placeholder (현재는 v1과 동일, 나중에 차별화)

TODO: 여기에 v2 고유 로직을 구현하세요.
예시:
- 다른 LLM 모델 사용
- 다른 프롬프트 템플릿
- 다른 후처리 체인
- 다른 judge 기준
"""
from app.core.fixer import process_single_problem
from app.core.pipelines.registry import register_pipeline

# 현재는 v1과 동일 - 나중에 이 함수를 교체
register_pipeline("v2", process_single_problem)
```

**Acceptance Criteria:**
- [x] registry.py에서 get_pipeline("v1") 호출 시 기존 process_single_problem 반환
- [x] registry.py에서 get_pipeline("v2") 호출 시 placeholder 함수 반환
- [x] get_pipeline("v99") 호출 시 ValueError 발생
- [x] available_versions()가 ["v1", "v2"] 반환

---

### Task 4: JobRunner 라우팅 로직 추가
**File:** `app/core/job_runner.py`

**Changes:**

```python
# import 추가
from app.core.pipelines.registry import get_pipeline
# v1, v2 모듈 import하여 자동 등록 트리거
import app.core.pipelines.v1  # noqa: F401
import app.core.pipelines.v2  # noqa: F401

class JobRunner:
    # submit_job 시그니처 변경
    def submit_job(self, job_id: int, input_type: str, input_value: str, pipeline_version: str = "v1") -> None:
        parsed_ids = [int(x.strip()) for x in input_value.split(",") if x.strip()]
        self.executor.submit(self._run_job, job_id, input_type, parsed_ids, pipeline_version)

    # _run_job 시그니처 변경
    def _run_job(self, job_id: int, input_type: str, input_value: List[int], pipeline_version: str = "v1") -> None:
        try:
            # 파이프라인 함수 조회
            process_fn = get_pipeline(pipeline_version)

            self._update_job_status(job_id, "running")
            problems = self._fetch_problem_data(input_type, input_value)
            # ... (기존 코드 동일)

            with ThreadPoolExecutor(max_workers=self.item_workers) as executor:
                future_to_problem = {
                    executor.submit(process_fn, problem): problem  # process_single_problem 대신 process_fn
                    for problem in problems
                }
                # ... (나머지 동일)
```

**핵심 변경 사항:**
1. `submit_job()`에 `pipeline_version` 파라미터 추가 (기본값 "v1")
2. `_run_job()`에 `pipeline_version` 파라미터 전달
3. `_run_job()` 내부에서 `process_single_problem` 직접 호출 대신 `get_pipeline(pipeline_version)` 사용
4. 기존 `from app.core.fixer import process_single_problem` import는 유지 (다른 곳에서 쓰일 수 있음) 또는 제거 가능

**Acceptance Criteria:**
- [x] pipeline_version="v1"일 때 기존과 100% 동일한 동작
- [x] pipeline_version="v2"일 때 v2 파이프라인의 process 함수 사용
- [x] 잘못된 pipeline_version 전달 시 job이 failed 상태로 전환

---

### Task 5: API 엔드포인트 수정
**File:** `app/api/jobs.py`

**Changes:**

```python
# create_job 내부:
@router.post("/jobs", response_model=JobResponse)
def create_job(payload: JobCreateRequest) -> JobResponse:
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

    # ... (에러 처리 동일)

    job_runner.submit_job(job_id, payload.input_type, payload.input_value, payload.pipeline_version)
    # ... (나머지 동일)

# _row_to_job에 pipeline_version 추가:
def _row_to_job(row) -> JobResponse:
    return JobResponse(
        job_id=row["id"],
        input_type=row["input_type"],
        input_value=row["input_value"],
        pipeline_version=row["pipeline_version"] if "pipeline_version" in row.keys() else "v1",
        # ... (나머지 동일)
    )
```

**Acceptance Criteria:**
- [x] POST /jobs에 `pipeline_version` 필드 전달 가능
- [x] pipeline_version 없이 호출해도 "v1"로 기본 동작
- [x] GET /jobs/{job_id} 응답에 pipeline_version 포함
- [x] DB에 pipeline_version이 정확히 기록됨

---

### Task 6: 홈 화면 UI (라디오 버튼)
**File:** `app/templates/index.html`

**Changes:**

폼에 파이프라인 버전 선택 라디오 버튼 그룹 추가 (textarea 위에):

```html
<!-- textarea 위에 추가 -->
<label>Pipeline Version</label>
<div class="pipeline-selector">
    <label class="radio-label">
        <input type="radio" name="pipeline-version" value="v1" checked>
        <span class="radio-text">v1</span>
        <span class="radio-desc">기본 파이프라인</span>
    </label>
    <label class="radio-label">
        <input type="radio" name="pipeline-version" value="v2">
        <span class="radio-text">v2</span>
        <span class="radio-desc">실험적 파이프라인</span>
    </label>
</div>
```

**CSS 추가 (기존 디자인 시스템과 일관성 유지):**
```css
.pipeline-selector {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
}

.radio-label {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
    font-size: inherit;
    color: inherit;
    text-transform: none;
    letter-spacing: normal;
    margin-bottom: 0;
}

.radio-label:has(input:checked) {
    border-color: var(--accent-color);
    background: rgba(0, 212, 255, 0.05);
}

.radio-label input[type="radio"] {
    accent-color: var(--accent-color);
}

.radio-text {
    font-weight: 600;
    color: var(--text-primary);
}

.radio-desc {
    font-size: 0.75rem;
    color: var(--text-secondary);
}
```

**JS 변경 (fetch body에 pipeline_version 추가):**
```javascript
// 기존:
body: JSON.stringify({
    input_type: 'group_id',
    input_value: groupIds.join(',')
})

// 변경:
const pipelineVersion = document.querySelector('input[name="pipeline-version"]:checked').value;
body: JSON.stringify({
    input_type: 'group_id',
    input_value: groupIds.join(','),
    pipeline_version: pipelineVersion
})
```

**Acceptance Criteria:**
- [x] 라디오 버튼이 기존 디자인과 일관성 있게 표시됨
- [x] v1이 기본 선택됨
- [x] 선택된 값이 POST body에 포함됨
- [x] 라디오 선택 시 시각적 피드백 (border color 변경)

---

### Task 7: Status 화면에 버전 표시
**File:** `app/templates/status.html`

**Changes:**

job-id 표시 부분에 pipeline version도 함께 표시:

```html
<!-- 기존: -->
<div class="job-id">Job ID: <span id="job-id">{{ job_id }}</span></div>

<!-- 변경: -->
<div class="job-id">
    Job ID: <span id="job-id">{{ job_id }}</span>
    <span class="pipeline-badge" id="pipeline-badge"></span>
</div>
```

```css
.pipeline-badge {
    display: inline-block;
    padding: 2px 8px;
    border: 1px solid var(--accent-color);
    border-radius: 3px;
    font-size: 0.7rem;
    color: var(--accent-color);
    margin-left: 8px;
    text-transform: uppercase;
}
```

JS에서 checkStatus() 응답 처리 시 badge 업데이트:
```javascript
// checkStatus() 내부에 추가:
const pipelineBadge = document.getElementById('pipeline-badge');
if (data.pipeline_version) {
    pipelineBadge.textContent = data.pipeline_version;
}
```

**Acceptance Criteria:**
- [x] status 페이지에서 현재 job의 pipeline version이 표시됨
- [x] badge 스타일이 기존 디자인과 일관적임

---

### Task 8: 검증
**Verification Steps:**

1. **하위 호환성 검증:**
   - pipeline_version 없이 POST /jobs 호출 -> v1으로 동작하는지 확인
   - 기존 DB의 jobs (pipeline_version 컬럼 없음) -> 마이그레이션 후 v1으로 표시되는지 확인

2. **v1 동작 검증:**
   - 홈에서 v1 선택 후 실행 -> 기존과 동일하게 동작하는지 확인
   - process_single_problem이 기존 fixer.py의 함수인지 확인

3. **v2 동작 검증:**
   - 홈에서 v2 선택 후 실행 -> job이 생성되고 pipeline_version="v2"로 기록되는지 확인
   - v2 파이프라인이 정상 실행되는지 확인

4. **UI 검증:**
   - 라디오 버튼이 정상 렌더링되는지 확인
   - status 페이지에서 pipeline version badge가 표시되는지 확인

5. **DB 검증:**
   - jobs 테이블에 pipeline_version 컬럼이 존재하는지 확인
   - 새 job에 올바른 pipeline_version 값이 저장되는지 확인

---

## Commit Strategy

### Commit 1: DB + Models
- `app/db/schema.sql` - pipeline_version 컬럼 추가
- `app/db/sqlite.py` - 마이그레이션 로직 추가
- `app/models/schemas.py` - JobCreateRequest, JobResponse에 pipeline_version 추가

### Commit 2: Pipeline Registry
- `app/core/pipelines/__init__.py` - 패키지 생성
- `app/core/pipelines/registry.py` - 레지스트리 구현
- `app/core/pipelines/v1.py` - v1 등록
- `app/core/pipelines/v2.py` - v2 placeholder 등록

### Commit 3: Backend Routing
- `app/core/job_runner.py` - pipeline_version 라우팅 추가
- `app/api/jobs.py` - API에 pipeline_version 전달

### Commit 4: Frontend UI
- `app/templates/index.html` - 라디오 버튼 UI 추가
- `app/templates/status.html` - pipeline version badge 추가

---

## Success Criteria

| Criteria | Measurement |
|----------|-------------|
| v1 비파괴 | v1 선택 시 기존과 100% 동일 동작 |
| v2 작동 | v2 선택 시 job 생성 및 처리 완료 |
| DB 기록 | pipeline_version이 jobs 테이블에 저장됨 |
| 하위 호환 | pipeline_version 없는 API 호출도 정상 동작 |
| 확장성 | v3 추가 시 파일 1개 + registry 등록 1줄 |
| UI | 라디오 버튼이 디자인 시스템과 일관적 |

---

## Risk Identification

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 기존 DB 마이그레이션 실패 | Low | High | ALTER TABLE + DEFAULT 'v1' 패턴은 이미 검증됨 (judge 컬럼 추가 선례) |
| pipeline import 순서 문제 | Medium | Medium | v1.py, v2.py를 job_runner.py에서 명시적으로 import (noqa: F401) |
| v2 placeholder가 v1과 동일해서 혼란 | Low | Low | v2.py 파일 상단에 TODO 주석으로 명시 |
| _row_to_job에서 pipeline_version 컬럼 누락 시 에러 | Medium | Medium | row.keys() 체크로 fallback "v1" 반환 |
