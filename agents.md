# Problem Fix Agent

## 개요
DB의 `problem` 테이블에서 데이터를 조회하여 OpenRouter(Gemini 3 Flash)를 통해 오류를 수정하고, 결과를 구조화된 JSON으로 저장하는 도구입니다.

## 환경 설정 (.env)
다음 환경 변수가 필요합니다:
- `OPENROUTER_API_KEY`: LLM API 키
- `DB_HOST`: 데이터베이스 호스트
- `DB_PROD_PORT`: 포트 번호
- `DB_USER`: 사용자 ID
- `DB_PROD_PASSWORD`: 비밀번호
- `DB_NAME`: DB 이름

## 기능
1. **Fetch**: 입력된 ID 리스트로 DB 데이터 조회
2. **Process**: 데이터를 JSON으로 조합해 LLM 전송 (오류 수정 요청)
3. **Save**: 응답받은 구조화된 JSON을 파일로 저장

## 실행 예시
```bash
python scripts/fix_problems.py --ids 101,102,103
```
