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
                WHEN donor.donor_type = 'Individual' THEN donor.bsn_citizen_service_number
                WHEN donor.donor_type = 'Organization' THEN donor.rsin_organization_tax_number
                ELSE NULL
            END as tax_id_value,
            donor.anbi_consent as consent_given,
            SUM(d.amount) as total_donations,
            COUNT(d.name) as donation_count,
            MIN(d.donation_date) as first_donation,
            MAX(d.donation_date) as last_donation,
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
        # Get tax ID (may be encrypted)
        tax_id = ""
        if row.get("tax_id_value"):
            # Check if it looks like encrypted data (starts with specific patterns)
            if row.get("tax_id_value", "").startswith(("gAAAAAB", "$")):
                try:
                    from frappe.utils.password import decrypt

                    tax_id = decrypt(row.get("tax_id_value"))
                except Exception:
                    tax_id = "***ENCRYPTED***"
            else:
                # Plain text or already decrypted
                tax_id = row.get("tax_id_value")

        # Determine agreement type
        agreement_type = "One-time Donations"
        agreement_number = ""

        if row.get("agreements") and row.get("agreements") != "None":
            # Get periodic donation agreement details
            agreement_names = [a for a in row.get("agreements", "").split(",") if a and a != "None"]
            if agreement_names:
                try:
                    agreement = frappe.get_doc("Periodic Donation Agreement", agreement_names[0])
                    if agreement.anbi_eligible:
                        agreement_type = "ANBI Periodic Agreement (5+ years)"
                    else:
                        agreement_type = "Donation Pledge (1-4 years)"
                    agreement_number = agreement.agreement_number
                except:
                    # Handle case where agreement doesn't exist
                    agreement_type = "Periodic Agreement"
                    agreement_number = agreement_names[0]
        elif row.get("agreement_numbers"):
            agreement_type = "ANBI Agreement"
            agreement_number = row.get("agreement_numbers", "").split(",")[0]

        # Determine if reportable
        reportable = row.get("reportable") or (row.get("total_donations", 0) >= min_reportable)

        data.append(
            {
                "donor": row.get("donor"),
                "donor_name": row.get("donor_name"),
                "donor_type": row.get("donor_type") or "Individual",
                "tax_id": tax_id or "",
                "agreement_type": agreement_type,
                "agreement_number": agreement_number,
                "total_donations": row.get("total_donations"),
                "donation_count": row.get("donation_count"),
                "reportable": reportable,
                "first_donation": row.get("first_donation"),
                "last_donation": row.get("last_donation"),
                "consent_given": row.get("consent_given"),
            }
        )

    return data


def get_conditions(filters):
    conditions = []

    if filters.get("from_date"):
        conditions.append("d.donation_date >= %(from_date)s")

    if filters.get("to_date"):
        conditions.append("d.donation_date <= %(to_date)s")

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
        conditions.append("donor.anbi_consent = 1")
    elif filters.get("consent_status") == "Not Given":
        conditions.append("(donor.anbi_consent = 0 OR donor.anbi_consent IS NULL)")

    return " AND " + " AND ".join(conditions) if conditions else ""
