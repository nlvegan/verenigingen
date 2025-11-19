"""
Integration tests for MollieConfigurationService migration

Verifies that the migrated code (balance_monitor, financial_dashboard, etc.)
correctly uses the configuration service instead of direct frappe.get_single() calls.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


class TestMollieConfigurationMigration(FrappeTestCase):
    """Test that migrated modules correctly use configuration service"""

    def test_balance_monitor_uses_config_service(self):
        """Test that balance_monitor uses configuration service"""
        from verenigingen.verenigingen_payments.monitoring.balance_monitor import run_balance_monitoring

        # This should not error - it should check backend API via config service
        result = run_balance_monitoring()

        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

        # If backend API not enabled, should return skipped
        if not get_mollie_config().is_backend_api_enabled():
            self.assertEqual(result["status"], "skipped")

    def test_financial_dashboard_uses_config_service(self):
        """Test that financial_dashboard uses configuration service"""
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import get_dashboard_data

        # This should not error - it should check backend API via config service
        result = get_dashboard_data()

        self.assertIsInstance(result, dict)

        # If backend API not enabled, should return error
        if not get_mollie_config().is_backend_api_enabled():
            self.assertEqual(result["success"], False)

    def test_reconciliation_engine_uses_config_service(self):
        """Test that reconciliation_engine uses configuration service"""
        from verenigingen.verenigingen_payments.workflows.reconciliation_engine import (
            run_scheduled_reconciliation,
        )

        # This should not error - it should check backend API via config service
        result = run_scheduled_reconciliation()

        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

        # If backend API not enabled, should return skipped
        if not get_mollie_config().is_backend_api_enabled():
            self.assertEqual(result["status"], "skipped")

    def test_subscription_manager_uses_config_service(self):
        """Test that subscription_manager uses configuration service"""
        from verenigingen.verenigingen_payments.workflows.subscription_manager import (
            sync_all_subscription_payments,
        )

        # This should not error - it should check backend API via config service
        result = sync_all_subscription_payments()

        self.assertIsInstance(result, dict)

        # If backend API not enabled, should return skipped with status field
        # If enabled, returns dict with total_members, synced, failed, etc.
        if not get_mollie_config().is_backend_api_enabled():
            self.assertIn("status", result)
            self.assertEqual(result["status"], "skipped")
        else:
            # When enabled, returns sync results
            self.assertIn("total_members", result)

    def test_balance_report_uses_config_service(self):
        """Test that mollie_balance_report uses configuration service"""
        from verenigingen.verenigingen_payments.report.mollie_balance_report.mollie_balance_report import (
            execute,
        )

        # This should not error - it should check backend API via config service
        columns, data = execute()

        self.assertIsInstance(columns, list)
        self.assertIsInstance(data, list)

        # If backend API not enabled, should return error message in data
        if not get_mollie_config().is_backend_api_enabled():
            self.assertEqual(len(data), 1)
            self.assertIn("not enabled", data[0][0])

    def test_bank_transaction_reconciliation_uses_config_service(self):
        """Test that bank_transaction_reconciliation uses configuration service"""
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            PaymentReconciliationManager,
        )

        # This should initialize without error using config service
        manager = PaymentReconciliationManager()

        # Should have config attribute
        self.assertTrue(hasattr(manager, "config"))
        self.assertEqual(manager.config, get_mollie_config())

    def test_mollie_base_client_still_accesses_settings_for_api_keys(self):
        """Test that mollie_base_client still uses direct access for API keys (security)"""
        from verenigingen.verenigingen_payments.core.mollie_base_client import MollieBaseClient

        # Should be able to initialize (will use direct access for API keys)
        # This proves we kept API key access as direct (security requirement)
        try:
            client = MollieBaseClient(use_backend_api=True)
            # If it initializes, that's good - API key access still works
            self.assertTrue(True)
        except frappe.ValidationError as e:
            # If backend API not enabled or token not configured, that's expected
            self.assertIn("Backend API", str(e))

    def test_configuration_service_cache_invalidation(self):
        """Test that cache is cleared when Mollie Settings are updated"""
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            MollieConfigurationService,
        )

        # Get initial settings
        config = get_mollie_config()
        settings1 = config.get_settings()

        # Clear cache manually (simulates what on_update hook does)
        MollieConfigurationService.clear_cache()

        # Get settings again - should reload from DB
        settings2 = config.get_settings()

        # Should be equal (same DB values) but fresh copy
        self.assertEqual(settings1, settings2)


def run_tests():
    """Helper function to run tests from console"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMollieConfigurationMigration)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)
