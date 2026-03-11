"""
Tests for the OCR → NER → Dictionary pipeline with review gates.

Covers:
- AuthorityCandidate model: create, serialize, deserialize
- OCR gating: only accepted OCR results produce NER entities
- NER gating: only accepted entities transfer to dictionary
- Authority gating: candidates must be accepted before commit
- Dictionary target export format
- Text normalization
- Pipeline status
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest

from kwb.core.workspace import (
    Workspace, DictionaryEntry, ReviewStatus,
    ImageAnalysisResult, ImageReviewStatus, AuthorityCandidate,
)
from kwb.core.normalize import normalize_term


class TestAuthorityCandidateModel(unittest.TestCase):

    def test_create_with_auto_id(self):
        c = AuthorityCandidate(entry_id="e1", source="gnd", authority_id="123")
        self.assertTrue(len(c.candidate_id) > 0)
        self.assertEqual(c.status, ReviewStatus.PENDING)

    def test_accept(self):
        c = AuthorityCandidate(entry_id="e1", source="gnd")
        c.accept(note="looks good")
        self.assertEqual(c.status, ReviewStatus.ACCEPTED)
        self.assertEqual(c.reviewer_note, "looks good")
        self.assertTrue(len(c.reviewed_at) > 0)

    def test_reject(self):
        c = AuthorityCandidate(entry_id="e1", source="wikidata")
        c.reject(note="wrong match")
        self.assertEqual(c.status, ReviewStatus.REJECTED)

    def test_roundtrip(self):
        c = AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="4005765-8",
            preferred_name="Berlin", authority_type="PlaceOrGeographicName",
            uri="https://d-nb.info/gnd/4005765-8", score=0.85,
            extra={"variants": ["Berlín"]},
        )
        d = c.to_dict()
        c2 = AuthorityCandidate.from_dict(d)
        self.assertEqual(c2.entry_id, "e1")
        self.assertEqual(c2.authority_id, "4005765-8")
        self.assertEqual(c2.score, 0.85)
        self.assertEqual(c2.extra, {"variants": ["Berlín"]})
        self.assertEqual(c2.status, ReviewStatus.PENDING)


class TestWorkspaceAuthorityCandidates(unittest.TestCase):

    def test_add_and_query(self):
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(term="Berlin", entry_id="e1"))
        ws.add_authority_candidate(AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="4005765-8",
        ))
        ws.add_authority_candidate(AuthorityCandidate(
            entry_id="e1", source="wikidata", authority_id="Q64",
        ))
        cands = ws.authority_candidates_for_entry("e1")
        self.assertEqual(len(cands), 2)

    def test_review_stats(self):
        ws = Workspace.create("test")
        c1 = AuthorityCandidate(entry_id="e1", source="gnd")
        c2 = AuthorityCandidate(entry_id="e1", source="wikidata")
        c2.accept()
        ws.add_authority_candidate(c1)
        ws.add_authority_candidate(c2)
        stats = ws.authority_review_stats()
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["total"], 2)

    def test_serialization_roundtrip(self):
        ws = Workspace.create("test")
        ws.add_authority_candidate(AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="123",
        ))
        d = ws.to_dict()
        ws2 = Workspace.from_dict(d)
        self.assertEqual(len(ws2.authority_candidates), 1)
        self.assertEqual(ws2.authority_candidates[0].authority_id, "123")


class TestOCRGating(unittest.TestCase):
    """Verify that only accepted OCR results should feed NER."""

    def test_accepted_ocr_analyses(self):
        ws = Workspace.create("test")
        # Add a pending OCR result
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img1", analyzed=True,
            result={"transcription": "Hallo Welt"},
            review_status=ImageReviewStatus.PENDING,
        ))
        # Add an accepted OCR result
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img2", analyzed=True,
            result={"transcription": "Johann Bach"},
            review_status=ImageReviewStatus.ACCEPTED,
        ))
        # Add a rejected OCR result
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img3", analyzed=True,
            result={"transcription": "Noise"},
            review_status=ImageReviewStatus.REJECTED,
        ))

        accepted = ws.accepted_ocr_analyses()
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].image_id, "img2")

    def test_from_ocr_filter_logic(self):
        """Simulate the from-ocr endpoint filtering logic."""
        ws = Workspace.create("test")
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img1", analyzed=True,
            result={"transcription": "Pending text"},
            review_status=ImageReviewStatus.PENDING,
        ))
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img2", analyzed=True,
            result={"transcription": "Accepted text"},
            review_status=ImageReviewStatus.ACCEPTED,
        ))

        # Only accepted should be collected
        ocr_texts = []
        for analysis in ws.image_analyses:
            if analysis.review_status != ImageReviewStatus.ACCEPTED:
                continue
            text = analysis.result.get("transcription", "")
            if text.strip():
                ocr_texts.append(text)

        self.assertEqual(len(ocr_texts), 1)
        self.assertEqual(ocr_texts[0], "Accepted text")


class TestNERGating(unittest.TestCase):
    """Verify that only accepted entities transfer to dictionary."""

    def test_only_accepted_to_dictionary(self):
        ws = Workspace.create("test")
        ws.add_entities([
            {"text": "Berlin", "type": "LOC", "confidence": 0.9},
            {"text": "Bach", "type": "PER", "confidence": 0.8},
            {"text": "Noise", "type": "PER", "confidence": 0.3},
        ])

        # Accept Berlin and Bach, reject Noise
        ws.entity_reviews[0].accept()
        ws.entity_reviews[1].accept()
        ws.entity_reviews[2].reject()

        # Simulate from-ner logic: only accepted
        entries_to_add = []
        for er in ws.entity_reviews:
            if er.status != ReviewStatus.ACCEPTED:
                continue
            entries_to_add.append({
                "term": er.text,
                "entity_type": er.entity_type,
                "source": "ner",
            })

        added = ws.add_to_dictionary(entries_to_add)
        self.assertEqual(added, 2)
        self.assertEqual(len(ws.dictionary), 2)
        terms = {e.term for e in ws.dictionary}
        self.assertIn("Berlin", terms)
        self.assertIn("Bach", terms)
        self.assertNotIn("Noise", terms)


class TestAuthorityGating(unittest.TestCase):
    """Verify that authority candidates must be accepted before commit."""

    def test_commit_only_accepted(self):
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(term="Berlin", entry_id="e1"))
        ws.add_entry(DictionaryEntry(term="München", entry_id="e2"))

        # GND candidate for Berlin - accepted
        c1 = AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="4005765-8",
            preferred_name="Berlin", uri="https://d-nb.info/gnd/4005765-8",
        )
        c1.accept()

        # GND candidate for München - still pending
        c2 = AuthorityCandidate(
            entry_id="e2", source="gnd", authority_id="4127793-4",
            preferred_name="München",
        )

        ws.add_authority_candidate(c1)
        ws.add_authority_candidate(c2)

        # Simulate commit logic
        committed = 0
        for candidate in ws.authority_candidates:
            if candidate.status != ReviewStatus.ACCEPTED:
                continue
            entry = ws.lookup_by_id(candidate.entry_id)
            if entry and candidate.source == "gnd":
                entry.gnd_id = candidate.authority_id
                committed += 1

        self.assertEqual(committed, 1)
        berlin = ws.lookup_by_id("e1")
        self.assertEqual(berlin.gnd_id, "4005765-8")
        munich = ws.lookup_by_id("e2")
        self.assertEqual(munich.gnd_id, "")


class TestDictionaryExport(unittest.TestCase):
    """Verify target JSON format output."""

    def test_target_format(self):
        entry = DictionaryEntry(
            term="Joh. Seb. Bach",
            entry_id="term_001",
            entity_type="person",
            preferred_name="Johann Sebastian Bach",
            record_ids=["rec_001", "rec_002"],
            gnd_id="11850529X",
            wikidata_id="Q1339",
            source="ocr",
            term_normalized="Johann Sebastian Bach",
            term_source="ocr",
        )

        target = {
            "id": entry.entry_id,
            "category": entry.entity_type,
            "term_source": entry.term,
            "term_normalized": entry.term_normalized or entry.preferred_name or entry.term,
            "source": entry.term_source or entry.source,
            "authority": {
                "wikidata_qid": entry.wikidata_id or None,
                "gnd_id": entry.gnd_id or None,
                "geonames_id": entry.geonames_id or None,
            },
            "occurrences": [{"record_id": rid} for rid in entry.record_ids],
        }

        self.assertEqual(target["id"], "term_001")
        self.assertEqual(target["category"], "person")
        self.assertEqual(target["term_source"], "Joh. Seb. Bach")
        self.assertEqual(target["term_normalized"], "Johann Sebastian Bach")
        self.assertEqual(target["source"], "ocr")
        self.assertEqual(target["authority"]["gnd_id"], "11850529X")
        self.assertEqual(target["authority"]["wikidata_qid"], "Q1339")
        self.assertIsNone(target["authority"]["geonames_id"])
        self.assertEqual(len(target["occurrences"]), 2)

    def test_new_fields_in_to_dict(self):
        entry = DictionaryEntry(
            term="Test",
            term_normalized="test",
            term_source="metadata",
        )
        d = entry.to_dict()
        self.assertEqual(d["term_normalized"], "test")
        self.assertEqual(d["term_source"], "metadata")

        # Roundtrip
        entry2 = DictionaryEntry.from_dict(d)
        self.assertEqual(entry2.term_normalized, "test")
        self.assertEqual(entry2.term_source, "metadata")


class TestTextNormalization(unittest.TestCase):

    def test_whitespace_collapse(self):
        self.assertEqual(normalize_term("  Johann   Sebastian   Bach  "), "Johann Sebastian Bach")

    def test_nfc_normalization(self):
        # ä composed vs decomposed
        composed = "Ä"  # U+00C4
        decomposed = "A\u0308"  # A + combining diaeresis
        self.assertEqual(normalize_term(composed), normalize_term(decomposed))

    def test_empty(self):
        self.assertEqual(normalize_term(""), "")
        self.assertEqual(normalize_term("   "), "")

    def test_tabs_and_newlines(self):
        self.assertEqual(normalize_term("hello\t\tworld\n"), "hello world")


class TestPipelineStatus(unittest.TestCase):

    def test_counts(self):
        ws = Workspace.create("test")
        # Add some image analyses
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img1", review_status=ImageReviewStatus.ACCEPTED,
        ))
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="img2", review_status=ImageReviewStatus.PENDING,
        ))

        # Add entities
        ws.add_entities([
            {"text": "Berlin", "type": "LOC"},
            {"text": "Bach", "type": "PER"},
        ])
        ws.entity_reviews[0].accept()

        # Add authority candidates
        c = AuthorityCandidate(entry_id="e1", source="gnd")
        c.accept()
        ws.add_authority_candidate(c)
        ws.add_authority_candidate(AuthorityCandidate(entry_id="e2", source="gnd"))

        # Add dictionary entries
        ws.add_entry(DictionaryEntry(term="Berlin", gnd_id="4005765-8"))
        ws.add_entry(DictionaryEntry(term="Bach"))

        # Check pipeline status
        ocr_stats = ws.image_review_stats()
        self.assertEqual(ocr_stats["total"], 2)

        ner_stats = ws.review_stats()
        self.assertEqual(ner_stats["total"], 2)
        self.assertEqual(ner_stats["accepted"], 1)

        auth_stats = ws.authority_review_stats()
        self.assertEqual(auth_stats["total"], 2)
        self.assertEqual(auth_stats["accepted"], 1)
        self.assertEqual(auth_stats["pending"], 1)

        dict_enriched = sum(1 for e in ws.dictionary if e.has_authority)
        self.assertEqual(dict_enriched, 1)
        self.assertEqual(len(ws.dictionary), 2)


if __name__ == "__main__":
    unittest.main()
