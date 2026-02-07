# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Unit tests for InvoiceGenerationOrchestrator.

Tests the orchestrator's branching logic (eligibility, test mode, locking, errors)
using mocks — no database or Redis required.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.services.billing.invoice_generation_orchestrator import (
    InvoiceGenerationOrchestrator,
)
from verenigingen.utils.operation_result import OperationResult


def _make_schedule(**overrides):
    """Create a minimal mock schedule for orchestrator tests."""
    sched = MagicMock()
    sched.name = "TEST-SCHED-001"
    sched.member = "TEST-MEM-001"
    sched.dues_rate = 25.0
    sched.test_mode = False
    sched.can_generate_invoice.return_value = (True, "")
    defaults = {}
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(sched, k, v)
    return sched


class TestEligibilitySkipRegression(unittest.TestCase):
    """Regression test: OperationResult.ok(skipped=True) must be detected via metadata, not .success."""

    def test_ineligible_schedule_returns_skipped_result(self):
        """When can_generate_invoice() returns False, generate() must return a skipped result."""
        sched = _make_schedule()
        sched.can_generate_invoice.return_value = (False, "Member not eligible for billing")

        orch = InvoiceGenerationOrchestrator(sched)
        result = orch.generate(force=False)

        # The bug was: .ok(skipped=True) sets success=True, so `if not result.success` never triggered.
        # Fixed: now checks metadata.get("skipped").
        self.assertTrue(result.success, "OperationResult.ok() always sets success=True")
        self.assertTrue(result.metadata.get("skipped"), "Must detect skip via metadata, not .success")
        self.assertIsNone(result.data)
        self.assertEqual(result.metadata.get("reason"), "Member not eligible for billing")

    def test_coverage_overlap_returns_skipped_result(self):
        """Coverage overlap is also a skip — must be caught by the same metadata check."""
        sched = _make_schedule()
        sched.can_generate_invoice.return_value = (False, "Coverage overlap detected")

        orch = InvoiceGenerationOrchestrator(sched)
        result = orch.generate(force=False)

        self.assertTrue(result.metadata.get("skipped"))
        self.assertIn("overlap", result.metadata.get("reason", "").lower())

    def test_force_bypasses_eligibility(self):
        """With force=True, eligibility failure should be ignored."""
        sched = _make_schedule()
        sched.can_generate_invoice.return_value = (False, "Not eligible")
        sched.test_mode = True  # Use test mode to avoid needing full generation pipeline

        orch = InvoiceGenerationOrchestrator(sched)
        result = orch.generate(force=True)

        # Should NOT be skipped — force overrides eligibility
        self.assertFalse(result.metadata.get("skipped", False))
        # Should reach test_mode handler instead
        self.assertTrue(result.metadata.get("test_mode", False))


class TestEligiblePath(unittest.TestCase):
    """Test that eligible schedules proceed past eligibility check."""

    def test_eligible_schedule_does_not_skip(self):
        """When can_generate_invoice() returns True, eligibility check must not set skipped."""
        sched = _make_schedule()
        sched.can_generate_invoice.return_value = (True, "")
        sched.test_mode = True  # Short-circuit at test mode

        orch = InvoiceGenerationOrchestrator(sched)
        result = orch.generate()

        self.assertFalse(result.metadata.get("skipped", False))
        self.assertTrue(result.metadata.get("test_mode", False))


class TestTestMode(unittest.TestCase):
    """Test the test_mode early return path."""

    def test_test_mode_returns_ok_with_metadata(self):
        sched = _make_schedule(test_mode=True)

        orch = InvoiceGenerationOrchestrator(sched)
        result = orch.generate()

        self.assertTrue(result.success)
        self.assertTrue(result.metadata.get("test_mode"))
        self.assertIsNone(result.data)
        sched.update_schedule_dates.assert_called_once()

    def test_test_mode_does_not_acquire_lock(self):
        """Test mode returns before lock acquisition — _acquire_lock should never be called."""
        sched = _make_schedule(test_mode=True)

        orch = InvoiceGenerationOrchestrator(sched)
        with patch.object(orch, "_acquire_lock") as mock_lock:
            orch.generate()
            mock_lock.assert_not_called()


class TestConcurrencyLock(unittest.TestCase):
    """Test Redis lock branching."""

    def test_concurrent_lock_returns_skipped(self):
        """If Redis lock is NOT acquired (another process holds it), must skip."""
        sched = _make_schedule()

        orch = InvoiceGenerationOrchestrator(sched)
        # Simulate: Redis available (redis_conn not None) but lock NOT acquired
        with patch.object(orch, "_acquire_lock", return_value=(False, MagicMock(), "lock_key")):
            result = orch.generate()

        self.assertTrue(result.metadata.get("skipped"))
        self.assertEqual(result.metadata.get("reason"), "concurrent_lock")

    def test_redis_unavailable_proceeds_without_lock(self):
        """If Redis is unavailable (redis_conn=None), generation should still proceed."""
        sched = _make_schedule()

        orch = InvoiceGenerationOrchestrator(sched)
        mock_invoice = MagicMock()
        mock_invoice.docstatus = 0
        mock_invoice.custom_coverage_start_date = "2025-01-01"
        mock_invoice.custom_coverage_end_date = "2025-12-31"
        mock_invoice.name = "SINV-001"
        mock_invoice.posting_date = "2025-01-01"

        gen_result = OperationResult.ok(mock_invoice)

        # Redis unavailable: returns (False, None, key)
        with patch.object(orch, "_acquire_lock", return_value=(False, None, "lock_key")):
            with patch.object(orch, "_execute_generation", return_value=gen_result):
                result = orch.generate()

        # Should succeed — redis_conn=None means the concurrent lock check is bypassed
        self.assertTrue(result.success)
        self.assertFalse(result.metadata.get("skipped", False))


class TestErrorHandling(unittest.TestCase):
    """Test that _handle_error raises ValidationError."""

    def test_handle_error_raises_validation_error(self):
        sched = _make_schedule()
        orch = InvoiceGenerationOrchestrator(sched)

        with self.assertRaises(frappe.ValidationError) as ctx:
            orch._handle_error(RuntimeError("something broke"))

        self.assertIn("TEST-SCHED-001", str(ctx.exception))
        self.assertIn("something broke", str(ctx.exception))
