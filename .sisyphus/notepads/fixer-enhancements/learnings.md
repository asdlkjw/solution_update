# Learnings - fixer-enhancements

## Conventions & Patterns

### Post-Processing Function Pattern
All post-processing functions follow this signature:
```python
def func_name(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    # Process and modify fixed_data
    return fixed_data
```

**Exception**: `restore_missing_images(original_data, fixed_data)` requires BOTH original and fixed data.

### Regex Patterns Used
- **Image tags**: `r'<img\s+[^>]*src\s*=\s*["\'][^"\']+["\'][^>]*/?\s*>'`
- **Marker patterns**: `r"<\s*p\s*>\s*(?:&lt;|<)\s*WORD\s*(?:&gt;|>)\s*</\s*p\s*>"`
- **Korean Hangul range**: `\uAC00-\uD7A3`
- **Math content**: `r'^[\s\w\d\+\-\*/\^=<>\(\)\[\]\{\},\.]+$'`

### Field Processing Order in process_single_problem
1. `restore_missing_images(problem, fixed_data)` - uses original data
2. `normalize_answer(fixed_data)` - convert circle numbers
3. `unescape_html_tags(fixed_data)` - fix escaped tags
4. `normalize_refer_view_header(fixed_data)` - remove <보기> from refer
5. `remove_refer_markers(fixed_data)` - remove <표>, <조건> markers
6. `normalize_html_wrappers(fixed_data)` - strip wrapper divs
7. `wrap_choice_latex(fixed_data)` - auto-wrap math in $
8. `normalize_reference_text(fixed_data)` - unify reference patterns

### Implementation Decisions
- **Image restoration**: Prepends images to field content (preserves existing content)
- **LaTeX wrapping**: Only wraps when $count <= 1, no Korean, no complex HTML
- **Marker removal**: Conditional on question content (avoid redundant headers)
- **Reference unification**: Only in answer/solution fields (not question/refer)

### Code Style Observed
- Korean comments for complex logic (matches project style)
- Docstrings in Korean (one-line functional descriptions)
- `re.IGNORECASE` flag for text matching
- `.strip()` after text transformations
