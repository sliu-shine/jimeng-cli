#!/usr/bin/env python3
"""
完整的抖音爆款视频分析流水线
下载视频 → 提取逐字稿 → 导入到爆款智能体
"""
import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from .downloader import DouyinDownloader
from .transcriber import batch_extract_transcripts


class DouyinViralPipeline:
    """抖音爆款视频分析流水线"""

    def __init__(
        self,
        output_dir: str = "./douyin_analysis",
        min_likes: int = 1000
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.min_likes = min_likes

    async def download_videos(
        self,
        user_urls: List[str],
        max_per_user: int = 20
    ) -> List[Path]:
        """
        批量下载多个账号的爆款视频

        Args:
            user_urls: 用户主页链接列表
            max_per_user: 每个账号最多下载数量

        Returns:
            所有下载的视频路径
        """
        all_videos = []

        async with DouyinDownloader(output_dir=str(self.output_dir / "videos")) as downloader:
            for user_url in user_urls:
                print(f"\n处理账号: {user_url}")
                videos = await downloader.download_user_viral_videos(
                    user_url=user_url,
                    max_count=max_per_user,
                    min_likes=self.min_likes
                )
                all_videos.extend(videos)

        return all_videos

    def extract_transcripts(
        self,
        video_paths: Optional[List[Path]] = None,
        method: str = "whisper",
        model_name: str = "large-v3"
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量提取视频逐字稿

        Args:
            video_paths: 视频路径列表（可选，默认处理所有视频）
            method: 识别方法（whisper/groq）
            model_name: Whisper 模型名称

        Returns:
            逐字稿结果字典
        """
        if video_paths is None:
            # 扫描所有视频目录
            video_dir = self.output_dir / "videos"
            video_paths = list(video_dir.rglob("*.mp4"))

        print(f"\n开始提取 {len(video_paths)} 个视频的逐字稿...")

        results = {}
        for video_path in video_paths:
            try:
                from .transcriber import extract_transcript
                result = extract_transcript(video_path, method, model_name)
                results[str(video_path)] = result
            except Exception as e:
                print(f"提取 {video_path.name} 失败: {e}")

        return results

    def export_for_viral_agent(
        self,
        transcripts: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Path:
        """
        导出为爆款智能体可用的格式

        Args:
            transcripts: 逐字稿字典（可选，自动加载）

        Returns:
            导出文件路径
        """
        if transcripts is None:
            # 加载所有已有的逐字稿
            transcripts = {}
            video_dir = self.output_dir / "videos"
            for transcript_file in video_dir.rglob("*.transcript.json"):
                with open(transcript_file, 'r', encoding='utf-8') as f:
                    video_name = transcript_file.stem.replace('.transcript', '')
                    transcripts[video_name] = json.load(f)

        # 转换为爆款智能体格式
        viral_samples = []
        for video_path, transcript in transcripts.items():
            # 加载视频元数据
            video_path_obj = Path(video_path)
            meta_file = video_path_obj.with_suffix('.json')

            metadata = {}
            if meta_file.exists():
                with open(meta_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

            sample = {
                "text": transcript["text"],
                "metadata": {
                    "source": "douyin",
                    "aweme_id": metadata.get("aweme_id", ""),
                    "likes": metadata.get("likes", 0),
                    "comments": metadata.get("comments", 0),
                    "shares": metadata.get("shares", 0),
                    "duration": metadata.get("duration", 0),
                    "desc": metadata.get("desc", ""),
                    "video_path": str(video_path)
                }
            }
            viral_samples.append(sample)

        # 按点赞数排序
        viral_samples.sort(key=lambda x: x["metadata"]["likes"], reverse=True)

        # 保存
        export_file = self.output_dir / "viral_samples.json"
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(viral_samples, f, ensure_ascii=False, indent=2)

        print(f"\n导出完成: {export_file}")
        print(f"共 {len(viral_samples)} 个爆款样本")

        return export_file

    async def run_full_pipeline(
        self,
        user_urls: List[str],
        max_per_user: int = 20,
        transcribe_method: str = "whisper",
        model_name: str = "large-v3"
    ) -> Path:
        """
        运行完整流水线

        Args:
            user_urls: 抖音账号链接列表
            max_per_user: 每个账号最多下载数量
            transcribe_method: 转录方法
            model_name: Whisper 模型

        Returns:
            导出文件路径
        """
        print("=" * 60)
        print("抖音爆款视频分析流水线")
        print("=" * 60)

        # 1. 下载视频
        print("\n[步骤 1/3] 下载爆款视频")
        videos = await self.download_videos(user_urls, max_per_user)
        print(f"下载完成: {len(videos)} 个视频")

        # 2. 提取逐字稿
        print("\n[步骤 2/3] 提取视频逐字稿")
        transcripts = self.extract_transcripts(videos, transcribe_method, model_name)
        print(f"提取完成: {len(transcripts)} 个逐字稿")

        # 3. 导出数据
        print("\n[步骤 3/3] 导出为爆款智能体格式")
        export_file = self.export_for_viral_agent(transcripts)

        print("\n" + "=" * 60)
        print("流水线完成！")
        print(f"导出文件: {export_file}")
        print("=" * 60)

        return export_file


async def main():
    """使用示例"""
    # 配置要分析的抖音账号
    user_urls = [
        "https://www.douyin.com/user/MS4wLjABAAAA...",  # 账号1
        "https://www.douyin.com/user/MS4wLjABAAAA...",  # 账号2
    ]

    pipeline = DouyinViralPipeline(
        output_dir="./douyin_analysis",
        min_likes=1000
    )

    export_file = await pipeline.run_full_pipeline(
        user_urls=user_urls,
        max_per_user=20,
        transcribe_method="whisper",  # 或 "groq"
        model_name="large-v3"
    )

    print(f"\n接下来可以将 {export_file} 导入到爆款智能体:")
    print(f"python -m viral_agent learn --from-file {export_file}")


if __name__ == "__main__":
    asyncio.run(main())
