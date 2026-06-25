"""
Real-integration tests for
``verenigingen/services/member/integration/member_donor_integration_service.py``.

MemberDonorIntegrationService.create_donor_from_member() builds a Donor from a
Member, copying name/email/phone/address and back-linking the member's Customer.
Unlike DonorManagementService it returns a plain dict ({success, message,
donor_name|error}).

Tests use real Member / Donor / Customer / Address records (no business-logic
mocking) as Administrator so the secure_document_operation permission gates are
satisfied.

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.tests.services.test_member_donor_integration_service
"""

import frappe

from verenigingen.services.member.integration.member_donor_integration_service import (
    MemberDonorIntegrationService,
    get_member_donor_integration_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberDonorIntegrationService(EnhancedTestCase):
    """Exercise MemberDonorIntegrationService.create_donor_from_member."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.service = get_member_donor_integration_service()

    # ----------------------------------------------------------- helpers

    def _make_member(self, **kwargs):
        kwargs.setdefault("first_name", "Integ")
        kwargs.setdefault("last_name", "Donor")
        return self.create_test_member(**kwargs)

    def _track_donor(self, donor_name):
        if donor_name and frappe.db.exists("Donor", donor_name):
            self.track_doc("Donor", donor_name)

    # ----------------------------------------------------------- factory

    def test_factory_returns_service(self):
        self.assertIsInstance(get_member_donor_integration_service(), MemberDonorIntegrationService)

    # ----------------------------------------------------------- create_donor_from_member

    def test_create_donor_happy_path(self):
        member = self._make_member(contact_number="0612345678")
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result["success"], msg=result.get("message"))
        self._track_donor(result["donor_name"])

        donor = frappe.get_doc("Donor", result["donor_name"])
        self.assertEqual(donor.donor_name, member.full_name)
        self.assertEqual(donor.donor_email, member.email)
        self.assertEqual(donor.donor_type, "Individual")
        self.assertEqual(donor.contact_person, member.full_name)
        self.assertEqual(donor.donor_category, "Regular Donor")
        self.assertEqual(donor.member, member.name)
        self.assertEqual(donor.phone, "+31612345678")

    def test_create_donor_no_phone_leaves_phone_empty(self):
        member = self._make_member()
        # Ensure the member truly has no contact number.
        member.contact_number = None
        member.save()
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result["success"], msg=result.get("message"))
        self._track_donor(result["donor_name"])
        donor = frappe.get_doc("Donor", result["donor_name"])
        self.assertFalse(donor.phone)

    def test_create_donor_dutch_landline_formatting(self):
        member = self._make_member(contact_number="0201234567")
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result["success"], msg=result.get("message"))
        self._track_donor(result["donor_name"])
        donor = frappe.get_doc("Donor", result["donor_name"])
        self.assertEqual(donor.phone, "+31201234567")

    def test_create_donor_already_prefixed_keeps_country_code(self):
        # A number already carrying a +country code is passed through with its
        # country code intact (the service does not re-prefix it).
        member = self._make_member(contact_number="+31612345678")
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result["success"], msg=result.get("message"))
        self._track_donor(result["donor_name"])
        donor = frappe.get_doc("Donor", result["donor_name"])
        self.assertEqual(donor.phone, "+31612345678")
        # No double-prefixing.
        self.assertFalse(donor.phone.startswith("+31+31"))

    def test_create_donor_duplicate_returns_existing(self):
        member = self._make_member()
        existing = self.create_test_donor(
            donor_name=member.full_name, donor_email=member.email, donor_type="Individual"
        )
        result = self.service.create_donor_from_member(member.name)
        self.assertFalse(result["success"])
        self.assertIn("already exists", result["message"].lower())
        self.assertEqual(result["donor_name"], existing.name)

    def test_create_donor_links_customer(self):
        member = self._make_member()
        self.assertTrue(member.customer, "factory should auto-create a customer")
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result["success"], msg=result.get("message"))
        self._track_donor(result["donor_name"])
        self.assertEqual(frappe.db.get_value("Customer", member.customer, "donor"), result["donor_name"])

    def test_create_donor_copies_address(self):
        member = self._make_member(address_line1="Prinsengracht 263", city="Amsterdam", postal_code="1016 GV")
        self.assertTrue(member.primary_address)
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result["success"], msg=result.get("message"))
        self._track_donor(result["donor_name"])
        donor = frappe.get_doc("Donor", result["donor_name"])
        self.assertIn("Prinsengracht 263", donor.address)
        self.assertIn("Amsterdam", donor.address)

    def test_create_donor_missing_member_returns_error(self):
        result = self.service.create_donor_from_member("Member-DOES-NOT-EXIST")
        self.assertFalse(result["success"])
        # The DoesNotExist is caught and reported, not raised.
        self.assertIn("error", result)
        self.assertTrue(result["error"])
