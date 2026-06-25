"""
Real-integration tests for
``verenigingen/services/member/donor/donor_management_service.py``.

DonorManagementService creates Donor records from Member data using the
OperationResult pattern (never raises). Tests drive real Member / Donor /
Customer / Address records (no business-logic mocking) as Administrator so
the secure_document_operation permission gates (Donor:create, Customer:write)
are actually satisfied.

Covered behaviour:
- check_donor_exists: existing (email match), not-existing, missing member
- create_donor_from_member: happy path (fields + member link), duplicate guard,
  customer linkage, address copy, Dutch phone formatting
- _format_dutch_phone_number: 06.., 0.., already-prefixed, no-leading-zero
- _copy_address_from_member: formatted string, no-address failure
- _link_customer_to_donor: success + missing customer failure

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.tests.services.test_donor_management_service
"""

import frappe

from verenigingen.services.member.donor.donor_management_service import (
    DonorManagementService,
    get_donor_management_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorManagementService(EnhancedTestCase):
    """Exercise DonorManagementService end-to-end with real records."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.service = get_donor_management_service()

    # ----------------------------------------------------------- helpers

    def _make_member(self, **kwargs):
        kwargs.setdefault("first_name", "Mgmt")
        kwargs.setdefault("last_name", "Donor")
        return self.create_test_member(**kwargs)

    def _track_donor(self, donor_name):
        if donor_name and frappe.db.exists("Donor", donor_name):
            self.track_doc("Donor", donor_name)

    # ----------------------------------------------------------- factory

    def test_factory_returns_service(self):
        self.assertIsInstance(get_donor_management_service(), DonorManagementService)

    # ----------------------------------------------------------- check_donor_exists

    def test_check_donor_exists_missing_member(self):
        result = self.service.check_donor_exists("Member-DOES-NOT-EXIST")
        self.assertTrue(result.success)
        self.assertIsNone(result.data)

    def test_check_donor_exists_no_donor(self):
        member = self._make_member()
        result = self.service.check_donor_exists(member.name)
        self.assertTrue(result.success)
        self.assertIsNone(result.data)

    def test_check_donor_exists_finds_by_email(self):
        member = self._make_member()
        donor = self.create_test_donor(
            donor_name=member.full_name, donor_email=member.email, donor_type="Individual"
        )
        result = self.service.check_donor_exists(member.name)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data)
        self.assertEqual(result.data["donor_name"], donor.name)
        self.assertEqual(result.data["donor_display_name"], donor.donor_name)

    # ----------------------------------------------------------- create_donor_from_member

    def test_create_donor_from_member_happy_path(self):
        member = self._make_member(contact_number="0612345678")
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result.success, msg=result.error_message)
        self._track_donor(result.data)

        donor = frappe.get_doc("Donor", result.data)
        self.assertEqual(donor.donor_name, member.full_name)
        self.assertEqual(donor.donor_email, member.email)
        self.assertEqual(donor.donor_type, "Individual")
        self.assertEqual(donor.donor_category, "Regular Donor")
        self.assertEqual(donor.member, member.name)
        # Dutch mobile 06.. formatted with +31.
        self.assertEqual(donor.phone, "+31612345678")

    def test_create_donor_from_member_links_customer(self):
        """Member auto-gets a Customer; the donor creation back-links it."""
        member = self._make_member()
        self.assertTrue(member.customer, "factory should auto-create a customer")
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result.success, msg=result.error_message)
        self._track_donor(result.data)
        # Customer.donor now points back to the new donor.
        self.assertEqual(frappe.db.get_value("Customer", member.customer, "donor"), result.data)

    def test_create_donor_from_member_duplicate_returns_failure(self):
        member = self._make_member()
        existing = self.create_test_donor(
            donor_name=member.full_name, donor_email=member.email, donor_type="Individual"
        )
        result = self.service.create_donor_from_member(member.name)
        self.assertFalse(result.success)
        self.assertIn("already exists", result.error_message.lower())
        # The existing donor name is surfaced in metadata.
        self.assertEqual(result.metadata.get("donor_name"), existing.name)

    def test_create_donor_from_member_copies_address(self):
        member = self._make_member(address_line1="Keizersgracht 123", city="Amsterdam", postal_code="1015 CJ")
        self.assertTrue(member.primary_address)
        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result.success, msg=result.error_message)
        self._track_donor(result.data)
        donor = frappe.get_doc("Donor", result.data)
        # Address is a single formatted "part, part, ..." string.
        self.assertIn("Keizersgracht 123", donor.address)
        self.assertIn("Amsterdam", donor.address)

    # ----------------------------------------------------------- _format_dutch_phone_number

    def test_format_phone_dutch_mobile(self):
        result = self.service._format_dutch_phone_number("0612345678")
        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    def test_format_phone_landline_leading_zero(self):
        result = self.service._format_dutch_phone_number("0201234567")
        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31201234567")

    def test_format_phone_already_prefixed_passthrough(self):
        result = self.service._format_dutch_phone_number("+31612345678")
        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    def test_format_phone_no_leading_zero_gets_prefix(self):
        result = self.service._format_dutch_phone_number("612345678")
        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    def test_format_phone_strips_spaces(self):
        result = self.service._format_dutch_phone_number("06 12 34 56 78")
        self.assertTrue(result.success)
        self.assertEqual(result.data, "+31612345678")

    # ----------------------------------------------------------- _copy_address_from_member

    def test_copy_address_no_primary_address_fails(self):
        member = self._make_member()
        self.assertFalse(member.primary_address)
        result = self.service._copy_address_from_member(member)
        self.assertFalse(result.success)
        self.assertIn("no primary address", result.error_message.lower())

    def test_copy_address_formats_parts(self):
        member = self._make_member(address_line1="Damrak 1", city="Amsterdam", postal_code="1012 LG")
        result = self.service._copy_address_from_member(member)
        self.assertTrue(result.success, msg=result.error_message)
        self.assertIn("Damrak 1", result.data)
        self.assertIn("Amsterdam", result.data)
        self.assertIn("Netherlands", result.data)

    # ----------------------------------------------------------- _link_customer_to_donor

    def test_link_customer_to_donor_success(self):
        member = self._make_member()
        donor = self.create_test_donor(
            donor_name="Link Target", donor_email=f"link.{frappe.generate_hash(length=6)}@example.com"
        )
        result = self.service._link_customer_to_donor(member.customer, donor.name)
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(frappe.db.get_value("Customer", member.customer, "donor"), donor.name)

    def test_link_customer_to_donor_missing_customer_fails(self):
        donor = self.create_test_donor(
            donor_name="Orphan Link", donor_email=f"orphan.{frappe.generate_hash(length=6)}@example.com"
        )
        result = self.service._link_customer_to_donor("Customer-DOES-NOT-EXIST", donor.name)
        self.assertFalse(result.success)
        self.assertTrue(result.errors)
