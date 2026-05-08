#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.parse import unquote
import shlex


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / ".webui"
DEFAULT_QUEUE_FILE = APP_DIR / "web.queue.json"
LEGACY_DEFAULT_QUEUE_FILE = APP_DIR / "web.queue.txt"
PROJECTS_DIR = APP_DIR / "projects"
PROJECTS_INDEX_FILE = APP_DIR / "projects.json"
GLOBAL_QUEUE_FILE = APP_DIR / "global.queue.json"
DEFAULT_OUTPUT_ROOT = ROOT / "web-output"
DEFAULT_STATE_FILE = APP_DIR / "queue-state.json"
RUNNER_META_FILE = APP_DIR / "runner.json"
RUNNER_LOG_FILE = APP_DIR / "runner.log"
UI_CONFIG_FILE = APP_DIR / "ui-config.json"
UPLOAD_DIR = APP_DIR / "uploads"
LOCK = threading.Lock()
MEDIA_SUFFIXES = {".mp4", ".mov", ".webm"}
TERMINAL_TASK_STATUSES = {"success", "failed", "fail", "rejected", "banned", "error", "cancelled"}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return default
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return default


def detect_dreamina_path() -> str | None:
    candidates = [
        shutil.which("dreamina"),
        str(Path.home() / ".local/bin/dreamina"),
        str(Path.home() / "bin/dreamina"),
        str(Path.home() / ".local/bin/dreamina.exe"),
        str(Path.home() / "bin/dreamina.exe"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


def save_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def normalize_queue_file_path(value: Any = None) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else DEFAULT_QUEUE_FILE
    try:
        if path.resolve() == LEGACY_DEFAULT_QUEUE_FILE.resolve():
            return DEFAULT_QUEUE_FILE
    except OSError:
        pass
    return path


def migrate_legacy_default_queue_file() -> None:
    if DEFAULT_QUEUE_FILE.exists() or not LEGACY_DEFAULT_QUEUE_FILE.exists():
        return
    ensure_dir(DEFAULT_QUEUE_FILE.parent)
    DEFAULT_QUEUE_FILE.write_text(LEGACY_DEFAULT_QUEUE_FILE.read_text(encoding="utf-8"), encoding="utf-8")


def load_ui_config() -> dict[str, Any]:
    migrate_legacy_default_queue_file()
    config = load_json(UI_CONFIG_FILE, {})
    if config.get("queue_file"):
        normalized = normalize_queue_file_path(config.get("queue_file"))
        if normalized == DEFAULT_QUEUE_FILE and str(config.get("queue_file")) != str(DEFAULT_QUEUE_FILE):
            config["queue_file"] = str(DEFAULT_QUEUE_FILE)
            save_json(UI_CONFIG_FILE, config)
    return config


def save_ui_config(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_ui_config()
    current.update({key: value for key, value in patch.items() if value is not None})
    save_json(UI_CONFIG_FILE, current)
    return current


def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 检查是否是僵尸进程
    try:
        import subprocess
        result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, timeout=1)
        stat = result.stdout.strip()
        # Z 或 Z+ 表示僵尸进程
        if stat.startswith("Z"):
            return False
    except Exception:
        pass
    return True


def read_runner_meta() -> dict[str, Any]:
    meta = load_json(RUNNER_META_FILE, {})
    pid = meta.get("pid")
    was_running = bool(meta.get("running"))
    if isinstance(pid, int) and pid > 0:
        meta["running"] = is_pid_running(pid)
    else:
        meta["running"] = False
    if was_running and not meta["running"]:
        meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save_json(RUNNER_META_FILE, meta)
    return meta


def tail_text(path: Path, max_lines: int = 120) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def queue_file_text(path: Path) -> str:
    if not path.exists():
        return json.dumps({"version": 1, "segments": []}, ensure_ascii=False, indent=2)
    return path.read_text(encoding="utf-8")


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
        line = raw_line.strip()
        if not current and (not line or line.startswith("#")):
            continue
        if not line:
            if current and is_command_complete("\n".join(current)):
                commands.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
        candidate = "\n".join(current).strip()
        if candidate and is_command_complete(candidate):
            commands.append(candidate)
            current = []

    if current:
        commands.append("\n".join(current).strip())
    return commands


def default_queue_document() -> dict[str, Any]:
    return {"version": 1, "segments": []}


def normalize_queue_segment(segment: Any, index: int) -> dict[str, Any]:
    if isinstance(segment, str):
        return {
            "id": f"legacy-{index}",
            "name": f"片段{index}",
            "mode": "",
            "command": segment.strip(),
            "prompt": "",
            "images": [],
            "videos": [],
            "audios": [],
            "duration": "",
            "ratio": "",
            "model_version": "",
        }

    if not isinstance(segment, dict):
        raise ValueError("队列段格式无效。")

    normalized = dict(segment)
    normalized["id"] = str(normalized.get("id") or uuid.uuid4().hex)
    normalized["name"] = str(normalized.get("name") or f"片段{index}").strip() or f"片段{index}"
    normalized["mode"] = str(normalized.get("mode") or normalized.get("type") or "").strip()
    normalized["command"] = str(normalized.get("command") or "").strip()
    normalized["prompt"] = str(normalized.get("prompt") or "").strip()
    normalized["duration"] = str(normalized.get("duration") or "").strip()
    normalized["ratio"] = str(normalized.get("ratio") or "").strip()
    normalized["model_version"] = str(normalized.get("model_version") or "").strip()
    for key in ["images", "videos", "audios"]:
        value = normalized.get(key)
        if isinstance(value, list):
            normalized[key] = [str(item).strip() for item in value if str(item).strip()]
        else:
            normalized[key] = parse_line_values(value)
    return normalized


def parse_queue_document(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return default_queue_document()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        commands = read_queue_commands_from_text(text)
        return {
            "version": 1,
            "segments": [normalize_queue_segment(command, index) for index, command in enumerate(commands, start=1)],
        }

    if isinstance(payload, list):
        segments = payload
        version = 1
    elif isinstance(payload, dict):
        segments = payload.get("segments")
        if segments is None:
            segments = payload.get("tasks")
        if segments is None:
            segments = payload.get("items")
        if segments is None:
            raise ValueError("JSON 队列里缺少 segments 字段。")
        version = int(payload.get("version") or 1)
    else:
        raise ValueError("队列文件必须是 JSON 对象或数组。")

    if not isinstance(segments, list):
        raise ValueError("segments 必须是数组。")

    return {
        "version": version,
        "segments": [normalize_queue_segment(segment, index) for index, segment in enumerate(segments, start=1)],
    }


def queue_document_to_text(document: dict[str, Any]) -> str:
    normalized = {
        "version": int(document.get("version") or 1),
        "segments": [normalize_queue_segment(segment, index) for index, segment in enumerate(document.get("segments", []), start=1)],
    }
    return json.dumps(normalized, ensure_ascii=False, indent=2)


def visible_queue_text(state: dict[str, Any], queue_file: Path) -> str:
    raw_text = queue_file_text(queue_file)
    document = parse_queue_document(raw_text)
    segments = document.get("segments", [])
    tasks = state.get("tasks")
    if not isinstance(tasks, list) or not tasks or not segments:
        return raw_text

    terminal_statuses = {"success", "failed", "fail", "rejected", "banned", "error", "cancelled"}

    def is_completed(task: dict[str, Any]) -> bool:
        if task.get("fail_reason"):
            return True
        return str(task.get("status") or "").strip().lower() in terminal_statuses

    completed_ids = {
        str(task.get("segment_id") or "").strip()
        for task in tasks
        if is_completed(task) and str(task.get("segment_id") or "").strip()
    }
    completed_counts: dict[str, int] = {}
    for task in tasks:
        command = str(task.get("command") or "").strip()
        if command and is_completed(task):
            completed_counts[command] = completed_counts.get(command, 0) + 1

    visible_segments: list[dict[str, Any]] = []
    for segment in segments:
        segment_id = str(segment.get("id") or "").strip()
        if segment_id and segment_id in completed_ids:
            continue
        command = str(segment.get("command") or "").strip()
        matched = completed_counts.get(command, 0)
        if command and matched > 0:
            completed_counts[command] = matched - 1
            continue
        visible_segments.append(segment)

    return queue_document_to_text({"version": document.get("version", 1), "segments": visible_segments})


def sanitize_filename(name: str) -> str:
    base = Path(name or "file").name
    base = re.sub(r"[^\w.\-]+", "-", base, flags=re.UNICODE)
    return base.strip("-") or "file"


def parse_line_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).splitlines()
    return [str(item).strip() for item in items if str(item).strip()]


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_folder_name(project_id)


def project_file(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def project_queue_file(project_id: str) -> Path:
    return project_dir(project_id) / "queue.json"


def project_upload_root(project_id: str) -> Path:
    return project_dir(project_id) / "uploads"


def project_output_root(project_id: str, base_output_root: Path | None = None) -> Path:
    # Keep generated videos with the project itself. The runner-level
    # output_root is still used for global state/logs, but each task receives
    # an explicit project-local download_dir.
    return project_dir(project_id) / "outputs"


def project_segment_output_dir(project_id: str, segment_name: str, segment_id: str = "") -> Path:
    label = sanitize_filename(str(segment_name or segment_id or "task"))
    return project_output_root(project_id) / label


def has_downloaded_video(path: Path | str | None) -> bool:
    if not path:
        return False
    directory = Path(str(path)).expanduser()
    if not directory.is_absolute():
        directory = ROOT / directory
    if not directory.exists() or not directory.is_dir():
        return False
    return any(child.is_file() and child.suffix.lower() in MEDIA_SUFFIXES for child in directory.iterdir())


def segment_is_success(project_id: str, segment: dict[str, Any]) -> bool:
    status = str(segment.get("status") or "").lower()
    if status == "success":
        return True
    segment_id = str(segment.get("id") or "").strip()
    segment_name = str(segment.get("name") or "").strip()
    return has_downloaded_video(segment.get("download_dir") or segment.get("output_dir") or project_segment_output_dir(project_id, segment_name, segment_id))


def segment_is_terminal(project_id: str, segment: dict[str, Any]) -> bool:
    status = str(segment.get("status") or "").lower()
    return status in TERMINAL_TASK_STATUSES or segment_is_success(project_id, segment)


def sync_project_queue_task(task: dict[str, Any]) -> None:
    project_id = str(task.get("project_id") or "").strip()
    segment_id = str(task.get("segment_id") or "").strip()
    if not project_id or not segment_id:
        return
    queue_path = project_queue_file(project_id)
    document = parse_queue_document(queue_file_text(queue_path))
    changed = False
    for segment in document.get("segments", []):
        if str(segment.get("id") or "") != segment_id:
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
        queue_path.write_text(queue_document_to_text(document), encoding="utf-8")


def merge_existing_segment_status(project_id: str, document: dict[str, Any]) -> dict[str, Any]:
    queue_path = project_queue_file(project_id)
    previous = parse_queue_document(queue_file_text(queue_path))
    previous_by_id = {
        str(segment.get("id") or ""): segment
        for segment in previous.get("segments", [])
        if isinstance(segment, dict) and str(segment.get("id") or "")
    }
    status_keys = [
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
    ]
    for segment in document.get("segments", []):
        if not isinstance(segment, dict):
            continue
        previous_segment = previous_by_id.get(str(segment.get("id") or ""))
        if not previous_segment:
            continue
        for key in status_keys:
            if key in previous_segment and key not in segment:
                segment[key] = previous_segment[key]
    return document


def sync_project_queues_from_state(state: dict[str, Any]) -> None:
    for task in state.get("tasks") or []:
        if isinstance(task, dict):
            sync_project_queue_task(task)


def save_queue_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    save_json(path, state)
    sync_project_queues_from_state(state)


def clear_stale_running_tasks(state_file: Path, state: dict[str, Any], runner: dict[str, Any]) -> dict[str, Any]:
    if runner.get("running"):
        return state
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        return state

    changed = False
    stopped_at = runner.get("finished_at") or now_iso()
    for task in tasks:
        if not isinstance(task, dict) or str(task.get("status") or "").lower() != "running":
            continue
        submit_id = str(task.get("submit_id") or "").strip()
        if submit_id:
            task["status"] = "paused"
            task["gen_status"] = task.get("gen_status") or "processing"
            task["fail_reason"] = (
                "runner 已停止；该任务已有 submit_id，未继续本地轮询。"
                "再次启动队列会用这个 submit_id 继续查询/下载，不会重复提交。"
            )
            task["finished_at"] = task.get("finished_at") or stopped_at
            changed = True
            continue
        task["status"] = "failed"
        task["gen_status"] = task.get("gen_status") or "interrupted"
        task["fail_reason"] = (
            f"runner 已停止，但任务仍停留在 running。"
            "已标记为 failed，避免重复提交。"
        )
        task["finished_at"] = task.get("finished_at") or stopped_at
        changed = True

    if changed:
        save_queue_state(state_file, state)
    return state


def normalize_state_file_path(value: Any | None = None) -> Path:
    return DEFAULT_STATE_FILE.resolve()


def short_project_suffix(project_id: str) -> str:
    value = sanitize_filename(project_id)
    if value.startswith("project-"):
        return value.split("project-", 1)[1][:10] or value[-10:]
    return value[-10:]


def make_project_folder_name(name: str, project_id: str) -> str:
    stem = sanitize_filename(name or "项目")
    suffix = short_project_suffix(project_id)
    return sanitize_filename(f"{stem}-{suffix}") if suffix else stem


def is_legacy_project_folder(folder: str, project_id: str) -> bool:
    return sanitize_filename(folder) == sanitize_filename(project_id)


def project_folder_name(project_id: str) -> str:
    safe_id = sanitize_filename(project_id)
    index = load_json(PROJECTS_INDEX_FILE, {})
    raw_projects = index.get("projects") if isinstance(index, dict) else None
    if isinstance(raw_projects, list):
        for item in raw_projects:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "") == project_id and item.get("folder"):
                return sanitize_filename(str(item.get("folder")))

    direct = PROJECTS_DIR / safe_id / "project.json"
    if direct.exists():
        return safe_id

    if PROJECTS_DIR.is_dir():
        for path in PROJECTS_DIR.glob("*/project.json"):
            try:
                payload = load_json(path, {})
            except Exception:
                continue
            if str(payload.get("id") or "") == project_id:
                return path.parent.name
    return safe_id


def default_project_record(name: str = "默认项目") -> dict[str, Any]:
    project_id = f"project-{uuid.uuid4().hex[:10]}"
    timestamp = now_iso()
    return {
        "id": project_id,
        "name": name,
        "description": "",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def normalize_project_record(project: dict[str, Any], index: int = 1, fallback_id: str | None = None) -> dict[str, Any]:
    project_id = str(project.get("id") or fallback_id or f"project-{uuid.uuid4().hex[:10]}").strip()
    name = str(project.get("name") or f"项目{index}").strip() or f"项目{index}"
    folder = str(project.get("folder") or "").strip()
    if not folder or is_legacy_project_folder(folder, project_id):
        folder = make_project_folder_name(name, project_id)
    return {
        "id": sanitize_filename(project_id),
        "name": name,
        "folder": sanitize_filename(folder),
        "description": str(project.get("description") or ""),
        "created_at": str(project.get("created_at") or now_iso()),
        "updated_at": str(project.get("updated_at") or now_iso()),
    }


def save_project_record(project: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_project_record(project)
    old_dir = project_dir(normalized["id"])
    next_dir = PROJECTS_DIR / normalized["folder"]
    if old_dir.exists() and old_dir != next_dir and not next_dir.exists():
        old_dir.rename(next_dir)
    ensure_dir(next_dir)
    save_json(next_dir / "project.json", normalized)
    return normalized


def load_project_record(project_id: str) -> dict[str, Any] | None:
    path = project_file(project_id)
    if not path.exists():
        return None
    payload = load_json(path, {})
    if isinstance(payload, dict) and not payload.get("folder"):
        payload["folder"] = path.parent.name
    return normalize_project_record(payload, fallback_id=project_id)


def load_projects() -> list[dict[str, Any]]:
    ensure_dir(PROJECTS_DIR)
    
    # 优先从物理目录扫描，确保不漏掉任何项目
    projects: list[dict[str, Any]] = []
    seen_folders = set()
    
    # 扫描所有物理文件夹
    for path in sorted(PROJECTS_DIR.glob("*/project.json")):
        folder_name = path.parent.name
        if folder_name in seen_folders:
            continue
            
        payload = load_json(path, {})
        # 如果文件为空或损坏，尝试从文件夹名恢复
        fallback_name = "新项目"
        fallback_id = None
        
        if "-" in folder_name:
            parts = folder_name.split("-")
            if len(parts) >= 2:
                fallback_id = f"project-{parts[-1]}"
                fallback_name = "-".join(parts[:-1])
        
        if isinstance(payload, dict):
            if not payload.get("name"):
                payload["name"] = fallback_name
            if not payload.get("folder"):
                payload["folder"] = folder_name
        else:
            payload = {"name": fallback_name, "folder": folder_name}
            
        stored = normalize_project_record(payload, index=len(projects) + 1, fallback_id=fallback_id)
        projects.append(save_project_record(stored))
        seen_folders.add(folder_name)

    # 如果物理目录没有任何项目，创建一个默认的
    if not projects:
        projects = [create_project("默认项目", migrate_legacy=True)]
    
    save_projects_index(projects)
    return projects


def save_projects_index(projects: list[dict[str, Any]]) -> None:
    normalized = [normalize_project_record(project, index) for index, project in enumerate(projects, start=1)]
    for project in normalized:
        save_project_record(project)
    save_json(PROJECTS_INDEX_FILE, {"version": 1, "projects": normalized})


def create_project(name: str, *, migrate_legacy: bool = False) -> dict[str, Any]:
    project = save_project_record(default_project_record(name.strip() or "新项目"))
    queue_path = project_queue_file(project["id"])
    ensure_dir(queue_path.parent)
    if migrate_legacy and DEFAULT_QUEUE_FILE.exists():
        queue_path.write_text(DEFAULT_QUEUE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    elif not queue_path.exists():
        queue_path.write_text(queue_document_to_text(default_queue_document()), encoding="utf-8")
    for kind in ["image", "video", "audio"]:
        ensure_dir(project_upload_root(project["id"]) / kind)
    return project


def get_active_project_id(ui_config: dict[str, Any] | None = None) -> str:
    return get_active_project(ui_config)["id"]


def get_active_project(ui_config: dict[str, Any] | None = None) -> dict[str, Any]:
    projects = load_projects()
    if not projects:
        raise RuntimeError("没有可用项目。")
    
    config = ui_config if ui_config is not None else load_ui_config()
    active_id = str(config.get("active_project_id") or "").strip()
    
    for project in projects:
        if project["id"] == active_id:
            return project
            
    # 没找到或没设置，选第一个
    active_id = projects[0]["id"]
    save_ui_config({"active_project_id": active_id})
    return projects[0]


def set_active_project(project_id: str) -> dict[str, Any]:
    projects = load_projects()
    for project in projects:
        if project["id"] == project_id:
            save_ui_config({"active_project_id": project_id})
            return project
    raise ValueError("项目不存在。")


def rename_project(project_id: str, name: str) -> dict[str, Any]:
    projects = load_projects()
    next_projects: list[dict[str, Any]] = []
    renamed: dict[str, Any] | None = None
    for project in projects:
        if project["id"] == project_id:
            project = dict(project)
            project["name"] = name.strip() or project["name"]
            project["folder"] = make_project_folder_name(project["name"], project["id"])
            project["updated_at"] = now_iso()
            renamed = save_project_record(project)
            next_projects.append(renamed)
        else:
            next_projects.append(project)
    if not renamed:
        raise ValueError("项目不存在。")
    save_projects_index(next_projects)
    return renamed


def successful_segment_ids(state: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for task in state.get("tasks") or []:
        status = str(task.get("status") or "").lower()
        if status != "success":
            continue
        segment_id = str(task.get("segment_id") or "").strip()
        project_id = str(task.get("project_id") or "").strip()
        if project_id and segment_id:
            ids.add(f"{project_id}:{segment_id}")
        elif segment_id:
            ids.add(segment_id)
    return ids


def successful_segment_signatures(state: dict[str, Any]) -> set[tuple[str, str, str]]:
    signatures: set[tuple[str, str, str]] = set()
    for task in state.get("tasks") or []:
        status = str(task.get("status") or "").lower()
        if status != "success":
            continue
        project_id = str(task.get("project_id") or "").strip()
        segment_id = str(task.get("segment_id") or "").strip()
        command = str(task.get("command") or "").strip()
        if segment_id and command:
            signatures.add((project_id, segment_id, command))
    return signatures


def project_task_counts(project_id: str, state: dict[str, Any]) -> dict[str, int]:
    queue_path = project_queue_file(project_id)
    try:
        segments = parse_queue_document(queue_file_text(queue_path)).get("segments", [])
    except Exception:
        segments = []
    project_tasks = [task for task in state.get("tasks") or [] if str(task.get("project_id") or "") == project_id]
    by_segment_id = {str(task.get("segment_id") or ""): task for task in project_tasks}
    success_count = 0
    failed_count = 0
    running_count = 0
    for segment in segments:
        task = by_segment_id.get(str(segment.get("id") or ""))
        status = str((task or segment).get("status") or "").lower() if isinstance((task or segment), dict) else ""
        if status == "success" or segment_is_success(project_id, segment):
            success_count += 1
        elif status in {"failed", "fail", "rejected", "banned", "error", "cancelled"}:
            failed_count += 1
        elif status == "running":
            running_count += 1
    return {
        "queued": len(segments),
        "running": running_count,
        "success": success_count,
        "failed": failed_count,
    }


def projects_for_payload(state: dict[str, Any], base_output_root: Path | None = None) -> list[dict[str, Any]]:
    return [
        {
            **project,
            "queue_file": str(project_queue_file(project["id"])),
            "upload_root": str(project_upload_root(project["id"])),
            "output_root": str(project_output_root(project["id"], base_output_root)),
            "counts": project_task_counts(project["id"], state),
        }
        for project in load_projects()
    ]


def compose_global_queue_document(state: dict[str, Any], base_output_root: Path | None = None) -> dict[str, Any]:
    completed = successful_segment_signatures(state)
    completed_ids = successful_segment_ids(state)
    global_segments: list[dict[str, Any]] = []
    for project in load_projects():
        queue_path = project_queue_file(project["id"])
        document = parse_queue_document(queue_file_text(queue_path))
        for segment in document.get("segments", []):
            segment_id = str(segment.get("id") or "").strip()
            command = str(segment.get("command") or "").strip()
            if not command:
                command = command_from_queue_segment(segment)
            if segment_is_terminal(project["id"], segment):
                continue
            if segment_id and f"{project['id']}:{segment_id}" in completed_ids:
                continue
            if segment_id and segment_id in completed_ids:
                continue
            if segment_id and (project["id"], segment_id, command) in completed:
                continue
            if segment_id and ("", segment_id, command) in completed:
                continue
            prepared = dict(segment)
            prepared["command"] = command
            prepared["project_id"] = project["id"]
            prepared["project_name"] = project["name"]
            prepared["download_dir"] = str(project_segment_output_dir(project["id"], str(segment.get("name") or ""), segment_id))
            global_segments.append(prepared)
    return {"version": 1, "segments": global_segments}


def normalize_model_version(value: Any) -> str:
    model = str(value or "").strip()
    legacy_map = {
        "seedance1.0fast": "seedance2.0fast",
        "seedance1.0": "seedance2.0",
        "seedance1.0fast_vip": "seedance2.0fast_vip",
        "seedance1.0_vip": "seedance2.0_vip",
    }
    return legacy_map.get(model, model)


def media_ref_aliases(path: str) -> set[str]:
    file_path = Path(str(path or ""))
    aliases = {file_path.stem, file_path.name}
    # Uploaded files are often prefixed with timestamp/uuid before the user renames them.
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


def build_multiframe_command(images: list[str], prompt: str, duration: str, transition_prompts: list[str] | None = None) -> list[str]:
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


def build_multimodal_command(payload: dict[str, Any]) -> str:
    images = parse_line_values(payload.get("images"))
    videos = parse_line_values(payload.get("videos"))
    audios = parse_line_values(payload.get("audios"))
    raw_prompt = str(payload.get("prompt") or "").strip()
    images, videos, audios = filter_media_by_prompt_refs(raw_prompt, images, videos, audios)

    if not images and not videos and not audios:
        raise ValueError("至少要有一个图片、视频或音频素材。")
    if not images and not videos:
        raise ValueError("全能参考至少要有图片或视频，不能只放音频。")

    media_refs = build_media_ref_map(images, videos, audios)
    prompt = normalize_prompt_text(raw_prompt, media_refs)
    transition_prompts = [normalize_prompt_text(item, media_refs) for item in parse_line_values(payload.get("transition_prompts"))]
    duration = str(payload.get("duration") or "").strip()
    ratio = str(payload.get("ratio") or "").strip()
    model_version = normalize_model_version(payload.get("model_version"))
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


def build_text2video_command(payload: dict[str, Any]) -> str:
    prompt = normalize_prompt_text(str(payload.get("prompt") or "").strip())
    if not prompt:
        raise ValueError("文生视频必须填写提示词。")

    command = ["text2video", "--prompt", prompt]
    duration = str(payload.get("duration") or "").strip()
    ratio = str(payload.get("ratio") or "").strip()
    model_version = normalize_model_version(payload.get("model_version"))
    if duration:
        command.extend(["--duration", duration])
    if ratio:
        command.extend(["--ratio", ratio])
    if model_version:
        command.extend(["--model_version", model_version])
    return shlex.join(command)


def parse_multipart_parts(handler: BaseHTTPRequestHandler) -> list[dict[str, Any]]:
    content_type = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b""
    boundary_match = re.search(r"boundary=([^;]+)", content_type)
    if not boundary_match:
        raise ValueError("上传请求缺少 boundary。")
    boundary = boundary_match.group(1).strip().strip('"').encode("utf-8")
    chunks = raw.split(b"--" + boundary)
    parts: list[dict[str, Any]] = []

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or chunk == b"--":
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        header_blob, body = chunk.split(b"\r\n\r\n", 1)
        if body.endswith(b"\r\n"):
            body = body[:-2]
        headers = {}
        for line in header_blob.decode("utf-8", errors="replace").split("\r\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        disposition = headers.get("content-disposition", "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        parts.append(
            {
                "name": name_match.group(1) if name_match else "",
                "filename": filename_match.group(1) if filename_match else None,
                "body": body,
            }
        )
    return parts


def save_uploaded_files(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    parts = parse_multipart_parts(handler)
    kind = "misc"
    project_id = ""
    for part in parts:
        if part["name"] == "kind":
            kind = part["body"].decode("utf-8", errors="replace").strip().lower() or "misc"
        if part["name"] == "project_id":
            project_id = part["body"].decode("utf-8", errors="replace").strip()
    if project_id:
        set_active_project(project_id)
        target_dir = project_upload_root(project_id) / kind
    else:
        target_dir = UPLOAD_DIR / kind
    ensure_dir(target_dir)

    file_parts = [part for part in parts if part["name"] == "files" and part.get("filename")]
    if not file_parts:
        raise ValueError("没有收到文件。")

    saved_paths: list[str] = []
    for item in file_parts:
        filename = sanitize_filename(item["filename"] or f"{kind}-{uuid.uuid4().hex}")
        timestamp = int(time.time())
        final_name = f"{timestamp}-{uuid.uuid4().hex[:8]}-{filename}"
        target = target_dir / final_name
        target.write_bytes(item["body"])
        saved_paths.append(str(target))
    return {"kind": kind, "project_id": project_id, "paths": saved_paths}


def build_upload_record(kind: str, path: Path) -> dict[str, Any]:
    return {
        "kind": kind,
        "name": path.name,
        "stem": path.stem,
        "path": str(path),
        "size": path.stat().st_size,
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_upload_path(path_value: str) -> Path:
    if not path_value:
        raise ValueError("缺少素材路径。")
    candidate = Path(unquote(path_value)).expanduser().resolve()
    allowed_roots = [UPLOAD_DIR.resolve(), PROJECTS_DIR.resolve()]
    if not any(_is_relative_to(candidate, root) for root in allowed_roots):
        raise ValueError("只能操作上传目录里的素材。")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError("素材文件不存在。")
    return candidate


def rename_uploaded_file(payload: dict[str, Any]) -> dict[str, Any]:
    source = resolve_upload_path(str(payload.get("path") or "").strip())
    new_name_raw = str(payload.get("new_name") or "").strip()
    if not new_name_raw:
        raise ValueError("请输入新的素材名称。")

    desired = Path(new_name_raw)
    safe_stem = sanitize_filename(desired.stem or new_name_raw)
    if not safe_stem:
        raise ValueError("新的素材名称无效。")

    target_name = f"{safe_stem}{source.suffix}"
    target = source.with_name(target_name)
    if target == source:
        return {"material": build_upload_record(source.parent.name, source)}
    if target.exists():
        raise ValueError(f"同目录下已存在同名文件：{target.name}")

    source.rename(target)
    return {"material": build_upload_record(target.parent.name, target)}


def parse_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    content_type = handler.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return json.loads(raw.decode("utf-8"))
    if "application/x-www-form-urlencoded" in content_type:
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}
    raise ValueError(f"Unsupported Content-Type: {content_type}")


def build_status_payload() -> dict[str, Any]:
    ensure_dir(APP_DIR)
    runner = read_runner_meta()
    ui_config = load_ui_config()
    active_project = get_active_project(ui_config)
    queue_file = project_queue_file(active_project["id"])
    output_root = Path(runner.get("output_root") or ui_config.get("output_root") or DEFAULT_OUTPUT_ROOT)
    state_file = normalize_state_file_path(runner.get("state_file") or ui_config.get("state_file"))
    state = load_json(state_file, {})
    state = clear_stale_running_tasks(state_file, state, runner)
    detected_dreamina = detect_dreamina_path()
    return {
        "runner": runner,
        "projects": projects_for_payload(state, output_root),
        "active_project": active_project,
        "queue_file": str(queue_file),
        "output_root": str(output_root),
        "video_output_root": str(project_output_root(active_project["id"])),
        "state_file": str(state_file),
        "detected_dreamina": detected_dreamina,
        "ui_config": ui_config,
        "queue_content": visible_queue_text(state, queue_file),
        "state": state,
        "log_tail": tail_text(RUNNER_LOG_FILE),
    }


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def persist_runtime_form(payload: dict[str, Any], dreamina: str | None = None) -> dict[str, Any]:
    return save_ui_config(
        {
            "dreamina": dreamina if dreamina is not None else (str(payload.get("dreamina") or "").strip() or None),
            "queue_file": str(payload.get("queue_file") or "").strip() or None,
            "output_root": str(payload.get("output_root") or "").strip() or None,
            "state_file": str(normalize_state_file_path(payload.get("state_file"))),
            "poll_interval": int(payload.get("poll_interval") or 30),
            "timeout_seconds": int(payload.get("timeout_seconds") or 10800),
            "resume": bool_value(payload.get("resume")),
            "stop_on_failure": bool_value(payload.get("stop_on_failure")),
            "active_project_id": str(payload.get("project_id") or "").strip() or None,
        }
    )


def write_active_and_global_queue(
    active_project: dict[str, Any],
    queue_content: Any,
    queue_file: Path,
    output_root: Path,
    state_file: Path,
) -> dict[str, Any]:
    active_queue_file = project_queue_file(active_project["id"]).expanduser().resolve()
    ensure_dir(active_queue_file.parent)
    ensure_dir(queue_file.parent)
    ensure_dir(output_root)
    ensure_dir(APP_DIR)
    if str(queue_content or "").strip():
        active_document = merge_existing_segment_status(active_project["id"], parse_queue_document(str(queue_content or "")))
        active_queue_file.write_text(queue_document_to_text(active_document), encoding="utf-8")
    previous_state = load_json(state_file, {})
    global_document = compose_global_queue_document(previous_state, output_root)
    if not global_document.get("segments"):
        raise ValueError("所有项目里都没有待执行任务。")
    queue_file.write_text(queue_document_to_text(global_document), encoding="utf-8")
    return global_document


def task_record_signature(task: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(task.get("project_id") or ""),
        str(task.get("segment_id") or ""),
        str(task.get("command") or ""),
    )


def task_record_identity(task: dict[str, Any]) -> tuple[str, str]:
    return (
        str(task.get("project_id") or ""),
        str(task.get("segment_id") or ""),
    )


def segment_record_signature(segment: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(segment.get("project_id") or ""),
        str(segment.get("id") or ""),
        str(segment.get("command") or ""),
    )


def segment_record_identity(segment: dict[str, Any]) -> tuple[str, str]:
    return (
        str(segment.get("project_id") or ""),
        str(segment.get("id") or ""),
    )


def build_pending_task_record(segment: dict[str, Any], index: int, output_root: Path) -> dict[str, Any]:
    command = command_from_queue_segment(segment)
    segment_id = str(segment.get("id") or f"legacy-{index}")
    segment_name = str(segment.get("name") or f"片段{index}")
    project_id = str(segment.get("project_id") or "")
    task_label = sanitize_filename(f"{segment_name}-{command[:48]}")
    download_dir = (
        project_segment_output_dir(project_id, segment_name, segment_id)
        if project_id
        else Path(str(segment.get("download_dir") or "")).expanduser()
        if segment.get("download_dir")
        else output_root / f"{index:03d}-{task_label}"
    )
    return {
        "index": index,
        "segment_id": segment_id,
        "segment_name": segment_name,
        "project_id": project_id,
        "project_name": str(segment.get("project_name") or ""),
        "command": command,
        "prompt": str(segment.get("prompt") or ""),
        "images": list(segment.get("images") or []),
        "transition_prompts": list(segment.get("transition_prompts") or []),
        "videos": list(segment.get("videos") or []),
        "audios": list(segment.get("audios") or []),
        "duration": str(segment.get("duration") or ""),
        "ratio": str(segment.get("ratio") or ""),
        "model_version": str(segment.get("model_version") or ""),
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


def command_from_queue_segment(segment: dict[str, Any]) -> str:
    command = str(segment.get("command") or "").strip()
    if command:
        return command

    images = list(segment.get("images") or [])
    videos = list(segment.get("videos") or [])
    audios = list(segment.get("audios") or [])
    mode = str(segment.get("mode") or segment.get("type") or "").strip()
    payload = {
        "prompt": str(segment.get("prompt") or ""),
        "images": images,
        "videos": videos,
        "audios": audios,
        "transition_prompts": list(segment.get("transition_prompts") or []),
        "duration": str(segment.get("duration") or ""),
        "ratio": str(segment.get("ratio") or ""),
        "model_version": str(segment.get("model_version") or ""),
    }
    if mode == "text2video" or not (images or videos or audios):
        return build_text2video_command(payload)
    return build_multimodal_command(payload)


def task_index_value(task: dict[str, Any]) -> int:
    try:
        return int(task.get("index") or 0)
    except (TypeError, ValueError):
        return 0


def append_pending_tasks_to_state(global_document: dict[str, Any], state_file: Path, output_root: Path) -> int:
    state = load_json(state_file, {})
    tasks = state.setdefault("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
        state["tasks"] = tasks
    existing = {task_record_signature(task) for task in tasks}
    existing_ids = {
        task_record_identity(task) for task in tasks
        if task_record_identity(task)[1]
    }
    new_segments = [
        segment for segment in global_document.get("segments") or []
        if segment_record_signature(segment) not in existing
        and segment_record_identity(segment) not in existing_ids
    ]
    if not new_segments:
        return 0

    next_index = max([task_index_value(task) for task in tasks] or [0]) + 1
    for offset, segment in enumerate(new_segments):
        tasks.append(build_pending_task_record(segment, next_index + offset, output_root))
    state.setdefault("created_at", now_iso())
    state.setdefault("queue_file", str(GLOBAL_QUEUE_FILE.resolve()))
    state.setdefault("output_root", str(output_root))
    save_queue_state(state_file, state)
    return len(new_segments)


def rebuild_global_queue_from_state(state_file: Path, output_root: Path, queue_file: Path = GLOBAL_QUEUE_FILE) -> dict[str, Any]:
    state = load_json(state_file, {})
    global_document = compose_global_queue_document(state, output_root)
    ensure_dir(queue_file.parent)
    queue_file.write_text(queue_document_to_text(global_document), encoding="utf-8")
    return global_document


def retry_task(payload: dict[str, Any]) -> dict[str, Any]:
    ui_config = load_ui_config()
    runner = read_runner_meta()
    output_root = Path(runner.get("output_root") or ui_config.get("output_root") or DEFAULT_OUTPUT_ROOT).expanduser().resolve()
    state_file = normalize_state_file_path(runner.get("state_file") or ui_config.get("state_file"))
    queue_file = Path(runner.get("queue_file") or GLOBAL_QUEUE_FILE).expanduser().resolve()
    project_id = str(payload.get("project_id") or "").strip()
    segment_id = str(payload.get("segment_id") or "").strip()
    if not project_id or not segment_id:
        raise ValueError("缺少 project_id 或 segment_id，无法重试。")

    state = load_json(state_file, {})
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("state 文件里没有任务列表。")

    target: dict[str, Any] | None = None
    for task in tasks:
        if str(task.get("project_id") or "") == project_id and str(task.get("segment_id") or "") == segment_id:
            target = task
            break
    if not target:
        raise ValueError("没有找到要重试的任务。")

    if str(target.get("status") or "") == "success":
        raise ValueError("任务已经成功，不需要重试。")
    if str(target.get("status") or "") == "running":
        raise ValueError("任务正在运行，不能重试。")

    target["status"] = "pending"
    target["submit_id"] = None
    target["gen_status"] = None
    target["fail_reason"] = None
    target["finished_at"] = None
    target["submit_stdout"] = None
    target["submit_stderr"] = None
    target["final_stdout"] = None
    target["final_stderr"] = None
    target["urls"] = []
    target["download_dir"] = str(project_segment_output_dir(project_id, str(target.get("segment_name") or ""), segment_id))
    target["manual_retry_requested_at"] = now_iso()
    target["retry_count"] = int(target.get("retry_count") or 0) + 1
    if not str(target.get("command") or "").strip():
        target["command"] = command_from_queue_segment({
            "command": target.get("command"),
            "prompt": target.get("prompt"),
            "images": target.get("images") or [],
            "videos": target.get("videos") or [],
            "audios": target.get("audios") or [],
            "transition_prompts": target.get("transition_prompts") or [],
            "duration": target.get("duration"),
            "ratio": target.get("ratio"),
            "model_version": target.get("model_version"),
        })

    pending = [
        task for task in tasks
        if task is not target
        and str(task.get("status") or "") not in {"success", "failed", "fail", "rejected", "banned", "error", "cancelled"}
    ]
    completed = [task for task in tasks if task is not target and task not in pending]
    next_tasks = pending + [target] + completed
    for index, task in enumerate(next_tasks, start=1):
        task["index"] = index
    state["tasks"] = next_tasks
    save_queue_state(state_file, state)
    global_document = rebuild_global_queue_from_state(state_file, output_root, queue_file)
    return {"task": target, "queued_count": len(global_document.get("segments") or [])}


def start_queue(payload: dict[str, Any]) -> dict[str, Any]:
    with LOCK:
        current = read_runner_meta()
        ui_config = load_ui_config()
        project_id = str(payload.get("project_id") or ui_config.get("active_project_id") or "").strip()
        active_project = set_active_project(project_id) if project_id else get_active_project(ui_config)
        output_root = Path(payload.get("output_root") or ui_config.get("output_root") or DEFAULT_OUTPUT_ROOT).expanduser().resolve()
        state_file = normalize_state_file_path(payload.get("state_file") or ui_config.get("state_file"))
        requested_dreamina = str(payload.get("dreamina") or ui_config.get("dreamina") or "").strip()
        dreamina = requested_dreamina or detect_dreamina_path() or "dreamina"
        queue_content = payload.get("queue_content", "")
        poll_interval = int(payload.get("poll_interval") or ui_config.get("poll_interval") or 30)
        timeout_seconds = int(payload.get("timeout_seconds") or ui_config.get("timeout_seconds") or 10800)
        resume = bool_value(payload.get("resume") if payload.get("resume") is not None else ui_config.get("resume"))
        stop_on_failure = bool_value(payload.get("stop_on_failure") if payload.get("stop_on_failure") is not None else ui_config.get("stop_on_failure"))

        if current.get("running"):
            running_queue_file = Path(current.get("queue_file") or GLOBAL_QUEUE_FILE).expanduser().resolve()
            running_output_root = Path(current.get("output_root") or output_root).expanduser().resolve()
            running_state_file = normalize_state_file_path(current.get("state_file") or state_file)
            global_document = write_active_and_global_queue(
                active_project,
                queue_content,
                running_queue_file,
                running_output_root,
                running_state_file,
            )
            added_count = append_pending_tasks_to_state(global_document, running_state_file, running_output_root)
            current["queued_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            current["queued_count"] = len(global_document.get("segments") or [])
            current["queued_added_count"] = added_count
            current["queued_while_running"] = True
            current["active_project_id"] = active_project["id"]
            current["active_project_name"] = active_project["name"]
            save_json(RUNNER_META_FILE, current)
            return current

        queue_file = GLOBAL_QUEUE_FILE.expanduser().resolve()

        # 校验 dreamina 路径
        import shutil
        if not shutil.which(dreamina) and not Path(dreamina).is_file():
            raise ValueError(f"dreamina 命令不存在: {dreamina}\n请在「队列配置」中填写正确的可执行文件路径")

        write_active_and_global_queue(active_project, queue_content, queue_file, output_root, state_file)

        if dreamina == "dreamina":
            resolved = shutil.which("dreamina")
        else:
            resolved = shutil.which(dreamina) or (dreamina if Path(dreamina).exists() else None)
        if not resolved:
            detected = detect_dreamina_path()
            if detected:
                dreamina = detected
            else:
                raise RuntimeError(
                    "dreamina 命令不存在。请先安装即梦 CLI，或在“队列配置”里填写正确的 dreamina 可执行文件路径。"
                )
        persist_runtime_form(
            {
                "queue_file": str(queue_file),
                "output_root": str(output_root),
                "state_file": str(state_file),
                "poll_interval": poll_interval,
                "timeout_seconds": timeout_seconds,
                "resume": resume,
                "stop_on_failure": stop_on_failure,
                "project_id": active_project["id"],
            },
            dreamina=dreamina,
        )

        command = [
            sys.executable,
            str(ROOT / "dreamina_queue.py"),
            "--dreamina",
            dreamina,
            "--queue-file",
            str(queue_file),
            "--output-root",
            str(output_root),
            "--state-file",
            str(state_file),
            "--poll-interval",
            str(poll_interval),
            "--timeout-seconds",
            str(timeout_seconds),
        ]
        if resume:
            command.append("--resume")
        if stop_on_failure:
            command.append("--stop-on-failure")

        with RUNNER_LOG_FILE.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )

        meta = {
            "pid": process.pid,
            "running": True,
            "started_at": None,
            "queue_file": str(queue_file),
            "output_root": str(output_root),
            "state_file": str(state_file),
            "dreamina": dreamina,
            "active_project_id": active_project["id"],
            "active_project_name": active_project["name"],
            "command": command,
            "log_file": str(RUNNER_LOG_FILE),
            "queued_while_running": False,
        }
        save_json(RUNNER_META_FILE, meta)
        return meta


def stop_queue() -> dict[str, Any]:
    with LOCK:
        meta = read_runner_meta()
        pid = meta.get("pid")
        if not isinstance(pid, int) or pid <= 0 or not meta.get("running"):
            raise RuntimeError("当前没有正在运行的队列。")

        os.killpg(pid, signal.SIGTERM)
        meta["running"] = False
        save_json(RUNNER_META_FILE, meta)
        return meta


def clear_execution_queue() -> dict[str, Any]:
    with LOCK:
        meta = read_runner_meta()
        pid = meta.get("pid")
        stopped_runner = False
        if isinstance(pid, int) and pid > 0 and meta.get("running"):
            try:
                os.killpg(pid, signal.SIGTERM)
                stopped_runner = True
            except ProcessLookupError:
                stopped_runner = False
            meta["running"] = False
            meta["finished_at"] = now_iso()
            meta["cleared_at"] = now_iso()
            save_json(RUNNER_META_FILE, meta)

        ui_config = load_ui_config()
        output_root = Path(meta.get("output_root") or ui_config.get("output_root") or DEFAULT_OUTPUT_ROOT).expanduser().resolve()
        state_file = normalize_state_file_path(meta.get("state_file") or ui_config.get("state_file"))
        queue_file = Path(meta.get("queue_file") or GLOBAL_QUEUE_FILE).expanduser().resolve()

        empty_queue = {"version": 1, "segments": []}
        ensure_dir(queue_file.parent)
        queue_file.write_text(json.dumps(empty_queue, ensure_ascii=False, indent=2), encoding="utf-8")

        empty_state = {
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "dreamina": meta.get("dreamina") or ui_config.get("dreamina") or "",
            "queue_file": str(queue_file),
            "output_root": str(output_root),
            "state_file": str(state_file),
            "poll_interval_seconds": int(ui_config.get("poll_interval") or 30),
            "timeout_seconds": int(ui_config.get("timeout_seconds") or 10800),
            "stop_on_failure": bool(ui_config.get("stop_on_failure")),
            "tasks": [],
        }
        ensure_dir(state_file.parent)
        state_file.write_text(json.dumps(empty_state, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "cleared": True,
            "stopped_runner": stopped_runner,
            "queue_file": str(queue_file),
            "state_file": str(state_file),
            "runner": meta,
        }


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dreamina Queue UI</title>
  <style>
    :root {
      --bg: #f5f7f6;
      --panel: #ffffff;
      --ink: #1e1d1a;
      --muted: #5f6b68;
      --line: #d8e1de;
      --accent: #176b5b;
      --accent-2: #315f8c;
      --danger: #a3392b;
      --ok: #1f7a45;
      --shadow: 0 16px 42px rgba(23, 36, 34, 0.08);
      --radius: 12px;
      --mono: "SFMono-Regular", "Menlo", monospace;
      --sans: "PingFang SC", "Helvetica Neue", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--sans);
      background:
        linear-gradient(180deg, #fbfcfb 0%, var(--bg) 100%);
      color: var(--ink);
    }
    .shell {
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px;
    }
    .hero {
      display: flex;
      gap: 20px;
      justify-content: space-between;
      align-items: end;
      margin-bottom: 22px;
    }
    .hero h1 {
      margin: 0 0 8px;
      font-size: 34px;
      letter-spacing: -0.03em;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
      max-width: 720px;
      line-height: 1.6;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      background: rgba(31,107,94,0.08);
      border: 1px solid rgba(31,107,94,0.14);
      border-radius: 999px;
      color: var(--accent);
      font-weight: 600;
    }
    .page-nav {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 0 0 18px;
    }
    .page-nav a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 10px 16px;
      border-radius: 999px;
      color: var(--accent);
      background: rgba(31,107,94,0.08);
      text-decoration: none;
      font-weight: 700;
      border: 1px solid transparent;
    }
    body[data-page="reference"] .nav-reference,
    body[data-page="text2video"] .nav-text2video {
      color: #fff;
      background: var(--accent);
      border-color: rgba(23,107,91,0.22);
    }
    body[data-page="reference"] .text-page,
    body[data-page="text2video"] .reference-page,
    body[data-page="text2video"] .materials-panel {
      display: none;
    }
    body[data-page="text2video"] .grid {
      grid-template-columns: 1fr;
    }
    .app-steps {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin: 0 0 20px;
    }
    .project-bar {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 14px;
      align-items: end;
      padding: 16px;
      margin: 0 0 18px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #fff;
      box-shadow: 0 10px 24px rgba(23, 36, 34, 0.05);
    }
    .project-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .project-meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .step-card {
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(255, 255, 255, 0.78);
      box-shadow: 0 10px 24px rgba(23, 36, 34, 0.05);
    }
    .step-card strong {
      display: grid;
      place-items: center;
      flex: 0 0 28px;
      width: 28px;
      height: 28px;
      border-radius: 999px;
      background: var(--accent);
      color: #fff;
      font-size: 13px;
    }
    .step-card span {
      display: block;
      color: var(--ink);
      font-weight: 700;
      margin-bottom: 3px;
    }
    .step-card p {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .grid {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 20px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid rgba(140, 123, 94, 0.18);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel-head {
      padding: 18px 20px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .panel-head h2 {
      margin: 0;
      font-size: 16px;
    }
    .panel-body {
      padding: 18px 20px 20px;
    }
    .fields {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 14px;
    }
    label {
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 8px;
      font-weight: 600;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      background: #fff;
      color: var(--ink);
      outline: none;
    }
    input:focus, textarea:focus, select:focus {
      border-color: rgba(31,107,94,0.55);
      box-shadow: 0 0 0 4px rgba(31,107,94,0.08);
    }
    textarea {
      min-height: 320px;
      resize: vertical;
      font-family: var(--mono);
      font-size: 13px;
      line-height: 1.55;
    }
    .row {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: center;
    }
    .check {
      display: inline-flex;
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
    }
    .check input {
      width: auto;
      padding: 0;
      margin: 0;
      box-shadow: none;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    .primary { background: var(--accent); color: #fff; }
    .warm { background: var(--accent-2); color: #fff; }
    .ghost { background: rgba(31,107,94,0.08); color: var(--accent); }
    .danger { background: rgba(163,57,43,0.1); color: var(--danger); }
    .stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: #fff;
    }
    .stat strong {
      display: block;
      font-size: 26px;
      margin-top: 6px;
    }
    .status-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 16px;
      padding: 14px;
      border-radius: 14px;
      background: #fff;
      border: 1px solid var(--line);
    }
    .pill {
      display: inline-flex;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .pill.success { background: rgba(31,122,69,0.12); color: var(--ok); }
    .pill.running { background: rgba(216,148,46,0.12); color: #b47814; }
    .pill.stopped { background: rgba(109,101,88,0.12); color: var(--muted); }
    .pill.failed { background: rgba(163,57,43,0.12); color: var(--danger); }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 10px 8px;
      text-align: left;
      border-bottom: 1px solid rgba(216,207,191,0.7);
      vertical-align: top;
    }
    th { color: var(--muted); font-weight: 700; }
    td code {
      font-family: var(--mono);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .table-section {
      margin-bottom: 16px;
    }
    .table-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }
    .table-head label {
      margin: 0;
    }
    .table-scroll {
      max-height: 360px;
      overflow: auto;
      background: #fff;
      border: 1px solid rgba(216,207,191,0.7);
      border-radius: 14px;
    }
    .table-scroll.completed {
      max-height: 280px;
    }
    .table-section:fullscreen {
      background: var(--bg);
      padding: 24px;
      overflow: hidden;
    }
    .table-section:fullscreen .table-scroll {
      max-height: calc(100vh - 96px);
      height: calc(100vh - 96px);
    }
    .fullscreen-table-btn {
      padding: 8px 12px;
      font-size: 12px;
      white-space: nowrap;
    }
    pre {
      margin: 0;
      padding: 14px;
      border-radius: 14px;
      background: #1f2421;
      color: #d9f3ee;
      font-size: 12px;
      line-height: 1.55;
      font-family: var(--mono);
      min-height: 260px;
      overflow: auto;
    }
    #logTail {
      min-height: 180px;
      max-height: 420px;
      overflow: auto;
    }
    .hint {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    .footer {
      margin-top: 20px;
      color: var(--muted);
      font-size: 12px;
    }
    .subcard {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 16px;
      background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(248,244,236,0.92));
    }
    .subcard.featured {
      border-color: rgba(23,107,91,0.26);
      background:
        radial-gradient(circle at top right, rgba(49,95,140,0.11), transparent 34%),
        linear-gradient(180deg, #ffffff, #f5faf8);
    }
    .subcard h3 {
      margin: 0 0 8px;
      font-size: 15px;
    }
    .subgrid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .subgrid.three {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .mini-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
      margin-bottom: 10px;
    }
    .upload-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 8px;
    }
    .upload-row input[type="file"] {
      padding: 8px;
      background: #fff;
    }
    .paste-zone {
      margin-top: 8px;
      border: 1px dashed rgba(31,107,94,0.45);
      border-radius: 14px;
      background: rgba(31,107,94,0.04);
      padding: 14px;
      color: var(--muted);
    }
    .paste-zone.active {
      border-color: var(--accent-2);
      background: rgba(215,109,63,0.08);
      color: var(--ink);
    }
    .refs-box {
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      background: #fff;
    }
    .ref-list {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .ref-chip {
      border: 0;
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(31,107,94,0.08);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }
    .ref-chip.video {
      background: rgba(215,109,63,0.10);
      color: var(--accent-2);
    }
    .ref-chip.audio {
      background: rgba(109,101,88,0.12);
      color: #5f564a;
    }
    .preview-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .preview-card {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      overflow: hidden;
      cursor: pointer;
    }
    .preview-card img {
      width: 100%;
      height: 110px;
      object-fit: cover;
      display: block;
      background: #f4f1ea;
    }
    .preview-meta {
      padding: 8px;
      font-size: 12px;
      line-height: 1.4;
    }
    .material-actions {
      display: flex;
      gap: 8px;
      padding: 0 8px 8px;
    }
    .material-actions button {
      flex: 1;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 12px;
    }
    .autocomplete {
      position: absolute;
      z-index: 50;
      min-width: 240px;
      max-width: 380px;
      max-height: 320px;
      overflow: auto;
      background: #fffdf8;
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: var(--shadow);
      padding: 6px;
      display: none;
    }
    .autocomplete.show {
      display: block;
    }
    .autocomplete-item {
      width: 100%;
      border: 0;
      background: transparent;
      border-radius: 10px;
      padding: 8px 10px;
      color: var(--ink);
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .autocomplete-item:hover {
      background: rgba(31,107,94,0.08);
    }
    .autocomplete-thumb {
      width: 44px;
      height: 44px;
      border-radius: 10px;
      flex: 0 0 44px;
      overflow: hidden;
      background: #f4f1ea;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--muted);
      font-size: 18px;
    }
    .autocomplete-thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .autocomplete-copy {
      min-width: 0;
      text-align: left;
    }
    .autocomplete-copy strong,
    .autocomplete-copy span {
      display: block;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .autocomplete-copy span {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }
    .modal {
      position: fixed;
      inset: 0;
      background: rgba(26, 24, 20, 0.45);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      z-index: 100;
    }
    .modal.show {
      display: flex;
    }
    .modal-card {
      width: min(760px, 100%);
      max-height: calc(100vh - 48px);
      overflow: auto;
      background: #fffdf8;
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }
    .modal-head,
    .modal-body,
    .modal-actions {
      padding: 18px 20px;
    }
    .modal-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--line);
    }
    .modal-body {
      display: grid;
      gap: 14px;
    }
    .modal-preview {
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: #f4f1ea;
      min-height: 240px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .modal-preview img {
      max-width: 100%;
      max-height: 60vh;
      display: block;
    }
    .modal-preview.empty {
      color: var(--muted);
      font-size: 14px;
      padding: 24px;
      text-align: center;
    }
    .modal-actions {
      border-top: 1px solid var(--line);
      display: flex;
      gap: 10px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .queue-list {
      display: grid;
      gap: 12px;
      margin-bottom: 14px;
    }
    .queue-item {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
      overflow: hidden;
    }
    .queue-item-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(31,107,94,0.05);
    }
    .queue-item-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .queue-item-actions button {
      padding: 6px 10px;
      font-size: 12px;
      border-radius: 10px;
    }
    .queue-media-strip {
      display: grid;
      gap: 10px;
      padding: 12px 12px 0;
    }
    .queue-image-strip {
      display: flex;
      gap: 10px;
      overflow: auto;
      padding-bottom: 2px;
    }
    .queue-image-thumb {
      width: 88px;
      min-width: 88px;
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
      background: #fff;
    }
    .queue-image-thumb img {
      width: 100%;
      height: 72px;
      object-fit: cover;
      display: block;
      background: #f4f1ea;
    }
    .queue-image-thumb span {
      display: block;
      padding: 6px 8px;
      font-size: 11px;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .queue-media-tags {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .queue-media-tags span {
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      background: rgba(31,107,94,0.08);
      color: var(--accent);
    }
    .queue-media-tags span.video {
      background: rgba(215,109,63,0.10);
      color: var(--accent-2);
    }
    .queue-media-tags span.audio {
      background: rgba(109,101,88,0.12);
      color: #5f564a;
    }
    .queue-item-input {
      width: 100%;
      min-height: 120px;
      border: 0;
      border-radius: 0;
      box-shadow: none;
      resize: vertical;
      background: transparent;
      font-size: 14px;
      line-height: 1.6;
    }
    .queue-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .queue-raw {
      margin-top: 10px;
    }
    .queue-raw summary {
      cursor: pointer;
      color: var(--accent);
      font-weight: 700;
      margin-bottom: 10px;
    }
    @media (max-width: 1080px) {
      .grid, .app-steps, .project-bar { grid-template-columns: 1fr; }
      .project-actions { justify-content: flex-start; }
    }
    @media (max-width: 720px) {
      .fields, .stats, .subgrid, .subgrid.three { grid-template-columns: 1fr; }
      .shell { padding: 16px; }
      .hero h1 { font-size: 28px; }
    }
  </style>
</head>
<body data-page="reference">
  <div class="shell">
    <div class="hero">
      <div>
        <h1>即梦视频队列</h1>
        <p>填写视频任务，按顺序自动生成。</p>
      </div>
      <div class="badge" id="runnerBadge">读取中</div>
    </div>

    <nav class="page-nav" aria-label="页面切换">
      <a class="nav-reference" href="/">全能参考</a>
      <a class="nav-text2video" href="/text2video">文生视频</a>
    </nav>

    <section class="project-bar" aria-label="项目管理">
      <div>
        <label for="projectSelect">当前项目</label>
        <select id="projectSelect"></select>
        <div class="project-meta" id="projectMeta"></div>
      </div>
      <div class="project-actions">
        <button class="ghost" id="newProjectBtn" type="button">新建项目</button>
        <button class="ghost" id="renameProjectBtn" type="button">重命名</button>
      </div>
    </section>

    <div class="app-steps">
      <div class="step-card">
        <strong>1</strong>
        <div>
          <span>选择项目</span>
          <p>每个项目有独立的素材、任务和输出目录。</p>
        </div>
      </div>
      <div class="step-card">
        <strong>2</strong>
        <div>
          <span>添加任务</span>
          <p>纯文字用“文生视频”，带素材用“全能参考”。</p>
        </div>
      </div>
      <div class="step-card">
        <strong>3</strong>
        <div>
          <span>全局串行执行</span>
          <p>所有项目的待执行任务会合并到一个队列里依次生成。</p>
        </div>
      </div>
    </div>

    <div class="grid">
      <section class="panel">
        <div class="panel-head">
          <h2>队列配置</h2>
            <div class="row">
            <button class="ghost" id="detectBtn">自动检测 dreamina</button>
            <button class="ghost" id="saveBtn">保存队列</button>
            <button class="primary" id="startBtn">启动队列</button>
            <button class="danger" id="stopBtn">停止队列</button>
            <button class="danger" id="clearExecutionQueueBtn">清空执行队列</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="text-page subcard featured">
            <h3>文生视频快速添加</h3>
            <p class="hint" style="margin-top:0;">不需要上传素材，只填提示词、时长、比例和模型，然后加入队列。</p>
            <div style="margin-bottom:12px;">
              <label for="tvSegmentName">视频段名称</label>
              <input id="tvSegmentName" placeholder="比如：片段1-地铁开场">
            </div>

            <label for="tvPrompt">提示词</label>
            <textarea id="tvPrompt" style="min-height:130px;" spellcheck="false" placeholder="比如：手机竖屏9:16，真实地铁车厢偷拍视频风格，女孩抬头看向镜头，轻微手持晃动，无字幕。"></textarea>

            <div class="subgrid three" style="margin-top:12px;">
              <div>
                <label for="tvDuration">时长</label>
                <input id="tvDuration" type="number" min="4" max="15" value="5">
              </div>
              <div>
                <label for="tvRatio">比例</label>
                <input id="tvRatio" value="9:16">
              </div>
              <div>
                <label for="tvModel">模型</label>
                <select id="tvModel">
                  <option value="seedance2.0fast" selected>seedance2.0fast</option>
                  <option value="seedance2.0">seedance2.0</option>
                  <option value="seedance2.0fast_vip">seedance2.0fast_vip</option>
                  <option value="seedance2.0_vip">seedance2.0_vip</option>
                </select>
              </div>
            </div>

            <div class="mini-actions">
              <button class="warm" id="addTextVideoBtn">加入队列</button>
              <button class="ghost" id="clearTextVideoBtn">清空这张表单</button>
            </div>

            <label for="tvPreview">将要加入队列的命令</label>
            <textarea id="tvPreview" style="min-height:96px;" readonly spellcheck="false"></textarea>
          </div>

          <div class="reference-page subcard">
            <h3>全能参考快速添加</h3>
            <p class="hint" style="margin-top:0;">你不用自己拼命令。这里固定使用即梦 CLI 的 `multimodal2video`，也就是“全能参考 / 参考生视频”。在提示词任意位置输入 `@` 会出现已上传素材，选中后会自动把素材路径加入对应输入框。</p>

	            <label for="mmPrompt">提示词</label>
	            <div style="margin-bottom:12px;">
	              <label for="mmSegmentName">视频段名称</label>
	              <input id="mmSegmentName" placeholder="比如：片段1-开场进入珠宝店">
	            </div>
	            <div style="position:relative;">
	              <textarea id="mmPrompt" style="min-height:140px;" spellcheck="false" placeholder="比如：手机竖屏9:16，真实纪录片风格，女孩回头看向镜头，轻微手持晃动..."></textarea>
	              <div id="atAutocomplete" class="autocomplete"></div>
	            </div>

            <div class="subgrid" style="margin-top:12px;">
              <div>
                <label for="mmDuration">时长</label>
                <input id="mmDuration" type="number" min="4" max="15" value="5">
              </div>
              <div>
                <label for="mmRatio">比例</label>
                <input id="mmRatio" value="9:16">
              </div>
              <div>
                <label for="mmModel">模型</label>
                <select id="mmModel">
                  <option value="seedance2.0fast" selected>seedance2.0fast</option>
                  <option value="seedance2.0">seedance2.0</option>
                  <option value="seedance2.0fast_vip">seedance2.0fast_vip</option>
                  <option value="seedance2.0_vip">seedance2.0_vip</option>
                </select>
              </div>
            </div>

	            <div style="margin-top:12px;">
	              <label for="mmImages">图片素材路径</label>
	              <textarea id="mmImages" style="min-height:90px;" spellcheck="false" placeholder="一行一个图片路径"></textarea>
                <p class="hint" style="margin-top:6px;">这些图片会作为全能参考素材通过 `--image` 传给即梦。不是只写进提示词里。</p>
	              <div class="upload-row">
	                <input id="uploadImages" type="file" multiple accept="image/*">
	                <button class="ghost" id="uploadImagesBtn">上传图片并填入</button>
	              </div>
	              <div class="paste-zone" id="pasteImageZone" tabindex="0">
                把焦点点到这里，然后直接粘贴截图或复制的图片。
                Mac 用 `Command + V`，Windows 用 `Ctrl + V`。
              </div>
	            </div>

            <div style="margin-top:12px;">
              <label for="mmTransitions">多图过渡提示词</label>
              <textarea id="mmTransitions" style="min-height:90px;" spellcheck="false" placeholder="只有多图时才用。一行描述一个过渡：第1张到第2张、第2张到第3张……"></textarea>
              <p class="hint" style="margin-top:6px;">2 张图时可以直接写上面的“提示词”；3 张及以上图片时，这里一行对应一个过渡段。</p>
            </div>

	            <div style="margin-top:12px;">
	              <label for="mmVideos">视频素材路径</label>
              <textarea id="mmVideos" style="min-height:90px;" spellcheck="false" placeholder="一行一个视频路径"></textarea>
              <div class="upload-row">
                <input id="uploadVideos" type="file" multiple accept="video/*">
                <button class="ghost" id="uploadVideosBtn">上传视频并填入</button>
              </div>
            </div>

            <div style="margin-top:12px;">
              <label for="mmAudios">音频素材路径</label>
              <textarea id="mmAudios" style="min-height:90px;" spellcheck="false" placeholder="一行一个音频路径"></textarea>
              <div class="upload-row">
                <input id="uploadAudios" type="file" multiple accept="audio/*">
                <button class="ghost" id="uploadAudiosBtn">上传音频并填入</button>
              </div>
            </div>

            <div class="mini-actions">
              <button class="warm" id="addMultimodalBtn">加入队列</button>
              <button class="ghost" id="clearMultimodalBtn">清空这张表单</button>
            </div>

            <div class="refs-box">
              <label>素材引用</label>
              <p class="hint" style="margin-top:0;">上传或粘贴后会自动生成引用名。你可以直接点下面按钮插入，也可以在提示词里输入 `@` 触发联想。</p>
              <div class="ref-list" id="refList"></div>
              <div class="preview-grid" id="imagePreviewGrid"></div>
            </div>

            <label for="mmPreview">将要加入队列的命令</label>
            <textarea id="mmPreview" style="min-height:110px;" readonly spellcheck="false"></textarea>
          </div>

          <div class="fields">
            <div>
              <label for="dreamina">dreamina 路径</label>
              <input id="dreamina" value="dreamina">
            </div>
            <div>
              <label for="queueFile">队列文件</label>
              <input id="queueFile">
            </div>
            <div>
              <label for="outputRoot">输出目录</label>
              <input id="outputRoot">
            </div>
            <div>
              <label for="stateFile">状态文件</label>
              <input id="stateFile">
            </div>
            <div>
              <label for="pollInterval">轮询间隔（秒）</label>
              <input id="pollInterval" type="number" min="0" value="30">
            </div>
            <div>
              <label for="timeoutSeconds">单任务超时（秒）</label>
              <input id="timeoutSeconds" type="number" min="1" value="10800">
            </div>
          </div>

          <div class="row" style="margin-bottom:14px;">
            <label class="check"><input id="resume" type="checkbox"> 断点续跑</label>
            <label class="check"><input id="stopOnFailure" type="checkbox"> 某条失败后立即停止</label>
            <button class="warm" id="refreshBtn">刷新状态</button>
          </div>

          <label for="queueContent">队列内容</label>
          <div class="queue-toolbar">
            <span class="hint">下面按列表展示每一条命令，可直接逐条编辑。</span>
            <button class="ghost" id="addQueueItemBtn" type="button">新增一条</button>
          </div>
          <div id="queueList" class="queue-list"></div>
          <details class="queue-raw">
            <summary>查看原始文本</summary>
            <textarea id="queueContent" spellcheck="false"></textarea>
          </details>
          <p class="hint">队列文件按 JSON 保存。每个 `segment` 就是一段视频，包含名称、提示词和素材/参数。</p>
        </div>
      </section>

      <section class="panel materials-panel">
        <div class="panel-head">
          <h2>已上传素材</h2>
        </div>
        <div class="panel-body">
          <p class="hint">点击引用名可插入到提示词里作为本地备注，提交前会自动转成普通文字，不是即梦 CLI 的官方绑定语法。</p>
          <div id="materialTabs" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
            <button class="ghost" id="tabAll" onclick="showMaterialTab('all')">全部</button>
            <button class="ghost" id="tabImage" onclick="showMaterialTab('image')">图片</button>
            <button class="ghost" id="tabVideo" onclick="showMaterialTab('video')">视频</button>
            <button class="ghost" id="tabAudio" onclick="showMaterialTab('audio')">音频</button>
          </div>
          <div id="materialGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;"></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>运行面板</h2>
          <span class="hint" id="updatedAt">尚未刷新</span>
        </div>
        <div class="panel-body">
          <div class="stats">
            <div class="stat"><span>总任务</span><strong id="totalCount">0</strong></div>
            <div class="stat"><span>成功</span><strong id="successCount">0</strong></div>
            <div class="stat"><span>失败</span><strong id="failCount">0</strong></div>
          </div>

          <div class="status-line">
            <div>
              <div>运行状态</div>
              <div id="runnerState" style="margin-top:6px;"></div>
            </div>
            <div>
              <div>PID</div>
              <div id="runnerPid" style="margin-top:6px;font-family:var(--mono);"></div>
            </div>
            <div>
              <div>输出目录</div>
              <div id="runnerOutput" style="margin-top:6px;font-family:var(--mono);word-break:break-all;"></div>
            </div>
          </div>

          <div class="table-section" id="pendingTableSection">
            <div class="table-head">
              <label>待执行 / 执行中</label>
              <button class="ghost fullscreen-table-btn" type="button" data-fullscreen-target="pendingTableSection">全屏</button>
            </div>
            <div class="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>项目</th>
                    <th>片段名</th>
                    <th>状态</th>
                    <th>submit_id</th>
                    <th>命令</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody id="taskTable"></tbody>
              </table>
            </div>
          </div>

          <div class="table-section" id="completedTableSection">
            <div class="table-head">
              <label>已完成</label>
              <button class="ghost fullscreen-table-btn" type="button" data-fullscreen-target="completedTableSection">全屏</button>
            </div>
            <div class="table-scroll completed">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>项目</th>
                    <th>片段名</th>
                    <th>状态</th>
                    <th>submit_id</th>
                    <th>命令</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody id="completedTaskTable"></tbody>
              </table>
            </div>
          </div>

          <div>
            <label>最近日志</label>
            <pre id="logTail"></pre>
          </div>
        </div>
      </section>
    </div>

    <div class="footer">建议先用 2 条命令试跑，确认本机 `dreamina` 登录态正常，再跑完整队列。</div>
  </div>

  <div id="materialModal" class="modal" aria-hidden="true">
    <div class="modal-card">
      <div class="modal-head">
        <div>
          <strong id="materialModalTitle">素材预览</strong>
          <div class="hint" id="materialModalToken" style="margin-top:4px;"></div>
        </div>
        <button class="ghost" id="materialModalCloseBtn">关闭</button>
      </div>
      <div class="modal-body">
        <div id="materialModalPreview" class="modal-preview empty">这里会显示素材预览。</div>
        <div>
          <label for="materialRenameInput">素材名称</label>
          <input id="materialRenameInput" placeholder="比如：角色正面定妆">
          <p class="hint" id="materialRenameHint" style="margin:8px 0 0;"></p>
        </div>
        <div>
          <label>本地路径</label>
          <div id="materialModalPath" class="hint" style="word-break:break-all;"></div>
        </div>
      </div>
      <div class="modal-actions">
        <button class="ghost" id="materialInsertBtn">插入到提示词</button>
        <button class="warm" id="materialRenameBtn">保存新名称</button>
      </div>
    </div>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    let activeProjectId = "";
    let allProjects = [];

    function setupPageMode() {
      const page = window.location.pathname === "/text2video" ? "text2video" : "reference";
      document.body.dataset.page = page;
      document.title = page === "text2video" ? "文生视频 - 即梦视频队列" : "全能参考 - 即梦视频队列";
      const title = document.querySelector(".hero h1");
      const subtitle = document.querySelector(".hero p");
      if (title && subtitle) {
        if (page === "text2video") {
          title.textContent = "文生视频队列";
          subtitle.textContent = "只填文字提示词，加入队列后按顺序自动生成。";
        } else {
          title.textContent = "全能参考队列";
          subtitle.textContent = "上传图片、视频或音频素材，按顺序自动生成。";
        }
      }
    }

    setupPageMode();

    function escapeHtml(text) {
      return String(text || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: {"Content-Type": "application/json"},
        ...options
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "请求失败");
      }
      return data;
    }

    function renderTasks(tasks) {
      const pendingBody = $("taskTable");
      const completedBody = $("completedTaskTable");
      pendingBody.innerHTML = "";
      completedBody.innerHTML = "";

      const terminalStatuses = ["success", "failed", "fail", "rejected", "banned", "error", "cancelled"];
      
      const pendingTasks = (tasks || []).filter(task => {
        // 如果有明确的失败原因，它就是失败的，即使底层 JSON 写着 running
        if (task.fail_reason) return false;
        return !terminalStatuses.includes(task.status);
      });
      
      const completedTasks = (tasks || []).filter(task => {
        if (task.fail_reason) return true;
        return terminalStatuses.includes(task.status);
      });

      function appendRows(target, taskList) {
        for (const task of taskList) {
          const tr = document.createElement("tr");
          let statusClass = "stopped";
          let displayStatus = task.status || "-";
          
          if (task.fail_reason) {
            // 如果有失败原因，强制认定为失败状态，即使底层 JSON 写着 running
            statusClass = "failed";
            displayStatus = "failed";
          } else if (task.status === "success") {
            statusClass = "success";
          } else if (["failed", "fail", "rejected", "banned", "error", "cancelled"].includes(task.status)) {
            statusClass = "failed";
          } else if (task.status === "running") {
            statusClass = "running";
          }

          const failReason = task.fail_reason ? `<div class="hint" style="color:var(--danger);margin-top:4px;">${escapeHtml(task.fail_reason)}</div>` : "";
          const retryAction = (task.fail_reason || ["failed", "fail", "rejected", "banned", "error", "cancelled"].includes(task.status))
            ? `<button class="ghost retry-task-btn" data-project-id="${escapeHtml(task.project_id || "")}" data-segment-id="${escapeHtml(task.segment_id || "")}">重试并加入队尾</button>`
            : "";
          tr.innerHTML = `
            <td>${task.index}</td>
            <td>${escapeHtml(task.project_name || "-")}</td>
            <td>${escapeHtml(task.segment_name || "-")}</td>
            <td>
              <span class="pill ${statusClass}">${escapeHtml(displayStatus)}</span>
              ${failReason}
            </td>
            <td><code>${escapeHtml(task.submit_id || "-")}</code></td>
            <td><code>${escapeHtml(task.command || "")}</code></td>
            <td>${retryAction}</td>
          `;
          target.appendChild(tr);
        }
      }

      appendRows(pendingBody, pendingTasks);
      appendRows(completedBody, completedTasks);

      if (!pendingTasks.length) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="7" class="hint">当前没有待执行任务</td>`;
        pendingBody.appendChild(tr);
      }

      if (!completedTasks.length) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="7" class="hint">当前还没有已完成任务</td>`;
        completedBody.appendChild(tr);
      }
    }

    async function retryTask(projectId, segmentId) {
      if (!projectId || !segmentId) {
        throw new Error("缺少任务标识，无法重试。");
      }
      if (!confirm("把这条失败任务重新加入它原项目的待执行队列队尾吗？")) return;
      const data = await api("/api/retry_task", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, segment_id: segmentId })
      });
      await refresh();
      alert(`已加入原项目待执行队列，当前待执行任务 ${data.queued_count || 0} 个。`);
    }

    async function toggleTableFullscreen(sectionId) {
      const section = $(sectionId);
      if (!section) return;
      if (document.fullscreenElement === section) {
        await document.exitFullscreen();
        return;
      }
      await section.requestFullscreen();
    }

    function updateFullscreenButtons() {
      document.querySelectorAll(".fullscreen-table-btn").forEach((button) => {
        const target = button.dataset.fullscreenTarget;
        button.textContent = document.fullscreenElement?.id === target ? "退出全屏" : "全屏";
      });
    }

    function collectPayload() {
      return {
        dreamina: $("dreamina").value.trim(),
        queue_file: $("queueFile").value.trim(),
        output_root: $("outputRoot").value.trim(),
        state_file: $("stateFile").value.trim(),
        poll_interval: Number($("pollInterval").value || 30),
        timeout_seconds: Number($("timeoutSeconds").value || 10800),
        resume: $("resume").checked,
        stop_on_failure: $("stopOnFailure").checked,
        project_id: activeProjectId,
        queue_content: $("queueContent").value
      };
    }

    function renderProjects(projects, activeProject) {
      allProjects = projects || [];
      activeProjectId = activeProject?.id || activeProjectId || allProjects[0]?.id || "";
      const select = $("projectSelect");
      select.innerHTML = "";
      allProjects.forEach((project) => {
        const option = document.createElement("option");
        option.value = project.id;
        const counts = project.counts || {};
        option.textContent = `${project.name}（${counts.queued || 0} 条）`;
        option.selected = project.id === activeProjectId;
        select.appendChild(option);
      });
      const current = allProjects.find((project) => project.id === activeProjectId) || activeProject || {};
      const counts = current.counts || {};
      $("projectMeta").innerHTML = `
        <span class="pill stopped">任务 ${counts.queued || 0}</span>
        <span class="pill running">成功 ${counts.success || 0}</span>
        <span class="pill failed">失败 ${counts.failed || 0}</span>
        <span class="hint">${escapeHtml(current.output_root || "")}</span>
      `;
    }

    async function refresh() {
      const data = await api("/api/status");
      const runner = data.runner || {};
      const state = data.state || {};
      const uiConfig = data.ui_config || {};
      renderProjects(data.projects || [], data.active_project || null);
      const tasks = state.tasks || [];
      const successCount = tasks.filter(item => item.status === "success").length;
      const failCount = tasks.filter(item => item.status === "failed").length;

      const currentDreamina = $("dreamina").value.trim();
      const currentDreaminaValue = (currentDreamina && currentDreamina !== "dreamina") ? currentDreamina : "";
      const detectedDreamina = data.detected_dreamina || "";
      const runnerDreamina = (runner.running && runner.dreamina && runner.dreamina !== "dreamina") ? runner.dreamina : "";
      $("dreamina").value = runnerDreamina || uiConfig.dreamina || detectedDreamina || currentDreaminaValue || "dreamina";
      $("queueFile").value = data.queue_file || uiConfig.queue_file || "";
      $("outputRoot").value = data.output_root || uiConfig.output_root || "";
      $("stateFile").value = data.state_file || uiConfig.state_file || "";
      $("pollInterval").value = uiConfig.poll_interval || $("pollInterval").value || 30;
      $("timeoutSeconds").value = uiConfig.timeout_seconds || $("timeoutSeconds").value || 10800;
      $("resume").checked = runner.running ? $("resume").checked : !!uiConfig.resume;
      $("stopOnFailure").checked = runner.running ? $("stopOnFailure").checked : !!uiConfig.stop_on_failure;
      if (!isQueueEditorActive() && !queueEditorDirty && !queueSaving) {
        $("queueContent").value = data.queue_content || queueDocumentToText(defaultQueueDocument());
        renderQueueList($("queueContent").value);
      }
      $("logTail").textContent = data.log_tail || "";
      $("totalCount").textContent = tasks.length;
      $("successCount").textContent = successCount;
      $("failCount").textContent = failCount;
      $("updatedAt").textContent = `最后刷新：${new Date().toLocaleString()}`;
      $("runnerPid").textContent = runner.pid || "-";
      $("runnerOutput").textContent = data.video_output_root || data.output_root || "-";

      const running = !!runner.running;
      $("runnerBadge").textContent = running ? "队列运行中" : "当前空闲";
      $("runnerState").innerHTML = running
        ? '<span class="pill running">running</span>'
        : '<span class="pill stopped">idle</span>';
      renderTasks(tasks);
    }

    function appendLines(textarea, lines) {
      const current = textarea.value.trim();
      const extra = (lines || []).join("\\n");
      textarea.value = current ? `${current}\\n${extra}` : extra;
      updatePreview().catch(() => {});
      renderRefs();
    }

    async function uploadFiles(kind, inputId, textareaId) {
      const input = $(inputId);
      if (!input.files || !input.files.length) {
        throw new Error("先选文件，再点上传。");
      }
      const form = new FormData();
      form.append("kind", kind);
      form.append("project_id", activeProjectId);
      for (const file of input.files) {
        form.append("files", file);
      }
      const response = await fetch("/api/upload", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "上传失败");
      }
      appendLines($(textareaId), data.paths || []);
      await loadMaterials();
      renderRefs();
      updateAutocomplete();
      input.value = "";
    }

    function collectMultimodalPayload() {
      return {
        prompt: $("mmPrompt").value,
        duration: $("mmDuration").value,
        ratio: $("mmRatio").value,
        model_version: $("mmModel").value,
        images: $("mmImages").value,
        transition_prompts: $("mmTransitions").value,
        videos: $("mmVideos").value,
        audios: $("mmAudios").value
      };
    }

    function collectTextVideoPayload() {
      return {
        prompt: $("tvPrompt").value,
        duration: $("tvDuration").value,
        ratio: $("tvRatio").value,
        model_version: $("tvModel").value
      };
    }

    // Materials library - 必须在 getMaterialRefs 之前声明
    let allMaterials = [];
    let currentMaterialTab = 'all';
    let activeMaterial = null;
    let promptSelectionSnapshot = null;
    let queueEditorDirty = false;
    let queueSaveTimer = null;
    let queueSaving = false;

    function listFromTextarea(id) {
      return $(id).value.split(/\\n+/).map(item => item.trim()).filter(Boolean);
    }

    function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

    function materialShortName(mat) {
      if (mat && mat.stem) return mat.stem;
      return (mat?.name || "").replace(/^\\d+-/, "").replace(/\\.[^.]+$/, "");
    }

    function materialToken(mat) {
      return '@' + capitalize(mat.kind) + materialShortName(mat);
    }

    function materialLabel(mat) {
      return (mat?.name || "").split("/").pop() || materialShortName(mat);
    }

    function materialFieldId(kind) {
      return {
        image: "mmImages",
        video: "mmVideos",
        audio: "mmAudios",
      }[kind];
    }

    function queueItemId() {
      if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
      }
      return `segment-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    }

    function defaultQueueDocument() {
      return { version: 1, segments: [] };
    }

    const NEWLINE = String.fromCharCode(10);

    function normalizeSegment(segment, index) {
      const raw = (segment && typeof segment === "object" && !Array.isArray(segment)) ? { ...segment } : { command: String(segment || "") };
      const commandText = String(raw.command || "").trim();
      const mode = String(raw.mode || raw.type || "").trim() || (commandText.startsWith("text2video") ? "text2video" : "");
      const normalizeList = (value) => {
        if (Array.isArray(value)) {
          return value.map((item) => String(item || "").trim()).filter(Boolean);
        }
        return String(value || "").split(NEWLINE).map((item) => item.trim()).filter(Boolean);
      };
      return {
        id: String(raw.id || queueItemId()),
        name: String(raw.name || `片段${index}`).trim() || `片段${index}`,
        mode,
        prompt: String(raw.prompt || "").trim(),
        command: commandText,
        images: normalizeList(raw.images),
        transition_prompts: normalizeList(raw.transition_prompts),
        videos: normalizeList(raw.videos),
        audios: normalizeList(raw.audios),
        duration: String(raw.duration || "").trim(),
        ratio: String(raw.ratio || "").trim(),
        model_version: String(raw.model_version || "").trim(),
      };
    }

    function shellQuote(value) {
      const text = String(value || "");
      if (!text) return "''";
      if (/^[A-Za-z0-9_/:.,=@%+-]+$/.test(text)) return text;
      return `'${text.replaceAll("'", `'\"'\"'`)}'`;
    }

    function joinCommand(args) {
      return args.map(shellQuote).join(" ");
    }

    function pathAliases(path) {
      const name = String(path || "").split("/").pop() || "";
      const stem = name.replace(/\\.[^.]+$/, "");
      const cleaned = stem.replace(/^\\d+-[0-9a-fA-F]{8}-/, "");
      return [name, stem, cleaned].filter(Boolean);
    }

    function mediaPathsForPromptRefs(paths, prompt, kind) {
      const refs = [...String(prompt || "").matchAll(new RegExp(`@${kind}([^\\\\s,，。、@]+)`, "g"))].map((match) => match[1]);
      if (!refs.length) return paths;
      const selected = [];
      refs.forEach((ref) => {
        let bestPath = "";
        let bestAlias = "";
        paths.forEach((path) => {
          pathAliases(path).forEach((alias) => {
            if ((ref === alias || ref.startsWith(alias)) && alias.length > bestAlias.length) {
              bestAlias = alias;
              bestPath = path;
            }
          });
        });
        if (bestPath && !selected.includes(bestPath)) {
          selected.push(bestPath);
        }
      });
      return selected;
    }

    function filterSegmentMediaByPromptRefs(segment) {
      return {
        ...segment,
        images: mediaPathsForPromptRefs(segment.images || [], segment.prompt, "Image"),
        videos: mediaPathsForPromptRefs(segment.videos || [], segment.prompt, "Video"),
        audios: mediaPathsForPromptRefs(segment.audios || [], segment.prompt, "Audio"),
      };
    }

    function buildMediaRefMap(segment) {
      const refs = new Map();
      const groups = [
        ["Image", "图片", segment.images || []],
        ["Video", "视频", segment.videos || []],
        ["Audio", "音频", segment.audios || []],
      ];
      groups.forEach(([kind, label, paths]) => {
        paths.forEach((path, index) => {
          pathAliases(path).forEach((alias) => refs.set(`${kind}:${alias}`, `${label}${index + 1}`));
        });
      });
      return refs;
    }

    function normalizePromptForCommand(prompt, segment = null) {
      const refs = segment ? buildMediaRefMap(segment) : new Map();
      return String(prompt || "")
        .trim()
        .replace(/@(Image|Video|Audio)([^\\s,，。、@]+)/g, (_, kind, name) => {
          const exact = refs.get(`${kind}:${name}`);
          if (exact) return exact;
          let bestAlias = "";
          let bestLabel = "";
          for (const [key, label] of refs.entries()) {
            const prefix = `${kind}:`;
            if (!key.startsWith(prefix)) continue;
            const alias = key.slice(prefix.length);
            if (name.startsWith(alias) && alias.length > bestAlias.length) {
              bestAlias = alias;
              bestLabel = label;
            }
          }
          return bestAlias ? `${bestLabel}${name.slice(bestAlias.length)}` : name;
        })
        .replace(/@Image\b/g, "图片参考")
        .replace(/@Video\b/g, "视频参考")
        .replace(/@Audio\b/g, "音频参考");
    }

    function normalizeModelVersion(model) {
      const value = String(model || "").trim();
      return {
        "seedance1.0fast": "seedance2.0fast",
        "seedance1.0": "seedance2.0",
        "seedance1.0fast_vip": "seedance2.0fast_vip",
        "seedance1.0_vip": "seedance2.0_vip",
      }[value] || value;
    }

    function appendCommonArgs(command, segment, includeRatio) {
      if (segment.duration) command.push("--duration", segment.duration);
      if (includeRatio && segment.ratio) command.push("--ratio", segment.ratio);
      const modelVersion = normalizeModelVersion(segment.model_version);
      if (modelVersion) command.push("--model_version", modelVersion);
      return command;
    }

    function buildCommandFromSegment(segment) {
      segment = filterSegmentMediaByPromptRefs(segment);
      const prompt = normalizePromptForCommand(segment.prompt, segment);
      const mode = segment.mode || (!segment.images.length && !segment.videos.length && !segment.audios.length ? "text2video" : "");
      if (mode === "text2video") {
        if (!prompt) return "";
        const command = ["text2video", "--prompt", prompt];
        return joinCommand(appendCommonArgs(command, segment, true));
      }

      if (segment.mode === "multimodal2video" || segment.images.length || segment.videos.length || segment.audios.length) {
        const command = ["multimodal2video"];
        segment.images.forEach((path) => command.push("--image", path));
        segment.videos.forEach((path) => command.push("--video", path));
        segment.audios.forEach((path) => command.push("--audio", path));
        if (prompt) command.push("--prompt", prompt);
        return joinCommand(appendCommonArgs(command, segment, true));
      }

      return "";
    }

    function commandLooksComplete(text) {
      let single = false;
      let double = false;
      let escaped = false;
      for (const ch of String(text || "")) {
        if (escaped) {
          escaped = false;
          continue;
        }
        if (ch === "\\\\") {
          escaped = true;
          continue;
        }
        if (ch === "'" && !double) {
          single = !single;
          continue;
        }
        if (ch === '"' && !single) {
          double = !double;
        }
      }
      return !single && !double;
    }

    function parseLegacyQueueCommands(raw) {
      const commands = [];
      let current = [];
      String(raw || "").split(NEWLINE).forEach((line) => {
        const stripped = line.trim();
        if (!current.length && (!stripped || stripped.startsWith("#"))) {
          return;
        }
        if (!stripped) {
          if (current.length && commandLooksComplete(current.join(NEWLINE))) {
            commands.push(current.join(NEWLINE).trim());
            current = [];
          }
          return;
        }
        current.push(stripped);
        const candidate = current.join(NEWLINE).trim();
        if (candidate && commandLooksComplete(candidate)) {
          commands.push(candidate);
          current = [];
        }
      });
      if (current.length) {
        commands.push(current.join(NEWLINE).trim());
      }
      return commands;
    }

    function extractPromptFromCommand(command) {
      const str = String(command || "");
      const marker = "--prompt";
      const start = str.indexOf(marker);
      if (start === -1) return "";
      let rest = str.slice(start + marker.length).trimStart();
      if (!rest) return "";
      const quote = rest[0];
      if (quote === "'" || quote === '"') {
        let value = "";
        let escaped = false;
        for (let i = 1; i < rest.length; i += 1) {
          const ch = rest[i];
          if (escaped) {
            value += ch;
            escaped = false;
            continue;
          }
          if (ch === "\\\\") {
            escaped = true;
            continue;
          }
          if (ch === quote) {
            return value;
          }
          value += ch;
        }
        return value.trim();
      }
      const nextFlag = rest.indexOf(" --");
      return (nextFlag === -1 ? rest : rest.slice(0, nextFlag)).trim();
    }

    function parseQueueDocument(text) {
      const raw = String(text || "").trim();
      if (!raw) return defaultQueueDocument();
      try {
        const parsed = JSON.parse(raw);
        const segments = Array.isArray(parsed)
          ? parsed
          : (parsed.segments || parsed.tasks || parsed.items || []);
        return {
          version: (parsed && typeof parsed === "object" && !Array.isArray(parsed) ? Number(parsed.version || 1) : 1),
          segments: Array.isArray(segments) ? segments.map((item, index) => normalizeSegment(item, index + 1)) : [],
        };
      } catch (_) {
        const commands = parseLegacyQueueCommands(raw);
        return {
          version: 1,
          segments: commands.map((command, index) => normalizeSegment({
            command,
            name: `片段${index + 1}`,
            prompt: extractPromptFromCommand(command)
          }, index + 1)),
        };
      }
    }

    function queueDocumentToText(doc) {
      const normalized = {
        version: Number(doc?.version || 1),
        segments: (doc?.segments || []).map((segment, index) => normalizeSegment(segment, index + 1)),
      };
      return JSON.stringify(normalized, null, 2);
    }

    function buildQueueSegmentFromForm() {
      const payload = collectMultimodalPayload();
      const draft = filterSegmentMediaByPromptRefs({
        prompt: payload.prompt,
        images: listFromTextarea("mmImages"),
        transition_prompts: listFromTextarea("mmTransitions"),
        videos: listFromTextarea("mmVideos"),
        audios: listFromTextarea("mmAudios"),
      });
      return normalizeSegment(
        {
          id: queueItemId(),
          name: $("mmSegmentName").value.trim() || `片段${Date.now()}`,
          mode: "multimodal2video",
          prompt: payload.prompt,
          images: draft.images,
          transition_prompts: listFromTextarea("mmTransitions"),
          videos: draft.videos,
          audios: draft.audios,
          duration: payload.duration,
          ratio: payload.ratio,
          model_version: payload.model_version,
        },
        (parseQueueDocument($("queueContent").value).segments || []).length + 1,
      );
    }

    function buildTextQueueSegmentFromForm(command) {
      return normalizeSegment(
        {
          id: queueItemId(),
          name: $("tvSegmentName").value.trim() || `文生视频-${Date.now()}`,
          mode: "text2video",
          prompt: $("tvPrompt").value.trim(),
          images: [],
          transition_prompts: [],
          videos: [],
          audios: [],
          duration: $("tvDuration").value.trim(),
          ratio: $("tvRatio").value.trim(),
          model_version: $("tvModel").value.trim(),
          command,
        },
        (parseQueueDocument($("queueContent").value).segments || []).length + 1,
      );
    }

    function isQueueEditorActive() {
      const active = document.activeElement;
      return active === $("queueContent") || !!active?.closest?.(".queue-item");
    }

    function segmentSummary(segment) {
      const parts = [];
      if (segment.images.length) parts.push(`图片 ${segment.images.length}`);
      if (segment.transition_prompts.length) parts.push(`过渡 ${segment.transition_prompts.length}`);
      if (segment.videos.length) parts.push(`视频 ${segment.videos.length}`);
      if (segment.audios.length) parts.push(`音频 ${segment.audios.length}`);
      if (segment.duration) parts.push(`${segment.duration}s`);
      if (segment.ratio) parts.push(segment.ratio);
      if (segment.model_version) parts.push(segment.model_version);
      return parts.join(" · ") || "仅提示词";
    }

    function renderQueueMediaStrip(segment) {
      const blocks = [];
      if (segment.images.length) {
        const thumbs = segment.images.map((path) => {
          const label = String(path).split("/").pop() || path;
          return `
            <div class="queue-image-thumb" title="${escapeHtml(path)}">
              <img src="/api/file?path=${encodeURIComponent(path)}" alt="${escapeHtml(label)}">
              <span>${escapeHtml(label)}</span>
            </div>
          `;
        }).join("");
        blocks.push(`<div class="queue-image-strip">${thumbs}</div>`);
      }

      const tags = [];
      segment.videos.forEach((path) => {
        const label = String(path).split("/").pop() || path;
        tags.push(`<span class="video" title="${escapeHtml(path)}">视频 · ${escapeHtml(label)}</span>`);
      });
      segment.audios.forEach((path) => {
        const label = String(path).split("/").pop() || path;
        tags.push(`<span class="audio" title="${escapeHtml(path)}">音频 · ${escapeHtml(label)}</span>`);
      });
      if (tags.length) {
        blocks.push(`<div class="queue-media-tags">${tags.join("")}</div>`);
      }

      if (!blocks.length) {
        return "";
      }
      return `<div class="queue-media-strip">${blocks.join("")}</div>`;
    }

    function syncQueueContentFromList() {
      const items = Array.from(document.querySelectorAll(".queue-item"));
      const documentData = {
        version: 1,
        segments: items.map((item, index) => normalizeSegment({
          id: item.dataset.segmentId,
          mode: item.dataset.segmentMode,
          name: item.querySelector("[data-field='name']").value,
          prompt: item.querySelector("[data-field='prompt']").value,
          images: item.querySelector("[data-field='images']").value,
          transition_prompts: item.querySelector("[data-field='transition_prompts']").value,
          videos: item.querySelector("[data-field='videos']").value,
          audios: item.querySelector("[data-field='audios']").value,
          duration: item.querySelector("[data-field='duration']").value,
          ratio: item.querySelector("[data-field='ratio']").value,
          model_version: item.querySelector("[data-field='model_version']").value,
          command: item.querySelector("[data-field='command']").value,
        }, index + 1)),
      };
      $("queueContent").value = queueDocumentToText(documentData);
      queueEditorDirty = true;
      return documentData;
    }

    async function saveQueueSilently() {
      if (queueSaving) return;
      queueSaving = true;
      try {
        await api("/api/save_queue", {
          method: "POST",
          body: JSON.stringify(collectPayload())
        });
        queueEditorDirty = false;
      } catch (err) {
        console.error("保存队列失败", err);
      } finally {
        queueSaving = false;
      }
    }

    function scheduleQueueAutosave(delay = 350) {
      clearTimeout(queueSaveTimer);
      queueSaveTimer = setTimeout(() => {
        saveQueueSilently().catch((err) => console.error("保存队列失败", err));
      }, delay);
    }

    function renderPromptWithTokens(prompt, segment) {
      if (!prompt) return "";
      const tokens = [];
      const regex = /@(Image|Video|Audio)([^\\s@]+)/g;
      let lastIndex = 0;
      let match;

      while ((match = regex.exec(prompt)) !== null) {
        const [fullMatch, type, name] = match;
        const startIndex = match.index;

        if (startIndex > lastIndex) {
          tokens.push({ type: "text", content: prompt.slice(lastIndex, startIndex) });
        }

        tokens.push({ type: "token", tokenType: type.toLowerCase(), name, fullMatch });
        lastIndex = regex.lastIndex;
      }

      if (lastIndex < prompt.length) {
        tokens.push({ type: "text", content: prompt.slice(lastIndex) });
      }

      return tokens.map(token => {
        if (token.type === "text") {
          return escapeHtml(token.content);
        }
        const typeLabel = { image: "图", video: "视", audio: "音" }[token.tokenType] || "?";
        const colorClass = token.tokenType;
        return `<span class="prompt-token ${colorClass}" title="${escapeHtml(token.fullMatch)}">${typeLabel}:${escapeHtml(token.name)}</span>`;
      }).join("");
    }

    function autoResizeTextarea(textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.max(textarea.scrollHeight, 120)}px`;
    }

    function renderQueueList(text) {
      const container = $("queueList");
      const documentData = parseQueueDocument(text);
      const segments = documentData.segments || [];
      container.innerHTML = "";
      if (!segments.length) {
        container.innerHTML = '<div class="hint">当前还没有视频段，点“新增一条”或用上面的表单加入队列。</div>';
        $("queueContent").value = queueDocumentToText(documentData);
        return;
      }

      segments.forEach((rawSegment, index) => {
        const segment = normalizeSegment({
          ...rawSegment,
          mode: rawSegment.mode || ((rawSegment.images?.length || rawSegment.videos?.length || rawSegment.audios?.length) ? "multimodal2video" : ""),
        }, index + 1);
        const filteredSegment = filterSegmentMediaByPromptRefs(segment);
        segment.images = filteredSegment.images;
        segment.videos = filteredSegment.videos;
        segment.audios = filteredSegment.audios;
        if (segment.mode === "multimodal2video" || segment.images.length || segment.videos.length || segment.audios.length) {
          segment.mode = "multimodal2video";
          segment.command = buildCommandFromSegment(segment);
        }
        documentData.segments[index] = segment;
        const card = document.createElement("div");
        card.className = "queue-item";
        card.dataset.segmentId = segment.id;
        card.dataset.segmentMode = segment.mode;
        card.innerHTML = `
          <div class="queue-item-head">
            <div>
              <strong>${escapeHtml(segment.name || `片段${index + 1}`)}</strong>
              <div class="hint" style="margin-top:4px;">${escapeHtml(segmentSummary(segment))}</div>
            </div>
            <div class="queue-item-actions">
              <button class="ghost" type="button" data-action="duplicate">复制</button>
              <button class="ghost" type="button" data-action="remove">删除</button>
            </div>
          </div>
          ${renderQueueMediaStrip(segment)}
          <div style="padding:12px;">
            <label>视频段名称</label>
            <input data-field="name" value="${escapeHtml(segment.name)}">
            <label style="margin-top:10px;">提示词</label>
	            <textarea class="queue-item-input" data-field="prompt" spellcheck="false">${escapeHtml(segment.prompt)}</textarea>
	            <details style="margin-top:10px;">
	              <summary style="cursor:pointer;color:var(--accent);font-weight:700;">素材与参数</summary>
	              <div style="display:grid;gap:10px;margin-top:10px;">
	                <div>
	                  <label>图片素材</label>
	                  <textarea data-field="images" class="queue-item-input" spellcheck="false">${escapeHtml(segment.images.join("\\n"))}</textarea>
                    <div class="hint" style="margin-top:6px;">多图按顺序解释。3 张及以上图片时，建议填写下面的“多图过渡提示词”。</div>
	                </div>
	                <div>
	                  <label>多图过渡提示词</label>
	                  <textarea data-field="transition_prompts" class="queue-item-input" spellcheck="false">${escapeHtml(segment.transition_prompts.join("\\n"))}</textarea>
	                </div>
	                <div>
	                  <label>视频素材</label>
	                  <textarea data-field="videos" class="queue-item-input" spellcheck="false">${escapeHtml(segment.videos.join("\\n"))}</textarea>
	                </div>
                <div>
                  <label>音频素材</label>
                  <textarea data-field="audios" class="queue-item-input" spellcheck="false">${escapeHtml(segment.audios.join("\\n"))}</textarea>
                </div>
                <div class="subgrid">
                  <div>
                    <label>时长</label>
                    <input data-field="duration" value="${escapeHtml(segment.duration)}">
                  </div>
                  <div>
                    <label>比例</label>
                    <input data-field="ratio" value="${escapeHtml(segment.ratio)}">
                  </div>
                  <div>
                    <label>模型</label>
                    <input data-field="model_version" value="${escapeHtml(segment.model_version)}">
                  </div>
                </div>
                <div>
                  <label>原始命令（兼容旧格式时可用）</label>
                  <textarea data-field="command" class="queue-item-input" spellcheck="false">${escapeHtml(segment.command)}</textarea>
                </div>
              </div>
            </details>
          </div>
        `;
        card.querySelectorAll("textarea").forEach(autoResizeTextarea);
        card.querySelectorAll("input, textarea").forEach((field) => {
          field.addEventListener("input", () => {
            if (field.tagName === "TEXTAREA") autoResizeTextarea(field);
            const nameEl = card.querySelector("[data-field='name']");
            const promptEl = card.querySelector("[data-field='prompt']");
            const commandEl = card.querySelector("[data-field='command']");
            if ((field.dataset.field || "") !== "command") {
              const draft = normalizeSegment({
                id: card.dataset.segmentId,
                mode: card.dataset.segmentMode,
                name: nameEl.value,
                prompt: promptEl.value,
                images: card.querySelector("[data-field='images']").value,
                transition_prompts: card.querySelector("[data-field='transition_prompts']").value,
                videos: card.querySelector("[data-field='videos']").value,
                audios: card.querySelector("[data-field='audios']").value,
                duration: card.querySelector("[data-field='duration']").value,
                ratio: card.querySelector("[data-field='ratio']").value,
                model_version: card.querySelector("[data-field='model_version']").value,
              }, index + 1);
              commandEl.value = buildCommandFromSegment(draft);
              autoResizeTextarea(commandEl);
            }
            card.querySelector(".queue-item-head strong").textContent = nameEl.value.trim() || `片段${index + 1}`;
            card.querySelector(".queue-item-head .hint").textContent = segmentSummary(normalizeSegment({
              id: card.dataset.segmentId,
              mode: card.dataset.segmentMode,
              name: nameEl.value,
		              prompt: promptEl.value,
		              images: card.querySelector("[data-field='images']").value,
	              transition_prompts: card.querySelector("[data-field='transition_prompts']").value,
	              videos: card.querySelector("[data-field='videos']").value,
	              audios: card.querySelector("[data-field='audios']").value,
              duration: card.querySelector("[data-field='duration']").value,
              ratio: card.querySelector("[data-field='ratio']").value,
              model_version: card.querySelector("[data-field='model_version']").value,
              command: card.querySelector("[data-field='command']").value,
            }, index + 1));
            syncQueueContentFromList();
            scheduleQueueAutosave();
          });
          field.addEventListener("change", () => {
            if (["images", "transition_prompts", "videos", "audios"].includes(field.dataset.field || "")) {
              syncQueueContentFromList();
              renderQueueList($("queueContent").value);
              scheduleQueueAutosave();
            }
          });
        });
        card.querySelector("[data-action='remove']").addEventListener("click", () => {
          card.remove();
          syncQueueContentFromList();
          renderQueueList($("queueContent").value);
          scheduleQueueAutosave(0);
        });
        card.querySelector("[data-action='duplicate']").addEventListener("click", () => {
          const doc = syncQueueContentFromList();
          const current = normalizeSegment(doc.segments[index], doc.segments.length + 1);
          doc.segments.splice(index + 1, 0, { ...current, id: queueItemId(), name: `${current.name}-复制` });
          $("queueContent").value = queueDocumentToText(doc);
          renderQueueList($("queueContent").value);
          scheduleQueueAutosave(0);
        });
        container.appendChild(card);
      });
      $("queueContent").value = queueDocumentToText(documentData);
    }

    function snapshotTextareaState(textarea) {
      return {
        start: textarea.selectionStart ?? textarea.value.length,
        end: textarea.selectionEnd ?? textarea.value.length,
        scrollTop: textarea.scrollTop ?? 0,
        scrollLeft: textarea.scrollLeft ?? 0,
        pageX: window.scrollX ?? 0,
        pageY: window.scrollY ?? 0,
      };
    }

    function rememberPromptSelection() {
      promptSelectionSnapshot = snapshotTextareaState($("mmPrompt"));
    }

    function getTextareaState(textarea) {
      if (textarea.id === "mmPrompt" && promptSelectionSnapshot) {
        return promptSelectionSnapshot;
      }
      return snapshotTextareaState(textarea);
    }

    function restoreTextareaState(textarea, state, caretPos) {
      try {
        textarea.focus({ preventScroll: true });
      } catch (_) {
        textarea.focus();
      }
      textarea.setSelectionRange(caretPos, caretPos);
      const scrollTop = state?.scrollTop ?? 0;
      const scrollLeft = state?.scrollLeft ?? 0;
      const pageX = state?.pageX ?? window.scrollX ?? 0;
      const pageY = state?.pageY ?? window.scrollY ?? 0;
      requestAnimationFrame(() => {
        textarea.scrollTop = scrollTop;
        textarea.scrollLeft = scrollLeft;
        window.scrollTo(pageX, pageY);
      });
      if (textarea.id === "mmPrompt") {
        promptSelectionSnapshot = {
          ...state,
          start: caretPos,
          end: caretPos,
          scrollTop,
          scrollLeft,
          pageX,
          pageY,
        };
      }
    }

    function getMaterialRefs() {
      // 只从已上传的素材库生成引用，过滤掉非媒体文件
      const refs = [];
      allMaterials.forEach((mat) => {
        // 过滤掉 .DS_Store 等非媒体文件
        if (mat.name.startsWith('.')) return;

        refs.push({
          token: materialToken(mat),
          path: mat.path,
          cls: mat.kind,
          type: mat.kind,
          name: mat.name,
          stem: materialShortName(mat)
        });
      });
      return refs;
    }

    function insertAtCursor(textarea, text) {
      const state = getTextareaState(textarea);
      const start = state.start ?? textarea.value.length;
      const end = state.end ?? textarea.value.length;
      const before = textarea.value.slice(0, start);
      const after = textarea.value.slice(end);
      const joiner = before && !before.endsWith(" ") && !before.endsWith("\\n") ? " " : "";
      textarea.value = `${before}${joiner}${text}${after}`;
      const nextPos = (before + joiner + text).length;
      restoreTextareaState(textarea, state, nextPos);
      updatePreview().catch(() => {});
    }

    function renderRefs() {
      const refList = $("refList");
      refList.innerHTML = "";
      const previewGrid = $("imagePreviewGrid");
      previewGrid.innerHTML = "";
      const refs = getMaterialRefs();

      for (const ref of refs) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `ref-chip ${ref.cls}`.trim();
        btn.textContent = ref.token;
        btn.title = ref.path;
        btn.addEventListener("click", () => insertAtCursor($("mmPrompt"), ref.token));
        refList.appendChild(btn);
      }

      for (const ref of refs.filter(item => item.type === "image")) {
        const card = document.createElement("div");
        card.className = "preview-card";
        card.title = `${ref.token}\n${ref.path}`;
        card.innerHTML = `
          <img src="/api/file?path=${encodeURIComponent(ref.path)}" alt="${ref.token}">
          <div class="preview-meta"><strong>${ref.token}</strong><br>${escapeHtml(ref.name || ref.path.split("/").pop() || ref.path)}</div>
        `;
        card.addEventListener("click", () => insertAtCursor($("mmPrompt"), ref.token));
        previewGrid.appendChild(card);
      }

      if (!refs.length) {
        const empty = document.createElement("span");
        empty.className = "hint";
        empty.textContent = "还没有素材引用";
        refList.appendChild(empty);
      }
    }

    function findAtToken(textarea) {
      const state = getTextareaState(textarea);
      const pos = state.start ?? 0;
      const before = textarea.value.slice(0, pos);
      const match = before.match(/@[^\\s@]*$/);
      if (!match) return null;
      return {
        token: match[0],
        start: pos - match[0].length,
        end: pos
      };
    }

    function hideAutocomplete() {
      $("atAutocomplete").classList.remove("show");
      $("atAutocomplete").innerHTML = "";
    }

    function applyAutocompleteToken(choice) {
      const textarea = $("mmPrompt");
      const info = findAtToken(textarea);
      if (!info) {
        insertAtCursor(textarea, choice.token);
        hideAutocomplete();
        return;
      }
      textarea.value = `${textarea.value.slice(0, info.start)}${choice.token}${textarea.value.slice(info.end)}`;
      const nextPos = info.start + choice.token.length;
      restoreTextareaState(textarea, getTextareaState(textarea), nextPos);
      hideAutocomplete();
      if (choice.path && choice.type) {
        const fieldId = materialFieldId(choice.type);
        if (fieldId) {
          const field = $(fieldId);
          const existing = listFromTextarea(fieldId);
          if (!existing.includes(choice.path)) {
            field.value = field.value ? `${field.value}\\n${choice.path}` : choice.path;
          }
        }
      }

      updatePreview().catch(() => {});
    }

    function updateAutocomplete() {
      const box = $("atAutocomplete");
      const textarea = $("mmPrompt");
      const info = findAtToken(textarea);
      if (!info) {
        hideAutocomplete();
        return;
      }
      const keyword = info.token.toLowerCase();
      const matches = getMaterialRefs().filter(item => item.token.toLowerCase().startsWith(keyword));
      if (!matches.length) {
        hideAutocomplete();
        return;
      }
      box.innerHTML = "";
      matches.forEach(item => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "autocomplete-item";
        const thumb = item.type === "image"
          ? `<div class="autocomplete-thumb"><img src="/api/file?path=${encodeURIComponent(item.path)}" alt="${escapeHtml(item.token)}"></div>`
          : `<div class="autocomplete-thumb">${item.type === "video" ? "▶" : "♫"}</div>`;
        btn.innerHTML = `
          ${thumb}
          <div class="autocomplete-copy">
            <strong>${escapeHtml(item.token)}</strong>
            <span>${escapeHtml(item.name || item.path.split("/").pop() || "")}</span>
          </div>
        `;
        btn.addEventListener("mousedown", (event) => event.preventDefault());
        btn.addEventListener("click", () => applyAutocompleteToken(item));
        box.appendChild(btn);
      });
      box.classList.add("show");
    }

    async function updatePreview() {
      const payload = collectMultimodalPayload();
      // Skip API call if no media files
      if (!payload.images.trim() && !payload.videos.trim() && !payload.audios.trim()) {
        $("mmPreview").value = "至少要有一个图片、视频或音频素材。";
        return;
      }
      try {
        const data = await api("/api/build_multimodal", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        $("mmPreview").value = data.command || "";
      } catch (err) {
        $("mmPreview").value = err.message;
      }
    }

    async function updateTextVideoPreview() {
      const payload = collectTextVideoPayload();
      if (!payload.prompt.trim()) {
        $("tvPreview").value = "填写提示词后会自动生成文生视频命令。";
        return;
      }
      try {
        const data = await api("/api/build_text2video", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        $("tvPreview").value = data.command || "";
      } catch (err) {
        $("tvPreview").value = err.message;
      }
    }

    async function addTextVideoTask() {
      const data = await api("/api/build_text2video", {
        method: "POST",
        body: JSON.stringify(collectTextVideoPayload())
      });
      const doc = parseQueueDocument($("queueContent").value);
      doc.segments.push(buildTextQueueSegmentFromForm(data.command));
      $("queueContent").value = queueDocumentToText(doc);
      renderQueueList($("queueContent").value);
      $("tvPreview").value = data.command;
      const payload = collectPayload();
      payload.queue_content = $("queueContent").value;
      await api("/api/save_queue", { method: "POST", body: JSON.stringify(payload) });
    }

    function clearTextVideoForm() {
      $("tvSegmentName").value = "";
      $("tvPrompt").value = "";
      $("tvDuration").value = "5";
      $("tvRatio").value = "9:16";
      $("tvModel").value = "seedance2.0fast";
      $("tvPreview").value = "";
      updateTextVideoPreview().catch(() => {});
    }

    async function addMultimodalTask() {
      const data = await api("/api/build_multimodal", {
        method: "POST",
        body: JSON.stringify(collectMultimodalPayload())
      });
      const doc = parseQueueDocument($("queueContent").value);
      doc.segments.push({
        ...buildQueueSegmentFromForm(),
        command: data.command,
      });
      $("queueContent").value = queueDocumentToText(doc);
      renderQueueList($("queueContent").value);
      $("mmPreview").value = data.command;
      // auto-save so refresh() wont clobber the queue
      const payload = collectPayload();
      payload.queue_content = $("queueContent").value;
      await api("/api/save_queue", { method: "POST", body: JSON.stringify(payload) });
    }

    function clearMultimodalForm() {
      $("mmSegmentName").value = "";
      $("mmPrompt").value = "";
      $("mmImages").value = "";
      $("mmTransitions").value = "";
      $("mmVideos").value = "";
      $("mmAudios").value = "";
      $("mmDuration").value = "5";
      $("mmRatio").value = "9:16";
      $("mmModel").value = "seedance2.0fast";
      $("mmPreview").value = "";
      renderRefs();
      hideAutocomplete();
    }

    function closeMaterialModal() {
      activeMaterial = null;
      $("materialModal").classList.remove("show");
      $("materialModal").setAttribute("aria-hidden", "true");
    }

    function openMaterialModal(mat) {
      activeMaterial = mat;
      $("materialModalTitle").textContent = materialLabel(mat);
      $("materialModalToken").textContent = materialToken(mat);
      $("materialModalPath").textContent = mat.path || "";
      $("materialRenameInput").value = materialShortName(mat);
      $("materialRenameHint").textContent = `保存时会同步修改本地文件名，扩展名 ${mat.name.includes(".") ? "." + mat.name.split(".").pop() : ""} 会保留。`;

      const preview = $("materialModalPreview");
      if (mat.kind === "image") {
        preview.classList.remove("empty");
        preview.innerHTML = `<img src="/api/file?path=${encodeURIComponent(mat.path)}" alt="${escapeHtml(materialLabel(mat))}">`;
      } else {
        preview.classList.add("empty");
        preview.textContent = mat.kind === "video" ? "这里暂时不做视频播放，主要用于改名。" : "这里暂时不做音频播放，主要用于改名。";
      }

      $("materialModal").classList.add("show");
      $("materialModal").setAttribute("aria-hidden", "false");
    }

    function replaceEverywhere(oldValue, nextValue) {
      if (!oldValue || oldValue === nextValue) return;
      ["mmPrompt", "mmImages", "mmVideos", "mmAudios"].forEach((id) => {
        const el = $(id);
        if (el.value.includes(oldValue)) {
          el.value = el.value.split(oldValue).join(nextValue);
        }
      });
    }

    function applyRenamedMaterial(oldMaterial, newMaterial) {
      allMaterials = allMaterials.map((item) => item.path === oldMaterial.path ? newMaterial : item);
      replaceEverywhere(oldMaterial.path, newMaterial.path);
      replaceEverywhere(materialToken(oldMaterial), materialToken(newMaterial));
      renderMaterials();
      renderRefs();
      updateAutocomplete();
      updatePreview().catch(() => {});
    }

    async function saveMaterialRename() {
      if (!activeMaterial) return;
      const input = $("materialRenameInput").value.trim();
      const data = await api("/api/rename_upload", {
        method: "POST",
        body: JSON.stringify({
          path: activeMaterial.path,
          new_name: input
        })
      });
      applyRenamedMaterial(activeMaterial, data.material);
      openMaterialModal(data.material);
    }

    async function uploadBlobs(kind, files, textareaId) {
      const form = new FormData();
      form.append("kind", kind);
      form.append("project_id", activeProjectId);
      for (const file of files) {
        form.append("files", file);
      }
      const response = await fetch("/api/upload", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "上传失败");
      }
      appendLines($(textareaId), data.paths || []);
      await loadMaterials();
      renderRefs();
      updateAutocomplete();
      return data;
    }

    async function handlePasteImage(event) {
      const items = Array.from(event.clipboardData?.items || []);
      const files = items
        .filter(item => item.type && item.type.startsWith("image/"))
        .map(item => item.getAsFile())
        .filter(Boolean);
      if (!files.length) {
        return;
      }
      event.preventDefault();
      $("pasteImageZone").classList.add("active");
      try {
        await uploadBlobs("image", files, "mmImages");
      } catch (err) {
        alert(err.message);
      } finally {
        setTimeout(() => $("pasteImageZone").classList.remove("active"), 300);
      }
    }

    async function saveQueue() {
      syncQueueContentFromList();
      await api("/api/save_queue", {
        method: "POST",
        body: JSON.stringify(collectPayload())
      });
      await refresh();
      alert("队列已保存");
    }

    async function saveCurrentQueueSilentlyBeforeProjectChange() {
      if (!activeProjectId) return;
      syncQueueContentFromList();
      await api("/api/save_queue", {
        method: "POST",
        body: JSON.stringify(collectPayload())
      });
      queueEditorDirty = false;
    }

    async function switchProject(projectId) {
      if (!projectId || projectId === activeProjectId) return;
      await saveCurrentQueueSilentlyBeforeProjectChange();
      await api("/api/projects/select", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId })
      });
      activeProjectId = projectId;
      queueEditorDirty = false;
      await refresh();
      await loadMaterials();
    }

    async function createProjectFromPrompt() {
      const name = window.prompt("项目名称", "新项目");
      if (name === null) return;
      await saveCurrentQueueSilentlyBeforeProjectChange();
      const data = await api("/api/projects/create", {
        method: "POST",
        body: JSON.stringify({ name })
      });
      activeProjectId = data.project?.id || activeProjectId;
      queueEditorDirty = false;
      await refresh();
      await loadMaterials();
    }

    async function renameCurrentProject() {
      const current = allProjects.find((project) => project.id === activeProjectId);
      if (!current) return;
      const name = window.prompt("新的项目名称", current.name || "");
      if (name === null) return;
      await api("/api/projects/rename", {
        method: "POST",
        body: JSON.stringify({ project_id: activeProjectId, name })
      });
      await refresh();
    }

    async function startQueue() {
      syncQueueContentFromList();
      const data = await api("/api/start", {
        method: "POST",
        body: JSON.stringify(collectPayload())
      });
      await refresh();
      const runner = data.runner || {};
      if (runner.queued_while_running) {
        const added = Number(runner.queued_added_count || 0);
        const count = Number(runner.queued_count || 0);
        if (added > 0) {
          alert(`已加入待执行队列，新增 ${added} 个任务，当前待执行任务 ${count} 个。`);
        } else {
          alert("队列已保存，但没有新增待执行任务。");
        }
      } else {
        alert("队列已启动。");
      }
    }

    async function stopQueue() {
      await api("/api/stop", {
        method: "POST",
        body: JSON.stringify({})
      });
      await refresh();
    }

    async function clearExecutionQueue() {
      if (!confirm("确认清空执行队列吗？\\n\\n会停止当前本地 runner，并清空 .webui/global.queue.json 和 .webui/queue-state.json。\\n不会清空任何项目里的 queue.json，也不会删除已下载视频。")) return;
      const data = await api("/api/clear_execution_queue", {
        method: "POST",
        body: JSON.stringify({})
      });
      await refresh();
      alert(data.stopped_runner ? "已停止 runner，并清空执行队列。" : "已清空执行队列。");
    }

    async function detectDreamina() {
      const data = await api("/api/status");
      if (!data.detected_dreamina) {
        throw new Error("没有自动检测到 dreamina。你可能还没安装即梦 CLI。");
      }
      $("dreamina").value = data.detected_dreamina;
      await api("/api/save_config", {
        method: "POST",
        body: JSON.stringify({
          dreamina: data.detected_dreamina,
          queue_file: $("queueFile").value.trim(),
          output_root: $("outputRoot").value.trim(),
          state_file: $("stateFile").value.trim(),
          poll_interval: Number($("pollInterval").value || 30),
          timeout_seconds: Number($("timeoutSeconds").value || 10800),
          resume: $("resume").checked,
          stop_on_failure: $("stopOnFailure").checked,
          project_id: activeProjectId
        })
      });
      alert(`已检测到 dreamina：\\n${data.detected_dreamina}`);
    }

    $("detectBtn").addEventListener("click", () => detectDreamina().catch(err => alert(err.message)));
    $("projectSelect").addEventListener("change", (event) => switchProject(event.target.value).catch(err => alert(err.message)));
    $("newProjectBtn").addEventListener("click", () => createProjectFromPrompt().catch(err => alert(err.message)));
    $("renameProjectBtn").addEventListener("click", () => renameCurrentProject().catch(err => alert(err.message)));
    $("saveBtn").addEventListener("click", () => saveQueue().catch(err => alert(err.message)));
    $("startBtn").addEventListener("click", () => startQueue().catch(err => alert(err.message)));
    $("stopBtn").addEventListener("click", () => stopQueue().catch(err => alert(err.message)));
    $("clearExecutionQueueBtn").addEventListener("click", () => clearExecutionQueue().catch(err => alert(err.message)));
    $("refreshBtn").addEventListener("click", () => refresh().catch(err => alert(err.message)));
    document.addEventListener("click", (event) => {
      const button = event.target?.closest?.(".retry-task-btn");
      if (!button) return;
      retryTask(button.dataset.projectId, button.dataset.segmentId).catch(err => alert(err.message));
    });
    document.addEventListener("click", (event) => {
      const button = event.target?.closest?.(".fullscreen-table-btn");
      if (!button) return;
      toggleTableFullscreen(button.dataset.fullscreenTarget).catch(err => alert(err.message));
    });
    document.addEventListener("fullscreenchange", updateFullscreenButtons);
    $("uploadImagesBtn").addEventListener("click", () => uploadFiles("image", "uploadImages", "mmImages").catch(err => alert(err.message)));
    $("uploadVideosBtn").addEventListener("click", () => uploadFiles("video", "uploadVideos", "mmVideos").catch(err => alert(err.message)));
    $("uploadAudiosBtn").addEventListener("click", () => uploadFiles("audio", "uploadAudios", "mmAudios").catch(err => alert(err.message)));
    $("addTextVideoBtn").addEventListener("click", () => addTextVideoTask().catch(err => alert(err.message)));
    $("clearTextVideoBtn").addEventListener("click", clearTextVideoForm);
    $("addMultimodalBtn").addEventListener("click", () => addMultimodalTask().catch(err => alert(err.message)));
    $("addQueueItemBtn").addEventListener("click", () => {
      const doc = parseQueueDocument($("queueContent").value);
      doc.segments.push(normalizeSegment({ id: queueItemId(), name: `片段${doc.segments.length + 1}` }, doc.segments.length + 1));
      $("queueContent").value = queueDocumentToText(doc);
      renderQueueList($("queueContent").value);
      scheduleQueueAutosave(0);
    });
    $("clearMultimodalBtn").addEventListener("click", clearMultimodalForm);
    $("pasteImageZone").addEventListener("paste", handlePasteImage);
    $("pasteImageZone").addEventListener("click", () => $("pasteImageZone").focus());
    $("materialModalCloseBtn").addEventListener("click", closeMaterialModal);
    $("materialInsertBtn").addEventListener("click", () => {
      if (activeMaterial) {
        insertMaterialRef(activeMaterial);
      }
    });
    $("materialRenameBtn").addEventListener("click", () => saveMaterialRename().catch(err => alert(err.message)));
    $("materialModal").addEventListener("click", (event) => {
      if (event.target === $("materialModal")) {
        closeMaterialModal();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hideAutocomplete();
        closeMaterialModal();
      }
    });
    $("mmPrompt").addEventListener("keyup", updateAutocomplete);
    $("mmPrompt").addEventListener("click", updateAutocomplete);
    $("mmPrompt").addEventListener("blur", () => setTimeout(hideAutocomplete, 120));
    ["keyup", "click", "input", "select", "scroll"].forEach((eventName) => {
      $("mmPrompt").addEventListener(eventName, rememberPromptSelection);
    });
    $("queueContent").addEventListener("input", () => {
      if (document.activeElement === $("queueContent")) {
        renderQueueList($("queueContent").value);
        scheduleQueueAutosave();
      }
    });
    ["mmPrompt", "mmDuration", "mmRatio", "mmModel", "mmImages", "mmVideos", "mmAudios"].forEach((id) => {
      $(id).addEventListener("input", () => {
        renderRefs();
        updatePreview().catch(() => {});
        if (id === "mmPrompt") updateAutocomplete();
      });
    });
    ["tvPrompt", "tvDuration", "tvRatio", "tvModel"].forEach((id) => {
      $(id).addEventListener("input", () => updateTextVideoPreview().catch(() => {}));
    });

    refresh().catch(err => alert(err.message));
    renderQueueList($("queueContent").value);
    renderRefs();
    updatePreview().catch(() => {});
    updateTextVideoPreview().catch(() => {});
    setInterval(() => refresh().catch(() => {}), 5000);

    async function loadMaterials() {
      try {
        const query = activeProjectId ? `?project_id=${encodeURIComponent(activeProjectId)}` : "";
        const res = await api('/api/uploads_list' + query);
        allMaterials = res.uploads || [];
        renderMaterials();
        renderRefs();
        updateAutocomplete();
      } catch (err) {
        console.error('loadMaterials error:', err);
      }
    }

    window.showMaterialTab = function(tab) {
      currentMaterialTab = tab;
      updateMaterialTabStyle();
      renderMaterials();
    };

    function updateMaterialTabStyle() {
      document.querySelectorAll('#materialTabs button').forEach(function(btn) {
        var tab = btn.id.replace('tab', '').toLowerCase();
        var active = tab === currentMaterialTab;
        btn.style.fontWeight = active ? '700' : 'normal';
        btn.style.background = active ? 'rgba(31,107,94,0.18)' : 'rgba(31,107,94,0.08)';
      });
    }

    function insertMaterialRef(mat) {
      var token = materialToken(mat);
      var textarea = $('mmPrompt');
      var state = getTextareaState(textarea);
      var pos = state.start != null ? state.start : textarea.value.length;
      var before = textarea.value.slice(0, pos);
      var after = textarea.value.slice(pos);
      var joiner = (before && before[before.length-1] !== ' ' && before[before.length-1] !== '\\n') ? ' ' : '';
      textarea.value = before + joiner + token + after;
      var nextPos = (before + joiner + token).length;
      restoreTextareaState(textarea, state, nextPos);
      var fieldId = materialFieldId(mat.kind);
      if (fieldId) {
        var existing = listFromTextarea(fieldId);
        if (!existing.includes(mat.path)) {
          var field = $(fieldId);
          field.value = field.value ? field.value + '\\n' + mat.path : mat.path;
        }
      }
      updatePreview().catch(function() {});
      renderRefs();
    }

    function renderMaterials() {
      var grid = $('materialGrid');
      var clean = allMaterials.filter(function(m) { return m && m.name && !m.name.startsWith('.'); });
      var filtered = currentMaterialTab === 'all'
        ? clean
        : clean.filter(function(m) { return m.kind === currentMaterialTab; });
      if (!filtered.length) {
        grid.innerHTML = '<span class="hint">暂无素材，上传后会显示在这。</span>';
        return;
      }
      grid.innerHTML = '';
      filtered.forEach(function(mat) {
        var card = document.createElement('div');
        card.className = 'preview-card';
        var shortName = materialShortName(mat);
        var token = materialToken(mat);
        var media = document.createElement('div');
        if (mat.kind === 'image') {
          media.innerHTML = '<img src="/api/file?path=' + encodeURIComponent(mat.path) + '" alt="">';
        } else {
          var icon = mat.kind === 'video' ? '&#9654;' : '&#9834;';
          var kindColor = mat.kind === 'video' ? 'rgba(215,109,63,0.10)' : 'rgba(109,101,88,0.12)';
          media.innerHTML = '<div style="height:110px;display:flex;align-items:center;justify-content:center;background:' + kindColor + ';font-size:36px;color:var(--muted);">' + icon + '</div>';
        }
        media.addEventListener('click', function() { openMaterialModal(mat); });
        card.appendChild(media);

        var meta = document.createElement('div');
        meta.className = 'preview-meta';
        meta.style.fontSize = '11px';
        meta.innerHTML =
          '<strong style="color:' + (mat.kind === 'image' ? 'var(--accent)' : 'var(--accent-2)') + ';">' + escapeHtml(token) + '</strong><br>' +
          '<span style="color:var(--muted);">' + escapeHtml(shortName) + '</span>';
        card.appendChild(meta);

        var actions = document.createElement('div');
        actions.className = 'material-actions';

        var insertBtn = document.createElement('button');
        insertBtn.type = 'button';
        insertBtn.className = 'ghost';
        insertBtn.textContent = '插入备注';
        insertBtn.addEventListener('click', function(event) {
          event.stopPropagation();
          insertMaterialRef(mat);
        });
        actions.appendChild(insertBtn);

        var editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'ghost';
        editBtn.textContent = '预览/改名';
        editBtn.addEventListener('click', function(event) {
          event.stopPropagation();
          openMaterialModal(mat);
        });
        actions.appendChild(editBtn);

        card.appendChild(actions);
        card.title = mat.path;
        grid.appendChild(card);
      });
    }

    loadMaterials().catch(function() {});
    setInterval(function() { loadMaterials().catch(function() {}); }, 10000);

  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/text2video"}:
            self._send_html(HTML)
            return
        if parsed.path == "/api/status":
            self._send_json(build_status_payload())
            return
        if parsed.path == "/api/save_config":
            self._send_json({"error": "Method Not Allowed"}, status=405)
            return
        if parsed.path == "/api/file":
            query = parse_qs(parsed.query)
            path_value = query.get("path", [""])[-1]
            file_path = Path(unquote(path_value))
            if not file_path.exists() or not file_path.is_file():
                self._send_json({"error": "文件不存在"}, status=404)
                return
            mime, _ = mimetypes.guess_type(str(file_path))
            content = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if parsed.path == "/api/uploads_list":
            query = parse_qs(parsed.query)
            requested_project_id = query.get("project_id", [""])[-1]
            active_project = set_active_project(requested_project_id) if requested_project_id else get_active_project()
            uploads = []
            roots = [project_upload_root(active_project["id"])]
            if active_project["name"] == "默认项目":
                roots.append(UPLOAD_DIR)
            for kind in ["image", "video", "audio"]:
                dirs = [root / kind for root in roots]
                files: list[Path] = []
                for dir_path in dirs:
                    if dir_path.is_dir():
                        files.extend([f for f in dir_path.iterdir() if f.is_file()])
                for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
                    if f.name.startswith("."):
                        continue
                    uploads.append(build_upload_record(kind, f))
            self._send_json({"uploads": uploads, "project_id": active_project["id"]})
            return
        self._send_json({"error": "Not Found"}, status=404)
    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/upload":
                result = save_uploaded_files(self)
                self._send_json({"ok": True, **result})
                return

            payload = parse_body(self)
            if parsed.path == "/api/projects/create":
                project = create_project(str(payload.get("name") or "新项目"))
                projects = load_projects()
                if not any(item["id"] == project["id"] for item in projects):
                    projects.append(project)
                save_projects_index(projects)
                set_active_project(project["id"])
                self._send_json({"ok": True, "project": project, "projects": load_projects()})
                return
            if parsed.path == "/api/projects/select":
                project = set_active_project(str(payload.get("project_id") or "").strip())
                self._send_json({"ok": True, "project": project, "projects": load_projects()})
                return
            if parsed.path == "/api/projects/rename":
                project = rename_project(str(payload.get("project_id") or "").strip(), str(payload.get("name") or "").strip())
                self._send_json({"ok": True, "project": project, "projects": load_projects()})
                return
            if parsed.path == "/api/start":
                meta = start_queue(payload)
                self._send_json({"ok": True, "runner": meta})
                return
            if parsed.path == "/api/retry_task":
                result = retry_task(payload)
                self._send_json({"ok": True, **result})
                return
            if parsed.path == "/api/save_config":
                config = persist_runtime_form(payload)
                self._send_json({"ok": True, "config": config})
                return
            if parsed.path == "/api/rename_upload":
                result = rename_uploaded_file(payload)
                self._send_json({"ok": True, **result})
                return
            if parsed.path == "/api/build_multimodal":
                command = build_multimodal_command(payload)
                self._send_json({"ok": True, "command": command})
                return
            if parsed.path == "/api/build_text2video":
                command = build_text2video_command(payload)
                self._send_json({"ok": True, "command": command})
                return
            if parsed.path == "/api/stop":
                meta = stop_queue()
                self._send_json({"ok": True, "runner": meta})
                return
            if parsed.path == "/api/clear_execution_queue":
                result = clear_execution_queue()
                self._send_json({"ok": True, **result})
                return
            if parsed.path == "/api/save_queue":
                project_id = str(payload.get("project_id") or load_ui_config().get("active_project_id") or "").strip()
                active_project = set_active_project(project_id) if project_id else get_active_project()
                queue_file = project_queue_file(active_project["id"]).expanduser().resolve()
                ensure_dir(queue_file.parent)
                document = merge_existing_segment_status(active_project["id"], parse_queue_document(str(payload.get("queue_content", ""))))
                normalized = queue_document_to_text(document)
                queue_file.write_text(normalized, encoding="utf-8")
                self._send_json({"ok": True, "queue_file": str(queue_file), "project": active_project})
                return
            self._send_json({"error": "Not Found"}, status=404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def log_message(self, format: str, *args: Any) -> None:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dreamina 队列可视化页面")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    ensure_dir(APP_DIR)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Dreamina Queue UI running at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
