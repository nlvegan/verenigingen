"""
Real-integration tests for ``verenigingen/services/donation/donor_service.py``
(was ~14.5% covered — almost entirely untested).

The service wraps donor lookup/creation/summary helpers used by the donation
flow. Tests create real Donor / Donation / Customer records (no business-logic
mocking) and run as Administrator. A throwaway real ``Donation`` document is
used as the service's ``donation_doc`` constructor argument.

Field-presence notes (verified against the Donor / Donation schema):
  - Donor has NO ``privacy_consent``, ``donor_status``, ``is_blacklisted`` or
    ``marketing_consent`` fields; the service reads them defensively via
    ``getattr`` / ``hasattr``. ``validate_donor_eligibility`` therefore always
    reports "Privacy consent required" because ``privacy_consent`` is absent.
  - Donation has NO ``is_recurring``, ``anbi_eligible`` or ``payment_status``
    field. Direct ``doc.is_recurring`` access raised AttributeError (now read
    defensively in the service); recurringness is taken from ``status ==
    "Recurring"``. ``_validate_recurring_eligibility`` is also tested directly.
    ``get_donor_donation_summary`` previously crashed on the missing
    ``payment_status`` column (now uses ``paid``), and
    ``link_donor_to_customer`` crashed on the missing ``donor_reference``
    column (now uses ``donor``).
"""

import frappe

from verenigingen.services.donation.donor_service import (
    DonationDonorService,
    get_donation_donor_service,
    get_donor_by_email,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorService(VereningingenTestCase):
    """Exercise DonationDonorService end to end with real records."""

    def setUp(self):
        super().setUp()
        self._ensure_territory()
        self.donor = self.create_test_donor(
            donor_name=f"SvcDonor {frappe.generate_hash(length=6)}",
            donor_email=f"svc.{frappe.generate_hash(length=6)}@example.com",
            donor_type="Individual",
        )
        # The service only reads donation.donor / donation.is_recurring /
        # donation.get("anbi_eligible") from its constructor arg. An in-memory
        # (uninserted) Donation doc backs the service without requiring a
        # Company master (a fresh test site may have none).
        self.service = get_donation_donor_service(self._new_donation(donor=self.donor.name))

    @staticmethod
    def _new_donation(donor=None):
        d = frappe.new_doc("Donation")
        if donor:
            d.donor = donor
        return d

    @staticmethod
    def _ensure_territory():
        if not frappe.db.exists("Territory", "All Territories"):
            t = frappe.new_doc("Territory")
            t.territory_name = "All Territories"
            t.is_group = 1
            t.insert()
            frappe.db.commit()

    # ----------------------------------------------------------- get_donor_by_email

    def test_get_donor_by_email_found(self):
        found = get_donor_by_email(self.donor.donor_email)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, self.donor.name)

    def test_get_donor_by_email_not_found(self):
        self.assertIsNone(get_donor_by_email(f"missing.{frappe.generate_hash(length=8)}@example.com"))

    def test_get_donor_by_email_empty(self):
        self.assertIsNone(get_donor_by_email(""))
        self.assertIsNone(get_donor_by_email(None))

    def test_get_donor_by_email_returns_latest(self):
        # Two donors share an email -> the most recently created is returned.
        email = f"dup.{frappe.generate_hash(length=6)}@example.com"
        self.create_test_donor(donor_name="First Dup", donor_email=email, donor_type="Individual")
        second = self.create_test_donor(
            donor_name="Second Dup", donor_email=email, donor_type="Individual"
        )
        found = get_donor_by_email(email)
        self.assertEqual(found.name, second.name)

    # ----------------------------------------------------------- get_service factory

    def test_factory_returns_service(self):
        self.assertIsInstance(self.service, DonationDonorService)

    # ----------------------------------------------------------- _get_default_donor_type

    def test_get_default_donor_type(self):
        dtype = self.service._get_default_donor_type()
        # Either a configured default in Verenigingen Settings, or "Individual".
        self.assertTrue(dtype)
        expected = frappe.db.get_single_value("Verenigingen Settings", "default_donor_type")
        self.assertEqual(dtype, expected or "Individual")

    # ----------------------------------------------------------- ensure_donor_exists

    def test_ensure_donor_exists_returns_existing(self):
        # donation.donor is already set and exists -> returned unchanged.
        self.assertEqual(self.service.ensure_donor_exists(), self.donor.name)

    def test_ensure_donor_exists_throws_for_non_website_user_without_donor(self):
        donation = self._new_donation()  # no donor set
        service = get_donation_donor_service(donation)
        # Administrator is not a Website User -> must throw "select a Donor".
        with self.assertRaises(frappe.ValidationError):
            service.ensure_donor_exists()

    # ----------------------------------------------------------- create_donor_from_donation_data

    def test_create_donor_from_donation_data_new(self):
        email = f"new.{frappe.generate_hash(length=6)}@example.com"
        name = self.service.create_donor_from_donation_data(
            donor_name="Created From Data", email=email, phone="+31612345678"
        )
        self.track_doc("Donor", name)
        donor = frappe.get_doc("Donor", name)
        self.assertEqual(donor.donor_email, email)
        self.assertEqual(donor.phone, "+31612345678")
        self.assertEqual(donor.anbi_consent, 0)  # new donors require explicit consent

    def test_create_donor_from_donation_data_invalid_email(self):
        with self.assertRaises(frappe.ValidationError):
            self.service.create_donor_from_donation_data(
                donor_name="Bad Email", email="not-an-email"
            )

    def test_create_donor_from_donation_data_updates_existing(self):
        # Existing donor with a SHORT name -> a longer name update is applied.
        email = f"existing.{frappe.generate_hash(length=6)}@example.com"
        existing = self.create_test_donor(donor_name="Al", donor_email=email, donor_type="Individual")
        returned = self.service.create_donor_from_donation_data(
            donor_name="Alexander Longername", email=email, phone="+31687654321"
        )
        self.assertEqual(returned, existing.name)
        existing.reload()
        self.assertEqual(existing.donor_name, "Alexander Longername")
        self.assertEqual(existing.phone, "+31687654321")

    # ----------------------------------------------------------- _update_existing_donor

    def test_update_existing_donor_no_change(self):
        # Same name, phone already set -> no update, returns name.
        donor = self.create_test_donor(
            donor_name="Already Complete",
            donor_email=f"complete.{frappe.generate_hash(length=6)}@example.com",
            donor_type="Individual",
            phone="+31623456789",
        )
        result = self.service._update_existing_donor(donor, "Already Complete", phone="+31687654321")
        self.assertEqual(result, donor.name)
        donor.reload()
        # Phone NOT overwritten (already set); name unchanged.
        self.assertEqual(donor.phone, "+31623456789")
        self.assertEqual(donor.donor_name, "Already Complete")

    # ----------------------------------------------------------- validate_donor_eligibility

    def test_validate_donor_eligibility_nonexistent(self):
        issues = self.service.validate_donor_eligibility("NON-EXISTENT-DONOR")
        self.assertEqual(issues, ["Donor does not exist"])

    def test_validate_donor_eligibility_reports_privacy_consent(self):
        # Donor has no privacy_consent field -> the privacy-consent issue is
        # always reported. This documents real service behavior.
        issues = self.service.validate_donor_eligibility(self.donor.name)
        self.assertIn("Privacy consent required for donation processing", issues)

    # ----------------------------------------------------------- _validate_recurring_eligibility

    def test_validate_recurring_eligibility_missing_email_false(self):
        donor = frappe._dict(donor_email=None)
        self.assertFalse(self.service._validate_recurring_eligibility(donor))

    def test_validate_recurring_eligibility_no_privacy_consent_false(self):
        # Has email but no privacy_consent -> ineligible.
        donor = frappe.get_doc("Donor", self.donor.name)
        self.assertFalse(self.service._validate_recurring_eligibility(donor))

    # ----------------------------------------------------------- get_donor_donation_summary

    def test_get_donor_donation_summary_nonexistent(self):
        self.assertEqual(self.service.get_donor_donation_summary("NON-EXISTENT"), {})

    def test_get_donor_donation_summary_shape(self):
        summary = self.service.get_donor_donation_summary(self.donor.name)
        # The draft donation is docstatus 0 -> not counted (filter docstatus=1).
        self.assertIn("total_donations", summary)
        self.assertIn("total_amount", summary)
        self.assertIn("purpose_breakdown", summary)
        self.assertEqual(summary["total_donations"], 0)

    # ----------------------------------------------------------- get_donor_preferences

    def test_get_donor_preferences_nonexistent(self):
        self.assertEqual(self.service.get_donor_preferences("NON-EXISTENT"), {})

    def test_get_donor_preferences_defaults(self):
        prefs = self.service.get_donor_preferences(self.donor.name)
        # Fields absent on Donor fall back to documented defaults.
        self.assertEqual(prefs["communication_method"], "Email")
        self.assertEqual(prefs["tax_receipt_preference"], "Email")
        self.assertIn("anbi_consent", prefs)
        self.assertFalse(prefs["privacy_consent"])  # no such field -> default False

    # ----------------------------------------------------------- update_donor_donation_history

    def test_update_donor_donation_history_does_not_raise(self):
        # History update is best-effort; it must never raise even if the
        # underlying history manager has issues. Assert it returns cleanly.
        self.assertIsNone(self.service.update_donor_donation_history(self.donor.name))

    # ----------------------------------------------------------- create_donor_for_website_user

    def test_create_donor_for_website_user_returns_existing(self):
        # When a donor already exists for the session user's email, that donor
        # is returned rather than creating a duplicate. Drive this by making a
        # Website User whose email matches an existing donor.
        email = f"webuser.{frappe.generate_hash(length=6)}@example.com"
        existing = self.create_test_donor(
            donor_name="Web Existing", donor_email=email, donor_type="Individual"
        )
        user = self.create_test_user(email, roles=[])
        frappe.db.set_value("User", user.name, "user_type", "Website User")
        with self.as_user(user.name):
            service = get_donation_donor_service(self._new_donation(donor=self.donor.name))
            returned = service.create_donor_for_website_user()
        self.assertEqual(returned, existing.name)

    # ----------------------------------------------------------- link_donor_to_customer

    def test_link_donor_to_customer_empty(self):
        self.assertIsNone(self.service.link_donor_to_customer(""))

    def test_link_donor_to_customer_creates_customer(self):
        customer_name = self.service.link_donor_to_customer(self.donor.name)
        self.assertTrue(customer_name)
        self.track_doc("Customer", customer_name)
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_name, self.donor.donor_name)
        self.assertEqual(customer.email_id, self.donor.donor_email)
