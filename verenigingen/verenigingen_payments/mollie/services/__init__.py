"""Business logic services for Mollie integration."""

# Working services
try:
    from .complete_payment_service import CompletePaymentService
    from .payment_service import PaymentService
    from .webhook_wrapper_service_unified import UnifiedWebhookWrapperService
except ImportError:
    UnifiedWebhookWrapperService = None
    PaymentService = None
    CompletePaymentService = None

# Backward-compat alias: the class was renamed from WebhookWrapperServiceUnified
# to UnifiedWebhookWrapperService. The old name was imported here (and silently
# fell back to None on ImportError, which also nulled the other two services),
# so keep the alias for any external importer of the old name.
WebhookWrapperServiceUnified = UnifiedWebhookWrapperService

# Still broken services - to be fixed later
# from .subscription_service import SubscriptionService
# from .webhook_service import WebhookService
# from .reconciliation_service import ReconciliationService

__all__ = [
    "UnifiedWebhookWrapperService",
    "WebhookWrapperServiceUnified",
    "PaymentService",
    "CompletePaymentService",
]
