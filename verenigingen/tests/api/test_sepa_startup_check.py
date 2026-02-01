"""
Tests for SEPA startup checks.

These tests verify that the Redis startup verification correctly detects
configuration issues and logs appropriate warnings.
"""
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.startup_checks import (
    run_all_startup_checks,
    verify_sepa_redis_on_startup,
)


class TestSEPAStartupCheck(FrappeTestCase):
    """Test cases for SEPA Redis startup verification."""

    def test_startup_check_returns_result(self):
        """Check returns expected structure."""
        result = verify_sepa_redis_on_startup()

        # Verify result structure
        self.assertIn("checked", result)
        self.assertIn("redis_enabled", result)
        self.assertIn("multi_worker", result)
        self.assertIn("warning", result)

        # Checked should always be True
        self.assertTrue(result["checked"])

        # redis_enabled and multi_worker should be booleans
        self.assertIsInstance(result["redis_enabled"], bool)
        self.assertIsInstance(result["multi_worker"], bool)

    @patch.object(frappe, "conf", {"gunicorn_workers": 4, "use_redis_locks_for_sepa": False})
    def test_startup_check_logs_warning_when_multi_worker_no_redis(self):
        """Warning logged when multi-worker but no Redis."""
        with patch.object(frappe, "logger") as mock_logger:
            mock_sepa_logger = MagicMock()
            mock_logger.return_value = mock_sepa_logger

            result = verify_sepa_redis_on_startup()

            # Should have a warning
            self.assertIsNotNone(result["warning"])
            self.assertIn("SEPA SAFETY WARNING", result["warning"])
            self.assertIn("4 workers", result["warning"])

            # Should have logged with "sepa" logger
            mock_logger.assert_called_with("sepa")
            mock_sepa_logger.warning.assert_called_once()

    @patch.object(frappe, "conf", {"gunicorn_workers": 1, "use_redis_locks_for_sepa": False})
    def test_startup_check_no_warning_single_worker(self):
        """No warning for single worker."""
        result = verify_sepa_redis_on_startup()

        # Should not have a warning for single worker
        self.assertIsNone(result["warning"])
        self.assertFalse(result["multi_worker"])
        self.assertFalse(result["redis_enabled"])

    @patch.object(frappe, "conf", {"gunicorn_workers": 4, "use_redis_locks_for_sepa": True})
    def test_startup_check_no_warning_with_redis_enabled(self):
        """No warning when Redis enabled (assuming health check passes)."""
        with patch(
            "verenigingen.api.sepa_duplicate_prevention.check_redis_health",
            return_value={"healthy": True},
        ):
            result = verify_sepa_redis_on_startup()

            # Should not have a warning when Redis is enabled and healthy
            self.assertIsNone(result["warning"])
            self.assertTrue(result["multi_worker"])
            self.assertTrue(result["redis_enabled"])

    @patch.object(frappe, "conf", {"gunicorn_workers": 4, "use_redis_locks_for_sepa": True})
    def test_startup_check_warning_when_redis_unhealthy(self):
        """Warning when Redis enabled but unhealthy."""
        with patch(
            "verenigingen.api.sepa_duplicate_prevention.check_redis_health",
            return_value={"healthy": False},
        ):
            with patch.object(frappe, "logger") as mock_logger:
                mock_sepa_logger = MagicMock()
                mock_logger.return_value = mock_sepa_logger

                result = verify_sepa_redis_on_startup()

                # Should have a warning about Redis health
                self.assertIsNotNone(result["warning"])
                self.assertIn("health check failed", result["warning"])

    @patch.object(frappe, "conf", {"gunicorn_workers": 4, "use_redis_locks_for_sepa": True})
    def test_startup_check_warning_when_redis_check_errors(self):
        """Warning when Redis health check raises exception."""
        with patch(
            "verenigingen.api.sepa_duplicate_prevention.check_redis_health",
            side_effect=Exception("Connection refused"),
        ):
            with patch.object(frappe, "logger") as mock_logger:
                mock_sepa_logger = MagicMock()
                mock_logger.return_value = mock_sepa_logger

                result = verify_sepa_redis_on_startup()

                # Should have a warning about the error
                self.assertIsNotNone(result["warning"])
                self.assertIn("health check error", result["warning"])
                self.assertIn("Connection refused", result["warning"])

    def test_run_all_startup_checks_includes_sepa_redis(self):
        """run_all_startup_checks includes sepa_redis check."""
        results = run_all_startup_checks()

        self.assertIn("sepa_redis", results)
        self.assertIn("checked", results["sepa_redis"])

    @patch.object(frappe, "conf", {"gunicorn_workers": 0, "use_redis_locks_for_sepa": False})
    def test_startup_check_zero_workers_treated_as_single(self):
        """Zero workers should be treated as single worker (no warning)."""
        result = verify_sepa_redis_on_startup()

        # 0 workers should not be multi-worker
        self.assertFalse(result["multi_worker"])
        self.assertIsNone(result["warning"])

    @patch.object(frappe, "conf", {})
    def test_startup_check_missing_config_uses_defaults(self):
        """Missing config values use sensible defaults."""
        result = verify_sepa_redis_on_startup()

        # Default should be single worker, no Redis
        self.assertFalse(result["multi_worker"])
        self.assertFalse(result["redis_enabled"])
        self.assertIsNone(result["warning"])


if __name__ == "__main__":
    unittest.main()
