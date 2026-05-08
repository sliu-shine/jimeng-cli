"""
分析器：用 Claude API 深度拆解爆款文案的模式
支持中转 API
"""
import json
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.claude_client import ClaudeClient
from .ai_providers import apply_provider, list_providers


def _call_provider(prompt: str, provider_id: str | None = None) -> str:
    provider = apply_provider(provider_id or os.environ.get("AI_PROVIDER_SELECTED"))
    client = ClaudeClient(provider_id=provider.id)

    result = client.create_message(
        model=provider.model or os.getenv("ANTHROPIC_MODEL", client.model),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3500,
    )

    return result['content'][0]['text']


def _call_claude(prompt: str) -> str:
    """通过已配置 AI Provider 调用，支持自动 fallback。"""
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
            errors.append(f"{name}: {str(exc)[:240]}")
            if os.getenv("AI_PROVIDER_AUTO_FALLBACK", "1").strip().lower() in {"0", "false", "no"}:
                break
    raise RuntimeError("所有 AI Provider 均调用失败：\n" + "\n".join(errors))


def engagement_level(likes: int = 0) -> str:
    if likes >= 100000:
        return "super_viral"
    if likes >= 10000:
        return "viral"
    if likes >= 3000:
        return "strong"
    if likes >= 1000:
        return "normal"
    return "unknown"


def analyze_script(script: str, likes: int = 0, niche: str = "", source_account: str = "", tags: list[str] | None = None) -> dict:
    """深度分析一条爆款文案，提取可复用模式"""
    tag_text = "、".join(tags or [])
    context = "\n".join(
        item for item in [
            f"点赞/互动数：{likes:,}" if likes else "",
            f"互动强度：{engagement_level(likes)}" if likes else "",
            f"来源账号：{source_account}" if source_account else "",
            f"赛道：{niche}" if niche else "",
            f"话题标签：{tag_text}" if tag_text else "",
        ]
        if item
    )

    prompt = f"""你是一位顶级短视频爆款分析师，专长是宠物科普、狗狗心理、训犬干货、动物解说类账号拆解。
请深度分析以下爆款视频文案，提取可复用的创作模式。必须把点赞/互动数作为爆款强度参考：互动越高，越要解释它为什么能促成完播、点赞、收藏、评论或转发。

【样本信息】
{context or "无"}

【原始文案】
{script}

请用JSON格式输出分析结果，包含以下字段：
{{
  "hook": "开头钩子的具体内容（原文摘录）",
  "hook_type": "钩子类型（痛点型/反常识型/悬念型/共鸣型/利益型/恐惧型/好奇型/拟人共情型）",
  "hook_formula": "钩子公式模板，用[]标记可替换变量，如：你还在[错误行为]？难怪[负面结果]",
  "topic_type": "选题类型，如狗狗心理/训犬边界/宠物冷知识/情绪陪伴/动物解说",
  "topic_formula": "选题公式，用[]标记变量",
  "structure": "内容结构描述，如：痛点引入→解决方案→案例佐证→行动号召",
  "retention_design": "完播推动机制：它如何让人继续看下去",
  "emotional_core": "情绪核心，如心疼、愧疚、惊讶、被理解、治愈",
  "counterintuitive_point": "反常识点或新鲜认知",
  "comment_trigger": "可能激发评论的点",
  "pet_personification": "拟人化方式和程度",
  "science_explanation": "科学/行为解释的使用方式",
  "interaction_analysis": "结合点赞/互动数判断，这条为什么值得点赞、收藏、评论或转发",
  "engagement_level": "{engagement_level(likes)}",
  "emotion_triggers": ["情绪触发点列表"],
  "viral_elements": ["爆款元素列表，如：反转、共鸣、干货、恐惧、稀缺"],
  "style_tags": ["风格标签，如强共情、轻科普、短句、拟人化、系列感"],
  "target_audience": "精准受众描述",
  "core_value": "核心价值主张",
  "why_viral": "为什么会爆的核心原因（3条以内）",
  "rewrite_template": "基于此文案的改写模板，用[]标记可替换部分",
  "replication_notes": "复刻注意事项：哪些可学，哪些不要照搬",
  "quality_score": 0到10的整数,
  "replication_score": 0到10的整数,
  "cta": "行动号召的方式"
}}

只输出JSON，不要其他内容。"""

    text = _call_claude(prompt)

    try:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "hook": script[:50],
            "hook_type": "未识别",
            "structure": "未分析",
            "why_viral": text[:200],
            "viral_elements": [],
            "emotion_triggers": [],
            "style_tags": [],
            "rewrite_template": script,
            "engagement_level": engagement_level(likes),
        }


def batch_analyze(scripts_data: list[dict]) -> list[dict]:
    results = []
    total = len(scripts_data)
    for i, item in enumerate(scripts_data):
        print(f"[{i+1}/{total}] 分析: {item.get('video_id', '')} ...")
        analysis = analyze_script(
            script=item["script"],
            likes=item.get("likes", 0),
            niche=item.get("niche", ""),
        )
        results.append({**item, "analysis": analysis})
    return results
