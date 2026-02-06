import os
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "app.db"


def get_db_path() -> Path:
    return Path(os.getenv("SQLITE_DB_PATH", str(DEFAULT_DB_PATH)))


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as schema_file:
        schema_sql = schema_file.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        cursor = conn.execute("PRAGMA table_info(jobs)")
        columns = {row["name"] for row in cursor.fetchall()}
        columns_to_add = [
            "judge_processed_count",
            "judge_retry_count",
            "judge_fail_count",
        ]
        for column_name in columns_to_add:
            if column_name not in columns:
                conn.execute(
                    f"ALTER TABLE jobs ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT 0"
                )
        conn.commit()
        # pipeline_version 마이그레이션
        if "pipeline_version" not in columns:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN pipeline_version TEXT NOT NULL DEFAULT 'v1'"
            )
            conn.commit()

        # human_review UNVERIFIED 마이그레이션
        # SQLite cannot ALTER CHECK constraints, so recreate the table
        try:
            conn.execute(
                "INSERT INTO results (job_id, original_id, original_json, fixed_json, human_review) "
                "VALUES (-1, -1, '{}', '{}', 'UNVERIFIED')"
            )
            conn.rollback()
        except sqlite3.IntegrityError:
            # UNVERIFIED not yet allowed — migrate
            conn.executescript("""
                CREATE TABLE results_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    original_id INTEGER NOT NULL,
                    group_id INTEGER,
                    original_json TEXT NOT NULL,
                    fixed_json TEXT NOT NULL,
                    human_review TEXT NOT NULL DEFAULT 'GOOD' CHECK (human_review IN ('GOOD', 'BAD', 'UNVERIFIED')),
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                INSERT INTO results_new SELECT * FROM results;
                DROP TABLE results;
                ALTER TABLE results_new RENAME TO results;
                CREATE INDEX IF NOT EXISTS idx_results_job_id ON results(job_id);
                CREATE INDEX IF NOT EXISTS idx_results_original_id ON results(original_id);
            """)
            conn.commit()
    finally:
        conn.close()
