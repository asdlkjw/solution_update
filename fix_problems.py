#!/usr/bin/env python3
import os
import sys
import json
import argparse
import csv
import re
import time
import pymysql
import pymysql.cursors
import requests
from dotenv import load_dotenv
from pathlib import Path
from typing import List, Dict, Any, Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from urllib.parse import urlsplit, urlunsplit

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PROD_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PROD_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
ENABLE_LT_SPACING_FIX = os.getenv("ENABLE_LT_SPACING_FIX", "1").lower() not in {
    "0",
    "false",
    "no",
}

MODEL_NAME = "google/gemini-3-flash-preview"
JUDGE_MODEL_NAME = MODEL_NAME
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
JUDGE_SYSTEM_PROMPT_MC = (
    "너는 수학 문제 수정 결과를 검수하는 심사자다. 원본과 수정본을 비교해서 품질을 판단한다. "
    "다음 항목을 엄격히 확인하라: 필수 조건 누락(특히 question/refer), "
    "question이 없는데 refer만 존재, LaTeX 수식 깨짐, HTML 태그 불완전/잘못된 중첩, "
    "가독성 저하(문장 붕괴, 의미 모호). "
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

JUDGE_SYSTEM_PROMPT_SA = (
    "너는 수학 문제 수정 결과를 검수하는 심사자다. 원본과 수정본을 비교해서 품질을 판단한다. "
    "다음 항목을 엄격히 확인하라: 필수 조건 누락(특히 question/refer), "
    "question이 없는데 refer만 존재, LaTeX 수식 깨짐, HTML 태그 불완전/잘못된 중첩, "
    "가독성 저하(문장 붕괴, 의미 모호). "
    "주관식 규칙: answer는 solution의 최종 결론과 일치해야 한다(HTML/LaTeX 포맷 차이는 허용). "
    "통과면 pass=true와 매우 짧은 reason을 주고, "
    "실패면 pass=false와 짧고 명확한 이유를 한국어로 적어라."
)


def read_group_ids_from_csv(csv_path: str) -> List[int]:
    # CSV 파일에서 group_id 목록을 읽어옵니다.
    group_ids = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row:  # 빈 줄 무시
                    group_ids.append(int(row[0].strip()))
        return group_ids
    except FileNotFoundError:
        print(f"Error: CSV file not found at {csv_path}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error parsing CSV file: {e}", file=sys.stderr)
        sys.exit(1)


def get_db_connection():
    # 데이터베이스 연결을 생성합니다.
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=int(DB_PORT) if DB_PORT else 3306,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            cursorclass=pymysql.cursors.DictCursor,
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_problems(
    ids: List[int] | None = None,
    group_ids: List[int] | None = None,
    mode: Literal["id", "group_id"] = "id",
) -> List[Dict[str, Any]]:
    # ID 또는 group_id 리스트에 해당하는 문제 데이터를 가져옵니다.
    conn = get_db_connection()
    # Connection 객체 생성 시 cursorclass를 지정했으므로 여기서는 그냥 cursor() 호출
    cursor = conn.cursor()

    # 식별을 위해 id 컬럼은 필수로 포함하고, 나머지는 요청된 컬럼만 조회
    cols = "id, group_id, type, question, refer, choice1, choice2, choice3, choice4, choice5, answer, solution, human_review"

    try:
        if mode == "id":
            # ID 기반 조회
            if ids is None or len(ids) == 0:
                return []
            if len(ids) == 1:
                query = f"SELECT {cols} FROM problem WHERE id = %s"
                cursor.execute(query, (ids[0],))
            else:
                # pymysql에서 IN 절 처리를 위해 %s 사용 및 튜플 전달
                format_strings = ",".join(["%s"] * len(ids))
                query = f"SELECT {cols} FROM problem WHERE id IN ({format_strings})"
                cursor.execute(query, tuple(ids))
        elif mode == "group_id":
            # group_id 기반 조회
            if group_ids is None or len(group_ids) == 0:
                return []
            if len(group_ids) == 1:
                query = f"SELECT {cols} FROM problem WHERE group_id = %s"
                cursor.execute(query, (group_ids[0],))
            else:
                # pymysql에서 IN 절 처리를 위해 %s 사용 및 튜플 전달
                format_strings = ",".join(["%s"] * len(group_ids))
                query = (
                    f"SELECT {cols} FROM problem WHERE group_id IN ({format_strings})"
                )
                cursor.execute(query, tuple(group_ids))

        rows = cursor.fetchall()
        return rows  # pymysql DictCursor returns list of dicts directly
    except Exception as e:
        print(f"Error fetching data: {e}", file=sys.stderr)
        return []
    finally:
        cursor.close()
        conn.close()


def fix_content_with_llm(
    problem_data: Dict[str, Any], judge_feedback: str | None = None
) -> Dict[str, Any]:
    # OpenRouter Gemini 모델을 사용하여 문제 내용을 수정합니다.

    # LLM 입력용 필드 필터링
    target_fields = [
        "type",
        "question",
        "refer",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "answer",
        "solution",
    ]
    # DB에서 가져온 데이터 중 target_fields에 해당하는 것만 추출
    filtered_input = {k: problem_data.get(k) for k in target_fields}

    serialized_data = json.loads(json.dumps(filtered_input, default=str))

    # Load prompt template from external JSON file
    try:
        with open(
            Path(__file__).parent / "prompt_template.json", "r", encoding="utf-8"
        ) as f:
            prompts = json.load(f)
    except FileNotFoundError:
        print("Error: prompt_template.json not found.", file=sys.stderr)
        return {
            "error": "prompt_template.json not found",
            "original_id": problem_data.get("id"),
        }

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
            "refer": {"type": ["string", "null"]},
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
            "refer",
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

    user_content = prompts["user"].format(
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
            {"role": "system", "content": prompts["system"]},
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
                error_msg = "Unauthorized: check OPENROUTER_API_KEY"
                print(
                    f"Error calling LLM for ID {problem_data.get('id')}: {error_msg}",
                    file=sys.stderr,
                )
                return {"error": error_msg, "original_id": problem_data.get("id")}
            if response.status_code in retry_statuses and attempt < max_attempts - 1:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            result = response.json()

            if "choices" not in result:
                error_msg = f"Invalid API response format (missing 'choices'). Response: {result}"
                if attempt < max_attempts - 1:
                    print(
                        f"API format error for ID {problem_data.get('id')}, retrying... ({attempt + 1}/{max_attempts})",
                        file=sys.stderr,
                    )
                    time.sleep(2**attempt)
                    continue
                print(
                    f"Error calling LLM for ID {problem_data.get('id')}: {error_msg}",
                    file=sys.stderr,
                )
                return {"error": error_msg, "original_id": problem_data.get("id")}

            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
        except requests.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code == 401:
                if attempt < 1 and attempt < max_attempts - 1:
                    time.sleep(2**attempt)
                    continue
                error_msg = "Unauthorized: check OPENROUTER_API_KEY"
                print(
                    f"Error calling LLM for ID {problem_data.get('id')}: {error_msg}",
                    file=sys.stderr,
                )
                return {"error": error_msg, "original_id": problem_data.get("id")}
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
                continue
            print(
                f"Error calling LLM for ID {problem_data.get('id')}: {e}",
                file=sys.stderr,
            )
            return {"error": str(e), "original_id": problem_data.get("id")}
        except Exception as e:
            print(
                f"Error calling LLM for ID {problem_data.get('id')}: {e}",
                file=sys.stderr,
            )
            return {"error": str(e), "original_id": problem_data.get("id")}

    return {
        "error": "Unknown error after retries",
        "original_id": problem_data.get("id"),
    }


def judge_fixed_output(
    original: Dict[str, Any], fixed: Dict[str, Any]
) -> Dict[str, Any]:
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
        "refer": original.get("refer"),
        "choice1": original.get("choice1"),
        "choice2": original.get("choice2"),
        "choice3": original.get("choice3"),
        "choice4": original.get("choice4"),
        "choice5": original.get("choice5"),
    }
    fixed_payload = {
        "type": fixed.get("type"),
        "question": fixed.get("question"),
        "refer": fixed.get("refer"),
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
        JUDGE_SYSTEM_PROMPT_MC
        if problem_type == "multiple_choice"
        else JUDGE_SYSTEM_PROMPT_SA
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


def normalize_answer(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    if fixed_data.get("type") != "multiple_choice":
        return fixed_data

    ans = str(fixed_data.get("answer", "")).strip()

    circle_to_num = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5"}
    for circle, num in circle_to_num.items():
        ans = ans.replace(circle, num)
    ans = ans.strip()

    if ans not in ["1", "2", "3", "4", "5"]:
        for i in range(1, 6):
            choice_val = str(fixed_data.get(f"choice{i}", "")).strip()
            if choice_val == ans:
                ans = str(i)
                break

    fixed_data["answer"] = ans
    return fixed_data


def normalize_html_wrappers(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    fields = ["choice1", "choice2", "choice3", "choice4", "choice5", "answer"]

    for field in fields:
        content = fixed_data.get(field)
        if not content or not isinstance(content, str):
            continue

        pattern = r'^\s*<div\s+class=["\'](?:choice|answer)["\']\s*>(.*)</div>\s*$'

        match = re.match(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            fixed_data[field] = match.group(1).strip()

    return fixed_data


def wrap_short_answer_with_math_delimiters(
    fixed_data: Dict[str, Any],
) -> Dict[str, Any]:
    if fixed_data.get("type") == "multiple_choice":
        return fixed_data

    answer = fixed_data.get("answer")
    if not isinstance(answer, str):
        return fixed_data

    answer = answer.strip()
    if not answer:
        return fixed_data

    if "$" in answer or r"\(" in answer or r"\)" in answer:
        return fixed_data

    if SHORT_ANSWER_ALLOWED_RE.fullmatch(answer):
        fixed_data["answer"] = f"${answer}$"

    return fixed_data


EMPTY_BRACKET_RE = re.compile(r"\[\s*\]")
HTML_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")
LT_FOLLOWED_BY_ALPHA_RE = re.compile(r"<(?=[A-Za-z])")
SHORT_ANSWER_ALLOWED_RE = re.compile(
    r"^[0-9A-Za-z\s\+\-\*/=<>^_.,:;!?()\[\]{}~`'\"|\\%&#!]+$"
)


def normalize_empty_brackets(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "question",
        "refer",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "solution",
    ]

    for field in fields:
        content = fixed_data.get(field)
        if isinstance(content, str):
            fixed_data[field] = EMPTY_BRACKET_RE.sub("[  ]", content)

    return fixed_data


def unescape_html_tags(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    tags = ["div", "p", "ol", "ul", "li"]

    for key, value in fixed_data.items():
        if isinstance(value, str):
            for tag in tags:
                pattern = f"<\\\\+/{tag}>"
                replacement = f"</{tag}>"
                value = re.sub(pattern, replacement, value)

                pattern_open = f"<\\\\+{tag}"
                replacement_open = f"<{tag}"
                value = re.sub(pattern_open, replacement_open, value)

            fixed_data[key] = value

    return fixed_data


def normalize_lt_spacing(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    if not ENABLE_LT_SPACING_FIX:
        return fixed_data

    fields = [
        "question",
        "refer",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "answer",
        "solution",
    ]

    for field in fields:
        content = fixed_data.get(field)
        if not isinstance(content, str):
            continue
        parts = HTML_TAG_SPLIT_RE.split(content)
        for idx, part in enumerate(parts):
            if not part:
                continue
            if HTML_TAG_SPLIT_RE.fullmatch(part):
                continue
            parts[idx] = LT_FOLLOWED_BY_ALPHA_RE.sub("< ", part)
        fixed_data[field] = "".join(parts)

    return fixed_data


LATEX_CONTROL_CHAR_SUFFIXES = {
    "\t": ("t", ["imes", "ext", "frac"]),
    "\r": ("r", ["ight"]),
    "\f": ("f", ["rac"]),
    "\v": ("v", ["dots"]),
    "\b": ("b", ["egin"]),
    "\a": ("a", ["lpha"]),
    "\n": ("n", ["abla", "eq", "ot"]),
}

LATEX_CONTROL_CHAR_FIELDS = [
    "question",
    "refer",
    "choice1",
    "choice2",
    "choice3",
    "choice4",
    "choice5",
    "answer",
    "solution",
]

DOUBLE_BACKSLASH_RE = re.compile(r"\\\\(?=[A-Za-z\[\]\(\)])")

IMAGE_CHECK_CACHE: Dict[str, bool] = {}
IMAGE_EXTENSIONS = {".bmp", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r"src\s*=\s*([\"'])([^\"']+)\1", re.IGNORECASE)
IMG_EMPTY_SRC_RE = re.compile(r"src\s*=\s*([\"'])\s*\1", re.IGNORECASE)


def restore_latex_control_char_commands(text: str) -> str:
    for control_char, (prefix, suffixes) in LATEX_CONTROL_CHAR_SUFFIXES.items():
        for suffix in suffixes:
            text = text.replace(f"{control_char}{suffix}", f"\\{prefix}{suffix}")
    return text


def restore_latex_control_char_fields(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    for field in LATEX_CONTROL_CHAR_FIELDS:
        value = fixed_data.get(field)
        if isinstance(value, str):
            fixed_data[field] = restore_latex_control_char_commands(value)
    return fixed_data


def normalize_latex_backslashes(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "question",
        "refer",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "answer",
        "solution",
    ]

    for field in fields:
        content = fixed_data.get(field)
        if isinstance(content, str):
            fixed_data[field] = DOUBLE_BACKSLASH_RE.sub(r"\\", content)

    return fixed_data


def remove_stray_newline_escapes(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "question",
        "refer",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "answer",
        "solution",
    ]

    for field in fields:
        content = fixed_data.get(field)
        if isinstance(content, str):
            fixed_data[field] = re.sub(r"\\n(?![A-Za-z])", " ", content)

    return fixed_data


def _build_image_variants(url: str) -> List[str]:
    parts = urlsplit(url)
    path = parts.path or ""
    if not path:
        return [url]

    base, ext = os.path.splitext(path)
    candidates = [url]
    for suffix in [".bmp", ".jpg", ".png"]:
        if ext:
            new_path = f"{base}{suffix}"
        else:
            new_path = f"{path}{suffix}"
        candidates.append(
            urlunsplit(
                (parts.scheme, parts.netloc, new_path, parts.query, parts.fragment)
            )
        )

    seen = set()
    ordered = []
    for candidate in candidates:
        if candidate not in seen:
            ordered.append(candidate)
            seen.add(candidate)
    return ordered


def _is_image_renderable(url: str) -> bool:
    cached = IMAGE_CHECK_CACHE.get(url)
    if cached is not None:
        return cached

    try:
        with requests.get(url, stream=True, timeout=5) as response:
            if response.status_code >= 400:
                IMAGE_CHECK_CACHE[url] = False
                return False
            content_type = response.headers.get("Content-Type")
            content_type_lower = content_type.lower() if content_type else ""
            if content_type_lower.startswith("image/"):
                IMAGE_CHECK_CACHE[url] = True
                return True
            if not content_type_lower or content_type_lower.startswith(
                "application/octet-stream"
            ):
                path = urlsplit(url).path
                _, ext = os.path.splitext(path.lower())
                is_image_ext = ext in IMAGE_EXTENSIONS
                IMAGE_CHECK_CACHE[url] = is_image_ext
                return is_image_ext
            IMAGE_CHECK_CACHE[url] = False
            return False
    except requests.RequestException:
        IMAGE_CHECK_CACHE[url] = False
        return False

    IMAGE_CHECK_CACHE[url] = True
    return True


def _resolve_image_src(src: str) -> str | None:
    cleaned = src.strip()
    if not cleaned:
        return None
    if cleaned.lower() in {"null", "error"}:
        return None
    if cleaned.startswith("data:"):
        return cleaned

    parts = urlsplit(cleaned)
    if parts.scheme not in {"http", "https"}:
        return cleaned

    for candidate in _build_image_variants(cleaned):
        if _is_image_renderable(candidate):
            return candidate
    return None


def validate_image_tags(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "question",
        "refer",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "solution",
    ]

    empty_src_removed = 0

    def replace_tag(match: re.Match[str]) -> str:
        nonlocal empty_src_removed
        tag = match.group(0)
        if IMG_EMPTY_SRC_RE.search(tag):
            empty_src_removed += 1
            return ""
        src_match = IMG_SRC_RE.search(tag)
        if not src_match:
            return ""

        src_value = src_match.group(2).strip()
        if not src_value:
            return ""
        resolved = _resolve_image_src(src_value)
        if resolved is None:
            return ""
        if resolved == src_value:
            return tag

        quote = src_match.group(1)
        return IMG_SRC_RE.sub(f"src={quote}{resolved}{quote}", tag, count=1)

    for field in fields:
        content = fixed_data.get(field)
        if isinstance(content, str):
            fixed_data[field] = IMG_TAG_RE.sub(replace_tag, content)

    fixed_data["_img_empty_src_removed"] = empty_src_removed

    return fixed_data


def _replace_math_segments(text: str, placeholder: str = "◎") -> str:
    patterns = [r"\$\$.*?\$\$", r"\$.*?\$", r"\\\(.*?\\\)"]
    candidates: List[tuple[int, int]] = []
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            candidates.append((match.start(), match.end()))
    if not candidates:
        return text
    start, end = sorted(candidates, key=lambda item: (item[0], item[1] - item[0]))[0]
    return text[:start] + placeholder + _replace_math_segments(text[end:], placeholder)


def _has_latex_syntax(text: str) -> bool:
    cleaned = re.sub(r"(?:_\s*){2,}", "", text)
    if re.search(r"\\[A-Za-z]+", cleaned):
        return True
    if re.search(r"\^(\{[^}]*\}|[A-Za-z0-9])", cleaned):
        return True
    if re.search(r"(?<=[A-Za-z0-9\}\)])_(\{[^}]*\}|[A-Za-z0-9])", cleaned):
        return True
    return False


def _collect_latex_tokens(text: str) -> List[Dict[str, Any]]:
    skip_ranges: List[tuple[int, int]] = []
    for pattern in [r"\$\$.*?\$\$", r"\$.*?\$", r"\\\(.*?\\\)"]:
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            skip_ranges.append((match.start(), match.end()))
    for match in re.finditer(r"<[^>]+>", text):
        skip_ranges.append((match.start(), match.end()))

    skip_ranges.sort()

    def is_skipped(start: int, end: int) -> bool:
        for left, right in skip_ranges:
            if start < right and end > left:
                return True
        return False

    tokens: List[Dict[str, Any]] = []
    patterns = [
        r"\\[A-Za-z]+",
        r"\^(\{[^}]*\}|[A-Za-z0-9])",
        r"(?<=[A-Za-z0-9\}\)])_(\{[^}]*\}|[A-Za-z0-9])",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if is_skipped(match.start(), match.end()):
                continue
            token = match.group(0)
            if not token:
                continue
            start = match.start()
            end = match.end()
            before = text[max(0, start - 20) : start]
            after = text[end : end + 20]
            tokens.append(
                {
                    "start": start,
                    "end": end,
                    "token": token,
                    "context_before": before,
                    "context_after": after,
                }
            )
    return tokens


def detect_latex_syntax_missing(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "question",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice5",
        "answer",
        "solution",
    ]
    bad_fields: List[str] = []
    bad_spans: List[Dict[str, Any]] = []
    for field in fields:
        content = fixed_data.get(field)
        if not content or not isinstance(content, str):
            continue
        replaced = _replace_math_segments(content)
        stripped = re.sub(r"<[^>]+>", " ", replaced)
        tokens = _collect_latex_tokens(content) if _has_latex_syntax(stripped) else []
        if tokens:
            bad_fields.append(field)
            for token in tokens:
                token["field"] = field
                bad_spans.append(token)

    if not bad_fields:
        return fixed_data

    reasons = fixed_data.get("_auto_bad_reasons")
    merged: List[str] = []
    if isinstance(reasons, list):
        merged.extend([r for r in reasons if isinstance(r, str)])
    for field in bad_fields:
        merged.append(f"latex_missing_delimiter:{field}")
    fixed_data["_auto_bad_reasons"] = list(dict.fromkeys(merged))
    fixed_data["_latex_bad_fields"] = list(dict.fromkeys(bad_fields))
    if bad_spans:
        fixed_data["_latex_bad_spans"] = bad_spans
    return fixed_data


def normalize_refer_view_header(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    question = fixed_data.get("question")
    if not isinstance(question, str):
        return fixed_data

    if re.search(r"보\s*기", question):
        return fixed_data

    refer = fixed_data.get("refer")
    if not isinstance(refer, str):
        return fixed_data

    patterns = [
        r"<\s*p\s*>\s*(?:&lt;|<)\s*보\s*기\s*(?:&gt;|>)\s*</\s*p\s*>",
        r"(?:&lt;|<)\s*보\s*기\s*(?:&gt;|>)",
    ]

    for pattern in patterns:
        refer = re.sub(pattern, "", refer, flags=re.IGNORECASE)

    fixed_data["refer"] = refer.strip()
    return fixed_data


def process_single_problem(problem: Dict[str, Any]) -> Dict[str, Any]:
    # 단일 문제 처리를 위한 래퍼 함수 (병렬 실행용)
    max_regen_attempts = 2
    judge_feedback = None
    judge_history = []
    judge_result = {"pass": False, "reason": "unknown"}
    fixed_data: Dict[str, Any] = {}

    for attempt in range(1, max_regen_attempts + 2):
        fixed_data = fix_content_with_llm(problem, judge_feedback=judge_feedback)

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

        # 후처리 로직 적용
        fixed_data = normalize_answer(fixed_data)
        fixed_data = unescape_html_tags(fixed_data)
        fixed_data = normalize_lt_spacing(fixed_data)
        fixed_data = validate_image_tags(fixed_data)
        fixed_data = restore_latex_control_char_fields(fixed_data)
        fixed_data = normalize_latex_backslashes(fixed_data)
        fixed_data = normalize_refer_view_header(fixed_data)
        fixed_data = normalize_html_wrappers(fixed_data)
        fixed_data = wrap_short_answer_with_math_delimiters(fixed_data)
        fixed_data = normalize_empty_brackets(fixed_data)
        fixed_data = detect_latex_syntax_missing(fixed_data)

        judge_result = {"pass": True, "reason": "judge_skipped"}
        judge_history.append(
            {
                "attempt": attempt,
                "pass": judge_result["pass"],
                "reason": judge_result["reason"],
            }
        )
        break

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


def generate_html_report(results: List[Dict[str, Any]], output_path: Path):
    # 결과 데이터를 HTML 리포트로 저장합니다.
    try:
        with open(
            Path(__file__).parent / "report_template.html", "r", encoding="utf-8"
        ) as f:
            html_content = f.read()
    except FileNotFoundError:
        print("Error: report_template.html not found.", file=sys.stderr)
        return

    # JSON 데이터를 JS 변수로 주입
    json_str = json.dumps(results, ensure_ascii=False)
    final_html = html_content.replace("__JSON_DATA_PLACEHOLDER__", json_str)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"Generated HTML Report: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Fix math problems using Gemini 2.0 Flash"
    )
    parser.add_argument(
        "--ids",
        type=str,
        required=False,
        help="Comma-separated list of problem IDs (e.g., 101,102,103)",
    )
    parser.add_argument(
        "--group-ids",
        type=str,
        required=False,
        help="Path to CSV file containing group_ids",
    )
    parser.add_argument(
        "--output", type=str, default="fixed_results.json", help="Output JSON file path"
    )

    args = parser.parse_args()

    # 최소 하나의 파라미터는 필수
    if not args.ids and not args.group_ids:
        print("Error: Either --ids or --group-ids must be provided.", file=sys.stderr)
        sys.exit(1)

    # 두 파라미터 중 하나만 사용
    if args.ids and args.group_ids:
        print("Error: Cannot use both --ids and --group-ids together.", file=sys.stderr)
        sys.exit(1)

    # 파라미터에 따라 조회 모드 결정
    if args.ids:
        try:
            ids = [int(x.strip()) for x in args.ids.split(",")]
        except ValueError:
            print("Error: IDs must be integers.", file=sys.stderr)
            sys.exit(1)

        print(f"Fetching {len(ids)} problems from DB by IDs...")
        problems = fetch_problems(ids=ids, mode="id")
    else:
        # group_ids CSV 파일 처리
        csv_path = Path(args.group_ids)
        if not csv_path.exists():
            print(f"Error: CSV file not found at {csv_path}", file=sys.stderr)
            sys.exit(1)

        group_ids = read_group_ids_from_csv(str(csv_path))
        print(f"Fetching {len(group_ids)} groups from DB by group_ids...")
        problems = fetch_problems(group_ids=group_ids, mode="group_id")

    if not problems:
        print("No problems found.", file=sys.stderr)
        sys.exit(1)

    results = []
    print(f"Processing {len(problems)} items with {MODEL_NAME} (Parallel x32)...")

    # ThreadPoolExecutor를 사용한 병렬 처리
    with ThreadPoolExecutor(max_workers=32) as executor:
        future_to_id = {
            executor.submit(process_single_problem, p): p["id"] for p in problems
        }

        for future in tqdm(
            as_completed(future_to_id), total=len(problems), desc="Processing"
        ):
            p_id = future_to_id[future]
            try:
                data = future.result()
                results.append(data)
            except Exception as exc:
                print(f"Problem {p_id} generated an exception: {exc}", file=sys.stderr)

    # 결과 정렬 (ID 순)
    results.sort(key=lambda x: x["original_id"])

    output_path = Path(__file__).parent / args.output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Done. JSON Results saved to {output_path}")

    # HTML 리포트 생성 (데이터 주입)
    html_path = output_path.with_suffix(".html")
    generate_html_report(results, html_path)


if __name__ == "__main__":
    main()
