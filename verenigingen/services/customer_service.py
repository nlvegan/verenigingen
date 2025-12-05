"""
Customer Service - Centralized customer creation and management.

DEPRECATED: This module is deprecated and will be removed in a future release.
Please use verenigingen.services.customer_handling_service.CustomerHandlingService instead.

Functions:
    - create_customer_for_member(): Create ERPNext Customer record for member
    - check_similar_customers(): Find existing customers with similar names
    - validate_customer_creation(): Pre-creation validation
"""

import logging
import warnings
from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.customer_handling_service import CustomerHandlingService

# Safe import of security framework with fallback
try:
    from verenigingen.utils.security.api_security_framework import OperationType, standard_api
except ImportError:
    # Fallback for environments where security framework is not available
    class OperationType:
        MEMBER_DATA = "member_data"

    def standard_api(operation_type=None):
        """Fallback decorator when security framework is not available"""

        def decorator(func):
            return func

        return decorator


logger = logging.getLogger(__name__)


def _get_service():
    """Helper to get the service instance."""
    return CustomerHandlingService()


@standard_api(operation_type=OperationType.MEMBER_DATA)
def create_customer_for_member(member_doc, suppress_messages=False) -> str:
    """Create a customer for this member in ERPNext.

    DEPRECATED: Use CustomerHandlingService().create_customer_for_member() instead.

    Args:
        member_doc: Member document instance
        suppress_messages (bool): Whether to suppress user messages

    Returns:
        str: Customer name (ID) of created customer
    """
    warnings.warn(
        "customer_service.create_customer_for_member is deprecated. Use CustomerHandlingService().create_customer_for_member instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_service().create_customer_for_member(member_doc, suppress_messages)


def check_similar_customers(full_name: str, limit: int = 10) -> List:
    """Check for existing customers with similar names.

    DEPRECATED: Use CustomerHandlingService().check_similar_customers() instead.
    """
    warnings.warn(
        "customer_service.check_similar_customers is deprecated. Use CustomerHandlingService().check_similar_customers instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_service().check_similar_customers(full_name, limit)


def find_exact_customer_match(full_name: str) -> Optional[Dict]:
    """Find customer with exact name match (case-insensitive).

    DEPRECATED: Use CustomerHandlingService().find_exact_customer_match() instead.
    """
    warnings.warn(
        "customer_service.find_exact_customer_match is deprecated. Use CustomerHandlingService().find_exact_customer_match instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_service().find_exact_customer_match(full_name)


def validate_customer_creation_requirements(member_doc) -> Dict:
    """Validate that member has required fields for customer creation.

    DEPRECATED: Use CustomerHandlingService().validate_customer_creation_requirements() instead.
    """
    warnings.warn(
        "customer_service.validate_customer_creation_requirements is deprecated. Use CustomerHandlingService().validate_customer_creation_requirements instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_service().validate_customer_creation_requirements(member_doc)


def update_member_customer_reference(member_doc, customer_name: str) -> bool:
    """Update member document with customer reference.

    DEPRECATED: Use CustomerHandlingService().update_member_customer_reference() instead.
    """
    warnings.warn(
        "customer_service.update_member_customer_reference is deprecated. Use CustomerHandlingService().update_member_customer_reference instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_service().update_member_customer_reference(member_doc, customer_name)
