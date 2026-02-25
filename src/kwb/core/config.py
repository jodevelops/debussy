"""
Configuration management.

Reads settings from (in order of priority):
1. Environment variables (KWB_GPUSTACK_URL, KWB_GPUSTACK_KEY, etc.)
2. .env file in project root
3. Defaults

API keys are NEVER hardcoded or logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from kwb.ai.provider import ProviderConfig


def _load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Minimal .env parser — no external dependency needed."""
    if path is None:
        # Walk up from CWD to find .env
        for candidate in [Path.cwd(), Path.cwd().parent, Path(__file__).parent.parent.parent.parent]:
            env_file = candidate / ".env"
            if env_file.exists():
                path = env_file
                break

    if path is None or not path.exists():
        return {}

    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            result[key] = value
    return result


def _get(key: str, dotenv: dict[str, str], default: str = "") -> str:
    """Get a config value: env var > .env > default."""
    return os.environ.get(key, dotenv.get(key, default))


@dataclass
class KWBConfig:
    """Central configuration for the Kuratierwerkbank."""

    # GPUStack / AI provider
    gpustack_url: str = ""
    gpustack_key: str = ""
    gpustack_model_text: str = ""
    gpustack_model_vision: str = ""

    # Processing
    batch_size: int = 50
    batch_delay_seconds: float = 0.1
    max_retries: int = 3
    timeout_seconds: int = 120

    # Output
    language: str = "de"

    @property
    def is_gpustack_configured(self) -> bool:
        return bool(self.gpustack_url)

    def to_provider_config(self) -> ProviderConfig:
        """Convert to a ProviderConfig for the AI provider."""
        return ProviderConfig(
            base_url=self.gpustack_url,
            api_key=self.gpustack_key,
            default_model=self.gpustack_model_text,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
        )

    def display_safe(self) -> dict[str, str]:
        """Return config as dict with secrets masked."""
        return {
            "gpustack_url": self.gpustack_url or "(nicht gesetzt)",
            "gpustack_key": "***" if self.gpustack_key else "(nicht gesetzt)",
            "gpustack_model_text": self.gpustack_model_text or "(nicht gesetzt)",
            "gpustack_model_vision": self.gpustack_model_vision or "(nicht gesetzt)",
            "batch_size": str(self.batch_size),
            "language": self.language,
        }


def load_config(dotenv_path: Path | None = None) -> KWBConfig:
    """Load configuration from environment and .env file."""
    dotenv = _load_dotenv(dotenv_path)

    return KWBConfig(
        gpustack_url=_get("KWB_GPUSTACK_URL", dotenv),
        gpustack_key=_get("KWB_GPUSTACK_KEY", dotenv),
        gpustack_model_text=_get("KWB_GPUSTACK_MODEL_TEXT", dotenv),
        gpustack_model_vision=_get("KWB_GPUSTACK_MODEL_VISION", dotenv),
        batch_size=int(_get("KWB_BATCH_SIZE", dotenv, "50")),
        batch_delay_seconds=float(_get("KWB_BATCH_DELAY", dotenv, "0.1")),
        max_retries=int(_get("KWB_MAX_RETRIES", dotenv, "3")),
        timeout_seconds=int(_get("KWB_TIMEOUT", dotenv, "120")),
        language=_get("KWB_LANGUAGE", dotenv, "de"),
    )
