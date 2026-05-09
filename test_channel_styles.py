#!/usr/bin/env python3
"""
测试频道风格功能
"""
from viral_agent.seedance_prompt_builder import (
    get_channel_choices,
    get_default_channel_id,
    get_channel_style,
)

def test_channel_functions():
    print("=" * 60)
    print("测试频道风格功能")
    print("=" * 60)

    # 测试获取频道列表
    choices = get_channel_choices()
    print(f"\n✅ 可用频道数量: {len(choices)}")
    for name, channel_id in choices:
        print(f"  - {name} (ID: {channel_id})")

    # 测试获取默认频道
    default_id = get_default_channel_id()
    print(f"\n✅ 默认频道ID: {default_id}")

    # 测试获取频道风格
    if choices:
        test_channel_id = choices[0][1]
        style = get_channel_style(test_channel_id)
        print(f"\n✅ 频道 '{choices[0][0]}' 的风格描述:")
        print(f"  {style[:100]}...")

    # 测试默认风格
    default_style = get_channel_style(None)
    print(f"\n✅ 默认风格描述:")
    print(f"  {default_style}")

    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    test_channel_functions()
