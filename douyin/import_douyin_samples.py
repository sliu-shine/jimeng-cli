#!/usr/bin/env python3
"""
将抖音爆款样本导入到爆款智能体知识库
"""
import json
import sys
from pathlib import Path

# 导入爆款智能体模块
from viral_agent.knowledge_base import add_script
from viral_agent.analyzer import analyze_script


def import_douyin_samples(samples_file: Path):
    """
    导入抖音爆款样本到知识库

    Args:
        samples_file: viral_samples.json 文件路径
    """
    if not samples_file.exists():
        print(f"文件不存在: {samples_file}")
        return

    with open(samples_file, 'r', encoding='utf-8') as f:
        samples = json.load(f)

    print(f"加载了 {len(samples)} 个抖音爆款样本")
    print("开始分析并导入知识库...\n")

    success_count = 0
    for i, sample in enumerate(samples, 1):
        text = sample["text"]
        metadata = sample["metadata"]

        video_id = metadata.get("aweme_id", f"douyin_{i}")
        likes = metadata.get("likes", 0)

        print(f"[{i}/{len(samples)}] 分析视频 {video_id} (点赞: {likes:,})")

        try:
            # 使用 Claude 分析文案
            analysis = analyze_script(text, niche="抖音短视频")

            # 存入知识库
            add_script(
                video_id=video_id,
                script=text,
                analysis=analysis,
                metadata={
                    "source": "douyin",
                    "likes": likes,
                    "comments": metadata.get("comments", 0),
                    "shares": metadata.get("shares", 0),
                    "duration": metadata.get("duration", 0),
                    "desc": metadata.get("desc", ""),
                    "niche": "抖音短视频"
                }
            )

            print(f"  ✅ 导入成功")
            success_count += 1

        except Exception as e:
            print(f"  ❌ 失败: {e}")
            continue

    print(f"\n导入完成: {success_count}/{len(samples)} 个样本成功")
    print(f"\n现在可以使用爆款智能体生成文案:")
    print(f"python -m viral_agent generate --topic '你的主题'")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python import_douyin_samples.py <viral_samples.json>")
        sys.exit(1)

    samples_file = Path(sys.argv[1])
    import_douyin_samples(samples_file)
