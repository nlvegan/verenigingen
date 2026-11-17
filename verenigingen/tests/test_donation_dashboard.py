"""Donation's Connections tab must not offer a Payment Entry mapping that cannot match (#1318).

`donation_dashboard.py` mapped `non_standard_fieldnames["Payment Entry"] = "reference_name"`.
`reference_name` is not a column of Payment Entry; it is the Dynamic Link on the
`Payment Entry Reference` child table, filtered here with no `reference_doctype`. A
match would need a Payment Entry Reference row whose `reference_doctype` is "Donation",
and ERPNext's `validate_reference_documents` refuses every doctype but
Sales Order / Sales Invoice / Journal Entry / Dunning / Payment Entry for a Customer
(Purchase Order / Purchase Invoice / ... for a Supplier). Donations reach the ledger
through `Donation.sales_invoice` / `journal_entry`, so the count is always 0.
Measured read-only on veg11: 0 of 3,528 Payment Entry Reference rows point at a Donation.
"""

from unittest.mock import patch

import frappe
from frappe.desk.notifications import get_open_count

from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonationDashboard(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_dashboard_offers_no_payment_entry_connection(self):
        donor = self.create_test_donor(donor_name="Dashboard Donor")
        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.amount = 10.0
        donation.donation_date = frappe.utils.today()
        donation.mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name")
        with patch("frappe.sendmail"):
            donation.insert()
        self.track_doc("Donation", donation.name)

        result = get_open_count("Donation", donation.name)
        found = {d["doctype"] for d in result["count"]["external_links_found"]}
        self.assertNotIn("Payment Entry", found)

    def test_payment_entry_cannot_reference_a_donation(self):
        """Tripwire for the premise: no party type may reference a Donation."""
        for party_type in ("Customer", "Supplier", "Employee", "Shareholder"):
            pe = frappe.new_doc("Payment Entry")
            pe.party_type = party_type
            valid = pe.get_valid_reference_doctypes()
            # Control: the list is a real, non-empty answer containing Journal Entry.
            self.assertIn("Journal Entry", valid)
            self.assertNotIn("Donation", valid)
