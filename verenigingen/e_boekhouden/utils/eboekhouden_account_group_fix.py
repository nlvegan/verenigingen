"""
DEPRECATED: This module is deprecated and maintained only for backward compatibility.

Please use the new service-oriented modules instead:
- verenigingen.e_boekhouden.services.account_organization_service
- verenigingen.e_boekhouden.services.account_diagnostics_service

This file will be removed in a future version.
"""

import frappe

from verenigingen.e_boekhouden.services.account_diagnostics_service import (
    AccountDiagnosticsService,
    check_tax_accounts as new_check_tax_accounts,
    diagnose_account_structure as new_diagnose_account_structure,
    find_misplaced_accounts as new_find_misplaced_accounts,
)
from verenigingen.e_boekhouden.services.account_organization_service import (
    AccountOrganizationService,
    organize_balance_sheet_accounts as new_organize_balance_sheet_accounts,
)
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


# Backward compatibility wrappers
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def fix_balance_sheet_account_parents():
    """
    DEPRECATED: Use AccountOrganizationService.organize_balance_sheet_accounts() instead.

    Maintained for backward compatibility only.
    """
    frappe.logger().warning(
        "fix_balance_sheet_account_parents() is deprecated. "
        "Use AccountOrganizationService.organize_balance_sheet_accounts() instead."
    )
    return new_organize_balance_sheet_accounts()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def diagnose_account_structure():
    """
    DEPRECATED: Use AccountDiagnosticsService.diagnose_account_structure() instead.

    Maintained for backward compatibility only.
    """
    frappe.logger().warning(
        "diagnose_account_structure() is deprecated. "
        "Use AccountDiagnosticsService.diagnose_account_structure() instead."
    )
    return new_diagnose_account_structure()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def check_tax_accounts():
    """
    DEPRECATED: Use AccountDiagnosticsService.check_tax_accounts() instead.

    Maintained for backward compatibility only.
    """
    frappe.logger().warning(
        "check_tax_accounts() is deprecated. " "Use AccountDiagnosticsService.check_tax_accounts() instead."
    )
    return new_check_tax_accounts()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def fix_tax_group_parents():
    """
    DEPRECATED: This function is no longer needed.
    Use AccountOrganizationService.organize_balance_sheet_accounts() instead,
    which handles tax groups automatically.

    Maintained for backward compatibility only.
    """
    frappe.logger().warning(
        "fix_tax_group_parents() is deprecated. "
        "Use AccountOrganizationService.organize_balance_sheet_accounts() instead."
    )
    return new_organize_balance_sheet_accounts()


# Legacy function stubs for old code that might still reference them
def analyze_account_hierarchy(accounts_data):
    """
    DEPRECATED: This function is no longer used.
    Account hierarchy analysis is now handled by AccountDiagnosticsService.
    """
    frappe.logger().warning(
        "analyze_account_hierarchy() is deprecated and no longer functional. "
        "Use AccountDiagnosticsService for account analysis."
    )
    return set()  # Return empty set for backward compatibility


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def fix_account_groups():
    """
    DEPRECATED: This function is no longer needed.
    Use AccountOrganizationService.organize_balance_sheet_accounts() instead.
    """
    frappe.logger().warning(
        "fix_account_groups() is deprecated. "
        "Use AccountOrganizationService.organize_balance_sheet_accounts() instead."
    )
    return {"success": False, "error": "This function is deprecated. Use AccountOrganizationService instead."}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def check_problem_accounts():
    """
    DEPRECATED: Use AccountDiagnosticsService.find_misplaced_accounts() instead.
    """
    frappe.logger().warning(
        "check_problem_accounts() is deprecated. "
        "Use AccountDiagnosticsService.find_misplaced_accounts() instead."
    )
    return new_find_misplaced_accounts()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def find_suitable_schulden_number():
    """
    DEPRECATED: This function is no longer needed.
    Account numbering is now handled automatically by AccountOrganizationService.
    """
    frappe.logger().warning("find_suitable_schulden_number() is deprecated and no longer needed.")
    return {
        "success": False,
        "error": "This function is deprecated. Account numbering is handled automatically.",
    }
