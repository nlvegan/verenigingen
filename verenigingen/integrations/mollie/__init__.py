# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Backwards-compatibility shim for mollie integration.

The mollie integration has been moved to verenigingen_payments.mollie.
This module provides explicit re-exports for deterministic backwards compatibility.

DEPRECATED: Import from verenigingen.verenigingen_payments.mollie instead.

Migration Guide:
    OLD: from verenigingen.integrations.mollie.core.client import MollieClient
    NEW: from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
"""

import sys
import warnings

# Emit deprecation warning on module import
warnings.warn(
    "verenigingen.integrations.mollie is deprecated. "
    "Use verenigingen.verenigingen_payments.mollie instead.",
    DeprecationWarning,
    stacklevel=2,
)

# === Explicit Re-exports for Deterministic Backwards Compatibility ===
# These imports guarantee availability regardless of import order.

# Submodule imports (for `from verenigingen.integrations.mollie import api`)
from verenigingen.verenigingen_payments.mollie import api, core, exceptions, services, utils  # noqa: E402
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (  # noqa: E402
    create_payment_entry_for_donation,
    find_donation_for_payment_by_id,
)

# Webhook handlers
from verenigingen.verenigingen_payments.mollie.api.webhooks import handle_mollie_payment_webhook  # noqa: E402

# Core client classes
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient  # noqa: E402
from verenigingen.verenigingen_payments.mollie.core.mollie_exceptions import (  # noqa: E402
    MollieAPIError,
    MollieConfigurationError,
    MolliePaymentError,
    MollieWebhookError,
)

# Payment services
from verenigingen.verenigingen_payments.mollie.services.payment_service import (  # noqa: E402
    PaymentService as MolliePaymentService,
)
from verenigingen.verenigingen_payments.mollie.services.subscription_service import (  # noqa: E402
    SubscriptionService as MollieSubscriptionService,
)

# === sys.modules aliasing for deep import paths ===
# This handles: from verenigingen.integrations.mollie.services.handlers.refund_handler import ...
_old_base = "verenigingen.integrations.mollie"
_new_base = "verenigingen.verenigingen_payments.mollie"

for key in list(sys.modules.keys()):
    if key.startswith(_new_base):
        old_key = key.replace(_new_base, _old_base, 1)
        if old_key not in sys.modules:
            sys.modules[old_key] = sys.modules[key]

__all__ = [
    # Submodules
    "api",
    "core",
    "exceptions",
    "services",
    "utils",
    # Core classes
    "MollieClient",
    "MollieAPIError",
    "MollieConfigurationError",
    "MolliePaymentError",
    "MollieWebhookError",
    # Services
    "MolliePaymentService",
    "MollieSubscriptionService",
    # Webhook functions
    "handle_mollie_payment_webhook",
    "create_payment_entry_for_donation",
    "find_donation_for_payment_by_id",
]
