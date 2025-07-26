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
            # Use explicit validation instead of fallback
            if template.billing_frequency:
                billing_frequency = template.billing_frequency
            else:
                billing_frequency = "Annual"  # Explicit default
                frappe.log_error(
                    f"Template '{membership_type.dues_schedule_template}' has no billing_frequency configured, using default 'Annual'",
                    "Membership Dues Integration Template Configuration",
                )
        except Exception:
            pass

    # Calculate first invoice date
    # For new members, typically invoice immediately
    first_invoice_date = today()

    # Get amount
    if not membership_application.fee_amount:
        # Fallback to template amount
        if not membership_type.dues_schedule_template:
            frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
        template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
        amount = membership_application.fee_amount or (template.suggested_amount or 0)
    else:
        amount = membership_application.fee_amount

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

    # Get payment history with enhanced error handling
    status["total_paid_ytd"] = _calculate_member_paid_ytd_optimized(member_name)

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


def _calculate_member_paid_ytd_optimized(member_name: str) -> float:
    """
    Calculate member's year-to-date payments with SQL optimization and Python fallback

    Follows the functional equivalence pattern from direct_debit_batch.py
    for consistent NULL/None handling and defensive programming.
    """
    try:
        # Primary SQL approach with SUM and NULL handling
        result = frappe.db.sql(
            """
            SELECT COALESCE(SUM(grand_total), 0)
            FROM `tabSales Invoice`
            WHERE customer = %s
            AND status = 'Paid'
            AND YEAR(posting_date) = YEAR(CURDATE())
            AND docstatus = 1
        """,
            member_name,
        )

        if result and result[0] and result[0][0] is not None:
            return float(result[0][0])
        else:
            return 0.0

    except Exception as e:
        # Fallback to Python iteration if SQL fails (graceful degradation)
        frappe.logger().warning(
            f"SQL aggregation failed for member YTD calculation, using Python fallback: {str(e)}"
        )
        return _calculate_member_paid_ytd_python(member_name)


def _calculate_member_paid_ytd_python(member_name: str) -> float:
    """
    Python fallback calculation functionally equivalent to SQL aggregation

    Implements the same defensive programming patterns as direct_debit_batch.py:
    - NULL/None handling equivalent to SQL COALESCE(grand_total, 0)
    - Type safety with try/except blocks for conversion errors
    - Currency precision with round(total, 2) for financial calculations
    - Handles edge cases (strings, invalid data) gracefully
    """
    try:
        from frappe.utils import getdate, today

        current_year = getdate(today()).year

        # Get paid invoices for this year using Frappe ORM
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member_name, "status": "Paid", "docstatus": 1},
            fields=["grand_total", "posting_date"],
        )

        if not invoices:
            return 0.0

        # Handle None/NULL values same way as SQL COALESCE(grand_total, 0)
        # Also handle potential string values and invalid data types gracefully
        total = 0.0
        for invoice in invoices:
            try:
                # Filter by year in Python
                posting_date = invoice.get("posting_date")
                if posting_date and getdate(posting_date).year != current_year:
                    continue

                amount = invoice.get("grand_total")
                if amount is None:
                    # Same as SQL COALESCE(grand_total, 0)
                    amount = 0.0
                elif isinstance(amount, str):
                    # Handle string amounts (shouldn't happen but defensive programming)
                    amount = float(amount) if amount.strip() else 0.0
                else:
                    # Ensure it's a float for precision consistency with SQL
                    amount = float(amount)

                total += amount

            except (ValueError, TypeError, AttributeError):
                # Handle any conversion errors by treating as 0 (same as SQL COALESCE behavior)
                # This matches SQL behavior where invalid/NULL data becomes 0
                continue

        # Ensure precision consistency with database currency handling
        return round(total, 2)

    except Exception as e:
        # Final fallback - log error and return 0
        frappe.logger().error(f"Python fallback calculation failed for member YTD: {str(e)}")
        return 0.0


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
