# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Backwards-compatibility shim for integrations module.

The mollie integration has been moved to verenigingen_payments.mollie.
This module provides aliases for backwards compatibility.

DEPRECATED: Import from verenigingen.verenigingen_payments.mollie instead.
"""

import warnings

warnings.warn(
    "verenigingen.integrations is deprecated. " "Use verenigingen.verenigingen_payments instead.",
    DeprecationWarning,
    stacklevel=2,
)
