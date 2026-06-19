"""
Refund Utility Module

Provides utility functions for processing refunds and chargebacks that can be called
from donation forms, payment entry forms, and member portal pages.
"""

import math
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from verenigingen.utils.constants import Roles
from verenigingen.utils.payment_services.constants import (
    LOG_CATEGORY_REFUND,
    LOG_CATEGORY_VALIDATION,
    MAX_REFUND_DESCRIPTION_LENGTH,
    MIN_REFUND_AMOUNT,
    REFUND_QUERY_BATCH_SIZE,
    STANDARD_ERROR_RESPONSE,
    STANDARD_SUCCESS_RESPONSE,
    is_valid_mollie_payment_id,
)
from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import (
    log_concurrent_refund_detected,
    log_refund_initiated,
)

# Known reversal types for null safety
KNOWN_REVERSAL_TYPES = ("Refund", "Chargeback")


def _validate_custom_fields_exist() -> Optional[Dict[str, Any]]:
    """
    Validate that required custom fields exist on Payment Entry.
    Returns error response if validation fails, None if valid.
    """
    try:
        meta = frappe.get_meta("Payment Entry")
        required_fields = ["custom_original_payment_id", "custom_reversal_type", "custom_donation"]
        missing_fields = [f for f in required_fields if not meta.has_field(f)]

        if missing_fields:
            frappe.log_error(
                f"Missing custom fields on Payment Entry: {missing_fields}",
                LOG_CATEGORY_VALIDATION,
            )
            return _create_error_response(
                "System configuration error - missing custom fields",
                error_code="MISSING_CUSTOM_FIELDS",
                details={"missing_fields": missing_fields},
            )
        return None
    except Exception as e:
        frappe.log_error(f"Error validating custom fields: {e}", LOG_CATEGORY_VALIDATION)
        return _create_error_response("System configuration error", error_code="FIELD_VALIDATION_ERROR")


def _validate_float_amount(amount: float) -> Optional[Dict[str, Any]]:
    """
    Validate that amount is a valid finite number.
    Returns error response if invalid, None if valid.
    """
    if amount is None:
        return None

    try:
        float_val = float(amount)
        if math.isnan(float_val) or math.isinf(float_val):
            return _create_error_response("Invalid amount value", error_code="INVALID_AMOUNT_VALUE")
        return None
    except (TypeError, ValueError):
        return _create_error_response("Amount must be a valid number", error_code="INVALID_AMOUNT_TYPE")


def _create_error_response(
    message: str, error_code: Optional[str] = None, details: Optional[Any] = None
) -> Dict[str, Any]:
    """Create standardized error response."""
    response = STANDARD_ERROR_RESPONSE.copy()
    response.update(
        {
            "message": message,
            "error_code": error_code,
            "details": details,
            "timestamp": now_datetime().isoformat(),
        }
    )
    return response


def _create_success_response(message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    """Create standardized success response."""
    response = STANDARD_SUCCESS_RESPONSE.copy()
    response.update({"message": message, "data": data, "timestamp": now_datetime().isoformat()})
    return response


def _validate_mollie_payment_id(payment_id: str) -> bool:
    """
    Validate Mollie payment ID format.

    Note: This is a local wrapper for backward compatibility.
    Use is_valid_mollie_payment_id from constants module for new code.
    """
    return is_valid_mollie_payment_id(payment_id)


def _validate_refund_amount(amount: float, max_amount: float) -> Optional[Dict[str, Any]]:
    """Validate refund amount against business rules."""
    if amount < MIN_REFUND_AMOUNT:
        return _create_error_response(
            f"Refund amount must be at least {MIN_REFUND_AMOUNT}", error_code="INVALID_AMOUNT"
        )

    if amount > max_amount:
        return _create_error_response(
            f"Refund amount cannot exceed payment amount of {max_amount}", error_code="AMOUNT_EXCEEDS_PAYMENT"
        )

    return None


def _validate_refund_reason(reason: Optional[str]) -> Optional[Dict[str, Any]]:
    """Validate refund reason/description."""
    if reason and len(reason) > MAX_REFUND_DESCRIPTION_LENGTH:
        return _create_error_response(
            f"Refund description cannot exceed {MAX_REFUND_DESCRIPTION_LENGTH} characters",
            error_code="DESCRIPTION_TOO_LONG",
        )

    return None


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def initiate_refund(
    payment_entry_name: str, amount: Optional[float] = None, reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Initiate a refund for a Payment Entry (callable from UI).

    Args:
        payment_entry_name: Name of the Payment Entry to refund
        amount: Optional partial refund amount (defaults to full payment amount)
        reason: Optional refund reason description

    Returns:
        Dict with refund status and details
    """
    try:
        # Input validation
        if not payment_entry_name:
            return _create_error_response("Payment Entry name is required", "MISSING_PAYMENT_ENTRY")

        # Validate custom fields exist before proceeding
        field_validation = _validate_custom_fields_exist()
        if field_validation:
            return field_validation

        # Validate amount is a valid float (not NaN/Infinity)
        float_validation = _validate_float_amount(amount)
        if float_validation:
            return float_validation

        # Validate refund reason
        reason_validation = _validate_refund_reason(reason)
        if reason_validation:
            return reason_validation

        # Get the Payment Entry document
        try:
            payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
        except frappe.DoesNotExistError:
            return _create_error_response("Payment Entry not found", "PAYMENT_ENTRY_NOT_FOUND")

        # Validate this is a payment we can refund
        if payment_entry.payment_type != "Receive":
            return _create_error_response("Can only refund received payments", "INVALID_PAYMENT_TYPE")

        # Check if payment was made via Mollie using standardized validation
        mollie_payment_id = payment_entry.reference_no
        if not _validate_mollie_payment_id(mollie_payment_id):
            return _create_error_response("Payment was not processed via Mollie", "NOT_MOLLIE_PAYMENT")

        # Validate and set refund amount
        max_refund_amount = payment_entry.paid_amount
        if amount is not None:
            amount_validation = _validate_refund_amount(amount, max_refund_amount)
            if amount_validation:
                return amount_validation
        else:
            amount = max_refund_amount

        # Use row-level locking to prevent race conditions in concurrent refunds
        # Lock the original payment entry while we check and process
        frappe.db.sql(
            """SELECT name FROM `tabPayment Entry` WHERE name = %s FOR UPDATE""",
            (payment_entry_name,),
        )

        # Check for existing refunds AND chargebacks to prevent over-refunding
        existing_reversals = frappe.db.sql(
            """
            SELECT
                COALESCE(SUM(paid_amount), 0) as total_reversed,
                COUNT(*) as reversal_count
            FROM `tabPayment Entry`
            WHERE payment_type = 'Pay'
                AND custom_original_payment_id = %s
                AND custom_reversal_type IN ('Refund', 'Chargeback')
                AND docstatus = 1
        """,
            (mollie_payment_id,),
            as_dict=True,
        )

        reversal_data = (
            existing_reversals[0] if existing_reversals else {"total_reversed": 0, "reversal_count": 0}
        )
        total_reversed = flt(reversal_data["total_reversed"])
        available_amount = max_refund_amount - total_reversed

        if amount > available_amount:
            log_concurrent_refund_detected(
                payment_id=mollie_payment_id,
                attempted_amount=amount,
                available_amount=available_amount,
            )
            return _create_error_response(
                f"Only {available_amount} available for refund (already reversed: {total_reversed})",
                error_code="INSUFFICIENT_REFUNDABLE_AMOUNT",
                details={
                    "available_amount": available_amount,
                    "total_reversed": total_reversed,
                    "reversal_count": reversal_data["reversal_count"],
                },
            )

        # Initialize Mollie service and create refund
        mollie_service = MolliePaymentService()
        refund_result = mollie_service.create_refund(
            payment_id=mollie_payment_id,
            amount=amount,
            description=reason or f"Refund for payment {payment_entry_name}",
        )

        if refund_result["status"] == "success":
            log_refund_initiated(
                payment_id=mollie_payment_id,
                refund_id=refund_result["refund_id"],
                amount=refund_result["amount"],
                reason=reason or f"Refund for payment {payment_entry_name}",
            )
            # Return success - webhook will handle creating reverse Payment Entry
            return _create_success_response(
                "Refund initiated successfully",
                data={
                    "refund_id": refund_result["refund_id"],
                    "amount": refund_result["amount"],
                    "payment_entry": payment_entry_name,
                    "info": "The refund will be processed automatically when confirmed by Mollie",
                },
            )
        else:
            return refund_result

    except frappe.DoesNotExistError:
        # Document not found - user-facing error
        frappe.log_error(f"Payment Entry not found for refund: {payment_entry_name}", LOG_CATEGORY_REFUND)
        return _create_error_response("Payment Entry not found", error_code="PAYMENT_ENTRY_NOT_FOUND")

    except frappe.PermissionError as e:
        # Permission denied - user-facing error
        frappe.log_error(
            f"Permission denied for refund on {payment_entry_name}: {str(e)}", LOG_CATEGORY_REFUND
        )
        return _create_error_response(
            "You do not have permission to process refunds", error_code="PERMISSION_DENIED"
        )

    except frappe.ValidationError as e:
        # Validation error - user-facing with details
        frappe.log_error(
            f"Validation error for refund on {payment_entry_name}: {str(e)}", LOG_CATEGORY_REFUND
        )
        return _create_error_response(f"Validation error: {str(e)}", error_code="VALIDATION_ERROR")

    except Exception as e:
        # Generic error - log full details but return generic message
        frappe.log_error(
            f"Error initiating refund for payment {payment_entry_name}: {str(e)}", LOG_CATEGORY_REFUND
        )
        return _create_error_response(
            "Failed to initiate refund - please try again", error_code="REFUND_INITIATION_FAILED"
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_payment_refund_info(payment_entry_name: str) -> Dict[str, Any]:
    """
    Get refund information for a Payment Entry.

    Args:
        payment_entry_name: Name of the Payment Entry

    Returns:
        Dict with refund status and history
    """
    try:
        # Get the Payment Entry document
        try:
            payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
        except frappe.DoesNotExistError:
            return _create_error_response("Payment Entry not found", "PAYMENT_ENTRY_NOT_FOUND")

        mollie_payment_id = payment_entry.reference_no
        if not is_valid_mollie_payment_id(mollie_payment_id):
            return _create_error_response("Payment was not processed via Mollie", "NOT_MOLLIE_PAYMENT")

        # Get existing refunds and chargebacks
        reversals = frappe.db.sql(
            """
            SELECT name, paid_amount, reference_no, reference_date, remarks, docstatus, custom_reversal_type
            FROM `tabPayment Entry`
            WHERE payment_type = 'Pay'
            AND custom_original_payment_id = %s
            AND custom_reversal_type IN ('Refund', 'Chargeback')
            ORDER BY creation DESC
        """,
            (mollie_payment_id,),
            as_dict=True,
        )

        # Separate refunds and chargebacks for reporting with null safety
        # Only include entries with known reversal types
        refunds = [r for r in reversals if r.get("custom_reversal_type") == "Refund"]
        chargebacks = [r for r in reversals if r.get("custom_reversal_type") == "Chargeback"]
        # Log any unknown reversal types for debugging
        unknown_types = [r for r in reversals if r.get("custom_reversal_type") not in KNOWN_REVERSAL_TYPES]
        if unknown_types:
            frappe.log_error(
                f"Unknown reversal types found for {mollie_payment_id}: "
                f"{[r.get('custom_reversal_type') for r in unknown_types]}",
                LOG_CATEGORY_VALIDATION,
            )

        total_refunded = sum(flt(r.paid_amount) for r in refunds if r.docstatus == 1)
        total_chargebacks = sum(flt(r.paid_amount) for r in chargebacks if r.docstatus == 1)
        available_amount = payment_entry.paid_amount - total_refunded - total_chargebacks

        return _create_success_response(
            "Payment refund information retrieved successfully",
            data={
                "can_refund": available_amount > 0,
                "original_amount": payment_entry.paid_amount,
                "total_refunded": total_refunded,
                "total_chargebacks": total_chargebacks,
                "available_amount": available_amount,
                "refund_history": refunds,
                "chargeback_history": chargebacks,
                "mollie_payment_id": mollie_payment_id,
            },
        )

    except frappe.DoesNotExistError:
        return _create_error_response("Payment Entry not found", error_code="PAYMENT_ENTRY_NOT_FOUND")

    except frappe.PermissionError:
        frappe.log_error(f"Permission denied for refund info on {payment_entry_name}", LOG_CATEGORY_REFUND)
        return _create_error_response(
            "You do not have permission to view refund information", error_code="PERMISSION_DENIED"
        )

    except Exception as e:
        frappe.log_error(
            f"Error getting refund info for payment {payment_entry_name}: {str(e)}", LOG_CATEGORY_REFUND
        )
        return _create_error_response("Failed to get refund information", error_code="REFUND_INFO_FAILED")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_donation_refund_info(donation_name: str) -> Dict[str, Any]:
    """
    Get refund information for a Donation.

    Args:
        donation_name: Name of the Donation

    Returns:
        Dict with refund status and payment history
    """
    try:
        # Get the Donation document
        try:
            donation_doc = frappe.get_doc("Donation", donation_name)
        except frappe.DoesNotExistError:
            return _create_error_response("Donation not found", "DONATION_NOT_FOUND")

        # Get associated payment entries
        payment_entries = frappe.db.sql(
            """
            SELECT name, payment_type, paid_amount, reference_no, custom_reversal_type, docstatus
            FROM `tabPayment Entry`
            WHERE custom_donation = %s
            ORDER BY creation ASC
        """,
            (donation_name,),
            as_dict=True,
        )

        if not payment_entries:
            return _create_error_response("No payment entries found for this donation", "NO_PAYMENT_ENTRIES")

        # Separate original payments from refunds/chargebacks with null safety
        original_payments = [pe for pe in payment_entries if pe.payment_type == "Receive"]
        refunds = [
            pe
            for pe in payment_entries
            if pe.payment_type == "Pay" and pe.get("custom_reversal_type") == "Refund"
        ]
        chargebacks = [
            pe
            for pe in payment_entries
            if pe.payment_type == "Pay" and pe.get("custom_reversal_type") == "Chargeback"
        ]
        # Log any unknown reversal types for debugging
        unknown_reversals = [
            pe
            for pe in payment_entries
            if pe.payment_type == "Pay" and pe.get("custom_reversal_type") not in KNOWN_REVERSAL_TYPES
        ]
        if unknown_reversals:
            frappe.log_error(
                f"Unknown reversal types found for donation {donation_name}: "
                f"{[pe.get('custom_reversal_type') for pe in unknown_reversals]}",
                LOG_CATEGORY_VALIDATION,
            )

        # Calculate totals
        total_paid = sum(flt(pe.paid_amount) for pe in original_payments if pe.docstatus == 1)
        total_refunded = sum(flt(pe.paid_amount) for pe in refunds if pe.docstatus == 1)
        total_chargebacks = sum(flt(pe.paid_amount) for pe in chargebacks if pe.docstatus == 1)

        net_amount = total_paid - total_refunded - total_chargebacks

        # Check if any original payments can be refunded
        can_refund = any(
            is_valid_mollie_payment_id(pe.reference_no) for pe in original_payments if pe.docstatus == 1
        )

        return _create_success_response(
            "Donation refund information retrieved successfully",
            data={
                "can_refund": can_refund and net_amount > 0,
                "total_paid": total_paid,
                "total_refunded": total_refunded,
                "total_chargebacks": total_chargebacks,
                "net_amount": net_amount,
                "original_payments": original_payments,
                "refunds": refunds,
                "chargebacks": chargebacks,
                "payment_history": donation_doc.get("payment_history", []),
            },
        )

    except frappe.DoesNotExistError:
        return _create_error_response("Donation not found", error_code="DONATION_NOT_FOUND")

    except frappe.PermissionError:
        frappe.log_error(
            f"Permission denied for donation refund info on {donation_name}", LOG_CATEGORY_REFUND
        )
        return _create_error_response(
            "You do not have permission to view donation refund information",
            error_code="PERMISSION_DENIED",
        )

    except Exception as e:
        frappe.log_error(
            f"Error getting donation refund info for {donation_name}: {str(e)}", LOG_CATEGORY_REFUND
        )
        return _create_error_response(
            "Failed to get donation refund information", error_code="DONATION_REFUND_INFO_FAILED"
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def initiate_donation_refund(
    donation_name: str, amount: Optional[float] = None, reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Initiate a refund for a Donation (callable from UI).

    Args:
        donation_name: Name of the Donation to refund
        amount: Optional partial refund amount
        reason: Optional refund reason description

    Returns:
        Dict with refund status and details
    """
    try:
        # Validate custom fields exist before proceeding
        field_validation = _validate_custom_fields_exist()
        if field_validation:
            return field_validation

        # Validate amount is a valid float (not NaN/Infinity)
        float_validation = _validate_float_amount(amount)
        if float_validation:
            return float_validation

        # Get donation refund info first
        refund_info = get_donation_refund_info(donation_name)

        if refund_info["status"] != "success":
            return refund_info

        if not refund_info["data"]["can_refund"]:
            return _create_error_response("This donation cannot be refunded", "DONATION_NOT_REFUNDABLE")

        # Find the best payment entry to refund from
        original_payments = refund_info["data"]["original_payments"]
        mollie_payments = [
            pe
            for pe in original_payments
            if pe.docstatus == 1 and is_valid_mollie_payment_id(pe.reference_no)
        ]

        if not mollie_payments:
            return _create_error_response("No Mollie payments found to refund", "NO_MOLLIE_PAYMENTS")

        # Use the most recent Mollie payment
        payment_to_refund = max(mollie_payments, key=lambda pe: pe.name)

        # Calculate available amount for this specific payment (including chargebacks)
        existing_reversals = frappe.db.sql(
            """
            SELECT SUM(paid_amount) as total_reversed
            FROM `tabPayment Entry`
            WHERE payment_type = 'Pay'
            AND custom_original_payment_id = %s
            AND custom_reversal_type IN ('Refund', 'Chargeback')
            AND docstatus = 1
        """,
            (payment_to_refund.reference_no,),
        )

        total_reversed = flt(
            existing_reversals[0][0] if existing_reversals and existing_reversals[0][0] else 0
        )
        available_amount = payment_to_refund.paid_amount - total_reversed

        if amount is None:
            amount = min(available_amount, refund_info["data"]["net_amount"])

        if amount > available_amount:
            log_concurrent_refund_detected(
                payment_id=payment_to_refund.name,
                attempted_amount=amount,
                available_amount=available_amount,
            )
            return _create_error_response(
                f"Only {available_amount} available for refund from this payment",
                error_code="INSUFFICIENT_REFUNDABLE_AMOUNT",
                details={"available_amount": available_amount, "requested_amount": amount},
            )

        # Initiate the refund using the payment entry
        return initiate_refund(
            payment_entry_name=payment_to_refund.name,
            amount=amount,
            reason=reason or f"Refund for donation {donation_name}",
        )

    except frappe.DoesNotExistError:
        return _create_error_response("Donation not found", error_code="DONATION_NOT_FOUND")

    except frappe.PermissionError:
        frappe.log_error(f"Permission denied for donation refund on {donation_name}", LOG_CATEGORY_REFUND)
        return _create_error_response(
            "You do not have permission to process donation refunds",
            error_code="PERMISSION_DENIED",
        )

    except frappe.ValidationError as e:
        frappe.log_error(
            f"Validation error for donation refund on {donation_name}: {str(e)}", LOG_CATEGORY_REFUND
        )
        return _create_error_response(f"Validation error: {str(e)}", error_code="VALIDATION_ERROR")

    except Exception as e:
        frappe.log_error(
            f"Error initiating donation refund for {donation_name}: {str(e)}", LOG_CATEGORY_REFUND
        )
        return _create_error_response(
            "Failed to initiate donation refund - please try again",
            error_code="DONATION_REFUND_INITIATION_FAILED",
        )


def validate_refund_permissions(user: Optional[str] = None) -> bool:
    """
    Validate if user has permissions to process refunds.

    Args:
        user: Optional user to check (defaults to current user)

    Returns:
        Boolean indicating if user can process refunds
    """
    if not user:
        user = frappe.session.user

    # Check if user has required roles or permissions
    return frappe.has_permission("Payment Entry", "write", user=user) and (
        "Accounts Manager" in frappe.get_roles(user) or Roles.VERENIGINGEN_ADMIN in frappe.get_roles(user)
    )
