"""
Tests for SEPA health check endpoint.

These tests verify that the health check endpoint correctly reports
the status of SEPA infrastructure components.
"""
import frappe
from frappe.tests import IntegrationTestCase


class TestSEPAHealthEndpoint(IntegrationTestCase):
    """Test cases for SEPA health check endpoint."""

    def test_health_check_returns_status(self):
        """Health endpoint should return overall status and checks."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("status", result)
        self.assertIn("timestamp", result)
        self.assertIn("checks", result)
        self.assertIn(result["status"], ["healthy", "degraded"])

    def test_health_check_includes_redis(self):
        """Health check should include Redis status."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("redis", result["checks"])
        self.assertIn("healthy", result["checks"]["redis"])

    def test_health_check_includes_pending_batches(self):
        """Health check should include pending batches count."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("pending_batches", result["checks"])
        self.assertIn("count", result["checks"]["pending_batches"])

    def test_health_check_includes_unreconciled(self):
        """Health check should include unreconciled transactions."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("unreconciled", result["checks"])
        self.assertIn("threshold", result["checks"]["unreconciled"])
        self.assertEqual(result["checks"]["unreconciled"]["threshold"], 50)

    def test_health_check_includes_recent_uploads(self):
        """Health check should include recent upload activity."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("recent_uploads", result["checks"])
        self.assertIn("count_24h", result["checks"]["recent_uploads"])

    def test_health_check_redis_has_locks_enabled(self):
        """Redis check should report locks_enabled status."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("locks_enabled", result["checks"]["redis"])
        self.assertIsInstance(result["checks"]["redis"]["locks_enabled"], bool)

    def test_health_check_timestamp_is_string(self):
        """Timestamp should be a string representation."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIsInstance(result["timestamp"], str)
        self.assertTrue(len(result["timestamp"]) > 0)

    def test_pending_batches_healthy_boolean(self):
        """Pending batches check should have healthy boolean."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("healthy", result["checks"]["pending_batches"])
        self.assertIsInstance(result["checks"]["pending_batches"]["healthy"], bool)

    def test_unreconciled_healthy_boolean(self):
        """Unreconciled check should have healthy boolean."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("healthy", result["checks"]["unreconciled"])
        self.assertIsInstance(result["checks"]["unreconciled"]["healthy"], bool)

    def test_recent_uploads_healthy_boolean(self):
        """Recent uploads check should have healthy boolean."""
        from verenigingen.api.sepa_health import get_sepa_health

        result = get_sepa_health()

        self.assertIn("healthy", result["checks"]["recent_uploads"])
        self.assertIsInstance(result["checks"]["recent_uploads"]["healthy"], bool)
