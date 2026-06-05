"""
Manage Donations Portal Page
Allows donors to view and manage their recurring donations
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, formatdate, getdate, today

# Import standardized member utilities
from verenigingen.utils.member_utils import (
    get_current_user_member_doc,
    get_current_user_member_name,
    get_current_user_member_name_required,
    get_member_name_for_user,
    require_login,
    validate_member_ownership,
)

# Import security framework for proper API protection
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    self_service_api,
)
from verenigingen.utils.validation_utilities import DateRangeValidator


def get_context(context):
    """Get context for manage donations page"""
    require_login()

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Manage Donations")

    # Ensure CSRF token is available
    context.csrf_token = frappe.session.csrf_token

    # Get member record using standardized utility
    context.member = get_current_user_member_doc()

    # Get donation summary statistics
    context.donation_summary = get_donation_summary(context.member.name)

    # Get active recurring donations
    context.recurring_donations = get_recurring_donations(context.member.name)

    # Get recent donation history (last 10 donations)
    context.recent_donations = get_recent_donations(context.member.name, limit=10)

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for manage donations page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = get_member_name_for_user(user)
    return bool(member)


def get_donation_summary(member_name):
    """Get donation summary statistics for a member"""
    try:
        # Get all donations for this member (by email matching)
        member = frappe.get_doc("Member", member_name)

        donations = frappe.get_all(
            "Donation",
            filters={"donor_email": member.email},
            fields=["name", "amount", "status", "paid", "donation_date"],
        )

        total_donated = 0
        total_donations = len(donations)
        active_recurring = 0

        for donation in donations:
            if donation.paid:
                total_donated += flt(donation.amount)

            if donation.status == "Recurring":
                # Check if this recurring donation is still active
                if is_recurring_donation_active(donation.name):
                    active_recurring += 1

        return {
            "total_donated": total_donated,
            "total_donations": total_donations,
            "active_recurring": active_recurring,
        }

    except Exception as e:
        frappe.log_error(f"Error getting donation summary: {str(e)}", "Manage Donations")
        return {
            "total_donated": 0,
            "total_donations": 0,
            "active_recurring": 0,
        }


def get_recurring_donations(member_name):
    """Get active recurring donations for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Get recurring donations that are still active
        recurring_donations = frappe.get_all(
            "Donation",
            filters={
                "donor_email": member.email,
                "status": "Recurring",
            },
            fields=[
                "name",
                "amount",
                "donation_date",
                "recurring_frequency",
                "mode_of_payment",
                "fund_designation",
                "mollie_subscription_id",
                "paid",
                "payment_status",
            ],
            order_by="donation_date desc",
        )

        # Enrich with subscription status for Mollie donations
        for donation in recurring_donations:
            if donation.mollie_subscription_id:
                subscription_info = get_mollie_subscription_info(donation.mollie_subscription_id)
                donation.update(subscription_info)

            # Only return active recurring donations
            if not is_recurring_donation_active(donation.name):
                recurring_donations.remove(donation)

        return recurring_donations

    except Exception as e:
        frappe.log_error(f"Error getting recurring donations: {str(e)}", "Manage Donations")
        return []


def get_recent_donations(member_name, limit=10):
    """Get recent donation history for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        recent_donations = frappe.get_all(
            "Donation",
            filters={"donor_email": member.email},
            fields=[
                "name",
                "donation_date",
                "amount",
                "status",
                "paid",
                "payment_status",
                "mode_of_payment",
                "fund_designation",
            ],
            order_by="donation_date desc",
            limit=limit,
        )

        return recent_donations

    except Exception as e:
        frappe.log_error(f"Error getting recent donations: {str(e)}", "Manage Donations")
        return []


def is_recurring_donation_active(donation_name):
    """Check if a recurring donation is still active"""
    try:
        donation = frappe.get_doc("Donation", donation_name)

        # If it has a Mollie subscription, check subscription status
        if donation.mollie_subscription_id:
            subscription_info = get_mollie_subscription_info(donation.mollie_subscription_id)
            return subscription_info.get("subscription_status") == "active"

        # For non-Mollie recurring donations, check if there are recent payments
        # and no explicit cancellation date
        if hasattr(donation, "recurring_cancelled_date") and donation.recurring_cancelled_date:
            return DateRangeValidator.is_date_in_future(donation.recurring_cancelled_date)

        # Default to active if it's a recurring donation without cancellation info
        return donation.status == "Recurring"

    except Exception:
        return False


def get_mollie_subscription_info(subscription_id):
    """Get REAL Mollie subscription information from API"""
    try:
        # Get real-time subscription status from Mollie API
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Call actual Mollie API to get subscription details
        try:
            # First, find the member with this subscription ID to get customer ID
            members = frappe.get_all(
                "Member",
                filters={"mollie_subscription_id": subscription_id},
                fields=["name", "mollie_customer_id"],
                limit=1,
            )

            if not members or not members[0].mollie_customer_id:
                raise Exception(f"No member found with mollie_customer_id for subscription {subscription_id}")

            customer_id = members[0].mollie_customer_id

            # Get the subscription through the customer (correct Mollie API usage)
            subscription = gateway.client.customers.get(customer_id).subscriptions.get(subscription_id)

            return {
                "subscription_status": subscription.status,
                "next_payment_date": (
                    subscription.next_payment_date if hasattr(subscription, "next_payment_date") else None
                ),
                "cancelled_date": subscription.canceled_at if hasattr(subscription, "canceled_at") else None,
                "amount": float(subscription.amount["value"]) if subscription.amount else 0.0,
            }

        except Exception as api_error:
            # If direct API call fails, fall back to local Member data
            frappe.log_error(
                f"Mollie API call failed, using local data: {str(api_error)}", "Manage Donations"
            )

            # Look for member with this subscription ID for fallback data
            members = frappe.get_all(
                "Member",
                filters={"mollie_subscription_id": subscription_id},
                fields=["name", "subscription_status", "next_payment_date", "subscription_cancelled_date"],
                limit=1,
            )

            if members:
                member_data = members[0]
                return {
                    "subscription_status": member_data.subscription_status or "unknown",
                    "next_payment_date": member_data.next_payment_date,
                    "cancelled_date": member_data.subscription_cancelled_date,
                }

            return {
                "subscription_status": "unknown",
                "next_payment_date": None,
                "cancelled_date": None,
            }

    except Exception as e:
        frappe.log_error(f"Error getting Mollie subscription info: {str(e)}", "Manage Donations")
        return {
            "subscription_status": "unknown",
            "next_payment_date": None,
            "cancelled_date": None,
        }


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True, audit_level="detailed")
def cancel_recurring_donation():
    """Cancel a recurring donation - with proper security framework"""
    try:
        # Get request data
        data = frappe.form_dict
        donation_id = data.get("donation_id")

        if not donation_id:
            frappe.throw(_("Donation ID is required"))

        # Get member record using improved utility
        member_name = get_current_user_member_name_required()
        member = frappe.get_doc("Member", member_name)

        # Get and validate the donation
        donation = frappe.get_doc("Donation", donation_id)

        # Verify ownership - donation must belong to this member. Guard against
        # empty values on BOTH sides: a member with a blank email must never match
        # an anonymous / email-less donation ("" == "").
        if not donation.donor_email or not member.email or donation.donor_email != member.email:
            frappe.throw(_("You can only cancel your own donations"))

        # Verify it's a recurring donation
        if donation.status != "Recurring":
            frappe.throw(_("This is not a recurring donation"))

        # Verify it's currently active
        if not is_recurring_donation_active(donation_id):
            frappe.throw(_("This recurring donation is already cancelled or inactive"))

        # Handle Mollie subscription cancellation
        if donation.mollie_subscription_id:
            try:
                from verenigingen.verenigingen_payments.utils.payment_gateways import (
                    cancel_mollie_subscription_by_id,
                )

                result = cancel_mollie_subscription_by_id(donation.mollie_subscription_id)

                if result.get("status") != "success":
                    frappe.throw(
                        _("Failed to cancel Mollie subscription: {0}").format(
                            result.get("message", "Unknown error")
                        )
                    )

            except ImportError:
                # Fallback if Mollie integration not available
                frappe.log_error(
                    "Mollie integration not available for subscription cancellation", "Manage Donations"
                )
            except Exception as e:
                frappe.log_error(f"Error cancelling Mollie subscription: {str(e)}", "Manage Donations")
                frappe.throw(_("Error cancelling Mollie subscription: {0}").format(str(e)))

        # Mark the recurring donation cancelled. The Donation status enum has no
        # "Cancelled" value; cancellation is tracked via recurring_cancelled_date,
        # which is_recurring_donation_active() honours. Status stays "Recurring".
        # Use db_set (not save) to write ONLY this field: ownership is already
        # verified, db_set bypasses the Donation write DocPerm a plain member lacks,
        # and it avoids persisting the whole in-memory document.
        # Note: the active-check above reads the in-memory doc, so two concurrent
        # portal sessions could both pass it; the db_set is idempotent (same date)
        # but a Mollie donation could see a double cancel API call — acceptable for
        # a low-frequency self-service action.
        donation.db_set("recurring_cancelled_date", today())
        donation.add_comment("Comment", _("Recurring donation cancelled by donor via portal"))

        return {
            "status": "success",
            "message": _("Recurring donation cancelled successfully"),
            "donation_id": donation_id,
        }

    except Exception as e:
        frappe.log_error(f"Recurring donation cancellation error: {str(e)}", "Manage Donations")
        frappe.throw(
            _(
                "An error occurred while cancelling your recurring donation. Please try again or contact support."
            )
        )


@frappe.whitelist(allow_guest=False)
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True, audit_level="detailed")
def update_recurring_donation():
    """Update a recurring donation amount - with proper security framework"""
    try:
        # Get request data
        data = frappe.form_dict
        donation_id = data.get("donation_id")
        new_amount = flt(data.get("new_amount"))

        if not donation_id:
            frappe.throw(_("Donation ID is required"))

        if new_amount <= 0:
            frappe.throw(_("Amount must be greater than zero"))

        # Get member record using improved utility
        member_name = get_current_user_member_name_required()
        member = frappe.get_doc("Member", member_name)

        # Get and validate the donation
        donation = frappe.get_doc("Donation", donation_id)

        # Verify ownership - donation must belong to this member. Guard against
        # empty values on BOTH sides: a member with a blank email must never match
        # an anonymous / email-less donation ("" == "").
        if not donation.donor_email or not member.email or donation.donor_email != member.email:
            frappe.throw(_("You can only update your own donations"))

        # Verify it's a recurring donation
        if donation.status != "Recurring":
            frappe.throw(_("This is not a recurring donation"))

        # Verify it's currently active
        if not is_recurring_donation_active(donation_id):
            frappe.throw(_("This recurring donation is not active"))

        old_amount = flt(donation.amount)

        # Handle Mollie subscription update
        if donation.mollie_subscription_id:
            try:
                from verenigingen.verenigingen_payments.utils.payment_gateways import (
                    update_mollie_subscription_amount,
                )

                result = update_mollie_subscription_amount(donation.mollie_subscription_id, new_amount)

                if result.get("status") != "success":
                    frappe.throw(
                        _("Failed to update Mollie subscription: {0}").format(
                            result.get("message", "Unknown error")
                        )
                    )

            except ImportError:
                # Fallback if Mollie integration not available
                frappe.log_error(
                    "Mollie integration not available for subscription update", "Manage Donations"
                )
                frappe.throw(_("Mollie subscription update not available. Please contact support."))
            except Exception as e:
                frappe.log_error(f"Error updating Mollie subscription: {str(e)}", "Manage Donations")
                frappe.throw(_("Error updating Mollie subscription: {0}").format(str(e)))

        # Update only the amount. Use db_set (not save): ownership is already
        # verified, db_set bypasses the Donation write DocPerm a plain member lacks,
        # and it avoids persisting the whole in-memory document.
        donation.db_set("amount", new_amount)
        donation.add_comment(
            "Comment",
            _("Recurring donation amount updated by donor via portal: €{0} → €{1}").format(
                old_amount, new_amount
            ),
        )

        return {
            "status": "success",
            "message": _("Recurring donation updated successfully"),
            "donation_id": donation_id,
            "old_amount": old_amount,
            "new_amount": new_amount,
        }

    except Exception as e:
        frappe.log_error(f"Recurring donation update error: {str(e)}", "Manage Donations")
        frappe.throw(
            _(
                "An error occurred while updating your recurring donation. Please try again or contact support."
            )
        )


@frappe.whitelist()
@self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True, audit_level="detailed")
def get_donation_stats():
    """Get donation statistics for the logged-in member (for AJAX calls).

    Self-service: returns only the caller's own summary (member derived from the
    session via get_current_user_member_name); plain members must be able to see
    their own donation stats, same as the cancel/update endpoints below/above.
    """
    try:
        if frappe.session.user == "Guest":
            return {"error": "Not logged in"}

        member_name = get_current_user_member_name()
        if not member_name:
            return {"error": "No member record found"}

        summary = get_donation_summary(member_name)
        return {"status": "success", "data": summary}

    except Exception as e:
        frappe.log_error(f"Error getting donation stats: {str(e)}", "Manage Donations")
        return {"error": str(e)}
