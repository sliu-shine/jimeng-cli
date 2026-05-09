#!/usr/bin/env python3
"""测试 JSON 清理"""
import json
import re

# 模拟 AI 返回的 JSON（包含值内部的双引号）
json_str = '''{
  "segments": [
    {"index": 1, "text": "为什么狗宁可饿一天,也要等你给它喂?你以为它只是嘴馋吗?这背后藏着一个真相,很多人听完都会沉默。"},
    {"index": 2, "text": "狗这种动物啊,天生就有囤积意识和等级观念。在它的认知里,食物分三个档次:最低档是狗粮,那是"反正饿不死"的保底口粮;"},
    {"index": 3, "text": "中档是你吃剩的、掉在地上的,那叫"意外之财";最高档才是你亲手喂给它的,那代表着"我在这个家的地位被认可了"。"}
  ]
}'''

print("原始 JSON:")
print(json_str[:300])
print("\n" + "="*60 + "\n")

# 使用正则表达式匹配并处理每个 "text": "..." 字段
def clean_json_text_field(json_text):
    """清理 JSON 中 text 字段内的双引号"""
    def escape_inner_quotes(match):
        # match.group(0) 是整个匹配 "text": "..."
        # match.group(1) 是 text 后面的内容（包括值）
        full_match = match.group(0)
        # 找到值的部分（第二个引号之后到最后一个引号之前）
        # "text": "value"
        parts = full_match.split('"', 3)  # 分成最多4部分
        if len(parts) >= 4:
            # parts[0] = ''
            # parts[1] = 'text'
            # parts[2] = ': '
            # parts[3] = 'value"...'
            value_and_rest = parts[3]
            # 找到最后一个引号
            last_quote = value_and_rest.rfind('"')
            if last_quote != -1:
                value = value_and_rest[:last_quote]
                rest = value_and_rest[last_quote:]
                # 转义值中的引号
                escaped_value = value.replace('"', '\\"')
                return f'"{parts[1]}"{parts[2]}"{escaped_value}{rest}'
        return full_match

    # 匹配 "text": "..." 模式（非贪婪匹配到行尾的引号）
    cleaned = re.sub(r'"text"\s*:\s*"[^"]*(?:"[^"]*)*"', escape_inner_quotes, json_text)
    return cleaned

cleaned = clean_json_text_field(json_str)

print("清理后的 JSON:")
print(cleaned[:400])
print("\n" + "="*60 + "\n")

# 尝试解析
try:
    data = json.loads(cleaned)
    print("✅ JSON 解析成功！")
    print(f"段落数: {len(data['segments'])}")
    for seg in data['segments']:
        print(f"  段落 {seg['index']}: {seg['text'][:50]}...")
except json.JSONDecodeError as e:
    print(f"❌ JSON 解析失败: {e}")
    print(f"错误位置: 第 {e.lineno} 行, 第 {e.colno} 列")

