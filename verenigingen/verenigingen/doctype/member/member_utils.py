import frappe
from frappe import _
from frappe.utils import cint, now, today

from verenigingen.utils.secure_operations import secure_document_operation

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


def get_member_settings():
    """Get member-related configuration settings with defaults"""
    try:
        settings = frappe.get_single("Verenigingen Settings")
        return {
            "mandate_expiry_warning_days": getattr(settings, "mandate_expiry_warning_days", 30),
            "default_mandate_type": getattr(settings, "default_mandate_type", "RCUR"),
        }
    except Exception:
        # Return defaults if settings not available
        return {
            "mandate_expiry_warning_days": 30,
            "default_mandate_type": "RCUR",
        }


def get_iban_bank_codes():
    """Get IBAN bank code mappings - configurable via custom settings"""
    # TODO: Move to Verenigingen Settings DocType for full configurability
    return {
        "NL": (4, 4),
        "DE": (4, 8),
        "BE": (4, 3),
        "FR": (4, 5),
        "IT": (5, 5),
        "ES": (4, 4),
        "GB": (4, 6),
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.PUBLIC)
def is_chapter_management_enabled():
    """Check if chapter management is enabled in settings"""
    try:
        return frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
    except (frappe.DoesNotExistError, frappe.ValidationError) as e:
        frappe.log_error(f"Settings access error in chapter management check: {str(e)}", "Member Utils")
        return True  # Default to enabled for backward compatibility
    except frappe.DatabaseError as e:
        frappe.log_error(f"Database error in chapter management check: {str(e)}", "Member Utils")
        return True


# get_board_memberships moved to ChapterManagementService
# Delegate function remains in member.py for API compatibility


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def check_sepa_mandate_status(member):
    """Check SEPA mandate status for dashboard indicators"""
    member_doc = frappe.get_doc("Member", member)
    active_mandates = member_doc.get_active_sepa_mandates()

    result = {"has_active_mandate": bool(active_mandates), "expiring_soon": False}

    # Get configurable warning threshold
    settings = get_member_settings()
    warning_days = settings["mandate_expiry_warning_days"]

    for mandate in active_mandates:
        if mandate.expiry_date:
            days_to_expiry = frappe.utils.date_diff(mandate.expiry_date, today())
            if 0 < days_to_expiry <= warning_days:
                result["expiring_soon"] = True
                break

    return result


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def update_member_payment_history(doc, method=None):
    """Update payment history for member when a payment entry is modified"""
    if doc.party_type != "Customer":
        return

    members = frappe.get_all("Member", filters={"customer": doc.party}, fields=["name"])

    for member_doc in members:
        try:
            member = frappe.get_doc("Member", member_doc.name)
            member.load_payment_history()

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            payment_result = secure_document_operation(
                operation="save",
                doc=member,
                justification=f"Update payment history for member {member.name} after payment entry {doc.name}",
                required_permissions=["Member:write"],
            )

            if not payment_result.success:
                frappe.log_error(
                    f"Failed to update payment history for Member {member.name}: {'; '.join(payment_result.errors)}",
                    "Member Payment History Security",
                )
                continue
        except frappe.DoesNotExistError:
            frappe.log_error(
                f"Member {member_doc.name} not found during payment history update", "Member Payment History"
            )
        except frappe.ValidationError as e:
            frappe.log_error(
                f"Validation error updating payment history for Member {member_doc.name}: {str(e)}",
                "Member Payment History",
            )
        except frappe.DatabaseError as e:
            frappe.log_error(
                f"Database error updating payment history for Member {member_doc.name}: {str(e)}",
                "Member Payment History",
            )
        except Exception as e:
            frappe.log_error(
                f"Unexpected error updating payment history for Member {member_doc.name}: {str(e)}",
                "Member Payment History",
            )


def update_member_payment_history_from_invoice(doc, method=None):
    """Update payment history for member when an invoice is modified"""
    if doc.doctype != "Sales Invoice" or doc.customer is None:
        return

    members = frappe.get_all("Member", filters={"customer": doc.customer}, fields=["name"])

    for member_doc in members:
        try:
            member = frappe.get_doc("Member", member_doc.name)
            member.load_payment_history()

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            invoice_result = secure_document_operation(
                operation="save",
                doc=member,
                justification=f"Update payment history for member {member.name} after invoice {doc.name}",
                required_permissions=["Member:write"],
            )

            if not invoice_result.success:
                frappe.log_error(
                    f"Failed to update payment history for Member {member.name}: {'; '.join(invoice_result.errors)}",
                    "Member Invoice History Security",
                )
                continue
        except frappe.DoesNotExistError:
            frappe.log_error(
                f"Member {member_doc.name} not found during invoice payment history update",
                "Member Payment History",
            )
        except frappe.ValidationError as e:
            frappe.log_error(
                f"Validation error updating payment history for Member {member_doc.name}: {str(e)}",
                "Member Payment History",
            )
        except frappe.DatabaseError as e:
            frappe.log_error(
                f"Database error updating payment history for Member {member_doc.name}: {str(e)}",
                "Member Payment History",
            )
        except Exception as e:
            frappe.log_error(
                f"Unexpected error updating payment history for Member {member_doc.name}: {str(e)}",
                "Member Payment History",
            )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def add_manual_payment_record(member, amount, payment_date=None, payment_method=None, notes=None):
    """Manually add a payment record (e.g., for cash donations)"""
    if not member or not amount:
        frappe.throw(_("Member and amount are required"))

    member_doc = frappe.get_doc("Member", member)

    if not member_doc.customer:
        frappe.throw(_("Member must have a customer record"))

    payment = frappe.new_doc("Payment Entry")
    payment.payment_type = "Receive"
    payment.party_type = "Customer"
    payment.party = member_doc.customer
    payment.posting_date = payment_date or today()
    payment.paid_amount = float(amount)
    payment.received_amount = float(amount)
    # Get mode of payment from explicit validation
    if payment_method:
        if frappe.db.exists("Mode of Payment", payment_method):
            payment.mode_of_payment = payment_method
        else:
            frappe.throw(
                f"Payment method '{payment_method}' does not exist. "
                "Please configure the payment method in Mode of Payment before processing."
            )
    else:
        # Use explicit default with validation
        if frappe.db.exists("Mode of Payment", "Cash"):
            payment.mode_of_payment = "Cash"
        else:
            frappe.throw(
                "No payment method provided and default 'Cash' mode of payment does not exist. "
                "Please either provide a payment method or configure 'Cash' mode of payment."
            )

    settings = frappe.get_single("Verenigingen Settings")
    payment.company = settings.company or frappe.defaults.get_global_default("company")

    payment.paid_from = frappe.get_value("Company", payment.company, "default_receivable_account")
    payment.paid_to = settings.donation_payment_account or frappe.get_value(
        "Company", payment.company, "default_cash_account"
    )

    payment.remarks = notes or "Manual donation entry"

    # Audit log before financial transaction
    frappe.log_error(
        f"AUDIT: Manual payment record creation initiated by {frappe.session.user} "
        f"for member {member} - Amount: {amount}, Method: {payment_method or 'Cash'}, Notes: {notes or 'None'}",
        "Financial Audit Trail",
    )

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    payment_result = secure_document_operation(
        operation="insert",
        doc=payment,
        justification=f"Manual payment record creation for member {member} - Amount: {amount}, Method: {payment_method or 'Cash'}",
        required_permissions=["Payment Entry:create"],
    )

    if not payment_result.success:
        frappe.log_error(
            f"Failed to create payment record: {'; '.join(payment_result.errors)}", "Payment Entry Security"
        )
        frappe.throw(_("Failed to create payment record for member {0}").format(member))

    payment = payment_result.doc
    payment.submit()

    # Audit log successful transaction
    frappe.log_error(
        f"AUDIT: Manual payment record {payment.name} successfully created and submitted "
        f"for member {member} by {frappe.session.user}",
        "Financial Audit Trail",
    )

    member_doc.load_payment_history()

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    member_result = secure_document_operation(
        operation="save",
        doc=member_doc,
        justification=f"Update member {member} payment history after manual payment {payment.name}",
        required_permissions=["Member:write"],
    )

    if not member_result.success:
        frappe.log_error(
            f"Failed to update member payment history: {'; '.join(member_result.errors)}",
            "Member Payment History Security",
        )
        frappe.throw(_("Failed to update payment history for member {0}").format(member))

    return payment.name


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_linked_donations(member):
    """Find linked donor record for a member to view donations"""
    if not member:
        return {"success": False, "message": "No member specified"}

    member_doc = frappe.get_doc("Member", member)
    if member_doc.email:
        donors = frappe.get_all("Donor", filters={"donor_email": member_doc.email}, fields=["name"])

        if donors:
            return {"success": True, "donor": donors[0].name}

    if member_doc.full_name:
        donors = frappe.get_all(
            "Donor", filters={"donor_name": ["like", f"%{member_doc.full_name}%"]}, fields=["name"]
        )

        if donors:
            return {"success": True, "donor": donors[0].name}

    return {"success": False, "message": "No donor record found for this member"}


# check_donor_exists moved to DonorManagementService
# Use DonorManagementService.check_donor_exists() for checking donor existence


# Removed duplicate create_donor_from_member function
# The correct implementation is in member.py with proper field validation
# This prevents field reference errors and ensures consistent behavior


@frappe.whitelist()
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_sepa_mandate_from_bank_details(
    member,
    iban,
    bic=None,
    account_holder_name=None,
    mandate_type=None,
    sign_date=None,
    used_for_memberships=1,
    used_for_donations=0,
):
    """Create a new SEPA mandate based on bank details already entered"""
    if not member or not iban:
        frappe.throw(_("Member and IBAN are required"))

    if not sign_date:
        sign_date = today()

    # Use configurable default mandate type if not provided
    if not mandate_type:
        settings = get_member_settings()
        mandate_type = settings["default_mandate_type"]

    member_doc = frappe.get_doc("Member", member)
    if not account_holder_name:
        account_holder_name = member_doc.full_name

    timestamp = now().replace(" ", "").replace("-", "").replace(":", "")[:14]
    mandate_id = f"M-{member_doc.member_id}-{timestamp}"

    mandate = frappe.new_doc("SEPA Mandate")
    mandate.mandate_id = mandate_id
    mandate.member = member
    mandate.member_name = member_doc.full_name
    mandate.account_holder_name = account_holder_name
    mandate.iban = iban
    if bic:
        mandate.bic = bic
    mandate.sign_date = sign_date
    mandate.mandate_type = mandate_type

    mandate.used_for_memberships = 1 if used_for_memberships else 0
    mandate.used_for_donations = 1 if used_for_donations else 0

    mandate.status = "Active"
    mandate.is_active = 1

    # Audit log before SEPA mandate creation
    frappe.log_error(
        f"AUDIT: SEPA mandate creation initiated by {frappe.session.user} "
        f"for member {member} - IBAN: {iban[-4:].rjust(len(iban), '*')}, "
        f"Mandate ID: {mandate_id}, Type: {mandate_type}",
        "SEPA Audit Trail",
    )

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    mandate_result = secure_document_operation(
        operation="insert",
        doc=mandate,
        justification=f"Create SEPA mandate {mandate_id} for member {member} with IBAN {iban[-4:].rjust(len(iban), '*')}",
        required_permissions=["SEPA Mandate:create"],
    )

    if not mandate_result.success:
        frappe.log_error(
            f"Failed to create SEPA mandate: {'; '.join(mandate_result.errors)}", "SEPA Mandate Security"
        )
        frappe.throw(_("Failed to create SEPA mandate for member {0}").format(member))

    mandate = mandate_result.doc

    # Audit log successful mandate creation
    frappe.log_error(
        f"AUDIT: SEPA mandate {mandate.name} successfully created and linked "
        f"to member {member} by {frappe.session.user}",
        "SEPA Audit Trail",
    )

    member_doc.append("sepa_mandates", {"sepa_mandate": mandate.name, "is_current": 1})

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    member_result = secure_document_operation(
        operation="save",
        doc=member_doc,
        justification=f"Link SEPA mandate {mandate.name} to member {member}",
        required_permissions=["Member:write"],
    )

    if not member_result.success:
        frappe.log_error(
            f"Failed to link SEPA mandate to member: {'; '.join(member_result.errors)}",
            "Member SEPA Link Security",
        )
        frappe.throw(_("Failed to link SEPA mandate to member {0}").format(member))

    return mandate.name


@frappe.whitelist()
@standard_api(operation_type=OperationType.PUBLIC)
def get_member_form_settings():
    """Get settings for the member form based on system configuration"""
    settings = {
        "show_chapter_field": is_chapter_management_enabled(),
        "chapter_field_label": _("Chapter") if is_chapter_management_enabled() else "",
    }

    return settings


@frappe.whitelist(allow_guest=True)
def find_chapter_by_postal_code(postal_code):
    """Find chapters matching a postal code"""
    if not is_chapter_management_enabled():
        return {"success": False, "message": "Chapter management is disabled"}

    if not postal_code:
        return {"success": False, "message": "Postal code is required"}

    chapters = frappe.get_all("Chapter", filters={"published": 1}, fields=["name", "region", "postal_codes"])

    matching_chapters = []

    for chapter in chapters:
        if not chapter.get("postal_codes"):
            continue

        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        if chapter_doc.matches_postal_code(postal_code):
            matching_chapters.append({"name": chapter.name, "region": chapter.region})

    return {"success": True, "matching_chapters": matching_chapters}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def check_mandate_iban_mismatch(member, current_iban):
    """Check if we should show SEPA mandate creation popup"""
    frappe.logger().debug(
        f"check_mandate_iban_mismatch called with member={member}, current_iban={current_iban}"
    )

    if not member or not current_iban:
        return {"show_popup": False, "error": "Missing parameters"}

    current_iban_normalized = current_iban.replace(" ", "").upper()

    existing_mandates = frappe.get_all(
        "SEPA Mandate",
        filters={"member": member, "status": "Active", "is_active": 1},
        fields=["name", "mandate_id", "iban", "creation"],
        order_by="creation desc",
    )

    frappe.logger().debug(f"Found {len(existing_mandates)} active mandates")

    if not existing_mandates:
        frappe.logger().debug("No existing mandates found - showing first-time setup popup")
        return {
            "show_popup": True,
            "reason": "no_existing_mandates",
            "scenario": "first_time_setup",
            "message": "No SEPA mandate found. Create one for SEPA Direct Debit payments?",
        }

    for mandate in existing_mandates:
        mandate_iban_normalized = mandate.iban.replace(" ", "").upper() if mandate.iban else ""

        frappe.logger().debug(
            f"Comparing mandate IBAN '{mandate_iban_normalized}' with current '{current_iban_normalized}'"
        )

        if mandate_iban_normalized and mandate_iban_normalized != current_iban_normalized:
            frappe.logger().debug(f"IBAN mismatch found in mandate {mandate.name}")
            return {
                "show_popup": True,
                "existing_mandate": mandate.name,
                "existing_iban": mandate.iban,
                "current_iban": current_iban,
                "reason": "iban_mismatch",
                "scenario": "bank_account_change",
                "message": "Your IBAN differs from existing mandate. Create new mandate?",
            }

    frappe.logger().debug("All existing mandates have matching IBAN")
    return {"show_popup": False, "reason": "iban_matches", "scenario": "no_change_needed"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def derive_bic_from_iban(iban):
    """Derive BIC from IBAN - redirects to SEPAService

    NOTE: Original implementation here was more sophisticated with full bank mappings.
    SEPAService should be enhanced with this mapping in a future iteration.
    """
    from verenigingen.utils.services import sepa_service

    return sepa_service.derive_bic_from_iban(iban)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_member_termination_status(member):
    """Get termination status for a member"""
    pending_requests = frappe.get_all(
        "Membership Termination Request",
        filters={"member": member, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "status", "termination_type", "request_date"],
    )

    executed_requests = frappe.get_all(
        "Membership Termination Request",
        filters={"member": member, "status": "Executed"},
        fields=["name", "termination_type", "execution_date"],
        limit=1,
        order_by="execution_date desc",
    )

    return {
        "pending_requests": pending_requests,
        "executed_requests": executed_requests,
        "is_terminated": len(executed_requests) > 0,
    }


def update_termination_status_display(doc, method=None):
    """
    Update member status and member_end_date based on termination request.

    Note: This function only updates fields that exist in the Member DocType:
    - status: The main member status ("Terminated", "Deceased", "Banned", etc.)
    - member_end_date: Date when membership ended

    Termination metadata is stored in Membership Termination Request records,
    not duplicated on the Member record. Use get_member_termination_status()
    to retrieve detailed termination information.
    """
    member = doc

    # CRITICAL: During termination execution, termination_integration.py sets status correctly
    # Don't override it - respect the _termination_in_progress flag and _termination_final_status
    if getattr(member, "_termination_in_progress", False):
        # Termination is being executed - status already set correctly by termination_integration.py
        if hasattr(member, "_termination_final_status"):
            # Ensure status matches what termination execution set
            if member.status != member._termination_final_status:
                member.status = member._termination_final_status
        return  # Skip database query and other logic

    # Get most recent executed termination
    executed_termination = frappe.get_all(
        "Membership Termination Request",
        filters={"member": member.name, "status": "Executed"},
        fields=["name", "termination_type", "execution_date", "termination_date"],
        order_by="execution_date desc",
        limit=1,
    )

    if executed_termination:
        term_data = executed_termination[0]

        # Map termination type to correct member status
        status_mapping = {
            "Deceased": "Deceased",
            "Expulsion": "Banned",
        }
        target_status = status_mapping.get(term_data.termination_type, "Terminated")

        # Update status if not already set correctly
        if member.status != target_status:
            member.status = target_status

        # Set member_end_date to the termination date
        target_date = term_data.termination_date or term_data.execution_date
        if member.member_end_date != target_date:
            member.member_end_date = target_date


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def reset_member_id_counter(counter_value):
    """Reset the member ID counter (called from client-side)"""
    from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("Insufficient permissions"))

    if not frappe.user.has_role("System Manager"):
        frappe.throw(_("Only System Managers can reset the member ID counter"))

    counter_value = cint(counter_value)
    if counter_value <= 0:
        frappe.throw(_("Counter value must be greater than 0"))

    MemberIDManager.reset_counter(counter_value)

    return {"success": True, "message": _("Member ID counter reset to {0}").format(counter_value)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.ADMIN)
def get_next_member_id_preview():
    """Get the next member ID that would be assigned"""
    from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

    if not frappe.has_permission("Member", "read"):
        frappe.throw(_("Insufficient permissions"))

    counter_key = "member_id_counter"
    current_counter = frappe.cache().get(counter_key)

    if current_counter is None:
        current_counter = MemberIDManager._initialize_counter()

    return {"next_id": current_counter + 1, "current_counter": current_counter}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_and_link_mandate_enhanced(
    member,
    mandate_id,
    iban,
    bic=None,
    account_holder_name=None,
    mandate_type="RCUR",
    sign_date=None,
    used_for_memberships=1,
    used_for_donations=0,
    notes=None,
    replace_mandate=None,
):
    """Create and link SEPA mandate - redirects to SEPAService

    NOTE: Original implementation here used secure_document_operation throughout.
    SEPAService should be enhanced with secure_document_operation in Phase 2B.

    TODO Phase 2B:
    - Add secure_document_operation to SEPAService.create_and_link_mandate_enhanced()
    - Add mandate superseding logic (not just cancellation)
    - Add member SEPA mandate link management with proper security
    """
    from verenigingen.utils.services import sepa_service

    # SEPAService uses "replace_existing" parameter instead of "replace_mandate"
    return sepa_service.create_and_link_mandate_enhanced(
        member=member,
        mandate_id=mandate_id,
        iban=iban,
        bic=bic,
        account_holder_name=account_holder_name,
        mandate_type=mandate_type,
        sign_date=sign_date,
        used_for_memberships=used_for_memberships,
        used_for_donations=used_for_donations,
        notes=notes,
        replace_existing=replace_mandate,  # Parameter name mapping
    )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def generate_mandate_reference(member):
    """Generate a suggested mandate reference for a member"""
    member_doc = frappe.get_doc("Member", member)

    member_id = member_doc.member_id or member_doc.name.replace("Assoc-Member-", "").replace("-", "")

    from datetime import datetime

    now_dt = datetime.now()
    date_str = now_dt.strftime("%Y%m%d")

    existing_mandates_today = frappe.get_all(
        "SEPA Mandate",
        filters={
            "mandate_id": ["like", f"M-{member_id}-{date_str}-%"],
            "creation": [">=", now_dt.strftime("%Y-%m-%d 00:00:00")],
        },
        fields=["mandate_id"],
    )

    sequence = len(existing_mandates_today) + 1
    sequence_str = str(sequence).zfill(3)

    suggested_reference = f"M-{member_id}-{date_str}-{sequence_str}"

    return {"mandate_reference": suggested_reference}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def validate_mandate_reference(mandate_id):
    """Validate if a mandate reference is available"""
    exists = frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id})

    return {"available": not bool(exists), "exists": bool(exists)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def check_and_handle_sepa_mandate(member, iban):
    """Check if a mandate exists for this IBAN and handle accordingly"""
    member_doc = frappe.get_doc("Member", member)

    matching_mandates = frappe.get_all(
        "SEPA Mandate",
        filters={"member": member, "iban": iban, "status": "Active", "is_active": 1},
        fields=["name"],
    )

    if matching_mandates:
        mandate_doc = frappe.get_doc("SEPA Mandate", matching_mandates[0].name)

        is_current = False
        for mandate_link in member_doc.sepa_mandates:
            if mandate_link.sepa_mandate == mandate_doc.name and mandate_link.is_current:
                is_current = True
                break

        if not is_current:
            for mandate_link in member_doc.sepa_mandates:
                if mandate_link.sepa_mandate == mandate_doc.name:
                    mandate_link.is_current = 1
                else:
                    mandate_link.is_current = 0

            from verenigingen.utils.secure_operations import secure_document_operation

            member_result = secure_document_operation(
                operation="save",
                doc=member_doc,
                justification=f"Set existing SEPA mandate {mandate_doc.name} as current for member {member}",
                required_permissions=["Member:write"],
            )
            if not member_result.success:
                frappe.throw(
                    _("Failed to update member mandate: {0}").format("; ".join(member_result.errors))
                )
            return {"action": "use_existing", "mandate": mandate_doc.name}
        else:
            return {"action": "none_needed"}
    else:
        return {"action": "create_new"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def need_new_mandate(member, iban):
    """Check if we need to create a new mandate for this IBAN"""
    matching_mandates = frappe.get_all(
        "SEPA Mandate",
        filters={"member": member, "iban": iban, "status": "Active", "is_active": 1},
        fields=["name"],
    )

    return {"need_new": not bool(matching_mandates)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_and_link_mandate(
    member,
    iban,
    bic=None,
    account_holder_name=None,
    mandate_type="RCUR",
    sign_date=None,
    used_for_memberships=1,
    used_for_donations=0,
):
    """Create a new mandate and link it to the member in one atomic operation"""
    if not member or not iban:
        frappe.throw(_("Member and IBAN are required"))

    if not sign_date:
        sign_date = today()

    member_doc = frappe.get_doc("Member", member)
    if not account_holder_name:
        account_holder_name = member_doc.full_name

    existing_mandates = frappe.get_all(
        "SEPA Mandate", filters={"member": member, "status": "Active", "is_active": 1}, fields=["name"]
    )

    if used_for_memberships:
        for mandate_data in existing_mandates:
            mandate = frappe.get_doc("SEPA Mandate", mandate_data.name)
            if mandate.used_for_memberships:
                mandate.status = "Suspended"
                mandate.is_active = 0
                from verenigingen.utils.secure_operations import secure_document_operation

                suspend_result = secure_document_operation(
                    operation="save",
                    doc=mandate,
                    justification=f"Suspend existing SEPA mandate {mandate.name} before creating new membership mandate for member {member}",
                    required_permissions=["SEPA Mandate:write"],
                )
                if not suspend_result.success:
                    frappe.throw(
                        _("Failed to suspend existing mandate: {0}").format("; ".join(suspend_result.errors))
                    )

    if used_for_donations:
        for mandate_data in existing_mandates:
            mandate = frappe.get_doc("SEPA Mandate", mandate_data.name)
            if mandate.used_for_donations and mandate.status == "Active":
                mandate.status = "Suspended"
                mandate.is_active = 0
                from verenigingen.utils.secure_operations import secure_document_operation

                suspend_result = secure_document_operation(
                    operation="save",
                    doc=mandate,
                    justification=f"Suspend existing donation SEPA mandate {mandate.name} for member {member}",
                    required_permissions=["SEPA Mandate:write"],
                )
                if not suspend_result.success:
                    frappe.throw(
                        _("Failed to suspend existing donation mandate: {0}").format(
                            "; ".join(suspend_result.errors)
                        )
                    )

    timestamp = now().replace(" ", "").replace("-", "").replace(":", "")[:14]
    mandate_id = f"M-{member_doc.member_id}-{timestamp}"

    mandate = frappe.new_doc("SEPA Mandate")
    mandate.mandate_id = mandate_id
    mandate.member = member
    mandate.member_name = member_doc.full_name
    mandate.account_holder_name = account_holder_name
    mandate.iban = iban
    if bic:
        mandate.bic = bic
    mandate.sign_date = sign_date
    mandate.mandate_type = mandate_type

    mandate.used_for_memberships = 1 if used_for_memberships else 0
    mandate.used_for_donations = 1 if used_for_donations else 0

    mandate.status = "Active"
    mandate.is_active = 1

    from verenigingen.utils.secure_operations import secure_document_operation

    mandate_result = secure_document_operation(
        operation="insert",
        doc=mandate,
        justification=f"Create new SEPA mandate {mandate_id} for member {member} with IBAN {iban}",
        required_permissions=["SEPA Mandate:create"],
    )
    if not mandate_result.success:
        error_details = "; ".join(mandate_result.errors)
        frappe.throw(
            _("Failed to create SEPA mandate {0} with IBAN {1} for member {2}: {3}").format(
                mandate_id, iban, member, error_details
            )
        )

    frappe.db.delete("Member SEPA Mandate Link", {"parent": member, "sepa_mandate": mandate.name})

    # Update member document with new mandate link using ORM
    member_doc = frappe.get_doc("Member", member)

    # Set all existing mandate links as inactive
    for mandate_link in member_doc.sepa_mandates:
        mandate_link.is_current = 0

    # Add new mandate link
    member_doc.append(
        "sepa_mandates",
        {
            "sepa_mandate": mandate.name,
            "is_current": 1,
            "mandate_reference": mandate.mandate_id,
            "status": "Active",
            "valid_from": mandate.sign_date,
        },
    )

    member_result = secure_document_operation(
        operation="save",
        doc=member_doc,
        justification=f"Link new SEPA mandate {mandate.name} to member {member}",
        required_permissions=["Member:write"],
    )
    if not member_result.success:
        error_details = "; ".join(member_result.errors)
        frappe.throw(
            _("Failed to link SEPA mandate {0} to member {1}: {2}").format(
                mandate.name, member, error_details
            )
        )

    return mandate.name


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def debug_postal_code_matching(postal_code):
    """Debug function to test postal code matching"""
    if not postal_code:
        return {"error": "No postal code provided"}

    chapters = frappe.get_all("Chapter", filters={"published": 1}, fields=["name", "region", "postal_codes"])

    results = {
        "postal_code": postal_code,
        "total_chapters": len(chapters),
        "matching_chapters": [],
        "non_matching_chapters": [],
    }

    for chapter in chapters:
        if not chapter.get("postal_codes"):
            results["non_matching_chapters"].append(
                {"name": chapter.name, "reason": "No postal codes defined"}
            )
            continue

        try:
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            matches = chapter_doc.matches_postal_code(postal_code)

            if matches:
                results["matching_chapters"].append(
                    {"name": chapter.name, "region": chapter.region, "postal_codes": chapter.postal_codes}
                )
            else:
                results["non_matching_chapters"].append(
                    {"name": chapter.name, "postal_codes": chapter.postal_codes, "reason": "No match"}
                )
        except Exception as e:
            results["non_matching_chapters"].append({"name": chapter.name, "reason": f"Error: {str(e)}"})

    return results


def sync_member_counter_with_settings(doc, method=None):
    """Called when Verenigingen Settings is updated"""
    from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

    if doc.doctype != "Verenigingen Settings":
        return

    if doc.has_value_changed("member_id_start"):
        old_start = cint(doc.get_db_value("member_id_start")) or 1000
        new_start = cint(doc.member_id_start) or 1000

        if new_start > old_start:
            MemberIDManager.sync_counter_with_settings()
