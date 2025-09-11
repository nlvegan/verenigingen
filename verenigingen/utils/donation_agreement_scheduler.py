"""
Hooks for Donation Agreement Processing

This module provides scheduled tasks and hooks for processing donation agreements,
creating recurring donation transactions, and maintaining income forecasting.
"""

import frappe
from frappe.utils import today


def process_recurring_donations():
    """
    Scheduled task to process recurring donation agreements

    Should be called daily via scheduler to:
    1. Find agreements due for transaction creation
    2. Create donation transactions
    3. Update agreement tracking
    4. Send notifications if configured
    """
    try:
        # TODO: Migrate this to work with Periodic Donation Agreement DocType
        # The original Donation Agreement DocType was replaced by Periodic Donation Agreement
        frappe.logger().info("Donation agreement processing temporarily disabled during DocType migration")
        return {"processed": 0, "errors": 0}

    except Exception as e:
        frappe.log_error(
            f"Error in scheduled donation agreement processing: {str(e)}",
            "Donation Agreement Scheduler Error",
        )
        return {"processed": 0, "errors": 1}


def send_payment_reminders():
    """
    Send payment reminders for bank transfer agreements

    Should be called daily to send reminders to donors with
    upcoming or overdue bank transfer donations.
    """
    try:
        from verenigingen.utils.donation_emails import send_payment_reminder

        # Find agreements needing reminders
        reminder_agreements = frappe.db.sql(
            """
            SELECT name, donor, donor_email, amount, next_due_date, reminder_days_before
            FROM `tabDonation Agreement`
            WHERE status = 'Active'
                AND docstatus = 1
                AND (sepa_mandate IS NULL AND enable_mollie_subscription = 0)
                AND send_reminders = 1
                AND DATE_ADD(next_due_date, INTERVAL -reminder_days_before DAY) <= %s
                AND next_due_date >= %s
        """,
            (today(), today()),
            as_dict=True,
        )

        sent_count = 0
        for agreement in reminder_agreements:
            try:
                # Check if reminder already sent today
                reminder_log = frappe.db.exists(
                    "Email Queue",
                    {
                        "recipient": agreement.donor_email,
                        "subject": ["like", f"%Payment Reminder%{agreement.name}%"],
                        "creation": [">=", today()],
                    },
                )

                if not reminder_log:
                    send_payment_reminder(agreement.name)
                    sent_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Error sending reminder for agreement {agreement.name}: {str(e)}",
                    "Payment Reminder Error",
                )

        if sent_count > 0:
            frappe.logger().info(f"Sent {sent_count} payment reminders")

        return sent_count

    except Exception as e:
        frappe.log_error(
            f"Error in payment reminder processing: {str(e)}", "Payment Reminder Scheduler Error"
        )
        return 0


def update_agreement_tracking():
    """
    Update financial tracking for all active agreements

    Should be called weekly to ensure tracking fields are accurate.
    """
    try:
        from verenigingen.utils.validation_utilities import get_all_active_records

        active_agreements = get_all_active_records("Donation Agreement")

        updated_count = 0
        for agreement in active_agreements:
            try:
                doc = frappe.get_doc("Donation Agreement", agreement.name)
                doc.update_financial_tracking()
                updated_count += 1
            except Exception as e:
                frappe.log_error(
                    f"Error updating tracking for agreement {agreement.name}: {str(e)}",
                    "Agreement Tracking Update Error",
                )

        frappe.logger().info(f"Updated tracking for {updated_count} agreements")
        return updated_count

    except Exception as e:
        frappe.log_error(
            f"Error in agreement tracking update: {str(e)}", "Agreement Tracking Scheduler Error"
        )
        return 0


# Integration hooks for existing Donation DocType
def on_donation_payment(doc, method):
    """
    Hook called when a donation payment is received

    Updates the related donation agreement tracking.
    """
    if doc.donation_agreement and doc.paid:
        try:
            agreement_doc = frappe.get_doc("Donation Agreement", doc.donation_agreement)
            agreement_doc.update_financial_tracking()
        except Exception as e:
            frappe.log_error(
                f"Error updating agreement tracking after payment {doc.name}: {str(e)}",
                "Agreement Payment Update Error",
            )


def validate_donation_agreement_link(doc, method):
    """
    Hook called when validating a donation

    Ensures donation is properly linked to agreement if specified.
    """
    if doc.donation_agreement:
        try:
            agreement = frappe.get_doc("Donation Agreement", doc.donation_agreement)

            # Validate donor matches
            if agreement.donor != doc.donor:
                frappe.throw("Donation donor must match agreement donor")

            # Validate amount if fixed
            if agreement.agreement_type in ["Recurring", "One-time Pledge"]:
                if flt(doc.amount) != flt(agreement.amount):
                    frappe.msgprint(
                        f"Donation amount ({doc.amount}) differs from agreement amount ({agreement.amount})",
                        indicator="yellow",
                    )

            # Auto-populate fields from agreement
            if not doc.donation_purpose and agreement.donation_purpose:
                doc.donation_purpose = agreement.donation_purpose

            # Mode of payment will be set by the agreement's transaction creation logic

        except Exception as e:
            frappe.log_error(
                f"Error validating donation agreement link for {doc.name}: {str(e)}",
                "Donation Agreement Validation Error",
            )
