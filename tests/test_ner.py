"""Tests for NER module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd
from kwb.analyze.ner import (
    EntityType, Entity, NERResult,
    ner_llm, ner_hybrid, scan_problematic_terms, SYSTEM_NER,
)
from kwb.ai.mock import MockProvider


class TestEntityType:
    def test_labels(self):
        assert EntityType.PER.label_de == "Person"
        assert EntityType.ORG.label_de == "Organisation"
        assert EntityType.LOC.label_de == "Ort/Geografie"

    def test_all_types_have_labels(self):
        for t in EntityType:
            assert t.label_de, f"Missing label for {t.value}"


class TestEntity:
    def test_basic(self):
        e = Entity(text="Berlin", entity_type=EntityType.GPE, confidence=0.9)
        assert e.text == "Berlin"
        assert e.entity_type == EntityType.GPE
        assert e.reviewed is False

    def test_with_gnd(self):
        e = Entity(text="Goethe", entity_type=EntityType.PER,
                   gnd_id="118540238", gnd_preferred="Goethe, Johann Wolfgang von")
        assert e.gnd_id == "118540238"


class TestNERResult:
    def test_by_type(self):
        r = NERResult(entities=[
            Entity(text="Berlin", entity_type=EntityType.GPE, confidence=0.9),
            Entity(text="Goethe", entity_type=EntityType.PER, confidence=0.8),
            Entity(text="München", entity_type=EntityType.GPE, confidence=0.7),
        ])
        by_type = r.by_type
        assert len(by_type[EntityType.GPE]) == 2
        assert len(by_type[EntityType.PER]) == 1

    def test_unique_entities(self):
        r = NERResult(entities=[
            Entity(text="Berlin", entity_type=EntityType.GPE, confidence=0.9),
            Entity(text="Berlin", entity_type=EntityType.GPE, confidence=0.7),
        ])
        uniq = r.unique_entities
        assert len(uniq) == 1
        assert list(uniq.values())[0].confidence == 0.9  # keeps highest

    def test_to_dict_list(self):
        r = NERResult(entities=[
            Entity(text="Berlin", entity_type=EntityType.GPE, confidence=0.9),
        ])
        dicts = r.to_dict_list()
        assert len(dicts) == 1
        assert dicts[0]["text"] == "Berlin"
        assert dicts[0]["type"] == "GPE"
        assert dicts[0]["type_label"] == "Geo-politische Einheit"


class TestNERLLM:
    def test_with_mock(self):
        ner_response = '{"entities": [{"text": "Berlin", "type": "GPE", "confidence": 0.9, "reasoning": "Hauptstadt"}]}'
        mock = MockProvider(rules=[
            (lambda msgs: True, ner_response),
        ])
        texts = [{"record_id": "r1", "text": "Blick auf Berlin", "column": "description"}]
        entities, batch = ner_llm(texts, mock)
        assert batch.total == 1
        assert batch.succeeded == 1
        assert len(entities) == 1
        assert entities[0].text == "Berlin"
        assert entities[0].entity_type == EntityType.GPE

    def test_empty_input(self):
        mock = MockProvider.with_defaults()
        entities, batch = ner_llm([], mock)
        assert batch.total == 0
        assert len(entities) == 0


class TestNERHybrid:
    def test_llm_only(self):
        ner_response = '{"entities": [{"text": "Test", "type": "CON", "confidence": 0.5, "reasoning": "test"}]}'
        mock = MockProvider(rules=[(lambda msgs: True, ner_response)])
        df = pd.DataFrame({
            "id": ["r1", "r2"],
            "desc": ["Alpenblick", "Stadtansicht Berlin"],
        })
        result = ner_hybrid(
            df, columns=["desc"], provider=mock,
            id_column="id", use_spacy=False, use_llm=True,
        )
        assert isinstance(result, NERResult)
        assert result.batch_report is not None


class TestScanProblematic:
    def test_with_mock(self):
        mock = MockProvider(rules=[
            (lambda msgs: True, '{"problematic_terms": [], "clean": true}'),
        ])
        df = pd.DataFrame({
            "id": ["r1"], "title": ["Berglandschaft"],
        })
        issues, batch = scan_problematic_terms(
            df, mock, id_column="id", sample_size=1,
        )
        assert batch.total == 1
        assert isinstance(issues, list)


if __name__ == "__main__":
    total = passed = failed = 0
    for cls in [TestEntityType, TestEntity, TestNERResult, TestNERLLM, TestNERHybrid, TestScanProblematic]:
        for name in sorted(m for m in dir(cls()) if m.startswith("test_")):
            total += 1
            try:
                getattr(cls(), name)()
                passed += 1
            except Exception as e:
                failed += 1
                print(f"FAIL {cls.__name__}.{name}: {e}")
    print(f"NER: {passed}/{total} passed, {failed} failed")
