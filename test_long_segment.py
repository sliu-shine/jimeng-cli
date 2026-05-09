#!/usr/bin/env python3
"""测试超长段落拆分"""
import sys
sys.path.insert(0, '.')

from viral_agent.text_segmenter import segment_by_sentences_ai, validate_segments

# 用真实的问题文案测试
test_text = """为什么狗宁可饿一天,也要等你给它喂?你以为它只是嘴馋吗?这背后藏着一个真相,很多人听完都会沉默。
狗这种动物啊,天生就有囤积意识和等级观念。在它的认知里,食物分三个档次:最低档是狗粮,那是反正饿不死的保底口粮;
中档是你吃剩的、掉在地上的,那叫意外之财;最高档才是你亲手喂给它的,那代表着我在这个家的地位被认可了。
所以当它拒绝吃狗粮的时候,本质上不是在挑食,而是在等一个信号——等你承认它是家庭成员,而不是一只只配吃工业饲料的动物。
你有没有发现,同样一块鸡胸肉,你扔地上它吃得很快,但你用手喂它就会吃得特别慢、特别小心?
因为那一刻它感受到的不是食物本身,而是被重视的感觉。所以它宁可饿着,也要赌你会在某个时刻,用手把食物递到它嘴边。"""

print("🧪 测试超长段落拆分...\n")
segments = segment_by_sentences_ai(test_text.strip())

print(f"\n共 {len(segments)} 个段落：\n")
for seg in segments:
    status = "✅" if seg['estimated_duration'] <= 15 else "❌ 超长！"
    print(f"  {status} 段落 {seg['index']}: {seg['estimated_duration']:.1f}秒 ({seg['char_count']}字)")
    print(f"     {seg['text'][:60]}...")

print()
result = validate_segments(segments)
print(f"验证结果: {'✅ 通过' if result['valid'] else '❌ 有警告'}")
for w in result['warnings']:
    print(f"  ⚠️ {w}")
print(f"统计: {result['stats']}")
