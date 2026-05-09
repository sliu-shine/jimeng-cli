"""
视频提示词智能体
理解文案上下文，为每个段落生成连贯的视频提示词
"""
import os
import re
from typing import List, Dict, Optional
from dataclasses import dataclass
from scripts.claude_client import ClaudeClient
from .ai_providers import apply_provider
from .seedance_prompt_builder import (
    build_prompt_for_segment,
    detect_pet_context,
    analyze_keywords,
    _channel_profile,
    _render_profile_text,
)


@dataclass
class SeedanceSegment:
    """Seedance 段落数据结构"""
    index: int
    duration: int
    transcript: str
    function: str
    main_action: str
    emotion: str
    scene: str
    storyboard: list[str]
    prompt: str
    source: str = "smart_segment"


def _call_claude_for_storyboard(
    segment_text: str,
    duration: int,
    pet_context: dict,
    channel_id: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> list[str]:
    """
    使用 Claude API 理解文案内容，生成定制化的分镜描述

    Args:
        segment_text: 段落文案
        duration: 时长（秒）
        pet_context: 宠物上下文
        channel_id: 频道ID
        provider_id: AI Provider ID

    Returns:
        分镜描述列表
    """
    pet_label = pet_context.get("pet_label", "狗狗")
    profile = _channel_profile(channel_id)
    hook_strategy = _render_profile_text(profile.get("hook_strategy"), pet_context)
    first_3s_rule = _render_profile_text(profile.get("first_3s_rule"), pet_context)
    retention_structure = _render_profile_text(profile.get("retention_structure"), pet_context)
    density_rule = _render_profile_text(profile.get("density_rule"), pet_context)
    shot_guidance = _render_profile_text(profile.get("shot_guidance"), pet_context)
    science_guidance = _render_profile_text(profile.get("science_guidance"), pet_context)
    motion = _render_profile_text(profile.get("motion"), pet_context)

    # 根据时长计算分镜数量
    shot_count = max(2, min(8, duration // 2))

    prompt = f"""你是专业的视频分镜师。请为以下文案设计精准的分镜描述。

# 文案内容
{segment_text}

# 基本信息
- 时长：{duration}秒
- 宠物类型：{pet_label}
- 目标风格：{profile.get("split_style", "温馨治愈日系二维手绘动画")}
- 动态原则：{motion}
- 分镜原则：{shot_guidance}
- 科普原则：{science_guidance}
- 分镜数量参考：约{shot_count}个，根据内容信息密度灵活增减

# 核心要求（非常重要！）

1. **先把爆款节奏内化成具体画面，不要把规则文字写进输出**
   - 开头策略：{hook_strategy}
   - 前3秒：{first_3s_rule}
   - 留存节奏：{retention_structure}
   - 画面密度：{density_rule}
   - 输出时不要写“爆款开头策略、前3秒视觉钩子、留存节奏原则、画面密度要求”等标签，只输出可见画面

2. **分镜必须准确表达文案的具体内容**
   - 如果文案说"深夜吃狗粮"，就要画{pet_label}起身走到狗盆前吃，不能画睡觉
   - 如果文案说"食物分三档"，就要用画面展示三种食物的区别（狗粮、掉地上的、手喂的）
   - 如果文案说"扔地上吃很快，手喂吃很慢"，就要有对比镜头展示速度差异
   - 如果文案说"出门前摸头、听脚步声"，就要画出门和回家的场景

3. **避免通用模板**
   - 不要每段都是"抬头-摸头-暖光扩散"
   - 要根据文案的具体情节设计画面
   - 每个分镜要有信息变化，不要重复

4. **画面要可视化文案的核心信息**
   - 用动画化的方式表现抽象概念（如"等级观念"可以用光圈层级、"赌"可以用期待的眼神）
   - 科普内容用温馨的动画符号（气味粒子、情绪云团、光圈等）
   - 不要出现任何字幕、中文文字、英文文字、小标签、手写体文字、屏幕文字

5. **镜头类型参考**
   - 近景固定镜头、微距特写镜头、中景轻微横移、俯拍镜头、主观视角镜头、特写镜头

# 输出格式
只输出分镜描述，每行一个分镜，格式如下：

0-2秒：近景固定镜头，[具体画面描述，必须符合文案内容]
2-4秒：微距特写镜头，缓慢推近，[具体画面描述]
...

要求：
- 每个分镜描述要具体、可执行
- 必须体现文案的核心情节
- 不要输出任何解释或说明
- 直接输出分镜列表
"""

    try:
        provider = apply_provider(provider_id or os.environ.get("AI_PROVIDER_SELECTED"))
        client = ClaudeClient(provider_id=provider.id)

        result = client.create_message(
            model=provider.model or os.getenv("ANTHROPIC_MODEL", client.model),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=int(os.getenv("STORYBOARD_MAX_TOKENS", "2000")),
            temperature=float(os.getenv("STORYBOARD_TEMPERATURE", "0.7")),
        )

        content = result.get("content") or []
        text = ""
        for item in content:
            if isinstance(item, dict) and item.get("type", "text") == "text":
                text += str(item.get("text") or "")

        if not text.strip():
            raise RuntimeError("AI 返回空内容")

        # 解析分镜列表，保留 0-2秒 / 2-4秒 这类时间轴前缀。
        storyboard = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^\s*[-*•]?\s*\d+[\.、)]\s*", "", line)
            storyboard.append(line)

        return storyboard if storyboard else [f"0-{duration}秒：{pet_label}日常互动，温馨场景"]

    except Exception as exc:
        print(f"⚠️ AI 生成分镜失败，使用默认分镜：{exc}")
        # 降级方案：返回基础分镜
        return [
            f"0-{max(2, min(duration, 2))}秒：{pet_label}在温馨客厅中的日常场景",
            f"{max(2, min(duration, 2))}-{duration}秒：主人与{pet_label}的温馨互动",
        ]


def generate_video_prompts(
    segments: List[Dict],
    full_context: str,
    channel_id: Optional[str] = None,
    scene_continuity: bool = True,
    provider_id: Optional[str] = None,
) -> List[Dict]:
    """
    为每个段落生成视频提示词

    Args:
        segments: 分段结果列表（来自 text_segmenter）
        full_context: 完整文案（用于理解上下文）
        channel_id: 频道ID（用于获取频道风格）
        scene_continuity: 是否保持场景连贯性
        provider_id: AI Provider ID

    Returns:
        每个段落的提示词配置列表
    """
    if not segments:
        return []

    # 检测宠物上下文（用于风格模板）
    pet_context = detect_pet_context(full_context)

    prompts = []

    print(f"\n🎬 开始生成 {len(segments)} 个段落的视频提示词...")

    # 为每个段落生成提示词
    for i, seg in enumerate(segments, 1):
        print(f"  [{i}/{len(segments)}] 正在为段落 {seg['index']} 生成分镜...")

        # 分析关键词
        keywords = analyze_keywords(seg["text"], pet_context)

        # 使用 AI 生成定制化分镜（理解文案内容）
        storyboard = _call_claude_for_storyboard(
            segment_text=seg["text"],
            duration=int(seg["estimated_duration"]),
            pet_context=pet_context,
            channel_id=channel_id,
            provider_id=provider_id,
        )

        print(f"    ✓ 生成了 {len(storyboard)} 个分镜")

        # 构建 SeedanceSegment 对象
        seedance_seg = SeedanceSegment(
            index=seg["index"],
            duration=int(seg["estimated_duration"]),
            transcript=seg["text"],
            function=f"段落{seg['index']}",
            main_action=keywords.get("actions", ["日常互动"])[0] if keywords.get("actions") else "日常互动",
            emotion=keywords.get("emotions", ["温馨"])[0] if keywords.get("emotions") else "温馨",
            scene=keywords.get("scenes", ["温馨客厅"])[0] if keywords.get("scenes") else "温馨客厅",
            storyboard=storyboard,
            prompt="",  # 将由 build_prompt_for_segment 生成
        )

        # 使用 Seedance 的提示词生成逻辑
        prompt_text = build_prompt_for_segment(
            segment=seedance_seg,
            pet_context=pet_context,
            material_refs=None,
            channel_id=channel_id,
        )

        prompts.append({
            "segment_index": seg["index"],
            "segment_text": seg["text"],
            "start_time": seg["start_time"],
            "end_time": seg["end_time"],
            "duration": seg["estimated_duration"],
            "prompt": prompt_text,
            "shot": "",  # Seedance 提示词已包含镜头信息
            "subject": pet_context.get("pet_label", "宠物"),
            "action": seedance_seg.main_action,
            "scene": seedance_seg.scene,
            "full_content": prompt_text,
        })

    print(f"✅ 全部 {len(prompts)} 个段落的提示词生成完成\n")

    return prompts


def format_prompts_for_display(prompts: List[Dict]) -> str:
    """
    格式化提示词结果用于显示
    """
    if not prompts:
        return "暂无提示词结果"

    lines = ["# 视频提示词生成结果\n"]
    lines.append(f"**总段落数：** {len(prompts)}\n")

    for p in prompts:
        lines.append(f"## 段落 {p['segment_index']} ({p['start_time']:.1f}s - {p['end_time']:.1f}s)")
        lines.append(f"**文案：** {p['segment_text']}\n")
        lines.append(f"**提示词：**")
        lines.append(f"{p['prompt']}\n")

        if p.get("shot") or p.get("subject") or p.get("action") or p.get("scene"):
            lines.append("**分镜元素：**")
            if p.get("shot"):
                lines.append(f"- 镜头：{p['shot']}")
            if p.get("subject"):
                lines.append(f"- 主体：{p['subject']}")
            if p.get("action"):
                lines.append(f"- 动作：{p['action']}")
            if p.get("scene"):
                lines.append(f"- 场景：{p['scene']}")
            lines.append("")

    return "\n".join(lines)


def prompts_to_table_data(prompts: List[Dict]) -> List[List]:
    """
    转换为表格数据格式（用于 Gradio Dataframe）
    """
    if not prompts:
        return []

    rows = []
    for p in prompts:
        rows.append([
            p["segment_index"],
            f"{p['start_time']:.1f}s - {p['end_time']:.1f}s",
            p["segment_text"][:30] + "..." if len(p["segment_text"]) > 30 else p["segment_text"],
            p["prompt"][:60] + "..." if len(p["prompt"]) > 60 else p["prompt"],
        ])

    return rows


def export_to_seedance_queue(
    prompts: List[Dict],
    project_name: str,
    ratio: str = "9:16",
    model_version: str = "seedance2.0",
) -> Dict:
    """
    导出为 Seedance 队列格式

    Returns:
        {
            "version": 1,
            "project_name": str,
            "segments": List[Dict]
        }
    """
    segments = []

    for p in prompts:
        segments.append({
            "id": f"segment-{p['segment_index']}",
            "name": f"段落{p['segment_index']}",
            "mode": "text2video",
            "prompt": p["prompt"],
            "duration": str(int(p["duration"])),
            "ratio": ratio,
            "model_version": model_version,
            "images": [],
            "videos": [],
            "audios": [],
            "metadata": {
                "segment_text": p["segment_text"],
                "start_time": p["start_time"],
                "end_time": p["end_time"],
                "shot": p.get("shot", ""),
                "subject": p.get("subject", ""),
                "action": p.get("action", ""),
                "scene": p.get("scene", ""),
            }
        })

    return {
        "version": 1,
        "project_name": project_name,
        "created_at": "",  # 由调用方填充
        "segments": segments,
    }
