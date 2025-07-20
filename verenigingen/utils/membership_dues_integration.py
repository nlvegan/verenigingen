"""
Integration utilities for Membership Dues System
Handles the connection between memberships, dues schedules, and invoices
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, getdate, today


def create_dues_schedule_from_application(membership_application):
    """
    Create dues schedule when membership application is approved
    This replaces subscription creation
    """

    # Get the newly created member and membership
    member = frappe.get_doc("Member", membership_application.member)
    membership = frappe.db.get_value("Membership", {"member": member.name}, "name")

    if not membership:
        frappe.throw("Membership not found for approved application")

    # Get membership type details
    membership_type = frappe.get_doc("Membership Type", membership_application.membership_type)

    # Determine billing frequency from template or default to annual
    billing_frequency = "Annual"  # Default

    if membership_type.dues_schedule_template:
        try:
            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
            billing_frequency = template.billing_frequency or "Annual"
        except Exception:
            pass

    # Calculate first invoice date
    # For new members, typically invoice immediately
    first_invoice_date = today()

    # Get amount
    amount = membership_application.fee_amount or membership_type.amount

    # Create dues schedule
    dues_schedule = frappe.new_doc("Membership Dues Schedule")
    dues_schedule.member = member.name
    dues_schedule.membership = membership
    dues_schedule.billing_frequency = billing_frequency
    dues_schedule.dues_rate = amount
    dues_schedule.next_invoice_date = first_invoice_date
    dues_schedule.invoice_days_before = (
        0  # Invoice immediately for new members, will use template value for renewals
    )
    dues_schedule.auto_generate = 1
    dues_schedule.status = "Active"
    dues_schedule.notes = f"Created from application {membership_application.name}"

    dues_schedule.insert()

    # Generate first invoice if payment wasn't made during application
    if not membership_application.payment_id:
        invoice = dues_schedule.generate_invoice(force=True)
        return dues_schedule.name, invoice
    else:
        # Payment already made during application
        # Just update the schedule to reflect prepayment
        dues_schedule.last_invoice_date = today()
        dues_schedule.next_invoice_date = calculate_next_billing_date(today(), billing_frequency)
        dues_schedule.notes = f"Initial payment made during application: {membership_application.payment_id}"
        dues_schedule.save()

    return dues_schedule.name, None


def calculate_next_billing_date(from_date, billing_frequency):
    """Calculate next billing date based on frequency"""
    from_date = getdate(from_date)

    if billing_frequency == "Annual":
        return add_months(from_date, 12)
    elif billing_frequency == "Semi-Annual":
        return add_months(from_date, 6)
    elif billing_frequency == "Quarterly":
        return add_months(from_date, 3)
    elif billing_frequency == "Monthly":
        return add_months(from_date, 1)
    else:
        # Default to annual
        return add_months(from_date, 12)


def handle_membership_termination(member_name, termination_date=None):
    """Handle dues schedules when membership is terminated"""

    termination_date = termination_date or today()

    # Get all active dues schedules for the member
    schedules = frappe.get_all(
        "Membership Dues Schedule", filters={"member": member_name, "status": "Active"}, pluck="name"
    )

    for schedule_name in schedules:
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

        # Cancel future invoicing
        schedule.status = "Cancelled"
        schedule.notes = f"{schedule.notes}\n\nCancelled due to membership termination on {termination_date}"

        # Check if there's a pending invoice that should be prorated
        if getdate(schedule.next_invoice_date) > getdate(termination_date):
            # Member is terminating before next billing cycle
            # Could implement proration logic here if needed
            pass

        schedule.save()


def get_member_billing_status(member_name):
    """Get comprehensive billing status for a member"""

    status = {
        "has_active_schedule": False,
        "schedules": [],
        "pending_invoices": [],
        "last_payment_date": None,
        "next_invoice_date": None,
        "total_paid_ytd": 0,
    }

    # Get all schedules
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": member_name},
        fields=["name", "status", "next_invoice_date", "last_invoice_date", "dues_rate"],
    )

    for schedule in schedules:
        if schedule.status == "Active":
            status["has_active_schedule"] = True

            # Get next invoice date
            if not status["next_invoice_date"] or getdate(schedule.next_invoice_date) < getdate(
                status["next_invoice_date"]
            ):
                status["next_invoice_date"] = schedule.next_invoice_date

        status["schedules"].append(schedule)

    # Get pending invoices
    pending = frappe.get_all(
        "Sales Invoice",
        filters={"customer": member_name, "status": ["in", ["Unpaid", "Overdue"]], "docstatus": 1},
        fields=["name", "due_date", "grand_total", "status"],
    )

    status["pending_invoices"] = pending

    # Get payment history
    paid_this_year = (
        frappe.db.sql(
            """
        SELECT SUM(grand_total)
        FROM `tabSales Invoice`
        WHERE customer = %s
        AND status = 'Paid'
        AND YEAR(posting_date) = YEAR(CURDATE())
    """,
            member_name,
        )[0][0]
        or 0
    )

    status["total_paid_ytd"] = paid_this_year

    # Last payment
    last_payment = frappe.db.sql(
        """
        SELECT MAX(posting_date)
        FROM `tabPayment Entry`
        WHERE party = %s
        AND docstatus = 1
    """,
        member_name,
    )[0][0]

    status["last_payment_date"] = last_payment

    return status


@frappe.whitelist()
def adjust_dues_schedule(schedule_name, new_amount=None, new_frequency=None, new_next_date=None, reason=None):
    """Adjust an existing dues schedule"""

    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    changes = []

    if new_amount and new_amount != schedule.dues_rate:
        changes.append(f"Amount: {schedule.dues_rate} → {new_amount}")
        schedule.dues_rate = new_amount

    if new_frequency and new_frequency != schedule.billing_frequency:
        changes.append(f"Frequency: {schedule.billing_frequency} → {new_frequency}")
        schedule.billing_frequency = new_frequency

    if new_next_date and new_next_date != schedule.next_invoice_date:
        changes.append(f"Next date: {schedule.next_invoice_date} → {new_next_date}")
        schedule.next_invoice_date = new_next_date

    if changes:
        # Add audit note
        change_note = f"Adjusted on {today()}: {', '.join(changes)}"
        if reason:
            change_note += f"\nReason: {reason}"

        schedule.notes = f"{schedule.notes}\n\n{change_note}" if schedule.notes else change_note
        schedule.save()

        return {"success": True, "changes": changes, "schedule": schedule_name}
    else:
        return {"success": False, "message": "No changes made"}


@frappe.whitelist()
def create_payment_plan(member_name, total_amount, installments, start_date=None, notes=None):
    """Create a payment plan with multiple dues schedules"""

    start_date = start_date or today()
    installment_amount = total_amount / installments

    # Get membership
    membership = frappe.db.get_value("Membership", {"member": member_name}, "name")

    if not membership:
        frappe.throw(f"No membership found for {member_name}")

    schedules_created = []

    for i in range(installments):
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.member = member_name
        schedule.membership = membership
        schedule.billing_frequency = "Custom"
        schedule.dues_rate = installment_amount
        schedule.next_invoice_date = add_months(start_date, i)
        schedule.auto_generate = 1
        schedule.status = "Active"
        schedule.notes = f"Payment plan installment {i + 1} of {installments}"
        if notes:
            schedule.notes += f"\n{notes}"

        schedule.insert()
        schedules_created.append(schedule.name)

    return {
        "success": True,
        "payment_plan": {
            "total_amount": total_amount,
            "installments": installments,
            "installment_amount": installment_amount,
            "schedules": schedules_created,
        },
    }
