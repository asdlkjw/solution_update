# Math Problem Fixer (Sisyphus)

이 도구는 수학 문제 데이터베이스의 오류(LaTeX 문법, 오타, 포맷팅 등)를 Google Gemini 2.0 Flash 모델을 사용하여 자동으로 수정하고, 결과를 검토 및 반영할 수 있는 시스템입니다. 기존 CLI 환경과 더불어 FastAPI 기반의 웹 UI를 제공하여 효율적인 리뷰 워크플로우를 지원합니다.

## 🚀 주요 기능

### 1. 코어 엔진 (Fixer)
- **DB 연동**: MySQL 프로덕션 데이터베이스에서 문제 데이터를 조회
- **AI 수정**: Gemini 3.0 Flash 모델을 사용하여 문제의 오류, 문법, 스타일을 자동으로 수정
- **병렬 처리**: ThreadPool을 사용하여 대량의 데이터를 고속으로 처리 (기본 32 workers)

### 2. 웹 인터페이스 (Sisyphus Web)
- **대시보드**: Group IDs를 입력하여 작업을 생성하고 관리
- **실시간 모니터링**: 작업 진행 상황과 에러 발생 여부를 실시간으로 확인
- **리뷰 시스템**: 수정 전/후 데이터를 비교하고 GOOD/BAD 여부를 판정
- **최종 제출**: 검토가 완료된 'GOOD' 데이터만 선별하여 프로덕션 DB에 일괄 반영

### 3. 리포트 및 결과물
- **JSON/HTML**: CLI 실행 시 구조화된 JSON 데이터와 시각적 비교 리포트(HTML) 생성

## 🛠️ 프로젝트 구조

```
.
├── app/                    # FastAPI 웹 서버 앱
│   ├── api/                # API 엔드포인트 (jobs, results, reviews)
│   ├── core/               # 비즈니스 로직 (fixer, updater, job_runner)
│   ├── db/                 # 데이터베이스 관리 (SQLite, schema.sql)
│   ├── models/             # Pydantic 데이터 모델
│   └── templates/          # UI 템플릿 (index, status, review)
├── fix_problems.py         # CLI: 문제 조회 및 수정 실행
├── update_problems.py      # CLI: 수정 결과를 DB에 반영
├── prompt_template.json    # LLM 프롬프트 템플릿
├── run_server.sh           # 웹 서버 실행 스크립트
├── pyproject.toml          # 의존성 및 프로젝트 설정
└── .env                    # 환경 변수 (DB 및 API Key)
```

## ⚙️ 환경 설정

### 1. 설치 (uv 사용 권장)
```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

### 2. 환경 변수 (.env)
```ini
OPENROUTER_API_KEY=sk-or-v1-...
DB_HOST=your-db-host
DB_PROD_PORT=3306
DB_USER=your-db-user
DB_PROD_PASSWORD=your-db-password
DB_NAME=your-db-name
```

## 🌐 웹 서버 사용 가이드

### 1. 서버 실행
```bash
./run_server.sh
```
접속 주소: `http://localhost:8000`

### 2. UI 워크플로우
1.  **입력 (Input)**: 메인 화면에서 처리할 문제의 `Group IDs`를 입력합니다. (공백, 개행, 쉼표 구분 가능)
2.  **진행률 (Progress)**: 작업이 생성되면 실시간으로 처리 현황(전체, 완료, 에러)을 확인합니다.
3.  **리뷰 (Review)**: 작업 완료 후 원본과 수정본을 비교 검토합니다.
    - **기본값**: 모든 결과는 기본적으로 **GOOD**으로 설정되어 있습니다.
    - **단축키**:
        - `1`: 현재 문제를 **GOOD**으로 설정
        - `2`: 현재 문제를 **BAD**으로 설정
        - `←` / `→`: 이전/다음 문제로 이동
4.  **최종 제출 (Submit)**: 리뷰를 마치고 '최종 제출'을 클릭하면 **GOOD** 판정을 받은 데이터만 MySQL 프로덕션 DB에 반영됩니다.

## 🏃 CLI 사용 가이드

### 기본 실행
```bash
# 문제 수정 실행
python fix_problems.py --ids 101,102,103 --output results.json

# DB 반영 실행
python update_problems.py results.json --execute
```

## 💾 데이터베이스 아키텍처

-   **SQLite (Meta DB)**: `app/db/app.db`에 저장되며, 웹 서버의 작업(Jobs) 상태와 임시 결과(Results), 리뷰 상태를 관리합니다.
-   **MySQL (Production DB)**: 실제 서비스 데이터가 담긴 원본 데이터베이스입니다. 최종 승인된 데이터만 이곳에 반영됩니다.

## 📡 API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/jobs` | 새로운 수정 작업 생성 |
| `GET` | `/jobs/{job_id}` | 작업 상태 및 진행률 조회 |
| `GET` | `/jobs/{job_id}/results` | 특정 작업의 전체 결과 리스트 조회 |
| `PATCH` | `/results/{result_id}` | 특정 결과의 리뷰 상태(GOOD/BAD) 업데이트 |
| `POST` | `/jobs/{job_id}/apply` | 검토 완료된 결과를 프로덕션 DB에 반영 |

## ⚠️ 주의사항

-   **로컬 전용**: 본 서버는 로컬 환경에서의 리뷰를 목적으로 하며 별도의 인증 시스템을 포함하고 있지 않습니다.
-   **API 비용**: OpenRouter를 통한 LLM 호출 시 비용이 발생하므로 대량 작업 전 테스트를 권장합니다.
-   **DB 부하**: 병렬 처리 Worker 수(`max_workers`)가 높을 경우 DB 연결 수 제한에 걸릴 수 있습니다.
