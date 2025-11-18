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
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
    standard_api,
)


def parse_mollie_customer_ids(customer_id_string, max_ids=10):
    """
    Safely parse and validate comma-separated Mollie customer IDs.

    Args:
        customer_id_string: String containing comma-separated customer IDs
        max_ids: Maximum number of IDs allowed (default 10, security limit)

    Returns:
        List of validated customer ID strings

    Raises:
        None - logs errors but returns empty list or truncated list on invalid input
    """
    if not customer_id_string:
        return []

    if not isinstance(customer_id_string, str):
        frappe.log_error(
            f"Invalid mollie_customer_id type: {type(customer_id_string).__name__}",
            "Mollie Customer ID Validation",
        )
        return []

    # Split on commas and strip whitespace
    customer_ids = [cid.strip() for cid in customer_id_string.split(",") if cid.strip()]

    # Enforce maximum limit to prevent DoS
    if len(customer_ids) > max_ids:
        frappe.log_error(
            f"Too many customer IDs ({len(customer_ids)}) exceeds limit of {max_ids}. Truncating.",
            "Mollie Customer ID Validation",
        )
        customer_ids = customer_ids[:max_ids]

    # Validate format - Mollie customer IDs match pattern: cst_[A-Za-z0-9]{10}
    import re

    customer_id_pattern = re.compile(r"^cst_[A-Za-z0-9]{10}$")
    validated_ids = []

    for cid in customer_ids:
        if customer_id_pattern.match(cid):
            validated_ids.append(cid)
        else:
            frappe.log_error(
                f"Invalid Mollie customer ID format: {cid}. Expected pattern: cst_[A-Za-z0-9]{{10}}",
                "Mollie Customer ID Validation",
            )

    return validated_ids


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

    # Get Mollie subscription information from both Member and Donor records
    mollie_customers = []

    # Check member record for Mollie customer ID (regardless of payment method)
    # Support comma-separated customer IDs for members with multiple Mollie accounts
    if context.member.mollie_customer_id:
        customer_ids = parse_mollie_customer_ids(context.member.mollie_customer_id, max_ids=5)
        for customer_id in customer_ids:
            mollie_customers.append(
                {
                    "customer_id": customer_id,
                    "subscription_id": context.member.mollie_subscription_id,
                    "status": context.member.subscription_status,
                    "next_payment_date": context.member.next_payment_date,
                    "cancelled_date": context.member.subscription_cancelled_date,
                    "source": "member",
                    "payment_method": context.member.payment_method,  # Track what it's used for
                }
            )

    # Check donor record for Mollie customer ID
    donor_records = frappe.get_all(
        "Donor",
        filters={"member": context.member.name, "mollie_customer_id": ["!=", ""]},
        fields=["name", "mollie_customer_id", "donor_name"],
        limit=1,
    )

    if donor_records:
        donor = donor_records[0]
        mollie_customers.append(
            {
                "customer_id": donor.mollie_customer_id,
                "subscription_id": None,  # Donor subscriptions handled differently
                "status": None,
                "next_payment_date": None,
                "cancelled_date": None,
                "source": "donor",
                "donor_name": donor.donor_name,
            }
        )

    # Store all Mollie customers (max 2: member + donor)
    context.mollie_customers = mollie_customers
    # Keep legacy field for backward compatibility
    context.mollie_subscription = mollie_customers[0] if mollie_customers else None

    # Get active dues schedule for displaying current rate
    if context.member.current_dues_schedule:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", context.member.current_dues_schedule)
            context.active_dues_schedule = {
                "name": schedule.name,
                "amount": schedule.dues_rate,  # Use dues_rate instead of amount
                "billing_frequency": schedule.billing_frequency,
            }
        except Exception:
            context.active_dues_schedule = None
    else:
        context.active_dues_schedule = None

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
@development_only_api(operation_type=OperationType.UTILITY)
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
@development_only_api(operation_type=OperationType.UTILITY)
def simple_test():
    """Simple test endpoint"""
    return {"status": "working", "user": frappe.session.user}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_subscription_details():
    """Get real-time subscription details from Mollie for the current user"""
    try:
        # Get member record using improved utility
        member_name = get_current_user_member_name_required()

        # CRITICAL SECURITY: Validate user can only access their own subscription details
        validate_member_ownership(member_name, _("You can only access your own subscription details"))

        member = frappe.get_doc("Member", member_name)

        # Collect Mollie customer IDs from MEMBER record only (not donor)
        # Dues pages should only check membership payment methods, not donation methods
        # Support comma-separated customer IDs for members with multiple Mollie accounts
        mollie_customer_ids = []

        # Check member record for Mollie customer ID
        if member.mollie_customer_id:
            customer_ids = parse_mollie_customer_ids(member.mollie_customer_id, max_ids=5)
            for customer_id in customer_ids:
                mollie_customer_ids.append(
                    {
                        "customer_id": customer_id,
                        "subscription_id": member.mollie_subscription_id,
                        "source": "member",
                        "local_status": member.subscription_status,
                        "local_cancelled_date": member.subscription_cancelled_date,
                    }
                )

        if not mollie_customer_ids:
            return {"status": "no_subscription", "message": _("No Mollie customer IDs found")}

        try:
            # Query Mollie API for all customer IDs (max 2)
            all_subscriptions = []

            for customer_info in mollie_customer_ids:
                customer_id = customer_info["customer_id"]

                # Use existing MollieDebugService to fetch ALL subscriptions (not just active)
                # This avoids relying on stored subscription_id which may point to canceled subscriptions
                try:
                    from verenigingen.services.mollie_debug_service import MollieDebugService

                    debug_service = MollieDebugService()

                    # Fetch ALL subscriptions for this customer (active_only=False)
                    subscriptions_result = debug_service.list_subscriptions(
                        customer_id=customer_id,
                        limit=250,
                        active_only=False,  # Get both active AND canceled subscriptions
                    )

                    if subscriptions_result.get("error"):
                        # API error - add customer-only info with error
                        customer_only_info = {
                            "customer_id": customer_id,
                            "source": customer_info["source"],
                            "subscription": None,
                            "has_customer_only": True,
                            "error": subscriptions_result["error"],
                            "mandate_valid": False,  # Customer validation failed, so mandate is not valid
                        }
                        if customer_info.get("donor_name"):
                            customer_only_info["donor_name"] = customer_info["donor_name"]
                        all_subscriptions.append(customer_only_info)
                        continue

                    # Check mandate validity for this customer by querying Mollie directly
                    # Don't rely on database SEPA Mandate records which may be missing/outdated
                    mandate_valid = False
                    mandate_status = None

                    try:
                        # Query Mollie for ALL mandates for this customer
                        client = debug_service.mollie_client.sdk_client
                        customer_obj = client.customers.get(customer_id)
                        mandates = customer_obj.mandates.list()

                        # Check if any mandate has status="valid"
                        for mandate in mandates:
                            if mandate.status == "valid":
                                mandate_valid = True
                                mandate_status = "valid"
                                break
                            elif not mandate_status:  # Track first mandate status found
                                mandate_status = mandate.status

                    except Exception as mandate_error:
                        # Log but don't fail - customer might not have mandates yet
                        frappe.logger().debug(
                            f"No mandates found for customer {customer_id}: {str(mandate_error)}"
                        )

                    # Process each subscription returned by the service
                    subscriptions = subscriptions_result.get("subscriptions", [])

                    if not subscriptions:
                        # Customer exists but has no subscriptions
                        customer_only_info = {
                            "customer_id": customer_id,
                            "source": customer_info["source"],
                            "subscription": None,
                            "has_customer_only": True,
                            "note": "Customer found but no subscriptions",
                            "mandate_valid": mandate_valid,
                            "mandate_status": mandate_status,
                        }
                        if customer_info.get("donor_name"):
                            customer_only_info["donor_name"] = customer_info["donor_name"]
                        all_subscriptions.append(customer_only_info)
                    else:
                        # Add each subscription to the results
                        for sub in subscriptions:
                            # Parse amount - MollieDebugService returns formatted string like "EUR 25.00"
                            # We need to extract the numeric value and currency
                            amount_value = 0.0
                            currency = "EUR"

                            amount_field = sub.get("amount")
                            if isinstance(amount_field, str):
                                # Format: "EUR 25.00" or "25.00 EUR"
                                parts = amount_field.split()
                                if len(parts) >= 2:
                                    # Try to parse - could be "EUR 25.00" or "25.00 EUR"
                                    try:
                                        amount_value = float(parts[1] if parts[0].isalpha() else parts[0])
                                        currency = parts[0] if parts[0].isalpha() else parts[1]
                                    except (ValueError, IndexError):
                                        frappe.log_error(f"Failed to parse amount string: {amount_field}")
                            elif isinstance(amount_field, dict):
                                # Fallback if format changes - handle raw Mollie format
                                amount_value = float(amount_field.get("value", 0))
                                currency = amount_field.get("currency", "EUR")

                            subscription_info = {
                                "customer_id": customer_id,
                                "subscription_id": sub.get("id"),
                                "source": customer_info["source"],
                                "subscription": {
                                    "id": sub.get("id"),
                                    "status": sub.get("status"),
                                    "amount": amount_value,
                                    "currency": currency,
                                    "interval": sub.get("interval"),
                                    "next_payment_date": sub.get("next_payment_date"),
                                    "is_active": sub.get("status") == "active",
                                    "is_canceled": sub.get("status") == "canceled",
                                    "description": sub.get("description"),
                                },
                                "member_status": {
                                    "local_status": customer_info.get("local_status"),
                                    "cancelled_date": customer_info.get("local_cancelled_date"),
                                },
                                "mandate_valid": mandate_valid,
                                "mandate_status": mandate_status,
                            }
                            # Add source-specific metadata
                            if customer_info["source"] == "donor":
                                subscription_info["donor_name"] = customer_info.get("donor_name")

                            all_subscriptions.append(subscription_info)

                except Exception as mollie_error:
                    frappe.log_error(
                        f"Error querying Mollie subscriptions for {customer_id}: {str(mollie_error)}",
                        "Mollie Subscription Query",
                    )
                    # Fallback to customer-only info
                    customer_only_info = {
                        "customer_id": customer_id,
                        "source": customer_info["source"],
                        "subscription": None,
                        "has_customer_only": True,
                        "error": "Could not fetch subscription data",
                        "mandate_valid": False,  # Error occurred, so mandate is not valid
                    }
                    if customer_info.get("donor_name"):
                        customer_only_info["donor_name"] = customer_info["donor_name"]
                    all_subscriptions.append(customer_only_info)

            return {
                "status": "success",
                "subscriptions": all_subscriptions,
                "total_customers": len(mollie_customer_ids),
            }

        except Exception as subscription_error:
            frappe.log_error(
                f"Error fetching subscription data: {str(subscription_error)}", "Subscription Data Fetch"
            )
            # Fallback to stored member data (sanitize error message)
            return {
                "status": "fallback",
                "subscription": {
                    "status": member.subscription_status,
                    "next_payment_date": member.next_payment_date,
                },
                "member_status": {
                    "local_status": member.subscription_status,
                    "cancelled_date": member.subscription_cancelled_date,
                },
                "message": _("Unable to fetch current data, showing last known status"),
            }

    except Exception as e:
        frappe.log_error(f"Error in get_subscription_details: {str(e)}", "Bank Details Subscription Data")
        return {"status": "error", "message": _("Error retrieving subscription details")}


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


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def cancel_specific_subscription():
    """Cancel a specific Mollie subscription by customer ID and subscription ID"""
    try:
        # Get request data from form
        data = frappe.local.form_dict
        customer_id = data.get("customer_id")
        subscription_id = data.get("subscription_id")

        frappe.logger().info(
            f"Cancel subscription request: customer={customer_id}, subscription={subscription_id}"
        )

        if not customer_id or not subscription_id:
            frappe.throw(_("Customer ID and Subscription ID are required"))

        # Get member record using improved utility
        member_name = get_current_user_member_name_required()

        # CRITICAL SECURITY: Validate user can only cancel their own subscriptions
        validate_member_ownership(member_name, _("You can only cancel your own subscriptions"))

        # Verify the customer ID belongs to this member (member or donor record)
        # Support comma-separated customer IDs
        member = frappe.get_doc("Member", member_name)
        authorized_customer_ids = []

        # Check member record - handle comma-separated customer IDs with validation
        if member.mollie_customer_id:
            customer_ids = parse_mollie_customer_ids(member.mollie_customer_id, max_ids=5)
            authorized_customer_ids.extend(customer_ids)

        # Check donor records
        donor_records = frappe.get_all(
            "Donor",
            filters={"member": member_name, "mollie_customer_id": ["!=", ""]},
            fields=["mollie_customer_id"],
        )
        for donor in donor_records:
            # Donor records may also have comma-separated IDs
            if donor.mollie_customer_id:
                donor_customer_ids = parse_mollie_customer_ids(donor.mollie_customer_id, max_ids=5)
                authorized_customer_ids.extend(donor_customer_ids)

        if customer_id not in authorized_customer_ids:
            frappe.throw(_("You are not authorized to cancel subscriptions for this customer"))

        # Cancel the subscription using MollieDebugService (reuses existing tested code)
        from verenigingen.services.mollie_debug_service import MollieDebugService

        frappe.logger().info(
            f"User {frappe.session.user} cancelling subscription {subscription_id} for customer {customer_id}"
        )

        debug_service = MollieDebugService()
        result = debug_service.admin_cancel_subscription(
            customer_id=customer_id,
            subscription_id=subscription_id,
            reason=f"User-initiated cancellation via bank details page by {frappe.session.user}",
        )

        # If cancellation was successful, clear the subscription ID from member record
        if result.get("status") == "success":
            # Check if this subscription ID matches the member's subscription
            if member.mollie_subscription_id == subscription_id:
                member.db_set("mollie_subscription_id", None)
                frappe.logger().info(
                    f"Cleared mollie_subscription_id from member {member_name} after successful cancellation"
                )

        return result

    except Exception as e:
        error_msg = f"Error cancelling subscription {subscription_id}: {str(e)}"
        frappe.log_error(error_msg)
        frappe.throw(_(f"Failed to cancel subscription: {str(e)}"))


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.MEMBER_DATA)
def calculate_subscription_start_date(member_id=None):
    """
    Calculate the optimal start date for a Mollie subscription based on member's payment status.

    Logic:
    - If member is fully up-to-date with payments: schedule for next period (min 2 months ahead)
    - If member has unpaid invoices for current period: try to schedule ASAP (current period if possible)
    - Returns the 25th (or configured day) of the first eligible month from Mollie Settings

    Returns:
        dict: {"start_date": "YYYY-MM-DD", "reason": "explanation"}
    """
    try:
        # Get member
        if not member_id:
            member_id = get_current_user_member_name_required()
        else:
            validate_member_ownership(member_id)

        member_doc = frappe.get_doc("Member", member_id)

        # Check if member has unpaid invoices for current/past periods
        has_overdue = False
        if member_doc.customer:
            from verenigingen.utils.constants import PaymentStatus

            overdue_count = frappe.db.count(
                "Sales Invoice",
                {"customer": member_doc.customer, "status": PaymentStatus.INVOICE_OVERDUE, "docstatus": 1},
            )
            has_overdue = overdue_count > 0

        # Get Mollie settings
        mollie_settings = frappe.get_single("Mollie Settings")

        # Determine min_months_ahead based on payment status
        if has_overdue:
            # Member is behind - try to schedule ASAP
            min_months_ahead = 0
            reason = "Member has overdue payments - scheduling for earliest available period"
        else:
            # Member is up-to-date - schedule for next period
            min_months_ahead = 2
            reason = "Member is up-to-date - scheduling for next payment period"

        # Calculate start date using Mollie Settings logic
        start_date = mollie_settings.get_next_payment_date_for_scheduled_months(min_months_ahead)

        if not start_date:
            # No quarterly/yearly months configured - use monthly default
            from datetime import datetime

            from dateutil.relativedelta import relativedelta

            payment_day = (
                int(mollie_settings.payment_day_of_month) if mollie_settings.payment_day_of_month else 25
            )
            today = datetime.now().date()
            next_month = today + relativedelta(months=1)
            start_date = datetime(next_month.year, next_month.month, min(payment_day, 28)).strftime(
                "%Y-%m-%d"
            )
            reason += " (using monthly default - no quarterly/yearly months configured)"

        return {"status": "success", "start_date": start_date, "reason": reason, "has_overdue": has_overdue}

    except Exception as e:
        frappe.log_error(f"Error calculating subscription start date: {str(e)}")
        return {"status": "error", "error": str(e)}


@frappe.whitelist(allow_guest=False)
@development_only_api(operation_type=OperationType.UTILITY)
def test_cancel_subscription():
    """Test cancellation with known customer/subscription IDs"""
    try:
        # Use the known active subscription from our debug
        customer_id = "cst_DNZCrmyjcR"
        subscription_id = "sub_zLL2uwSN2x"  # €25 daily subscription

        frappe.logger().info(f"TEST: Cancelling subscription {subscription_id} for customer {customer_id}")

        from verenigingen.integrations.mollie.core.client import MollieClient

        mollie_client = MollieClient()
        result = mollie_client.cancel_subscription(customer_id, subscription_id)

        return {
            "status": "success",
            "result": str(result),
            "message": f"Test cancellation successful for {subscription_id}",
        }

    except Exception as e:
        frappe.log_error(f"Test cancellation error: {str(e)}")
        return {"status": "error", "error": str(e), "message": f"Test cancellation failed: {str(e)}"}
