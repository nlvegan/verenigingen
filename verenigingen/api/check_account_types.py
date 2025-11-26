"""
E-Boekhouden Account Type Analysis and Correction API
====================================================

Provides comprehensive analysis and automated correction capabilities for account
type mismatches that commonly occur during eBoekhouden to ERPNext migration.
This module addresses the critical need for accurate account type configuration
to ensure proper financial reporting and transaction processing.

Primary Purpose:
    Analyzes imported eBoekhouden accounts and identifies account type mismatches
    based on Dutch accounting standards and eBoekhouden account code patterns.
    Provides automated correction capabilities with detailed reasoning for each
    suggested change to maintain financial data integrity.

Key Features:
    * Intelligent account type analysis based on eBoekhouden account codes
    * Dutch accounting standard compliance verification
    * Automated account type correction with administrative oversight
    * Comprehensive issue reporting with detailed reasoning
    * Batch correction capabilities for efficient migration processing

Account Code Analysis Framework:
    Implements sophisticated pattern matching for Dutch chart of accounts:
    * 10xxx: Bank and Cash accounts (Asset classification)
    * 13xxx: Receivables and Current Assets
    * 02xxx: Fixed Assets and Capital Equipment
    * 44xxx: Payables and Current Liabilities
    * 5xxxx: Equity accounts
    * 8xxxx: Income and Revenue accounts
    * 6xxx/7xxx: Operating and Administrative Expenses
    * Tax-specific codes: BTW and fiscal obligation accounts

Business Impact:
    Proper account type configuration is essential for:
    * Accurate financial statement generation
    * Correct balance sheet and P&L classification
    * Proper cash flow statement preparation
    * Compliance with Dutch accounting regulations
    * Integration with ERPNext's financial workflow automation

Migration Context:
    Addresses common issues encountered during eBoekhouden migration where:
    * Account types may not transfer correctly
    * Dutch accounting patterns may not match ERPNext defaults
    * Manual review and correction becomes necessary for data integrity
    * Bulk corrections need administrative oversight and audit trails

Security and Compliance:
    Administrative functions require high-security access due to potential
    impact on financial reporting accuracy and regulatory compliance.
    All corrections are logged and reversible for audit requirements.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation

# Security framework imports
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def review_account_types(company) -> OperationResult[Dict[str, Any]]:
    """
    Comprehensive analysis of account types for eBoekhouden imported accounts.

    This function performs intelligent analysis of all accounts imported from eBoekhouden,
    identifying account type mismatches based on Dutch accounting standards and
    eBoekhouden account code patterns. It provides detailed suggestions for corrections
    with clear reasoning to help administrators maintain financial data integrity.

    Args:
        company (str): Company name to analyze accounts for. Required to scope
                      the analysis to specific company's chart of accounts.

    Analysis Process:
        1. Retrieves all accounts with eBoekhouden account numbers from the database
        2. Applies Dutch accounting code pattern analysis to each account
        3. Compares current account types with suggested types based on code patterns
        4. Identifies discrepancies and provides detailed correction recommendations
        5. Generates comprehensive report with actionable insights

    Account Code Pattern Analysis:
        Uses sophisticated pattern matching based on Dutch chart of accounts:
        * Bank/Cash accounts (10xxx): Proper Asset classification
        * Receivables (13xxx): Current Asset or Receivable types
        * Fixed Assets (02xxx): Fixed Asset classification
        * Payables (44xxx): Payable or Current Liability types
        * Equity (5xxxx): Equity classification
        * Income (8xxxx): Revenue classification
        * Expenses (6xxx/7xxx): Expense classification
        * Tax accounts (154x/157x): Tax-specific classifications

    Returns:
        OperationResult[Dict[str, Any]]: Comprehensive analysis results containing:
            - issues (list): Detailed list of account type mismatches including:
              * account: Account document name
              * account_name: Human-readable account name
              * account_code: eBoekhouden account code
              * current_type: Current account type in ERPNext
              * suggested_type: Recommended account type based on code analysis
              * current_root: Current root type (Asset/Liability/Income/Expense)
              * suggested_root: Recommended root type
              * reason: Detailed explanation for the suggestion
            - total_accounts: Total number of eBoekhouden accounts analyzed
            - issues_found: Number of account type mismatches identified

    Business Value:
        Ensures accurate financial reporting by identifying and suggesting corrections
        for account type mismatches that could lead to incorrect financial statements,
        balance sheet misclassifications, or compliance issues with Dutch accounting standards.

    Usage Context:
        Typically used during or after eBoekhouden migration to validate account
        configuration accuracy and ensure proper integration with ERPNext's
        financial reporting and workflow systems.

    Error Handling:
        Comprehensive error handling with detailed logging for troubleshooting
        database access issues or pattern matching problems during analysis.
    """
    try:
        # Get all accounts with E-Boekhouden numbers
        accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, root_type, account_number,
                   eboekhouden_grootboek_nummer, parent_account
            FROM `tabAccount`
            WHERE company = %s
            AND eboekhouden_grootboek_nummer IS NOT NULL
            AND eboekhouden_grootboek_nummer != ''
            ORDER BY account_number
        """,
            company,
            as_dict=True,
        )

        issues = []

        for account in accounts:
            account_code = account.get("eboekhouden_grootboek_nummer") or account.get("account_number", "")

            # Analyze account based on code patterns
            suggested_type, suggested_root = _analyze_account_code(account_code, account.account_name)

            if suggested_type and suggested_type != account.account_type:
                issues.append(
                    {
                        "account": account.name,
                        "account_name": account.account_name,
                        "account_code": account_code,
                        "current_type": account.account_type or "Not Set",
                        "suggested_type": suggested_type,
                        "current_root": account.root_type,
                        "suggested_root": suggested_root,
                        "reason": _get_suggestion_reason(account_code, suggested_type),
                    }
                )

        data = {
            "issues": issues,
            "total_accounts": len(accounts),
            "issues_found": len(issues),
        }

        return OperationResult.ok(
            data,
            message=_("Successfully analyzed {0} accounts and found {1} issues").format(
                len(accounts), len(issues)
            ),
        )

    except Exception as e:
        frappe.log_error(
            f"Error reviewing account types: {str(e)}\n{traceback.format_exc()}", "Account Type Review Error"
        )
        return OperationResult.fail(
            _("Failed to review account types"),
            errors=[str(e)],
            context={"operation": "review_account_types", "company": company},
        )


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def fix_account_type_issues(issues) -> OperationResult[Dict[str, Any]]:
    """
    Automated correction of multiple account type issues with administrative oversight.

    This high-security administrative function performs batch correction of account
    type mismatches identified by the review_account_types function. It applies
    the suggested corrections with proper validation, error handling, and audit
    trails to maintain financial data integrity.

    Args:
        issues (list or str): List of account type issues to fix, or JSON string
                             containing the issues. Each issue should contain:
                             - account: Account document name to update
                             - suggested_type: New account type to apply
                             - suggested_root: New root type to apply

    Security Requirements:
        Requires high-security API access due to potential impact on:
        * Financial reporting accuracy and compliance
        * Chart of accounts integrity and consistency
        * Historical transaction classification
        * Regulatory compliance with Dutch accounting standards

    Correction Process:
        1. Validates and parses the input issues list
        2. Iterates through each issue and loads the account document
        3. Applies the suggested account type and root type corrections
        4. Saves each account with proper validation
        5. Tracks successful corrections and any errors encountered
        6. Commits all changes as a single transaction

    Returns:
        OperationResult[Dict[str, Any]]: Batch correction results containing:
            - fixed_count (int): Number of accounts successfully corrected
            - errors (list): Detailed error messages for any failed corrections

    Error Handling:
        * Individual account correction failures don't stop the entire batch
        * Detailed error messages are collected for troubleshooting
        * Failed corrections are logged with specific account and error details
        * Successful corrections are committed even if some individual items fail

    Business Impact:
        Successful corrections ensure:
        * Accurate financial statement classification
        * Proper balance sheet and P&L presentation
        * Compliance with Dutch accounting regulations
        * Correct integration with ERPNext financial workflows
        * Improved data quality for reporting and analysis

    Audit Trail:
        All corrections are automatically logged through ERPNext's document
        history system, providing complete audit trails for regulatory
        compliance and change management purposes.

    Usage Context:
        Typically used after running review_account_types to apply the
        identified corrections in a controlled, auditable manner with
        appropriate administrative oversight and error handling.
    """
    try:
        if not issues:
            return OperationResult.ok({"fixed_count": 0, "errors": []}, message=_("No issues to fix"))

        # Parse issues if it's a string
        if isinstance(issues, str):
            import json

            issues = json.loads(issues)

        fixed_count = 0
        errors = []

        for issue in issues:
            try:
                # Update account type
                account = frappe.get_doc("Account", issue["account"])
                account.account_type = issue["suggested_type"]
                account.root_type = issue["suggested_root"]

                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="save",
                    doc=account,
                    justification=f"Fix account type for {issue['account_name']} from E-Boekhouden migration - financial account structure correction",
                    required_permissions=["Account:write"],
                )

                if result.success:
                    fixed_count += 1
                else:
                    errors.append(f"Failed to update {issue['account_name']}: {'; '.join(result.errors)}")

            except Exception as e:
                errors.append(f"Failed to update {issue['account_name']}: {str(e)}")

        frappe.db.commit()

        data = {"fixed_count": fixed_count, "errors": errors}

        if errors:
            return OperationResult.ok(
                data, message=_("Fixed {0} accounts with {1} errors").format(fixed_count, len(errors))
            )
        else:
            return OperationResult.ok(data, message=_("Successfully fixed {0} accounts").format(fixed_count))

    except Exception as e:
        frappe.log_error(
            f"Error fixing account type issues: {str(e)}\n{traceback.format_exc()}", "Account Type Fix Error"
        )
        return OperationResult.fail(
            _("Failed to fix account type issues"),
            errors=[str(e)],
            context={"operation": "fix_account_type_issues"},
        )


def _analyze_account_code(account_code, account_name):
    """
    Analyze eBoekhouden account code and suggest appropriate ERPNext account type.

    This function uses the AccountClassificationService to provide intelligent account
    type suggestions based on Dutch chart of accounts standards and eBoekhouden coding
    conventions. It leverages the centralized classification service which implements
    priority-based classification with settings integration.

    Args:
        account_code (str): eBoekhouden account code (grootboek nummer)
        account_name (str): Human-readable account name for context analysis

    Returns:
        tuple: (suggested_type, suggested_root) where:
            - suggested_type (str): Specific ERPNext account type or empty string
            - suggested_root (str): Root type (Asset/Liability/Equity/Income/Expense)
            - (None, None): If classification fails or no pattern match found

    Integration Note:
        Uses AccountClassificationService for consistent classification across all
        eBoekhouden migration and analysis functions. The service respects user
        configuration from E-Boekhouden Settings and implements the full priority
        hierarchy (group mappings, category codes, ranges, keywords, patterns).
    """
    if not account_code:
        return None, None

    try:
        from verenigingen.e_boekhouden.services.account_classification_service import (
            AccountClassificationService,
        )

        # Create minimal account data for classification
        # Note: We don't have category/group here, so service will use code patterns
        account_data = {
            "code": account_code,
            "description": account_name or "",
            "category": "",  # Not available in this context
            "group": "",  # Not available in this context
        }

        service = AccountClassificationService()
        result = service.classify_account(account_data)

        return result.account_type, result.root_type

    except Exception as e:
        frappe.logger().error(
            f"AccountClassificationService failed for {account_code}: {str(e)}. Using fallback."
        )

        # Fallback: Basic hardcoded patterns for critical cases
        if account_code.startswith("10"):
            if account_code == "10000" or "kas" in (account_name or "").lower():
                return "Cash", "Asset"
            return "Bank", "Asset"
        elif account_code.startswith("8"):
            return "", "Income"
        elif account_code.startswith(("6", "7")):
            return "", "Expense"
        elif account_code.startswith("5"):
            return "", "Equity"

        return None, None


def _get_suggestion_reason(account_code, suggested_type):
    """
    Generate human-readable explanation for account type suggestions.

    This function provides clear, business-friendly explanations for why
    specific account type changes are being suggested, helping administrators
    understand the reasoning behind each recommendation and make informed
    decisions about accepting or modifying the suggestions.

    Args:
        account_code (str): eBoekhouden account code that triggered the suggestion
        suggested_type (str): The suggested ERPNext account type

    Reasoning Categories:
        * Pattern-based reasons: Based on Dutch accounting code conventions
        * Contextual reasons: Based on account name analysis
        * Standard compliance: Based on Dutch accounting standards
        * ERPNext integration: Based on ERPNext workflow requirements

    Returns:
        str: Human-readable explanation for the suggestion, formatted for
             administrative review and decision-making. Includes specific
             reference to the account code pattern that triggered the suggestion.

    Business Value:
        Provides transparency in the suggestion process, enabling administrators
        to understand the logic behind recommendations and make informed decisions
        about accepting, modifying, or rejecting suggested account type changes
        based on their specific business context and accounting requirements.
    """
    if account_code.startswith("10"):
        if account_code == "10000":
            return "Cash account (account code 10000)"
        return "Bank account (account code starts with 10)"

    elif account_code.startswith("13"):
        return "Receivable/Current Asset (account code starts with 13)"

    elif account_code.startswith("02"):
        return "Fixed Asset (account code starts with 02)"

    elif account_code.startswith("14"):
        return "Current Asset (account code starts with 14)"

    elif account_code.startswith("44"):
        return "Payable/Current Liability (account code starts with 44)"

    elif account_code.startswith(("17", "18")):
        return "Current Liability (account code starts with 17/18)"

    elif account_code.startswith("5"):
        return "Equity (account code starts with 5)"

    elif account_code.startswith("8"):
        return "Income (account code starts with 8)"

    elif account_code.startswith(("6", "7")):
        return "Expense (account code starts with 6/7)"

    elif any(tax_prefix in account_code for tax_prefix in ["1540", "1570", "1571", "1572"]):
        return "Tax account (BTW-related account code)"

    return f"Based on account code pattern ({account_code})"
