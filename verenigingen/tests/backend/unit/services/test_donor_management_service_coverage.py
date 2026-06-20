# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Coverage tests for DonorManagementService branches not covered by the existing
test_donor_management_service.py:

- _copy_address_from_member: success path (formats a real Address)
- _link_customer_to_donor: links a real Customer back to a Donor
- create_donor_from_member: full happy path (address copied, customer linked)
"""

import frappe

from verenigingen.services.member.donor.donor_management_service import DonorManagementService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorManagementServiceCoverage(EnhancedTestCase):
    """Happy-path / linkage coverage for donor management."""

    def setUp(self):
        super().setUp()
        self.service = DonorManagementService()

    def _member_with_address(self):
        member = self.create_test_member(first_name="Donor", last_name="Mgmt")
        address = self.factory.create_address(
            address_line1="Prinsengracht 200",
            city="Amsterdam",
            pincode="1016 HH",
            link_doctype="Member",
            link_name=member.name,
        )
        member.primary_address = address.name
        member.save()
        return member, address

    def test_copy_address_success_formats_parts(self):
        """A real primary address is flattened into a comma-joined string."""
        member, _address = self._member_with_address()
        result = self.service._copy_address_from_member(member)
        self.assertTrue(result.success, result.error_message)
        self.assertIn("Prinsengracht 200", result.data)
        self.assertIn("Amsterdam", result.data)
        self.assertIn("1016 HH", result.data)

    def test_link_customer_to_donor_sets_backlink(self):
        """Linking writes the donor name onto the customer's donor field."""
        customer = self.factory.create_test_customer()
        donor = self.create_test_donor(donor_email="linkme.mgmt@example.com")

        result = self.service._link_customer_to_donor(customer.name, donor.name)
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(frappe.db.get_value("Customer", customer.name, "donor"), donor.name)

    def test_create_donor_from_member_full_happy_path(self):
        """create_donor_from_member copies address, links customer, returns donor name."""
        member, _address = self._member_with_address()
        customer = self.factory.create_test_customer()
        member.customer = customer.name
        member.contact_number = "0612345678"
        member.save()

        result = self.service.create_donor_from_member(member.name)
        self.assertTrue(result.success, result.error_message)
        donor_name = result.data
        self.track_doc("Donor", donor_name)

        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_email, member.email)
        self.assertEqual(donor.member, member.name)
        # Dutch phone formatting applied.
        self.assertEqual(donor.phone, "+31612345678")
        # Address was copied into the donor.address text field.
        self.assertIn("Prinsengracht 200", donor.address or "")
        # Customer back-link established.
        self.assertEqual(frappe.db.get_value("Customer", customer.name, "donor"), donor_name)
