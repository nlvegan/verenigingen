"""
eBoekhouden Migration Configuration and Account Mapping Management

This module provides comprehensive configuration management for eBoekhouden to ERPNext
migration operations, with specific focus on payment account mapping and validation.
It handles the complex translation between Dutch accounting structures and ERPNext's
framework while maintaining compliance with Dutch accounting standards.

Key Features:
    * Payment account classification and mapping
    * Mode of Payment standardization for Dutch banking
    * Migration validation and readiness assessment
    * Fallback configuration for incomplete setups
    * Integration with custom DocTypes for flexible mapping

Business Context:
    Nederlandse Vereniging voor Veganisme operates with multiple banking relationships
    including Triodos Bank, ASN Bank, and PayPal. This configuration ensures proper
    classification of these accounts during migration while supporting SEPA direct
    debit operations for membership dues collection.

Configuration Structure:
    - Bank accounts: Triodos, ASN, PayPal with specific account numbers
    - Cash accounts: Physical cash handling for events and donations
    - Payment modes: Bank transfer, PayPal, Cash, SEPA Direct Debit
    - Validation rules: Ensuring migration readiness
"""

import json

import frappe

# Bank and cash account configurations for Nederlandse Vereniging voor Veganisme
# This configuration maps eBoekhouden account codes to ERPNext payment structure
PAYMENT_ACCOUNT_CONFIG = {
    "bank_accounts": {
        "10440": {
            "name": "Triodos - 19.83.96.716 - Algemeen",
            "type": "Bank",
            "mode_of_payment": "Bank Transfer",
        },
        "10470": {"name": "PayPal - info@veganisme.org", "type": "Bank", "mode_of_payment": "PayPal"},
        "10620": {"name": "ASN - 97.88.80.455", "type": "Bank", "mode_of_payment": "Bank Transfer"},
    },
    "cash_accounts": {"10000": {"name": "Kas", "type": "Cash", "mode_of_payment": "Cash"}},
}


def is_payment_account(account_code, company=None):
    """
    Determine if an eBoekhouden account code represents a payment account.

    This function provides intelligent classification of account codes to identify
    payment-related accounts (bank and cash accounts) during migration operations.
    It supports both database-driven mapping and fallback configuration.

    Args:
        account_code (str): eBoekhouden account code to classify
        company (str, optional): Company context for database lookup

    Returns:
        bool: True if account represents a payment account, False otherwise

    Note:
        Database mappings take precedence over hardcoded configuration
        to support flexible account structures across different entities.
    """
    if not account_code:
        return False

    # First check database mappings if company is provided
    if company:
        mapping = frappe.db.exists(
            "EBoekhouden Payment Mapping",
            {"company": company, "eboekhouden_account_code": account_code, "active": 1},
        )
        if mapping:
            return True

    # Fallback to hardcoded config
    return (
        account_code in PAYMENT_ACCOUNT_CONFIG["bank_accounts"]
        or account_code in PAYMENT_ACCOUNT_CONFIG["cash_accounts"]
    )


def get_payment_account_info(account_code, company=None):
    """
    Retrieve comprehensive payment account configuration data.

    Provides detailed information about payment accounts including name,
    type classification, mode of payment, and ERPNext account mapping.
    Supports both dynamic database configuration and static fallback.

    Args:
        account_code (str): eBoekhouden account code
        company (str, optional): Company context for database lookup

    Returns:
        dict: Payment account configuration containing:
            - name (str): Human-readable account name
            - type (str): Account type (Bank/Cash)
            - mode_of_payment (str): Associated payment mode
            - erpnext_account (str, optional): Mapped ERPNext account
        None: If account is not a payment account
    """
    # First check database mappings if company is provided
    if company:
        from verenigingen.verenigingen.doctype.eboekhouden_payment_mapping.eboekhouden_payment_mapping import (
            get_payment_account_mapping,
        )

        mapping = get_payment_account_mapping(company, account_code)
        if mapping:
            return {
                "name": mapping.get("account_name"),
                "type": mapping.get("account_type"),
                "mode_of_payment": mapping.get("mode_of_payment"),
                "erpnext_account": mapping.get("erpnext_account"),
            }

    # Fallback to hardcoded config
    if account_code in PAYMENT_ACCOUNT_CONFIG["bank_accounts"]:
        return PAYMENT_ACCOUNT_CONFIG["bank_accounts"][account_code]
    elif account_code in PAYMENT_ACCOUNT_CONFIG["cash_accounts"]:
        return PAYMENT_ACCOUNT_CONFIG["cash_accounts"][account_code]
    return None


@frappe.whitelist()
def setup_payment_modes():
    """
    Initialize required payment modes for Dutch banking integration.

    Creates standardized payment modes that align with Dutch banking
    practices and eBoekhouden integration requirements. This setup
    is essential for proper payment classification during migration.

    Payment Modes Created:
        - Bank Transfer: Standard IBAN-based transfers
        - PayPal: Online payment processing
        - Cash: Physical cash transactions
        - SEPA Direct Debit: Automated membership dues collection

    Returns:
        dict: Operation result containing:
            - success (bool): Overall operation success
            - created (list): Names of newly created payment modes
            - message (str): Human-readable summary

    Note:
        This function is exposed via Frappe's whitelist for use in
        setup wizards and administrative interfaces.
    """

    modes_to_create = [
        {"name": "Bank Transfer", "type": "Bank", "enabled": 1},
        {"name": "PayPal", "type": "Bank", "enabled": 1},
        {"name": "Cash", "type": "Cash", "enabled": 1},
        {"name": "SEPA Direct Debit", "type": "Bank", "enabled": 1},
    ]

    created = []
    for mode_config in modes_to_create:
        if not frappe.db.exists("Mode of Payment", mode_config["name"]):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = mode_config["name"]
            mode.type = mode_config["type"]
            mode.enabled = mode_config["enabled"]
            mode.insert(ignore_permissions=True)
            created.append(mode_config["name"])

    frappe.db.commit()

    return {"success": True, "created": created, "message": "Created {len(created)} modes of payment"}


@frappe.whitelist()
def validate_migration_setup():
    """
    Perform comprehensive validation of migration readiness.

    Conducts thorough checks of system configuration to ensure successful
    eBoekhouden migration. Validates account structures, payment modes,
    customer/supplier data, and integration settings.

    Validation Areas:
        - E-Boekhouden Settings configuration
        - Payment account existence in Chart of Accounts
        - Required payment modes availability
        - Customer and supplier data presence

    Returns:
        dict: Comprehensive validation report containing:
            - success (bool): Overall readiness status
            - issues (list): Critical problems preventing migration
            - warnings (list): Non-critical issues that may affect migration
            - summary (dict): Statistical overview of system state

    Note:
        Critical issues must be resolved before migration can proceed.
        Warnings indicate potential data quality issues but don't prevent migration.
    """

    issues = []
    warnings = []

    # Check if E-Boekhouden Settings exists
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.default_company:
            issues.append("No default company set in E-Boekhouden Settings")
    except Exception:
        issues.append("E-Boekhouden Settings not found")

    # Check if payment accounts exist in ERPNext
    for account_code, info in PAYMENT_ACCOUNT_CONFIG["bank_accounts"].items():
        if not frappe.db.exists("Account", {"account_number": account_code}):
            warnings.append(
                f"Bank account {account_code} ({info['name']}) not found in Chart of Accounts"  # noqa: E713
            )

    for account_code, info in PAYMENT_ACCOUNT_CONFIG["cash_accounts"].items():
        if not frappe.db.exists("Account", {"account_number": account_code}):
            warnings.append(
                f"Cash account {account_code} ({info['name']}) not found in Chart of Accounts"  # noqa: E713
            )

    # Check modes of payment
    required_modes = ["Bank Transfer", "PayPal", "Cash", "SEPA Direct Debit"]
    for mode in required_modes:
        if not frappe.db.exists("Mode of Payment", mode):
            warnings.append("Mode of Payment f'{mode}' not found")

    # Check if there are customers and suppliers
    customer_count = frappe.db.count("Customer")
    supplier_count = frappe.db.count("Supplier")

    if customer_count == 0:
        warnings.append("No customers found - customer payments won't be created")
    if supplier_count == 0:
        warnings.append("No suppliers found - supplier payments won't be created")

    return {
        "success": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "summary": {
            "customers": customer_count,
            "suppliers": supplier_count,
            "ready_for_migration": len(issues) == 0,
        },
    }
