"""Configuration management — reads from env vars and .env file."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from kwb.ai.provider import ProviderConfig

def _load_dotenv(path=None):
    if path is None:
        for c in [Path.cwd(), Path.cwd().parent, Path(__file__).parent.parent.parent.parent]:
            if (c / ".env").exists():
                path = c / ".env"
                break
    if not path or not Path(path).exists():
        return {}
    result = {}
    for line in Path(path).read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip("\"'")
    return result

def _get(key, dotenv, default=""):
    return os.environ.get(key, dotenv.get(key, default))

@dataclass
class KWBConfig:
    gpustack_url: str = ""
    gpustack_key: str = ""
    gpustack_model_text: str = ""
    gpustack_model_vision: str = ""
    batch_size: int = 50
    batch_delay_seconds: float = 0.1
    max_retries: int = 3
    timeout_seconds: int = 120
    language: str = "de"

    @property
    def is_gpustack_configured(self): return bool(self.gpustack_url)

    def to_provider_config(self):
        return ProviderConfig(
            base_url=self.gpustack_url, api_key=self.gpustack_key,
            default_model=self.gpustack_model_text,
            timeout_seconds=self.timeout_seconds, max_retries=self.max_retries,
        )

    def display_safe(self):
        from kwb.core.utils import mask_secret
        return {
            "gpustack_url": self.gpustack_url or "(nicht gesetzt)",
            "gpustack_key": mask_secret(self.gpustack_key),
            "gpustack_model_text": self.gpustack_model_text or "(nicht gesetzt)",
            "gpustack_model_vision": self.gpustack_model_vision or "(nicht gesetzt)",
            "batch_size": str(self.batch_size), "language": self.language,
        }

def load_config(dotenv_path=None):
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
