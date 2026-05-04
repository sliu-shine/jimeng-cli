#!/usr/bin/env python3
"""
从 douyin_videos 目录导入视频到知识库
支持自动转录和分析
"""
import asyncio
import json
import sys
from pathlib import Path

from douyin_downloader.transcriber import extract_transcript
from viral_agent.analyzer import analyze_script
from viral_agent import knowledge_base


async def import_videos(video_dir: str, method: str = "whisper", groq_api_key: str = None):
    """
    导入视频目录到知识库

    Args:
        video_dir: 视频目录路径
        method: 转录方法 (whisper/groq)
        groq_api_key: Groq API key
    """
    video_path = Path(video_dir)

    if not video_path.exists():
        print(f"❌ 目录不存在: {video_dir}")
        return

    # 查找所有视频文件
    video_files = list(video_path.glob("*.mp4"))

    if not video_files:
        print(f"❌ 未找到视频文件: {video_dir}")
        return

    print("=" * 70)
    print(f"找到 {len(video_files)} 个视频文件")
    print("=" * 70)

    success_count = 0

    for i, video_file in enumerate(video_files, 1):
        print(f"\n[{i}/{len(video_files)}] 处理: {video_file.name}")

        # 检查是否已有转录文件
        transcript_file = video_file.with_suffix(".txt")

        if transcript_file.exists():
            print("  ✓ 使用已有转录文件")
            with open(transcript_file, "r", encoding="utf-8") as f:
                transcript = f.read()
        else:
            print(f"  🔄 转录中（{method}）...")
            result = extract_transcript(
                video_path=video_file,
                method=method,
                model_name="base" if method == "whisper" else "large-v3"
            )
            transcript = result.get("text", "")

            if transcript:
                # 保存转录结果
                with open(transcript_file, "w", encoding="utf-8") as f:
                    f.write(transcript)
                print(f"  ✅ 转录完成: {len(transcript)} 字符")
            else:
                print("  ❌ 转录失败，跳过")
                continue

        # 从文件名提取点赞数
        filename_parts = video_file.stem.split("_")
        likes = int(filename_parts[-1]) if len(filename_parts) > 1 else 0

        # 分析爆款模式
        print("  🔄 分析爆款模式...")
        analysis = analyze_script(transcript, likes=likes, niche="抖音短视频")

        if not analysis:
            print("  ❌ 分析失败，跳过")
            continue

        # 导入知识库
        video_id = video_file.stem

        knowledge_base.add_script(
            video_id=video_id,
            script=transcript,
            analysis=analysis,
            metadata={
                "source": "douyin_selenium",
                "likes": likes,
                "niche": "抖音短视频"
            }
        )

        print(f"  ✅ 已导入知识库")
        print(f"     钩子类型: {analysis.get('hook_type', 'N/A')}")
        print(f"     钩子公式: {analysis.get('hook_formula', 'N/A')}")

        success_count += 1

    # 显示统计
    print("\n" + "=" * 70)
    print(f"✅ 导入完成: {success_count}/{len(video_files)} 个视频")
    print("=" * 70)

    stats = knowledge_base.get_stats()
    print("\n知识库统计:")
    print(stats)

    print("\n现在可以使用爆款智能体生成文案:")
    print("  python viral_agent_ui.py")
    print("  或")
    print("  python -m viral_agent generate '你的主题'")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="导入视频到知识库")
    parser.add_argument("video_dir", help="视频目录路径")
    parser.add_argument("--method", choices=["whisper", "groq"],
                       default="whisper", help="转录方法")
    parser.add_argument("--groq-api-key", help="Groq API key")

    args = parser.parse_args()

    asyncio.run(import_videos(
        args.video_dir,
        method=args.method,
        groq_api_key=args.groq_api_key
    ))


if __name__ == "__main__":
    main()
