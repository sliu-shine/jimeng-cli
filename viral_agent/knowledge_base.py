"""
知识库：存储爆款文案 + 模式分析，支持语义检索
使用 ChromaDB（本地，无需服务器）
"""
import json
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions


DB_PATH = Path(__file__).parent.parent / ".viral_kb"

# 全局单例，避免重复初始化
_collection = None


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
        "niche": metadata.get("niche", ""),
        "hook_type": analysis.get("hook_type", ""),
        "hook": analysis.get("hook", ""),
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


def search_scripts(query: str, n: int = 5, niche: Optional[str] = None) -> list[dict]:
    """语义检索相似爆款文案"""
    collection = get_db()

    where = {"niche": niche} if niche else None
    results = collection.query(
        query_texts=[query],
        n_results=min(n, collection.count() or 1),
        where=where,
    )

    scripts = []
    if results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            scripts.append({
                "video_id": doc_id,
                "script": meta.get("script", ""),
                "hook": meta.get("hook", ""),
                "hook_type": meta.get("hook_type", ""),
                "structure": meta.get("structure", ""),
                "why_viral": meta.get("why_viral", ""),
                "likes": meta.get("likes", 0),
                "analysis": json.loads(meta.get("analysis_json", "{}")),
                "similarity": 1 - results["distances"][0][i],
            })
    return scripts


def get_all_patterns(niche: Optional[str] = None) -> dict:
    """获取知识库中所有爆款的模式统计"""
    collection = get_db()
    count = collection.count()
    if count == 0:
        return {"count": 0, "patterns": []}

    where = {"niche": niche} if niche else None
    results = collection.get(where=where, include=["metadatas"])

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
