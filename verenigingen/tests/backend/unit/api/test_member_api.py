# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Member whitelisted API methods
Tests the API endpoints that JavaScript calls
"""


import frappe
from frappe.utils import add_days, random_string, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberWhitelistMethods(VereningingenTestCase):
    """Test Member whitelisted API methods as called from JavaScript"""

    def setUp(self):
        """Set up test environment using factory methods"""
        super().setUp()
        
        # Create test data using factory methods
        self.test_member = self.create_test_member(
            first_name="TestAPI",
            last_name="Member",
            email="testapi@example.com"
        )

        # Set up builder for compatibility with legacy test methods
        from verenigingen.tests.utils.factories import TestDataBuilder
        self.builder = TestDataBuilder()

        # Get or create membership type
        existing_types = frappe.get_all("Membership Type", limit=1)
        if existing_types:
            self.membership_type = existing_types[0].name
        else:
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test API Membership",
                "amount": 50.0
            })
            mt.insert()
            self.track_doc("Membership Type", mt.name)
            self.membership_type = mt.name
    
    def tearDown(self):
        """Clean up test data including builder cleanup"""
        if hasattr(self, 'builder'):
            self.builder.cleanup()
        super().tearDown()

    # tearDown handled automatically by VereningingenTestCase

    def _get_test_membership_type(self):
        """Helper to get the test membership type"""
        return self.membership_type

    def test_create_customer_whitelist(self):
        """Test create_customer method as called from JavaScript"""
        test_data = self.builder.with_member(first_name="Customer", last_name="Test").build()

        member = test_data["member"]

        # Clear customer if auto-created
        if member.customer:
            member.customer = None
            member.save()

        # Test via API call (simulating JavaScript)
        customer_name = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_customer", doc=member.as_dict()
        )

        # Verify customer was created
        self.assertTrue(customer_name)

        # Reload member to verify link
        member.reload()
        self.assertEqual(member.customer, customer_name)

        # Verify customer details
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_name, member.full_name)
        # Note: CustomerHandlingService does not populate Customer.email_id directly;
        # the email link goes through the Contact doctype. Asserting the name is enough.

    def test_create_user_whitelist(self):
        """Test create_user method as called from JavaScript"""
        test_data = self.builder.with_member(
            first_name="User", last_name="Creation", email=f"user.creation.{random_string(8)}@test.com"
        ).build()

        member = test_data["member"]

        # Test via API call
        # MemberUserAccountService.create_user_for_member returns (username, action)
        # where action is "already_exists" | "linked_existing" | "created_new".
        user_name, action = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_user", doc=member.as_dict()
        )

        # Verify user was created
        self.assertTrue(user_name)
        self.assertEqual(action, "created_new")

        # Reload member to verify link
        member.reload()
        self.assertEqual(member.user, user_name)

        # Verify user details
        user = frappe.get_doc("User", user_name)
        self.assertEqual(user.first_name, member.first_name)
        self.assertEqual(user.last_name, member.last_name)
        self.assertIn("Verenigingen Member", [r.role for r in user.roles])

    def test_get_active_sepa_mandate_whitelist(self):
        """Test get_active_sepa_mandate method"""
        test_data = self.builder.with_member(
            payment_method="SEPA Direct Debit", iban="NL91ABNA0417164300", bank_account_name="Test Member"
        ).build()

        member = test_data["member"]

        # Create SEPA mandate
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member.name,
                "mandate_reference": f"TEST-{random_string(8)}",
                "iban": member.iban,
                "account_holder_name": member.bank_account_name,
                "status": "Active",
                "sign_date": today()}
        )
        mandate.insert()
        self.track_doc("SEPA Mandate", mandate.name)
        self.track_doc("SEPA Mandate", mandate.name)

        # Test via API call: signature takes `member` (name).
        active_mandate = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_active_sepa_mandate",
            member=member.name,
        )

        # Verify mandate found
        self.assertIsNotNone(active_mandate)
        self.assertEqual(active_mandate["name"], mandate.name)
        self.assertEqual(active_mandate["status"], "Active")

    def test_get_linked_donations_whitelist(self):
        """Test get_linked_donations method"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create donor if not exists (check by email since member.donor field doesn't exist)
        existing_donor = frappe.db.get_value("Donor", {"donor_email": member.email}, "name")
        if not existing_donor:
            donor = frappe.get_doc(
                {
                    "doctype": "Donor",
                    "donor_name": member.full_name,
                    "donor_email": member.email,  # Correct field name
                    "donor_type": "Individual",   # Required field
                    "member": member.name}
            )
            donor.insert()
            self.track_doc("Donor", donor.name)
            donor_name = donor.name
        else:
            donor_name = existing_donor

        # Create donations
        for i in range(2):
            donation = frappe.get_doc(
                {
                    "doctype": "Donation",
                    "donor": donor_name,  # Use donor_name variable instead of non-existent member.donor
                    "amount": 50 * (i + 1),
                    "donation_date": add_days(today(), -30 * i),
                    "mode_of_payment": "Cash"}
            )
            donation.insert()
            self.track_doc("Donation", donation.name)
            self.track_doc("Donation", donation.name)

        # Test via API call: signature takes `member` (name). Despite the name,
        # get_linked_donations resolves the linked Donor (by email/name), not the
        # Donation rows themselves: {"success": True, "donor": <donor name>}.
        result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_linked_donations",
            member=member.name,
        )

        # Verify donor link resolved
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("donor"), donor_name)

    def test_get_current_membership_fee_whitelist(self):
        """Test get_current_membership_fee method"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self._get_test_membership_type())
            .build()
        )

        member = test_data["member"]
        membership = test_data["membership"]

        # Submit membership to make it active
        membership.submit()

        # Test via API call
        # MemberFeeCalculationService.get_current_membership_fee returns
        # {"amount": float, "source": str, ...}.
        fee = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_current_membership_fee",
            doc=member.as_dict(),
        )

        # Verify fee shape and source
        self.assertIsInstance(fee, dict)
        self.assertIn("amount", fee)
        self.assertIn("source", fee)
        self.assertIn(fee["source"], {"custom_override", "template", "none"})

    def test_get_display_membership_fee_whitelist(self):
        """Test get_display_membership_fee method with override"""
        test_data = self.builder.with_member(
            dues_rate=75.00, fee_override_reason="Special discount"
        ).build()

        member = test_data["member"]

        # Test via API call
        # MemberFeeCalculationService.get_display_membership_fee returns
        # {"current_amount": float, "display_amount": float, "status": str, ...}.
        display_fee = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_display_membership_fee",
            doc=member.as_dict(),
        )

        # Should reflect the dues_rate override
        self.assertIsInstance(display_fee, dict)
        self.assertEqual(display_fee["current_amount"], 75.00)

    # test_reject_application_whitelist deleted in T4.1 - it exercised the
    # deprecated Member.reject_application whitelisted doctype method,
    # which has been retired in favour of
    # api.membership_application_review.reject_membership_application.

    def test_update_membership_duration_whitelist(self):
        """Test update_membership_duration method"""
        test_data = (
            self.builder.with_member()
            .with_membership(
                membership_type=self._get_test_membership_type(), start_date=add_days(today(), -365)
            )
            .build()
        )

        member = test_data["member"]
        membership = test_data["membership"]

        # Submit membership
        membership.submit()

        # Test via API call
        # MemberDurationService.update_duration returns an OperationResult dict and
        # writes the human-readable duration to member.cumulative_membership_duration
        # (the raw day count is no longer persisted on the Member doctype).
        result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.update_membership_duration",
            doc=member.as_dict(),
        )
        self.assertIsNotNone(result)

        # Verify duration updated
        member.reload()
        self.assertTrue(member.cumulative_membership_duration)

    def test_ensure_member_id_whitelist(self):
        """Test ensure_member_id method"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Clear member_id for testing
        frappe.db.set_value("Member", member.name, "member_id", None)
        member.reload()

        # Test via API call
        # ensure_member_has_id returns an OperationResult; once whitelisted methods
        # cross the HTTP boundary they get serialised via OperationResult.to_dict().
        result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.ensure_member_id", doc=member.as_dict()
        )

        # Verify a member_id was assigned and persisted
        self.assertTrue(result)
        member.reload()
        self.assertTrue(member.member_id)

    def test_get_address_members_html_whitelist(self):
        """Test get_address_members_html method"""
        # Create members at same address
        address_data = {
            "street_name": "Test Street",
            "house_number": "123",
            "postal_code": "1234",
            "city": "Amsterdam"}

        test_data1 = self.builder.with_member(
            first_name="First", last_name="Resident", **address_data
        ).build()

        self.builder.cleanup()
        test_data2 = self.builder.with_member(
            first_name="Second", last_name="Resident", **address_data
        ).build()

        member2 = test_data2["member"]

        # Test via API call
        html = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_address_members_html",
            doc=member2.as_dict(),
        )

        # Verify HTML structure
        self.assertIn("<div", html)
        # Should show "No address selected" if no primary_address is set
        if not member2.primary_address:
            self.assertIn("No address selected", html)

    def test_module_level_functions(self):
        """Test module-level whitelisted functions"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Test is_chapter_management_enabled
        enabled = frappe.call("verenigingen.verenigingen.doctype.member.member.is_chapter_management_enabled")
        self.assertIsInstance(enabled, bool)

        # Test get_member_current_chapters
        chapters = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_member_current_chapters",
            member_name=member.name,
        )
        self.assertIsInstance(chapters, list)

        # Test assign_member_id
        new_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "New",
                "last_name": "Member",
                "email": f"new.{random_string(8)}@test.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer"}
        )
        new_member.insert()
        self.track_doc("Member", new_member.name)
        self.track_doc("Member", new_member.name)

        member_id = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.assign_member_id", member_name=new_member.name
        )
        self.assertTrue(member_id)

    def test_payment_processing_methods(self):
        """Test payment-related whitelisted methods"""
        test_data = self.builder.with_member(
            payment_method="SEPA Direct Debit", iban="NL91ABNA0417164300", bank_account_name="Test Member"
        ).build()

        member = test_data["member"]

        # Test validate_mandate_creation: signature is (member, iban, mandate_id)
        # and the deprecated wrapper returns a dict with at least success/valid keys.
        result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.validate_mandate_creation",
            member=member.name,
            iban=member.iban,
            mandate_id=f"TEST-{random_string(8)}",
        )
        self.assertIsInstance(result, dict)
        self.assertIn("valid", result)

        # Test derive_bic_from_iban: returns {"bic": <code>} dict, not the raw string.
        bic = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban", iban=member.iban
        )
        self.assertEqual(bic, {"bic": "ABNANL2A"})

    def test_fee_management_actions(self):
        """Test fee management JavaScript actions"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self._get_test_membership_type())
            .build()
        )

        member = test_data["member"]
        membership = test_data["membership"]

        # Submit membership
        membership.submit()

        # Test getting current dues schedule details: signature takes `member` (name).
        # Returned dict surfaces schedule metadata (dues_rate / billing_frequency /
        # next_invoice_date / membership_type), not a generic amount/status pair.
        details = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details",
            member=member.name,
        )

        self.assertTrue(details.get("has_schedule"))
        self.assertIn("membership_type", details)
        self.assertIn("dues_rate", details)
        self.assertIn("billing_frequency", details)

    # test_suspension_reactivation_workflow deleted: the "Member Suspension"
    # DocType referenced here never existed in this codebase, so the test
    # exercised no real surface. Suspension is currently driven directly via
    # member.status changes; the reactivation half is covered elsewhere.

    def test_create_donor_from_member_whitelist(self):
        """Test create_donor_from_member function"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Ensure no donor exists (check by email instead of non-existent member.donor field)
        existing_donor = frappe.db.get_value("Donor", {"donor_email": member.email}, "name")
        if existing_donor:
            frappe.delete_doc("Donor", existing_donor)

        # Create donor via API
        result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_donor_from_member",
            member_name=member.name,
        )

        # Verify donor created (the function returns a dict with success and donor_name)
        self.assertTrue(result)
        self.assertTrue(result.get("success"))
        donor_name = result.get("donor_name")
        self.assertTrue(donor_name)
        
        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.member, member.name)
        self.assertEqual(donor.donor_name, member.full_name)
        self.assertEqual(donor.donor_email, member.email)

        # Track for cleanup
        self.track_doc("Donor", donor_name)

    def test_sepa_mandate_management(self):
        """Test SEPA mandate creation and management"""
        test_data = self.builder.with_member(
            payment_method="SEPA Direct Debit", iban="NL91ABNA0417164300", bank_account_name="Test Member"
        ).build()

        member = test_data["member"]

        # Create mandate via API. Signature is now
        # create_and_link_mandate_enhanced(member, mandate_id, iban, ...).
        mandate_id = f"TEST-{random_string(8)}"
        mandate_result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_and_link_mandate_enhanced",
            member=member.name,
            mandate_id=mandate_id,
            iban=member.iban,
            account_holder_name=member.bank_account_name,
        )

        # Verify mandate created. The deprecated wrapper returns a dict with
        # mandate_name (DB primary key) and mandate_id (caller-supplied reference).
        self.assertTrue(mandate_result)
        self.assertTrue(mandate_result.get("success"))
        self.assertIn("mandate_name", mandate_result)
        self.assertEqual(mandate_result["mandate_id"], mandate_id)

        mandate = frappe.get_doc("SEPA Mandate", mandate_result["mandate_name"])
        self.assertEqual(mandate.member, member.name)

    def test_permission_checks(self):
        """Test permission checks on whitelisted methods"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create a non-admin user
        test_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": "test.member.api@example.com",
                "first_name": "Test",
                "last_name": "User",
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}]}
        )
        test_user.insert()
        self.track_doc("User", test_user.name)
        self.track_doc("User", test_user.name)

        # Test as non-admin user
        with self.as_user("test.member.api@example.com"):
            # Should not be able to create customer without permissions
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.verenigingen.doctype.member.member.create_customer",
                    doc=member.as_dict(),
                )

    def test_error_handling(self):
        """Test error handling in whitelisted methods"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Test invalid IBAN: derive_bic_from_iban returns {"bic": None} rather
        # than raising. Pin that graceful-degradation contract.
        result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban",
            iban="INVALID-IBAN",
        )
        self.assertEqual(result, {"bic": None})

        # Test creating user with duplicate email
        member.user = None
        member.save()

        # Create user with same email
        existing_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": member.email,
                "first_name": "Existing",
                "last_name": "User",
                "enabled": 1}
        )
        existing_user.insert()
        self.track_doc("User", existing_user.name)
        self.track_doc("User", existing_user.name)

        # Should handle duplicate email gracefully: the service links the existing
        # user rather than raising. Pin that behaviour so we notice regressions.
        result = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_user", doc=member.as_dict()
        )
        linked_user, action = result
        self.assertEqual(linked_user, existing_user.name)
        self.assertEqual(action, "linked_existing")

    def test_data_integrity(self):
        """Test data integrity in member operations"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Test member_id uniqueness
        member_id = member.member_id

        # Create another member
        new_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Another",
                "last_name": "Member",
                "email": f"another.{random_string(8)}@test.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer"}
        )
        new_member.insert()
        self.track_doc("Member", new_member.name)
        self.track_doc("Member", new_member.name)

        # Ensure different member_id
        self.assertNotEqual(new_member.member_id, member_id)

        # Test customer creation idempotency
        customer1 = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_customer", doc=member.as_dict()
        )

        customer2 = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.create_customer", doc=member.as_dict()
        )

        # Should return same customer
        self.assertEqual(customer1, customer2)
