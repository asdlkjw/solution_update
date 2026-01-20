# Math Problem Fixer (Sisyphus)

이 도구는 수학 문제 데이터베이스의 오류(LaTeX 문법, 오타, 포맷팅 등)를 Google Gemini 2.0 Flash 모델을 사용하여 자동으로 수정하고, 결과를 JSON 및 HTML 리포트로 생성하는 자동화 스크립트입니다.

## 🚀 주요 기능

- **DB 연동**: MySQL 데이터베이스에서 문제 데이터를 조회
- **AI 수정**: Gemini 3.0 Flash 모델을 사용하여 문제의 오류, 문법, 스타일을 자동으로 수정
- **병렬 처리**: ThreadPool을 사용하여 대량의 데이터를 고속으로 처리 (기본 32 workers)
- **리포트 생성**:
  - `JSON`: 수정된 데이터를 구조화된 JSON 파일로 저장
  - `HTML`: 수정 전/후를 비교할 수 있는 시각적 리포트 생성 (MathJax 수식 렌더링 지원)

## 🛠️ 프로젝트 구조

```
.
├── fix_problems.py        # 메인 실행 스크립트
├── prompt_template.json   # LLM 프롬프트 템플릿 (System/User 메시지 정의)
├── report_template.html   # HTML 리포트 생성용 템플릿
├── pyproject.toml         # Python 프로젝트 및 의존성 설정 (uv 호환)
├── group_ids.csv          # (Optional) 처리할 문제 그룹 ID 목록
├── .env                   # 환경 변수 (DB 접속 정보, API Key)
└── README.md              # 프로젝트 문서
```

## ⚙️ 환경 설정

### 1. 필수 요구사항
- Python 3.9 이상
- `uv` (패키지 관리자) - 선택사항이지만 권장됨

### 2. 설치

**uv 사용 시 (권장):**
```bash
# 가상환경 생성 및 의존성 설치
uv venv
source .venv/bin/activate
uv pip install -r pyproject.toml
```

**pip 사용 시:**
```bash
pip install pymysql requests python-dotenv cryptography
```

### 3. 환경 변수 설정 (.env)
프로젝트 루트 또는 상위 디렉토리에 `.env` 파일을 생성하고 다음 정보를 입력하세요.

```ini
OPENROUTER_API_KEY=sk-or-v1-...
DB_HOST=your-db-host
DB_PROD_PORT=3306
DB_USER=your-db-user
DB_PROD_PASSWORD=your-db-password
DB_NAME=your-db-name
```

## 🏃 실행 방법

### 기본 실행 (문제 ID 직접 지정)
```bash
python fix_problems.py --ids 101,102,103
```

### CSV 파일로 실행 (Group ID 사용)
`group_ids.csv` 파일에 처리할 그룹 ID를 한 줄에 하나씩 작성한 후 실행합니다.

```bash
python fix_problems.py --group-ids group_ids.csv --output my_results.json
```

### 실행 옵션
- `--ids`: 처리할 문제 ID 리스트 (콤마로 구분)
- `--group-ids`: 처리할 그룹 ID가 담긴 CSV 파일 경로
- `--output`: 결과 저장 파일명 (기본값: `fixed_results.json`)

## 📊 결과물

실행이 완료되면 두 개의 파일이 생성됩니다:

1. **JSON 파일** (`my_results.json`): DB 업데이트용 구조화된 데이터
2. **HTML 파일** (`my_results.html`): 브라우저에서 바로 확인 가능한 비교 리포트
   - 좌측: 원본 데이터 (Original)
   - 우측: AI 수정 데이터 (Fixed)
   - 차이점(Diff) 하이라이팅 및 MathJax 수식 렌더링 지원

## 📝 커스터마이징

- **프롬프트 수정**: `prompt_template.json` 파일의 `system` 또는 `user` 값을 수정하여 AI의 수정 지침을 변경할 수 있습니다.
- **HTML 스타일 수정**: `report_template.html` 파일의 CSS를 수정하여 리포트 디자인을 변경할 수 있습니다.

## ⚠️ 주의사항

- **비용**: OpenRouter API를 사용하므로 토큰 비용이 발생할 수 있습니다.
- **DB 부하**: 병렬 처리를 사용하므로 DB 연결 수 제한에 주의하세요. 필요 시 `max_workers` 값을 조정하세요.
