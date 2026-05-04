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

from claude_client import ClaudeClient


def _call_claude(prompt: str) -> str:
    """通过 Claude API 调用"""
    client = ClaudeClient()

    result = client.create_message(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000
    )

    return result['content'][0]['text']


def analyze_script(script: str, likes: int = 0, niche: str = "") -> dict:
    """深度分析一条爆款文案，提取可复用模式"""
    context = f"点赞数：{likes:,}\n赛道：{niche}\n" if likes or niche else ""

    prompt = f"""你是一位顶级短视频爆款分析师。请深度分析以下爆款视频文案，提取可复用的爆款模式。

{context}【原始文案】
{script}

请用JSON格式输出分析结果，包含以下字段：
{{
  "hook": "开头钩子的具体内容（原文摘录）",
  "hook_type": "钩子类型（痛点型/反常识型/悬念型/共鸣型/利益型/恐惧型/好奇型）",
  "hook_formula": "钩子公式模板，用[]标记可替换变量，如：你还在[错误行为]？难怪[负面结果]",
  "structure": "内容结构描述，如：痛点引入→解决方案→案例佐证→行动号召",
  "emotion_triggers": ["情绪触发点列表"],
  "viral_elements": ["爆款元素列表，如：反转、共鸣、干货、恐惧、稀缺"],
  "target_audience": "精准受众描述",
  "core_value": "核心价值主张",
  "why_viral": "为什么会爆的核心原因（3条以内）",
  "rewrite_template": "基于此文案的改写模板，用[]标记可替换部分",
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
            "rewrite_template": script,
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
