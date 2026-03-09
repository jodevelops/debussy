"""
Tests für NerService- und DateService-Klassen und zugehörige Protocols.

Prüft:
  - DefaultNerService delegiert an ner_hybrid
  - MockNerService gibt konfigurierte Entities zurück ohne KI-Aufruf
  - DefaultDateService delegiert an normalize_dates
  - MockDateService gibt konfigurierte Ergebnisse zurück ohne KI-Aufruf
  - NerServiceProtocol und DateServiceProtocol werden korrekt erkannt (runtime_checkable)
  - get_ner_service() und get_date_service() in deps.py geben richtige Typen zurück
"""
import unittest
import pandas as pd

from kwb.analyze.ner import Entity, EntityType, NERResult
from kwb.analyze.ner_service import DefaultNerService, MockNerService
from kwb.enrich.edtf import EDTFResult
from kwb.enrich.date_service import DefaultDateService, MockDateService
from kwb.core.interfaces import NerServiceProtocol, DateServiceProtocol


class TestNerServiceProtocol(unittest.TestCase):
    """Protocol-Konformität der NER-Services."""

    def test_mock_satisfies_protocol(self):
        svc = MockNerService()
        self.assertIsInstance(svc, NerServiceProtocol)

    def test_default_satisfies_protocol(self):
        svc = DefaultNerService()
        self.assertIsInstance(svc, NerServiceProtocol)

    def test_plain_object_does_not_satisfy(self):
        self.assertNotIsInstance(object(), NerServiceProtocol)


class TestDateServiceProtocol(unittest.TestCase):
    """Protocol-Konformität der Date-Services."""

    def test_mock_satisfies_protocol(self):
        svc = MockDateService()
        self.assertIsInstance(svc, DateServiceProtocol)

    def test_default_satisfies_protocol(self):
        svc = DefaultDateService()
        self.assertIsInstance(svc, DateServiceProtocol)

    def test_plain_object_does_not_satisfy(self):
        self.assertNotIsInstance(object(), DateServiceProtocol)


class TestMockNerService(unittest.TestCase):
    """MockNerService verhält sich deterministisch, ruft keine KI auf."""

    def _make_df(self, rows=3):
        return pd.DataFrame({"Titel": [f"Werk {i}" for i in range(rows)]})

    def test_returns_configured_entities(self):
        entities = [
            Entity(text="Berlin", entity_type=EntityType.LOC, confidence=0.9, source="mock"),
            Entity(text="Goethe", entity_type=EntityType.PER, confidence=0.8, source="mock"),
        ]
        svc = MockNerService(entities=entities)
        df = self._make_df()
        result = svc.run(df, ["Titel"])

        self.assertIsInstance(result, NERResult)
        self.assertEqual(len(result.entities), 2)
        self.assertEqual(result.entities[0].text, "Berlin")
        self.assertEqual(result.entities[1].entity_type, EntityType.PER)

    def test_empty_entities_by_default(self):
        svc = MockNerService()
        df = self._make_df()
        result = svc.run(df, ["Titel"])
        self.assertEqual(result.entities, [])

    def test_call_log_records_invocations(self):
        svc = MockNerService()
        df = self._make_df(5)
        svc.run(df, ["Titel"], model="test-model")
        svc.run(df, ["Titel"])

        self.assertEqual(len(svc.call_log), 2)
        self.assertEqual(svc.call_log[0]["rows"], 5)
        self.assertEqual(svc.call_log[0]["model"], "test-model")
        self.assertIsNone(svc.call_log[1]["model"])

    def test_does_not_call_provider(self):
        # Provider should never be invoked — MockNerService is pure
        svc = MockNerService(entities=[
            Entity(text="Test", entity_type=EntityType.CON, confidence=1.0),
        ])
        df = self._make_df()
        # Pass None as provider — must not raise
        result = svc.run(df, ["Titel"], provider=None)
        self.assertEqual(len(result.entities), 1)

    def test_use_flags_recorded_in_log(self):
        svc = MockNerService()
        df = self._make_df()
        svc.run(df, [], use_spacy=False, use_llm=True)
        self.assertFalse(svc.call_log[0]["use_spacy"])
        self.assertTrue(svc.call_log[0]["use_llm"])


class TestMockDateService(unittest.TestCase):
    """MockDateService verhält sich deterministisch, ruft keine KI auf."""

    def test_returns_configured_results(self):
        results = [
            EDTFResult(original="um 1920", edtf="1920~", confidence=0.85, method="mock"),
            EDTFResult(original="Sommer 1933", edtf="1933-21", confidence=0.9, method="mock"),
        ]
        svc = MockDateService(results=results)
        items = [
            {"text": "um 1920", "record_id": "001"},
            {"text": "Sommer 1933", "record_id": "002"},
        ]
        out, report = svc.normalize(items)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].edtf, "1920~")
        self.assertEqual(out[1].original, "Sommer 1933")
        self.assertIsNone(report)

    def test_empty_results_by_default(self):
        svc = MockDateService()
        out, report = svc.normalize([{"text": "1850", "record_id": "1"}])
        self.assertEqual(out, [])
        self.assertIsNone(report)

    def test_call_log_records_invocations(self):
        svc = MockDateService()
        svc.normalize([{"text": "1800", "record_id": "1"}, {"text": "1900", "record_id": "2"}])
        svc.normalize([{"text": "1950", "record_id": "3"}], model="some-model")

        self.assertEqual(len(svc.call_log), 2)
        self.assertEqual(svc.call_log[0]["item_count"], 2)
        self.assertEqual(svc.call_log[1]["model"], "some-model")
        self.assertFalse(svc.call_log[0]["has_provider"])

    def test_does_not_call_provider(self):
        svc = MockDateService(results=[
            EDTFResult(original="1900", edtf="1900", confidence=1.0, method="mock"),
        ])
        out, _ = svc.normalize([{"text": "1900", "record_id": "1"}], provider=None)
        self.assertEqual(out[0].edtf, "1900")

    def test_returns_independent_copies(self):
        results = [EDTFResult(original="1800", edtf="1800", confidence=1.0, method="mock")]
        svc = MockDateService(results=results)
        out1, _ = svc.normalize([])
        out2, _ = svc.normalize([])
        # Should be separate list instances
        self.assertIsNot(out1, out2)


class TestDefaultNerServiceDelegation(unittest.TestCase):
    """DefaultNerService delegiert an ner_hybrid (Smoke-Test mit Mock-Provider)."""

    def test_runs_without_provider(self):
        svc = DefaultNerService()
        df = pd.DataFrame({"Titel": ["Gemälde aus Berlin, 1920"]})
        # use_spacy=False, use_llm=False → SpaCy nicht installiert, LLM nicht verfügbar
        result = svc.run(df, ["Titel"], provider=None, use_spacy=False, use_llm=False)
        self.assertIsInstance(result, NERResult)
        # No entities extracted without spacy or LLM
        self.assertIsInstance(result.entities, list)


class TestDefaultDateServiceDelegation(unittest.TestCase):
    """DefaultDateService delegiert an normalize_dates (Smoke-Test regelbasiert)."""

    def test_rules_based_conversion(self):
        svc = DefaultDateService()
        items = [
            {"text": "1920", "record_id": "001"},
            {"text": "01.01.1850", "record_id": "002"},
        ]
        results, report = svc.normalize(items, provider=None)
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        # "1920" should convert cleanly
        self.assertEqual(results[0].edtf, "1920")
        # method should be rules-based
        self.assertIn(results[0].method, ("rule", "rules", "edtf-rule", "iso"))


class TestDepsFactories(unittest.TestCase):
    """get_ner_service() und get_date_service() geben korrekte Typen zurück."""

    def test_get_ner_service(self):
        from kwb.api.deps import get_ner_service
        svc = get_ner_service()
        self.assertIsInstance(svc, NerServiceProtocol)
        self.assertIsInstance(svc, DefaultNerService)

    def test_get_date_service(self):
        from kwb.api.deps import get_date_service
        svc = get_date_service()
        self.assertIsInstance(svc, DateServiceProtocol)
        self.assertIsInstance(svc, DefaultDateService)


if __name__ == "__main__":
    unittest.main()
