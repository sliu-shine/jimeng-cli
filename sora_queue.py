#!/usr/bin/env python3
"""
Sora 2.0 队列执行器 - 对接云雾 API

专门处理 sora-2-all 模型的视频生成任务
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 如果没有 python-dotenv，直接使用环境变量


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / ".webui"
PROJECTS_DIR = APP_DIR / "projects"
PROJECTS_INDEX_FILE = APP_DIR / "projects.json"

TERMINAL_STATUSES = {"success", "fail", "failed", "error", "cancelled"}
SUCCESS_STATUSES = {"success"}
FAIL_STATUSES = {"fail", "failed", "error", "cancelled"}

DEFAULT_TIMEOUT_SECONDS = 3 * 60 * 60  # 3小时
POLL_INTERVAL_SECONDS = 10  # 每10秒查询一次状态


@dataclass
class SoraTask:
    """Sora 任务"""
    task_id: str
    status: str
    video_url: str | None = None
    error_message: str | None = None


def now_iso() -> str:
    """返回当前时间的 ISO 格式字符串"""
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(message: str) -> None:
    """打印日志"""
    print(f"[{now_iso()}] {message}", flush=True)


class YunwuSoraClient:
    """云雾 Sora API 客户端"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("YUNWU_SORA_API_KEY", "")
        self.base_url = base_url or os.getenv("YUNWU_BASE_URL", "https://api.yunwu.ai")

        if not self.api_key:
            raise ValueError("需要设置 YUNWU_API_KEY 环境变量")

    def _headers(self) -> dict[str, str]:
        """构建请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def submit_video_generation(
        self,
        prompt: str,
        duration: int = 10,
        ratio: str = "16:9",
        model: str = "sora-2-all",
        max_retries: int = 3,
        retry_delay: int = 5,
    ) -> str:
        """
        提交视频生成任务

        Args:
            prompt: 提示词
            duration: 时长（秒，支持 10 或 15）
            ratio: 宽高比（暂不使用，保留接口兼容性）
            model: 模型名称
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）

        Returns:
            task_id: 任务ID
        """
        # 使用正确的端点：/v1/videos
        url = f"{self.base_url}/v1/videos"

        # 使用正确的参数格式
        payload = {
            "model": model,
            "prompt": prompt,
            "duration": duration,  # 必须是数字 10 或 15
        }

        log(f"提交 Sora 任务: {prompt[:100]}...")

        last_error = None
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=self._headers(), json=payload, timeout=30)

                # 处理 429 负载饱和错误
                if response.status_code == 429:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("message", "")
                        if "负载已饱和" in error_msg:
                            log(f"⏳ 服务器负载饱和，等待 {retry_delay} 秒后重试 ({attempt + 1}/{max_retries})...")
                            time.sleep(retry_delay)
                            continue
                    except:
                        pass

                response.raise_for_status()
                data = response.json()

                task_id = data.get("id") or data.get("task_id") or data.get("data", {}).get("task_id")
                if not task_id:
                    raise ValueError(f"API 返回缺少 task_id: {data}")

                log(f"✅ 任务已提交，task_id: {task_id}")
                return task_id

            except requests.exceptions.RequestException as e:
                last_error = e
                log(f"❌ 提交任务失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)

        raise last_error or Exception("提交任务失败")

    def query_task_status(self, task_id: str) -> SoraTask:
        """
        查询任务状态

        Args:
            task_id: 任务ID

        Returns:
            SoraTask: 任务信息
        """
        url = f"{self.base_url}/v1/video/generations/{task_id}"

        try:
            response = requests.get(url, headers=self._headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

            status = data.get("status", "unknown")
            video_url = None
            error_message = None

            # 根据云雾 API 的实际响应格式调整
            if status == "completed" or status == "success":
                status = "success"
                video_url = data.get("video_url") or data.get("url")
            elif status in ["failed", "error"]:
                status = "failed"
                error_message = data.get("error") or data.get("message")

            return SoraTask(
                task_id=task_id,
                status=status,
                video_url=video_url,
                error_message=error_message,
            )

        except requests.exceptions.RequestException as e:
            log(f"❌ 查询任务状态失败: {e}")
            return SoraTask(
                task_id=task_id,
                status="error",
                error_message=str(e),
            )

    def wait_for_completion(
        self,
        task_id: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        poll_interval: int = POLL_INTERVAL_SECONDS,
    ) -> SoraTask:
        """
        等待任务完成

        Args:
            task_id: 任务ID
            timeout_seconds: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            SoraTask: 最终任务信息
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                log(f"⏱️ 任务超时 ({timeout_seconds}秒)")
                return SoraTask(
                    task_id=task_id,
                    status="error",
                    error_message=f"任务超时 ({timeout_seconds}秒)",
                )

            task = self.query_task_status(task_id)
            log(f"📊 任务状态: {task.status} (已等待 {int(elapsed)}秒)")

            if task.status in TERMINAL_STATUSES:
                return task

            time.sleep(poll_interval)


def download_video(url: str, output_path: Path) -> bool:
    """
    下载视频文件

    Args:
        url: 视频URL
        output_path: 输出路径

    Returns:
        是否成功
    """
    try:
        log(f"📥 下载视频: {url}")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        log(f"✅ 视频已保存: {output_path}")
        return True

    except Exception as e:
        log(f"❌ 下载失败: {e}")
        return False


def load_queue(queue_file: Path) -> dict:
    """加载队列文件"""
    if not queue_file.exists():
        return {"version": 1, "segments": []}

    try:
        with open(queue_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log(f"❌ 加载队列文件失败: {e}")
        return {"version": 1, "segments": []}


def save_queue(queue_file: Path, queue_data: dict) -> None:
    """保存队列文件"""
    queue_data["updated_at"] = now_iso()
    try:
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(queue_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log(f"❌ 保存队列文件失败: {e}")


def process_segment(
    segment: dict,
    client: YunwuSoraClient,
    output_dir: Path,
) -> dict:
    """
    处理单个片段

    Args:
        segment: 片段数据
        client: Sora 客户端
        output_dir: 输出目录

    Returns:
        更新后的片段数据
    """
    segment_id = segment.get("id", "unknown")
    segment_name = segment.get("name", segment_id)

    log(f"\n{'='*60}")
    log(f"开始处理: {segment_name}")
    log(f"{'='*60}")

    # 检查是否已完成
    if segment.get("status") == "success":
        log(f"⏭️  片段已完成，跳过")
        return segment

    # 提取参数
    prompt = segment.get("prompt", "")
    duration = int(segment.get("duration", 10))
    ratio = segment.get("ratio", "16:9")
    model = segment.get("model_version", "sora-2-all")

    if not prompt:
        log(f"❌ 缺少 prompt，跳过")
        segment["status"] = "error"
        segment["error_message"] = "缺少 prompt"
        return segment

    try:
        # 提交任务
        segment["started_at"] = now_iso()
        task_id = client.submit_video_generation(
            prompt=prompt,
            duration=duration,
            ratio=ratio,
            model=model,
        )
        segment["task_id"] = task_id

        # 等待完成
        task = client.wait_for_completion(task_id)

        # 更新状态
        segment["status"] = task.status
        segment["finished_at"] = now_iso()

        if task.status == "success" and task.video_url:
            # 下载视频
            video_filename = f"{segment_name}.mp4"
            video_path = output_dir / video_filename

            if download_video(task.video_url, video_path):
                segment["video_url"] = task.video_url
                segment["local_path"] = str(video_path)
                log(f"✅ 片段完成: {segment_name}")
            else:
                segment["status"] = "error"
                segment["error_message"] = "视频下载失败"
        else:
            segment["error_message"] = task.error_message or "生成失败"
            log(f"❌ 片段失败: {task.error_message}")

    except Exception as e:
        log(f"❌ 处理片段时出错: {e}")
        segment["status"] = "error"
        segment["error_message"] = str(e)
        segment["finished_at"] = now_iso()

    return segment


def run_queue(queue_file: Path, output_dir: Path | None = None) -> None:
    """
    运行队列

    Args:
        queue_file: 队列文件路径
        output_dir: 输出目录（可选）
    """
    log(f"🚀 开始处理 Sora 队列: {queue_file}")

    # 加载队列
    queue_data = load_queue(queue_file)
    segments = queue_data.get("segments", [])

    if not segments:
        log("❌ 队列为空")
        return

    # 确定输出目录
    if output_dir is None:
        output_dir = queue_file.parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建客户端
    try:
        client = YunwuSoraClient()
    except ValueError as e:
        log(f"❌ 初始化客户端失败: {e}")
        return

    # 处理每个片段
    total = len(segments)
    success_count = 0

    for idx, segment in enumerate(segments, 1):
        log(f"\n进度: {idx}/{total}")

        segment = process_segment(segment, client, output_dir)
        segments[idx - 1] = segment

        # 保存进度
        save_queue(queue_file, queue_data)

        if segment.get("status") == "success":
            success_count += 1

    # 总结
    log(f"\n{'='*60}")
    log(f"队列处理完成")
    log(f"成功: {success_count}/{total}")
    log(f"失败: {total - success_count}/{total}")
    log(f"输出目录: {output_dir}")
    log(f"{'='*60}")


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="Sora 2.0 队列执行器")
    parser.add_argument("queue_file", type=Path, help="队列 JSON 文件路径")
    parser.add_argument("--output-dir", type=Path, help="输出目录（可选）")

    args = parser.parse_args()

    if not args.queue_file.exists():
        print(f"❌ 队列文件不存在: {args.queue_file}")
        sys.exit(1)

    run_queue(args.queue_file, args.output_dir)


if __name__ == "__main__":
    main()
