"""Turn video performance data into reusable learning signals."""

from __future__ import annotations

import json
import os
import re
from statistics import mean

from viral_agent.ai_providers import apply_provider, list_providers
from scripts.claude_client import ClaudeClient

from .tracker import get_feedback, get_generation, get_latest_feedback, get_recent_reviews, save_review


def _rate(numerator: float, denominator: float) -> float:
    return float(numerator or 0) / float(denominator or 1) if denominator else 0.0


def _pct(value) -> float | None:
    if value in (None, ""):
        return None
    value = float(value)
    return value / 100 if value > 1 else value


def _pct_text(value: float | None) -> str:
    if value is None:
        return "未知"
    return f"{value * 100:.2f}%"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _call_feedback_model(prompt: str, provider_id: str | None = None) -> str:
    selected_id = (provider_id or os.environ.get("AI_PROVIDER_SELECTED") or os.environ.get("AI_PROVIDER_DEFAULT") or "").strip().lower()
    providers = list_providers()
    ordered_ids: list[str] = []
    if selected_id:
        ordered_ids.append(selected_id)
    ordered_ids.extend(provider.id for provider in providers if provider.id not in ordered_ids)

    errors: list[str] = []
    for item_id in ordered_ids:
        try:
            provider = apply_provider(item_id)
            client = ClaudeClient(provider_id=provider.id)
            result = client.create_message(
                model=provider.model or os.getenv("ANTHROPIC_MODEL", client.model),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=int(os.getenv("VIRAL_FEEDBACK_MAX_TOKENS", "4000")),
                temperature=float(os.getenv("VIRAL_FEEDBACK_TEMPERATURE", "0.2")),
            )
            parts = []
            for item in result.get("content") or []:
                if isinstance(item, dict) and item.get("type", "text") == "text":
                    parts.append(str(item.get("text") or ""))
            text = "\n".join(part for part in parts if part.strip()).strip()
            if text:
                return text
        except Exception as exc:
            errors.append(f"{item_id}: {str(exc)[:200]}")
            if os.getenv("AI_PROVIDER_AUTO_FALLBACK", "1").strip().lower() in {"0", "false", "no"}:
                break
    raise RuntimeError("AI反馈复盘调用失败：" + "；".join(errors))


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
    raise ValueError("AI反馈复盘返回不是有效 JSON")


def _string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def _merge_unique(base: list[str], extra: list[str], limit: int = 8) -> list[str]:
    merged: list[str] = []
    for item in [*base, *extra]:
        text = str(item or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged[:limit]


def _normalize_ai_review(data: dict) -> dict:
    patch = data.get("strategy_patch") if isinstance(data.get("strategy_patch"), dict) else {}
    labels = data.get("labels") if isinstance(data.get("labels"), dict) else {}
    return {
        "summary": str(data.get("summary") or data.get("main_diagnosis") or "").strip(),
        "result_level": str(data.get("result_level") or "").strip(),
        "script_diagnosis": {
            "hook": str((data.get("script_diagnosis") or {}).get("hook") or "").strip(),
            "body": str((data.get("script_diagnosis") or {}).get("body") or "").strip(),
            "emotion": str((data.get("script_diagnosis") or {}).get("emotion") or "").strip(),
            "ending": str((data.get("script_diagnosis") or {}).get("ending") or "").strip(),
        },
        "labels": {
            "success": _string_list(labels.get("success"))[:6],
            "failure": _string_list(labels.get("failure"))[:6],
            "uncertain": _string_list(labels.get("uncertain"))[:4],
        },
        "next_version_brief": str(data.get("next_version_brief") or "").strip(),
        "strategy_patch": {
            "must_use": _string_list(patch.get("must_use"))[:6],
            "prefer": _string_list(patch.get("prefer"))[:6],
            "avoid": _string_list(patch.get("avoid"))[:6],
            "experiment": _string_list(patch.get("experiment"))[:6],
        },
    }


def _build_ai_review_prompt(generation: dict, feedback: dict, rule_review: dict) -> str:
    script = str(generation.get("script") or "")[:5000]
    payload = {
        "generation": {
            "generation_id": generation.get("id"),
            "topic": generation.get("topic"),
            "niche": generation.get("niche"),
            "hook_type": generation.get("hook_type"),
            "structure": generation.get("structure"),
            "emotion_direction": generation.get("emotion_direction"),
            "script": script,
        },
        "feedback": {
            "video_id": feedback.get("video_id"),
            "platform": feedback.get("platform"),
            "title": feedback.get("title"),
            "published_at": feedback.get("published_at"),
            "duration_seconds": feedback.get("duration_seconds"),
            "views": feedback.get("views"),
            "likes": feedback.get("likes"),
            "comments": feedback.get("comments"),
            "favorites": feedback.get("favorites"),
            "shares": feedback.get("shares"),
            "completion_rate": feedback.get("completion_rate"),
            "bounce_2s_rate": feedback.get("bounce_2s_rate"),
            "completion_5s_rate": feedback.get("completion_5s_rate"),
            "avg_watch_seconds": feedback.get("avg_watch_seconds"),
            "avg_watch_ratio": feedback.get("avg_watch_ratio"),
            "notes": feedback.get("notes"),
        },
        "rule_review": rule_review,
    }
    return f"""你是短视频运营复盘专家，擅长结合真实数据和文案内容，判断一条视频为什么表现好或不好。

请基于下面的生成记录、发布数据、规则诊断，对这条视频做真正的语义复盘。

要求：
1. 不要只复述数据，要结合原文案判断问题出在哪一句、哪种结构、哪类情绪。
2. 区分确定结论和不确定因素，不要把低播放都归因到文案。
3. 给下一条同赛道文案可直接使用的生成策略补丁。
4. 只输出 JSON，不要 Markdown，不要解释。

输出格式：
{{
  "result_level": "爆款/潜力/普通/失败",
  "summary": "一句话核心判断",
  "script_diagnosis": {{
    "hook": "开头语义诊断",
    "body": "正文节奏/信息密度诊断",
    "emotion": "情绪触发诊断",
    "ending": "结尾互动/传播诊断"
  }},
  "labels": {{
    "success": ["可保留点"],
    "failure": ["失败点"],
    "uncertain": ["不确定因素"]
  }},
  "next_version_brief": "下一版应该怎么写，一句话创作简报",
  "strategy_patch": {{
    "must_use": ["下次必须使用的具体规则"],
    "prefer": ["优先使用的方向"],
    "avoid": ["避免复用的表达/结构"],
    "experiment": ["下一条可测试的实验"]
  }}
}}

待复盘数据：
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def _apply_ai_review(rule_review: dict, ai_review: dict) -> dict:
    if ai_review.get("result_level"):
        rule_review["result_level"] = ai_review["result_level"]
    if ai_review.get("summary"):
        rule_review["main_diagnosis"] = ai_review["summary"]
    rule_review["ai_model_used"] = True
    rule_review["ai_review"] = ai_review

    labels = rule_review.setdefault("labels", {})
    ai_labels = ai_review.get("labels") or {}
    labels["keep"] = _merge_unique(labels.get("keep") or [], ai_labels.get("success") or [], 8)
    labels["improve"] = _merge_unique(labels.get("improve") or [], ai_labels.get("failure") or [], 8)
    labels["uncertain"] = _merge_unique(labels.get("uncertain") or [], ai_labels.get("uncertain") or [], 6)

    patch = rule_review.setdefault("strategy_patch", {})
    ai_patch = ai_review.get("strategy_patch") or {}
    for key in ("must_use", "prefer", "avoid", "experiment"):
        patch[key] = _merge_unique(ai_patch.get(key) or [], patch.get(key) or [], 8)
    if ai_review.get("next_version_brief"):
        rule_review.setdefault("next_suggestion", {})["ai_brief"] = ai_review["next_version_brief"]
    return rule_review


def _result_level(views: int, like_rate: float, completion_rate: float | None, comments: int) -> str:
    if views >= 10000 and (like_rate >= 0.04 or comments >= 20) and (completion_rate or 0) >= 0.20:
        return "爆款"
    if views >= 2000 and (like_rate >= 0.025 or comments >= 5 or (completion_rate or 0) >= 0.18):
        return "潜力"
    if views >= 500 and (like_rate >= 0.015 or (completion_rate or 0) >= 0.10):
        return "普通"
    return "失败"


def _diagnose_feedback(generation: dict, feedback: dict) -> dict:
    views = int(feedback.get("views") or 0)
    likes = int(feedback.get("likes") or 0)
    comments = int(feedback.get("comments") or 0)
    favorites = int(feedback.get("favorites") or 0)
    shares = int(feedback.get("shares") or 0)
    like_rate = _rate(likes, views)
    comment_rate = _rate(comments, views)
    favorite_rate = _rate(favorites, views)
    share_rate = _rate(shares, views)
    completion_rate = _pct(feedback.get("completion_rate"))
    bounce_2s_rate = _pct(feedback.get("bounce_2s_rate"))
    completion_5s_rate = _pct(feedback.get("completion_5s_rate"))
    avg_watch_seconds = _safe_float(feedback.get("avg_watch_seconds"))
    avg_watch_ratio = _pct(feedback.get("avg_watch_ratio"))

    duration = _safe_float(feedback.get("duration_seconds"))
    if not duration and avg_watch_seconds and avg_watch_ratio:
        duration = avg_watch_seconds / avg_watch_ratio

    result_level = _result_level(views, like_rate, completion_rate, comments)

    traffic = "平台给了基础小流量，但没有明显放大" if views >= 500 else "基础播放偏低，选题、封面、账号标签或发布时间都需要排查"
    if views >= 3000:
        traffic = "平台给了二轮以上流量，可以重点分析留存和互动是否承接住"

    if bounce_2s_rate is None:
        hook = "缺少2s跳出率，暂不能判断第一眼吸引力"
    elif bounce_2s_rate <= 0.25:
        hook = "2s跳出率较低，第一眼吸引力尚可"
    elif bounce_2s_rate <= 0.35:
        hook = "2s跳出率中等，开头能留住一部分人，但还不够强"
    else:
        hook = "2s跳出率偏高，第一句话或第一画面需要重做"

    if completion_5s_rate is not None:
        if completion_5s_rate < 0.50:
            hook += "；5s留存偏弱，前5秒没有快速建立看完理由"
        elif completion_5s_rate >= 0.65:
            hook += "；5s留存不错，开头承诺可以保留"

    if avg_watch_ratio is None and completion_rate is None:
        body = "缺少完播/播放占比，暂不能判断正文承接"
    elif (avg_watch_ratio or 0) < 0.30 or (completion_rate or 0) < 0.12:
        body = "正文留存明显不足，节奏、信息密度或视频时长需要优化"
    elif (avg_watch_ratio or 0) < 0.45 or (completion_rate or 0) < 0.22:
        body = "正文承接一般，需要增加中段刺激点和更清晰的结构"
    else:
        body = "正文承接较好，可以复用当前结构"

    if comment_rate == 0 and favorite_rate < 0.006 and share_rate < 0.004:
        interaction = "互动没有被激活，缺少评论触发点、收藏价值或分享理由"
    elif like_rate >= 0.03 and comments == 0:
        interaction = "点赞率尚可但评论为0，内容被认可但没有激发表达"
    elif comments > 0 or shares > 0:
        interaction = "已经出现互动信号，可以分析评论区提炼下一条选题"
    else:
        interaction = "互动一般，需要强化情绪、争议或具体价值"

    keep = []
    improve = []
    avoid = []
    prefer = []
    experiments = []

    if views >= 500:
        keep.append("选题可以继续小规模测试")
    if like_rate >= 0.025:
        keep.append("内容有一定认可度")
        prefer.append("保留当前核心观点，换更强表达方式")
    if bounce_2s_rate is not None and bounce_2s_rate <= 0.35:
        keep.append("第一眼吸引力不算失败")

    if completion_5s_rate is not None and completion_5s_rate < 0.55:
        improve.append("前5秒直接抛结果、冲突或收益")
        prefer.append("反常识或数据对比式hook")
    if (avg_watch_ratio or 0) < 0.35:
        improve.append("压缩时长，提高中段信息密度")
        avoid.append("长铺垫和先讲背景再讲重点")
    if duration and duration > 70 and (avg_watch_ratio or 0) < 0.35:
        prefer.append("45-60秒版本")
        avoid.append("70秒以上弱节奏结构")
    if comments == 0:
        improve.append("结尾加入二选一立场问题或具体提问")
        experiments.append("同选题加入争议型结尾测试评论率")
    if favorites <= 0 or favorite_rate < 0.006:
        improve.append("加入清单、步骤、方法或可保存的信息点")

    if not experiments:
        experiments.append("同选题换hook做一条变体")
    if not keep:
        keep.append("保留数据作为失败样本，避免直接复刻")

    main_diagnosis = "，".join(
        part for part in [
            "开头勉强过关" if bounce_2s_rate is not None and bounce_2s_rate <= 0.35 else "开头需要强化",
            "中后段留存不足" if (avg_watch_ratio or 0) < 0.35 or (completion_rate or 0) < 0.12 else "正文承接尚可",
            "互动未激活" if comments == 0 else "已有互动信号",
        ]
    )

    return {
        "result_level": result_level,
        "main_diagnosis": main_diagnosis,
        "metrics": {
            "views": views,
            "likes": likes,
            "comments": comments,
            "favorites": favorites,
            "shares": shares,
            "like_rate": round(like_rate, 4),
            "comment_rate": round(comment_rate, 4),
            "favorite_rate": round(favorite_rate, 4),
            "share_rate": round(share_rate, 4),
            "completion_rate": completion_rate,
            "bounce_2s_rate": bounce_2s_rate,
            "completion_5s_rate": completion_5s_rate,
            "avg_watch_seconds": avg_watch_seconds,
            "avg_watch_ratio": avg_watch_ratio,
            "estimated_duration_seconds": round(duration, 1) if duration else None,
        },
        "data_reading": {
            "traffic": traffic,
            "hook": hook,
            "body": body,
            "interaction": interaction,
        },
        "labels": {
            "keep": keep[:5],
            "improve": list(dict.fromkeys(improve))[:6],
            "uncertain": [
                "低播放不一定等于文案失败，需同时排查封面、画面、账号标签和发布时间"
            ] if views < 500 else [],
        },
        "next_suggestion": {
            "continue_topic": views >= 500 or like_rate >= 0.02,
            "duration": "45-60秒" if duration and duration > 70 else "保持短节奏，优先控制在60秒内",
            "hook": "前5秒明确结果/冲突/收益",
            "structure": "钩子→冲突→3点信息→评论触发",
            "ending": "用二选一问题、真实争议或评论区追问收尾",
        },
        "strategy_patch": {
            "must_use": [
                "前5秒明确看完收益",
                "每10-15秒加入一个新信息点",
            ],
            "prefer": list(dict.fromkeys(prefer))[:5],
            "avoid": list(dict.fromkeys(avoid))[:5],
            "experiment": list(dict.fromkeys(experiments))[:5],
        },
        "source": {
            "generation_id": generation.get("id"),
            "feedback_id": feedback.get("id"),
            "topic": generation.get("topic"),
            "niche": generation.get("niche"),
        },
    }


def analyze_single_video(
    generation_id: str,
    feedback_id: int | None = None,
    save: bool = True,
    use_ai: bool = True,
    provider_id: str | None = None,
) -> dict:
    generation = get_generation(generation_id)
    if not generation:
        raise ValueError(f"找不到 generation_id：{generation_id}")
    feedback = get_feedback(feedback_id) if feedback_id else get_latest_feedback(generation_id)
    if not feedback:
        raise ValueError(f"generation_id 暂无反馈数据：{generation_id}")
    review = _diagnose_feedback(generation, feedback)
    review["ai_model_used"] = False
    if use_ai:
        try:
            prompt = _build_ai_review_prompt(generation, feedback, review)
            ai_data = _extract_json_object(_call_feedback_model(prompt, provider_id=provider_id))
            if isinstance(ai_data, dict):
                review = _apply_ai_review(review, _normalize_ai_review(ai_data))
        except Exception as exc:
            review["ai_model_error"] = str(exc)
    if save:
        review["review_id"] = save_review(generation_id, int(feedback["id"]), review)
    return review


def build_learning_context(niche: str = "", limit: int = 10) -> dict:
    reviews = get_recent_reviews(niche=niche, limit=limit)
    patches = []
    levels = []
    for item in reviews:
        review = item.get("review_json") or {}
        levels.append(str(review.get("result_level") or ""))
        patch = review.get("strategy_patch") or {}
        patches.append(patch)

    def collect(key: str) -> list[str]:
        values: list[str] = []
        for patch in patches:
            for value in patch.get(key) or []:
                text = str(value).strip()
                if text and text not in values:
                    values.append(text)
        return values[:8]

    avg_like_rate = []
    avg_completion = []
    for item in reviews:
        metrics = (item.get("review_json") or {}).get("metrics") or {}
        if metrics.get("like_rate") is not None:
            avg_like_rate.append(float(metrics["like_rate"]))
        if metrics.get("completion_rate") is not None:
            avg_completion.append(float(metrics["completion_rate"]))

    return {
        "sample_size": len(reviews),
        "niche": niche,
        "result_levels": {level: levels.count(level) for level in sorted(set(levels)) if level},
        "avg_like_rate": round(mean(avg_like_rate), 4) if avg_like_rate else None,
        "avg_completion_rate": round(mean(avg_completion), 4) if avg_completion else None,
        "must_use": collect("must_use"),
        "prefer": collect("prefer"),
        "avoid": collect("avoid"),
        "experiment": collect("experiment"),
    }


def format_review_markdown(review: dict) -> str:
    metrics = review.get("metrics") or {}
    data = review.get("data_reading") or {}
    labels = review.get("labels") or {}
    patch = review.get("strategy_patch") or {}
    ai_review = review.get("ai_review") or {}
    lines = [
        f"## 单条视频复盘：{review.get('result_level')}",
        "",
        f"**核心判断：** {review.get('main_diagnosis')}",
        f"**复盘方式：** {'AI模型语义复盘 + 规则诊断' if review.get('ai_model_used') else '规则诊断（AI模型未启用或调用失败）'}",
        "",
        "### 数据诊断",
        f"- 播放：{metrics.get('views', 0)}",
        f"- 点赞率：{metrics.get('like_rate', 0) * 100:.2f}%",
        f"- 评论率：{metrics.get('comment_rate', 0) * 100:.2f}%",
        f"- 收藏率：{metrics.get('favorite_rate', 0) * 100:.2f}%",
        f"- 完播率：{_pct_text(metrics.get('completion_rate'))}",
        f"- 2s跳出率：{_pct_text(metrics.get('bounce_2s_rate'))}",
        f"- 5s完播率：{_pct_text(metrics.get('completion_5s_rate'))}",
        f"- 平均播放占比：{_pct_text(metrics.get('avg_watch_ratio'))}",
        "",
        "### 归因",
        f"- 流量：{data.get('traffic', '')}",
        f"- 开头：{data.get('hook', '')}",
        f"- 正文：{data.get('body', '')}",
        f"- 互动：{data.get('interaction', '')}",
    ]
    if ai_review:
        script_diag = ai_review.get("script_diagnosis") or {}
        lines.extend([
            "",
            "### AI语义复盘",
            f"- 开头：{script_diag.get('hook') or '未输出'}",
            f"- 正文：{script_diag.get('body') or '未输出'}",
            f"- 情绪：{script_diag.get('emotion') or '未输出'}",
            f"- 结尾：{script_diag.get('ending') or '未输出'}",
        ])
        if ai_review.get("next_version_brief"):
            lines.append(f"- 下一版简报：{ai_review['next_version_brief']}")
    elif review.get("ai_model_error"):
        lines.extend([
            "",
            "### AI语义复盘",
            f"- 调用失败：{review['ai_model_error']}",
        ])
    lines.extend([
        "",
        "### 可保留",
        *[f"- {item}" for item in labels.get("keep") or []],
        "",
        "### 必须改",
        *[f"- {item}" for item in labels.get("improve") or []],
        "",
        "### 策略补丁",
        f"- must_use：{'；'.join(patch.get('must_use') or [])}",
        f"- prefer：{'；'.join(patch.get('prefer') or [])}",
        f"- avoid：{'；'.join(patch.get('avoid') or [])}",
        f"- experiment：{'；'.join(patch.get('experiment') or [])}",
    ])
    return "\n".join(lines).strip()
