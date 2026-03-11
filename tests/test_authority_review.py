"""
Tests for authority candidate CRUD, review, and commit-to-dictionary flow.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import unittest

from kwb.core.workspace import (
    Workspace, DictionaryEntry, AuthorityCandidate, ReviewStatus,
)


class TestAuthorityCandidateCRUD(unittest.TestCase):

    def test_add_candidate(self):
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(term="Berlin", entry_id="e1"))
        ws.add_authority_candidate(AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="4005765-8",
            preferred_name="Berlin", score=0.85,
        ))
        self.assertEqual(len(ws.authority_candidates), 1)

    def test_candidates_for_entry(self):
        ws = Workspace.create("test")
        ws.add_authority_candidate(AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="1",
        ))
        ws.add_authority_candidate(AuthorityCandidate(
            entry_id="e2", source="gnd", authority_id="2",
        ))
        ws.add_authority_candidate(AuthorityCandidate(
            entry_id="e1", source="wikidata", authority_id="Q64",
        ))
        self.assertEqual(len(ws.authority_candidates_for_entry("e1")), 2)
        self.assertEqual(len(ws.authority_candidates_for_entry("e2")), 1)
        self.assertEqual(len(ws.authority_candidates_for_entry("e3")), 0)


class TestAuthorityCandidateReview(unittest.TestCase):

    def test_accept_and_reject(self):
        ws = Workspace.create("test")
        c1 = AuthorityCandidate(entry_id="e1", source="gnd")
        c2 = AuthorityCandidate(entry_id="e2", source="gnd")
        ws.add_authority_candidate(c1)
        ws.add_authority_candidate(c2)

        c1.accept(note="correct")
        c2.reject(note="wrong match")

        stats = ws.authority_review_stats()
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["pending"], 0)

    def test_review_stats_initial(self):
        ws = Workspace.create("test")
        ws.add_authority_candidate(AuthorityCandidate(entry_id="e1", source="gnd"))
        ws.add_authority_candidate(AuthorityCandidate(entry_id="e2", source="gnd"))
        stats = ws.authority_review_stats()
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["total"], 2)


class TestAuthorityCommit(unittest.TestCase):

    def test_commit_gnd(self):
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(term="Berlin", entry_id="e1"))

        c = AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="4005765-8",
            preferred_name="Berlin", authority_type="PlaceOrGeographicName",
            uri="https://d-nb.info/gnd/4005765-8",
        )
        c.accept()
        ws.add_authority_candidate(c)

        # Commit
        for candidate in ws.authority_candidates:
            if candidate.status != ReviewStatus.ACCEPTED:
                continue
            entry = ws.lookup_by_id(candidate.entry_id)
            if entry and candidate.source == "gnd":
                entry.gnd_id = candidate.authority_id
                entry.gnd_preferred = candidate.preferred_name
                entry.gnd_type = candidate.authority_type
                entry.gnd_uri = candidate.uri

        berlin = ws.lookup_by_id("e1")
        self.assertEqual(berlin.gnd_id, "4005765-8")
        self.assertEqual(berlin.gnd_uri, "https://d-nb.info/gnd/4005765-8")

    def test_commit_wikidata(self):
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(term="Berlin", entry_id="e1"))

        c = AuthorityCandidate(
            entry_id="e1", source="wikidata", authority_id="Q64",
            extra={"gnd_id": "4005765-8"},
        )
        c.accept()
        ws.add_authority_candidate(c)

        for candidate in ws.authority_candidates:
            if candidate.status != ReviewStatus.ACCEPTED:
                continue
            entry = ws.lookup_by_id(candidate.entry_id)
            if entry and candidate.source == "wikidata":
                entry.wikidata_id = candidate.authority_id
                if not entry.gnd_id and candidate.extra.get("gnd_id"):
                    entry.gnd_id = candidate.extra["gnd_id"]

        berlin = ws.lookup_by_id("e1")
        self.assertEqual(berlin.wikidata_id, "Q64")
        self.assertEqual(berlin.gnd_id, "4005765-8")

    def test_commit_geonames(self):
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(term="Berlin", entry_id="e1"))

        c = AuthorityCandidate(
            entry_id="e1", source="geonames", authority_id="2950159",
        )
        c.accept()
        ws.add_authority_candidate(c)

        for candidate in ws.authority_candidates:
            if candidate.status != ReviewStatus.ACCEPTED:
                continue
            entry = ws.lookup_by_id(candidate.entry_id)
            if entry and candidate.source == "geonames":
                entry.geonames_id = candidate.authority_id

        berlin = ws.lookup_by_id("e1")
        self.assertEqual(berlin.geonames_id, "2950159")

    def test_pending_not_committed(self):
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(term="Berlin", entry_id="e1"))

        c = AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="4005765-8",
        )
        # NOT accepted
        ws.add_authority_candidate(c)

        committed = 0
        for candidate in ws.authority_candidates:
            if candidate.status != ReviewStatus.ACCEPTED:
                continue
            committed += 1

        self.assertEqual(committed, 0)
        berlin = ws.lookup_by_id("e1")
        self.assertEqual(berlin.gnd_id, "")

    def test_full_workspace_roundtrip(self):
        """Full serialization roundtrip with authority candidates."""
        ws = Workspace.create("test")
        ws.add_entry(DictionaryEntry(
            term="Berlin", entry_id="e1",
            term_normalized="Berlin", term_source="metadata",
        ))
        c = AuthorityCandidate(
            entry_id="e1", source="gnd", authority_id="4005765-8",
            preferred_name="Berlin",
        )
        c.accept()
        ws.add_authority_candidate(c)

        # Roundtrip
        json_str = ws.to_json()
        ws2 = Workspace.from_json(json_str)

        self.assertEqual(len(ws2.authority_candidates), 1)
        self.assertEqual(ws2.authority_candidates[0].status, ReviewStatus.ACCEPTED)
        self.assertEqual(ws2.authority_candidates[0].authority_id, "4005765-8")

        self.assertEqual(len(ws2.dictionary), 1)
        self.assertEqual(ws2.dictionary[0].term_normalized, "Berlin")
        self.assertEqual(ws2.dictionary[0].term_source, "metadata")

        # Summary should include authority stats
        summary = ws2.to_summary()
        self.assertEqual(summary["authority_candidates_count"], 1)
        self.assertEqual(summary["authority_review_status"]["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
