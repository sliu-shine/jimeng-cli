"""
Claude API 客户端 - 支持中转 API
"""
import os
import json
import httpx
from typing import Optional


class ClaudeClient:
    """支持中转 API 的 Claude 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

        if not self.api_key:
            raise ValueError("需要提供 ANTHROPIC_API_KEY")

    def create_message(
        self,
        model: str,
        messages: list,
        max_tokens: int = 1024,
        temperature: float = 1.0,
        system: Optional[str] = None
    ) -> dict:
        """创建消息"""
        url = f"{self.base_url}/v1/messages"

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,  # 中转 API 使用 x-api-key
            "anthropic-version": "2023-06-01"
        }

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        if system:
            payload["system"] = system

        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()


def test_connection():
    """测试连接"""
    print("=" * 60)
    print("测试 Claude API 连接")
    print("=" * 60)

    try:
        client = ClaudeClient(
            api_key="sk-8efdb67427cea88f1c3de7e9b592fa57e6c3521d7de0e7c75016ce52d55a4942",
            base_url="https://v3.codesome.cn"
        )

        print(f"Base URL: {client.base_url}")
        print(f"API Key: {client.api_key[:20]}...")

        result = client.create_message(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "请用一句话介绍你自己"}],
            max_tokens=200
        )

        print("\n✅ API 连接成功！")
        print(f"\n回复: {result['content'][0]['text']}")
        print(f"\nTokens: {result['usage']['input_tokens']} 输入 + {result['usage']['output_tokens']} 输出")

        return True

    except Exception as e:
        print(f"\n❌ API 连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_connection()
