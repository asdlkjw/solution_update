# Sisyphus Web Server 개발 로드맵

이 문서는 Math Problem Fixer 시스템을 CLI에서 웹 기반 서비스로 확장하기 위한 단계별 개발 계획을 정리합니다.

## 1단계: 설계 및 기반 구조 구축 (Architecture & DB)

### 아키텍처 설계
- **프레임워크**: FastAPI (비동기 처리 및 빠른 API 개발)
- **비즈니스 로직**: 기존 `fix_problems.py` 로직을 `app.core` 모듈로 분리 및 재사용
- **DB 이중화**:
  - **Meta DB (SQLite)**: 작업 상태(status), 리뷰 결과(human_review), 임시 데이터 저장
  - **Production DB (MySQL)**: 최종 승인된 데이터만 반영되는 원천 데이터베이스

### 데이터베이스 스키마 (SQLite)
- `jobs` 테이블: `id`, `input_type`, `input_value`, `status`, `total_count`, `processed_count`, `error_count`, `output_json_path`, `output_html_path`
- `results` 테이블: `id`, `job_id`, `original_id`, `group_id`, `original_json`, `fixed_json`, `human_review` (기본값: GOOD)

## 2단계: API 및 백그라운드 워커 구현 (API & Background)

### 핵심 API 엔드포인트
- `POST /jobs`: 새로운 작업 큐 등록 및 백그라운드 실행 트리거
- `GET /jobs/{job_id}`: 작업 진행률 조회용
- `GET /jobs/{job_id}/results`: 리뷰를 위한 수정 데이터 조회
- `PATCH /results/{result_id}`: 사용자 리뷰(GOOD/BAD) 저장
- `POST /jobs/{job_id}/apply`: 최종 DB 반영 로직 실행

### 비동기 작업 처리
- `ThreadPoolExecutor`를 활용하여 FastAPI 요청과 독립적으로 LLM 수정 작업 수행
- 작업 상태 변화를 SQLite에 실시간 기록

## 3단계: 프론트엔드 UI 개발 (UI/UX)

### 주요 화면 구성
- **Dashboard (index)**: 다중 ID 입력 인터페이스 및 작업 생성
- **Status (progress)**: 프로그레스 바를 통한 실시간 진행 현황 가시화
- **Reviewer (review)**: 
  - 원본 vs 수정본 병렬 배치 (Diff 강조)
  - MathJax를 이용한 수식 렌더링
  - 키보드 단축키(1, 2, 방향키)를 통한 고속 리뷰 환경 구축

## 4단계: 검증 및 배포 준비 (Test & Deployment)

### 테스트 전략
- **기능 테스트**: API 엔드포인트별 정상 동작 확인
- **통합 테스트**: 작업 생성부터 최종 DB 반영까지의 전체 흐름 검증
- **예외 처리**: DB 연결 실패, API 타임아웃, LLM 응답 오류 시나리오 대응

### 배포 환경 구성
- `run_server.sh`를 통한 원클릭 실행 환경 제공
- 환경 변수(`.env`) 관리 가이드 작성
- 의존성 관리 최적화 (`pyproject.toml`, `uv`)

## 5단계: 향후 확장 계획
- 다중 사용자 세션 지원 (로그인 기능)
- 과거 작업 이력(History) 조회 기능
- LLM 프롬프트 웹 UI 상에서 직접 튜닝 기능
- 에러 발생 건에 대한 재시도(Retry) 기능
