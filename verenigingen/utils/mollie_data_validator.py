"""
Compatibility Shim for Mollie Data Validator

This module provides backward compatibility for code that was importing
from the old path (verenigingen.utils.mollie_data_validator) by redirecting
to the new enhanced validation system at the correct location.
"""

# Redirect to the new validation system
from verenigingen.integrations.mollie.utils.data_validator import (
    MollieDataValidator,
    get_mollie_validator,
    validate_mollie_customer_data,
)

# Re-export everything for backward compatibility
# Also provide the old class name for compatibility
MollieValidator = MollieDataValidator

__all__ = ["get_mollie_validator", "validate_mollie_customer_data", "MollieDataValidator", "MollieValidator"]
