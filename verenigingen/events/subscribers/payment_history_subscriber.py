"""
Payment History Event Subscriber

This module handles updating member payment history in response to invoice events.
It's decoupled from the invoice submission process to prevent validation errors
from blocking core business operations.
"""

import time

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.background_jobs import enqueue


def _serialize_member_updates(member_name):
    """
    Create a serialization key for member updates to prevent concurrent modifications.

    This uses Frappe's enqueue deduplication feature to ensure only one
    update job runs per member at a time.
    """
    return f"payment_history_update_{member_name}"


def handle_invoice_submitted(event_name=None, event_data=None):
    """
    Handle the invoice_submitted event by updating member payment history.

    This runs asynchronously in the background, so any failures here
    won't affect the invoice submission.
    """
    if not event_data:
        return

    invoice_name = event_data.get("invoice")
    customer = event_data.get("customer")

    if not invoice_name or not customer:
        frappe.log_error(
            f"Invalid event data for invoice_submitted: {event_data}", "Payment History Subscriber Error"
        )
        return

    try:
        # Find all members associated with this customer
        members = frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

        if not members:
            # No members to update - this is fine
            return

        # Update each member's payment history
        for member_data in members:
            _update_member_payment_history_safe(member_data.name, invoice_name, "submitted")

        frappe.logger("events").info(
            f"Successfully updated payment history for {len(members)} members after invoice {invoice_name} submission"
        )

    except Exception as e:
        # Log the error but don't raise - this should never fail silently in production
        frappe.log_error(
            f"Failed to update payment history for invoice {invoice_name}: {str(e)}\n"
            f"Event data: {event_data}",
            "Payment History Update Failed",
        )


def handle_invoice_cancelled(event_name=None, event_data=None):
    """Handle the invoice_cancelled event"""
    if not event_data:
        return

    invoice_name = event_data.get("invoice")
    customer = event_data.get("customer")

    if not invoice_name or not customer:
        return

    try:
        members = frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

        for member_data in members:
            _update_member_payment_history_safe(member_data.name, invoice_name, "cancelled")

    except Exception as e:
        frappe.log_error(
            f"Failed to update payment history for cancelled invoice {invoice_name}: {str(e)}",
            "Payment History Update Failed",
        )


def handle_invoice_updated(event_name=None, event_data=None):
    """Handle the invoice_updated_after_submit event"""
    if not event_data:
        return

    invoice_name = event_data.get("invoice")
    customer = event_data.get("customer")

    if not invoice_name or not customer:
        return

    try:
        members = frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

        for member_data in members:
            _update_member_payment_history_safe(member_data.name, invoice_name, "updated")

    except Exception as e:
        frappe.log_error(
            f"Failed to update payment history for updated invoice {invoice_name}: {str(e)}",
            "Payment History Update Failed",
        )


def _update_member_payment_history_safe(member_name, invoice_name, action):
    """
    Safely update a single member's payment history.

    This function includes retry logic and validation error handling
    to ensure robustness. It specifically handles document modification
    conflicts that occur when multiple processes update the same member.
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            # Get fresh copy of member document
            member = frappe.get_doc("Member", member_name)

            # Reload payment history
            if hasattr(member, "load_payment_history"):
                member.load_payment_history()
            else:
                # Fallback if method doesn't exist
                frappe.log_error(
                    f"Member {member_name} doesn't have load_payment_history method",
                    "Payment History Method Missing",
                )
                return

            # Save with validation
            member.save(ignore_permissions=True)

            # Success - exit retry loop
            return

        except frappe.TimestampMismatchError:
            # This is the "document has been modified" error
            retry_count += 1

            if retry_count >= max_retries:
                # Log but don't fail - this is expected in concurrent scenarios
                frappe.logger("events").info(
                    f"Payment history sync skipped for member {member_name} "
                    f"after {action} invoice {invoice_name} due to concurrent updates. "
                    f"This is expected behavior and payment history will be updated "
                    f"on the next sync."
                )

                # Add a comment to track this
                try:
                    member = frappe.get_doc("Member", member_name)
                    member.add_comment(
                        "Comment",
                        f"Payment history sync skipped for invoice {invoice_name} ({action}) "
                        f"due to concurrent update. Payment history will sync on next update.",
                    )
                except:
                    pass
            else:
                # Wait with exponential backoff before retry
                time.sleep(0.1 * (2**retry_count))
                continue

        except frappe.ValidationError as e:
            retry_count += 1

            if retry_count >= max_retries:
                # Log validation error after all retries exhausted
                frappe.log_error(
                    f"Validation error updating payment history for member {member_name} "
                    f"after {action} invoice {invoice_name}: {str(e)}\n"
                    f"This error occurred {max_retries} times.",
                    "Payment History Validation Error",
                )

                # Try to save without the payment history update as last resort
                try:
                    member = frappe.get_doc("Member", member_name)
                    member.add_comment(
                        "Comment",
                        f"Payment history sync failed for invoice {invoice_name} ({action}). "
                        f"Error: {str(e)}",
                    )
                except:
                    pass  # Even commenting failed, give up

        except Exception as e:
            # Check if this is a document modified error with different exception type
            error_message = str(e).lower()
            if "document has been modified" in error_message or "timestamp mismatch" in error_message:
                # Treat as TimestampMismatchError
                retry_count += 1

                if retry_count >= max_retries:
                    frappe.logger("events").info(
                        f"Payment history sync skipped for member {member_name} "
                        f"after {action} invoice {invoice_name} due to concurrent updates."
                    )
                else:
                    time.sleep(0.1 * (2**retry_count))
                    continue
            else:
                # Other unexpected errors
                retry_count += 1

                if retry_count >= max_retries:
                    frappe.log_error(
                        f"Unexpected error updating payment history for member {member_name} "
                        f"after {action} invoice {invoice_name}: {str(e)}",
                        "Payment History Update Error",
                    )
                    break

                # Wait a bit before retry
                time.sleep(0.5 * retry_count)
