"""
System-Check — probe optional dependencies and report capability status.

Issue #180: A user installs Debussy and tries to load a PDF, gets ``PDFLoadError``.
They install ``pypdf``, try again, get a "fallback" pseudo-result. They install
``pdf2image``, get ``cannot import name 'convert_from_path'`` because they
need *poppler* on the system too. Each step is a separate friction-fail loop.

This module probes for every optional capability once and surfaces install
instructions. CLI and API both expose it so the user sees the full picture
before they hit the first error.
"""
from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import asdict, dataclass, field
from typing import Literal

ProbeStatus = Literal["ok", "warn", "missing"]


@dataclass
class Probe:
    """Result of a single capability check."""
    name: str
    capability: str
    status: ProbeStatus
    message: str
    version: str | None = None
    install_hint: str | None = None
    docs_url: str | None = None
    related_issues: list[str] = field(default_factory=list)


def _import_version(module_name: str) -> str | None:
    """Best-effort version lookup for an installed module."""
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return None
    for attr in ("__version__", "VERSION", "version"):
        v = getattr(mod, attr, None)
        if v is None:
            continue
        if isinstance(v, str):
            return v
        try:
            return ".".join(str(p) for p in v)
        except TypeError:
            return str(v)
    return None


def check_python() -> Probe:
    """Python version itself (must be >= 3.10 per project policy)."""
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 10):
        return Probe(
            name="Python", capability="Runtime",
            status="ok", version=version,
            message=f"Python {version}",
        )
    return Probe(
        name="Python", capability="Runtime",
        status="missing", version=version,
        message=f"Python {version} ist zu alt; mindestens 3.10 erforderlich.",
        install_hint="Installiere Python 3.10 oder neuer.",
    )


def check_chardet() -> Probe:
    """Encoding detection (#166)."""
    version = _import_version("chardet")
    if version:
        return Probe(
            name="chardet", capability="Encoding-Erkennung",
            status="ok", version=version,
            message="Encoding wird zuverlässig erkannt.",
        )
    return Probe(
        name="chardet", capability="Encoding-Erkennung",
        status="warn",
        message="Ohne chardet fällt der CSV-Import still auf 'utf-8' zurück — "
                "Mojibake bei Latin-1-Dateien möglich.",
        install_hint="pip install chardet",
        related_issues=["#166"],
    )


def check_openpyxl() -> Probe:
    """XLSX support."""
    version = _import_version("openpyxl")
    if version:
        return Probe(
            name="openpyxl", capability="XLSX-Import",
            status="ok", version=version,
            message="Excel-Dateien (.xlsx) können geladen werden.",
        )
    return Probe(
        name="openpyxl", capability="XLSX-Import",
        status="missing",
        message="Excel-Dateien können nicht geladen werden.",
        install_hint="pip install openpyxl",
    )


def check_pypdf() -> Probe:
    """PDF text extraction fallback."""
    version = _import_version("pypdf")
    if version:
        return Probe(
            name="pypdf", capability="PDF-Text (Fallback)",
            status="ok", version=version,
            message="PDF-Seiten zählen und Text extrahieren funktioniert "
                    "(ohne Bild-Rendering).",
        )
    return Probe(
        name="pypdf", capability="PDF-Text (Fallback)",
        status="warn",
        message="Ohne pypdf gibt es keinen reinen Python-Fallback für PDFs; "
                "wenn auch pdf2image+poppler fehlt, scheitert der PDF-Import.",
        install_hint="pip install pypdf",
    )


def check_pdf2image_poppler() -> Probe:
    """High-quality PDF rendering: needs pdf2image AND poppler binary."""
    py_version = _import_version("pdf2image")
    poppler = shutil.which("pdftoppm")

    if py_version and poppler:
        return Probe(
            name="pdf2image + poppler", capability="PDF → Bild-Rendering",
            status="ok", version=f"{py_version} (pdftoppm: {poppler})",
            message="PDFs werden als hochauflösende Bilder gerendert.",
        )
    if py_version and not poppler:
        return Probe(
            name="pdf2image + poppler", capability="PDF → Bild-Rendering",
            status="warn", version=py_version,
            message="pdf2image ist installiert, aber das Poppler-System-Binary "
                    "'pdftoppm' wurde nicht in PATH gefunden. PDF-Rendering "
                    "scheitert zur Laufzeit; Fallback auf pypdf (nur Text) "
                    "wird verwendet.",
            install_hint=(
                "Linux: sudo apt-get install poppler-utils  |  "
                "macOS: brew install poppler  |  "
                "Windows: https://github.com/oschwartz10612/poppler-windows"
            ),
            related_issues=["#210"],
        )
    if not py_version and poppler:
        return Probe(
            name="pdf2image + poppler", capability="PDF → Bild-Rendering",
            status="warn",
            message="Poppler ist verfügbar, aber das pdf2image-Python-Paket fehlt.",
            install_hint="pip install pdf2image",
        )
    return Probe(
        name="pdf2image + poppler", capability="PDF → Bild-Rendering",
        status="missing",
        message="Kein hochwertiges PDF-Rendering möglich. Falls pypdf installiert "
                "ist, funktioniert ein einfacher Text-Fallback.",
        install_hint=(
            "pip install pdf2image  +  Poppler-Binary "
            "(Linux: apt install poppler-utils, macOS: brew install poppler)"
        ),
        related_issues=["#210"],
    )


def check_fastapi() -> Probe:
    """API server."""
    version = _import_version("fastapi")
    if version:
        return Probe(
            name="fastapi", capability="API-Server",
            status="ok", version=version,
            message="Web-Dashboard und REST-Endpoints stehen bereit.",
        )
    return Probe(
        name="fastapi", capability="API-Server",
        status="missing",
        message="API-Server kann nicht gestartet werden.",
        install_hint="pip install fastapi uvicorn python-multipart",
    )


def check_httpx() -> Probe:
    """HTTP client used by all AI providers."""
    version = _import_version("httpx")
    if version:
        return Probe(
            name="httpx", capability="LLM-Provider-HTTP",
            status="ok", version=version,
            message="GPUStack/Ollama/OpenAI-kompatible APIs sind erreichbar.",
        )
    return Probe(
        name="httpx", capability="LLM-Provider-HTTP",
        status="missing",
        message="Keine LLM-Provider erreichbar.",
        install_hint="pip install httpx",
    )


def check_spacy_de() -> Probe:
    """SpaCy plus the German large model for hybrid NER."""
    spacy_version = _import_version("spacy")
    if not spacy_version:
        return Probe(
            name="spaCy + de_core_news_lg", capability="NER (SpaCy-Baseline)",
            status="warn",
            message="Ohne spaCy steht der LLM-Pfad weiter zur Verfügung, "
                    "aber der schnellere SpaCy-Hybrid-Modus nicht.",
            install_hint=(
                "pip install spacy  und  "
                "python -m spacy download de_core_news_lg"
            ),
        )
    try:
        import spacy
        spacy.load("de_core_news_lg")
        return Probe(
            name="spaCy + de_core_news_lg", capability="NER (SpaCy-Baseline)",
            status="ok", version=spacy_version,
            message="Deutsches Modell 'de_core_news_lg' geladen.",
        )
    except OSError:
        return Probe(
            name="spaCy + de_core_news_lg", capability="NER (SpaCy-Baseline)",
            status="warn", version=spacy_version,
            message="spaCy installiert, aber Modell 'de_core_news_lg' fehlt.",
            install_hint="python -m spacy download de_core_news_lg",
        )


_PROBES = (
    check_python,
    check_fastapi,
    check_httpx,
    check_chardet,
    check_openpyxl,
    check_pypdf,
    check_pdf2image_poppler,
    check_spacy_de,
)


def run_system_check() -> dict:
    """Run all probes and return a serializable report.

    Returns:
        {
            "probes": [Probe.asdict(), ...],
            "summary": {"ok": n, "warn": n, "missing": n},
            "overall_status": "ok" | "warn" | "missing",
        }
    """
    probes = [p() for p in _PROBES]
    counts = {"ok": 0, "warn": 0, "missing": 0}
    for p in probes:
        counts[p.status] += 1
    if counts["missing"] > 0:
        overall = "missing"
    elif counts["warn"] > 0:
        overall = "warn"
    else:
        overall = "ok"
    return {
        "probes": [asdict(p) for p in probes],
        "summary": counts,
        "overall_status": overall,
    }


def render_text(report: dict) -> str:
    """Render the report as a human-readable text block (used by CLI)."""
    icons = {"ok": "✓", "warn": "⚠", "missing": "✗"}
    lines = ["Debussy — System-Check", "=" * 60]
    for p in report["probes"]:
        icon = icons.get(p["status"], "?")
        line = f"  {icon} {p['name']:<28} {p['capability']}"
        if p.get("version"):
            line += f"  ({p['version']})"
        lines.append(line)
        lines.append(f"      → {p['message']}")
        if p["status"] != "ok" and p.get("install_hint"):
            lines.append(f"      Install: {p['install_hint']}")
        if p.get("related_issues"):
            lines.append(f"      Related: {', '.join(p['related_issues'])}")
    s = report["summary"]
    lines.append("=" * 60)
    lines.append(
        f"  Status: {report['overall_status'].upper()}  "
        f"(ok: {s['ok']}, warn: {s['warn']}, missing: {s['missing']})"
    )
    return "\n".join(lines)
