"""
Mollie Payment Integration v2.0

Complete service-oriented architecture for Mollie payment processing with:
- Payment processing (donations, membership dues, events)
- Subscription management
- Webhook handling with idempotency protection
- Financial reconciliation
- Comprehensive logging and monitoring
- Health checks and performance tracking

Architecture:
- core/: API client and core data models
- services/: Business logic service layer with clean interfaces
- utils/: Utilities, validators, logging, and monitoring
- api/: Secured HTTP endpoints with proper decorators
- tests/: Comprehensive test suites
- exceptions/: Custom exception hierarchy

Service Layer:
- UnifiedWebhookWrapperService: Unified webhook processing with idempotency protection
- PaymentService: Core payment operations (basic structure)
- CompletePaymentService: Full payment workflow management
- MollieClient: Simplified API client for essential operations

Key Features:
- Gradual migration path from monolithic to service architecture
- Comprehensive structured logging with security filtering
- Performance monitoring and health checks
- Idempotency protection for webhook processing
- Security framework integration with proper operation types
- Backward compatibility maintained during refactoring
"""

# Import key classes for easy access
# Note: Some services temporarily disabled due to missing dependencies
# from .core.mollie_client import MollieClient
# from .core.mollie_exceptions import MollieIntegrationError, MollieAPIError
# from .services.payment_service import PaymentService
# from .services.subscription_service import SubscriptionService
# from .services.webhook_service import WebhookService

# Working services
try:
    from .services.payment_service import PaymentService
    from .services.webhook_wrapper_service_unified import UnifiedWebhookWrapperService
except ImportError:
    UnifiedWebhookWrapperService = None
    PaymentService = None

# Backward-compat alias: the class was renamed from WebhookWrapperServiceUnified.
WebhookWrapperServiceUnified = UnifiedWebhookWrapperService

__version__ = "2.0.0"
__all__ = [
    "UnifiedWebhookWrapperService",  # Unified webhook processing
    "WebhookWrapperServiceUnified",  # Backward-compat alias
    "PaymentService",  # Basic structure, needs completion
    # Still need to implement:
    # "MollieClient",
    # "MollieIntegrationError",
    # "MollieAPIError",
    # "SubscriptionService",
    # "WebhookService",
]
