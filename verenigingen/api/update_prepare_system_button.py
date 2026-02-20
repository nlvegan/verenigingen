import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    standard_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def should_remove_prepare_system_button():
    """
    Analysis of whether the 'Prepare System' button should be removed
    """

    return {
        "recommendation": "Transform, don't remove",
        "reasons": [
            "SOAP API now handles all account/customer/supplier creation dynamically",
            "Account type fixing is now intelligent and based on actual usage patterns",
            "No need to pre-create cost centers or parties - they're created as needed",
            "System preparation steps are now integrated into the migration process itself",
        ],
        "useful_features_to_keep": [
            "Date range detection - helps users understand their data scope",
            "Connection testing - validates API credentials",
            "Data statistics - shows what will be imported",
        ],
        "suggested_changes": {
            "rename_to": "Analyze E-Boekhouden Data",
            "new_functionality": [
                "Show date range of available transactions",
                "Display count of mutations by type",
                "Preview account usage patterns",
                "Identify potential issues before migration",
            ],
            "remove": [
                "Cost center creation",
                "Party creation",
                "Account type adjustments",
                "Manual system preparation steps",
            ],
        },
    }


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
