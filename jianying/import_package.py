"""
Generate a stable Jianying import package.

This route avoids writing Jianying's private draft format. It produces files
that Jianying can import normally:
    - final.mp4
    - subtitles.srt
    - import_guide.json
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass
class ImportSegment:
    index: int
    text: str
    video_path: str
    start_time: float
    duration: float


def _safe_project_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "自动生产视频"


def natural_sort_key(value: str) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]


def _format_srt_time(seconds: float) -> str:
    milliseconds = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _wrap_subtitle_text(text: str, max_chars: int = 18) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _split_subtitle_cues(text: str, max_chars: int = 14) -> List[str]:
    punct = "，,。！？!?；;、"
    units = re.findall(rf"[^{re.escape(punct)}\n]+[{re.escape(punct)}]?", str(text or "").strip())
    units = [unit.strip() for unit in units if unit.strip()]
    if not units:
        return []

    cues: List[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) > max_chars:
            cues.append(current)
            current = ""

        while len(unit) > max_chars:
            split_at = max_chars
            if len(unit) > split_at and unit[split_at] in punct:
                split_at += 1
            cues.append(unit[:split_at])
            unit = unit[split_at:]

        current += unit

    if current:
        cues.append(current)

    cleaned: List[str] = []
    for cue in cues:
        cue = cue.strip()
        if not cue:
            continue
        if cleaned and (cue in punct or cue[0] in punct or len(cue) <= 2):
            cleaned[-1] += cue
        else:
            cleaned.append(cue)
    return cleaned


def write_srt(segments: Iterable[ImportSegment], output_path: Path) -> None:
    blocks = []
    cue_index = 1
    for segment in segments:
        cues = _split_subtitle_cues(segment.text)
        if not cues:
            continue

        weights = [max(1, len(re.sub(r"\s+", "", cue))) for cue in cues]
        total_weight = sum(weights)
        cursor = segment.start_time

        for cue, weight in zip(cues, weights):
            cue_duration = segment.duration * (weight / total_weight)
            cue_end = min(segment.start_time + segment.duration, cursor + cue_duration)
            if cue_end <= cursor:
                cue_end = min(segment.start_time + segment.duration, cursor + 0.5)

            start = _format_srt_time(cursor)
            end = _format_srt_time(cue_end)
            text = _wrap_subtitle_text(cue)
            blocks.append(f"{cue_index}\n{start} --> {end}\n{text}\n")
            cue_index += 1
            cursor = cue_end

    output_path.write_text("\n".join(blocks), encoding="utf-8")


def _probe_duration(video_path: str) -> Optional[float]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return None

    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def _concat_videos(video_files: List[str], output_path: Path, work_dir: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请先安装：brew install ffmpeg")

    concat_list = work_dir / "concat_list.txt"
    concat_list.write_text(
        "\n".join(f"file '{Path(path).resolve().as_posix()}'" for path in video_files) + "\n",
        encoding="utf-8",
    )

    copy_cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c",
        "copy",
        str(output_path),
    ]
    copy_result = subprocess.run(copy_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if copy_result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        concat_list.unlink(missing_ok=True)
        return

    encode_cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    encode_result = subprocess.run(encode_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if encode_result.returncode != 0:
        raise RuntimeError(f"ffmpeg 合并失败：{encode_result.stderr.strip() or copy_result.stderr.strip()}")
    concat_list.unlink(missing_ok=True)


def _split_sentences_with_punctuation(transcript: str) -> List[str]:
    parts = re.split(r"(?<=[。！？!?])|\n+", str(transcript or "").strip())
    return [part.strip() for part in parts if part.strip()]


def split_transcript_by_video_count(transcript: str, count: int) -> List[str]:
    """Split transcript into exactly count chunks for the selected videos."""
    if count <= 0:
        return []

    sentences = _split_sentences_with_punctuation(transcript)
    if not sentences:
        return [""] * count
    if count == 1:
        return ["".join(sentences)]
    if len(sentences) <= count:
        return sentences + [""] * (count - len(sentences))

    total_chars = sum(len(sentence) for sentence in sentences)
    target_chars = max(1, total_chars / count)
    chunks: List[str] = []
    current: List[str] = []
    current_chars = 0

    for sentence_index, sentence in enumerate(sentences):
        remaining_sentences = len(sentences) - sentence_index
        remaining_slots_after_current = count - len(chunks) - 1
        can_close_current = remaining_sentences > remaining_slots_after_current
        if current and len(chunks) < count - 1 and current_chars >= target_chars and can_close_current:
            chunks.append("".join(current))
            current = [sentence]
            current_chars = len(sentence)
        else:
            current.append(sentence)
            current_chars += len(sentence)

    if len(chunks) < count and current:
        chunks.append("".join(current))
    return chunks[:count] + [""] * max(0, count - len(chunks))


def create_import_package(
    project_name: str,
    transcript: str,
    video_files: List[str],
    output_dir: Optional[str] = None,
    add_subtitles: bool = True,
) -> dict:
    if not transcript.strip():
        raise ValueError("请输入视频文案")
    if not video_files:
        raise ValueError("请选择视频文件")

    source_videos = sorted(
        [str(Path(path).expanduser().resolve()) for path in video_files],
        key=natural_sort_key,
    )
    missing = [path for path in source_videos if not Path(path).exists()]
    if missing:
        raise FileNotFoundError(f"视频文件不存在：{missing[0]}")

    subtitle_texts = split_transcript_by_video_count(transcript, len(source_videos))

    root_dir = Path(output_dir) if output_dir else Path(__file__).parent.parent / "jianying_import_packages"
    output_path = root_dir / f"{_safe_project_name(project_name)}_{int(time.time())}"
    output_path.mkdir(parents=True, exist_ok=True)

    final_video = output_path / "final.mp4"
    subtitles = output_path / "subtitles.srt"
    guide = output_path / "import_guide.json"

    import_segments: List[ImportSegment] = []
    current_time = 0.0

    for index, (text, video_path) in enumerate(zip(subtitle_texts, source_videos), start=1):
        duration = _probe_duration(video_path) or 3.0
        import_segments.append(
            ImportSegment(
                index=index,
                text=text,
                video_path=video_path,
                start_time=current_time,
                duration=duration,
            )
        )
        current_time += duration

    _concat_videos(source_videos, final_video, output_path)

    if add_subtitles:
        write_srt(import_segments, subtitles)

    guide_data = {
        "project_name": project_name,
        "created_at": int(time.time()),
        "final_video": str(final_video),
        "subtitles": str(subtitles) if add_subtitles else None,
        "total_duration": current_time,
        "segments_count": len(import_segments),
        "segments": [asdict(segment) for segment in import_segments],
        "jianying_steps": [
            "打开剪映专业版，点击开始创作。",
            "导入 final.mp4。",
            "如果需要可编辑字幕，导入 subtitles.srt 或使用剪映自动识别字幕。",
            "在剪映中继续添加配音、滤镜、转场并导出。",
        ],
    }
    guide.write_text(json.dumps(guide_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_path": str(output_path),
        "final_video": str(final_video),
        "subtitles": str(subtitles) if add_subtitles else None,
        "total_duration": current_time,
        "segments_count": len(import_segments),
        "segments": [asdict(segment) for segment in import_segments],
    }
