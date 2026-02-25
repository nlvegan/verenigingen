import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def analyze_eboekhouden_data():
    """
    Analyze E-Boekhouden data without making any system changes.

    Deprecated: The SOAP API modules this relied on have been removed.
    Use the migration document's analyze methods instead.
    """
    return {
        "success": False,
        "error": "This analysis function is deprecated. The SOAP API has been removed. "
        "Use the migration document's 'Analyze E-Boekhouden Data' button instead.",
    }
