"""
Shared response builders and HMAC helper for verenigingen_payments.

Pure-Python; no Frappe dependency — importable in any context.
"""

import hashlib
import hmac
from typing import Optional


class ResponseBuilder:
    """
    Factory for standardized response dicts.

    Key shapes are intentionally compatible with:
    - payment_services/constants.py STANDARD_ERROR_RESPONSE / STANDARD_SUCCESS_RESPONSE
    - refund_utility._create_error_response / _create_success_response

    webhook_error_handler adds correlation_id + timestamp on top; those fields
    remain that handler's responsibility (R6 will delegate the base dict here).
    """

    @staticmethod
    def error(
        message: str,
        *,
        status: str = "error",
        error_code: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> dict:
        """Return a standardized error response dict."""
        return {
            "status": status,
            "message": message,
            "error_code": error_code,
            "details": details,
        }

    @staticmethod
    def success(
        message: str = "",
        *,
        status: str = "success",
        data: Optional[dict] = None,
    ) -> dict:
        """Return a standardized success response dict."""
        return {
            "status": status,
            "message": message,
            "data": data,
        }


def compute_hmac_signature(secret: str, payload: str, *, algorithm: str = "sha256") -> str:
    """
    Return the hex HMAC of *payload* under *secret* using hashlib.<algorithm>.

    Replicates the pattern used in webhook_security.py and mollie/utils/security.py:
        hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    """
    hash_fn = getattr(hashlib, algorithm)
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hash_fn).hexdigest()
