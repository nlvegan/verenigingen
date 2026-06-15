"""
Unit tests for Ponto Sync client.

Tier-1 unit tests: the inner PontoClient HTTP boundary is stubbed (injected via
the PontoSyncClient(client=...) constructor argument). Asserts endpoint/payload
construction, response parsing, and the error-class-to-status mapping.

Usage:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_sync_client_unit
"""

import unittest
from unittest.mock import MagicMock

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ponto.clients.sync_client import PontoSyncClient
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError


class TestPontoSyncClientUnit(FrappeTestCase):
    """Unit tests for PontoSyncClient (HTTP boundary injected as mock)."""

    ACCOUNT_ID = "acc-uuid-sync"

    def _make_client(self):
        inner = MagicMock()
        return PontoSyncClient(client=inner), inner

    # -------------------------------------------------------------------------
    # trigger_sync
    # -------------------------------------------------------------------------

    def test_trigger_sync_success(self):
        client, inner = self._make_client()
        inner.post.return_value = {"data": {"id": "sync-1", "type": "synchronization"}}

        result = client.trigger_sync(self.ACCOUNT_ID)

        inner.post.assert_called_once_with(
            f"/accounts/{self.ACCOUNT_ID}/synchronizations",
            data={"data": {"type": "synchronization"}},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["synchronization_id"], "sync-1")

    def test_trigger_sync_missing_account_id(self):
        client, inner = self._make_client()
        result = client.trigger_sync("")
        self.assertEqual(result["status"], "error")
        inner.post.assert_not_called()

    def test_trigger_sync_in_progress_returns_pending(self):
        client, inner = self._make_client()
        inner.post.side_effect = PontoAPIError(
            "already syncing", error_code="synchronizationInProgress"
        )
        result = client.trigger_sync(self.ACCOUNT_ID)
        self.assertEqual(result["status"], "pending")

    def test_trigger_sync_rate_limited_returns_pending(self):
        client, inner = self._make_client()
        inner.post.side_effect = PontoAPIError(
            "rate limited", error_code="rateLimitExceeded"
        )
        result = client.trigger_sync(self.ACCOUNT_ID)
        self.assertEqual(result["status"], "pending")

    def test_trigger_sync_404_returns_skipped(self):
        client, inner = self._make_client()
        inner.post.side_effect = PontoAPIError("not found", status_code=404)
        result = client.trigger_sync(self.ACCOUNT_ID)
        self.assertEqual(result["status"], "skipped")

    def test_trigger_sync_resource_not_found_returns_skipped(self):
        client, inner = self._make_client()
        inner.post.side_effect = PontoAPIError(
            "not found", error_code="resourceNotFound"
        )
        result = client.trigger_sync(self.ACCOUNT_ID)
        self.assertEqual(result["status"], "skipped")

    def test_trigger_sync_other_api_error_returns_error(self):
        client, inner = self._make_client()
        inner.post.side_effect = PontoAPIError("server error", status_code=500)
        result = client.trigger_sync(self.ACCOUNT_ID)
        self.assertEqual(result["status"], "error")

    def test_trigger_sync_unexpected_exception_returns_error(self):
        client, inner = self._make_client()
        inner.post.side_effect = RuntimeError("boom")
        result = client.trigger_sync(self.ACCOUNT_ID)
        self.assertEqual(result["status"], "error")

    def test_trigger_sync_response_without_data(self):
        client, inner = self._make_client()
        inner.post.return_value = {}
        result = client.trigger_sync(self.ACCOUNT_ID)
        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["synchronization_id"])

    # -------------------------------------------------------------------------
    # get_synchronization
    # -------------------------------------------------------------------------

    def test_get_synchronization_parses_attributes(self):
        client, inner = self._make_client()
        inner.get.return_value = {
            "data": {
                "id": "sync-1",
                "attributes": {
                    "status": "success",
                    "subtype": "accountDetails",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-01T00:01:00Z",
                },
            }
        }
        result = client.get_synchronization(self.ACCOUNT_ID, "sync-1")
        inner.get.assert_called_once_with(
            f"/accounts/{self.ACCOUNT_ID}/synchronizations/sync-1"
        )
        self.assertEqual(result["id"], "sync-1")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subtype"], "accountDetails")

    def test_get_synchronization_no_data(self):
        client, inner = self._make_client()
        inner.get.return_value = {}
        result = client.get_synchronization(self.ACCOUNT_ID, "sync-1")
        self.assertEqual(result["status"], "unknown")

    def test_get_synchronization_error(self):
        client, inner = self._make_client()
        inner.get.side_effect = RuntimeError("boom")
        result = client.get_synchronization(self.ACCOUNT_ID, "sync-1")
        self.assertEqual(result["status"], "error")

    # -------------------------------------------------------------------------
    # get_latest_synchronization
    # -------------------------------------------------------------------------

    def test_get_latest_synchronization_returns_first(self):
        client, inner = self._make_client()
        inner.get.return_value = {
            "data": [
                {
                    "id": "latest",
                    "attributes": {
                        "status": "success",
                        "subtype": "accountTransactions",
                        "createdAt": "2026-01-02T00:00:00Z",
                        "updatedAt": "2026-01-02T00:05:00Z",
                    },
                }
            ]
        }
        result = client.get_latest_synchronization(self.ACCOUNT_ID)
        inner.get.assert_called_once_with(
            f"/accounts/{self.ACCOUNT_ID}/synchronizations", params={"limit": 1}
        )
        self.assertEqual(result["id"], "latest")
        self.assertEqual(result["status"], "success")

    def test_get_latest_synchronization_empty_list(self):
        client, inner = self._make_client()
        inner.get.return_value = {"data": []}
        result = client.get_latest_synchronization(self.ACCOUNT_ID)
        self.assertIsNone(result)

    def test_get_latest_synchronization_no_data(self):
        client, inner = self._make_client()
        inner.get.return_value = {}
        result = client.get_latest_synchronization(self.ACCOUNT_ID)
        self.assertIsNone(result)

    def test_get_latest_synchronization_error(self):
        client, inner = self._make_client()
        inner.get.side_effect = RuntimeError("boom")
        result = client.get_latest_synchronization(self.ACCOUNT_ID)
        self.assertIsNone(result)

    def test_factory_returns_instance(self):
        from verenigingen.verenigingen_payments.ponto.clients.sync_client import (
            get_sync_client,
        )

        self.assertIsInstance(get_sync_client(), PontoSyncClient)


if __name__ == "__main__":
    unittest.main()
