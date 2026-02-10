# V2 Pipeline Differentiation Plan

## 1. Context

### Original Request
V2 파이프라인을 V1과 차별화. 현재 V2는 V1과 동일한 placeholder. Input 통합 (question_context), Output에서 refer 필드 제거, question에 refer 내용 통합.

### Interview Summary
- **목적**: question과 refer가 분리되어 있어 자연스러운 문제 생성이 안 됨. refer가 question 사이에 들어가야 하는 경우가 있는데 컬럼 분리로 구조적 자유 억압.
- **Input 변경**: `question_context` (question + refer + choice1~5 통합), `solution`, `answer` 3가지로 통합하여 LLM에 전달
- **Output 변경**: refer 필드 제거, question에 refer 내용 통합 (div class="question", div class="reference" HTML class 유지)
- **제약**: V1 코드에 영향 없어야 함

### Research Findings (Codebase Analysis)

**현재 아키텍처:**
- `app/core/pipelines/registry.py`: `register_pipeline(version, process_fn)` / `get_pipeline(version)` 패턴
- `app/core/pipelines/v1.py`: `fixer.process_single_problem`을 그대로 등록
- `app/core/pipelines/v2.py`: V1과 동일한 placeholder
- `app/core/fixer.py`: `process_single_problem()` -> `fix_content_with_llm()` -> 18개 후처리 -> `judge_fixed_output()` -> 최대 2회 재시도
- `app/core/job_runner.py`: `get_pipeline(version)`으로 process_fn을 가져와서 ThreadPoolExecutor에서 실행
- `prompt_template.json`: system/user 키로 V1 프롬프트 관리
- `app/core/updater.py`: `update_problems_from_results()` - fixed_json에서 refer 포함 10개 필드를 MySQL problem 테이블에 업데이트

**refer 필드를 직접 참조하는 후처리 함수 (10개):**
1. `restore_missing_images` - original의 refer에서 이미지 복원 -> fixed의 refer에 삽입
2. `validate_image_tags` - refer 필드 이미지 검증
3. `normalize_lt_spacing` - refer 필드 `<` 뒤 공백 처리
4. `restore_latex_control_char_fields` - refer 필드 LaTeX 제어문자 복원
5. `normalize_latex_backslashes` - refer 필드 이중 백슬래시 정규화
6. `normalize_refer_view_header` - refer에서 `<보기>` 헤더 처리
7. `remove_refer_markers` - refer에서 `<표>`, `<조건>` 마커 제거
8. `restore_field_div_classes` - refer에 `class="reference"` 추가
9. `separate_image_div` - refer에서 이미지 div 분리
10. `remove_duplicate_reference_div` - refer 중복 div 제거

**refer를 참조하지 않지만 fields 리스트에 "refer"가 있는 함수:**
- `normalize_empty_brackets` - fields 리스트에 refer 포함
- `add_displaystyle_to_binom` - fields 리스트에 refer 포함

**DB 구조:**
- MySQL `problem` 테이블: id, group_id, type, question, refer, choice1~5, answer, solution, human_review
- SQLite `results` 테이블: fixed_json (JSON blob으로 저장)
- `updater.py`의 `fields_to_update` 리스트에 refer 포함

**review.html:**
- `UPDATE_FIELDS` 배열에 refer 포함
- `renderPanel`에서 refer 필드를 렌더링 (값이 null이면 스킵)

---

## 2. Architecture Decisions

### Decision 1: V2 프롬프트 저장 위치
**결정: `prompt_template.json`에 `system_v2` / `user_v2` 키 추가**
- 근거: 별도 파일(prompt_template_v2.json) 대신 같은 파일에 V2 키를 추가하면 관리 포인트가 1개로 유지됨
- `fix_content_with_llm_v2()`에서 `prompts["system_v2"]`, `prompts["user_v2"]`를 읽음

### Decision 2: V2 process function 위치
**결정: `app/core/pipelines/v2.py`에 독립 구현**
- 근거: fixer.py에 새 함수를 추가하면 V1과 V2가 하나의 파일에 뒤섞여 복잡해짐. v2.py에 V2 전용 함수들을 모아서 독립적으로 관리.
- `v2.py`에 `process_single_problem_v2()`, `fix_content_with_llm_v2()`, `judge_fixed_output_v2()` 구현
- fixer.py에서 재사용할 함수들은 import하여 사용

### Decision 3: V2 후처리 체인
**결정: V1 함수 중 refer-independent 함수는 import하여 재사용, refer-specific 함수는 skip 또는 question 대상으로 수정**

| V1 함수 | V2 처리 |
|---------|---------|
| `restore_missing_images` | **수정 재구현**: original의 refer 이미지를 fixed의 question으로 복원 |
| `validate_image_tags` | **재사용**: fields 리스트에서 refer 제거, question에 통합되어 있으므로 question에서 처리 |
| `normalize_answer` | **재사용**: refer 무관 |
| `unescape_html_tags` | **재사용**: 모든 필드 대상이므로 그대로 |
| `normalize_lt_spacing` | **재사용**: fields 리스트에서 refer 제거 |
| `restore_latex_control_char_fields` | **재사용**: LATEX_CONTROL_CHAR_FIELDS 리스트 사용, refer 포함이지만 없으면 skip |
| `normalize_latex_backslashes` | **재사용**: fields 리스트에서 refer 제거 |
| `normalize_refer_view_header` | **SKIP**: V2에서는 refer가 question에 통합되므로 불필요 |
| `remove_refer_markers` | **SKIP**: 동일 이유 |
| `normalize_html_wrappers` | **재사용**: refer 무관 |
| `wrap_short_answer_with_math_delimiters` | **재사용**: refer 무관 |
| `normalize_empty_brackets` | **재사용**: fields에 refer 있지만 없으면 skip |
| `restore_field_div_classes` | **수정 재구현**: V2에서는 question 내부에 class="reference" div가 있을 수 있으므로 question에만 class="question" 적용 |
| `separate_image_div` | **수정 재구현**: question 필드에 대해서만 동작, class="reference" div도 포함 |
| `wrap_latex_content` | **재사용**: choice 필드만 대상 |
| `normalize_reference_text` | **재사용**: answer/solution만 대상 |
| `remove_duplicate_reference_div` | **SKIP**: V2에서는 refer 필드 없음 |
| `add_displaystyle_to_binom` | **재사용**: fields에 refer 있지만 없으면 skip |

### Decision 4: V2 Output Schema
**결정: refer 필드 없이 question에 통합된 HTML**
```json
{
  "type": "string (multiple_choice | short_answer)",
  "question": "string (div class='question' + div class='reference' 내용 통합)",
  "choice1": "string | null",
  "choice2": "string | null",
  "choice3": "string | null",
  "choice4": "string | null",
  "choice5": "string | null",
  "answer": "string",
  "solution": "string | null"
}
```
- `required`: type, question, choice1~5, answer, solution (refer 제거)
- question 내부에 `<div class="question">...</div>` 와 `<div class="reference">...</div>` 가 공존 가능

### Decision 5: question_context 조합 로직
**결정: V2 LLM Input 구조**
```json
{
  "question_context": "<원본 question>\n\n<원본 refer (있으면)>\n\n<choice1~5 (있으면)>",
  "solution": "<원본 solution>",
  "answer": "<원본 answer>"
}
```
- `question_context` = question + (refer가 있으면 "\n\n" + refer) + (각 choice가 있으면 "\n\nchoice1: " + choice1 ...)
- type은 별도로 전달하지 않고 question_context 안에 choice 유무로 LLM이 판단하도록 함 -> **아니요, type은 명시적으로 전달해야 안전함**
- 수정: `type`도 input에 포함

최종 V2 LLM Input:
```json
{
  "type": "multiple_choice | short_answer",
  "question_context": "question + refer + choice1~5 통합 텍스트",
  "answer": "원본 answer",
  "solution": "원본 solution"
}
```

### Decision 6: DB 업데이트 (updater.py) 처리
**결정: V2 결과의 경우 refer 필드를 null로 설정**
- V2 fixed_json에는 refer 키가 없음
- `updater.py`의 `fields_to_update`에 refer가 있지만, `if field in fixed_json` 조건으로 refer가 없으면 자동 skip
- 단, 기존 DB의 refer 값이 남아있게 됨 -> **V2에서는 refer를 명시적으로 null로 설정해야 함**
- V2 process function에서 fixed_data에 `"refer": None`을 명시적으로 추가하여 DB 업데이트 시 null로 덮어씀

### Decision 7: review.html 처리
**결정: 변경 불필요**
- refer가 null이면 `renderField`에서 `if (value === null || value === undefined) return '';`로 자동 스킵
- V2 결과에서 refer가 null이므로 REFER 필드는 표시되지 않음
- question 안에 `<div class="reference">` 가 포함되어 있어 시각적으로 구분 가능

### Decision 8: Judge 프롬프트 (V2)
**결정: V2 전용 judge -- `JUDGE_SYSTEM_PROMPT_V2` 상수를 `v2.py` 상단에 정의**
- V1은 fixer.py 라인 39에 `JUDGE_SYSTEM_PROMPT` 상수로 정의됨
- V2는 `app/core/pipelines/v2.py` 파일 상단에 `JUDGE_SYSTEM_PROMPT_V2` 상수를 정의
- 근거: V2 judge 로직은 v2.py 내부에서만 사용되므로 같은 파일에 두는 것이 응집도 높음. prompt_template.json은 LLM 호출용 프롬프트 전용으로 유지하고, judge 프롬프트는 코드 상수로 관리 (V1 패턴 동일)

**V2 Judge 프롬프트 텍스트 (V1과의 차이):**

V1 원문:
```
"너는 수학 문제 수정 결과를 검수하는 심사자다. 원본과 수정본을 비교해서 품질을 판단한다.
다음 항목을 엄격히 확인하라: 필수 조건 누락(특히 question/refer),
question이 없는데 refer만 존재, LaTeX 수식 깨짐, HTML 태그 불완전/잘못된 중첩,
가독성 저하(문장 붕괴, 의미 모호). 통과면 pass=true와 매우 짧은 reason을 주고,
실패면 pass=false와 짧고 명확한 이유를 한국어로 적어라."
```

V2 변경본 (`JUDGE_SYSTEM_PROMPT_V2`):
```
"너는 수학 문제 수정 결과를 검수하는 심사자다. 원본과 수정본을 비교해서 품질을 판단한다.
다음 항목을 엄격히 확인하라: question 필드 누락 또는 비어있음,
question 내부에 <div class=\"question\">과 <div class=\"reference\"> 구조가 올바른지
(reference 내용이 있는 경우 반드시 <div class=\"reference\">로 감싸져 있어야 함),
LaTeX 수식 깨짐, HTML 태그 불완전/잘못된 중첩,
가독성 저하(문장 붕괴, 의미 모호). 이 버전에서는 refer 필드가 없고 question에 통합되어 있다.
통과면 pass=true와 매우 짧은 reason을 주고,
실패면 pass=false와 짧고 명확한 이유를 한국어로 적어라."
```

핵심 차이점:
1. "필수 조건 누락(특히 question/refer)" -> "question 필드 누락 또는 비어있음" (refer 언급 제거)
2. "question이 없는데 refer만 존재" -> question 내부 div 구조 검증으로 대체
3. "이 버전에서는 refer 필드가 없고 question에 통합되어 있다" 문맥 추가
4. `<div class="reference">` 존재 여부 확인 규칙 추가

---

## 3. Must Have / Must NOT Have

### Must Have
- V2 전용 `question_context` input 조합 로직
- V2 전용 프롬프트 (system_v2, user_v2) in prompt_template.json
- V2 전용 output JSON schema (refer 필드 없음)
- V2 전용 후처리 체인 (refer 관련 함수 skip/수정)
- V2 전용 judge (refer 없는 구조에 맞춘 검증)
- `<div class="question">`, `<div class="reference">` HTML class 유지
- V2 fixed_data에 `"refer": None` 명시적 설정
- V1 코드 무변경

### Must NOT Have
- fixer.py 변경 (V1 영향 방지)
- 새로운 DB 마이그레이션 (기존 schema로 충분)
- review.html 변경 (기존 null 처리로 충분)
- prompt_template.json의 기존 system/user 키 변경

---

## 4. Detailed TODO Tasks

### TASK 1: prompt_template.json에 V2 프롬프트 추가
**File:** `/Users/classday/workplace/scripts/prompt_template.json`
**Changes:**
- `system_v2` 키 추가: V2 전용 시스템 프롬프트
  - 핵심 차이: Input이 `question_context` (question+refer+choices 통합)로 들어옴을 명시
  - Output에서 refer 필드 없음을 명시
  - question 필드 안에 `<div class="question">` 와 `<div class="reference">` 를 모두 포함해야 함을 명시
  - 나머지 규칙 (LaTeX, HTML, 용어 등)은 V1과 동일하게 유지
- `user_v2` 키 추가: V2 전용 유저 프롬프트
  - `{json_data}` placeholder 사용 (V1과 동일 패턴)

**system_v2 프롬프트 핵심 차이점:**
1. "Input Data는 `type`, `question_context`, `answer`, `solution` 4개 필드로 구성됨"
2. "`question_context`는 원본의 question, refer(보기/조건), choice1~5를 통합한 텍스트임"
3. **"`question_context` 내부에서 `[문제]`, `[보기/조건]`, `[선택지]` 섹션 마커로 각 부분이 구분되어 있음. `[문제]` 뒤에 문제 본문, `[보기/조건]` 뒤에 보기/조건 텍스트 (없으면 해당 섹션 생략), `[선택지]` 뒤에 번호가 매겨진 선택지 목록 (없으면 해당 섹션 생략)"** *(Issue 5 해결)*
4. "Output의 `question` 필드에는 문제 본문과 보기/조건을 자연스럽게 통합하여 작성"
5. "question 내에서 보기/조건 부분은 `<div class=\"reference\">...</div>`로 감싸고, 문제 본문은 `<div class=\"question\">...</div>`로 감싸야 함"
6. "Output에 `refer` 필드가 없음 - question에 통합됨"
7. "choice1~5는 input의 question_context `[선택지]` 섹션에 포함되어 있으나, output에서는 별도 필드로 분리하여 반환"

**Acceptance Criteria:**
- [x] prompt_template.json이 유효한 JSON
- [x] system_v2, user_v2 키 존재
- [x] 기존 system, user 키 무변경
- [x] V2 프롬프트에 question_context input 설명 포함
- [x] V2 프롬프트에 `[문제]`/`[보기/조건]`/`[선택지]` 섹션 마커 설명 포함
- [x] V2 프롬프트에 refer 없는 output 명시
- [x] V2 프롬프트에 div class="question"/class="reference" 유지 규칙 명시

---

### TASK 2: v2.py에 V2 전용 process function 구현
**File:** `/Users/classday/workplace/scripts/app/core/pipelines/v2.py`
**Changes:** 전체 재작성

**구현할 함수:**

#### 2a. `build_question_context(problem: Dict) -> str`
- `problem["question"]` + `problem["refer"]` (있으면) + `problem["choice1"]`~`problem["choice5"]` (있으면) 통합
- 형식 (**`[문제]`/`[보기/조건]`/`[선택지]` 마커 사용 -- system_v2 프롬프트에서도 이 마커를 설명함**):
  ```
  [문제]
  {question}

  [보기/조건]  (refer가 있을 때만)
  {refer}

  [선택지]  (choice가 있을 때만)
  1. {choice1}
  2. {choice2}
  ...
  ```

#### 2b. `fix_content_with_llm_v2(problem_data: Dict, judge_feedback: str | None = None) -> Dict`
- fixer.py의 `fix_content_with_llm`과 유사하되:
  - Input: `type`, `question_context` (build_question_context로 생성), `answer`, `solution`
  - 프롬프트: `prompts["system_v2"]`, `prompts["user_v2"]`
  - Output JSON schema: refer 필드 없음
    ```python
    json_schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["multiple_choice", "short_answer"]},
            "question": {"type": "string"},
            "choice1": {"type": ["string", "null"]},
            "choice2": {"type": ["string", "null"]},
            "choice3": {"type": ["string", "null"]},
            "choice4": {"type": ["string", "null"]},
            "choice5": {"type": ["string", "null"]},
            "answer": {"type": "string"},
            "solution": {"type": ["string", "null"]},
        },
        "required": ["type", "question", "choice1", "choice2", "choice3", "choice4", "choice5", "answer", "solution"],
        "additionalProperties": False,
    }
    ```
  - 나머지 API 호출 로직 (retry, error handling)은 fixer.py에서 복사

#### 2c. `judge_fixed_output_v2(original: Dict, fixed: Dict) -> Dict`
- fixer.py의 `judge_fixed_output`과 유사하되:
  - original_payload에서 refer 제거
  - fixed_payload에서 refer 제거
  - **`JUDGE_SYSTEM_PROMPT_V2` 상수 사용 (v2.py 파일 상단에 정의, Decision 8 참조)** *(Issue 4 해결)*

#### 2d. `_v2_restore_missing_images(original_data: Dict, fixed_data: Dict) -> Dict`

*(Issue 1 해결 -- 정확한 필드 매핑 테이블 및 pseudo-code)*

**이미지 복원 필드 매핑 테이블:**

| Original 필드 | Fixed 복원 대상 필드 | 유형 | 설명 |
|---------------|---------------------|------|------|
| `original.question` | `fixed.question` | SAME-FIELD | 문제 본문 이미지 복원 |
| `original.refer` | `fixed.question` | **CROSS-FIELD** | 보기/조건 이미지가 question에 통합됨 |
| `original.choice1` | `fixed.choice1` | SAME-FIELD | 선택지1 이미지 복원 |
| `original.choice2` | `fixed.choice2` | SAME-FIELD | 선택지2 이미지 복원 |
| `original.choice3` | `fixed.choice3` | SAME-FIELD | 선택지3 이미지 복원 |
| `original.choice4` | `fixed.choice4` | SAME-FIELD | 선택지4 이미지 복원 |
| `original.choice5` | `fixed.choice5` | SAME-FIELD | 선택지5 이미지 복원 |
| `original.answer` | `fixed.answer` | SAME-FIELD | 정답 이미지 복원 |
| `original.solution` | `fixed.solution` | SAME-FIELD | 풀이 이미지 복원 |

**Pseudo-code:**
```python
def _v2_restore_missing_images(original_data: Dict, fixed_data: Dict) -> Dict:
    img_pattern = r'<img\s+[^>]*src\s*=\s*["\'][^"\']+["\'][^>]*/?\s*>'

    # Phase 1: SAME-FIELD 복원 (V1과 동일 로직, refer 제외)
    same_field_pairs = [
        ("question", "question"),
        ("choice1", "choice1"),
        ("choice2", "choice2"),
        ("choice3", "choice3"),
        ("choice4", "choice4"),
        ("choice5", "choice5"),
        ("answer", "answer"),
        ("solution", "solution"),
    ]

    for orig_field, fixed_field in same_field_pairs:
        original_content = original_data.get(orig_field)
        if not original_content or not isinstance(original_content, str):
            continue
        original_images = re.findall(img_pattern, original_content, re.IGNORECASE)
        if not original_images:
            continue

        fixed_content = fixed_data.get(fixed_field) or ""
        fixed_images = re.findall(img_pattern, str(fixed_content), re.IGNORECASE)

        for img in original_images:
            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img, re.IGNORECASE)
            if not src_match:
                continue
            src_value = src_match.group(1)
            img_exists = any(src_value in fixed_img for fixed_img in fixed_images)
            if not img_exists:
                fixed_data[fixed_field] = img + " " + fixed_content if fixed_content else img
                fixed_content = fixed_data[fixed_field]
                # fixed_images 갱신 (다음 이미지 비교를 위해)
                fixed_images = re.findall(img_pattern, str(fixed_content), re.IGNORECASE)

    # Phase 2: CROSS-FIELD 복원 (original.refer -> fixed.question)
    # Phase 1에서 original.question의 이미지는 이미 fixed.question에 복원됨
    # 이제 original.refer의 이미지 중 fixed.question에 아직 없는 것을 추가
    refer_content = original_data.get("refer")
    if refer_content and isinstance(refer_content, str):
        refer_images = re.findall(img_pattern, refer_content, re.IGNORECASE)
        if refer_images:
            fixed_question = fixed_data.get("question") or ""
            fixed_q_images = re.findall(img_pattern, str(fixed_question), re.IGNORECASE)

            for img in refer_images:
                src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img, re.IGNORECASE)
                if not src_match:
                    continue
                src_value = src_match.group(1)
                img_exists = any(src_value in fixed_img for fixed_img in fixed_q_images)
                if not img_exists:
                    fixed_data["question"] = img + " " + fixed_question if fixed_question else img
                    fixed_question = fixed_data["question"]
                    fixed_q_images = re.findall(img_pattern, str(fixed_question), re.IGNORECASE)

    return fixed_data
```

**핵심 포인트:**
- Phase 1 (SAME-FIELD)이 먼저 실행되어 `fixed.question`에 `original.question` 이미지 복원
- Phase 2 (CROSS-FIELD)가 그 후 실행되어 `original.refer` 이미지를 `fixed.question`에 추가
- Phase 2 시점에는 Phase 1의 결과가 반영된 `fixed.question`을 기준으로 중복 검사하므로 이미지 중복 삽입 방지

#### 2e. `_v2_restore_field_div_classes(fixed_data: Dict) -> Dict`

*(Issue 2 해결 -- 복수 bare div 처리 로직 명시)*

**V2에서 question 필드의 구조:**
V2의 `fixed.question`에는 LLM이 출력한 복수의 div가 포함될 수 있음:
```html
<div class="question">문제 본문...</div><div class="reference">보기/조건...</div>
```

그러나 LLM이 class를 누락할 수 있는 케이스:
1. `<div>문제 본문...</div><div class="reference">...</div>` -- 첫 번째 div에 class 누락
2. `<div class="question">...</div><div>보기/조건...</div>` -- 두 번째 div에 class 누락
3. `<div>문제 본문...</div><div>보기/조건...</div>` -- 둘 다 class 누락
4. `<div>문제 본문...</div>` -- div 하나만 있고 class 누락 (refer가 없는 문제)

**처리 전략: LLM 프롬프트를 신뢰하되, 첫 번째 bare div만 보정**
- V2 프롬프트가 `<div class="question">`과 `<div class="reference">` 구조를 명시적으로 지시하므로 LLM이 올바른 class를 출력할 것으로 기대
- 후처리에서는 **보수적으로 첫 번째 bare `<div>`에만 class="question"을 추가** (V1과 동일한 count=1 로직)
- 두 번째 이후의 bare `<div>`는 건드리지 않음 (LLM이 class를 출력했을 것으로 신뢰, 잘못 추측하면 데이터 훼손 위험)
- solution 필드는 V1과 동일하게 처리 (class="solution")

**Pseudo-code:**
```python
def _v2_restore_field_div_classes(fixed_data: Dict) -> Dict:
    # V2에서는 question과 solution만 처리 (refer 필드 없음)
    field_class_map = {
        "question": "question",   # 첫 번째 bare <div>에만 class="question" 추가
        "solution": "solution",
    }

    for field, class_name in field_class_map.items():
        content = fixed_data.get(field)
        if not content or not isinstance(content, str):
            continue

        # V1과 동일: 콘텐츠가 bare <div>로 시작하면 첫 번째만 class 추가
        if re.match(r"^\s*<div\s*>", content, re.IGNORECASE):
            content = re.sub(
                r"^(\s*)<div\s*>",
                f'\\1<div class="{class_name}">',
                content,
                count=1,
                flags=re.IGNORECASE,
            )
            fixed_data[field] = content

    return fixed_data
```

**왜 두 번째 bare div를 "reference"로 자동 변환하지 않는가:**
- 두 번째 div가 항상 reference인 것은 아님 (LLM이 다른 구조로 출력할 수 있음)
- 잘못된 class 부여는 데이터 훼손으로 직결됨
- judge_fixed_output_v2가 `<div class="reference">` 누락을 감지하여 재시도 트리거 가능
- 즉, 이 함수는 "확실한 것만 고치는" 보수적 전략

#### 2f. `_v2_separate_image_div(fixed_data: Dict) -> Dict`

*(Issue 3 해결 -- 이중 패스 처리 명시)*

**V1과의 차이:**
- V1은 `{"question": "question", "refer": "reference"}` 두 필드를 각각 한 번씩 처리
- V2에서는 refer 필드가 없고, question 필드 하나에 `class="question"`과 `class="reference"` div가 모두 존재
- 따라서 question 필드에 대해 **TWO PASSES** 필요: 한 번은 `class="question"` div, 한 번은 `class="reference"` div

**Pseudo-code:**
```python
def _v2_separate_image_div(fixed_data: Dict) -> Dict:
    # question 필드에 대해 2회 패스 (question div + reference div)
    # solution 필드는 V1에서도 처리하지 않으므로 V2에서도 제외

    question_classes = ["question", "reference"]

    for class_name in question_classes:
        content = fixed_data.get("question")
        if not content or not isinstance(content, str):
            continue

        # V1과 동일한 div_pattern 구성 (class_name만 변경)
        div_pattern = (
            r'(<div\s+[^>]*class\s*=\s*["\']'
            + re.escape(class_name)
            + r'["\'][^>]*>)(.*?)(</div>)'
        )
        match = re.search(div_pattern, content, re.DOTALL | re.IGNORECASE)

        if not match:
            continue

        opening_tag = match.group(1)
        inner_content = match.group(2)
        closing_tag = match.group(3)

        # V1과 동일한 segment 파싱 로직 (top-level 요소 분리)
        segments = _parse_top_level_segments(inner_content)

        # 혼합 콘텐츠 체크 (img + 다른 콘텐츠)
        has_img = any(re.search(r"<img\s+[^>]*/?>", seg, re.IGNORECASE) for seg in segments)
        has_other = any(not re.match(r"^\s*<img\s+[^>]*/?\s*>\s*$", seg, re.IGNORECASE) for seg in segments)

        if not has_img or not has_other or len(segments) <= 1:
            continue

        # 각 segment를 개별 div로 감싸기
        new_divs = []
        for segment in segments:
            stripped = segment.strip()
            if stripped:
                new_divs.append(f"{opening_tag}{segment}{closing_tag}")

        if new_divs:
            new_content = content[:match.start()] + "".join(new_divs) + content[match.end():]
            fixed_data["question"] = new_content

    # solution 필드는 처리하지 않음 (V1과 동일)
    return fixed_data
```

**핵심 포인트:**
- `question_classes = ["question", "reference"]` 리스트를 순회하며 2회 패스
- 첫 번째 패스: `<div class="question">` 내부의 img 분리
- 두 번째 패스: `<div class="reference">` 내부의 img 분리
- 각 패스에서 `fixed_data["question"]`을 업데이트하므로, 두 번째 패스는 첫 번째 패스의 결과를 반영한 content에서 작업
- `_parse_top_level_segments()` 헬퍼 함수는 V1의 while loop 로직을 그대로 추출 (depth tracking으로 top-level 요소 분리)

#### 2g. `process_single_problem_v2(problem: Dict) -> Dict`
- V1의 `process_single_problem`과 동일한 구조 (LLM -> 후처리 -> judge -> 재시도)
- 차이점:
  - `fix_content_with_llm_v2()` 호출
  - V2 후처리 체인:
    ```python
    fixed_data = _v2_restore_missing_images(problem, fixed_data)
    fixed_data = validate_image_tags(fixed_data)       # V1 재사용 (refer 없으면 skip)
    fixed_data = normalize_answer(fixed_data)           # V1 재사용
    fixed_data = unescape_html_tags(fixed_data)         # V1 재사용
    fixed_data = normalize_lt_spacing(fixed_data)       # V1 재사용 (refer 없으면 skip)
    fixed_data = restore_latex_control_char_fields(fixed_data)  # V1 재사용
    fixed_data = normalize_latex_backslashes(fixed_data)        # V1 재사용
    # normalize_refer_view_header -> SKIP
    # remove_refer_markers -> SKIP
    fixed_data = normalize_html_wrappers(fixed_data)    # V1 재사용
    fixed_data = wrap_short_answer_with_math_delimiters(fixed_data)  # V1 재사용
    fixed_data = normalize_empty_brackets(fixed_data)   # V1 재사용
    fixed_data = _v2_restore_field_div_classes(fixed_data)  # V2 전용
    fixed_data = _v2_separate_image_div(fixed_data)     # V2 전용
    fixed_data = wrap_latex_content(fixed_data)         # V1 재사용
    fixed_data = normalize_reference_text(fixed_data)   # V1 재사용
    # remove_duplicate_reference_div -> SKIP
    fixed_data = add_displaystyle_to_binom(fixed_data)  # V1 재사용
    ```
  - `judge_fixed_output_v2()` 호출
  - fixed_data에 `"refer": None` 명시적 추가 (DB 업데이트 시 null로 덮어씀)
- `register_pipeline("v2", process_single_problem_v2)` 등록

**Acceptance Criteria:**
- [x] `process_single_problem_v2`가 pipeline registry에 "v2"로 등록됨
- [x] LLM input에 `question_context` 필드 사용
- [x] LLM output schema에 refer 필드 없음
- [x] 후처리 체인에서 refer-specific 함수 (normalize_refer_view_header, remove_refer_markers, remove_duplicate_reference_div) 제거
- [x] fixed_data에 `"refer": None` 명시적 설정
- [x] V1의 fixer.py 무변경
- [x] V1 재사용 함수는 import하여 사용 (복사 아님)
- [x] `_v2_restore_missing_images`가 CROSS-FIELD (original.refer -> fixed.question) 복원을 수행
- [x] `_v2_restore_field_div_classes`가 question 필드의 첫 번째 bare div에만 class="question" 추가
- [x] `_v2_separate_image_div`가 question 필드에서 "question"과 "reference" 두 class에 대해 2회 패스 실행
- [x] `JUDGE_SYSTEM_PROMPT_V2` 상수가 v2.py 상단에 정의됨

---

### TASK 3: fixer.py에서 V2가 재사용할 함수들의 import 가능성 확인 및 필요시 리팩토링
**File:** `/Users/classday/workplace/scripts/app/core/fixer.py`
**Changes:** **없음 (V1 무변경 원칙)**

**분석 결과:**
- V2에서 재사용할 함수들 (`validate_image_tags`, `normalize_answer`, `unescape_html_tags`, `normalize_lt_spacing`, `restore_latex_control_char_fields`, `normalize_latex_backslashes`, `normalize_html_wrappers`, `wrap_short_answer_with_math_delimiters`, `normalize_empty_brackets`, `wrap_latex_content`, `normalize_reference_text`, `add_displaystyle_to_binom`)은 모두 fixer.py에 정의되어 있음
- 이 함수들은 `fixed_data` dict를 받아서 처리하므로 refer 키가 없어도 `dict.get()` 또는 `isinstance` 체크로 안전하게 skip됨
- **V2에서 `from app.core.fixer import validate_image_tags, ...`로 직접 import 가능**
- fixer.py 수정 불필요

**또한 필요한 import:**
- `OPENROUTER_API_KEY`, `OPENROUTER_URL`, `MODEL_NAME`, `JUDGE_MODEL_NAME` 등 상수
- `PROMPT_TEMPLATE_PATH` 상수

**Acceptance Criteria:**
- [x] fixer.py 파일 변경 없음 (git diff 확인)

---

### TASK 4: updater.py V2 호환성 확인
**File:** `/Users/classday/workplace/scripts/app/core/updater.py`
**Changes:** **없음**

**분석:**
- `update_problems_from_results()`의 `default_fields`에 "refer" 포함
- V2 fixed_json에 `"refer": null`이 명시적으로 포함되므로 `if field in fixed_json` 조건 통과
- `val = fixed_json[field]` -> `None` -> pymysql이 NULL로 변환
- 따라서 V2 결과 apply 시 DB의 refer 컬럼이 NULL로 업데이트됨
- **변경 불필요**

**Acceptance Criteria:**
- [x] updater.py 파일 변경 없음
- [x] V2 결과 apply 시 refer가 NULL로 업데이트되는지 수동 테스트

---

### TASK 5: review.html V2 호환성 확인
**File:** `/Users/classday/workplace/scripts/app/templates/review.html`
**Changes:** **없음**

**분석:**
- `UPDATE_FIELDS` 배열에 refer 포함 -> V2에서는 refer가 null이므로 체크박스는 표시되지만 값이 null이면 renderField가 빈 문자열 반환
- 실제로 `renderField` 함수: `if (value === null || value === undefined) return '';` -> refer 필드 영역 자체가 렌더링되지 않음
- V2의 question 내부 `<div class="reference">` HTML은 MathJax 렌더링 후 자연스럽게 표시됨
- **변경 불필요**

**Acceptance Criteria:**
- [x] review.html 파일 변경 없음
- [x] V2 결과에서 refer 영역이 표시되지 않는지 확인
- [x] V2 결과에서 question 내부 reference div가 정상 렌더링되는지 확인

---

### TASK 6: 통합 테스트
**Manual Testing:**
1. 서버 실행
2. V2 파이프라인으로 job 생성: `POST /jobs` with `pipeline_version: "v2"`
3. 결과 확인:
   - fixed_json에 refer가 null인지 확인
   - fixed_json의 question에 `<div class="reference">` 포함 여부 확인
   - choice1~5, answer, solution이 정상인지 확인
4. review 페이지에서 V2 결과 표시 확인
5. apply 실행 후 MySQL problem 테이블에서 refer가 NULL인지 확인
6. V1 파이프라인으로 동일 problem 처리 후 기존과 동일한 결과인지 확인 (V1 무영향)

---

## 5. Task Dependency Flow

```
TASK 1 (prompt_template.json V2 프롬프트)
    |
    v
TASK 3 (fixer.py 무변경 확인) --+
    |                            |
    v                            v
TASK 2 (v2.py 전체 구현) --------+
    |
    v
TASK 4 (updater.py 호환 확인)
    |
    v
TASK 5 (review.html 호환 확인)
    |
    v
TASK 6 (통합 테스트)
```

실질적으로 TASK 1과 TASK 2가 핵심 구현 태스크이며, TASK 3/4/5는 무변경 확인, TASK 6은 테스트.

---

## 6. Commit Strategy

### Commit 1: V2 프롬프트 추가
- `prompt_template.json` 변경
- Message: "feat: add V2 prompt template (system_v2, user_v2) for integrated question_context input"

### Commit 2: V2 파이프라인 구현
- `app/core/pipelines/v2.py` 전체 재작성
- Message: "feat: implement V2 pipeline with question_context input and refer-free output"

---

## 7. Risk Identification

### Risk 1: LLM이 V2 프롬프트를 제대로 이해하지 못할 수 있음
- **확률:** 중간
- **영향:** question 내에 `<div class="reference">` 를 생성하지 않거나, 구조가 깨질 수 있음
- **완화:** 프롬프트에 명확한 예시 포함. 후처리에서 `restore_field_div_classes` V2 버전으로 보완. judge가 reference div 누락을 감지하여 재시도 트리거.

### Risk 2: question_context 통합 시 정보 손실
- **확률:** 낮음
- **영향:** choice 내용이 question_context에서 잘못 파싱될 수 있음
- **완화:** 명확한 구분자 (`[문제]`, `[보기/조건]`, `[선택지]`) 사용. 프롬프트에서 이 마커를 명시적으로 설명.

### Risk 3: 기존 V1 후처리 함수가 refer=None에서 예기치 않은 동작
- **확률:** 매우 낮음
- **영향:** 런타임 에러
- **완화:** 모든 재사용 함수가 `dict.get()` 또는 `isinstance` 체크를 사용하므로 None에 안전. 코드 리뷰로 확인 완료.

### Risk 4: DB에서 refer를 NULL로 업데이트한 후 다른 시스템이 refer를 참조
- **확률:** 낮음 (해당 시스템 존재 여부 불명)
- **영향:** 다른 서비스에서 refer가 없어 문제 표시 오류
- **완화:** V2를 사용하는 것은 의도적 선택이므로 운영자가 인지하고 사용. refer 내용이 question에 통합되어 있으므로 정보 손실은 없음.

### Risk 5: V2의 fix_content_with_llm_v2에서 fixer.py 상수(API key, URL 등) import
- **확률:** 없음 (Python import로 해결)
- **영향:** 없음
- **완화:** `from app.core.fixer import OPENROUTER_API_KEY, OPENROUTER_URL, ...` 로 import

---

## 8. Success Criteria

1. `POST /jobs` with `pipeline_version: "v2"` 가 정상 동작
2. V2 결과의 fixed_json에 `refer: null` 포함
3. V2 결과의 fixed_json question에 `<div class="question">` 와 `<div class="reference">` HTML 구조 포함
4. V2 결과의 output schema가 V1과 다름 (refer 없음)
5. V1 파이프라인이 기존과 동일하게 동작 (regression 없음)
6. review.html에서 V2 결과가 정상 렌더링
7. apply 후 MySQL problem 테이블의 refer가 NULL로 업데이트

---

## Appendix: Critic Issue Resolution Traceability

| Critic Issue | Resolution Location | Summary |
|-------------|---------------------|---------|
| Issue 1: `_v2_restore_missing_images` field mapping | Task 2d - 매핑 테이블 + pseudo-code | 9개 필드 매핑 (8 SAME-FIELD + 1 CROSS-FIELD: original.refer -> fixed.question). 2-phase 알고리즘. |
| Issue 2: `_v2_restore_field_div_classes` multiple divs | Task 2e - pseudo-code + 전략 설명 | 보수적 전략: 첫 번째 bare div에만 class="question" 추가. 두 번째 이후 bare div는 건드리지 않음 (LLM 신뢰 + judge 재시도로 보완). |
| Issue 3: `_v2_separate_image_div` dual class types | Task 2f - pseudo-code + 2-pass 설명 | `question_classes = ["question", "reference"]` 순회하여 2회 패스. 각 패스가 fixed_data를 업데이트하여 순차적 반영. |
| Issue 4: V2 judge prompt storage location | Decision 8 + Task 2c | `JUDGE_SYSTEM_PROMPT_V2` 상수를 v2.py 상단에 정의. 전체 텍스트와 V1 대비 차이점 4가지 명시. |
| Issue 5: Section markers in system_v2 prompt | Task 1 - system_v2 차이점 #3 | `[문제]`/`[보기/조건]`/`[선택지]` 마커 설명을 system_v2 프롬프트 필수 항목으로 추가. Task 2a와 일관성 확보. |
