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

    # feedback 子命令
    feedback_parser = subparsers.add_parser("feedback", help="视频发布反馈学习")
    feedback_sub = feedback_parser.add_subparsers(dest="feedback_command")

    feedback_list = feedback_sub.add_parser("list", help="列出最近生成记录")
    feedback_list.add_argument("--limit", type=int, default=20)

    feedback_add = feedback_sub.add_parser("add", help="手动录入某条视频表现数据")
    feedback_add.add_argument("--generation-id", required=True, help="生成追踪ID")
    feedback_add.add_argument("--video-id", default="", help="平台视频ID")
    feedback_add.add_argument("--platform", default="douyin", help="平台")
    feedback_add.add_argument("--title", default="", help="视频标题")
    feedback_add.add_argument("--published-at", default="", help="发布时间")
    feedback_add.add_argument("--duration", type=float, default=None, help="视频时长，秒")
    feedback_add.add_argument("--views", type=int, default=0, help="播放量")
    feedback_add.add_argument("--likes", type=int, default=0, help="点赞数")
    feedback_add.add_argument("--comments", type=int, default=0, help="评论数")
    feedback_add.add_argument("--favorites", type=int, default=0, help="收藏数")
    feedback_add.add_argument("--shares", type=int, default=0, help="分享数")
    feedback_add.add_argument("--completion-rate", type=float, default=None, help="完播率，可填 11.01 或 0.1101")
    feedback_add.add_argument("--bounce-2s-rate", type=float, default=None, help="2s跳出率，可填 29.9 或 0.299")
    feedback_add.add_argument("--completion-5s-rate", type=float, default=None, help="5s完播率，可填 48.72 或 0.4872")
    feedback_add.add_argument("--avg-watch-seconds", type=float, default=None, help="平均播放时长，秒")
    feedback_add.add_argument("--avg-watch-ratio", type=float, default=None, help="平均播放占比，可填 26.25 或 0.2625")
    feedback_add.add_argument("--notes", default="", help="人工备注")
    feedback_add.add_argument("--analyze", action="store_true", help="录入后立即复盘")

    feedback_analyze = feedback_sub.add_parser("analyze", help="复盘某条视频反馈")
    feedback_analyze.add_argument("--generation-id", required=True, help="生成追踪ID")
    feedback_analyze.add_argument("--feedback-id", type=int, default=None, help="反馈记录ID，默认使用最新一条")
    feedback_analyze.add_argument("--json", action="store_true", help="输出JSON")

    feedback_context = feedback_sub.add_parser("context", help="查看最近反馈学习上下文")
    feedback_context.add_argument("--niche", default="", help="赛道")
    feedback_context.add_argument("--limit", type=int, default=10)
    feedback_context.add_argument("--json", action="store_true", help="输出JSON")

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

    elif args.command == "feedback":
        if args.feedback_command == "list":
            from .feedback import list_generations

            rows = list_generations(limit=args.limit)
            if not rows:
                print("还没有生成记录。先运行 generate 生成一条文案。")
            for item in rows:
                print(
                    f"{item['id']} · {item.get('generated_at', '')[:19]} · "
                    f"{item.get('niche') or '未填赛道'} · {item.get('topic') or '未命名主题'}"
                )

        elif args.feedback_command == "add":
            from .feedback import add_video_feedback
            from .feedback.analyzer import analyze_single_video, format_review_markdown

            feedback_id = add_video_feedback(
                generation_id=args.generation_id,
                video_id=args.video_id,
                platform=args.platform,
                title=args.title,
                published_at=args.published_at,
                duration_seconds=args.duration,
                views=args.views,
                likes=args.likes,
                comments=args.comments,
                favorites=args.favorites,
                shares=args.shares,
                completion_rate=args.completion_rate,
                bounce_2s_rate=args.bounce_2s_rate,
                completion_5s_rate=args.completion_5s_rate,
                avg_watch_seconds=args.avg_watch_seconds,
                avg_watch_ratio=args.avg_watch_ratio,
                notes=args.notes,
            )
            print(f"✅ 已录入反馈：feedback_id={feedback_id}")
            if args.analyze:
                review = analyze_single_video(args.generation_id, feedback_id=feedback_id)
                print()
                print(format_review_markdown(review))

        elif args.feedback_command == "analyze":
            from .feedback.analyzer import analyze_single_video, format_review_markdown

            review = analyze_single_video(args.generation_id, feedback_id=args.feedback_id)
            if args.json:
                print(json.dumps(review, ensure_ascii=False, indent=2))
            else:
                print(format_review_markdown(review))

        elif args.feedback_command == "context":
            from .feedback import build_learning_context

            context = build_learning_context(niche=args.niche, limit=args.limit)
            if args.json:
                print(json.dumps(context, ensure_ascii=False, indent=2))
            else:
                print(f"样本数：{context['sample_size']}")
                print(f"结果分布：{context['result_levels']}")
                print(f"must_use：{'；'.join(context['must_use'])}")
                print(f"prefer：{'；'.join(context['prefer'])}")
                print(f"avoid：{'；'.join(context['avoid'])}")
                print(f"experiment：{'；'.join(context['experiment'])}")
        else:
            feedback_parser.print_help()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
