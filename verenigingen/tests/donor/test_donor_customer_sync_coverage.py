"""
Coverage tests for donor_customer_sync helper branches not covered elsewhere.

Targets:
- clear_customer_link_on_donor_delete: nulls the Customer.donor back-reference
  when the linked Donor is removed (prevents dangling links / recycled-name reuse)
- get_sync_status_summary: aggregate shape over real Donor rows
- bulk_sync_donors_to_customers: filtered run returns the expected result shape
"""

import frappe

from verenigingen.services.member.donor.donor_customer_sync import (
    bulk_sync_donors_to_customers,
    clear_customer_link_on_donor_delete,
    get_sync_status_summary,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorCustomerSyncCoverage(VereningingenTestCase):
    """Real-DB coverage for donor-customer sync helpers."""

    def _make_customer(self, name):
        customer = frappe.new_doc("Customer")
        customer.customer_name = name
        customer.customer_group = frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups"
        customer.territory = "All Territories"
        customer.insert()
        self.track_doc("Customer", customer.name)
        return customer

    def test_clear_customer_link_on_donor_delete_nulls_backreference(self):
        """Deleting a donor clears Customer.donor pointing at it."""
        customer = self._make_customer("Sync Del Cust")
        donor = self.create_test_donor(donor_email="syncdel@example.com")

        # Point the customer back at the donor (the dangling-risk link).
        frappe.db.set_value("Customer", customer.name, "donor", donor.name)
        self.assertEqual(frappe.db.get_value("Customer", customer.name, "donor"), donor.name)

        # Simulate the on_trash hook firing for this donor.
        clear_customer_link_on_donor_delete(donor)

        # The back-reference is now cleared, so the donor can be removed cleanly.
        self.assertFalse(frappe.db.get_value("Customer", customer.name, "donor"))

    def test_clear_customer_link_no_linked_customers_is_noop(self):
        """A donor with no referencing customers leaves everything untouched."""
        donor = self.create_test_donor(donor_email="syncdel.none@example.com")
        # Should not raise even when nothing references the donor.
        clear_customer_link_on_donor_delete(donor)

    def test_get_sync_status_summary_counts_are_consistent(self):
        """Both aggregates count every Donor exactly once, so their totals must agree
        with each other and with the real Donor row count (catches a GROUP BY / dict
        comprehension regression, not just the shape)."""
        # Ensure at least one donor exists so the aggregate is non-empty.
        self.create_test_donor(donor_email="syncsummary@example.com")

        summary = get_sync_status_summary()
        self.assertNotIn("error", summary)
        self.assertIsInstance(summary["sync_status"], dict)
        self.assertIsInstance(summary["customer_links"], dict)

        total_donors = frappe.db.count("Donor")
        self.assertGreaterEqual(total_donors, 1)
        self.assertEqual(sum(summary["sync_status"].values()), total_donors)
        self.assertEqual(sum(summary["customer_links"].values()), total_donors)

    def test_bulk_sync_with_restrictive_filter_returns_counts(self):
        """A bulk sync constrained to a nonexistent donor processes zero rows."""
        result = bulk_sync_donors_to_customers(filters={"name": "Donor-NONEXISTENT-ZZZ"})
        self.assertNotIn("error", result)
        self.assertEqual(result["total_processed"], 0)
        self.assertEqual(result["created_customers"], 0)
        self.assertEqual(result["updated_customers"], 0)
        self.assertEqual(result["errors"], 0)
