# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_months, get_last_day, get_quarter_ending, getdate


def execute(filters=None):
    """
    Reconstruct member_end_date for terminated members by analyzing:
    1. Active SEPA mandates / Mollie subscriptions
    2. Last invoice coverage periods
    3. Last payment dates + billing frequency
    """
    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    """Define report columns"""
    return [
        {
            "fieldname": "member",
            "label": _("Member ID"),
            "fieldtype": "Link",
            "options": "Member",
            "width": 140,
        },
        {"fieldname": "member_name", "label": _("Name"), "fieldtype": "Data", "width": 180},
        {"fieldname": "current_end_date", "label": _("Current End Date"), "fieldtype": "Date", "width": 120},
        {"fieldname": "status_indicator", "label": _("Status"), "fieldtype": "Data", "width": 150},
        {
            "fieldname": "suggested_end_date",
            "label": _("Suggested End Date"),
            "fieldtype": "Date",
            "width": 140,
        },
        {"fieldname": "confidence", "label": _("Confidence"), "fieldtype": "Data", "width": 100},
        {"fieldname": "data_source", "label": _("Data Source"), "fieldtype": "Data", "width": 200},
        {"fieldname": "last_payment_date", "label": _("Last Payment"), "fieldtype": "Date", "width": 120},
        {
            "fieldname": "billing_frequency",
            "label": _("Billing Frequency"),
            "fieldtype": "Data",
            "width": 120,
        },
        {"fieldname": "details", "label": _("Details"), "fieldtype": "Text", "width": 250},
    ]


def get_data(filters):
    """Get terminated members and reconstruct end dates"""

    # Get all terminated members without member_end_date
    members = frappe.db.sql(
        """
        SELECT
            name,
            full_name,
            member_end_date,
            customer,
            email
        FROM `tabMember`
        WHERE status = 'Terminated'
        AND (member_end_date IS NULL OR member_end_date = '')
        ORDER BY full_name
    """,
        as_dict=True,
    )

    data = []

    for member in members:
        row = analyze_member(member)
        data.append(row)

    return data


def analyze_member(member):
    """Analyze a single member and suggest end date"""

    result = {
        "member": member.name,
        "member_name": member.full_name,
        "current_end_date": member.member_end_date,
        "suggested_end_date": None,
        "confidence": "Unknown",
        "data_source": "No data available",
        "status_indicator": "",
        "last_payment_date": None,
        "billing_frequency": "",
        "details": "",
    }

    # Step 1: Check for active payment methods (indicates still active)
    if check_active_payment_methods(member, result):
        return result

    # Step 2: Check last invoice coverage dates
    if check_invoice_coverage(member, result):
        return result

    # Step 3: Check last payment + billing frequency
    if check_last_payment(member, result):
        return result

    # No data found
    result["confidence"] = "No Data"
    result["data_source"] = "No invoices or payments found"
    result["details"] = "Unable to determine end date - no payment history"

    return result


def check_active_payment_methods(member, result):
    """Check if member has active SEPA mandate or Mollie subscription"""

    # Check SEPA mandates
    active_sepa = frappe.db.exists(
        "SEPA Mandate", {"member": member["name"], "status": "Active", "is_active": 1}
    )

    # Check Mollie subscription on customer
    mollie_subscription = None
    if member["customer"]:
        mollie_subscription = frappe.db.get_value(
            "Customer", member["customer"], "custom_mollie_subscription_id"
        )

    if active_sepa or mollie_subscription:
        result["status_indicator"] = "⚠️ Still Active"
        result["confidence"] = "High"
        result["data_source"] = []

        if active_sepa:
            result["data_source"].append("Active SEPA mandate")
        if mollie_subscription:
            result["data_source"].append(f"Mollie subscription {mollie_subscription}")

        result["data_source"] = ", ".join(result["data_source"])
        result[
            "details"
        ] = "Member appears to still have active payment method - review before setting end date"
        result["suggested_end_date"] = None

        return True

    return False


def check_invoice_coverage(member, result):
    """Check last invoice coverage end date"""

    if not member["customer"]:
        return False

    # Get last invoice with coverage dates
    last_invoice = frappe.db.sql(
        """
        SELECT
            name,
            custom_coverage_start_date,
            custom_coverage_end_date,
            posting_date,
            grand_total,
            outstanding_amount
        FROM `tabSales Invoice`
        WHERE customer = %(customer)s
        AND docstatus = 1
        AND custom_coverage_end_date IS NOT NULL
        ORDER BY custom_coverage_end_date DESC
        LIMIT 1
    """,
        {"customer": member["customer"]},
        as_dict=True,
    )

    if last_invoice:
        invoice = last_invoice[0]
        result["suggested_end_date"] = invoice.custom_coverage_end_date
        result["confidence"] = "High" if invoice.outstanding_amount == 0 else "Medium"
        result["data_source"] = f"Last invoice {invoice.name}"
        result["status_indicator"] = "✓ Invoice Coverage"
        result["details"] = (
            f"Coverage: {invoice.custom_coverage_start_date} to {invoice.custom_coverage_end_date}. "
            f"{'Paid' if invoice.outstanding_amount == 0 else f'Unpaid (€{invoice.outstanding_amount})'}"
        )

        return True

    return False


def check_last_payment(member, result):
    """Check last payment and calculate end date based on billing frequency"""

    if not member["customer"]:
        return False

    # Get last payment
    last_payment = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.posting_date,
            pe.paid_amount,
            si.name as invoice
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        LEFT JOIN `tabSales Invoice` si ON si.name = per.reference_name
        WHERE pe.party = %(customer)s
        AND pe.docstatus = 1
        AND pe.payment_type = 'Receive'
        ORDER BY pe.posting_date DESC
        LIMIT 1
    """,
        {"customer": member["customer"]},
        as_dict=True,
    )

    if not last_payment:
        return False

    payment = last_payment[0]
    result["last_payment_date"] = payment.posting_date

    # Get billing frequency from dues schedule
    billing_frequency = get_member_billing_frequency(member["name"])
    result["billing_frequency"] = billing_frequency or "Unknown"

    if not billing_frequency:
        result["confidence"] = "Low"
        result["data_source"] = f"Last payment {payment.name}"
        result["details"] = "Payment found but no billing frequency - cannot calculate period end"
        return True

    # Calculate period end date based on billing frequency
    payment_date = getdate(payment.posting_date)

    if billing_frequency == "Monthly":
        # End of month
        suggested_date = get_last_day(payment_date)
    elif billing_frequency == "Quarterly":
        # End of quarter
        suggested_date = get_quarter_ending(payment_date)
    elif billing_frequency in ["Annual", "Yearly"]:
        # End of year
        suggested_date = datetime(payment_date.year, 12, 31).date()
    else:
        # Unknown frequency - suggest end of month as fallback
        suggested_date = get_last_day(payment_date)

    result["suggested_end_date"] = suggested_date
    result["confidence"] = "Medium"
    result["status_indicator"] = "📅 Payment-Based"
    result["data_source"] = f"Last payment {payment.name}"
    result["details"] = (
        f"Last payment: €{payment.paid_amount} on {payment.posting_date}. "
        f"Calculated {billing_frequency} period end."
    )

    return True


def get_member_billing_frequency(member_name):
    """Get billing frequency from member's dues schedule"""

    # Get the most recent dues schedule
    dues_schedule = frappe.db.sql(
        """
        SELECT billing_frequency
        FROM `tabMembership Dues Schedule`
        WHERE member = %(member)s
        ORDER BY creation DESC
        LIMIT 1
    """,
        {"member": member_name},
        as_dict=True,
    )

    if dues_schedule:
        return dues_schedule[0].billing_frequency

    return None


@frappe.whitelist()
def apply_suggestion(member_id, suggested_date):
    """Apply suggested end date to member record"""

    # Verify user has permission
    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("You don't have permission to update member records"))

    member = frappe.get_doc("Member", member_id)

    # Verify member is terminated and has no end date
    if member.status != "Terminated":
        frappe.throw(_("Member must have Terminated status"))

    if member.member_end_date:
        frappe.throw(_("Member already has an end date: {0}").format(member.member_end_date))

    # Apply the suggestion
    member.member_end_date = suggested_date
    member.add_comment(
        "Info", f"End date reconstructed: {suggested_date} (via Member End Date Reconstruction report)"
    )
    member.save()

    frappe.msgprint(_("End date updated to {0}").format(suggested_date))

    return {"success": True, "message": f"Updated {member_id} with end date {suggested_date}"}


@frappe.whitelist()
def apply_all_suggestions():
    """Apply all high-confidence suggestions in batch"""

    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("You don't have permission to update member records"))

    # Get all terminated members without end date
    members = frappe.db.sql(
        """
        SELECT name
        FROM `tabMember`
        WHERE status = 'Terminated'
        AND (member_end_date IS NULL OR member_end_date = '')
    """,
        as_dict=True,
    )

    updated_count = 0
    skipped_count = 0
    errors = []

    for member_data in members:
        try:
            # Analyze member
            member = frappe.db.get_value(
                "Member", member_data.name, ["name", "full_name", "customer"], as_dict=True
            )
            analysis = analyze_member(member)

            # Only apply high-confidence suggestions
            if analysis["confidence"] == "High" and analysis["suggested_end_date"]:
                member_doc = frappe.get_doc("Member", member_data.name)
                member_doc.member_end_date = analysis["suggested_end_date"]
                member_doc.add_comment(
                    "Info",
                    f"End date reconstructed: {analysis['suggested_end_date']} - Source: {analysis['data_source']}",
                )
                member_doc.save()
                updated_count += 1
            else:
                skipped_count += 1

        except Exception as e:
            errors.append(f"{member_data.name}: {str(e)}")
            continue

    message = f"Updated {updated_count} members. Skipped {skipped_count} (low confidence or active)."
    if errors:
        message += f"\n\nErrors: {len(errors)}\n" + "\n".join(errors[:10])

    frappe.msgprint(message)

    return {"success": True, "updated": updated_count, "skipped": skipped_count, "errors": errors}
