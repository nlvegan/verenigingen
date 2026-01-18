# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for DuesScheduleLifecycleService.

Tests schedule lifecycle operations including:
- Pause/resume operations
- Status transition validation
- Cancel operations
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.services.billing.dues_schedule_lifecycle_service import (
    DuesScheduleLifecycleService,
    get_dues_schedule_lifecycle_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.exceptions import InvalidStatusTransitionError


class TestDuesScheduleLifecycleService(EnhancedTestCase):
    """Test suite for DuesScheduleLifecycleService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_dues_schedule_lifecycle_service()

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        service = DuesScheduleLifecycleService()
        self.assertEqual(service.service_name, "DuesScheduleLifecycleService")
        self.assertIsNotNone(service.logger)

    def test_get_lifecycle_service_returns_instance(self):
        """Test that factory function returns service instance."""
        service = get_dues_schedule_lifecycle_service()
        self.assertIsInstance(service, DuesScheduleLifecycleService)

    def test_allowed_transitions_defined(self):
        """Test that status transitions are properly defined."""
        transitions = DuesScheduleLifecycleService.ALLOWED_TRANSITIONS

        self.assertIn("Active", transitions)
        self.assertIn("Paused", transitions)
        self.assertIn("Cancelled", transitions)
        self.assertIn("Test", transitions)

        # Active can transition to Paused or Cancelled
        self.assertIn("Paused", transitions["Active"])
        self.assertIn("Cancelled", transitions["Active"])

        # Paused can transition to Active or Cancelled
        self.assertIn("Active", transitions["Paused"])
        self.assertIn("Cancelled", transitions["Paused"])

        # Cancelled is terminal
        self.assertEqual(transitions["Cancelled"], [])


class TestPauseSchedule(EnhancedTestCase):
    """Test suite for pause_schedule functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_dues_schedule_lifecycle_service()

    def test_pause_active_schedule(self):
        """Test pausing an active schedule."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Active"
        mock_schedule.notes = None

        self.service.pause_schedule(mock_schedule, reason="Member requested")

        self.assertEqual(mock_schedule.status, "Paused")
        mock_schedule.save.assert_called_once()
        self.assertIn("Paused on", mock_schedule.notes)
        self.assertIn("Member requested", mock_schedule.notes)

    def test_pause_test_schedule(self):
        """Test pausing a test mode schedule."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Test"
        mock_schedule.notes = "Existing notes"

        self.service.pause_schedule(mock_schedule, reason="Testing pause")

        self.assertEqual(mock_schedule.status, "Paused")
        self.assertIn("Existing notes", mock_schedule.notes)
        self.assertIn("Testing pause", mock_schedule.notes)

    def test_pause_without_reason(self):
        """Test pausing without providing a reason."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Active"
        mock_schedule.notes = None

        self.service.pause_schedule(mock_schedule)

        self.assertEqual(mock_schedule.status, "Paused")
        # Notes should not be set when no reason provided
        self.assertIsNone(mock_schedule.notes)

    def test_pause_invalid_status(self):
        """Test that pausing a cancelled schedule raises error."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Cancelled"

        with self.assertRaises(InvalidStatusTransitionError):
            self.service.pause_schedule(mock_schedule)


class TestResumeSchedule(EnhancedTestCase):
    """Test suite for resume_schedule functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_dues_schedule_lifecycle_service()

    def test_resume_paused_schedule(self):
        """Test resuming a paused schedule."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Paused"
        mock_schedule.notes = None
        mock_schedule.next_invoice_date = "2025-01-15"

        self.service.resume_schedule(mock_schedule)

        self.assertEqual(mock_schedule.status, "Active")
        mock_schedule.save.assert_called_once()
        self.assertIn("Resumed on", mock_schedule.notes)

    def test_resume_with_new_date(self):
        """Test resuming with a new next invoice date."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Paused"
        mock_schedule.notes = None
        mock_schedule.next_invoice_date = "2025-01-15"

        self.service.resume_schedule(mock_schedule, new_next_date="2025-02-01")

        self.assertEqual(mock_schedule.status, "Active")
        self.assertEqual(mock_schedule.next_invoice_date, "2025-02-01")

    def test_resume_invalid_status(self):
        """Test that resuming an active schedule raises error."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Active"

        with self.assertRaises(InvalidStatusTransitionError):
            self.service.resume_schedule(mock_schedule)


class TestStatusTransitionValidation(EnhancedTestCase):
    """Test suite for status transition validation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_dues_schedule_lifecycle_service()

    def test_validate_new_document_always_passes(self):
        """Test that new documents skip validation."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = True

        # Should not raise
        self.service.validate_status_transition(mock_schedule)

    def test_validate_no_previous_state(self):
        """Test that validation passes when no previous state exists."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = False
        mock_schedule._doc_before_save = None

        # Should not raise
        self.service.validate_status_transition(mock_schedule)

    def test_validate_same_status(self):
        """Test that same status transition is allowed."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = False
        mock_schedule.status = "Active"
        mock_schedule._doc_before_save = MagicMock()
        mock_schedule._doc_before_save.status = "Active"

        # Should not raise
        self.service.validate_status_transition(mock_schedule)

    def test_validate_allowed_transition(self):
        """Test that allowed transitions pass validation."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = False
        mock_schedule.status = "Paused"
        mock_schedule._doc_before_save = MagicMock()
        mock_schedule._doc_before_save.status = "Active"

        # Should not raise (Active -> Paused is allowed)
        self.service.validate_status_transition(mock_schedule)

    def test_validate_disallowed_transition(self):
        """Test that disallowed transitions raise error."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = False
        mock_schedule.status = "Active"
        mock_schedule._doc_before_save = MagicMock()
        mock_schedule._doc_before_save.status = "Cancelled"

        # Cancelled -> Active is not allowed
        with self.assertRaises(InvalidStatusTransitionError):
            self.service.validate_status_transition(mock_schedule)


class TestCancelSchedule(EnhancedTestCase):
    """Test suite for cancel_schedule functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_dues_schedule_lifecycle_service()

    def test_cancel_active_schedule(self):
        """Test cancelling an active schedule."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Active"
        mock_schedule.notes = None

        self.service.cancel_schedule(mock_schedule, reason="Membership terminated")

        self.assertEqual(mock_schedule.status, "Cancelled")
        mock_schedule.save.assert_called_once()
        self.assertIn("Cancelled on", mock_schedule.notes)
        self.assertIn("Membership terminated", mock_schedule.notes)

    def test_cancel_paused_schedule(self):
        """Test cancelling a paused schedule."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Paused"
        mock_schedule.notes = "Was paused"

        self.service.cancel_schedule(mock_schedule)

        self.assertEqual(mock_schedule.status, "Cancelled")

    def test_cancel_already_cancelled(self):
        """Test that cancelling already cancelled schedule is idempotent."""
        mock_schedule = MagicMock()
        mock_schedule.status = "Cancelled"
        mock_schedule.name = "Test-Schedule"

        # Should not raise, just log and return
        self.service.cancel_schedule(mock_schedule)

        # save should NOT be called for already cancelled
        mock_schedule.save.assert_not_called()
