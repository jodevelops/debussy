# Debussy — Kuratierwerkbank

KI-gestützte Kuratierungswerkbank für GLAM-Sammlungsdaten (Galerien, Bibliotheken, Archive, Museen).
Python 3.10+, MIT-Lizenz, v0.5.2.

## Schnellreferenz

```bash
# Tests ausführen (immer vor Commit!)
PYTHONPATH=src python -m unittest discover tests

# Linting
ruff check src/ tests/

# API-Server starten
PYTHONPATH=src python -m kwb.api.app
# → http://localhost:8765

# CLI
PYTHONPATH=src python -m kwb.cli analyze daten.csv
PYTHONPATH=src python -m kwb.cli plan --top 8
```

## Projektstruktur

```
src/kwb/
├── core/           # Typen (models.py), Config, Workspace-Persistenz
├── ingest/         # CSV/TSV-Loader, Bild-Loader (TIFF/JPEG/PNG)
├── analyze/        # Strukturanalyse (7 Checks), NER, Semantik
├── normalize/      # EDTF-Datumsnormalisierung
├── enrich/         # GND, Geonames (teilweise geplant)
├── export/         # Goobi-XML
├── ai/             # Provider-Abstraktion (GPUStack, Mock), Batch, Prompts
├── report/         # Markdown-Report
├── api/            # FastAPI-Server + Dashboard (Single-Page HTML)
└── cli.py          # Kommandozeile
```

## Architektur-Regeln

- **Provider-Abstraktion**: Alle LLM-Aufrufe über `ai/provider.py`-Interface. GPUStack für Produktion, Mock für Tests.
- **Modularer Aufbau**: Jedes GLAM-Institut nutzt nur, was es braucht.
- **Sprache**: Code auf Englisch, UI/Doku auf Deutsch.
- **Dependencies minimal halten**: Kern nur pandas + pydantic. Extras über optional-dependencies.
- **Tests**: unittest-basiert. Jedes neue Feature braucht Tests.

## Abhängigkeiten

- **Kern**: pandas ≥ 2.0, pydantic ≥ 2.0
- **API**: fastapi, uvicorn, python-multipart
- **AI**: httpx
- **Dev**: pytest, pytest-cov, ruff

## Aktueller Stand

- **Phase 1** (Strukturanalyse): ✅ abgeschlossen
- **Phase 2** (KI-Kern + Bilder): 🟡 in Arbeit
- **Phase 3–5**: geplant (siehe docs/ARCHITECTURE.md)

Detaillierter Feature-Katalog: docs/FUNKTIONSKATALOG.md

## Konventionen

- Ruff Line-Length: 100
- Python Target: 3.10
- PYTHONPATH=src ist nötig zum Ausführen (kein pip install im Dev)
- `.env` für lokale Konfiguration (nie committen), Vorlage: `.env.example`
