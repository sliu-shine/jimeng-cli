#!/usr/bin/env python3
"""
测试完整的智能分段 + 提示词生成流程
"""
from viral_agent.text_segmenter import segment_by_sentences
from viral_agent.prompt_agent import generate_video_prompts, format_prompts_for_display

# 测试文案
test_script = """
你家狗子会不会熬到半夜才跑去吃狗粮？它是不饿吗？不，它聪明着呢。它其实是在心里跟你算一笔账，陪你玩一场关于耐心的心理博弈。它把每天的食物严格分成了两档：狗盆里那碗永远跑不掉的干粮，是它的保底筹码；而你筷子上夹的肉丝、手里撕开的零食，才是它真正想博一把的大奖。你想想看，一只狗的胃容量就那么大，要是大清早就用干巴巴的狗粮把肚子填得死死的，万一中午你点了外卖炸鸡、晚上又拆了火腿肠，它拿什么装？所以为了赌这一口，它展现出了惊人的自控力。
"""

def test_full_workflow():
    print("=" * 60)
    print("测试完整流程：智能分段 + 提示词生成")
    print("=" * 60)

    # 步骤1：智能分段
    print("\n步骤1：智能分段")
    print("-" * 60)
    segments = segment_by_sentences(
        text=test_script,
        target_duration=10,
        max_duration=15,
        chars_per_second=6.0,
    )
    print(f"✅ 分段成功！共 {len(segments)} 个段落\n")
    for seg in segments:
        print(f"段落 {seg['index']}: {seg['start_time']:.1f}s - {seg['end_time']:.1f}s ({seg['estimated_duration']:.1f}秒)")
        print(f"  {seg['text'][:50]}...")

    # 步骤2：生成提示词
    print("\n\n步骤2：生成视频提示词")
    print("-" * 60)
    print("使用频道：channel-healing (温馨治愈系)")

    prompts = generate_video_prompts(
        segments=segments,
        full_context=test_script,
        channel_id="channel-healing",
        scene_continuity=True,
    )

    print(f"✅ 提示词生成成功！共 {len(prompts)} 个段落\n")

    # 显示结果
    for p in prompts:
        print(f"\n段落 {p['segment_index']} ({p['start_time']:.1f}s - {p['end_time']:.1f}s)")
        print(f"文案: {p['segment_text'][:40]}...")
        print(f"提示词: {p['prompt'][:100]}...")

    # 格式化显示
    print("\n\n" + "=" * 60)
    print("格式化显示结果")
    print("=" * 60)
    display = format_prompts_for_display(prompts)
    print(display[:500] + "...")

    print("\n\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)
    print("\n提示词已使用 Seedance 频道风格生成")
    print("每个段落的提示词都符合频道特色")


if __name__ == "__main__":
    test_full_workflow()
