"""
Coverage tests for donor_auto_creation helper functions.

The end-to-end Payment Entry / Journal Entry pipelines are already covered by
test_donor_auto_creation.py and test_donor_auto_creation_comprehensive.py. This
module targets the remaining helper branches directly with real Customer/Donor
documents:

- create_donor_from_customer: Organization vs Individual type, placeholder email,
  mobile_no copy, defensive existing-donor short-circuit, customer back-link
- is_customer_group_eligible: configured-list vs allow-all
- has_existing_donor: by customer link and by Customer.donor reference
"""

import frappe

from verenigingen.services.member.donor.donor_auto_creation import (
    create_donor_from_customer,
    has_existing_donor,
    is_customer_group_eligible,
)
from verenigingen.tests.setup import ensure_member_test_masters
from verenigingen.tests.utils.base import VereningingenTestCase


class _Settings:
    """Lightweight settings stand-in for is_customer_group_eligible."""

    def __init__(self, donor_customer_groups):
        self.donor_customer_groups = donor_customer_groups


class TestDonorAutoCreationHelpers(VereningingenTestCase):
    """Targeted helper-branch coverage for auto donor creation."""

    def setUp(self):
        super().setUp()
        ensure_member_test_masters()
        if not frappe.db.exists("Customer Group", "Individual"):
            cg = frappe.new_doc("Customer Group")
            cg.customer_group_name = "Individual"
            cg.insert()

    def _make_customer(self, name, *, customer_type="Individual", email_id=None, mobile_no=None):
        """Create and track a minimal Customer for helper tests."""
        customer = frappe.new_doc("Customer")
        customer.customer_name = name
        customer.customer_group = "Individual"
        customer.customer_type = customer_type
        customer.territory = "All Territories"
        if email_id:
            customer.email_id = email_id
        if mobile_no:
            customer.mobile_no = mobile_no
        customer.insert()
        self.track_doc("Customer", customer.name)
        return customer

    # ----- is_customer_group_eligible -----

    def test_eligible_allows_all_when_unconfigured(self):
        """No configured groups => every customer group is eligible."""
        self.assertTrue(is_customer_group_eligible("Anything", _Settings("")))
        self.assertTrue(is_customer_group_eligible("Whatever", _Settings(None)))

    def test_eligible_respects_configured_list(self):
        """A configured comma list only admits listed groups (whitespace-trimmed)."""
        settings = _Settings("Donors, Individual")
        self.assertTrue(is_customer_group_eligible("Individual", settings))
        self.assertTrue(is_customer_group_eligible("Donors", settings))
        self.assertFalse(is_customer_group_eligible("Corporate", settings))

    # ----- has_existing_donor -----

    def test_has_existing_donor_false_for_unlinked_customer(self):
        """A customer with no donor is reported as not having one."""
        customer = self._make_customer("Unlinked Cust")
        self.assertFalse(has_existing_donor(customer.name))

    def test_has_existing_donor_true_via_donor_customer_link(self):
        """A Donor whose customer field points at the customer is detected."""
        customer = self._make_customer("Linked Cust")
        donor = self.create_test_donor(donor_email="linked.cust@example.com")
        donor.customer = customer.name
        donor.flags.ignore_customer_sync = True
        donor.save()

        self.assertTrue(has_existing_donor(customer.name))

    # ----- create_donor_from_customer -----

    def test_create_donor_individual_with_email_and_mobile(self):
        """An Individual customer yields an Individual donor copying email and phone."""
        customer = self._make_customer(
            "Indiv Donor Cust",
            customer_type="Individual",
            email_id="indiv.donor@example.com",
            mobile_no="+31611112222",
        )

        donor_name = create_donor_from_customer(customer, 200.0, "TEST-REF-PE-1")
        self.assertIsNotNone(donor_name)
        self.track_doc("Donor", donor_name)

        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_type, "Individual")
        self.assertEqual(donor.donor_email, "indiv.donor@example.com")
        self.assertEqual(donor.phone, "+31611112222")
        self.assertEqual(donor.customer, customer.name)
        self.assertEqual(donor.created_from_payment, "TEST-REF-PE-1")
        self.assertEqual(donor.customer_sync_status, "Auto-Created")
        # Customer back-reference is set.
        self.assertEqual(frappe.db.get_value("Customer", customer.name, "donor"), donor_name)

    def test_create_donor_company_becomes_organization_with_placeholder_email(self):
        """A Company customer with no email becomes an Organization donor with a placeholder email."""
        customer = self._make_customer("Org Donor Cust", customer_type="Company")
        # No email_id on the customer -> placeholder generated.
        donor_name = create_donor_from_customer(customer, 500.0, "TEST-REF-JE-1")
        self.assertIsNotNone(donor_name)
        self.track_doc("Donor", donor_name)

        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_type, "Organization")
        # Placeholder email derived from the customer name.
        self.assertTrue(donor.donor_email.endswith("@example.com"))
        self.assertIn("donor.", donor.donor_email)

    def test_create_donor_short_circuits_when_donor_exists(self):
        """The defensive existing-donor check returns None without creating a duplicate."""
        customer = self._make_customer("Existing Donor Cust")
        existing = self.create_test_donor(donor_email="existing.cust@example.com")
        existing.customer = customer.name
        existing.flags.ignore_customer_sync = True
        existing.save()

        before = frappe.db.count("Donor", {"customer": customer.name})
        result = create_donor_from_customer(customer, 300.0, "TEST-REF-DUP")
        after = frappe.db.count("Donor", {"customer": customer.name})

        self.assertIsNone(result)
        self.assertEqual(before, after)
