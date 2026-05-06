"""
爆款文案智能体
用 claude CLI 做推理，手动管理检索→生成流程
"""
import os
import re
import subprocess
from . import knowledge_base as kb
from .ai_providers import apply_provider


CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")


def _call_claude(prompt: str) -> str:
    provider = apply_provider(os.environ.get("AI_PROVIDER_SELECTED"))
    env = os.environ.copy()
    api_key = provider.api_key or os.environ.get("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
    base_url = provider.base_url or os.environ.get("ANTHROPIC_BASE_URL", ANTHROPIC_BASE_URL)
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_MODEL"] = provider.model
    env["CLAUDE_MODEL"] = provider.model

    command = [CLAUDE_BIN, "-p", prompt, "--output-format", "text"]
    if provider.model:
        command.extend(["--model", provider.model])

    result = subprocess.run(
        command,
        capture_output=True, text=True, env=env, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI 错误: {result.stderr[:300]}")
    return result.stdout.strip()


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
            "hook_type": item.get("hook_type", ""),
            "structure": item.get("structure", ""),
        })
    return items


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
            kb_context += f"爆款{i}（点赞{s['likes']:,}，相似度{s['similarity']:.2f}）\n"
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

    format_blocks = "\n\n".join(
        [
            f"【版本{i} - 钩子类型】\n（参考：借鉴了爆款X的XX公式）\n这里写完整口播文案正文，不要分析，不要说明"
            for i in range(1, int(versions) + 1)
        ]
    )

    prompt = f"""你是一位顶级短视频爆款文案创作者。你的任务是直接交付可拍摄、可口播的短视频成片文案，不写创作说明，不写分析报告。

{kb_context}{pattern_context}
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
6. 每个版本必须是一整段能直接口播的正文，正文不少于300字
7. 不要输出“创作说明”“版本对比分析”“共同优化点”“建议测试”“适合人群”等解释性内容
8. 不要用项目符号拆分析点，除标题和参考行外，只输出文案正文
9. 如果用户输入的是长参考原文，最终文案必须明显不同于原文：不能只是加几句开头，也不能按原文顺序逐句复述

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
    viral_score = _score_generated_script(result, references, similarity)
    publish = _suggest_publish_metadata(result, niche=niche)
    metadata = {
        "references": references,
        "publish": publish,
        "source_similarity": similarity,
        "top_reference_similarity": max([item["similarity"] for item in references] or [0]),
        "viral_score": viral_score,
    }
    print("\n✅ 生成完毕\n")
    return {
        "content": result,
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
