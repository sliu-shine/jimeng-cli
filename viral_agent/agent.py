"""
爆款文案智能体
用 Claude API 做推理，手动管理检索→生成流程
"""
import os
import json
import re
from pathlib import Path
from . import knowledge_base as kb
from .ai_providers import apply_provider, list_providers
from scripts.claude_client import ClaudeClient

PROMPTS_DIR = Path(__file__).parent / "prompts"

# niche 关键词 → prompt 文件名映射
_NICHE_PROMPT_MAP = {
    "宠物": "pet",
    "pet": "pet",
    "猫": "pet",
    "狗": "pet",
    "萌宠": "pet",
}


def _load_niche_rules(niche: str) -> str:
    """按 niche 加载对应的运营规则 prompt 文件，找不到返回空字符串。"""
    if not niche:
        return ""
    key = str(niche).strip().lower()
    filename = _NICHE_PROMPT_MAP.get(key) or _NICHE_PROMPT_MAP.get(niche.strip())
    if not filename:
        # 模糊匹配：niche 包含关键词
        for keyword, fname in _NICHE_PROMPT_MAP.items():
            if keyword in niche:
                filename = fname
                break
    if not filename:
        return ""
    path = PROMPTS_DIR / f"{filename}.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _call_provider(prompt: str, provider_id: str | None = None) -> str:
    provider = apply_provider(provider_id or os.environ.get("AI_PROVIDER_SELECTED"))
    client = ClaudeClient(provider_id=provider.id)
    result = client.create_message(
        model=provider.model or os.getenv("ANTHROPIC_MODEL", client.model),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=int(os.getenv("VIRAL_AGENT_MAX_TOKENS", "8000")),
        temperature=float(os.getenv("VIRAL_AGENT_TEMPERATURE", "0.7")),
    )
    content = result.get("content") or []
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type", "text") == "text":
            parts.append(str(item.get("text") or ""))
    text = "\n".join(part for part in parts if part.strip()).strip()
    if not text:
        raise RuntimeError(f"AI Provider 返回空内容：{provider.name} · {provider.model}")
    return text


def _call_claude(prompt: str) -> str:
    selected_id = (os.environ.get("AI_PROVIDER_SELECTED") or os.environ.get("AI_PROVIDER_DEFAULT") or "").strip().lower()
    providers = list_providers()
    ordered_ids: list[str] = []
    if selected_id:
        ordered_ids.append(selected_id)
    ordered_ids.extend(provider.id for provider in providers if provider.id not in ordered_ids)

    errors: list[str] = []
    for provider_id in ordered_ids:
        try:
            return _call_provider(prompt, provider_id)
        except Exception as exc:
            provider = next((item for item in providers if item.id == provider_id), None)
            name = provider.name if provider else provider_id
            errors.append(f"{name}: {str(exc)[:300]}")
            if os.getenv("AI_PROVIDER_AUTO_FALLBACK", "1").strip().lower() in {"0", "false", "no"}:
                break
    raise RuntimeError("所有 AI Provider 均调用失败：\n" + "\n".join(errors))


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _shingle_similarity(source: str, candidate: str, size: int = 12) -> float:
    source_text = _compact_text(source)
    candidate_text = _compact_text(candidate)
    if len(source_text) < size or len(candidate_text) < size:
        return 0.0
    source_shingles = {source_text[i:i + size] for i in range(0, len(source_text) - size + 1)}
    candidate_shingles = {candidate_text[i:i + size] for i in range(0, len(candidate_text) - size + 1)}
    if not source_shingles or not candidate_shingles:
        return 0.0
    return len(source_shingles & candidate_shingles) / len(candidate_shingles)


def _topic_input_context(topic: str) -> tuple[str, str]:
    clean_topic = str(topic or "").strip()
    if len(_compact_text(clean_topic)) < 120:
        return clean_topic, f"主题：{clean_topic}"

    source_preview = clean_topic[:1800]
    search_query = clean_topic[:160]
    context = f"""用户输入的是一段参考原文/视频转录稿，不是要你照抄的主题。

【参考原文】
{source_preview}

处理方式：
1. 只提炼它的核心选题、信息点和受众需求
2. 必须重新创作，不要复述原文
3. 换一个开头钩子，换叙事顺序，换句式表达
4. 不得连续复用参考原文中超过12个字的原句
5. 可以保留事实信息，但要用新的表达和新的节奏讲出来"""
    return search_query, context


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _has_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def _score_generated_script(content: str, references: list[dict], source_similarity: float) -> dict:
    body = re.sub(r"【版本\d+[^】]*】|（参考：[^）]*）", "", str(content or "")).strip()
    compact = _compact_text(body)
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), body[:80])
    score = 45.0
    details: list[str] = []

    if 260 <= len(compact) <= 900:
        score += 12
        details.append("篇幅适合口播")
    elif len(compact) >= 180:
        score += 7
        details.append("篇幅基本可用")
    else:
        score -= 10
        details.append("篇幅偏短")

    if _has_any(first_line[:80], ["你知道吗", "为什么", "别不信", "千万", "如果", "其实", "很多人", "原来"]):
        score += 12
        details.append("开头有钩子")

    if _has_any(body, ["第一", "第二", "第三", "首先", "然后", "最后", "记住", "所以"]):
        score += 10
        details.append("结构清晰")

    if _has_any(body, ["你家", "你以为", "你可以", "下次", "试试", "评论", "记住"]):
        score += 8
        details.append("互动/行动感强")

    if _has_any(body, ["因为", "其实", "本质", "原因", "答案"]):
        score += 7
        details.append("有解释价值")

    if references:
        top_ref = max(float(item.get("similarity") or 0) for item in references)
        top_likes = max(int(float(item.get("likes") or 0)) for item in references)
        score += min(10, top_ref * 10)
        if top_likes >= 100000:
            score += 6
            details.append("参考过高赞样本")
        elif top_likes >= 10000:
            score += 4
            details.append("参考过万赞样本")

    if source_similarity > 0.22:
        score -= 18
        details.append("原文相似度偏高")
    elif source_similarity > 0 and source_similarity <= 0.12:
        score += 5
        details.append("改写差异度较好")

    return {"score": _clamp_score(score), "details": details[:5]}


def _plain_script_body(content: str) -> str:
    return re.sub(r"【版本\d+[^】]*】|（参考：[^）]*）", "", str(content or "")).strip()


def _split_generated_versions(content: str) -> list[dict]:
    text = str(content or "").strip()
    if not text:
        return []
    pattern = re.compile(r"^【版本\s*(\d+)[^】]*】", flags=re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        return [{"index": 1, "content": text}]

    versions = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        versions.append({
            "index": int(match.group(1)),
            "content": text[start:end].strip(),
        })
    return versions


def _parse_version_fields(content: str) -> dict:
    """从版本内容中提取结构化字段：标题、描述、标签、封面图建议、封面文字建议"""
    text = str(content or "").strip()

    # 提取标题（在"标题："和下一个双换行或下一个字段标记之间）
    title_match = re.search(r"标题[：:]\s*\n(.+?)(?=\n\n描述[：:]|\n\n标签推荐|\n描述[：:]|$)", text, re.S)
    title = title_match.group(1).strip() if title_match else ""

    # 提取描述（在"描述："和"标签推荐："之间）
    desc_match = re.search(r"描述[：:]\s*\n(.+?)(?=\n\n标签推荐[：:]|\n标签推荐[：:]|$)", text, re.S)
    description = desc_match.group(1).strip() if desc_match else ""

    # 提取标签（在"标签推荐："和"封面图建议："之间）
    tags_match = re.search(r"标签推荐[：:]\s*\n(.+?)(?=\n\n封面图建议|\n封面图建议|$)", text, re.S)
    tags_text = tags_match.group(1).strip() if tags_match else ""
    tags = [tag.strip().lstrip("#") for tag in re.split(r"[#\s]+", tags_text) if tag.strip()]

    # 提取封面图建议（在"封面图建议："和"封面文字建议："之间）
    cover_img_match = re.search(r"封面图建议[：:]\s*\n(.+?)(?=\n\n封面文字建议|\n封面文字建议|$)", text, re.S)
    cover_image = cover_img_match.group(1).strip() if cover_img_match else ""

    # 提取封面文字建议（在"封面文字建议："和"AI质检："之间，或到结尾）
    cover_text_match = re.search(r"封面文字建议[：:]\s*\n(.+?)(?=\n\nAI质检[：:]|\nAI质检[：:]|$)", text, re.S)
    cover_text = cover_text_match.group(1).strip() if cover_text_match else ""

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "cover_image": cover_image,
        "cover_text": cover_text,
    }


def _extract_json_object(text: str):
    clean = str(text or "").strip()
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I | re.S).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    starts = [i for i, char in enumerate(clean) if char in "[{"]
    for start in starts:
        expected_end = "]" if clean[start] == "[" else "}"
        end = clean.rfind(expected_end)
        while end > start:
            try:
                return json.loads(clean[start:end + 1])
            except json.JSONDecodeError:
                end = clean.rfind(expected_end, start, end)
    raise ValueError("AI 质检返回不是有效 JSON")


def _normalize_review_item(item: dict, index: int) -> dict:
    def string_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()][:5]
        if value:
            return [str(value).strip()]
        return []

    raw_score = item.get("score") or item.get("评分") or 0
    if isinstance(raw_score, str):
        match = re.search(r"\d+(?:\.\d+)?", raw_score)
        raw_score = match.group(0) if match else 0
    score = int(float(raw_score))
    score = max(0, min(100, score))
    passed_value = item.get("passed", item.get("通过", score >= 75))
    if isinstance(passed_value, str):
        passed = passed_value.strip().lower() in {"true", "1", "yes", "y", "pass", "passed", "通过", "合格"}
    else:
        passed = bool(passed_value)

    return {
        "version": int(item.get("version") or item.get("版本") or index),
        "score": score,
        "passed": passed,
        "strengths": string_list(item.get("strengths") or item.get("亮点")),
        "problems": string_list(item.get("problems") or item.get("issues") or item.get("问题")),
        "suggestion": str(item.get("suggestion") or item.get("optimization") or item.get("优化建议") or "").strip(),
    }


def _fallback_quality_reviews(versions: list[dict], references: list[dict], source_text: str) -> list[dict]:
    reviews = []
    for item in versions:
        version_text = item["content"]
        score = _score_generated_script(version_text, references, _shingle_similarity(source_text, version_text))
        details = score.get("details") or []
        reviews.append({
            "version": item["index"],
            "score": score["score"],
            "passed": score["score"] >= 75,
            "strengths": details[:3] or ["结构基本完整"],
            "problems": [] if score["score"] >= 75 else ["需要人工复核标题、正文节奏和封面表达是否足够具体"],
            "suggestion": "优先压缩重复表达，强化前3秒钩子、具体画面和评论引导。",
            "fallback": True,
        })
    return reviews


def _review_generated_versions(content: str, topic_context: str, niche: str, requirements: str, references: list[dict]) -> list[dict]:
    versions = _split_generated_versions(content)
    if not versions:
        return []

    review_input = "\n\n".join(
        f"版本{item['index']}：\n{item['content'][:2200]}"
        for item in versions
    )
    prompt = f"""你是短视频爆款文案的 AI 质检官。请对下面每一个版本独立质检，不能只给总体评价。

用户输入与要求：
{topic_context}
{f'赛道：{niche}' if niche else ''}
{f'额外要求：{requirements}' if requirements else ''}

质检维度：
1. 是否贴合原始主题/参考原文，是否跑题或照抄
2. 每版是否具备完整发布成品包：标题、描述/正文、标签推荐、封面图建议、封面文字建议
3. 爆款结构是否成立：前3秒钩子、冲突/痛点、信息增量、行动/评论引导
4. 是否有 AI 腔、空泛、重复、模板化表达
5. 是否存在夸大、绝对化、低俗、引战或平台风险
6. 封面建议是否能形成点击理由，封面文字是否短、狠、清楚

请只输出 JSON 数组，不要 Markdown，不要解释。数组长度必须等于版本数，每项格式：
[
  {{
    "version": 1,
    "score": 0-100,
    "passed": true,
    "strengths": ["最多3条亮点"],
    "problems": ["最多3条问题，没有则为空数组"],
    "suggestion": "一句具体优化建议"
  }}
]

待质检内容：
{review_input}
"""
    try:
        data = _extract_json_object(_call_claude(prompt))
        if isinstance(data, dict):
            data = data.get("reviews") or data.get("versions") or []
        reviews = [_normalize_review_item(item, index + 1) for index, item in enumerate(data) if isinstance(item, dict)]
        by_version = {int(item["version"]): item for item in reviews}
        ordered = [by_version.get(item["index"]) for item in versions]
        if all(ordered):
            return ordered
    except Exception as exc:
        print(f"⚠️ AI 质检失败，使用本地规则兜底：{exc}")
    return _fallback_quality_reviews(versions, references, topic_context)


def _append_quality_reviews(content: str, reviews: list[dict]) -> str:
    versions = _split_generated_versions(content)
    if not versions or not reviews:
        return content

    by_version = {int(item.get("version") or 0): item for item in reviews}
    blocks = []
    for item in versions:
        review = by_version.get(item["index"])
        block = item["content"].strip()
        if review:
            strengths = "；".join(review.get("strengths") or []) or "暂无明显亮点"
            problems = "；".join(review.get("problems") or []) or "未发现明显问题"
            status = "通过" if review.get("passed") else "需优化"
            block += (
                "\n\nAI质检：\n"
                f"评分：{int(review.get('score') or 0)}/100（{status}）\n"
                f"亮点：{strengths}\n"
                f"问题：{problems}\n"
                f"优化建议：{review.get('suggestion') or '可直接进入人工终审。'}"
            )
        blocks.append(block)
    return "\n\n".join(blocks)


def _suggest_publish_metadata(content: str, niche: str = "") -> dict:
    body = _plain_script_body(content)
    compact = _compact_text(body)
    first_sentence = re.split(r"[。！？!?]", body, maxsplit=1)[0].strip()
    title = first_sentence or compact[:42]
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > 42:
        title = title[:39] + "..."

    seed_tags = [
        str(niche or "").strip(),
        "宠物",
        "狗狗",
        "养狗经验",
        "宠物科普",
    ]
    keyword_tags = []
    keyword_map = {
        "选狗": ["选狗", "幼犬挑选"],
        "性格": ["狗狗性格"],
        "家庭": ["养宠家庭"],
        "地位": ["狗狗行为"],
        "训练": ["宠物训练"],
        "护卫": ["护卫犬"],
        "陪伴": ["陪伴犬"],
        "食物": ["狗狗喂养"],
    }
    for keyword, tags in keyword_map.items():
        if keyword in body:
            keyword_tags.extend(tags)

    tags = []
    for tag in seed_tags + keyword_tags:
        tag = tag.strip().lstrip("#")
        if tag and tag not in tags:
            tags.append(tag)

    return {
        "title": title,
        "tags": tags[:8],
        "niche": str(niche or "").strip(),
    }


def _reference_report_items(similar: list[dict]) -> list[dict]:
    items = []
    for index, item in enumerate(similar[:3], 1):
        metadata = item.get("metadata") or {}
        title = metadata.get("title") or metadata.get("description") or metadata.get("desc") or ""
        tags_value = metadata.get("tags") or metadata.get("hashtags") or ""
        if isinstance(tags_value, str):
            tags = [tag.strip().lstrip("#") for tag in re.split(r"[,，#\s]+", tags_value) if tag.strip()]
        elif isinstance(tags_value, list):
            tags = [str(tag).strip().lstrip("#") for tag in tags_value if str(tag).strip()]
        else:
            tags = []
        source = (
            title
            or metadata.get("filename")
            or metadata.get("source")
            or metadata.get("transcript_path")
            or item.get("video_id")
            or f"爆款{index}"
        )
        items.append({
            "rank": index,
            "video_id": item.get("video_id", ""),
            "source": str(source),
            "title": str(title),
            "tags": tags[:8],
            "author": str(metadata.get("author") or ""),
            "video_url": str(metadata.get("video_url") or metadata.get("url") or ""),
            "niche": str(metadata.get("niche") or ""),
            "likes": int(float(item.get("likes") or 0)),
            "similarity": float(item.get("similarity") or 0),
            "rank_score": float(item.get("rank_score") or 0),
            "score_breakdown": item.get("score_breakdown") or {},
            "hook_type": item.get("hook_type", ""),
            "hook": item.get("hook", ""),
            "topic_type": item.get("topic_type", ""),
            "topic_formula": item.get("topic_formula", ""),
            "account_type": item.get("account_type", ""),
            "content_type": item.get("content_type", ""),
            "structure": item.get("structure", ""),
            "quality_score": int(float(item.get("quality_score") or 0)),
            "replication_score": int(float(item.get("replication_score") or 0)),
            "why_viral": item.get("why_viral", ""),
        })
    return items


def _generation_strategy(similar: list[dict], stats: dict, search_query: str, niche: str, versions: int) -> dict:
    hook_types = []
    structures = []
    content_types = []
    for item in similar:
        for key, bucket in [
            ("hook_type", hook_types),
            ("structure", structures),
            ("content_type", content_types),
        ]:
            value = str(item.get(key) or "").strip()
            if value and value not in bucket:
                bucket.append(value)
    return {
        "retrieval": {
            "query": search_query,
            "requested_top_n": 5,
            "ranking": "hybrid_similarity_performance_quality_recency",
            "niche_filter": str(niche or "").strip(),
        },
        "selected_patterns": {
            "hook_types": hook_types[:5],
            "structures": structures[:5],
            "content_types": content_types[:5],
            "global_hook_distribution": stats.get("hook_types", {}),
            "global_viral_elements": (stats.get("top_viral_elements") or [])[:10],
        },
        "generation": {
            "versions": int(versions),
            "format": "direct_publishable_oral_script",
        },
    }


def format_generation_report(metadata: dict | None) -> str:
    metadata = metadata or {}
    if not metadata:
        return ""
    references = metadata.get("references") or []
    publish = metadata.get("publish") or {}
    viral_score = metadata.get("viral_score") or {}
    source_similarity = float(metadata.get("source_similarity") or 0)
    reference_similarity = float(metadata.get("top_reference_similarity") or 0)
    lines = ["\n\n---", "### 生成评估"]
    if metadata.get("generation_id"):
        lines.append(f"- **反馈追踪ID：** `{metadata['generation_id']}`")
    lines.append(f"- **爆款评分：** {int(viral_score.get('score') or 0)}/100")
    if viral_score.get("details"):
        lines.append(f"- **评分依据：** {'、'.join(viral_score['details'])}")
    lines.append(f"- **原文相似度：** {source_similarity:.0%}（越低越不像照抄；超过 22% 会自动重写一次）")
    lines.append(f"- **参考匹配相似度：** {reference_similarity:.0%}（知识库里最接近的爆款样本）")
    if publish:
        tags = " ".join([f"#{tag}" for tag in publish.get("tags", [])])
        lines.append("- **发布信息建议：**")
        lines.append(f"  - 标题：{publish.get('title') or '未生成'}")
        if tags:
            lines.append(f"  - 标签：{tags}")
    if references:
        lines.append("- **参考来源：**")
        for ref in references:
            title = str(ref.get("title") or ref.get("source") or ref.get("video_id") or f"爆款{ref.get('rank', '')}")
            if len(title) > 80:
                title = title[:77] + "..."
            tags = " ".join([f"#{tag}" for tag in ref.get("tags", [])])
            lines.append(
                f"  {int(ref.get('rank') or 0)}. {title} · "
                f"点赞 {int(ref.get('likes') or 0):,} · "
                f"相似度 {float(ref.get('similarity') or 0):.0%} · "
                f"综合分 {float(ref.get('rank_score') or 0):.0%} · "
                f"{ref.get('hook_type') or '未知钩子'}"
            )
            extra = []
            if tags:
                extra.append(f"标签：{tags}")
            if ref.get("author"):
                extra.append(f"作者：{ref['author']}")
            if ref.get("video_id"):
                extra.append(f"视频ID：{ref['video_id']}")
            if ref.get("video_url"):
                extra.append(f"链接：{ref['video_url']}")
            if extra:
                lines.append(f"     {' · '.join(extra)}")
    version_reviews = metadata.get("version_reviews") or []
    if version_reviews:
        lines.append("- **逐版本 AI质检：**")
        for review in version_reviews:
            status = "通过" if review.get("passed") else "需优化"
            lines.append(
                f"  - 版本{int(review.get('version') or 0)}："
                f"{int(review.get('score') or 0)}/100 · {status}"
            )
    return "\n".join(lines)


def generate_detailed(
    topic: str,
    requirements: str = "",
    niche: str = "",
    versions: int = 3,
) -> dict:
    """生成爆款文案"""
    print(f"\n🤖 爆款智能体启动...")
    print(f"📝 主题：{topic}")
    print(f"📊 {kb.get_stats()}\n")

    search_query, topic_context = _topic_input_context(topic)

    # Step 1: 检索相似爆款
    print("🔍 检索相似爆款...")
    similar = kb.search_scripts(search_query, n=5, niche=niche or None)

    # Step 2: 获取整体规律
    stats = kb.get_all_patterns(niche=niche or None)

    # Step 3: 拼装上下文，调用 Claude 生成
    print("✍️  生成文案中...")

    kb_context = ""
    if similar:
        kb_context = "【知识库中的相关爆款】\n\n"
        for i, s in enumerate(similar, 1):
            kb_context += f"爆款{i}（点赞{s['likes']:,}，相似度{s['similarity']:.2f}，综合参考分{s.get('rank_score', 0):.2f}）\n"
            kb_context += f"钩子类型：{s['hook_type']}\n"
            kb_context += f"钩子公式：{s['analysis'].get('hook_formula', '')}\n"
            kb_context += f"结构：{s['structure']}\n"
            kb_context += f"爆火原因：{s['why_viral']}\n"
            kb_context += f"原文（前150字）：{s['script'][:150]}\n\n"
    else:
        kb_context = "（知识库暂无相关内容，请先用 learn 命令导入爆款视频）\n"

    pattern_context = ""
    if stats["count"] > 0:
        pattern_context = f"\n【知识库整体规律】共{stats['count']}条爆款\n"
        pattern_context += f"钩子类型分布：{stats['hook_types']}\n"
        pattern_context += f"高频爆款元素：{', '.join(stats['top_viral_elements'][:10])}\n"

    learning_context = ""
    try:
        from .feedback.analyzer import build_learning_context

        learned = build_learning_context(niche=niche or "", limit=10)
        if learned.get("sample_size"):
            learning_context = (
                f"\n【最近发布反馈学习】共{learned['sample_size']}条复盘样本\n"
                f"结果分布：{learned.get('result_levels')}\n"
            )
            if learned.get("must_use"):
                learning_context += f"本次必须强化：{', '.join(learned['must_use'])}\n"
            if learned.get("prefer"):
                learning_context += f"优先使用：{', '.join(learned['prefer'])}\n"
            if learned.get("avoid"):
                learning_context += f"避免复用：{', '.join(learned['avoid'])}\n"
            if learned.get("experiment"):
                learning_context += f"可测试方向：{', '.join(learned['experiment'])}\n"
    except Exception as exc:
        print(f"⚠️ 读取反馈学习上下文失败，跳过：{exc}")

    format_blocks = "\n\n".join(
        [
            f"""【版本{i} - 钩子类型】
（参考：借鉴了爆款X的XX公式）
标题：
这里写一个适合发布页/标题栏的标题

描述：
这里写完整口播文案正文，不少于300字

标签推荐：
#标签1 #标签2 #标签3 #标签4 #标签5

封面图建议：
这里写具体可执行的封面画面建议，包含主体、动作、场景、情绪和构图

封面文字建议：
这里写一句适合放在封面上的短文字，12字以内优先"""
            for i in range(1, int(versions) + 1)
        ]
    )

    niche_rules = _load_niche_rules(niche)
    niche_rules_block = f"\n【{niche}赛道运营规则】\n{niche_rules}\n" if niche_rules else ""

    prompt = f"""你是一位顶级短视频爆款文案创作者。你的任务是直接交付可拍摄、可口播的短视频成片文案，不写创作说明，不写分析报告。

{kb_context}{pattern_context}{learning_context}{niche_rules_block}
---
现在请基于以上爆款数据和用户输入，创作{versions}个版本的爆款短视频文案。用户要求几个版本，你就只输出几个版本，不要多输出：

{topic_context}
{f'赛道：{niche}' if niche else ''}
{f'要求：{requirements}' if requirements else ''}

创作要求：
1. 每个版本使用不同的钩子类型（从上面的爆款中提炼）
2. 前3秒必须有强钩子，参考知识库中表现最好的公式
3. 结构清晰：钩子→冲突/痛点→解决/干货→行动号召
4. 口语化，真人讲述感
5. 每个版本注明：借鉴了哪个爆款的结构/公式
6. 每个版本必须是独立发布成品包，包含标题、描述、标签推荐、封面图建议、封面文字建议
7. 描述必须是一整段能直接口播的正文，正文不少于300字
8. 封面图建议必须具体到画面，不要写抽象形容词堆砌
9. 封面文字建议必须短、清楚、有点击理由，不要超过16个字
10. 不要输出“创作说明”“版本对比分析”“共同优化点”“建议测试”“适合人群”等解释性内容
11. 不要用项目符号拆分析点，只按指定字段输出
12. 如果用户输入的是长参考原文，最终文案必须明显不同于原文：不能只是加几句开头，也不能按原文顺序逐句复述

只能使用下面格式输出：
{format_blocks}
"""

    result = _call_claude(prompt)
    similarity = _shingle_similarity(topic, result)
    if len(_compact_text(topic)) >= 120 and similarity > 0.22:
        rewrite_prompt = f"""{prompt}

---
你刚才生成的文案和参考原文相似度过高，像是在复述原稿。
请重新生成，要求更严格：
1. 只保留参考原文的核心选题和必要事实，不保留原文句子
2. 换一个全新的开头，不要沿用参考原文第一句话或常见疑问句
3. 换叙事顺序，先制造误区或场景，再解释方法
4. 不要连续复用参考原文中超过12个字的原句
5. 只输出指定格式的成片口播文案，不要解释
"""
        result = _call_claude(rewrite_prompt)
        similarity = _shingle_similarity(topic, result)
    references = _reference_report_items(similar)
    print("🧪 逐版本 AI 质检中...")
    version_reviews = _review_generated_versions(result, topic_context, niche, requirements, references)
    reviewed_result = _append_quality_reviews(result, version_reviews)
    viral_score = _score_generated_script(reviewed_result, references, similarity)
    publish = _suggest_publish_metadata(reviewed_result, niche=niche)
    strategy = _generation_strategy(similar, stats, search_query, niche, versions)
    metadata = {
        "references": references,
        "strategy": strategy,
        "publish": publish,
        "version_reviews": version_reviews,
        "source_similarity": similarity,
        "top_reference_similarity": max([item["similarity"] for item in references] or [0]),
        "top_reference_rank_score": max([item["rank_score"] for item in references] or [0]),
        "viral_score": viral_score,
    }
    # 拆分成独立版本列表，每个版本含正文、质检结果、版本号、结构化字段
    by_review = {int(r.get("version") or 0): r for r in version_reviews}
    versions_list = []
    for item in _split_generated_versions(reviewed_result):
        review = by_review.get(item["index"]) or {}
        fields = _parse_version_fields(item["content"])
        versions_list.append({
            "index": item["index"],
            "content": item["content"],
            "title": fields["title"],
            "description": fields["description"],
            "tags": fields["tags"],
            "cover_image": fields["cover_image"],
            "cover_text": fields["cover_text"],
            "score": int(review.get("score") or 0),
            "passed": bool(review.get("passed")),
            "strengths": review.get("strengths") or [],
            "problems": review.get("problems") or [],
            "suggestion": review.get("suggestion") or "",
        })
    try:
        from .feedback.tracker import record_generation

        generation_id = record_generation(
            script=reviewed_result,
            topic=topic,
            niche=niche,
            requirements=requirements,
            hook_type=",".join(strategy.get("selected_patterns", {}).get("hook_types", [])[:3]),
            structure=",".join(strategy.get("selected_patterns", {}).get("structures", [])[:3]),
            reference_videos=[item.get("video_id", "") for item in references if item.get("video_id")],
            generation_params={"versions": int(versions)},
            metadata=metadata,
        )
        metadata["generation_id"] = generation_id
        print(f"🧠 已记录生成ID：{generation_id}")
    except Exception as exc:
        print(f"⚠️ 记录生成反馈样本失败：{exc}")

    print("\n✅ 生成完毕\n")
    return {
        "content": reviewed_result,
        "versions_list": versions_list,
        "metadata": metadata,
        "report_markdown": format_generation_report(metadata),
    }


def generate(
    topic: str,
    requirements: str = "",
    niche: str = "",
    versions: int = 3,
) -> str:
    """生成爆款文案，兼容 CLI/旧调用，只返回正文。"""
    return generate_detailed(topic=topic, requirements=requirements, niche=niche, versions=versions)["content"]
