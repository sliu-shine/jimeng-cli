#!/usr/bin/env python3
"""
测试 AI 智能分段功能
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from viral_agent.text_segmenter import segment_by_sentences_ai, segment_by_sentences


def test_ai_vs_algorithm():
    """对比 AI 分段和算法分段"""

    text = """你知道吗？狗狗对食物的态度，藏着它对你的爱。
同样的狗粮，扔在地上，它吃得飞快，好像怕被抢走。
但如果你用手喂，它会吃得很慢，甚至舔你的手心。
这不是因为味道变了，而是因为，它舍不得这顿饭结束。
在狗狗心里，食物分三档：狗粮、掉在地上的、你手里的。
前两种填饱肚子，最后一种填满心。
它知道，吃完了，你就会离开。
所以它故意磨蹭，想让这一刻再长一点。
深夜，狗狗会偷偷起来吃狗粮，因为那时候，没人陪它。"""

    print("=" * 80)
    print("📝 测试文案")
    print("=" * 80)
    print(text)
    print()

    # 算法分段
    print("=" * 80)
    print("⚡ 算法分段结果")
    print("=" * 80)
    algo_segments = segment_by_sentences(text, target_duration=10, max_duration=15)
    for seg in algo_segments:
        print(f"\n段落 {seg['index']} ({seg['estimated_duration']}秒, {seg['char_count']}字)")
        print(f"时间轴: {seg['start_time']}s - {seg['end_time']}s")
        print(f"文案: {seg['text']}")

    print(f"\n总计: {len(algo_segments)} 个段落")

    # AI 智能分段
    print("\n" + "=" * 80)
    print("🤖 AI 智能分段结果")
    print("=" * 80)
    ai_segments = segment_by_sentences_ai(text, target_duration=10, max_duration=15)
    for seg in ai_segments:
        print(f"\n段落 {seg['index']} ({seg['estimated_duration']}秒, {seg['char_count']}字)")
        print(f"时间轴: {seg['start_time']}s - {seg['end_time']}s")
        print(f"文案: {seg['text']}")

    print(f"\n总计: {len(ai_segments)} 个段落")

    # 对比分析
    print("\n" + "=" * 80)
    print("📊 对比分析")
    print("=" * 80)
    print(f"算法分段: {len(algo_segments)} 个段落")
    print(f"AI 分段: {len(ai_segments)} 个段落")
    print()
    print("关键差异：")
    print("- 算法分段：按句子边界切分，快速但可能割裂语义")
    print("- AI 分段：理解语义结构，保持情节完整性")
    print()
    print("例如：")
    print("- '食物分三档' 应该和后面的解释在同一段（AI 会识别列举结构）")
    print("- '扔地上吃很快 vs 手喂吃很慢' 应该在同一段（AI 会识别对比结构）")
    print("- '深夜吃狗粮' 是新场景，应该独立成段（AI 会识别场景转换）")


if __name__ == "__main__":
    test_ai_vs_algorithm()
