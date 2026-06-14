"""
Real-integration tests for the Donor doctype controller
``verenigingen/verenigingen/doctype/donor/donor.py`` (was ~68% covered).

Focus areas that were untested or thinly covered:
  - onload / has_permlevel_access (permission-gated decryption)
  - encrypt_field / decrypt_field / is_encrypted / mask_identifier
  - decrypt_sensitive_fields
  - get_decrypted_bsn / get_decrypted_rsin (permission-gated accessors)
  - validate_bsn_eleven_proof / validate_rsin_eleven_proof
  - sync_with_customer / create_customer_from_donor / get_or_create_customer_contact
  - create_new_customer_contact / _get_donor_customer_group / get_customer_info

BSN/RSIN are encrypted at rest. Tests assert plaintext only through the
``get_decrypted_*`` accessors (or by decrypting via ``decrypt_field``), never by
reading the stored field directly. Tests run as Administrator (which holds
permlevel access) unless a dedicated non-admin user is created.
"""

import frappe

from verenigingen.tests.fixtures.dutch_validation_helpers import (
    generate_valid_bsn,
    generate_valid_rsin,
    get_test_bsn_numbers,
)
from verenigingen.tests.utils.base import VereningingenTestCase

IBAN_TEST = "NL13TEST0123456789"


class TestDonorController(VereningingenTestCase):
    """Exercise the Donor controller end to end with real records."""

    def setUp(self):
        super().setUp()
        self.bsn = get_test_bsn_numbers()[0]  # "123456782" - valid eleven-proof BSN
        self.rsin = generate_valid_rsin()
        self._ensure_territory()

    @staticmethod
    def _ensure_territory():
        """Customer creation requires a Territory; a freshly-provisioned test
        site can lack the ERPNext-seeded 'All Territories' root. Create it once
        so the donor->customer sync paths are reachable (infra setup, not a
        product assertion)."""
        if not frappe.db.exists("Territory", "All Territories"):
            t = frappe.new_doc("Territory")
            t.territory_name = "All Territories"
            t.is_group = 1
            t.insert()
            frappe.db.commit()

    def _make_individual_donor(self, with_bsn=True):
        kwargs = {
            "donor_name": f"Indiv {frappe.generate_hash(length=6)}",
            "donor_email": f"indiv.{frappe.generate_hash(length=6)}@example.com",
            "donor_type": "Individual",
        }
        if with_bsn:
            kwargs["bsn_citizen_service_number"] = self.bsn
        return self.create_test_donor(**kwargs)

    def _make_org_donor(self, with_rsin=True):
        kwargs = {
            "donor_name": f"Org {frappe.generate_hash(length=6)}",
            "donor_email": f"org.{frappe.generate_hash(length=6)}@example.com",
            "donor_type": "Organization",
        }
        if with_rsin:
            kwargs["rsin_organization_tax_number"] = self.rsin
        return self.create_test_donor(**kwargs)

    # ----------------------------------------------------------- eleven-proof validation

    def test_validate_bsn_eleven_proof_valid(self):
        donor = frappe.new_doc("Donor")
        for bsn in get_test_bsn_numbers():
            self.assertTrue(donor.validate_bsn_eleven_proof(bsn), f"{bsn} should be a valid BSN")

    def test_validate_bsn_eleven_proof_invalid(self):
        donor = frappe.new_doc("Donor")
        self.assertFalse(donor.validate_bsn_eleven_proof("123456789"))  # fails eleven-proof
        self.assertFalse(donor.validate_bsn_eleven_proof("12345"))  # wrong length

    def test_validate_rsin_eleven_proof_valid(self):
        donor = frappe.new_doc("Donor")
        self.assertTrue(donor.validate_rsin_eleven_proof(generate_valid_rsin()))

    def test_validate_rsin_eleven_proof_invalid(self):
        donor = frappe.new_doc("Donor")
        # "111111111" weighted by [9..1] sums to 45, not divisible by 11 -> invalid.
        self.assertFalse(donor.validate_rsin_eleven_proof("111111111"))
        self.assertFalse(donor.validate_rsin_eleven_proof("1234"))  # wrong length

    def test_invalid_bsn_rejected_on_save(self):
        # A BSN that fails the eleven-proof must be rejected by validate().
        with self.assertRaises(frappe.ValidationError):
            self.create_test_donor(
                donor_name=f"Bad BSN {frappe.generate_hash(length=6)}",
                donor_type="Individual",
                bsn_citizen_service_number="123456789",
            )

    def test_bsn_wrong_length_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.create_test_donor(
                donor_name=f"Short BSN {frappe.generate_hash(length=6)}",
                donor_type="Individual",
                bsn_citizen_service_number="12345",
            )

    # ----------------------------------------------------------- encryption primitives

    def test_encrypt_decrypt_field_roundtrip(self):
        donor = frappe.new_doc("Donor")
        enc = donor.encrypt_field("987654321")
        self.assertTrue(enc.startswith("ENC:"))
        self.assertTrue(donor.is_encrypted(enc))
        self.assertEqual(donor.decrypt_field(enc), "987654321")

    def test_encrypt_field_empty_passthrough(self):
        donor = frappe.new_doc("Donor")
        self.assertEqual(donor.encrypt_field(""), "")
        self.assertEqual(donor.encrypt_field(None), None)

    def test_decrypt_field_non_encrypted_passthrough(self):
        donor = frappe.new_doc("Donor")
        self.assertEqual(donor.decrypt_field("plaintext"), "plaintext")
        self.assertEqual(donor.decrypt_field(""), "")

    def test_is_encrypted(self):
        donor = frappe.new_doc("Donor")
        self.assertTrue(donor.is_encrypted("ENC:abc"))
        self.assertFalse(donor.is_encrypted("abc"))
        self.assertFalse(donor.is_encrypted(""))

    def test_mask_identifier(self):
        donor = frappe.new_doc("Donor")
        self.assertEqual(donor.mask_identifier("123456789"), "*****6789")
        # Shorter than 4 chars -> returned unchanged.
        self.assertEqual(donor.mask_identifier("abc"), "abc")
        self.assertEqual(donor.mask_identifier(""), "")

    # ----------------------------------------------------------- stored encryption

    def test_bsn_encrypted_at_rest(self):
        donor = self._make_individual_donor()
        # The persisted value must be encrypted, never plaintext.
        stored = frappe.db.get_value("Donor", donor.name, "bsn_citizen_service_number")
        self.assertTrue(stored.startswith("ENC:"))
        self.assertNotIn(self.bsn, stored)

    def test_rsin_encrypted_at_rest(self):
        donor = self._make_org_donor()
        stored = frappe.db.get_value("Donor", donor.name, "rsin_organization_tax_number")
        self.assertTrue(stored.startswith("ENC:"))
        self.assertNotIn(self.rsin, stored)

    # ----------------------------------------------------------- permlevel access / accessors

    def test_has_permlevel_access_as_administrator(self):
        donor = self._make_individual_donor()
        # Administrator always has permlevel access.
        self.assertTrue(donor.has_permlevel_access())

    def test_get_decrypted_bsn_as_administrator(self):
        donor = self._make_individual_donor()
        donor.reload()
        self.assertEqual(donor.get_decrypted_bsn(), self.bsn)

    def test_get_decrypted_rsin_as_administrator(self):
        donor = self._make_org_donor()
        donor.reload()
        self.assertEqual(donor.get_decrypted_rsin(), self.rsin)

    def test_get_decrypted_bsn_none_when_absent(self):
        donor = self._make_individual_donor(with_bsn=False)
        donor.reload()
        self.assertIn(donor.get_decrypted_bsn(), (None, ""))

    def test_get_decrypted_bsn_denied_for_unprivileged_user(self):
        donor = self._make_individual_donor()
        user = self.create_test_user(
            f"unpriv.{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Member"],
        )
        fresh = frappe.get_doc("Donor", donor.name)
        with self.as_user(user.name):
            self.assertFalse(fresh.has_permlevel_access())
            # The accessor guards with frappe.throw(), which raises ValidationError.
            with self.assertRaises(frappe.ValidationError):
                fresh.get_decrypted_bsn()

    def test_get_decrypted_rsin_denied_for_unprivileged_user(self):
        donor = self._make_org_donor()
        user = self.create_test_user(
            f"unpriv.{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Member"],
        )
        fresh = frappe.get_doc("Donor", donor.name)
        with self.as_user(user.name):
            with self.assertRaises(frappe.ValidationError):
                fresh.get_decrypted_rsin()

    # ----------------------------------------------------------- decrypt_sensitive_fields / onload

    def test_decrypt_sensitive_fields_masks_for_display(self):
        donor = self._make_individual_donor()
        fresh = frappe.get_doc("Donor", donor.name)
        # Before decrypt: stored encrypted.
        self.assertTrue(fresh.is_encrypted(fresh.bsn_citizen_service_number))
        fresh.decrypt_sensitive_fields()
        # After decrypt_sensitive_fields: masked plaintext (last 4 digits visible).
        self.assertTrue(fresh.bsn_citizen_service_number.endswith(self.bsn[-4:]))
        self.assertIn("*", fresh.bsn_citizen_service_number)

    def test_onload_decrypts_for_privileged_user(self):
        donor = self._make_individual_donor()
        # Administrator (privileged) -> onload masks the encrypted BSN.
        fresh = frappe.get_doc("Donor", donor.name)
        fresh.run_method("onload")
        self.assertTrue(fresh.bsn_citizen_service_number.endswith(self.bsn[-4:]))
        self.assertIn("*", fresh.bsn_citizen_service_number)

    def test_onload_keeps_encrypted_for_unprivileged_user(self):
        donor = self._make_individual_donor()
        user = self.create_test_user(
            f"unpriv.{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Member"],
        )
        with self.as_user(user.name):
            fresh = frappe.get_doc("Donor", donor.name)
            fresh.run_method("onload")
            # Unprivileged user must NOT get decryption; stays encrypted.
            self.assertTrue(fresh.is_encrypted(fresh.bsn_citizen_service_number))

    # ----------------------------------------------------------- anbi consent date

    def test_anbi_consent_date_autoset(self):
        donor = self.create_test_donor(
            donor_name=f"Consent {frappe.generate_hash(length=6)}",
            donor_type="Individual",
            anbi_consent=1,
        )
        donor.reload()
        self.assertTrue(donor.anbi_consent_date)

    # ----------------------------------------------------------- customer integration

    def test_get_customer_info_no_customer_returns_empty(self):
        donor = self._make_individual_donor(with_bsn=False)
        self.assertEqual(donor.get_customer_info(), {})

    def test_get_donor_customer_group_creates_donors_group(self):
        donor = self._make_individual_donor(with_bsn=False)
        # Clear the configured donor_customer_group so the auto-create path runs.
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_group", None)
        group = donor._get_donor_customer_group()
        self.assertTrue(group)
        # Resolved group must be a real, leaf (non-group) Customer Group.
        self.assertEqual(frappe.db.get_value("Customer Group", group, "is_group"), 0)

    def test_create_customer_from_donor_creates_linked_customer(self):
        donor = self._make_individual_donor(with_bsn=False)
        customer_name = donor.create_customer_from_donor()
        self.assertTrue(customer_name)
        self.track_doc("Customer", customer_name)
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_name, donor.donor_name)
        self.assertEqual(customer.customer_type, "Individual")
        # The donor link is set after both docs exist.
        self.assertEqual(frappe.db.get_value("Customer", customer_name, "donor"), donor.name)

    def test_create_customer_from_org_donor_is_company(self):
        donor = self._make_org_donor(with_rsin=False)
        customer_name = donor.create_customer_from_donor()
        self.assertTrue(customer_name)
        self.track_doc("Customer", customer_name)
        self.assertEqual(
            frappe.db.get_value("Customer", customer_name, "customer_type"), "Company"
        )

    def test_get_or_create_customer_contact(self):
        donor = self._make_individual_donor(with_bsn=False)
        customer_name = donor.create_customer_from_donor()
        self.track_doc("Customer", customer_name)
        # create_customer_from_donor already created a primary contact; fetching
        # again must return the same contact, not a duplicate.
        contact = donor.get_or_create_customer_contact(customer_name)
        self.assertTrue(contact)
        self.track_doc("Contact", contact.name)
        primary = frappe.db.get_value("Customer", customer_name, "customer_primary_contact")
        self.assertEqual(contact.name, primary)

    def test_create_new_customer_contact_carries_email(self):
        donor = self._make_individual_donor(with_bsn=False)
        # Build a bare customer to attach a fresh contact to.
        customer_name = donor.create_customer_from_donor()
        self.track_doc("Customer", customer_name)
        contact = donor.create_new_customer_contact(customer_name)
        self.assertTrue(contact)
        self.track_doc("Contact", contact.name)
        emails = [e.email_id for e in contact.email_ids]
        self.assertIn(donor.donor_email, emails)

    def test_sync_with_customer_creates_and_links_customer(self):
        donor = self._make_individual_donor(with_bsn=False)
        # Opt in to customer sync (suppressed in tests by default).
        donor.flags.enable_customer_sync_in_test = True
        donor.sync_with_customer()
        self.assertTrue(donor.customer, "sync should have linked a customer")
        self.track_doc("Customer", donor.customer)
        self.assertEqual(donor.customer_sync_status, "Synced")
        self.assertEqual(frappe.db.get_value("Customer", donor.customer, "donor"), donor.name)

    def test_sync_with_customer_skipped_when_flag_disabled(self):
        donor = self._make_individual_donor(with_bsn=False)
        # In tests, without the opt-in flag, sync must be a no-op.
        donor.sync_with_customer()
        self.assertFalse(donor.customer)

    def test_get_customer_info_after_sync(self):
        donor = self._make_individual_donor(with_bsn=False)
        donor.flags.enable_customer_sync_in_test = True
        donor.sync_with_customer()
        self.track_doc("Customer", donor.customer)
        info = donor.get_customer_info()
        self.assertEqual(info.get("name"), donor.customer)
        self.assertIn("outstanding_amount", info)
