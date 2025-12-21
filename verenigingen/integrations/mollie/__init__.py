# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Backwards-compatibility shim for mollie integration.

The mollie integration has been moved to verenigingen_payments.mollie.
This module re-exports all public APIs for backwards compatibility.

DEPRECATED: Import from verenigingen.verenigingen_payments.mollie instead.
"""

import sys

# Import the new module
from verenigingen.verenigingen_payments import mollie as _mollie

# Register submodules under old path for backwards compatibility
# This allows: from verenigingen.integrations.mollie.core.client import MollieClient
_old_base = "verenigingen.integrations.mollie"
_new_base = "verenigingen.verenigingen_payments.mollie"

# Copy all submodule registrations from new path to old path
for key in list(sys.modules.keys()):
    if key.startswith(_new_base):
        old_key = key.replace(_new_base, _old_base, 1)
        if old_key not in sys.modules:
            sys.modules[old_key] = sys.modules[key]

# Re-export submodules
from verenigingen.verenigingen_payments.mollie import api, core, exceptions, services, utils  # noqa: E402

__all__ = ["api", "core", "services", "utils", "exceptions"]
