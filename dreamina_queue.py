#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / ".webui"
PROJECTS_DIR = APP_DIR / "projects"
PROJECTS_INDEX_FILE = APP_DIR / "projects.json"
TERMINAL_STATUSES = {"success", "fail", "failed", "rejected", "banned", "error", "cancelled"}
SUCCESS_STATUSES = {"success"}
FAIL_STATUSES = {"fail", "failed", "rejected", "banned", "error", "cancelled"}
SUBMIT_ID_PATTERNS = [
    re.compile(r'"submit_id"\s*:\s*"([^"]+)"'),
    re.compile(r"\bsubmit_id\b\s*[:=]\s*([A-Za-z0-9_-]+)"),
]
GEN_STATUS_PATTERNS = [
    re.compile(r'"gen_status"\s*:\s*"([^"]+)"'),
    re.compile(r"\bgen_status\b\s*[:=]\s*([A-Za-z0-9_-]+)"),
]
FAIL_REASON_PATTERNS = [
    re.compile(r'"fail_reason"\s*:\s*"([^"]*)"'),
    re.compile(r"\bfail_reason\b\s*[:=]\s*(.+)"),
]
RESULT_URL_PATTERNS = [
    re.compile(r'"(https?://[^"]+)"'),
]
DEFAULT_TIMEOUT_SECONDS = 3 * 60 * 60
RETRYABLE_FAILURE_MARKERS = (
    "generation failed",
    "final generation failed",
    "query_result 未返回 success",
)
NON_RETRYABLE_FAILURE_MARKERS = (
    "post-tns check",
    "audit",
    "compliance",
    "rejected",
    "banned",
    "sensitive",
    "审核",
    "confirmationrequired",
    "compliance check",
    "tns check",
)
TEXT_REFERENCE_MARKERS = ("提示词", "分镜", "脚本", "字幕", "台词", "prompt")
SAFE_RETRY_MAX_IMAGES = 4
SAFE_RETRY_MAX_VIDEOS = 1
SAFE_RETRY_MAX_AUDIOS = 1
SAFE_RETRY_DURATION_SECONDS = 5
SAFE_RETRY_PROMPT_CHARS = 220
ULTRA_SAFE_RETRY_MAX_IMAGES = 1
ULTRA_SAFE_RETRY_PROMPT_CHARS = 90
MAX_RETRY_ATTEMPTS = 2


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]

    @property
    def combined(self) -> str:
        return "\n".join(part for part in [self.stdout.strip(), self.stderr.strip()] if part).strip()


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(message: str) -> None:
    print(f"[{now_iso()}] {message}", flush=True)


def is_command_complete(text: str) -> bool:
    try:
        shlex.split(text)
        return True
    except ValueError as exc:
        return "No closing quotation" not in str(exc)


def read_queue_commands_from_text(text: str) -> list[str]:
    commands: list[str] = []
    current: list[str] = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        if not stripped:
            if current and is_command_complete("\n".join(current)):
                commands.append("\n".join(current).strip())
                current = []
            continue
        current.append(stripped)
        candidate = "\n".join(current).strip()
        if candidate and is_command_complete(candidate):
            commands.append(candidate)
            current = []

    if current:
        commands.append("\n".join(current).strip())
    return commands


def read_queue_file(path: Path) -> list[str]:
    return read_queue_commands_from_text(path.read_text(encoding="utf-8"))


def media_ref_aliases(path: str) -> set[str]:
    file_path = Path(str(path or ""))
    aliases = {file_path.stem, file_path.name}
    cleaned = re.sub(r"^\d+-[0-9a-fA-F]{8}-", "", file_path.stem)
    aliases.add(cleaned)
    aliases.add(Path(cleaned).stem)
    return {alias for alias in aliases if alias}


def build_media_ref_map(images: list[str], videos: list[str], audios: list[str]) -> dict[tuple[str, str], str]:
    mapping: dict[tuple[str, str], str] = {}
    groups = [
        ("Image", "图片", images),
        ("Video", "视频", videos),
        ("Audio", "音频", audios),
    ]
    for kind, label, paths in groups:
        for index, path in enumerate(paths, start=1):
            ref_label = f"{label}{index}"
            for alias in media_ref_aliases(path):
                mapping[(kind, alias)] = ref_label
    return mapping


def media_paths_for_prompt_refs(paths: list[str], prompt: str, kind: str) -> list[str]:
    refs = re.findall(rf"@{kind}([^\s,，。、@]+)", str(prompt or ""))
    if not refs:
        return paths

    selected: list[str] = []
    for ref in refs:
        best_path = ""
        best_alias = ""
        for path in paths:
            for alias in media_ref_aliases(path):
                if ref == alias or ref.startswith(alias):
                    if len(alias) > len(best_alias):
                        best_alias = alias
                        best_path = path
        if best_path and best_path not in selected:
            selected.append(best_path)
    return selected


def filter_media_by_prompt_refs(
    prompt: str,
    images: list[str],
    videos: list[str],
    audios: list[str],
) -> tuple[list[str], list[str], list[str]]:
    return (
        media_paths_for_prompt_refs(images, prompt, "Image"),
        media_paths_for_prompt_refs(videos, prompt, "Video"),
        media_paths_for_prompt_refs(audios, prompt, "Audio"),
    )


def normalize_prompt_text(prompt: str, media_refs: dict[tuple[str, str], str] | None = None) -> str:
    text = str(prompt or "").strip()
    if not text:
        return ""

    labels = {"Image": "图片", "Video": "视频", "Audio": "音频"}

    def replace_named(match: re.Match[str]) -> str:
        kind = match.group(1)
        name = match.group(2)
        if media_refs:
            exact = media_refs.get((kind, name))
            if exact:
                return exact
            prefix_matches = [
                (alias, label)
                for (ref_kind, alias), label in media_refs.items()
                if ref_kind == kind and name.startswith(alias)
            ]
            if prefix_matches:
                alias, label = max(prefix_matches, key=lambda item: len(item[0]))
                return f"{label}{name[len(alias):]}"
        return name

    text = re.sub(r"@(Image|Video|Audio)([^\s,，。、@]+)", replace_named, text)
    for kind, label in labels.items():
        text = re.sub(rf"@{kind}\b", f"{label}参考", text)
    return text


def normalize_model_version(value: Any) -> str:
    model = str(value or "").strip()
    legacy_map = {
        "seedance1.0fast": "seedance2.0fast",
        "seedance1.0": "seedance2.0",
        "seedance1.0fast_vip": "seedance2.0fast_vip",
        "seedance1.0_vip": "seedance2.0_vip",
    }
    return legacy_map.get(model, model)


def build_multiframe_command(
    images: list[str],
    prompt: str,
    duration: str,
    transition_prompts: list[str] | None = None,
) -> list[str]:
    command = ["multiframe2video", "--images", ",".join(images)]
    if len(images) == 2:
        if prompt:
            command.extend(["--prompt", prompt])
        if duration:
            command.extend(["--duration", duration])
        return command

    transition_count = len(images) - 1
    prompts = [str(item).strip() for item in (transition_prompts or []) if str(item).strip()]
    if len(prompts) >= transition_count:
        prompts = prompts[:transition_count]
    else:
        fallback = prompt or "保持角色与场景连贯，自然过渡到下一帧"
        while len(prompts) < transition_count:
            prompts.append(fallback)
    for item in prompts:
        command.extend(["--transition-prompt", item])
    if duration:
        try:
            total_duration = float(duration)
            segment_duration = max(0.5, min(8.0, total_duration / transition_count))
            segment_duration_text = f"{segment_duration:.2f}".rstrip("0").rstrip(".")
            for _ in range(transition_count):
                command.extend(["--transition-duration", segment_duration_text])
        except ValueError:
            pass
    return command


def build_multimodal_command_from_segment(segment: dict[str, Any]) -> str:
    images = [str(path).strip() for path in segment.get("images") or [] if str(path).strip()]
    videos = [str(path).strip() for path in segment.get("videos") or [] if str(path).strip()]
    audios = [str(path).strip() for path in segment.get("audios") or [] if str(path).strip()]
    raw_prompt = str(segment.get("prompt") or "").strip()
    images, videos, audios = filter_media_by_prompt_refs(raw_prompt, images, videos, audios)
    media_refs = build_media_ref_map(images, videos, audios)
    prompt = normalize_prompt_text(raw_prompt, media_refs)
    transition_prompts = [normalize_prompt_text(str(item), media_refs) for item in segment.get("transition_prompts") or [] if str(item).strip()]
    duration = str(segment.get("duration") or "").strip()
    ratio = str(segment.get("ratio") or "").strip()
    model_version = normalize_model_version(segment.get("model_version"))

    if not images and not videos:
        raise SystemExit("全能参考至少要有图片或视频，不能只放音频。")

    command = ["multimodal2video"]
    for path in images:
        command.extend(["--image", path])
    for path in videos:
        command.extend(["--video", path])
    for path in audios:
        command.extend(["--audio", path])
    if prompt:
        command.extend(["--prompt", prompt])
    if duration:
        command.extend(["--duration", duration])
    if ratio:
        command.extend(["--ratio", ratio])
    if model_version:
        command.extend(["--model_version", model_version])
    return shlex.join(command)


def build_text2video_command_from_segment(segment: dict[str, Any]) -> str:
    prompt = normalize_prompt_text(str(segment.get("prompt") or "").strip())
    if not prompt:
        raise SystemExit("文生视频任务必须填写提示词。")

    command = ["text2video", "--prompt", prompt]
    duration = str(segment.get("duration") or "").strip()
    ratio = str(segment.get("ratio") or "").strip()
    model_version = normalize_model_version(segment.get("model_version"))
    if duration:
        command.extend(["--duration", duration])
    if ratio:
        command.extend(["--ratio", ratio])
    if model_version:
        command.extend(["--model_version", model_version])
    return shlex.join(command)


def looks_like_text_reference(path: str) -> bool:
    stem = Path(str(path or "")).stem.lower()
    return any(marker.lower() in stem for marker in TEXT_REFERENCE_MARKERS)


def simplify_prompt_text(prompt: str, limit: int = SAFE_RETRY_PROMPT_CHARS) -> str:
    text = normalize_prompt_text(prompt)
    if not text:
        return ""
    text = re.sub(r"\b规则[:：]\s*", "", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    filtered: list[str] = []
    for line in lines:
        lowered = line.lower()
        if line in {"规则：", "规则:"}:
            continue
        if "不要在视频中显示任何文字" in line or "视频不要出现任何字幕" in line:
            continue
        if "输出纯净画面" in line:
            continue
        if lowered.startswith("风格：") or lowered.startswith("风格:"):
            continue
        filtered.append(line)
    compact = " ".join(filtered)
    compact = re.sub(r"\s+", " ", compact).strip(" ，。")
    if not compact:
        compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact

    pieces = re.split(r"[。！？!?；;]", compact)
    chosen: list[str] = []
    total = 0
    for piece in pieces:
        candidate = piece.strip(" ，。")
        if not candidate:
            continue
        extra = len(candidate) + (1 if chosen else 0)
        if chosen and total + extra > limit:
            break
        chosen.append(candidate)
        total += extra
        if total >= limit * 0.7:
            break
    shortened = "。".join(chosen).strip(" ，。")
    if not shortened:
        shortened = compact[:limit].rstrip(" ，。")
    return shortened


def build_safe_retry_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    if not any(entry.get(key) for key in ("prompt", "images", "videos", "audios")):
        return None

    original_images = [str(path).strip() for path in entry.get("images") or [] if str(path).strip()]
    non_text_images = [path for path in original_images if not looks_like_text_reference(path)]
    retry_images = (non_text_images or original_images)[:SAFE_RETRY_MAX_IMAGES]
    retry_videos = [str(path).strip() for path in entry.get("videos") or [] if str(path).strip()][:SAFE_RETRY_MAX_VIDEOS]
    retry_audios = [str(path).strip() for path in entry.get("audios") or [] if str(path).strip()][:SAFE_RETRY_MAX_AUDIOS]

    if not retry_images and not retry_videos:
        return None

    duration_raw = str(entry.get("duration") or "").strip()
    try:
        duration_value = int(duration_raw) if duration_raw else SAFE_RETRY_DURATION_SECONDS
    except ValueError:
        duration_value = SAFE_RETRY_DURATION_SECONDS
    retry_duration = str(min(max(duration_value, 4), SAFE_RETRY_DURATION_SECONDS))

    prompt = simplify_prompt_text(str(entry.get("prompt") or ""))
    if not prompt:
        prompt = str(entry.get("name") or "参考素材生成视频").strip()

    retry_entry = {
        "id": entry.get("id"),
        "name": str(entry.get("name") or "").strip() or "保守重试",
        "prompt": prompt,
        "images": retry_images,
        "videos": retry_videos,
        "audios": retry_audios,
        "duration": retry_duration,
        "ratio": str(entry.get("ratio") or "").strip(),
        "model_version": str(entry.get("model_version") or "").strip(),
    }
    retry_entry["command"] = build_multimodal_command_from_segment(retry_entry)
    return retry_entry


def build_ultra_safe_retry_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    original_images = [str(path).strip() for path in entry.get("images") or [] if str(path).strip()]
    non_text_images = [path for path in original_images if not looks_like_text_reference(path)]
    retry_images = (non_text_images or original_images)[:ULTRA_SAFE_RETRY_MAX_IMAGES]
    retry_videos = [str(path).strip() for path in entry.get("videos") or [] if str(path).strip()][:1]
    if not retry_images and not retry_videos:
        return None

    prompt = simplify_prompt_text(str(entry.get("prompt") or ""), limit=ULTRA_SAFE_RETRY_PROMPT_CHARS)
    prompt = re.sub(r"[【】\[\]]", "", prompt)
    prompt = re.sub(r"\s+", " ", prompt).strip(" ，。")
    if len(prompt) > ULTRA_SAFE_RETRY_PROMPT_CHARS:
        prompt = prompt[:ULTRA_SAFE_RETRY_PROMPT_CHARS].rstrip(" ，。")
    if not prompt:
        prompt = str(entry.get("name") or "参考图生成视频").strip()
    prompt = f"{prompt}，写实电影感，单镜头，无字幕。".strip()

    model_version = str(entry.get("model_version") or "").strip()
    if model_version == "seedance2.0fast":
        model_version = "seedance2.0"
    elif model_version == "seedance2.0fast_vip":
        model_version = "seedance2.0_vip"

    retry_entry = {
        "id": entry.get("id"),
        "name": str(entry.get("name") or "").strip() or "极简重试",
        "prompt": prompt,
        "images": retry_images,
        "videos": retry_videos,
        "audios": [],
        "duration": "4",
        "ratio": str(entry.get("ratio") or "").strip(),
        "model_version": model_version,
    }
    retry_entry["command"] = build_multimodal_command_from_segment(retry_entry)
    return retry_entry


def should_retry_with_safe_fallback(task: dict[str, Any], fail_reason: str | None, *, max_attempts: int = MAX_RETRY_ATTEMPTS) -> bool:
    if int(task.get("retry_count") or 0) >= max_attempts:
        return False
    reason = str(fail_reason or "").strip().lower()
    if not reason:
        return False
    if any(marker in reason for marker in NON_RETRYABLE_FAILURE_MARKERS):
        return False
    return any(marker in reason for marker in RETRYABLE_FAILURE_MARKERS)


def normalize_queue_entry(item: Any, index: int) -> dict[str, Any]:
    if isinstance(item, str):
        command = item.strip()
        return {
            "id": f"legacy-{index}",
            "name": f"片段{index}",
            "command": command,
            "prompt": "",
            "images": [],
            "transition_prompts": [],
            "videos": [],
            "audios": [],
            "duration": "",
            "ratio": "",
            "model_version": "",
        }

    if not isinstance(item, dict):
        raise SystemExit(f"第 {index} 个队列段格式无效。")

    entry = dict(item)
    entry_id = str(entry.get("id") or uuid.uuid4().hex)
    name = str(entry.get("name") or f"片段{index}").strip() or f"片段{index}"
    mode = str(entry.get("mode") or entry.get("type") or "").strip()
    command = str(entry.get("command") or "").strip()
    for key in ["images", "transition_prompts", "videos", "audios"]:
        value = entry.get(key)
        if isinstance(value, list):
            entry[key] = [str(part).strip() for part in value if str(part).strip()]
        elif value is None:
            entry[key] = []
        else:
            entry[key] = [line.strip() for line in str(value).splitlines() if line.strip()]
    has_media = bool(entry.get("images") or entry.get("videos") or entry.get("audios"))
    structured_mode = mode in {"text2video", "multimodal2video", "reference", "multimodal"}
    if not command or structured_mode or has_media:
        if mode == "text2video" or not has_media:
            mode = "text2video"
            command = build_text2video_command_from_segment(entry)
        else:
            mode = "multimodal2video"
            entry["images"], entry["videos"], entry["audios"] = filter_media_by_prompt_refs(
                str(entry.get("prompt") or ""),
                list(entry.get("images") or []),
                list(entry.get("videos") or []),
                list(entry.get("audios") or []),
            )
            command = build_multimodal_command_from_segment(entry)

    return {
        "id": entry_id,
        "name": name,
        "mode": mode,
        "project_id": str(entry.get("project_id") or ""),
        "project_name": str(entry.get("project_name") or ""),
        "download_dir": str(entry.get("download_dir") or ""),
        "command": command,
        "prompt": str(entry.get("prompt") or ""),
        "images": list(entry.get("images") or []),
        "transition_prompts": list(entry.get("transition_prompts") or []),
        "videos": list(entry.get("videos") or []),
        "audios": list(entry.get("audios") or []),
        "duration": str(entry.get("duration") or ""),
        "ratio": str(entry.get("ratio") or ""),
        "model_version": str(entry.get("model_version") or ""),
    }


def read_queue_entries(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        return []

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return [normalize_queue_entry(command, index) for index, command in enumerate(read_queue_file(path), start=1)]

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("segments")
        if items is None:
            items = payload.get("tasks")
        if items is None:
            items = payload.get("items")
    else:
        items = None

    if not isinstance(items, list):
        raise SystemExit("JSON 队列文件必须包含 segments 数组。")

    return [normalize_queue_entry(item, index) for index, item in enumerate(items, start=1)]


def sanitize_name(raw: str) -> str:
    value = re.sub(r"[^\w.-]+", "-", raw.strip(), flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "task"


def unwrap_json(value: Any) -> Any:
    current = value
    for _ in range(3):
        if not isinstance(current, str):
            break
        text = current.strip()
        if not text:
            break
        if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
            break
        try:
            current = json.loads(text)
        except json.JSONDecodeError:
            break
    return current


def collect_fields(value: Any, found: dict[str, Any]) -> None:
    value = unwrap_json(value)
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = key.lower()
            if lowered in {"submit_id", "gen_status", "fail_reason", "result_json", "result", "submit_info"}:
                if lowered not in found:
                    found[lowered] = nested
            collect_fields(nested, found)
    elif isinstance(value, list):
        for item in value:
            collect_fields(item, found)


def parse_json_blob(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    candidates = [stripped]
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    candidates.extend(lines)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        found: dict[str, Any] = {}
        collect_fields(data, found)
        return found
    return {}


def first_match(patterns: list[re.Pattern[str]], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def parse_command_output(text: str) -> dict[str, Any]:
    parsed = parse_json_blob(text)
    submit_id = parsed.get("submit_id")
    gen_status = parsed.get("gen_status")
    fail_reason = parsed.get("fail_reason")

    if not submit_id:
        submit_id = first_match(SUBMIT_ID_PATTERNS, text)
    if not gen_status:
        gen_status = first_match(GEN_STATUS_PATTERNS, text)
    if not fail_reason:
        fail_reason = first_match(FAIL_REASON_PATTERNS, text)

    urls: list[str] = []
    for pattern in RESULT_URL_PATTERNS:
        urls.extend(pattern.findall(text))
    unique_urls = list(dict.fromkeys(urls))

    normalized_status = gen_status.lower() if isinstance(gen_status, str) else None
    normalized_reason = fail_reason.strip() if isinstance(fail_reason, str) else None

    # 兜底逻辑：如果文本里明确说了 generation failed，即使没解析到状态，也认为失败
    if not normalized_status or normalized_status not in TERMINAL_STATUSES:
        lower_text = text.lower()
        if "generation failed" in lower_text or "final generation failed" in lower_text:
            normalized_status = "failed"
            if not normalized_reason:
                normalized_reason = "检测到文本输出中的生成失败标识"
        elif any(marker in lower_text for marker in NON_RETRYABLE_FAILURE_MARKERS):
            normalized_status = "failed"
            if not normalized_reason:
                # 提取具体的失败原因，比如 "post-TNS check did not pass"
                for marker in NON_RETRYABLE_FAILURE_MARKERS:
                    if marker in lower_text:
                        normalized_reason = f"审核/合规拦截: {marker}"
                        break
                if not normalized_reason:
                    normalized_reason = "检测到不可重试的失败标识（如审核未通过）"

    return {
        "submit_id": submit_id,
        "gen_status": normalized_status,
        "fail_reason": normalized_reason,
        "urls": unique_urls,
        "raw_fields": parsed,
    }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def build_task_records(entries: list[dict[str, Any]], output_root: Path, start_index: int = 1) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=start_index):
        command = str(entry["command"])
        segment_name = str(entry.get("name") or f"片段{index}")
        project_id = str(entry.get("project_id") or "")
        project_name = str(entry.get("project_name") or "")
        task_label = sanitize_name(f"{segment_name}-{command[:48]}")
        download_dir = Path(str(entry.get("download_dir") or "")).expanduser() if entry.get("download_dir") else output_root / f"{index:03d}-{task_label}"
        tasks.append(
            {
                "index": index,
                "segment_id": str(entry.get("id") or f"legacy-{index}"),
                "segment_name": segment_name,
                "project_id": project_id,
                "project_name": project_name,
                "command": command,
                "prompt": str(entry.get("prompt") or ""),
                "images": list(entry.get("images") or []),
                "transition_prompts": list(entry.get("transition_prompts") or []),
                "videos": list(entry.get("videos") or []),
                "audios": list(entry.get("audios") or []),
                "duration": str(entry.get("duration") or ""),
                "ratio": str(entry.get("ratio") or ""),
                "model_version": str(entry.get("model_version") or ""),
                "label": f"{index:03d}-{task_label}",
                "status": "pending",
                "submit_id": None,
                "gen_status": None,
                "fail_reason": None,
                "started_at": None,
                "finished_at": None,
                "download_dir": str(download_dir),
                "submit_stdout": None,
                "submit_stderr": None,
                "final_stdout": None,
                "final_stderr": None,
                "urls": [],
                "retry_attempted": False,
                "retry_count": 0,
                "retry_command": None,
                "retry_submit_id": None,
            }
        )
    return tasks


def load_state(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError, FileNotFoundError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return default
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError, FileNotFoundError):
        return default


def save_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def project_folder_name(project_id: str) -> str:
    index = load_json(PROJECTS_INDEX_FILE, {})
    for project in index.get("projects") or []:
        if isinstance(project, dict) and str(project.get("id") or "") == project_id and project.get("folder"):
            return str(project["folder"])
    return project_id


def project_queue_file(project_id: str) -> Path:
    return PROJECTS_DIR / project_folder_name(project_id) / "queue.json"


def task_is_terminal(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "").lower() in TERMINAL_STATUSES


def task_retry_requested(task: dict[str, Any]) -> bool:
    return bool(str(task.get("manual_retry_requested_at") or "").strip())


def merge_task_record(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing_status = str(existing.get("status") or "").lower()
    incoming_status = str(incoming.get("status") or "").lower()
    if existing.get("fail_reason") and not incoming.get("fail_reason"):
        incoming = {**incoming, "fail_reason": existing.get("fail_reason")}
    if task_retry_requested(incoming):
        existing.update(incoming)
        return
    if existing_status == "running" and incoming_status in {"", "pending"}:
        # A stale on-disk pending record must not hide the task currently being
        # submitted or polled by this runner.
        return
    if existing_status == "success" and incoming_status != "success":
        return
    if incoming_status == "success":
        existing.update(incoming)
        return
    if task_is_terminal(existing) and not task_is_terminal(incoming):
        return
    existing.update(incoming)


def sync_project_queue_task(task: dict[str, Any]) -> None:
    project_id = str(task.get("project_id") or "").strip()
    segment_id = str(task.get("segment_id") or "").strip()
    if not project_id or not segment_id:
        return
    queue_path = project_queue_file(project_id)
    document = load_json(queue_path, {})
    segments = document.get("segments")
    if not isinstance(segments, list):
        return
    changed = False
    for segment in segments:
        if not isinstance(segment, dict) or str(segment.get("id") or "") != segment_id:
            continue
        for key in [
            "status",
            "submit_id",
            "gen_status",
            "fail_reason",
            "started_at",
            "finished_at",
            "download_dir",
            "urls",
            "retry_count",
            "manual_retry_requested_at",
        ]:
            if key in task:
                segment[key] = task.get(key)
        changed = True
        break
    if changed:
        document["updated_at"] = now_iso()
        save_json(queue_path, document)


def sync_project_queues_from_state(state: dict[str, Any]) -> None:
    for task in state.get("tasks") or []:
        if isinstance(task, dict):
            sync_project_queue_task(task)


def prepare_state(args: argparse.Namespace, entries: list[dict[str, Any]]) -> dict[str, Any]:
    output_root = args.output_root.resolve()
    if args.state_file.exists():
        state = load_state(args.state_file)
        existing = {task_signature(task) for task in state.get("tasks", [])}
        existing_ids = {
            task_identity(task) for task in state.get("tasks", [])
            if task_identity(task)[1]
        }
        new_entries = [
            entry for entry in entries
            if entry_signature(entry) not in existing
            and entry_identity(entry) not in existing_ids
        ]
        if new_entries:
            next_index = len(state.get("tasks", [])) + 1
            state.setdefault("tasks", []).extend(build_task_records(new_entries, output_root, start_index=next_index))
            update_state(args.state_file.resolve(), state)
        return state

    state = {
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "dreamina": args.dreamina,
        "queue_file": str(args.queue_file.resolve()),
        "output_root": str(output_root),
        "poll_interval_seconds": args.poll_interval,
        "timeout_seconds": args.timeout_seconds,
        "stop_on_failure": args.stop_on_failure,
        "tasks": build_task_records(entries, output_root),
    }
    save_state(args.state_file, state)
    return state


def task_signature(task: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(task.get("project_id") or ""),
        str(task.get("segment_id") or ""),
        str(task.get("command") or ""),
    )


def task_identity(task: dict[str, Any]) -> tuple[str, str]:
    return (
        str(task.get("project_id") or ""),
        str(task.get("segment_id") or ""),
    )


def entry_signature(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("project_id") or ""),
        str(entry.get("id") or ""),
        str(entry.get("command") or ""),
    )


def entry_identity(entry: dict[str, Any]) -> tuple[str, str]:
    return (
        str(entry.get("project_id") or ""),
        str(entry.get("id") or ""),
    )


def merge_external_state_tasks(state: dict[str, Any], state_path: Path) -> int:
    external_state = load_state(state_path)
    external_tasks = external_state.get("tasks")
    if not isinstance(external_tasks, list):
        return 0

    tasks = state.setdefault("tasks", [])
    by_identity = {task_identity(task): task for task in tasks if task_identity(task)[1]}
    by_signature = {task_signature(task): task for task in tasks}
    added = []
    updated = 0
    for task in external_tasks:
        target = by_identity.get(task_identity(task)) or by_signature.get(task_signature(task))
        if target:
            before = json.dumps(target, ensure_ascii=False, sort_keys=True)
            merge_task_record(target, task)
            after = json.dumps(target, ensure_ascii=False, sort_keys=True)
            if before != after:
                updated += 1
            continue
        added.append(task)
    if not added:
        if updated:
            log(f"合并 {updated} 个外部状态更新。")
        return 0

    tasks.extend(added)
    log(f"合并 {len(added)} 个外部追加任务，更新 {updated} 个已有任务。")
    return len(added)


def merge_external_state_before_save(state: dict[str, Any], state_path: Path) -> None:
    if state_path.exists():
        merge_external_state_tasks(state, state_path)


def append_new_tasks_from_queue(args: argparse.Namespace, state: dict[str, Any], state_path: Path) -> int:
    merge_external_state_tasks(state, state_path)
    try:
        entries = read_queue_entries(args.queue_file)
    except Exception as exc:
        log(f"刷新队列文件失败，保留当前队列继续执行: {exc}")
        return 0

    existing = {task_signature(task) for task in state.get("tasks", [])}
    existing_ids = {
        task_identity(task) for task in state.get("tasks", [])
        if task_identity(task)[1]
    }
    new_entries = [
        entry for entry in entries
        if entry_signature(entry) not in existing
        and entry_identity(entry) not in existing_ids
    ]
    if not new_entries:
        return 0

    output_root = args.output_root.resolve()
    next_index = len(state.get("tasks", [])) + 1
    new_tasks = build_task_records(new_entries, output_root, start_index=next_index)
    state.setdefault("tasks", []).extend(new_tasks)
    update_state(state_path, state)
    log(f"检测到 {len(new_tasks)} 个新任务，已追加到队列末尾。")
    return len(new_tasks)


def expand_command(dreamina: str, raw_command: str) -> list[str]:
    parts = shlex.split(raw_command)
    if not parts:
        raise ValueError("空命令")
    if parts[0] == "dreamina":
        return [dreamina, *parts[1:]]
    return [dreamina, *parts]


def run_command(command: list[str]) -> CommandResult:
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        command=command,
    )


def compact_command(command: list[str], max_chars: int = 360) -> str:
    text = " ".join(shlex.quote(part) for part in command)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def command_failure_reason(result: CommandResult, stage: str) -> str:
    output = result.combined.strip()
    if output:
        return output
    return (
        f"{stage} 执行失败：dreamina 返回码 {result.returncode}，但 stdout/stderr 为空。"
        f"命令：{compact_command(result.command)}"
    )


def should_stop_queue_for_failure(fail_reason: str | None) -> bool:
    text = str(fail_reason or "").lower()
    return "exceedconcurrencylimit" in text or "ret=1310" in text


def persist_command_logs(base_dir: Path, prefix: str, result: CommandResult) -> None:
    ensure_dir(base_dir)
    write_text(base_dir / f"{prefix}.stdout.log", result.stdout)
    write_text(base_dir / f"{prefix}.stderr.log", result.stderr)


def update_state(state_path: Path, state: dict[str, Any]) -> None:
    merge_external_state_before_save(state, state_path)
    state["updated_at"] = now_iso()
    save_state(state_path, state)
    sync_project_queues_from_state(state)


def patch_task_in_state(state_path: Path, task: dict[str, Any], updates: dict[str, Any]) -> None:
    state = load_state(state_path)
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        return

    identity = task_identity(task)
    signature = task_signature(task)
    target = None
    for candidate in tasks:
        if not isinstance(candidate, dict):
            continue
        if identity[1] and task_identity(candidate) == identity:
            target = candidate
            break
        if task_signature(candidate) == signature:
            target = candidate
            break
    if target is None:
        return

    target.update(updates)
    for key in [
        "index",
        "segment_id",
        "segment_name",
        "project_id",
        "project_name",
        "command",
        "prompt",
        "images",
        "transition_prompts",
        "videos",
        "audios",
        "duration",
        "ratio",
        "model_version",
        "label",
        "download_dir",
    ]:
        if key in task and key not in target:
            target[key] = task.get(key)
    state["updated_at"] = now_iso()
    save_state(state_path, state)
    sync_project_queue_task(target)


def status_from_polled_result(parsed: dict[str, Any]) -> str:
    gen_status = str(parsed.get("gen_status") or "").strip().lower()
    if gen_status in SUCCESS_STATUSES:
        return "success"
    if gen_status in FAIL_STATUSES or parsed.get("fail_reason"):
        return "failed"
    return "running"


def wait_for_completion(
    dreamina: str,
    submit_id: str,
    download_dir: Path,
    poll_interval: int,
    timeout_seconds: int,
    task_log_dir: Path,
    log_prefix: str = "query",
    on_status: Any | None = None,
) -> tuple[dict[str, Any], CommandResult]:
    started = time.time()
    last_result: CommandResult | None = None
    last_parsed: dict[str, Any] = {}

    while True:
        elapsed = time.time() - started
        if elapsed > timeout_seconds:
            raise TimeoutError(f"任务 {submit_id} 超过等待上限 {timeout_seconds} 秒")

        query_cmd = [dreamina, "query_result", f"--submit_id={submit_id}"]
        result = run_command(query_cmd)
        persist_command_logs(task_log_dir, f"{log_prefix}-{int(elapsed)}", result)
        parsed = parse_command_output(result.combined)
        last_result = result
        last_parsed = parsed
        status = parsed.get("gen_status")
        if on_status:
            on_status(parsed, result)

        if result.returncode != 0 and status not in TERMINAL_STATUSES:
            raise RuntimeError(command_failure_reason(result, "查询阶段"))

        if status in SUCCESS_STATUSES:
            ensure_dir(download_dir)
            final_cmd = [dreamina, "query_result", f"--submit_id={submit_id}", f"--download_dir={download_dir}"]
            final_result = run_command(final_cmd)
            persist_command_logs(task_log_dir, f"{log_prefix}-final-download", final_result)
            final_parsed = parse_command_output(final_result.combined)
            if final_result.returncode != 0 and final_parsed.get("gen_status") not in SUCCESS_STATUSES:
                raise RuntimeError(command_failure_reason(final_result, "成功后下载阶段"))
            merged = {**parsed, **final_parsed}
            urls = list(dict.fromkeys([*parsed.get("urls", []), *final_parsed.get("urls", [])]))
            merged["urls"] = urls
            return merged, final_result

        if status in FAIL_STATUSES:
            return parsed, result

        log(f"submit_id={submit_id} 仍在排队/生成中，{poll_interval}s 后继续查询")
        time.sleep(poll_interval)


def execute_task_attempt(
    args: argparse.Namespace,
    task: dict[str, Any],
    task_log_dir: Path,
    command_text: str,
    state_path: Path,
    submit_prefix: str = "submit",
    query_prefix: str = "query",
) -> dict[str, Any]:
    command = expand_command(args.dreamina, command_text)
    log(f"开始任务 #{task['index']}: {' '.join(shlex.quote(part) for part in command)}")
    submit_result = run_command(command)
    persist_command_logs(task_log_dir, submit_prefix, submit_result)

    parsed_submit = parse_command_output(submit_result.combined)
    status = parsed_submit.get("gen_status")
    attempt: dict[str, Any] = {
        "command": command_text,
        "submit_stdout": str(task_log_dir / f"{submit_prefix}.stdout.log"),
        "submit_stderr": str(task_log_dir / f"{submit_prefix}.stderr.log"),
        "submit_id": parsed_submit.get("submit_id"),
        "gen_status": status,
        "fail_reason": parsed_submit.get("fail_reason"),
        "urls": parsed_submit.get("urls", []),
        "final_stdout": None,
        "final_stderr": None,
        "status": "failed",
    }

    if submit_result.returncode != 0 and not attempt["submit_id"]:
        attempt["fail_reason"] = attempt["fail_reason"] or command_failure_reason(submit_result, "提交阶段")
        return attempt

    submit_id = attempt["submit_id"]
    if not submit_id:
        attempt["fail_reason"] = "提交结果里没有解析到 submit_id，无法继续排队"
        return attempt

    patch_task_in_state(
        state_path,
        task,
        {
            "status": status_from_polled_result(parsed_submit),
            "submit_id": submit_id,
            "gen_status": status or "processing",
            "fail_reason": parsed_submit.get("fail_reason"),
            "submit_stdout": attempt["submit_stdout"],
            "submit_stderr": attempt["submit_stderr"],
            "started_at": task.get("started_at") or now_iso(),
            "finished_at": None,
            "download_dir": task.get("download_dir"),
        },
    )

    if status in SUCCESS_STATUSES:
        attempt["status"] = "success"
        return attempt

    if status in FAIL_STATUSES:
        if not attempt["fail_reason"]:
            attempt["fail_reason"] = command_failure_reason(submit_result, "提交阶段")
        return attempt

    try:
        final_parsed, final_result = wait_for_completion(
            dreamina=args.dreamina,
            submit_id=submit_id,
            download_dir=Path(task["download_dir"]),
            poll_interval=args.poll_interval,
            timeout_seconds=args.timeout_seconds,
            task_log_dir=task_log_dir,
            log_prefix=query_prefix,
            on_status=lambda parsed, _result: patch_task_in_state(
                state_path,
                task,
                {
                    "status": status_from_polled_result(parsed),
                    "submit_id": submit_id,
                    "gen_status": parsed.get("gen_status") or "processing",
                    "fail_reason": parsed.get("fail_reason"),
                    "download_dir": task.get("download_dir"),
                },
            ),
        )
    except Exception as exc:
        attempt["fail_reason"] = str(exc)
        return attempt

    attempt["final_stdout"] = str(task_log_dir / f"{query_prefix}-final-download.stdout.log")
    attempt["final_stderr"] = str(task_log_dir / f"{query_prefix}-final-download.stderr.log")
    attempt["gen_status"] = final_parsed.get("gen_status")
    attempt["fail_reason"] = final_parsed.get("fail_reason")
    attempt["urls"] = final_parsed.get("urls", [])
    if final_parsed.get("gen_status") in SUCCESS_STATUSES:
        attempt["status"] = "success"
        return attempt

    attempt["fail_reason"] = attempt["fail_reason"] or command_failure_reason(final_result, "下载/查询阶段")
    return attempt


def continue_task_from_submit_id(
    args: argparse.Namespace,
    task: dict[str, Any],
    task_log_dir: Path,
    submit_id: str,
    state_path: Path,
) -> dict[str, Any]:
    log(f"继续查询任务 #{task['index']}，submit_id={submit_id}")
    try:
        final_parsed, final_result = wait_for_completion(
            dreamina=args.dreamina,
            submit_id=submit_id,
            download_dir=Path(task["download_dir"]),
            poll_interval=args.poll_interval,
            timeout_seconds=args.timeout_seconds,
            task_log_dir=task_log_dir,
            log_prefix="resume-query",
            on_status=lambda parsed, _result: patch_task_in_state(
                state_path,
                task,
                {
                    "status": status_from_polled_result(parsed),
                    "submit_id": submit_id,
                    "gen_status": parsed.get("gen_status") or "processing",
                    "fail_reason": parsed.get("fail_reason"),
                    "download_dir": task.get("download_dir"),
                },
            ),
        )
    except Exception as exc:
        return {
            "command": str(task.get("command") or ""),
            "submit_stdout": task.get("submit_stdout"),
            "submit_stderr": task.get("submit_stderr"),
            "submit_id": submit_id,
            "gen_status": "failed",
            "fail_reason": str(exc),
            "urls": [],
            "final_stdout": None,
            "final_stderr": None,
            "status": "failed",
        }

    return {
        "command": str(task.get("command") or ""),
        "submit_stdout": task.get("submit_stdout"),
        "submit_stderr": task.get("submit_stderr"),
        "submit_id": submit_id,
        "gen_status": final_parsed.get("gen_status"),
        "fail_reason": final_parsed.get("fail_reason"),
        "urls": final_parsed.get("urls", []),
        "final_stdout": str(task_log_dir / "resume-query-final-download.stdout.log"),
        "final_stderr": str(task_log_dir / "resume-query-final-download.stderr.log"),
        "status": "success" if final_parsed.get("gen_status") in SUCCESS_STATUSES else "failed",
    }


def apply_attempt_to_task(task: dict[str, Any], attempt: dict[str, Any], *, is_retry: bool = False) -> None:
    task["command"] = attempt["command"]
    task["submit_stdout"] = attempt["submit_stdout"]
    task["submit_stderr"] = attempt["submit_stderr"]
    task["submit_id"] = attempt["submit_id"]
    task["gen_status"] = attempt["gen_status"]
    task["fail_reason"] = attempt["fail_reason"]
    task["urls"] = attempt["urls"]
    task["final_stdout"] = attempt["final_stdout"]
    task["final_stderr"] = attempt["final_stderr"]
    
    # 强制同步 status，确保不会出现 "running" 状态却有 "fail_reason" 的情况
    if attempt.get("status"):
        task["status"] = attempt["status"]
    elif task["fail_reason"]:
        task["status"] = "failed"

    if is_retry:
        task["retry_attempted"] = True
        task["retry_count"] = int(task.get("retry_count") or 0) + 1
        task["retry_command"] = attempt["command"]
        task["retry_submit_id"] = attempt["submit_id"]


def run_queue(args: argparse.Namespace) -> int:
    entries = read_queue_entries(args.queue_file)
    if not entries:
        raise SystemExit("队列文件里没有可执行命令。")

    output_root = args.output_root.resolve()
    ensure_dir(output_root)
    state = prepare_state(args, entries)
    state_path = args.state_file.resolve()

    if args.resume:
        state["tasks"].sort(
            key=lambda task: (
                0 if str(task.get("status") or "") == "running" and str(task.get("submit_id") or "").strip() else 1,
                int(task.get("index") or 0),
            )
        )
        for index, task in enumerate(state["tasks"], start=1):
            task["index"] = index
        update_state(state_path, state)

    task_index = 0
    while task_index < len(state["tasks"]):
        task = state["tasks"][task_index]
        if task["status"] == "success":
            log(f"跳过已完成任务 #{task['index']} submit_id={task.get('submit_id') or '-'}")
            task_index += 1
            append_new_tasks_from_queue(args, state, state_path)
            continue
        if str(task.get("status") or "").lower() in TERMINAL_STATUSES:
            log(f"跳过终态任务 #{task['index']} status={task.get('status') or '-'} submit_id={task.get('submit_id') or '-'}")
            task_index += 1
            append_new_tasks_from_queue(args, state, state_path)
            continue
        if task["status"] in {"running", "paused"}:
            submit_id = str(task.get("submit_id") or "").strip()
            if submit_id:
                label = task["label"]
                task_log_dir = output_root / "logs" / label
                ensure_dir(task_log_dir)
                attempt = continue_task_from_submit_id(args, task, task_log_dir, submit_id, state_path)
                apply_attempt_to_task(task, attempt)
                task["finished_at"] = now_iso()
                update_state(state_path, state)
                if task["status"] == "success":
                    log(f"任务 #{task['index']} 续跑完成，submit_id={submit_id}，已下载到 {task['download_dir']}")
                    task_index += 1
                    append_new_tasks_from_queue(args, state, state_path)
                    continue
                log(f"任务 #{task['index']} 续跑失败，submit_id={submit_id}，原因: {task.get('fail_reason') or '-'}")
                if should_stop_queue_for_failure(task.get("fail_reason")):
                    log("检测到平台并发限制，已停止继续提交，剩余 pending 任务保留在队列中。")
                    return 1
                if args.stop_on_failure:
                    return 1
                task_index += 1
                append_new_tasks_from_queue(args, state, state_path)
                continue
            if args.resume:
                task["status"] = "pending"

        label = task["label"]
        task_log_dir = output_root / "logs" / label
        ensure_dir(task_log_dir)
        task["started_at"] = task.get("started_at") or now_iso()
        task["status"] = "running"
        task["fail_reason"] = None
        task["gen_status"] = "processing"
        task["finished_at"] = None
        update_state(state_path, state)
        patch_task_in_state(
            state_path,
            task,
            {
                "status": "running",
                "submit_id": task.get("submit_id"),
                "gen_status": "processing",
                "fail_reason": None,
                "started_at": task["started_at"],
                "finished_at": None,
                "download_dir": task.get("download_dir"),
            },
        )
        first_attempt = execute_task_attempt(args, task, task_log_dir, task["command"], state_path)
        apply_attempt_to_task(task, first_attempt)

        final_attempt = first_attempt
        task["status"] = final_attempt["status"]
        task["finished_at"] = now_iso()
        merge_external_state_tasks(state, state_path)
        update_state(state_path, state)

        if final_attempt["status"] == "success":
            if task.get("retry_attempted"):
                log(
                    f"任务 #{task['index']} 保守重试后完成，submit_id={task.get('submit_id') or '-'}，已下载到 {task['download_dir']}"
                )
            else:
                log(f"任务 #{task['index']} 完成，submit_id={task.get('submit_id') or '-'}，已下载到 {task['download_dir']}")
            task_index += 1
            append_new_tasks_from_queue(args, state, state_path)
            continue

        log(f"任务 #{task['index']} 失败，submit_id={task.get('submit_id') or '-'}，原因: {task.get('fail_reason') or '-'}")
        if should_stop_queue_for_failure(task.get("fail_reason")):
            log("检测到平台并发限制，已停止继续提交，剩余 pending 任务保留在队列中。")
            return 1
        if args.stop_on_failure:
            return 1
        task_index += 1
        append_new_tasks_from_queue(args, state, state_path)
        continue

    failures = [task for task in state["tasks"] if task["status"] == "failed"]
    successes = [task for task in state["tasks"] if task["status"] == "success"]
    log(f"队列结束：成功 {len(successes)} 个，失败 {len(failures)} 个，state 文件: {state_path}")
    return 1 if failures and args.stop_on_failure else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="串行执行 dreamina 视频生成任务：上一个完成后自动轮询并提交下一个。",
    )
    parser.add_argument(
        "--queue-file",
        type=Path,
        required=True,
        help="队列文件路径。每行一条 dreamina 生成命令，支持空行和 # 注释。",
    )
    parser.add_argument(
        "--dreamina",
        default="dreamina",
        help="dreamina 可执行程序路径，默认直接从 PATH 查找。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("./queue-output"),
        help="输出目录，保存下载结果、日志和状态文件。",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=APP_DIR / "queue-state.json",
        help="状态文件路径，用于断点续跑。",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="轮询 query_result 的时间间隔，单位秒，默认 30。",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="单个任务最多等待多久，默认 10800 秒（3 小时）。",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从已有 state 文件恢复，跳过已成功任务。",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="任一任务失败后立即停止队列。默认失败后继续跑剩余任务。",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_queue(args)


if __name__ == "__main__":
    sys.exit(main())
