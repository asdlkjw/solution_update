# Decisions - image-generation-button

## [Initial] Architectural Decisions
- Use `item.original_id` (not `item.original.id`) for problem_id extraction
- Reuse existing `bad-list-*` CSS classes (no new classes)
- Use `Promise.allSettled` for parallel API calls (fail-fast not required)
- `deduplicate: true` hardcoded (user's API example)
- Manual QA only (no test infrastructure)
