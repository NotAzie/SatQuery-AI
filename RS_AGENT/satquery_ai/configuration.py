"""Configuration loading for SatQuery AI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the application configuration and apply environment overrides."""
    load_dotenv(PROJECT_ROOT / ".env")
    config_file = Path(config_path) if config_path else PROJECT_ROOT / "configs" / "default.yaml"
    with open(config_file, encoding="utf-8") as config_stream:
        config = yaml.safe_load(config_stream)

    config["embedding"]["model"] = os.getenv("EMBEDDING_MODEL", config["embedding"]["model"])
    config["embedding"]["device"] = os.getenv("EMBEDDING_DEVICE", config["embedding"]["device"])

    llm_config = config.setdefault("llm", {})
    if os.getenv("LLM_PROVIDER"):
        llm_config["provider"] = os.getenv("LLM_PROVIDER")
    if os.getenv("LLM_MODEL"):
        llm_config["model"] = os.getenv("LLM_MODEL")
    if llm_config.get("provider") == "groq" and llm_config.get("model") in {
        "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
    }:
        llm_config["model"] = "openai/gpt-oss-20b"

    api_key = os.getenv("GROQ_API_KEY") if llm_config.get("provider") == "groq" else None
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if api_key:
        llm_config["api_key"] = api_key
    if os.getenv("OPENAI_API_BASE"):
        llm_config["api_base"] = os.getenv("OPENAI_API_BASE")
    elif llm_config.get("provider") == "groq":
        llm_config["api_base"] = "https://api.groq.com/openai/v1"
    return config


def resolve_path(path: str | Path) -> Path:
    """Resolve a path relative to the SatQuery AI project root."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate