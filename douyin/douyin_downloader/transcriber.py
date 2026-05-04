#!/usr/bin/env python3
"""
视频逐字稿提取模块
支持从视频中提取音频并转为文字
"""
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False


def extract_audio(video_path: Path, audio_path: Optional[Path] = None) -> Path:
    """
    使用 ffmpeg 从视频中提取音频

    Args:
        video_path: 视频文件路径
        audio_path: 音频输出路径（可选）

    Returns:
        音频文件路径
    """
    if audio_path is None:
        audio_path = video_path.with_suffix('.mp3')

    if audio_path.exists():
        print(f"音频已存在: {audio_path}")
        return audio_path

    cmd = [
        'ffmpeg',
        '-i', str(video_path),
        '-vn',  # 不要视频
        '-acodec', 'libmp3lame',
        '-ar', '16000',  # 16kHz 采样率（Whisper 推荐）
        '-ac', '1',  # 单声道
        '-b:a', '64k',  # 比特率
        '-y',  # 覆盖已存在文件
        str(audio_path)
    ]

    try:
        print(f"提取音频: {video_path.name} -> {audio_path.name}")
        subprocess.run(cmd, check=True, capture_output=True)
        return audio_path
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg 提取音频失败: {e.stderr.decode()}")


def transcribe_with_whisper(
    audio_path: Path,
    model_name: str = "large-v3",
    language: str = "zh"
) -> Dict[str, Any]:
    """
    使用 Whisper 进行语音识别

    Args:
        audio_path: 音频文件路径
        model_name: Whisper 模型名称（tiny/base/small/medium/large/large-v3）
        language: 语言代码（zh=中文）

    Returns:
        识别结果字典，包含 text 和 segments
    """
    if not WHISPER_AVAILABLE:
        raise RuntimeError("Whisper 未安装，请运行: pip install openai-whisper")

    print(f"加载 Whisper 模型: {model_name}")
    model = whisper.load_model(model_name)

    print(f"识别音频: {audio_path.name}")
    result = model.transcribe(
        str(audio_path),
        language=language,
        verbose=False,
        initial_prompt="以下是抖音短视频的口播文案。"  # 提示词优化中文识别
    )

    return {
        "text": result["text"].strip(),
        "segments": [
            {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip()
            }
            for seg in result["segments"]
        ]
    }


def transcribe_with_groq(
    audio_path: Path,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 Groq API 进行语音识别（更快，需要API key）

    Args:
        audio_path: 音频文件路径
        api_key: Groq API key（可选，从环境变量读取）

    Returns:
        识别结果字典
    """
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("Groq SDK 未安装，请运行: pip install groq")

    import os
    api_key = api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("需要提供 GROQ_API_KEY")

    client = Groq(api_key=api_key)

    print(f"使用 Groq API 识别: {audio_path.name}")
    with open(audio_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(audio_path.name, f.read()),
            model="whisper-large-v3",
            language="zh",
            response_format="verbose_json"
        )

    # 转换为统一格式
    segments = []
    if hasattr(transcription, 'segments'):
        segments = [
            {
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", "").strip()
            }
            for seg in transcription.segments
        ]

    return {
        "text": transcription.text.strip(),
        "segments": segments
    }


def extract_transcript(
    video_path: Path,
    method: str = "whisper",
    model_name: str = "large-v3",
    save_json: bool = True
) -> Dict[str, Any]:
    """
    从视频提取逐字稿（完整流程）

    Args:
        video_path: 视频文件路径
        method: 识别方法（whisper/groq）
        model_name: Whisper 模型名称
        save_json: 是否保存为 JSON 文件

    Returns:
        逐字稿结果
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    # 1. 提取音频
    audio_path = extract_audio(video_path)

    # 2. 语音识别
    if method == "groq":
        result = transcribe_with_groq(audio_path)
    else:
        result = transcribe_with_whisper(audio_path, model_name)

    # 3. 保存结果
    if save_json:
        transcript_file = video_path.with_suffix('.transcript.json')
        with open(transcript_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"逐字稿已保存: {transcript_file}")

    return result


def batch_extract_transcripts(
    video_dir: Path,
    method: str = "whisper",
    model_name: str = "large-v3"
) -> Dict[str, Dict[str, Any]]:
    """
    批量提取视频逐字稿

    Args:
        video_dir: 视频目录
        method: 识别方法
        model_name: 模型名称

    Returns:
        {video_filename: transcript_result}
    """
    video_dir = Path(video_dir)
    video_files = list(video_dir.glob("*.mp4"))

    print(f"找到 {len(video_files)} 个视频文件")

    results = {}
    for video_path in video_files:
        try:
            # 检查是否已有逐字稿
            transcript_file = video_path.with_suffix('.transcript.json')
            if transcript_file.exists():
                print(f"跳过已处理: {video_path.name}")
                with open(transcript_file, 'r', encoding='utf-8') as f:
                    results[video_path.name] = json.load(f)
                continue

            result = extract_transcript(video_path, method, model_name)
            results[video_path.name] = result

        except Exception as e:
            print(f"处理 {video_path.name} 失败: {e}")
            continue

    return results


if __name__ == "__main__":
    # 测试示例
    video_path = Path("./douyin_videos/test.mp4")

    if video_path.exists():
        result = extract_transcript(video_path, method="whisper", model_name="base")
        print("\n逐字稿:")
        print(result["text"])
        print(f"\n共 {len(result['segments'])} 个片段")
