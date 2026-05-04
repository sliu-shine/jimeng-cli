#!/usr/bin/env python3
"""
抖音视频下载器
支持通过用户主页链接批量下载爆款视频
"""
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

import aiohttp
import aiofiles


class DouyinDownloader:
    """抖音视频下载器"""

    # 使用开源API服务
    API_BASE = "https://api.douyin.wtf"

    def __init__(self, output_dir: str = "./douyin_videos"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def extract_sec_uid(self, user_url: str) -> Optional[str]:
        """从用户主页链接提取 sec_uid"""
        # 支持多种格式
        # https://www.douyin.com/user/MS4wLjABAAAA...
        # https://v.douyin.com/xxx (短链接需要先解析)
        match = re.search(r'user/([^/?]+)', user_url)
        if match:
            return match.group(1)
        return None

    async def get_user_videos(
        self,
        sec_uid: str,
        max_count: int = 50,
        min_likes: int = 100000
    ) -> List[Dict[str, Any]]:
        """
        获取用户的视频列表

        Args:
            sec_uid: 用户的 sec_uid
            max_count: 最多获取多少个视频
            min_likes: 最低点赞数筛选（默认10万+）

        Returns:
            视频信息列表
        """
        if not self.session:
            raise RuntimeError("请使用 async with 上下文管理器")

        videos = []
        cursor = 0
        page_size = 20

        while len(videos) < max_count:
            try:
                # 调用API获取用户作品列表
                url = f"{self.API_BASE}/api/douyin/web/fetch_user_post_videos"
                params = {
                    "sec_user_id": sec_uid,
                    "count": page_size,
                    "cursor": cursor
                }

                async with self.session.get(url, params=params, timeout=30) as resp:
                    if resp.status != 200:
                        print(f"API请求失败: {resp.status}")
                        break

                    data = await resp.json()

                    # 检查响应格式
                    if data.get("code") != 0:
                        print(f"API返回错误: {data.get('message')}")
                        break

                    aweme_list = data.get("data", {}).get("aweme_list", [])
                    if not aweme_list:
                        break

                    # 筛选爆款视频
                    for item in aweme_list:
                        stats = item.get("statistics", {})
                        likes = stats.get("digg_count", 0)

                        if likes >= min_likes:
                            video_info = {
                                "aweme_id": item.get("aweme_id"),
                                "desc": item.get("desc", ""),
                                "create_time": item.get("create_time"),
                                "likes": likes,
                                "comments": stats.get("comment_count", 0),
                                "shares": stats.get("share_count", 0),
                                "video_url": self._extract_video_url(item),
                                "cover_url": self._extract_cover_url(item),
                                "duration": item.get("video", {}).get("duration", 0) / 1000,  # 转为秒
                            }
                            videos.append(video_info)

                            if len(videos) >= max_count:
                                break

                    # 检查是否还有更多
                    has_more = data.get("data", {}).get("has_more", False)
                    if not has_more:
                        break

                    cursor = data.get("data", {}).get("cursor", cursor + page_size)

                    # 避免请求过快
                    await asyncio.sleep(1)

            except Exception as e:
                print(f"获取视频列表出错: {e}")
                break

        return videos

    def _extract_video_url(self, item: Dict) -> str:
        """提取视频下载链接"""
        video = item.get("video", {})
        play_addr = video.get("play_addr", {})
        url_list = play_addr.get("url_list", [])
        return url_list[0] if url_list else ""

    def _extract_cover_url(self, item: Dict) -> str:
        """提取封面图链接"""
        video = item.get("video", {})
        cover = video.get("cover", {})
        url_list = cover.get("url_list", [])
        return url_list[0] if url_list else ""

    async def download_video(
        self,
        video_info: Dict[str, Any],
        save_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """
        下载单个视频

        Args:
            video_info: 视频信息字典
            save_dir: 保存目录（可选）

        Returns:
            下载后的文件路径
        """
        if not self.session:
            raise RuntimeError("请使用 async with 上下文管理器")

        save_dir = save_dir or self.output_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        aweme_id = video_info["aweme_id"]
        video_url = video_info["video_url"]

        if not video_url:
            print(f"视频 {aweme_id} 没有下载链接")
            return None

        # 文件名：aweme_id + 点赞数
        likes = video_info["likes"]
        filename = f"{aweme_id}_{likes}likes.mp4"
        filepath = save_dir / filename

        # 如果已存在则跳过
        if filepath.exists():
            print(f"视频已存在，跳过: {filename}")
            return filepath

        try:
            print(f"下载视频: {filename}")
            async with self.session.get(video_url, timeout=60) as resp:
                if resp.status != 200:
                    print(f"下载失败: {resp.status}")
                    return None

                async with aiofiles.open(filepath, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        await f.write(chunk)

            # 保存视频元数据
            meta_file = filepath.with_suffix('.json')
            async with aiofiles.open(meta_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(video_info, ensure_ascii=False, indent=2))

            print(f"下载完成: {filename}")
            return filepath

        except Exception as e:
            print(f"下载视频 {aweme_id} 出错: {e}")
            if filepath.exists():
                filepath.unlink()
            return None

    async def download_user_viral_videos(
        self,
        user_url: str,
        max_count: int = 20,
        min_likes: int = 100000
    ) -> List[Path]:
        """
        下载用户的爆款视频

        Args:
            user_url: 用户主页链接
            max_count: 最多下载数量
            min_likes: 最低点赞数

        Returns:
            下载成功的视频文件路径列表
        """
        # 提取 sec_uid
        sec_uid = self.extract_sec_uid(user_url)
        if not sec_uid:
            print(f"无法从链接提取 sec_uid: {user_url}")
            return []

        print(f"获取用户 {sec_uid} 的视频列表...")
        videos = await self.get_user_videos(sec_uid, max_count, min_likes)
        print(f"找到 {len(videos)} 个爆款视频（点赞 >= {min_likes}）")

        if not videos:
            return []

        # 按点赞数排序
        videos.sort(key=lambda x: x["likes"], reverse=True)

        # 创建用户专属目录
        user_dir = self.output_dir / sec_uid
        user_dir.mkdir(parents=True, exist_ok=True)

        # 并发下载（限制并发数）
        downloaded = []
        semaphore = asyncio.Semaphore(3)  # 最多3个并发下载

        async def download_with_semaphore(video_info):
            async with semaphore:
                return await self.download_video(video_info, user_dir)

        tasks = [download_with_semaphore(v) for v in videos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Path):
                downloaded.append(result)

        print(f"成功下载 {len(downloaded)}/{len(videos)} 个视频")
        return downloaded


async def main():
    """测试示例"""
    # 示例：下载某个账号的爆款视频
    user_url = "https://www.douyin.com/user/MS4wLjABAAAA..."  # 替换为实际链接

    async with DouyinDownloader(output_dir="./douyin_videos") as downloader:
        videos = await downloader.download_user_viral_videos(
            user_url=user_url,
            max_count=20,
            min_likes=100000  # 10万点赞以上
        )

        print(f"\n下载完成，共 {len(videos)} 个视频")
        for video_path in videos:
            print(f"  - {video_path}")


if __name__ == "__main__":
    asyncio.run(main())
