# Kuratierwerkbank — Architektur & Roadmap

## Vollständige Vision

```
src/kwb/
│
├── core/                    # Gemeinsame Typen, Config, Registry
│   ├── models.py            # ✅ v0.1 — Finding, Profile, Report
│   ├── config.py            # 🔲 v0.2 — Zentrale Konfiguration
│   └── registry.py          # 🔲 v0.2 — Plugin-Registrierung für Checks
│
├── ingest/                  # Datenimport — ein Loader pro Format
│   ├── csv_loader.py        # ✅ v0.1 — CSV/TSV
│   ├── image_loader.py      # 🔲 v0.2 — TIFF/JPEG/PNG → Thumbnail + EXIF
│   ├── xml_loader.py        # 🔲 v0.3 — METS/MODS, LIDO, EAD
│   ├── pdf_loader.py        # 🔲 v0.4 — PDF → Text + Seitenbilder
│   └── media_loader.py      # 🔲 v0.5 — Video/Audio → Keyframes + Metadaten
│
├── analyze/                 # Analyse — regelbasiert + KI
│   ├── structural.py        # ✅ v0.1 — 7 regelbasierte Checks
│   ├── semantic.py          # 🔲 v0.2 — LLM-gestützte Klassifikation
│   ├── visual.py            # 🔲 v0.2 — Vision-Modell: Bildbeschreibung
│   ├── ocr.py               # 🔲 v0.3 — OCR/HTR auf Bildern + PDFs
│   └── cross_modal.py       # 🔲 v0.4 — Bild↔Metadaten-Konsistenz
│
├── enrich/                  # Normdaten-Anreicherung
│   ├── gnd.py               # 🔲 v0.2 — GND-API Batch-Lookup
│   ├── wikidata.py          # 🔲 v0.3 — Wikidata SPARQL
│   ├── geonames.py          # 🔲 v0.3 — Geo-Koordinaten
│   └── iconclass.py         # 🔲 v0.4 — Ikonographische Klassifikation
│
├── export/                  # Zielformat-Export
│   ├── csv_export.py        # 🔲 v0.2 — Bereinigte CSV (Goobi-kompatibel)
│   ├── mets_mods.py         # 🔲 v0.3 — METS/MODS-XML
│   ├── jsonld.py            # 🔲 v0.4 — JSON-LD (Linked Open Data)
│   └── goobi_api.py         # 🔲 v0.5 — Direkte Goobi REST-API
│
├── ai/                      # KI-Abstraktionsschicht
│   ├── provider.py          # 🔲 v0.2 — Interface für alle LLM-Provider
│   ├── gpustack.py          # 🔲 v0.2 — GPUStack (OpenAI-kompatibel)
│   ├── ollama.py            # 🔲 v0.2 — Ollama-Fallback
│   ├── prompts.py           # 🔲 v0.2 — Prompt-Templates für GLAM
│   └── batch.py             # 🔲 v0.2 — Batch-Verarbeitung mit Retry
│
├── report/                  # Berichtsgenerierung
│   ├── markdown.py          # ✅ v0.1 — Markdown-Report
│   └── html.py              # 🔲 v0.3 — Interaktiver HTML-Report
│
├── api/                     # Web-Interface
│   ├── app.py               # 🔲 v0.3 — FastAPI-Server
│   ├── routes.py            # 🔲 v0.3 — REST-Endpoints
│   └── websocket.py         # 🔲 v0.3 — Live-Progress für Batch-Jobs
│
└── cli.py                   # ✅ v0.1 — Kommandozeile
```

## Phasenplan

### Phase 1 — Strukturanalyse (✅ abgeschlossen)
- CSV-Ingest mit Encoding-Erkennung
- 7 regelbasierte Qualitäts-Checks
- GND-Abdeckungsanalyse
- Cross-File-Linkage
- Markdown-Report
- 18 Tests, alle grün
- **Ergebnis:** 161 Findings auf 8.308 GIUB-Records

### Phase 2 — KI-Kern + Bilder (nächster Schritt)
**Ziel:** Beweisen, dass lokale LLMs für GLAM-Metadaten taugen.

Module:
- `ai/provider.py` — Abstrakte Schnittstelle (Provider-unabhängig)
- `ai/gpustack.py` — GPUStack via OpenAI-kompatible API
- `ai/ollama.py` — Ollama als Fallback/Entwicklungs-Provider  
- `ai/prompts.py` — GLAM-spezifische Prompt-Templates
- `ai/batch.py` — Batch-Verarbeitung mit Rate-Limiting
- `ingest/image_loader.py` — Bilder laden, EXIF extrahieren
- `analyze/semantic.py` — LLM klassifiziert Metadaten
- `analyze/visual.py` — Vision-Modell beschreibt Bilder

**Kritische Fragen, die Phase 2 beantwortet:**
1. Welche Modellgröße liefert brauchbare GLAM-Ergebnisse?
2. Wie lange dauert ein Batch von 8.000 Records?
3. Stimmen KI-generierte Beschreibungen mit vorhandenen Metadaten überein?

### Phase 3 — Enrichment + Export
- GND-API, Wikidata, Geonames
- CSV-Export (Goobi-Import-Format)
- METS/MODS-XML-Export
- Interaktiver HTML-Report

### Phase 4 — OCR + erweiterte Formate
- OCR/HTR auf Bildern und PDFs
- XML-Import (METS/MODS, LIDO, EAD als Input)
- PDF-Import
- JSON-LD-Export

### Phase 5 — Web-UI + Integrationen
- FastAPI + React Dashboard
- Goobi REST-API-Anbindung
- Video/Audio-Verarbeitung (Keyframe-Extraktion)
- Cross-modale Analyse (Bild ↔ Metadaten)

## Coding-Konventionen

### Timestamps
**Regel:** Alle persistierten Zeitstempel laufen über
`kwb.core.utils.utc_now_iso()` und sind ISO-8601-Strings mit Timezone-
Offset (`+00:00`). Niemals `datetime.utcnow()` (deprecated, naive
datetime) oder `datetime.now()` (lokale Zeitzone) für persistierte
Daten benutzen.

```python
from kwb.core.utils import utc_now_iso

result.analyzed_at = utc_now_iso()
# → "2026-05-05T10:23:11.123456+00:00"
```

**Warum:** Konsistente Vergleichbarkeit über Workspaces, Server und
Zeitzonen hinweg; Timezone-aware Strings sind self-documenting.

### Enums über Modulgrenzen
Wenn ein `Enum` in mehr als einem Modul gebraucht wird, lebt er in
`kwb.core.models`. Andere Module re-exportieren ihn über `__all__`,
damit bestehende Import-Pfade weiter funktionieren. **Niemals** einen
Enum mit gleichem Namen in zwei Modulen definieren — selbst wenn die
Member zufällig identisch sind, geben Cross-Modul-Vergleiche silently
`False` zurück (Python vergleicht nach Klasse, nicht nach Wert).

### Persistenz-Schutz
Datei-basierte Stores (User-Accounts, Workspaces) müssen Korruption
*sichtbar* behandeln: bare `except: pass` ist verboten. Stattdessen:
spezifische Exceptions catchen, loggen, und (wo das Risiko
unbeabsichtigter Datenmanipulation besteht) die korrupte Datei mit
Zeitstempel-Suffix archivieren, statt sie zu überschreiben.

## Design-Entscheidungen

### Warum diese Reihenfolge?
1. **KI zuerst** — Höchstes technisches Risiko, Kern-Differentiator
2. **Bilder parallel** — Vision-Modelle laufen über die gleiche Infrastruktur
3. **Export vor UI** — CLI + Export ist sofort nutzbar, UI ist nice-to-have
4. **OCR nach Enrichment** — OCR braucht die AI-Schicht, die in Phase 2 gebaut wird

### Warum Provider-Abstraktion?
GPUStack, Ollama und OpenAI nutzen alle die gleiche API-Struktur.
Ein Interface (`AIProvider`) mit drei Implementierungen bedeutet:
- Entwicklung mit Ollama lokal (kein GPU nötig)
- Produktion mit GPUStack (volle Kontrolle)
- Tests mit Mock-Provider (deterministisch)
- Optional: Cloud-Fallback für Demos

### Warum kein Monolith?
Jedes GLAM-Institut hat andere Bedürfnisse:
- Bibliothek: braucht METS/MODS + GND, nicht LIDO
- Museum: braucht LIDO + Iconclass, nicht METS
- Archiv: braucht EAD + OCR, nicht Bildbeschreibung

Modularer Aufbau = jede Institution installiert nur, was sie braucht.
