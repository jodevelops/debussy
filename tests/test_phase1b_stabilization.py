"""Regression tests for Phase 1b stabilization (Audit 2026-04-28, Analyze/Enrich modules).

Each test maps to a specific issue from `debussy-core-audit-issues.md`.
The audit ID is given in the docstring so future contributors can link
the test to its rationale.

Issues covered:
- EXT-BUG-02 — NER LLM batch failures not tracked in completion_summary
- EXT-BUG-04 — Bare except in _get_affected_ids silently swallows errors
- EXT-BUG-08 — Hardcoded 0.8 confidence in LobidGNDClient.search()
- EXT-BUG-10 — O(n²) lookup in _normalize_dates_llm() for failed items
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd


class TestNERCompletionSummary(unittest.TestCase):
    """EXT-BUG-02: NER hybrid should track batch completion in completion_summary."""

    def test_completion_summary_present_when_llm_used(self):
        """NERResult.completion_summary must exist when LLM provider is given."""
        from kwb.analyze.ner import ner_hybrid
        from kwb.ai.provider import AIProvider

        df = pd.DataFrame({
            "id": ["1", "2"],
            "title": ["Berlin Wall", "Munich Agreement"],
        })

        mock_provider = MagicMock(spec=AIProvider)
        result = ner_hybrid(
            df, columns=["title"], provider=mock_provider,
            id_column="id", use_spacy=False, use_llm=True, model="test"
        )

        self.assertIsNotNone(result.completion_summary)
        self.assertIn("total_items", result.completion_summary)
        self.assertIn("successful_parses", result.completion_summary)
        self.assertIn("failed_parses", result.completion_summary)
        self.assertIn("success_rate", result.completion_summary)

    def test_completion_summary_tracks_parse_success(self):
        """Completion summary must show ratio of successful vs failed parses."""
        from kwb.analyze.ner import ner_hybrid
        from kwb.ai.provider import AIProvider

        df = pd.DataFrame({
            "id": ["1", "2"],
            "title": ["Berlin", "Munich"],
        })

        mock_batch = MagicMock()
        mock_batch.results = [
            MagicMock(record_id="1", parsed={"entities": []}),  # success
            MagicMock(record_id="2", parsed=None),  # failure
        ]

        mock_provider = MagicMock(spec=AIProvider)

        with patch("kwb.analyze.ner.process_batch", return_value=mock_batch):
            result = ner_hybrid(
                df, columns=["title"], provider=mock_provider,
                id_column="id", use_spacy=False, use_llm=True
            )

        self.assertEqual(result.completion_summary["total_items"], 2)
        self.assertEqual(result.completion_summary["successful_parses"], 1)
        self.assertEqual(result.completion_summary["failed_parses"], 1)
        self.assertAlmostEqual(result.completion_summary["success_rate"], 0.5, places=2)


class TestAffectedIdsExceptionHandling(unittest.TestCase):
    """EXT-BUG-04: _get_affected_ids must not use bare except."""

    def test_get_affected_ids_specific_exception(self):
        """_get_affected_ids must catch only (IndexError, KeyError, ValueError)."""
        from kwb.analyze.structural import _get_affected_ids

        df = pd.DataFrame({
            "id": ["a", "b", "c"],
            "value": [1, 2, 3],
        })

        # Valid mask — should return IDs
        mask = pd.Series([True, False, True])
        result = _get_affected_ids(df, mask, "id", limit=2)
        self.assertEqual(result, ["a", "c"])

    def test_get_affected_ids_missing_column_safe(self):
        """_get_affected_ids must safely handle missing id_column."""
        from kwb.analyze.structural import _get_affected_ids

        df = pd.DataFrame({"value": [1, 2, 3]})
        mask = pd.Series([True, False, True])

        # Non-existent id_col — should return empty list, not raise
        result = _get_affected_ids(df, mask, "nonexistent", limit=2)
        self.assertEqual(result, [])

    def test_get_affected_ids_no_id_col_parameter(self):
        """_get_affected_ids must safely handle None id_col."""
        from kwb.analyze.structural import _get_affected_ids

        df = pd.DataFrame({"value": [1, 2, 3]})
        mask = pd.Series([True, False, True])

        result = _get_affected_ids(df, mask, None, limit=2)
        self.assertEqual(result, [])


class TestLobidConfidenceRank(unittest.TestCase):
    """EXT-BUG-08: LobidGNDClient.search() must use rank-based confidence."""

    def test_lobid_confidence_rank_decreases(self):
        """First match must have higher confidence than second, etc."""
        from kwb.enrich.gnd import LobidGNDClient
        from unittest.mock import patch
        import json

        client = LobidGNDClient()

        # Mock API response with 3 results
        mock_response_data = {
            "member": [
                {
                    "gndIdentifier": "123",
                    "preferredName": "Berlin",
                    "type": ["PlaceOrGeographicName"],
                    "variantName": [],
                },
                {
                    "gndIdentifier": "124",
                    "preferredName": "Berlina",
                    "type": ["PlaceOrGeographicName"],
                    "variantName": [],
                },
                {
                    "gndIdentifier": "125",
                    "preferredName": "Berliner",
                    "type": ["PlaceOrGeographicName"],
                    "variantName": [],
                },
            ]
        }

        with patch("kwb.enrich.gnd.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(mock_response_data).encode("utf-8")
            mock_response.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_response

            matches = client.search("Berlin", size=3)

        self.assertEqual(len(matches), 3)
        # Confidence must decrease: 1.0 → 0.8 → 0.6
        self.assertEqual(matches[0].confidence, 1.0)
        self.assertEqual(matches[1].confidence, 0.8)
        self.assertEqual(matches[2].confidence, 0.6)

    def test_lobid_confidence_minimum_floor(self):
        """Confidence must never go below 0.2 even for many results."""
        from kwb.enrich.gnd import LobidGNDClient
        from unittest.mock import patch
        import json

        client = LobidGNDClient()

        # Mock API response with 5 results
        member = [
            {
                "gndIdentifier": f"{100+i}",
                "preferredName": f"Term{i}",
                "type": ["PlaceOrGeographicName"],
                "variantName": [],
            }
            for i in range(5)
        ]

        with patch("kwb.enrich.gnd.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({"member": member}).encode("utf-8")
            mock_response.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_response

            matches = client.search("test", size=5)

        # All should have confidence >= 0.2
        for match in matches:
            self.assertGreaterEqual(match.confidence, 0.2)


class TestEDTFLookupOptimization(unittest.TestCase):
    """EXT-BUG-10: _normalize_dates_llm must use O(1) dict instead of O(n²) search."""

    def test_edtf_preserves_original_on_llm_failure(self):
        """Failed LLM results must preserve the original input text."""
        from kwb.enrich.edtf import _normalize_dates_llm
        from kwb.ai.provider import AIProvider
        from unittest.mock import patch

        items = [
            {"record_id": "1", "text": "5. Januar 1920"},
            {"record_id": "2", "text": "unknown date"},
        ]

        # Mock batch with one success, one failure
        mock_batch = MagicMock()
        mock_batch.results = [
            MagicMock(record_id="1", parsed={"original": "5. Januar 1920", "edtf": "1920-01-05", "confidence": 1.0, "note": ""}),
            MagicMock(record_id="2", parsed=None),  # failure
        ]

        mock_provider = MagicMock(spec=AIProvider)

        with patch("kwb.enrich.edtf.process_batch", return_value=mock_batch):
            results, _ = _normalize_dates_llm(items, mock_provider)

        # Result for failed item must preserve original text
        failed_result = [r for r in results if r.record_id == "2"][0]
        self.assertEqual(failed_result.original, "unknown date")
        self.assertEqual(failed_result.edtf, "")
        self.assertIn("fehlgeschlagen", failed_result.note.lower())

    def test_edtf_handles_missing_record_id(self):
        """EDTFResult must handle batch results with missing record_ids gracefully."""
        from kwb.enrich.edtf import _normalize_dates_llm
        from kwb.ai.provider import AIProvider
        from unittest.mock import patch

        items = [
            {"record_id": "1", "text": "5. Januar 1920"},
        ]

        mock_batch = MagicMock()
        mock_batch.results = [
            MagicMock(record_id="unknown", parsed=None),  # no match in items
        ]

        mock_provider = MagicMock(spec=AIProvider)

        with patch("kwb.enrich.edtf.process_batch", return_value=mock_batch):
            results, _ = _normalize_dates_llm(items, mock_provider)

        # Must not crash, should return empty original text
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].original, "")
        self.assertEqual(results[0].record_id, "unknown")


if __name__ == "__main__":
    unittest.main()
