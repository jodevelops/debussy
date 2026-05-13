"""
PDF Ingest — convert PDF pages to base64 images for vision AI analysis.

Each page is rendered as a PNG image and returned as an ImageProfile
with base64_data populated, suitable for sending to vision LLM models.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PAGES = 200


class PDFLoadError(Exception):
    """Raised when a PDF cannot be processed."""


def pdf_to_images(
    path: str | Path,
    max_pages: int = MAX_PAGES,
    dpi: int = 150,
) -> list:
    """Convert PDF pages to ImageProfile objects with base64 data.

    Returns a list of ImageProfile objects, one per page.
    Requires pypdf for metadata; uses pdf2image or a fallback
    for page rendering.
    """

    path = Path(path)
    if not path.exists():
        raise PDFLoadError(f"File not found: {path}")

    if path.suffix.lower() != ".pdf":
        raise PDFLoadError(f"Not a PDF file: {path.suffix}")

    # Try pdf2image (poppler-based, best quality). If pdf2image is installed
    # but the poppler binary is missing from PATH (#210), convert_from_path
    # raises at runtime — fall back to pypdf rather than surfacing the
    # poppler error to the user.
    try:
        from pdf2image import convert_from_path  # noqa: F401
        pdf2image_available = True
    except ImportError:
        pdf2image_available = False

    if pdf2image_available:
        try:
            return _load_with_pdf2image(path, max_pages, dpi)
        except Exception as e:
            # PDFInfoNotInstalledError, PDFPageCountError, etc. all stem from
            # poppler being unreachable. Log and fall through to pypdf.
            logger.warning(
                "pdf2image rendering failed (%s); falling back to pypdf. "
                "Install poppler-utils to enable PDF → image rendering.",
                e,
            )

    # Fallback: pypdf for page count + basic extraction
    try:
        import pypdf  # noqa: F401
        return _load_with_pypdf(path, max_pages)
    except ImportError:
        pass

    raise PDFLoadError(
        "PDF support requires pdf2image (with poppler) or pypdf: "
        "pip install pypdf  oder  pip install pdf2image + Poppler-Binary."
    )


def _load_with_pdf2image(
    path: Path, max_pages: int, dpi: int,
) -> list:
    """Render PDF pages as images using pdf2image (poppler)."""
    from pdf2image import convert_from_path
    from kwb.ingest.image_loader import ImageProfile

    images = convert_from_path(
        str(path), dpi=dpi, first_page=1,
        last_page=min(max_pages, 9999),
        fmt="png",
    )

    profiles = []
    for i, img in enumerate(images):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        sha = hashlib.sha256(png_bytes).hexdigest()
        b64 = base64.b64encode(png_bytes).decode("ascii")

        profiles.append(ImageProfile(
            path=str(path),
            filename=f"{path.stem}_page_{i + 1}.png",
            file_size_bytes=len(png_bytes),
            mime_type="image/png",
            width=img.width,
            height=img.height,
            hash_sha256=sha,
            base64_data=b64,
        ))

    logger.info(f"PDF {path.name}: rendered {len(profiles)} pages as PNG")
    return profiles


def _load_with_pypdf(path: Path, max_pages: int) -> list:
    """Minimal PDF page extraction using pypdf (no image rendering).

    Creates placeholder ImageProfile objects with page metadata.
    For actual image analysis, pdf2image with poppler is recommended.
    """
    import pypdf
    from kwb.ingest.image_loader import ImageProfile

    reader = pypdf.PdfReader(str(path))
    page_count = min(len(reader.pages), max_pages)

    profiles = []
    file_bytes = path.read_bytes()
    sha = hashlib.sha256(file_bytes).hexdigest()
    b64 = base64.b64encode(file_bytes).decode("ascii")

    for i in range(page_count):
        page = reader.pages[i]
        mb = page.mediabox

        profiles.append(ImageProfile(
            path=str(path),
            filename=f"{path.stem}_page_{i + 1}.pdf",
            file_size_bytes=len(file_bytes),
            mime_type="application/pdf",
            width=int(float(mb.width)) if mb else None,
            height=int(float(mb.height)) if mb else None,
            hash_sha256=sha,
            base64_data=b64 if i == 0 else "",
        ))

    logger.info(
        f"PDF {path.name}: extracted {len(profiles)} page metadata (pypdf)"
    )
    return profiles
