"""
Unit Tests for AlertManager - Reconciliation Threshold Alerts

Tests the reconciliation backlog monitoring functionality of the AlertManager.
This is part of the SEPA audit remediation (P2.2) to monitor unreconciled payments.

Test Strategy:
    - Test alert triggering at warning threshold
    - Test no alert below threshold
    - Test critical alert at critical threshold
    - Test exact threshold boundary behavior
    - Test message contains relevant information
    - Test default threshold values

Author: Verenigingen Development Team
"""

import frappe
from frappe.tests import IntegrationTestCase

from verenigingen.services.payment.alert_manager import AlertManager, ReconciliationAlertResult


class TestReconciliationAlertResult(IntegrationTestCase):
    """Test the ReconciliationAlertResult dataclass"""

    def test_info_result_creation(self):
        """Test creating an info-level result"""
        result = ReconciliationAlertResult(
            alert_triggered=False,
            severity="info",
            message="No alert needed",
            unreconciled_count=10,
        )

        self.assertFalse(result.alert_triggered)
        self.assertEqual(result.severity, "info")
        self.assertEqual(result.unreconciled_count, 10)

    def test_warning_result_creation(self):
        """Test creating a warning-level result"""
        result = ReconciliationAlertResult(
            alert_triggered=True,
            severity="warning",
            message="Warning threshold exceeded",
            unreconciled_count=50,
        )

        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "warning")
        self.assertEqual(result.unreconciled_count, 50)

    def test_critical_result_creation(self):
        """Test creating a critical-level result"""
        result = ReconciliationAlertResult(
            alert_triggered=True,
            severity="critical",
            message="Critical threshold exceeded",
            unreconciled_count=100,
        )

        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "critical")
        self.assertEqual(result.unreconciled_count, 100)


class TestReconciliationAlerts(IntegrationTestCase):
    """Test the AlertManager reconciliation status checking"""

    def setUp(self):
        super().setUp()
        self.alert_manager = AlertManager()

    def test_alert_triggered_at_warning_threshold(self):
        """Alert should trigger when unreconciled count >= warning threshold."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=50,
            threshold=25,
        )

        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "warning")
        self.assertEqual(result.unreconciled_count, 50)

    def test_no_alert_below_threshold(self):
        """No alert when unreconciled count is below threshold."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=10,
            threshold=25,
        )

        self.assertFalse(result.alert_triggered)
        self.assertEqual(result.severity, "info")
        self.assertEqual(result.unreconciled_count, 10)

    def test_critical_alert_at_critical_threshold(self):
        """Critical alert when unreconciled exceeds critical threshold."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=100,
            threshold=25,
            critical_threshold=75,
        )

        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "critical")
        self.assertEqual(result.unreconciled_count, 100)

    def test_at_exact_threshold(self):
        """Exactly at threshold should trigger alert."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=25,
            threshold=25,
        )

        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "warning")
        self.assertEqual(result.unreconciled_count, 25)

    def test_at_exact_critical_threshold(self):
        """Exactly at critical threshold should trigger critical alert."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=75,
            threshold=25,
            critical_threshold=75,
        )

        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "critical")
        self.assertEqual(result.unreconciled_count, 75)

    def test_message_contains_count(self):
        """Alert message should include the count."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=30,
            threshold=25,
        )

        self.assertIn("30", result.message)

    def test_message_contains_threshold(self):
        """Alert message should include threshold information for context."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=30,
            threshold=25,
        )

        # Message should provide useful context about the threshold
        self.assertIn("25", result.message)

    def test_default_thresholds(self):
        """Default thresholds should work correctly."""
        # Below default warning threshold (25)
        result = self.alert_manager.check_reconciliation_status(unreconciled_count=20)
        self.assertFalse(result.alert_triggered)
        self.assertEqual(result.severity, "info")

        # Above default warning threshold, below critical
        result = self.alert_manager.check_reconciliation_status(unreconciled_count=50)
        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "warning")

        # Above default critical threshold (75)
        result = self.alert_manager.check_reconciliation_status(unreconciled_count=80)
        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "critical")

    def test_zero_unreconciled(self):
        """Zero unreconciled items should not trigger alert."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=0,
            threshold=25,
        )

        self.assertFalse(result.alert_triggered)
        self.assertEqual(result.severity, "info")
        self.assertEqual(result.unreconciled_count, 0)

    def test_between_warning_and_critical(self):
        """Count between warning and critical should be warning severity."""
        result = self.alert_manager.check_reconciliation_status(
            unreconciled_count=50,
            threshold=25,
            critical_threshold=75,
        )

        self.assertTrue(result.alert_triggered)
        self.assertEqual(result.severity, "warning")
        # Should not be critical
        self.assertNotEqual(result.severity, "critical")
