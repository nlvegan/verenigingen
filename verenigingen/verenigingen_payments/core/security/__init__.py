"""
Security Module for Mollie Backend Integration
Provides comprehensive security features for financial data protection

Note: the live Mollie webhook signature/validation path is in
``verenigingen_payments/utils/webhook_security.py`` (plus the API-refetch trust
model in ``webhook_wrapper_service_unified.py``); secret handling uses Frappe
``Password`` fields. The former ``EncryptionHandler`` / ``WebhookValidator``
helpers here were never wired into production and have been removed.
"""

from .mollie_security_manager import MollieSecurityManager, SecurityException

__all__ = [
    "MollieSecurityManager",
    "SecurityException",
]
