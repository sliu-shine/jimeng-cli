#!/usr/bin/env python3
"""
检查和修复系统依赖
"""
import subprocess
import sys
from pathlib import Path


def check_dependency(module_name, package_name=None):
    """检查单个依赖"""
    if package_name is None:
        package_name = module_name

    try:
        __import__(module_name)
        print(f"✅ {package_name}")
        return True
    except ImportError:
        print(f"❌ {package_name} - 未安装")
        return False


def main():
    print("=" * 60)
    print("爆款文案智能体 - 依赖检查")
    print("=" * 60)

    # 检查核心依赖
    print("\n【核心依赖】")
    core_deps = [
        ("anthropic", "anthropic"),
        ("chromadb", "chromadb"),
        ("sentence_transformers", "sentence-transformers"),
    ]

    core_ok = all(check_dependency(mod, pkg) for mod, pkg in core_deps)

    # 检查转录依赖
    print("\n【转录依赖】")
    transcribe_deps = [
        ("whisper", "openai-whisper"),
        ("groq", "groq"),
    ]

    transcribe_ok = any(check_dependency(mod, pkg) for mod, pkg in transcribe_deps)

    # 检查抖音下载依赖
    print("\n【抖音下载依赖】")
    douyin_deps = [
        ("aiohttp", "aiohttp"),
        ("aiofiles", "aiofiles"),
    ]

    douyin_ok = all(check_dependency(mod, pkg) for mod, pkg in douyin_deps)

    # 检查 Selenium 依赖
    print("\n【Selenium 依赖】")
    selenium_deps = [
        ("selenium", "selenium"),
        ("webdriver_manager", "webdriver-manager"),
    ]

    selenium_ok = all(check_dependency(mod, pkg) for mod, pkg in selenium_deps)

    # 检查 ffmpeg
    print("\n【系统依赖】")
    try:
        result = subprocess.run(["ffmpeg", "-version"],
                              capture_output=True,
                              timeout=5)
        if result.returncode == 0:
            print("✅ ffmpeg")
            ffmpeg_ok = True
        else:
            print("❌ ffmpeg - 未安装")
            ffmpeg_ok = False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("❌ ffmpeg - 未安装")
        ffmpeg_ok = False

    # 总结
    print("\n" + "=" * 60)
    print("检查结果")
    print("=" * 60)

    if core_ok and transcribe_ok and douyin_ok and selenium_ok and ffmpeg_ok:
        print("✅ 所有依赖已安装，可以正常使用")
        return 0
    else:
        print("❌ 部分依赖缺失，请按以下步骤安装：\n")

        if not core_ok:
            print("1. 安装核心依赖：")
            print("   pip install -r requirements_viral.txt\n")

        if not douyin_ok or not selenium_ok:
            print("2. 安装抖音下载依赖：")
            print("   pip install -r requirements_douyin.txt")
            print("   pip install -r requirements_selenium.txt\n")

        if not ffmpeg_ok:
            print("3. 安装 ffmpeg：")
            print("   brew install ffmpeg  # macOS")
            print("   # 或访问 https://ffmpeg.org/download.html\n")

        return 1


if __name__ == "__main__":
    sys.exit(main())
