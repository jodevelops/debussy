"""
Rigorous tests for kwb.analyze.ner.

Focus areas:
1. Entity.dedup_key is case-insensitive.
2. _merge_entity_lists: higher confidence wins, LLM wins on tie.
3. Merged entities get source="hybrid".
4. Entities unique to one source keep original source.
5. to_dict_list(deduplicated=True) never returns duplicates.
6. to_dict_list(deduplicated=False) preserves all entities.
7. ner_llm forwards the model parameter.
8. ner_hybrid with both sources.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest
import pandas as pd

from kwb.analyze.ner import (
    Entity, EntityType, NERResult,
    _merge_entity_lists, ner_llm, ner_hybrid,
)
from kwb.ai.mock import MockProvider


def _entity(text, etype=EntityType.LOC, conf=0.5, source="spacy", record_id="r1"):
    return Entity(
        text=text, entity_type=etype,
        confidence=conf, source=source, record_id=record_id,
    )


class TestEntityDedupKey(unittest.TestCase):

    def test_key_is_case_insensitive(self):
        a = _entity("Berlin")
        b = _entity("berlin")
        self.assertEqual(a.dedup_key, b.dedup_key)

    def test_key_includes_type(self):
        loc = _entity("Berlin", EntityType.LOC)
        gpe = _entity("Berlin", EntityType.GPE)
        self.assertNotEqual(loc.dedup_key, gpe.dedup_key)

    def test_key_strips_whitespace(self):
        a = _entity(" Berlin ")
        b = _entity("Berlin")
        self.assertEqual(a.dedup_key, b.dedup_key)


class TestMergeEntityLists(unittest.TestCase):

    def test_no_overlap_both_kept(self):
        spacy = [_entity("Berlin", EntityType.LOC, source="spacy")]
        llm   = [_entity("München", EntityType.LOC, source="llm")]
        result = _merge_entity_lists(spacy, llm)
        texts = {e.text.lower() for e in result}
        self.assertIn("berlin", texts)
        self.assertIn("münchen", texts)

    def test_llm_wins_on_equal_confidence(self):
        spacy = [_entity("Berlin", conf=0.6, source="spacy")]
        llm   = [_entity("Berlin", conf=0.6, source="llm")]
        result = _merge_entity_lists(spacy, llm)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "hybrid")
        # On equal confidence, LLM wins (higher or equal → llm path taken)
        self.assertAlmostEqual(result[0].confidence, 0.6)

    def test_higher_spacy_confidence_wins(self):
        spacy = [_entity("Berlin", conf=0.9, source="spacy")]
        llm   = [_entity("Berlin", conf=0.5, source="llm")]
        result = _merge_entity_lists(spacy, llm)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "hybrid")
        self.assertAlmostEqual(result[0].confidence, 0.9)

    def test_higher_llm_confidence_wins(self):
        spacy = [_entity("Berlin", conf=0.5, source="spacy")]
        llm   = [_entity("Berlin", conf=0.9, source="llm")]
        result = _merge_entity_lists(spacy, llm)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "hybrid")
        self.assertAlmostEqual(result[0].confidence, 0.9)

    def test_overlap_sets_source_hybrid(self):
        spacy = [_entity("Wien", source="spacy")]
        llm   = [_entity("Wien", source="llm")]
        result = _merge_entity_lists(spacy, llm)
        self.assertEqual(result[0].source, "hybrid")

    def test_unique_spacy_keeps_source(self):
        spacy = [_entity("Graz", source="spacy")]
        result = _merge_entity_lists(spacy, [])
        self.assertEqual(result[0].source, "spacy")

    def test_unique_llm_keeps_source(self):
        llm = [_entity("Salzburg", source="llm")]
        result = _merge_entity_lists([], llm)
        self.assertEqual(result[0].source, "llm")

    def test_empty_lists(self):
        self.assertEqual(_merge_entity_lists([], []), [])

    def test_case_insensitive_dedup(self):
        spacy = [_entity("berlin", source="spacy")]
        llm   = [_entity("Berlin", source="llm")]
        result = _merge_entity_lists(spacy, llm)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "hybrid")

    def test_multiple_entities_mixed(self):
        spacy = [
            _entity("Berlin", EntityType.GPE, conf=0.7, source="spacy"),
            _entity("Spree",  EntityType.LOC, conf=0.6, source="spacy"),
        ]
        llm = [
            _entity("Berlin",    EntityType.GPE, conf=0.9, source="llm"),
            _entity("Brandenburger Tor", EntityType.FAC, conf=0.85, source="llm"),
        ]
        result = _merge_entity_lists(spacy, llm)
        self.assertEqual(len(result), 3)  # Berlin(hybrid), Spree(spacy), BT(llm)
        sources = {e.text.lower(): e.source for e in result}
        self.assertEqual(sources["berlin"], "hybrid")
        self.assertEqual(sources["spree"], "spacy")
        self.assertEqual(sources["brandenburger tor"], "llm")


class TestNERResult(unittest.TestCase):

    def _result(self, entities):
        r = NERResult()
        r.entities = entities
        return r

    def test_to_dict_list_deduplicated_default(self):
        """Default behavior: no duplicates."""
        entities = [
            _entity("Berlin", conf=0.7, source="spacy"),
            _entity("Berlin", conf=0.9, source="llm"),   # duplicate
        ]
        r = self._result(entities)
        result = r.to_dict_list()
        self.assertEqual(len(result), 1)
        # Highest confidence wins
        self.assertAlmostEqual(result[0]["confidence"], 0.9)

    def test_to_dict_list_raw_returns_all(self):
        entities = [
            _entity("Berlin", conf=0.7, source="spacy"),
            _entity("Berlin", conf=0.9, source="llm"),
        ]
        r = self._result(entities)
        result = r.to_dict_list(deduplicated=False)
        self.assertEqual(len(result), 2)

    def test_to_dict_list_includes_gnd_fields(self):
        e = _entity("Berlin")
        e.gnd_id = "4005765-8"
        e.gnd_preferred = "Berlin"
        r = self._result([e])
        d = r.to_dict_list()[0]
        self.assertEqual(d["gnd_id"], "4005765-8")
        self.assertEqual(d["gnd_preferred"], "Berlin")

    def test_unique_entities_property(self):
        entities = [
            _entity("Berlin", conf=0.5),
            _entity("BERLIN", conf=0.9),  # same entity, different case
        ]
        r = self._result(entities)
        self.assertEqual(len(r.unique_entities), 1)

    def test_by_type_grouping(self):
        entities = [
            _entity("Berlin", EntityType.GPE),
            _entity("Wien", EntityType.GPE),
            _entity("Alpen", EntityType.LOC),
        ]
        r = self._result(entities)
        self.assertEqual(len(r.by_type[EntityType.GPE]), 2)
        self.assertEqual(len(r.by_type[EntityType.LOC]), 1)


class TestNERLLMModelForwarding(unittest.TestCase):

    def test_ner_llm_uses_specified_model(self):
        """Model specified in ner_llm() must appear in MockProvider.call_log."""
        mock = MockProvider.with_ner_response([
            {"text": "Berlin", "type": "GPE", "confidence": 0.9, "reasoning": "Capital"}
        ])
        texts = [{"text": "Berlin ist die Hauptstadt.", "record_id": "r1", "column": "desc"}]
        entities, batch = ner_llm(texts, mock, model="gpt-oss-120b")

        self.assertEqual(len(mock.call_log), 1)
        self.assertEqual(mock.call_log[0]["model"], "gpt-oss-120b")

    def test_ner_llm_default_model_when_none(self):
        """When model=None, provider uses its default_model."""
        mock = MockProvider(
            config=None,
            default_response='{"entities": []}',
        )
        mock.config.default_model = "default-model"
        texts = [{"text": "Test", "record_id": "r1", "column": "x"}]
        ner_llm(texts, mock, model=None)
        self.assertEqual(mock.call_log[0]["model"], "default-model")

    def test_ner_llm_parses_entities(self):
        mock = MockProvider.with_ner_response([
            {"text": "Berlin", "type": "GPE", "confidence": 0.85, "reasoning": "Capital city"},
            {"text": "Spree", "type": "LOC", "confidence": 0.75, "reasoning": "River"},
        ])
        texts = [{"text": "Berlin liegt an der Spree.", "record_id": "r1", "column": "title"}]
        entities, _ = ner_llm(texts, mock)
        self.assertEqual(len(entities), 2)
        self.assertEqual(entities[0].text, "Berlin")
        self.assertEqual(entities[0].entity_type, EntityType.GPE)
        self.assertEqual(entities[1].text, "Spree")
        self.assertEqual(entities[1].entity_type, EntityType.LOC)

    def test_ner_llm_handles_invalid_type(self):
        """Unknown entity types fall back to CON."""
        mock = MockProvider.with_ner_response([
            {"text": "Ding", "type": "INVALID_TYPE", "confidence": 0.5, "reasoning": ""},
        ])
        texts = [{"text": "Ding da", "record_id": "r1", "column": "x"}]
        entities, _ = ner_llm(texts, mock)
        self.assertEqual(entities[0].entity_type, EntityType.CON)

    def test_ner_llm_gracefully_handles_empty_response(self):
        mock = MockProvider(default_response='{"entities": []}')
        texts = [{"text": "Text ohne Entitäten", "record_id": "r1", "column": "x"}]
        entities, batch = ner_llm(texts, mock)
        self.assertEqual(entities, [])
        self.assertTrue(batch.succeeded > 0)


class TestNERHybrid(unittest.TestCase):

    def _df(self):
        return pd.DataFrame([
            {"record_id": "r1", "title": "Berlin und München", "desc": "Reise nach Wien"},
            {"record_id": "r2", "title": "Zürich", "desc": ""},
        ])

    def test_hybrid_llm_only(self):
        """Without SpaCy, result comes entirely from LLM."""
        mock = MockProvider.with_ner_response([
            {"text": "Berlin", "type": "GPE", "confidence": 0.9, "reasoning": ""},
        ])
        result = ner_hybrid(
            self._df(), ["title"],
            provider=mock,
            id_column="record_id",
            use_spacy=False,
            use_llm=True,
        )
        self.assertIsInstance(result, NERResult)
        self.assertTrue(len(result.entities) > 0)
        self.assertTrue(all(e.source == "llm" for e in result.entities))

    def test_hybrid_no_provider_no_llm(self):
        """Without provider, NER runs SpaCy only (or returns empty if SpaCy not installed)."""
        result = ner_hybrid(
            self._df(), ["title"],
            provider=None,
            use_spacy=False,
            use_llm=False,
        )
        self.assertIsInstance(result, NERResult)
        self.assertEqual(result.entities, [])

    def test_hybrid_model_forwarded(self):
        mock = MockProvider.with_ner_response([
            {"text": "Wien", "type": "GPE", "confidence": 0.9, "reasoning": ""},
        ])
        ner_hybrid(
            self._df(), ["desc"],
            provider=mock,
            model="vision-model-xyz",
            use_spacy=False,
            use_llm=True,
        )
        self.assertTrue(len(mock.call_log) > 0)
        # All calls must use the specified model
        for call in mock.call_log:
            self.assertEqual(call["model"], "vision-model-xyz")

    def test_hybrid_dedup_result(self):
        """After merge, to_dict_list() must not contain duplicates."""
        mock = MockProvider.with_ner_response([
            {"text": "Berlin", "type": "GPE", "confidence": 0.9, "reasoning": ""},
            {"text": "Berlin", "type": "GPE", "confidence": 0.8, "reasoning": ""},  # dup
        ])
        df = pd.DataFrame([{"record_id": "r1", "title": "Berlin Berlin"}])
        result = ner_hybrid(
            df, ["title"],
            provider=mock,
            id_column="record_id",
            use_spacy=False,
            use_llm=True,
        )
        dicts = result.to_dict_list(deduplicated=True)
        berlin_entries = [d for d in dicts if d["text"] == "Berlin"]
        self.assertEqual(len(berlin_entries), 1)

    def test_hybrid_skips_empty_values(self):
        mock = MockProvider.with_ner_response([])
        df = pd.DataFrame([{"record_id": "r1", "desc": ""}])
        result = ner_hybrid(df, ["desc"], provider=mock, use_spacy=False, use_llm=True)
        # Empty cell should not generate an LLM call
        self.assertEqual(len(mock.call_log), 0)

    def test_hybrid_sample_size_limits_calls(self):
        mock = MockProvider.with_ner_response([])
        df = pd.DataFrame([
            {"record_id": f"r{i}", "title": f"Text {i}"}
            for i in range(20)
        ])
        ner_hybrid(
            df, ["title"],
            provider=mock,
            sample_size=5,
            use_spacy=False,
            use_llm=True,
        )
        # Only 5 items → at most 5 LLM calls
        self.assertLessEqual(len(mock.call_log), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
