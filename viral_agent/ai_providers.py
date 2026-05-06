"""
AI provider configuration.

Supports legacy ANTHROPIC_* env vars and multiple named providers from .env:

AI_PROVIDER_DEFAULT=codesome
AI_PROVIDERS=codesome,yunwu
AI_PROVIDER_CODESOME_NAME=Codesome
AI_PROVIDER_CODESOME_BASE_URL=https://v3.codesome.cn
AI_PROVIDER_CODESOME_API_KEY=sk-...
AI_PROVIDER_CODESOME_MODEL=claude-sonnet-4-6
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass
class AIProvider:
    id: str
    name: str
    api_key: str
    base_url: str
    model: str = DEFAULT_MODEL


def load_dotenv_file(path: Path = ENV_FILE) -> None:
    """Lightweight .env loader that does not overwrite existing env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _provider_ids_from_env() -> list[str]:
    explicit = os.getenv("AI_PROVIDERS", "")
    ids = [item.strip().lower() for item in explicit.split(",") if item.strip()]
    found = set(ids)
    pattern = re.compile(r"^AI_PROVIDER_([A-Z0-9_]+)_API_KEY$")
    for key in os.environ:
        match = pattern.match(key)
        if match:
            found.add(match.group(1).lower())
    return sorted(found)


def _provider_from_id(provider_id: str) -> AIProvider | None:
    suffix = re.sub(r"[^A-Za-z0-9_]+", "_", provider_id).upper()
    api_key = os.getenv(f"AI_PROVIDER_{suffix}_API_KEY", "").strip()
    base_url = os.getenv(f"AI_PROVIDER_{suffix}_BASE_URL", "").strip()
    if not api_key or not base_url:
        return None
    return AIProvider(
        id=provider_id.lower(),
        name=os.getenv(f"AI_PROVIDER_{suffix}_NAME", provider_id).strip() or provider_id,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=os.getenv(f"AI_PROVIDER_{suffix}_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
    )


def list_providers() -> list[AIProvider]:
    load_dotenv_file()
    providers: list[AIProvider] = []
    seen: set[str] = set()
    has_explicit_providers = bool(os.getenv("AI_PROVIDERS", "").strip())

    legacy_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    legacy_base = os.getenv("ANTHROPIC_BASE_URL", "").strip()
    if legacy_key and legacy_base and not has_explicit_providers:
        providers.append(
            AIProvider(
                id="legacy",
                name=os.getenv("AI_PROVIDER_LEGACY_NAME", "当前 .env 默认"),
                api_key=legacy_key,
                base_url=legacy_base.rstrip("/"),
                model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            )
        )
        seen.add("legacy")

    for provider_id in _provider_ids_from_env():
        if provider_id in seen:
            continue
        provider = _provider_from_id(provider_id)
        if provider:
            providers.append(provider)
            seen.add(provider.id)
    return providers


def get_provider(provider_id: str | None = None) -> AIProvider:
    providers = list_providers()
    if not providers:
        raise ValueError("没有可用 AI Provider，请配置 ANTHROPIC_* 或 AI_PROVIDER_*")

    wanted = (provider_id or os.getenv("AI_PROVIDER_SELECTED") or os.getenv("AI_PROVIDER_DEFAULT") or "").strip().lower()
    if wanted:
        for provider in providers:
            if provider.id == wanted:
                return provider
    return providers[0]


def apply_provider(provider_id: str | None = None) -> AIProvider:
    provider = get_provider(provider_id)
    os.environ["AI_PROVIDER_SELECTED"] = provider.id
    os.environ["ANTHROPIC_API_KEY"] = provider.api_key
    os.environ["ANTHROPIC_BASE_URL"] = provider.base_url
    os.environ["ANTHROPIC_MODEL"] = provider.model
    os.environ["CLAUDE_MODEL"] = provider.model
    return provider


def provider_choices() -> list[tuple[str, str]]:
    choices = []
    for provider in list_providers():
        choices.append((f"{provider.name} · {provider.model}", provider.id))
    return choices


def masked_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"
