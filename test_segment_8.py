#!/usr/bin/env python3
"""
专门测试段落8（深夜吃狗粮）的分镜生成
"""
from viral_agent.text_segmenter import segment_by_sentences
from viral_agent.prompt_agent import generate_video_prompts

# 完整测试文案
test_script = """
为什么狗宁可饿一天,也要等你给它喂?你以为它只是嘴馋吗?这背后藏着一个真相,很多人听完都会沉默。狗这种动物啊,天生就有囤积意识和等级观念。在它的认知里,食物分三个档次:最低档是狗粮,那是"反正饿不死"的保底口粮;中档是你吃剩的、掉在地上的,那叫"意外之财";最高档才是你亲手喂给它的,那代表着"我在这个家的地位被认可了"。所以当它拒绝吃狗粮的时候,本质上不是在挑食,而是在等一个信号——等你承认它是家庭成员,而不是一只只配吃工业饲料的动物。你有没有发现,同样一块鸡胸肉,你扔地上它吃得很快,但你用手喂它就会吃得特别慢、特别小心?因为那一刻它感受到的不是食物本身,而是被重视的感觉。所以它宁可饿着,也要赌你会在某个时刻想起它、分给它一口。这场赌局从早上你出门就开始了:它会记住你出门前有没有摸它的头,会判断你今天心情好不好,会根据你回家的脚步声预测今晚有没有好吃的。如果一整天都没等到,它也不会闹,只会在深夜你睡着以后,悄悄走到狗盆前把那顿狗粮吃掉,就像一个没等到父母夸奖的小孩,默默把作业写完。其实它要的从来不是那口吃的,它要的是你弯下腰、看着它、把食物递到它嘴边的那三秒钟。那三秒钟里,它觉得自己被爱着。
"""

def test_segment_8():
    print("=" * 60)
    print("专门测试段落8：深夜吃狗粮场景")
    print("=" * 60)

    # 智能分段
    segments = segment_by_sentences(
        text=test_script,
        target_duration=10,
        max_duration=15,
        chars_per_second=6.0,
    )

    print(f"\n总共 {len(segments)} 个段落")

    # 找到段落8
    segment_8 = None
    for seg in segments:
        if "深夜" in seg["text"] and "狗盆" in seg["text"]:
            segment_8 = seg
            break

    if not segment_8:
        print("❌ 未找到段落8（深夜吃狗粮）")
        return

    print(f"\n找到段落8（段落 {segment_8['index']}）：")
    print(f"文案: {segment_8['text']}")
    print(f"时长: {segment_8['estimated_duration']:.1f}秒")

    # 只生成段落8的提示词
    print("\n" + "=" * 60)
    print("生成段落8的视频提示词...")
    print("=" * 60)

    prompts = generate_video_prompts(
        segments=[segment_8],
        full_context=test_script,
        channel_id="channel-healing",
        scene_continuity=True,
    )

    if not prompts:
        print("❌ 提示词生成失败")
        return

    prompt = prompts[0]

    print("\n" + "=" * 60)
    print("段落8 完整提示词")
    print("=" * 60)
    print(prompt["prompt"])

    print("\n" + "=" * 60)
    print("关键检查")
    print("=" * 60)

    # 检查关键词
    prompt_text = prompt["prompt"].lower()

    checks = {
        "✓ 包含'深夜'或'夜晚'": any(word in prompt_text for word in ["深夜", "夜晚", "月光", "夜色"]),
        "✓ 包含'走'或'起身'": any(word in prompt_text for word in ["走", "起身", "站起", "踏出"]),
        "✓ 包含'狗盆'或'狗粮'": any(word in prompt_text for word in ["狗盆", "狗粮", "食物"]),
        "✓ 包含'吃'的动作": any(word in prompt_text for word in ["吃", "咀嚼", "吞咽", "进食"]),
        "✗ 不应该包含'睡'": "睡" not in prompt_text or "睡着" in prompt_text and "主人" in prompt_text,
    }

    all_passed = True
    for check, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 段落8 分镜生成正确！")
        print("画面应该是：深夜狗狗起身走到狗盆前吃狗粮")
    else:
        print("⚠️ 段落8 分镜可能有问题，请检查")
    print("=" * 60)


if __name__ == "__main__":
    test_segment_8()
