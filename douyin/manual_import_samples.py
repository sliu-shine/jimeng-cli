#!/usr/bin/env python3
"""
手动导入爆款文案样本
用于测试智能体功能
"""
import json
from pathlib import Path
from viral_agent import knowledge_base as kb
from viral_agent.analyzer import analyze_script

# 示例爆款文案（来自真实抖音爆款）
SAMPLE_SCRIPTS = [
    {
        "title": "职场升职加薪",
        "niche": "职场",
        "script": """你知道吗？那些升职快的人，都有一个共同点。
不是加班最多，也不是最会拍马屁。
而是懂得在关键时刻展示自己的价值。
我观察了100个升职案例，发现他们都做对了这3件事：
第一，主动汇报工作成果，让领导看见你的努力。
第二，提前思考问题的解决方案，而不是只会提问题。
第三，帮助团队成员成长，展现你的领导力。
记住，升职不是靠等，而是靠主动争取。
点赞收藏，下次详细讲每一条的具体做法。""",
        "likes": 156000,
        "comments": 8900
    },
    {
        "title": "理财认知差距",
        "niche": "理财",
        "script": """为什么有人30岁就财务自由，你却还在为房租发愁？
差距不在收入，而在认知。
普通人想的是：我要努力工作赚更多钱。
有钱人想的是：我要让钱为我工作。
这就是穷人思维和富人思维的本质区别。
我花了5年时间，从月光族到年入百万，靠的就是改变了这3个认知：
第一，不要用时间换钱，要用价值换钱。
第二，不要只有工资收入，要建立多元收入渠道。
第三，不要害怕投资，要学会让钱生钱。
关注我，每天分享一个财富认知，帮你打开赚钱思路。""",
        "likes": 234000,
        "comments": 12000
    },
    {
        "title": "情感关系真相",
        "niche": "情感",
        "script": """你以为的爱情，其实只是你的自我感动。
真正爱你的人，不会让你猜来猜去。
不会忽冷忽热，不会若即若离。
他会主动找你，会在意你的感受，会为你改变。
如果一个人总是让你患得患失，说明他根本没那么喜欢你。
别再骗自己了，放手吧。
你值得被更好地对待。
点赞的人，都会遇到真正爱你的人。""",
        "likes": 189000,
        "comments": 15600
    },
    {
        "title": "健康养生误区",
        "niche": "健康",
        "script": """医生从来不会告诉你的5个真相！
第一，多喝热水不能治百病，反而可能伤食道。
第二，每天8杯水是谣言，喝水要看个人需求。
第三，保健品不是智商税，但90%的人都买错了。
第四，熬夜真的会死人，不是吓唬你。
第五，体检正常不代表健康，很多病查不出来。
我是三甲医院医生，关注我，每天科普一个健康知识，让你少走弯路。
点赞收藏，可能救你一命。""",
        "likes": 278000,
        "comments": 18900
    },
    {
        "title": "教育孩子方法",
        "niche": "教育",
        "script": """为什么别人家的孩子那么优秀？
不是基因好，而是父母做对了这件事。
我采访了50个考上清北的学霸家长，发现他们都有一个共同点：
从不逼孩子学习，而是培养孩子的内驱力。
怎么做？3个方法：
第一，让孩子体验成功的快感，而不是失败的恐惧。
第二，给孩子选择权，而不是命令。
第三，做孩子的榜样，而不是监工。
记住，教育的本质是唤醒，不是灌输。
关注我，每天分享一个教育方法，帮你培养出优秀的孩子。""",
        "likes": 198000,
        "comments": 11200
    }
]


def main():
    """导入样本数据"""
    print("🚀 开始导入爆款文案样本...")

    success_count = 0

    for i, sample in enumerate(SAMPLE_SCRIPTS, 1):
        print(f"\n[{i}/{len(SAMPLE_SCRIPTS)}] 处理: {sample['title']}")
        print(f"  文案长度: {len(sample['script'])} 字")
        print(f"  点赞数: {sample['likes']:,}")

        try:
            # 分析文案
            print("  🔍 分析中...")
            analysis = analyze_script(
                script=sample['script'],
                likes=sample['likes'],
                niche=sample['niche']
            )

            # 存入知识库
            kb.add_script(
                video_id=f"manual_{i}",
                script=sample['script'],
                analysis=analysis,
                metadata={
                    "title": sample['title'],
                    "likes": sample['likes'],
                    "niche": sample['niche'],
                    "source": "manual_import"
                }
            )

            print(f"  ✅ 成功")
            success_count += 1

        except Exception as e:
            print(f"  ❌ 失败: {e}")
            import traceback
            traceback.print_exc()

    # 显示统计
    print(f"\n{'='*50}")
    print(f"✅ 导入完成: {success_count}/{len(SAMPLE_SCRIPTS)} 条")

    if success_count > 0:
        try:
            stats = kb.get_stats()
            print(f"\n📊 知识库统计:")
            print(f"  {stats}")
        except Exception as e:
            print(f"\n📊 知识库统计失败: {e}")


if __name__ == "__main__":
    main()
