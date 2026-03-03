"""Kuratierwerkbank — AI-assisted curation workbench for GLAM collection data."""

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("debussy")
    except PackageNotFoundError:
        __version__ = "0.5.1"  # fallback for dev installs
except ImportError:
    __version__ = "0.5.1"
