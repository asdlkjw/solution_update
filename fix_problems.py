#!/usr/bin/env python3
import os
import sys
import json
import argparse
import csv
import pymysql
import pymysql.cursors
import requests
from dotenv import load_dotenv
from pathlib import Path
from typing import List, Dict, Any, Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PROD_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PROD_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

MODEL_NAME = "google/gemini-3-flash-preview"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


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

    payload = {
        "model": MODEL_NAME,
        "temperature": 0.7,
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

    try:
        response = requests.post(
            OPENROUTER_URL, headers=headers, json=payload, timeout=60
        )
        response.raise_for_status()
        result = response.json()

        content = result["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(
            f"Error calling LLM for ID {problem_data.get('id')}: {e}", file=sys.stderr
        )
        return {"error": str(e), "original_id": problem_data.get("id")}


def normalize_answer(fixed_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    후처리 로직:
    - type이 multiple_choice인 경우 answer의 원문자(①~⑤)를 숫자로 변환
    """
    if fixed_data.get("type") == "multiple_choice":
        ans = str(fixed_data.get("answer", ""))
        replacements = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5"}
        for circle, num in replacements.items():
            ans = ans.replace(circle, num)
        fixed_data["answer"] = ans.strip()
    return fixed_data


def process_single_problem(problem: Dict[str, Any]) -> Dict[str, Any]:
    # 단일 문제 처리를 위한 래퍼 함수 (병렬 실행용)
    fixed_data = fix_content_with_llm(problem)

    # 후처리 로직 적용
    fixed_data = normalize_answer(fixed_data)

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
