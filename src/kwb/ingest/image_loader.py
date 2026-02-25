"""
Image ingestion — load images, extract EXIF metadata, prepare for AI vision.

Handles TIFF, JPEG, PNG. Prepares base64-encoded versions for vision models
without requiring Pillow (uses stdlib only, Pillow optional for advanced features).
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ImageProfile:
    """Metadata extracted from an image file."""
    path: str
    filename: str
    file_size_bytes: int
    mime_type: str
    width: int | None = None
    height: int | None = None
    exif: dict[str, Any] = field(default_factory=dict)
    hash_sha256: str = ""
    base64_data: str = ""  # For sending to vision models
    errors: list[str] = field(default_factory=list)


def _detect_mime(path: Path) -> str:
    """Detect MIME type from file extension and magic bytes."""
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime

    # Fallback: check magic bytes
    with open(path, "rb") as f:
        header = f.read(16)

    if header[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    elif header[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    elif header[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return "image/tiff"
    elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"

    return "application/octet-stream"


def _read_jpeg_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Read JPEG dimensions from SOF marker without Pillow."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        i = 2  # skip SOI marker
        while i < len(data) - 1:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xD9:  # EOI
                break
            if marker in (0xC0, 0xC1, 0xC2):  # SOF markers
                height = struct.unpack(">H", data[i + 5:i + 7])[0]
                width = struct.unpack(">H", data[i + 7:i + 9])[0]
                return width, height
            # Skip to next marker
            if i + 3 < len(data):
                length = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + length
            else:
                break
    except Exception:
        pass
    return None, None


def _read_png_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Read PNG dimensions from IHDR chunk."""
    try:
        with open(path, "rb") as f:
            f.read(8)  # Skip signature
            f.read(4)  # Skip IHDR length
            f.read(4)  # Skip IHDR type
            width = struct.unpack(">I", f.read(4))[0]
            height = struct.unpack(">I", f.read(4))[0]
            return width, height
    except Exception:
        return None, None


def _get_dimensions(path: Path, mime: str) -> tuple[int | None, int | None]:
    """Get image dimensions without Pillow."""
    if mime == "image/jpeg":
        return _read_jpeg_dimensions(path)
    elif mime == "image/png":
        return _read_png_dimensions(path)
    # TIFF dimensions require complex parsing — skip for now
    return None, None


def _compute_hash(path: Path) -> str:
    """Compute SHA-256 hash for deduplication."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_image(path: str | Path, load_base64: bool = True) -> ImageProfile:
    """
    Load an image file and extract its metadata.

    Args:
        path: Path to the image file.
        load_base64: If True, load the full image as base64 (needed for vision AI).

    Returns:
        ImageProfile with metadata and optional base64 data.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    mime = _detect_mime(path)
    width, height = _get_dimensions(path, mime)
    file_hash = _compute_hash(path)

    profile = ImageProfile(
        path=str(path),
        filename=path.name,
        file_size_bytes=path.stat().st_size,
        mime_type=mime,
        width=width,
        height=height,
        hash_sha256=file_hash,
    )

    if load_base64:
        raw = path.read_bytes()
        profile.base64_data = base64.b64encode(raw).decode("ascii")

    return profile


def scan_image_directory(
    directory: str | Path,
    extensions: set[str] | None = None,
    load_base64: bool = False,
) -> list[ImageProfile]:
    """
    Scan a directory for image files and profile each one.

    Args:
        directory: Path to scan.
        extensions: File extensions to include (default: common image types).
        load_base64: If True, load base64 for all images (memory-intensive!).
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    if extensions is None:
        extensions = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp"}

    profiles = []
    for p in sorted(directory.rglob("*")):
        if p.is_file() and p.suffix.lower() in extensions:
            try:
                profile = ingest_image(p, load_base64=load_base64)
                profiles.append(profile)
            except Exception as e:
                profiles.append(ImageProfile(
                    path=str(p),
                    filename=p.name,
                    file_size_bytes=0,
                    mime_type="unknown",
                    errors=[str(e)],
                ))

    return profiles
