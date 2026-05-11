"""
视频提示词智能体
理解文案上下文，为每个段落生成连贯的视频提示词
"""
import os
import re
from pathlib import Path
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

PROMPTS_DIR = Path(__file__).parent / "prompts"

_NICHE_PROMPT_MAP = {
    "宠物": "pet", "pet": "pet", "猫": "pet", "狗": "pet", "萌宠": "pet",
}


def _load_niche_storyboard_rules(niche: str = "") -> str:
    """加载 niche 对应 prompt 文件中与分镜相关的运营规则。"""
    key = str(niche).strip().lower()
    filename = _NICHE_PROMPT_MAP.get(key) or _NICHE_PROMPT_MAP.get(niche.strip())
    if not filename:
        for keyword, fname in _NICHE_PROMPT_MAP.items():
            if keyword in niche:
                filename = fname
                break
    if not filename:
        # 默认尝试 pet（宠物内容检测）
        filename = "pet"
    path = PROMPTS_DIR / f"{filename}.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    # 只提取"前15秒结构"和"数据诊断"两节，其余（选题/封面/避坑）与分镜无关
    sections = []
    for section_title in ["前15秒结构", "数据诊断"]:
        pattern = rf"(## {section_title}.*?)(?=\n## |\Z)"
        match = re.search(pattern, text, re.S)
        if match:
            sections.append(match.group(1).strip())
    return "\n\n".join(sections)


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
    niche: str = "",
    main_characters: Optional[List[str]] = None,
    is_first_segment: bool = False,
) -> tuple:
    """
    使用 Claude API 理解文案内容，生成定制化的分镜描述

    Args:
        segment_text: 段落文案
        duration: 时长（秒）
        pet_context: 宠物上下文
        channel_id: 频道ID
        provider_id: AI Provider ID
        main_characters: 主角特征列表（从第一段传递过来）
        is_first_segment: 是否是第一段（需要生成主角特征）

    Returns:
        (分镜描述列表, 主体, 动作, 场景, 主角特征列表)
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

    niche_rules = _load_niche_storyboard_rules(niche or "宠物")
    niche_rules_block = f"\n# 赛道运营规则（转化为画面时参考）\n{niche_rules}\n" if niche_rules else ""

    # 根据时长计算分镜数量
    shot_count = max(2, min(8, duration // 2))

    # 根据是否是第一段，调整 main_characters 的格式说明
    if is_first_segment:
        main_characters_format = '["主角1特征描述"] 或 ["角色1：特征", "角色2：特征"] （如果有多个主角）'
        main_characters_requirement = '必须输出！根据文案确定主角的具体特征（品种、毛色、体型、气质），如果有多个主角需要分别描述'
    else:
        main_characters_format = '（已在第一段确定，本段无需输出此字段）'
        main_characters_requirement = '本段无需输出此字段，主角特征已在第一段确定'

    # 构建主角一致性说明
    character_consistency_note = ""
    if main_characters and not is_first_segment:
        # 后续段落：使用已确定的主角特征
        characters_desc = "、".join(main_characters)
        character_consistency_note = f"""
# 主角特征（必须严格遵守！）
本视频的主角特征已在第一段确定，所有段落必须保持一致：
{characters_desc}

**重要**：主角的品种、颜色、体型、气质等核心特征必须与上述描述完全一致，不要改变！
如果文案中提到其他猫狗（配角），可以自由设计，但主角必须保持一致。
"""
    elif is_first_segment:
        # 第一段：需要确定主角特征
        character_consistency_note = f"""
# 主角特征确定（第一段重要任务！）
这是本视频的第一段，你需要根据文案内容确定主角的具体特征。
主角特征将在后续所有段落中保持一致，所以请仔细设计。

**主角特征要求**：
- 如果文案明确提到品种（如"金毛"、"橘猫"），必须使用该品种
- 如果文案没有明确品种，根据内容氛围选择合适的品种
- 描述要包含：品种、毛色、体型、气质等核心特征
- 描述要具体但不过度细节化（不要描述项圈颜色、具体伤疤等）
- 如果有多个主角（如"老大、老二、老三"），需要分别描述每个角色的特征

**示例**：
- 单主角："金毛犬，奶油色毛发，大耳朵垂下，温柔眼神，体型中等偏大"
- 多主角：["老大：橘猫，体型最大，毛色深橘，眼神淡定", "老二：狸花猫，虎斑纹路，体型中等，眼神警惕", "老三：白猫，体型最小，毛色纯白，眼神胆怯"]
"""

    prompt = f"""你是专业的视频分镜师。请为以下文案设计精准的分镜描述。

# 文案内容
{segment_text}
{character_consistency_note}
# 基本信息
- 时长：{duration}秒
- 宠物类型：{pet_label}
- 目标风格：{profile.get("split_style", "温馨治愈日系二维手绘动画")}
- 动态原则：{motion}
- 分镜原则：{shot_guidance}
- 科普原则：{science_guidance}
- 分镜数量参考：约{shot_count}个，根据内容信息密度灵活增减
{niche_rules_block}
# 核心要求（按优先级排序）

## 优先级1：识别并视觉化文案的钩子（最重要！）

**第一步：识别文案的钩子是什么**
- 仔细阅读文案的前1-2句话
- 找出最吸引人的反差、误会、异常行为或悬念
- 例如：你家狗叼着球过来，你一伸手它就跑 → 钩子是叼球来找你但不给你

**第二步：第一个分镜必须直接呈现这个钩子画面**
- 不要从常规动作开始（如主人扔球）
- 直接画出文案里描述的那个吸引人的场景
- 例如：应该画狗叼球凑过来，主人伸手，狗转身跑开，而不是主人扔球

**第三步：后续分镜承接钩子，展开解释**
- 第2-3个分镜可以解释为什么（科普示意）
- 第4-5个分镜展示正确做法或对比
- 最后收束在温馨画面

## 优先级2：准确表达文案的具体内容

- 如果文案说深夜吃狗粮，就要画{pet_label}起身走到狗盆前吃，不能画睡觉
- 如果文案说食物分三档，就要用画面展示三种食物的区别（狗粮、掉地上的、手喂的）
- 如果文案说扔地上吃很快，手喂吃很慢，就要有对比镜头展示速度差异
- 如果文案说出门前摸头、听脚步声，就要画出门和回家的场景

## 优先级3：避免通用模板

- 不要每段都是抬头-摸头-暖光扩散
- 要根据文案的具体情节设计画面
- 每个分镜要有信息变化，不要重复

## 优先级4：镜头语言与转场过渡（重要！）

**镜头类型要求：**
- 每个分镜必须明确指定镜头类型（近景、特写、中景、全景、俯拍、仰拍等）
- 镜头类型要根据内容需求选择，不要固定模式
- 可选镜头类型：近景固定镜头、微距特写镜头、中景横移、中景推进、俯拍镜头、仰拍镜头、主观视角镜头、特写镜头、全景镜头、低角度跟拍等

**转场连贯性要求：**
- 相邻分镜之间要有自然的视觉过渡，避免跳跃感
- 如果前一个分镜是特写，下一个可以是拉远的中景或全景
- 如果前一个分镜是静态固定镜头，下一个可以是横移或推进
- 如果前一个分镜是快速动作，下一个可以是慢速或静态镜头形成节奏对比
- 场景转换时，可以用相似元素（如光线、色调、动作方向）来衔接

**视觉效果与景深转场：**
- 可以使用前景遮挡效果增加画面层次感（如：前景玻璃花瓶柔焦遮挡、前景植物叶片虚化、前景书本边缘虚化）
- 可以使用景深变化作为转场（如：从浅景深特写过渡到深景深全景）
- 可以使用光影变化作为转场（如：从暗部过渡到亮部、从侧光过渡到顶光）
- 可以使用细微视差效果（前景和背景的移动速度差异）
- 注意：前景遮挡物要根据场景自然选择（室内可以是花瓶、书本、杯子；户外可以是树叶、草丛、栏杆），不要固定使用某一种物体

**转场示例：**
- 特写猫咪眼睛 → 拉远到中景猫咪全身 → 全景展示整个房间
- 固定镜头猫咪趴着 → 横移镜头跟随猫咪走动 → 俯拍镜头猫咪跳上沙发
- 快速镜头猫咪奔跑 → 慢速镜头猫咪停下 → 静态镜头猫咪坐下
- 前景花瓶柔焦遮挡，焦点在猫咪 → 拉远全景展示房间 → 俯拍猫咪在地毯上
- 窗边侧光特写 → 中景横移跟随 → 前景窗帘虚化，猫咪在背景

## 优先级5：画面细节要求

- 用动画化的方式表现抽象概念（如等级观念可以用光圈层级、赌可以用期待的眼神）
- 科普内容用温馨的动画符号（气味粒子、情绪云团、光圈等）
- 不要出现任何字幕、中文文字、英文文字、小标签、手写体文字、屏幕文字

## 优先级6：音频要求（重要！）

- **严禁背景音乐**：不要背景音乐、不要配乐、不要BGM，避免每段视频音乐不一致导致合成时衔接不上
- **保留自然音效**：可以有环境音效（脚步声、爪子踩地声、球落地声、布料摩擦声、风声、草地声、室内环境声）
- **保留动物声音**：可以有动物自然声音（猫咪呼噜声、轻微呼吸声、小动物叫声）
- **允许感叹音效**：可以有感叹音效（惊讶声"啊"、轻笑声、叹气声），但不要完整的说话内容
- **口型但无语言**：人物可以有口型动作（如张嘴、微笑），但不要发出清晰的语言声音

## 内化但不输出的规则
- 开头策略：{hook_strategy}
- 前3秒：{first_3s_rule}
- 留存节奏：{retention_structure}
- 画面密度：{density_rule}
- 不要在输出中写爆款开头策略、前3秒视觉钩子等标签，只输出可见画面
- 音频规则：不要背景音乐/配乐/BGM，只保留自然音效和感叹音效

# 输出格式
输出 JSON 格式，包含分镜列表和分镜元素：

{{
  "subject": "本段核心主体（如：金毛叼着球、柴犬甩头拽玩具）",
  "action": "本段核心动作（如：叼球不给主人、甩头邀请拽玩具、放球脚边退后）",
  "scene": "本段核心场景（如：客厅地板、草地、窗边）",
  "main_characters": {main_characters_format},
  "storyboard": [
    "0-2秒：近景固定镜头，[具体画面描述，必须符合文案内容]",
    "2-4秒：中景缓慢推进，[具体画面描述，注意与上一镜的过渡]",
    "4-6秒：特写镜头，[具体画面描述，注意与上一镜的过渡]"
  ]
}}

要求：
- subject/action/scene 必须从文案中提取具体内容，不要用日常互动、温馨客厅这类泛化词
- main_characters: {main_characters_requirement}
- 每个分镜描述必须包含：时间轴 + 镜头类型 + 具体画面内容
- 镜头类型要多样化，不要重复使用同一种镜头
- 相邻分镜之间要考虑转场的自然过渡
- 必须体现文案的核心情节
- 不要输出任何解释或说明
- 只输出 JSON
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

        # 解析 JSON 格式的分镜结果
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                import json
                data = json.loads(json_match.group(0))
                subject = str(data.get("subject") or f"{pet_label}日常互动")
                action = str(data.get("action") or "日常互动")
                scene = str(data.get("scene") or "温馨客厅")
                storyboard_raw = data.get("storyboard") or []

                # 提取主角特征（仅第一段）
                extracted_characters = None
                if is_first_segment:
                    characters_data = data.get("main_characters")
                    if characters_data:
                        if isinstance(characters_data, list):
                            extracted_characters = characters_data
                        elif isinstance(characters_data, str):
                            extracted_characters = [characters_data]
                        print(f"  ✓ 提取到主角特征：{extracted_characters}")
            else:
                # 兜底：如果不是 JSON，按原来的行解析
                subject = f"{pet_label}日常互动"
                action = "日常互动"
                scene = "温馨客厅"
                storyboard_raw = [line.strip() for line in text.strip().split('\n') if line.strip()]
                extracted_characters = None
        except (json.JSONDecodeError, AttributeError):
            # JSON 解析失败，按原来的行解析
            subject = f"{pet_label}日常互动"
            action = "日常互动"
            scene = "温馨客厅"
            storyboard_raw = [line.strip() for line in text.strip().split('\n') if line.strip()]
            extracted_characters = None

        # 清理分镜列表
        storyboard = []
        for line in storyboard_raw:
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^\s*[-*•]?\s*\d+[\.、)]\s*", "", line)
            storyboard.append(line)

        if storyboard:
            return storyboard, subject, action, scene, extracted_characters
        else:
            return ([f"0-{duration}秒：{pet_label}日常互动，温馨场景"], f"{pet_label}", "日常互动", "温馨客厅", extracted_characters)

    except Exception as exc:
        print(f"⚠️ AI 生成分镜失败，使用默认分镜：{exc}")
        # 降级方案：返回基础分镜和默认元素
        return (
            [
                f"0-{max(2, min(duration, 2))}秒：{pet_label}在温馨客厅中的日常场景",
                f"{max(2, min(duration, 2))}-{duration}秒：主人与{pet_label}的温馨互动",
            ],
            f"{pet_label}",
            "日常互动",
            "温馨客厅",
            None  # 失败时没有主角特征
        )


def generate_video_prompts(
    segments: List[Dict],
    full_context: str,
    channel_id: Optional[str] = None,
    scene_continuity: bool = True,
    provider_id: Optional[str] = None,
    niche: str = "",
) -> List[Dict]:
    """
    为每个段落生成视频提示词

    Args:
        segments: 分段结果列表（来自 text_segmenter）
        full_context: 完整文案（用于理解上下文）
        channel_id: 频道ID（用于获取频道风格）
        scene_continuity: 是否保持场景连贯性
        provider_id: AI Provider ID
        niche: 赛道

    Returns:
        每个段落的提示词配置列表
    """
    if not segments:
        return []

    # 检测宠物上下文（用于风格模板）
    pet_context = detect_pet_context(full_context)

    prompts = []

    # 主角特征注册表：从第一段提取，后续段落复用
    main_characters = None

    print(f"\n🎬 开始生成 {len(segments)} 个段落的视频提示词...")

    # 为每个段落生成提示词
    for i, seg in enumerate(segments, 1):
        is_first_segment = (i == 1)
        print(f"  [{i}/{len(segments)}] 正在为段落 {seg['index']} 生成分镜...")

        # 分析关键词
        keywords = analyze_keywords(seg["text"], pet_context)

        # 强制限制 duration 在 4-15 秒范围内（视频模型限制）
        safe_duration = max(4, min(15, int(seg["estimated_duration"])))

        # 使用 AI 生成定制化分镜（理解文案内容）
        storyboard, subject, action, scene, extracted_characters = _call_claude_for_storyboard(
            segment_text=seg["text"],
            duration=safe_duration,
            pet_context=pet_context,
            channel_id=channel_id,
            provider_id=provider_id,
            niche=niche,
            main_characters=main_characters,
            is_first_segment=is_first_segment,
        )

        # 如果是第一段且提取到了主角特征，保存下来
        if is_first_segment and extracted_characters:
            main_characters = extracted_characters
            print(f"  ✓ 主角特征已确定，将在后续 {len(segments) - 1} 个段落中保持一致")
        elif is_first_segment and not extracted_characters:
            # 第一段没有提取到主角特征，使用兜底方案
            if pet_context.get("breed_detected"):
                # 如果检测到了品种，使用品种描述
                main_characters = [pet_context["subject_style"]]
                print(f"  ⚠️ AI未返回主角特征，使用检测到的品种：{main_characters}")
            else:
                # 使用默认描述
                main_characters = [f"{pet_context['pet_label']}，具体特征由视频模型自然生成"]
                print(f"  ⚠️ AI未返回主角特征，使用默认描述")

        print(f"    ✓ 生成了 {len(storyboard)} 个分镜")

        # 构建 SeedanceSegment 对象（使用安全的 duration）
        seedance_seg = SeedanceSegment(
            index=seg["index"],
            duration=safe_duration,
            transcript=seg["text"],
            function=f"段落{seg['index']}",
            main_action=action,  # 使用 AI 提取的动作
            emotion=keywords.get("emotions", ["温馨"])[0] if keywords.get("emotions") else "温馨",
            scene=scene,  # 使用 AI 提取的场景
            storyboard=storyboard,
            prompt="",  # 将由 build_prompt_for_segment 生成
        )

        # 使用 Seedance 的提示词生成逻辑（传入主角特征）
        prompt_text = build_prompt_for_segment(
            segment=seedance_seg,
            pet_context=pet_context,
            material_refs=None,
            channel_id=channel_id,
            main_characters=main_characters,  # 传入主角特征
        )

        prompts.append({
            "segment_index": seg["index"],
            "segment_text": seg["text"],
            "start_time": seg["start_time"],
            "end_time": seg["end_time"],
            "duration": safe_duration,  # 使用安全的 duration
            "prompt": prompt_text,
            "shot": "",  # Seedance 提示词已包含镜头信息
            "subject": subject,  # 使用 AI 提取的主体
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
