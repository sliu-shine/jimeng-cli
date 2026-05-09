#!/usr/bin/env python3
"""测试 text_segmenter 修复"""

from viral_agent.text_segmenter import segment_by_sentences_ai

# 测试文案
test_text = """
狗狗深夜偷吃狗粮的秘密。你知道吗，狗狗对食物有等级观念。
同样的狗粮，扔地上它吃得很快，手喂它就吃得很慢。
这是因为狗狗觉得掉地上的食物会被抢走，而手喂的食物是主人的爱。
"""

print("🧪 测试 AI 分段功能...\n")
print(f"测试文案：{test_text.strip()}\n")
print("=" * 60)

try:
    segments = segment_by_sentences_ai(
        text=test_text.strip(),
        target_duration=10,
        max_duration=15,
        chars_per_second=6.0,
    )

    print(f"\n✅ AI 分段成功！共 {len(segments)} 个段落：\n")

    for seg in segments:
        print(f"段落 {seg['index']}:")
        print(f"  时长: {seg['estimated_duration']:.1f}秒")
        print(f"  字数: {seg['char_count']}字")
        print(f"  内容: {seg['text']}")
        print()

except Exception as e:
    print(f"\n❌ 测试失败：{e}")
    import traceback
    traceback.print_exc()
