#!/usr/bin/env python3
"""
测试新的目录结构
"""
from pathlib import Path

def analyze_directory_structure(video_dir: str = "douyin_videos"):
    """分析视频目录结构"""
    video_dir = Path(video_dir)

    print("=" * 70)
    print("视频目录结构分析")
    print("=" * 70)

    # 统计
    total_videos = 0
    accounts = {}
    old_structure = 0
    new_structure = 0

    # 遍历所有 JSON 文件
    for json_file in video_dir.rglob("*.json"):
        if json_file.stem.endswith('.transcript'):
            continue

        total_videos += 1
        relative_path = json_file.relative_to(video_dir)
        path_parts = relative_path.parts

        # 判断目录结构
        if len(path_parts) >= 3:
            # 新结构：账号名/视频标题/文件
            account_name = path_parts[0]
            video_folder = path_parts[1]
            new_structure += 1

            if account_name not in accounts:
                accounts[account_name] = []
            accounts[account_name].append(video_folder)
        else:
            # 旧结构：标签/文件 或 文件
            old_structure += 1

    print(f"\n📊 总体统计:")
    print(f"  总视频数: {total_videos}")
    print(f"  新结构 (账号/标题): {new_structure}")
    print(f"  旧结构 (标签/文件): {old_structure}")

    if accounts:
        print(f"\n👥 账号分布 (新结构):")
        for account, videos in sorted(accounts.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"  {account}: {len(videos)} 个视频")
            # 显示前3个视频标题
            for video in videos[:3]:
                print(f"    - {video[:60]}{'...' if len(video) > 60 else ''}")
            if len(videos) > 3:
                print(f"    ... 还有 {len(videos) - 3} 个视频")

    print("\n" + "=" * 70)

    # 显示目录结构示例
    if new_structure > 0:
        print("\n📁 新结构示例:")
        print("douyin_videos/")
        for account, videos in list(accounts.items())[:2]:
            print(f"├── {account}/")
            for video in videos[:2]:
                print(f"│   ├── {video}/")
                print(f"│   │   ├── [赞数]_{video}_[ID].m4a")
                print(f"│   │   ├── [赞数]_{video}_[ID].json")
                print(f"│   │   └── [赞数]_{video}_[ID].transcript.json")
            if len(videos) > 2:
                print(f"│   └── ... 还有 {len(videos) - 2} 个视频")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="分析视频目录结构")
    parser.add_argument("--video-dir", default="douyin_videos", help="视频目录路径")

    args = parser.parse_args()

    analyze_directory_structure(args.video_dir)
