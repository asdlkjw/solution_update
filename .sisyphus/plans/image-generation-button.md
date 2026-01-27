# 이미지 생성 버튼 기능 추가

## Context

### Original Request
최종 제출 버튼 옆에 이미지 생성 버튼을 추가. GOOD으로 처리된 문제들의 problem_id로 외부 API(`https://class.day/img-conv/api/render`)를 호출하고, 반환된 job_id 목록을 BAD ID 표시 방식과 동일하게 보여주기.

### Interview Summary
**Key Discussions**:
- **버튼 위치**: 최종 제출 후 result-modal 내, BAD 목록 아래에 배치
- **요청 방식**: 병렬 요청 (Promise.all)
- **에러 처리**: 실패 건 스킵, 성공한 job_id와 실패한 problem_id 각각 표시
- **결과 표시**: BAD ID와 동일한 패턴 (textarea + 복사 버튼)
- **deduplicate**: 기본값 true 사용

**Research Findings**:
- 최종 제출 버튼: `review.html` Line 405
- result-modal: Lines 430-452
- BAD 표시 패턴: `bad-list-container` CSS + `openResultModal()` 함수
- GOOD 조회: `reviewStates[item.result_id] === 'GOOD'` && `item.original_id`

### Metis Review
**Identified Gaps** (addressed):
- `original_id` vs `original.id` → `item.original_id` 사용 (DB 컬럼, 더 신뢰성 높음)
- 0 GOOD일 때 처리 → 버튼 비활성화 + 안내 메시지
- 로딩 상태 → 버튼 disabled + 텍스트 변경
- 중복 problem_id → `Set` 사용하여 중복 제거

---

## Work Objectives

### Core Objective
최종 제출 완료 후 GOOD 문제들의 이미지를 생성 요청하는 버튼과 결과(job_id) 표시 기능 구현

### Concrete Deliverables
- `review.html` 수정:
  - result-modal 내 이미지 생성 버튼 추가
  - job_id 표시 영역 (textarea + 복사 버튼)
  - 실패한 problem_id 표시 영역
  - `generateImages()` JavaScript 함수
  - `copyJobIds()` JavaScript 함수

### Definition of Done
- [x] 최종 제출 후 result-modal에 "이미지 생성" 버튼이 보임
- [x] 버튼 클릭 시 GOOD 문제들에 대해 API 호출됨
- [x] 성공한 job_id 목록이 textarea에 표시됨
- [x] 실패한 problem_id가 별도로 표시됨
- [x] job_id 복사 버튼이 동작함

### Must Have
- GOOD 문제의 `original_id`로 API 호출
- 병렬 요청 (Promise.all)
- 실패 건 스킵하고 계속 진행
- BAD 표시와 동일한 UI 패턴

### Must NOT Have (Guardrails)
- 새로운 CSS 클래스 생성 금지 (기존 `bad-list-*` 패턴 재사용)
- 재시도 로직 추가 금지
- 진행률 표시 추가 금지
- 취소 기능 추가 금지
- `openResultModal()` 함수 시그니처 변경 금지

---

## Verification Strategy (MANDATORY)

### Test Decision
- **Infrastructure exists**: NO
- **User wants tests**: Manual-only
- **Framework**: none

### If Manual QA Only

**By Deliverable Type:**

| Type | Verification Tool | Procedure |
|------|------------------|-----------|
| **Frontend/UI** | 브라우저 직접 확인 | 서버 실행 → 리뷰 → 제출 → 버튼 클릭 → 결과 확인 |

---

## Task Flow

```
Task 1 (HTML 구조) → Task 2 (JS 함수) → Task 3 (통합 검증)
```

## Parallelization

| Task | Depends On | Reason |
|------|------------|--------|
| 1 | - | 독립적 |
| 2 | 1 | HTML 요소 ID 참조 필요 |
| 3 | 2 | 전체 기능 통합 검증 |

---

## TODOs

- [x] 1. result-modal에 이미지 생성 UI 요소 추가

  **What to do**:
  - result-modal 내 BAD 목록 영역(`bad-list-container`) 아래에 새로운 섹션 추가
  - "이미지 생성" 버튼 추가 (초기 상태: 버튼 활성화)
  - job_id 표시용 textarea + 복사 버튼 추가 (초기 상태: hidden)
  - 실패한 problem_id 표시용 textarea (초기 상태: hidden)

  **Must NOT do**:
  - 새로운 CSS 클래스 생성 금지 (기존 `bad-list-*` 패턴 재사용)
  - `bad-list-container` 스타일 그대로 복제하여 사용

  **Parallelizable**: NO (첫 번째 태스크)

  **References**:

  **Pattern References**:
  - `app/templates/review.html:430-452` - result-modal 전체 구조. 이 modal 내부에 새 섹션 추가
  - `app/templates/review.html:436-445` - BAD 목록 컨테이너 패턴. 이 구조를 job_id 표시에도 동일하게 적용
  - `app/templates/review.html:358-390` - `bad-list-*` CSS 클래스들. 동일 클래스 재사용하되 색상만 변경

  **UI 구조 (추가할 HTML)**:
  ```html
  <!-- BAD 목록 아래에 추가 -->
  <div class="bad-list-container" style="margin-top: 20px;">
      <button id="btn-generate-images" class="btn" style="width: 100%; border-color: var(--accent-color); color: var(--accent-color);" onclick="generateImages()">
          이미지 생성
      </button>
      <div id="img-job-container" style="display: none; margin-top: 15px;">
          <div class="bad-list-label" style="color: var(--good-color);">
              <span id="img-job-status">생성된 Job ID</span>
          </div>
          <textarea id="img-job-list" class="bad-list-textarea" readonly onclick="this.select()"></textarea>
          <button id="btn-copy-jobs" class="btn" style="width: 100%; border-color: var(--good-color); color: var(--good-color);" onclick="copyJobIds()">
              Job ID 복사
          </button>
      </div>
      <div id="img-fail-container" style="display: none; margin-top: 15px;">
          <div class="bad-list-label">
              <span id="img-fail-status">실패한 Problem ID</span>
          </div>
          <textarea id="img-fail-list" class="bad-list-textarea" readonly onclick="this.select()"></textarea>
      </div>
  </div>
  ```

  **Acceptance Criteria**:

  **Manual Execution Verification:**
  - [ ] 서버 실행: `./run_server.sh`
  - [ ] 브라우저에서 `http://localhost:8000` 접속
  - [ ] 작업 생성 → 리뷰 화면 진입 → 최종 제출
  - [ ] result-modal에서 "이미지 생성" 버튼 확인
  - [ ] 버튼이 BAD 목록 아래에 위치함 확인
  - [ ] job_id/fail 영역이 초기에 숨겨져 있음 확인

  **Commit**: NO (groups with 2)

---

- [x] 2. generateImages() 및 copyJobIds() JavaScript 함수 구현

  **What to do**:
  - `generateImages()` 함수 구현:
    1. GOOD 상태인 문제들의 `original_id` 수집 (Set으로 중복 제거)
    2. 0개면 alert 표시 후 종료
    3. 버튼 disabled + 텍스트 "생성 중..." 변경
    4. Promise.all로 병렬 API 호출
    5. 성공한 job_id와 실패한 problem_id 분리
    6. 결과 표시 (성공: job_id textarea, 실패: fail textarea)
    7. 버튼 텍스트 "완료" 또는 "생성 완료"로 변경
  - `copyJobIds()` 함수 구현 (기존 `copyBadGroupIds()` 패턴 복제)

  **Must NOT do**:
  - 재시도 로직 추가 금지
  - 진행률 표시 추가 금지
  - 취소 기능 추가 금지

  **Parallelizable**: NO (depends on 1)

  **References**:

  **Pattern References**:
  - `app/templates/review.html:637-648` - GOOD/BAD 아이템 수집 패턴. `original_id` 사용으로 변경
  - `app/templates/review.html:689-718` - `copyBadGroupIds()` 함수. 이 패턴 그대로 복제하여 `copyJobIds()` 구현
  - `app/templates/review.html:608-659` - `submitReview()` 함수의 Promise.all 패턴 참조

  **API 호출 예시**:
  ```javascript
  const response = await fetch('https://class.day/img-conv/api/render', {
      method: 'POST',
      headers: {
          'accept': 'application/json',
          'Content-Type': 'application/json'
      },
      body: JSON.stringify({ problem_id: id, deduplicate: true })
  });
  const data = await response.json();
  // data.job_id 추출
  ```

  **JavaScript 구현 (추가할 코드)**:
  ```javascript
  async function generateImages() {
      const btn = document.getElementById('btn-generate-images');
      const jobContainer = document.getElementById('img-job-container');
      const jobTextarea = document.getElementById('img-job-list');
      const jobStatus = document.getElementById('img-job-status');
      const failContainer = document.getElementById('img-fail-container');
      const failTextarea = document.getElementById('img-fail-list');
      const failStatus = document.getElementById('img-fail-status');

      // 1. GOOD problem_id 수집 (중복 제거)
      const goodProblemIds = new Set();
      DATA.forEach(item => {
          if (reviewStates[item.result_id] === 'GOOD') {
              if (item.original_id !== undefined && item.original_id !== null) {
                  goodProblemIds.add(item.original_id);
              }
          }
      });

      const problemIds = Array.from(goodProblemIds);
      if (problemIds.length === 0) {
          alert('GOOD으로 마킹된 문제가 없습니다.');
          return;
      }

      // 2. 버튼 비활성화 + 로딩 상태
      btn.disabled = true;
      btn.textContent = '생성 중...';

      // 3. 병렬 API 호출
      const results = await Promise.allSettled(
          problemIds.map(async (id) => {
              const response = await fetch('https://class.day/img-conv/api/render', {
                  method: 'POST',
                  headers: {
                      'accept': 'application/json',
                      'Content-Type': 'application/json'
                  },
                  body: JSON.stringify({ problem_id: id, deduplicate: true })
              });
              if (!response.ok) throw new Error(`HTTP ${response.status}`);
              const data = await response.json();
              return { problem_id: id, job_id: data.job_id };
          })
      );

      // 4. 성공/실패 분리
      const successJobs = [];
      const failedIds = [];

      results.forEach((result, index) => {
          if (result.status === 'fulfilled' && result.value.job_id) {
              successJobs.push(result.value.job_id);
          } else {
              failedIds.push(problemIds[index]);
          }
      });

      // 5. 결과 표시
      if (successJobs.length > 0) {
          jobContainer.style.display = 'block';
          jobTextarea.value = successJobs.join('\n');
          jobStatus.textContent = `생성된 Job ID (${successJobs.length}건)`;
      } else {
          jobContainer.style.display = 'none';
      }

      if (failedIds.length > 0) {
          failContainer.style.display = 'block';
          failTextarea.value = failedIds.join('\n');
          failStatus.textContent = `실패한 Problem ID (${failedIds.length}건)`;
      } else {
          failContainer.style.display = 'none';
      }

      // 6. 버튼 상태 업데이트
      btn.textContent = '생성 완료';
  }

  function copyJobIds() {
      const textarea = document.getElementById('img-job-list');
      const text = textarea.value;
      const btn = document.getElementById('btn-copy-jobs');
      const originalText = btn.textContent;

      const showSuccess = () => {
          btn.textContent = '복사 완료!';
          btn.style.background = 'var(--good-color)';
          btn.style.color = '#000';
          setTimeout(() => {
              btn.textContent = originalText;
              btn.style.background = '';
              btn.style.color = '';
          }, 2000);
      };

      if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(text).then(showSuccess).catch(() => {
              textarea.select();
              document.execCommand('copy');
              showSuccess();
          });
      } else {
          textarea.select();
          textarea.setSelectionRange(0, 99999);
          document.execCommand('copy');
          showSuccess();
      }
  }
  ```

  **Acceptance Criteria**:

  **Manual Execution Verification:**
  - [ ] 최종 제출 후 "이미지 생성" 버튼 클릭
  - [ ] 버튼이 "생성 중..."으로 변경됨 확인
  - [ ] API 호출 완료 후 job_id 목록이 textarea에 표시됨
  - [ ] 각 job_id가 줄바꿈으로 구분되어 표시됨
  - [ ] "Job ID 복사" 버튼 클릭 시 클립보드에 복사됨
  - [ ] (실패 케이스 테스트) 네트워크 끊은 상태에서 실패한 problem_id 표시 확인

  **Commit**: YES
  - Message: `feat(review): add image generation button for GOOD problems`
  - Files: `app/templates/review.html`
  - Pre-commit: 없음 (테스트 인프라 없음)

---

- [x] 3. 통합 검증 및 엣지 케이스 확인

  **What to do**:
  - 전체 플로우 E2E 검증
  - 엣지 케이스 확인:
    - 0 GOOD인 경우
    - 전체 성공인 경우
    - 일부 실패인 경우
    - 전체 실패인 경우

  **Must NOT do**:
  - 추가 기능 구현 금지 (검증만)

  **Parallelizable**: NO (depends on 2)

  **References**:

  **검증 시나리오**:
  
  | 시나리오 | 테스트 방법 | 예상 결과 |
  |---------|------------|----------|
  | 0 GOOD | 모든 항목 BAD로 마킹 후 제출 → 이미지 생성 클릭 | alert "GOOD으로 마킹된 문제가 없습니다." |
  | 전체 성공 | 정상 네트워크에서 GOOD 항목들 이미지 생성 | job_id 목록만 표시, 실패 영역 숨김 |
  | 일부 실패 | DevTools Network에서 일부 요청 Block 후 테스트 | 성공 job_id + 실패 problem_id 둘 다 표시 |
  | 전체 실패 | DevTools에서 해당 도메인 Block | 실패 problem_id만 표시, job_id 영역 숨김 |

  **Acceptance Criteria**:

  **Manual Execution Verification:**
  - [ ] **0 GOOD 케이스**: 
    - 모든 문제를 BAD로 마킹 → 최종 제출 → "이미지 생성" 클릭
    - 결과: alert 메시지 표시 "GOOD으로 마킹된 문제가 없습니다."
  - [ ] **전체 성공 케이스**:
    - GOOD 문제 있는 상태로 제출 → "이미지 생성" 클릭
    - 결과: job_id textarea에 ID 목록 표시, 실패 영역 숨김
  - [ ] **복사 기능**:
    - "Job ID 복사" 클릭 → 메모장에 붙여넣기
    - 결과: job_id 목록이 정확히 복사됨

  **Commit**: NO (검증만)

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 2 | `feat(review): add image generation button for GOOD problems` | `app/templates/review.html` | 브라우저 수동 검증 |

---

## Success Criteria

### Verification Commands
```bash
# 서버 실행
./run_server.sh

# 브라우저에서 확인
# http://localhost:8000
```

### Final Checklist
- [x] result-modal에 "이미지 생성" 버튼 표시됨
- [x] GOOD 문제들에 대해 API 병렬 호출됨
- [x] 성공한 job_id 목록이 textarea에 표시됨
- [x] 실패한 problem_id가 별도 표시됨
- [x] 복사 버튼이 정상 동작함
- [x] 0 GOOD 시 적절한 alert 표시됨
- [x] 새로운 CSS 클래스 없이 기존 패턴 재사용됨
