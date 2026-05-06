#!/usr/bin/env python3
"""
Create a Jianying import package.

Output:
    final.mp4       - merged video
    subtitles.srt   - editable subtitle file for Jianying
    import_guide.json
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jianying.import_package import create_import_package


def auto_produce_video(
    transcript: str,
    video_files: list[str],
    project_name: str = "自动生产视频",
    add_subtitles: bool = True,
    output_dir: str | None = None,
) -> str:
    print("🎬 开始生成剪映导入包...")
    print(f"📝 文案长度: {len(transcript)} 字")
    print(f"🎥 视频片段数: {len(video_files)}")

    package = create_import_package(
        project_name=project_name,
        transcript=transcript,
        video_files=video_files,
        output_dir=output_dir,
        add_subtitles=add_subtitles,
    )

    print("\n✅ 导入包生成完成")
    print(f"📁 导入包: {package['output_path']}")
    print(f"🎞️ 视频: {package['final_video']}")
    if package["subtitles"]:
        print(f"💬 字幕: {package['subtitles']}")
    print(f"⏱️ 总时长: {package['total_duration']:.1f}秒")
    print("\n下一步:")
    print("1. 打开剪映专业版，点击「开始创作」")
    print("2. 导入 final.mp4")
    print("3. 导入 subtitles.srt，或使用剪映自动识别字幕")
    print("4. 在剪映中继续精修、配音和导出")
    return package["output_path"]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成剪映导入包")
    parser.add_argument("--transcript", "-t", required=True, help="视频文案文本或文案文件路径")
    parser.add_argument("--videos", "-v", required=True, help="视频文件路径，支持通配符")
    parser.add_argument("--project-name", "-n", default="自动生产视频", help="项目名称")
    parser.add_argument("--no-subtitles", action="store_true", help="不生成 SRT 字幕")
    parser.add_argument("--output-dir", "-o", help="输出目录")
    args = parser.parse_args()

    if os.path.isfile(args.transcript):
        with open(args.transcript, "r", encoding="utf-8") as f:
            transcript = f.read().strip()
    else:
        transcript = args.transcript

    video_files = glob.glob(args.videos, recursive=True)
    if not video_files:
        print(f"❌ 错误: 未找到视频文件: {args.videos}")
        sys.exit(1)
    video_files.sort()

    auto_produce_video(
        transcript=transcript,
        video_files=video_files,
        project_name=args.project_name,
        add_subtitles=not args.no_subtitles,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
