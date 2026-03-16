"""Tests for pipeline step state management."""
import unittest
from unittest.mock import patch

from kwb.api.routes.pipeline import (
    _compute_step_status,
    _check_prerequisites,
    STEP_DEFS,
)


class TestPipelineSteps(unittest.TestCase):
    """Test pipeline step logic."""

    def test_step_definitions(self):
        self.assertEqual(len(STEP_DEFS), 7)
        for i, sd in enumerate(STEP_DEFS):
            self.assertEqual(sd["number"], i + 1)
            self.assertIn("key", sd)
            self.assertIn("name", sd)

    def test_compute_status_completed(self):
        pipeline = {"active_step": 3, "completed_steps": [1, 2]}
        self.assertEqual(_compute_step_status(1, pipeline), "completed")
        self.assertEqual(_compute_step_status(2, pipeline), "completed")

    def test_compute_status_active(self):
        pipeline = {"active_step": 3, "completed_steps": [1, 2]}
        self.assertEqual(_compute_step_status(3, pipeline), "active")

    def test_compute_status_locked(self):
        pipeline = {"active_step": 2, "completed_steps": [1]}
        self.assertEqual(_compute_step_status(5, pipeline), "locked")

    def test_step1_always_available(self):
        pipeline = {"active_step": 1, "completed_steps": []}
        can, reason = _check_prerequisites(1, pipeline)
        self.assertTrue(can)

    @patch("kwb.api.routes.pipeline.get_datasets")
    @patch("kwb.api.routes.pipeline.get_workspace")
    def test_step2_needs_data(self, mock_ws, mock_ds):
        mock_ds.return_value = {}
        pipeline = {"active_step": 1, "completed_steps": []}
        can, reason = _check_prerequisites(2, pipeline)
        self.assertFalse(can)
        self.assertIn("Daten", reason)

    @patch("kwb.api.routes.pipeline.get_datasets")
    @patch("kwb.api.routes.pipeline.get_workspace")
    def test_step2_with_data(self, mock_ws, mock_ds):
        mock_ds.return_value = {"test.csv": ("df", "profile")}
        pipeline = {"active_step": 1, "completed_steps": [1]}
        can, reason = _check_prerequisites(2, pipeline)
        self.assertTrue(can)

    @patch("kwb.api.routes.pipeline.get_datasets")
    @patch("kwb.api.routes.pipeline.get_workspace")
    def test_step3_needs_test_batch(self, mock_ws, mock_ds):
        pipeline = {
            "active_step": 2, "completed_steps": [1],
            "test_batch_ner": False, "test_batch_images": False,
        }
        can, reason = _check_prerequisites(3, pipeline)
        self.assertFalse(can)

    @patch("kwb.api.routes.pipeline.get_datasets")
    @patch("kwb.api.routes.pipeline.get_workspace")
    def test_step3_with_test_batch(self, mock_ws, mock_ds):
        pipeline = {
            "active_step": 2, "completed_steps": [1, 2],
            "test_batch_ner": True, "test_batch_images": False,
        }
        can, reason = _check_prerequisites(3, pipeline)
        self.assertTrue(can)

    @patch("kwb.api.routes.pipeline.get_datasets")
    @patch("kwb.api.routes.pipeline.get_workspace")
    def test_step4_needs_review(self, mock_ws, mock_ds):
        pipeline = {
            "active_step": 3, "completed_steps": [1, 2],
            "test_batch_reviewed": False,
        }
        can, reason = _check_prerequisites(4, pipeline)
        self.assertFalse(can)


if __name__ == "__main__":
    unittest.main()
