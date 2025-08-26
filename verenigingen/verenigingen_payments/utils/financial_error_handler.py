"""
Financial Error Handling Framework for SEPA Processing

Provides specialized error handling, classification, and recovery mechanisms
for financial operations within the Verenigingen SEPA system.

Author: Verenigingen Development Team
Date: August 2025
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import frappe
from frappe import _


class FinancialErrorSeverity(Enum):
    """Financial error severity levels"""

    CRITICAL = "critical"  # System failure, financial data at risk
    COMPLIANCE = "compliance"  # SEPA/regulatory violation
    SECURITY = "security"  # Permission/access violation
    BUSINESS = "business"  # Business rule violation
    WARNING = "warning"  # Non-blocking issue
    INFO = "info"  # Informational message


class FinancialErrorCategory(Enum):
    """Categories of financial errors"""

    SEPA_VALIDATION = "sepa_validation"
    PERMISSION_VIOLATION = "permission_violation"
    DATA_INTEGRITY = "data_integrity"
    BANK_COMMUNICATION = "bank_communication"
    MANDATE_VIOLATION = "mandate_violation"
    CONFIGURATION_ERROR = "configuration_error"
    CALCULATION_ERROR = "calculation_error"
    BATCH_PROCESSING = "batch_processing"


@dataclass
class FinancialError:
    """Structured financial error information"""

    severity: FinancialErrorSeverity
    category: FinancialErrorCategory
    code: str
    message: str
    context: Dict[str, Any]
    suggested_action: str
    recoverable: bool = False
    user_message: Optional[str] = None


class FinancialErrorHandler:
    """Centralized financial error handling and classification"""

    ERROR_CODES = {
        # SEPA Compliance Errors (F1xxx)
        "F1001": {
            "message": "Invalid IBAN format for creditor account",
            "category": FinancialErrorCategory.SEPA_VALIDATION,
            "severity": FinancialErrorSeverity.COMPLIANCE,
            "action": "Configure valid IBAN in Verenigingen Settings",
        },
        "F1002": {
            "message": "Invalid BIC format or missing BIC",
            "category": FinancialErrorCategory.SEPA_VALIDATION,
            "severity": FinancialErrorSeverity.COMPLIANCE,
            "action": "Configure valid BIC in Verenigingen Settings",
        },
        "F1003": {
            "message": "Invalid Creditor ID (Incassant ID)",
            "category": FinancialErrorCategory.SEPA_VALIDATION,
            "severity": FinancialErrorSeverity.COMPLIANCE,
            "action": "Configure valid Dutch Creditor ID in format NL13ZZZ...",
        },
        "F1004": {
            "message": "SEPA XML validation failed against pain.008.001.08 schema",
            "category": FinancialErrorCategory.SEPA_VALIDATION,
            "severity": FinancialErrorSeverity.COMPLIANCE,
            "action": "Review XML structure and field formats",
        },
        # Permission Errors (F2xxx)
        "F2001": {
            "message": "Insufficient permissions to create Payment Entry",
            "category": FinancialErrorCategory.PERMISSION_VIOLATION,
            "severity": FinancialErrorSeverity.SECURITY,
            "action": "Grant Payment Entry create permissions to user role",
        },
        "F2002": {
            "message": "Insufficient permissions to submit SEPA batch",
            "category": FinancialErrorCategory.PERMISSION_VIOLATION,
            "severity": FinancialErrorSeverity.SECURITY,
            "action": "Grant Direct Debit Batch submit permissions to user role",
        },
        # Data Integrity Errors (F3xxx)
        "F3001": {
            "message": "Negative batch total amount calculated",
            "category": FinancialErrorCategory.DATA_INTEGRITY,
            "severity": FinancialErrorSeverity.CRITICAL,
            "action": "Review invoice amounts and calculations",
        },
        "F3002": {
            "message": "Batch total mismatch between SQL and Python calculation",
            "category": FinancialErrorCategory.DATA_INTEGRITY,
            "severity": FinancialErrorSeverity.CRITICAL,
            "action": "Check database integrity and recalculate manually",
        },
        # Mandate Errors (F4xxx)
        "F4001": {
            "message": "No active SEPA mandate found for member",
            "category": FinancialErrorCategory.MANDATE_VIOLATION,
            "severity": FinancialErrorSeverity.BUSINESS,
            "action": "Create or reactivate SEPA mandate for member",
        },
        "F4002": {
            "message": "Using RCUR sequence type without prior FRST usage",
            "category": FinancialErrorCategory.MANDATE_VIOLATION,
            "severity": FinancialErrorSeverity.COMPLIANCE,
            "action": "Use FRST for first collection on this mandate",
        },
        # Configuration Errors (F5xxx)
        "F5001": {
            "message": "Missing required SEPA configuration in Verenigingen Settings",
            "category": FinancialErrorCategory.CONFIGURATION_ERROR,
            "severity": FinancialErrorSeverity.CRITICAL,
            "action": "Complete SEPA configuration in Verenigingen Settings",
        },
        "F5002": {
            "message": "Bank-specific configuration not found for BIC",
            "category": FinancialErrorCategory.CONFIGURATION_ERROR,
            "severity": FinancialErrorSeverity.WARNING,
            "action": "Add bank-specific configuration or use defaults",
        },
    }

    def __init__(self):
        self.error_log = []

    def handle_error(
        self, error_code: str, context: Dict[str, Any] = None, user_facing: bool = True
    ) -> FinancialError:
        """
        Handle and classify a financial error

        Args:
            error_code: Predefined error code (F1001, F2001, etc.)
            context: Additional context information
            user_facing: Whether to show user-friendly message

        Returns:
            FinancialError object with full details
        """
        context = context or {}

        if error_code not in self.ERROR_CODES:
            # Unknown error - treat as critical
            return self._handle_unknown_error(error_code, context)

        error_def = self.ERROR_CODES[error_code]

        financial_error = FinancialError(
            severity=error_def["severity"],
            category=error_def["category"],
            code=error_code,
            message=error_def["message"],
            context=context,
            suggested_action=error_def["action"],
            recoverable=error_def.get("recoverable", False),
            user_message=self._generate_user_message(error_def, context) if user_facing else None,
        )

        # Log the error appropriately based on severity
        self._log_financial_error(financial_error)

        # Store for analysis
        self.error_log.append(financial_error)

        # Throw appropriate Frappe exception
        if user_facing:
            self._throw_user_exception(financial_error)

        return financial_error

    def _handle_unknown_error(self, error_code: str, context: Dict[str, Any]) -> FinancialError:
        """Handle unknown/unclassified errors"""
        financial_error = FinancialError(
            severity=FinancialErrorSeverity.CRITICAL,
            category=FinancialErrorCategory.BATCH_PROCESSING,
            code=error_code,
            message=f"Unknown financial error: {error_code}",
            context=context,
            suggested_action="Contact system administrator",
            recoverable=False,
            user_message="An unexpected financial processing error occurred",
        )

        self._log_financial_error(financial_error)
        return financial_error

    def _generate_user_message(self, error_def: Dict[str, Any], context: Dict[str, Any]) -> str:
        """Generate user-friendly error message"""
        base_message = error_def["message"]

        # Add context if available
        if context.get("member_name"):
            base_message += f" (Member: {context['member_name']})"
        if context.get("batch_name"):
            base_message += f" (Batch: {context['batch_name']})"
        if context.get("invoice_name"):
            base_message += f" (Invoice: {context['invoice_name']})"

        return base_message

    def _log_financial_error(self, error: FinancialError):
        """Log financial error with appropriate severity"""
        log_title = f"Financial Error {error.code}"
        log_message = f"{error.message}\nContext: {error.context}\nSuggested Action: {error.suggested_action}"

        if error.severity == FinancialErrorSeverity.CRITICAL:
            frappe.log_error(log_message, f"CRITICAL - {log_title}")
        elif error.severity == FinancialErrorSeverity.COMPLIANCE:
            frappe.log_error(log_message, f"COMPLIANCE - {log_title}")
        elif error.severity == FinancialErrorSeverity.SECURITY:
            frappe.log_error(log_message, f"SECURITY - {log_title}")
        else:
            frappe.logger().warning(f"{log_title}: {log_message}")

    def _throw_user_exception(self, error: FinancialError):
        """Throw appropriate user-facing exception"""
        if error.severity == FinancialErrorSeverity.CRITICAL:
            frappe.throw(_(error.user_message or error.message), frappe.ValidationError)
        elif error.severity == FinancialErrorSeverity.COMPLIANCE:
            frappe.throw(
                _(f"SEPA Compliance Error: {error.user_message or error.message}"), frappe.ValidationError
            )
        elif error.severity == FinancialErrorSeverity.SECURITY:
            frappe.throw(_(f"Security Error: {error.user_message or error.message}"), frappe.PermissionError)
        elif error.severity == FinancialErrorSeverity.BUSINESS:
            frappe.throw(
                _(f"Business Rule Error: {error.user_message or error.message}"), frappe.ValidationError
            )

    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of all errors encountered"""
        summary = {
            "total_errors": len(self.error_log),
            "by_severity": {},
            "by_category": {},
            "critical_errors": [],
        }

        for error in self.error_log:
            # Count by severity
            severity_key = error.severity.value
            summary["by_severity"][severity_key] = summary["by_severity"].get(severity_key, 0) + 1

            # Count by category
            category_key = error.category.value
            summary["by_category"][category_key] = summary["by_category"].get(category_key, 0) + 1

            # Track critical errors
            if error.severity == FinancialErrorSeverity.CRITICAL:
                summary["critical_errors"].append(
                    {"code": error.code, "message": error.message, "context": error.context}
                )

        return summary


# Singleton instance for global use
_financial_error_handler = None


def get_financial_error_handler() -> FinancialErrorHandler:
    """Get the global financial error handler instance"""
    global _financial_error_handler
    if _financial_error_handler is None:
        _financial_error_handler = FinancialErrorHandler()
    return _financial_error_handler


# Convenience functions for common error scenarios
def handle_sepa_validation_error(error_code: str, context: Dict[str, Any] = None):
    """Handle SEPA validation errors"""
    return get_financial_error_handler().handle_error(error_code, context)


def handle_permission_error(error_code: str, context: Dict[str, Any] = None):
    """Handle permission-related errors"""
    return get_financial_error_handler().handle_error(error_code, context)


def handle_data_integrity_error(error_code: str, context: Dict[str, Any] = None):
    """Handle data integrity errors"""
    return get_financial_error_handler().handle_error(error_code, context)


@frappe.whitelist()
def get_financial_error_statistics():
    """API endpoint to get financial error statistics"""
    handler = get_financial_error_handler()
    return {"success": True, "statistics": handler.get_error_summary()}
