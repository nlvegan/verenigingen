"""
SEPA Direct Debit Batch Workflow Controller
Implements business logic for workflow state transitions and validations
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.authorization import (
    SEPAOperation,
    SEPAPermissionLevel,
    require_sepa_permission,
)


@high_security_api(operation_type=OperationType.FINANCIAL)
@require_sepa_permission(SEPAPermissionLevel.VALIDATE, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def validate_batch_for_approval(batch_name):
    """
    Validate batch and determine appropriate approval path

    Returns:
        Dict with validation results and recommended next state
    """
    try:
        batch = frappe.get_doc("Direct Debit Batch", batch_name)

        validation_result = {
            "valid": True,
            "risk_level": "Low",
            "issues": [],
            "warnings": [],
            "recommended_state": "Pending Approval",
            "approval_notes": [],
        }

        # === VALIDATION CHECKS ===

        # 1. Basic validation
        if not batch.invoices:
            validation_result["valid"] = False
            validation_result["issues"].append("No invoices in batch")

        # 2. Amount validation
        total_amount = flt(batch.total_amount)
        if total_amount <= 0:
            validation_result["valid"] = False
            validation_result["issues"].append("Invalid total amount")

        # 3. SEPA mandate validation
        mandate_issues = validate_sepa_mandates(batch)
        if mandate_issues:
            validation_result["issues"].extend(mandate_issues)
            validation_result["valid"] = False

        # 4. Bank details validation
        bank_issues = validate_bank_details(batch)
        if bank_issues:
            validation_result["warnings"].extend(bank_issues)

        # === RISK ASSESSMENT ===

        risk_factors = []

        # High-value batch (>€5000)
        if total_amount > 5000:
            risk_factors.append("High value batch")
            validation_result["risk_level"] = "High"

        # Large batch (>50 invoices)
        if batch.entry_count > 50:
            risk_factors.append("Large invoice count")
            if validation_result["risk_level"] != "High":
                validation_result["risk_level"] = "Medium"

        # First-time SEPA batch
        if batch.batch_type == "FRST":
            risk_factors.append("First-time direct debit")
            if validation_result["risk_level"] == "Low":
                validation_result["risk_level"] = "Medium"

        # Weekend or holiday processing
        batch_date = getdate(batch.batch_date)
        if batch_date.weekday() >= 5:  # Saturday or Sunday
            risk_factors.append("Weekend processing")
            validation_result["warnings"].append("Processing on weekend")

        # === ROUTING DECISION ===

        if validation_result["risk_level"] == "High":
            validation_result["recommended_state"] = "Pending Senior Approval"
            validation_result["approval_notes"].append("Requires senior approval due to high risk factors")
        elif total_amount > 10000 or batch.entry_count > 100:
            validation_result["recommended_state"] = "Pending Senior Approval"
            validation_result["approval_notes"].append("Requires senior approval due to size")

        # Update batch fields
        batch.db_set("risk_level", validation_result["risk_level"])
        if validation_result["approval_notes"]:
            batch.db_set("approval_notes", "\n".join(validation_result["approval_notes"]))

        return validation_result

    except Exception as e:
        frappe.log_error(f"Error validating batch {batch_name}: {str(e)}", "DD Batch Validation Error")
        return {"valid": False, "error": str(e), "issues": [f"Validation error: {str(e)}"]}


def validate_sepa_mandates(batch):
    """Validate SEPA mandates for all invoices in batch"""
    issues = []

    for invoice_item in batch.invoices:
        # Check mandate reference exists
        if not invoice_item.mandate_reference:
            issues.append(f"Missing mandate reference for invoice {invoice_item.invoice}")
            continue

        # Check if mandate exists and is active
        mandate = frappe.db.get_value(
            "SEPA Mandate",
            {"mandate_id": invoice_item.mandate_reference},
            ["name", "status", "is_active", "member"],
            as_dict=True,
        )

        if not mandate:
            issues.append(
                f"SEPA mandate {invoice_item.mandate_reference} not found for invoice {invoice_item.invoice}"
            )
        elif mandate.status != "Active" or not mandate.is_active:
            issues.append(
                f"SEPA mandate {invoice_item.mandate_reference} is not active for invoice {invoice_item.invoice}"
            )
        elif mandate.member != invoice_item.member:
            issues.append(f"SEPA mandate member mismatch for invoice {invoice_item.invoice}")

    return issues


def validate_bank_details(batch):
    """Validate bank details for all invoices in batch"""
    warnings = []

    for invoice_item in batch.invoices:
        # Check IBAN format
        if not invoice_item.iban:
            warnings.append(f"Missing IBAN for invoice {invoice_item.invoice}")
        elif not is_valid_iban_format(invoice_item.iban):
            warnings.append(f"Invalid IBAN format for invoice {invoice_item.invoice}")

        # Check if IBAN matches mandate
        if invoice_item.mandate_reference and invoice_item.iban:
            mandate_iban = frappe.db.get_value(
                "SEPA Mandate", {"mandate_id": invoice_item.mandate_reference}, "iban"
            )

            if mandate_iban and normalize_iban(mandate_iban) != normalize_iban(invoice_item.iban):
                warnings.append(f"IBAN mismatch with mandate for invoice {invoice_item.invoice}")

    return warnings


def is_valid_iban_format(iban):
    """Basic IBAN format validation"""
    if not iban:
        return False

    # Remove spaces and convert to uppercase
    iban = iban.replace(" ", "").upper()

    # Basic length check (minimum 15, maximum 34 characters)
    if len(iban) < 15 or len(iban) > 34:
        return False

    # Should start with two letters (country code)
    if not iban[:2].isalpha():
        return False

    # Next two should be digits (check digits)
    if not iban[2:4].isdigit():
        return False

    return True


def normalize_iban(iban):
    """Normalize IBAN for comparison"""
    if not iban:
        return ""
    return iban.replace(" ", "").upper()


@critical_api()
@require_sepa_permission(SEPAPermissionLevel.PROCESS, SEPAOperation.BATCH_PROCESS)
@frappe.whitelist()
def approve_batch(batch_name, approval_notes=None):
    """
    Approve batch and move to next state

    Args:
        batch_name: Name of the batch to approve
        approval_notes: Optional approval notes

    Returns:
        Success status and next state
    """
    try:
        batch = frappe.get_doc("Direct Debit Batch", batch_name)

        # Validate user has permission to approve
        if not can_user_approve_batch(batch):
            frappe.throw(_("You don't have permission to approve this batch"))

        # Re-validate before approval
        validation_result = validate_batch_for_approval(batch_name)
        if not validation_result.get("valid"):
            frappe.throw(
                _("Batch validation failed: {0}").format(", ".join(validation_result.get("issues", [])))
            )

        # Add approval notes
        if approval_notes:
            current_notes = batch.approval_notes or ""
            timestamp = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
            new_note = f"{timestamp} - {frappe.session.user}: {approval_notes}"

            if current_notes:
                batch.approval_notes = f"{current_notes}\n{new_note}"
            else:
                batch.approval_notes = new_note

            batch.save()

        # Determine next state based on current workflow state
        current_state = batch.approval_status

        if current_state == "Pending Approval":
            next_state = "Approved"
        elif current_state == "Pending Senior Approval":
            next_state = "Approved"
        else:
            frappe.throw(_("Batch is not in a state that can be approved"))

        return {
            "success": True,
            "next_state": next_state,
            "message": f"Batch approved and moved to {next_state}",
        }

    except Exception as e:
        frappe.log_error(f"Error approving batch {batch_name}: {str(e)}", "DD Batch Approval Error")
        frappe.throw(_("Error approving batch: {0}").format(str(e)))


@critical_api()
@require_sepa_permission(SEPAPermissionLevel.PROCESS, SEPAOperation.BATCH_CANCEL)
@frappe.whitelist()
def reject_batch(batch_name, rejection_reason):
    """
    Reject batch and provide reason

    Args:
        batch_name: Name of the batch to reject
        rejection_reason: Reason for rejection

    Returns:
        Success status
    """
    try:
        batch = frappe.get_doc("Direct Debit Batch", batch_name)

        # Add rejection notes
        timestamp = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        rejection_note = f"{timestamp} - {frappe.session.user}: REJECTED - {rejection_reason}"

        current_notes = batch.approval_notes or ""
        if current_notes:
            batch.approval_notes = f"{current_notes}\n{rejection_note}"
        else:
            batch.approval_notes = rejection_note

        batch.save()

        return {"success": True, "message": "Batch rejected with reason provided"}

    except Exception as e:
        frappe.log_error(f"Error rejecting batch {batch_name}: {str(e)}", "DD Batch Rejection Error")
        frappe.throw(_("Error rejecting batch: {0}").format(str(e)))


def can_user_approve_batch(batch):
    """Check if current user can approve the batch"""
    user_roles = frappe.get_roles()

    # System Manager can approve anything
    if "System Manager" in user_roles:
        return True

    # Check approval level based on batch risk
    risk_level = batch.risk_level

    if risk_level == "High":
        return "Finance Manager" in user_roles
    elif risk_level == "Medium":
        return "Verenigingen Manager" in user_roles or "Finance Manager" in user_roles
    else:  # Low risk
        return "Verenigingen Manager" in user_roles or "Finance Manager" in user_roles

    return False


@standard_api()
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def get_batch_approval_history(batch_name):
    """Get approval history for a batch"""
    try:
        batch = frappe.get_doc("Direct Debit Batch", batch_name)

        # Parse approval notes into structured history
        history = []

        if batch.approval_notes:
            lines = batch.approval_notes.split("\n")
            for line in lines:
                if " - " in line and ": " in line:
                    try:
                        timestamp_part = line.split(" - ")[0]
                        user_and_action = line.split(" - ")[1]
                        user = user_and_action.split(": ")[0]
                        action = user_and_action.split(": ")[1]

                        history.append({"timestamp": timestamp_part, "user": user, "action": action})
                    except Exception:
                        # If parsing fails, add as raw entry
                        history.append({"timestamp": "", "user": "", "action": line})

        return {
            "success": True,
            "history": history,
            "current_state": batch.approval_status,
            "risk_level": batch.risk_level,
        }

    except Exception as e:
        frappe.log_error(
            f"Error getting approval history for batch {batch_name}: {str(e)}", "DD Batch History Error"
        )
        return {"success": False, "error": str(e)}


@critical_api()
@require_sepa_permission(SEPAPermissionLevel.PROCESS, SEPAOperation.XML_GENERATE)
@frappe.whitelist()
def trigger_sepa_generation(batch_name):
    """
    Trigger SEPA file generation for approved batch

    Args:
        batch_name: Name of the approved batch

    Returns:
        Generation result
    """
    try:
        batch = frappe.get_doc("Direct Debit Batch", batch_name)

        # Check batch is in approved state
        if batch.approval_status != "Approved":
            frappe.throw(_("Batch must be approved before SEPA generation"))

        # Check user has permission
        user_roles = frappe.get_roles()
        if "System Manager" not in user_roles and "Finance Manager" not in user_roles:
            frappe.throw(_("You don't have permission to generate SEPA files"))

        # Generate SEPA file using existing method
        sepa_file = batch.generate_sepa_xml()

        # Add generation note
        timestamp = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        generation_note = f"{timestamp} - {frappe.session.user}: SEPA file generated"

        current_notes = batch.approval_notes or ""
        if current_notes:
            batch.approval_notes = f"{current_notes}\n{generation_note}"
        else:
            batch.approval_notes = generation_note

        batch.save()

        return {"success": True, "sepa_file": sepa_file, "message": "SEPA file generated successfully"}

    except Exception as e:
        frappe.log_error(
            f"Error generating SEPA file for batch {batch_name}: {str(e)}", "DD SEPA Generation Error"
        )
        frappe.throw(_("Error generating SEPA file: {0}").format(str(e)))


@standard_api()
@require_sepa_permission(SEPAPermissionLevel.READ, SEPAOperation.BATCH_VALIDATE)
@frappe.whitelist()
def get_batches_pending_approval():
    """Get all batches pending approval for current user"""
    try:
        user_roles = frappe.get_roles()

        # Determine which batches user can approve
        filters = {"docstatus": 0}

        if "System Manager" in user_roles:
            # System Manager can see all draft batches (equivalent to pending approval)
            filters["status"] = ["in", ["Draft", "Generated"]]
        elif "Finance Manager" in user_roles:
            # Finance Manager can see all draft batches
            filters["status"] = ["in", ["Draft", "Generated"]]
        elif "Verenigingen Manager" in user_roles:
            # Membership Manager can only see draft batches
            filters["status"] = "Draft"
        else:
            # No approval permissions
            return {"success": True, "batches": []}

        batches = frappe.get_all(
            "Direct Debit Batch",
            filters=filters,
            fields=[
                "name",
                "batch_date",
                "batch_description",
                "total_amount",
                "entry_count",
                "status",
                "creation",
            ],
            order_by="creation desc",
        )

        return {"success": True, "batches": batches, "user_roles": user_roles}

    except Exception as e:
        frappe.log_error(f"Error getting pending approvals: {str(e)}", "DD Batch Approval List Error")
        return {"success": False, "error": str(e)}
