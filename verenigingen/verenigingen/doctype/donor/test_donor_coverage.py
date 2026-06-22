"""
Real-DB coverage tests for the Donor DocType controller
(``verenigingen/verenigingen/doctype/donor/donor.py``).

The existing ``test_donor.py`` covers BSN/RSIN validation + encryption roundtrip.
This file fills the large uncovered surface:

- permlevel access + masked decrypt on onload / get_decrypted_*
- mask_identifier edge cases
- the Customer integration subsystem: sync_with_customer / get_or_create_customer
  / create_customer_from_donor / sync_data_to_customer / Contact creation /
  _get_donor_customer_group / get_customer_info / refresh_customer_sync
- parse_donor_name_for_contact and _calculate_sync_hash change detection

Customer sync is gated behind an in-test opt-in flag
(``enable_customer_sync_in_test``); the factory helper
``create_test_donor_with_sync`` sets it, and ``refresh_customer_sync`` sets it
internally, so the real ERPNext Customer/Contact records get created. No
business logic is mocked.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorCoverage(VereningingenTestCase):
    def _new_donor(self, **kwargs):
        data = {
            "donor_name": f"Cov Donor {frappe.generate_hash(length=6)}",
            "donor_type": "Individual",
            "donor_email": f"covdonor.{frappe.generate_hash(length=8).lower()}@example.com",
        }
        data.update(kwargs)
        donor = frappe.new_doc("Donor")
        donor.update(data)
        return donor

    # ------------------------------------------------------------ mask_identifier

    def test_mask_identifier_masks_all_but_last_four(self):
        donor = self._new_donor()
        self.assertEqual(donor.mask_identifier("123456789"), "*****6789")

    def test_mask_identifier_short_value_unchanged(self):
        donor = self._new_donor()
        # < 4 chars is returned as-is (nothing to mask meaningfully).
        self.assertEqual(donor.mask_identifier("12"), "12")
        self.assertEqual(donor.mask_identifier(""), "")
        self.assertIsNone(donor.mask_identifier(None))

    # ------------------------------------------------------------ permlevel access

    def test_has_permlevel_access_admin_true(self):
        # Running as Administrator (System Manager) grants permlevel access.
        donor = self.create_test_donor()
        self.assertTrue(donor.has_permlevel_access())

    # ------------------------------------------------------------ decrypt helpers

    def test_get_decrypted_bsn_returns_plaintext_for_authorized(self):
        donor = self._new_donor(bsn_citizen_service_number="123456782")  # valid BSN
        donor.insert()
        self.track_doc("Donor", donor.name)
        # After insert the stored value is encrypted; the decrypt accessor returns
        # the original plaintext for an authorized (admin) user.
        reloaded = frappe.get_doc("Donor", donor.name)
        self.assertTrue(reloaded.is_encrypted(reloaded.bsn_citizen_service_number))
        self.assertEqual(reloaded.get_decrypted_bsn(), "123456782")

    def test_get_decrypted_rsin_returns_plaintext_for_authorized(self):
        # 9-digit RSIN that passes eleven-proof (weight +1 on last digit): 123456789
        donor = self._new_donor(donor_type="Organization", rsin_organization_tax_number="123456789")
        donor.insert()
        self.track_doc("Donor", donor.name)
        reloaded = frappe.get_doc("Donor", donor.name)
        self.assertEqual(reloaded.get_decrypted_rsin(), "123456789")

    def test_onload_masks_encrypted_bsn_for_display(self):
        donor = self._new_donor(bsn_citizen_service_number="123456782")
        donor.insert()
        self.track_doc("Donor", donor.name)
        reloaded = frappe.get_doc("Donor", donor.name)
        # onload (authorized) decrypts then masks for display: only last 4 shown.
        reloaded.onload()
        self.assertTrue(reloaded.bsn_citizen_service_number.endswith("6782"))
        self.assertIn("*", reloaded.bsn_citizen_service_number)

    # ------------------------------------------------------------ name parsing

    def test_parse_donor_name_two_parts(self):
        donor = self._new_donor(donor_name="Jan de Vries")
        first, last = donor.parse_donor_name_for_contact()
        self.assertEqual(first, "Jan de")
        self.assertEqual(last, "Vries")

    def test_parse_donor_name_single_part(self):
        donor = self._new_donor(donor_name="Cher")
        first, last = donor.parse_donor_name_for_contact()
        self.assertEqual(first, "Cher")
        self.assertEqual(last, "")

    def test_parse_donor_name_empty(self):
        donor = self._new_donor(donor_name="")
        self.assertEqual(donor.parse_donor_name_for_contact(), ("", ""))

    # ------------------------------------------------------------ sync hash

    def test_calculate_sync_hash_changes_with_email(self):
        donor = self._new_donor(donor_email="a@example.com")
        h1 = donor._calculate_sync_hash()
        donor.donor_email = "b@example.com"
        h2 = donor._calculate_sync_hash()
        self.assertNotEqual(h1, h2)

    # ------------------------------------------------------------ customer group

    def test_get_donor_customer_group_creates_donors_group(self):
        donor = self.create_test_donor()
        group = donor._get_donor_customer_group()
        self.assertTrue(group)
        # The resolved group must be a leaf (is_group == 0) so Customer.insert accepts it.
        self.assertEqual(frappe.db.get_value("Customer Group", group, "is_group"), 0)

    # ------------------------------------------------------------ full customer sync

    def test_create_test_donor_with_sync_links_customer(self):
        donor = self.create_test_donor_with_sync()
        self.assertTrue(donor.customer, "sync should create + link a Customer")
        self.assertTrue(frappe.db.exists("Customer", donor.customer))
        # The Customer carries the donor back-reference.
        self.assertEqual(frappe.db.get_value("Customer", donor.customer, "donor"), donor.name)

    def test_get_or_create_customer_idempotent(self):
        donor = self.create_test_donor_with_sync()
        existing = donor.customer
        # Re-resolving must return the already-linked customer, not create a new one.
        self.assertEqual(donor.get_or_create_customer(), existing)

    def test_sync_data_to_customer_propagates_name_change(self):
        donor = self.create_test_donor_with_sync()
        customer = donor.customer
        new_name = f"Renamed Donor {frappe.generate_hash(length=6)}"
        donor.donor_name = new_name
        donor.flags.enable_customer_sync_in_test = True
        donor.sync_data_to_customer(customer)
        frappe.db.commit()
        self.assertEqual(frappe.db.get_value("Customer", customer, "customer_name"), new_name)

    def test_get_customer_info_returns_data_when_linked(self):
        donor = self.create_test_donor_with_sync()
        info = donor.get_customer_info()
        self.assertEqual(info["name"], donor.customer)
        self.assertIn("outstanding_amount", info)

    def test_get_customer_info_empty_when_unlinked(self):
        donor = self.create_test_donor()  # no customer link
        self.assertEqual(donor.get_customer_info(), {})

    def test_refresh_customer_sync_creates_and_links(self):
        # A donor created WITHOUT sync has no customer; refresh_customer_sync
        # forces the in-test opt-in, runs the sync, saves and reloads.
        donor = self.create_test_donor()
        self.assertFalse(donor.customer)
        result = donor.refresh_customer_sync()
        self.assertIn("refreshed", result["message"])
        donor.reload()
        self.assertTrue(donor.customer, "refresh must create + persist a customer link")
        self.track_doc("Customer", donor.customer)

    def test_sync_with_customer_skipped_when_ignore_flag_set(self):
        donor = self.create_test_donor()
        donor.flags.ignore_customer_sync = True
        donor.flags.enable_customer_sync_in_test = True
        donor.sync_with_customer()
        # Skipped entirely: no customer link established.
        self.assertFalse(donor.customer)

    def test_sync_with_customer_skipped_in_test_without_optin(self):
        donor = self.create_test_donor()
        # in_test is set during the run and no opt-in flag -> sync is a no-op.
        donor.sync_with_customer()
        self.assertFalse(donor.customer)
