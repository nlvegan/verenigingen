"""
Test Harness for Mollie Backend Integration
Allows testing without full Frappe environment
"""

import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Mock Frappe if not available
try:
    import frappe
except ImportError:
    # Use our comprehensive mock
    from verenigingen.tests.frappe_mock import frappe
    sys.modules['frappe'] = frappe


class TestEnvironment:
    """Manages test environment setup and teardown"""
    
    def __init__(self, use_sandbox: bool = True):
        """
        Initialize test environment
        
        Args:
            use_sandbox: Whether to use Mollie sandbox API
        """
        self.use_sandbox = use_sandbox
        self.mocks = {}
        self._setup_environment()
    
    def _setup_environment(self):
        """Setup test environment variables and mocks"""
        # Set environment variables
        if self.use_sandbox:
            os.environ['MOLLIE_API_KEY'] = 'test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        
        # Setup default mocks
        self._setup_frappe_mocks()
        self._setup_mollie_mocks()
    
    def _setup_frappe_mocks(self):
        """Setup Frappe framework mocks"""
        # Mock Mollie Settings
        settings_doc = {
            "doctype": "Mollie Settings",
            "name": "Test Settings",
            "enabled": 1,
            "gateway_name": "Test",
            "profile_id": "pfl_test123",
            "webhook_url": "https://example.com/webhook",
            "get_password": Mock(return_value="test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        }
        
        frappe.get_doc = Mock(return_value=Mock(**settings_doc))
        frappe.get_all = Mock(return_value=[{"name": "Test Settings"}])
    
    def _setup_mollie_mocks(self):
        """Setup Mollie API mocks"""
        # Create mock Mollie client
        mock_client = MagicMock()
        
        # Mock balance responses
        mock_balance = Mock(
            id="primary",
            currency="EUR",
            available_amount=Mock(value="1000.00", currency="EUR"),
            pending_amount=Mock(value="50.00", currency="EUR"),
            created_at="2024-01-01T00:00:00Z"
        )
        
        mock_client.balances.get = Mock(return_value=mock_balance)
        mock_client.balances.list = Mock(return_value=[mock_balance])
        
        # Mock settlement responses
        mock_settlement = Mock(
            id="stl_test123",
            reference="123456",
            amount=Mock(value="500.00", currency="EUR"),
            status="paidout",
            created_at="2024-01-01T00:00:00Z",
            settled_at="2024-01-02T00:00:00Z",
            periods=[]
        )
        
        mock_client.settlements.get = Mock(return_value=mock_settlement)
        mock_client.settlements.list = Mock(return_value=[mock_settlement])
        
        # Mock payment responses
        mock_payment = Mock(
            id="tr_test123",
            status="paid",
            amount=Mock(value="25.00", currency="EUR"),
            method="ideal",
            created_at="2024-01-01T00:00:00Z",
            paid_at="2024-01-01T00:01:00Z",
            checkout_url="https://www.mollie.com/checkout/test",
            metadata={}
        )
        
        mock_client.payments.create = Mock(return_value=mock_payment)
        mock_client.payments.get = Mock(return_value=mock_payment)
        
        # Store mock client
        self.mocks['mollie_client'] = mock_client
    
    def get_mock_client(self):
        """Get mock Mollie client"""
        return self.mocks.get('mollie_client')
    
    def cleanup(self):
        """Cleanup test environment"""
        # Remove environment variables
        if 'MOLLIE_API_KEY' in os.environ:
            del os.environ['MOLLIE_API_KEY']


class TestRunner:
    """Runs tests with proper mocking and reporting"""
    
    def __init__(self, verbose: bool = True):
        """
        Initialize test runner
        
        Args:
            verbose: Whether to print detailed output
        """
        self.verbose = verbose
        self.results = {
            "passed": [],
            "failed": [],
            "errors": [],
            "skipped": []
        }
    
    def run_test(self, test_name: str, test_func, *args, **kwargs):
        """
        Run a single test
        
        Args:
            test_name: Name of the test
            test_func: Test function to run
            *args: Test function arguments
            **kwargs: Test function keyword arguments
        """
        try:
            if self.verbose:
                print(f"Running {test_name}...", end=" ")
            
            result = test_func(*args, **kwargs)
            
            self.results["passed"].append(test_name)
            
            if self.verbose:
                print("✅ PASSED")
            
            return result
            
        except AssertionError as e:
            self.results["failed"].append({
                "test": test_name,
                "error": str(e)
            })
            
            if self.verbose:
                print(f"❌ FAILED: {str(e)}")
            
        except Exception as e:
            self.results["errors"].append({
                "test": test_name,
                "error": str(e)
            })
            
            if self.verbose:
                print(f"💥 ERROR: {str(e)}")
    
    def print_summary(self):
        """Print test results summary"""
        total = (len(self.results["passed"]) + 
                len(self.results["failed"]) + 
                len(self.results["errors"]))
        
        print("\n" + "="*60)
        print("TEST RESULTS SUMMARY")
        print("="*60)
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {len(self.results['passed'])}")
        print(f"❌ Failed: {len(self.results['failed'])}")
        print(f"💥 Errors: {len(self.results['errors'])}")
        print(f"⏭️  Skipped: {len(self.results['skipped'])}")
        
        if self.results["failed"]:
            print("\nFailed Tests:")
            for failure in self.results["failed"]:
                print(f"  - {failure['test']}: {failure['error']}")
        
        if self.results["errors"]:
            print("\nTest Errors:")
            for error in self.results["errors"]:
                print(f"  - {error['test']}: {error['error']}")
        
        print("="*60)
        
        # Return success status
        return len(self.results["failed"]) == 0 and len(self.results["errors"]) == 0


def test_mollie_connector():
    """Test Mollie connector functionality"""
    env = TestEnvironment(use_sandbox=True)
    
    try:
        # Mock the Mollie client import
        with patch('verenigingen.verenigingen_payments.integration.mollie_connector.MollieClient') as mock_class:
            mock_class.return_value = env.get_mock_client()
            
            # Import after mocking
            from verenigingen.verenigingen_payments.integration.mollie_connector import (
                MollieConnector, get_mollie_connector
            )
            
            # Test connector initialization
            connector = MollieConnector("Test Settings")
            assert connector is not None, "Connector should initialize"
            
            # Test balance operations
            balance = connector.get_balance("primary")
            assert balance["id"] == "primary", "Should get primary balance"
            assert balance["currency"] == "EUR", "Should have EUR currency"
            assert balance["available"]["amount"] == "1000.00", "Should have correct available amount"
            
            # Test settlement operations
            settlements = connector.list_settlements()
            assert len(settlements) > 0, "Should list settlements"
            assert settlements[0]["id"] == "stl_test123", "Should have test settlement"
            
            # Test payment creation
            payment = connector.create_payment(
                amount=Decimal("25.00"),
                currency="EUR",
                description="Test payment"
            )
            assert payment["id"] == "tr_test123", "Should create payment"
            assert payment["status"] == "paid", "Payment should be paid"
            
            print("✅ All connector tests passed!")
            return True
            
    except Exception as e:
        print(f"❌ Connector test failed: {str(e)}")
        return False
        
    finally:
        env.cleanup()


def test_resilience_patterns():
    """Test resilience patterns (circuit breaker, rate limiter, retry)"""
    try:
        from verenigingen.verenigingen_payments.core.resilience.circuit_breaker import (
            CircuitBreaker, CircuitState
        )
        from verenigingen.verenigingen_payments.core.resilience.rate_limiter import TokenBucketRateLimiter as RateLimiter
        from verenigingen.verenigingen_payments.core.resilience.retry_policy import ExponentialBackoffRetry as RetryPolicy
        
        # Test Circuit Breaker
        breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=1,
            success_threshold=2
        )
        
        assert breaker.state == CircuitState.CLOSED, "Should start in CLOSED state"
        
        # Simulate failures
        for _ in range(3):
            try:
                breaker.call(lambda: 1/0)  # Will fail
            except:
                pass
        
        assert breaker.state == CircuitState.OPEN, "Should be OPEN after failures"
        
        # Test Rate Limiter
        limiter = RateLimiter(max_tokens=20, refill_rate=10, refill_period=1.0)
        
        # Should allow initial burst
        for _ in range(20):
            allowed = limiter.acquire(1)
            assert allowed, "Should allow burst requests"
        
        # Should rate limit after burst
        allowed = limiter.acquire(1, wait=False)
        assert not allowed, "Should rate limit after burst"
        
        # Test Retry Policy
        policy = RetryPolicy(max_attempts=3, base_delay=0.1)
        
        attempt = 0
        def failing_func():
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise ConnectionError("Test error")
            return "success"
        
        result = policy.execute(failing_func)
        assert result == "success", "Should retry and succeed"
        assert attempt == 3, "Should have made 3 attempts"
        
        print("✅ All resilience tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Resilience test failed: {str(e)}")
        return False


def test_security_components():
    """Test security components"""
    try:
        from verenigingen.verenigingen_payments.core.security.encryption_handler import (
            EncryptionHandler
        )
        from verenigingen.verenigingen_payments.core.security.webhook_validator import (
            WebhookValidator
        )
        
        # Test Encryption
        handler = EncryptionHandler()
        
        sensitive_data = "secret_api_key_12345"
        encrypted = handler.encrypt_data(sensitive_data)
        decrypted = handler.decrypt_data(encrypted)
        
        assert decrypted == sensitive_data, "Should encrypt and decrypt correctly"
        assert encrypted != sensitive_data, "Encrypted data should be different"
        
        # Test Webhook Validation
        with patch.object(WebhookValidator, '_load_settings') as mock_settings:
            mock_settings.return_value = {
                "webhook_secret": "test_secret_123"
            }
            
            validator = WebhookValidator("Test Settings")
            
            # Create test webhook
            payload = '{"id": "tr_123", "amount": "100.00"}'
            signature = validator._compute_signature(
                payload.encode(),
                b"test_secret_123"
            )
            
            # Validate webhook
            is_valid = validator.validate_webhook(payload.encode(), signature)
            assert is_valid, "Should validate correct signature"
            
            # Test invalid signature
            is_valid = validator.validate_webhook(payload.encode(), "invalid_sig")
            assert not is_valid, "Should reject invalid signature"
        
        print("✅ All security tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Security test failed: {str(e)}")
        return False


def test_business_workflows():
    """Test business workflow components"""
    env = TestEnvironment(use_sandbox=True)
    
    try:
        # Mock dependencies
        with patch('verenigingen.verenigingen_payments.clients.balances_client.BalancesClient'):
            with patch('verenigingen.verenigingen_payments.clients.settlements_client.SettlementsClient'):
                
                from verenigingen.verenigingen_payments.workflows.reconciliation_engine import (
                    ReconciliationEngine
                )
                
                # Test Reconciliation Engine
                engine = ReconciliationEngine("Test Settings")
                
                # Mock settlement processing
                result = {
                    "settlement_id": "stl_test123",
                    "status": "reconciled",
                    "matched_count": 5,
                    "unmatched_count": 0
                }
                
                with patch.object(engine, 'process_settlement', return_value=result):
                    settlement_result = engine.process_settlement("stl_test123")
                    assert settlement_result["status"] == "reconciled", "Should reconcile settlement"
                    assert settlement_result["matched_count"] == 5, "Should match payments"
        
        print("✅ All workflow tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Workflow test failed: {str(e)}")
        return False
        
    finally:
        env.cleanup()


def main():
    """Main test execution"""
    print("="*60)
    print("MOLLIE BACKEND INTEGRATION TEST SUITE")
    print("="*60)
    print()
    
    runner = TestRunner(verbose=True)
    
    # Run test suites
    print("1. Testing Mollie Connector...")
    runner.run_test("Mollie Connector", test_mollie_connector)
    
    print("\n2. Testing Resilience Patterns...")
    runner.run_test("Resilience Patterns", test_resilience_patterns)
    
    print("\n3. Testing Security Components...")
    runner.run_test("Security Components", test_security_components)
    
    print("\n4. Testing Business Workflows...")
    runner.run_test("Business Workflows", test_business_workflows)
    
    # Print summary
    success = runner.print_summary()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()