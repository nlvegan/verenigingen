# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
SEPA Mandate API - Member SEPA mandate management endpoints.

Extracted from member.py module-level functions for better organization.
All functions maintain backward compatibility through re-exports.

Functions:
    - refresh_sepa_mandates: Sync SEPA mandates child table with actual records
    - get_active_sepa_mandate: Get active mandate for a member (deprecated)
    - create_and_link_mandate_enhanced: Create and link a new mandate (deprecated)
    - derive_bic_from_iban: Derive BIC from IBAN (deprecated)
    - deactivate_old_sepa_mandates: Deactivate old mandates on IBAN change (deprecated)
    - validate_mandate_creation: Validate mandate creation parameters (deprecated)
"""

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.utils.boolean_utils import cbool
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    self_service_api,
)


def _cancel_active_mandates(member: str, reason: str) -> list:
    """Cancel every Active SEPA Mandate of a member, returning what was cancelled.

    A member may hold at most one Active mandate (#584), so a replacement must cancel
    what is there first. Both flows that activate a mandate need this, in this order:
    activating first and cancelling afterwards would trip
    ``SEPAMandate.validate_single_active_mandate`` before the cleanup could run.
    """
    cancelled = []
    for old in frappe.get_all(
        "SEPA Mandate", filters={"member": member, "status": "Active"}, fields=["name"]
    ):
        old_doc = frappe.get_doc("SEPA Mandate", old.name)
        old_doc.status = "Cancelled"
        old_doc.is_active = 0
        old_doc.cancelled_date = today()
        old_doc.cancellation_reason = reason
        old_doc.save()
        cancelled.append(old.name)
    return cancelled


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def refresh_sepa_mandates(member: str):
    """Refresh the SEPA mandates child table by syncing with actual SEPA Mandate records"""
    try:
        member_doc = frappe.get_doc("Member", member)
        result = member_doc.refresh_sepa_mandates_table()
        return result

    except Exception as e:
        frappe.log_error(f"Error refreshing SEPA mandates for member {member}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_active_sepa_mandate(member: str, iban: str = None):
    """
    Get active SEPA mandate for a member.

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.get_active_mandates` instead.
        This function will be removed in a future version.
    """
    import warnings

    from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

    warnings.warn(
        "get_active_sepa_mandate() is deprecated. Use SEPAMandateManager.get_active_mandates() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Delegate to service
    manager = get_sepa_mandate_manager()
    mandates = manager.get_active_mandates(member, iban=iban)

    # Return first mandate or None (legacy API returned single mandate)
    if mandates:
        m = mandates[0]  # SEPA Mandate document, not Member
        return {
            "name": m.name,
            "mandate_id": m.mandate_id,  # ast-skip: SEPA Mandate field
            "status": m.status,
            "iban": m.iban,
            "account_holder_name": m.account_holder_name,  # ast-skip: SEPA Mandate field
        }
    return None


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_and_link_mandate_enhanced(
    member: str,
    mandate_id,
    iban: str,
    bic="",
    account_holder_name: str = "",
    mandate_type="Recurring",
    sign_date=None,
    used_for_memberships=1,
    used_for_donations=0,
    notes="",
    replace_existing=None,
):
    """
    Create a new SEPA mandate and link it to the member.

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.create_mandate` instead.
        This function will be removed in a future version.

    Note: This function delegates to SEPAMandateManager.create_mandate() which creates mandates in Draft status.
    For Active status, activate the mandate after creation.
    """
    import warnings

    from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

    warnings.warn(
        "create_and_link_mandate_enhanced() is deprecated. Use SEPAMandateManager.create_mandate() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Validate mandatory fields for backward compatibility
    # (Legacy API required these; service auto-generates mandate_id if empty)
    if not mandate_id or not str(mandate_id).strip():
        return {"success": False, "valid": False, "error": _("Mandate ID is required")}
    if not iban or not str(iban).strip():
        return {"success": False, "valid": False, "error": _("IBAN is required for SEPA mandate creation")}
    if not account_holder_name or not str(account_holder_name).strip():
        return {"success": False, "valid": False, "error": _("Account holder name is required")}

    # Convert mandate type to internal format with unknown type warning
    type_mapping = {"One-off": "OOFF", "One-of": "OOFF", "Recurring": "RCUR"}
    if mandate_type not in type_mapping:
        frappe.log_error(
            f"Unknown mandate type '{mandate_type}' for member {member}, defaulting to RCUR",
            "SEPA Mandate Type Warning",
        )
    internal_type = type_mapping.get(mandate_type, "RCUR")

    # Delegate to service with allow_duplicate_iban=True for legacy compatibility
    # Legacy function allowed creating mandates even with existing IBAN
    manager = get_sepa_mandate_manager()
    result = manager.create_mandate(
        member=member,
        iban=iban,
        bic=bic or None,
        account_holder_name=account_holder_name or None,
        mandate_id=mandate_id,
        sign_date=sign_date,
        used_for_memberships=cbool(used_for_memberships),
        used_for_donations=cbool(used_for_donations),
        mandate_type=internal_type,
        notes=notes or None,
        allow_duplicate_iban=True,
    )

    # Convert ValidationResult to legacy dict format (standardized response)
    if result.valid:
        # Activate the mandate for backward compatibility (service creates as Draft)
        # Use get_doc + save to trigger proper hooks and validation
        response_data = dict(result.data) if result.data else {}
        if response_data.get("mandate_name"):
            mandate_doc = frappe.get_doc("SEPA Mandate", response_data["mandate_name"])
            # Cancel first: a member may hold at most one Active mandate (#584), and
            # this flow used to activate without cancelling anything -- which is how
            # two Active mandates came to exist and `get_invoice_mandate_info` came
            # to pick between them by recency.
            _cancel_active_mandates(member, f"Replaced by mandate {mandate_doc.mandate_id} on {today()}")
            mandate_doc.status = "Active"
            mandate_doc.is_active = 1
            mandate_doc.save()
            response_data["status"] = "Active"  # Update return data to reflect actual status

            # Also mark this mandate as current in the member's sepa_mandates child table
            # (Legacy API expected is_current=1 for newly created mandates)
            member_doc = frappe.get_doc("Member", member)
            for link in member_doc.sepa_mandates:
                if link.sepa_mandate == mandate_doc.name:
                    link.is_current = 1
                    link.status = "Active"
                    break
            member_doc.save()

        return {"success": True, "valid": True, **response_data}
    else:
        response = {"success": False, "valid": False, "error": result.message}
        if result.errors:
            response["errors"] = result.errors
        return response


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def derive_bic_from_iban(iban: str):
    """
    Derive BIC from IBAN for Dutch banks.

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.utils.validation.iban_validator.derive_bic_from_iban` instead.
        This function will be removed in a future version.
    """
    import warnings

    from verenigingen.utils.validation.iban_validator import derive_bic_from_iban as _derive_bic

    warnings.warn(
        "member.derive_bic_from_iban() is deprecated. Use iban_validator.derive_bic_from_iban() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Delegate to canonical implementation
    bic = _derive_bic(iban)
    return {"bic": bic} if bic else {"bic": None}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def deactivate_old_sepa_mandates(member: str, new_iban):
    """
    Deactivate old SEPA mandates when IBAN changes.

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.deactivate_mandates_for_iban_change` instead.
        This function will be removed in a future version.
    """
    import warnings

    from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

    warnings.warn(
        "deactivate_old_sepa_mandates() is deprecated. Use SEPAMandateManager.deactivate_mandates_for_iban_change() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Delegate to service
    manager = get_sepa_mandate_manager()
    result = manager.deactivate_mandates_for_iban_change(member, new_iban)

    # Convert ValidationResult to legacy dict format (standardized response)
    if result.valid:
        return {"success": True, "valid": True, **(result.data or {})}
    else:
        response = {"success": False, "valid": False, "error": result.message}
        if result.errors:
            response["errors"] = result.errors
        return response


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def validate_mandate_creation(member: str, iban: str, mandate_id):
    """
    Validate mandate creation parameters and check for existing mandates.

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.validate_mandate_creation` instead.
        This function will be removed in a future version.
    """
    import warnings

    from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

    warnings.warn(
        "validate_mandate_creation() is deprecated. Use SEPAMandateManager.validate_mandate_creation() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Delegate to service with allow_duplicate_iban=True for legacy behavior
    # Legacy API returned valid=True with warning for duplicate IBAN
    manager = get_sepa_mandate_manager()
    result = manager.validate_mandate_creation(member, iban, mandate_id, allow_duplicate_iban=True)

    # Convert ValidationResult to legacy dict format (standardized response)
    if result.valid:
        response = {"success": True, "valid": True, **(result.data or {})}
        # Check for existing mandate with same IBAN and add warning (legacy behavior)
        existing_mandates = manager.get_active_mandates(member, iban=iban)
        if existing_mandates:
            response["existing_mandate"] = existing_mandates[0].mandate_id
            response["warning"] = _("An active mandate already exists for this IBAN: {0}").format(
                existing_mandates[0].mandate_id
            )
        return response
    else:
        response = {"success": False, "valid": False, "error": result.message}
        if result.errors:
            response["errors"] = result.errors
        return response


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def setup_sepa_direct_debit(iban: str = None, account_holder_name: str = None):
    """
    Set up SEPA Direct Debit for the current member.

    Creates or updates bank details and creates a new SEPA mandate.

    Args:
        iban: International Bank Account Number
        account_holder_name: Name on the bank account

    Returns:
        Dict with success status and mandate details
    """
    from frappe.utils import today

    from verenigingen.utils.member_utils import (
        get_current_user_member_name_required,
        validate_member_ownership,
    )
    from verenigingen.utils.validation.iban_validator import derive_bic_from_iban, validate_iban

    # Get form data if not provided as parameters
    if not iban:
        iban = frappe.local.form_dict.get("iban", "")
    if not account_holder_name:
        account_holder_name = frappe.local.form_dict.get("account_holder_name", "")

    # Clean input
    iban = iban.replace(" ", "").upper().strip() if iban else ""
    account_holder_name = account_holder_name.strip() if account_holder_name else ""

    # Validate required fields
    if not iban:
        return {"success": False, "error": _("IBAN is required")}
    if not account_holder_name:
        return {"success": False, "error": _("Account holder name is required")}

    # Validate IBAN format
    validation_result = validate_iban(iban)
    if not validation_result.get("valid"):
        return {"success": False, "error": validation_result.get("message", _("Invalid IBAN format"))}

    # Get and validate member
    member_name = get_current_user_member_name_required()
    validate_member_ownership(member_name, _("You can only update your own bank details"))

    member = frappe.get_doc("Member", member_name)

    # Derive BIC for Dutch IBANs
    bic = derive_bic_from_iban(iban) or ""

    try:
        # Update member bank details with ignore_permissions: the Member write
        # DocPerm for plain members is if_owner-gated, but member records are owned
        # by the staff who created them, so a self-service member can never satisfy
        # the framework write check on their OWN record (and secure_document_operation
        # can't help — it escalates to a system user, which plain members may not
        # request). Ownership was already verified via validate_member_ownership
        # above, and Member.validate() (IBAN history, etc.) still runs under
        # ignore_permissions — only the mis-fitting if_owner perm check is skipped.
        member.iban = iban
        member.bic = bic
        member.bank_account_name = account_holder_name
        member.payment_method = "SEPA Direct Debit"
        # Security: self-service caller verified as the record owner via
        # validate_member_ownership above; ignore_permissions only skips the
        # mis-fitting if_owner DocPerm, Member.validate() still runs.
        member.save(ignore_permissions=True)

        # Check for existing active mandate with same IBAN
        existing_mandate = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member_name, "iban": iban, "status": "Active", "is_active": 1},
            fields=["name", "mandate_id"],
            limit=1,
        )

        if existing_mandate:
            # Mandate already exists for this IBAN
            return {
                "success": True,
                "message": _("Bank details updated. Your existing SEPA mandate remains active."),
                "mandate_id": existing_mandate[0].mandate_id,
                "redirect": "/payment_dashboard?success=bank_details_updated",
            }

        # Deactivate any other active mandates for this member. Note the filter no
        # longer requires is_active=1: `status` is the field the guard and the batch
        # query both read, and a row with status Active but is_active 0 would have
        # been left behind to block the new mandate.
        _cancel_active_mandates(member_name, f"Replaced by a new mandate on {today()}")

        # Generate unique mandate ID
        mandate_id = _generate_sepa_mandate_id(member_name)

        # Create new SEPA mandate
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": mandate_id,
                "member": member_name,
                "account_holder_name": account_holder_name,
                "iban": iban,
                "bic": bic,
                "status": "Active",
                "is_active": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "sign_date": today(),
                "first_collection_date": frappe.utils.add_days(today(), 5),
                "used_for_memberships": 1,
                "frequency": "Monthly",
            }
        )
        mandate.insert()

        frappe.db.commit()

        frappe.logger().info(
            f"SEPA mandate {mandate_id} created for member {member_name} by user {frappe.session.user}"
        )

        return {
            "success": True,
            "message": _("SEPA Direct Debit has been set up successfully. Your mandate is now active."),
            "mandate_id": mandate_id,
            "mandate_name": mandate.name,
            "redirect": "/payment_dashboard?success=sepa_mandate_created",
        }

    except Exception as e:
        frappe.log_error(f"SEPA setup failed for member {member_name}: {str(e)}", "SEPA Setup Error")
        return {"success": False, "error": _("Failed to set up SEPA Direct Debit: {0}").format(str(e))}


def _generate_sepa_mandate_id(member_name: str) -> str:
    """Generate a unique SEPA mandate ID."""
    from frappe.utils import today

    # Format: SEPA-YYYYMMDD-XXXX where XXXX is a sequence number
    date_part = today().replace("-", "")

    # Get count of mandates created today
    today_count = frappe.db.count(
        "SEPA Mandate",
        filters={"creation": [">=", today()]},
    )

    return f"SEPA-{date_part}-{str(today_count + 1).zfill(4)}"
