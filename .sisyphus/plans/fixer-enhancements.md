# Fixer 후처리 함수 및 프롬프트 개선

## Context

### Original Request
수학 문제 수정 시스템(Sisyphus)의 후처리 로직 추가 및 LLM 프롬프트 개선:
1. 누락된 이미지 태그 복원
2. 선택지 LaTeX 자동 감싸기
3. `<표>`, `<보기>`, `<조건>` 마커 제거
4. "표 참고", "그래프 참고" → "해설 참고" 통일
5. 프롬프트에 정답/풀이 일치 강조, 다중 답안 형식 등 추가

### Interview Summary
**Key Discussions**:
- 데이터 접근: `restore_missing_images`만 `process_single_problem`에서 특별 처리 (original + fixed)
- 코드 동기화: `app/core/fixer.py`만 수정 (CLI는 별도 작업)
- LaTeX 감싸기: $가 0개 또는 1개이고 영문/숫자/기호만 있을 때 적용
- 마커 제거: refer 필드에서만, question에 해당 단어 없을 때 제거
- 참고 텍스트 통일: answer/solution 필드에서만 적용

**Research Findings**:
- 기존 후처리 함수: `normalize_answer`, `normalize_html_wrappers`, `unescape_html_tags`, `normalize_refer_view_header`
- 모든 함수 시그니처: `def func(fixed_data: Dict[str, Any]) -> Dict[str, Any]`
- `process_single_problem()` 함수에서 순차적으로 호출됨

### Metis Review
**Identified Gaps** (addressed):
- 이미지 복원 시 original 데이터 필요 → `process_single_problem`에서 별도 호출
- 코드 중복 (fix_problems.py vs fixer.py) → app/core/fixer.py만 수정
- LaTeX 감싸기 범위 불명확 → $가 0-1개이고 영문/숫자/기호만 있을 때로 정의

---

## Work Objectives

### Core Objective
LLM 수정 결과의 품질을 높이기 위해 후처리 함수를 추가하고, 프롬프트를 개선하여 더 정확한 출력을 유도합니다.

### Concrete Deliverables
- `app/core/fixer.py`: 5개의 새 후처리 함수 추가 + `process_single_problem` 업데이트
- `prompt_template.json`: 4개의 새 규칙 추가

### Definition of Done
- [x] 모든 새 후처리 함수가 `fixer.py`에 추가됨
- [x] `process_single_problem()`이 새 함수들을 올바른 순서로 호출
- [x] 프롬프트에 새 규칙이 추가됨
- [x] 웹 서버 실행 시 에러 없이 동작 (`./run_server.sh`)

### Must Have
- 이미지 복원 기능
- LaTeX 자동 감싸기
- 마커 제거 (`<표>`, `<보기>`, `<조건>`)
- 참고 텍스트 통일
- 프롬프트 개선 (정답/풀이 일치, 원본 언급 금지, 다중 답안 형식)

### Must NOT Have (Guardrails)
- `fix_problems.py` (루트) 수정 금지 - app/core/fixer.py만 수정
- 기존 후처리 함수 로직 변경 금지 - 새 함수만 추가
- JSON 스키마 또는 LLM API 통합 변경 금지
- 새 의존성 추가 금지
- 테스트 코드 작성 금지 (별도 요청 시에만)
- UI/템플릿 파일 수정 금지

---

## Verification Strategy (MANDATORY)

### Test Decision
- **Infrastructure exists**: NO (테스트 프레임워크 미설정)
- **User wants tests**: Manual-only
- **Framework**: none

### Manual QA

각 TODO 완료 후 수동 검증:

**검증 방법**:
1. 웹 서버 실행: `./run_server.sh`
2. 브라우저에서 `http://localhost:8000` 접속
3. 테스트용 group_id 입력하여 작업 생성
4. 결과 리뷰 화면에서 후처리 적용 확인

---

## Task Flow

```
Task 1 (이미지 복원) → Task 2 (마커 제거) → Task 3 (LaTeX 감싸기)
                                              ↓
Task 4 (참고 텍스트 통일) → Task 5 (process_single_problem 연결)
                                              ↓
Task 6 (프롬프트 수정)
```

## Parallelization

| Task | Depends On | Reason |
|------|------------|--------|
| 1-4 | None | 독립적인 함수 추가 |
| 5 | 1-4 | 새 함수들을 연결해야 함 |
| 6 | None | 프롬프트는 독립적 |

---

## TODOs

- [x] 1. 이미지 복원 함수 추가 (`restore_missing_images`)

  **What to do**:
  - `app/core/fixer.py`에 `restore_missing_images(original_data, fixed_data)` 함수 추가
  - 원본의 각 필드에서 `<img src="..."/>` 패턴 추출
  - fixed에 해당 이미지가 없으면 필드 앞에 추가
  - 체크할 필드: question, refer, choice1~5, answer, solution

  **Must NOT do**:
  - 기존 함수 시그니처 변경 금지
  - 이미지 URL 수정 금지

  **Parallelizable**: YES (with 2, 3, 4, 6)

  **References**:
  - `app/core/fixer.py:289-305` - `unescape_html_tags` 패턴 (필드 순회 방식)
  - `app/core/fixer.py:250-269` - `normalize_answer` 패턴 (함수 구조)

  **Acceptance Criteria**:
  - [ ] 함수가 `app/core/fixer.py`에 추가됨
  - [ ] `lsp_diagnostics`로 문법 오류 없음 확인
  - [ ] 테스트: 원본에 `<img src="test.png"/>`가 있고 fixed에 없을 때 복원되는지 확인

  **Commit**: NO (groups with 5)

---

- [x] 2. 마커 제거 함수 추가 (`remove_refer_markers`)

  **What to do**:
  - 기존 `normalize_refer_view_header` 확장 또는 새 함수 생성
  - `<표>`, `<보기>`, `<조건>` 마커 제거
  - refer 필드에서만 적용
  - question에 해당 단어(조\s*건, 보\s*기, 표)가 없을 때만 제거
  - 패턴: `<p>&lt;표&gt;</p>`, `&lt;표&gt;`, `<표>` 등

  **Must NOT do**:
  - question 필드 수정 금지
  - 기존 `normalize_refer_view_header` 삭제 금지

  **Parallelizable**: YES (with 1, 3, 4, 6)

  **References**:
  - `app/core/fixer.py:308-329` - `normalize_refer_view_header` (확장 대상)

  **Acceptance Criteria**:
  - [ ] 함수가 `app/core/fixer.py`에 추가됨
  - [ ] `<표>`, `<보기>`, `<조건>` 패턴이 refer에서 제거됨
  - [ ] question에 해당 단어가 있으면 제거하지 않음

  **Commit**: NO (groups with 5)

---

- [x] 3. LaTeX 감싸기 함수 추가 (`wrap_choice_latex`)

  **What to do**:
  - choice1~5 필드 대상
  - 조건: $가 0개 또는 1개이고 영문/숫자/기호($ 제외)만 있을 때
  - 전체 내용을 `${content}$`로 감싸기
  - HTML 태그가 있으면 스킵 (복잡한 케이스)
  - 한글이 포함되면 스킵

  **Must NOT do**:
  - 이미 $로 완전히 감싸진 경우 중복 감싸기 금지
  - answer, solution 필드 처리 금지

  **Parallelizable**: YES (with 1, 2, 4, 6)

  **References**:
  - `app/core/fixer.py:272-286` - `normalize_html_wrappers` (choice 필드 처리 패턴)

  **Acceptance Criteria**:
  - [ ] 함수가 `app/core/fixer.py`에 추가됨
  - [ ] `2x+1` → `$2x+1$` 변환됨
  - [ ] `$x^2$` (이미 있음) → 변경 없음
  - [ ] `가` (한글) → 변경 없음

  **Commit**: NO (groups with 5)

---

- [x] 4. 참고 텍스트 통일 함수 추가 (`normalize_reference_text`)

  **What to do**:
  - answer, solution 필드 대상
  - 패턴 변환:
    - "표 참고" → "해설 참고"
    - "그래프 참고" → "해설 참고"
    - "그림 참고" → "해설 참고"
    - "도표 참고" → "해설 참고"
    - "표를 참고" → "해설을 참고"
    - "그래프를 참고" → "해설을 참고"
    - "그림을 참고" → "해설을 참고"

  **Must NOT do**:
  - question, refer 필드 처리 금지
  - "참고" 단어 자체 제거 금지

  **Parallelizable**: YES (with 1, 2, 3, 6)

  **References**:
  - `app/core/fixer.py:289-305` - `unescape_html_tags` (패턴 치환 방식)

  **Acceptance Criteria**:
  - [ ] 함수가 `app/core/fixer.py`에 추가됨
  - [ ] solution에 "표 참고" → "해설 참고" 변환됨
  - [ ] question의 "표 참고"는 변경 없음

  **Commit**: NO (groups with 5)

---

- [x] 5. `process_single_problem` 업데이트

  **What to do**:
  - 새 후처리 함수들을 호출 순서에 맞게 추가
  - `restore_missing_images`는 original 데이터도 전달
  - 호출 순서:
    1. `fix_content_with_llm(problem)` - 기존
    2. `restore_missing_images(problem, fixed_data)` - **NEW** (original 필요)
    3. `normalize_answer(fixed_data)` - 기존
    4. `unescape_html_tags(fixed_data)` - 기존
    5. `normalize_refer_view_header(fixed_data)` - 기존
    6. `remove_refer_markers(fixed_data)` - **NEW** (또는 기존 확장)
    7. `normalize_html_wrappers(fixed_data)` - 기존
    8. `wrap_choice_latex(fixed_data)` - **NEW**
    9. `normalize_reference_text(fixed_data)` - **NEW**

  **Must NOT do**:
  - 기존 함수 호출 순서 변경 금지
  - return 구조 변경 금지

  **Parallelizable**: NO (depends on 1-4)

  **References**:
  - `app/core/fixer.py:332-346` - `process_single_problem` (수정 대상)

  **Acceptance Criteria**:
  - [ ] `process_single_problem`이 모든 새 함수를 호출
  - [ ] `restore_missing_images`에 original 데이터 전달됨
  - [ ] `lsp_diagnostics`로 문법 오류 없음 확인
  - [ ] 서버 실행 후 정상 동작 확인: `./run_server.sh`

  **Commit**: YES
  - Message: `feat(fixer): add post-processing functions for image, latex, markers`
  - Files: `app/core/fixer.py`
  - Pre-commit: `./run_server.sh` 실행 후 에러 없음

---

- [x] 6. 프롬프트 수정 (`prompt_template.json`)

  **What to do**:
  - 다음 규칙 추가:
    1. **정답/풀이 일치 필수**: "The final answer in `solution` MUST match the `answer` field value exactly."
    2. **원본 언급 금지**: "NEVER reference or mention the original content in your fixed version. Write as if it's new content."
    3. **다중 답안 형식**: "For multiple answers, use comma-space separator: `1, 3` (not `1,3` or `1 3`)."
    4. **보기/조건 표시**: "If the question mentions '보기' (examples) or '조건' (conditions), add `<p>&lt;보기&gt;</p>` or `<p>&lt;조건&gt;</p>` header at the top of the `refer` field."

  **Must NOT do**:
  - 기존 규칙 삭제 금지
  - JSON 구조 변경 금지 (system, user 키 유지)
  - 한국어로 작성 금지 (영어 유지)

  **Parallelizable**: YES (with 1-4)

  **References**:
  - `prompt_template.json:1-4` - 전체 구조

  **Acceptance Criteria**:
  - [ ] 4개의 새 규칙이 system 프롬프트에 추가됨
  - [ ] JSON 파싱 오류 없음 (`python -c "import json; json.load(open('prompt_template.json'))"`)
  - [ ] 기존 규칙과 충돌 없음

  **Commit**: YES
  - Message: `feat(prompt): add rules for answer consistency and format`
  - Files: `prompt_template.json`
  - Pre-commit: JSON 파싱 확인

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 5 | `feat(fixer): add post-processing functions for image, latex, markers` | `app/core/fixer.py` | `./run_server.sh` |
| 6 | `feat(prompt): add rules for answer consistency and format` | `prompt_template.json` | JSON 파싱 확인 |

---

## Success Criteria

### Verification Commands
```bash
# 서버 실행 확인
./run_server.sh  # Expected: "Uvicorn running on http://0.0.0.0:8000"

# JSON 파싱 확인
python -c "import json; json.load(open('prompt_template.json'))"  # Expected: no error

# Python 문법 확인
python -c "from app.core.fixer import process_single_problem"  # Expected: no error
```

### Final Checklist
- [x] 모든 새 후처리 함수 추가됨 (5개)
- [x] `process_single_problem`이 새 함수 호출
- [x] 프롬프트에 새 규칙 추가됨 (4개)
- [x] 서버 정상 실행
- [x] 기존 기능 동작 유지
