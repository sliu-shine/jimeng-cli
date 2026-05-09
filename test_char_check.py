#!/usr/bin/env python3
"""检查中文引号字符"""

text = '那是"反正饿不死"的保底口粮'
print('原始:', repr(text))
print('左引号 unicode:', hex(ord('"')))
print('右引号 unicode:', hex(ord('"')))

# 测试替换
result = []
for char in text:
    if char == '"' or char == '"':
        result.append(f'[{char}={hex(ord(char))}]')
    else:
        result.append(char)

print('检测结果:', ''.join(result))
