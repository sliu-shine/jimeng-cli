"""Record generated scripts and manually entered post-publish feedback."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from .database import connect


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def record_generation(
    script: str,
    topic: str = "",
    niche: str = "",
    requirements: str = "",
    hook_type: str = "",
    structure: str = "",
    emotion_direction: str = "",
    reference_videos: list[str] | None = None,
    generation_params: dict | None = None,
    metadata: dict | None = None,
    source_record_id: str = "",
    generation_id: str | None = None,
) -> str:
    """Store one AI generation and return its generation_id."""
    generation_id = generation_id or f"gen_{uuid.uuid4().hex[:12]}"
    created_at = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO generated_content (
                id, source_record_id, topic, niche, requirements, script,
                hook_type, structure, emotion_direction, reference_videos,
                generation_params, metadata_json, generated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                source_record_id,
                topic,
                niche,
                requirements,
                script,
                hook_type,
                structure,
                emotion_direction,
                _json(reference_videos or []),
                _json(generation_params or {}),
                _json(metadata or {}),
                created_at,
                created_at,
            ),
        )
    return generation_id


def get_generation(generation_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM generated_content WHERE id = ?",
            (generation_id,),
        ).fetchone()
    item = _row_to_dict(row)
    for key in ("reference_videos", "generation_params", "metadata_json"):
        if item.get(key):
            try:
                item[key] = json.loads(item[key])
            except json.JSONDecodeError:
                pass
    return item


def list_generations(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, topic, niche, hook_type, structure, generated_at
            FROM generated_content
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def add_video_feedback(
    generation_id: str,
    video_id: str = "",
    platform: str = "douyin",
    title: str = "",
    published_at: str = "",
    duration_seconds: float | None = None,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    favorites: int = 0,
    shares: int = 0,
    completion_rate: float | None = None,
    bounce_2s_rate: float | None = None,
    completion_5s_rate: float | None = None,
    avg_watch_seconds: float | None = None,
    avg_watch_ratio: float | None = None,
    notes: str = "",
    raw: dict | None = None,
) -> int:
    """Store manually entered performance data and return feedback_id."""
    if not get_generation(generation_id):
        raise ValueError(f"找不到 generation_id：{generation_id}")
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO video_feedback (
                generation_id, video_id, platform, title, published_at,
                duration_seconds, views, likes, comments, favorites, shares,
                completion_rate, bounce_2s_rate, completion_5s_rate,
                avg_watch_seconds, avg_watch_ratio, notes, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                video_id,
                platform,
                title,
                published_at,
                duration_seconds,
                int(views or 0),
                int(likes or 0),
                int(comments or 0),
                int(favorites or 0),
                int(shares or 0),
                completion_rate,
                bounce_2s_rate,
                completion_5s_rate,
                avg_watch_seconds,
                avg_watch_ratio,
                notes,
                _json(raw or {}),
                _now(),
            ),
        )
        return int(cursor.lastrowid)


def get_feedback(feedback_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM video_feedback WHERE id = ?",
            (int(feedback_id),),
        ).fetchone()
    item = _row_to_dict(row)
    if item.get("raw_json"):
        try:
            item["raw_json"] = json.loads(item["raw_json"])
        except json.JSONDecodeError:
            pass
    return item


def get_latest_feedback(generation_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM video_feedback
            WHERE generation_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (generation_id,),
        ).fetchone()
    return _row_to_dict(row)


def save_review(generation_id: str, feedback_id: int, review: dict) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO feedback_reviews (
                generation_id, feedback_id, result_level, main_diagnosis,
                review_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                int(feedback_id),
                str(review.get("result_level") or ""),
                str(review.get("main_diagnosis") or ""),
                _json(review),
                _now(),
            ),
        )
        return int(cursor.lastrowid)


def get_recent_reviews(niche: str = "", limit: int = 10) -> list[dict]:
    params: list[Any] = []
    where = ""
    if niche:
        where = "WHERE g.niche = ?"
        params.append(niche)
    params.append(int(limit))
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, g.topic, g.niche
            FROM feedback_reviews r
            JOIN generated_content g ON g.id = r.generation_id
            {where}
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["review_json"] = json.loads(item.get("review_json") or "{}")
        except json.JSONDecodeError:
            pass
        items.append(item)
    return items
