# Sisyphus Agent Guide

이 문서는 Sisyphus 시스템을 확장하거나 개선할 때, 개발 에이전트(AI)가 효율적으로 작업을 수행할 수 있도록 돕는 프롬프트 가이드와 필수 맥락 정보를 포함합니다.

---

## 🛠️ 프로젝트 개요

**Math Problem Fixer (Sisyphus)** - 수학 문제 데이터베이스의 오류(LaTeX 문법, 오타, 포맷팅)를 Gemini 3.0 Flash 모델을 사용하여 자동 수정하고, 결과를 검토/반영하는 시스템입니다.

### 핵심 컴포넌트
- **Fixer Engine**: LLM 기반 문제 수정 (CLI + 웹)
- **Web UI**: FastAPI 기반 대시보드/리뷰 시스템
- **Database**: MySQL (Production) + SQLite (Meta/Temporary)

---

## 📦 Build & Test Commands

### 설치 (uv 사용 권장)
```bash
uv venv                           # 가상환경 생성 (없는 경우)
source .venv/bin/activate        # 가상환경 활성화
uv pip install -e .               # 패키지 설치
```

### 웹 서버 실행
```bash
./run_server.sh                   # 또는
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### CLI 실행
```bash
python fix_problems.py --ids 101,102,103 --output results.json
python update_problems.py results.json --execute
```

### Linting & Formatting
```bash
black .                           # 코드 포맷팅
flake8 .                          # 린트 체크
mypy .                            # 타입 체크
```

### 테스트 실행
```bash
pytest                            # 전체 테스트
pytest tests/test_specific.py      # 단일 파일
pytest tests/test_specific.py::test_function  # 단일 테스트
pytest -v                         # 상세 출력
pytest --cov                      # 커버리지
```

---

## 🎨 Code Style Guidelines

### Import 순서
1. **표준 라이브러리** (os, sys, json, pathlib 등)
2. **서드파티** (pymysql, fastapi, requests, pydantic 등)
3. **로컬 모듈** (`app.*`)

```python
# 올바른 예
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Literal, Optional

import pymysql
import requests
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.fixer import fetch_problems
from app.db.sqlite import get_connection
```

### Naming Conventions
- **함수/변수**: `snake_case` (e.g., `fetch_problems`, `job_runner`)
- **클래스**: `PascalCase` (e.g., `JobRunner`, `JobResponse`)
- **상수**: `UPPER_SNAKE_CASE` (e.g., `OPENROUTER_API_KEY`, `DB_HOST`)
- **타입 별칭**: `PascalCase` (e.g., `ProblemData`, `JobId`)

### Type Hints (필수)
모든 함수와 메서드에는 타입 힌트를 사용하세요.

```python
from typing import List, Dict, Any, Optional, Literal

def fetch_problems(
    ids: List[int] | None = None,
    group_ids: List[int] | None = None,
    mode: Literal["id", "group_id"] = "id",
) -> List[Dict[str, Any]]:
    """ID 또는 group_id 리스트에 해당하는 문제 데이터를 가져옵니다."""
    ...
```

### Error Handling
1. **구체적 예외**를 우선 사용
2. **generic Exception**은 최후의 수단으로
3. 에러 메시지는 `sys.stderr`에 출력
4. 치명적 에러는 `sys.exit(1)`로 종료

```python
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"Error: File not found at {path}", file=sys.stderr)
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"Error parsing JSON: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Unexpected error: {e}", file=sys.stderr)
    sys.exit(1)
```

### Database Operations
- **MySQL**: `pymysql.cursors.DictCursor` 사용
- **SQLite**: `conn.row_factory = sqlite3.Row` 사용
- 항상 `try-finally` 또는 `with`로 커넥션 정리

```python
# MySQL
def get_db_connection():
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=int(DB_PORT) if DB_PORT else 3306,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            cursorclass=pymysql.cursors.DictCursor,
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        sys.exit(1)

# SQLite
from contextlib import closing

with closing(get_connection()) as conn:
    cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
```

### Comments & Docstrings
- **주석**: 한국어 사용, 설명은 간결하게
- **Docstring**: 주요 함수/클래스에만 추가

```python
def normalize_answer(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    answer 필드의 텍스트를 정규화합니다.
    공백 제거, 특수문자 처리 등의 표준화 작업을 수행합니다.
    """
    # 답안 문자열에서 불필요한 공백 제거
    answer = fixed_data.get("answer", "")
    fixed_data["answer"] = " ".join(answer.split())
    return fixed_data
```

### Environment Variables
- `.env` 파일에서 로드 (`.env`는 `.gitignore`)
- 항상 `Path(__file__).resolve().parent.parent / ".env"`로 경로 지정
- 대문자 + 밑줄 형식

```python
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DB_HOST = os.getenv("DB_HOST")
```

---

## 🏗️ 프로젝트 구조

```
.
├── app/                    # FastAPI 웹 서버
│   ├── api/                # API 라우터 (jobs, results, reviews)
│   ├── core/               # 비즈니스 로직 (fixer, updater, job_runner)
│   ├── db/                 # 데이터베이스 관리 (SQLite, schema.sql)
│   ├── models/             # Pydantic 스키마
│   ├── templates/          # Jinja2 템플릿
│   └── main.py             # FastAPI 앱 엔트리포인트
├── fix_problems.py         # CLI: 문제 수정 실행
├── update_problems.py      # CLI: DB 반영 실행
├── prompt_template.json    # LLM 프롬프트 템플릿
├── run_server.sh           # 웹 서버 시작 스크립트
└── pyproject.toml          # 패키지 설정
```

---

## 🔄 데이터 흐름

1. **조회**: MySQL (Production DB) → 문제 데이터 가져오기
2. **처리**: SQLite (Meta DB) → LLM 수정 결과 저장
3. **리뷰**: Web UI → 사용자 검토 (GOOD/BAD 판정)
4. **반영**: MySQL (Production DB) → GOOD 결과만 반영

---

## 🚀 향후 개선 요청 템플릿

```markdown
### 1. 작업 개요
- [ ] 예: "리뷰 화면에 문제 유형(Type) 필터 추가"

### 2. 관련 파일
- `app/templates/review.html` (UI 변경)
- `app/api/results.py` (조회 로직 변경)

### 3. 상세 요구사항
- 리뷰 화면 상단에 드롭다운 메뉴 추가
- 선택한 유형에 맞는 결과만 리스트업되도록 API 쿼리 수정
- 비동기(JS)로 화면 갱신 처리

### 4. 주의사항
- 기존 단축키(1, 2, 방향키) 기능이 깨지지 않아야 함
- SQLite 쿼리 작성 시 인덱스 활용 고려
```

---

## 🎯 주요 개선 포인트 (Backlog)

- **안정성 강화**:
  - LLM API 호출 실패 시 자동 재시도 로직
  - 대량 데이터 처리 시 DB 커넥션 풀링 최적화
- **UI/UX 개선**:
  - 리뷰 화면에서 수정된 부분만 하이라이트(Diff) 표시
  - 다중 작업 동시 진행 시 목록 관리 기능
- **통계 기능**:
  - 작업별 성공률, 에러 유형별 통계 대시보드
- **테스트 자동화**:
  - API 엔드포인트 유닛 테스트 작성

---

## 💡 프롬프트 작성 팁

- **기존 코드 참고**: "`fix_problems.py`의 로직을 참고해서..."처럼 맥락 연결
- **스타일 일관성**: "`index.html`의 사이버펑크 테마를 유지해줘"처럼 명시
- **도메인 지식**: "수식은 항상 `$` 또는 `$$`로 감싸진 LaTeX 형식을 유지해야 해"처럼 명시
