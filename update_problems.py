#!/usr/bin/env python3
import os
import sys
import json
import argparse
import pymysql
from dotenv import load_dotenv
from pathlib import Path
from typing import List, Dict, Any

# Load environment variables (same as fix_problems.py)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PROD_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PROD_PASSWORD")
DB_NAME = os.getenv("DB_NAME")


def get_db_connection():
    """Creates a database connection."""
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


def update_problems(json_path: str, execute: bool = False):
    """
    Updates the problem table using the JSON data.
    Sets human_review = 'GOOD'.
    """
    if not os.path.exists(json_path):
        print(f"Error: File not found - {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("Error: JSON data must be a list of objects.", file=sys.stderr)
        sys.exit(1)

    conn = get_db_connection()
    cursor = conn.cursor()

    updated_count = 0
    skipped_count = 0

    print(f"Loaded {len(data)} items from {json_path}")
    if not execute:
        print(">>> DRY RUN MODE (No changes will be committed) <<<")

    try:
        for item in data:
            original_id = item.get("original_id")
            fixed = item.get("fixed")

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
