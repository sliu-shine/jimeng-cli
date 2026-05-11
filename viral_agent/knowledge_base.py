"""
知识库：存储爆款文案 + 模式分析，支持语义检索
使用 ChromaDB（本地，无需服务器）
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions


DB_PATH = Path(__file__).parent.parent / ".viral_kb"

# 全局单例，避免重复初始化
_collection = None


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_log(value, cap: float) -> float:
    value = max(0.0, _as_float(value))
    if cap <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(cap))


def _norm_score(value, scale: float = 10.0) -> float:
    value = max(0.0, _as_float(value))
    if value > scale and value <= 100:
        value = value / 10
    return min(1.0, value / scale) if scale else 0.0


def _parse_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10000000000 else value
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        timestamp = int(text)
        timestamp = timestamp / 1000 if timestamp > 10000000000 else timestamp
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_score(meta: dict) -> float:
    published = (
        meta.get("publish_time")
        or meta.get("published_at")
        or meta.get("create_time")
        or meta.get("created_at")
        or meta.get("download_time")
    )
    dt = _parse_datetime(published)
    if not dt:
        return 0.5
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0, (datetime.now(timezone.utc) - dt).days)
    if days <= 30:
        return 1.0
    if days <= 180:
        return 0.8
    if days <= 365:
        return 0.65
    if days <= 730:
        return 0.45
    return 0.3


def _rate(numerator, denominator) -> float:
    denominator = _as_float(denominator)
    if denominator <= 0:
        return 0.0
    return max(0.0, _as_float(numerator) / denominator)


def _performance_score(meta: dict) -> float:
    likes = _as_float(meta.get("likes"))
    views = _as_float(meta.get("views") or meta.get("play_count") or meta.get("plays"))
    comments = _as_float(meta.get("comments") or meta.get("comment_count"))
    shares = _as_float(meta.get("shares") or meta.get("share_count"))
    favorites = _as_float(meta.get("favorites") or meta.get("collects") or meta.get("collect_count"))
    completion_rate = _as_float(meta.get("completion_rate") or meta.get("finish_rate"))

    raw_engagement = (
        0.46 * _norm_log(likes, 100000)
        + 0.18 * _norm_log(comments, 20000)
        + 0.18 * _norm_log(shares, 20000)
        + 0.10 * _norm_log(favorites, 30000)
        + 0.08 * _norm_log(views, 3000000)
    )
    if views > 0:
        rate_score = (
            0.45 * min(1.0, _rate(likes, views) / 0.08)
            + 0.20 * min(1.0, _rate(comments, views) / 0.012)
            + 0.20 * min(1.0, _rate(shares, views) / 0.012)
            + 0.15 * min(1.0, _rate(favorites, views) / 0.02)
        )
        raw_engagement = 0.72 * raw_engagement + 0.28 * rate_score
    if completion_rate:
        raw_engagement = 0.85 * raw_engagement + 0.15 * min(1.0, completion_rate / 100 if completion_rate > 1 else completion_rate)
    return min(1.0, raw_engagement)


def _quality_signal(meta: dict) -> float:
    transcript_quality = _as_float(meta.get("transcript_quality"))
    if transcript_quality > 10:
        transcript_quality = transcript_quality / 10
    quality = _norm_score(meta.get("quality_score"), 10)
    replication = _norm_score(meta.get("replication_score"), 10)
    if transcript_quality:
        return min(1.0, 0.40 * quality + 0.40 * replication + 0.20 * min(1.0, transcript_quality / 10))
    return min(1.0, 0.50 * quality + 0.50 * replication)


def _hybrid_rank_score(meta: dict, similarity: float, niche: Optional[str] = None) -> tuple[float, dict]:
    similarity_score = max(0.0, min(1.0, _as_float(similarity)))
    performance = _performance_score(meta)
    quality = _quality_signal(meta)
    recency = _recency_score(meta)
    niche_match = 1.0 if niche and str(meta.get("niche") or meta.get("channel") or "").strip() == str(niche).strip() else 0.0
    transcript_penalty = 0.0
    transcript_quality = _as_float(meta.get("transcript_quality"))
    if transcript_quality and transcript_quality < 60:
        transcript_penalty = 0.08

    score = (
        0.46 * similarity_score
        + 0.24 * performance
        + 0.18 * quality
        + 0.07 * recency
        + 0.05 * niche_match
        - transcript_penalty
    )
    breakdown = {
        "similarity": round(similarity_score, 4),
        "performance": round(performance, 4),
        "quality": round(quality, 4),
        "recency": round(recency, 4),
        "niche_match": round(niche_match, 4),
        "transcript_penalty": round(transcript_penalty, 4),
    }
    return round(max(0.0, min(1.0, score)), 4), breakdown


def get_db():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(DB_PATH))
        # 使用默认的轻量级嵌入函数（基于 onnx，更快更省内存）
        ef = embedding_functions.DefaultEmbeddingFunction()
        _collection = client.get_or_create_collection(
            name="viral_scripts",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def add_script(
    video_id: str,
    script: str,
    analysis: dict,
    metadata: dict,
):
    """
    存入一条爆款文案及其分析结果
    analysis: {hook, structure, emotion_triggers, viral_elements, why_viral}
    metadata: {likes, niche, platform, duration, url}
    """
    collection = get_db()

    # 用于检索的文本 = 原始文案 + 关键模式标签
    search_text = f"{script}\n标签: {analysis.get('viral_elements', '')}"

    doc_metadata = {
        "video_id": video_id,
        "likes": metadata.get("likes", 0),
        "engagement_level": metadata.get("engagement_level", analysis.get("engagement_level", "")),
        "niche": metadata.get("niche", ""),
        "channel": metadata.get("channel", ""),
        "source_account": metadata.get("source_account", metadata.get("author", "")),
        "account_type": metadata.get("account_type") or "",
        "content_type": metadata.get("content_type") or analysis.get("topic_type", ""),
        "hook_type": analysis.get("hook_type", ""),
        "hook": analysis.get("hook", ""),
        "topic_type": analysis.get("topic_type", ""),
        "topic_formula": analysis.get("topic_formula", ""),
        "style_tags": ",".join(analysis.get("style_tags", [])) if isinstance(analysis.get("style_tags"), list) else str(analysis.get("style_tags", "")),
        "quality_score": int(analysis.get("quality_score", 0) or 0),
        "replication_score": int(analysis.get("replication_score", 0) or 0),
        "structure": analysis.get("structure", ""),
        "why_viral": analysis.get("why_viral", ""),
        "analysis_json": json.dumps(analysis, ensure_ascii=False),
        "script": script,
        **{k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool))},
    }

    collection.upsert(
        ids=[video_id],
        documents=[search_text],
        metadatas=[doc_metadata],
    )
    print(f"✅ 已存入知识库: {video_id} (点赞: {metadata.get('likes', 0):,})")


def has_script(video_id: str) -> bool:
    """检查指定 video_id 是否已在知识库中。"""
    if not video_id:
        return False
    collection = get_db()
    result = collection.get(ids=[video_id], include=[])
    return bool(result.get("ids"))


def delete_script(video_id: str) -> bool:
    """从知识库删除指定 video_id。返回删除前是否存在。"""
    if not video_id:
        return False
    collection = get_db()
    existed = has_script(video_id)
    if existed:
        collection.delete(ids=[video_id])
        print(f"🗑️ 已从知识库删除: {video_id}")
    return existed


def search_scripts(query: str, n: int = 5, niche: Optional[str] = None, candidate_multiplier: int = 6) -> list[dict]:
    """语义召回后用互动、质量、复刻、时效等信号混合排序。"""
    collection = get_db()
    total = collection.count()
    if total == 0:
        return []

    where = {"niche": niche} if niche else None
    candidate_count = min(total, max(int(n), int(n) * max(1, int(candidate_multiplier)), 30))
    results = collection.query(
        query_texts=[query],
        n_results=candidate_count,
        where=where,
    )

    scripts = []
    if results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            similarity = 1 - results["distances"][0][i]
            rank_score, score_breakdown = _hybrid_rank_score(meta, similarity, niche=niche)
            scripts.append({
                "video_id": doc_id,
                "script": meta.get("script", ""),
                "hook": meta.get("hook", ""),
                "hook_type": meta.get("hook_type", ""),
                "topic_type": meta.get("topic_type", ""),
                "topic_formula": meta.get("topic_formula", ""),
                "source_account": meta.get("source_account", ""),
                "account_type": meta.get("account_type", ""),
                "content_type": meta.get("content_type", meta.get("topic_type", "")),
                "channel": meta.get("channel", ""),
                "structure": meta.get("structure", ""),
                "why_viral": meta.get("why_viral", ""),
                "likes": meta.get("likes", 0),
                "engagement_level": meta.get("engagement_level", ""),
                "quality_score": meta.get("quality_score", 0),
                "replication_score": meta.get("replication_score", 0),
                "analysis": json.loads(meta.get("analysis_json", "{}")),
                "metadata": meta,
                "similarity": similarity,
                "rank_score": rank_score,
                "score_breakdown": score_breakdown,
            })
    return sorted(scripts, key=lambda item: item.get("rank_score", 0), reverse=True)[:int(n)]


def get_all_patterns(niche: Optional[str] = None) -> dict:
    """获取知识库中所有爆款的模式统计"""
    collection = get_db()
    total = collection.count()
    if total == 0:
        return {"count": 0, "patterns": []}

    where = {"niche": niche} if niche else None
    results = collection.get(where=where, include=["metadatas"])
    count = len(results.get("metadatas") or [])
    if count == 0:
        return {"count": 0, "patterns": []}

    hook_types = {}
    viral_elements = []
    structures = []

    for meta in results["metadatas"]:
        ht = meta.get("hook_type", "")
        if ht:
            hook_types[ht] = hook_types.get(ht, 0) + 1
        analysis = json.loads(meta.get("analysis_json", "{}"))
        viral_elements.extend(analysis.get("viral_elements", []) if isinstance(analysis.get("viral_elements"), list) else [])
        structures.append(meta.get("structure", ""))

    return {
        "count": count,
        "hook_types": hook_types,
        "top_viral_elements": list(set(viral_elements))[:20],
        "sample_structures": structures[:5],
    }


def get_stats() -> str:
    collection = get_db()
    count = collection.count()
    return f"知识库共 {count} 条爆款文案"
