# 프롬프트 풀이참조 예외 규칙 추가

## Context

### Original Request
`prompt_template.json`에 "풀이참조" 예외 규칙 추가 필요. 
정답이 "풀이참조"일 때 "따라서 정답은 풀이참조 이다." 같은 기계적 형식이 아니라, 
풀이 과정에서 도출된 실제 결론을 마지막 문장으로 써야 함.

### User Requirements
- **Wrong**: "따라서 정답은 풀이참조 이다."
- **Correct**: "따라서 주어진 조건을 만족한다.", "따라서 $f(x) = x^2 + 1$이다." 등 실제 결론

---

## Work Objectives

### Core Objective
`prompt_template.json`의 "Answer & Solution" 섹션에 "풀이참조 Exception" 규칙 추가

### Concrete Deliverables
- `prompt_template.json` 수정 (Short Answer 규칙 다음에 새 규칙 추가)

### Definition of Done
- [x] 파일 수정 완료
- [x] JSON 문법 유효성 확인
- [x] 커밋 완료

---

## Verification Strategy

### Test Decision
- **Infrastructure**: Manual verification (no automated tests for prompt)
- **Method**: JSON syntax validation

---

## TODOs

- [x] 1. prompt_template.json 수정 ✅ COMPLETED

  **What to do**:
  - "Short Answer" 규칙 바로 다음에 "풀이참조 Exception" 규칙 추가
  - JSON 이스케이프 처리 주의 (큰따옴표는 `\"`, 백슬래시는 `\\`)
  
  **Exact text to add** (after "Short Answer" line):
  ```
  - **풀이참조 Exception**: When the answer is \"풀이참조\", do NOT use the standard format. Instead, write a natural concluding sentence based on the actual conclusion derived from the solution process.\n    - Wrong: \"따라서 정답은 풀이참조 이다.\"\n    - Correct: \"따라서 [actual conclusion from solution] 이다.\" (e.g., \"따라서 주어진 조건을 만족한다.\", \"따라서 $f(x) = x^2 + 1$이다.\")
  ```
  
  **Must NOT do**:
  - JSON 문법 깨지지 않도록 주의
  - 기존 규칙 삭제 금지
  
  **Parallelizable**: NO

  **Commit**: YES
  - Message: `feat(prompt): add exception rule for 풀이참조 answers`

---

## Success Criteria

- [x] JSON 문법 유효성 확인: `python3 -m json.tool prompt_template.json > /dev/null`
- [x] 추가된 규칙이 올바른 위치에 있음
- [x] 커밋 완료
