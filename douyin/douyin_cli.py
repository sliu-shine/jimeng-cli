#!/usr/bin/env python3
"""
抖音爆款视频下载和分析工具 - CLI 入口
"""
import asyncio
import argparse
from pathlib import Path

from douyin_downloader.pipeline import DouyinViralPipeline


def main():
    parser = argparse.ArgumentParser(description="抖音爆款视频下载和分析工具")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # download 命令
    download_parser = subparsers.add_parser("download", help="下载爆款视频")
    download_parser.add_argument("--users", nargs="+", required=True, help="抖音用户主页链接")
    download_parser.add_argument("--max-per-user", type=int, default=20, help="每个账号最多下载数量")
    download_parser.add_argument("--min-likes", type=int, default=1000, help="最低点赞数")
    download_parser.add_argument("--output", default="./douyin_analysis", help="输出目录")

    # transcribe 命令
    transcribe_parser = subparsers.add_parser("transcribe", help="提取视频逐字稿")
    transcribe_parser.add_argument("--video-dir", required=True, help="视频目录")
    transcribe_parser.add_argument("--method", choices=["whisper", "groq", "yunwu"], default="whisper", help="识别方法")
    transcribe_parser.add_argument("--model", default="large-v3", help="Whisper 模型名称")
    transcribe_parser.add_argument("--groq-api-key", help="Groq API key（使用 groq 方法时需要）")
    transcribe_parser.add_argument("--yunwu-api-key", help="云雾 API key（使用 yunwu 方法时需要）")

    # pipeline 命令（完整流程）
    pipeline_parser = subparsers.add_parser("pipeline", help="运行完整流水线")
    pipeline_parser.add_argument("--users", nargs="+", required=True, help="抖音用户主页链接")
    pipeline_parser.add_argument("--max-per-user", type=int, default=20, help="每个账号最多下载数量")
    pipeline_parser.add_argument("--min-likes", type=int, default=1000, help="最低点赞数")
    pipeline_parser.add_argument("--output", default="./douyin_analysis", help="输出目录")
    pipeline_parser.add_argument("--method", choices=["whisper", "groq", "yunwu"], default="whisper", help="识别方法")
    pipeline_parser.add_argument("--model", default="large-v3", help="Whisper 模型名称")
    pipeline_parser.add_argument("--groq-api-key", help="Groq API key（使用 groq 方法时需要）")
    pipeline_parser.add_argument("--yunwu-api-key", help="云雾 API key（使用 yunwu 方法时需要）")

    args = parser.parse_args()

    if args.command == "download":
        asyncio.run(download_videos(args))
    elif args.command == "transcribe":
        transcribe_videos(args)
    elif args.command == "pipeline":
        asyncio.run(run_pipeline(args))
    else:
        parser.print_help()


async def download_videos(args):
    """下载视频"""
    pipeline = DouyinViralPipeline(
        output_dir=args.output,
        min_likes=args.min_likes
    )

    videos = await pipeline.download_videos(
        user_urls=args.users,
        max_per_user=args.max_per_user
    )

    print(f"\n下载完成: {len(videos)} 个视频")


def transcribe_videos(args):
    """提取逐字稿"""
    import os

    # 设置 API key 环境变量
    if args.method == "groq" and args.groq_api_key:
        os.environ["GROQ_API_KEY"] = args.groq_api_key
    elif args.method == "yunwu" and args.yunwu_api_key:
        os.environ["YUNWU_API_KEY"] = args.yunwu_api_key

    pipeline = DouyinViralPipeline(output_dir=args.output)

    video_dir = Path(args.video_dir)
    video_paths = list(video_dir.glob("*.mp4"))

    transcripts = pipeline.extract_transcripts(
        video_paths=video_paths,
        method=args.method,
        model_name=args.model
    )

    print(f"\n提取完成: {len(transcripts)} 个逐字稿")


async def run_pipeline(args):
    """运行完整流水线"""
    import os

    # 设置 API key 环境变量
    if args.method == "groq" and args.groq_api_key:
        os.environ["GROQ_API_KEY"] = args.groq_api_key
    elif args.method == "yunwu" and args.yunwu_api_key:
        os.environ["YUNWU_API_KEY"] = args.yunwu_api_key

    pipeline = DouyinViralPipeline(
        output_dir=args.output,
        min_likes=args.min_likes
    )

    export_file = await pipeline.run_full_pipeline(
        user_urls=args.users,
        max_per_user=args.max_per_user,
        transcribe_method=args.method,
        model_name=args.model
    )

    print(f"\n✅ 完成！导出文件: {export_file}")
    print(f"\n接下来可以导入到爆款智能体:")
    print(f"python import_douyin_samples.py {export_file}")


if __name__ == "__main__":
    main()
