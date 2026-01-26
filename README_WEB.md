# Sisyphus Web Server

FastAPI 기반 웹 서버로 전환된 Math Problem Fixer입니다. 기존 CLI 스크립트를 웹 UI로 사용할 수 있습니다.

## 주요 기능

- **웹 UI**: 브라우저에서 Group IDs 입력 및 결과 리뷰
- **실시간 진행률**: Polling 방식으로 작업 진행 상황 확인
- **GOOD/BAD 리뷰**: 키보드 단축키(1=GOOD, 2=BAD)로 빠른 리뷰
- **최종 제출**: 리뷰 결과를 production DB에 반영
- **SQLite 메타 DB**: 작업 상태 및 결과 저장

## 프로젝트 구조

```
scripts/
├── app/
│   ├── main.py              # FastAPI 앱
│   ├── api/
│   │   ├── jobs.py          # POST /jobs, GET /jobs/{job_id}
│   │   ├── results.py       # GET /jobs/{job_id}/results, PATCH /results/{result_id}
│   │   └── reviews.py       # POST /jobs/{job_id}/apply
│   ├── core/
│   │   ├── fixer.py         # fix_problems.py 로직 모듈화
│   │   ├── updater.py       # update_problems.py 로직 함수화
│   │   └── job_runner.py    # ThreadPoolExecutor 백그라운드 작업
│   ├── db/
│   │   ├── schema.sql       # SQLite 스키마 (jobs, results)
│   │   └── sqlite.py        # DB 연결/초기화
│   ├── models/
│   │   └── schemas.py       # Pydantic 요청/응답 스키마
│   └── templates/
│       ├── index.html       # 입력 화면
│       ├── status.html      # 진행률 화면
│       └── review.html      # 리뷰 화면 (GOOD/BAD 토글)
├── fix_problems.py          # 기존 CLI (app.core.fixer 사용)
├── update_problems.py       # 기존 CLI (app.core.updater 사용)
├── run_server.sh            # 서버 실행 스크립트
└── pyproject.toml           # 의존성 (FastAPI, uvicorn, jinja2)
```

## 설치 및 실행

### 1. 의존성 설치

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

### 2. 환경변수 설정

`.env` 파일에 다음 정보를 입력:

```ini
OPENROUTER_API_KEY=sk-or-v1-...
DB_HOST=your-db-host
DB_PROD_PORT=3306
DB_USER=your-db-user
DB_PROD_PASSWORD=your-db-password
DB_NAME=your-db-name
```

### 3. 서버 실행

```bash
./run_server.sh
```

또는 수동 실행:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 브라우저 접속

```
http://localhost:8000
```

## 사용 방법

### 1. Group IDs 입력

- 메인 화면에서 Group IDs 입력 (공백, 개행, 쉼표로 구분)
- "실행" 버튼 클릭

### 2. 진행률 확인

- 자동으로 진행률 화면으로 이동
- 2초마다 자동 갱신
- 완료 시 "리뷰 시작" 버튼 표시

### 3. 결과 리뷰

- 좌측: 원본 데이터 (Original)
- 우측: AI 수정 데이터 (Fixed by Gemini 3.0)
- **키보드 단축키**:
  - `←` / `→`: 이전/다음 문제
  - `1`: GOOD
  - `2`: BAD
- 각 문제마다 GOOD/BAD 선택 (기본값: GOOD)

### 4. 최종 제출

- "최종 제출" 버튼 클릭
- 확인 팝업에서 GOOD/BAD 통계 확인
- 확인 시 production DB 업데이트 (GOOD만 반영)

## API 엔드포인트

### POST /jobs

작업 생성

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"input_type": "group_id", "input_value": "128126,128127"}'
```

응답:

```json
{
  "job_id": 1,
  "status": "queued",
  "total_count": 0,
  "processed_count": 0,
  "error_count": 0
}
```

### GET /jobs/{job_id}

작업 상태 조회

```bash
curl http://localhost:8000/jobs/1
```

응답:

```json
{
  "job_id": 1,
  "status": "running",
  "total_count": 120,
  "processed_count": 80,
  "error_count": 3
}
```

### GET /jobs/{job_id}/results

작업 결과 조회

```bash
curl http://localhost:8000/jobs/1/results
```

### PATCH /results/{result_id}

결과 리뷰 업데이트

```bash
curl -X PATCH http://localhost:8000/results/10 \
  -H "Content-Type: application/json" \
  -d '{"human_review": "BAD"}'
```

### POST /jobs/{job_id}/apply

Production DB에 반영

```bash
curl -X POST http://localhost:8000/jobs/1/apply
```

응답:

```json
{
  "updated_count": 80,
  "skipped_count": 5,
  "message": "Applied 80 results to production DB (skipped 5)"
}
```

## 기술 스택

- **Backend**: FastAPI, Uvicorn
- **Frontend**: HTML, CSS, JavaScript (Vanilla)
- **Database**: SQLite (메타), MySQL (Production)
- **AI**: OpenRouter (Gemini 3 Flash)
- **Math Rendering**: MathJax 3
- **Styling**: Cyberpunk-inspired Dark Theme

## 주의사항

- 로컬 환경 전용 (인증/보안 기능 없음)
- 작업 중 서버 재시작 시 진행 중인 작업은 실패 상태로 전환
- 제출 후에는 리뷰 수정 불가 (UI 잠금)

## 기존 CLI 유지

기존 `fix_problems.py`와 `update_problems.py`는 그대로 사용 가능합니다.

```bash
python fix_problems.py --group-ids group_ids.csv --output my_results.json
python update_problems.py my_results.json --execute
```
