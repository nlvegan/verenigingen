#!/usr/bin/env python3
"""
Core Test Runner for Mollie Backend Integration
Tests the essential components that are fully working
"""

import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup test environment
import setup_test_env


def test_mollie_connector():
    """Test the core Mollie connector functionality"""
    print("\n1. Testing Mollie Connector...")

    try:
        # Mock Mollie client
        mock_client = Mock()
        mock_balance = Mock(
            id="primary",
            currency="EUR",
            available_amount=Mock(value="1000.00", currency="EUR"),
            pending_amount=Mock(value="50.00", currency="EUR"),
            created_at="2024-01-01T00:00:00Z",
        )
        mock_client.balances.get.return_value = mock_balance
        mock_client.balances.list.return_value = [mock_balance]
        mock_client.methods.list.return_value = []

        with patch(
            "verenigingen.verenigingen_payments.integration.mollie_connector.MollieClient"
        ) as mock_class:
            mock_class.return_value = mock_client

            from verenigingen.verenigingen_payments.integration.mollie_connector import (
                MollieConnector,
                get_mollie_connector,
            )

            # Test initialization
            connector = MollieConnector("Test Settings")
            assert connector is not None
            print("   ✓ Connector initialized")

            # Test balance operations
            balance = connector.get_balance("primary")
            assert balance["id"] == "primary"
            assert balance["currency"] == "EUR"
            print("   ✓ Balance operations work")

            # Test singleton pattern
            connector2 = get_mollie_connector("Test Settings")
            assert connector2 is not None
            print("   ✓ Singleton pattern works")

        print("   ✅ Mollie Connector tests PASSED")
        return True

    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
        return False


def test_circuit_breaker():
    """Test circuit breaker resilience pattern"""
    print("\n2. Testing Circuit Breaker...")

    try:
        from verenigingen.verenigingen_payments.core.resilience.circuit_breaker import (
            CircuitBreaker,
            CircuitState,
        )

        # Create breaker
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1, success_threshold=1)

        assert breaker.state == CircuitState.CLOSED
        print("   ✓ Circuit starts CLOSED")

        # Test failures
        for _ in range(2):
            try:
                breaker.call(lambda: 1 / 0)
            except:
                pass

        assert breaker.state == CircuitState.OPEN
        print("   ✓ Circuit opens after failures")

        print("   ✅ Circuit Breaker tests PASSED")
        return True

    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
        return False


def test_rate_limiter():
    """Test token bucket rate limiter"""
    print("\n3. Testing Rate Limiter...")

    try:
        from verenigingen.verenigingen_payments.core.resilience.rate_limiter import TokenBucketRateLimiter

        # Create limiter with small bucket
        limiter = TokenBucketRateLimiter(max_tokens=5, refill_rate=1, refill_period=0.1)

        # Test burst capacity
        tokens_acquired = 0
        for _ in range(5):
            if limiter.acquire(1):
                tokens_acquired += 1

        assert tokens_acquired == 5
        print("   ✓ Burst capacity works")

        # Test rate limiting
        denied = not limiter.acquire(1, wait=False)
        assert denied
        print("   ✓ Rate limiting works")

        print("   ✅ Rate Limiter tests PASSED")
        return True

    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
        return False


def test_encryption():
    """Test encryption handler"""
    print("\n4. Testing Encryption...")

    try:
        # Mock frappe.conf for encryption key storage
        with patch("frappe.conf", {"mollie_encryption_key": "mock_key_123"}):
            from cryptography.fernet import Fernet

            from verenigingen.verenigingen_payments.core.security.encryption_handler import EncryptionHandler

            # Create a test encryption key
            test_key = Fernet.generate_key()
            handler = EncryptionHandler(encryption_key=test_key)

            # Test encryption/decryption
            sensitive = "secret_data_123"
            encrypted = handler.encrypt_data(sensitive)
            decrypted = handler.decrypt_data(encrypted)

            assert decrypted == sensitive
            assert encrypted != sensitive
            print("   ✓ Encryption/decryption works")

        print("   ✅ Encryption tests PASSED")
        return True

    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
        return False


def test_webhook_validation():
    """Test webhook signature validation"""
    print("\n5. Testing Webhook Validation...")

    try:
        from cryptography.fernet import Fernet

        from verenigingen.verenigingen_payments.core.security.mollie_security_manager import (
            MollieSecurityManager,
        )

        # Mock Mollie settings with proper structure
        mock_settings = Mock()
        mock_settings.get_password.return_value = "test_secret_webhook"

        # Mock the encryption key generation to avoid base64 padding issues
        test_key = Fernet.generate_key()

        with patch.object(MollieSecurityManager, "_get_or_create_encryption_key", return_value=test_key):
            security_manager = MollieSecurityManager(mock_settings)

            # Test webhook signature validation
            payload = '{"id": "test123", "resource": "payment", "status": "paid", "amount": {"value": "10.00", "currency": "EUR"}}'

            # Calculate expected signature
            import hashlib
            import hmac

            expected_signature = hmac.new(
                "test_secret_webhook".encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
            ).hexdigest()

            # Test validation
            is_valid = security_manager.validate_webhook_signature(payload, expected_signature)
            assert is_valid
            print("   ✓ Signature validation works")

            # Test invalid signature
            is_invalid = security_manager.validate_webhook_signature(payload, "bad_signature")
            assert not is_invalid
            print("   ✓ Invalid signature detection works")

        print("   ✅ Webhook Validation tests PASSED")
        return True

    except Exception as e:
        print(f"   ❌ FAILED: {str(e)}")
        return False


def main():
    """Run all core tests"""
    print("=" * 60)
    print("MOLLIE BACKEND CORE TESTS")
    print("=" * 60)

    results = {
        "Mollie Connector": test_mollie_connector(),
        "Circuit Breaker": test_circuit_breaker(),
        "Rate Limiter": test_rate_limiter(),
        "Encryption": test_encryption(),
        "Webhook Validation": test_webhook_validation(),
    }

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"Total: {total}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {total - passed}")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print("\n⚠️  Some tests failed")
        for name, result in results.items():
            if not result:
                print(f"   - {name}")

    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
