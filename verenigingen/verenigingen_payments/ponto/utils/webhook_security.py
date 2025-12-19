# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Webhook Security

Handles JWT-based webhook signature verification for Ibanity/Ponto webhooks.
Ibanity uses RS512 JWT signatures with JWKS for key management.

The verification process:
1. Fetch signing keys from Ibanity's JWKS endpoint
2. Decode and verify the JWT signature header using RS512
3. Validate claims: audience, issuer, exp, iat
4. Verify payload digest matches SHA-512 hash of request body

Usage:
    from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
        verify_ponto_webhook,
    )

    try:
        claims = verify_ponto_webhook(
            payload=request.get_data(),
            signature=request.headers.get("Signature"),
            application_id="your-app-id",
        )
    except PontoWebhookError as e:
        # Handle verification failure
"""

import base64
import hashlib
import time
from typing import Any, Dict, Optional

import frappe
import jwt
import requests
from jwt import PyJWKClient

from verenigingen.verenigingen_payments.ponto.exceptions import PontoWebhookError

# Ibanity API endpoints
IBANITY_API_BASE = "https://api.ibanity.com"
IBANITY_PONTO_API_BASE = "https://api.myponto.com"

# JWKS endpoint - Ibanity publishes signing keys here
# Note: This may need adjustment based on actual Ibanity documentation
IBANITY_JWKS_URL = f"{IBANITY_API_BASE}/webhooks/keys"
IBANITY_PONTO_JWKS_URL = f"{IBANITY_PONTO_API_BASE}/webhooks/keys"

# Default tolerance for timestamp validation (seconds)
DEFAULT_TOLERANCE = 30

# Algorithm used by Ibanity for JWT signing
SIGNING_ALGORITHM = "RS512"


class PontoWebhookVerifier:
    """
    Verifies Ponto webhook signatures using JWT/JWKS.

    Ibanity uses RS512 JWT signatures with rotating keys managed via JWKS.
    This class handles key fetching, caching, and signature verification.
    """

    # Cache JWKS keys for 5 minutes
    JWKS_CACHE_KEY = "ponto_webhook_jwks"
    JWKS_CACHE_TTL = 300

    def __init__(
        self,
        application_id: str,
        issuer: str = None,
        tolerance: int = DEFAULT_TOLERANCE,
        jwks_url: str = None,
    ):
        """
        Initialize the webhook verifier.

        Args:
            application_id: Ponto application ID (used as JWT audience)
            issuer: Expected JWT issuer (defaults to Ponto API base URL)
            tolerance: Timestamp tolerance in seconds (default 30)
            jwks_url: JWKS endpoint URL (defaults to Ibanity endpoint)
        """
        self.application_id = application_id
        self.issuer = issuer or IBANITY_PONTO_API_BASE
        self.tolerance = tolerance
        self.jwks_url = jwks_url or IBANITY_PONTO_JWKS_URL
        self._jwks_client = None

    def _get_jwks_client(self) -> PyJWKClient:
        """
        Get or create the JWKS client with caching.

        Returns:
            PyJWKClient configured with the JWKS endpoint
        """
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.jwks_url, cache_keys=True)
        return self._jwks_client

    def _fetch_signing_key(self, token: str):
        """
        Fetch the signing key for a given JWT token.

        Args:
            token: JWT token string

        Returns:
            Signing key for verification

        Raises:
            PontoWebhookError: If key cannot be fetched
        """
        try:
            jwks_client = self._get_jwks_client()
            return jwks_client.get_signing_key_from_jwt(token)
        except jwt.exceptions.PyJWKClientError as e:
            frappe.logger().error(f"Failed to fetch JWKS signing key: {e}")
            raise PontoWebhookError(
                message="Failed to fetch webhook signing keys",
                details={"error": str(e), "jwks_url": self.jwks_url},
            )
        except Exception as e:
            frappe.logger().error(f"Unexpected error fetching JWKS key: {e}")
            raise PontoWebhookError(
                message="Unexpected error fetching webhook signing keys",
                details={"error": str(e)},
            )

    def _compute_payload_digest(self, payload: bytes) -> str:
        """
        Compute SHA-512 base64 digest of payload.

        Args:
            payload: Raw request body bytes

        Returns:
            Base64-encoded SHA-512 digest
        """
        digest = hashlib.sha512(payload).digest()
        return base64.b64encode(digest).decode("utf-8")

    def verify(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """
        Verify a Ponto webhook signature.

        Args:
            payload: Raw request body (bytes)
            signature: JWT signature from Signature header

        Returns:
            Dict with verified JWT claims

        Raises:
            PontoWebhookError: If verification fails
        """
        if not signature:
            raise PontoWebhookError(
                message="Missing webhook signature",
                details={"reason": "No Signature header provided"},
            )

        if not payload:
            raise PontoWebhookError(
                message="Empty webhook payload",
                details={"reason": "Request body is empty"},
            )

        try:
            # Fetch signing key from JWKS
            signing_key = self._fetch_signing_key(signature)

            # Decode and verify JWT
            claims = jwt.decode(
                signature,
                key=signing_key.key,
                algorithms=[SIGNING_ALGORITHM],
                audience=self.application_id,
                issuer=self.issuer,
                options={
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "require": ["exp", "iat", "aud", "iss", "digest"],
                },
                leeway=self.tolerance,
            )

            # Verify payload digest
            expected_digest = claims.get("digest")
            if expected_digest:
                actual_digest = self._compute_payload_digest(payload)
                if expected_digest != actual_digest:
                    raise PontoWebhookError(
                        message="Webhook payload digest mismatch",
                        details={
                            "reason": "The payload has been tampered with",
                            "expected_digest_prefix": expected_digest[:20] + "...",
                            "actual_digest_prefix": actual_digest[:20] + "...",
                        },
                    )

            # Validate issued-at within tolerance
            iat = claims.get("iat")
            if iat:
                now = time.time()
                if abs(now - iat) > self.tolerance:
                    raise PontoWebhookError(
                        message="Webhook timestamp out of tolerance",
                        details={
                            "reason": "iat claim is too old or in the future",
                            "iat": iat,
                            "now": now,
                            "tolerance": self.tolerance,
                        },
                    )

            frappe.logger().info(
                f"Ponto webhook signature verified successfully for audience {self.application_id}"
            )
            return claims

        except jwt.ExpiredSignatureError:
            raise PontoWebhookError(
                message="Webhook signature expired",
                details={"reason": "JWT exp claim indicates signature has expired"},
            )
        except jwt.InvalidAudienceError:
            raise PontoWebhookError(
                message="Invalid webhook audience",
                details={
                    "reason": "JWT aud claim does not match application ID",
                    "expected_audience": self.application_id,
                },
            )
        except jwt.InvalidIssuerError:
            raise PontoWebhookError(
                message="Invalid webhook issuer",
                details={
                    "reason": "JWT iss claim does not match expected issuer",
                    "expected_issuer": self.issuer,
                },
            )
        except jwt.InvalidAlgorithmError:
            raise PontoWebhookError(
                message="Invalid webhook signature algorithm",
                details={
                    "reason": f"Expected {SIGNING_ALGORITHM} algorithm",
                },
            )
        except jwt.DecodeError as e:
            raise PontoWebhookError(
                message="Failed to decode webhook signature",
                details={"reason": str(e)},
            )
        except PontoWebhookError:
            # Re-raise our own exceptions
            raise
        except Exception as e:
            frappe.logger().error(f"Unexpected webhook verification error: {e}")
            raise PontoWebhookError(
                message="Webhook verification failed",
                details={"error": str(e)},
            )


def verify_ponto_webhook(
    payload: bytes,
    signature: str,
    application_id: str = None,
    issuer: str = None,
    tolerance: int = DEFAULT_TOLERANCE,
) -> Dict[str, Any]:
    """
    Verify a Ponto webhook signature.

    Convenience function that creates a verifier and validates the webhook.

    Args:
        payload: Raw request body (bytes)
        signature: JWT signature from Signature header
        application_id: Ponto application ID (uses settings if not provided)
        issuer: Expected JWT issuer (defaults to Ponto API)
        tolerance: Timestamp tolerance in seconds

    Returns:
        Dict with verified JWT claims

    Raises:
        PontoWebhookError: If verification fails
    """
    # Get application ID from settings if not provided
    if not application_id:
        settings = frappe.get_single("Ponto Settings")
        # For Ponto Connect, the application ID is typically the client_id
        # or a separate application identifier
        application_id = settings.get_active_client_id()

    if not application_id:
        raise PontoWebhookError(
            message="Cannot verify webhook: no application ID configured",
            details={"reason": "Configure client_id in Ponto Settings"},
        )

    verifier = PontoWebhookVerifier(
        application_id=application_id,
        issuer=issuer,
        tolerance=tolerance,
    )

    return verifier.verify(payload, signature)


def get_webhook_verifier(
    application_id: str = None,
    issuer: str = None,
    tolerance: int = DEFAULT_TOLERANCE,
) -> PontoWebhookVerifier:
    """
    Factory function to get a configured webhook verifier.

    Args:
        application_id: Ponto application ID (uses settings if not provided)
        issuer: Expected JWT issuer
        tolerance: Timestamp tolerance in seconds

    Returns:
        Configured PontoWebhookVerifier instance
    """
    if not application_id:
        settings = frappe.get_single("Ponto Settings")
        application_id = settings.get_active_client_id()

    return PontoWebhookVerifier(
        application_id=application_id,
        issuer=issuer,
        tolerance=tolerance,
    )
