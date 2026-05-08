#!/usr/bin/env python3
"""
从 douyin_videos 目录导入视频到知识库
支持自动转录和分析
"""
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from douyin_downloader.transcriber import extract_transcript
from viral_agent.analyzer import analyze_script
from viral_agent import knowledge_base

MEDIA_SUFFIXES = {".mp4", ".m4a", ".mp3", ".aac", ".wav"}


def load_json_file(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def transcript_candidates(media_file: Path) -> list[Path]:
    return [
        media_file.parent / "transcript.json",
        media_file.with_suffix(".transcription.json"),
        media_file.with_suffix(".transcript.json"),
        media_file.with_suffix(".txt"),
    ]


def read_existing_transcript(media_file: Path) -> tuple[str, Path | None]:
    for transcript_file in transcript_candidates(media_file):
        if not transcript_file.exists():
            continue

        if transcript_file.suffix == ".txt":
            text = transcript_file.read_text(encoding="utf-8").strip()
        else:
            data = load_json_file(transcript_file)
            text = str(data.get("text") or data.get("transcript") or "").strip()
            if not text and isinstance(data.get("segments"), list):
                text = "".join(
                    str(segment.get("text") or "")
                    for segment in data["segments"]
                    if isinstance(segment, dict)
                ).strip()

        if text:
            return text, transcript_file

    return "", None


def extract_likes_from_filename(media_file: Path) -> int:
    match = re.search(r"\[(\d+(?:\.\d+)?)(w|W|万)?赞\]", media_file.name)
    if match:
        value = float(match.group(1))
        if match.group(2):
            value *= 10000
        return int(value)
    return 0


def media_metadata(media_file: Path) -> dict:
    metadata = load_json_file(media_file.with_suffix(".json"))
    metadata.setdefault("video_id", metadata.get("videoId") or metadata.get("aweme_id") or media_file.stem)
    metadata.setdefault("likes", extract_likes_from_filename(media_file))
    metadata.setdefault("title", media_file.stem)
    return metadata


def source_account_from_path(media_file: Path, root: Path) -> str:
    try:
        rel = media_file.relative_to(root)
    except ValueError:
        return ""
    return rel.parts[0] if len(rel.parts) > 1 else ""


def engagement_level(likes: int) -> str:
    if likes >= 100000:
        return "super_viral"
    if likes >= 10000:
        return "viral"
    if likes >= 3000:
        return "strong"
    if likes >= 1000:
        return "normal"
    return "unknown"


def split_tags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lstrip("#") for item in value if str(item).strip()]
    text = str(value or "")
    return [tag.strip().lstrip("#") for tag in re.split(r"[,，#\s]+", text) if tag.strip()]


def infer_channel(title: str, tags: list[str], account: str) -> str:
    text = " ".join([title, account, *tags])
    if any(word in text for word in ["训练", "训犬", "边界", "纠正", "规矩", "护官"]):
        return "训犬干货"
    if any(word in text for word in ["心理", "行为", "为什么", "原因", "冷知识", "科普", "科学养狗", "经验分享", "宇宙"]):
        return "宠物科普"
    if any(word in text for word in ["陪伴", "一生", "爱", "治愈", "情绪", "报恩"]):
        return "情绪陪伴"
    if any(word in text for word in ["猫", "英短", "蓝猫", "布偶"]):
        return "猫咪知识"
    if any(word in text for word in ["第", "犬", "动物解说", "品种"]):
        return "动物解说"
    return "抖音短视频"


def media_preference(media_file: Path) -> tuple[int, int, int]:
    """同一 video_id 有多个媒体时，优先选已有转录的音频文件。"""
    has_transcript = 1 if read_existing_transcript(media_file)[0] else 0
    suffix_score = {
        ".m4a": 5,
        ".mp3": 4,
        ".aac": 3,
        ".wav": 2,
        ".mp4": 1,
    }.get(media_file.suffix.lower(), 0)
    return has_transcript, suffix_score, int(media_file.stat().st_mtime)


def dedupe_media_files(media_files: list[Path]) -> tuple[list[Path], int]:
    selected: dict[str, Path] = {}
    duplicate_count = 0
    for media_file in media_files:
        video_id = str(media_metadata(media_file).get("video_id") or media_file.stem)
        existing = selected.get(video_id)
        if existing is None:
            selected[video_id] = media_file
            continue
        duplicate_count += 1
        if media_preference(media_file) > media_preference(existing):
            selected[video_id] = media_file
    return list(selected.values()), duplicate_count


async def import_videos(
    video_dir: str,
    method: str = "whisper",
    groq_api_key: str = None,
    transcribe_missing: bool = True,
    dry_run: bool = False,
    account_filter: str = "",
    limit: int = 0,
):
    """
    导入视频目录到知识库

    Args:
        video_dir: 视频目录路径
        method: 转录方法 (whisper/groq)
        groq_api_key: Groq API key
        transcribe_missing: 没有转录文件时是否自动转录
        dry_run: 只预检，不分析、不入库
        account_filter: 只导入指定一级账号目录
        limit: 最多处理多少条去重后视频
    """
    video_path = Path(video_dir)

    if not video_path.exists():
        print(f"❌ 目录不存在: {video_dir}")
        return

    # 查找所有可转录媒体文件，兼容 账号名/视频标题/文件 的目录结构
    video_files = [
        path for path in video_path.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
    ]
    raw_media_count = len(video_files)
    video_files, duplicate_count = dedupe_media_files(video_files)
    if account_filter:
        video_files = [
            path for path in video_files
            if source_account_from_path(path, video_path) == account_filter
        ]
    if limit and limit > 0:
        video_files = video_files[:limit]

    if not video_files:
        print(f"❌ 未找到媒体文件: {video_dir}")
        return

    print("=" * 70)
    print(f"找到 {raw_media_count} 个媒体文件，去重后 {len(video_files)} 个视频")
    if duplicate_count:
        print(f"跳过同 video_id 重复媒体: {duplicate_count} 个")
    if account_filter:
        print(f"账号筛选: {account_filter}")
    if limit and limit > 0:
        print(f"数量限制: {limit}")
    print("=" * 70)

    success_count = 0

    for i, video_file in enumerate(video_files, 1):
        print(f"\n[{i}/{len(video_files)}] 处理: {video_file.name}")

        metadata = media_metadata(video_file)
        source_account = str(metadata.get("author") or metadata.get("account_name") or source_account_from_path(video_file, video_path))

        # 检查是否已有转录文件
        transcript, transcript_file = read_existing_transcript(video_file)
        if transcript:
            print(f"  ✓ 使用已有转录文件: {transcript_file.name}")
        else:
            if not transcribe_missing:
                print("  ⏭️  未找到转录文件，已按 --no-transcribe 跳过")
                continue
            print(f"  🔄 转录中（{method}）...")
            result = extract_transcript(
                video_path=video_file,
                method=method,
                model_name="base" if method == "whisper" else "large-v3"
            )
            transcript = result.get("text", "")

            if transcript:
                # 保存转录结果
                transcript_file = video_file.parent / "transcript.json"
                with open(transcript_file, "w", encoding="utf-8") as f:
                    json.dump({"text": transcript}, f, ensure_ascii=False, indent=2)
                print(f"  ✅ 转录完成: {len(transcript)} 字符")
            else:
                print("  ❌ 转录失败，跳过")
                continue

        # 明确标记为错误数据才跳过；已有转录文本默认可导入。
        if video_file.with_suffix('.json').exists():
            transcription_verified = metadata.get('transcription_verified')
            if transcription_verified is False:
                print("  ⏭️  已标记为错误数据，跳过")
                continue

        likes = int(metadata.get("likes") or 0)
        tags = split_tags(metadata.get("tags"))
        title = str(metadata.get("title") or video_file.stem)
        channel = str(metadata.get("channel") or metadata.get("niche") or infer_channel(title, tags, source_account))
        level = engagement_level(likes)
        if dry_run:
            print(f"  ✅ 可导入预检通过: {len(transcript)} 字符 | 账号: {source_account or '-'} | 互动: {likes}({level}) | 频道: {channel}")
            success_count += 1
            continue

        # 分析爆款模式
        print("  🔄 分析爆款模式...")
        niche = channel
        try:
            analysis = analyze_script(
                transcript,
                likes=likes,
                niche=niche,
                source_account=source_account,
                tags=tags,
            )
        except Exception as exc:
            print(f"  ❌ 分析失败，跳过: {exc}")
            continue

        if not analysis:
            print("  ❌ 分析失败，跳过")
            continue

        # 导入知识库
        video_id = str(metadata.get("video_id") or video_file.stem)

        knowledge_base.add_script(
            video_id=video_id,
            script=transcript,
            analysis=analysis,
            metadata={
                "source": "douyin_selenium",
                "likes": likes,
                "engagement_level": level,
                "niche": niche,
                "channel": channel,
                "source_account": source_account,
                "title": title,
                "author": metadata.get("author", source_account),
                "tags": ",".join(tags),
                "media_path": str(video_file),
                "transcript_path": str(transcript_file) if transcript_file else "",
                "video_url": metadata.get("video_url", ""),
                "media_type": metadata.get("media_type", video_file.suffix.lower().lstrip(".")),
            }
        )

        print(f"  ✅ 已导入知识库")
        print(f"     钩子类型: {analysis.get('hook_type', 'N/A')}")
        print(f"     钩子公式: {analysis.get('hook_formula', 'N/A')}")

        success_count += 1

    # 显示统计
    print("\n" + "=" * 70)
    action = "预检完成" if dry_run else "导入完成"
    print(f"✅ {action}: {success_count}/{len(video_files)} 个视频")
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
    parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help="只导入已有 transcript.json/.transcription.json/.transcript.json/.txt，不自动转录缺失文件",
    )
    parser.add_argument("--dry-run", action="store_true", help="只预检可导入数量，不调用 AI 分析、不写入知识库")
    parser.add_argument("--account", default="", help="只处理指定一级账号目录，例如：狗狗执行官-Kiki")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条去重后视频，用于小批量试跑")

    args = parser.parse_args()

    asyncio.run(import_videos(
        args.video_dir,
        method=args.method,
        groq_api_key=args.groq_api_key,
        transcribe_missing=not args.no_transcribe,
        dry_run=args.dry_run,
        account_filter=args.account,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
