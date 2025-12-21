"""HTTP API endpoints for Mollie integration."""

# Note: These modules contain Frappe @whitelist endpoints
# Import them to register the routes
# Temporarily disabled problematic imports:
# from . import webhooks  # Has type hint issues
# from . import dashboard
# from . import sync

# Working imports:
try:
    from . import monitoring_api, payment_webhook, unified_payment_api
except ImportError:
    pass  # Gracefully handle missing dependencies

__all__ = ["webhooks", "dashboard", "sync"]
