"""
Sora 2.0 prompt builder for cat/dog viral videos.

专门为云雾 API 的 sora-2-all 模型设计的提示词构建器。
与 Seedance 相比，Sora 更擅长真实感视频，所以风格定位不同。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

# 复用 Seedance 的一些基础功能
from viral_agent.seedance_prompt_builder import (
    detect_pet_context,
    analyze_keywords,
    BEHAVIOR_KEYWORDS,
    EMOTION_KEYWORDS,
    SCIENCE_KEYWORDS,
)


# Sora 的默认风格模板（更偏向真实感）
SORA_STYLE_TEMPLATE = (
    "高质量真实感视频风格，电影级画面质感，自然光影，真实物理运动。"
    "核心主体为{subject_style}，{pet_label}毛发自然真实，表情生动自然，动作流畅。"
    "场景为真实生活化场景，可以是家庭客厅、卧室、户外公园、草地等，"
    "保持自然真实的光线和环境氛围。"
    "镜头运动自然流畅，避免过度夸张的特效。"
    "整体风格温暖治愈，贴近生活，真实可信。"
)

# Sora 的全局质量要求
SORA_QUALITY_REQUIREMENTS = (
    "适配云雾 Sora 2.0 模型，16:9 横屏，高质量真实感视频，"
    "画面稳定流畅，角色造型一致，动作自然真实，"
    "无画面崩坏，无逻辑错误，无角色变形。"
)

# Sora 的负面约束
SORA_NEGATIVE_CONSTRAINTS = (
    "不要出现字幕、文字、水印、logo。"
    "不要过度卡通化、不要动漫风格、不要3D渲染感。"
    "不要低质量画面、不要模糊失焦。"
)

# Sora 的无对话约束
SORA_NO_DIALOGUE = (
    "画面为纯视觉内容，不要人声对话、不要口型说话、不要配音旁白；"
    "人物和宠物通过表情、动作和肢体语言表达情绪。"
)


@dataclass
class SoraSegment:
    """Sora 视频片段"""
    index: int
    duration: int
    transcript: str
    scene_description: str
    main_action: str
    camera_movement: str
    prompt: str


def _normalize_text(text: str) -> str:
    """标准化文本"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _split_sentences(text: str) -> list[str]:
    """按句子拆分文本"""
    parts = re.split(r"(?<=[。！？!?])", _normalize_text(text))
    return [part.strip() for part in parts if part.strip()]


def _estimate_seconds(text: str) -> int:
    """估算文本对应的视频时长（秒）"""
    compact = re.sub(r"\s+", "", text)
    return max(5, math.ceil(len(compact) / 4.5))


def split_transcript_for_sora(transcript: str) -> list[tuple[int, str]]:
    """
    将文案拆分为适合 Sora 的视频片段

    Sora 支持更长的视频，所以可以拆分成更大的段落
    """
    sentences = _split_sentences(transcript)
    if not sentences:
        return []

    segments: list[tuple[int, str]] = []
    current: list[str] = []
    current_seconds = 0

    for sentence in sentences:
        sentence_seconds = min(20, max(5, _estimate_seconds(sentence)))
        if current and current_seconds + sentence_seconds > 20:
            segments.append((max(5, min(20, current_seconds)), "".join(current)))
            current = [sentence]
            current_seconds = sentence_seconds
        else:
            current.append(sentence)
            current_seconds += sentence_seconds

    if current:
        duration = max(5, min(20, current_seconds))
        segments.append((duration, "".join(current)))

    return segments


def _render_template(text: str, pet_context: dict[str, str]) -> str:
    """渲染模板"""
    return text.format(**pet_context)


def _scene_description(text: str, pet_context: dict[str, str]) -> str:
    """生成场景描述"""
    pet_label = pet_context["pet_label"]

    # 根据关键词判断场景
    if any(word in text for word in ["睡", "床", "卧室"]):
        return f"温暖的卧室，柔和的自然光线，{pet_label}在床边或地毯上"
    if any(word in text for word in ["草地", "公园", "户外"]):
        return f"户外公园或草地，自然日光，{pet_label}在开阔的环境中"
    if any(word in text for word in ["沙发", "客厅"]):
        return f"温馨的客厅，沙发和家具，{pet_label}和主人在家中"
    if any(word in text for word in ["窗边", "阳光"]):
        return f"窗边明亮的室内空间，阳光洒进来，{pet_label}在光线中"

    return f"温暖的家庭环境，自然光线，{pet_label}和主人的日常生活场景"


def _main_action(text: str, keywords: dict[str, list[str]], pet_context: dict[str, str]) -> str:
    """生成主要动作描述"""
    pet_label = pet_context["pet_label"]

    # 优先使用关键词匹配的行为
    if keywords["behaviors"]:
        return keywords["behaviors"][0]

    # 根据文本内容推断动作
    if "主人" in text:
        return f"{pet_label}看向主人，眼神温柔，尾巴轻轻摇动，靠近主人身边"

    return f"{pet_label}自然地活动，表情生动，动作流畅自然"


def _camera_movement(index: int, total: int) -> str:
    """生成镜头运动描述"""
    movements = [
        "镜头缓慢推进，从中景到近景",
        "镜头平稳横移，跟随主体移动",
        "固定镜头，捕捉细节和表情",
        "镜头缓慢拉远，展现环境全景",
        "低角度镜头，从宠物视角观察",
        "镜头轻微俯拍，温柔的观察视角",
    ]

    if index == 1:
        return "镜头缓慢推进，建立场景和主体"
    if index == total:
        return "镜头缓慢拉远，温馨收尾"

    return movements[index % len(movements)]


def build_sora_prompt(
    segment: SoraSegment,
    pet_context: dict[str, str],
    style_template: str = SORA_STYLE_TEMPLATE,
) -> str:
    """构建 Sora 的完整提示词"""
    style = _render_template(style_template, pet_context)

    prompt = (
        f"{SORA_NO_DIALOGUE}"
        f"{style} "
        f"场景：{segment.scene_description}。"
        f"主要动作：{segment.main_action}。"
        f"镜头：{segment.camera_movement}。"
        f"{SORA_QUALITY_REQUIREMENTS}"
        f"{SORA_NEGATIVE_CONSTRAINTS}"
    )

    return prompt


def build_sora_segments(transcript: str) -> list[SoraSegment]:
    """
    构建 Sora 视频片段列表

    Args:
        transcript: 文案文本

    Returns:
        Sora 片段列表
    """
    raw_segments = split_transcript_for_sora(transcript)
    pet_context = detect_pet_context(transcript)

    segments: list[SoraSegment] = []
    total = len(raw_segments)

    for idx, (duration, text) in enumerate(raw_segments, 1):
        keywords = analyze_keywords(text, pet_context)

        segment = SoraSegment(
            index=idx,
            duration=duration,
            transcript=text,
            scene_description=_scene_description(text, pet_context),
            main_action=_main_action(text, keywords, pet_context),
            camera_movement=_camera_movement(idx, total),
            prompt="",
        )

        segment.prompt = build_sora_prompt(segment, pet_context)
        segments.append(segment)

    return segments


def build_sora_queue_document(segments: list[SoraSegment]) -> str:
    """
    构建 Sora 队列 JSON 文档

    格式与 Seedance 保持一致，便于复用队列执行逻辑
    """
    queue_segments = []
    for segment in segments:
        queue_segments.append({
            "id": f"sora-segment-{segment.index:02d}",
            "name": f"Sora视频片段{segment.index:02d}",
            "mode": "text2video",
            "prompt": segment.prompt,
            "images": [],
            "videos": [],
            "audios": [],
            "transition_prompts": [],
            "duration": str(segment.duration),
            "ratio": "16:9",
            "model_version": "sora-2-all",
        })
    return json.dumps({"version": 1, "segments": queue_segments}, ensure_ascii=False, indent=2)


def format_sora_markdown(transcript: str, segments: list[SoraSegment]) -> str:
    """格式化为 Markdown 展示"""
    if not segments:
        return "请先载入或粘贴一段逐字稿。"

    split_way = " + ".join(f"{segment.duration}秒" for segment in segments)
    pet_context = detect_pet_context(transcript)

    lines = [
        "## 对应逐字稿的 Sora 2.0 视频提示词",
        "",
        "### 逐字稿整体拆分说明",
        f"总体拆分逻辑：按内容信息密度拆成5-20秒的视频片段",
        f"预计片段数量：{len(segments)}段",
        f"拆分方式：{split_way}",
        f"核心主体：{pet_context['pet_label']}",
        f"视频风格：高质量真实感视频",
    ]

    for segment in segments:
        lines.extend([
            "",
            f"### 片段{segment.index}",
            f"对应文案：{segment.transcript[:50]}{'...' if len(segment.transcript) > 50 else ''}",
            f"场景：{segment.scene_description}",
            f"主要动作：{segment.main_action}",
            f"镜头运动：{segment.camera_movement}",
            f"生成时长：{segment.duration}秒",
            "",
            f"**Sora 2.0 Prompt：**",
            f"```",
            segment.prompt,
            f"```",
        ])

    return "\n".join(lines)


def build_sora_outputs(transcript: str) -> tuple[str, str]:
    """
    构建 Sora 输出（Markdown + Queue JSON）

    Args:
        transcript: 文案文本

    Returns:
        (markdown_text, queue_json)
    """
    segments = build_sora_segments(transcript)
    markdown = format_sora_markdown(transcript, segments)
    queue_json = build_sora_queue_document(segments)
    return markdown, queue_json
