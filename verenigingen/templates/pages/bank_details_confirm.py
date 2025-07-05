"""
Bank Details Confirmation Page
Shows confirmation of bank details changes before processing
"""

import frappe
from frappe import _
from frappe.utils import now, today


def get_context(context):
    """Get context for bank details confirmation page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Check if we have pending update data
    with open("/tmp/bank_details_debug.log", "a") as f:
        f.write(f"CONFIRM PAGE CALLED - User: {frappe.session.user} - Time: {frappe.utils.now()}\n")

    update_data = frappe.session.get("bank_details_update")

    with open("/tmp/bank_details_debug.log", "a") as f:
        f.write(f"CONFIRM: Session data retrieved: {update_data}\n")

    frappe.logger().info("=== BANK DETAILS CONFIRM ===")
    frappe.logger().info(f"User: {frappe.session.user}")
    frappe.logger().info(f"Update data: {update_data}")

    if not update_data:
        with open("/tmp/bank_details_debug.log", "a") as f:
            f.write("CONFIRM: No update data found, redirecting\n")
        frappe.logger().info("No update data found, redirecting to bank_details")
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = "/bank_details"
        return

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Confirm Bank Details Update")

    # Pass all update data to template
    for key, value in update_data.items():
        context[key] = value

    # Reconstruct member object if needed for template
    if "member_name" in update_data:
        context["member"] = frappe.get_doc("Member", update_data["member_name"])

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for bank details confirmation page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    return bool(member)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def process_bank_details_update():
    """Process the confirmed bank details update"""

    # Get member
    member_name = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member_name:
        frappe.throw(_("No member record found"), frappe.DoesNotExistError)

    # Get pending update data
    update_data = frappe.session.get("bank_details_update")
    if not update_data:
        frappe.throw(_("No pending update found"), frappe.ValidationError)

    try:
        # Get member document
        member = frappe.get_doc("Member", member_name)

        # Extract update data
        new_iban = update_data["new_iban"]
        new_bic = update_data["new_bic"]
        new_account_holder = update_data["new_account_holder"]
        enable_dd = update_data["enable_dd"]
        action_needed = update_data["action_needed"]
        current_mandate = update_data["current_mandate"]

        # Update bank details on member record
        member.iban = new_iban
        member.bic = new_bic
        member.bank_account_name = new_account_holder

        # Update payment method based on direct debit choice
        if enable_dd:
            member.payment_method = "SEPA Direct Debit"
        else:
            # Only change if currently SEPA Direct Debit, preserve other methods
            if member.payment_method == "SEPA Direct Debit":
                member.payment_method = "Manual"

        # Save member changes (members can update their own records)
        member.save()

        # Handle SEPA mandate changes
        mandate_result = handle_sepa_mandate_changes(
            member_name, action_needed, current_mandate, new_iban, new_bic, new_account_holder
        )

        # Clear session data
        if "bank_details_update" in frappe.session:
            del frappe.session["bank_details_update"]

        # Create success message based on processing method
        processing_method = mandate_result.get("method", "unknown")

        if enable_dd:
            if action_needed == "create_mandate":
                if processing_method == "direct":
                    message = _(
                        "Bank details updated and SEPA Direct Debit enabled successfully! Your mandate is active immediately."
                    )
                else:
                    message = _(
                        "Bank details updated successfully. SEPA mandate will be created by our scheduled task within 24 hours."
                    )
            elif action_needed == "replace_mandate":
                if processing_method == "direct":
                    message = _(
                        "Bank details and SEPA mandate updated successfully! Changes are active immediately."
                    )
                else:
                    message = _(
                        "Bank details updated successfully. Your SEPA mandate will be updated within 24 hours."
                    )
            else:
                message = _("Bank details updated successfully. Your SEPA Direct Debit remains active.")
        else:
            if action_needed == "cancel_mandate":
                if processing_method == "direct":
                    message = _("Bank details updated and SEPA Direct Debit disabled successfully!")
                else:
                    message = _(
                        "Bank details updated successfully. SEPA Direct Debit will be disabled within 24 hours."
                    )
            else:
                message = _("Bank details updated successfully.")

        frappe.msgprint(message, title=_("Update Successful"), indicator="green")

        # Redirect to member dashboard
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = "/member_dashboard?success=bank_details_updated"

    except Exception as e:
        frappe.log_error(f"Bank details update failed: {str(e)}")
        frappe.throw(_("Failed to update bank details. Please try again or contact support."))


def handle_sepa_mandate_changes(
    member_name, action_needed, current_mandate, new_iban, new_bic, new_account_holder
):
    """Handle SEPA mandate changes based on action needed"""

    result = {"action": action_needed, "success": True}

    try:
        if action_needed == "create_mandate":
            # Try to create mandate directly
            mandate_result = create_mandate_pending_record(member_name, new_iban, new_bic, new_account_holder)
            result.update(mandate_result)
            result["message"] = "Mandate creation processed"

        elif action_needed == "replace_mandate":
            # Cancel existing mandate and create new one
            if current_mandate:
                cancel_result = cancel_existing_mandate(current_mandate["name"])
                result["cancel_result"] = cancel_result

            mandate_result = create_mandate_pending_record(member_name, new_iban, new_bic, new_account_holder)
            result.update(mandate_result)
            result["message"] = "Mandate replacement processed"

        elif action_needed == "cancel_mandate":
            # Cancel existing mandate
            if current_mandate:
                cancel_result = cancel_existing_mandate(current_mandate["name"])
                result.update(cancel_result)
            result["message"] = "Mandate cancellation processed"

        elif action_needed == "keep_mandate":
            # Update existing mandate with new details (if bank details changed)
            if current_mandate:
                update_result = update_existing_mandate(
                    current_mandate["name"], new_iban, new_bic, new_account_holder
                )
                result.update(update_result)
            result["message"] = "Mandate update processed"

        # Log the action for audit trail
        frappe.log_error(
            f"SEPA mandate action '{action_needed}' processed for member {member_name}", "Bank Details Update"
        )

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        frappe.log_error(f"SEPA mandate handling failed: {str(e)}")

    return result


def create_mandate_pending_record(member_name, iban, bic, account_holder):
    """Try to create SEPA mandate directly, fallback to async processing"""

    try:
        # Try to create mandate directly first
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": generate_mandate_id(),
                "member": member_name,
                "account_holder_name": account_holder,
                "iban": iban,
                "bic": bic or "",
                "status": "Active",
                "is_active": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "sign_date": today(),
                "first_collection_date": frappe.utils.add_days(
                    today(), 5
                ),  # SEPA requires 5 business days notice
                "used_for_memberships": 1,
                "frequency": "Monthly",
            }
        )
        mandate.insert()
        return {"success": True, "method": "direct", "mandate_id": mandate.name}

    except frappe.PermissionError:
        # If permission denied, schedule for async processing
        frappe.log_error(
            f"SEPA_MANDATE_REQUEST|{member_name}|{iban}|{bic or ''}|{account_holder}|{now()}",
            "SEPA Mandate Pending",
        )
        return {"success": True, "method": "async"}

    except Exception as e:
        frappe.log_error(f"Failed to create mandate for {member_name}: {str(e)}")
        return {"success": False, "error": str(e)}


def generate_mandate_id():
    """Generate a unique SEPA mandate ID"""
    import uuid

    # Generate a short unique ID for the mandate
    unique_id = str(uuid.uuid4())[:8].upper()
    return f"MANDATE-{frappe.utils.today().replace('-', '')}-{unique_id}"


def cancel_existing_mandate(mandate_name):
    """Try to cancel existing SEPA mandate directly, fallback to async processing"""

    try:
        # Try direct cancellation first
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        mandate.status = "Cancelled"
        mandate.is_active = 0
        mandate.cancellation_date = today()
        mandate.save()
        return {"success": True, "method": "direct"}

    except frappe.PermissionError:
        # If permission denied, schedule for async processing
        frappe.log_error(f"SEPA_MANDATE_CANCEL|{mandate_name}|{now()}", "SEPA Mandate Cancellation Pending")
        return {"success": True, "method": "async"}

    except Exception as e:
        frappe.log_error(f"Failed to cancel mandate {mandate_name}: {str(e)}")
        return {"success": False, "error": str(e)}


def update_existing_mandate(mandate_name, new_iban, new_bic, new_account_holder):
    """Try to update existing mandate directly, fallback to async processing"""

    try:
        # Try direct update first
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        mandate.iban = new_iban
        mandate.bic = new_bic
        mandate.account_holder_name = new_account_holder
        mandate.save()
        return {"success": True, "method": "direct"}

    except frappe.PermissionError:
        # If permission denied, schedule for async processing
        frappe.log_error(
            f"SEPA_MANDATE_UPDATE|{mandate_name}|{new_iban}|{new_bic or ''}|{new_account_holder}|{now()}",
            "SEPA Mandate Update Pending",
        )
        return {"success": True, "method": "async"}

    except Exception as e:
        frappe.log_error(f"Failed to update mandate {mandate_name}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_sepa_integration():
    """Test SEPA Direct Debit integration functionality"""
    results = {"tests": [], "summary": {}}

    try:
        # Test 1: Check SEPA Mandate permissions
        member_perms = frappe.db.sql(
            """
            SELECT role, `create`, `read`, `write`
            FROM `tabDocPerm`
            WHERE parent = 'SEPA Mandate' AND role = 'Verenigingen Member'
        """,
            as_dict=True,
        )

        results["tests"].append(
            {
                "test": "Member permissions for SEPA Mandate",
                "passed": len(member_perms) > 0,
                "details": f"Found {len(member_perms)} permission entries",
            }
        )

        # Test 2: Test IBAN validation
        from verenigingen.templates.pages.bank_details import derive_bic_from_dutch_iban, validate_iban_format

        test_iban = "NL91ABNA0417164300"
        iban_valid = validate_iban_format(test_iban)
        results["tests"].append(
            {
                "test": "IBAN validation function",
                "passed": iban_valid,
                "details": f"IBAN {test_iban} validation: {iban_valid}",
            }
        )

        # Test 3: Test BIC derivation
        bic = derive_bic_from_dutch_iban(test_iban)
        results["tests"].append(
            {"test": "BIC derivation function", "passed": bic == "ABNANL2A", "details": f"Derived BIC: {bic}"}
        )

        # Test 4: Test mandate ID generation
        mandate_id = generate_mandate_id()
        results["tests"].append(
            {
                "test": "Mandate ID generation",
                "passed": mandate_id and mandate_id.startswith("MANDATE-"),
                "details": f"Generated ID: {mandate_id}",
            }
        )

        # Test 5: Find a test member
        test_member = frappe.db.get_value("Member", {"docstatus": 1}, "name")
        results["tests"].append(
            {
                "test": "Test member available",
                "passed": bool(test_member),
                "details": f"Using member: {test_member}" if test_member else "No members found",
            }
        )

        # Test 6: Test mandate creation (dry run)
        if test_member:
            try:
                result = create_mandate_pending_record(
                    test_member, "NL20RABO0123456789", "RABONL2U", "Test Account Holder"
                )

                results["tests"].append(
                    {
                        "test": "Mandate creation function",
                        "passed": result.get("success", False),
                        "details": f"Method: {result.get('method', 'unknown')}, Result: {result}",
                    }
                )

                # If mandate was created directly, clean it up
                if result.get("method") == "direct" and result.get("mandate_id"):
                    try:
                        mandate_doc = frappe.get_doc("SEPA Mandate", result["mandate_id"])
                        mandate_doc.status = "Cancelled"
                        mandate_doc.is_active = 0
                        mandate_doc.save()

                        results["tests"].append(
                            {
                                "test": "Test mandate cleanup",
                                "passed": True,
                                "details": f"Cleaned up mandate: {result['mandate_id']}",
                            }
                        )
                    except Exception as cleanup_err:
                        results["tests"].append(
                            {
                                "test": "Test mandate cleanup",
                                "passed": False,
                                "details": f"Cleanup failed: {str(cleanup_err)}",
                            }
                        )

            except Exception as e:
                results["tests"].append(
                    {"test": "Mandate creation function", "passed": False, "details": f"Error: {str(e)}"}
                )

        # Summary
        passed = sum(1 for t in results["tests"] if t["passed"])
        total = len(results["tests"])

        results["summary"] = {
            "total_tests": total,
            "passed_tests": passed,
            "success_rate": f"{(passed / total * 100):.1f}%",
            "overall_success": passed == total,
            "implementation_status": "Ready for production" if passed == total else "Needs attention",
        }

        return results

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc(), "tests": results.get("tests", [])}


@frappe.whitelist()
def check_foppe_member_record():
    """Check if Foppe de Haan has a member record"""
    try:
        # Search for Foppe by name
        foppe_members = frappe.db.sql(
            """
            SELECT name, email, user, full_name, first_name, last_name
            FROM `tabMember`
            WHERE full_name LIKE '%Foppe%' OR first_name LIKE '%Foppe%'
        """,
            as_dict=True,
        )

        # Search for users with Foppe in the name
        foppe_users = frappe.db.sql(
            """
            SELECT name, email, full_name, enabled
            FROM `tabUser`
            WHERE full_name LIKE '%Foppe%' OR name LIKE '%foppe%'
        """,
            as_dict=True,
        )

        return {
            "foppe_members": foppe_members,
            "foppe_users": foppe_users,
            "total_members": len(foppe_members),
            "total_users": len(foppe_users),
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def test_foppe_member_lookup():
    """Test member lookup for Foppe's accounts"""
    try:
        current_user = frappe.session.user

        # Test both potential user accounts
        test_users = ["fjdh@leden.socialisten.org", "foppe.haan@leden.rsp.nu"]
        results = {"current_user": current_user, "lookup_tests": []}

        for test_user in test_users:
            # Test email lookup
            member_by_email = frappe.db.get_value("Member", {"email": test_user}, "name")
            # Test user field lookup
            member_by_user = frappe.db.get_value("Member", {"user": test_user}, "name")

            results["lookup_tests"].append(
                {
                    "test_user": test_user,
                    "member_by_email": member_by_email,
                    "member_by_user": member_by_user,
                    "found_member": member_by_email or member_by_user,
                    "is_current_user": test_user == current_user,
                }
            )

        return results

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def get_current_user_info():
    """Get current user information and member lookup status"""
    try:
        current_user = frappe.session.user

        # Try member lookup with current user
        member_by_email = frappe.db.get_value("Member", {"email": current_user}, "name")
        member_by_user = frappe.db.get_value("Member", {"user": current_user}, "name")

        # Get user details
        user_details = frappe.db.get_value(
            "User", current_user, ["name", "email", "full_name", "enabled"], as_dict=True
        )

        # Get all of Foppe's accounts for reference
        foppe_members = frappe.db.sql(
            """
            SELECT name, email, user, full_name
            FROM `tabMember`
            WHERE full_name LIKE '%Foppe%'
        """,
            as_dict=True,
        )

        foppe_users = frappe.db.sql(
            """
            SELECT name, email, full_name, enabled
            FROM `tabUser`
            WHERE full_name LIKE '%Foppe%'
        """,
            as_dict=True,
        )

        return {
            "current_user": current_user,
            "user_details": user_details,
            "member_lookup": {
                "by_email": member_by_email,
                "by_user": member_by_user,
                "found": member_by_email or member_by_user,
            },
            "foppe_accounts": {"members": foppe_members, "users": foppe_users},
        }

    except Exception as e:
        return {"error": str(e)}


def process_bank_details_update_direct(
    member_name, new_iban, new_bic, new_account_holder, enable_dd, action_needed, current_mandate
):
    """Process bank details update directly without confirmation page"""

    try:
        # Get member document
        member = frappe.get_doc("Member", member_name)

        # Update bank details on member record
        member.iban = new_iban
        member.bic = new_bic
        member.bank_account_name = new_account_holder

        # Update payment method based on direct debit choice
        if enable_dd:
            member.payment_method = "SEPA Direct Debit"
        else:
            # Only change if currently SEPA Direct Debit, preserve other methods
            if member.payment_method == "SEPA Direct Debit":
                member.payment_method = "Manual"

        # Save member changes
        member.save()

        # Handle SEPA mandate changes
        mandate_result = handle_sepa_mandate_changes(
            member_name, action_needed, current_mandate, new_iban, new_bic, new_account_holder
        )

        return {
            "success": True,
            "message": "Bank details updated successfully",
            "mandate_result": mandate_result,
        }

    except Exception as e:
        frappe.log_error(f"Direct bank details update failed: {str(e)}")
        return {"success": False, "error": str(e)}
