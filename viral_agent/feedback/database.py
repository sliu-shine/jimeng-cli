"""SQLite storage for the feedback learning MVP."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / ".viral_feedback" / "feedback.sqlite3"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS generated_content (
            id TEXT PRIMARY KEY,
            source_record_id TEXT,
            topic TEXT,
            niche TEXT,
            requirements TEXT,
            script TEXT NOT NULL,
            hook_type TEXT,
            structure TEXT,
            emotion_direction TEXT,
            reference_videos TEXT,
            generation_params TEXT,
            metadata_json TEXT,
            generated_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS video_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id TEXT NOT NULL,
            video_id TEXT,
            platform TEXT,
            title TEXT,
            published_at TEXT,
            duration_seconds REAL,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            favorites INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            completion_rate REAL,
            bounce_2s_rate REAL,
            completion_5s_rate REAL,
            avg_watch_seconds REAL,
            avg_watch_ratio REAL,
            notes TEXT,
            raw_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(generation_id) REFERENCES generated_content(id)
        );

        CREATE TABLE IF NOT EXISTS feedback_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id TEXT NOT NULL,
            feedback_id INTEGER NOT NULL,
            result_level TEXT,
            main_diagnosis TEXT,
            review_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(generation_id) REFERENCES generated_content(id),
            FOREIGN KEY(feedback_id) REFERENCES video_feedback(id)
        );

        CREATE INDEX IF NOT EXISTS idx_feedback_generation_id
            ON video_feedback(generation_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_generation_id
            ON feedback_reviews(generation_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_created_at
            ON feedback_reviews(created_at);
        """
    )
    conn.commit()
