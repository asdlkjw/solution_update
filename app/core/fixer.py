import argparse
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Literal

import pymysql
import pymysql.cursors
import requests
from dotenv import load_dotenv
from tqdm import tqdm

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PROD_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PROD_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

MODEL_NAME = "google/gemini-3-flash-preview"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "prompt_template.json"
REPORT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "report_template.html"


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


def fix_content_with_llm(problem_data: Dict[str, Any]) -> Dict[str, Any]:
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
        with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
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

    payload = {
        "model": MODEL_NAME,
        "temperature": 0.4,
        "max_tokens": 4000,
        "top_p": 0.95,
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {
                "role": "user",
                "content": prompts["user"].format(
                    json_data=json.dumps(serialized_data, indent=2, ensure_ascii=False)
                ),
            },
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
    retry_statuses = {502, 503, 504}
    for attempt in range(max_attempts):
        payload["temperature"] = 0.4 if attempt == 0 else 0.7
        try:
            response = requests.post(
                OPENROUTER_URL, headers=headers, json=payload, timeout=60
            )
            if response.status_code in retry_statuses and attempt < max_attempts - 1:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            result = response.json()

            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
        except requests.RequestException as e:
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
                continue
            print(
                f"Error calling LLM for ID {problem_data.get('id')}: {e}",
                file=sys.stderr,
            )
            return {"error": str(e), "original_id": problem_data.get("id")}
        except json.JSONDecodeError as e:
            if attempt < max_attempts - 1:
                print(
                    f"JSON parse error for ID {problem_data.get('id')}, retrying... ({attempt + 1}/{max_attempts})",
                    file=sys.stderr,
                )
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


def restore_missing_images(
    original_data: Dict[str, Any], fixed_data: Dict[str, Any]
) -> Dict[str, Any]:
    """원본에 있던 이미지 태그가 fixed에서 누락된 경우 복원합니다."""
    img_pattern = r'<img\s+[^>]*src\s*=\s*["\'][^"\']+["\'][^>]*/?\s*>'

    fields_to_check = [
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

    for field in fields_to_check:
        original_content = original_data.get(field)
        fixed_content = fixed_data.get(field)

        if not original_content or not isinstance(original_content, str):
            continue

        # 원본에서 이미지 태그 추출
        original_images = re.findall(img_pattern, str(original_content), re.IGNORECASE)
        if not original_images:
            continue

        # fixed가 None이거나 빈 문자열인 경우
        if not fixed_content:
            fixed_content = ""

        # fixed에서 이미지 태그 추출
        fixed_images = re.findall(img_pattern, str(fixed_content), re.IGNORECASE)

        # 누락된 이미지 찾기
        for img in original_images:
            # src 값 추출하여 비교
            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img, re.IGNORECASE)
            if not src_match:
                continue
            src_value = src_match.group(1)

            # fixed_images에 같은 src가 있는지 확인
            img_exists = any(src_value in fixed_img for fixed_img in fixed_images)

            if not img_exists:
                # 이미지를 콘텐츠 앞에 추가
                if fixed_content:
                    fixed_data[field] = img + " " + fixed_content
                else:
                    fixed_data[field] = img
                fixed_content = fixed_data[field]

    return fixed_data


def remove_refer_markers(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    """refer 필드에서 <표>, <조건> 마커를 제거합니다 (question에 없을 때만)."""
    question = fixed_data.get("question")
    if not isinstance(question, str):
        return fixed_data

    refer = fixed_data.get("refer")
    if not isinstance(refer, str):
        return fixed_data

    # 각 마커에 대해 처리
    markers = [
        (
            r"표",
            [
                r"<\s*p\s*>\s*(?:&lt;|<)\s*표\s*(?:&gt;|>)\s*</\s*p\s*>",
                r"(?:&lt;|<)\s*표\s*(?:&gt;|>)",
            ],
        ),
        (
            r"조\s*건",
            [
                r"<\s*p\s*>\s*(?:&lt;|<)\s*조\s*건\s*(?:&gt;|>)\s*</\s*p\s*>",
                r"(?:&lt;|<)\s*조\s*건\s*(?:&gt;|>)",
            ],
        ),
    ]

    for marker_word, patterns in markers:
        # question에 해당 단어가 없으면 refer에서 제거
        if not re.search(marker_word, question):
            for pattern in patterns:
                refer = re.sub(pattern, "", refer, flags=re.IGNORECASE)

    fixed_data["refer"] = refer.strip()
    return fixed_data


def wrap_latex_content(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    """LaTeX 수식이 $로 감싸지지 않은 경우 감쌉니다."""
    target_fields = ["choice1", "choice2", "choice3", "choice4", "choice5", "answer"]

    # LaTeX 명령어 패턴 (backslash로 시작)
    latex_command_pattern = r"\\(?:frac|cfrac|sqrt|cdot|times|div|pm|mp|leq|geq|neq|approx|infty|sum|prod|int|lim|sin|cos|tan|log|ln|exp|alpha|beta|gamma|delta|theta|pi|sigma|omega)"

    for field in target_fields:
        content = fixed_data.get(field)
        if not content or not isinstance(content, str):
            continue

        # HTML 태그 제거 후 텍스트만 추출
        text_only = re.sub(r"<[^>]+>", "", content).strip()
        if not text_only:
            continue

        # 이미 $로 완전히 감싸져 있으면 스킵
        if text_only.startswith("$") and text_only.endswith("$"):
            continue

        # $ 개수 확인
        dollar_count = content.count("$")

        # $가 없는 경우에만 처리
        if dollar_count == 0:
            # 한글 체크 - 한글 음절(\uAC00-\uD7A3) 또는 자모(\u3131-\u318F)가 있으면 스킵
            if re.search(r"[\uAC00-\uD7A3\u3131-\u318F]", text_only):
                continue

            # HTML 태그가 있으면 스킵
            if "<" in content and ">" in content:
                continue

            # LaTeX 명령어가 있으면 감싸기
            if re.search(latex_command_pattern, text_only):
                fixed_data[field] = f"${text_only}$"
                continue

            # 영문자, 숫자, 수학 기호만 있으면 감싸기
            math_content_pattern = r"^[\s\w\d\+\-\*/\^=<>\(\)\[\]\{\},\.\\]+$"
            if re.match(math_content_pattern, text_only) and len(text_only) > 0:
                fixed_data[field] = f"${text_only}$"

    return fixed_data


def normalize_reference_text(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    """'표 참고', '그래프 참고' 등을 '해설 참고'로 통일합니다."""
    patterns = [
        (r"표\s*참고", "해설 참고"),
        (r"그래프\s*참고", "해설 참고"),
        (r"그림\s*참고", "해설 참고"),
        (r"도표\s*참고", "해설 참고"),
        (r"표를\s*참고", "해설을 참고"),
        (r"그래프를\s*참고", "해설을 참고"),
        (r"그림을\s*참고", "해설을 참고"),
    ]

    # answer와 solution 필드에서만 적용
    fields = ["answer", "solution"]

    for field in fields:
        content = fixed_data.get(field)
        if not content or not isinstance(content, str):
            continue

        for pattern, replacement in patterns:
            content = re.sub(pattern, replacement, content)

        fixed_data[field] = content

    return fixed_data


def process_single_problem(problem: Dict[str, Any]) -> Dict[str, Any]:
    # 단일 문제 처리를 위한 래퍼 함수 (병렬 실행용)
    fixed_data = fix_content_with_llm(problem)

    # 후처리 로직 적용
    fixed_data = restore_missing_images(problem, fixed_data)
    fixed_data = normalize_answer(fixed_data)
    fixed_data = unescape_html_tags(fixed_data)
    fixed_data = normalize_refer_view_header(fixed_data)
    fixed_data = remove_refer_markers(fixed_data)
    fixed_data = normalize_html_wrappers(fixed_data)
    fixed_data = wrap_latex_content(fixed_data)
    fixed_data = normalize_reference_text(fixed_data)

    return {
        "original_id": problem.get("id"),
        "original": json.loads(json.dumps(problem, default=str)),
        "fixed": fixed_data,
    }


def generate_html_report(results: List[Dict[str, Any]], output_path: Path):
    # 결과 데이터를 HTML 리포트로 저장합니다.
    try:
        with open(REPORT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
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

    output_path = Path(__file__).resolve().parents[2] / args.output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Done. JSON Results saved to {output_path}")

    # HTML 리포트 생성 (데이터 주입)
    html_path = output_path.with_suffix(".html")
    generate_html_report(results, html_path)


if __name__ == "__main__":
    main()
