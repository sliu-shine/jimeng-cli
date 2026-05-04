"""
转录器：音频 → 文字
支持本地 Whisper 或 Groq API（更快）
"""
import os
import subprocess
from pathlib import Path


def extract_audio(video_path: str) -> str:
    """从视频提取音频"""
    audio_path = str(Path(video_path).with_suffix(".mp3"))
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-q:a", "0", "-map", "a", audio_path, "-y"],
        check=True, capture_output=True,
    )
    return audio_path


def transcribe_whisper(audio_path: str) -> str:
    """用本地 Whisper 转录（精度高，需 GPU 更快）"""
    import whisper
    model = whisper.load_model("large-v3")
    result = model.transcribe(audio_path, language="zh")
    return result["text"].strip()


def transcribe_groq(audio_path: str) -> str:
    """用 Groq Whisper API 转录（速度快，免费额度大）"""
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    with open(audio_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(Path(audio_path).name, f),
            model="whisper-large-v3",
            language="zh",
        )
    return transcription.text.strip()


def transcribe(audio_path: str, use_groq: bool = True) -> str:
    """
    转录音频为文字
    use_groq=True: 优先用 Groq API（快）
    use_groq=False: 用本地 Whisper
    """
    if use_groq and os.environ.get("GROQ_API_KEY"):
        return transcribe_groq(audio_path)
    return transcribe_whisper(audio_path)
