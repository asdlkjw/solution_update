import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Tuple, cast

import pymysql
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

DB_PORT = os.getenv("DB_PROD_PORT")


def exit_with_error(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(1)


def get_db_connection():
    """Creates a database connection."""
    try:
        try:
            db_host = os.environ["DB_HOST"]
        except KeyError:
            exit_with_error("Error: DB_HOST is not set.")
        if db_host == "":
            exit_with_error("Error: DB_HOST is not set.")
        try:
            db_user = os.environ["DB_USER"]
        except KeyError:
            exit_with_error("Error: DB_USER is not set.")
        if db_user == "":
            exit_with_error("Error: DB_USER is not set.")
        try:
            db_password = os.environ["DB_PROD_PASSWORD"]
        except KeyError:
            exit_with_error("Error: DB_PROD_PASSWORD is not set.")
        if db_password == "":
            exit_with_error("Error: DB_PROD_PASSWORD is not set.")
        try:
            db_name = os.environ["DB_NAME"]
        except KeyError:
            exit_with_error("Error: DB_NAME is not set.")
        if db_name == "":
            exit_with_error("Error: DB_NAME is not set.")
        conn = pymysql.connect(
            host=db_host,
            port=int(DB_PORT) if DB_PORT else 3306,
            user=db_user,
            password=str(db_password),
            database=db_name,
            cursorclass=pymysql.cursors.DictCursor,
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        sys.exit(1)


def update_problems_from_data(
    data: List[Dict[str, Any]], execute: bool = False
) -> Tuple[int, int]:
    """
    Updates the problem table using the JSON data.
    Sets human_review = 'GOOD'.
    """
    if not isinstance(data, list):
        print("Error: JSON data must be a list of objects.", file=sys.stderr)
        sys.exit(1)

    conn = get_db_connection()
    cursor = conn.cursor()

    updated_count = 0
    skipped_count = 0

    print(f"Loaded {len(data)} items from provided data")
    if not execute:
        print(">>> DRY RUN MODE (No changes will be committed) <<<")

    try:
        for item in data:
            original_id = item["original_id"] if "original_id" in item else None
            fixed = item["fixed"] if "fixed" in item else None

            # Basic Validation
            if not original_id or not fixed:
                print(f"[SKIP] Invalid item structure: {item.keys()}")
                skipped_count += 1
                continue

            # Skip if error occurred during generation
            if "error" in fixed:
                print(
                    f"[SKIP] ID {original_id}: Generation error found ({fixed['error']})"
                )
                skipped_count += 1
                continue

            # Prepare Update Query
            fields_to_update = [
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

            update_clauses = []
            values = []

            for field in fields_to_update:
                if field in fixed:
                    val = fixed[field]
                    # Convert None to NULL (None in Python is handled by pymysql as NULL)
                    update_clauses.append(f"{field} = %s")
                    values.append(val)

            # FORCE UPDATE: human_review column
            update_clauses.append("human_review = 'GOOD'")

            if not update_clauses:
                print(f"[SKIP] ID {original_id}: No fields to update")
                skipped_count += 1
                continue

            sql = f"UPDATE problem SET {', '.join(update_clauses)} WHERE id = %s"
            values.append(original_id)

            if execute:
                cursor.execute(sql, tuple(values))
            else:
                # Dry run: just print the SQL (truncated)
                print(
                    f"[DRY RUN] ID {original_id}: Would update human_review='GOOD' and content fields."
                )

            updated_count += 1

        if execute:
            conn.commit()
            print(
                f"\nSUCCESS: Updated {updated_count} rows. (Skipped: {skipped_count})"
            )
        else:
            conn.rollback()
            print(
                f"\nDRY RUN COMPLETE: Would update {updated_count} rows. (Skipped: {skipped_count})"
            )
            print("To actually execute, run with --execute flag.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: Transaction failed. Rolled back. Reason: {e}", file=sys.stderr)
    finally:
        cursor.close()
        conn.close()

    return updated_count, skipped_count


def normalize_result_id(value: int | str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise exc


def normalize_update_fields_map(
    update_fields_map: Dict[int | str, List[str]],
) -> Dict[int, List[str]]:
    normalized: Dict[int, List[str]] = {}
    for result_id, fields in update_fields_map.items():
        normalized_key = normalize_result_id(result_id)
        normalized[normalized_key] = fields
    return normalized


def update_problems_from_results(
    results: List[Any],
    update_fields: List[str] | None = None,
    update_fields_map: Dict[int | str, List[str]] | None = None,
) -> Tuple[int, int]:
    conn = get_db_connection()
    cursor = conn.cursor()

    normalized_update_fields_map: Dict[int, List[str]] | None = None
    if update_fields_map is not None:
        normalized_update_fields_map = normalize_update_fields_map(update_fields_map)

    updated_count = 0
    skipped_count = 0

    try:
        for row in results:
            original_id = row["original_id"]
            fixed_json = (
                json.loads(row["fixed_json"])
                if isinstance(row["fixed_json"], str)
                else row["fixed_json"]
            )
            human_review = row["human_review"]
            result_id: int = normalize_result_id(row["id"])

            if human_review == "BAD":
                sql = "UPDATE problem SET human_review = %s WHERE id = %s"
                cursor.execute(sql, (human_review, original_id))
                updated_count += 1
                continue

            if "error" in fixed_json:
                skipped_count += 1
                continue

            default_fields = [
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

            map_fields = None
            if normalized_update_fields_map is not None:
                normalized_result_id = cast(int, result_id)
                if normalized_result_id in normalized_update_fields_map:
                    map_fields = normalized_update_fields_map[normalized_result_id]

            if map_fields is not None:
                candidate_fields = map_fields
            elif update_fields is not None:
                candidate_fields = update_fields
            else:
                candidate_fields = default_fields

            update_field_set = {
                field for field in candidate_fields if field in default_fields
            }
            fields_to_update = [
                field for field in default_fields if field in update_field_set
            ]

            update_clauses = []
            values = []

            for field in fields_to_update:
                if field in fixed_json:
                    val = fixed_json[field]
                    update_clauses.append(f"{field} = %s")
                    values.append(val)

            update_clauses.append("human_review = %s")
            values.append(human_review)

            if not update_clauses:
                skipped_count += 1
                continue

            sql = f"UPDATE problem SET {', '.join(update_clauses)} WHERE id = %s"
            values.append(original_id)

            cursor.execute(sql, tuple(values))
            updated_count += 1

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

    return updated_count, skipped_count


def update_problems(json_path: str, execute: bool = False) -> Tuple[int, int]:
    if not os.path.exists(json_path):
        print(f"Error: File not found - {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return update_problems_from_data(data, execute)


def main():
    parser = argparse.ArgumentParser(
        description="Update problem table with fixed data from JSON"
    )
    parser.add_argument("input_file", help="Path to the fixed results JSON file")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the update queries (Commit changes)",
    )

    args = parser.parse_args()

    update_problems(args.input_file, args.execute)


if __name__ == "__main__":
    main()
