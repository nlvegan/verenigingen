# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, formatdate, getdate, today


def execute(filters=None):
    if not filters:
        filters = {}

    # Check if ANBI functionality is enabled
    anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
    if not anbi_enabled:
        frappe.msgprint(_("ANBI functionality is not enabled. Please enable it in Verenigingen Settings."))
        return [], []

    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    return [
        {
            "label": _("Agreement #"),
            "fieldname": "agreement_number",
            "fieldtype": "Link",
            "options": "Periodic Donation Agreement",
            "width": 140,
        },
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
        {"label": _("Type"), "fieldname": "commitment_type", "fieldtype": "Data", "width": 200},
        {"label": _("Donor"), "fieldname": "donor", "fieldtype": "Link", "options": "Donor", "width": 150},
        {"label": _("Donor Name"), "fieldname": "donor_name", "fieldtype": "Data", "width": 200},
        {"label": _("Duration"), "fieldname": "duration", "fieldtype": "Data", "width": 100},
        {"label": _("Start Date"), "fieldname": "start_date", "fieldtype": "Date", "width": 100},
        {"label": _("End Date"), "fieldname": "end_date", "fieldtype": "Date", "width": 100},
        {"label": _("Days Left"), "fieldname": "days_remaining", "fieldtype": "Int", "width": 80},
        {"label": _("Annual Amount"), "fieldname": "annual_amount", "fieldtype": "Currency", "width": 120},
        {
            "label": _("Payment Frequency"),
            "fieldname": "payment_frequency",
            "fieldtype": "Data",
            "width": 120,
        },
        {"label": _("Total Donated"), "fieldname": "total_donated", "fieldtype": "Currency", "width": 120},
        {
            "label": _("Completion %"),
            "fieldname": "completion_percentage",
            "fieldtype": "Percent",
            "width": 100,
        },
        {"label": _("Expected Total"), "fieldname": "expected_total", "fieldtype": "Currency", "width": 120},
        {
            "label": _("Next Expected"),
            "fieldname": "next_expected_donation",
            "fieldtype": "Date",
            "width": 110,
        },
        {"label": _("ANBI Eligible"), "fieldname": "anbi_eligible", "fieldtype": "Check", "width": 100},
    ]


def get_data(filters):
    conditions = get_conditions(filters)

    # Get agreement data
    agreement_data = frappe.db.sql(
        """
        SELECT
            pda.name,
            pda.agreement_number,
            pda.status,
            pda.commitment_type,
            pda.donor,
            pda.donor_name,
            pda.agreement_duration_years,
            pda.start_date,
            pda.end_date,
            pda.annual_amount,
            pda.payment_frequency,
            pda.payment_amount,
            pda.total_donated,
            pda.donations_count,
            pda.last_donation_date,
            pda.next_expected_donation,
            pda.anbi_eligible,
            pda.docstatus
        FROM `tabPeriodic Donation Agreement` pda
        WHERE pda.docstatus = 1
        {conditions}
        ORDER BY pda.end_date ASC, pda.agreement_number ASC
    """.format(
            conditions=conditions
        ),
        filters,
        as_dict=1,
    )

    data = []
    today_date = getdate(today())

    for row in agreement_data:
        # Calculate days remaining
        days_remaining = 0
        if row.end_date and row.status == "Active":
            days_remaining = date_diff(row.end_date, today_date)
            if days_remaining < 0:
                days_remaining = 0

        # Calculate expected total based on duration
        expected_total = 0
        if row.start_date and row.end_date and row.annual_amount:
            years = date_diff(row.end_date, row.start_date) / 365.25
            expected_total = flt(row.annual_amount * years, 2)

        # Calculate completion percentage
        completion_percentage = 0
        if expected_total > 0:
            completion_percentage = flt((row.total_donated or 0) / expected_total * 100, 2)

        # Format duration
        duration = row.agreement_duration_years or ""
        if duration:
            # Extract years from string like "5 Years (ANBI Minimum)"
            try:
                years = int(duration.split()[0])
                duration = f"{years} Year{'s' if years > 1 else ''}"
            except:
                pass

        # Add status indicators
        status = row.status
        if row.status == "Active" and days_remaining > 0 and days_remaining <= 90:
            status = f"{row.status} (Expiring Soon)"
        elif row.status == "Active" and days_remaining == 0:
            status = "Expired"

        data.append(
            {
                "agreement_number": row.agreement_number,
                "status": status,
                "commitment_type": row.commitment_type
                or ("ANBI Agreement" if row.anbi_eligible else "Donation Pledge"),
                "donor": row.donor,
                "donor_name": row.donor_name,
                "duration": duration,
                "start_date": row.start_date,
                "end_date": row.end_date,
                "days_remaining": days_remaining if row.status == "Active" else 0,
                "annual_amount": row.annual_amount,
                "payment_frequency": row.payment_frequency,
                "total_donated": row.total_donated or 0,
                "completion_percentage": completion_percentage,
                "expected_total": expected_total,
                "next_expected_donation": row.next_expected_donation if row.status == "Active" else None,
                "anbi_eligible": row.anbi_eligible,
            }
        )

    return data


def get_conditions(filters):
    conditions = []

    if filters.get("status"):
        conditions.append("pda.status = %(status)s")

    if filters.get("donor"):
        conditions.append("pda.donor = %(donor)s")

    if filters.get("anbi_eligible") == "Yes":
        conditions.append("pda.anbi_eligible = 1")
    elif filters.get("anbi_eligible") == "No":
        conditions.append("(pda.anbi_eligible = 0 OR pda.anbi_eligible IS NULL)")

    if filters.get("expiring_in_days"):
        future_date = add_days(today(), int(filters.get("expiring_in_days")))
        conditions.append(
            f"pda.end_date <= '{future_date}' AND pda.end_date >= '{today()}' AND pda.status = 'Active'"
        )

    if filters.get("payment_frequency"):
        conditions.append("pda.payment_frequency = %(payment_frequency)s")

    if filters.get("min_annual_amount"):
        conditions.append("pda.annual_amount >= %(min_annual_amount)s")

    return " AND " + " AND ".join(conditions) if conditions else ""
