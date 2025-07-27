# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, formatdate, getdate, today


def get_context(context):
    # Check if user has permission
    if not frappe.has_permission("Donation", "read") or not frappe.has_permission(
        "Periodic Donation Agreement", "read"
    ):
        frappe.throw(_("You do not have permission to access this page"), frappe.PermissionError)

    # Check if ANBI functionality is enabled
    anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
    if not anbi_enabled:
        context.anbi_disabled = True
        return context

    context.no_cache = 1
    context.show_sidebar = True

    # Get ANBI settings
    settings = frappe.get_single("Verenigingen Settings")
    context.organization_has_anbi_status = settings.organization_has_anbi_status
    context.anbi_minimum_reportable_amount = settings.anbi_minimum_reportable_amount

    # Get current year statistics
    current_year = getdate(today()).year
    year_start = f"{current_year}-01-01"
    year_end = f"{current_year}-12-31"

    # Total donations this year
    total_donations = frappe.db.sql(
        """
        SELECT
            SUM(amount) as total_amount,
            COUNT(*) as count
        FROM `tabDonation`
        WHERE paid = 1
        AND docstatus = 1
        AND date BETWEEN %s AND %s
    """,
        (year_start, year_end),
        as_dict=1,
    )[0]

    context.total_donations_amount = flt(total_donations.get("total_amount", 0), 2)
    context.total_donations_count = total_donations.get("count", 0)

    # Periodic agreement statistics
    periodic_stats = frappe.db.sql(
        """
        SELECT
            COUNT(CASE WHEN status = 'Active' AND anbi_eligible = 1 THEN 1 END) as active_anbi_count,
            COUNT(CASE WHEN status = 'Active' AND (anbi_eligible = 0 OR anbi_eligible IS NULL) THEN 1 END) as active_pledge_count,
            SUM(CASE WHEN status = 'Active' THEN annual_amount ELSE 0 END) as total_annual_amount,
            COUNT(CASE WHEN status = 'Active' AND end_date <= %s THEN 1 END) as expiring_soon_count
        FROM `tabPeriodic Donation Agreement`
        WHERE docstatus = 1
    """,
        (add_days(today(), 90),),
        as_dict=1,
    )[0]

    context.active_anbi_agreements = periodic_stats.get("active_anbi_count", 0)
    context.active_pledge_agreements = periodic_stats.get("active_pledge_count", 0)
    context.total_annual_commitment = flt(periodic_stats.get("total_annual_amount", 0), 2)
    context.expiring_soon_count = periodic_stats.get("expiring_soon_count", 0)

    # Donor statistics
    donor_stats = frappe.db.sql(
        """
        SELECT
            COUNT(DISTINCT donor.name) as unique_donors,
            COUNT(DISTINCT CASE WHEN donor.donor_type = 'Individual' THEN donor.name END) as individual_donors,
            COUNT(DISTINCT CASE WHEN donor.donor_type = 'Organization' THEN donor.name END) as organization_donors,
            COUNT(DISTINCT CASE WHEN donor.anbi_consent = 1 THEN donor.name END) as donors_with_consent
        FROM `tabDonor` donor
        WHERE donor.name IN (
            SELECT DISTINCT d.donor FROM `tabDonation` d
            WHERE d.paid = 1 AND d.docstatus = 1
        )
    """,
        as_dict=1,
    )[0]

    context.unique_donors = donor_stats.get("unique_donors", 0)
    context.individual_donors = donor_stats.get("individual_donors", 0)
    context.organization_donors = donor_stats.get("organization_donors", 0)
    context.donors_with_consent = donor_stats.get("donors_with_consent", 0)
    context.consent_percentage = flt(
        (context.donors_with_consent / context.unique_donors * 100) if context.unique_donors > 0 else 0, 1
    )

    # Reportable donations
    reportable_donations = frappe.db.sql(
        """
        SELECT
            COUNT(*) as count,
            SUM(amount) as total_amount
        FROM `tabDonation`
        WHERE paid = 1
        AND docstatus = 1
        AND date BETWEEN %s AND %s
        AND (belastingdienst_reportable = 1 OR amount >= %s)
    """,
        (year_start, year_end, settings.anbi_minimum_reportable_amount),
        as_dict=1,
    )[0]

    context.reportable_donations_count = reportable_donations.get("count", 0)
    context.reportable_donations_amount = flt(reportable_donations.get("total_amount", 0), 2)

    # Recent donations
    context.recent_donations = frappe.db.sql(
        """
        SELECT
            d.name,
            d.donor,
            donor.donor_name,
            d.amount,
            d.donation_date,
            d.periodic_donation_agreement,
            pda.agreement_number,
            pda.anbi_eligible
        FROM `tabDonation` d
        LEFT JOIN `tabDonor` donor ON d.donor = donor.name
        LEFT JOIN `tabPeriodic Donation Agreement` pda ON d.periodic_donation_agreement = pda.name
        WHERE d.paid = 1
        AND d.docstatus = 1
        ORDER BY d.donation_date DESC
        LIMIT 10
    """,
        as_dict=1,
    )

    # Expiring agreements
    context.expiring_agreements = frappe.db.sql(
        """
        SELECT
            name,
            agreement_number,
            donor_name,
            end_date,
            annual_amount,
            anbi_eligible,
            DATEDIFF(end_date, %s) as days_remaining
        FROM `tabPeriodic Donation Agreement`
        WHERE status = 'Active'
        AND docstatus = 1
        AND end_date <= %s
        ORDER BY end_date ASC
        LIMIT 10
    """,
        (today(), add_days(today(), 90)),
        as_dict=1,
    )

    # Monthly trend data for chart
    monthly_trend = frappe.db.sql(
        """
        SELECT
            MONTH(date) as month,
            SUM(amount) as total_amount,
            COUNT(*) as count
        FROM `tabDonation`
        WHERE paid = 1
        AND docstatus = 1
        AND YEAR(date) = %s
        GROUP BY MONTH(date)
        ORDER BY MONTH(date)
    """,
        (current_year,),
        as_dict=1,
    )

    # Prepare chart data
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    chart_labels = []
    chart_values = []

    for i in range(1, 13):
        month_data = next((m for m in monthly_trend if m.month == i), None)
        chart_labels.append(months[i - 1])
        chart_values.append(float(month_data.total_amount) if month_data else 0)

    context.donation_trend_chart = {
        "labels": chart_labels,
        "datasets": [{"name": "Donations", "values": chart_values}],
    }

    # Agreement type distribution
    agreement_distribution = frappe.db.sql(
        """
        SELECT
            CASE
                WHEN anbi_eligible = 1 THEN 'ANBI Agreements'
                ELSE 'Donation Pledges'
            END as type,
            COUNT(*) as count
        FROM `tabPeriodic Donation Agreement`
        WHERE status = 'Active'
        AND docstatus = 1
        GROUP BY anbi_eligible
    """,
        as_dict=1,
    )

    context.agreement_distribution = {
        "labels": [d.type for d in agreement_distribution],
        "datasets": [{"name": "Agreements", "values": [d.count for d in agreement_distribution]}],
    }

    return context
