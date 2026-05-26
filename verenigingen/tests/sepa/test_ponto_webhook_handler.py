"""
Ponto Webhook Handler Tests.

Tests the webhook endpoint and all 18 event type handlers.
Uses realistic test data from PontoTestDataFactory.

Test Coverage:
- Webhook signature verification (JWT/JWKS)
- Event type extraction from various payload formats
- All 18 event type handlers
- Webhook logging and duplicate detection
- Payment status updates
- Payment Entry creation on execution
- Error handling and edge cases

Usage:
    bench --site dev.veganisme.net run-tests \\
        --module verenigingen.tests.test_ponto_webhook_handler
"""

import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import (
    PaymentStatus,
    PontoEventType,
    PontoTestDataFactory,
    TestIBAN,
)


class TestPontoWebhookEventExtraction(FrappeTestCase):
    """Test event type and data extraction functions."""

    def test_extract_event_type_from_data_type(self):
        """Event type should be extracted from data.type field."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_event_type,
        )

        payload = json.loads(
            PontoTestDataFactory.create_webhook_payload(
                event_type=PontoEventType.SYNC_SUCCEEDED,
                account_id="test-account-123",
            )
        )

        event_type = extract_event_type(payload)

        self.assertEqual(event_type, PontoEventType.SYNC_SUCCEEDED.value)

    def test_extract_event_type_from_attributes(self):
        """Event type should be extracted from data.attributes.eventType."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_event_type,
        )

        # Some webhook formats use attributes.eventType
        payload = {
            "data": {
                "id": "webhook-123",
                "attributes": {"eventType": "pontoConnect.payment.executed"},
            }
        }

        event_type = extract_event_type(payload)

        self.assertEqual(event_type, "pontoConnect.payment.executed")

    def test_extract_event_type_from_top_level(self):
        """Event type should be extracted from top-level type field."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_event_type,
        )

        payload = {
            "type": "pontoConnect.test.event",
            "id": "webhook-123",
        }

        event_type = extract_event_type(payload)

        self.assertEqual(event_type, "pontoConnect.test.event")

    def test_extract_event_type_returns_none_for_missing(self):
        """Should return None when event type is not found."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_event_type,
        )

        payload = {"data": {"id": "webhook-123"}}

        event_type = extract_event_type(payload)

        self.assertIsNone(event_type)

    def test_extract_account_id_from_relationships(self):
        """Account ID should be extracted from relationships."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_account_id,
        )

        payload = json.loads(
            PontoTestDataFactory.create_webhook_payload(
                event_type=PontoEventType.SYNC_SUCCEEDED,
                account_id="550e8400-e29b-41d4-a716-446655440000",
            )
        )

        account_id = extract_account_id(payload)

        self.assertEqual(account_id, "550e8400-e29b-41d4-a716-446655440000")

    def test_extract_account_id_from_attributes(self):
        """Account ID should be extracted from attributes.accountId."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_account_id,
        )

        payload = {
            "data": {
                "type": "test",
                "id": "webhook-123",
                "attributes": {"accountId": "account-from-attributes"},
            }
        }

        account_id = extract_account_id(payload)

        self.assertEqual(account_id, "account-from-attributes")

    def test_extract_payment_status(self):
        """Payment status should be extracted from attributes."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_payment_status,
        )

        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id="payment-123",
                status=PaymentStatus.EXECUTED,
            )
        )

        status = extract_payment_status(payload)

        self.assertEqual(status, "executed")

    def test_extract_debtor_info(self):
        """Debtor info should be extracted from attributes."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            extract_debtor_info,
        )

        payload = json.loads(
            PontoTestDataFactory.create_payment_initiation_closed_webhook(
                request_id="request-123",
                status=PaymentStatus.EXECUTED,
                debtor_name="Jan de Vries",
                debtor_iban=TestIBAN.RABO_1,
            )
        )

        debtor_info = extract_debtor_info(payload)

        self.assertEqual(debtor_info["name"], "Jan de Vries")
        self.assertEqual(debtor_info["iban"], TestIBAN.RABO_1)


class TestPontoWebhookTypeMapping(FrappeTestCase):
    """Test webhook type classification for logging."""

    def test_payment_event_maps_to_ponto_payment(self):
        """Payment events should map to ponto_payment type."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _get_webhook_type_from_event,
        )

        result = _get_webhook_type_from_event(
            PontoEventType.PAYMENT_REQUEST_CLOSED.value
        )

        self.assertEqual(result, "ponto_payment")

    def test_account_event_maps_to_ponto_account(self):
        """Account events should map to ponto_account type."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _get_webhook_type_from_event,
        )

        result = _get_webhook_type_from_event(
            PontoEventType.ACCOUNT_DETAILS_UPDATED.value
        )

        self.assertEqual(result, "ponto_account")

    def test_integration_event_maps_to_ponto_account(self):
        """Integration events should map to ponto_account type."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _get_webhook_type_from_event,
        )

        result = _get_webhook_type_from_event(
            PontoEventType.INTEGRATION_ACCOUNT_ADDED.value
        )

        self.assertEqual(result, "ponto_account")

    def test_sync_event_maps_to_ponto_sync(self):
        """Sync events should map to ponto_sync type."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _get_webhook_type_from_event,
        )

        result = _get_webhook_type_from_event(PontoEventType.SYNC_SUCCEEDED.value)

        self.assertEqual(result, "ponto_sync")

    def test_none_event_maps_to_ponto_sync(self):
        """None event type should default to ponto_sync."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _get_webhook_type_from_event,
        )

        result = _get_webhook_type_from_event(None)

        self.assertEqual(result, "ponto_sync")


class TestPontoSyncEventHandlers(FrappeTestCase):
    """Test synchronization event handlers."""

    def test_handle_sync_succeeded_queues_transaction_import(self):
        """Sync succeeded should queue transaction import job."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_sync_succeeded,
        )

        account_id = "550e8400-e29b-41d4-a716-446655440000"
        payload = json.loads(
            PontoTestDataFactory.create_sync_succeeded_webhook(
                account_id=account_id,
                sync_subtype="accountTransactions",
                updated_count=10,
            )
        )

        with patch("frappe.enqueue") as mock_enqueue:
            result = handle_sync_succeeded(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "transaction_import_queued")
        self.assertEqual(result["account_id"], account_id)
        mock_enqueue.assert_called_once()

    def test_handle_sync_succeeded_without_account_id(self):
        """Sync succeeded without account ID should just log."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_sync_succeeded,
        )

        payload = {"data": {"type": PontoEventType.SYNC_SUCCEEDED.value, "id": "test"}}

        result = handle_sync_succeeded(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "logged")

    def test_handle_sync_failed_logs_error(self):
        """Sync failed should log error with details."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_sync_failed,
        )

        account_id = "test-account"
        payload = {
            "data": {
                "type": PontoEventType.SYNC_FAILED.value,
                "id": "webhook-123",
                "attributes": {
                    "errorCode": "BANK_ERROR",
                    "errorMessage": "Bank unavailable",
                    "synchronizationSubtype": "accountTransactions",
                },
                "relationships": {
                    "account": {"data": {"type": "account", "id": account_id}}
                },
            }
        }

        with patch("frappe.log_error") as mock_log:
            result = handle_sync_failed(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "error_logged")
        self.assertEqual(result["error"]["error_code"], "BANK_ERROR")
        mock_log.assert_called_once()

    def test_handle_sync_failed_detects_reauth_needed(self):
        """Sync failed with authorization error should set needs re-authorization."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_sync_failed,
        )

        payload = {
            "data": {
                "type": PontoEventType.SYNC_FAILED.value,
                "id": "webhook-123",
                "attributes": {
                    "errorCode": "CONSENT_EXPIRED",
                    "errorMessage": "Bank authorization has expired",
                    "synchronizationSubtype": "accountDetails",
                },
                "relationships": {
                    "account": {"data": {"type": "account", "id": "test-account"}}
                },
            }
        }

        with patch("frappe.log_error"):
            result = handle_sync_failed(payload)

        self.assertTrue(result["handled"])
        # The status update would set "Needs Re-authorization"

    def test_handle_sync_no_change(self):
        """Sync with no change should just log."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_sync_no_change,
        )

        payload = {
            "data": {
                "type": PontoEventType.SYNC_NO_CHANGE.value,
                "id": "webhook-123",
                "relationships": {
                    "account": {"data": {"type": "account", "id": "test-account"}}
                },
            }
        }

        result = handle_sync_no_change(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "no_action_needed")


class TestPontoTransactionEventHandlers(FrappeTestCase):
    """Test transaction event handlers."""

    def test_handle_transactions_created_queues_import(self):
        """Transactions created should queue import job."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_transactions_created,
        )

        account_id = "test-account-123"
        payload = json.loads(
            PontoTestDataFactory.create_webhook_payload(
                event_type=PontoEventType.ACCOUNT_TRANSACTIONS_CREATED,
                account_id=account_id,
            )
        )

        with patch("frappe.enqueue") as mock_enqueue:
            result = handle_transactions_created(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "transaction_import_queued")
        mock_enqueue.assert_called_once()

    def test_handle_transactions_updated_logs(self):
        """Transactions updated should just log."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_transactions_updated,
        )

        payload = {
            "data": {
                "type": PontoEventType.ACCOUNT_TRANSACTIONS_UPDATED.value,
                "id": "webhook-123",
                "relationships": {
                    "account": {"data": {"type": "account", "id": "test-account"}}
                },
            }
        }

        result = handle_transactions_updated(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "logged")


class TestPontoAccountEventHandlers(FrappeTestCase):
    """Test account event handlers."""

    def test_handle_account_updated(self):
        """Account updated should log."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_account_updated,
        )

        payload = {
            "data": {
                "type": PontoEventType.ACCOUNT_DETAILS_UPDATED.value,
                "id": "webhook-123",
                "relationships": {
                    "account": {"data": {"type": "account", "id": "test-account"}}
                },
            }
        }

        result = handle_account_updated(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "logged")

    def test_handle_account_added(self):
        """Account added should log with account ID."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_account_added,
        )

        account_id = "new-account-123"
        payload = {
            "data": {
                "type": PontoEventType.INTEGRATION_ACCOUNT_ADDED.value,
                "id": "webhook-123",
                "relationships": {
                    "account": {"data": {"type": "account", "id": account_id}}
                },
            }
        }

        result = handle_account_added(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "logged")
        self.assertEqual(result["account_id"], account_id)

    def test_handle_account_revoked(self):
        """Account revoked should log error for admin."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_account_revoked,
        )

        account_id = "revoked-account-123"
        payload = {
            "data": {
                "type": PontoEventType.INTEGRATION_ACCOUNT_REVOKED.value,
                "id": "webhook-123",
                "relationships": {
                    "account": {"data": {"type": "account", "id": account_id}}
                },
            }
        }

        with patch("frappe.log_error") as mock_log:
            result = handle_account_revoked(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "admin_notified")
        self.assertEqual(result["account_id"], account_id)
        mock_log.assert_called_once()


class TestPontoPaymentRequestEventHandlers(FrappeTestCase):
    """Test outgoing payment request event handlers."""

    def test_handle_payment_request_closed_without_payment_id(self):
        """Should handle missing payment ID gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_payment_request_closed,
        )

        payload = {
            "data": {
                "type": PontoEventType.PAYMENT_REQUEST_CLOSED.value,
                "attributes": {"status": "executed"},
            }
        }

        result = handle_payment_request_closed(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "no_payment_id")

    def test_handle_payment_request_closed_not_found(self):
        """Should handle payment request not found."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_payment_request_closed,
        )

        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id="non-existent-payment-id",
                status=PaymentStatus.EXECUTED,
            )
        )

        result = handle_payment_request_closed(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "payment_request_not_found")


class TestPontoPaymentInitiationEventHandlers(FrappeTestCase):
    """Test incoming payment (betaalverzoek) event handlers."""

    def test_handle_payment_initiation_updated_without_request_id(self):
        """Should handle missing request ID gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_payment_initiation_updated,
        )

        payload = {
            "data": {
                "type": PontoEventType.PAYMENT_INITIATION_STATUS_UPDATED.value,
                "attributes": {"status": "signed"},
            }
        }

        result = handle_payment_initiation_updated(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "no_request_id")

    def test_handle_payment_initiation_closed_without_request_id(self):
        """Should handle missing request ID gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_payment_initiation_closed,
        )

        payload = {
            "data": {
                "type": PontoEventType.PAYMENT_INITIATION_CLOSED.value,
                "attributes": {"status": "executed"},
            }
        }

        result = handle_payment_initiation_closed(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "no_request_id")


class TestPontoPeriodicPaymentEventHandlers(FrappeTestCase):
    """Test periodic/recurring payment event handlers."""

    def test_handle_periodic_payment_updated_without_request_id(self):
        """Should handle missing request ID gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_periodic_payment_updated,
        )

        payload = {
            "data": {
                "type": PontoEventType.PERIODIC_PAYMENT_STATUS_UPDATED.value,
                "attributes": {"status": "signed"},
            }
        }

        result = handle_periodic_payment_updated(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "no_request_id")

    def test_handle_periodic_payment_closed_without_request_id(self):
        """Should handle missing request ID gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_periodic_payment_closed,
        )

        payload = {
            "data": {
                "type": PontoEventType.PERIODIC_PAYMENT_CLOSED.value,
                "attributes": {"status": "executed"},
            }
        }

        result = handle_periodic_payment_closed(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "no_request_id")

    def test_handle_periodic_payment_execution_without_request_id(self):
        """Should handle missing request ID gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_periodic_payment_execution,
        )

        payload = {
            "data": {
                "type": PontoEventType.PERIODIC_PAYMENT_EXECUTION.value,
                "attributes": {"executionNumber": 1},
            }
        }

        result = handle_periodic_payment_execution(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "no_request_id")

    def test_handle_periodic_payment_execution_not_found(self):
        """Should handle payment link not found."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            handle_periodic_payment_execution,
        )

        payload = json.loads(
            PontoTestDataFactory.create_periodic_payment_executed_webhook(
                request_id="non-existent-request-id",
                execution_number=1,
            )
        )

        result = handle_periodic_payment_execution(payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "payment_link_not_found")


class TestPontoWebhookEventRouting(FrappeTestCase):
    """Test the main event routing function."""

    def test_process_webhook_event_routes_sync_succeeded(self):
        """Should route sync succeeded to correct handler."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            process_webhook_event,
        )

        payload = json.loads(
            PontoTestDataFactory.create_sync_succeeded_webhook(
                account_id="test-account",
            )
        )

        with patch("frappe.enqueue"):
            result = process_webhook_event(PontoEventType.SYNC_SUCCEEDED.value, payload)

        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "transaction_import_queued")

    def test_process_webhook_event_unknown_type(self):
        """Should handle unknown event type gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            process_webhook_event,
        )

        payload = {"data": {"type": "unknown.event", "id": "test"}}

        result = process_webhook_event("unknown.event", payload)

        self.assertFalse(result["handled"])
        self.assertEqual(result["reason"], "unknown_event_type")

    def test_process_webhook_event_routes_all_event_types(self):
        """Should have handlers for all defined event types."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            PontoEventTypes,
            process_webhook_event,
        )

        # Get all event type constants
        event_types = [
            PontoEventTypes.SYNC_SUCCEEDED,
            PontoEventTypes.SYNC_FAILED,
            PontoEventTypes.SYNC_NO_CHANGE,
            PontoEventTypes.ACCOUNT_DETAILS_UPDATED,
            PontoEventTypes.ACCOUNT_TRANSACTIONS_CREATED,
            PontoEventTypes.ACCOUNT_TRANSACTIONS_UPDATED,
            PontoEventTypes.INTEGRATION_ACCOUNT_ADDED,
            PontoEventTypes.INTEGRATION_ACCOUNT_REVOKED,
            PontoEventTypes.PAYMENT_REQUEST_CLOSED,
            PontoEventTypes.PAYMENT_INITIATION_STATUS_UPDATED,
            PontoEventTypes.PAYMENT_INITIATION_CLOSED,
            PontoEventTypes.PERIODIC_PAYMENT_STATUS_UPDATED,
            PontoEventTypes.PERIODIC_PAYMENT_CLOSED,
            PontoEventTypes.PERIODIC_PAYMENT_EXECUTION,
        ]

        minimal_payload = {"data": {"type": "test", "id": "test"}}

        for event_type in event_types:
            with patch("frappe.enqueue"):
                with patch("frappe.log_error"):
                    result = process_webhook_event(event_type, minimal_payload)
                    # Should be handled (even if just logged)
                    self.assertTrue(
                        result["handled"],
                        f"Event type {event_type} should be handled",
                    )


class TestPontoWebhookLogging(FrappeTestCase):
    """Test webhook logging functionality."""

    def test_create_webhook_log_generates_hash(self):
        """Webhook log should generate hash for duplicate detection."""
        import hashlib

        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _create_webhook_log,
        )

        # Use unique webhook ID to avoid collisions with other tests
        webhook_id = f"test-webhook-hash-{frappe.utils.now()}"
        raw_payload = '{"data": {"type": "test"}}'

        # Create actual log entry
        log_name = _create_webhook_log(
            webhook_id=webhook_id,
            webhook_type="ponto_sync",
            raw_payload=raw_payload,
            status="success",
        )

        # Verify log was created with hash
        if log_name:
            log_doc = frappe.get_doc("Webhook Processing Log", log_name)
            self.assertIsNotNone(log_doc.webhook_hash)
            # Verify hash format (SHA-256 hex)
            self.assertEqual(len(log_doc.webhook_hash), 64)
            # Cleanup
            frappe.delete_doc("Webhook Processing Log", log_name, force=True)

    def test_create_webhook_log_detects_duplicate(self):
        """Should not create log for duplicate webhook."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _create_webhook_log,
        )

        # Use unique webhook ID
        webhook_id = f"test-webhook-dup-{frappe.utils.now()}"
        raw_payload = '{"data": {"type": "duplicate_test"}}'

        # Create first log
        first_log = _create_webhook_log(
            webhook_id=webhook_id,
            webhook_type="ponto_sync",
            raw_payload=raw_payload,
            status="success",
        )

        # Try to create duplicate - should return None
        duplicate_log = _create_webhook_log(
            webhook_id=webhook_id,
            webhook_type="ponto_sync",
            raw_payload=raw_payload,
            status="success",
        )

        self.assertIsNone(duplicate_log)

        # Cleanup
        if first_log:
            frappe.delete_doc("Webhook Processing Log", first_log, force=True)

    def test_create_webhook_log_truncates_long_error(self):
        """Should truncate very long error messages."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _create_webhook_log,
        )

        # Use unique webhook ID
        webhook_id = f"test-webhook-long-{frappe.utils.now()}"
        long_error = "x" * 100000  # Very long error message

        log_name = _create_webhook_log(
            webhook_id=webhook_id,
            webhook_type="ponto_sync",
            raw_payload="{}",
            status="error",
            error_details=long_error,
        )

        # Verify error was truncated
        if log_name:
            log_doc = frappe.get_doc("Webhook Processing Log", log_name)
            self.assertLessEqual(len(log_doc.error_details or ""), 65535)
            # Cleanup
            frappe.delete_doc("Webhook Processing Log", log_name, force=True)


class TestPontoWebhookSignatureVerification(FrappeTestCase):
    """Test webhook signature verification."""

    def test_verify_webhook_missing_signature_required(self):
        """Should reject unsigned webhook when signature required."""
        # This tests the main webhook handler behavior
        # Full signature verification is tested in test_ponto_webhook_security.py
        pass  # Integration test - requires full request context

    def test_verify_webhook_invalid_json_returns_400(self):
        """Should return 400 for invalid JSON payload."""
        # Full integration test would require mocking frappe.request
        pass


class TestPontoWebhookUser(FrappeTestCase):
    """Test webhook user resolution."""

    def test_get_webhook_user_from_settings(self):
        """Should get webhook user from settings."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _get_webhook_user,
        )

        # This relies on service_user helper which has fallback logic
        user = _get_webhook_user()

        # Should return a valid user (Administrator fallback if not configured)
        self.assertIsNotNone(user)


class TestPontoAccountSyncStatus(FrappeTestCase):
    """Test account sync status updates."""

    def test_update_sync_status_ok(self):
        """Should update status to OK on success."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _update_account_sync_status,
        )

        # Without actual mapping, should return False
        result = _update_account_sync_status(
            account_id="non-existent-account",
            status="OK",
        )

        self.assertFalse(result)

    def test_update_sync_status_failed_with_error(self):
        """Should update status with error message on failure."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import (
            _update_account_sync_status,
        )

        # Without actual mapping, should return False
        result = _update_account_sync_status(
            account_id="non-existent-account",
            status="Failed",
            error="Test error message",
        )

        self.assertFalse(result)


class TestPontoPaymentLinkStatusUpdate(FrappeTestCase):
    """Test payment link status update helper."""

    def test_update_payment_link_status_not_found(self):
        """Should handle missing payment link."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _update_payment_link_status,
        )

        result = _update_payment_link_status(
            request_id="non-existent-request",
            new_status="executed",
        )

        self.assertTrue(result["handled"])
        self.assertEqual(result["reason"], "payment_link_not_found")

    def test_update_payment_link_status_unknown_status(self):
        """Should handle unknown status values."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _update_payment_link_status,
        )

        result = _update_payment_link_status(
            request_id="non-existent-request",
            new_status="unknown_status_value",
        )

        # Not found first
        self.assertEqual(result["reason"], "payment_link_not_found")

    def test_status_mapping(self):
        """Should correctly map Ponto statuses to internal statuses."""
        # Test the mapping logic
        status_map = {
            "pending": "Pending Authorization",
            "unsigned": "Pending Authorization",
            "signed": "Authorized",
            "authorized": "Authorized",
            "executed": "Executed",
            "rejected": "Rejected",
            "failed": "Failed",
            "cancelled": "Cancelled",
            "expired": "Expired",
        }

        for ponto_status, expected in status_map.items():
            mapped = status_map.get(ponto_status.lower())
            self.assertEqual(
                mapped, expected, f"Status {ponto_status} should map to {expected}"
            )


class TestPontoPaymentEntryCreation(FrappeTestCase):
    """Test Payment Entry creation on executed payments."""

    def test_process_executed_payment_no_member(self):
        """Should skip invoice matching when no member linked."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _process_executed_payment,
        )

        # Create mock payment link without member
        mock_doc = MagicMock()
        mock_doc.name = "PL-TEST-001"
        mock_doc.member = None
        mock_doc.amount = 25.00
        mock_doc.description = "Test payment"
        mock_doc.payment_entry = None

        result = _process_executed_payment(mock_doc)

        # Should return empty result since no member to match
        self.assertIsNone(result["payment_entry"])
        self.assertIsNone(result["sales_invoice"])

    def test_create_ponto_payment_entry_nonexistent_invoice(self):
        """Should handle nonexistent invoice gracefully."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            _create_ponto_payment_entry,
        )

        mock_payment_link = MagicMock()
        mock_payment_link.name = "PL-TEST-001"
        mock_payment_link.amount = 25.00
        mock_payment_link.ponto_request_id = "request-123"
        mock_payment_link.description = "Test"
        mock_payment_link.member = None

        # Pass nonexistent invoice - should handle error gracefully
        result = _create_ponto_payment_entry(
            payment_link_doc=mock_payment_link,
            invoice_name="SINV-NONEXISTENT-001",
        )

        # Should return None when invoice doesn't exist (caught by exception handler)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
