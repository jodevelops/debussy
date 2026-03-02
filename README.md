# Debussy — KI-gestützte Kuratierungswerkbank

Datenqualitäts-Analyse und -Anreicherung für GLAM-Institutionen.

## Quickstart

```bash
pip install fastapi uvicorn python-multipart
cd debussy && $env:PYTHONPATH = "src" && python -m kwb.api.app
# → http://localhost:8765
```

## Tests

```bash
PYTHONPATH=src python -m unittest discover tests
```

## Dashboard-Tabs

| Tab | Funktion |
|-----|----------|
| Analyse | CSV laden, strukturelle Checks, Profile |
| KI-Werkzeuge | NER, Klassifikation, EDTF, Scans |
| KI-Konfiguration | Modelle, System-Prompts, Kategorien |
| Funktionen | Feature-Katalog mit Status |
