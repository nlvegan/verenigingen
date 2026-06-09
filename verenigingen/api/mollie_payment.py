"""
Mollie Payment API Endpoints

API endpoints for creating and managing Mollie payments and subscriptions.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.member_utils import (
    get_current_user_member_name_required,
    validate_member_ownership,
)
from verenigingen.utils.mollie_data_validator import parse_mollie_customer_ids
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, self_service_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_payment(donation_data: Dict[str, Any] = None) -> OperationResult[Dict[str, Any]]:
    """
    Create a Mollie payment for a donation.

    Args:
        donation_data: Payment data including amount, donor information, etc.

    Returns:
        OperationResult containing payment creation result
    """
    try:
        if not donation_data:
            donation_data = frappe.local.form_dict

        # Initialize Mollie payment service
        service = MolliePaymentService()

        # Create payment
        result = service.create_payment(donation_data)

        frappe.logger().info("Mollie payment created successfully")

        return OperationResult.ok({"payment_data": result}, message=_("Mollie payment created successfully"))

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Mollie payment creation failed: {error_msg}\n{traceback.format_exc()}")
        frappe.log_error(
            title="Mollie Payment API",
            message=f"Mollie payment creation failed: {error_msg}\n{traceback.format_exc()}",
        )

        return OperationResult.fail(
            error=_("Failed to create Mollie payment: {0}").format(error_msg), http_status=500
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_payment_status(payment_id: str) -> OperationResult[Dict[str, Any]]:
    """
    Get the status of a Mollie payment.

    Args:
        payment_id: Mollie payment ID

    Returns:
        OperationResult containing payment status information
    """
    try:
        if not payment_id:
            payment_id = frappe.local.form_dict.get("payment_id")

        if not payment_id:
            return OperationResult.fail(_("Payment ID is required"), http_status=400)

        # Initialize Mollie payment service
        service = MolliePaymentService()

        # Get payment status
        payment_data = service.get_payment(payment_id)

        return OperationResult.ok(
            {"payment": payment_data}, message=_("Payment status retrieved successfully")
        )

    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Failed to get Mollie payment status: {error_msg}\n{traceback.format_exc()}")
        frappe.log_error(
            title="Mollie Payment API",
            message=f"Failed to get Mollie payment status: {error_msg}\n{traceback.format_exc()}",
        )

        return OperationResult.fail(
            error=_("Failed to retrieve payment status: {0}").format(error_msg), http_status=500
        )


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
def get_subscription_details():
    """
    Get real-time subscription details from Mollie for the current user.

    Returns subscription information including status, next payment date,
    and mandate validity for all Mollie customer IDs associated with the member.
    """
    try:
        # Get member record using improved utility with automatic error handling
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
            # Query Mollie API for all customer IDs
            all_subscriptions = []

            for customer_info in mollie_customer_ids:
                customer_id = customer_info["customer_id"]

                # Use existing MollieDebugService to fetch ALL subscriptions (not just active)
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
                            "mandate_valid": False,
                        }
                        all_subscriptions.append(customer_only_info)
                        continue

                    # Check mandate validity for this customer by querying Mollie directly
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
                        all_subscriptions.append(customer_only_info)
                    else:
                        # Add each subscription to the results
                        for sub in subscriptions:
                            # Parse amount - MollieDebugService returns formatted string like "EUR 25.00"
                            amount_value = 0.0
                            currency = "EUR"

                            amount_field = sub.get("amount")
                            if isinstance(amount_field, str):
                                parts = amount_field.split()
                                if len(parts) >= 2:
                                    try:
                                        amount_value = float(parts[1] if parts[0].isalpha() else parts[0])
                                        currency = parts[0] if parts[0].isalpha() else parts[1]
                                    except (ValueError, IndexError):
                                        frappe.log_error(f"Failed to parse amount string: {amount_field}")
                            elif isinstance(amount_field, dict):
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
                            all_subscriptions.append(subscription_info)

                except Exception as mollie_error:
                    frappe.log_error(
                        f"Error querying Mollie subscriptions for {customer_id}: {str(mollie_error)}",
                        "Mollie Subscription Query",
                    )
                    customer_only_info = {
                        "customer_id": customer_id,
                        "source": customer_info["source"],
                        "subscription": None,
                        "has_customer_only": True,
                        "error": "Could not fetch subscription data",
                        "mandate_valid": False,
                    }
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
            # Fallback to stored member data
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
        frappe.log_error(f"Error in get_subscription_details: {str(e)}", "Mollie Subscription API")
        return {"status": "error", "message": _("Error retrieving subscription details")}


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def cancel_specific_subscription(customer_id: str = None, subscription_id: str = None):
    """
    Cancel a specific Mollie subscription by customer ID and subscription ID.

    Args:
        customer_id: Mollie customer ID (cst_xxx)
        subscription_id: Mollie subscription ID (sub_xxx)

    Returns:
        Dict with cancellation result
    """
    try:
        # Get request data from form if not provided as params
        if not customer_id:
            customer_id = frappe.local.form_dict.get("customer_id")
        if not subscription_id:
            subscription_id = frappe.local.form_dict.get("subscription_id")

        frappe.logger().info(
            f"Cancel subscription request: customer={customer_id}, subscription={subscription_id}"
        )

        if not customer_id or not subscription_id:
            frappe.throw(_("Customer ID and Subscription ID are required"))

        # Get member record using improved utility
        member_name = get_current_user_member_name_required()

        # CRITICAL SECURITY: Validate user can only cancel their own subscriptions
        validate_member_ownership(member_name, _("You can only cancel your own subscriptions"))

        # Verify the customer ID belongs to this member
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
            if donor.mollie_customer_id:
                donor_customer_ids = parse_mollie_customer_ids(donor.mollie_customer_id, max_ids=5)
                authorized_customer_ids.extend(donor_customer_ids)

        if customer_id not in authorized_customer_ids:
            frappe.throw(_("You are not authorized to cancel subscriptions for this customer"))

        # Cancel the subscription using MollieDebugService
        from verenigingen.services.mollie_debug_service import MollieDebugService

        frappe.logger().info(
            f"User {frappe.session.user} cancelling subscription {subscription_id} for customer {customer_id}"
        )

        debug_service = MollieDebugService()
        result = debug_service.admin_cancel_subscription(
            customer_id=customer_id,
            subscription_id=subscription_id,
            reason=f"User-initiated cancellation via payment dashboard by {frappe.session.user}",
        )

        # If cancellation was successful, clear the subscription ID from member record
        if result.get("status") == "success":
            # Check if this subscription ID matches the member's subscription
            if member.mollie_subscription_id == subscription_id:
                member.db_set("mollie_subscription_id", None)
                member.db_set("subscription_status", "cancelled")
                frappe.logger().info(
                    f"Cleared mollie_subscription_id from member {member_name} after successful cancellation"
                )

        return result

    except Exception as e:
        error_msg = f"Error cancelling subscription {subscription_id}: {str(e)}"
        frappe.log_error(error_msg, "Mollie Subscription Cancel")
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
def update_mollie_bank_account(iban: str = None, account_holder_name: str = None):
    """
    Update the bank account (mandate) on the member's active Mollie subscription.

    Creates a new Mollie SEPA Direct Debit mandate with the provided IBAN, then
    PATCHes the active subscription to use the new mandate.

    Args:
        iban: New IBAN for the bank account
        account_holder_name: Name on the bank account

    Returns:
        Dict with status, message, and masked IBAN on success
    """
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
        return {"status": "error", "message": _("IBAN is required")}
    if not account_holder_name:
        return {"status": "error", "message": _("Account holder name is required")}
    if len(account_holder_name) > 70:
        return {"status": "error", "message": _("Account holder name must not exceed 70 characters")}

    # Validate IBAN format
    validation_result = validate_iban(iban)
    if not validation_result.get("valid"):
        return {"status": "error", "message": validation_result.get("message", _("Invalid IBAN format"))}

    # Get and validate member
    member_name = get_current_user_member_name_required()
    validate_member_ownership(member_name, _("You can only update your own bank account"))

    member = frappe.get_doc("Member", member_name)

    # Verify member has Mollie subscription
    if not member.mollie_customer_id or not member.mollie_subscription_id:
        return {"status": "error", "message": _("No active Mollie subscription found")}

    customer_ids = parse_mollie_customer_ids(member.mollie_customer_id, max_ids=1)
    if not customer_ids:
        return {"status": "error", "message": _("Invalid or missing Mollie customer ID")}
    customer_id = customer_ids[0]
    subscription_id = member.mollie_subscription_id
    old_mandate_id = member.mollie_mandate_id

    # Derive BIC for Dutch IBANs
    bic = derive_bic_from_iban(iban) or None

    try:
        from verenigingen.services.mollie_debug_service import MollieDebugService

        service = MollieDebugService()

        # Step 1: Verify subscription is active
        client = service.mollie_client.sdk_client
        customer_obj = client.customers.get(customer_id)
        subscription = customer_obj.subscriptions.get(subscription_id)

        if subscription.status != "active":
            return {
                "status": "error",
                "message": _("Your subscription is not active. Cannot update bank account."),
            }

        # Step 2: Create new Mollie mandate with the new IBAN
        mandate_data = {
            "method": "directdebit",
            "consumerName": account_holder_name,
            "consumerAccount": iban,
            "signatureDate": frappe.utils.today(),
        }
        if bic:
            mandate_data["consumerBic"] = bic

        new_mandate = customer_obj.mandates.create(mandate_data)
        new_mandate_id = new_mandate.id

        # Step 3: PATCH subscription with new mandate
        try:
            service.update_subscription_mandate(
                customer_id=customer_id,
                subscription_id=subscription_id,
                new_mandate_id=new_mandate_id,
                reason=f"Bank account update by {frappe.session.user}",
            )
        except Exception as patch_error:
            # Rollback: revoke the newly created mandate
            try:
                customer_obj.mandates.delete(new_mandate_id)
            except Exception:
                frappe.logger().warning(
                    f"Could not revoke new mandate {new_mandate_id} after failed subscription update"
                )
            raise patch_error

        # Step 4: Update member record
        member.db_set("mollie_mandate_id", new_mandate_id, update_modified=False)
        frappe.db.commit()

        # Step 5: Best-effort cleanup of old mandate
        if old_mandate_id:
            try:
                customer_obj.mandates.delete(old_mandate_id)
            except Exception as revoke_error:
                frappe.logger().warning(f"Could not revoke old mandate {old_mandate_id}: {str(revoke_error)}")

        # Mask IBAN for response
        masked_iban = f"{iban[:2]}{'*' * (len(iban) - 6)}{iban[-4:]}" if len(iban) >= 6 else "****"

        frappe.logger().info(
            f"BANK ACCOUNT UPDATE: User {frappe.session.user} updated Mollie bank account "
            f"for member {member_name}. IBAN: {masked_iban}"
        )

        return {
            "status": "success",
            "message": _("Bank account updated successfully. Your next payment will use the new account."),
            "masked_iban": masked_iban,
        }

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(
            f"Mollie bank account update failed for member {member_name}: {error_msg}",
            "Mollie Bank Account Update",
        )
        return {
            "status": "error",
            "message": _("Failed to update bank account. Please try again or contact support."),
        }
