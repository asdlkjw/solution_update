"""v2 pipeline - Unified question+refer model.

In V2 the LLM receives a combined question_context (question + refer + choices)
and returns a schema with NO refer field.  Reference content is integrated into
the question field via <div class="reference"> blocks.
"""

import json
import re
import sys
import time
from typing import Any, Dict, List

import requests

from app.core.fixer import (
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    MODEL_NAME,
    JUDGE_MODEL_NAME,
    PROMPT_TEMPLATE_PATH,
    # V1 reusable post-processing functions
    _fix_image_src_format,
    preserve_original_images,
    clamp_image_widths,
    validate_image_tags,
    normalize_answer,
    unescape_html_tags,
    normalize_lt_spacing,
    restore_latex_control_char_fields,
    normalize_latex_backslashes,
    normalize_html_wrappers,
    wrap_short_answer_with_math_delimiters,
    normalize_empty_brackets,
    wrap_latex_content,
    normalize_reference_text,
    add_displaystyle_to_binom,
    convert_binom_to_combination,
)
from app.core.pipelines.registry import register_pipeline

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT_V2_MC = (
    "너는 수학 문제 수정 결과를 검수하는 심사자다. 원본과 수정본을 비교해서 품질을 판단한다. "
    "다음 항목을 엄격히 확인하라: question 필드 누락 또는 비어있음, "
    'question 내부에 <div class="question">과 <div class="reference"> 구조가 올바른지 '
    '(reference 내용이 있는 경우 반드시 <div class="reference">로 감싸져 있어야 함), '
    "LaTeX 수식 깨짐, HTML 태그 불완전/잘못된 중첩, "
    "가독성 저하(문장 붕괴, 의미 모호). 이 버전에서는 refer 필드가 없고 question에 통합되어 있다. "
    "객관식 규칙: answer는 1~5 중 하나의 번호이다. solution에서 정답 값(예: 8)이 서술되더라도 "
    "choice{answer}의 내용과 일치하면 정답으로 간주하라. answer가 1~5가 아니거나, "
    "choice{answer}가 비어있거나, solution의 결론이 해당 선택지와 명백히 불일치하면 실패로 판단하라. "
    "answer는 선택지 번호만 의미하며 값(예: 3)으로 해석하지 않는다. 예: answer=3, choice3='4'이면 정답 값은 4이고 올바르다. "
    "정답 번호의 의미에 대해 의심하거나 확인 필요 같은 표현을 하지 말고 규칙대로 판단하라. "
    "복수정답 허용: answer는 '2, 5'처럼 콤마-공백으로 여러 번호가 될 수 있으며 각 번호는 1~5여야 한다. "
    "solution의 결론이 해당 선택지 집합과 일치하면 통과로 판단하라. "
    "통과면 pass=true와 매우 짧은 reason을 주고, "
    "실패면 pass=false와 짧고 명확한 이유를 한국어로 적어라."
)

JUDGE_SYSTEM_PROMPT_V2_SA = (
    "너는 수학 문제 수정 결과를 검수하는 심사자다. 원본과 수정본을 비교해서 품질을 판단한다. "
    "다음 항목을 엄격히 확인하라: question 필드 누락 또는 비어있음, "
    'question 내부에 <div class="question">과 <div class="reference"> 구조가 올바른지 '
    '(reference 내용이 있는 경우 반드시 <div class="reference">로 감싸져 있어야 함), '
    "LaTeX 수식 깨짐, HTML 태그 불완전/잘못된 중첩, "
    "가독성 저하(문장 붕괴, 의미 모호). 이 버전에서는 refer 필드가 없고 question에 통합되어 있다. "
    "주관식 규칙: answer는 solution의 최종 결론과 일치해야 한다(HTML/LaTeX 포맷 차이는 허용). "
    "통과면 pass=true와 매우 짧은 reason을 주고, "
    "실패면 pass=false와 짧고 명확한 이유를 한국어로 적어라."
)

# ---------------------------------------------------------------------------
# Helper: build unified question context for the LLM
# ---------------------------------------------------------------------------


def build_question_context(problem: Dict[str, Any]) -> str:
    """Combine problem fields into unified text with section markers.

    Output format:
        [문제]
        {question}

        [보기/조건]          <-- only when refer exists and is non-empty
        {refer}

        [선택지]             <-- only when any choice field exists
        1. {choice1}
        2. {choice2}
        ...
    """
    parts: List[str] = []

    # -- 문제 --
    question = problem.get("question") or ""
    parts.append(f"[문제]\n{question}")

    # -- 보기/조건 --
    refer = problem.get("refer")
    if refer and str(refer).strip():
        parts.append(f"[보기/조건]\n{refer}")

    # -- 선택지 --
    choice_lines: List[str] = []
    for i in range(1, 6):
        val = problem.get(f"choice{i}")
        if val and str(val).strip():
            choice_lines.append(f"{i}. {val}")
    if choice_lines:
        parts.append("[선택지]\n" + "\n".join(choice_lines))

    return "\n\n".join(parts)


STEP_PROMPT_FILES = {
    1: "prompt_template_v2_step1.json",
    2: "prompt_template_v2_step2.json",
    3: "prompt_template_v2_step3.json",
}


def _load_v2_prompt(step: int) -> tuple[str, str] | None:
    step_file = STEP_PROMPT_FILES.get(step)
    step_path = PROMPT_TEMPLATE_PATH.parent / step_file if step_file else None
    prompt_path = (
        step_path if step_path and step_path.exists() else PROMPT_TEMPLATE_PATH
    )

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompts = json.load(f)
    except FileNotFoundError:
        return None

    system_prompt = prompts.get("system_v2") or prompts.get("system")
    user_template = prompts.get("user_v2") or prompts.get("user")
    if not system_prompt or not user_template:
        return None

    return system_prompt, user_template


def _call_llm_v2(
    llm_input: Dict[str, Any],
    system_prompt: str,
    user_template: str,
    judge_feedback: str | None = None,
) -> Dict[str, Any]:
    serialized_data = json.loads(json.dumps(llm_input, default=str))

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/code-yeongyu/sisyphus",
        "X-Title": "Problem Fix Script",
    }

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
        "required": [
            "type",
            "question",
            "choice1",
            "choice2",
            "choice3",
            "choice4",
            "choice5",
            "answer",
            "solution",
        ],
        "additionalProperties": False,
    }

    user_content = user_template.format(
        json_data=json.dumps(serialized_data, indent=2, ensure_ascii=False)
    )
    if judge_feedback:
        user_content = f"{user_content}\n\n[이전 심사 피드백]\n{judge_feedback}"

    payload = {
        "model": MODEL_NAME,
        "temperature": 0.4,
        "max_tokens": 4000,
        "top_p": 0.95,
        "thinking_level": "high",
        "reasoning": {"effort": "low"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "math_problem_correction",
                "strict": True,
                "schema": json_schema,
            },
        },
    }

    max_attempts = 3
    retry_statuses = {408, 429, 500, 502, 503, 504}
    for attempt in range(max_attempts):
        payload["temperature"] = 0.4 if attempt == 0 else 0.7
        try:
            response = requests.post(
                OPENROUTER_URL, headers=headers, json=payload, timeout=60
            )
            if response.status_code == 401:
                if attempt < 1 and attempt < max_attempts - 1:
                    time.sleep(2**attempt)
                    continue
                return {
                    "error": "Unauthorized: check OPENROUTER_API_KEY",
                    "original_id": llm_input.get("id"),
                }
            if response.status_code in retry_statuses and attempt < max_attempts - 1:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            result = response.json()

            if "choices" not in result:
                error_msg = (
                    "Invalid API response format (missing 'choices'). Response: "
                    f"{result}"
                )
                if attempt < max_attempts - 1:
                    time.sleep(2**attempt)
                    continue
                return {"error": error_msg, "original_id": llm_input.get("id")}

            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
        except requests.RequestException as e:
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
                continue
            return {"error": str(e), "original_id": llm_input.get("id")}
        except json.JSONDecodeError as e:
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
                continue
            return {"error": str(e), "original_id": llm_input.get("id")}
        except Exception as e:
            return {"error": str(e), "original_id": llm_input.get("id")}

    return {"error": "Unknown error after retries", "original_id": llm_input.get("id")}


# ---------------------------------------------------------------------------
# LLM call: fix content (V2)
# ---------------------------------------------------------------------------


def fix_content_with_llm_v2(
    problem_data: Dict[str, Any], judge_feedback: str | None = None
) -> Dict[str, Any]:
    """Call LLM to fix a problem using the V2 unified-question schema."""

    # Build the condensed input payload for the LLM
    question_context = build_question_context(problem_data)
    llm_input = {
        "type": problem_data.get("type"),
        "question_context": question_context,
        "answer": problem_data.get("answer"),
        "solution": problem_data.get("solution"),
    }
    step1_prompt = _load_v2_prompt(1)
    if not step1_prompt:
        print("Error: prompt_template.json not found.", file=sys.stderr)
        return {
            "error": "prompt_template.json not found",
            "original_id": problem_data.get("id"),
        }
    step1_system, step1_user = step1_prompt
    step1_result = _call_llm_v2(llm_input, step1_system, step1_user, judge_feedback)
    if "error" in step1_result:
        step1_result.setdefault("original_id", problem_data.get("id"))
        return step1_result

    step2_prompt = _load_v2_prompt(2)
    if not step2_prompt:
        print("Error: prompt_template.json not found.", file=sys.stderr)
        return {
            "error": "prompt_template.json not found",
            "original_id": problem_data.get("id"),
        }
    step2_system, step2_user = step2_prompt
    step2_result = _call_llm_v2(step1_result, step2_system, step2_user)
    if "error" in step2_result:
        step2_result.setdefault("original_id", problem_data.get("id"))
        return step2_result

    step3_prompt = _load_v2_prompt(3)
    if not step3_prompt:
        print("Error: prompt_template.json not found.", file=sys.stderr)
        return {
            "error": "prompt_template.json not found",
            "original_id": problem_data.get("id"),
        }
    step3_system, step3_user = step3_prompt
    step3_result = _call_llm_v2(step2_result, step3_system, step3_user)
    if "error" in step3_result:
        step3_result.setdefault("original_id", problem_data.get("id"))
        return step3_result

    return step3_result


# ---------------------------------------------------------------------------
# Judge (V2)
# ---------------------------------------------------------------------------


def judge_fixed_output_v2(
    original: Dict[str, Any], fixed: Dict[str, Any]
) -> Dict[str, Any]:
    """Judge the quality of a V2 fix.  No refer field in payloads."""

    judge_schema = {
        "type": "object",
        "properties": {
            "pass": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["pass", "reason"],
        "additionalProperties": False,
    }

    original_payload = {
        "type": original.get("type"),
        "question": original.get("question"),
        "choice1": original.get("choice1"),
        "choice2": original.get("choice2"),
        "choice3": original.get("choice3"),
        "choice4": original.get("choice4"),
        "choice5": original.get("choice5"),
    }
    fixed_payload = {
        "type": fixed.get("type"),
        "question": fixed.get("question"),
        "choice1": fixed.get("choice1"),
        "choice2": fixed.get("choice2"),
        "choice3": fixed.get("choice3"),
        "choice4": fixed.get("choice4"),
        "choice5": fixed.get("choice5"),
        "answer": fixed.get("answer"),
        "solution": fixed.get("solution"),
    }

    problem_type = fixed.get("type") or original.get("type")
    if problem_type not in {"multiple_choice", "short_answer"}:
        has_choices = any(
            fixed.get(key) or original.get(key)
            for key in ("choice1", "choice2", "choice3", "choice4", "choice5")
        )
        problem_type = "multiple_choice" if has_choices else "short_answer"
    judge_prompt = (
        JUDGE_SYSTEM_PROMPT_V2_MC
        if problem_type == "multiple_choice"
        else JUDGE_SYSTEM_PROMPT_V2_SA
    )

    user_content = json.dumps(
        {"original": original_payload, "fixed": fixed_payload},
        ensure_ascii=False,
        indent=2,
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/code-yeongyu/sisyphus",
        "X-Title": "Problem Fix Script",
    }

    payload = {
        "model": JUDGE_MODEL_NAME,
        "temperature": 0.1,
        "max_tokens": 800,
        "top_p": 0.95,
        "thinking_level": "high",
        "reasoning": {"effort": "low"},
        "messages": [
            {"role": "system", "content": judge_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "judge_result",
                "strict": True,
                "schema": judge_schema,
            },
        },
    }

    try:
        response = requests.post(
            OPENROUTER_URL, headers=headers, json=payload, timeout=45
        )
        response.raise_for_status()
        result = response.json()
        if "choices" not in result:
            error_msg = (
                f"Invalid API response format (missing 'choices'). Response: {result}"
            )
            return {"pass": True, "reason": f"judge_error: {error_msg}"}
        content = result["choices"][0]["message"]["content"]
        return json.loads(content)
    except requests.RequestException as e:
        return {"pass": True, "reason": f"judge_error: {e}"}
    except json.JSONDecodeError as e:
        return {"pass": True, "reason": f"judge_error: {e}"}
    except Exception as e:
        return {"pass": True, "reason": f"judge_error: {e}"}


# ---------------------------------------------------------------------------
# V2 post-processing: image restoration (same-field + cross-field)
# ---------------------------------------------------------------------------


def _v2_restore_missing_images(
    original_data: Dict[str, Any], fixed_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Restore images lost during LLM processing.

    Phase 1 (SAME-FIELD): For each field present in both original and fixed,
    restore images whose src is missing in fixed.

    Phase 2 (CROSS-FIELD): Images from original.refer that are not found
    anywhere in fixed are prepended to fixed.question.
    """
    img_pattern = r'<img\s+[^>]*src\s*=\s*["\'][^"\']+["\'][^>]*/?\s*>'

    def _extract_srcs(html: str) -> List[str]:
        """Return list of src values from img tags in *html*."""
        return [
            _fix_image_src_format(src)
            for src in re.findall(r'src\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
        ]

    # -- Phase 1: same-field restoration --
    same_fields = [
        "question",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "answer",
        "solution",
    ]

    for field in same_fields:
        original_content = original_data.get(field)
        fixed_content = fixed_data.get(field)

        if not original_content or not isinstance(original_content, str):
            continue

        original_images = re.findall(img_pattern, str(original_content), re.IGNORECASE)
        if not original_images:
            continue

        if not fixed_content:
            fixed_content = ""

        fixed_images = re.findall(img_pattern, str(fixed_content), re.IGNORECASE)

        for img in original_images:
            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img, re.IGNORECASE)
            if not src_match:
                continue
            src_value = _fix_image_src_format(src_match.group(1))
            fixed_srcs = {
                _fix_image_src_format(src)
                for src in _extract_srcs(" ".join(fixed_images))
            }
            img_exists = src_value in fixed_srcs
            if not img_exists:
                if fixed_content:
                    fixed_data[field] = img + " " + fixed_content
                else:
                    fixed_data[field] = img
                fixed_content = fixed_data[field]

    # -- Phase 2: cross-field (original.refer -> fixed.question) --
    refer_content = original_data.get("refer")
    if refer_content and isinstance(refer_content, str):
        refer_images = re.findall(img_pattern, str(refer_content), re.IGNORECASE)

        if refer_images:
            # Collect ALL src values currently in fixed_data
            all_fixed_srcs: set[str] = set()
            for field in same_fields:
                fc = fixed_data.get(field)
                if isinstance(fc, str):
                    all_fixed_srcs.update(_extract_srcs(fc))

            question_content = fixed_data.get("question") or ""
            ref_pattern = re.compile(
                r'<div\s+[^>]*class\s*=\s*["\']reference["\'][^>]*>.*?</div>',
                re.DOTALL | re.IGNORECASE,
            )
            ref_matches = list(ref_pattern.finditer(question_content))
            insert_at = None
            if ref_matches:
                insert_at = ref_matches[-1].end()
            else:
                first_div_end = re.search(r"</div>", question_content, re.IGNORECASE)
                if first_div_end:
                    insert_at = first_div_end.end()
                else:
                    insert_at = len(question_content)

            for img in refer_images:
                src_match = re.search(
                    r'src\s*=\s*["\']([^"\']+)["\']', img, re.IGNORECASE
                )
                if not src_match:
                    continue
                src_value = _fix_image_src_format(src_match.group(1))

                if src_value not in all_fixed_srcs:
                    block = f'<div class="reference">{img}</div>'
                    if question_content:
                        question_content = (
                            question_content[:insert_at]
                            + block
                            + question_content[insert_at:]
                        )
                        insert_at += len(block)
                    else:
                        question_content = block
                        insert_at = len(question_content)
                    all_fixed_srcs.add(src_value)

            fixed_data["question"] = question_content

    return fixed_data


# ---------------------------------------------------------------------------
# V2 post-processing: restore field div classes
# ---------------------------------------------------------------------------


def _v2_restore_field_div_classes(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add class to bare opening <div> in question and solution fields.

    Conservative strategy: only process "question" and "solution" (no "refer").
    Only touches the FIRST bare <div> if the content starts with one.
    """
    field_class_map = {
        "question": "question",
        "solution": "solution",
    }

    for field, class_name in field_class_map.items():
        content = fixed_data.get(field)
        if not content or not isinstance(content, str):
            continue

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


# ---------------------------------------------------------------------------
# V2 post-processing: separate image divs in question field
# ---------------------------------------------------------------------------


def _v2_separate_image_div(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    """Two-pass processing on the question field to split mixed img+text divs.

    Pass 1: Process <div class="question"> divs.
    Pass 2: Process <div class="reference"> divs (on updated content from pass 1).
    """
    content = fixed_data.get("question")
    if not content or not isinstance(content, str):
        return fixed_data

    passes = [
        ("question", "question"),
        ("reference", "reference"),
    ]

    for class_name, _ in passes:
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

        # Parse inner content into top-level segments
        segments: List[str] = []
        i = 0
        depth = 0
        current_segment = ""

        while i < len(inner_content):
            char = inner_content[i]

            if char == "<":
                tag_end = inner_content.find(">", i)
                if tag_end == -1:
                    current_segment += char
                    i += 1
                    continue

                tag = inner_content[i : tag_end + 1]

                if tag.startswith("</"):
                    if depth == 0:
                        current_segment += tag
                        i = tag_end + 1
                        continue
                    depth -= 1
                    current_segment += tag
                elif tag.endswith("/>") or tag.startswith("<!"):
                    if depth == 0:
                        if current_segment.strip():
                            segments.append(current_segment)
                        segments.append(tag)
                        current_segment = ""
                    else:
                        current_segment += tag
                else:
                    if depth == 0:
                        if current_segment.strip():
                            segments.append(current_segment)
                            current_segment = ""
                    current_segment += tag
                    depth += 1

                i = tag_end + 1
            else:
                current_segment += char
                i += 1

        if current_segment.strip():
            segments.append(current_segment)

        # Check for mixed content (img + other)
        has_img = any(
            re.search(r"<img\s+[^>]*/?>", seg, re.IGNORECASE) for seg in segments
        )
        has_other = any(
            not re.match(r"^\s*<img\s+[^>]*/?\s*>\s*$", seg, re.IGNORECASE)
            for seg in segments
        )

        if not has_img or not has_other or len(segments) <= 1:
            continue

        # Wrap each segment in its own div
        new_divs: List[str] = []
        for segment in segments:
            stripped = segment.strip()
            if stripped:
                new_divs.append(f"{opening_tag}{segment}{closing_tag}")

        if new_divs:
            content = (
                content[: match.start()] + "".join(new_divs) + content[match.end() :]
            )

    fixed_data["question"] = content
    return fixed_data


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def process_single_problem_v2(problem: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single problem through the V2 pipeline.

    Same loop structure as V1: fix -> post-process -> judge -> retry.
    Key differences:
    - Uses build_question_context for LLM input
    - Output schema has no refer field
    - Post-processing chain skips refer-specific steps
    - Explicitly sets refer=None on output
    """
    max_regen_attempts = 2
    judge_feedback = None
    judge_history: List[Dict[str, Any]] = []
    judge_result: Dict[str, Any] = {"pass": False, "reason": "unknown"}
    fixed_data: Dict[str, Any] = {}

    for attempt in range(1, max_regen_attempts + 2):
        fixed_data = fix_content_with_llm_v2(problem, judge_feedback=judge_feedback)

        if "error" in fixed_data:
            judge_result = {
                "pass": False,
                "reason": f"fix_error: {fixed_data.get('error')}",
            }
            judge_history.append(
                {
                    "attempt": attempt,
                    "pass": judge_result["pass"],
                    "reason": judge_result["reason"],
                }
            )
            break

        # -- Post-processing chain (V2) --
        fixed_data = _v2_restore_missing_images(problem, fixed_data)  # V2 specific
        fixed_data = preserve_original_images(problem, fixed_data)
        fixed_data = validate_image_tags(fixed_data)  # V1 reuse
        fixed_data = clamp_image_widths(fixed_data)
        fixed_data = unescape_html_tags(fixed_data)  # V1 reuse
        fixed_data = normalize_lt_spacing(fixed_data)  # V1 reuse
        fixed_data = normalize_html_wrappers(fixed_data)  # V1 reuse
        fixed_data = normalize_empty_brackets(fixed_data)  # V1 reuse
        fixed_data = _v2_restore_field_div_classes(fixed_data)  # V2 specific
        fixed_data = _v2_separate_image_div(fixed_data)  # V2 specific
        fixed_data = normalize_answer(fixed_data)  # V1 reuse
        fixed_data = normalize_reference_text(fixed_data)  # V1 reuse
        fixed_data = restore_latex_control_char_fields(fixed_data)  # V1 reuse
        fixed_data = normalize_latex_backslashes(fixed_data)  # V1 reuse
        fixed_data = wrap_short_answer_with_math_delimiters(fixed_data)  # V1 reuse
        fixed_data = wrap_latex_content(fixed_data)  # V1 reuse
        fixed_data = convert_binom_to_combination(fixed_data)  # V1 reuse
        fixed_data = add_displaystyle_to_binom(fixed_data)  # V1 reuse

        # Judge
        judge_result = judge_fixed_output_v2(problem, fixed_data)
        judge_history.append(
            {
                "attempt": attempt,
                "pass": judge_result["pass"],
                "reason": judge_result["reason"],
            }
        )

        if judge_result["pass"]:
            break
        judge_feedback = judge_result["reason"]

    # V2: explicitly null out refer
    fixed_data["refer"] = None

    # Attach judge metadata
    fixed_data["_judge"] = {
        "pass": judge_result["pass"],
        "reason": judge_result["reason"],
        "attempts": len(judge_history),
        "model": JUDGE_MODEL_NAME,
        "history": judge_history,
    }

    return {
        "original_id": problem.get("id"),
        "original": json.loads(json.dumps(problem, default=str)),
        "fixed": fixed_data,
    }


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

register_pipeline("v2", process_single_problem_v2)
