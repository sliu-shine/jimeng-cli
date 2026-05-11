#!/usr/bin/env python3
"""
爆款文案智能体 - 可视化界面
"""
import os
import sys
import json
import asyncio
import threading
import time
import re
import uuid
import subprocess
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "douyin"))

import gradio as gr
from viral_agent import knowledge_base as kb
from viral_agent.analyzer import _call_claude, analyze_script, engagement_level
from viral_agent.agent import format_generation_report, generate_detailed
from viral_agent.ai_providers import apply_provider, get_provider, masked_key, provider_choices
from viral_agent.seedance_prompt_builder import build_seedance_outputs, get_channel_choices, get_default_channel_id
from viral_agent.sora_prompt_builder import build_sora_outputs
from viral_agent.text_segmenter import (
    segment_by_sentences,
    format_segments_for_display,
    segments_to_table_data,
    validate_segments,
)
from viral_agent.prompt_agent import (
    generate_video_prompts,
    format_prompts_for_display,
    prompts_to_table_data,
    export_to_seedance_queue,
)
from douyin.douyin_downloader.pipeline import DouyinViralPipeline
from douyin.douyin_downloader.transcriber import extract_transcript
from scripts.claude_client import ClaudeClient

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / ".webui"
DOUYIN_ACCOUNTS_FILE = APP_DIR / "douyin_accounts.json"
GENERATED_SCRIPTS_FILE = APP_DIR / "generated_scripts.json"
GENERATED_SCRIPT_PROJECTS_DIR = APP_DIR / "generated-script-projects"
GENERATED_SCRIPTS_INDEX_FILE = APP_DIR / "generated_scripts_index.json"
WEB_QUEUE_FILE = APP_DIR / "web.queue.json"
PROJECTS_DIR = APP_DIR / "projects"
PROJECTS_INDEX_FILE = APP_DIR / "projects.json"
UI_CONFIG_FILE = APP_DIR / "ui-config.json"

# ── 环境变量（可在界面顶部覆盖）──────────────────────────
try:
    DEFAULT_PROVIDER = apply_provider(os.environ.get("AI_PROVIDER_DEFAULT"))
except Exception:
    DEFAULT_PROVIDER = None
DEFAULT_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://cc.codesome.ai")
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
DEFAULT_TRANSCRIBE_API_KEY = os.environ.get("YUNWU_API_KEY", "")
TRANSCRIBABLE_SUFFIXES = {".mp4", ".m4a", ".mp3", ".aac", ".wav"}

# ── 全局变量：Selenium 抖音采集任务状态 ──────────────────
selenium_task = {
    "is_running": False,
    "thread": None,
    "downloader": None,
    "accounts_status": [],
    "logs": [],
    "current_account": 0,
    "total_accounts": 0,
    "active_account_indices": [],
    "auto_clear_completed_done": False
}


def set_env(api_key: str, base_url: str, model: str = "", provider_id: str = ""):
    if provider_id:
        try:
            apply_provider(provider_id)
        except Exception:
            pass
    if api_key and api_key.strip() and "..." not in api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key.strip()
    if base_url and base_url.strip():
        os.environ["ANTHROPIC_BASE_URL"] = base_url.strip()
    if model and model.strip():
        os.environ["ANTHROPIC_MODEL"] = model.strip()
        os.environ["CLAUDE_MODEL"] = model.strip()


def select_ai_provider(provider_id: str):
    provider = apply_provider(provider_id)
    return masked_key(provider.api_key), provider.base_url, provider.model, f"✅ 已切换到 {provider.name} · {provider.model}"


def refresh_ai_providers():
    choices = provider_choices()
    provider = get_provider(os.environ.get("AI_PROVIDER_SELECTED") or os.environ.get("AI_PROVIDER_DEFAULT"))
    return (
        gr.update(choices=choices, value=provider.id),
        masked_key(provider.api_key),
        provider.base_url,
        provider.model,
        f"已发现 {len(choices)} 个 AI Provider。",
    )


def test_ai_provider(provider_id: str):
    try:
        provider = apply_provider(provider_id)
        client = ClaudeClient(provider_id=provider.id)
        result = client.create_message(
            model=provider.model,
            messages=[{"role": "user", "content": "只回复 OK"}],
            max_tokens=20,
            temperature=0,
        )
        text = result.get("content", [{}])[0].get("text", "").strip()
        return f"✅ {provider.name} 可用：{text or 'OK'}"
    except Exception as exc:
        return f"❌ Provider 测试失败：{exc}"


def extract_video_id_from_media(media_path: Path, metadata: dict | None = None) -> str:
    metadata = metadata or {}
    for key in ("video_id", "videoId", "aweme_id"):
        if metadata.get(key):
            return str(metadata[key])

    import re
    matches = re.findall(r"(?<!\d)(\d{10,})(?!\d)", media_path.stem)
    return matches[-1] if matches else media_path.stem


def read_media_metadata(media_path: Path) -> dict:
    metadata_file = media_path.with_suffix(".json")
    if not metadata_file.exists():
        return {}
    try:
        with open(metadata_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def transcript_candidates(media_path: Path) -> list[Path]:
    return [
        transcript_path(media_path),
        media_path.with_suffix(".transcription.json"),
        media_path.with_suffix(".transcript.json"),
        media_path.with_suffix(".txt"),
    ]


def transcript_path(media_path: Path) -> Path:
    return media_path.parent / "transcript.json"


def cleaned_transcript_path(media_path: Path) -> Path:
    return media_path.parent / "cleaned.json"


def quality_report_path(media_path: Path) -> Path:
    return media_path.parent / "quality.json"


def legacy_cleaned_transcript_path(media_path: Path) -> Path:
    return media_path.with_suffix(".cleaned.json")


def legacy_quality_report_path(media_path: Path) -> Path:
    return media_path.with_suffix(".quality.json")


def read_transcript_text(media_path: Path) -> tuple[str, Path | None]:
    for transcript_file in transcript_candidates(media_path):
        if not transcript_file.exists():
            continue
        try:
            if transcript_file.suffix == ".txt":
                text = transcript_file.read_text(encoding="utf-8").strip()
            else:
                data = json.loads(transcript_file.read_text(encoding="utf-8"))
                text = str(data.get("text") or data.get("transcript") or "").strip()
                if not text and isinstance(data.get("segments"), list):
                    text = "".join(
                        str(segment.get("text") or "")
                        for segment in data["segments"]
                        if isinstance(segment, dict)
                    ).strip()
        except (OSError, json.JSONDecodeError):
            continue
        if text:
            return text, transcript_file
    return "", None


def read_cleaned_transcript_text(media_path: Path) -> tuple[str, Path | None, dict]:
    clean_file = next(
        (path for path in [cleaned_transcript_path(media_path), legacy_cleaned_transcript_path(media_path)] if path.exists()),
        None,
    )
    if not clean_file:
        return "", None, {}
    try:
        data = json.loads(clean_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", None, {}
    if not isinstance(data, dict):
        return "", None, {}
    text = str(data.get("cleaned_text") or data.get("text") or "").strip()
    return (text, clean_file, data) if text else ("", None, data)


def read_import_transcript_text(media_path: Path) -> tuple[str, Path | None, dict]:
    cleaned_text, cleaned_file, cleaned_data = read_cleaned_transcript_text(media_path)
    if cleaned_text and cleaned_file:
        return cleaned_text, cleaned_file, cleaned_data
    raw_text, raw_file = read_transcript_text(media_path)
    return raw_text, raw_file, {}


def load_quality_report(media_path: Path) -> dict:
    path = next(
        (item for item in [quality_report_path(media_path), legacy_quality_report_path(media_path)] if item.exists()),
        None,
    )
    if not path:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def clean_status_for_media(media_path: Path) -> tuple[str, dict]:
    quality = load_quality_report(media_path)
    cleaned_text, _, cleaned_data = read_cleaned_transcript_text(media_path)
    report = {**quality, **cleaned_data}
    if report.get("needs_review") or report.get("abnormal"):
        score = report.get("quality_score", "")
        return f"⚠️ 异常{f'({score})' if score != '' else ''}", report
    if cleaned_text:
        score = report.get("quality_score", "")
        return f"✅ 已清洗{f'({score})' if score != '' else ''}", report
    return "🧹 待清洗", report


def split_tags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lstrip("#") for item in value if str(item).strip()]
    return [tag.strip().lstrip("#") for tag in re.split(r"[,，#\s]+", str(value or "")) if tag.strip()]


def source_account_from_media_path(media_path: Path, root: Path) -> str:
    try:
        rel = media_path.resolve().relative_to(root.resolve())
    except ValueError:
        return ""
    return rel.parts[0] if len(rel.parts) > 1 else ""


def infer_channel(title: str, tags: list[str], account: str) -> str:
    text = " ".join([title, account, *tags])
    if any(word in text for word in ["训练", "训犬", "边界", "纠正", "规矩", "护官"]):
        return "训犬干货"
    if any(word in text for word in ["心理", "行为", "为什么", "原因", "冷知识", "科普", "科学养狗", "经验分享", "宇宙"]):
        return "宠物科普"
    if any(word in text for word in ["陪伴", "一生", "爱", "治愈", "情绪", "报恩"]):
        return "情绪陪伴"
    if any(word in text for word in ["猫", "英短", "蓝猫", "布偶"]):
        return "猫咪知识"
    if any(word in text for word in ["第", "犬", "动物解说", "品种"]):
        return "动物解说"
    return "抖音短视频"


def resolve_media_root(video_dir: str) -> Path:
    video_path = Path(video_dir or "./douyin_videos")
    if not video_path.is_absolute():
        video_path = (ROOT / video_path).resolve()
    return video_path


def dataframe_rows(dataframe):
    """Normalize Gradio Dataframe values across pandas/list return shapes."""
    if dataframe is None:
        return []
    if hasattr(dataframe, "values"):
        return dataframe.values.tolist()
    return dataframe


def scan_local_videos_with_stats(video_dir: str, status_filter: str = "全部", folder_filter: str = "全部"):
    """扫描本地视频，并同步返回最新知识库统计，避免顶部计数停留在旧值。"""
    video_list, status_msg = scan_local_videos(video_dir, status_filter, folder_filter)
    return video_list, status_msg, kb.get_stats()


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        content = path.read_text(encoding="utf-8").strip()
        return json.loads(content) if content else default
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, payload) -> None:
    ensure_app_dir()
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_web_projects() -> list[dict]:
    index = load_json(PROJECTS_INDEX_FILE, {})
    projects = index.get("projects") if isinstance(index, dict) else None
    if isinstance(projects, list) and projects:
        return [item for item in projects if isinstance(item, dict)]

    found = []
    if PROJECTS_DIR.exists():
        for project_file in sorted(PROJECTS_DIR.glob("*/project.json")):
            project = load_json(project_file, {})
            if isinstance(project, dict) and project.get("id"):
                found.append(project)
    return found


def project_choices() -> list[tuple[str, str]]:
    choices = []
    for project in load_web_projects():
        label = f"{project.get('name') or project.get('id')} · {project.get('id')}"
        choices.append((label, str(project.get("id"))))
    return choices


def active_project_id() -> str:
    config = load_json(UI_CONFIG_FILE, {})
    active_id = str(config.get("active_project_id") or "").strip() if isinstance(config, dict) else ""
    project_ids = [str(item.get("id")) for item in load_web_projects()]
    if active_id in project_ids:
        return active_id
    return project_ids[0] if project_ids else ""


def project_by_id(project_id: str) -> dict | None:
    for project in load_web_projects():
        if str(project.get("id")) == str(project_id):
            return project
    return None


def project_queue_path(project_id: str) -> Path:
    project = project_by_id(project_id)
    if not project:
        raise ValueError(f"找不到项目：{project_id}")
    folder = str(project.get("folder") or "")
    if not folder:
        raise ValueError(f"项目缺少 folder：{project_id}")
    return PROJECTS_DIR / folder / "queue.json"


def sanitize_project_name(name: str) -> str:
    value = re.sub(r"[^\w.\-]+", "-", str(name or ""), flags=re.UNICODE).strip("-")
    return value or "Seedance项目"


def default_seedance_project_name(script: str) -> str:
    text = re.sub(r"\s+", "", str(script or ""))
    text = re.sub(r"[【】#：:，,。！？!?（）()\"'“”‘’、；;]+", "", text)
    base = text[:16] or "猫狗动画分镜"
    return f"{base}-{datetime.now().strftime('%m%d-%H%M')}"


def create_web_project(name: str, description: str = "") -> dict:
    ensure_app_dir()
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    project_id = f"project-{uuid.uuid4().hex[:10]}"
    clean_name = str(name or "").strip() or "Seedance动画分镜"
    folder = f"{sanitize_project_name(clean_name)}-{project_id.split('project-', 1)[1]}"
    project = {
        "id": project_id,
        "name": clean_name,
        "folder": folder,
        "description": str(description or ""),
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    project_dir = PROJECTS_DIR / folder
    (project_dir / "uploads").mkdir(parents=True, exist_ok=True)
    save_json(project_dir / "project.json", project)
    save_json(project_dir / "queue.json", {"version": 1, "segments": []})

    projects = [item for item in load_web_projects() if str(item.get("id")) != project_id]
    projects.append(project)
    save_json(PROJECTS_INDEX_FILE, {"version": 1, "projects": projects})

    config = load_json(UI_CONFIG_FILE, {})
    if not isinstance(config, dict):
        config = {}
    config["active_project_id"] = project_id
    save_json(UI_CONFIG_FILE, config)
    return project


def load_generated_scripts() -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()

    if GENERATED_SCRIPT_PROJECTS_DIR.exists():
        for script_file in sorted(GENERATED_SCRIPT_PROJECTS_DIR.glob("*/generated_scripts.json")):
            try:
                data = json.loads(script_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                record_id = str(item.get("id") or "")
                if record_id and record_id in seen:
                    continue
                item = dict(item)
                item["_storage_path"] = str(script_file)
                item["_project_dir"] = str(script_file.parent)
                item["_legacy_global"] = False
                if record_id:
                    seen.add(record_id)
                records.append(item)

    if GENERATED_SCRIPTS_FILE.exists():
        try:
            data = json.loads(GENERATED_SCRIPTS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                record_id = str(item.get("id") or "")
                if record_id and record_id in seen:
                    continue
                item = dict(item)
                item["_storage_path"] = str(GENERATED_SCRIPTS_FILE)
                item["_project_dir"] = ""
                item["_legacy_global"] = True
                if record_id:
                    seen.add(record_id)
                records.append(item)

    return sorted(records, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def save_generated_scripts(records: list[dict]) -> None:
    ensure_app_dir()
    tmp = GENERATED_SCRIPTS_FILE.with_name(f".{GENERATED_SCRIPTS_FILE.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(GENERATED_SCRIPTS_FILE)


def generated_script_project_folder_name(topic: str, created_at: datetime, record_id: str) -> str:
    date_part = created_at.strftime("%Y-%m-%d_%H-%M-%S")
    clean_topic = sanitize_project_name(str(topic or "").strip())[:36] or "未命名文案"
    return f"{date_part}-{clean_topic}-{record_id[:8]}"


def save_generated_scripts_index(record: dict) -> None:
    index = load_json(GENERATED_SCRIPTS_INDEX_FILE, {})
    items = index.get("records") if isinstance(index, dict) else []
    if not isinstance(items, list):
        items = []
    items = [item for item in items if str(item.get("id")) != str(record.get("id"))]
    items.insert(0, {
        "id": record.get("id"),
        "created_at": record.get("created_at"),
        "topic": record.get("topic"),
        "niche": record.get("niche"),
        "project_name": record.get("project_name"),
        "project_folder": record.get("project_folder"),
        "script_file": record.get("script_file"),
    })
    save_json(GENERATED_SCRIPTS_INDEX_FILE, {"version": 1, "records": items[:500]})


def generated_script_choices() -> list[tuple[str, str]]:
    choices = []
    for item in load_generated_scripts():
        created_at = str(item.get("created_at", ""))[:16].replace("T", " ")
        topic = str(item.get("topic") or "未命名主题").strip()
        niche = str(item.get("niche") or "未填赛道").strip()
        prefix = "旧全局 · " if item.get("_legacy_global") else ""
        project_name = str(item.get("project_name") or "").strip()
        project_label = f" · {project_name[:18]}" if project_name else ""
        label = f"{prefix}{created_at} · {topic[:28]} · {niche}{project_label}"
        choices.append((label, str(item.get("id"))))
    return choices


def save_generated_script_record(
    topic: str,
    niche: str,
    requirements: str,
    versions: int,
    content: str,
    metadata: dict | None = None,
    versions_list: list | None = None,
) -> dict:
    metadata = metadata or {}
    references = metadata.get("references") or []
    created_at = datetime.now()
    record_id = uuid.uuid4().hex
    project_name = str(topic or "").strip()[:48] or "未命名文案项目"
    project_folder = generated_script_project_folder_name(project_name, created_at, record_id)
    project_dir = GENERATED_SCRIPT_PROJECTS_DIR / project_folder
    script_file = project_dir / "generated_scripts.json"
    record = {
        "id": record_id,
        "created_at": created_at.isoformat(timespec="seconds"),
        "project_name": project_name,
        "project_folder": project_folder,
        "project_dir": str(project_dir),
        "script_file": str(script_file),
        "topic": str(topic or "").strip(),
        "niche": str(niche or "").strip(),
        "requirements": str(requirements or "").strip(),
        "versions": int(versions or 1),
        "content": str(content or "").strip(),
        "versions_list": versions_list or [],
        "reference_ids": [str(item.get("video_id") or "") for item in references if item.get("video_id")],
        "reference_summary": [
            {
                "rank": item.get("rank"),
                "video_id": item.get("video_id"),
                "source": item.get("source"),
                "likes": item.get("likes"),
                "similarity": item.get("similarity"),
                "rank_score": item.get("rank_score"),
                "hook_type": item.get("hook_type"),
                "structure": item.get("structure"),
            }
            for item in references
        ],
        "strategy": metadata.get("strategy") or {},
        "metadata": metadata,
    }
    project_dir.mkdir(parents=True, exist_ok=True)
    save_json(script_file, [record])
    save_generated_scripts_index(record)
    return record


def refresh_generated_scripts():
    choices = generated_script_choices()
    value = choices[0][1] if choices else None
    status = f"已保存 {len(choices)} 条文案。" if choices else "还没有保存过生成文案。"
    return gr.update(choices=choices, value=value), status


def switch_version(versions_list: list, index: int):
    """切换到指定版本（index 从1开始）"""
    if not versions_list or index < 1 or index > len(versions_list):
        return (
            gr.update(),
            f"版本{index} 不存在（共 {len(versions_list)} 个版本）",
            "", "", "", "", "",
        )
    item = versions_list[index - 1]
    content = str(item.get("content") or "").strip()
    score = item.get("score") or 0
    passed = "✅ 通过" if item.get("passed") else "⚠️ 需优化"
    title = str(item.get("title") or "")
    description = str(item.get("description") or "")
    tags = " ".join([f"#{tag}" for tag in item.get("tags") or []])
    cover_image = str(item.get("cover_image") or "")
    cover_text = str(item.get("cover_text") or "")
    return (
        content,
        f"当前：版本{index} · {score}分 · {passed}",
        title,
        description,
        tags,
        cover_image,
        cover_text,
    )


def load_saved_generated_script(script_id: str):
    for item in load_generated_scripts():
        if str(item.get("id")) == str(script_id):
            versions_list = item.get("versions_list") or []
            if versions_list:
                first_version = versions_list[0]
                script_text = str(first_version.get("content") or "").strip()
                title = str(first_version.get("title") or "")
                description = str(first_version.get("description") or "")
                tags = " ".join([f"#{tag}" for tag in first_version.get("tags") or []])
                cover_image = str(first_version.get("cover_image") or "")
                cover_text = str(first_version.get("cover_text") or "")
            else:
                script_text = str(item.get("content") or "").strip()
                title = description = tags = cover_image = cover_text = ""
            display_content = str(item.get("content") or "") + format_generation_report(item.get("metadata"))
            status = f"已载入：{item.get('topic') or '未命名主题'}"
            if item.get("_storage_path"):
                status += f"\n\n文件：`{item.get('_storage_path')}`"
            n = len(versions_list)
            ver_status = f"共 {n} 个版本，当前：版本1" if n > 0 else "（旧格式，无版本拆分）"
            return (
                display_content,
                script_text,
                item.get("topic", ""),
                item.get("niche", ""),
                item.get("requirements", ""),
                int(item.get("versions") or 1),
                status,
                versions_list,
                ver_status,
                title,
                description,
                tags,
                cover_image,
                cover_text,
            )
    return "", "", gr.update(), gr.update(), gr.update(), gr.update(), "未找到这条保存记录。", [], "", "", "", "", "", ""


def delete_saved_generated_script(script_id: str):
    deleted = False
    for item in load_generated_scripts():
        if str(item.get("id")) != str(script_id):
            continue
        storage_path = Path(str(item.get("_storage_path") or ""))
        if item.get("_legacy_global"):
            legacy_records = []
            if GENERATED_SCRIPTS_FILE.exists():
                try:
                    data = json.loads(GENERATED_SCRIPTS_FILE.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = []
                if isinstance(data, list):
                    legacy_records = [
                        row for row in data
                        if isinstance(row, dict) and str(row.get("id")) != str(script_id)
                    ]
            save_generated_scripts(legacy_records)
            deleted = True
        elif storage_path.name == "generated_scripts.json" and storage_path.parent.exists():
            shutil.rmtree(storage_path.parent)
            index = load_json(GENERATED_SCRIPTS_INDEX_FILE, {})
            items = index.get("records") if isinstance(index, dict) else []
            if isinstance(items, list):
                items = [row for row in items if str(row.get("id")) != str(script_id)]
                save_json(GENERATED_SCRIPTS_INDEX_FILE, {"version": 1, "records": items})
            deleted = True
        break
    choices = generated_script_choices()
    value = choices[0][1] if choices else None
    status = "已删除。" if deleted else "未找到可删除的记录。"
    return gr.update(choices=choices, value=value), "", "", status


def _first_generated_version(text: str) -> str:
    body = str(text or "").strip()
    match = re.search(r"(【版本\s*1[^】]*】.*?)(?=【版本\s*2|\Z)", body, flags=re.S)
    return match.group(1).strip() if match else body


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    sentence = sentence.strip()
    if len(sentence) <= max_chars:
        return [sentence] if sentence else []
    parts = re.split(r"(?<=[，,；;、])", sentence)
    chunks: list[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        if current and len(current) + len(part) > max_chars:
            chunks.append(current.strip())
            current = part
        else:
            current += part
    if current.strip():
        chunks.append(current.strip())
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final.append(chunk)
        else:
            final.extend(chunk[i:i + max_chars] for i in range(0, len(chunk), max_chars))
    return [item.strip() for item in final if item.strip()]


def split_script_into_segments(script: str, max_seconds: int = 15) -> list[dict]:
    text = _first_generated_version(script)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("参考：") or stripped.startswith("（参考："):
            continue
        if re.match(r"^#+\s*", stripped) or re.match(r"^【版本\s*\d+", stripped):
            continue
        lines.append(stripped)
    normalized = re.sub(r"\s+", " ", "".join(lines)).strip()
    if not normalized:
        return []

    max_chars = max(35, int(max_seconds) * 4)
    sentences = re.split(r"(?<=[。！？!?])", normalized)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for part in _split_long_sentence(sentence, max_chars):
            if current and len(current) + len(part) > max_chars:
                pieces.append(current.strip())
                current = part
            else:
                current += part
    if current.strip():
        pieces.append(current.strip())

    segments = []
    for index, narration in enumerate(pieces, 1):
        seconds = min(int(max_seconds), max(5, round(len(narration) / 4)))
        segments.append({"index": index, "duration": seconds, "narration": narration})
    return segments


def build_dreamina_prompts(script: str, max_seconds: int, model_version: str, channel_id: str):
    return build_seedance_outputs(script, model_version=model_version or "seedance2.0fast", channel_id=channel_id or None)


def build_sora_prompts(script: str):
    """构建 Sora 提示词"""
    return build_sora_outputs(script)


def save_sora_queue_to_file(queue_json: str, file_path: str) -> str:
    """保存 Sora 队列到文件"""
    if not queue_json or not queue_json.strip():
        return "❌ 队列 JSON 为空，请先点击「拆分为 Sora 2.0 视频提示词」。"

    if not file_path or not file_path.strip():
        return "❌ 请输入保存路径。"

    try:
        # 验证 JSON 格式
        json.loads(queue_json)

        # 保存文件
        output_path = Path(file_path.strip())
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(queue_json)

        return f"✅ 队列已保存到: {output_path}\n\n执行命令：\n```bash\npython sora_queue.py {output_path}\n```"

    except json.JSONDecodeError as e:
        return f"❌ JSON 格式错误: {e}"
    except Exception as e:
        return f"❌ 保存失败: {e}"


def refresh_project_choices():
    choices = project_choices()
    value = active_project_id() or (choices[0][1] if choices else None)
    status = f"已发现 {len(choices)} 个项目。" if choices else "未发现 web_app.py 项目。"
    return gr.update(choices=choices, value=value), status


def parse_seedance_queue_payload(queue_json: str):
    content = str(queue_json or "").strip()
    if not content:
        return None, "❌ 队列 JSON 草稿为空，请先点击「拆分为 Seedance 2.0 动画分镜提示词」。"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return None, f"❌ 队列 JSON 格式错误：{exc}"

    new_segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(new_segments, list) or not new_segments:
        return None, "❌ 没有可导入的分镜片段。"
    return new_segments, None


def import_seedance_queue_to_web_queue(queue_json: str, project_id: str):
    new_segments, error = parse_seedance_queue_payload(queue_json)
    if error:
        return error

    project = project_by_id(project_id or active_project_id())
    if not project:
        return "❌ 请先选择要导入的项目。"

    try:
        queue_path = project_queue_path(str(project["id"]))
    except ValueError as exc:
        return f"❌ {exc}"

    current = load_json(queue_path, {"version": 1, "segments": []})
    if not isinstance(current, dict):
        current = {"version": 1, "segments": []}
    current_segments = current.get("segments")
    if not isinstance(current_segments, list):
        current_segments = []

    imported = []
    for index, segment in enumerate(new_segments, 1):
        if not isinstance(segment, dict):
            continue
        item = dict(segment)
        item["id"] = f"{item.get('id') or 'seedance'}-{uuid.uuid4().hex[:8]}"
        item["name"] = str(item.get("name") or f"Seedance动画片段{index:02d}")
        item["mode"] = str(item.get("mode") or "text2video")
        item["ratio"] = str(item.get("ratio") or "16:9")
        item["model_version"] = str(item.get("model_version") or "seedance2.0fast")
        item.setdefault("images", [])
        item.setdefault("videos", [])
        item.setdefault("audios", [])
        item.setdefault("transition_prompts", [])
        imported.append(item)

    if not imported:
        return "❌ 队列里没有有效片段。"

    current["version"] = int(current.get("version") or 1)
    current["segments"] = current_segments + imported
    save_json(queue_path, current)
    project_name = project.get("name") or project.get("id")
    return f"✅ 已导入 {len(imported)} 个文生视频片段到项目「{project_name}」：{queue_path}"


def create_project_and_import_seedance_queue(queue_json: str, project_name: str, script: str):
    _, error = parse_seedance_queue_payload(queue_json)
    if error:
        return gr.update(choices=project_choices(), value=active_project_id()), error

    name = str(project_name or "").strip() or default_seedance_project_name(script)
    project = create_web_project(name, description="Seedance 2.0 猫狗科普动画分镜自动创建")
    status = import_seedance_queue_to_web_queue(queue_json, str(project["id"]))
    choices = project_choices()
    return gr.update(choices=choices, value=project["id"]), f"{status}\n\n已新建独立项目「{project['name']}」。"


# ── 知识库导入辅助 ────────────────────────────────────────
def learn_single(script: str, likes: int, niche: str, api_key: str, base_url: str):
    set_env(api_key, base_url)
    if not script.strip():
        return "❌ 请输入文案内容", kb.get_stats()

    video_id = f"manual_{hash(script) % 100000:05d}"
    yield f"⏳ 正在分析文案...", kb.get_stats()

    analysis = analyze_script(script, likes=int(likes), niche=niche)

    kb.add_script(
        video_id=video_id,
        script=script,
        analysis=analysis,
        metadata={"likes": int(likes), "niche": niche, "platform": "manual"},
    )

    result = f"✅ 分析完成，已存入知识库！\n\n"
    result += f"**钩子类型：** {analysis.get('hook_type', '')}\n\n"
    result += f"**开头钩子：** {analysis.get('hook', '')}\n\n"
    result += f"**钩子公式：** `{analysis.get('hook_formula', '')}`\n\n"
    result += f"**内容结构：** {analysis.get('structure', '')}\n\n"
    result += f"**爆火原因：** {analysis.get('why_viral', '')}\n\n"
    result += f"**改写模板：**\n{analysis.get('rewrite_template', '')}"

    yield result, kb.get_stats()


def learn_batch(json_text: str, niche: str, api_key: str, base_url: str):
    set_env(api_key, base_url)
    try:
        scripts = json.loads(json_text)
    except json.JSONDecodeError as e:
        yield f"❌ JSON 格式错误: {e}", kb.get_stats()
        return

    total = len(scripts)
    logs = []
    for i, item in enumerate(scripts):
        script = item.get("script", "")
        video_id = item.get("video_id", f"batch_{i:04d}")
        likes = item.get("likes", 0)
        item_niche = item.get("niche", niche)

        logs.append(f"[{i+1}/{total}] 分析 {video_id}...")
        yield "\n".join(logs), kb.get_stats()

        analysis = analyze_script(script, likes=likes, niche=item_niche)
        kb.add_script(video_id, script, analysis, {"likes": likes, "niche": item_niche, "platform": "batch"})
        logs[-1] += f" ✅ 点赞{likes:,} | {analysis.get('hook_type', '')}"
        yield "\n".join(logs), kb.get_stats()

    logs.append(f"\n🎉 全部完成！{kb.get_stats()}")
    yield "\n".join(logs), kb.get_stats()


# ── 检索知识库 ────────────────────────────────────────────
def search_kb(query: str, niche: str, n: int):
    results = kb.search_scripts(query, n=int(n), niche=niche or None)
    if not results:
        return "知识库为空或无相关内容，请先导入爆款文案。"

    out = f"找到 **{len(results)}** 条相关爆款：\n\n"
    for i, s in enumerate(results, 1):
        out += f"---\n### 爆款 {i}  ·  点赞 {s['likes']:,}  ·  相似度 {s['similarity']:.2f}\n\n"
        out += f"**钩子类型：** {s['hook_type']}\n\n"
        out += f"**钩子公式：** `{s['analysis'].get('hook_formula', '')}`\n\n"
        out += f"**结构：** {s['structure']}\n\n"
        out += f"**爆火原因：** {s['why_viral']}\n\n"
        out += f"**原文：**\n> {s['script'][:200]}...\n\n"
    return out


def show_stats(niche: str):
    stats = kb.get_all_patterns(niche=niche or None)
    if stats["count"] == 0:
        return "知识库为空，请先导入爆款文案。"

    out = f"## 📊 知识库统计（共 {stats['count']} 条）\n\n"
    out += "### 钩子类型分布\n"
    for k, v in sorted(stats["hook_types"].items(), key=lambda x: -x[1]):
        bar = "█" * v
        out += f"- **{k}** {bar} {v}条\n"
    out += f"\n### 高频爆款元素\n"
    out += "  ".join([f"`{e}`" for e in stats["top_viral_elements"][:15]])
    out += "\n\n### 典型文案结构\n"
    for s in stats["sample_structures"][:3]:
        out += f"- {s}\n"
    return out


# ── 生成文案 ──────────────────────────────────────────────
def run_generate(
    topic: str,
    niche: str,
    requirements: str,
    versions: int,
    api_key: str,
    base_url: str,
    model: str,
    provider_id: str,
):
    set_env(api_key, base_url, model, provider_id)
    if not topic.strip():
        yield "❌ 请输入视频主题", gr.update(), "未保存：缺少视频主题。", gr.update(), gr.update(), [], ""
        return
    yield "⏳ 智能体运行中，正在检索爆款知识库、生成文案并逐版本 AI 质检...", gr.update(), "", gr.update(), gr.update(), [], ""
    generation = generate_detailed(topic=topic, niche=niche, requirements=requirements, versions=int(versions))
    result = generation["content"]
    metadata = generation.get("metadata") or {}
    report_markdown = generation.get("report_markdown") or format_generation_report(metadata)
    display_result = result + report_markdown
    vlist = generation.get("versions_list") or []
    record = save_generated_script_record(topic, niche, requirements, int(versions), result, metadata, vlist)
    status = f"✅ 已自动保存到 {record.get('script_file')} · ID {record['id'][:8]}"
    n = len(vlist)
    ver_status = f"共 {n} 个版本，当前：版本1" if n > 0 else ""
    yield (
        display_result,
        gr.update(choices=generated_script_choices(), value=record["id"]),
        status,
        _first_generated_version(result),
        "已自动载入最新生成文案，可直接拆分即梦提示词。",
        vlist,
        ver_status,
    )


# ── 旧版采集流水线辅助 ────────────────────────────────────
def run_douyin_pipeline(
    user_urls_text: str,
    max_per_user: int,
    min_likes: int,
    transcribe_method: str,
    whisper_model: str,
    auto_import: bool,
    niche: str,
    api_key: str,
    base_url: str
):
    """运行抖音采集流水线"""
    set_env(api_key, base_url)

    # 解析用户链接
    user_urls = [url.strip() for url in user_urls_text.strip().split('\n') if url.strip()]
    if not user_urls:
        yield "❌ 请输入至少一个抖音用户主页链接", kb.get_stats()
        return

    yield f"🚀 开始采集 {len(user_urls)} 个账号的爆款视频...\n", kb.get_stats()

    # 创建流水线
    pipeline = DouyinViralPipeline(
        output_dir="./douyin_analysis",
        min_likes=int(min_likes)
    )

    logs = []

    try:
        # 运行异步流水线
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        logs.append(f"📥 [1/3] 下载爆款视频（点赞数 ≥ {min_likes:,}）")
        yield "\n".join(logs), kb.get_stats()

        export_file = loop.run_until_complete(
            pipeline.run_full_pipeline(
                user_urls=user_urls,
                max_per_user=int(max_per_user),
                transcribe_method=transcribe_method,
                model_name=whisper_model
            )
        )

        logs.append(f"✅ 流水线完成！导出文件: {export_file}")
        yield "\n".join(logs), kb.get_stats()

        # 自动导入到知识库
        if auto_import:
            logs.append(f"\n📚 [额外步骤] 自动导入到知识库...")
            yield "\n".join(logs), kb.get_stats()

            with open(export_file, 'r', encoding='utf-8') as f:
                samples = json.load(f)

            imported = 0
            for i, sample in enumerate(samples):
                script = sample.get("text", "")
                metadata = sample.get("metadata", {})
                video_id = metadata.get("aweme_id", f"douyin_{i:04d}")
                likes = metadata.get("likes", 0)

                logs.append(f"  [{i+1}/{len(samples)}] 分析 {video_id}...")
                yield "\n".join(logs), kb.get_stats()

                analysis = analyze_script(script, likes=likes, niche=niche)
                kb.add_script(
                    video_id=video_id,
                    script=script,
                    analysis=analysis,
                    metadata={**metadata, "niche": niche, "platform": "douyin"}
                )
                imported += 1
                logs[-1] += f" ✅ 点赞{likes:,}"
                yield "\n".join(logs), kb.get_stats()

            logs.append(f"\n🎉 全部完成！共导入 {imported} 条爆款文案到知识库")
        else:
            logs.append(f"\n💡 提示：可以手动导入到知识库：")
            logs.append(f"   python -m viral_agent learn --from-file {export_file}")

        yield "\n".join(logs), kb.get_stats()

    except Exception as e:
        logs.append(f"\n❌ 错误: {str(e)}")
        yield "\n".join(logs), kb.get_stats()
    finally:
        loop.close()


# ── Tab: 转录本地视频 ──────────────────────────────────────
def media_folder_choices(video_dir: str):
    video_path = resolve_media_root(video_dir)
    if not video_path.exists():
        return ["全部"]

    folders = []
    for child in sorted(video_path.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir():
            continue
        has_media = any(
            path.is_file() and path.suffix.lower() in TRANSCRIBABLE_SUFFIXES
            for path in child.rglob("*")
        )
        if has_media:
            folders.append(child.name)
    return ["全部", *folders]


def refresh_media_folder_filter(video_dir: str):
    choices = media_folder_choices(video_dir)
    return gr.update(choices=choices, value="全部")


def scan_local_videos(video_dir: str, status_filter: str = "全部", folder_filter: str = "全部"):
    """扫描本地视频目录，返回视频列表和转录状态（递归扫描子目录）"""
    video_path = resolve_media_root(video_dir)
    if not video_path.exists():
        return [], f"❌ 目录不存在: {video_dir}"

    scan_root = video_path
    folder_filter = str(folder_filter or "全部")
    if folder_filter != "全部":
        candidate = video_path / folder_filter
        try:
            candidate.resolve().relative_to(video_path.resolve())
        except ValueError:
            return [], f"❌ 无效目录筛选: {folder_filter}"
        if not candidate.exists() or not candidate.is_dir():
            return [], f"❌ 筛选目录不存在: {folder_filter}"
        scan_root = candidate

    # 递归扫描所有可转录媒体文件
    video_files = [
        path
        for path in scan_root.rglob("*")
        if path.is_file() and path.suffix.lower() in TRANSCRIBABLE_SUFFIXES
    ]
    if not video_files:
        suffix = f" / {folder_filter}" if folder_filter != "全部" else ""
        return [], f"📁 目录中没有找到可转录媒体文件: {video_path}{suffix}"

    # 检查每个视频的转录状态
    video_list = []
    transcribed_count = 0
    untranscribed_count = 0
    imported_count = 0
    unimported_count = 0
    cleaned_count = 0
    abnormal_count = 0
    pending_clean_count = 0
    imported_video_ids = set()

    for video_file in sorted(video_files):
        metadata = read_media_metadata(video_file)
        video_id = extract_video_id_from_media(video_file, metadata)
        transcript_text, transcript_file = read_transcript_text(video_file)
        is_transcribed = bool(transcript_text and transcript_file)
        status = "✅ 已转录" if is_transcribed else "⏳ 未转录"
        clean_status, _ = clean_status_for_media(video_file)
        is_imported = kb.has_script(video_id) if is_transcribed else False
        import_status = "✅ 已入库" if is_imported else ("📥 未入库" if is_transcribed else "—")

        # 统计数量
        if is_transcribed:
            transcribed_count += 1
            if "异常" in clean_status:
                abnormal_count += 1
            elif "已清洗" in clean_status:
                cleaned_count += 1
            else:
                pending_clean_count += 1
            if is_imported:
                imported_count += 1
                imported_video_ids.add(video_id)
            else:
                unimported_count += 1
        else:
            untranscribed_count += 1

        # 根据筛选条件过滤
        if status_filter == "已转录" and not is_transcribed:
            continue
        elif status_filter == "未转录" and is_transcribed:
            continue
        elif status_filter == "未入库" and (not is_transcribed or is_imported):
            continue
        elif status_filter == "已入库" and not is_imported:
            continue
        elif status_filter == "待清洗" and (not is_transcribed or "待清洗" not in clean_status):
            continue
        elif status_filter == "已清洗" and "已清洗" not in clean_status:
            continue
        elif status_filter == "异常" and "异常" not in clean_status:
            continue

        # 获取文件大小
        size_mb = video_file.stat().st_size / (1024 * 1024)

        # 显示相对路径（更易读）
        rel_path = video_file.relative_to(video_path)

        # 返回列表格式，而不是字典
        video_list.append([
            False,  # 选择
            status,  # 状态
            clean_status,  # 清洗状态
            import_status,  # 入库状态
            str(rel_path),  # 文件名（相对路径，包含子目录）
            f"{size_mb:.1f}",  # 大小(MB)
            video_id,  # 视频 ID
            str(video_file)  # 完整路径（隐藏列，用于后续处理）
        ])

    total = len(video_files)
    shown = len(video_list)
    status_msg = (
        f"✅ 共 {total} 个媒体 | 已转录: {transcribed_count} | 未转录: {untranscribed_count} | "
        f"已清洗: {cleaned_count} | 待清洗: {pending_clean_count} | 异常: {abnormal_count} | "
        f"已入库文件: {imported_count} | 未入库文件: {unimported_count} | "
        f"知识库唯一视频: {len(imported_video_ids)}"
    )
    if folder_filter != "全部":
        status_msg += f" | 目录: {folder_filter}"
    if status_filter != "全部":
        status_msg += f" | 当前显示: {shown} 个（{status_filter}）"

    return video_list, status_msg


def transcribe_selected_videos(video_dir: str, dataframe, method: str, api_key: str):
    """转录选中的视频"""
    if dataframe is None or len(dataframe) == 0:
        yield "❌ 没有视频可转录", None
        return

    # 设置 API key
    if method == "yunwu" and api_key:
        os.environ["YUNWU_API_KEY"] = api_key
    elif method == "groq" and api_key:
        os.environ["GROQ_API_KEY"] = api_key

    # 获取选中的视频
    selected = [row for row in dataframe_rows(dataframe) if row and row[0]]  # row[0] 是"选择"列

    if not selected:
        yield "❌ 请至少选择一个视频", None
        return

    total = len(selected)
    logs = [f"🚀 开始转录 {total} 个视频（方式: {method}）\n"]
    yield "\n".join(logs), None

    success_count = 0
    skip_count = 0
    error_count = 0

    for i, row in enumerate(selected, 1):
        status = row[1]    # row[1] 是"状态"列
        filename = row[4]  # row[4] 是"文件名"列

        video_path = resolve_media_root(video_dir) / filename

        # 检查文件是否存在和完整性
        if not video_path.exists():
            logs.append(f"[{i}/{total}] ❌ {filename} - 文件不存在")
            error_count += 1
            yield "\n".join(logs), None
            continue

        # 检查文件大小（小于 1KB 可能是损坏文件）
        file_size = video_path.stat().st_size
        if file_size < 1024:
            logs.append(f"[{i}/{total}] ⚠️  {filename} - 文件损坏（仅 {file_size} 字节），跳过")
            skip_count += 1
            yield "\n".join(logs), None
            continue

        # 跳过已转录的视频
        if "已转录" in status:
            logs.append(f"[{i}/{total}] ⏭️  {filename} - 已转录，跳过")
            skip_count += 1
            yield "\n".join(logs), None
            continue

        logs.append(f"[{i}/{total}] 🎬 {filename} - 转录中...")
        yield "\n".join(logs), None

        try:
            # 执行转录
            result = extract_transcript(
                video_path=video_path,
                method=method,
                save_json=True,
                api_key=api_key if api_key else None
            )

            text_preview = result["text"][:100] + "..." if len(result["text"]) > 100 else result["text"]
            logs[-1] = f"[{i}/{total}] ✅ {filename} - 转录完成"
            logs.append(f"    预览: {text_preview}")
            success_count += 1

            # 更新视频 JSON 文件，添加转录标识
            video_json_path = video_path.with_suffix('.json')
            if video_json_path.exists():
                try:
                    with open(video_json_path, 'r', encoding='utf-8') as f:
                        video_info = json.load(f)

                    video_info['transcribed'] = True
                    video_info['transcribed_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    video_info['transcription_method'] = method

                    with open(video_json_path, 'w', encoding='utf-8') as f:
                        json.dump(video_info, f, ensure_ascii=False, indent=2)
                except Exception as json_err:
                    logs.append(f"    ⚠️  更新 JSON 文件失败: {str(json_err)}")

        except Exception as e:
            logs[-1] = f"[{i}/{total}] ❌ {filename} - 失败: {str(e)}"
            error_count += 1

        yield "\n".join(logs), None

    # 最终统计
    logs.append(f"\n{'='*60}")
    logs.append(f"🎉 转录完成！")
    logs.append(f"   ✅ 成功: {success_count} 个")
    logs.append(f"   ⏭️  跳过: {skip_count} 个")
    logs.append(f"   ❌ 失败: {error_count} 个")
    logs.append(f"{'='*60}")

    # 刷新视频列表
    updated_list, _ = scan_local_videos(video_dir)

    yield "\n".join(logs), updated_list


def _json_from_ai_text(text: str) -> dict:
    content = str(text or "").strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.lstrip().startswith("json"):
            content = content.lstrip()[4:]

    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        content = content[start:end + 1]

    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as first_error:
        candidates = [
            re.sub(r",(\s*[}\]])", r"\1", content),
            _escape_loose_quotes_in_json_strings(re.sub(r",(\s*[}\]])", r"\1", content)),
        ]
        for fixed in candidates:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                continue

        try:
            return _parse_clean_transcript_loose_json(content)
        except Exception:
            lines = content.splitlines() or [content]
            error_line = max(1, getattr(first_error, "lineno", 1))
            context_start = max(0, error_line - 3)
            context_end = min(len(lines), error_line + 2)
            context = "\n".join(
                f"{line_no + 1:3d}: {lines[line_no]}"
                for line_no in range(context_start, context_end)
            )
            raise ValueError(
                f"AI 返回的 JSON 解析失败：第 {first_error.lineno} 行第 {first_error.colno} 列，"
                f"{first_error.msg}\n上下文:\n{context}"
            ) from first_error


def _escape_loose_quotes_in_json_strings(text: str) -> str:
    """Escape AI-produced bare quotes inside JSON string values."""
    result: list[str] = []
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if char != '"' or escaped:
            result.append(char)
            escaped = (char == "\\" and not escaped)
            if char != "\\":
                escaped = False
            continue

        if not in_string:
            in_string = True
            result.append(char)
            escaped = False
            continue

        next_non_space = ""
        for next_char in text[index + 1:]:
            if not next_char.isspace():
                next_non_space = next_char
                break

        if next_non_space in {":", ",", "}", "]"}:
            in_string = False
            result.append(char)
        else:
            result.append('\\"')
        escaped = False

    return "".join(result)


def _loose_json_field(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*', text)
    if not match:
        return None
    index = match.end()
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != '"':
        return None

    start = index + 1
    index = start
    while index < len(text):
        if text[index] == '"' and (index == 0 or text[index - 1] != "\\"):
            probe = index + 1
            while probe < len(text) and text[probe].isspace():
                probe += 1
            if probe >= len(text) or text[probe] in {",", "}"}:
                return text[start:index].replace('\\"', '"')
        index += 1
    return None


def _loose_json_int(text: str, key: str, default: int = 0) -> int:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(\d+)', text)
    return int(match.group(1)) if match else default


def _loose_json_bool(text: str, key: str, default: bool = False) -> bool:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(true|false)', text, flags=re.IGNORECASE)
    if not match:
        return default
    return match.group(1).lower() == "true"


def _loose_json_string_list(text: str, key: str) -> list[str]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
    if not match:
        return []
    values = re.findall(r'"((?:\\"|[^"])*)"', match.group(1))
    return [value.replace('\\"', '"') for value in values]


def _parse_clean_transcript_loose_json(text: str) -> dict:
    cleaned_text = _loose_json_field(text, "cleaned_text")
    if not cleaned_text:
        raise ValueError("missing cleaned_text")
    return {
        "cleaned_text": cleaned_text,
        "quality_score": _loose_json_int(text, "quality_score"),
        "match_score": _loose_json_int(text, "match_score"),
        "needs_review": _loose_json_bool(text, "needs_review"),
        "issues": _loose_json_string_list(text, "issues"),
        "corrections": [],
        "summary": _loose_json_field(text, "summary") or "",
    }


def _clean_transcript_with_ai(
    transcript: str,
    title: str,
    tags: list[str],
    source_account: str,
    likes: int,
) -> dict:
    prompt = f"""你是短视频中文口播稿校对助手，任务是把 ASR 逐字稿清洗成可用于爆款文案知识库分析的标准文案。

要求：
1. 只修正常见语音识别错字、同音错字、断句和标点，不要凭空添加新观点。
2. 如果原始转录和标题/标签明显不匹配，要标记 needs_review=true，不要强行改写。
3. 宠物领域常见词要优先纠正，例如：遛弯、凑过来、嫌弃、撒娇、贴贴、小型犬、认知、同类、任职/认知等按上下文判断。
4. 输出文本要保留短视频口播感，适合后续分析钩子、结构、情绪和观点。
5. JSON 字符串内不要使用未转义英文双引号；需要引用原话时优先使用中文引号“”。

【样本信息】
标题：{title}
账号：{source_account or "未知"}
点赞：{likes}
标签：{"、".join(tags) if tags else "无"}

【原始 ASR 转录】
{transcript}

请只输出 JSON：
{{
  "cleaned_text": "清洗后的完整文案",
  "quality_score": 0到100的整数,
  "match_score": 0到100的整数，表示清洗稿与标题/标签是否匹配,
  "needs_review": true或false,
  "issues": ["发现的问题，如同音错字较多/疑似音频不匹配/文本过短"],
  "corrections": [{{"from": "原词", "to": "修正词", "reason": "原因"}}],
  "summary": "一句话说明清洗结果"
}}"""
    result = _json_from_ai_text(_call_claude(prompt))
    cleaned_text = str(result.get("cleaned_text") or "").strip()
    quality_score = int(result.get("quality_score", 0) or 0)
    match_score = int(result.get("match_score", 0) or 0)
    result["cleaned_text"] = cleaned_text
    result["quality_score"] = max(0, min(100, quality_score))
    result["match_score"] = max(0, min(100, match_score))
    result["needs_review"] = bool(result.get("needs_review")) or quality_score < 60 or match_score < 50 or len(cleaned_text) < 30
    if not isinstance(result.get("issues"), list):
        result["issues"] = [str(result.get("issues"))] if result.get("issues") else []
    if not isinstance(result.get("corrections"), list):
        result["corrections"] = []
    return result


def clean_selected_transcripts(
    video_dir: str,
    dataframe,
    api_key: str,
    base_url: str,
    model: str = "",
    provider_id: str = "",
):
    """清洗选中的已有转录，生成 .cleaned.json 和 .quality.json。"""
    set_env(api_key, base_url, model, provider_id)

    if dataframe is None or len(dataframe) == 0:
        yield "❌ 没有媒体可清洗", None
        return

    selected = [row for row in dataframe_rows(dataframe) if row and row[0]]
    if not selected:
        yield "❌ 请至少选择一个已转录媒体", None
        return

    media_root = resolve_media_root(video_dir)
    logs = [f"🧹 开始清洗 {len(selected)} 条转录\n"]
    yield "\n".join(logs), None

    success_count = 0
    abnormal_count = 0
    skip_count = 0
    error_count = 0

    for i, row in enumerate(selected, 1):
        transcribe_status = str(row[1])
        filename = str(row[4])
        media_path = media_root / filename

        if "已转录" not in transcribe_status:
            logs.append(f"[{i}/{len(selected)}] ⏭️ {filename} - 未转录，跳过")
            skip_count += 1
            yield "\n".join(logs), None
            continue

        raw_text, raw_file = read_transcript_text(media_path)
        if not raw_text or not raw_file:
            logs.append(f"[{i}/{len(selected)}] ❌ {filename} - 找不到原始转录")
            error_count += 1
            yield "\n".join(logs), None
            continue

        metadata = read_media_metadata(media_path)
        title = str(metadata.get("title") or media_path.stem)
        tags = split_tags(metadata.get("tags", []))
        likes = int(metadata.get("likes", 0) or 0)
        source_account = str(
            metadata.get("source_account")
            or metadata.get("account_name")
            or metadata.get("accountName")
            or metadata.get("author")
            or source_account_from_media_path(media_path, media_root)
            or ""
        )

        logs.append(f"[{i}/{len(selected)}] 🧹 {filename} - AI 清洗中...")
        yield "\n".join(logs), None

        try:
            result = _clean_transcript_with_ai(raw_text, title, tags, source_account, likes)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload = {
                **result,
                "source_transcript_path": str(raw_file),
                "media_path": str(media_path),
                "title": title,
                "tags": tags,
                "source_account": source_account,
                "cleaned_time": now,
            }
            cleaned_transcript_path(media_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            quality_report_path(media_path).write_text(json.dumps({
                "quality_score": payload.get("quality_score", 0),
                "match_score": payload.get("match_score", 0),
                "needs_review": payload.get("needs_review", False),
                "issues": payload.get("issues", []),
                "summary": payload.get("summary", ""),
                "cleaned_path": str(cleaned_transcript_path(media_path)),
                "updated_time": now,
            }, ensure_ascii=False, indent=2), encoding="utf-8")

            if payload.get("needs_review"):
                abnormal_count += 1
                issues = "；".join(str(item) for item in payload.get("issues", [])[:3])
                logs[-1] = f"[{i}/{len(selected)}] ⚠️ {filename} - 已清洗但标记异常 Q{payload.get('quality_score')} M{payload.get('match_score')} {issues}"
            else:
                success_count += 1
                logs[-1] = f"[{i}/{len(selected)}] ✅ {filename} - 清洗完成 Q{payload.get('quality_score')} M{payload.get('match_score')}"
        except Exception as exc:
            logs[-1] = f"[{i}/{len(selected)}] ❌ {filename} - 清洗失败: {exc}"
            error_count += 1

        yield "\n".join(logs), None

    logs.append(f"\n{'='*60}")
    logs.append("🧹 清洗完成")
    logs.append(f"   ✅ 正常: {success_count} 条")
    logs.append(f"   ⚠️ 异常: {abnormal_count} 条")
    logs.append(f"   ⏭️ 跳过: {skip_count} 条")
    logs.append(f"   ❌ 失败: {error_count} 条")
    logs.append(f"{'='*60}")
    updated_list, _ = scan_local_videos(video_dir)
    yield "\n".join(logs), updated_list


def inspect_selected_transcript_quality(video_dir: str, dataframe):
    selected = [row for row in dataframe_rows(dataframe) if row and row[0]]
    if not selected:
        return "❌ 请先勾选一个媒体文件。"

    media_root = resolve_media_root(video_dir)
    row = selected[0]
    filename = str(row[4])
    media_path = media_root / filename
    metadata = read_media_metadata(media_path)
    raw_text, raw_file = read_transcript_text(media_path)
    cleaned_text, cleaned_file, cleaned_data = read_cleaned_transcript_text(media_path)
    quality = load_quality_report(media_path)
    report = {**quality, **cleaned_data}
    issues = report.get("issues", [])
    corrections = report.get("corrections", [])

    preview = cleaned_text or raw_text
    preview = preview[:500] + ("..." if len(preview) > 500 else "")
    issue_text = "\n".join(f"- {item}" for item in issues[:10]) if issues else "无"
    correction_text = "\n".join(
        f"- {item.get('from', '')} → {item.get('to', '')}：{item.get('reason', '')}"
        for item in corrections[:10]
        if isinstance(item, dict)
    ) or "无"

    return "\n\n".join([
        f"**媒体文件:** `{media_path}`",
        f"**标题:** {metadata.get('title', media_path.stem)}",
        f"**原始转录:** `{raw_file}`" if raw_file else "**原始转录:** 未找到",
        f"**清洗文件:** `{cleaned_file}`" if cleaned_file else "**清洗文件:** 未生成",
        f"**质量报告:** `{quality_report_path(media_path)}`" if quality_report_path(media_path).exists() else "**质量报告:** 未生成",
        f"**质量分:** {report.get('quality_score', '-')}",
        f"**匹配分:** {report.get('match_score', '-')}",
        f"**是否异常:** {'是' if report.get('needs_review') or report.get('abnormal') else '否'}",
        f"**异常原因:**\n{issue_text}",
        f"**主要修正:**\n{correction_text}",
        f"**预览:**\n{preview}",
    ])


def import_selected_transcripts(
    video_dir: str,
    dataframe,
    default_niche: str,
    api_key: str,
    base_url: str,
    model: str = "",
    provider_id: str = "",
    force_reimport: bool = False,
):
    """把勾选的已转录/未入库文案分析后导入知识库。"""
    set_env(api_key, base_url, model, provider_id)

    if dataframe is None or len(dataframe) == 0:
        yield "❌ 没有媒体可导入", None, kb.get_stats()
        return

    selected = [row for row in dataframe_rows(dataframe) if row and row[0]]
    if not selected:
        yield "❌ 请至少选择一个已转录且未入库的媒体", None, kb.get_stats()
        return

    total = len(selected)
    action = "重新入库" if force_reimport else "导入"
    logs = [f"🚀 开始{action} {total} 条转录文案到知识库\n"]
    yield "\n".join(logs), None, kb.get_stats()

    success_count = 0
    skip_count = 0
    error_count = 0
    media_root = resolve_media_root(video_dir)

    for i, row in enumerate(selected, 1):
        transcribe_status = str(row[1])
        clean_status = str(row[2])
        import_status = str(row[3])
        filename = str(row[4])
        video_id = str(row[6] or "")
        media_path = media_root / filename

        if "已转录" not in transcribe_status:
            logs.append(f"[{i}/{total}] ⏭️ {filename} - 未转录，跳过")
            skip_count += 1
            yield "\n".join(logs), None, kb.get_stats()
            continue

        already_imported = "已入库" in import_status or kb.has_script(video_id)
        if already_imported and not force_reimport:
            logs.append(f"[{i}/{total}] ⏭️ {filename} - 已入库，跳过")
            skip_count += 1
            yield "\n".join(logs), None, kb.get_stats()
            continue

        if "待清洗" in clean_status:
            logs.append(f"[{i}/{total}] ⏭️ {filename} - 尚未清洗，先点击“清洗选中转录”")
            skip_count += 1
            yield "\n".join(logs), None, kb.get_stats()
            continue

        if "异常" in clean_status:
            logs.append(f"[{i}/{total}] ⏭️ {filename} - 清洗异常，暂不自动入库")
            skip_count += 1
            yield "\n".join(logs), None, kb.get_stats()
            continue

        script, transcript_file, clean_data = read_import_transcript_text(media_path)
        if not script or not transcript_file:
            logs.append(f"[{i}/{total}] ❌ {filename} - 找不到转录文件")
            error_count += 1
            yield "\n".join(logs), None, kb.get_stats()
            continue

        try:
            if force_reimport and video_id:
                kb.delete_script(video_id)

            if len(script) < 30:
                logs.append(f"[{i}/{total}] ⏭️ {filename} - 文案过短，跳过")
                skip_count += 1
                yield "\n".join(logs), None, kb.get_stats()
                continue

            metadata = read_media_metadata(media_path)
            video_id = video_id or extract_video_id_from_media(media_path, metadata)
            likes = int(metadata.get("likes", 0) or 0)
            tags = split_tags(metadata.get("tags", []))
            title = str(metadata.get("title") or media_path.stem)
            source_account = str(
                metadata.get("source_account")
                or metadata.get("account_name")
                or metadata.get("accountName")
                or metadata.get("author")
                or source_account_from_media_path(media_path, media_root)
                or ""
            )
            channel = str(
                default_niche.strip()
                or metadata.get("channel")
                or metadata.get("niche")
                or infer_channel(title, tags, source_account)
            )
            level = engagement_level(likes)

            logs.append(f"[{i}/{total}] 🧠 {filename} - 分析并入库中...")
            yield "\n".join(logs), None, kb.get_stats()

            analysis = analyze_script(
                script,
                likes=likes,
                niche=channel,
                source_account=source_account,
                tags=tags,
            )
            kb.add_script(
                video_id=video_id,
                script=script,
                analysis=analysis,
                metadata={
                    "source": "douyin_webui",
                    "views": metadata.get("views", metadata.get("play_count", metadata.get("plays", 0))),
                    "likes": likes,
                    "comments": metadata.get("comments", metadata.get("comment_count", 0)),
                    "shares": metadata.get("shares", metadata.get("share_count", 0)),
                    "favorites": metadata.get("favorites", metadata.get("collects", metadata.get("collect_count", 0))),
                    "completion_rate": metadata.get("completion_rate", metadata.get("finish_rate", "")),
                    "publish_time": metadata.get("publish_time", metadata.get("published_at", metadata.get("create_time", ""))),
                    "account_type": metadata.get("account_type", ""),
                    "engagement_level": level,
                    "niche": channel,
                    "channel": channel,
                    "platform": "douyin",
                    "source_account": source_account,
                    "media_path": str(media_path),
                    "transcript_path": str(transcript_file),
                    "transcript_quality": clean_data.get("quality_score", ""),
                    "transcript_match_score": clean_data.get("match_score", ""),
                    "title": title,
                    "description": metadata.get("description", "") or metadata.get("desc", ""),
                    "video_url": metadata.get("video_url", ""),
                    "author": metadata.get("author", source_account),
                    "media_type": metadata.get("media_type", media_path.suffix.lower().lstrip(".")),
                    "tags": ",".join(tags),
                },
            )

            metadata["imported_to_kb"] = True
            metadata["imported_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            metadata["kb_video_id"] = video_id
            with open(media_path.with_suffix(".json"), "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            logs[-1] = f"[{i}/{total}] ✅ {filename} - 已导入知识库"
            success_count += 1

        except Exception as e:
            logs.append(f"[{i}/{total}] ❌ {filename} - 导入失败: {e}")
            error_count += 1

        yield "\n".join(logs), None, kb.get_stats()

    logs.append(f"\n{'='*60}")
    logs.append("🎉 导入完成！")
    logs.append(f"   ✅ 成功: {success_count} 条")
    logs.append(f"   ⏭️  跳过: {skip_count} 条")
    logs.append(f"   ❌ 失败: {error_count} 条")
    logs.append(f"{'='*60}")

    updated_list, _ = scan_local_videos(video_dir)
    yield "\n".join(logs), updated_list, kb.get_stats()


def reimport_selected_transcripts(
    video_dir: str,
    dataframe,
    default_niche: str,
    api_key: str,
    base_url: str,
    model: str = "",
    provider_id: str = "",
):
    yield from import_selected_transcripts(
        video_dir,
        dataframe,
        default_niche,
        api_key,
        base_url,
        model,
        provider_id,
        force_reimport=True,
    )


def remove_selected_from_kb(video_dir: str, dataframe):
    """从知识库删除选中的样本，不删除本地媒体/转录文件。"""
    if dataframe is None or len(dataframe) == 0:
        return "❌ 没有媒体可出库", None, kb.get_stats()

    selected = [row for row in dataframe_rows(dataframe) if row and row[0]]
    if not selected:
        return "❌ 请至少选择一个已入库媒体", None, kb.get_stats()

    media_root = resolve_media_root(video_dir)
    logs = [f"🗑️ 开始出库 {len(selected)} 条样本\n"]
    removed = 0
    skipped = 0

    for i, row in enumerate(selected, 1):
        filename = str(row[4])
        video_id = str(row[6] or "")
        media_path = media_root / filename
        metadata = read_media_metadata(media_path)
        video_id = video_id or extract_video_id_from_media(media_path, metadata)

        if kb.delete_script(video_id):
            removed += 1
            metadata["imported_to_kb"] = False
            metadata["removed_from_kb_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            metadata["kb_video_id"] = video_id
            metadata_path = media_path.with_suffix(".json")
            if metadata_path.exists():
                metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            logs.append(f"[{i}/{len(selected)}] ✅ {filename} - 已出库")
        else:
            skipped += 1
            logs.append(f"[{i}/{len(selected)}] ⏭️ {filename} - 知识库中不存在，跳过")

    logs.append(f"\n{'='*60}")
    logs.append(f"出库完成：删除 {removed} 条，跳过 {skipped} 条")
    logs.append(f"{'='*60}")
    updated_list, _ = scan_local_videos(video_dir)
    return "\n".join(logs), updated_list, kb.get_stats()


# ── Tab: Selenium 抖音采集 ──────────────────────────────────
def load_selenium_accounts():
    """加载 web_app.py 同款抖音账号列表。"""
    if not DOUYIN_ACCOUNTS_FILE.exists():
        return []
    try:
        with open(DOUYIN_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            accounts = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(accounts, list):
        return []
    return [acc for acc in accounts if isinstance(acc, dict) and acc.get("url")]


def save_selenium_accounts(accounts):
    """保存 web_app.py 同款抖音账号列表。"""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(DOUYIN_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def selenium_accounts_to_rows(accounts=None):
    accounts = accounts if accounts is not None else load_selenium_accounts()
    return [
        [
            bool(acc.get("enabled", True)),
            acc.get("url", ""),
            acc.get("status", "pending") or "pending",
            int(acc.get("progress", 0) or 0),
        ]
        for acc in accounts
    ]


def selenium_rows_to_accounts(rows):
    if rows is None:
        return []

    values = rows.values.tolist() if hasattr(rows, "values") else rows
    accounts = []
    for row in values:
        if not row or len(row) < 2:
            continue
        url = str(row[1] or "").strip()
        if not url:
            continue
        enabled_value = row[0]
        enabled = enabled_value
        if isinstance(enabled_value, str):
            enabled = enabled_value.strip().lower() not in {"false", "0", "否", "no", ""}
        accounts.append({
            "enabled": bool(enabled),
            "url": url,
            "status": str(row[2] or "pending") if len(row) > 2 else "pending",
            "progress": int(float(row[3] or 0)) if len(row) > 3 else 0,
        })
    return accounts


def selenium_account_stats(rows=None):
    if rows is None:
        accounts = load_selenium_accounts()
    elif isinstance(rows, list) and (not rows or isinstance(rows[0], dict)):
        accounts = rows
    else:
        accounts = selenium_rows_to_accounts(rows)
    total = len(accounts)
    completed = sum(1 for acc in accounts if acc.get("status") == "completed")
    pending = sum(1 for acc in accounts if not acc.get("status") or acc.get("status") == "pending")
    enabled = sum(1 for acc in accounts if acc.get("enabled", True))
    return f"**总账号数:** {total}　**启用:** {enabled}　**已完成:** {completed}　**待下载:** {pending}"


def load_selenium_accounts_ui():
    rows = selenium_accounts_to_rows()
    return rows, selenium_account_stats(rows)


def add_selenium_account(account_url: str, rows):
    url = (account_url or "").strip()
    accounts = selenium_rows_to_accounts(rows)

    if not url:
        return selenium_accounts_to_rows(accounts), "", selenium_account_stats(accounts), "❌ 请输入抖音账号链接"
    if "douyin.com" not in url:
        return selenium_accounts_to_rows(accounts), account_url, selenium_account_stats(accounts), "❌ 请输入有效的抖音链接"
    if any(acc.get("url") == url for acc in accounts):
        return selenium_accounts_to_rows(accounts), "", selenium_account_stats(accounts), "ℹ️ 账号已存在"

    accounts.append({"url": url, "status": "pending", "enabled": True, "progress": 0})
    save_selenium_accounts(accounts)
    add_selenium_log("info", f"已添加账号: {url}")
    rows = selenium_accounts_to_rows(accounts)
    return rows, "", selenium_account_stats(rows), format_selenium_logs()


def save_selenium_accounts_ui(rows):
    accounts = selenium_rows_to_accounts(rows)
    save_selenium_accounts(accounts)
    add_selenium_log("info", "账号列表已保存")
    rows = selenium_accounts_to_rows(accounts)
    return rows, selenium_account_stats(rows), format_selenium_logs()


def clear_completed_selenium_accounts(rows):
    accounts = [acc for acc in selenium_rows_to_accounts(rows) if acc.get("status") != "completed"]
    save_selenium_accounts(accounts)
    add_selenium_log("info", "已清除所有已完成的账号")
    rows = selenium_accounts_to_rows(accounts)
    return rows, selenium_account_stats(rows), format_selenium_logs()


def clear_all_selenium_accounts():
    save_selenium_accounts([])
    add_selenium_log("info", "已清空账号列表")
    return [], selenium_account_stats([]), format_selenium_logs()


def add_selenium_log(level: str, message: str):
    """添加日志"""
    global selenium_task
    log_entry = {
        "level": level,
        "message": message,
        "time": time.strftime("%H:%M:%S")
    }
    selenium_task["logs"].append(log_entry)
    # 只保留最近50条
    if len(selenium_task["logs"]) > 50:
        selenium_task["logs"] = selenium_task["logs"][-50:]


def format_selenium_logs():
    if not selenium_task["logs"]:
        return "[等待开始] 准备就绪，等待启动下载任务..."
    return "\n".join([
        f"[{log['time']}] {log['message']}"
        for log in selenium_task["logs"][-20:]
    ])


def list_recent_selenium_media(save_path: str, limit: int = 30):
    """列出最近下载的媒体，方便定位错配音频和对应元数据。"""
    base_dir = Path(save_path or "./douyin_videos").expanduser()
    if not base_dir.is_absolute():
        base_dir = (ROOT / base_dir).resolve()
    if not base_dir.exists():
        return [], f"目录不存在：{base_dir}"

    media_files = [
        path for path in base_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".m4a", ".mp4", ".mp3", ".aac", ".wav"}
    ]
    media_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    rows = []
    for path in media_files[: int(limit or 30)]:
        metadata = read_media_metadata(path)
        rel_path = path.relative_to(base_dir)
        download = metadata.get("download") if isinstance(metadata, dict) else {}
        fallback_reason = metadata.get("fallback_reason", "") if isinstance(metadata, dict) else ""
        audio_candidates = int(metadata.get("audio_candidates_count") or 0) if isinstance(metadata, dict) else 0
        method = download.get("method") if isinstance(download, dict) else ""
        status = "✅ 正常"
        if fallback_reason:
            status = "🛟 兜底"
        elif audio_candidates > 1:
            status = "⚠️ 多音频"

        rows.append([
            False,
            status,
            path.suffix.lower().lstrip("."),
            metadata.get("video_id", "") if isinstance(metadata, dict) else "",
            metadata.get("title", "") if isinstance(metadata, dict) else "",
            metadata.get("author", "") if isinstance(metadata, dict) else "",
            str(audio_candidates),
            str(method or ("browser" if metadata else "")),
            time.strftime("%H:%M:%S", time.localtime(path.stat().st_mtime)),
            str(rel_path),
            str(path),
        ])

    return rows, f"已列出最近 {len(rows)} 个媒体文件：{base_dir}"


def refresh_selenium_media_locator(save_path: str):
    return list_recent_selenium_media(save_path)


def selected_media_path(rows) -> Path | None:
    for row in dataframe_rows(rows):
        if row and row[0] and len(row) >= 11:
            path = Path(str(row[10] or ""))
            if path.exists():
                return path
    return None


def reveal_selected_selenium_media(rows):
    path = selected_media_path(rows)
    if not path:
        return "❌ 请先在最近下载文件表里勾选一个存在的文件。"

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        elif os.name == "nt":
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path.parent)], check=False)
    except Exception as exc:
        return f"❌ 打开文件位置失败：{exc}"

    return f"✅ 已定位文件：{path}\n\n元数据：{path.with_suffix('.json')}"


def inspect_selected_selenium_media(rows):
    path = selected_media_path(rows)
    if not path:
        return "❌ 请先勾选一个媒体文件。"

    metadata = read_media_metadata(path)
    media_transcript_path = transcript_path(path)
    summary = [
        f"**媒体文件:** `{path}`",
        f"**元数据:** `{path.with_suffix('.json')}`",
        f"**转录文件:** `{media_transcript_path}`" if media_transcript_path.exists() else "**转录文件:** 未生成",
        "",
        f"**video_id:** `{metadata.get('video_id', '')}`",
        f"**标题:** {metadata.get('title', '')}",
        f"**账号:** {metadata.get('author') or metadata.get('account_name', '')}",
        f"**下载方式:** {(metadata.get('download') or {}).get('method', 'browser') if metadata else '未知'}",
        f"**音频候选数:** {metadata.get('audio_candidates_count', '')}",
        f"**兜底原因:** {metadata.get('fallback_reason', '') or '无'}",
        f"**校验:** {metadata.get('validation', '')}",
        f"**原视频链接:** {metadata.get('video_url', '')}",
    ]
    return "\n\n".join(summary)


def start_selenium_download(rows, save_path: str, min_likes: int,
                           organize_by_tag: bool, save_metadata: bool, auto_next: bool):
    """启动 Selenium 下载任务"""
    global selenium_task

    if selenium_task["is_running"]:
        return "❌ 下载任务已在运行中，请先停止当前任务", rows, selenium_account_stats(rows)

    accounts = selenium_rows_to_accounts(rows)
    save_selenium_accounts(accounts)
    active_accounts = [
        (idx, acc)
        for idx, acc in enumerate(accounts)
        if acc.get("enabled", True)
    ]
    user_urls = [acc["url"] for _, acc in active_accounts]
    if not user_urls:
        return "❌ 请至少添加并启用一个账号", selenium_accounts_to_rows(accounts), selenium_account_stats(accounts)

    # 初始化任务状态
    selenium_task["is_running"] = True
    selenium_task["accounts_status"] = []
    selenium_task["logs"] = []
    selenium_task["current_account"] = 0
    selenium_task["total_accounts"] = len(user_urls)
    selenium_task["active_account_indices"] = [idx for idx, _ in active_accounts]
    selenium_task["auto_clear_completed_done"] = False

    add_selenium_log("info", f"启动下载任务，共 {len(user_urls)} 个账号")
    if save_metadata:
        add_selenium_log("info", "视频元数据将随视频保存")

    # 后台线程运行下载
    def run_download():
        try:
            from douyin_selenium import DouyinSeleniumDownloader

            def progress_callback(account_index, status, progress, **kwargs):
                """进度回调"""
                selenium_task["current_account"] = account_index + 1
                if account_index < len(selenium_task["accounts_status"]):
                    selenium_task["accounts_status"][account_index] = {
                        "url": user_urls[account_index],
                        "status": status,
                        "progress": progress,
                        **kwargs
                    }

            def log_callback(level, message):
                """日志回调"""
                add_selenium_log(level, message)

            downloader = DouyinSeleniumDownloader(
                output_dir=save_path,
                organize_by_tag=organize_by_tag,
                progress_callback=progress_callback,
                log_callback=log_callback
            )

            selenium_task["downloader"] = downloader

            # 初始化账号状态
            for url in user_urls:
                selenium_task["accounts_status"].append({
                    "url": url,
                    "status": "pending",
                    "progress": 0
                })

            # 运行批量下载
            downloader.run_batch(
                user_urls=user_urls,
                scroll_times=10,
                min_likes=min_likes,
                auto_mode=auto_next
            )

            add_selenium_log("success", "所有下载任务已完成")

        except Exception as e:
            add_selenium_log("error", f"下载任务异常: {str(e)}")
            import traceback
            add_selenium_log("error", traceback.format_exc())
        finally:
            selenium_task["is_running"] = False
            selenium_task["downloader"] = None

    thread = threading.Thread(target=run_download, daemon=True)
    thread.start()
    selenium_task["thread"] = thread

    return format_selenium_logs(), selenium_accounts_to_rows(accounts), selenium_account_stats(accounts)


def stop_selenium_download():
    """停止 Selenium 下载任务"""
    global selenium_task

    if not selenium_task["is_running"]:
        return "ℹ️ 没有运行中的任务"

    try:
        downloader = selenium_task.get("downloader")
        if downloader:
            downloader.stop()

        add_selenium_log("info", "下载任务已停止")
        return format_selenium_logs()
    except Exception as e:
        return f"❌ 停止失败: {str(e)}"


def get_selenium_status(rows):
    """获取 Selenium 下载状态"""
    global selenium_task

    # 检查线程是否还在运行
    if selenium_task["is_running"]:
        thread = selenium_task.get("thread")
        if thread and not thread.is_alive():
            selenium_task["is_running"] = False
            selenium_task["thread"] = None
            add_selenium_log("success", "所有下载任务已完成")

    accounts = selenium_rows_to_accounts(rows)
    active_indices = selenium_task.get("active_account_indices", [])
    for idx, status in enumerate(selenium_task["accounts_status"]):
        account_index = active_indices[idx] if idx < len(active_indices) else idx
        if account_index < len(accounts):
            accounts[account_index]["status"] = status.get("status", accounts[account_index].get("status", "pending"))
            accounts[account_index]["progress"] = status.get("progress", accounts[account_index].get("progress", 0))

    if (
        not selenium_task["is_running"]
        and selenium_task["accounts_status"]
        and not selenium_task.get("auto_clear_completed_done")
    ):
        before_count = len(accounts)
        accounts = [acc for acc in accounts if acc.get("status") != "completed"]
        removed_count = before_count - len(accounts)
        if removed_count:
            save_selenium_accounts(accounts)
            add_selenium_log("info", f"已自动清除 {removed_count} 个已完成账号")
        selenium_task["auto_clear_completed_done"] = True

    current_rows = selenium_accounts_to_rows(accounts)

    # 格式化状态信息
    status_text = f"**运行状态:** {'🟢 运行中' if selenium_task['is_running'] else '⚪ 空闲'}\n\n"

    if selenium_task["total_accounts"] > 0:
        status_text += f"**进度:** {selenium_task['current_account']}/{selenium_task['total_accounts']} 个账号\n\n"

    # 账号状态
    if selenium_task["accounts_status"]:
        status_text += "**账号状态:**\n\n"
        for i, acc in enumerate(selenium_task["accounts_status"], 1):
            status_icon = {
                "pending": "⏳",
                "downloading": "📥",
                "completed": "✅",
                "error": "❌"
            }.get(acc.get("status", "pending"), "⏳")

            status_text += f"{i}. {status_icon} {acc.get('url', 'Unknown')[:50]}... - {acc.get('status', 'pending')}\n"

    return status_text, format_selenium_logs(), current_rows, selenium_account_stats(current_rows)


# ── 界面布局 ──────────────────────────────────────────────
with gr.Blocks(title="爆款文案智能体") as demo:
    gr.Markdown("# 🔥 爆款文案智能体\n基于爆款视频知识库，自动生成高质量短视频文案")

    # 全局配置
    with gr.Accordion("⚙️ API 配置", open=False):
        with gr.Row():
            provider_input = gr.Dropdown(
                label="AI Provider",
                choices=provider_choices(),
                value=(DEFAULT_PROVIDER.id if DEFAULT_PROVIDER else None),
                interactive=True,
                scale=2,
            )
            refresh_provider_btn = gr.Button("刷新 Provider", scale=1)
            test_provider_btn = gr.Button("测试当前 Provider", scale=1)
        with gr.Row():
            api_key_input = gr.Textbox(
                value=masked_key(DEFAULT_API_KEY), label="API Key（来自 .env，默认隐藏）",
                placeholder="sk-...", type="password", scale=3,
            )
            base_url_input = gr.Textbox(
                value=DEFAULT_BASE_URL, label="Base URL",
                placeholder="https://api.anthropic.com", scale=2,
            )
            model_input = gr.Textbox(
                value=DEFAULT_MODEL, label="模型",
                placeholder="claude-sonnet-4-6", scale=2,
            )
        provider_status = gr.Markdown()

        provider_input.change(
            select_ai_provider,
            inputs=[provider_input],
            outputs=[api_key_input, base_url_input, model_input, provider_status],
        )
        refresh_provider_btn.click(
            refresh_ai_providers,
            outputs=[provider_input, api_key_input, base_url_input, model_input, provider_status],
        )
        test_provider_btn.click(
            test_ai_provider,
            inputs=[provider_input],
            outputs=[provider_status],
        )

    kb_stats = gr.Markdown(value=kb.get_stats(), label="知识库状态")

    with gr.Tabs():
        # ── Tab 0: 转录本地视频 ──
        with gr.Tab("🎬 转录本地视频"):
            gr.Markdown("""
### 📹 转录本地视频文件

**使用步骤：**
1. 输入视频目录路径（默认 `./douyin_videos`）
2. 点击"扫描视频"查看视频列表
3. 勾选需要转录的视频（已转录的会显示 ✅）
4. 选择转录方式（推荐使用云雾 API）
5. 点击"开始转录"，逐字稿会保存到视频同目录下
6. 在列表里看到"已转录 / 未入库"后，勾选并点击"导入知识库"
            """)

            with gr.Row():
                with gr.Column(scale=1):
                    video_dir_input = gr.Textbox(
                        label="视频目录路径",
                        value="./douyin_videos",
                        placeholder="./douyin_videos"
                    )
                    with gr.Row():
                        folder_filter = gr.Dropdown(
                            label="目录筛选",
                            choices=media_folder_choices("./douyin_videos"),
                            value="全部",
                            interactive=True,
                            scale=3,
                        )
                        refresh_folder_filter_btn = gr.Button("刷新目录", variant="secondary", scale=1)

                    status_filter = gr.Radio(
                        label="状态筛选",
                        choices=["全部", "已转录", "未转录", "待清洗", "已清洗", "异常", "未入库", "已入库"],
                        value="全部",
                        info="筛选要显示的视频"
                    )

                    scan_btn = gr.Button("🔍 扫描视频", variant="secondary")

                    transcribe_method_local = gr.Radio(
                        label="转录方式",
                        choices=["yunwu", "groq", "whisper"],
                        value="yunwu",
                        info="⚠️ whisper需下载2.88GB模型！推荐使用yunwu（云端，无需下载）"
                    )

                    transcribe_api_key = gr.Textbox(
                        label="API Key（yunwu/groq 需要）",
                        value=DEFAULT_TRANSCRIBE_API_KEY,
                        type="password",
                        placeholder="sk-..."
                    )

                    transcribe_btn = gr.Button("🚀 开始转录选中视频", variant="primary", size="lg")
                    clean_transcript_btn = gr.Button("🧹 清洗选中转录", variant="secondary", size="lg")
                    inspect_quality_btn = gr.Button("🔎 查看清洗/异常报告", variant="secondary")

                    import_niche_input = gr.Dropdown(
                        label="默认赛道",
                        choices=["猫狗科普", "宠物健康", "宠物救助", "动物行为学", "动物解说", "动物科普"],
                        value="猫狗科普",
                        allow_custom_value=True,
                        info="导入知识库时使用的赛道标签，可手动输入自定义赛道"
                    )
                    import_kb_btn = gr.Button("📥 导入知识库", variant="secondary", size="lg")
                    reimport_kb_btn = gr.Button("🔁 重新入库选中", variant="secondary")
                    remove_kb_btn = gr.Button("🗑️ 出库选中", variant="secondary")

                with gr.Column(scale=2):
                    scan_status = gr.Textbox(label="扫描状态", lines=1, interactive=False)
                    video_list_df = gr.Dataframe(
                        headers=["选择", "转录状态", "清洗状态", "入库状态", "文件名", "大小(MB)", "视频ID", "路径"],
                        datatype=["bool", "str", "str", "str", "str", "str", "str", "str"],
                        column_count=(8, "fixed"),
                        label="视频列表",
                        interactive=True,
                        wrap=True
                    )

            transcribe_log = gr.Textbox(
                label="转录日志",
                lines=15,
                max_lines=25,
                interactive=False
            )

            clean_log = gr.Textbox(
                label="清洗日志 / 异常报告",
                lines=12,
                max_lines=25,
                interactive=False
            )

            import_log = gr.Textbox(
                label="入库日志",
                lines=12,
                max_lines=25,
                interactive=False
            )

            # 扫描视频
            scan_btn.click(
                scan_local_videos_with_stats,
                inputs=[video_dir_input, status_filter, folder_filter],
                outputs=[video_list_df, scan_status, kb_stats]
            )

            refresh_folder_filter_btn.click(
                refresh_media_folder_filter,
                inputs=[video_dir_input],
                outputs=[folder_filter]
            )

            # 状态筛选变化时重新扫描
            status_filter.change(
                scan_local_videos_with_stats,
                inputs=[video_dir_input, status_filter, folder_filter],
                outputs=[video_list_df, scan_status, kb_stats]
            )

            folder_filter.change(
                scan_local_videos_with_stats,
                inputs=[video_dir_input, status_filter, folder_filter],
                outputs=[video_list_df, scan_status, kb_stats]
            )

            # 转录视频
            transcribe_btn.click(
                transcribe_selected_videos,
                inputs=[video_dir_input, video_list_df, transcribe_method_local, transcribe_api_key],
                outputs=[transcribe_log, video_list_df]
            )

            clean_transcript_btn.click(
                clean_selected_transcripts,
                inputs=[video_dir_input, video_list_df, api_key_input, base_url_input, model_input, provider_input],
                outputs=[clean_log, video_list_df]
            )

            inspect_quality_btn.click(
                inspect_selected_transcript_quality,
                inputs=[video_dir_input, video_list_df],
                outputs=[clean_log]
            )

            import_kb_btn.click(
                import_selected_transcripts,
                inputs=[video_dir_input, video_list_df, import_niche_input, api_key_input, base_url_input, model_input, provider_input],
                outputs=[import_log, video_list_df, kb_stats]
            )

            reimport_kb_btn.click(
                reimport_selected_transcripts,
                inputs=[video_dir_input, video_list_df, import_niche_input, api_key_input, base_url_input, model_input, provider_input],
                outputs=[import_log, video_list_df, kb_stats]
            )

            remove_kb_btn.click(
                remove_selected_from_kb,
                inputs=[video_dir_input, video_list_df],
                outputs=[import_log, video_list_df, kb_stats]
            )

        # ── Tab: Selenium 抖音采集 ──
        with gr.Tab("🤖 Selenium 采集"):
            gr.Markdown("""
### 抖音视频采集器
批量采集抖音账号的爆款视频，支持元数据提取和智能分类
            """)

            with gr.Row():
                with gr.Column(scale=2):
                    gr.Markdown("### 账号列表")
                    selenium_account_stats_display = gr.Markdown(value=selenium_account_stats())

                    selenium_account_input = gr.Textbox(
                        label="添加抖音账号链接",
                        placeholder="粘贴抖音账号主页链接，例如：https://www.douyin.com/user/..."
                    )

                    with gr.Row():
                        selenium_add_account_btn = gr.Button("添加账号", variant="primary")
                        selenium_save_accounts_btn = gr.Button("保存列表", variant="secondary")
                        selenium_clear_completed_btn = gr.Button("清除已完成", variant="secondary")
                        selenium_clear_all_btn = gr.Button("清空列表", variant="secondary")

                    selenium_accounts_df = gr.Dataframe(
                        headers=["启用", "账号链接", "状态", "进度"],
                        datatype=["bool", "str", "str", "number"],
                        value=selenium_accounts_to_rows(),
                        column_count=(4, "fixed"),
                        label="账号列表",
                        interactive=True,
                        wrap=True
                    )

                    gr.Markdown("### 下载日志")
                    selenium_log_display = gr.Textbox(
                        label="实时日志",
                        value=format_selenium_logs(),
                        lines=15,
                        max_lines=20,
                        interactive=False
                    )
                    gr.Markdown("### 最近下载文件")
                    with gr.Row():
                        selenium_refresh_media_btn = gr.Button("刷新文件列表", variant="secondary")
                        selenium_reveal_media_btn = gr.Button("在 Finder 中定位", variant="secondary")
                    selenium_media_status = gr.Textbox(
                        label="文件定位状态",
                        value="点击刷新文件列表查看最近下载结果",
                        lines=2,
                        interactive=False
                    )
                    selenium_media_df = gr.Dataframe(
                        headers=["选择", "风险", "类型", "视频ID", "标题", "账号", "音频候选", "下载方式", "时间", "相对路径", "完整路径"],
                        datatype=["bool", "str", "str", "str", "str", "str", "str", "str", "str", "str", "str"],
                        column_count=(11, "fixed"),
                        label="最近下载媒体",
                        interactive=True,
                        wrap=True
                    )
                    selenium_media_detail = gr.Markdown(value="勾选一行后点击查看元数据。")
                    selenium_inspect_media_btn = gr.Button("查看选中文件元数据", variant="secondary")

                with gr.Column(scale=1):
                    gr.Markdown("### 下载设置")

                    selenium_save_path = gr.Textbox(
                        label="保存路径",
                        value="./douyin_videos",
                        info="视频保存的目录"
                    )

                    selenium_min_likes = gr.Number(
                        label="最低点赞数",
                        value=2000,
                        minimum=0,
                        info="只下载点赞数超过此值的视频"
                    )

                    selenium_organize_by_tag = gr.Checkbox(
                        label="按标签分类保存",
                        value=True,
                        info="自动按视频标签创建子目录"
                    )

                    selenium_save_metadata = gr.Checkbox(
                        label="保存视频元数据",
                        value=True
                    )

                    selenium_auto_next = gr.Checkbox(
                        label="自动切换下一个账号",
                        value=True
                    )

                    with gr.Row():
                        selenium_start_btn = gr.Button("开始下载", variant="primary", size="lg")
                        selenium_stop_btn = gr.Button("停止下载", variant="stop", size="lg")

                    selenium_status_display = gr.Markdown(
                        value="**运行状态:** ⚪ 空闲",
                        label="任务状态"
                    )

                    gr.Markdown("""
### 使用说明
1. 安装 Tampermonkey 浏览器扩展
2. 导入 `douyin/douyin_downloader/tampermonkey_script.js`
3. 添加要采集的抖音账号链接
4. 配置下载参数
5. 点击开始下载启动浏览器
6. 等待自动扫描和下载完成
                    """)

            selenium_add_account_btn.click(
                add_selenium_account,
                inputs=[selenium_account_input, selenium_accounts_df],
                outputs=[
                    selenium_accounts_df,
                    selenium_account_input,
                    selenium_account_stats_display,
                    selenium_log_display
                ]
            )

            selenium_save_accounts_btn.click(
                save_selenium_accounts_ui,
                inputs=[selenium_accounts_df],
                outputs=[selenium_accounts_df, selenium_account_stats_display, selenium_log_display]
            )

            selenium_clear_completed_btn.click(
                clear_completed_selenium_accounts,
                inputs=[selenium_accounts_df],
                outputs=[selenium_accounts_df, selenium_account_stats_display, selenium_log_display]
            )

            selenium_clear_all_btn.click(
                clear_all_selenium_accounts,
                outputs=[selenium_accounts_df, selenium_account_stats_display, selenium_log_display]
            )

            selenium_refresh_media_btn.click(
                refresh_selenium_media_locator,
                inputs=[selenium_save_path],
                outputs=[selenium_media_df, selenium_media_status]
            )

            selenium_reveal_media_btn.click(
                reveal_selected_selenium_media,
                inputs=[selenium_media_df],
                outputs=[selenium_media_status]
            )

            selenium_inspect_media_btn.click(
                inspect_selected_selenium_media,
                inputs=[selenium_media_df],
                outputs=[selenium_media_detail]
            )

            # 定时刷新状态
            selenium_refresh_timer = gr.Timer(value=2.0, active=True)
            selenium_refresh_timer.tick(
                get_selenium_status,
                inputs=[selenium_accounts_df],
                outputs=[
                    selenium_status_display,
                    selenium_log_display,
                    selenium_accounts_df,
                    selenium_account_stats_display
                ]
            )

            selenium_start_btn.click(
                start_selenium_download,
                inputs=[
                    selenium_accounts_df,
                    selenium_save_path,
                    selenium_min_likes,
                    selenium_organize_by_tag,
                    selenium_save_metadata,
                    selenium_auto_next
                ],
                outputs=[selenium_log_display, selenium_accounts_df, selenium_account_stats_display]
            )

            selenium_stop_btn.click(
                stop_selenium_download,
                outputs=[selenium_log_display]
            )

        # ── Tab 1: 知识库 ──
        with gr.Tab("🗂️ 知识库"):
            with gr.Tabs():
                with gr.Tab("语义检索"):
                    with gr.Row():
                        search_query = gr.Textbox(label="检索内容", placeholder="职场升职、减肥瘦身...", scale=3)
                        search_niche = gr.Textbox(label="筛选赛道（可选）", placeholder="情感", scale=1)
                        search_n = gr.Slider(label="返回数量", minimum=1, maximum=10, value=5, step=1)
                    search_btn = gr.Button("🔍 检索", variant="primary")
                    search_output = gr.Markdown()
                    search_btn.click(search_kb, inputs=[search_query, search_niche, search_n], outputs=search_output)

                with gr.Tab("统计分析"):
                    stats_niche = gr.Textbox(label="筛选赛道（可选）", placeholder="留空查看全部")
                    stats_btn = gr.Button("📊 查看统计", variant="primary")
                    stats_output = gr.Markdown()
                    stats_btn.click(show_stats, inputs=[stats_niche], outputs=stats_output)

        # ── Tab 2: 生成 ──
        with gr.Tab("✍️ 生成文案"):
            with gr.Row():
                with gr.Column(scale=1):
                    topic_input = gr.Textbox(
                        label="视频主题 / 参考原文 *",
                        placeholder="短主题：普通人如何月入过万\n或粘贴一段参考原文，系统会提炼选题后重新创作，避免照抄。",
                        lines=8,
                    )
                    niche_input3 = gr.Textbox(label="赛道", placeholder="干货、情感、美食...")
                    req_input = gr.Textbox(
                        label="额外要求（可选）",
                        placeholder="目标受众：25-35岁职场人\n风格：接地气、有共鸣感",
                        lines=3,
                    )
                    versions_input = gr.Slider(label="生成版本数", minimum=1, maximum=5, value=3, step=1)
                    gen_btn = gr.Button("🔥 生成爆款文案", variant="primary", size="lg")
                with gr.Column(scale=2):
                    gen_output = gr.Markdown(label="生成结果")
                    gen_save_status = gr.Markdown()

            with gr.Accordion("💾 已保存文案 / Seedance 2.0 动画提示词拆分", open=True):
                with gr.Row():
                    gen_saved_dropdown = gr.Dropdown(
                        label="已保存文案",
                        choices=generated_script_choices(),
                        interactive=True,
                        scale=3,
                    )
                    refresh_saved_btn = gr.Button("刷新列表", scale=1)
                    load_saved_btn = gr.Button("载入", variant="primary", scale=1)
                    delete_saved_btn = gr.Button("删除", scale=1)

                saved_status = gr.Markdown(value=f"已保存 {len(generated_script_choices())} 条文案。")

                versions_list_state = gr.State([])

                with gr.Row():
                    ver_btn_1 = gr.Button("版本1", size="sm", scale=1)
                    ver_btn_2 = gr.Button("版本2", size="sm", scale=1)
                    ver_btn_3 = gr.Button("版本3", size="sm", scale=1)
                    ver_btn_4 = gr.Button("版本4", size="sm", scale=1)
                    ver_btn_5 = gr.Button("版本5", size="sm", scale=1)
                    ver_label = gr.Textbox(value="← 载入文案后点击切换版本", interactive=False, show_label=False, scale=3)

                saved_script_text = gr.Textbox(
                    label="当前文案正文（可编辑）",
                    lines=10,
                    placeholder="生成或载入文案后，这里会出现可继续加工的文案。",
                )

                with gr.Accordion("📋 结构化字段", open=False):
                    ver_title = gr.Textbox(label="标题", lines=1, interactive=False)
                    ver_description = gr.Textbox(label="描述", lines=8, interactive=False)
                    ver_tags = gr.Textbox(label="标签", lines=1, interactive=False)
                    ver_cover_image = gr.Textbox(label="封面图建议", lines=3, interactive=False)
                    ver_cover_text = gr.Textbox(label="封面文字建议", lines=1, interactive=False)

                with gr.Row():
                    dreamina_max_seconds = gr.Slider(
                        label="Seedance 单段最长秒数（模板固定优先15秒，保留此项兼容旧界面）",
                        minimum=5,
                        maximum=15,
                        value=15,
                        step=1,
                    )
                    dreamina_model = gr.Dropdown(
                        label="Seedance 模型",
                        choices=["seedance2.0fast", "seedance2.0", "seedance2.0fast_vip", "seedance2.0_vip"],
                        value="seedance2.0fast",
                        interactive=True,
                    )
                    channel_dropdown = gr.Dropdown(
                        label="频道画风",
                        choices=get_channel_choices(),
                        value=get_default_channel_id(),
                        interactive=True,
                        info="选择不同频道使用不同的画风模板",
                        scale=2,
                    )
                split_dreamina_btn = gr.Button("🎬 拆分为 Seedance 2.0 动画分镜提示词", variant="primary")
                with gr.Row():
                    seedance_project_dropdown = gr.Dropdown(
                        label="导入到项目",
                        choices=project_choices(),
                        value=active_project_id(),
                        interactive=True,
                        scale=3,
                    )
                    refresh_projects_btn = gr.Button("刷新项目", scale=1)
                    import_seedance_queue_btn = gr.Button("📥 一键导入到项目文生视频队列", variant="secondary", scale=2)
                with gr.Row():
                    seedance_new_project_name = gr.Textbox(
                        label="新建独立项目名称（可选，不填则按文案自动命名）",
                        placeholder="例如：猫咪踩奶科普动画",
                        scale=3,
                    )
                    create_project_import_btn = gr.Button("🆕 新建独立项目并导入", variant="primary", scale=2)
                seedance_import_status = gr.Markdown()
                dreamina_prompts_output = gr.Markdown(label="Seedance 2.0 提示词")
                dreamina_queue_json = gr.Textbox(
                    label="队列 JSON 草稿（可后续导入 web_app.py 即梦队列页）",
                    lines=8,
                )

                refresh_saved_btn.click(
                    refresh_generated_scripts,
                    outputs=[gen_saved_dropdown, saved_status],
                )
                load_saved_btn.click(
                    load_saved_generated_script,
                    inputs=[gen_saved_dropdown],
                    outputs=[
                        gen_output,
                        saved_script_text,
                        topic_input,
                        niche_input3,
                        req_input,
                        versions_input,
                        saved_status,
                        versions_list_state,
                        ver_label,
                        ver_title,
                        ver_description,
                        ver_tags,
                        ver_cover_image,
                        ver_cover_text,
                    ],
                )
                for _ver_idx, _ver_btn in enumerate([ver_btn_1, ver_btn_2, ver_btn_3, ver_btn_4, ver_btn_5], start=1):
                    _ver_btn.click(
                        fn=lambda vl, idx=_ver_idx: switch_version(vl, idx),
                        inputs=[versions_list_state],
                        outputs=[saved_script_text, ver_label, ver_title, ver_description, ver_tags, ver_cover_image, ver_cover_text],
                    )
                delete_saved_btn.click(
                    delete_saved_generated_script,
                    inputs=[gen_saved_dropdown],
                    outputs=[gen_saved_dropdown, gen_output, saved_script_text, saved_status],
                )
                split_dreamina_btn.click(
                    build_dreamina_prompts,
                    inputs=[saved_script_text, dreamina_max_seconds, dreamina_model, channel_dropdown],
                    outputs=[dreamina_prompts_output, dreamina_queue_json],
                )
                refresh_projects_btn.click(
                    refresh_project_choices,
                    outputs=[seedance_project_dropdown, seedance_import_status],
                )
                import_seedance_queue_btn.click(
                    import_seedance_queue_to_web_queue,
                    inputs=[dreamina_queue_json, seedance_project_dropdown],
                    outputs=[seedance_import_status],
                )
                create_project_import_btn.click(
                    create_project_and_import_seedance_queue,
                    inputs=[dreamina_queue_json, seedance_new_project_name, saved_script_text],
                    outputs=[seedance_project_dropdown, seedance_import_status],
                )

        with gr.Tab("🎥 Sora 视频生成"):
            gr.Markdown("""
## Sora 2.0 视频生成（云雾 API）

使用云雾 API 的 sora-2-all 模型生成高质量真实感视频。

**特点：**
- 真实感视频风格（与 Seedance 的动画风格不同）
- 支持 5-20 秒视频片段
- 电影级画面质感

**使用前准备：**
1. 设置环境变量 `YUNWU_API_KEY`（云雾 API 密钥）
2. 可选设置 `YUNWU_BASE_URL`（默认：https://api.yunwu.ai）
""")

            with gr.Row():
                with gr.Column(scale=2):
                    sora_gen_saved_dropdown = gr.Dropdown(
                        label="已保存的文案",
                        choices=generated_script_choices(),
                        interactive=True,
                        scale=3,
                    )
                sora_refresh_saved_btn = gr.Button("刷新列表", scale=1)
                sora_load_saved_btn = gr.Button("载入", variant="primary", scale=1)

            sora_saved_status = gr.Markdown(value=f"已保存 {len(generated_script_choices())} 条文案。")
            sora_script_text = gr.Textbox(
                label="当前文案（可编辑）",
                lines=10,
                placeholder="生成或载入文案后，这里会出现可继续加工的文案。",
            )

            sora_split_btn = gr.Button("🎥 拆分为 Sora 2.0 视频提示词", variant="primary")

            sora_prompts_output = gr.Markdown(label="Sora 2.0 提示词")
            sora_queue_json = gr.Textbox(
                label="Sora 队列 JSON（可保存后使用 sora_queue.py 执行）",
                lines=8,
            )

            with gr.Row():
                sora_save_queue_btn = gr.Button("💾 保存队列到文件", variant="secondary")
                sora_queue_file_path = gr.Textbox(
                    label="保存路径",
                    placeholder="例如：/path/to/sora_queue.json",
                    scale=3,
                )
            sora_save_status = gr.Markdown()

            gr.Markdown("""
### 执行队列

保存队列文件后，在命令行执行：

```bash
python sora_queue.py /path/to/sora_queue.json
```

或指定输出目录：

```bash
python sora_queue.py /path/to/sora_queue.json --output-dir /path/to/outputs
```
""")

            # 事件绑定
            sora_refresh_saved_btn.click(
                refresh_generated_scripts,
                outputs=[sora_gen_saved_dropdown, sora_saved_status],
            )
            sora_load_saved_btn.click(
                load_saved_generated_script,
                inputs=[sora_gen_saved_dropdown],
                outputs=[
                    gr.Textbox(visible=False),  # gen_output placeholder
                    sora_script_text,
                    gr.Textbox(visible=False),  # topic_input placeholder
                    gr.Textbox(visible=False),  # niche_input3 placeholder
                    gr.Textbox(visible=False),  # req_input placeholder
                    gr.Number(visible=False),   # versions_input placeholder
                    sora_saved_status,
                ],
            )
            sora_split_btn.click(
                build_sora_prompts,
                inputs=[sora_script_text],
                outputs=[sora_prompts_output, sora_queue_json],
            )
            sora_save_queue_btn.click(
                lambda queue_json, file_path: save_sora_queue_to_file(queue_json, file_path),
                inputs=[sora_queue_json, sora_queue_file_path],
                outputs=[sora_save_status],
            )

            gen_btn.click(
                run_generate,
                inputs=[topic_input, niche_input3, req_input, versions_input, api_key_input, base_url_input, model_input, provider_input],
                outputs=[gen_output, gen_saved_dropdown, gen_save_status, saved_script_text, saved_status, versions_list_state, ver_label],
            )

        with gr.Tab("🎯 智能分段+提示词"):
            gr.Markdown("""
## 智能分段 + 视频提示词生成

**新功能：** 独立的两步式工作流，与现有功能完全独立。

### 工作流程
1. **步骤1：智能分段** - 按句子完整性分段，每段约10秒（最长15秒）
2. **步骤2：生成提示词** - AI理解上下文，为每段生成连贯的视频提示词

### 特点
- 考虑句子完整性，不会在句子中间切断
- 支持 Seedance 2.0（最长15秒视频）
- AI智能生成连贯镜头描述
- 可导出到项目队列
""")

            # ========== 步骤1：输入文案 ==========
            gr.Markdown("### 步骤1：输入文案")

            with gr.Row():
                with gr.Column(scale=2):
                    smart_seg_saved_dropdown = gr.Dropdown(
                        label="已保存的文案",
                        choices=generated_script_choices(),
                        interactive=True,
                        scale=3,
                    )
                smart_seg_refresh_saved_btn = gr.Button("刷新列表", scale=1)
                smart_seg_load_saved_btn = gr.Button("载入", variant="primary", scale=1)

            smart_seg_saved_status = gr.Markdown(value=f"已保存 {len(generated_script_choices())} 条文案。")

            smart_seg_input_text = gr.Textbox(
                label="完整文案（可编辑）",
                lines=12,
                placeholder="输入或载入完整文案...",
            )

            # ========== 步骤2：智能分段 ==========
            gr.Markdown("### 步骤2：智能分段")

            with gr.Row():
                smart_seg_method = gr.Radio(
                    label="分段方式",
                    choices=[
                        ("🤖 AI 智能分段（理解语义和情节）", "ai"),
                        ("⚡ 算法分段（快速、基于句子边界）", "algorithm"),
                    ],
                    value="algorithm",
                    scale=2,
                )

            with gr.Row():
                smart_seg_target_duration = gr.Slider(
                    label="目标时长（秒/段）",
                    minimum=5,
                    maximum=15,
                    value=10,
                    step=1,
                )
                smart_seg_max_duration = gr.Slider(
                    label="最大时长（秒/段）",
                    minimum=10,
                    maximum=15,
                    value=15,
                    step=1,
                )
                smart_seg_chars_per_sec = gr.Slider(
                    label="口播速度（字/秒）",
                    minimum=4.0,
                    maximum=8.0,
                    value=6.0,
                    step=0.5,
                )

            smart_seg_segment_btn = gr.Button("🔪 开始智能分段", variant="primary", size="lg")

            smart_seg_result_display = gr.Markdown(label="分段结果")
            smart_seg_result_table = gr.Dataframe(
                headers=["序号", "时间轴", "时长", "字数", "文案预览"],
                label="分段详情",
                interactive=False,
            )
            smart_seg_validation = gr.Markdown(label="验证结果")

            # 隐藏字段：存储分段结果
            smart_seg_segments_json = gr.Textbox(visible=False)

            # ========== 步骤3：生成提示词 ==========
            gr.Markdown("### 步骤3：生成视频提示词")

            with gr.Row():
                smart_seg_channel = gr.Dropdown(
                    label="视觉风格（频道）",
                    choices=get_channel_choices(),
                    value=get_default_channel_id(),
                    scale=3,
                )
                smart_seg_continuity = gr.Checkbox(
                    label="保持场景连贯",
                    value=True,
                    scale=1,
                )

            smart_seg_generate_prompts_btn = gr.Button("🎬 生成视频提示词", variant="primary", size="lg")

            smart_seg_prompts_display = gr.Markdown(label="提示词结果")
            smart_seg_prompts_table = gr.Dataframe(
                headers=["序号", "时间轴", "文案", "提示词"],
                label="提示词详情",
                interactive=False,
            )

            # 隐藏字段：存储提示词结果
            smart_seg_prompts_json = gr.Textbox(visible=False)

            # ========== 步骤4：导出 ==========
            gr.Markdown("### 步骤4：导出到项目")

            with gr.Row():
                smart_seg_project_name = gr.Textbox(
                    label="项目名称",
                    placeholder="留空则自动生成",
                    scale=2,
                )
                smart_seg_ratio = gr.Dropdown(
                    label="视频比例",
                    choices=["9:16", "16:9", "1:1"],
                    value="16:9",
                    scale=1,
                )
                smart_seg_model = gr.Dropdown(
                    label="模型版本",
                    choices=["seedance2.0", "seedance2.0fast", "seedance2.0_vip", "seedance2.0fast_vip"],
                    value="seedance2.0fast",
                    scale=1,
                )

            with gr.Row():
                smart_seg_export_new_btn = gr.Button("📦 导出为新项目", variant="primary")
                smart_seg_export_existing_btn = gr.Button("📥 导入到现有项目", variant="secondary")
                smart_seg_project_dropdown = gr.Dropdown(
                    label="选择项目",
                    choices=project_choices(),
                    value=active_project_id(),
                    scale=2,
                )

            smart_seg_export_status = gr.Markdown()

            # ========== 事件绑定 ==========

            # 刷新和载入文案
            smart_seg_refresh_saved_btn.click(
                refresh_generated_scripts,
                outputs=[smart_seg_saved_dropdown, smart_seg_saved_status],
            )

            smart_seg_load_saved_btn.click(
                load_saved_generated_script,
                inputs=[smart_seg_saved_dropdown],
                outputs=[
                    gr.Textbox(visible=False),  # gen_output placeholder
                    smart_seg_input_text,
                    gr.Textbox(visible=False),  # topic_input placeholder
                    gr.Textbox(visible=False),  # niche_input3 placeholder
                    gr.Textbox(visible=False),  # req_input placeholder
                    gr.Number(visible=False),   # versions_input placeholder
                    smart_seg_saved_status,
                ],
            )

            # 智能分段
            def do_smart_segment(text, method, target_duration, max_duration, chars_per_sec, provider_id):
                if not text or not text.strip():
                    return "❌ 请先输入文案", [], "❌ 没有分段结果", ""

                try:
                    if method == "ai":
                        # AI 智能分段
                        from viral_agent.text_segmenter import segment_by_sentences_ai
                        segments = segment_by_sentences_ai(
                            text=text,
                            target_duration=int(target_duration),
                            max_duration=int(max_duration),
                            chars_per_second=float(chars_per_sec),
                            provider_id=provider_id,
                        )
                    else:
                        # 算法分段
                        segments = segment_by_sentences(
                            text=text,
                            target_duration=int(target_duration),
                            max_duration=int(max_duration),
                            chars_per_second=float(chars_per_sec),
                        )

                    if not segments:
                        return "❌ 分段失败，请检查文案内容", [], "❌ 没有分段结果", ""

                    display = format_segments_for_display(segments)
                    table = segments_to_table_data(segments)
                    validation = validate_segments(segments, max_duration=int(max_duration))

                    method_name = "🤖 AI 智能分段" if method == "ai" else "⚡ 算法分段"
                    validation_text = f"**分段方式：** {method_name}\n\n"
                    validation_text += f"**验证结果：** {'✅ 通过' if validation['valid'] else '⚠️ 有警告'}\n\n"
                    validation_text += f"**统计：** {validation['stats']['total_segments']}段 | "
                    validation_text += f"总时长 {validation['stats']['total_duration']}秒 | "
                    validation_text += f"平均 {validation['stats']['avg_duration']}秒/段\n\n"

                    if validation['warnings']:
                        validation_text += "**警告：**\n"
                        for warning in validation['warnings']:
                            validation_text += f"- {warning}\n"

                    segments_json = json.dumps(segments, ensure_ascii=False)

                    return display, table, validation_text, segments_json

                except Exception as exc:
                    return f"❌ 分段失败：{exc}", [], f"❌ 错误：{exc}", ""

            smart_seg_segment_btn.click(
                do_smart_segment,
                inputs=[smart_seg_input_text, smart_seg_method, smart_seg_target_duration, smart_seg_max_duration, smart_seg_chars_per_sec, provider_input],
                outputs=[smart_seg_result_display, smart_seg_result_table, smart_seg_validation, smart_seg_segments_json],
            )

            # 生成提示词
            def do_generate_prompts(segments_json, full_text, channel_id, continuity, provider_id):
                if not segments_json or not segments_json.strip():
                    return "❌ 请先完成智能分段", [], ""

                try:
                    segments = json.loads(segments_json)
                    if not segments:
                        return "❌ 分段数据为空", [], ""

                    prompts = generate_video_prompts(
                        segments=segments,
                        full_context=full_text,
                        channel_id=channel_id,
                        scene_continuity=continuity,
                        provider_id=provider_id,
                    )

                    if not prompts:
                        return "❌ 提示词生成失败", [], ""

                    display = format_prompts_for_display(prompts)
                    table = prompts_to_table_data(prompts)
                    prompts_json = json.dumps(prompts, ensure_ascii=False)

                    return display, table, prompts_json

                except json.JSONDecodeError:
                    return "❌ 分段数据格式错误", [], ""
                except Exception as exc:
                    return f"❌ 生成失败：{exc}", [], ""

            smart_seg_generate_prompts_btn.click(
                do_generate_prompts,
                inputs=[smart_seg_segments_json, smart_seg_input_text, smart_seg_channel, smart_seg_continuity, provider_input],
                outputs=[smart_seg_prompts_display, smart_seg_prompts_table, smart_seg_prompts_json],
            )

            # 导出为新项目
            def do_export_new_project(prompts_json, project_name, script, ratio, model):
                if not prompts_json or not prompts_json.strip():
                    return gr.update(), "❌ 请先生成提示词"

                try:
                    prompts = json.loads(prompts_json)
                    if not prompts:
                        return gr.update(), "❌ 提示词数据为空"

                    name = str(project_name or "").strip() or default_seedance_project_name(script)
                    project = create_web_project(name, description="智能分段+提示词自动创建")

                    queue_data = export_to_seedance_queue(
                        prompts=prompts,
                        project_name=name,
                        ratio=ratio,
                        model_version=model,
                    )
                    queue_data["created_at"] = datetime.now().isoformat(timespec="seconds")

                    queue_path = project_queue_path(str(project["id"]))
                    save_json(queue_path, queue_data)

                    choices = project_choices()
                    status = f"✅ 已创建新项目「{project['name']}」\n\n"
                    status += f"- 项目ID: {project['id']}\n"
                    status += f"- 队列文件: {queue_path}\n"
                    status += f"- 片段数: {len(prompts)}\n"

                    return gr.update(choices=choices, value=project["id"]), status

                except json.JSONDecodeError:
                    return gr.update(), "❌ 提示词数据格式错误"
                except Exception as exc:
                    return gr.update(), f"❌ 导出失败：{exc}"

            smart_seg_export_new_btn.click(
                do_export_new_project,
                inputs=[smart_seg_prompts_json, smart_seg_project_name, smart_seg_input_text, smart_seg_ratio, smart_seg_model],
                outputs=[smart_seg_project_dropdown, smart_seg_export_status],
            )

            # 导入到现有项目
            def do_export_existing_project(prompts_json, project_id, ratio, model):
                if not prompts_json or not prompts_json.strip():
                    return "❌ 请先生成提示词"

                try:
                    prompts = json.loads(prompts_json)
                    if not prompts:
                        return "❌ 提示词数据为空"

                    project = project_by_id(project_id or active_project_id())
                    if not project:
                        return "❌ 请先选择项目"

                    queue_path = project_queue_path(str(project["id"]))
                    current = load_json(queue_path, {"version": 1, "segments": []})

                    queue_data = export_to_seedance_queue(
                        prompts=prompts,
                        project_name=project.get("name", ""),
                        ratio=ratio,
                        model_version=model,
                    )

                    current_segments = current.get("segments", [])
                    current_segments.extend(queue_data["segments"])
                    current["segments"] = current_segments
                    current["updated_at"] = datetime.now().isoformat(timespec="seconds")

                    save_json(queue_path, current)

                    status = f"✅ 已导入到项目「{project['name']}」\n\n"
                    status += f"- 新增片段: {len(prompts)}\n"
                    status += f"- 总片段数: {len(current_segments)}\n"
                    status += f"- 队列文件: {queue_path}\n"

                    return status

                except json.JSONDecodeError:
                    return "❌ 提示词数据格式错误"
                except Exception as exc:
                    return f"❌ 导入失败：{exc}"

            smart_seg_export_existing_btn.click(
                do_export_existing_project,
                inputs=[smart_seg_prompts_json, smart_seg_project_dropdown, smart_seg_ratio, smart_seg_model],
                outputs=[smart_seg_export_status],
            )

    gr.Markdown("""
---
**使用流程：** 🎬 转录本地视频 → 🗂️ 检索验证 → ✍️ 生成文案

知识库越丰富（建议每个赛道 30+ 条），生成质量越高
""")


if __name__ == "__main__":
    import os

    # 禁用 Gradio 分析和启动事件检查
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    os.environ["GRADIO_SERVER_NAME"] = "127.0.0.1"
    os.environ["GRADIO_SERVER_PORT"] = "7860"

    # 禁用 httpx 代理（解决 502 问题）
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"
    os.environ["no_proxy"] = "localhost,127.0.0.1"

    try:
        # 使用最简单的启动方式
        demo.launch(
            server_name="127.0.0.1",
            server_port=7860,
            share=False,
            inbrowser=False
        )
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        print("\n尝试备用启动方式...")
        # 备用方案：直接启动服务器
        from gradio import routes
        import uvicorn

        app = routes.App.create_app(demo)
        print("\n✅ 服务器已启动: http://127.0.0.1:7860")
        print("请在浏览器中打开上述地址\n")
        uvicorn.run(app, host="127.0.0.1", port=7860, log_level="info")
