# Image Div Separation Post-Processor

## Context

### Original Request
question, refer 필드에서 `<img>` 태그가 다른 콘텐츠와 함께 `<div>` 안에 있을 때, 각각을 별도의 `<div>`로 분리하는 후처리 함수 추가

### Interview Summary
**Key Discussions**:
- 대상 필드: `question`, `refer` 만
- 다중 이미지: 각각 별도 `<div>`로 분리
- 순서: 원본 순서 유지
- 텍스트 노드: 텍스트도 별도 `<div>`로 감싸기
- 중첩 구조: 직계 자식만 처리 (`<p><img/></p>`는 `<p>` 전체를 분리)

**Research Findings (Metis)**:
- 기존 코드베이스는 regex 패턴 사용 (일관성 유지)
- `restore_field_div_classes` 패턴 참고 가능
- `<img>` vs `<img/>` 둘 다 매칭 필요

---

## Work Objectives

### Core Objective
`question`, `refer` 필드에서 혼합 콘텐츠가 있는 div를 분리하여 각 `<img>`와 기타 콘텐츠가 독립적인 `<div>`를 갖도록 함

### Concrete Deliverables
- `app/core/fixer.py`에 `separate_image_div()` 함수 추가
- `process_single_problem()` 파이프라인에 호출 추가

### Definition of Done
- [x] 혼합 콘텐츠 div가 올바르게 분리됨
- [x] 순서가 보존됨
- [x] 기존 후처리 함수들과 충돌 없음

### Must Have
- `<img>` 태그가 다른 콘텐츠와 함께 있을 때 분리
- 각 `<img>`는 자신만의 `<div class="X">` 획득
- 텍스트 노드도 별도 `<div class="X">`로 감싸기
- 모든 div 속성(class, id, style 등) 보존
- 원본 순서 유지

### Must NOT Have (Guardrails)
- 중첩된 div 처리 금지 (직계 자식만)
- `<img>`만 있는 div 수정 금지 (혼합 콘텐츠가 아님)
- 다른 필드 처리 금지 (`solution` 등)
- 외부 라이브러리 추가 금지 (BeautifulSoup 등)
- 요소 내부 콘텐츠 수정 금지 (구조 변경만)

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: NO
- **User wants tests**: Manual-only
- **Framework**: none

### Manual QA Procedures
서버 실행 후 Review UI에서 수정된 데이터 확인:
1. `./run_server.sh` 실행
2. 새 작업 생성 또는 기존 결과 확인
3. question, refer 필드의 HTML 구조 육안 검증

---

## Task Flow

```
Task 1 → Task 2 → Task 3
```

---

## TODOs

- [x] 1. `separate_image_div` 함수 구현

  **What to do**:
  - `app/core/fixer.py`에 함수 추가
  - `question`, `refer` 필드의 `<div class="question|reference">...</div>` 파싱
  - 직계 자식 레벨에서 `<img>` 태그와 기타 콘텐츠 분리
  - 각 요소(img, 텍스트, 다른 태그)를 별도 div로 감싸기
  - 빈 콘텐츠(공백만)는 무시

  **Must NOT do**:
  - 중첩된 구조 안으로 들어가지 않음
  - `<img>`만 있는 div 수정하지 않음
  - 요소 내부 콘텐츠 변경하지 않음

  **Parallelizable**: NO (첫 번째 태스크)

  **References**:
  
  **Pattern References**:
  - `app/core/fixer.py:302-325` - `restore_field_div_classes` 함수 (유사한 field_class_map 패턴)
  - `app/core/fixer.py:349-400` - `wrap_latex_content` 함수 (문자열 파싱 패턴)

  **API/Type References**:
  - 함수 시그니처: `def separate_image_div(fixed_data: Dict[str, Any]) -> Dict[str, Any]`

  **Implementation Hints**:
  - img 매칭: `<img\s+[^>]*/?>` (자가 닫힘 여부 모두 대응)
  - field_class_map: `{"question": "question", "refer": "reference"}`
  - 직계 자식 파싱: 태그 깊이(depth) 추적으로 최상위 요소만 식별
  - 텍스트 노드: img/태그 사이의 텍스트도 별도 div로

  **Acceptance Criteria**:

  **Manual Execution Verification:**
  
  - [ ] 케이스 1 - 기본 분리:
    - Input: `<div class="reference"><img src="x"/><ol><li>ㄱ</li></ol></div>`
    - Expected: `<div class="reference"><img src="x"/></div><div class="reference"><ol><li>ㄱ</li></ol></div>`
  
  - [ ] 케이스 2 - 이미지만 있는 경우 (변경 없음):
    - Input: `<div class="reference"><img src="x"/></div>`
    - Expected: 동일 (변경 없음)
  
  - [ ] 케이스 3 - 다중 이미지:
    - Input: `<div class="question"><img src="1"/><img src="2"/><p>text</p></div>`
    - Expected: `<div class="question"><img src="1"/></div><div class="question"><img src="2"/></div><div class="question"><p>text</p></div>`
  
  - [ ] 케이스 4 - 텍스트 노드 포함:
    - Input: `<div class="question">텍스트1<img src="x"/>텍스트2</div>`
    - Expected: `<div class="question">텍스트1</div><div class="question"><img src="x"/></div><div class="question">텍스트2</div>`
  
  - [ ] 케이스 5 - 중첩 img는 건드리지 않음:
    - Input: `<div class="reference"><p><img src="x"/></p><ol>...</ol></div>`
    - Expected: `<div class="reference"><p><img src="x"/></p></div><div class="reference"><ol>...</ol></div>`

  **Commit**: NO (그룹으로 커밋)

---

- [x] 2. `process_single_problem`에 호출 추가

  **What to do**:
  - `app/core/fixer.py`의 `process_single_problem` 함수에 `separate_image_div` 호출 추가
  - 위치: `restore_field_div_classes` 다음 (class가 있어야 복사 가능)

  **Must NOT do**:
  - 다른 후처리 함수 순서 변경하지 않음

  **Parallelizable**: NO (1번에 의존)

  **References**:
  
  **Pattern References**:
  - `app/core/fixer.py:780-795` - `process_single_problem` 함수 (현재 파이프라인)

  **Implementation Hints**:
  - 추가 위치: `restore_field_div_classes` 호출 바로 다음 줄
  - 코드: `fixed_data = separate_image_div(fixed_data)`

  **Acceptance Criteria**:

  - [ ] 함수가 파이프라인에 추가됨
  - [ ] 순서: `restore_field_div_classes` → `separate_image_div` → `wrap_latex_content`

  **Commit**: NO (그룹으로 커밋)

---

- [x] 3. 통합 테스트 및 커밋

  **What to do**:
  - 서버 실행하여 전체 동작 확인
  - 기존 결과 데이터로 분리 동작 육안 검증
  - 커밋

  **Parallelizable**: NO (1, 2에 의존)

  **References**:
  - `run_server.sh` - 서버 실행 스크립트
  - `http://localhost:8000` - Review UI

  **Acceptance Criteria**:

  **Manual Execution Verification:**
  - [ ] Using shell:
    - Command: `./run_server.sh`
    - Expected: 서버 정상 시작, 에러 없음
  
  - [ ] Using browser:
    - Navigate to: `http://localhost:8000`
    - Verify: Review UI 정상 로드
    - Check: question/refer 필드에서 img 분리 확인

  **Commit**: YES
  - Message: `feat(fixer): separate img tags into individual div wrappers`
  - Files: `app/core/fixer.py`
  - Pre-commit: 수동 검증 완료 후

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 3 | `feat(fixer): separate img tags into individual div wrappers` | app/core/fixer.py | Manual UI check |

---

## Success Criteria

### Verification Commands
```bash
./run_server.sh  # Expected: Server starts without errors
```

### Final Checklist
- [x] 혼합 콘텐츠 div가 분리됨
- [x] 순서 보존됨
- [x] 이미지만 있는 div는 변경 없음
- [x] 기존 기능에 영향 없음
