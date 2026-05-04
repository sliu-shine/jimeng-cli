"""
爆款文案智能体
用 claude CLI 做推理，手动管理检索→生成流程
"""
import os
import subprocess
from . import knowledge_base as kb


CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")


def _call_claude(prompt: str) -> str:
    env = os.environ.copy()
    if ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    if ANTHROPIC_BASE_URL:
        env["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL

    result = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
        capture_output=True, text=True, env=env, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI 错误: {result.stderr[:300]}")
    return result.stdout.strip()


def generate(
    topic: str,
    requirements: str = "",
    niche: str = "",
    versions: int = 3,
) -> str:
    """生成爆款文案"""
    print(f"\n🤖 爆款智能体启动...")
    print(f"📝 主题：{topic}")
    print(f"📊 {kb.get_stats()}\n")

    # Step 1: 检索相似爆款
    print("🔍 检索相似爆款...")
    similar = kb.search_scripts(topic, n=5, niche=niche or None)

    # Step 2: 获取整体规律
    stats = kb.get_all_patterns(niche=niche or None)

    # Step 3: 拼装上下文，调用 Claude 生成
    print("✍️  生成文案中...")

    kb_context = ""
    if similar:
        kb_context = "【知识库中的相关爆款】\n\n"
        for i, s in enumerate(similar, 1):
            kb_context += f"爆款{i}（点赞{s['likes']:,}，相似度{s['similarity']:.2f}）\n"
            kb_context += f"��子类型：{s['hook_type']}\n"
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
        pattern_context += f"高频爆款��素：{', '.join(stats['top_viral_elements'][:10])}\n"

    prompt = f"""你是一位顶级短视频爆款文案创作者，拥有海量爆款学习经验。

{kb_context}{pattern_context}
---
现在请基于以上爆款数据，为以下主题创作{versions}个版本的爆款短视频文案：

主题：{topic}
{f'赛道：{niche}' if niche else ''}
{f'要求：{requirements}' if requirements else ''}

创作要求：
1. 每个版本使用不同的钩子类型（从上面的爆款中提炼）
2. 前3秒必须有强钩子，参考知识库中表现最好的公式
3. 结构清晰：钩子→冲突/痛点→解决/干货→行动号召
4. 口语化，真人讲述感
5. 每个版本注明：借鉴了哪个爆款的结构/公式

输出格式：
【版本1 - 钩子类型】
（参考：借鉴了爆款X的XX公式）
文案正文...

【版本2 - 钩子类型】
...
"""

    result = _call_claude(prompt)
    print("\n✅ 生成完毕\n")
    return result
