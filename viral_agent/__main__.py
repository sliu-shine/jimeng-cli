"""
爆款智能体 CLI 入口

用法：
  # 学习：从本地视频目录
  python -m viral_agent learn --dir ./对标爆款/0415 --niche 美食

  # 学习：手动输入文案（最简单）
  python -m viral_agent learn --text scripts.json --niche 情感

  # 学习：从抖音账号自动下载
  python -m viral_agent learn --account SEC_USER_ID --niche 美食 --min-likes 50000

  # 生成文案
  python -m viral_agent generate --topic "减肥不需要控制饮食" --niche 健康 --versions 3

  # 查看知识库状态
  python -m viral_agent stats
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="爆款文案智能体")
    subparsers = parser.add_subparsers(dest="command")

    # learn 子命令
    learn_parser = subparsers.add_parser("learn", help="学习爆款视频")
    learn_src = learn_parser.add_mutually_exclusive_group(required=True)
    learn_src.add_argument("--dir", help="本地视频目录路径")
    learn_src.add_argument("--text", help="文案JSON文件路径")
    learn_src.add_argument("--account", help="抖音账号 sec_user_id")
    learn_parser.add_argument("--niche", default="", help="赛道分类（如：美食、情感、干货）")
    learn_parser.add_argument("--min-likes", type=int, default=2000, help="最低点赞数筛选")
    learn_parser.add_argument("--max-videos", type=int, default=20, help="最多处理视频数")
    learn_parser.add_argument("--no-groq", action="store_true", help="使用本地Whisper而不是Groq")

    # generate 子命令
    gen_parser = subparsers.add_parser("generate", help="生成爆款文案")
    gen_parser.add_argument("--topic", required=True, help="视频主题")
    gen_parser.add_argument("--niche", default="", help="赛道分类")
    gen_parser.add_argument("--requirements", default="", help="额外要求")
    gen_parser.add_argument("--versions", type=int, default=3, help="生成版本数")

    # stats 子命令
    subparsers.add_parser("stats", help="查看知识库状态")

    args = parser.parse_args()

    if args.command == "learn":
        from .pipeline import learn_from_directory, learn_from_text, learn_from_douyin_account

        if args.dir:
            learn_from_directory(
                args.dir,
                niche=args.niche,
                min_likes=args.min_likes,
                use_groq=not args.no_groq,
            )
        elif args.text:
            with open(args.text, encoding="utf-8") as f:
                scripts = json.load(f)
            learn_from_text(scripts, niche=args.niche)
        elif args.account:
            learn_from_douyin_account(
                args.account,
                niche=args.niche,
                min_likes=args.min_likes,
                max_videos=args.max_videos,
            )

    elif args.command == "generate":
        from .agent import generate
        result = generate(
            topic=args.topic,
            niche=args.niche,
            requirements=args.requirements,
            versions=args.versions,
        )
        print(result)

    elif args.command == "stats":
        from . import knowledge_base as kb
        stats = kb.get_all_patterns()
        print(f"\n📊 {kb.get_stats()}")
        if stats["count"] > 0:
            print("\n钩子类型分布：")
            for k, v in sorted(stats["hook_types"].items(), key=lambda x: -x[1]):
                print(f"  {k}: {v}个")
            print(f"\n高频爆款元素：{', '.join(stats['top_viral_elements'][:10])}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
