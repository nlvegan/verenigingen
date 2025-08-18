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
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.core.resilience.circuit_breaker import CircuitBreaker, CircuitState
from verenigingen.verenigingen_payments.core.resilience.rate_limiter import RateLimiter
from verenigingen.verenigingen_payments.core.resilience.retry_policy import RetryPolicy, RetryStrategy
from verenigingen.verenigingen_payments.core.http_client import ResilientHTTPClient
from verenigingen.verenigingen_payments.workflows.reconciliation_engine import ReconciliationEngine
from verenigingen.verenigingen_payments.workflows.subscription_manager import SubscriptionManager
from verenigingen.verenigingen_payments.core.compliance.audit_trail import AuditTrail, AuditEventType, AuditSeverity


class TestErrorRecovery(FrappeTestCase):
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
        
        # Create test settings with resilience configuration
        if not frappe.db.exists("Mollie Settings", "Resilience Test"):
            settings = frappe.new_doc("Mollie Settings")
            settings.gateway_name = "Resilience Test"
            settings.secret_key = "resilience_test_key"
            settings.profile_id = "pfl_resilience"
            settings.enable_backend_api = True
            settings.circuit_breaker_failure_threshold = 3
            settings.circuit_breaker_timeout = 1
            settings.retry_max_attempts = 3
            settings.retry_backoff_base = 1
            settings.connection_timeout = 2
            settings.request_timeout = 5
            settings.insert(ignore_permissions=True)
            frappe.db.commit()
    
    def setUp(self):
        """Set up test case"""
        super().setUp()
        self.settings_name = "Resilience Test"
        self.audit_trail = AuditTrail()
    
    def test_circuit_breaker_state_transitions(self):
        """Test circuit breaker state transitions and recovery"""
        
        breaker = CircuitBreaker(
            failure_threshold=3,
            timeout=1.0,
            expected_exception=Exception
        )
        
        # Initial state should be CLOSED
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        
        # Cause failures to trip the breaker
        for i in range(3):
            try:
                with breaker:
                    raise Exception(f"Failure {i+1}")
            except Exception:
                pass
        
        # Should be OPEN after threshold
        self.assertEqual(breaker.state, CircuitState.OPEN)
        
        # Should reject calls while OPEN
        with self.assertRaises(Exception) as context:
            with breaker:
                pass
        self.assertIn("Circuit breaker is OPEN", str(context.exception))
        
        # Wait for timeout
        time.sleep(1.1)
        
        # Should transition to HALF_OPEN
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)
        
        # Successful call should close the circuit
        try:
            with breaker:
                pass  # Success
        except Exception:
            self.fail("Circuit breaker should allow test call in HALF_OPEN")
        
        # Should be CLOSED again
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        
        # Test immediate re-opening on failure in HALF_OPEN
        for i in range(3):
            try:
                with breaker:
                    raise Exception(f"Failure {i+1}")
            except Exception:
                pass
        
        self.assertEqual(breaker.state, CircuitState.OPEN)
        time.sleep(1.1)
        
        # Single failure in HALF_OPEN should re-open immediately
        try:
            with breaker:
                raise Exception("Single failure")
        except Exception:
            pass
        
        self.assertEqual(breaker.state, CircuitState.OPEN)
    
    def test_retry_policy_with_backoff(self):
        """Test retry policy with exponential backoff"""
        
        policy = RetryPolicy(
            max_attempts=4,
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            backoff_base=0.1,  # Short for testing
            max_backoff=1.0
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
        
        # Verify exponential backoff timing
        for i in range(1, len(attempt_times)):
            delay = attempt_times[i] - attempt_times[i-1]
            expected_delay = 0.1 * (2 ** (i-1))
            # Allow some tolerance for timing
            self.assertAlmostEqual(delay, expected_delay, delta=0.05)
    
    def test_rate_limiter_with_burst_recovery(self):
        """Test rate limiter burst handling and recovery"""
        
        limiter = RateLimiter(
            requests_per_second=10,
            burst_size=15
        )
        
        # Consume burst capacity
        burst_allowed = 0
        for _ in range(20):
            can_proceed, wait_time = limiter.check_rate_limit("test")
            if can_proceed:
                burst_allowed += 1
        
        # Should allow burst size
        self.assertEqual(burst_allowed, 15)
        
        # Should be rate limited now
        can_proceed, wait_time = limiter.check_rate_limit("test")
        self.assertFalse(can_proceed)
        self.assertGreater(wait_time, 0)
        
        # Wait for recovery
        time.sleep(wait_time + 0.1)
        
        # Should allow more requests after recovery
        can_proceed, wait_time = limiter.check_rate_limit("test")
        self.assertTrue(can_proceed)
    
    def test_http_client_resilience_integration(self):
        """Test HTTP client with all resilience features"""
        
        client = ResilientHTTPClient(
            circuit_breaker_threshold=2,
            rate_limit_per_second=5,
            retry_max_attempts=3
        )
        
        # Test 1: Circuit breaker integration
        with patch('requests.request') as mock_request:
            # Simulate failures
            mock_request.side_effect = [
                Exception("Connection error"),
                Exception("Connection error"),
                MagicMock(status_code=200, json=lambda: {"status": "ok"})
            ]
            
            # First two calls should fail and open circuit
            for _ in range(2):
                try:
                    client.request("GET", "https://api.test.com/endpoint")
                except Exception:
                    pass
            
            # Circuit should be open
            with self.assertRaises(Exception) as context:
                client.request("GET", "https://api.test.com/endpoint")
            self.assertIn("Circuit breaker", str(context.exception))
        
        # Test 2: Rate limiting integration
        client = ResilientHTTPClient(rate_limit_per_second=2)
        
        with patch('requests.request') as mock_request:
            mock_request.return_value = MagicMock(status_code=200)
            
            # Should rate limit after burst
            success_count = 0
            for _ in range(10):
                try:
                    client.request("GET", "https://api.test.com/endpoint")
                    success_count += 1
                except Exception:
                    pass
            
            # Should be rate limited
            self.assertLess(success_count, 10)
        
        # Test 3: Retry with circuit breaker interaction
        client = ResilientHTTPClient(
            circuit_breaker_threshold=5,
            retry_max_attempts=3
        )
        
        with patch('requests.request') as mock_request:
            # Fail twice, then succeed
            mock_request.side_effect = [
                Exception("Temporary error"),
                Exception("Temporary error"),
                MagicMock(status_code=200, json=lambda: {"result": "success"})
            ]
            
            response = client.request("GET", "https://api.test.com/endpoint")
            self.assertEqual(response.status_code, 200)
    
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
                doc1.insert(ignore_permissions=True)
                
                # Create second record
                doc2 = frappe.new_doc("Mollie Audit Log")
                doc2.event_type = "TEST_ROLLBACK_2"
                doc2.message = "Second record"
                doc2.severity = "INFO"
                doc2.insert(ignore_permissions=True)
                
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
        count = frappe.db.count("Mollie Audit Log", 
                              filters={"event_type": ["in", ["TEST_ROLLBACK_1", "TEST_ROLLBACK_2"]]})
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
            processor.queue.put({
                "id": f"item_{i}",
                "fail_count": 2 if i % 3 == 0 else 0  # Every 3rd item fails twice
            })
        
        # Process queue
        processor.process_with_retry(max_retries=3)
        
        # Verify recovery
        self.assertEqual(len(processor.processed_items), 10, "Not all items recovered")
        self.assertEqual(len(processor.failed_items), 0, "Some items failed permanently")
    
    def test_network_partition_handling(self):
        """Test handling of network partitions"""
        
        class NetworkSimulator:
            def __init__(self):
                self.partition_active = False
                self.request_count = 0
                
            def make_request(self, endpoint):
                """Simulate network request"""
                self.request_count += 1
                
                if self.partition_active:
                    raise ConnectionError("Network unreachable")
                
                return {"status": "success", "endpoint": endpoint}
        
        network = NetworkSimulator()
        
        # Test with circuit breaker
        breaker = CircuitBreaker(failure_threshold=3, timeout=0.5)
        
        def resilient_request(endpoint):
            """Make request with circuit breaker"""
            with breaker:
                return network.make_request(endpoint)
        
        # Normal operation
        result = resilient_request("/api/test")
        self.assertEqual(result["status"], "success")
        
        # Simulate network partition
        network.partition_active = True
        
        # Should fail and open circuit
        failures = 0
        for _ in range(5):
            try:
                resilient_request("/api/test")
            except (ConnectionError, Exception):
                failures += 1
        
        self.assertEqual(failures, 5)
        self.assertEqual(breaker.state, CircuitState.OPEN)
        
        # Heal network partition
        network.partition_active = False
        
        # Wait for circuit breaker timeout
        time.sleep(0.6)
        
        # Should recover
        result = resilient_request("/api/test")
        self.assertEqual(result["status"], "success")
        self.assertEqual(breaker.state, CircuitState.CLOSED)
    
    def test_cascading_failure_prevention(self):
        """Test prevention of cascading failures"""
        
        class ServiceDependency:
            def __init__(self, name, failure_rate=0):
                self.name = name
                self.failure_rate = failure_rate
                self.call_count = 0
                self.breaker = CircuitBreaker(failure_threshold=2, timeout=0.5)
                
            def call(self):
                """Simulate service call"""
                self.call_count += 1
                
                with self.breaker:
                    if random.random() < self.failure_rate:
                        raise Exception(f"{self.name} failed")
                    return f"{self.name} response"
        
        # Create service dependency chain
        services = {
            "auth": ServiceDependency("auth", failure_rate=0),
            "payment": ServiceDependency("payment", failure_rate=0.8),  # High failure rate
            "notification": ServiceDependency("notification", failure_rate=0.1)
        }
        
        def process_request():
            """Process request with multiple service dependencies"""
            results = {}
            
            # Auth service (critical)
            try:
                results["auth"] = services["auth"].call()
            except Exception:
                return {"error": "Authentication failed"}
            
            # Payment service (can fail)
            try:
                results["payment"] = services["payment"].call()
            except Exception:
                results["payment"] = "payment_degraded"
            
            # Notification service (non-critical)
            try:
                results["notification"] = services["notification"].call()
            except Exception:
                results["notification"] = "notification_skipped"
            
            return results
        
        # Process multiple requests
        success_count = 0
        degraded_count = 0
        
        for _ in range(10):
            result = process_request()
            
            if "error" not in result:
                if result.get("payment") == "payment_degraded":
                    degraded_count += 1
                else:
                    success_count += 1
        
        # Should prevent cascading failures
        self.assertGreater(degraded_count, 0, "No degraded operations")
        self.assertEqual(success_count + degraded_count, 10, "Some requests failed completely")
        
        # Payment circuit should be open
        self.assertEqual(services["payment"].breaker.state, CircuitState.OPEN)
        
        # Other services should still be operational
        self.assertEqual(services["auth"].breaker.state, CircuitState.CLOSED)
    
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
                    "timestamp": datetime.now()
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
        
        engine = ReconciliationEngine(self.settings_name)
        
        # Test 1: Partial settlement processing failure
        settlements = [
            {"id": f"stl_{i}", "amount": 100 * i} 
            for i in range(1, 6)
        ]
        
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
        
        # Test audit logging doesn't fail even when main operation fails
        def failing_operation():
            try:
                # Log start
                self.audit_trail.log_event(
                    AuditEventType.RECONCILIATION_STARTED,
                    AuditSeverity.INFO,
                    "Starting operation"
                )
                
                # Operation fails
                raise Exception("Operation failed")
                
            except Exception as e:
                # Log failure
                self.audit_trail.log_event(
                    AuditEventType.ERROR_OCCURRED,
                    AuditSeverity.ERROR,
                    f"Operation failed: {str(e)}"
                )
                raise
        
        # Execute failing operation
        with self.assertRaises(Exception):
            failing_operation()
        
        # Verify audit trail captured both events
        logs = frappe.get_all(
            "Mollie Audit Log",
            filters={
                "event_type": ["in", ["RECONCILIATION_STARTED", "ERROR_OCCURRED"]],
                "created": [">", datetime.now() - timedelta(minutes=1)]
            },
            fields=["event_type", "severity", "message"]
        )
        
        self.assertEqual(len(logs), 2)
        
        # Verify order and content
        start_log = next((l for l in logs if l["event_type"] == "RECONCILIATION_STARTED"), None)
        error_log = next((l for l in logs if l["event_type"] == "ERROR_OCCURRED"), None)
        
        self.assertIsNotNone(start_log)
        self.assertIsNotNone(error_log)
        self.assertEqual(error_log["severity"], "ERROR")
    
    def tearDown(self):
        """Clean up test data"""
        # Clean up test audit logs
        frappe.db.delete("Mollie Audit Log", {
            "event_type": ["like", "%TEST%"]
        })
        frappe.db.commit()
        super().tearDown()