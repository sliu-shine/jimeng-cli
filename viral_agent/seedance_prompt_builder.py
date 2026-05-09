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
from pathlib import Path

from scripts.claude_client import ClaudeClient


PROMPT_CONFIG_PATH = Path(__file__).parent / "prompts" / "seedance_profiles.json"


def _load_prompt_config() -> dict:
    if not PROMPT_CONFIG_PATH.exists():
        return {}
    try:
        with open(PROMPT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


PROMPT_CONFIG = _load_prompt_config()


# 默认画风模板（向后兼容）
FIXED_STYLE_TEMPLATE = (
    "温暖日系二维手绘动画风格，柔和电影感，自然水彩背景，治愈家庭氛围，"
    "非真实摄影，非写实视频，非3D，非半写实；画面为纯二维手绘动画质感，线条柔和流畅，"
    "无尖锐棱角，色彩饱和度适中偏暖，暖黄色与浅橙色自然柔光，画面干净通透，背景简洁耐看，"
    "光影柔和，有温暖家庭陪伴感。核心主体为{subject_style}，"
    "{pet_label}毛发蓬松柔软、层次清楚，脸部表情拟人化但不过度夸张，眼睛明亮有神，动作自然，"
    "情绪灵动，造型可爱治愈，全程角色造型稳定统一。场景为生活化二维动画场景，可以是温暖客厅、"
    "卧室、沙发边、阳光草地、公园、家庭地板、窗边等，所有场景都保持同一套温暖日系手绘动画质感。"
    "科普示意画面只在分镜明确需要时出现，必须保持同一治愈动画风格，气味粒子、信任光圈、脆弱部位示意、"
    "情绪云团等都要画成柔和、干净、温暖、易懂的动画化示意，不要冷冰冰科技风，不要真实医学图，不要恐怖微观画面。"
)
FIXED_STYLE_TEMPLATE = str(PROMPT_CONFIG.get("default_style_template") or FIXED_STYLE_TEMPLATE)


def _load_channel_styles() -> dict:
    """加载频道画风配置"""
    config_path = Path(__file__).parent.parent / ".webui" / "channel_styles.json"
    if not config_path.exists():
        return {"version": 1, "channels": [], "default_channel": None}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "channels": [], "default_channel": None}


def get_channel_choices() -> list[tuple[str, str]]:
    """获取频道选择列表，返回 (显示名称, channel_id)"""
    config = _load_channel_styles()
    channels = config.get("channels", [])
    choices = []
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if not channel.get("enabled", True):
            continue
        channel_id = str(channel.get("id", ""))
        name = str(channel.get("name", channel_id))
        if channel_id:
            choices.append((name, channel_id))
    return choices


def get_default_channel_id() -> str | None:
    """获取默认频道ID"""
    config = _load_channel_styles()
    return config.get("default_channel")


def get_channel_style(channel_id: str | None) -> str:
    """
    获取频道的视觉风格描述

    Args:
        channel_id: 频道ID

    Returns:
        视觉风格描述字符串
    """
    if not channel_id:
        return "清晰日漫动画风格，16:9，电影级画面"

    config = _load_channel_styles()
    channels = config.get("channels", [])

    for channel in channels:
        if isinstance(channel, dict) and str(channel.get("id")) == str(channel_id):
            style = channel.get("style_description", "")
            if style:
                return style
            # 如果没有 style_description，尝试从 split_style 构建
            split_style = channel.get("split_style", "")
            if split_style:
                return f"{split_style}，16:9，电影级画面"

    # 如果找不到频道，返回默认风格
    return "清晰日漫动画风格，16:9，电影级画面"


GLOBAL_QUALITY_REQUIREMENTS = str(PROMPT_CONFIG.get("global", {}).get("quality_requirements") or (
    "适配即梦 Seedance 2.0，全能参考入口文生视频模式，16:9 横屏，指令理解精准，"
    "画面风格全程稳定统一，角色造型细节全程一致无跳变，科普示意画面清晰易懂，"
    "无画面崩坏，无逻辑错误，无角色变形，无画风漂移。"
))

NO_DIALOGUE_CONSTRAINTS = str(PROMPT_CONFIG.get("global", {}).get("no_dialogue_constraints") or (
    "画面内容按纯视觉设计，全程不要人声朗读、不要人物聊天声、不要口型讲话、不要宠物拟人说话；"
    "人物和猫狗通过表情、动作和画面氛围表达情绪，嘴巴保持自然闭合或呼吸状态。"
))

GLOBAL_NEGATIVE_CONSTRAINTS = str(PROMPT_CONFIG.get("global", {}).get("negative_constraints") or (
    "屏幕上不要出现任何字幕、中文文字、英文文字、水印、logo、账号名、标题贴纸。"
    "不要真实摄影、不要写实真人脸部、不要3D建模感、不要水印、不要低清晰度画面。"
))


CHANNEL_PROMPT_PROFILES = {
    "channel-healing": {
        "split_style": "温馨治愈日系二维手绘动画，猫狗行为故事主线 + 科普示意插帧 + 情绪隐喻镜头",
        "motion": (
            "本频道按剧情式二维手绘动画处理，动作自然流畅，镜头衔接顺滑，猫狗微表情生动，"
            "主人和宠物有清晰但不过度夸张的互动，整体亮度中等偏亮，保持温暖、清晰、干净。"
        ),
        "shot_guidance": "每段平均约2秒一个分镜。15秒通常7-8个分镜，10秒通常5个分镜，5秒通常2-3个分镜。",
        "science_guidance": "科普词出现时必须有动画化科普示意，不能只拍猫狗坐着或发呆。",
        "shot_counts": (3, 5, 8),
        "shot_styles": [
            "近景固定镜头",
            "微距特写镜头，缓慢推近",
            "科普示意镜头，柔和转场",
            "中景轻微横移",
            "俯拍镜头，缓慢下移",
            "主观视角镜头，轻微跟拍",
            "特写镜头，柔和拉近",
            "全景镜头，慢慢拉远",
        ],
    },
    "channel-science": {
        "split_style": "明亮透明水彩绘本插画轻动态，猫狗日常生活切片 + 纸面手绘科普小图示",
        "motion": (
            "本频道不是剧情动画片段，而是透明水彩插画轻动态；动作幅度小，画面像手绘插画缓慢呼吸，"
            "以慢速横移、轻微推近、细微视差、前景玻璃花瓶或书本柔焦遮挡为主，避免频繁切镜和强剧情动画表演。"
        ),
        "shot_guidance": "每段不要频繁切镜。15秒通常3-5个画面重点，10秒通常3个画面重点，5秒通常2个画面重点。",
        "science_guidance": "科普内容用浅色半透明手绘图示表现，像画在纸上的水彩小插图，不要发光特效和科技感。",
        "shot_counts": (2, 3, 5),
        "shot_styles": [
            "窗边中景慢速横移",
            "前景玻璃花瓶柔焦遮挡，细微视差",
            "纸面手绘科普小图示，轻轻浮现",
            "桌面近景轻微推近",
            "固定镜头，角色和花叶只有细小动作",
        ],
    },
    "channel-funny": {
        "split_style": "日系二次元AI厚涂动态插画，冷淡厌世女仆系角色气质 + 宠物反差萌表现 + 科普装饰图示",
        "motion": (
            "本频道按二次元AI厚涂动态插画处理，整体有柔雾感、厚涂渐变和轻微低清短视频质感；"
            "动态只作为插画轻度动态化，主要通过半闭眼眨动、轻微表情变化、头部细动、衣发轻摆、宠物姿态变化和镜头轻微推进完成，"
            "不固定具体场景和动作，不依赖复杂逐帧动画，避免高清动漫电影截图感和过度温柔治愈感。"
        ),
        "shot_guidance": "每段使用角色向轻动态画面。15秒通常4-6个画面重点，10秒通常4个画面重点，5秒通常2个画面重点。",
        "science_guidance": "科普示意保持二次元厚涂装饰图示风格，可爱、清晰、易懂，不要真实医学图，不要科技感过重。",
        "shot_counts": (2, 4, 6),
        "shot_styles": [
            "角色向镜头轻微推近",
            "宠物反差萌特写，轻微眨眼或转头",
            "二次元厚涂科普装饰图示，轻轻浮现",
            "中景固定镜头，衣发和宠物只有细小动作",
            "冷淡无语表情反应特写，轻微拉近",
            "按内容自然选择的场景轻微横移",
        ],
    },
}


DEFAULT_PROMPT_PROFILE = {
    "split_style": "猫狗治愈动画，行为故事主线 + 科普示意插帧 + 情绪隐喻镜头",
    "motion": "动作自然，镜头衔接顺滑，猫狗表情生动，整体保持温暖、清晰、干净。",
    "shot_guidance": "每段按内容信息密度安排分镜。15秒通常5-7个分镜，10秒通常4个分镜，5秒通常2个分镜。",
    "science_guidance": "科普词出现时安排清晰、柔和、易懂的科普示意。",
    "shot_counts": (2, 4, 7),
    "shot_styles": [
        "近景固定镜头",
        "微距特写镜头，缓慢推近",
        "科普示意镜头，柔和转场",
        "中景轻微横移",
        "全景镜头，慢慢拉远",
    ],
    "default_visuals": [
        "{pet_label}抬头看向主人，眼睛明亮，轻轻眨眼",
        "主人蹲下伸手轻摸{pet_label}头顶，表情逐渐放松",
        "暖黄色光点在主人和{pet_label}之间缓慢扩散，空气变得柔软",
    ],
    "add_default_questioning_prefix": True,
    "first_shot_hook_prefix": "先用结果前置制造悬念：主人明显愣住，画面立刻切到",
    "ending_visual_suffix": "画面收束在主人与{pet_label}安静陪伴的温暖瞬间",
    "default_emotion": "温馨、治愈、轻科普、被{pet_label}爱着的安心感",
    "emotion_atmosphere": "温馨治愈、轻科普、{love_phrase}",
    "hook_strategy": "开头优先用反常行为、误会反差、结果前置或强情绪表情制造停留，不要用安静铺垫。",
    "first_3s_rule": "前3秒必须出现一个观众一眼能看懂的异常动作、强反差或悬念画面，并给出宠物或主人的即时反应。",
    "retention_structure": "前3秒必须有明确视觉钩子，后续根据内容灵活安排反差、递进、解释和情绪回收；不要机械套固定时间段，每个镜头都要提供新的动作、信息或情绪变化。",
    "density_rule": "避免纯氛围空镜；每个镜头至少承担一个功能：推进动作、制造反差、解释原因、放大情绪或完成转折。",
}


def _profile_from_config(profile_id: str) -> dict:
    profiles = PROMPT_CONFIG.get("profiles", {})
    profile = profiles.get(profile_id) if isinstance(profiles, dict) else None
    return profile if isinstance(profile, dict) else {}


def _merge_profile(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if key == "shot_counts" and isinstance(value, list):
            value = tuple(value)
        merged[key] = value
    return merged


def _channel_style_config(channel_id: str | None) -> dict:
    if not channel_id:
        return {}
    config = _load_channel_styles()
    channels = config.get("channels", [])
    for channel in channels:
        if isinstance(channel, dict) and str(channel.get("id", "")) == str(channel_id):
            return channel
    return {}


def _channel_profile(channel_id: str | None = None) -> dict:
    base = CHANNEL_PROMPT_PROFILES.get(str(channel_id or ""), DEFAULT_PROMPT_PROFILE)
    override = _profile_from_config(str(channel_id or "default"))
    if not override and channel_id is None:
        override = _profile_from_config("default")
    merged = _merge_profile(base, override)
    return _merge_profile(merged, _channel_style_config(channel_id))


BEHAVIOR_KEYWORDS = {
    "睡": "{pet_label}熟睡、胸口轻轻起伏、耳朵偶尔微动",
    "闻": "{pet_label}靠近主人衣角轻轻闻嗅，鼻尖微动",
    "舔": "{pet_label}低头轻舔爪子或轻轻舔主人手背",
    "摇尾巴": "{pet_label}尾巴轻轻摇动，身体放松靠近主人",
    "尾巴": "{pet_label}尾巴自然轻摆，露出放松的小动作",
    "靠": "{pet_label}把身体贴近主人腿边，缓慢蹭蹭",
    "蹭": "{pet_label}用脸颊或身体轻轻蹭主人，动作亲密自然",
    "踩奶": "猫咪在柔软毯子上轻轻踩奶，爪子一伸一缩",
    "呼噜": "猫咪眯着眼趴在毯子上，喉部轻微起伏，身体完全放松",
    "看": "{pet_label}抬头看向主人，眼睛明亮，轻轻眨眼",
    "叫": "{pet_label}抬头看向主人，耳朵微动，表情柔软，用动作安静回应",
    "喵": "猫咪抬头看向主人，耳朵微动，眼神柔软，用动作安静回应",
    "汪": "狗狗抬头看向主人，尾巴轻摆，表情柔软，用动作安静回应",
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


VISUAL_EVENT_PATTERNS = [
    {
        "keywords": ["最奢侈", "不是吃多贵", "不是住多大", "毫无保留", "做自己"],
        "main_action": "{pet_label}在主人面前自然放松地做自己，从闻嗅、摇尾到贴近，主人逐渐理解这份信任比物质更珍贵",
        "emotion": "从误会到理解，温柔揭开信任主题",
        "scene": "温暖客厅与家中细节，食盆、狗窝和主人身边的空地形成对比",
        "visuals": [
            "温暖客厅里，精致食盆和柔软狗窝只作为背景，{pet_label}真正停留在主人脚边",
            "{pet_label}抬头看主人后自然摇尾，身体没有拘谨，像在确认可以安心做自己",
            "主人原本看向食盆和房间，随后低头看见{pet_label}贴近自己，表情从疑惑变柔",
            "{pet_label}把鼻尖轻轻碰到主人手背，耳朵放松，尾巴慢慢扫过地板",
            "柔和信任光圈只在主人手和{pet_label}接触处轻轻出现，突出真正珍贵的是毫无保留的靠近"
        ],
    },
    {
        "keywords": ["刚被领养", "流浪狗", "空洞", "警惕", "小心翼翼"],
        "main_action": "{pet_label}站在新家门口或角落，身体压低，耳朵后贴，眼神警惕又不安",
        "emotion": "刚到新家的紧张、试探和不敢放松",
        "scene": "新家玄关或客厅角落，旁边有干净食盆、旧毯子或打开的纸箱",
        "visuals": [
            "{pet_label}半个身体躲在门边或纸箱旁，耳朵后贴，眼神小心扫视房间",
            "主人蹲在远处保持距离，手掌摊开放低，没有强行靠近",
            "{pet_label}向前迈半步又停住，鼻尖轻轻嗅空气，尾巴低低垂着",
            "暖光从门缝和窗边落进来，但{pet_label}仍贴着角落保持警惕"
        ],
    },
    {
        "keywords": ["给它食物", "看你的脸色", "叫它名字", "往后缩"],
        "main_action": "{pet_label}面对食盆迟迟不敢吃，先抬眼观察主人表情，听见名字后身体本能后缩",
        "emotion": "害怕做错、谨慎求生、让人心疼",
        "scene": "温暖客厅地板上的食盆旁，主人蹲在一米外安静陪伴",
        "visuals": [
            "食盆放在地板中央，{pet_label}靠近又停下，爪子停在碗边",
            "{pet_label}没有立刻低头吃，而是抬眼偷看主人脸色，耳朵轻轻后压",
            "主人轻轻放低手，身体后退半步给它空间，表情温柔克制",
            "{pet_label}听见被呼唤的动作暗示后肩膀一缩，身体往后挪到安全距离",
            "最后{pet_label}小口靠近食盆，仍一边吃一边用余光看主人"
        ],
    },
    {
        "keywords": ["蜷成", "紧绷的球", "梦里", "不敢放松"],
        "main_action": "{pet_label}睡觉时蜷成紧绷的小球，爪子收紧，耳朵在梦里也轻轻发抖",
        "emotion": "疲惫、戒备、心疼和压抑的不安全感",
        "scene": "夜晚卧室或客厅小毯子上，灯光很柔但空间安静",
        "visuals": [
            "{pet_label}蜷缩成很小的一团睡在毯子边缘，背部弓起，爪子紧紧收在胸前",
            "微距特写里耳朵轻颤，眼皮在梦里不安地动，呼吸很浅",
            "主人在远处停下脚步，没有打扰，只把柔软毯角轻轻拉近",
            "画面用淡灰色小云团压在{pet_label}身边，随后被房间暖光轻轻稀释"
        ],
    },
    {
        "keywords": ["这种", "懂事", "心疼", "怕", "失去这个家"],
        "main_action": "{pet_label}克制地坐在主人面前，不敢靠太近，眼神一直确认主人的反应",
        "emotion": "心疼、理解和害怕再次失去家的脆弱感",
        "scene": "安静客厅，主人坐在地板上和{pet_label}保持平视",
        "visuals": [
            "{pet_label}坐得很端正，尾巴贴着地面，像在努力不犯错",
            "主人慢慢放下手中的东西，视线变柔，意识到它的紧绷不是乖巧而是害怕",
            "{pet_label}抬头确认主人表情，眼睛湿润但没有夸张流泪",
            "家的轮廓变成柔和暖光包围客厅，角落的灰色阴影慢慢变浅"
        ],
    },
    {
        "keywords": ["发疯", "狂奔", "撞了墙", "继续跑", "小疯子", "犯傻", "闹腾"],
        "main_action": "{pet_label}在客厅突然撒欢狂奔，急刹转弯，轻轻撞到软垫或墙边后又开心继续跑",
        "emotion": "被宠大的松弛、放肆、快乐和安全感",
        "scene": "明亮客厅，沙发、地毯和软垫形成安全的奔跑路线",
        "visuals": [
            "{pet_label}从沙发边突然冲出，耳朵和毛发被速度带起，尾巴高高摆动",
            "低机位跟拍{pet_label}在地毯上急刹转弯，爪子轻轻打滑但动作可爱自然",
            "{pet_label}轻轻撞到软垫或墙边后愣一瞬，立刻甩甩头继续快乐奔跑",
            "主人先惊讶后笑着让开路线，手里抱枕被风带起一点",
            "全景里客厅被跑动轨迹带出柔和弧线，强调这是安全环境里的撒欢"
        ],
    },
    {
        "keywords": ["四脚朝天", "肚皮", "口水", "跨过去", "懒得动"],
        "main_action": "{pet_label}四脚朝天睡在地板或地毯上，肚皮完全露出，嘴边有一点口水，主人从旁边跨过它也不动",
        "emotion": "彻底信任、放松到毫无防备",
        "scene": "午后客厅地毯或卧室地板，阳光落在{pet_label}肚皮和爪子上",
        "visuals": [
            "{pet_label}仰躺在地毯中央，四只爪子松松摊开，肚皮随着呼吸轻轻起伏",
            "微距特写嘴边一点透明口水和放松的胡须，表情睡得很安心",
            "主人抱着衣物从旁边小心跨过，{pet_label}只是耳朵动一下，完全懒得起身",
            "柔和示意镜头用浅色光圈标出肚皮的脆弱位置，再自然回到现实画面",
            "{pet_label}翻了半个身又继续露着肚皮睡，尾巴末端轻轻扫一下地毯"
        ],
    },
    {
        "keywords": ["沙发", "挤到你怀里", "专属沙发"],
        "main_action": "{pet_label}硬挤进坐在沙发上的主人怀里，把主人当成柔软靠垫",
        "emotion": "亲密、依赖、理直气壮的安心感",
        "scene": "温暖客厅沙发上，主人坐着休息，旁边有毯子和抱枕",
        "visuals": [
            "主人刚坐到沙发上，{pet_label}从画面边缘挤进来，鼻尖顶开毯子",
            "{pet_label}前爪搭上主人腿，身体一点点往怀里塞，动作笨拙又坚定",
            "主人被挤得轻轻后仰，随后笑着调整坐姿给它让出位置",
            "{pet_label}把下巴压在主人手臂上，眼睛半眯，像占到专属位置",
            "全景里主人和{pet_label}挤在一起，沙发空间被它理直气壮占满"
        ],
    },
    {
        "keywords": ["犬类", "最致命", "绝对信任", "完全暴露"],
        "main_action": "{pet_label}在主人面前慢慢翻身露出肚皮，身体完全松开，没有任何防备动作",
        "emotion": "从脆弱到信任的温柔解释",
        "scene": "客厅地毯上，现实互动与柔和信任示意自然衔接",
        "visuals": [
            "{pet_label}先侧躺看着主人，确认安全后慢慢翻成露肚皮姿势",
            "柔和示意镜头里，{pet_label}的身体轮廓旁出现浅色保护光圈，肚皮位置用温暖线条轻轻标出",
            "主人没有突然伸手，只把手停在旁边等待，给{pet_label}选择空间",
            "{pet_label}主动用爪子轻碰主人手腕，眼神放松，尾巴轻轻扫地",
            "画面回到现实，主人轻轻抚摸胸口旁边的毛发，{pet_label}安心闭眼"
        ],
    },
    {
        "keywords": ["笃定", "不会伤害", "整个生命", "真心"],
        "main_action": "{pet_label}在主人身边自由奔跑、露肚皮、贴靠，所有放肆动作汇成对家的信任",
        "emotion": "信任升华、被爱托住的安全感",
        "scene": "家庭客厅到窗边的连续温暖空间，像回忆蒙太奇",
        "visuals": [
            "{pet_label}从客厅奔跑画面自然切到露肚皮睡觉画面，动作像回忆一样连贯",
            "主人坐在窗边伸手，{pet_label}主动把头放进掌心，身体完全靠近",
            "暖色信任光圈不是装饰性乱飞，而是沿着主人手掌和{pet_label}身体接触处轻轻扩散",
            "画面短暂闪回曾经小心翼翼的角落，再回到现在明亮客厅里的放松姿态",
            "{pet_label}抬头看主人后安心趴下，像确认这个家不会消失"
        ],
    },
    {
        "keywords": ["别嫌它烦", "摸摸它的头", "放心", "永远是你的"],
        "main_action": "主人蹲下轻轻摸{pet_label}的头，{pet_label}从兴奋慢慢安静下来，把头贴进主人掌心",
        "emotion": "安抚、承诺和家的归属感",
        "scene": "傍晚客厅或门口暖光里，主人和{pet_label}平视相处",
        "visuals": [
            "{pet_label}还带着刚撒欢后的兴奋，小步围着主人转，尾巴轻快摇动",
            "主人蹲下来伸手，动作缓慢稳定，轻轻摸过{pet_label}头顶和耳后",
            "{pet_label}逐渐停下，眼睛变柔，把头主动贴进主人掌心",
            "房间里的灯光像家的边界一样温柔包住一人一狗",
            "收束在{pet_label}安心趴到主人脚边，尾巴末端轻轻动一下"
        ],
    },
    {
        "keywords": ["评论区", "神经病", "瞬间"],
        "main_action": "主人拿着手机微笑看向{pet_label}，{pet_label}凑近镜头做出调皮小动作，形成无文字的互动邀请",
        "emotion": "轻松、亲密、带一点调皮的收尾",
        "scene": "温暖客厅沙发边或地毯上，手机屏幕不显示任何文字内容",
        "visuals": [
            "主人坐在地毯上拿着手机，屏幕朝外但没有任何可读文字，脸上露出回忆般的微笑",
            "{pet_label}从旁边把脑袋凑过来，鼻尖几乎碰到手机边缘",
            "{pet_label}忽然做出一个调皮姿势，比如歪头、趴到主人腿上或用爪子轻碰手机",
            "主人放下手机摸摸它，画面停在一人一狗轻松贴在一起的温暖瞬间"
        ],
    },
]


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
            "subject_style": "可爱的猫咪或本次内容指定猫咪，胡须细腻、耳朵灵动、尾巴动作自然",
            "love_phrase": "像在重新理解猫咪的爱",
            "strategy_label": "猫咪行为主线",
        }
    if dog_score > cat_score:
        return {
            "kind": "dog",
            "pet_label": "狗狗",
            "subject_style": "可爱的金毛犬或本次内容指定狗狗，耳朵灵动、尾巴动作自然",
            "love_phrase": "像在重新理解狗狗的爱",
            "strategy_label": "狗狗行为主线",
        }
    return {
        "kind": "pet",
        "pet_label": "猫咪或狗狗",
        "subject_style": "可爱的猫咪或狗狗，优先遵循本次内容指定宠物，耳朵灵动、动作自然",
        "love_phrase": "像在重新理解毛孩子的爱",
        "strategy_label": "猫狗行为主线",
    }


def _render_template(text: str, pet_context: dict[str, str]) -> str:
    return text.format(**pet_context)


def _render_profile_text(value: object, pet_context: dict[str, str], fallback: str = "") -> str:
    text = str(value or fallback or "")
    try:
        return _render_template(text, pet_context)
    except KeyError:
        return text


def _sentence(text: str) -> str:
    clean = str(text or "").strip()
    return clean if not clean or re.search(r"[。！？!?；;.]$", clean) else clean + "。"


def get_style_template_for_channel(channel_id: str | None = None) -> str:
    """根据频道ID获取画风模板"""
    config_style = _profile_from_config(str(channel_id or "default")).get("style_template")
    if isinstance(config_style, str) and config_style.strip():
        return config_style
    if not channel_id:
        return FIXED_STYLE_TEMPLATE

    config = _load_channel_styles()
    channels = config.get("channels", [])

    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if str(channel.get("id", "")) == str(channel_id):
            return str(channel.get("style_template", FIXED_STYLE_TEMPLATE))

    return FIXED_STYLE_TEMPLATE


def fixed_style_for_pet(pet_context: dict[str, str], channel_id: str | None = None) -> str:
    """获取渲染后的画风模板（支持频道选择）"""
    template = get_style_template_for_channel(channel_id)
    return _render_template(template, pet_context)


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
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        # 尝试修复常见的 JSON 错误
        # 1. 移除尾随逗号
        fixed = re.sub(r',(\s*[}\]])', r'\1', clean)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            # 如果还是失败，打印更详细的错误信息
            lines = clean.split('\n')
            error_line = e.lineno if hasattr(e, 'lineno') else 0
            context_start = max(0, error_line - 3)
            context_end = min(len(lines), error_line + 3)
            context = '\n'.join(f"{i+1:3d}: {lines[i]}" for i in range(context_start, context_end))
            raise ValueError(f"JSON 解析失败在第 {e.lineno} 行: {e.msg}\n上下文:\n{context}") from e


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


def _matched_visual_events(text: str, pet_context: dict[str, str]) -> list[dict]:
    matched = []
    for event in VISUAL_EVENT_PATTERNS:
        keywords = event.get("keywords", [])
        score = sum(1 for keyword in keywords if str(keyword) in text)
        if score:
            rendered = {}
            for key, value in event.items():
                if key == "keywords":
                    continue
                if isinstance(value, list):
                    rendered[key] = [_render_template(str(item), pet_context) for item in value]
                else:
                    rendered[key] = _render_template(str(value), pet_context)
            rendered["_score"] = score
            rendered["_keyword_chars"] = sum(len(str(keyword)) for keyword in keywords if str(keyword) in text)
            matched.append(rendered)
    matched.sort(key=lambda item: (int(item.get("_score", 0)), int(item.get("_keyword_chars", 0))), reverse=True)
    return matched


def _first_visual_event(text: str, pet_context: dict[str, str]) -> dict | None:
    events = _matched_visual_events(text, pet_context)
    return events[0] if events else None


def _segment_function(index: int, total: int, keywords: dict[str, list[str]], pet_context: dict[str, str], channel_id: str | None = None) -> str:
    pet_label = pet_context["pet_label"]
    if channel_id == "channel-science":
        if index == 1:
            return f"开头生活切片，用明亮水彩插画建立{pet_label}与主人的安静陪伴"
        if index == total:
            return f"情绪收束，用透明水彩轻动态呈现主人和{pet_label}的温柔陪伴"
        if keywords["science"]:
            return "轻科普解释段，用纸面手绘水彩图示解释行为背后的原因"
        return f"日常画面推进段，用{pet_label}的小动作和室内光线承接情绪"
    if index == 1:
        return f"开头强钩子，建立{pet_label}行为误会与治愈期待"
    if index == total:
        return f"情绪收束与行动建议，强化主人和{pet_label}的陪伴关系"
    if keywords["science"]:
        return "轻科普解释段，用治愈动画插帧解释行为背后的原因"
    return f"故事推进段，用{pet_label}行为和主人反应承接情绪共鸣"


def _scene_for_segment(text: str, channel_id: str | None = None, pet_context: dict[str, str] | None = None) -> str:
    pet_context = pet_context or detect_pet_context(text)
    event = _first_visual_event(text, pet_context)
    if event and event.get("scene"):
        return str(event["scene"])
    if any(word in text for word in ["睡", "床", "卧室"]):
        return "按本段内容自然选择的卧室或睡眠相关生活场景"
    if any(word in text for word in ["草地", "公园", "狼", "远古"]):
        return "按本段内容自然选择的户外草地、公园或远古生活场景"
    if any(word in text for word in ["窗", "书桌", "纸", "铅笔", "咖啡", "茶", "书架"]):
        return "按本段内容自然选择的窗边、书桌或文艺日常场景"
    if any(word in text for word in ["沙发", "客厅", "家里", "主人", "陪伴"]):
        return "按本段内容自然选择的家庭日常生活场景"
    return "按本段内容自然选择的生活化场景"


def _main_action(text: str, keywords: dict[str, list[str]], pet_context: dict[str, str]) -> str:
    event = _first_visual_event(text, pet_context)
    if event and event.get("main_action"):
        return str(event["main_action"])
    if keywords["behaviors"]:
        return keywords["behaviors"][0]
    pet_label = pet_context["pet_label"]
    if "主人" in text:
        return f"{pet_label}围绕主人做出自然小动作，抬头、眨眼、耳朵微动、尾巴轻摆或轻轻贴近"
    return f"{pet_label}在温暖家庭场景中自然活动，靠近、闻嗅、抬头、贴贴"


def _main_emotion(text: str, keywords: dict[str, list[str]], pet_context: dict[str, str], channel_id: str | None = None) -> str:
    event = _first_visual_event(text, pet_context)
    if event and event.get("emotion"):
        return str(event["emotion"])
    if keywords["emotions"]:
        return keywords["emotions"][0]
    if any(word in text for word in ["不是", "其实", "原来"]):
        return "从误会到理解的温柔释然"
    profile = _channel_profile(channel_id)
    return _render_profile_text(
        profile.get("default_emotion"),
        pet_context,
        f"温馨、治愈、轻科普、被{pet_context['pet_label']}爱着的安心感",
    )


def _shot_count(duration: int, channel_id: str | None = None, keywords: dict[str, list[str]] | None = None) -> int:
    short_count, medium_count, long_count = _channel_profile(channel_id)["shot_counts"]
    if duration <= 5:
        base = short_count
    elif duration <= 10:
        base = medium_count
    else:
        base = long_count

    keywords = keywords or {"behaviors": [], "emotions": [], "science": []}
    info_points = sum(len(keywords.get(key, [])) for key in ["behaviors", "emotions", "science"])
    if info_points >= 4 and duration >= 8:
        base += 1
    if info_points >= 6 and duration >= 12:
        base += 1
    if info_points <= 1 and duration >= 8:
        base -= 1

    min_count = 2 if duration <= 5 else 3
    max_count = max(min_count, min(9, duration))
    return max(min_count, min(max_count, base))


def _shot_visuals(text: str, keywords: dict[str, list[str]], pet_context: dict[str, str], channel_id: str | None = None) -> list[str]:
    visuals = []
    for event in _matched_visual_events(text, pet_context):
        event_visuals = event.get("visuals")
        if isinstance(event_visuals, list):
            visuals.extend(str(item) for item in event_visuals if str(item).strip())
    visuals.extend(keywords["behaviors"])
    if keywords["science"] or any(word in text for word in ["犬类", "肚皮", "信任", "嗅觉", "气味", "大脑", "多巴胺"]):
        visuals.extend(keywords["science"])
    visuals.extend(keywords["emotions"])
    if not visuals:
        profile = _channel_profile(channel_id)
        default_visuals = profile.get("default_visuals")
        if isinstance(default_visuals, list) and default_visuals:
            visuals = [_render_profile_text(item, pet_context) for item in default_visuals if str(item).strip()]
        if not visuals:
            pet_label = pet_context["pet_label"]
            visuals = [
                f"{pet_label}抬头看向主人，眼睛明亮，轻轻眨眼",
                f"主人蹲下伸手轻摸{pet_label}头顶，表情逐渐放松",
                f"暖黄色光点在主人和{pet_label}之间缓慢扩散，空气变得柔软",
            ]
    return visuals


def build_storyboard(duration: int, text: str, keywords: dict[str, list[str]], pet_context: dict[str, str], channel_id: str | None = None) -> list[str]:
    count = _shot_count(duration, channel_id, keywords)
    visuals = _shot_visuals(text, keywords, pet_context, channel_id)
    has_event_visuals = bool(_matched_visual_events(text, pet_context))
    shots = []
    ranges = []
    start = 0
    for i in range(count):
        end = duration if i == count - 1 else min(duration, start + 2)
        ranges.append((start, end))
        start = end
        if start >= duration:
            break

    shot_styles = _channel_profile(channel_id)["shot_styles"]
    profile = _channel_profile(channel_id)
    for idx, (start, end) in enumerate(ranges):
        visual = visuals[idx % len(visuals)]
        first_prefix = _render_profile_text(profile.get("first_shot_prefix"), pet_context)
        hook_prefix = _render_profile_text(profile.get("first_shot_hook_prefix"), pet_context)
        if idx == 0 and hook_prefix and not has_event_visuals:
            visual = f"{hook_prefix}{visual}"
        elif idx == 0 and first_prefix:
            visual = f"{first_prefix}{visual}"
        elif idx == 0 and not has_event_visuals and profile.get("add_default_questioning_prefix", True) and "误会" not in visual:
            visual = f"主人先露出轻微疑惑，随后看见{visual}"
        if idx == len(ranges) - 1:
            ending_suffix = _render_profile_text(profile.get("ending_visual_suffix"), pet_context)
            if ending_suffix:
                visual = f"{visual}，{ending_suffix}"
        shots.append(f"{start}-{end}秒：{shot_styles[idx % len(shot_styles)]}，{visual}。")
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


def _has_time_range(text: str) -> bool:
    return bool(re.search(r"\d+(?:\.\d+)?\s*[-~—至到]\s*\d+(?:\.\d+)?\s*秒", str(text or "")))


def _normalize_storyboard_timing(items: list[object], duration: int) -> list[str]:
    clean_items = [str(item).strip() for item in items if str(item).strip()]
    if not clean_items:
        return []
    if any(_has_time_range(item) for item in clean_items):
        return clean_items

    count = len(clean_items)
    safe_duration = max(1, int(duration or count))
    timed_items = []
    for index, item in enumerate(clean_items):
        start = min(safe_duration, index * 2)
        end = safe_duration if index == count - 1 else min(safe_duration, start + 2)
        start_text = str(int(start)) if float(start).is_integer() else str(start)
        end_text = str(int(end)) if float(end).is_integer() else str(end)
        timed_items.append(f"{start_text}-{end_text}秒：{item}")
    return timed_items


def _sanitize_storyboard_items(items: list[object]) -> list[str]:
    clean_items = []
    for item in items:
        clean = _sanitize_visual_text(str(item))
        if clean:
            clean_items.append(_ensure_sentence_end(clean))
    return clean_items


def _sanitize_visual_text(text: str) -> str:
    clean = str(text or "").strip()
    replacements = [
        (r"[，,。；;]?\s*对应逐字稿画面关键词“[^”]*”", ""),
        (r"[，,。；;]?\s*对应逐字稿关键词“[^”]*”", ""),
        (r"[，,。；;]?\s*对应解说关键词“[^”]*”", ""),
        (r"[，,。；;]?\s*对应旁白“[^”]*”", ""),
        (r"[，,。；;]?\s*对应台词“[^”]*”", ""),
        (r"[，,。；;]?\s*对应口播“[^”]*”", ""),
        (r"[，,。；;]?\s*对应[^。；;]*", ""),
        (r"[，,。；;]?\s*视觉重点[：:][^。；;]*", ""),
        (r"[，,。；;]?\s*视觉重点“[^”]*”", ""),
        (r"[，,。；;]?\s*画面重点[：:][^。；;]*", ""),
        (r"[，,。；;]?\s*画面重点“[^”]*”", ""),
        (r"旁白[:：][^。；;]*", ""),
        (r"解说[:：][^。；;]*", ""),
        (r"台词[:：][^。；;]*", ""),
        (r"口播[:：][^。；;]*", ""),
        (r"旁白内容[:：][^。；;]*", ""),
        (r"解说内容[:：][^。；;]*", ""),
        (r"台词内容[:：][^。；;]*", ""),
        (r"口播内容[:：][^。；;]*", ""),
        (r"字幕[^，。；;]*", ""),
        (r"说出[^，。；;]*", "用表情和动作表达"),
        (r"开口说话", "保持安静表情"),
        (r"张嘴说话", "保持自然表情"),
        (r"人物对话", "人物无声互动"),
        (r"人物说话", "人物无声互动"),
        (r"狗狗说话|猫咪说话|动物说话", "宠物通过动作表达"),
        (r"狗狗开口|猫咪开口|动物开口", "宠物通过动作表达"),
        (r"配音|对白|台词|口播|朗读", "视觉表达"),
    ]
    for pattern, repl in replacements:
        clean = re.sub(pattern, repl, clean)
    clean = clean.replace("逐字稿", "画面").replace("解说", "画面").replace("旁白", "画面")
    clean = clean.replace("台词", "画面").replace("口播", "画面").replace("对白", "画面")
    clean = re.sub(r"[，,]\s*[。；;]", "。", clean)
    clean = re.sub(r"：\s*[。；;]", "。", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


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


def _join_visual_state(*parts: str) -> str:
    clean_parts = [_sanitize_visual_text(part).strip("，,。；; ") for part in parts if _sanitize_visual_text(part).strip("，,。；; ")]
    return "，".join(clean_parts) if clean_parts else "猫狗自然活动，主人安静陪伴"


def build_prompt_for_segment(
    segment: SeedanceSegment,
    pet_context: dict[str, str],
    material_refs: dict[str, str] | None = None,
    channel_id: str | None = None,
) -> str:
    material_text = _material_instruction(material_refs)
    storyboard_items = _normalize_storyboard_timing(segment.storyboard, segment.duration)
    storyboard_text = " ".join(_ensure_sentence_end(_sanitize_visual_text(item)) for item in storyboard_items if str(item).strip())
    profile = _channel_profile(channel_id)
    emotion_atmosphere = _render_profile_text(
        profile.get("emotion_atmosphere"),
        pet_context,
        f"温馨治愈、轻科普、{pet_context['love_phrase']}",
    )
    return (
        f"{NO_DIALOGUE_CONSTRAINTS}{fixed_style_for_pet(pet_context, channel_id)} 16:9 横屏。{material_text}"
        f"本段主场景：{_sanitize_visual_text(segment.scene)}。"
        f"本段{pet_context['pet_label']}和主人状态：{_join_visual_state(segment.main_action, segment.emotion)}。"
        f"本段按时间轴分镜：{storyboard_text} "
        f"主情绪氛围：{emotion_atmosphere}。"
        f"{profile['motion']}{GLOBAL_QUALITY_REQUIREMENTS}{GLOBAL_NEGATIVE_CONSTRAINTS}"
    )


def _ai_split_prompt(transcript: str, pet_context: dict[str, str], channel_id: str | None = None) -> str:
    profile = _channel_profile(channel_id)
    hook_strategy = _render_profile_text(profile.get("hook_strategy"), pet_context)
    first_3s_rule = _render_profile_text(profile.get("first_3s_rule"), pet_context)
    retention_structure = _render_profile_text(profile.get("retention_structure"), pet_context)
    density_rule = _render_profile_text(profile.get("density_rule"), pet_context)
    return f"""你是抖音猫狗治愈轻科普账号的纯视觉导演。请把输入文案拆成适配即梦 Seedance 2.0 的文生视频任务段，并输出严格 JSON。

主体识别：{pet_context['pet_label']}
目标风格：{profile['split_style']}。
动态原则：{profile['motion']}
爆款开头策略：{hook_strategy}
前3秒视觉钩子：{first_3s_rule}
留存节奏原则：{retention_structure}
画面密度要求：{density_rule}

硬性规则：
1. 每段 duration 必须是 4-15 的整数，优先 15 秒，最后一段可以 4-14 秒，不要为了凑满 15 秒加无效画面。
2. {profile['shot_guidance']}
3. 每个分镜必须写清时间轴、景别、运镜、画面动作，分镜描述以可看见的画面为主；可以保留自然动作音效和环境音效，但不要设计人声内容。
4. 必须主动识别输入文案里的猫狗行为关键词、情绪关键词、轻科普关键词，并安排对应画面；不要把不同段都写成“抬头、摸头、暖光光点”。
5. {profile['science_guidance']}
6. 主人不能抢戏，猫狗永远是核心主体；人物只能以当前频道画风表现，避免写实真人脸部。
7. 第一段必须把最有停留价值的异常动作、反差结果或悬念画面提前到前3秒；后续段也要在开头快速给出本段信息点，不要慢铺垫。
8. 不要机械套固定时间比例；根据内容灵活安排反差、递进、解释、情绪回收，但每个分镜都必须提供新动作、新信息或新情绪。
9. 不要输出固定画风、负面约束和质量词，这些由程序统一注入。
10. 严禁在 function、main_action、emotion、scene、storyboard 中出现或暗示：字幕、文字贴片、人物开口、宠物开口、人声朗读、聊天、对白、台词、口播、配音、旁白、解说；允许出现脚步声、爪子踩地声、球落地声、布料摩擦声、轻微呼吸声、猫咪自然呼噜声、风声、草地声和室内环境声。
11. 严禁在 storyboard 中写“对应……”“视觉重点……”“画面重点……”或复制输入文案原句；分镜只能写镜头中实际发生的可见动作和动画化示意。
12. 情绪必须有转折：害怕/警惕的段落要画出身体压低、后缩、偷看、蜷缩；信任/撒欢的段落要画出奔跑、露肚皮、挤怀里、贴靠等具体动作。
13. 只输出 JSON，不要 Markdown，不要解释。

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
        "0-2秒：近景固定镜头，刚到新家的狗狗半躲在门边，耳朵后贴，眼神小心扫视房间",
        "2-4秒：低机位跟拍镜头，狗狗在客厅地毯上突然撒欢冲出，急刹转弯，尾巴高高摆动"
      ]
    }}
  ]
}}

输入文案：
{transcript}
"""


def _coerce_duration(value: object) -> int:
    try:
        duration = int(float(str(value).replace("秒", "").strip()))
    except (TypeError, ValueError):
        duration = 15
    return max(4, min(15, duration))


def _segments_from_ai_plan(plan: dict, transcript: str, pet_context: dict[str, str], material_refs: dict[str, str] | None, channel_id: str | None = None) -> list[SeedanceSegment]:
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
        storyboard = _sanitize_storyboard_items(storyboard)
        if not storyboard:
            keywords = analyze_keywords(text, pet_context)
            storyboard = build_storyboard(duration, text, keywords, pet_context, channel_id)

        keywords = analyze_keywords(text, pet_context)
        segment = SeedanceSegment(
            index=index,
            duration=duration,
            transcript=text,
            function=_sanitize_visual_text(str(raw.get("function") or _segment_function(index, len(raw_segments), keywords, pet_context, channel_id))),
            main_action=_sanitize_visual_text(str(raw.get("main_action") or _main_action(text, keywords, pet_context))),
            emotion=_sanitize_visual_text(str(raw.get("emotion") or _main_emotion(text, keywords, pet_context, channel_id))),
            scene=_sanitize_visual_text(str(raw.get("scene") or _scene_for_segment(text, channel_id, pet_context))),
            storyboard=_sanitize_storyboard_items(storyboard),
            prompt="",
            source="ai",
        )
        segment.prompt = build_prompt_for_segment(segment, pet_context, material_refs, channel_id)
        segments.append(segment)
    return segments


def build_seedance_segments_rule(transcript: str, material_refs: dict[str, str] | None = None, channel_id: str | None = None) -> list[SeedanceSegment]:
    raw_segments = split_transcript_for_seedance(transcript)
    total = len(raw_segments)
    pet_context = detect_pet_context(transcript)
    segments: list[SeedanceSegment] = []
    for idx, (duration, text) in enumerate(raw_segments, 1):
        keywords = analyze_keywords(text, pet_context)
        storyboard = _sanitize_storyboard_items(build_storyboard(duration, text, keywords, pet_context, channel_id))
        segment = SeedanceSegment(
            index=idx,
            duration=duration,
            transcript=text,
            function=_segment_function(idx, total, keywords, pet_context, channel_id),
            main_action=_main_action(text, keywords, pet_context),
            emotion=_main_emotion(text, keywords, pet_context, channel_id),
            scene=_scene_for_segment(text, channel_id, pet_context),
            storyboard=storyboard,
            prompt="",
        )
        segment.prompt = build_prompt_for_segment(segment, pet_context, material_refs, channel_id)
        segments.append(segment)
    return segments


def build_seedance_segments(
    transcript: str,
    material_refs: dict[str, str] | None = None,
    use_ai: bool = True,
    channel_id: str | None = None,
) -> list[SeedanceSegment]:
    pet_context = detect_pet_context(transcript)
    if use_ai and os.getenv("ANTHROPIC_API_KEY"):
        try:
            plan = _call_ai_splitter(_ai_split_prompt(transcript, pet_context, channel_id))
            return _segments_from_ai_plan(plan, transcript, pet_context, material_refs, channel_id)
        except Exception as exc:
            print(f"⚠️ Seedance AI 拆分失败，回退规则拆分: {exc}")
    return build_seedance_segments_rule(transcript, material_refs=material_refs, channel_id=channel_id)


def format_seedance_markdown(transcript: str, segments: list[SeedanceSegment], channel_id: str | None = None) -> str:
    if not segments:
        return "请先载入或粘贴一段逐字稿。"
    split_way = " + ".join(f"{segment.duration}秒" for segment in segments)
    pet_context = detect_pet_context(transcript)
    all_keywords = analyze_keywords(transcript, pet_context)
    profile = _channel_profile(channel_id)
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
        f"总体拆分逻辑：{'AI模型导演拆分' if any(segment.source == 'ai' for segment in segments) else '规则兜底拆分'}，按内容信息密度优先拆成15秒以内任务段，{profile['shot_guidance']}",
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
            *[_sanitize_visual_text(item) for item in segment.storyboard],
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
    channel_id: str | None = None,
) -> tuple[str, str]:
    segments = build_seedance_segments(transcript, material_refs=material_refs, use_ai=use_ai, channel_id=channel_id)
    markdown = format_seedance_markdown(transcript, segments, channel_id=channel_id)
    queue_json = build_seedance_queue_document(segments, multimodal=bool(material_refs), model_version=model_version)
    return markdown, queue_json
