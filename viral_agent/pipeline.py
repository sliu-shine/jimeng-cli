"""
学习管道：把爆款视频批量导入知识库
支持：
  1. 视频文件目录（本地已下载的视频）
  2. 抖音账号 URL（自动下载爆款）
  3. 直接输入文案文本（手动录入）
"""
import os
import json
from pathlib import Path
from typing import Optional

from .transcriber import extract_audio, transcribe
from .analyzer import analyze_script
from . import knowledge_base as kb


def learn_from_directory(
    video_dir: str,
    niche: str = "",
    min_likes: int = 0,
    use_groq: bool = True,
):
    """
    从本地视频目录批量学习
    视频文件名格式建议: {video_id}_{likes}.mp4 或 任意名称
    同目录下如有 metadata.json 会自动读取点赞数等信息
    """
    video_dir = Path(video_dir)
    metadata_file = video_dir / "metadata.json"

    # 尝试读取 metadata
    metadata_map = {}
    if metadata_file.exists():
        with open(metadata_file) as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    metadata_map[item.get("video_id", "")] = item
            elif isinstance(data, dict):
                metadata_map = data

    # 找所有视频文件
    video_files = list(video_dir.glob("*.mp4")) + list(video_dir.glob("*.mov"))
    print(f"找到 {len(video_files)} 个视频文件")

    for video_path in video_files:
        video_id = video_path.stem
        meta = metadata_map.get(video_id, {})
        likes = meta.get("likes", meta.get("digg_count", 0))

        if min_likes and likes < min_likes:
            print(f"跳过 {video_id}（点赞 {likes} < {min_likes}）")
            continue

        print(f"\n处理: {video_path.name} ...")

        try:
            # 1. 提取音频
            audio_path = extract_audio(str(video_path))

            # 2. 转录
            print("  转录中...")
            script = transcribe(audio_path, use_groq=use_groq)
            print(f"  文案: {script[:80]}...")

            # 3. 分析
            print("  分析爆款模式...")
            analysis = analyze_script(script, likes=likes, niche=niche)

            # 4. 存入知识库
            kb.add_script(
                video_id=video_id,
                script=script,
                analysis=analysis,
                metadata={
                    "likes": likes,
                    "niche": niche,
                    "platform": meta.get("platform", "douyin"),
                    **meta,
                },
            )

            # 清理临时音频
            Path(audio_path).unlink(missing_ok=True)

        except Exception as e:
            print(f"  ❌ 处理失败: {e}")

    print(f"\n✅ 学习完成！{kb.get_stats()}")


def learn_from_text(
    scripts: list[dict],
    niche: str = "",
):
    """
    直接从文本学习（手动录入或从其他来源获取）
    scripts: [{"video_id": "xxx", "script": "文案内容", "likes": 10000, "niche": "美食"}, ...]
    """
    print(f"开始分析 {len(scripts)} 条文案...")
    for i, item in enumerate(scripts):
        video_id = item.get("video_id", f"manual_{i:04d}")
        script = item["script"]
        likes = item.get("likes", 0)
        item_niche = item.get("niche", niche)

        print(f"\n[{i+1}/{len(scripts)}] 分析: {video_id}")
        analysis = analyze_script(script, likes=likes, niche=item_niche)

        kb.add_script(
            video_id=video_id,
            script=script,
            analysis=analysis,
            metadata={
                "likes": likes,
                "niche": item_niche,
                "platform": item.get("platform", "manual"),
            },
        )

    print(f"\n✅ 全部完成！{kb.get_stats()}")


def learn_from_douyin_account(
    sec_user_id: str,
    niche: str = "",
    min_likes: int = 100000,
    max_videos: int = 20,
    api_base: str = "http://localhost:8080",
):
    """
    从抖音账号自动下载爆款并学习
    依赖: DouYin_TikTok_Download_API 本地服务
    """
    import httpx
    import yt_dlp
    import tempfile

    print(f"获取账号 {sec_user_id} 的爆款视频...")

    # 获取视频列表
    all_videos = []
    max_cursor = 0
    while len(all_videos) < max_videos * 3:  # 多拉一些，筛选后够用
        resp = httpx.get(
            f"{api_base}/api/douyin/web/fetch_user_post_videos",
            params={"sec_user_id": sec_user_id, "max_cursor": max_cursor, "count": 20},
            timeout=30,
        )
        data = resp.json()
        videos = data.get("aweme_list", [])
        if not videos:
            break
        all_videos.extend(videos)
        max_cursor = data.get("max_cursor", 0)
        if not data.get("has_more"):
            break

    # 筛选爆款
    hot_videos = [
        v for v in all_videos
        if v.get("statistics", {}).get("digg_count", 0) >= min_likes
    ]
    hot_videos.sort(key=lambda x: x.get("statistics", {}).get("digg_count", 0), reverse=True)
    hot_videos = hot_videos[:max_videos]

    print(f"筛选出 {len(hot_videos)} 个爆款（点赞 ≥ {min_likes:,}）")

    with tempfile.TemporaryDirectory() as tmpdir:
        for video in hot_videos:
            video_id = video["aweme_id"]
            likes = video["statistics"]["digg_count"]
            play_url = video["video"]["play_addr"]["url_list"][0]

            print(f"\n下载: {video_id}（点赞: {likes:,}）")
            video_path = Path(tmpdir) / f"{video_id}.mp4"

            try:
                # 下载视频
                with yt_dlp.YoutubeDL({
                    "outtmpl": str(video_path),
                    "quiet": True,
                }) as ydl:
                    ydl.download([play_url])

                # 转录 + 分析 + 存储
                audio_path = extract_audio(str(video_path))
                script = transcribe(audio_path)
                print(f"  文案: {script[:80]}...")

                analysis = analyze_script(script, likes=likes, niche=niche)
                kb.add_script(
                    video_id=video_id,
                    script=script,
                    analysis=analysis,
                    metadata={
                        "likes": likes,
                        "niche": niche,
                        "platform": "douyin",
                        "sec_user_id": sec_user_id,
                    },
                )
                Path(audio_path).unlink(missing_ok=True)

            except Exception as e:
                print(f"  ❌ 失败: {e}")

    print(f"\n✅ 全部完成！{kb.get_stats()}")
