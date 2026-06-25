"""
Real-integration tests for
``verenigingen/services/member/donor/donor_customer_sync.py``.

These exercise the Donor<->Customer sync hooks and admin utilities with real
Donor / Customer records (no business-logic mocking) as Administrator. The hooks
are intentionally inert "in test context" unless the
``enable_customer_sync_in_test`` flag is set, so tests opt in explicitly to
drive the real sync path.

Covered behaviour:
- sync_donor_to_customer: skip flags (ignore_customer_sync / from_customer_sync),
  and a real sync that creates+links a Customer and persists customer_sync_status
- sync_customer_to_donor: name/email propagation back to the linked donor
- clear_customer_link_on_donor_delete: nulls the Customer.donor back-ref
- get_sync_status_summary: status counts and the NULL/""->"Unknown" collision
  fold (regression guard for the previously-dropped NULL bucket)
- bulk_sync_donors_to_customers: processes/creates customers and reports counts

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.tests.services.test_donor_customer_sync
"""

import frappe

from verenigingen.services.member.donor import donor_customer_sync as dcs
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorCustomerSync(EnhancedTestCase):
    """Exercise donor-customer sync hooks and utilities with real records."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    # ----------------------------------------------------------- helpers

    def _unique_email(self, prefix="dcs"):
        return f"{prefix}.{frappe.generate_hash(length=8)}@example.com"

    def _make_donor(self, **kwargs):
        kwargs.setdefault("donor_name", "Sync Donor")
        kwargs.setdefault("donor_email", self._unique_email())
        kwargs.setdefault("donor_type", "Individual")
        return self.create_test_donor(**kwargs)

    def _make_customer(self, **kwargs):
        kwargs.setdefault("customer_group", "Individual")
        return self.factory.create_test_customer(**kwargs)

    # ----------------------------------------------------------- sync_donor_to_customer (skips)

    def test_sync_donor_to_customer_skips_on_ignore_flag(self):
        donor = self._make_donor()
        donor.flags.ignore_customer_sync = True
        # Should return without creating/linking a customer.
        dcs.sync_donor_to_customer(donor)
        donor.reload()
        self.assertFalse(donor.customer)

    def test_sync_donor_to_customer_skips_when_from_customer_sync(self):
        donor = self._make_donor()
        donor.flags.from_customer_sync = True
        dcs.sync_donor_to_customer(donor)
        donor.reload()
        self.assertFalse(donor.customer)

    def test_sync_donor_to_customer_skips_in_test_without_optin(self):
        # Default test context: no enable_customer_sync_in_test flag -> inert.
        donor = self._make_donor()
        dcs.sync_donor_to_customer(donor)
        donor.reload()
        self.assertFalse(donor.customer)

    # ----------------------------------------------------------- sync_donor_to_customer (real)

    def test_sync_donor_to_customer_creates_and_links_customer(self):
        donor = self._make_donor(donor_name="Real Sync Donor")
        # Opt in to the real sync path inside the test context.
        donor.flags.enable_customer_sync_in_test = True
        dcs.sync_donor_to_customer(donor)

        # The hook persists the customer link + sync status via db_set.
        persisted = frappe.db.get_value(
            "Donor", donor.name, ["customer", "customer_sync_status"], as_dict=True
        )
        self.assertTrue(persisted.customer, "a customer should have been created and linked")
        self.assertEqual(persisted.customer_sync_status, "Synced")
        self.track_doc("Customer", persisted.customer)
        # The created customer carries the donor's name.
        customer = frappe.get_doc("Customer", persisted.customer)
        self.assertEqual(customer.customer_name, donor.donor_name)
        # Back-reference customer.donor points to the donor.
        self.assertEqual(customer.donor, donor.name)

    # ----------------------------------------------------------- sync_customer_to_donor

    def test_sync_customer_to_donor_skips_without_donor_ref(self):
        customer = self._make_customer()
        # No donor back-ref -> nothing happens, no exception.
        dcs.sync_customer_to_donor(customer)  # should be a no-op

    def test_sync_customer_to_donor_propagates_name_and_email(self):
        donor = self._make_donor(donor_name="Before Name")
        customer = self._make_customer(customer_name="After Name", email_id=self._unique_email("cust"))
        # Link the customer to the donor (back-ref the hook keys on).
        frappe.db.set_value("Customer", customer.name, "donor", donor.name)
        customer.donor = donor.name

        dcs.sync_customer_to_donor(customer)

        donor.reload()
        self.assertEqual(donor.donor_name, "After Name")
        self.assertEqual(donor.donor_email, customer.email_id)
        self.assertEqual(donor.customer, customer.name)
        self.assertEqual(donor.customer_sync_status, "Synced")

    # ----------------------------------------------------------- clear_customer_link_on_donor_delete

    def test_clear_customer_link_on_donor_delete(self):
        donor = self._make_donor()
        customer = self._make_customer()
        frappe.db.set_value("Customer", customer.name, "donor", donor.name)
        self.assertEqual(frappe.db.get_value("Customer", customer.name, "donor"), donor.name)

        # Simulate the on_trash hook.
        dcs.clear_customer_link_on_donor_delete(donor)

        self.assertIsNone(frappe.db.get_value("Customer", customer.name, "donor"))

    # ----------------------------------------------------------- get_sync_status_summary

    def test_get_sync_status_summary_shape_and_counts(self):
        # Create donors with distinct sync statuses.
        self._make_donor()  # default status (Pending/None)
        synced = self._make_donor()
        frappe.db.set_value("Donor", synced.name, "customer_sync_status", "Synced")

        summary = dcs.get_sync_status_summary()
        self.assertIn("sync_status", summary)
        self.assertIn("customer_links", summary)
        # The Synced bucket counts at least our one synced donor.
        self.assertGreaterEqual(summary["sync_status"].get("Synced", 0), 1)

    def test_get_sync_status_summary_folds_null_and_empty_into_unknown(self):
        """Regression guard: NULL and '' customer_sync_status both fold to
        'Unknown' and their counts are SUMMED (a dict-comprehension previously
        dropped the NULL bucket, undercounting the total)."""
        d_null = self._make_donor()
        d_empty = self._make_donor()
        # One NULL, one empty string -> both should land in "Unknown".
        frappe.db.sql("UPDATE `tabDonor` SET customer_sync_status = NULL WHERE name = %s", d_null.name)
        frappe.db.set_value("Donor", d_empty.name, "customer_sync_status", "")

        summary = dcs.get_sync_status_summary()
        unknown = summary["sync_status"].get("Unknown", 0)
        # Both donors must be counted under "Unknown" (>= 2, not overwritten to 1).
        self.assertGreaterEqual(
            unknown, 2, msg=f"NULL+empty should both fold into Unknown; got {summary['sync_status']}"
        )

    # ----------------------------------------------------------- bulk_sync_donors_to_customers

    def test_bulk_sync_creates_customers(self):
        donor = self._make_donor(donor_name="Bulk Sync Donor")
        # bulk_sync calls donor.sync_with_customer(), which is inert in test
        # context unless the global opt-in flag is set. Enable it for the call
        # so the real customer-creation path runs, then restore.
        prior = frappe.flags.get("enable_customer_sync_in_test")
        frappe.flags.enable_customer_sync_in_test = True
        try:
            # Restrict the bulk run to our donor to keep it deterministic.
            result = dcs.bulk_sync_donors_to_customers(filters={"name": donor.name})
        finally:
            frappe.flags.enable_customer_sync_in_test = prior
        self.assertEqual(result["total_processed"], 1)
        # A customer is created (donor had none) -> created_customers incremented.
        self.assertEqual(result["created_customers"], 1)
        self.assertEqual(result["errors"], 0)

        # Verify the donor is now linked to a real customer.
        donor.reload()
        self.assertTrue(donor.customer)
        self.track_doc("Customer", donor.customer)
