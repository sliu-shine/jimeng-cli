"""
Seedance 2.0 prompt builder for cat/dog light-science animation videos.

This module is intentionally template-driven so the account style is stable
across generations and does not depend on chat memory.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass

from scripts.claude_client import ClaudeClient


FIXED_STYLE_TEMPLATE = (
    "温馨治愈日系二维手绘动画画风，吉卜力式温暖动画质感，宫崎骏动画电影般的柔和氛围，"
    "非真实摄影，非写实视频，非3D，非半写实；画面为纯二维手绘动画质感，线条柔和流畅，"
    "无尖锐棱角，色彩饱和度适中偏暖，暖黄色与浅橙色自然柔光，画面干净通透，背景简洁耐看，"
    "光影柔和，有温暖家庭陪伴感和轻电影感。核心主体为{subject_style}，"
    "{pet_label}毛发蓬松柔软、根根分明，脸部表情拟人化但不过度夸张，眼睛大而明亮有神，动作自然，"
    "情绪灵动，造型可爱治愈，全程角色造型稳定统一。场景为生活化二维动画场景，可以是温暖客厅、"
    "卧室、沙发边、阳光草地、公园、家庭地板、窗边等，所有场景都保持同一套温暖日系手绘动画质感。"
    "科普示意画面也必须保持同一治愈动画风格，微生物、DNA、大脑结构、多巴胺、气味粒子、情绪云团等"
    "都要画成柔和、干净、温暖、易懂的动画化示意，不要冷冰冰科技风，不要真实医学图，不要恐怖微观画面。"
)

QUALITY_REQUIREMENTS = (
    "适配即梦 Seedance 2.0，全能参考入口文生视频模式，16:9 横屏，物理规律合理，动作表现自然流畅，"
    "镜头衔接连贯顺滑，指令理解精准，画面风格全程稳定统一，角色造型细节全程一致无跳变，"
    "猫狗动作自然不僵硬，猫狗微表情生动，情绪演绎精准到位，科普示意画面清晰易懂，"
    "故事画面与科普插帧自然衔接，光影质感自然，画面细节清晰丰富，无画面崩坏，无逻辑错误，"
    "无角色变形，无画风漂移。"
)

NEGATIVE_CONSTRAINTS = (
    "屏幕上不要出现任何字幕、中文文字、英文文字、水印、logo、账号名、标题贴纸。"
    "不要生成旁白、配音、人声朗读，不要生成突兀音乐，优先保留自然温柔的环境音效。"
    "禁止真实摄影、写实真人脸部、3D建模感、半写实人物、欧美美漫风、低幼Q版夸张卡通，"
    "禁止画面过暗，整体亮度中等偏亮，保持温暖、清晰、干净。"
)


BEHAVIOR_KEYWORDS = {
    "睡": "{pet_label}熟睡、胸口轻轻起伏、耳朵偶尔微动",
    "闻": "{pet_label}靠近主人衣角轻轻闻嗅，鼻尖微动",
    "舔": "{pet_label}低头轻舔爪子或轻轻舔主人手背",
    "摇尾巴": "{pet_label}尾巴轻轻摇动，身体放松靠近主人",
    "尾巴": "{pet_label}尾巴自然轻摆，露出放松的小动作",
    "靠": "{pet_label}把身体贴近主人腿边，缓慢蹭蹭",
    "蹭": "{pet_label}用脸颊或身体轻轻蹭主人，动作亲密自然",
    "踩奶": "猫咪在柔软毯子上轻轻踩奶，爪子一伸一缩",
    "呼噜": "猫咪眯着眼发出轻柔呼噜，身体完全放松",
    "看": "{pet_label}抬头看向主人，眼睛明亮，轻轻眨眼",
    "叫": "{pet_label}轻声回应主人，表情柔软",
    "喵": "猫咪轻轻喵叫回应，耳朵微动，眼神柔软",
    "汪": "狗狗轻声汪叫回应，尾巴轻摆，表情柔软",
    "趴": "{pet_label}趴在温暖地板或沙发边，身体完全放松",
}

EMOTION_KEYWORDS = {
    "误会": "主人先露出疑惑表情，随后被{pet_label}的小动作温柔打动",
    "爱": "主人和{pet_label}对视，周围出现温柔心跳光圈但不夸张",
    "焦虑": "主人胸口或脑海里的灰色小云团被{pet_label}身上的暖光慢慢融化",
    "压力": "灰色压力云团从主人肩膀散开，空气变得柔软明亮",
    "治愈": "暖黄色光点在主人和{pet_label}之间缓慢扩散",
    "安全感": "{pet_label}身边形成柔软暖光保护圈，主人表情逐渐放松",
    "陪伴": "主人坐在地板边，{pet_label}安静贴着主人，画面平稳温暖",
}

SCIENCE_KEYWORDS = {
    "微生物": "{pet_label}毛发表面出现温柔微观世界，小小发光微生物像暖色小精灵一样在毛发间活动",
    "菌群": "毛发间浮现柔和微生物群落，发出细小暖光",
    "代谢": "微生物释放柔和光点，气味粒子缓慢流向空气",
    "气味": "暖黄色香气粒子从{pet_label}毛发间飘起，轻轻环绕主人",
    "爆米花": "香气粒子幻化成小小爆米花意象，保持二维手绘质感",
    "烤面包": "香气粒子幻化成小麦和烤面包的温柔意象",
    "体温": "{pet_label}熟睡时身体周围出现柔和暖光和轻微热气",
    "毛孔": "{pet_label}毛发近景，毛孔微微张开，毛发自然蓬松被暖光照亮",
    "DNA": "温柔发光的DNA双螺旋示意浮现，线条柔和，颜色温暖",
    "大脑": "{pet_label}头部旁边出现半透明大脑结构示意，线条柔和干净",
    "多巴胺": "大脑里金色小光点跳动扩散，形成温暖愉悦的视觉隐喻",
    "狼": "远古草地上温顺的狼远远看着人类营地篝火和食物残渣",
    "野猫": "温柔动画化的远古野猫在谷仓和人类居住地边缘观察食物与安全环境",
    "祖先": "温柔远古场景中，猫狗祖先靠近人类生活区，画面像绘本一样柔和",
    "嗅觉": "{pet_label}鼻尖微距特写，柔和气味粒子形成清晰路径",
    "听觉": "{pet_label}耳朵轻轻转动，空气中出现柔和声波线条",
}


@dataclass
class SeedanceSegment:
    index: int
    duration: int
    transcript: str
    function: str
    main_action: str
    emotion: str
    scene: str
    storyboard: list[str]
    prompt: str
    source: str = "rule"


def detect_pet_context(text: str) -> dict[str, str]:
    clean = str(text or "")
    cat_score = sum(clean.count(word) for word in ["猫", "猫咪", "小猫", "狸花", "橘猫", "布偶", "英短", "喵", "呼噜", "踩奶", "猫砂"])
    dog_score = sum(clean.count(word) for word in ["狗", "狗狗", "小狗", "金毛", "柯基", "柴犬", "拉布拉多", "汪", "摇尾巴", "护卫犬"])
    if cat_score > dog_score:
        return {
            "kind": "cat",
            "pet_label": "猫咪",
            "subject_style": "可爱的猫咪或逐字稿指定猫咪，胡须细腻、耳朵灵动、尾巴动作自然",
            "love_phrase": "像在重新理解猫咪的爱",
            "strategy_label": "猫咪行为主线",
        }
    if dog_score > cat_score:
        return {
            "kind": "dog",
            "pet_label": "狗狗",
            "subject_style": "可爱的金毛犬或逐字稿指定狗狗，耳朵灵动、尾巴动作自然",
            "love_phrase": "像在重新理解狗狗的爱",
            "strategy_label": "狗狗行为主线",
        }
    return {
        "kind": "pet",
        "pet_label": "猫咪或狗狗",
        "subject_style": "可爱的猫咪或狗狗，优先遵循逐字稿指定宠物，耳朵灵动、动作自然",
        "love_phrase": "像在重新理解毛孩子的爱",
        "strategy_label": "猫狗行为主线",
    }


def _render_template(text: str, pet_context: dict[str, str]) -> str:
    return text.format(**pet_context)


def fixed_style_for_pet(pet_context: dict[str, str]) -> str:
    return _render_template(FIXED_STYLE_TEMPLATE, pet_context)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _json_from_model_text(text: str) -> dict:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        blocks = clean.split("```")
        clean = blocks[1] if len(blocks) > 1 else clean
        if clean.lstrip().startswith("json"):
            clean = clean.lstrip()[4:]
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        clean = clean[start:end + 1]
    return json.loads(clean)


def _call_ai_splitter(prompt: str) -> dict:
    client = ClaudeClient()
    result = client.create_message(
        model=os.getenv("SEEDANCE_SPLIT_MODEL", os.getenv("ANTHROPIC_MODEL", client.model)),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=int(os.getenv("SEEDANCE_SPLIT_MAX_TOKENS", "8000")),
        temperature=float(os.getenv("SEEDANCE_SPLIT_TEMPERATURE", "0.4")),
    )
    return _json_from_model_text(result["content"][0]["text"])


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?])", _normalize_text(text))
    return [part.strip() for part in parts if part.strip()]


def _estimate_seconds(text: str) -> int:
    compact = re.sub(r"\s+", "", text)
    return max(4, math.ceil(len(compact) / 4.2))


def split_transcript_for_seedance(transcript: str) -> list[tuple[int, str]]:
    sentences = _split_sentences(transcript)
    if not sentences:
        return []

    segments: list[tuple[int, str]] = []
    current: list[str] = []
    current_seconds = 0

    for sentence in sentences:
        sentence_seconds = min(15, max(4, _estimate_seconds(sentence)))
        if current and current_seconds + sentence_seconds > 15:
            segments.append((max(4, min(15, current_seconds)), "".join(current)))
            current = [sentence]
            current_seconds = sentence_seconds
        else:
            current.append(sentence)
            current_seconds += sentence_seconds

    if current:
        duration = max(4, min(15, current_seconds))
        segments.append((duration, "".join(current)))

    return segments


def _matched_values(text: str, mapping: dict[str, str], pet_context: dict[str, str]) -> list[str]:
    values = []
    for keyword, value in mapping.items():
        rendered = _render_template(value, pet_context)
        if keyword in text and rendered not in values:
            values.append(rendered)
    return values


def analyze_keywords(text: str, pet_context: dict[str, str] | None = None) -> dict[str, list[str]]:
    pet_context = pet_context or detect_pet_context(text)
    return {
        "behaviors": _matched_values(text, BEHAVIOR_KEYWORDS, pet_context),
        "emotions": _matched_values(text, EMOTION_KEYWORDS, pet_context),
        "science": _matched_values(text, SCIENCE_KEYWORDS, pet_context),
    }


def _segment_function(index: int, total: int, keywords: dict[str, list[str]], pet_context: dict[str, str]) -> str:
    pet_label = pet_context["pet_label"]
    if index == 1:
        return f"开头强钩子，建立{pet_label}行为误会与治愈期待"
    if index == total:
        return f"情绪收束与行动建议，强化主人和{pet_label}的陪伴关系"
    if keywords["science"]:
        return "轻科普解释段，用治愈动画插帧解释行为背后的原因"
    return f"故事推进段，用{pet_label}行为和主人反应承接情绪共鸣"


def _scene_for_segment(text: str) -> str:
    if any(word in text for word in ["睡", "床", "卧室"]):
        return "暖黄色卧室和床边地毯"
    if any(word in text for word in ["草地", "公园", "狼", "远古"]):
        return "阳光草地或温柔远古营地"
    if any(word in text for word in ["沙发", "客厅", "家里", "主人"]):
        return "温暖客厅、沙发边和家庭地板"
    return "温暖客厅与窗边阳光区域"


def _main_action(text: str, keywords: dict[str, list[str]], pet_context: dict[str, str]) -> str:
    if keywords["behaviors"]:
        return keywords["behaviors"][0]
    pet_label = pet_context["pet_label"]
    if "主人" in text:
        return f"{pet_label}围绕主人做出自然小动作，抬头、眨眼、耳朵微动、尾巴轻摆或轻轻贴近"
    return f"{pet_label}在温暖家庭场景中自然活动，靠近、闻嗅、抬头、贴贴"


def _main_emotion(text: str, keywords: dict[str, list[str]], pet_context: dict[str, str]) -> str:
    if keywords["emotions"]:
        return keywords["emotions"][0]
    if any(word in text for word in ["不是", "其实", "原来"]):
        return "从误会到理解的温柔释然"
    return f"温馨、治愈、轻科普、被{pet_context['pet_label']}爱着的安心感"


def _shot_count(duration: int) -> int:
    if duration <= 5:
        return 3
    if duration <= 10:
        return 5
    return 8


def _shot_visuals(text: str, keywords: dict[str, list[str]], pet_context: dict[str, str]) -> list[str]:
    visuals = []
    visuals.extend(keywords["behaviors"])
    visuals.extend(keywords["science"])
    visuals.extend(keywords["emotions"])
    if not visuals:
        pet_label = pet_context["pet_label"]
        visuals = [
            f"{pet_label}抬头看向主人，眼睛明亮，轻轻眨眼",
            f"主人蹲下伸手轻摸{pet_label}头顶，表情逐渐放松",
            f"暖黄色光点在主人和{pet_label}之间缓慢扩散，空气变得柔软",
        ]
    return visuals


def build_storyboard(duration: int, text: str, keywords: dict[str, list[str]], pet_context: dict[str, str]) -> list[str]:
    count = _shot_count(duration)
    visuals = _shot_visuals(text, keywords, pet_context)
    shots = []
    ranges = []
    start = 0
    for i in range(count):
        end = duration if i == count - 1 else min(duration, start + 2)
        ranges.append((start, end))
        start = end
        if start >= duration:
            break

    shot_styles = [
        "近景固定镜头",
        "微距特写镜头，缓慢推近",
        "科普示意镜头，柔和转场",
        "中景轻微横移",
        "俯拍镜头，缓慢下移",
        "主观视角镜头，轻微跟拍",
        "特写镜头，柔和拉近",
        "全景镜头，慢慢拉远",
    ]
    for idx, (start, end) in enumerate(ranges):
        visual = visuals[idx % len(visuals)]
        if idx == 0 and "误会" not in visual:
            visual = f"主人先露出轻微疑惑，随后看见{visual}"
        if idx == len(ranges) - 1:
            visual = f"{visual}，画面收束在主人与{pet_context['pet_label']}安静陪伴的温暖瞬间"
        shots.append(f"{start}-{end}秒：{shot_styles[idx % len(shot_styles)]}，{visual}，对应逐字稿画面关键词“{_keyword_excerpt(text)}”。")
    return shots


def _keyword_excerpt(text: str) -> str:
    text = _normalize_text(text)
    if len(text) <= 26:
        return text
    for mark in ["，", "。", "；", "、"]:
        first = text.split(mark, 1)[0].strip()
        if 6 <= len(first) <= 26:
            return first
    return text[:26]


def _ensure_sentence_end(text: str) -> str:
    clean = str(text or "").strip()
    if not clean:
        return ""
    return clean if re.search(r"[。！？!?；;.]$", clean) else clean + "。"


def _material_instruction(material_refs: dict[str, str] | None) -> str:
    if not material_refs:
        return ""
    lines = []
    for name, purpose in material_refs.items():
        clean_name = str(name).strip()
        clean_purpose = str(purpose).strip()
        if clean_name and clean_purpose:
            lines.append(f"{clean_name} 作为{clean_purpose}")
    if not lines:
        return ""
    return "参考素材用途：" + "；".join(lines) + "。"


def build_prompt_for_segment(
    segment: SeedanceSegment,
    pet_context: dict[str, str],
    material_refs: dict[str, str] | None = None,
) -> str:
    material_text = _material_instruction(material_refs)
    storyboard_text = " ".join(_ensure_sentence_end(item) for item in segment.storyboard if str(item).strip())
    return (
        f"{fixed_style_for_pet(pet_context)} 16:9 横屏。{material_text}"
        f"本段主场景：{segment.scene}。本段{pet_context['pet_label']}和主人状态：{segment.main_action}，{segment.emotion}。"
        f"本段按时间轴分镜：{storyboard_text} "
        f"主情绪氛围：温馨治愈、轻科普、{pet_context['love_phrase']}。"
        f"{QUALITY_REQUIREMENTS}{NEGATIVE_CONSTRAINTS}"
    )


def _ai_split_prompt(transcript: str, pet_context: dict[str, str]) -> str:
    return f"""你是抖音猫狗治愈动画轻科普账号的分镜导演。请把逐字稿拆成适配即梦 Seedance 2.0 的文生视频任务段，并输出严格 JSON。

主体识别：{pet_context['pet_label']}
目标风格：温馨治愈日系二维手绘动画，猫狗行为故事主线 + 科普示意插帧 + 情绪隐喻镜头。

硬性规则：
1. 每段 duration 必须是 4-15 的整数，优先 15 秒，最后一段可以 4-14 秒，不要为了凑满 15 秒加无效画面。
2. 每段平均约 2 秒一个分镜。15 秒通常 7-8 个分镜，10 秒通常 5 个分镜，5 秒通常 2-3 个分镜。
3. 每个分镜必须写清时间轴、景别、运镜、画面动作、对应逐字稿画面关键词，但不要要求画面生成旁白或字幕。
4. 必须主动识别逐字稿里的猫狗行为关键词、情绪关键词、轻科普关键词，并安排对应画面。
5. 科普词出现时必须有动画化科普示意，不能只拍猫狗坐着或发呆。
6. 主人不能抢戏，猫狗永远是核心主体；人物只能是柔和二维动画人物，避免写实真人脸部。
7. 不要输出固定画风、负面约束和质量词，这些由程序统一注入。
8. 只输出 JSON，不要 Markdown，不要解释。

JSON 格式：
{{
  "segments": [
    {{
      "duration": 15,
      "transcript": "本段对应的逐字稿原文范围，短句即可",
      "function": "本段功能定位",
      "main_action": "本段核心猫狗动作",
      "emotion": "本段核心情绪",
      "scene": "本段核心场景",
      "storyboard": [
        "0-2秒：近景固定镜头，画面动作，对应逐字稿画面关键词“...”",
        "2-4秒：微距特写镜头，画面动作，对应逐字稿画面关键词“...”"
      ]
    }}
  ]
}}

逐字稿：
{transcript}
"""


def _coerce_duration(value: object) -> int:
    try:
        duration = int(float(str(value).replace("秒", "").strip()))
    except (TypeError, ValueError):
        duration = 15
    return max(4, min(15, duration))


def _segments_from_ai_plan(plan: dict, transcript: str, pet_context: dict[str, str], material_refs: dict[str, str] | None) -> list[SeedanceSegment]:
    raw_segments = plan.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("AI拆分结果缺少 segments")

    segments: list[SeedanceSegment] = []
    for index, raw in enumerate(raw_segments, 1):
        if not isinstance(raw, dict):
            raise ValueError("AI拆分段格式无效")
        duration = _coerce_duration(raw.get("duration"))
        text = _normalize_text(raw.get("transcript") or "")
        if not text:
            text = _keyword_excerpt(transcript)
        storyboard = raw.get("storyboard")
        if not isinstance(storyboard, list):
            storyboard = []
        storyboard = [_ensure_sentence_end(item) for item in storyboard if str(item).strip()]
        if not storyboard:
            keywords = analyze_keywords(text, pet_context)
            storyboard = build_storyboard(duration, text, keywords, pet_context)

        keywords = analyze_keywords(text, pet_context)
        segment = SeedanceSegment(
            index=index,
            duration=duration,
            transcript=text,
            function=str(raw.get("function") or _segment_function(index, len(raw_segments), keywords, pet_context)).strip(),
            main_action=str(raw.get("main_action") or _main_action(text, keywords, pet_context)).strip(),
            emotion=str(raw.get("emotion") or _main_emotion(text, keywords, pet_context)).strip(),
            scene=str(raw.get("scene") or _scene_for_segment(text)).strip(),
            storyboard=storyboard,
            prompt="",
            source="ai",
        )
        segment.prompt = build_prompt_for_segment(segment, pet_context, material_refs)
        segments.append(segment)
    return segments


def build_seedance_segments_rule(transcript: str, material_refs: dict[str, str] | None = None) -> list[SeedanceSegment]:
    raw_segments = split_transcript_for_seedance(transcript)
    total = len(raw_segments)
    pet_context = detect_pet_context(transcript)
    segments: list[SeedanceSegment] = []
    for idx, (duration, text) in enumerate(raw_segments, 1):
        keywords = analyze_keywords(text, pet_context)
        storyboard = build_storyboard(duration, text, keywords, pet_context)
        segment = SeedanceSegment(
            index=idx,
            duration=duration,
            transcript=text,
            function=_segment_function(idx, total, keywords, pet_context),
            main_action=_main_action(text, keywords, pet_context),
            emotion=_main_emotion(text, keywords, pet_context),
            scene=_scene_for_segment(text),
            storyboard=storyboard,
            prompt="",
        )
        segment.prompt = build_prompt_for_segment(segment, pet_context, material_refs)
        segments.append(segment)
    return segments


def build_seedance_segments(
    transcript: str,
    material_refs: dict[str, str] | None = None,
    use_ai: bool = True,
) -> list[SeedanceSegment]:
    pet_context = detect_pet_context(transcript)
    if use_ai and os.getenv("ANTHROPIC_API_KEY"):
        try:
            plan = _call_ai_splitter(_ai_split_prompt(transcript, pet_context))
            return _segments_from_ai_plan(plan, transcript, pet_context, material_refs)
        except Exception as exc:
            print(f"⚠️ Seedance AI 拆分失败，回退规则拆分: {exc}")
    return build_seedance_segments_rule(transcript, material_refs=material_refs)


def format_seedance_markdown(transcript: str, segments: list[SeedanceSegment]) -> str:
    if not segments:
        return "请先载入或粘贴一段逐字稿。"
    split_way = " + ".join(f"{segment.duration}秒" for segment in segments)
    pet_context = detect_pet_context(transcript)
    all_keywords = analyze_keywords(transcript, pet_context)
    visual_parts = []
    if all_keywords["behaviors"]:
        visual_parts.append(pet_context["strategy_label"])
    if all_keywords["science"]:
        visual_parts.append("科普示意插帧")
    visual_parts.append("情绪隐喻镜头")
    lines = [
        "## 对应逐字稿的 Seedance 2.0 文生视频提示词",
        "",
        "### 逐字稿整体拆分说明",
        f"总体拆分逻辑：{'AI模型导演拆分' if any(segment.source == 'ai' for segment in segments) else '规则兜底拆分'}，按口播信息密度优先拆成15秒以内任务段，保证每段平均约2秒一个镜头重点。",
        f"预计任务段数量：{len(segments)}段",
        f"拆分方式：{split_way}",
        f"核心视觉策略：{' + '.join(visual_parts)}",
    ]
    for segment in segments:
        lines.extend([
            "",
            f"### 功能段{segment.index}：{segment.function}",
            f"对应逐字稿范围：{_keyword_excerpt(segment.transcript)}",
            f"主动作：{segment.main_action}",
            f"主情绪：{segment.emotion}",
            f"主场景：{segment.scene}",
            f"生成时长：{segment.duration}秒",
            "分镜规划：",
            *segment.storyboard,
            f"Seedance 2.0 全能参考文生视频 Prompt：{segment.prompt}",
        ])
    return "\n\n".join(lines)


def build_seedance_queue_document(
    segments: list[SeedanceSegment],
    multimodal: bool = False,
    model_version: str = "seedance2.0fast",
) -> str:
    queue_segments = []
    for segment in segments:
        queue_segments.append({
            "id": f"seedance-segment-{segment.index:02d}",
            "name": f"Seedance动画片段{segment.index:02d}",
            "mode": "multimodal2video" if multimodal else "text2video",
            "prompt": segment.prompt,
            "images": [],
            "videos": [],
            "audios": [],
            "transition_prompts": [],
            "duration": str(segment.duration),
            "ratio": "16:9",
            "model_version": model_version or "seedance2.0fast",
        })
    return json.dumps({"version": 1, "segments": queue_segments}, ensure_ascii=False, indent=2)


def build_seedance_outputs(
    transcript: str,
    material_refs: dict[str, str] | None = None,
    use_ai: bool = True,
    model_version: str = "seedance2.0fast",
) -> tuple[str, str]:
    segments = build_seedance_segments(transcript, material_refs=material_refs, use_ai=use_ai)
    markdown = format_seedance_markdown(transcript, segments)
    queue_json = build_seedance_queue_document(segments, multimodal=bool(material_refs), model_version=model_version)
    return markdown, queue_json
