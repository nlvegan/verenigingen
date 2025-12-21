"""
Mollie Integration Exceptions

DEPRECATED: This module is deprecated. Import exceptions from
verenigingen.verenigingen_payments.mollie.exceptions instead.

This module is kept for backward compatibility and will be removed in a future version.
"""

import warnings

# Re-export from canonical location for backward compatibility
from ..exceptions import (
    MollieAPIError,
    MollieConfigurationError,
    MollieIntegrationError,
    MollieSecurityError,
    MollieValidationError,
    MollieWebhookError,
)

__all__ = [
    "MollieIntegrationError",
    "MollieAPIError",
    "MollieConfigurationError",
    "MollieValidationError",
    "MollieWebhookError",
    "MollieSecurityError",
]


def __getattr__(name):
    """Emit deprecation warning when importing from this module."""
    if name in __all__:
        warnings.warn(
            f"Importing {name} from mollie_exceptions is deprecated. "
            "Use verenigingen.verenigingen_payments.mollie.exceptions instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
