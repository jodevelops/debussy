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
    goobi_api_url: str = ""
    goobi_api_key: str = ""
    goobi_project: str = ""
    geonames_username: str = ""
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

    def save_to_dotenv(self, path=None) -> None:
        """Write/update GPUStack vars in a .env file.

        Only the four GPUStack fields are written; all other lines are preserved.
        If *path* is None the same search order as ``_load_dotenv`` is used;
        if no .env exists at all a new one is created in the current directory.
        """
        if path is None:
            for candidate in [Path.cwd(), Path.cwd().parent,
                               Path(__file__).parent.parent.parent.parent]:
                p = candidate / ".env"
                if p.exists():
                    path = p
                    break
            if path is None:
                path = Path.cwd() / ".env"

        path = Path(path)
        mapping = {
            "KWB_GPUSTACK_URL": self.gpustack_url,
            "KWB_GPUSTACK_KEY": self.gpustack_key,
            "KWB_GPUSTACK_MODEL_TEXT": self.gpustack_model_text,
            "KWB_GPUSTACK_MODEL_VISION": self.gpustack_model_vision,
        }

        existing_lines: list[str] = []
        if path.exists():
            existing_lines = path.read_text("utf-8").splitlines()

        updated_keys: set[str] = set()
        new_lines: list[str] = []
        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in mapping:
                    new_lines.append(f"{key}={mapping[key]}")
                    updated_keys.add(key)
                    continue
            new_lines.append(line)

        for key, value in mapping.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}")

        path.write_text("\n".join(new_lines) + "\n", "utf-8")

    def display_safe(self):
        from kwb.core.utils import mask_secret
        return {
            "gpustack_url": self.gpustack_url or "(nicht gesetzt)",
            "gpustack_key": mask_secret(self.gpustack_key),
            "gpustack_model_text": self.gpustack_model_text or "(nicht gesetzt)",
            "gpustack_model_vision": self.gpustack_model_vision or "(nicht gesetzt)",
            "goobi_api_url": self.goobi_api_url or "(nicht gesetzt)",
            "goobi_api_key": mask_secret(self.goobi_api_key),
            "goobi_project": self.goobi_project or "(nicht gesetzt)",
            "batch_size": str(self.batch_size), "language": self.language,
        }

def load_config(dotenv_path=None):
    dotenv = _load_dotenv(dotenv_path)
    return KWBConfig(
        gpustack_url=_get("KWB_GPUSTACK_URL", dotenv),
        gpustack_key=_get("KWB_GPUSTACK_KEY", dotenv),
        gpustack_model_text=_get("KWB_GPUSTACK_MODEL_TEXT", dotenv),
        gpustack_model_vision=_get("KWB_GPUSTACK_MODEL_VISION", dotenv),
        geonames_username=_get("KWB_GEONAMES_USERNAME", dotenv),
        goobi_api_url=_get("KWB_GOOBI_API_URL", dotenv),
        goobi_api_key=_get("KWB_GOOBI_API_KEY", dotenv),
        goobi_project=_get("KWB_GOOBI_PROJECT", dotenv),
        batch_size=int(_get("KWB_BATCH_SIZE", dotenv, "50")),
        batch_delay_seconds=float(_get("KWB_BATCH_DELAY", dotenv, "0.1")),
        max_retries=int(_get("KWB_MAX_RETRIES", dotenv, "3")),
        timeout_seconds=int(_get("KWB_TIMEOUT", dotenv, "120")),
        language=_get("KWB_LANGUAGE", dotenv, "de"),
    )
