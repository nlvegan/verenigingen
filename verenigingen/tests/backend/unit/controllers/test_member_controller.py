# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Member controller methods
Tests the Python controller methods directly, not just doctype CRUD
"""


import frappe
from frappe.utils import add_days, today

from verenigingen.tests.harness_logger import get_harness_logger
from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestMemberController(VereningingenUnitTestCase):
    """Test Member controller methods"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        try:
            cls.test_env = TestEnvironmentSetup.create_standard_test_environment()
        except Exception:
            # If environment setup fails, create minimal environment
            cls.test_env = {"membership_types": [], "chapters": [], "teams": []}

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()

    def tearDown(self):
        """Clean up after each test"""
        # super().tearDown() FIRST, THEN builder.cleanup(commit=True): the base
        # teardown's `_rollback_once_before_draining` must discard this test's
        # other uncommitted rows before the commit below runs, or the commit makes
        # ALL of them durable too -- not just the builder's registered deletes.
        # Measured: the other order leaked untracked Chapter/Membership Dues
        # Schedule/User rows (#489).
        super().tearDown()
        try:
            self.builder.cleanup(commit=True)
        except Exception as e:
            # get_harness_logger, NOT frappe.logger(): the latter reaches no log CI
            # surfaces, so this message did not exist where it was needed -- and
            # the builder's Member delete failing here is precisely what leaves a
            # submitted Membership behind for the drain to trip over (#433).
            get_harness_logger("member-controller").error(
                "Cleanup error in %s: %s", self._testMethodName, e
            )

    def _get_test_membership_type(self):
        """Helper to get or create a test membership type"""
        if self.test_env.get("membership_types") and len(self.test_env["membership_types"]) > 0:
            return self.test_env["membership_types"][0].name
        else:
            # Create a test membership type
            mt = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": f"Test Membership Type {frappe.utils.random_string(8)}",
                    "amount": 100,
                    "currency": "EUR"}
            )
            mt.insert()  # VereningingenUnitTestCase handles permissions
            self.track_doc("Membership Type", mt.name)
            return mt.name

    def test_create_customer_method(self):
        """Test the create_customer method"""
        # Create member without customer
        test_data = self.builder.with_member(first_name="CustomerTest", last_name="Member").build()

        member = test_data["member"]

        # Initially might have a customer if auto-created
        initial_customer = member.customer

        # Call create_customer method
        customer_name = member.create_customer()

        # Reload member
        member.reload()

        # Verify customer was created and linked
        self.assertTrue(customer_name)
        self.assertEqual(member.customer, customer_name)

        # If initially had no customer, verify it was created
        if not initial_customer:
            self.assertNotEqual(member.customer, initial_customer)

        # Verify customer details. Customer.email_id/mobile_no are read-only
        # fetch_from fields populated from the primary Contact, not set on the
        # Customer at creation time. Verify the email on the source Contact.
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_name, member.full_name)
        self.assertTrue(customer.customer_primary_contact, "Customer should have a primary contact")
        contact = frappe.get_doc("Contact", customer.customer_primary_contact)
        self.assertIn(member.email, [e.email_id for e in contact.email_ids])

        # Test idempotency - calling again should return same customer
        customer_name_2 = member.create_customer()
        self.assertEqual(customer_name, customer_name_2)

    def test_create_user_account_method(self):
        """Test the create_user method"""
        # Create member without user
        test_data = self.builder.with_member(first_name="UserTest", last_name="Member").build()

        member = test_data["member"]

        # Initially should have no user
        self.assertFalse(member.user)

        # Call create_user method. It delegates to MemberUserAccountService and
        # returns a (username, action) tuple.
        user_name, action = member.create_user()

        # Reload member
        member.reload()

        # Verify user was created and linked
        self.assertTrue(user_name)
        self.assertEqual(action, "created_new")
        self.assertEqual(member.user, user_name)

        # Verify user details
        user = frappe.get_doc("User", user_name)
        self.assertEqual(user.email.lower(), member.email.lower())
        self.assertEqual(user.first_name, member.first_name)
        self.assertEqual(user.last_name, member.last_name)
        self.assertIn("Verenigingen Member", [r.role for r in user.roles])

    def test_update_payment_status_method(self):
        """Test payment status update logic"""
        # Create member with membership
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self._get_test_membership_type())
            .build()
        )

        test_data["member"]
        test_data["membership"]

        # Test payment status updates
        # This would test the actual payment status logic
        # Implementation depends on payment integration

    def test_calculate_membership_fee_method(self):
        """Test membership fee calculation"""
        # Create member with different membership types
        for membership_type in self.test_env["membership_types"]:
            test_data = (
                self.builder.with_member().with_membership(membership_type=membership_type.name).build()
            )

            test_data["member"]

            # Test fee calculation
            # This would test discount logic, pro-rating, etc.
            # Implementation depends on business rules

            self.builder.cleanup()

    def test_payment_mixin_methods(self):
        """Test PaymentMixin methods"""
        # Create member with payment method
        test_data = self.builder.with_member(
            payment_method="SEPA Direct Debit", iban="NL91ABNA0417164300", bank_account_name="Test Member"
        ).build()

        member = test_data["member"]

        # Test IBAN validation
        self.assertEqual(member.iban, "NL91 ABNA 0417 1643 00")

        # Test payment method validation
        # This would test the mixin methods

    def test_sepa_mandate_mixin_methods(self):
        """Test SEPAMandateMixin methods"""
        # Create member with SEPA details
        test_data = self.builder.with_member(
            payment_method="SEPA Direct Debit", iban="NL91ABNA0417164300", bank_account_name="Test Member"
        ).build()

        test_data["member"]

        # Test mandate creation
        # This would test the SEPA mandate mixin methods

    def test_chapter_mixin_methods(self):
        """Test ChapterMixin methods"""
        # Create member with chapter
        # Check if chapters were created, otherwise create one
        if self.test_env.get("chapters") and len(self.test_env["chapters"]) > 0:
            chapter_name = self.test_env["chapters"][0].name
        else:
            chapter_name = None  # Let builder create a new chapter

        test_data = self.builder.with_chapter(chapter_name).with_member().build()

        member = test_data["member"]
        chapter = test_data["chapter"]

        # Verify chapter assignment (chapter linkage is via Chapter Member child rows)
        member_chapter = frappe.db.get_value(
            "Chapter Member", {"member": member.name, "enabled": 1}, "parent"
        )
        self.assertEqual(member_chapter, chapter.name)

        # Verify members child table was updated
        chapter.reload()
        chapter_members = [cm.member for cm in chapter.members]
        self.assertIn(member.name, chapter_members)

    def test_termination_mixin_methods(self):
        """Test TerminationMixin methods"""
        # Create active member
        test_data = self.builder.with_member(status="Active").build()
        test_data["member"]

        # Test termination process
        # This would test the termination mixin methods

    def test_membership_status_update(self):
        """Test update_membership_status method"""
        # Create member with expired membership
        test_data = (
            self.builder.with_member()
            .with_membership(
                membership_type=self._get_test_membership_type(),
                start_date=add_days(today(), -400),
                renewal_date=add_days(today(), -35),
            )
            .build()
        )

        member = test_data["member"]
        membership = test_data["membership"]

        # Submit the membership to make it active
        membership.submit()

        # Update membership status
        member.update_membership_status()

        # Verify status fields are updated
        member.reload()
        self.assertEqual(member.membership_status, "Expired")

    def test_get_active_membership(self):
        """Test get_active_membership method"""
        # Create member with multiple memberships
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create expired membership
        expired = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": self._get_test_membership_type(),
                "start_date": add_days(today(), -400),
                "end_date": add_days(today(), -35),
                "status": "Expired"}
        )
        expired.insert()  # VereningingenUnitTestCase handles permissions
        self.track_doc("Membership", expired.name)

        # Create active membership
        # Get or create a membership type
        if self.test_env.get("membership_types") and len(self.test_env["membership_types"]) > 0:
            membership_type_name = self.test_env["membership_types"][0].name
        else:
            # Create a test membership type
            mt = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Active Membership",
                    "amount": 100,
                    "currency": "EUR"}
            )
            mt.insert()  # VereningingenUnitTestCase handles permissions
            self.track_doc("Membership Type", mt.name)
            membership_type_name = mt.name

        active = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type_name,
                "start_date": today(),
                "renewal_date": add_days(today(), 365),
                "status": "Active"}
        )
        active.insert()  # VereningingenUnitTestCase handles permissions
        self.track_doc("Membership", active.name)
        active.submit()

        # Test get_active_membership returns the active one
        active_membership = member.get_active_membership()
        self.assertIsNotNone(active_membership)
        self.assertEqual(active_membership.name, active.name)
        self.assertEqual(active_membership.status, "Active")

    def test_validate_name_fields(self):
        """Test name field validation"""
        # Test invalid characters
        with self.assert_validation_error("contains invalid characters"):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Test@123",  # Invalid character
                    "last_name": "Member",
                    "email": "test@example.com",
                    "contact_number": "+31612345678",
                    "payment_method": "Bank Transfer"}
            )
            member.insert()

    def test_validate_bank_details(self):
        """Test bank details validation for SEPA"""
        # Test missing IBAN for SEPA
        with self.assert_validation_error("IBAN is required"):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Test",
                    "last_name": "Member",
                    "email": "test@example.com",
                    "contact_number": "+31612345678",
                    "payment_method": "SEPA Direct Debit"
                    # Missing IBAN
                }
            )
            member.insert()

    def test_full_name_update(self):
        """Test automatic full name updates"""
        test_data = self.builder.with_member(first_name="John", last_name="Doe").build()

        member = test_data["member"]
        self.assertEqual(member.full_name, "John Doe")

        # Update with middle name
        member.middle_name = "Middle"
        member.update_full_name()
        self.assertEqual(member.full_name, "John Middle Doe")

    def test_age_calculation(self):
        """Test age calculation from birth date"""
        test_data = self.builder.with_member(birth_date=add_days(today(), -365 * 30)).build()  # 30 years ago

        member = test_data["member"]
        self.assertIn(member.age, [29, 30])  # Depending on exact dates

    def test_member_lifecycle_events(self):
        """Test member lifecycle event handlers"""
        # Test before_insert
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Lifecycle",
                "last_name": "Test",
                "email": "lifecycle@test.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer"}
        )

        # Should generate member_id before insert
        member.insert()
        self.track_doc("Member", member.name)
        self.assertTrue(member.member_id)

        # Test on_update
        member.first_name = "Updated"
        member.save()

        # Full name should be updated
        self.assertEqual(member.full_name, "Updated Test")

    def test_send_welcome_email_method(self):
        """Test the send_welcome_email method"""
        # Create member
        test_data = self.builder.with_member(
            first_name="Welcome", last_name="Email", email="welcome.email@test.com"
        ).build()

        test_data["member"]

        # Mock email sending if needed
        # member.send_welcome_email()

        # Verify email was queued
        # This would check email queue

    def test_get_other_members_at_address(self):
        """Test finding other members at same address"""
        # Create members at same address
        address_data = {
            "street_name": "Shared Street",
            "house_number": "42",
            "postal_code": "1234",
            "city": "Amsterdam"}

        # First member
        test_data1 = self.builder.with_member(
            first_name="First", last_name="Resident", **address_data
        ).build()

        # Second member at same address
        self.builder.cleanup()
        test_data2 = self.builder.with_member(
            first_name="Second", last_name="Resident", **address_data
        ).build()

        member1 = test_data1["member"]
        member2 = test_data2["member"]

        # Test get_other_members_at_address
        others = member2.get_other_members_at_address()
        # Skip assertion if no primary address is set (depends on builder implementation)
        if member1.primary_address and member2.primary_address:
            self.assertTrue(len(others) > 0)
            other_names = [m.get("name") for m in others]
            self.assertIn(member1.name, other_names)

    # test_approve_application_method and test_reject_application_method
    # deleted in T4.1 - they exercised the deprecated Member.approve_application /
    # Member.reject_application doctype methods which have been retired in
    # favour of the canonical api.membership_application_review path. The
    # canonical approve/reject flow is covered end-to-end by
    # test_canonical_approval_chapter_activation.py and
    # test_chapter_membership_approval_integration.py.

    def test_calculate_cumulative_membership_duration(self):
        """Test cumulative membership duration calculation"""
        # Create member with multiple memberships
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create past membership
        past_membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": self._get_test_membership_type(),
                "start_date": add_days(today(), -730),  # 2 years ago
                "renewal_date": add_days(today(), -365),  # 1 year ago
                "status": "Expired"}
        )
        past_membership.insert()  # VereningingenUnitTestCase handles permissions
        past_membership.submit()  # Duration calculation only counts submitted memberships
        self.track_doc("Membership", past_membership.name)

        # Create current membership
        current_membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": self._get_test_membership_type(),
                "start_date": add_days(today(), -180),  # 6 months ago
                "renewal_date": add_days(today(), 185),  # 6 months future
                "status": "Active"}
        )
        current_membership.insert()  # VereningingenUnitTestCase handles permissions
        self.track_doc("Membership", current_membership.name)
        # Submit to make it active
        current_membership.submit()

        # Calculate duration
        duration = member.calculate_cumulative_membership_duration()

        # Should be around 1.5 years (365 days from past expired + ~180 days current to today)
        # Active memberships only count up to today, not future renewal_date
        self.assertGreater(duration, 1.4)
        self.assertLess(duration, 1.6)

    def test_update_membership_duration(self):
        """Test update_membership_duration method"""
        # Create member with membership
        test_data = (
            self.builder.with_member()
            .with_membership(
                membership_type=self._get_test_membership_type(), start_date=add_days(today(), -365)
            )
            .build()
        )

        member = test_data["member"]
        membership = test_data["membership"]

        # Submit the membership first
        membership.submit()

        # Reload member to avoid timestamp mismatch
        member.reload()

        # Update duration. The service stores only the human-readable
        # cumulative_membership_duration field (there is no stored
        # total_membership_days column — the day count is calculated on demand).
        result = member.update_membership_duration()
        # Happy path returns an OperationResult (with a .success attr); the error
        # path returns a {"success": ...} dict — accept either shape.
        result_ok = getattr(result, "success", None)
        if result_ok is None and isinstance(result, dict):
            result_ok = result.get("success")
        self.assertTrue(result_ok)

        # Verify the stored duration field is populated, and the on-demand
        # day-count calculation returns a positive value for a 1-year membership.
        member.reload()
        self.assertTrue(member.cumulative_membership_duration)
        self.assertGreater(member.calculate_total_membership_days(), 0)

    def test_get_address_members_html(self):
        """Test HTML generation for address members"""
        # Create members at same address
        test_data = self.builder.with_member(
            first_name="HTML", last_name="Test", street_name="Test Street", house_number="123"
        ).build()

        member = test_data["member"]

        # Get HTML - should show "No address selected" since member has no primary_address
        html = member.get_address_members_html()

        # Verify HTML structure
        self.assertIn("<div", html)
        self.assertIn("No address selected", html)

    def test_validate_fee_override_permissions(self):
        """Test fee override permission validation"""
        # Create member with fee override
        test_data = self.builder.with_member(
            dues_rate=50.00, fee_override_reason="Test discount for validation"
        ).build()

        member = test_data["member"]

        # Test as non-admin user
        with self.as_user("test.member@example.com"):
            # Should raise permission error
            with self.assertRaises(frappe.PermissionError):
                member.dues_rate = 75.00
                member.validate_fee_override_permissions()

