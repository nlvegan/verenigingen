"""
Bank Details Form for Members
Allows members to view and update their bank details and manage SEPA Direct Debit
"""

import frappe
from frappe import _

# Import standardized member utilities
from verenigingen.utils.member_utils import (
    get_current_user_member_doc,
    get_current_user_member_name,
    get_current_user_member_name_required,
    get_member_name_for_user,
    validate_member_ownership,
)

# Import security framework for proper API protection
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


def get_context(context):
    """Get context for bank details form"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Bank Details")

    # Ensure CSRF token is available
    context.csrf_token = frappe.session.csrf_token

    # Get member record using standardized utility
    context.member = get_current_user_member_doc()

    # Get current bank details
    current_details = {
        "iban": context.member.iban,
        "bic": context.member.bic,
        "bank_account_name": context.member.bank_account_name,
    }
    context.current_details = current_details

    # Check for active SEPA mandate
    context.current_mandate = get_active_sepa_mandate(context.member.name)

    # Get Mollie subscription information if member uses Mollie
    if context.member.payment_method == "Mollie" and context.member.mollie_customer_id:
        context.mollie_subscription = {
            "customer_id": context.member.mollie_customer_id,
            "subscription_id": context.member.mollie_subscription_id,
            "status": context.member.subscription_status,
            "next_payment_date": context.member.next_payment_date,
            "cancelled_date": context.member.subscription_cancelled_date,
        }
    else:
        context.mollie_subscription = None

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for bank details page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    # Use standardized member lookup utility
    member = get_member_name_for_user(user)
    return bool(member)


@frappe.whitelist(allow_guest=False)
def update_bank_details():
    """Handle bank details form submission"""

    try:
        # Log function entry for audit purposes
        frappe.logger().info(f"Bank details update requested by user: {frappe.session.user}")

        # Get member record for current user using improved utility
        member_name = get_current_user_member_name_required()

        frappe.logger().info(f"Found member: {member_name}")
        member = frappe.get_doc("Member", member_name)

        # Parse and validate form data
        try:
            form_data = frappe.local.form_dict
            new_iban = form_data.get("iban", "").replace(" ", "").upper()
            new_bic = form_data.get("bic", "").strip().upper()
            new_account_holder = form_data.get("account_holder_name", "").strip()
            enable_dd = form_data.get("enable_direct_debit") == "on"

        except Exception as form_error:
            frappe.logger().error(f"Error parsing form data: {str(form_error)}")
            frappe.throw(_("Error processing form data: {0}").format(str(form_error)))

        # Validate required fields
        if not new_iban:
            frappe.throw(_("IBAN is required"))

        if not new_account_holder:
            frappe.throw(_("Account holder name is required"))

        # Validate IBAN format with comprehensive validation
        from verenigingen.utils.validation.iban_validator import validate_iban

        validation_result = validate_iban(new_iban)
        if not validation_result["valid"]:
            frappe.throw(_(validation_result["message"]))

        # Auto-derive BIC for Dutch IBANs if not provided
        if not new_bic and new_iban.startswith("NL"):
            new_bic = derive_bic_from_dutch_iban(new_iban)

        # Check if bank details changed
        bank_details_changed = (
            member.iban != new_iban or member.bic != new_bic or member.bank_account_name != new_account_holder
        )

        # Get current SEPA mandate status
        current_mandate = get_active_sepa_mandate(member_name)
        current_payment_method = member.payment_method

        # Determine action needed for SEPA mandate
        action_needed = determine_mandate_action(
            current_mandate, current_payment_method, enable_dd, bank_details_changed
        )

        # Prepare context for confirmation page (serialize member object) - unused
        # context = {
        #     "member_name": member.name,
        #     "member_full_name": member.full_name,
        #     "new_iban": new_iban,
        #     "new_bic": new_bic,
        #     "new_account_holder": new_account_holder,
        #     "enable_dd": enable_dd,
        #     "bank_details_changed": bank_details_changed,
        #     "current_mandate": current_mandate,
        #     "action_needed": action_needed,
        #     "current_payment_method": current_payment_method,
        # }

        # Process the update directly using the confirmation logic
        from verenigingen.templates.pages.bank_details_confirm import process_bank_details_update_direct

        try:
            result = process_bank_details_update_direct(
                member_name=member.name,
                new_iban=new_iban,
                new_bic=new_bic,
                new_account_holder=new_account_holder,
                enable_dd=enable_dd,
                action_needed=action_needed,
                current_mandate=current_mandate,
            )

            # Log successful processing
            frappe.logger().info(f"Bank details updated successfully for member: {member.name}")

            # Prepare detailed success messages
            success_messages = []

            # Bank details update message
            success_messages.append(_("Your bank details have been updated successfully"))
            success_messages.append(_("IBAN: {0}").format(format_iban_display(new_iban)))
            success_messages.append(_("Account Holder: {0}").format(new_account_holder))
            if new_bic:
                success_messages.append(_("BIC: {0}").format(new_bic))

            # Payment method change message
            if enable_dd:
                success_messages.append(_("Payment method changed to SEPA Direct Debit"))

            # SEPA mandate messages based on processing result
            if result.get("mandate_result"):
                mandate_result = result["mandate_result"]
                if mandate_result.get("success"):
                    method = mandate_result.get("method", "unknown")
                    mandate_id = mandate_result.get("mandate_id", "")

                    if action_needed == "create_mandate":
                        if method == "direct":
                            success_messages.append(
                                _(
                                    "A new SEPA Direct Debit mandate has been created and activated immediately"
                                )
                            )
                            if mandate_id:
                                success_messages.append(_("Mandate ID: {0}").format(mandate_id))
                        else:
                            success_messages.append(
                                _("A new SEPA Direct Debit mandate will be created within 24 hours")
                            )
                    elif action_needed == "replace_mandate":
                        if method == "direct":
                            success_messages.append(
                                _("Your SEPA mandate has been updated with the new bank details")
                            )
                        else:
                            success_messages.append(_("Your SEPA mandate will be updated within 24 hours"))
                    elif action_needed == "keep_mandate":
                        success_messages.append(_("Your existing SEPA Direct Debit mandate remains active"))

            # Store success messages in session
            frappe.session["bank_details_success"] = success_messages

            # Redirect to success page
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = "/bank_details_success"

        except Exception as process_error:
            frappe.logger().error(f"Bank details processing failed: {str(process_error)}")
            frappe.throw(_("Failed to update bank details: {0}").format(str(process_error)))

    except Exception as e:
        # Log the full error for debugging
        import traceback

        frappe.logger().error(f"Bank details update error: {str(e)}")
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")

        # Return a user-friendly error
        frappe.logger().error("=== BANK DETAILS UPDATE FAILED ===")
        frappe.throw(
            _(
                "An error occurred while processing your bank details. Please try again or contact support. Error: {0}"
            ).format(str(e))
        )


def validate_iban_format(iban):
    """Validate IBAN format using comprehensive validation"""
    from verenigingen.utils.validation.iban_validator import validate_iban

    result = validate_iban(iban)
    return result["valid"]


def derive_bic_from_dutch_iban(iban):
    """Derive BIC from Dutch IBAN bank code using centralized function"""
    from verenigingen.utils.validation.iban_validator import derive_bic_from_iban

    return derive_bic_from_iban(iban)


def format_iban_display(iban):
    """Format IBAN for display with spaces every 4 characters"""
    if not iban:
        return ""
    # Remove any existing spaces and format with spaces every 4 characters
    clean_iban = iban.replace(" ", "")
    return " ".join(clean_iban[i : i + 4] for i in range(0, len(clean_iban), 4))


def get_active_sepa_mandate(member_name):
    """Get active SEPA mandate for member"""
    try:
        mandate = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member_name, "status": "Active", "is_active": 1},
            fields=["name", "mandate_id", "iban", "account_holder_name", "status"],
            limit=1,
        )
        return mandate[0] if mandate else None
    except Exception:
        return None


def determine_mandate_action(current_mandate, current_payment_method, enable_dd, bank_details_changed):
    """Determine what action is needed for SEPA mandate"""

    if enable_dd:
        if current_mandate:
            if bank_details_changed:
                return "replace_mandate"  # Cancel current, create new
            else:
                return "keep_mandate"  # Keep existing
        else:
            return "create_mandate"  # Create new
    else:
        if current_mandate:
            return "cancel_mandate"  # Cancel existing
        else:
            return "no_mandate"  # No mandate needed

    return "no_action"


@frappe.whitelist()
def test_bank_details_api():
    """Test function to check if the bank details API is accessible"""
    try:
        current_user = frappe.session.user
        frappe.logger().info(f"Test API called by user: {current_user}")

        # Check member lookup using standardized utility
        member = get_member_name_for_user(current_user)

        result = {
            "success": True,
            "user": current_user,
            "member": member,
            "found_member": bool(member),
            "message": "Bank details API is accessible",
        }

        frappe.logger().info(f"Test API result: {result}")
        return result

    except Exception as e:
        frappe.logger().error(f"Test API error: {str(e)}")
        import traceback

        frappe.logger().error(f"Test API traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e), "message": "Bank details API test failed"}


@frappe.whitelist(allow_guest=False)
def debug_form_submission():
    """Debug endpoint to test form submission"""
    try:
        frappe.logger().info("=== DEBUG FORM SUBMISSION ===")
        frappe.logger().info(f"User: {frappe.session.user}")
        frappe.logger().info(f"Form data: {frappe.local.form_dict}")

        return {
            "success": True,
            "user": frappe.session.user,
            "form_data": dict(frappe.local.form_dict),
            "message": "Debug endpoint working",
        }
    except Exception as e:
        frappe.logger().error(f"Debug endpoint error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def simple_test():
    """Simple test endpoint"""
    return {"status": "working", "user": frappe.session.user}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def cancel_subscription():
    """Cancel Mollie subscription for the current user - with proper security framework"""
    try:
        # Get member record using improved utility with automatic error handling
        member_name = get_current_user_member_name_required()
        member = frappe.get_doc("Member", member_name)

        # Verify member has Mollie subscription
        if not (
            member.payment_method == "Mollie" and member.mollie_customer_id and member.mollie_subscription_id
        ):
            frappe.throw(_("No active Mollie subscription found"))

        # Verify subscription is active
        if member.subscription_status in ["cancelled", "inactive", "expired"]:
            frappe.throw(_("Subscription is already cancelled or inactive"))

        # Import and call the subscription cancellation function
        from verenigingen.verenigingen_payments.utils.payment_gateways import cancel_member_subscription

        result = cancel_member_subscription(member_name)

        if result.get("status") == "success":
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = "/bank_details?cancelled=1"
        else:
            frappe.throw(_(result.get("message", "Failed to cancel subscription")))

    except Exception as e:
        frappe.log_error(f"Web subscription cancellation error: {str(e)}", "Bank Details Subscription Cancel")
        frappe.throw(
            _("An error occurred while cancelling your subscription. Please try again or contact support.")
        )
