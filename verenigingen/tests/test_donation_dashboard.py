"""Donation's Connections tab counts Payment Entries through `custom_donation` (#1318).

`donation_dashboard.py` used to map `non_standard_fieldnames["Payment Entry"] =
"reference_name"`. That is not a column of Payment Entry (it is the Dynamic Link on the
`Payment Entry Reference` child table, and ERPNext never lets a Donation sit there), so
the count was always 0. The field that really links a Payment Entry to a Donation is the
Custom Field `Payment Entry.custom_donation` (Link to Donation), which
`refund_utility.get_donation_refund_info` reads.

Probe shortcut, stated: nothing in the app writes `custom_donation` from Python, so the
linked Payment Entry is built by the real PaymentEntryFactory (a submitted, ledger-posting
Payment Entry for a donor) and `custom_donation` is then set with `db.set_value`, standing in
for whoever fills the field in.
"""

import frappe
from frappe.desk.notifications import get_open_count

from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.shared.test_payment_entry_factory_coverage import (
    _FactoryBase,
)


class TestDonationDashboard(_FactoryBase):
    def _payment_entry_for(self, donor, customer):
        pe = self.factory_obj.create_payment_entry(
            PaymentContext("donation", "Donor", donor.name),
            {"payment_id": f"tr_{frappe.generate_hash(length=12)}", "amount": "15.50", "method": "ideal"},
            customer=customer.name,
        )
        self.assertIsNotNone(pe, "the factory must return a submitted Payment Entry")
        return pe

    def test_connections_count_only_payment_entries_linked_by_custom_donation(self):
        customer = self.factory.create_test_customer()
        donor = self.create_test_donor(donor_name="Dashboard Donor", customer=customer.name)
        donation = self.create_test_donation(donor=donor.name, donation_purpose_type="General")
        linked = self._payment_entry_for(donor, customer)
        self._payment_entry_for(donor, customer)  # same donor, NOT linked: must not count
        frappe.db.set_value("Payment Entry", linked.name, "custom_donation", donation.name)

        found = get_open_count("Donation", donation.name)["count"]["external_links_found"]
        counts = [d for d in found if d["doctype"] == "Payment Entry"]
        self.assertEqual(len(counts), 1)
        self.assertEqual(counts[0]["fieldname"], "custom_donation")
        self.assertEqual(counts[0]["count"], 1)
