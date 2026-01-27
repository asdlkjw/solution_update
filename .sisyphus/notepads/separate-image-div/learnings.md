# Learnings - separate-image-div

## Project Patterns
- Existing postprocessing functions use regex-based approach
- Functions follow pattern: `def func_name(fixed_data: Dict[str, Any]) -> Dict[str, Any]`
- Field-specific processing uses `field_class_map` dictionary

## Conventions
- Target fields: `question`, `refer` only
- All div attributes must be preserved
- Order preservation is critical

## Implementation Notes - Task 1 & 2

### Function Added: `separate_image_div()`
- Location: `app/core/fixer.py:328-441`
- Follows `restore_field_div_classes` pattern
- Uses character-level parsing with depth tracking for top-level element identification

### Parsing Approach
- Regex to match outer `<div class="X">...</div>`
- Manual parsing of inner content (not regex - handles nested tags correctly)
- Depth counter tracks tag nesting level
- Segments identified at depth=0 (top level)

### Pipeline Integration
- Added at line 908: after `restore_field_div_classes`, before `wrap_latex_content`
- This ensures class attributes exist before processing

### Edge Cases Handled
- Self-closing tags: `<img/>` and `<img>`
- Nested structures: only processes direct children
- Text nodes: wrapped in separate divs
- Empty content: skipped (whitespace-only)
- Img-only divs: no modification (not mixed content)

### Bug Fixed During Implementation
- Line 418: Fixed regex pattern from `r"^\s*<img\s+[^>]*/?>  \s*$"` (double space) to `r"^\s*<img\s+[^>]*/?\s*>\s*$"`
