#!/usr/bin/env python3
"""
GPUStack-Verbindungstest.

Dieses Skript testet die Verbindung zu deinem GPUStack und zeigt,
welche Modelle verfügbar sind. Dann führt es einen kleinen
Klassifikationstest mit echten GLAM-Daten durch.

Voraussetzung:
    1. cp .env.example .env
    2. .env anpassen (URL, Key)
    3. python scripts/test_connection.py

Gibt bei Erfolg konkrete Ergebnisse aus, bei Fehler klare Hinweise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add src to path so we can import kwb
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.core.config import load_config
from kwb.ai.provider import AIMessage, ProviderConfig
from kwb.ai.gpustack import GPUStackProvider
from kwb.ai.prompts import prompt_classify_subject, prompt_describe_image


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def test_connection(provider: GPUStackProvider) -> bool:
    section("1. Verbindungstest")
    available = provider.is_available()
    if available:
        print(f"  ✅ GPUStack erreichbar unter {provider.config.base_url}")
    else:
        print(f"  ❌ GPUStack NICHT erreichbar unter {provider.config.base_url}")
        print(f"     Prüfe:")
        print(f"     - Läuft GPUStack? (gpustack start)")
        print(f"     - Stimmt die URL in .env?")
        print(f"     - Firewall / Port offen?")
    return available


def test_models(provider: GPUStackProvider) -> list[str]:
    section("2. Verfügbare Modelle")
    models = provider.list_models()
    if models:
        for m in models:
            print(f"  📦 {m}")
        print(f"\n  {len(models)} Modell(e) gefunden.")
    else:
        print("  ⚠️  Keine Modelle gefunden.")
        print("     Lade ein Modell in GPUStack, z.B.:")
        print("     - Text:   Qwen/Qwen2.5-7B-Instruct")
        print("     - Vision: Qwen/Qwen2-VL-7B-Instruct")
    return models


def test_text_completion(provider: GPUStackProvider, model: str) -> bool:
    section(f"3. Text-Test mit '{model}'")
    print("  Sende GLAM-Klassifikationsanfrage …")

    messages = prompt_classify_subject(
        subject_text="Minarett; Stadtmauer; sandige Talebene",
        context="GIUB-Testrecord dcb-col-003_obid-00002",
    )

    try:
        response = provider.complete(messages, model=model, max_tokens=512)
        print(f"  ✅ Antwort erhalten ({len(response.content)} Zeichen)")
        print(f"  Modell: {response.model}")
        if response.usage:
            print(f"  Tokens: {response.usage.get('prompt_tokens', '?')} prompt, "
                  f"{response.usage.get('completion_tokens', '?')} completion")

        # Try parsing as JSON
        try:
            parsed = json.loads(response.content)
            print(f"\n  📋 Ergebnis (JSON):")
            print(json.dumps(parsed, indent=4, ensure_ascii=False))
            return True
        except json.JSONDecodeError:
            print(f"\n  ⚠️  Antwort ist kein valides JSON:")
            print(f"  {response.content[:500]}")
            print(f"\n  Das Modell gibt möglicherweise Markdown statt JSON aus.")
            print(f"  → Prompt-Tuning nötig, oder anderes Modell probieren.")
            return True  # Connection works, just needs tuning

    except Exception as e:
        print(f"  ❌ Fehler: {e}")
        return False


def test_vision(provider: GPUStackProvider, model: str) -> bool:
    section(f"4. Vision-Test mit '{model}'")

    # Create a tiny 1x1 JPEG for testing (no real image needed)
    import base64
    mini_jpeg = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00,
        0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
    ])
    b64 = base64.b64encode(mini_jpeg).decode("ascii")

    msgs = prompt_describe_image(additional_context="Testbild")
    # Replace last message with vision message
    text_content = msgs[-1].content
    vision_msg = AIMessage.user_with_image(text_content, b64, "image/jpeg")
    messages = [msgs[0], vision_msg]

    try:
        response = provider.complete(messages, model=model, max_tokens=512)
        print(f"  ✅ Vision-Antwort erhalten ({len(response.content)} Zeichen)")

        try:
            parsed = json.loads(response.content)
            print(f"\n  📋 Ergebnis (JSON):")
            print(json.dumps(parsed, indent=4, ensure_ascii=False))
        except json.JSONDecodeError:
            print(f"\n  Antwort (Rohtext):")
            print(f"  {response.content[:500]}")

        return True

    except Exception as e:
        print(f"  ❌ Fehler: {e}")
        print(f"     Mögliche Ursache: '{model}' unterstützt kein Vision.")
        print(f"     Versuche ein Vision-Modell wie Qwen2-VL oder LLaVA.")
        return False


def test_with_real_data(provider: GPUStackProvider, model: str) -> None:
    section(f"5. Echtdaten-Test (5 Records)")

    # Try to load real GIUB data
    data_candidates = [
        Path("data/subjects_restructured_1.csv"),
        Path("../data/subjects_restructured_1.csv"),
    ]

    data_path = None
    for p in data_candidates:
        if p.exists():
            data_path = p
            break

    if not data_path:
        print("  ⏭️  Keine Testdaten gefunden in data/")
        print("     Lege subjects_restructured_1.csv in data/ ab für den Echttest.")
        return

    from kwb.ingest.csv_loader import ingest_csv
    from kwb.analyze.semantic import classify_subjects

    df, profile = ingest_csv(data_path)
    print(f"  Geladen: {profile.row_count} Records aus {data_path}")

    findings, batch = classify_subjects(
        df, profile, provider,
        subject_column="subject_extract_original",
        sample_size=5,
        model=model,
    )

    print(f"\n  Ergebnis: {batch.succeeded}/{batch.total} erfolgreich")
    print(f"  Durchschnittliche Dauer: {batch.avg_duration:.2f}s pro Record")

    for r in batch.results:
        status = "✅" if r.success else "❌"
        print(f"\n  {status} {r.record_id} ({r.duration_seconds:.2f}s)")
        if r.parsed:
            print(f"     {json.dumps(r.parsed, ensure_ascii=False)[:200]}")
        elif r.error:
            print(f"     Fehler: {r.error}")


def main():
    print("╔════════════════════════════════════════════════════════╗")
    print("║  Kuratierwerkbank — GPUStack-Verbindungstest          ║")
    print("╚════════════════════════════════════════════════════════╝")

    # Load config
    config = load_config()
    print(f"\nKonfiguration:")
    for k, v in config.display_safe().items():
        print(f"  {k}: {v}")

    if not config.is_gpustack_configured:
        print("\n❌ GPUStack nicht konfiguriert!")
        print("   1. cp .env.example .env")
        print("   2. .env bearbeiten: KWB_GPUSTACK_URL und KWB_GPUSTACK_KEY setzen")
        print("   3. Dieses Skript erneut starten")
        sys.exit(1)

    # Create provider
    provider = GPUStackProvider(config.to_provider_config())

    # Test 1: Connection
    if not test_connection(provider):
        sys.exit(1)

    # Test 2: Models
    models = test_models(provider)
    if not models:
        sys.exit(1)

    # Test 3: Text completion
    text_model = config.gpustack_model_text
    if not text_model:
        print(f"\n  KWB_GPUSTACK_MODEL_TEXT nicht gesetzt.")
        print(f"  Verfügbare Modelle: {', '.join(models)}")
        text_model = models[0]
        print(f"  → Verwende erstes Modell: {text_model}")

    text_ok = test_text_completion(provider, text_model)

    # Test 4: Vision (only if vision model configured)
    vision_model = config.gpustack_model_vision
    if vision_model:
        test_vision(provider, vision_model)
    else:
        section("4. Vision-Test")
        print("  ⏭️  Übersprungen (KWB_GPUSTACK_MODEL_VISION nicht gesetzt)")
        print(f"     Setze es in .env auf eines der Modelle: {', '.join(models)}")

    # Test 5: Real data (only if text works)
    if text_ok:
        test_with_real_data(provider, text_model)

    section("Zusammenfassung")
    print("  Nächste Schritte:")
    print("  1. Kopiere deine CSV-Daten nach data/")
    print("  2. Starte eine Analyse:")
    print("     PYTHONPATH=src python -m kwb.cli analyze data/deine_datei.csv -o report.md")
    print()


if __name__ == "__main__":
    main()
