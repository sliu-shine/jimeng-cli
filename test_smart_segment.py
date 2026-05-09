#!/usr/bin/env python3
"""
测试智能分段和提示词生成功能
"""
from viral_agent.text_segmenter import segment_by_sentences, format_segments_for_display, validate_segments

# 测试文案
test_script = """
狗狗做梦都想告诉你，它其实需要吃这3个习惯食物，会连毛发都越来越好，因为野生犬科动物吃猎物时，会连毛带骨一起吞，所以毛发营养就是用来把这些东西成团排出去的，而现在家养的狗因然不打猎了，但胃里还是会有毛发和食物残渣，而没有纤维素就很难排出，这些东西在胃里堆积，所以以前都是在家到处乱翻垃圾，出门后看到草就啃，但外面的草不够干净，因为你不知道是否有农药残留或者狗尿，所以最好的办法就是在家种一盆猫草，小麦苗或者燕麦苗都可以，狗狗天就能开花，底部还有纱网包裹，非常还有纱网包裹，这样狗狗就有吃不完的猫草了，推荐你试试。
"""

def test_segmentation():
    print("=" * 60)
    print("测试智能分段功能")
    print("=" * 60)

    # 测试分段
    segments = segment_by_sentences(
        text=test_script,
        target_duration=10,
        max_duration=15,
        chars_per_second=6.0,
    )

    print(f"\n✅ 分段成功！共 {len(segments)} 个段落\n")

    # 显示分段结果
    for seg in segments:
        print(f"段落 {seg['index']}: {seg['start_time']:.1f}s - {seg['end_time']:.1f}s ({seg['estimated_duration']:.1f}秒, {seg['char_count']}字)")
        print(f"  {seg['text'][:60]}{'...' if len(seg['text']) > 60 else ''}")
        print()

    # 验证分段
    validation = validate_segments(segments, max_duration=15)
    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)
    print(f"状态: {'✅ 通过' if validation['valid'] else '⚠️ 有警告'}")
    print(f"统计: {validation['stats']}")

    if validation['warnings']:
        print("\n警告:")
        for warning in validation['warnings']:
            print(f"  - {warning}")

    return segments


def test_display_format(segments):
    print("\n" + "=" * 60)
    print("格式化显示")
    print("=" * 60)
    display = format_segments_for_display(segments)
    print(display)


if __name__ == "__main__":
    segments = test_segmentation()
    test_display_format(segments)

    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)
    print("\n下一步：启动 UI 测试完整流程")
    print("运行命令: python viral_agent_ui.py")
