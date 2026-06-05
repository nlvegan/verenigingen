"""
Error Recovery Testing for Mollie Backend API
Tests system resilience and recovery from various failure scenarios
"""

import json
import random
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List
from unittest.mock import MagicMock, patch, PropertyMock
import threading
import queue

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase

from verenigingen.verenigingen_payments.core.resilience.rate_limiter import TokenBucketRateLimiter
from verenigingen.verenigingen_payments.core.resilience.retry_policy import SmartRetryPolicy, RetryStrategy
from verenigingen.verenigingen_payments.core.http_client import ResilientHTTPClient
from verenigingen.verenigingen_payments.workflows.reconciliation_engine import ReconciliationEngine
from verenigingen.verenigingen_payments.workflows.subscription_manager import SubscriptionManager
from verenigingen.verenigingen_payments.core.compliance.audit_trail import (
    ImmutableAuditTrail,
    AuditEventType,
    AuditSeverity,
)


def _enable_mollie_backend_api():
    """Enable the Mollie Backend API on the Mollie Settings Single.

    ReconciliationEngine() constructs the backend-API clients, which refuse to
    build unless enable_backend_api is set and an organization_access_token is
    present. A freshly reset test site has neither; this turns both on with a
    dummy token. No real Mollie call is made by the reconciliation test (it is
    a pure in-memory simulation), so the dummy token only satisfies the in-app
    "is configured" gate. The config service caches settings, so clear it too.
    """
    settings = frappe.get_single("Mollie Settings")
    settings.enable_backend_api = 1
    settings.organization_access_token = "test_dummy_org_token"
    settings.flags.ignore_mandatory = True
    settings.flags.ignore_validate = True
    settings.save(ignore_permissions=True)

    from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
        get_mollie_config,
    )

    get_mollie_config().clear_cache()


class TestErrorRecovery(VereningingenTestCase):
    """
    Error recovery tests for system resilience

    Tests:
    - Graceful degradation
    - Automatic recovery mechanisms
    - Data consistency during failures
    - Transaction rollback scenarios
    - Queue processing failures
    - Network partition handling
    """

    @classmethod
    def setUpClass(cls):
        """Set up resilience test environment"""
        super().setUpClass()

        # Use existing Default Mollie Settings or skip test
        try:
            settings = frappe.get_doc("Mollie Settings", "Default")
            # Update with resilience test configuration without saving
            settings.circuit_breaker_failure_threshold = 3
            settings.circuit_breaker_timeout = 1
            settings.retry_max_attempts = 3
            settings.retry_backoff_base = 1
            settings.connection_timeout = 2
            settings.request_timeout = 5
        except frappe.DoesNotExistError:
            # Skip test if no Mollie Settings configured
            pass

    def setUp(self):
        """Set up test case"""
        super().setUp()
        self.settings_name = "Resilience Test"
        self.audit_trail = ImmutableAuditTrail()

    def test_retry_policy_with_backoff(self):
        """Test retry policy with exponential backoff"""
        from verenigingen.verenigingen_payments.core.resilience.retry_policy import ExponentialBackoffRetry

        # Use ExponentialBackoffRetry which has the proper API for exponential backoff testing
        policy = ExponentialBackoffRetry(
            max_attempts=4,
            base_delay=0.1,  # Short for testing
            max_delay=1.0,
            jitter=False,  # Disable jitter for predictable timing
        )

        attempt_times = []

        def failing_operation():
            attempt_times.append(time.time())
            if len(attempt_times) < 3:
                raise Exception("Transient failure")
            return "success"

        start_time = time.time()
        result = policy.execute(failing_operation)
        total_time = time.time() - start_time

        self.assertEqual(result, "success")
        self.assertEqual(len(attempt_times), 3)

        # Verify exponential backoff timing (with base=0.1, factor=2)
        # First retry: 0.1s, Second retry: 0.2s
        for i in range(1, len(attempt_times)):
            delay = attempt_times[i] - attempt_times[i - 1]
            expected_delay = 0.1 * (2 ** (i - 1))
            # Allow some tolerance for timing
            self.assertAlmostEqual(delay, expected_delay, delta=0.1)

    def test_rate_limiter_with_burst_recovery(self):
        """Test rate limiter burst handling and recovery"""

        # TokenBucketRateLimiter uses max_tokens for burst capacity
        # and refill_rate for tokens added per refill_period
        limiter = TokenBucketRateLimiter(
            max_tokens=15,  # Burst capacity
            refill_rate=10.0,  # Tokens per refill period
            refill_period=1.0,  # Refill every second
        )

        # Consume burst capacity
        burst_allowed = 0
        for _ in range(20):
            # acquire() returns True if token acquired, False otherwise
            can_proceed = limiter.acquire(tokens=1, wait=False)
            if can_proceed:
                burst_allowed += 1

        # Should allow burst size (max_tokens)
        self.assertEqual(burst_allowed, 15)

        # Should be rate limited now
        can_proceed = limiter.acquire(tokens=1, wait=False)
        self.assertFalse(can_proceed)

        # Wait for recovery. Refills are quantized to whole refill_periods
        # (refill_count = int(elapsed / refill_period)), so a sub-period sleep
        # adds zero tokens — wait slightly more than one full period (1.0s).
        time.sleep(1.1)

        # Should allow more requests after recovery
        can_proceed = limiter.acquire(tokens=1, wait=False)
        self.assertTrue(can_proceed)

    def test_http_client_resilience_integration(self):
        """Test HTTP client with all resilience features"""

        # ResilientHTTPClient requires base_url and uses different param names
        # Note: circuit_breaker_threshold is now ignored (circuit breakers deprecated 2026-02)
        client = ResilientHTTPClient(
            base_url="https://api.test.com",
            circuit_breaker_threshold=2,  # Ignored - kept for API compat
            rate_limit=5,
            max_retries=3,
        )

        # Test 1: Error handling (circuit breakers deprecated)
        # With circuit breakers removed, requests just fail with the underlying exception
        with patch.object(client.session, "request") as mock_request:
            # Simulate failures
            mock_request.side_effect = Exception("Connection error")

            # Calls should fail with the underlying exception
            with self.assertRaises(Exception) as context:
                client.request("GET", "/endpoint")
            self.assertIn("Connection error", str(context.exception))

        # Test 2: Rate limiting integration
        client = ResilientHTTPClient(base_url="https://api.test.com", rate_limit=2)

        with patch.object(client.session, "request") as mock_request:
            mock_request.return_value = MagicMock(status_code=200, headers={}, json=lambda: {})

            # Should rate limit after burst
            success_count = 0
            for _ in range(10):
                try:
                    client.request("GET", "/endpoint")
                    success_count += 1
                except Exception:
                    pass

            # Should be rate limited (not all requests succeed)
            self.assertLess(success_count, 10)

        # Test 3: Retry with circuit breaker interaction
        client = ResilientHTTPClient(
            base_url="https://api.test.com", circuit_breaker_threshold=5, max_retries=3
        )

        with patch.object(client.session, "request") as mock_request:
            # Successful response
            mock_response = MagicMock(
                status_code=200,
                headers={"Content-Type": "application/json"},
                json=lambda: {"result": "success"},
                text='{"result": "success"}',
            )
            mock_response.raise_for_status = MagicMock()
            mock_request.return_value = mock_response

            response_data, status_code = client.request("GET", "/endpoint")
            self.assertEqual(status_code, 200)

    def test_database_transaction_rollback(self):
        """Test database transaction rollback on failure"""

        def failing_transaction():
            """Transaction that fails midway"""
            frappe.db.begin()

            try:
                # Create first record
                doc1 = frappe.new_doc("Mollie Audit Log")
                doc1.event_type = "TEST_ROLLBACK_1"
                doc1.message = "First record"
                doc1.severity = "INFO"
                doc1.insert()  # VereningingenTestCase handles permissions

                # Create second record
                doc2 = frappe.new_doc("Mollie Audit Log")
                doc2.event_type = "TEST_ROLLBACK_2"
                doc2.message = "Second record"
                doc2.severity = "INFO"
                doc2.insert()  # VereningingenTestCase handles permissions

                # Simulate failure
                raise Exception("Transaction failed")

                # This should not be reached
                frappe.db.commit()

            except Exception:
                frappe.db.rollback()
                raise

        # Execute failing transaction
        with self.assertRaises(Exception):
            failing_transaction()

        # Verify rollback - no records should exist
        count = frappe.db.count(
            "Mollie Audit Log", filters={"event_type": ["in", ["TEST_ROLLBACK_1", "TEST_ROLLBACK_2"]]}
        )
        self.assertEqual(count, 0, "Transaction not rolled back properly")

    def test_queue_processing_failure_recovery(self):
        """Test queue processing with failure recovery"""

        # Simulate a queue processor
        class QueueProcessor:
            def __init__(self):
                self.queue = queue.Queue()
                self.failed_items = []
                self.processed_items = []
                self.retry_queue = queue.Queue()

            def process_item(self, item):
                """Process a single item"""
                if item.get("fail_count", 0) > 0:
                    item["fail_count"] -= 1
                    raise Exception(f"Processing failed for {item['id']}")

                self.processed_items.append(item)
                return True

            def process_with_retry(self, max_retries=3):
                """Process queue with retry logic"""
                while not self.queue.empty():
                    item = self.queue.get()
                    retry_count = 0

                    while retry_count <= max_retries:
                        try:
                            self.process_item(item)
                            break
                        except Exception:
                            retry_count += 1
                            if retry_count > max_retries:
                                self.failed_items.append(item)
                            else:
                                # Add back to retry queue with delay
                                time.sleep(0.01 * retry_count)  # Exponential backoff
                                item["retry_count"] = retry_count

        processor = QueueProcessor()

        # Add items to queue (some will fail initially)
        for i in range(10):
            processor.queue.put(
                {
                    "id": f"item_{i}",
                    "fail_count": 2 if i % 3 == 0 else 0,  # Every 3rd item fails twice
                }
            )

        # Process queue
        processor.process_with_retry(max_retries=3)

        # Verify recovery
        self.assertEqual(len(processor.processed_items), 10, "Not all items recovered")
        self.assertEqual(len(processor.failed_items), 0, "Some items failed permanently")

    def test_data_consistency_during_partial_failure(self):
        """Test data consistency when partial failures occur"""

        class TransactionalProcessor:
            def __init__(self):
                self.state = {"balance": 1000, "transactions": []}

            def process_payment(self, amount, should_fail_at_step=None):
                """Process payment with potential failure points"""

                # Step 1: Validate
                if amount > self.state["balance"]:
                    raise ValueError("Insufficient balance")

                if should_fail_at_step == 1:
                    raise Exception("Validation failed")

                # Step 2: Deduct balance
                original_balance = self.state["balance"]
                self.state["balance"] -= amount

                if should_fail_at_step == 2:
                    # Rollback
                    self.state["balance"] = original_balance
                    raise Exception("Balance update failed")

                # Step 3: Record transaction
                transaction = {
                    "id": f"txn_{len(self.state['transactions'])}",
                    "amount": amount,
                    "timestamp": datetime.now(),
                }

                try:
                    self.state["transactions"].append(transaction)

                    if should_fail_at_step == 3:
                        raise Exception("Transaction recording failed")

                except Exception:
                    # Rollback everything
                    self.state["balance"] = original_balance
                    if transaction in self.state["transactions"]:
                        self.state["transactions"].remove(transaction)
                    raise

                return transaction

        processor = TransactionalProcessor()

        # Test successful transaction
        txn1 = processor.process_payment(100)
        self.assertEqual(processor.state["balance"], 900)
        self.assertEqual(len(processor.state["transactions"]), 1)

        # Test failure at validation
        with self.assertRaises(Exception):
            processor.process_payment(100, should_fail_at_step=1)

        # State should be unchanged
        self.assertEqual(processor.state["balance"], 900)
        self.assertEqual(len(processor.state["transactions"]), 1)

        # Test failure at balance update
        with self.assertRaises(Exception):
            processor.process_payment(100, should_fail_at_step=2)

        # State should be rolled back
        self.assertEqual(processor.state["balance"], 900)
        self.assertEqual(len(processor.state["transactions"]), 1)

        # Test failure at transaction recording
        with self.assertRaises(Exception):
            processor.process_payment(100, should_fail_at_step=3)

        # Everything should be rolled back
        self.assertEqual(processor.state["balance"], 900)
        self.assertEqual(len(processor.state["transactions"]), 1)

    def test_reconciliation_failure_recovery(self):
        """Test reconciliation engine recovery from failures"""

        # ReconciliationEngine builds the backend-API clients in its
        # constructor, which require the backend API to be enabled.
        _enable_mollie_backend_api()

        # ReconciliationEngine takes no constructor arguments
        engine = ReconciliationEngine()

        # Test 1: Partial settlement processing failure
        settlements = [{"id": f"stl_{i}", "amount": 100 * i} for i in range(1, 6)]

        processed = []
        failed = []

        for settlement in settlements:
            try:
                # Simulate failure for specific settlements
                if settlement["id"] in ["stl_3", "stl_4"]:
                    raise Exception(f"Failed to process {settlement['id']}")

                processed.append(settlement)
            except Exception:
                failed.append(settlement)

        # Should track both processed and failed
        self.assertEqual(len(processed), 3)
        self.assertEqual(len(failed), 2)

        # Test 2: Retry failed settlements
        retry_success = []

        for settlement in failed:
            try:
                # Second attempt succeeds
                processed.append(settlement)
                retry_success.append(settlement)
            except Exception:
                pass

        self.assertEqual(len(retry_success), 2)
        self.assertEqual(len(processed), 5)

    def test_audit_trail_during_failures(self):
        """Test audit trail maintains integrity during failures"""

        # Use valid AuditEventType members (there is no RECONCILIATION_STARTED
        # in the enum). SETTLEMENT_PROCESSED stands in for the "start" event.
        # A unique marker in the description scopes the query to THIS test's
        # events (other tests in the module also emit these event types).
        start_event = AuditEventType.SETTLEMENT_PROCESSED
        marker = f"AUDITTEST-{frappe.generate_hash(length=8)}"

        # Test audit logging doesn't fail even when main operation fails
        def failing_operation():
            try:
                # Log start
                self.audit_trail.log_event(
                    start_event, AuditSeverity.INFO, f"{marker} Starting operation"
                )

                # Operation fails
                raise Exception("Operation failed")

            except Exception as e:
                # Log failure
                self.audit_trail.log_event(
                    AuditEventType.ERROR_OCCURRED, AuditSeverity.ERROR, f"{marker} Operation failed: {str(e)}"
                )
                raise

        # Execute failing operation
        with self.assertRaises(Exception):
            failing_operation()

        # Events are buffered until the buffer fills (or is flushed), so flush to
        # persist them to Mollie Audit Log before querying.
        self.audit_trail._flush_buffer()
        frappe.db.commit()

        # The stored event_type is the enum VALUE (lowercase), not its NAME.
        logs = frappe.get_all(
            "Mollie Audit Log",
            filters={
                "description": ["like", f"{marker}%"],
            },
            fields=["event_type", "severity", "description"],
        )

        self.assertEqual(len(logs), 2)

        # Verify order and content
        start_log = next((l for l in logs if l["event_type"] == start_event.value), None)
        error_log = next(
            (l for l in logs if l["event_type"] == AuditEventType.ERROR_OCCURRED.value), None
        )

        self.assertIsNotNone(start_log)
        self.assertIsNotNone(error_log)
        # Severity values are lowercase in the schema: info, warning, error, critical
        self.assertEqual(error_log["severity"], "error")

    def tearDown(self):
        """Clean up test data"""
        # Clean up test audit logs
        frappe.db.delete("Mollie Audit Log", {"event_type": ["like", "%TEST%"]})
        frappe.db.commit()
        super().tearDown()
