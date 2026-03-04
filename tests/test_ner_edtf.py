"""Tests for NER and EDTF modules."""
import unittest
import pandas as pd
from kwb.analyze.ner import (
    EntityType, Entity, NERResult, ner_hybrid, ner_llm,
    scan_problematic_terms, SYSTEM_NER, _SPACY_TYPE_MAP,
)
from kwb.enrich.edtf import normalize_date_rules, normalize_dates, SYSTEM_EDTF
from kwb.ai.mock import MockProvider


class TestEntityTypes(unittest.TestCase):
    def test_all_types_exist(self):
        expected = {"PER","ORG","LOC","GPE","FAC","EVT","WRK","DAT","ETH","CON"}
        self.assertEqual({e.value for e in EntityType}, expected)

    def test_german_labels(self):
        self.assertEqual(EntityType.PER.label_de, "Person")
        self.assertEqual(EntityType.LOC.label_de, "Ort/Geografie")
        self.assertEqual(EntityType.FAC.label_de, "Bauwerk/Einrichtung")

    def test_spacy_type_mapping(self):
        self.assertEqual(_SPACY_TYPE_MAP["PER"], EntityType.PER)
        self.assertEqual(_SPACY_TYPE_MAP["NORP"], EntityType.ETH)
        self.assertEqual(_SPACY_TYPE_MAP["GPE"], EntityType.GPE)


class TestNERResult(unittest.TestCase):
    def test_empty(self):
        r = NERResult()
        self.assertEqual(len(r.entities), 0)
        self.assertEqual(r.to_dict_list(), [])

    def test_dedup(self):
        r = NERResult(entities=[
            Entity(text="Bern", entity_type=EntityType.GPE, confidence=0.8),
            Entity(text="Bern", entity_type=EntityType.GPE, confidence=0.95),
            Entity(text="Bern", entity_type=EntityType.LOC, confidence=0.6),
        ])
        unique = r.unique_entities
        self.assertEqual(len(unique), 2)  # GPE + LOC
        self.assertAlmostEqual(unique["bern||GPE"].confidence, 0.95)

    def test_by_type(self):
        r = NERResult(entities=[
            Entity(text="Bern", entity_type=EntityType.GPE),
            Entity(text="Müller", entity_type=EntityType.PER),
            Entity(text="Zürich", entity_type=EntityType.GPE),
        ])
        by = r.by_type
        self.assertEqual(len(by[EntityType.GPE]), 2)
        self.assertEqual(len(by[EntityType.PER]), 1)

    def test_to_dict_list(self):
        r = NERResult(entities=[
            Entity(text="ETH Zürich", entity_type=EntityType.ORG, confidence=0.9,
                   source="llm", record_id="rec1", column="col1"),
        ])
        d = r.to_dict_list()
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["text"], "ETH Zürich")
        self.assertEqual(d[0]["type"], "ORG")
        self.assertEqual(d[0]["type_label"], "Organisation")
        self.assertFalse(d[0]["reviewed"])


class TestNERWithMock(unittest.TestCase):
    def test_llm_ner_with_mock(self):
        provider = MockProvider(
            default_response='{"entities": [{"text": "Bern", "type": "GPE", "confidence": 0.9, "reasoning": "city"}]}')
        texts = [{"record_id": "r1", "text": "Altstadt von Bern", "column": "title"}]
        entities, batch = ner_llm(texts, provider)
        self.assertEqual(batch.succeeded, 1)
        self.assertTrue(len(entities) >= 1)
        self.assertEqual(entities[0].text, "Bern")
        self.assertEqual(entities[0].entity_type, EntityType.GPE)

    def test_hybrid_llm_only(self):
        provider = MockProvider(
            default_response='{"entities": [{"text": "Müller", "type": "PER", "confidence": 0.85}]}')
        df = pd.DataFrame({"id": ["r1"], "title": ["Prof. Müller"]})
        result = ner_hybrid(df, ["title"], provider=provider, id_column="id",
                           use_spacy=False, use_llm=True)
        self.assertTrue(len(result.entities) >= 1)

    def test_scan_problematic(self):
        provider = MockProvider(
            default_response='{"problematic_terms": [{"term": "Eingeborene", "reason": "kolonialer Begriff", "severity": "high", "suggestion": "Indigene Bevölkerung"}], "clean": false}')
        df = pd.DataFrame({"id": ["r1"], "desc": ["Die Eingeborene des Landes"]})
        issues, batch = scan_problematic_terms(df, provider, id_column="id", sample_size=1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["term"], "Eingeborene")
        self.assertEqual(issues[0]["severity"], "high")


class TestEDTFRules(unittest.TestCase):
    def _r(self, text): return normalize_date_rules(text)

    def test_plain_year(self):
        self.assertEqual(self._r("1923").edtf, "1923")
        self.assertEqual(self._r("1923").confidence, 1.0)

    def test_full_date_de(self):
        self.assertEqual(self._r("17.05.1923").edtf, "1923-05-17")

    def test_full_date_iso(self):
        self.assertEqual(self._r("1923-05-17").edtf, "1923-05-17")

    def test_year_month(self):
        self.assertEqual(self._r("1923-05").edtf, "1923-05")

    def test_approximate_um(self):
        r = self._r("um 1920")
        self.assertEqual(r.edtf, "1920~")
        self.assertEqual(r.note, "approximate")

    def test_approximate_ca(self):
        self.assertEqual(self._r("ca. 1850").edtf, "1850~")
        self.assertEqual(self._r("circa 1900").edtf, "1900~")

    def test_uncertain(self):
        self.assertEqual(self._r("1920?").edtf, "1920?")

    def test_range_dash(self):
        self.assertEqual(self._r("1920-1930").edtf, "1920/1930")

    def test_range_bis(self):
        self.assertEqual(self._r("1920 bis 1930").edtf, "1920/1930")

    def test_decade(self):
        self.assertEqual(self._r("1920er Jahre").edtf, "192X")
        self.assertEqual(self._r("1920er").edtf, "192X")

    def test_century(self):
        self.assertEqual(self._r("19. Jahrhundert").edtf, "18XX")
        self.assertEqual(self._r("20. Jh.").edtf, "19XX")

    def test_before(self):
        self.assertEqual(self._r("vor 1900").edtf, "../1900")

    def test_after(self):
        self.assertEqual(self._r("nach 1950").edtf, "1950/..")

    def test_month_year_de(self):
        self.assertEqual(self._r("mai 1923").edtf, "1923-05")
        self.assertEqual(self._r("dezember 1900").edtf, "1923-12" if False else "1900-12")

    def test_season(self):
        self.assertEqual(self._r("sommer 1923").edtf, "1923-22")

    def test_unknown(self):
        self.assertEqual(self._r("undatiert").edtf, "")
        self.assertEqual(self._r("o.j.").edtf, "")
        self.assertEqual(self._r("").edtf, "")

    def test_no_match(self):
        self.assertIsNone(self._r("Anfang des 19. Jh. bis Mitte 20. Jh."))


class TestEDTFHybrid(unittest.TestCase):
    def test_rules_only(self):
        vals = [{"record_id": "r1", "text": "1923"}, {"record_id": "r2", "text": "ca. 1850"}]
        results, batch = normalize_dates(vals, provider=None)
        self.assertEqual(len(results), 2)
        self.assertIsNone(batch)
        self.assertEqual(results[0].edtf, "1923")
        self.assertEqual(results[1].edtf, "1850~")

    def test_with_mock_fallback(self):
        provider = MockProvider(
            default_response='{"original": "Wohl aus der Nachkriegszeit", "edtf": "1945/1955", "confidence": 0.7, "note": "ambiguous"}')
        vals = [{"record_id": "r1", "text": "1923"}, {"record_id": "r2", "text": "Wohl aus der Nachkriegszeit"}]
        results, batch = normalize_dates(vals, provider=provider)
        self.assertEqual(len(results), 2)
        self.assertIsNotNone(batch)


class TestSystemPrompts(unittest.TestCase):
    def test_ner_prompt_exists(self):
        self.assertIn("Named Entity", SYSTEM_NER)
        self.assertIn("PER", SYSTEM_NER)

    def test_edtf_prompt_exists(self):
        self.assertIn("EDTF", SYSTEM_EDTF)
        self.assertIn("Dekade", SYSTEM_EDTF)


if __name__ == "__main__":
    unittest.main()
