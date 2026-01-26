"""
Tests for E-Boekhouden Progress Tracking Utilities

Tests the progress tracking module which provides throttled commit
progress updates for migration operations.

Key functionality tested:
- MigrationProgressTracker class state management
- Throttled commits at percentage milestones
- Operation-based and percentage-based tracking
- Phase management and elapsed time calculation
- Error recording
- Convenience function for one-off updates

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_progress_utils
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import frappe


class TestMigrationProgressTrackerInit(unittest.TestCase):
    """Tests for MigrationProgressTracker initialization"""

    def test_init_with_defaults(self):
        """Test initialization with default values"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()

        self.assertIsNone(tracker.migration_doc)
        self.assertIsNone(tracker.state["phase"])
        self.assertIsNone(tracker.state["current_operation"])
        self.assertEqual(tracker.state["progress_percentage"], 0)
        self.assertEqual(tracker.state["total_operations"], 0)
        self.assertEqual(tracker.state["completed_operations"], 0)
        self.assertIsNone(tracker.state["start_time"])
        self.assertIsNone(tracker.state["phase_start_time"])
        self.assertEqual(tracker.state["errors"], [])

    def test_init_with_migration_doc(self):
        """Test initialization with migration document"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)

        self.assertEqual(tracker.migration_doc, mock_doc)

    def test_init_with_total_operations(self):
        """Test initialization with total operations count"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=100)

        self.assertEqual(tracker.state["total_operations"], 100)

    def test_commit_milestones_defined(self):
        """Test that commit milestones include expected values"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        expected_milestones = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
        self.assertEqual(MigrationProgressTracker.COMMIT_MILESTONES, expected_milestones)


class TestMigrationProgressTrackerStart(unittest.TestCase):
    """Tests for start() method"""

    def test_start_sets_phase(self):
        """Test that start() sets the phase name"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.start("accounts")

        self.assertEqual(tracker.state["phase"], "accounts")

    def test_start_sets_start_time(self):
        """Test that start() sets start_time on first call"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        before = datetime.now()
        tracker.start("accounts")
        after = datetime.now()

        self.assertIsNotNone(tracker.state["start_time"])
        self.assertGreaterEqual(tracker.state["start_time"], before)
        self.assertLessEqual(tracker.state["start_time"], after)

    def test_start_preserves_start_time_on_subsequent_calls(self):
        """Test that start() doesn't overwrite start_time on subsequent phases"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.start("phase1")
        first_start_time = tracker.state["start_time"]

        tracker.start("phase2")

        self.assertEqual(tracker.state["start_time"], first_start_time)

    def test_start_sets_phase_start_time(self):
        """Test that start() sets phase_start_time"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.start("accounts")

        self.assertIsNotNone(tracker.state["phase_start_time"])

    def test_start_resets_progress_percentage(self):
        """Test that start() resets progress to 0"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.state["progress_percentage"] = 50
        tracker.start("new_phase")

        self.assertEqual(tracker.state["progress_percentage"], 0)

    def test_start_sets_current_operation(self):
        """Test that start() sets current operation message"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.start("accounts")

        self.assertEqual(tracker.state["current_operation"], "Starting accounts...")

    def test_start_with_total_operations(self):
        """Test that start() can set total_operations"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.start("accounts", total_operations=50)

        self.assertEqual(tracker.state["total_operations"], 50)
        self.assertEqual(tracker.state["completed_operations"], 0)

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_start_persists_with_force_commit(self, mock_frappe):
        """Test that start() persists progress with force commit"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)
        tracker.start("accounts")

        mock_doc.db_set.assert_called_once()
        mock_frappe.db.commit.assert_called_once()


class TestMigrationProgressTrackerUpdatePercentage(unittest.TestCase):
    """Tests for update_percentage() method"""

    def test_update_percentage_sets_operation(self):
        """Test that update_percentage() sets current operation"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.update_percentage("Processing item 5", 50)

        self.assertEqual(tracker.state["current_operation"], "Processing item 5")

    def test_update_percentage_sets_percentage(self):
        """Test that update_percentage() sets progress percentage"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.update_percentage("Processing", 75)

        self.assertEqual(tracker.state["progress_percentage"], 75)

    def test_update_percentage_clamps_to_100(self):
        """Test that percentage is clamped to max 100"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.update_percentage("Processing", 150)

        self.assertEqual(tracker.state["progress_percentage"], 100)

    def test_update_percentage_clamps_to_0(self):
        """Test that percentage is clamped to min 0"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.update_percentage("Processing", -10)

        self.assertEqual(tracker.state["progress_percentage"], 0)

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_update_percentage_commits_at_milestones(self, mock_frappe):
        """Test that commits occur at 10% milestones"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)

        # Test milestone percentages trigger commit
        for milestone in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            mock_frappe.db.commit.reset_mock()
            tracker.update_percentage("Processing", milestone)
            mock_frappe.db.commit.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_update_percentage_no_commit_between_milestones(self, mock_frappe):
        """Test that no commit occurs between milestones"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)

        # Test non-milestone percentages don't trigger commit
        for percentage in [5, 15, 25, 33, 47, 55, 67, 78, 85, 95]:
            mock_frappe.db.commit.reset_mock()
            tracker.update_percentage("Processing", percentage)
            mock_frappe.db.commit.assert_not_called()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_update_percentage_force_commit(self, mock_frappe):
        """Test that force_commit triggers commit regardless of percentage"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)

        tracker.update_percentage("Processing", 33, force_commit=True)

        mock_frappe.db.commit.assert_called_once()


class TestMigrationProgressTrackerIncrement(unittest.TestCase):
    """Tests for increment() method"""

    def test_increment_increases_completed_operations(self):
        """Test that increment() increases completed_operations count"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=10)
        tracker.increment()

        self.assertEqual(tracker.state["completed_operations"], 1)

    def test_increment_updates_percentage(self):
        """Test that increment() updates percentage based on total"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=10)

        for i in range(5):
            tracker.increment()

        self.assertEqual(tracker.state["completed_operations"], 5)
        self.assertEqual(tracker.state["progress_percentage"], 50)

    def test_increment_sets_operation_if_provided(self):
        """Test that increment() updates operation if provided"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=10)
        tracker.increment("Processing item 1")

        self.assertEqual(tracker.state["current_operation"], "Processing item 1")

    def test_increment_preserves_operation_if_not_provided(self):
        """Test that increment() preserves operation if not provided"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=10)
        tracker.state["current_operation"] = "Existing operation"
        tracker.increment()

        self.assertEqual(tracker.state["current_operation"], "Existing operation")

    def test_increment_caps_percentage_at_100(self):
        """Test that increment() caps percentage at 100"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=5)

        for i in range(10):  # More increments than total
            tracker.increment()

        self.assertEqual(tracker.state["progress_percentage"], 100)

    def test_increment_no_percentage_update_without_total(self):
        """Test that increment() doesn't update percentage if total is 0"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()  # total_operations=0
        tracker.increment()

        self.assertEqual(tracker.state["completed_operations"], 1)
        self.assertEqual(tracker.state["progress_percentage"], 0)


class TestMigrationProgressTrackerComplete(unittest.TestCase):
    """Tests for complete() method"""

    def test_complete_sets_percentage_to_100(self):
        """Test that complete() sets percentage to 100"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.state["progress_percentage"] = 50
        tracker.complete()

        self.assertEqual(tracker.state["progress_percentage"], 100)

    def test_complete_sets_default_message(self):
        """Test that complete() sets default completion message"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.complete()

        self.assertEqual(tracker.state["current_operation"], "Completed")

    def test_complete_sets_custom_message(self):
        """Test that complete() can set custom message"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.complete("Migration finished successfully!")

        self.assertEqual(tracker.state["current_operation"], "Migration finished successfully!")

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_complete_force_commits(self, mock_frappe):
        """Test that complete() forces a commit"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)
        tracker.complete()

        mock_frappe.db.commit.assert_called_once()


class TestMigrationProgressTrackerRecordError(unittest.TestCase):
    """Tests for record_error() method"""

    def test_record_error_adds_to_errors_list(self):
        """Test that record_error() appends to errors list"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.record_error("Something went wrong")

        self.assertEqual(len(tracker.state["errors"]), 1)

    def test_record_error_includes_message(self):
        """Test that error record includes message"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.record_error("Database connection failed")

        self.assertEqual(tracker.state["errors"][0]["message"], "Database connection failed")

    def test_record_error_includes_timestamp(self):
        """Test that error record includes timestamp"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.record_error("Error")

        self.assertIn("timestamp", tracker.state["errors"][0])

    def test_record_error_includes_phase(self):
        """Test that error record includes current phase"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.start("accounts")
        tracker.record_error("Error during accounts")

        self.assertEqual(tracker.state["errors"][0]["phase"], "accounts")

    def test_record_error_includes_operation(self):
        """Test that error record includes current operation"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.update_percentage("Processing item 42", 50)
        tracker.record_error("Failed to process item")

        self.assertEqual(tracker.state["errors"][0]["operation"], "Processing item 42")

    def test_record_error_with_context(self):
        """Test that error record can include context"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        context = {"item_id": 42, "retry_count": 3}
        tracker.record_error("Failed after retries", context=context)

        self.assertEqual(tracker.state["errors"][0]["context"], context)

    def test_record_multiple_errors(self):
        """Test that multiple errors can be recorded"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.record_error("Error 1")
        tracker.record_error("Error 2")
        tracker.record_error("Error 3")

        self.assertEqual(len(tracker.state["errors"]), 3)


class TestMigrationProgressTrackerGetProgress(unittest.TestCase):
    """Tests for get_progress() method"""

    def test_get_progress_returns_copy(self):
        """Test that get_progress() returns a copy of state"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        progress = tracker.get_progress()

        # Modifying returned dict shouldn't affect internal state
        progress["phase"] = "modified"
        self.assertIsNone(tracker.state["phase"])

    def test_get_progress_includes_operation_percentage(self):
        """Test that get_progress() computes operation_percentage"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=10)
        tracker.state["completed_operations"] = 3

        progress = tracker.get_progress()

        self.assertEqual(progress["operation_percentage"], 30.0)

    def test_get_progress_includes_elapsed_seconds(self):
        """Test that get_progress() computes elapsed_seconds"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.state["start_time"] = datetime.now() - timedelta(seconds=30)

        progress = tracker.get_progress()

        self.assertIn("elapsed_seconds", progress)
        self.assertGreaterEqual(progress["elapsed_seconds"], 30)

    def test_get_progress_includes_phase_elapsed_seconds(self):
        """Test that get_progress() computes phase_elapsed_seconds"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        tracker.state["phase_start_time"] = datetime.now() - timedelta(seconds=15)

        progress = tracker.get_progress()

        self.assertIn("phase_elapsed_seconds", progress)
        self.assertGreaterEqual(progress["phase_elapsed_seconds"], 15)

    def test_get_progress_no_elapsed_without_start_time(self):
        """Test that elapsed_seconds not computed if no start_time"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()
        progress = tracker.get_progress()

        self.assertNotIn("elapsed_seconds", progress)


class TestMigrationProgressTrackerPersistence(unittest.TestCase):
    """Tests for _persist_progress() method"""

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_persist_skipped_without_migration_doc(self, mock_frappe):
        """Test that persistence is skipped if no migration_doc"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()  # No migration_doc
        tracker._persist_progress()

        mock_frappe.db.commit.assert_not_called()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_persist_calls_db_set(self, mock_frappe):
        """Test that persistence calls db_set with correct values"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)
        tracker.state["current_operation"] = "Test operation"
        tracker.state["progress_percentage"] = 42

        tracker._persist_progress()

        mock_doc.db_set.assert_called_once_with({
            "current_operation": "Test operation",
            "progress_percentage": 42,
        })

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_persist_commits_when_forced(self, mock_frappe):
        """Test that persistence commits when force_commit=True"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)

        tracker._persist_progress(force_commit=True)

        mock_frappe.db.commit.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_persist_no_commit_without_force(self, mock_frappe):
        """Test that persistence doesn't commit without force_commit"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        tracker = MigrationProgressTracker(migration_doc=mock_doc)

        tracker._persist_progress(force_commit=False)

        mock_frappe.db.commit.assert_not_called()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_persist_handles_exception(self, mock_frappe):
        """Test that persistence handles exceptions gracefully"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        mock_doc = MagicMock()
        mock_doc.db_set.side_effect = Exception("Database error")
        tracker = MigrationProgressTracker(migration_doc=mock_doc)

        # Should not raise
        tracker._persist_progress()

        mock_frappe.log_error.assert_called_once()


class TestUpdateMigrationProgressFunction(unittest.TestCase):
    """Tests for update_migration_progress() convenience function"""

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_calls_db_set(self, mock_frappe):
        """Test that function calls db_set with correct values"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            update_migration_progress,
        )

        mock_doc = MagicMock()

        update_migration_progress(mock_doc, "Processing", 50)

        mock_doc.db_set.assert_called_once_with({
            "current_operation": "Processing",
            "progress_percentage": 50,
        })

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_commits_at_milestones(self, mock_frappe):
        """Test that function commits at 10% milestones"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            update_migration_progress,
        )

        mock_doc = MagicMock()

        for milestone in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            mock_frappe.db.commit.reset_mock()
            update_migration_progress(mock_doc, "Processing", milestone)
            mock_frappe.db.commit.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_no_commit_between_milestones(self, mock_frappe):
        """Test that function doesn't commit between milestones"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            update_migration_progress,
        )

        mock_doc = MagicMock()

        for percentage in [5, 15, 25, 33, 47, 55, 67, 78, 85, 95]:
            mock_frappe.db.commit.reset_mock()
            update_migration_progress(mock_doc, "Processing", percentage)
            mock_frappe.db.commit.assert_not_called()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_force_commit(self, mock_frappe):
        """Test that force_commit triggers commit regardless of percentage"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            update_migration_progress,
        )

        mock_doc = MagicMock()

        update_migration_progress(mock_doc, "Processing", 33, force_commit=True)

        mock_frappe.db.commit.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.consolidated.progress_utils.frappe")
    def test_handles_exception(self, mock_frappe):
        """Test that function handles exceptions gracefully"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            update_migration_progress,
        )

        mock_doc = MagicMock()
        mock_doc.db_set.side_effect = Exception("Database error")

        # Should not raise
        update_migration_progress(mock_doc, "Processing", 50)

        mock_frappe.log_error.assert_called_once()


class TestMigrationProgressTrackerIntegration(unittest.TestCase):
    """Integration tests for typical usage patterns"""

    def test_typical_migration_flow(self):
        """Test a typical migration workflow"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker(total_operations=100)

        # Phase 1: Accounts
        tracker.start("accounts", total_operations=20)
        for i in range(20):
            tracker.increment(f"Processing account {i+1}")
        tracker.complete("Accounts phase complete")

        # Phase 2: Transactions
        tracker.start("transactions", total_operations=80)
        for i in range(80):
            if i == 50:
                tracker.record_error("Failed to process transaction 50")
            tracker.increment(f"Processing transaction {i+1}")
        tracker.complete("Transactions phase complete")

        # Verify final state
        progress = tracker.get_progress()
        self.assertEqual(progress["phase"], "transactions")
        self.assertEqual(progress["progress_percentage"], 100)
        self.assertEqual(len(progress["errors"]), 1)
        self.assertIn("elapsed_seconds", progress)

    def test_percentage_based_tracking(self):
        """Test percentage-based tracking workflow"""
        from verenigingen.e_boekhouden.utils.consolidated.progress_utils import (
            MigrationProgressTracker,
        )

        tracker = MigrationProgressTracker()

        tracker.start("import")
        tracker.update_percentage("Validating data", 10)
        tracker.update_percentage("Processing records", 50)
        tracker.update_percentage("Finalizing", 90)
        tracker.complete()

        self.assertEqual(tracker.state["progress_percentage"], 100)
        self.assertEqual(tracker.state["current_operation"], "Completed")
