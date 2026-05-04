#!/usr/bin/env python3
"""
爆款文案智能体 - 可视化界面
"""
import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import gradio as gr
from viral_agent import knowledge_base as kb
from viral_agent.analyzer import analyze_script
from viral_agent.agent import generate
from douyin_downloader.pipeline import DouyinViralPipeline

# ── 环境变量（可在界面顶部覆盖）──────────────────────────
DEFAULT_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://cc.codesome.ai")


def set_env(api_key: str, base_url: str):
    if api_key.strip():
        os.environ["ANTHROPIC_API_KEY"] = api_key.strip()
    if base_url.strip():
        os.environ["ANTHROPIC_BASE_URL"] = base_url.strip()


# ── Tab1: 学习爆款 ────────────────────────────────────────
def learn_single(script: str, likes: int, niche: str, api_key: str, base_url: str):
    set_env(api_key, base_url)
    if not script.strip():
        return "❌ 请输入文案内容", kb.get_stats()

    video_id = f"manual_{hash(script) % 100000:05d}"
    yield f"⏳ 正在分析文案...", kb.get_stats()

    analysis = analyze_script(script, likes=int(likes), niche=niche)

    kb.add_script(
        video_id=video_id,
        script=script,
        analysis=analysis,
        metadata={"likes": int(likes), "niche": niche, "platform": "manual"},
    )

    result = f"✅ 分析完成，已存入知识库！\n\n"
    result += f"**钩子类型：** {analysis.get('hook_type', '')}\n\n"
    result += f"**开头钩子：** {analysis.get('hook', '')}\n\n"
    result += f"**钩子公式：** `{analysis.get('hook_formula', '')}`\n\n"
    result += f"**内容结构：** {analysis.get('structure', '')}\n\n"
    result += f"**爆火原因：** {analysis.get('why_viral', '')}\n\n"
    result += f"**改写模板：**\n{analysis.get('rewrite_template', '')}"

    yield result, kb.get_stats()


def learn_batch(json_text: str, niche: str, api_key: str, base_url: str):
    set_env(api_key, base_url)
    try:
        scripts = json.loads(json_text)
    except json.JSONDecodeError as e:
        yield f"❌ JSON 格式错误: {e}", kb.get_stats()
        return

    total = len(scripts)
    logs = []
    for i, item in enumerate(scripts):
        script = item.get("script", "")
        video_id = item.get("video_id", f"batch_{i:04d}")
        likes = item.get("likes", 0)
        item_niche = item.get("niche", niche)

        logs.append(f"[{i+1}/{total}] 分析 {video_id}...")
        yield "\n".join(logs), kb.get_stats()

        analysis = analyze_script(script, likes=likes, niche=item_niche)
        kb.add_script(video_id, script, analysis, {"likes": likes, "niche": item_niche, "platform": "batch"})
        logs[-1] += f" ✅ 点赞{likes:,} | {analysis.get('hook_type', '')}"
        yield "\n".join(logs), kb.get_stats()

    logs.append(f"\n🎉 全部完成！{kb.get_stats()}")
    yield "\n".join(logs), kb.get_stats()


# ── Tab2: 检索知识库 ──────────────────────────────────────
def search_kb(query: str, niche: str, n: int):
    results = kb.search_scripts(query, n=int(n), niche=niche or None)
    if not results:
        return "知识库为空或无相关内容，请先导入爆款文案。"

    out = f"找到 **{len(results)}** 条相关爆款：\n\n"
    for i, s in enumerate(results, 1):
        out += f"---\n### 爆款 {i}  ·  点赞 {s['likes']:,}  ·  相似度 {s['similarity']:.2f}\n\n"
        out += f"**钩子类型：** {s['hook_type']}\n\n"
        out += f"**钩子公式：** `{s['analysis'].get('hook_formula', '')}`\n\n"
        out += f"**结构：** {s['structure']}\n\n"
        out += f"**爆火原因：** {s['why_viral']}\n\n"
        out += f"**原文：**\n> {s['script'][:200]}...\n\n"
    return out


def show_stats(niche: str):
    stats = kb.get_all_patterns(niche=niche or None)
    if stats["count"] == 0:
        return "知识库为空，请先导入爆款文案。"

    out = f"## 📊 知识库统计（共 {stats['count']} 条）\n\n"
    out += "### 钩子类型分布\n"
    for k, v in sorted(stats["hook_types"].items(), key=lambda x: -x[1]):
        bar = "█" * v
        out += f"- **{k}** {bar} {v}条\n"
    out += f"\n### 高频爆款元素\n"
    out += "  ".join([f"`{e}`" for e in stats["top_viral_elements"][:15]])
    out += "\n\n### 典型文案结构\n"
    for s in stats["sample_structures"][:3]:
        out += f"- {s}\n"
    return out


# ── Tab3: 生成文案 ────────────────────────────────────────
def run_generate(topic: str, niche: str, requirements: str, versions: int, api_key: str, base_url: str):
    set_env(api_key, base_url)
    if not topic.strip():
        return "❌ 请输入视频主题"
    yield "⏳ 智能体运行中，正在检索爆款知识库并生成文案..."
    result = generate(topic=topic, niche=niche, requirements=requirements, versions=int(versions))
    yield result


# ── Tab4: 抖音采集 ────────────────────────────────────────
def run_douyin_pipeline(
    user_urls_text: str,
    max_per_user: int,
    min_likes: int,
    transcribe_method: str,
    whisper_model: str,
    auto_import: bool,
    niche: str,
    api_key: str,
    base_url: str
):
    """运行抖音采集流水线"""
    set_env(api_key, base_url)

    # 解析用户链接
    user_urls = [url.strip() for url in user_urls_text.strip().split('\n') if url.strip()]
    if not user_urls:
        yield "❌ 请输入至少一个抖音用户主页链接", kb.get_stats()
        return

    yield f"🚀 开始采集 {len(user_urls)} 个账号的爆款视频...\n", kb.get_stats()

    # 创建流水线
    pipeline = DouyinViralPipeline(
        output_dir="./douyin_analysis",
        min_likes=int(min_likes)
    )

    logs = []

    try:
        # 运行异步流水线
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        logs.append(f"📥 [1/3] 下载爆款视频（点赞数 ≥ {min_likes:,}）")
        yield "\n".join(logs), kb.get_stats()

        export_file = loop.run_until_complete(
            pipeline.run_full_pipeline(
                user_urls=user_urls,
                max_per_user=int(max_per_user),
                transcribe_method=transcribe_method,
                model_name=whisper_model
            )
        )

        logs.append(f"✅ 流水线完成！导出文件: {export_file}")
        yield "\n".join(logs), kb.get_stats()

        # 自动导入到知识库
        if auto_import:
            logs.append(f"\n📚 [额外步骤] 自动导入到知识库...")
            yield "\n".join(logs), kb.get_stats()

            with open(export_file, 'r', encoding='utf-8') as f:
                samples = json.load(f)

            imported = 0
            for i, sample in enumerate(samples):
                script = sample.get("text", "")
                metadata = sample.get("metadata", {})
                video_id = metadata.get("aweme_id", f"douyin_{i:04d}")
                likes = metadata.get("likes", 0)

                logs.append(f"  [{i+1}/{len(samples)}] 分析 {video_id}...")
                yield "\n".join(logs), kb.get_stats()

                analysis = analyze_script(script, likes=likes, niche=niche)
                kb.add_script(
                    video_id=video_id,
                    script=script,
                    analysis=analysis,
                    metadata={**metadata, "niche": niche, "platform": "douyin"}
                )
                imported += 1
                logs[-1] += f" ✅ 点赞{likes:,}"
                yield "\n".join(logs), kb.get_stats()

            logs.append(f"\n🎉 全部完成！共导入 {imported} 条爆款文案到知识库")
        else:
            logs.append(f"\n💡 提示：可以手动导入到知识库：")
            logs.append(f"   python -m viral_agent learn --from-file {export_file}")

        yield "\n".join(logs), kb.get_stats()

    except Exception as e:
        logs.append(f"\n❌ 错误: {str(e)}")
        yield "\n".join(logs), kb.get_stats()
    finally:
        loop.close()


# ── 界面布局 ──────────────────────────────────────────────
with gr.Blocks(title="爆款文案智能体", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🔥 爆款文案智能体\n基于爆款视频知识库，自动生成高质量短视频文案")

    # 全局配置
    with gr.Accordion("⚙️ API 配置", open=False):
        with gr.Row():
            api_key_input = gr.Textbox(
                value=DEFAULT_API_KEY, label="API Key",
                placeholder="sk-...", type="password", scale=3,
            )
            base_url_input = gr.Textbox(
                value=DEFAULT_BASE_URL, label="Base URL",
                placeholder="https://api.anthropic.com", scale=2,
            )

    kb_stats = gr.Markdown(value=kb.get_stats(), label="知识库状态")

    with gr.Tabs():
        # ── Tab 0: 抖音采集 ──
        with gr.Tab("📥 抖音采集"):
            gr.Markdown("""
### 🎯 从抖音爆款账号批量采集视频文案

**使用步骤：**
1. 输入抖音用户主页链接（每行一个）
2. 设置筛选条件（点赞数阈值、下载数量）
3. 选择转录方式（Whisper 本地 或 Groq API）
4. 点击开始采集，等待完成
5. 可选：自动导入到知识库
            """)

            with gr.Row():
                with gr.Column(scale=1):
                    user_urls_input = gr.Textbox(
                        label="抖音用户主页链接（每行一个）",
                        placeholder="https://www.douyin.com/user/MS4wLjABAAAA...\nhttps://www.douyin.com/user/MS4wLjABAAAA...",
                        lines=5
                    )
                    with gr.Row():
                        min_likes_input = gr.Number(
                            label="最低点赞数",
                            value=100000,
                            minimum=0,
                            info="只下载点赞数超过此值的视频"
                        )
                        max_per_user_input = gr.Number(
                            label="每账号最多下载",
                            value=20,
                            minimum=1,
                            maximum=100,
                            info="每个账号最多下载多少个视频"
                        )

                    transcribe_method_input = gr.Radio(
                        label="转录方式",
                        choices=["whisper", "groq"],
                        value="whisper",
                        info="whisper=本地（慢但免费），groq=云端（快但需API key）"
                    )
                    whisper_model_input = gr.Dropdown(
                        label="Whisper 模型（仅本地模式）",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        value="base",
                        info="模型越大越准确但越慢"
                    )

                    with gr.Row():
                        auto_import_input = gr.Checkbox(
                            label="自动导入到知识库",
                            value=True,
                            info="采集完成后自动分析并导入"
                        )
                        douyin_niche_input = gr.Textbox(
                            label="赛道标签",
                            placeholder="情感、干货、美食...",
                            value="",
                            scale=2
                        )

                    douyin_btn = gr.Button("🚀 开始采集", variant="primary", size="lg")

                with gr.Column(scale=2):
                    douyin_output = gr.Textbox(
                        label="采集日志",
                        lines=20,
                        max_lines=30,
                        interactive=False
                    )

            douyin_btn.click(
                run_douyin_pipeline,
                inputs=[
                    user_urls_input,
                    max_per_user_input,
                    min_likes_input,
                    transcribe_method_input,
                    whisper_model_input,
                    auto_import_input,
                    douyin_niche_input,
                    api_key_input,
                    base_url_input
                ],
                outputs=[douyin_output, kb_stats]
            )

        # ── Tab 1: 学习 ──
        with gr.Tab("📥 学习爆款"):
            with gr.Tabs():
                with gr.Tab("单条录入"):
                    with gr.Row():
                        with gr.Column(scale=2):
                            script_input = gr.Textbox(
                                label="爆款文案内容",
                                placeholder="粘贴爆款视频的文案...",
                                lines=8,
                            )
                            with gr.Row():
                                likes_input = gr.Number(label="点赞数", value=100000, minimum=0)
                                niche_input1 = gr.Textbox(label="赛道", placeholder="情感、干货、美食...")
                            learn_btn = gr.Button("🚀 分析并存入知识库", variant="primary")
                        with gr.Column(scale=2):
                            learn_output = gr.Markdown(label="分析结果")

                    learn_btn.click(
                        learn_single,
                        inputs=[script_input, likes_input, niche_input1, api_key_input, base_url_input],
                        outputs=[learn_output, kb_stats],
                    )

                with gr.Tab("批量导入 JSON"):
                    json_input = gr.Textbox(
                        label="JSON 格式文案列表",
                        placeholder='''[
  {"video_id": "v001", "script": "文案内容...", "likes": 100000, "niche": "情感"},
  {"video_id": "v002", "script": "文案内容...", "likes": 200000, "niche": "干货"}
]''',
                        lines=12,
                    )
                    niche_input2 = gr.Textbox(label="默认赛道（JSON中无niche时使用）", placeholder="情感")
                    batch_btn = gr.Button("🚀 批量分析导入", variant="primary")
                    batch_output = gr.Textbox(label="处理日志", lines=10)

                    batch_btn.click(
                        learn_batch,
                        inputs=[json_input, niche_input2, api_key_input, base_url_input],
                        outputs=[batch_output, kb_stats],
                    )

        # ── Tab 2: 知识库 ──
        with gr.Tab("🗂️ 知识库"):
            with gr.Tabs():
                with gr.Tab("语义检索"):
                    with gr.Row():
                        search_query = gr.Textbox(label="检索内容", placeholder="职场升职、减肥瘦身...", scale=3)
                        search_niche = gr.Textbox(label="筛选赛道（可选）", placeholder="情感", scale=1)
                        search_n = gr.Slider(label="返回数量", minimum=1, maximum=10, value=5, step=1)
                    search_btn = gr.Button("🔍 检索", variant="primary")
                    search_output = gr.Markdown()
                    search_btn.click(search_kb, inputs=[search_query, search_niche, search_n], outputs=search_output)

                with gr.Tab("统计分析"):
                    stats_niche = gr.Textbox(label="筛选赛道（可选）", placeholder="留空查看全部")
                    stats_btn = gr.Button("📊 查看统计", variant="primary")
                    stats_output = gr.Markdown()
                    stats_btn.click(show_stats, inputs=[stats_niche], outputs=stats_output)

        # ── Tab 3: 生成 ──
        with gr.Tab("✍️ 生成文案"):
            with gr.Row():
                with gr.Column(scale=1):
                    topic_input = gr.Textbox(label="视频主题 *", placeholder="普通人如何月入过万", lines=2)
                    niche_input3 = gr.Textbox(label="赛道", placeholder="干货、情感、美食...")
                    req_input = gr.Textbox(
                        label="额外要求（可选）",
                        placeholder="目标受众：25-35岁职场人\n风格：接地气、有共鸣感",
                        lines=3,
                    )
                    versions_input = gr.Slider(label="生成版本数", minimum=1, maximum=5, value=3, step=1)
                    gen_btn = gr.Button("🔥 生成爆款文案", variant="primary", size="lg")
                with gr.Column(scale=2):
                    gen_output = gr.Markdown(label="生成结果")

            gen_btn.click(
                run_generate,
                inputs=[topic_input, niche_input3, req_input, versions_input, api_key_input, base_url_input],
                outputs=gen_output,
            )

    gr.Markdown("""
---
**使用流程：** 📥 抖音采集（自动） → 📥 学习爆款（手动补充） → 🗂️ 检索验证 → ✍️ 生成文案

知识库越丰富（建议每个赛道 30+ 条），生成质量越高
""")


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
    )
