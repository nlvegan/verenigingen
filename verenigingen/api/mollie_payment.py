"""
Mollie Payment API Endpoints

Member-portal endpoints (payment dashboard) for a member to view and manage their
OWN Mollie subscription: view details, cancel a subscription, and change the bank
account on the active subscription. All three resolve the member from the session
and delegate Mollie operations to the production SubscriptionService.
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import (
    get_current_user_member_name_required,
    validate_member_ownership,
)
from verenigingen.utils.mollie_data_validator import parse_mollie_customer_ids
from verenigingen.utils.security.api_security_framework import OperationType, self_service_api
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import mollie_signature_date


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

        # CRITICAL SECURITY: a member may only view their OWN subscription details.
        validate_member_ownership(member_name, _("You can only access your own subscription details"))

        member = frappe.get_doc("Member", member_name)
        customer_infos = _collect_member_customer_infos(member)

        if not customer_infos:
            return {"status": "no_subscription", "message": _("No Mollie customer IDs found")}

        try:
            from verenigingen.verenigingen_payments.mollie.services.subscription_service import (
                SubscriptionService,
            )

            service = SubscriptionService()
            all_subscriptions = []
            for customer_info in customer_infos:
                all_subscriptions.extend(_fetch_customer_subscriptions(service, customer_info))

            return {
                "status": "success",
                "subscriptions": all_subscriptions,
                "total_customers": len(customer_infos),
            }

        except Exception as subscription_error:
            frappe.log_error(
                f"Error fetching subscription data: {str(subscription_error)}", "Subscription Data Fetch"
            )
            return _subscription_fallback(member)

    except Exception as e:
        frappe.log_error(f"Error in get_subscription_details: {str(e)}", "Mollie Subscription API")
        return {"status": "error", "message": _("Error retrieving subscription details")}


# Sentinel: distinguishes "mandate validity not checked" from a checked-but-None status.
_UNSET = object()


def _collect_member_customer_infos(member):
    """Build the per-customer context list from the member's Mollie customer ID(s).

    Only the MEMBER record is consulted (not Donor): the dues dashboard shows
    membership payment methods, not donation methods. Supports comma-separated
    customer IDs for members with multiple Mollie accounts.
    """
    customer_infos = []
    if member.mollie_customer_id:
        for customer_id in parse_mollie_customer_ids(member.mollie_customer_id, max_ids=5):
            customer_infos.append(
                {
                    "customer_id": customer_id,
                    "subscription_id": member.mollie_subscription_id,
                    "source": "member",
                    "local_status": member.subscription_status,
                    "local_cancelled_date": member.subscription_cancelled_date,
                }
            )
    return customer_infos


def _fetch_customer_subscriptions(service, customer_info):
    """Fetch and shape all subscriptions for one customer.

    Returns a list of result entries: one per subscription (active + canceled), or
    a single "customer-only" entry when the customer has no subscriptions or the
    Mollie query fails. Never raises — a per-customer failure degrades to an error
    entry so the other customers still render.
    """
    customer_id = customer_info["customer_id"]
    try:
        subscriptions_result = service.list_subscriptions(customer_id, limit=250, active_only=False)

        if subscriptions_result.get("error"):
            return [_customer_only_entry(customer_info, error=subscriptions_result["error"])]

        mandate_valid, mandate_status = _check_mandate_validity(service, customer_id)

        subscriptions = subscriptions_result.get("subscriptions", [])
        if not subscriptions:
            return [
                _customer_only_entry(
                    customer_info,
                    mandate_valid=mandate_valid,
                    mandate_status=mandate_status,
                    note="Customer found but no subscriptions",
                )
            ]

        return [
            _shape_subscription(sub, customer_info, mandate_valid, mandate_status) for sub in subscriptions
        ]

    except Exception as mollie_error:
        frappe.log_error(
            f"Error querying Mollie subscriptions for {customer_id}: {str(mollie_error)}",
            "Mollie Subscription Query",
        )
        return [_customer_only_entry(customer_info, error="Could not fetch subscription data")]


def _check_mandate_validity(service, customer_id):
    """Return (mandate_valid, mandate_status) for a customer.

    A customer is "valid" if any mandate has status "valid". Missing mandates are
    not an error (the customer may not have set one up yet) → returns (False, None).
    """
    try:
        customer_obj = service.client.sdk_client.customers.get(customer_id)
        mandate_status = None
        for mandate in customer_obj.mandates.list():
            if mandate.status == "valid":
                return True, "valid"
            if not mandate_status:  # remember the first non-valid status seen
                mandate_status = mandate.status
        return False, mandate_status
    except Exception as mandate_error:
        frappe.logger().debug(f"No mandates found for customer {customer_id}: {str(mandate_error)}")
        return False, None


def _shape_subscription(sub, customer_info, mandate_valid, mandate_status):
    """Shape one structured subscription dict (from SubscriptionService.list_subscriptions)
    into a portal response entry.

    Reads the structured ``amount_value``/``currency`` fields directly — no string
    parsing.
    """
    status = sub.get("status")
    return {
        "customer_id": customer_info["customer_id"],
        "subscription_id": sub.get("id"),
        "source": customer_info["source"],
        "subscription": {
            "id": sub.get("id"),
            "status": status,
            "amount": sub.get("amount_value", 0.0),
            "currency": sub.get("currency", "EUR"),
            "interval": sub.get("interval"),
            "next_payment_date": sub.get("next_payment_date"),
            "is_active": status == "active",
            "is_canceled": status == "canceled",
            "description": sub.get("description"),
        },
        "member_status": {
            "local_status": customer_info.get("local_status"),
            "cancelled_date": customer_info.get("local_cancelled_date"),
        },
        "mandate_valid": mandate_valid,
        "mandate_status": mandate_status,
    }


def _customer_only_entry(customer_info, *, error=None, note=None, mandate_valid=False, mandate_status=_UNSET):
    """Build a "customer-only" result entry (no subscription rendered).

    ``mandate_status`` is omitted entirely when not supplied (mandate validity was
    not checked — e.g. on a list error), matching the legacy response shape.
    """
    entry = {
        "customer_id": customer_info["customer_id"],
        "source": customer_info["source"],
        "subscription": None,
        "has_customer_only": True,
        "mandate_valid": mandate_valid,
    }
    if mandate_status is not _UNSET:
        entry["mandate_status"] = mandate_status
    if error is not None:
        entry["error"] = error
    if note is not None:
        entry["note"] = note
    return entry


def _subscription_fallback(member):
    """Fallback to last-known member-record status when the live Mollie query fails."""
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

        # Cancel the subscription via the production SubscriptionService
        from verenigingen.verenigingen_payments.mollie.services.subscription_service import (
            SubscriptionService,
        )

        frappe.logger().info(
            f"User {frappe.session.user} cancelling subscription {subscription_id} for customer {customer_id}"
        )

        service = SubscriptionService()
        result = service.admin_cancel_subscription(
            customer_id=customer_id,
            subscription_id=subscription_id,
            reason=f"User-initiated cancellation via payment dashboard by {frappe.session.user}",
        )

        # If cancellation was successful, clear the subscription ID from member record
        if result.get("status") == "success":
            # Check if this subscription ID matches the member's subscription
            if member.mollie_subscription_id == subscription_id:
                member.db_set("mollie_subscription_id", None)
                # "canceled" is the Member.subscription_status Select option (single
                # l); db_set bypasses validation, so a typo'd value would silently
                # render blank and never match status == "canceled" checks.
                member.db_set("subscription_status", "canceled")
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
        from verenigingen.verenigingen_payments.mollie.services.subscription_service import (
            SubscriptionService,
        )

        service = SubscriptionService()

        # Step 1: Verify subscription is active
        client = service.client.sdk_client
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
            # UTC date (see mollie_signature_date): Mollie 422s a future signature
            # date, which site-local today() can produce east of Mollie's timezone.
            "signatureDate": mollie_signature_date(),
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
