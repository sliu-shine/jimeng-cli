#!/usr/bin/env python3
"""
测试 AI 生成定制分镜功能
"""
from viral_agent.text_segmenter import segment_by_sentences
from viral_agent.prompt_agent import generate_video_prompts

# 测试文案 - 包含段落8的关键场景
test_script = """
为什么狗宁可饿一天,也要等你给它喂?在它的认知里,食物分三个档次:最低档是狗粮,那是"反正饿不死"的保底口粮;中档是你吃剩的、掉在地上的,那叫"意外之财";最高档才是你亲手喂给它的。你有没有发现,同样一块鸡胸肉,你扔地上它吃得很快,但你用手喂它就会吃得特别慢、特别小心?如果一整天都没等到,它也不会闹,只会在深夜你睡着以后,悄悄走到狗盆前把那顿狗粮吃掉,就像一个没等到父母夸奖的小孩,默默把作业写完。
"""

def test_ai_storyboard():
    print("=" * 60)
    print("测试 AI 生成定制分镜")
    print("=" * 60)

    # 步骤1：智能分段
    print("\n步骤1：智能分段")
    segments = segment_by_sentences(
        text=test_script,
        target_duration=10,
        max_duration=15,
        chars_per_second=6.0,
    )
    print(f"✅ 分段成功！共 {len(segments)} 个段落\n")

    # 只测试前3个段落（节省时间和API调用）
    test_segments = segments[:3]

    print(f"测试前 {len(test_segments)} 个段落：")
    for seg in test_segments:
        print(f"  段落 {seg['index']}: {seg['text'][:40]}...")

    # 步骤2：生成提示词（使用 AI 生成分镜）
    print("\n步骤2：使用 AI 生成定制分镜")
    print("-" * 60)

    try:
        prompts = generate_video_prompts(
            segments=test_segments,
            full_context=test_script,
            channel_id="channel-healing",
            scene_continuity=True,
        )

        print("\n" + "=" * 60)
        print("生成结果")
        print("=" * 60)

        for p in prompts:
            print(f"\n段落 {p['segment_index']}")
            print(f"文案: {p['segment_text'][:50]}...")
            print(f"提示词预览: {p['prompt'][:200]}...")
            print()

        print("✅ 测试完成！")
        print("\n关键检查点：")
        print("1. 分镜是否根据文案内容定制？")
        print("2. 是否避免了重复的模板？")
        print("3. 段落8是否正确画出'深夜吃狗粮'而不是'睡觉'？")

    except Exception as exc:
        print(f"\n❌ 测试失败：{exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_ai_storyboard()
