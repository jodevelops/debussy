"""Regression tests for Phase 1 stabilization (Audit 2026-04-28).

Each test maps to a specific issue from `debussy-core-audit-issues.md`.
The audit ID is given in the docstring so future contributors can link
the test to its rationale.

Issues covered:
- CORE-BUG-01 — Duplicate ``image_review_stats()`` method
- CORE-BUG-02 — Two distinct ``ReviewStatus`` enums
- CORE-BUG-04 — Silent JSON load failure in ``UserStore``
- CORE-BUG-06 — ``save_to_dotenv`` only persisted 4 of 13 keys
- CORE-BUG-07 — Deprecated ``datetime.utcnow()`` produced naive timestamps
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path


class TestImageReviewStats(unittest.TestCase):
    """CORE-BUG-01: ``image_review_stats`` must use enum-aligned keys."""

    def test_returned_keys_match_enum(self):
        """Returned dict keys must be exactly ``ImageReviewStatus`` values + ``total``."""
        from kwb.core.workspace import (
            ImageAnalysisResult,
            ImageReviewStatus,
            Workspace,
        )

        ws = Workspace.create("test")
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="x",
            review_status=ImageReviewStatus.ACCEPTED,
        ))
        stats = ws.image_review_stats()

        expected_keys = {s.value for s in ImageReviewStatus} | {"total"}
        self.assertEqual(set(stats.keys()), expected_keys)

    def test_accepted_image_counted_under_accepted_key(self):
        """Regression: previously the buggy duplicate counted under ``"approved"``."""
        from kwb.core.workspace import (
            ImageAnalysisResult,
            ImageReviewStatus,
            Workspace,
        )

        ws = Workspace.create("test")
        ws.save_image_analysis(ImageAnalysisResult(
            image_id="x",
            review_status=ImageReviewStatus.ACCEPTED,
        ))
        stats = ws.image_review_stats()

        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["rejected"], 0)
        self.assertEqual(stats["total"], 1)
        self.assertNotIn("approved", stats)


class TestReviewStatusUnified(unittest.TestCase):
    """CORE-BUG-02: only one ``ReviewStatus`` enum should exist."""

    def test_workspace_reviewstatus_is_models_reviewstatus(self):
        """The two import paths must yield the *same* class object."""
        from kwb.core.models import ReviewStatus as ModelsRS
        from kwb.core.workspace import ReviewStatus as WorkspaceRS

        self.assertIs(ModelsRS, WorkspaceRS)

    def test_pending_value_equality(self):
        """``ReviewStatus.PENDING`` from either module compares as identical."""
        from kwb.core.models import ReviewStatus as ModelsRS
        from kwb.core.workspace import ReviewStatus as WorkspaceRS

        self.assertEqual(ModelsRS.PENDING, WorkspaceRS.PENDING)
        self.assertEqual(ModelsRS.PENDING.value, WorkspaceRS.PENDING.value)


class TestUserStoreCorruptionSafety(unittest.TestCase):
    """CORE-BUG-04: corrupt ``users.json`` must not cause silent admin reset."""

    def test_corrupt_file_blocks_default_admin(self):
        """If the user store can't be loaded, ``ensure_default_admin`` must refuse."""
        from kwb.core.auth import UserStore

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "users.json"
            # Write clearly invalid JSON
            path.write_text("{ this is not valid JSON ", encoding="utf-8")

            store = UserStore(path)
            self.assertFalse(store.load_ok)
            self.assertFalse(
                store.ensure_default_admin(),
                "Default admin must NOT be created when load failed",
            )
            self.assertEqual(store.user_count(), 0)

    def test_corrupt_file_is_preserved(self):
        """Corrupt file must be renamed (with timestamp) so operator can recover."""
        from kwb.core.auth import UserStore

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "users.json"
            path.write_text("not json", encoding="utf-8")

            UserStore(path)

            backups = list(Path(d).glob("users.json.corrupt-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "not json")
            # Original path should no longer hold the corrupt content
            self.assertFalse(path.exists())

    def test_legitimate_first_run_creates_admin(self):
        """A non-existent file is the legitimate first-run case."""
        from kwb.core.auth import UserStore

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "users.json"
            store = UserStore(path)
            self.assertTrue(store.load_ok)
            self.assertTrue(store.ensure_default_admin())
            self.assertEqual(store.user_count(), 1)


class TestSaveToDotenvRoundTrip(unittest.TestCase):
    """CORE-BUG-06: ``save_to_dotenv`` must persist all keys ``load_config`` reads."""

    def test_full_round_trip(self):
        """``load_config → save_to_dotenv → load_config`` preserves every field."""
        from kwb.core.config import KWBConfig, load_config

        cfg = KWBConfig(
            gpustack_url="http://gpu:80",
            gpustack_key="sk-key",
            gpustack_model_text="qwen-text",
            gpustack_model_vision="qwen-vision",
            geonames_username="alice",
            goobi_api_url="http://goobi:8080",
            goobi_api_key="goobi-key",
            goobi_project="GIUB",
            batch_size=42,
            batch_delay_seconds=0.25,
            max_retries=7,
            timeout_seconds=180,
            language="en",
        )
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            cfg.save_to_dotenv(p)
            reloaded = load_config(p)

        self.assertEqual(reloaded.gpustack_url, cfg.gpustack_url)
        self.assertEqual(reloaded.gpustack_key, cfg.gpustack_key)
        self.assertEqual(reloaded.gpustack_model_text, cfg.gpustack_model_text)
        self.assertEqual(reloaded.gpustack_model_vision, cfg.gpustack_model_vision)
        self.assertEqual(reloaded.geonames_username, cfg.geonames_username)
        self.assertEqual(reloaded.goobi_api_url, cfg.goobi_api_url)
        self.assertEqual(reloaded.goobi_api_key, cfg.goobi_api_key)
        self.assertEqual(reloaded.goobi_project, cfg.goobi_project)
        self.assertEqual(reloaded.batch_size, cfg.batch_size)
        self.assertEqual(reloaded.batch_delay_seconds, cfg.batch_delay_seconds)
        self.assertEqual(reloaded.max_retries, cfg.max_retries)
        self.assertEqual(reloaded.timeout_seconds, cfg.timeout_seconds)
        self.assertEqual(reloaded.language, cfg.language)


class TestUtcTimestamps(unittest.TestCase):
    """CORE-BUG-07: timestamps must be UTC and timezone-aware."""

    # ISO-8601 with offset: e.g. "2026-05-05T10:23:11.123456+00:00"
    _ISO_TZ_RE = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$",
    )

    def test_utc_now_iso_has_timezone_offset(self):
        from kwb.core.utils import utc_now_iso

        ts = utc_now_iso()
        self.assertRegex(ts, self._ISO_TZ_RE)

    def test_workspace_created_at_has_timezone(self):
        from kwb.core.workspace import Workspace

        ws = Workspace.create("test")
        self.assertRegex(ws.created_at, self._ISO_TZ_RE)
        self.assertRegex(ws.updated_at, self._ISO_TZ_RE)

    def test_curation_task_created_at_has_timezone(self):
        from kwb.core.tasks import CurationTask

        t = CurationTask(title="x")
        self.assertRegex(t.created_at, self._ISO_TZ_RE)


if __name__ == "__main__":
    unittest.main()
