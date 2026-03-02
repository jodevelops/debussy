"""
Shared state and dependency helpers for Debussy API routes.

Centralises:
  - _state dict (datasets, workspace, config, report)
  - _cfg()   — cached config loader
  - _prov()  — AI provider factory
  - _ws()    — current workspace accessor
  - security constants

All route modules import from here instead of duplicating state.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from kwb.core.config import load_config
from kwb.core.workspace import Workspace

# ---------------------------------------------------------------------------
# Security limits (module-level constants — importable, not hardcoded per file)
# ---------------------------------------------------------------------------
MAX_UPLOAD_FILES = 10
MAX_FILE_BYTES = 50 * 1024 * 1024       # 50 MB
MAX_WORKSPACE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_CSV_ROWS = 500_000
MAX_CSV_COLS = 200
ALLOWED_EXTENSIONS = {".csv", ".tsv"}
ALLOWED_WS_EXT = {".json"}
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

# ---------------------------------------------------------------------------
# Workspace storage directory
# ---------------------------------------------------------------------------
_WORKSPACE_DIR = Path(os.environ.get(
    "KWB_WORKSPACE_DIR",
    str(Path(tempfile.gettempdir()) / "debussy_workspaces"),
))
_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


def workspace_dir() -> Path:
    return _WORKSPACE_DIR


def safe_filename(name: str, ext: str = ".debussy.json") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())[:80]
    safe = re.sub(r"\.{2,}", ".", safe)
    safe = safe.strip("._- ")
    if not safe:
        safe = "project"
    return safe + ext


# ---------------------------------------------------------------------------
# Shared in-process state
# (In a multi-worker deployment this should move to Redis/DB, but fine for v0.5)
# ---------------------------------------------------------------------------
_state: dict[str, Any] = {
    "datasets": {},
    "report": None,
    "config": None,
    "workspace": Workspace(name="default"),
}


def get_state() -> dict[str, Any]:
    return _state


def get_datasets() -> dict:
    return _state["datasets"]


def get_workspace() -> Workspace:
    return _state["workspace"]


def set_workspace(ws: Workspace) -> None:
    _state["workspace"] = ws


# ---------------------------------------------------------------------------
# Config (cached)
# ---------------------------------------------------------------------------
_config_cache = None


def get_config():
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------
def get_provider(model: str = ""):
    """Build AI provider: GPUStack if configured, else MockProvider."""
    from kwb.ai.gpustack import GPUStackProvider
    from kwb.ai.mock import MockProvider

    c = get_config()
    if c.is_gpustack_configured:
        pc = c.to_provider_config()
        if model:
            pc.default_model = model
        return GPUStackProvider(pc)
    return MockProvider.with_defaults()
