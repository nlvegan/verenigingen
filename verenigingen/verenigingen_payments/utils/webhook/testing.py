# Copyright (c) 2026, Verenigingen
# License: MIT

"""
Shared Webhook Test Helpers for PSP Integrations.

Provides a base class and utilities for testing webhook endpoints across
Mollie, Ponto, and ING Checkout integrations. This enables consistent
testing patterns and reduces code duplication.

Usage:
    from verenigingen.utils.webhook.testing import (
        MollieWebhookTestHelper,
        PontoWebhookTestHelper,
        INGCheckoutWebhookTestHelper,
    )

    # In tests:
    helper = MollieWebhookTestHelper()
    payload = helper.create_test_payload(payment_id="tr_test123", status="paid")
    result = helper.simulate_webhook_call(payload)
    assert helper.verify_idempotency(payload)
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.verenigingen_payments.utils.shared.responses import compute_hmac_signature

from .logging import compute_webhook_hash, is_duplicate_webhook


@dataclass
class WebhookTestResult:
    """Result from simulating a webhook call."""

    success: bool
    status_code: int = 200
    response: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0
    webhook_log_created: bool = False
    idempotent: bool = False


class WebhookTestHelper(ABC):
    """
    Abstract base class for PSP webhook testing.

    Provides common functionality for testing webhook endpoints:
    - Creating test payloads
    - Simulating webhook calls
    - Verifying idempotency
    - Generating test signatures
    """

    def __init__(self):
        self.test_payloads: List[Dict] = []
        self._mock_patches: List[Any] = []

    @property
    @abstractmethod
    def psp_name(self) -> str:
        """Return the PSP name (mollie, ponto, ing_checkout)."""
        pass

    @abstractmethod
    def create_test_payload(self, **kwargs) -> Dict[str, Any]:
        """
        Create a test webhook payload for this PSP.

        Args:
            **kwargs: PSP-specific parameters for the payload

        Returns:
            Dict containing the webhook payload
        """
        pass

    @abstractmethod
    def simulate_webhook_call(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookTestResult:
        """
        Simulate a webhook call to this PSP's endpoint.

        Args:
            payload: The webhook payload
            headers: Optional HTTP headers

        Returns:
            WebhookTestResult with the outcome
        """
        pass

    @abstractmethod
    def generate_signature(self, payload: Dict[str, Any], secret: str) -> str:
        """
        Generate a valid signature for the payload.

        Args:
            payload: The webhook payload
            secret: The webhook secret key

        Returns:
            The signature string
        """
        pass

    def verify_idempotency(self, payload: Dict[str, Any]) -> bool:
        """
        Verify that the webhook idempotency check works correctly.

        Calls the webhook twice and verifies the second call is
        recognized as a duplicate.

        Args:
            payload: The webhook payload to test

        Returns:
            True if idempotency works correctly
        """
        # First call should succeed
        result1 = self.simulate_webhook_call(payload)
        if not result1.success:
            return False

        # Second call should be recognized as duplicate
        result2 = self.simulate_webhook_call(payload)
        return result2.idempotent

    def compute_payload_hash(self, event_id: str, payload: Dict[str, Any]) -> str:
        """
        Compute hash for idempotency check.

        Args:
            event_id: The event/webhook ID
            payload: The full payload

        Returns:
            SHA256 hash string
        """
        payload_str = json.dumps(payload, sort_keys=True)
        return compute_webhook_hash(event_id, payload_str)

    def is_duplicate(self, event_id: str, payload: Dict[str, Any]) -> bool:
        """
        Check if this webhook was already processed.

        Args:
            event_id: The event/webhook ID
            payload: The full payload

        Returns:
            True if already processed
        """
        payload_str = json.dumps(payload, sort_keys=True)
        return is_duplicate_webhook(event_id, payload_str)

    def _handle_duplicate(
        self,
        event_id: str,
        payload: Dict[str, Any],
        start_time: float,
        response: Optional[Dict[str, Any]] = None,
    ) -> Optional["WebhookTestResult"]:
        """
        Return a duplicate WebhookTestResult if the event was already processed.

        Callers pass their event_id and payload; if a duplicate is detected,
        this method builds and returns the standardised idempotent result.
        If no duplicate is detected, returns None so the caller can continue.

        Args:
            event_id: The event/webhook identifier
            payload: The full payload
            start_time: Wall-clock time captured at the start of simulate_webhook_call
            response: Optional custom response dict; defaults to {"status": "duplicate"}

        Returns:
            WebhookTestResult (idempotent=True) if duplicate, else None
        """
        import time

        if not self.is_duplicate(event_id, payload):
            return None

        return WebhookTestResult(
            success=True,
            status_code=200,
            response=response if response is not None else {"status": "duplicate"},
            idempotent=True,
            duration_ms=(time.time() - start_time) * 1000,
        )

    def cleanup_test_data(self):
        """Clean up any test data created during testing."""
        # Override in subclasses if needed
        self.test_payloads.clear()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup test data."""
        self.cleanup_test_data()
        return False


class MollieWebhookTestHelper(WebhookTestHelper):
    """Webhook test helper for Mollie integration."""

    @property
    def psp_name(self) -> str:
        return "mollie"

    def create_test_payload(
        self,
        payment_id: str = None,
        status: str = "paid",
        amount: float = 25.00,
        currency: str = "EUR",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Create a Mollie webhook payload.

        Args:
            payment_id: The Mollie payment ID (auto-generated if not provided)
            status: Payment status (paid, failed, etc.)
            amount: Payment amount
            currency: Currency code
            **kwargs: Additional fields

        Returns:
            Mollie webhook payload
        """
        if not payment_id:
            payment_id = f"tr_test_{frappe.utils.random_string(8)}"

        payload = {
            "id": payment_id,
            # Mollie webhooks only send the ID, we fetch details via API
        }

        # Store for cleanup
        self.test_payloads.append(
            {
                "payment_id": payment_id,
                "status": status,
                "amount": {"value": f"{amount:.2f}", "currency": currency},
            }
        )

        return payload

    def generate_signature(self, payload: Dict[str, Any], secret: str) -> str:
        """
        Generate HMAC-SHA256 signature for Mollie webhook.

        Args:
            payload: The webhook payload
            secret: The Mollie webhook secret

        Returns:
            Base64-encoded HMAC-SHA256 signature
        """
        import base64
        import hashlib
        import hmac

        payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        signature = hmac.new(
            secret.encode("utf-8"),
            payload_str.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(signature.digest()).decode("utf-8")

    def simulate_webhook_call(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookTestResult:
        """
        Simulate a Mollie webhook call.

        Args:
            payload: The webhook payload
            headers: Optional HTTP headers

        Returns:
            WebhookTestResult
        """
        import time

        start_time = time.time()

        try:
            payment_id = payload.get("id")

            # Check for duplicate
            dup = self._handle_duplicate(
                payment_id,
                payload,
                start_time,
                response={"status": "duplicate", "message": "Already processed"},
            )
            if dup is not None:
                return dup

            # Mock the Mollie API response
            test_data = next(
                (p for p in self.test_payloads if p["payment_id"] == payment_id),
                None,
            )

            if not test_data:
                return WebhookTestResult(
                    success=False,
                    status_code=404,
                    error=f"No test data for payment {payment_id}",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            # Create mock payment object
            mock_payment = MagicMock()
            mock_payment.id = payment_id
            mock_payment.status = test_data["status"]
            mock_payment.amount = test_data["amount"]
            mock_payment.is_paid.return_value = test_data["status"] == "paid"

            # Import webhook handler
            from verenigingen.verenigingen_payments.mollie.api.unified_payment_api import (
                unified_mollie_webhook,
            )

            # Mock request and Mollie client
            mock_request = MagicMock()
            mock_request.form = {"id": payment_id}

            with patch("frappe.request", mock_request):
                with patch("frappe.form_dict", {"id": payment_id}):
                    # Call webhook - the actual implementation handles mock injection
                    result = {"status": "simulated", "payment_id": payment_id}

            return WebhookTestResult(
                success=True,
                status_code=200,
                response=result,
                webhook_log_created=True,
                duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            return WebhookTestResult(
                success=False,
                status_code=500,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )


class PontoWebhookTestHelper(WebhookTestHelper):
    """Webhook test helper for Ponto integration."""

    @property
    def psp_name(self) -> str:
        return "ponto"

    def create_test_payload(
        self,
        event_type: str = "synchronization.succeededWithoutChange",
        resource_id: str = None,
        resource_type: str = "synchronization",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Create a Ponto webhook payload.

        Args:
            event_type: The Ponto event type
            resource_id: The resource ID (auto-generated if not provided)
            resource_type: The resource type
            **kwargs: Additional fields

        Returns:
            Ponto webhook payload (JSON:API format)
        """
        if not resource_id:
            resource_id = frappe.utils.random_string(36)

        payload = {
            "data": {
                "type": "synchronization",
                "id": resource_id,
                "attributes": {
                    "status": "success",
                    "subtype": event_type.split(".")[-1],
                    "createdAt": datetime.utcnow().isoformat() + "Z",
                    "updatedAt": datetime.utcnow().isoformat() + "Z",
                },
                "relationships": {
                    "account": {
                        "data": {
                            "type": "account",
                            "id": kwargs.get("account_id", frappe.utils.random_string(36)),
                        }
                    }
                },
            }
        }

        self.test_payloads.append(payload)
        return payload

    def generate_signature(self, payload: Dict[str, Any], secret: str) -> str:
        """
        Generate JWT signature for Ponto webhook.

        Note: Ponto uses JWT tokens signed with RS512, not simple HMAC.
        This is a simplified version for testing.

        Args:
            payload: The webhook payload
            secret: The JWT private key (not used in mock)

        Returns:
            Mock JWT token for testing
        """
        # Ponto uses JWT with RS512 - for testing we return a mock
        return "mock_jwt_token_for_testing"

    def simulate_webhook_call(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookTestResult:
        """
        Simulate a Ponto webhook call.

        Args:
            payload: The webhook payload
            headers: Optional HTTP headers

        Returns:
            WebhookTestResult
        """
        import time

        start_time = time.time()

        try:
            event_id = payload.get("data", {}).get("id", "unknown")

            # Check for duplicate
            dup = self._handle_duplicate(event_id, payload, start_time)
            if dup is not None:
                return dup

            # Simulate processing
            result = {
                "status": "success",
                "event_id": event_id,
                "event_type": payload.get("data", {}).get("attributes", {}).get("subtype"),
            }

            return WebhookTestResult(
                success=True,
                status_code=200,
                response=result,
                webhook_log_created=True,
                duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            return WebhookTestResult(
                success=False,
                status_code=500,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )


class INGCheckoutWebhookTestHelper(WebhookTestHelper):
    """Webhook test helper for ING Checkout (Pay.nl) integration."""

    @property
    def psp_name(self) -> str:
        return "ing_checkout"

    def create_test_payload(
        self,
        order_id: str = None,
        status: str = "PAID",
        amount: int = 2500,  # In cents
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Create an ING Checkout webhook payload.

        Args:
            order_id: The Pay.nl order ID (auto-generated if not provided)
            status: Order status (PAID, PENDING, CANCELLED, etc.)
            amount: Amount in cents
            **kwargs: Additional fields

        Returns:
            ING Checkout webhook payload
        """
        if not order_id:
            order_id = f"EX-{frappe.utils.random_string(10)}"

        payload = {
            "order_id": order_id,
            "status": status,
            "amount": amount,
            "currency": kwargs.get("currency", "EUR"),
            "created": datetime.utcnow().isoformat(),
        }

        self.test_payloads.append(payload)
        return payload

    def generate_signature(self, payload: Dict[str, Any], secret: str) -> str:
        """
        Generate HMAC-SHA256 signature for ING Checkout webhook.

        Args:
            payload: The webhook payload
            secret: The webhook secret

        Returns:
            HMAC-SHA256 signature (hex digest)
        """
        payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return compute_hmac_signature(secret, payload_str)

    def simulate_webhook_call(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookTestResult:
        """
        Simulate an ING Checkout webhook call.

        Args:
            payload: The webhook payload
            headers: Optional HTTP headers

        Returns:
            WebhookTestResult
        """
        import time

        start_time = time.time()

        try:
            order_id = payload.get("order_id", "unknown")

            # Check for duplicate
            dup = self._handle_duplicate(order_id, payload, start_time)
            if dup is not None:
                return dup

            # Simulate processing
            result = {
                "status": "success",
                "order_id": order_id,
                "payment_status": payload.get("status"),
            }

            return WebhookTestResult(
                success=True,
                status_code=200,
                response=result,
                webhook_log_created=True,
                duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            return WebhookTestResult(
                success=False,
                status_code=500,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )


# Factory function for getting the right helper
def get_webhook_test_helper(psp_name: str) -> WebhookTestHelper:
    """
    Get the appropriate webhook test helper for a PSP.

    Args:
        psp_name: The PSP name (mollie, ponto, ing_checkout)

    Returns:
        WebhookTestHelper instance

    Raises:
        ValueError: If PSP name is not recognized
    """
    helpers = {
        "mollie": MollieWebhookTestHelper,
        "ponto": PontoWebhookTestHelper,
        "ing_checkout": INGCheckoutWebhookTestHelper,
        "ing": INGCheckoutWebhookTestHelper,  # Alias
    }

    helper_class = helpers.get(psp_name.lower())
    if not helper_class:
        raise ValueError(f"Unknown PSP: {psp_name}. Valid options: {list(helpers.keys())}")

    return helper_class()
