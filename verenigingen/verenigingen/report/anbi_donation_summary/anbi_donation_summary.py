# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate


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
        {"label": _("Donor"), "fieldname": "donor", "fieldtype": "Link", "options": "Donor", "width": 150},
        {"label": _("Donor Name"), "fieldname": "donor_name", "fieldtype": "Data", "width": 200},
        {"label": _("Donor Type"), "fieldname": "donor_type", "fieldtype": "Data", "width": 100},
        {"label": _("BSN/RSIN"), "fieldname": "tax_id", "fieldtype": "Data", "width": 120},
        {"label": _("Agreement Type"), "fieldname": "agreement_type", "fieldtype": "Data", "width": 180},
        {"label": _("Agreement #"), "fieldname": "agreement_number", "fieldtype": "Data", "width": 140},
        {
            "label": _("Total Donations"),
            "fieldname": "total_donations",
            "fieldtype": "Currency",
            "width": 120,
        },
        {"label": _("# of Donations"), "fieldname": "donation_count", "fieldtype": "Int", "width": 100},
        {"label": _("Reportable"), "fieldname": "reportable", "fieldtype": "Check", "width": 90},
        {"label": _("First Donation"), "fieldname": "first_donation", "fieldtype": "Date", "width": 110},
        {"label": _("Last Donation"), "fieldname": "last_donation", "fieldtype": "Date", "width": 110},
        {"label": _("Consent Given"), "fieldname": "consent_given", "fieldtype": "Check", "width": 100},
    ]


def get_data(filters):
    conditions = get_conditions(filters)

    # Get donation data with donor information
    donation_data = frappe.db.sql(
        """
        SELECT
            d.donor,
            donor.donor_name,
            donor.donor_type,
            CASE
                WHEN donor.donor_type = 'Individual' THEN donor.bsn_encrypted
                WHEN donor.donor_type = 'Organization' THEN donor.rsin_encrypted
                ELSE NULL
            END as tax_id_encrypted,
            donor.anbi_consent_given as consent_given,
            SUM(d.amount) as total_donations,
            COUNT(d.name) as donation_count,
            MIN(d.date) as first_donation,
            MAX(d.date) as last_donation,
            MAX(d.belastingdienst_reportable) as reportable,
            GROUP_CONCAT(DISTINCT d.periodic_donation_agreement) as agreements,
            GROUP_CONCAT(DISTINCT d.anbi_agreement_number) as agreement_numbers
        FROM `tabDonation` d
        INNER JOIN `tabDonor` donor ON d.donor = donor.name
        WHERE d.paid = 1
        AND d.docstatus = 1
        {conditions}
        GROUP BY d.donor
        ORDER BY total_donations DESC
    """.format(
            conditions=conditions
        ),
        filters,
        as_dict=1,
    )

    # Get minimum reportable amount
    min_reportable = (
        frappe.db.get_single_value("Verenigingen Settings", "anbi_minimum_reportable_amount") or 500
    )

    # Process data
    data = []
    for row in donation_data:
        # Decrypt tax ID if available
        tax_id = None
        if row.tax_id_encrypted:
            try:
                from frappe.utils.password import decrypt

                tax_id = decrypt(row.tax_id_encrypted)
            except:
                tax_id = "***ENCRYPTED***"

        # Determine agreement type
        agreement_type = "One-time Donations"
        agreement_number = ""

        if row.agreements and row.agreements != "None":
            # Get periodic donation agreement details
            agreement_names = [a for a in row.agreements.split(",") if a and a != "None"]
            if agreement_names:
                agreement = frappe.get_doc("Periodic Donation Agreement", agreement_names[0])
                if agreement.anbi_eligible:
                    agreement_type = "ANBI Periodic Agreement (5+ years)"
                else:
                    agreement_type = "Donation Pledge (1-4 years)"
                agreement_number = agreement.agreement_number
        elif row.agreement_numbers:
            agreement_type = "ANBI Agreement"
            agreement_number = row.agreement_numbers.split(",")[0]

        # Determine if reportable
        reportable = row.reportable or (row.total_donations >= min_reportable)

        data.append(
            {
                "donor": row.donor,
                "donor_name": row.donor_name,
                "donor_type": row.donor_type or "Individual",
                "tax_id": tax_id or "",
                "agreement_type": agreement_type,
                "agreement_number": agreement_number,
                "total_donations": row.total_donations,
                "donation_count": row.donation_count,
                "reportable": reportable,
                "first_donation": row.first_donation,
                "last_donation": row.last_donation,
                "consent_given": row.consent_given,
            }
        )

    return data


def get_conditions(filters):
    conditions = []

    if filters.get("from_date"):
        conditions.append("d.date >= %(from_date)s")

    if filters.get("to_date"):
        conditions.append("d.date <= %(to_date)s")

    if filters.get("donor"):
        conditions.append("d.donor = %(donor)s")

    if filters.get("donor_type"):
        conditions.append("donor.donor_type = %(donor_type)s")

    if filters.get("only_reportable"):
        min_reportable = (
            frappe.db.get_single_value("Verenigingen Settings", "anbi_minimum_reportable_amount") or 500
        )
        conditions.append(f"(d.belastingdienst_reportable = 1 OR d.amount >= {min_reportable})")

    if filters.get("only_periodic"):
        conditions.append("d.periodic_donation_agreement IS NOT NULL")

    if filters.get("consent_status") == "Given":
        conditions.append("donor.anbi_consent_given = 1")
    elif filters.get("consent_status") == "Not Given":
        conditions.append("(donor.anbi_consent_given = 0 OR donor.anbi_consent_given IS NULL)")

    return " AND " + " AND ".join(conditions) if conditions else ""
