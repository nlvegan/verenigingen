"""
Bank Details Form for Members
Allows members to view and update their bank details and manage SEPA Direct Debit
"""


import frappe
from frappe import _


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

    # Get member record
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        # Try alternative lookup by user field
        member = frappe.db.get_value("Member", {"user": frappe.session.user})

    if not member:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    context.member = frappe.get_doc("Member", member)

    # Get current bank details
    current_details = {
        "iban": context.member.iban,
        "bic": context.member.bic,
        "bank_account_name": context.member.bank_account_name,
    }
    context.current_details = current_details

    # Check for active SEPA mandate
    context.current_mandate = get_active_sepa_mandate(member)

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for bank details page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    if not member:
        member = frappe.db.get_value("Member", {"user": user})
    return bool(member)


@frappe.whitelist(allow_guest=False)
def update_bank_details():
    """Handle bank details form submission"""

    try:
        # Write to a debug file to see if function is called
        debug_msg = f"BANK DETAILS UPDATE CALLED - User: {frappe.session.user} - Time: {frappe.utils.now()}\n"
        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write(debug_msg)

        # Log incoming request details
        frappe.logger().info("=== BANK DETAILS UPDATE START ===")
        frappe.logger().info(f"User: {frappe.session.user}")

        # Safely check for request method
        request_method = getattr(frappe.local, "request", None)
        if request_method and hasattr(request_method, "method"):
            frappe.logger().info(f"Request method: {request_method.method}")
        else:
            frappe.logger().info("Request method: Not available (direct execution)")

        frappe.logger().info(f"Form dict keys: {list(frappe.local.form_dict.keys())}")
        frappe.logger().info(f"Raw form dict: {frappe.local.form_dict}")

        # Get member
        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write("DEBUG: Starting member lookup\n")

        member_name = frappe.db.get_value("Member", {"email": frappe.session.user})
        if not member_name:
            # Try alternative lookup by user field
            member_name = frappe.db.get_value("Member", {"user": frappe.session.user})

        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write(f"DEBUG: Member lookup result: {member_name}\n")

        if not member_name:
            frappe.logger().error(f"No member record found for user: {frappe.session.user}")
            frappe.throw(_("No member record found"), frappe.DoesNotExistError)

        frappe.logger().info(f"Found member: {member_name}")
        member = frappe.get_doc("Member", member_name)

        # Get form data with error handling
        try:
            with open("/tmp/bank_details_debug.log", "a") as f:
                f.write("DEBUG: Starting form data parsing\n")

            form_data = frappe.local.form_dict
            frappe.logger().info(f"Form data received: {form_data}")

            with open("/tmp/bank_details_debug.log", "a") as f:
                f.write(f"DEBUG: Form data: {form_data}\n")

            new_iban = form_data.get("iban", "").replace(" ", "").upper()
            new_bic = form_data.get("bic", "").strip().upper()
            new_account_holder = form_data.get("account_holder_name", "").strip()
            enable_dd = form_data.get("enable_direct_debit") == "on"

            with open("/tmp/bank_details_debug.log", "a") as f:
                f.write(
                    f"DEBUG: Parsed - IBAN: {new_iban}, BIC: {new_bic}, Holder: {new_account_holder}, DD: {enable_dd}\n"
                )

            frappe.logger().info(
                f"Parsed form data - IBAN: {new_iban}, BIC: {new_bic}, Account holder: {new_account_holder}, Enable DD: {enable_dd}"
            )

        except Exception as form_error:
            with open("/tmp/bank_details_debug.log", "a") as f:
                f.write(f"DEBUG: Form parsing error: {str(form_error)}\n")
            frappe.logger().error(f"Error parsing form data: {str(form_error)}")
            frappe.throw(_("Error processing form data: {0}").format(str(form_error)))

        # Validate required fields
        if not new_iban:
            frappe.throw(_("IBAN is required"))

        if not new_account_holder:
            frappe.throw(_("Account holder name is required"))

        # Validate IBAN format with comprehensive validation
        from verenigingen.utils.iban_validator import validate_iban

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

        # Determine action needed
        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write(
                f"DEBUG: Bank details changed: {bank_details_changed}, Current mandate: {current_mandate}\n"
            )

        action_needed = determine_mandate_action(
            current_mandate, current_payment_method, enable_dd, bank_details_changed
        )

        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write(f"DEBUG: Action needed: {action_needed}\n")

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

        # For now, let's skip the confirmation page and process directly
        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write("DEBUG: Processing bank details update directly\n")

        # Process the update directly by calling the confirm function
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

            with open("/tmp/bank_details_debug.log", "a") as f:
                f.write(f"DEBUG: Direct processing result: {result}\n")

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

            with open("/tmp/bank_details_debug.log", "a") as f:
                f.write(f"DEBUG: Success messages stored: {success_messages}\n")

            # Redirect to success page
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = "/bank_details_success"

        except Exception as process_error:
            with open("/tmp/bank_details_debug.log", "a") as f:
                f.write(f"DEBUG: Direct processing error: {str(process_error)}\n")
            frappe.throw(_("Failed to update bank details: {0}").format(str(process_error)))

        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write("DEBUG: Redirect response set\n")

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
    from verenigingen.utils.iban_validator import validate_iban

    result = validate_iban(iban)
    return result["valid"]


def derive_bic_from_dutch_iban(iban):
    """Derive BIC from Dutch IBAN bank code using centralized function"""
    from verenigingen.utils.iban_validator import derive_bic_from_iban

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

        # Check member lookup
        member_by_email = frappe.db.get_value("Member", {"email": current_user}, "name")
        member_by_user = frappe.db.get_value("Member", {"user": current_user}, "name")

        result = {
            "success": True,
            "user": current_user,
            "member_by_email": member_by_email,
            "member_by_user": member_by_user,
            "found_member": member_by_email or member_by_user,
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
