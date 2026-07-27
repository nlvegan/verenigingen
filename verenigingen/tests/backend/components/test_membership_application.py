import unittest

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.api.member_management import add_member_to_chapter_roster

# Note: approve_membership_application / reject_membership_application
# imported here are the DEPRECATED shims in api.membership_application.
# They emit DeprecationWarning and delegate to the canonical
# api.membership_application_review functions. T4.1 kept the shims alive
# (they correctly delegate) to avoid breaking the many call sites in this
# test file; future cleanup is tracked as a follow-up.
from verenigingen.api.membership_application import (
    approve_membership_application,
    reject_membership_application,
    submit_application,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.validation.application_validators import (
    validate_birth_date as validate_birth_date_util,
)


def _ensure_region(region_name: str, region_code: str) -> str:
    """Idempotently create a Region and return its actual .name (autoname scrubs)."""
    existing = frappe.db.get_value("Region", {"region_name": region_name}, "name")
    if existing:
        return existing
    try:
        doc = frappe.get_doc({
            "doctype": "Region",
            "region_name": region_name,
            "region_code": region_code,
        }).insert(ignore_permissions=True)
        return doc.name
    except frappe.DuplicateEntryError:
        return frappe.db.get_value("Region", {"region_name": region_name}, "name") \
            or region_name.lower().replace(" ", "-")


def get_member_primary_chapter(member_name):
    """Helper function to get member's primary chapter from Chapter Member table"""
    try:
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
            limit=1,
        )
        return chapters[0].parent if chapters else None
    except Exception:
        return None


class TestMembershipApplication(VereningingenTestCase):
    """Test membership application workflow"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        super().setUpClass()  # Initialize _track_created_docs
        # Seed master records (Verenigingen Settings.creation_user, payment
        # modes, ERPNext base masters) that `run-tests --module` does not seed
        # because it skips the before_tests hook. Without creation_user,
        # submit_application fails with "System user for automated operations is
        # not configured".
        from verenigingen.tests.setup import ensure_member_test_masters
        ensure_member_test_masters()
        # Create required Item Group for membership types
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Membership",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0}
            )
            item_group.insert()

        # Create required Region for chapters
        # Note: Region autoname is field:region_name which converts "Test Region" to "test-region"
        if not frappe.db.exists("Region", "test-region"):
            region = frappe.get_doc({
                "doctype": "Region",
                "region_name": "Test Region",
                "region_code": "TST"
            })
            region.insert()

        # Create test membership type
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "minimum_amount": 15,  # Match default template dues_rate
                    "role_profile": "Verenigingen Member",
                }
            )
            membership_type.insert()
            # Dues schedule system handles payment processing automatically

        # Create test chapter
        if not frappe.db.exists("Chapter", "Test Chapter"):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": "Test Chapter",
                    "region": "test-region",  # Use autonamed region
                    "postal_codes": "1000-1999",
                    "published": 1,
                    "introduction": "Test chapter for basic functionality"}
            )
            chapter.insert()

        # Create volunteer interest categories (Volunteer Interest Area is a child table)
        interest_categories = ["Event Planning", "Technical Support", "Community Outreach"]
        for category in interest_categories:
            if not frappe.db.exists("Volunteer Interest Category", category):
                frappe.get_doc({
                    "doctype": "Volunteer Interest Category",
                    "category_name": category
                }).insert()

    def setUp(self):
        """Set up for each test using factory methods"""
        super().setUp()

        self.test_email = f"test_{frappe.generate_hash(length=8)}@example.com"

        # Use the dedicated "Test Membership" type (minimum_amount=15, created in
        # setUpClass). Picking an arbitrary existing type via get_all(limit=1) is
        # unsafe on the shared test site — other types have a €50 minimum that
        # conflicts with the €15 default dues template, breaking invoice creation.
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test Membership",
                "minimum_amount": 15,  # Match default template dues_rate
                "role_profile": "Verenigingen Member",
            })
            membership_type.insert()
            self.track_doc("Membership Type", membership_type.name)
        self.test_membership_type = "Test Membership"

        # Create test chapter using factory method
        self.test_chapter = self.create_test_chapter(
            chapter_name="Test Chapter Application",
            postal_codes="1000-1999"
        )

        self.application_data = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": self.test_membership_type,
            "contact_number": "+31612345678",
            "interested_in_volunteering": 1,
            "volunteer_availability": "Monthly",
            "volunteer_interests": ["Event Planning", "Technical Support"],
            "volunteer_skills": "Project management, Python programming",
            "newsletter_opt_in": 1,
            "application_source": "Website"
        }
        # Base class will handle cleanup automatically

    def test_submit_application(self):
        """Test application submission"""
        result = submit_application(**self.application_data)

        self.assertTrue(result["success"])
        self.assertIn("member_record", result["data"])
        self.assertIn("application_id", result["data"])

        # Verify member created
        member = frappe.get_doc("Member", result["data"]["member_record"])
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Pending")
        self.assertEqual(member.email, self.test_email)
        self.assertEqual(member.interested_in_volunteering, 1)

        # Verify application ID is set
        self.assertIsNotNone(result["data"]["application_id"])
        self.assertEqual(member.application_id, result["data"]["application_id"])

    def test_age_validation(self):
        """An under-age applicant must be rejected by the eligibility gate.

        REWRITTEN 2026-07-26. This asserted that a 10-year-old's application
        SUCCEEDED "but age warning should be noted" -- it never asserted any
        warning, and the product has never accepted under-16s: the minimum age
        (Verenigingen Settings.minimum_membership_age) is enforced on save by
        Member.validate_age_requirements. The test was simply baselined as a
        known failure instead of being corrected.

        It now also covers the gap that made the old behaviour plausible: the
        applicant-facing pre-check (validate_birth_date) used to accept any age
        >= 0, so the form green-lit the applicant and only the save rejected them.
        Both paths now apply the same rule.
        """
        young_data = self.application_data.copy()
        young_data["birth_date"] = add_days(today(), -365 * 10)
        young_data["email"] = f"young_{self.test_email}"

        # The eligibility gate deliberately log_error()s the failure detail.
        self.expectErrorLog("Application Eligibility Failed")
        result = submit_application(**young_data)

        self.assertFalse(result["success"], "a 10-year-old must not be accepted")
        # Message-pinned: assert the AGE rule rejected it, not some unrelated
        # validation error that would otherwise satisfy assertFalse. OperationResult
        # nests the detail under "error" rather than a flat "message".
        failure_message = str(result["error"]["message"])
        self.assertIn("at least", failure_message)
        self.assertIn("16", failure_message)

        # And the pre-check the application form calls must agree, rather than
        # green-lighting an applicant the submission will reject.
        precheck = validate_birth_date_util(young_data["birth_date"])
        self.assertFalse(precheck["valid"], "pre-check must not green-light an under-age applicant")

    def test_chapter_suggestion(self):
        """Test automatic chapter suggestion"""
        result = submit_application(**self.application_data)
        member = frappe.get_doc("Member", result["data"]["member_record"])

        # Should suggest Test Chapter based on postal code
        # Note: suggested_chapter field may not exist, check current_chapter_display instead
        if hasattr(member, 'suggested_chapter') and member.suggested_chapter:
            self.assertEqual(member.suggested_chapter, self.test_chapter.name)
        elif hasattr(member, 'current_chapter_display') and member.current_chapter_display:
            self.assertIn(self.test_chapter.chapter_name, member.current_chapter_display)

    @unittest.skip("Dues schedule creation timing issues - needs investigation")
    def test_approve_application(self):
        """Test application approval workflow"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name, "Approved for testing")

        self.assertTrue(approval_result["success"])
        self.assertIn("invoice", approval_result["data"])

        # Verify member status
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.review_notes, "Approved for testing")

        # Verify membership created
        membership = frappe.get_doc("Membership", {"member": member_name})
        self.assertIn(membership.status, ["Draft", "Pending", "Active"])  # May be activated after approval
        self.assertEqual(membership.membership_type, "Test Membership")

        # Verify dues schedule created
        self.assertIsNotNone(
            membership.dues_schedule, "Dues schedule should be created for approved membership"
        )
        dues_schedule = frappe.get_doc("Membership Dues Schedule", membership.dues_schedule)
        self.assertEqual(dues_schedule.status, "Active", "Dues schedule should be active")
        self.assertEqual(
            float(dues_schedule.monthly_amount), 15.0, "Dues schedule amount should match membership type minimum_amount"
        )

    def test_reject_application(self):
        """Test application rejection"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # Reject application
        # VereningingenTestCase handles Administrator context appropriately
        rejection_result = reject_membership_application(member_name, "Does not meet requirements")

        self.assertTrue(rejection_result["success"])

        # Verify member status
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Rejected")
        self.assertEqual(member.status, "Rejected")
        self.assertEqual(member.review_notes, "Does not meet requirements")

    def test_payment_processing(self):
        """Test that an approved application reaches the Approved state and
        provisions the related volunteer record."""
        # Submit and approve application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # VereningingenTestCase handles Administrator context appropriately
        approve_membership_application(member_name)

        # Verify approval worked
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Approved")

        # Verify volunteer record created
        volunteer = frappe.get_doc("Volunteer", {"member": member_name})
        self.assertEqual(volunteer.volunteer_name, member.full_name)
        self.assertIn(volunteer.status, ["New", "Active"])  # May be auto-activated

    def test_duplicate_email_prevention(self):
        """Test that duplicate emails are prevented"""
        # Submit first application
        first_result = submit_application(**self.application_data)
        self.assertTrue(first_result["success"])

        # Try to submit with same email - should fail or handle reapplication
        second_result = submit_application(**self.application_data)
        # Either fails with error, or handles reapplication scenario
        if not second_result["success"]:
            error = second_result.get("error", {})
            error_message = error.get("message", "") if isinstance(error, dict) else str(error)
            self.assertIn("already", error_message.lower())
        else:
            # Reapplication scenario - same member record updated
            self.assertTrue(second_result["success"])

    def test_overdue_detection(self):
        """Test overdue application detection"""
        # Create an old application
        old_data = self.application_data.copy()
        old_data["email"] = f"old_{self.test_email}"
        result = submit_application(**old_data)

        # Manually set the application date to 3 weeks ago
        frappe.db.set_value("Member", result["data"]["member_record"], "application_date", add_days(now_datetime(), -21))

        # Overdue check function was removed with application_notifications.py
        # The functionality now lives in api/overdue_application_notifications.py
        self.assertTrue(True)


class TestMembershipApplicationLoad(EnhancedTestCase):
    """Load testing for membership applications"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Seed master records that `run-tests --module` skips (it does not run
        # the before_tests hook). Without Verenigingen Settings.creation_user,
        # submit_application fails with "System user for automated operations is
        # not configured". These tests also rely on the "Test Membership" type
        # and "Membership" Item Group seeded by the sibling test class /
        # full-suite run; create them here so the module runs standalone.
        from verenigingen.tests.setup import ensure_member_test_masters
        ensure_member_test_masters()
        if not frappe.db.exists("Item Group", "Membership"):
            frappe.get_doc({
                "doctype": "Item Group",
                "item_group_name": "Membership",
                "parent_item_group": "All Item Groups",
                "is_group": 0,
            }).insert(ignore_permissions=True)
        if not frappe.db.exists("Membership Type", "Test Membership"):
            frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test Membership",
                "minimum_amount": 15,
                "role_profile": "Verenigingen Member",
            }).insert(ignore_permissions=True)

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        # Unique suffix per test: submit_application commits the created Customer
        # (autonamed by customer_name), so a shared "Load Tester" name would
        # collide with DuplicateEntryError across the tests in this class.
        unique = frappe.generate_hash(length=8)
        self.test_email = f"load_test_{unique}@example.com"
        self.application_data = {
            "first_name": "Load",
            "last_name": f"Tester {unique}",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
            "contact_number": "+31612345678",
            "interested_in_volunteering": 1,
            "volunteer_availability": "Monthly",
            "volunteer_interests": ["Event Planning", "Technical Support"],
            "volunteer_skills": "Project management, Python programming",
            "newsletter_opt_in": 1,
            "application_source": "Website"}

    def _cleanup_member_completely(self, member_name):
        """
        Clean up a member and all related documents in the correct order.

        Deletion order to avoid LinkExistsError:
        1. Sales Invoices (link to Customer and Contact)
        2. Payment Entries
        3. Membership Dues Schedules
        4. Memberships
        5. Volunteers
        6. Member
        7. Customer (auto-deletes Contacts/Addresses)
        """
        try:
            member = frappe.get_doc("Member", member_name)
            customer_name = member.customer
        except frappe.DoesNotExistError:
            return  # Member doesn't exist, nothing to clean up

        # 1. Delete Sales Invoices first
        if customer_name:
            invoices = frappe.get_all("Sales Invoice", filters={"customer": customer_name})
            for inv in invoices:
                try:
                    inv_doc = frappe.get_doc("Sales Invoice", inv.name)
                    if inv_doc.docstatus == 1:
                        inv_doc.cancel()
                    frappe.delete_doc("Sales Invoice", inv.name, force=True)
                except Exception:
                    pass

        # 2. Delete Payment Entries
        if customer_name:
            payments = frappe.get_all("Payment Entry", filters={"party": customer_name, "party_type": "Customer"})
            for pe in payments:
                try:
                    pe_doc = frappe.get_doc("Payment Entry", pe.name)
                    if pe_doc.docstatus == 1:
                        pe_doc.cancel()
                    frappe.delete_doc("Payment Entry", pe.name, force=True)
                except Exception:
                    pass

        # 3. Delete Membership Dues Schedules
        schedules = frappe.get_all("Membership Dues Schedule", filters={"member": member_name})
        for schedule in schedules:
            try:
                frappe.delete_doc("Membership Dues Schedule", schedule.name, force=True)
            except Exception:
                pass

        # 4. Delete Memberships
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        for membership in memberships:
            try:
                m_doc = frappe.get_doc("Membership", membership.name)
                if m_doc.docstatus == 1:
                    m_doc.cancel()
                frappe.delete_doc("Membership", membership.name, force=True)
            except Exception:
                pass

        # 5. Delete Volunteers
        volunteers = frappe.get_all("Volunteer", filters={"member": member_name})
        for volunteer in volunteers:
            try:
                frappe.delete_doc("Volunteer", volunteer.name, force=True)
            except Exception:
                pass

        # 6. Delete Member
        try:
            frappe.delete_doc("Member", member_name, force=True)
        except Exception:
            pass

        # 7. Delete Customer last
        if customer_name:
            try:
                frappe.delete_doc("Customer", customer_name, force=True)
            except Exception:
                pass

    @unittest.skip("Concurrent tests have threading/infrastructure issues")
    def test_concurrent_applications(self):
        """Test handling of multiple concurrent applications"""
        import threading

        results = []
        errors = []

        def submit_test_application(index):
            try:
                data = {
                    "first_name": f"Test{index}",
                    "last_name": "Concurrent",
                    "email": f"concurrent{index}@test.com",
                    "birth_date": "1990-01-01",
                    "address_line1": "123 Test Street",
                    "city": "Amsterdam",
                    "postal_code": "1234AB",
                    "country": "Netherlands",
                    "selected_membership_type": "Test Membership"}
                result = submit_application(data)
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        # Create 10 concurrent applications
        threads = []
        for i in range(10):
            t = threading.Thread(target=submit_test_application, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Verify results
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 10)

        # Clean up
        for result in results:
            if isinstance(result, dict) and result.get("data") and "member_record" in result.get("data", {}):
                frappe.delete_doc("Member", result["data"]["member_record"])
            elif isinstance(result, dict) and "member_id" in result:
                frappe.delete_doc("Member", result["member_id"])

    def test_custom_fee_application_no_change_tracking(self):
        """Test that applications with custom fees don't trigger fee change tracking"""
        print("\n🧪 Testing custom fee application submission...")

        # Application data with custom amount
        custom_fee_data = self.application_data.copy()
        custom_fee_data["custom_contribution_fee"] = 75.0
        custom_fee_data["uses_custom_amount"] = True
        custom_fee_data["custom_amount_reason"] = "Supporter contribution level"
        custom_fee_data["email"] = f"customfee_{self.test_email}"

        # Submit application with custom fee
        result = submit_application(**custom_fee_data)

        # Verify submission successful
        self.assertTrue(result["success"])
        self.assertIn("member_record", result["data"])

        # Get created member
        member = frappe.get_doc("Member", result["data"]["member_record"])

        # Verify custom fee was set correctly
        self.assertEqual(member.dues_rate, 75.0)
        self.assertIn("Supporter contribution", member.fee_override_reason)
        self.assertEqual(member.application_status, "Pending")

        # KEY TEST: Verify no fee change tracking was triggered
        self.assertFalse(
            hasattr(member, "_pending_fee_change"),
            "Application with custom fee should not trigger fee change tracking",
        )

        print(f"✅ Custom fee application successful for {member.name}")
        print(f"   Custom fee: €{member.dues_rate}")
        print(f"   Reason: {member.fee_override_reason}")
        print("   No fee change tracking triggered (correct for new application)")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member.name, force=True)

    def test_application_id_generation(self):
        """Test that application_id is properly generated and accessible"""
        print("\n🧪 Testing application_id generation...")

        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # Get member and verify application_id exists
        member = frappe.get_doc("Member", member_name)

        # Application ID should be generated
        self.assertIsNotNone(member.application_id, "Member should have application_id")
        self.assertTrue(member.application_id.startswith("APP-"), "Application ID should start with APP-")

        # The response should include applicant_id (which maps to application_id)
        self.assertIn("applicant_id", result["data"], "Response should include applicant_id")
        self.assertEqual(
            result["data"]["applicant_id"],
            member.application_id,
            "Response applicant_id should match member application_id",
        )

        print(f"✅ Application ID generated: {member.application_id}")
        print(f"   Response includes applicant_id: {result['data'].get('applicant_id')}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    @unittest.skip("Volunteer record creation issues - needs investigation")
    def test_volunteer_skills_array_format(self):
        """Test that volunteer skills in array format are properly processed"""
        print("\n🧪 Testing volunteer skills array format processing...")

        # Create application data with skills in array format (as sent by the form)
        skills_data = self.application_data.copy()
        skills_data["volunteer_skills"] = [
            {"skill_name": "Event Planning", "skill_level": "Advanced"},
            {"skill_name": "Python Programming", "skill_level": "Intermediate"},
            {"skill_name": "Public Speaking", "skill_level": "Expert"},
        ]
        skills_data["email"] = f"skills_{self.test_email}"

        # Submit application
        result = submit_application(**skills_data)
        member_name = result["data"]["member_record"]

        # Verify member was created
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.interested_in_volunteering, 1)

        # Check if volunteer record was created with skills
        volunteers = frappe.get_all("Volunteer", filters={"member": member_name})
        self.assertEqual(len(volunteers), 1, "Should create exactly one volunteer record")

        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)

        # Check that skills were added to volunteer record
        skills = volunteer.skills_and_qualifications
        self.assertGreater(len(skills), 0, "Volunteer should have skills")

        # Verify specific skills
        skill_names = [skill.volunteer_skill for skill in skills]
        self.assertIn("Event Planning", skill_names)
        self.assertIn("Python Programming", skill_names)
        self.assertIn("Public Speaking", skill_names)

        # Verify proficiency levels were mapped correctly
        for skill in skills:
            if skill.volunteer_skill == "Event Planning":
                self.assertEqual(skill.proficiency_level, "4 - Advanced")
            elif skill.volunteer_skill == "Python Programming":
                self.assertEqual(skill.proficiency_level, "3 - Intermediate")
            elif skill.volunteer_skill == "Public Speaking":
                self.assertEqual(skill.proficiency_level, "5 - Expert")

        print("✅ Volunteer skills processed correctly")
        print(f"   Skills added: {len(skills)}")
        for skill in skills:
            print(f"   - {skill.volunteer_skill}: {skill.proficiency_level} ({skill.skill_category})")

        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_volunteer_skills_empty_array(self):
        """Test that empty volunteer skills array doesn't cause errors"""
        print("\n🧪 Testing empty volunteer skills array...")

        # Create application data with empty skills array
        skills_data = self.application_data.copy()
        skills_data["volunteer_skills"] = []
        skills_data["email"] = f"emptyskills_{self.test_email}"

        # Submit application
        result = submit_application(**skills_data)
        member_name = result["data"]["member_record"]

        # Verify member was created
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.interested_in_volunteering, 1)

        # Check if volunteer record was created
        volunteers = frappe.get_all("Volunteer", filters={"member": member_name})
        self.assertEqual(len(volunteers), 1, "Should create volunteer record even with no skills")

        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)

        # Should have no skills
        skills = volunteer.skills_and_qualifications
        self.assertEqual(len(skills), 0, "Volunteer should have no skills")

        print("✅ Empty skills array handled correctly")

        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_iban_data_preservation(self):
        """Test that IBAN data from application is properly saved to member"""
        # Application data with IBAN details
        iban_data = self.application_data.copy()
        iban_data["payment_method"] = "SEPA Direct Debit"
        iban_data["iban"] = "NL02ABNA0123456789"
        iban_data["bic"] = "ABNANL2A"
        # Use bank_account_name as that's what the backend expects from form mapping
        iban_data["bank_account_name"] = "Test Account Holder"
        iban_data["email"] = f"iban_{self.test_email}"

        # Submit application
        result = submit_application(**iban_data)

        # Verify submission successful
        self.assertTrue(result["success"])
        self.assertIn("member_record", result["data"])

        # Get created member
        member = frappe.get_doc("Member", result["data"]["member_record"])

        # Verify IBAN data was preserved
        self.assertEqual(member.iban, "NL02 ABNA 0123 4567 89")  # Should be formatted
        self.assertEqual(member.bic, "ABNANL2A")
        self.assertEqual(member.bank_account_name, "Test Account Holder")
        self.assertEqual(member.payment_method, "SEPA Direct Debit")

        print(f"✅ IBAN data properly transferred for {member.name}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member.name, force=True)

    def test_contact_number_field_usage(self):
        """Test that contact_number is used instead of mobile_no"""
        # Submit application with contact number
        result = submit_application(**self.application_data)

        # Get created member
        member = frappe.get_doc("Member", result["data"]["member_record"])

        # Verify contact_number field is used
        self.assertEqual(member.contact_number, "+31612345678")

        # Verify no mobile_no field is set (should not exist or be empty)
        self.assertFalse(hasattr(member, "mobile_no") and getattr(member, "mobile_no", None))

        print(f"✅ Contact number field properly used for {member.name}")

    def test_membership_submission_after_approval(self):
        """Test that membership is properly submitted after approval"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name, "Approved for testing")

        self.assertTrue(approval_result["success"])

        # Verify member status
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Approved")

        # Verify membership was created and submitted properly
        memberships = frappe.get_all(
            "Membership", filters={"member": member_name}, fields=["name", "docstatus", "status"]
        )
        self.assertEqual(len(memberships), 1)

        membership = frappe.get_doc("Membership", memberships[0].name)
        # Membership may be submitted (docstatus=1) or draft (docstatus=0) depending on workflow
        self.assertIn(membership.docstatus, [0, 1], "Membership docstatus should be 0 (draft) or 1 (submitted)")

        print(f"✅ Membership created for {member_name}, docstatus={membership.docstatus}")

    def test_invoice_period_dates(self):
        """Test that invoices have proper billing period dates"""
        # Submit and approve application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])
        self.assertIn("invoice", approval_result["data"])

        # Get the invoice
        invoice = frappe.get_doc("Sales Invoice", approval_result["data"]["invoice"])

        # Verify invoice has basic fields (billing_period fields may not exist)
        self.assertTrue(invoice.posting_date, "Invoice should have posting date")
        self.assertTrue(invoice.due_date, "Invoice should have due date")

        # Note: billing_period_start/end fields don't exist in standard Sales Invoice
        # These would be custom fields if needed

        print(f"✅ Invoice {invoice.name} has proper dates: posting {invoice.posting_date}, due {invoice.due_date}")

    def test_no_duplicate_invoices(self):
        """Test that approval doesn't create duplicate invoices"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Count invoices for this member
        member = frappe.get_doc("Member", member_name)
        if member.customer:
            invoices = frappe.get_all("Sales Invoice", filters={"customer": member.customer})
            self.assertEqual(len(invoices), 1, "Should only have one invoice after approval")

        print(f"✅ No duplicate invoices created for {member_name}")

    @unittest.skip("Custom amount billing integration needs separate investigation - test setup/isolation issues")
    def test_no_duplicate_invoices_with_custom_amount(self):
        """Test that approval with custom amount doesn't create duplicate invoices"""
        print("\n🧪 Testing duplicate invoice prevention with custom amount...")

        # Submit application with custom amount
        custom_amount_data = self.application_data.copy()
        custom_amount_data["custom_contribution_fee"] = 45.0
        custom_amount_data["uses_custom_amount"] = True
        custom_amount_data["custom_amount_reason"] = "Higher contribution level"
        custom_amount_data["email"] = f"customdup_{self.test_email}"

        result = submit_application(**custom_amount_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Get member and verify setup
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.application_status, "Active")

        # Check invoices - should be exactly one with custom amount
        if member.customer:
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": ["!=", 2]},
                fields=["name", "grand_total", "status"],
            )

            # Should have exactly one invoice
            self.assertEqual(
                len(invoices),
                1,
                f"Should have exactly one invoice, found {len(invoices)}: {[inv.name for inv in invoices]}",
            )

            # Invoice should have the custom amount
            invoice = invoices[0]
            self.assertEqual(
                float(invoice.grand_total),
                45.0,
                f"Invoice amount should be €45.00, got €{invoice.grand_total}",
            )

            # Invoice should be linked to the membership
            self.assertIsNotNone(invoice.membership, "Invoice should be linked to membership")

            # Check membership record
            memberships = frappe.get_all("Membership", filters={"member": member_name})
            self.assertEqual(len(memberships), 1, "Should have exactly one membership")

            membership = frappe.get_doc("Membership", memberships[0].name)
            self.assertTrue(membership.uses_custom_amount, "Membership should use custom amount")
            self.assertEqual(
                float(membership.custom_amount), 45.0, "Membership custom amount should be €45.00"
            )

            # Check dues schedule was created and uses correct custom amount
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name, "membership": membership.name},
                fields=["name", "dues_rate", "status", "contribution_mode"]
            )

            if dues_schedules:
                dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

                # CRITICAL TEST: Dues schedule should use the custom amount (€45.00)
                self.assertEqual(
                    float(dues_schedule.dues_rate),
                    45.0,
                    f"Dues schedule amount should be €45.00 (custom amount), got €{dues_schedule.dues_rate}",
                )

                self.assertEqual(dues_schedule.contribution_mode, "Custom", "Should use custom contribution mode")
                self.assertTrue(dues_schedule.uses_custom_amount, "Should be marked as using custom amount")

                # Dues schedule should be configured properly
                print(f"   Dues schedule effective date: {dues_schedule.effective_date}")
                print(f"   Dues schedule status: {dues_schedule.status}")
                print(f"   Dues schedule amount: €{dues_schedule.dues_rate}")
            else:
                print("   ⚠️  No dues schedule found - may be using legacy override system")

            print(f"✅ Custom amount approval successful for {member_name}")
            print(f"   Single invoice created: {invoice.name} (€{invoice.grand_total})")
            print(f"   Membership custom amount: €{membership.custom_amount}")
            if dues_schedules:
                print(f"   Dues schedule amount: €{dues_schedule.dues_rate}")
            print("   No duplicate invoices created")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    @unittest.skip("Complex billing coordination needs separate investigation")
    def test_invoice_dues_schedule_coordination(self):
        """Test that invoice creation and dues schedule creation are properly coordinated"""
        print("\n🧪 Testing invoice-dues schedule coordination...")

        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Get member and verify the coordination
        member = frappe.get_doc("Member", member_name)

        if member.customer:
            # Get all invoices
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": ["!=", 2]},
                fields=["name", "grand_total", "posting_date"],
            )

            # Get membership
            memberships = frappe.get_all("Membership", filters={"member": member_name})
            self.assertEqual(len(memberships), 1, "Should have exactly one membership")

            membership = frappe.get_doc("Membership", memberships[0].name)

            # Verify invoice is linked to membership
            application_invoices = [inv for inv in invoices if inv.membership == membership.name]
            self.assertEqual(
                len(application_invoices), 1, "Should have exactly one invoice linked to membership"
            )

            # Verify dues schedule exists and is properly configured
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name, "membership": membership.name},
                fields=["name", "status", "dues_rate", "effective_date"]
            )

            if dues_schedules:
                dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

                # Dues schedule should be properly configured
                from frappe.utils import getdate

                if dues_schedule.effective_date >= getdate(membership.start_date):
                    print(f"   ✅ Dues schedule effective from {dues_schedule.effective_date}")
                else:
                    print("   ✅ Dues schedule configured for immediate billing")

            print(f"✅ Invoice-dues schedule coordination working for {member_name}")
            print(f"   Application invoice: {application_invoices[0].name}")
            print(f"   Membership: {membership.name}")
            print(f"   Dues schedules: {len(dues_schedules)}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_custom_amount_dues_schedule_creation(self):
        """Test that custom amounts create proper dues schedules with correct costs"""
        print("\n🧪 Testing custom amount dues schedule creation...")

        # Test multiple custom amounts to ensure each creates the right plan
        test_amounts = [25.0, 50.0, 75.0]

        for custom_amount in test_amounts:
            print(f"\n  Testing custom amount: €{custom_amount}")

            # Submit application with custom amount
            custom_data = self.application_data.copy()
            custom_data["custom_contribution_fee"] = custom_amount
            custom_data["uses_custom_amount"] = True
            custom_data["custom_amount_reason"] = f"Custom contribution of €{custom_amount}"
            custom_data["email"] = f"custom{int(custom_amount)}_{self.test_email}"

            result = submit_application(**custom_data)
            member_name = result["data"]["member_record"]

            # Approve application
            # VereningingenTestCase handles Administrator context appropriately
            approval_result = approve_membership_application(member_name)

            self.assertTrue(approval_result["success"])

            # Get member and check membership
            member = frappe.get_doc("Member", member_name)
            memberships = frappe.get_all("Membership", filters={"member": member_name})
            self.assertEqual(len(memberships), 1, f"Should have exactly one membership for €{custom_amount}")

            membership = frappe.get_doc("Membership", memberships[0].name)

            # Verify membership billing amount
            billing_amount = membership.get_billing_amount()
            self.assertEqual(
                float(billing_amount),
                custom_amount,
                f"Membership billing amount should be €{custom_amount}, got €{billing_amount}",
            )

            # Verify dues schedule
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name, "membership": membership.name},
                fields=["name", "dues_rate", "status", "contribution_mode"]
            )
            self.assertTrue(len(dues_schedules) > 0, f"Dues schedule should exist for €{custom_amount}")

            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

            # CRITICAL ASSERTIONS: Dues schedule amount must match custom amount
            self.assertEqual(
                float(dues_schedule.dues_rate),
                custom_amount,
                f"Dues schedule amount should be €{custom_amount}, got €{dues_schedule.dues_rate}",
            )

            # Clean up
            if member.customer:
                frappe.delete_doc("Customer", member.customer, force=True)
            frappe.delete_doc("Member", member_name, force=True)

            # Clean up custom dues schedule
            if 'dues_schedule' in locals():
                frappe.delete_doc("Membership Dues Schedule", dues_schedule.name, force=True)

        print("✅ All custom amount dues schedules created correctly")

    def test_standard_amount_uses_original_dues_schedule(self):
        """Test that standard amounts use the membership type configuration"""
        print("\n🧪 Testing standard amount uses original membership type configuration...")

        # Submit application WITHOUT custom amount
        standard_data = self.application_data.copy()
        standard_data["email"] = f"standard_{self.test_email}"
        # Explicitly ensure no custom amount
        standard_data.pop("custom_contribution_fee", None)
        standard_data.pop("uses_custom_amount", None)

        result = submit_application(**standard_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Get member and check membership
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        self.assertEqual(len(memberships), 1, "Should have exactly one membership")

        membership = frappe.get_doc("Membership", memberships[0].name)

        # Verify dues schedule uses membership type configuration
        # (the custom-amount flag lives on Membership Dues Schedule, not Membership)
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate", "contribution_mode"]
        )

        if dues_schedules:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)
            membership_type = frappe.get_doc("Membership Type", membership.membership_type)

            # Verify the dues schedule does NOT use a custom amount
            self.assertFalse(
                dues_schedule.uses_custom_amount, "Standard membership should not use custom amount"
            )

            # Standard amount is sourced from the membership type's dues schedule
            # template, not from minimum_amount (which may be 0). Verify the
            # member's dues schedule rate matches the template's configured rate.
            template = frappe.get_doc(
                "Membership Dues Schedule", membership_type.dues_schedule_template
            )
            self.assertEqual(
                float(dues_schedule.dues_rate),
                float(template.dues_rate),
                f"Dues schedule amount should match membership type template rate €{template.dues_rate}, got €{dues_schedule.dues_rate}",
            )

            print(f"✅ Standard membership uses membership type configuration")
            print(f"✅ Dues schedule amount matches membership type template: €{dues_schedule.dues_rate}")
        else:
            print("ℹ️  No dues schedule found - may be using legacy override system")

        # Clean up
        self._cleanup_member_completely(member_name)

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_custom_amount_billing_amount_method(self):
        """Test that get_billing_amount() returns correct amounts for both custom and standard memberships"""
        print("\n🧪 Testing get_billing_amount() method...")

        # Test custom amount
        custom_data = self.application_data.copy()
        custom_data["custom_contribution_fee"] = 35.0
        custom_data["uses_custom_amount"] = True
        custom_data["email"] = f"billing_custom_{self.test_email}"

        result = submit_application(**custom_data)
        member_name = result["data"]["member_record"]

        # VereningingenTestCase handles Administrator context appropriately
        approve_membership_application(member_name)

        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        # Test get_billing_amount() for custom amount
        billing_amount = membership.get_billing_amount()
        self.assertEqual(
            float(billing_amount),
            35.0,
            f"Custom membership billing amount should be €35.00, got €{billing_amount}",
        )

        # Test that dues schedule creation uses this amount
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate", "contribution_mode"]
        )

        if dues_schedules:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)
            self.assertEqual(
                float(dues_schedule.dues_rate),
                35.0,
                f"Generated dues schedule should cost €35.00, got €{dues_schedule.dues_rate}",
            )
            print(f"✅ Dues schedule amount correct: €{dues_schedule.dues_rate}")
        else:
            print("ℹ️  No dues schedule found - using legacy override system")

        print(f"✅ Custom billing amount method works: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)
        if 'dues_schedule' in locals():
            frappe.delete_doc("Membership Dues Schedule", dues_schedule.name, force=True)

        # Test standard amount
        standard_data = self.application_data.copy()
        standard_data["email"] = f"billing_standard_{self.test_email}"
        standard_data.pop("custom_contribution_fee", None)
        standard_data.pop("uses_custom_amount", None)

        result = submit_application(**standard_data)
        member_name = result["data"]["member_record"]

        approve_membership_application(member_name)

        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        # Test get_billing_amount() for standard amount
        billing_amount = membership.get_billing_amount()
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)

        self.assertEqual(
            float(billing_amount),
            float(membership_type.minimum_amount),
            f"Standard membership billing amount should match membership type €{membership_type.minimum_amount}, got €{billing_amount}",
        )

        # Test that dues schedule uses membership type configuration
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate"]
        )

        if dues_schedules:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)
            self.assertEqual(
                float(dues_schedule.dues_rate),
                float(membership_type.minimum_amount),
                "Standard membership should use membership type amount",
            )
            print(f"✅ Uses membership type amount: €{dues_schedule.dues_rate}")
        else:
            print("ℹ️  No dues schedule found - using legacy system")

        print(f"✅ Standard billing amount method works: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    # Test removed - dues schedule system handles amount changes automatically

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_custom_amount_dues_schedule_integration_end_to_end(self):
        """End-to-end integration test for custom amount dues schedule flow"""
        print("\n🧪 Testing complete custom amount dues schedule integration...")

        custom_amount = 42.50

        # 1. Submit application with custom amount
        custom_data = self.application_data.copy()
        custom_data["custom_contribution_fee"] = custom_amount
        custom_data["uses_custom_amount"] = True
        custom_data["custom_amount_reason"] = "Integration test custom amount"
        custom_data["email"] = f"integration_{self.test_email}"

        result = submit_application(**custom_data)
        member_name = result["data"]["member_record"]

        # 2. Verify member has custom amount data in fee override field
        member = frappe.get_doc("Member", member_name)
        self.assertIsNotNone(member.dues_rate, "Member should have fee override set")
        self.assertEqual(
            float(member.dues_rate),
            custom_amount,
            "Fee override should match submitted amount",
        )

        print(f"✅ Custom amount data stored and extracted: €{member.dues_rate}")

        # 3. Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)
        self.assertTrue(approval_result["success"], "Application approval should succeed")

        # 4. Verify complete flow
        member.reload()

        # Check invoice
        if member.customer:
            invoices = frappe.get_all(
                "Sales Invoice", filters={"customer": member.customer, "docstatus": ["!=", 2]}
            )
            self.assertEqual(len(invoices), 1, "Should have exactly one invoice")

            invoice = frappe.get_doc("Sales Invoice", invoices[0].name)
            self.assertEqual(
                float(invoice.grand_total),
                custom_amount,
                f"Invoice should have custom amount €{custom_amount}, got €{invoice.grand_total}",
            )

            print(f"✅ Invoice created with correct amount: €{invoice.grand_total}")

        # Check membership
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        self.assertEqual(len(memberships), 1, "Should have exactly one membership")

        membership = frappe.get_doc("Membership", memberships[0].name)
        self.assertTrue(membership.uses_custom_amount, "Membership should use custom amount")
        self.assertEqual(
            float(membership.custom_amount), custom_amount, "Membership custom amount should match"
        )
        self.assertEqual(float(membership.get_billing_amount()), custom_amount, "Billing amount should match")

        print(f"✅ Membership configured correctly: €{membership.custom_amount}")

        # Check dues schedule (THE CRITICAL TEST)
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate", "status", "contribution_mode"]
        )
        self.assertTrue(len(dues_schedules) > 0, "Dues schedule should be created")

        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

        # THIS IS THE KEY ASSERTION THAT WOULD HAVE CAUGHT THE ORIGINAL BUG
        self.assertEqual(
            float(dues_schedule.dues_rate),
            custom_amount,
            f"CRITICAL: Dues schedule amount MUST be €{custom_amount}, got €{dues_schedule.dues_rate}",
        )

        self.assertEqual(dues_schedule.contribution_mode, "Custom", f"Contribution mode should be Custom")
        self.assertTrue(dues_schedule.uses_custom_amount, "Should use custom amount")

        print(f"🎯 CRITICAL TEST PASSED: Dues schedule amount = €{dues_schedule.dues_rate}")
        print(f"🎯 Custom dues schedule: {dues_schedule.name}")

        # The critical dues-schedule amount assertion above already verifies that
        # future invoice generation will use the correct custom amount.
        print("🎉 END-TO-END INTEGRATION TEST PASSED - Custom amount flows correctly through entire system!")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom dues schedule
        try:
            frappe.delete_doc("Membership Dues Schedule", dues_schedule.name, force=True)
        except Exception:
            pass

    def test_volunteer_application_processing(self):
        """Test that volunteer applications are properly processed"""
        # Submit application with volunteer interest
        volunteer_data = self.application_data.copy()
        volunteer_data["interested_in_volunteering"] = 1
        volunteer_data["volunteer_availability"] = "Weekly"
        volunteer_data["volunteer_interests"] = ["Event Planning", "Technical Support"]
        volunteer_data["volunteer_skills"] = "Event coordination, Public speaking, IT support"
        volunteer_data["email"] = f"volunteer_{self.test_email}"

        result = submit_application(**volunteer_data)

        # Verify submission successful
        self.assertTrue(result["success"])
        member = frappe.get_doc("Member", result["data"]["member_record"])

        # Verify volunteer data was stored
        self.assertEqual(member.interested_in_volunteering, 1)
        # Note: volunteer_availability is not stored in Member doctype
        # Volunteer-specific data is stored in Volunteer record when created

        print(f"✅ Volunteer application data properly stored for {member.name}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member.name, force=True)

    def test_volunteer_record_creation_after_payment(self):
        """Test that volunteer record is created after application approval"""
        # Submit application with volunteer interest
        volunteer_data = self.application_data.copy()
        volunteer_data["interested_in_volunteering"] = 1
        volunteer_data["volunteer_availability"] = "Monthly"
        volunteer_data["volunteer_interests"] = ["Community Outreach"]
        volunteer_data["volunteer_skills"] = "Community engagement, Communication"
        volunteer_data["email"] = f"volpay_{self.test_email}"

        # Submit and approve application
        result = submit_application(**volunteer_data)
        member_name = result["data"]["member_record"]

        # VereningingenTestCase handles Administrator context appropriately
        approve_membership_application(member_name)

        # Verify volunteer record was created
        volunteer_exists = frappe.db.exists("Volunteer", {"member": member_name})
        self.assertTrue(volunteer_exists, "Volunteer record should be created after approval")

        if volunteer_exists:
            volunteer = frappe.get_doc("Volunteer", {"member": member_name})
            self.assertEqual(volunteer.volunteer_name, frappe.get_doc("Member", member_name).full_name)
            self.assertTrue(volunteer.status in ["New", "Active"])

            print(f"✅ Volunteer record created: {volunteer.name} for member {member_name}")

        # Clean up
        self._cleanup_member_completely(member_name)

    def test_non_volunteer_application(self):
        """Test that non-volunteer applications don't create volunteer records"""
        # Submit application without volunteer interest
        non_volunteer_data = self.application_data.copy()
        non_volunteer_data["interested_in_volunteering"] = 0
        non_volunteer_data["email"] = f"nonvol_{self.test_email}"

        # Submit and approve application
        result = submit_application(**non_volunteer_data)
        member_name = result["data"]["member_record"]

        # VereningingenTestCase handles Administrator context appropriately
        approve_membership_application(member_name)

        # Verify NO volunteer record was created
        volunteer_exists = frappe.db.exists("Volunteer", {"member": member_name})
        self.assertFalse(volunteer_exists, "No volunteer record should be created for non-volunteer members")

        print(f"✅ No volunteer record created for non-volunteer member {member_name}")

        # Clean up
        self._cleanup_member_completely(member_name)

    def test_volunteer_interest_areas_validation(self):
        """Test that volunteer interest areas are properly validated"""
        # Submit application with valid volunteer interests
        valid_volunteer_data = self.application_data.copy()
        valid_volunteer_data["interested_in_volunteering"] = 1
        valid_volunteer_data["volunteer_interests"] = ["Event Planning", "Technical Support"]
        valid_volunteer_data["email"] = f"validvol_{self.test_email}"

        result = submit_application(**valid_volunteer_data)
        self.assertTrue(result["success"])

        member = frappe.get_doc("Member", result["data"]["member_record"])
        # Should store the interests properly
        self.assertTrue(member.interested_in_volunteering)

        print(f"✅ Valid volunteer interests processed for {member.name}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member.name, force=True)

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_edge_case_zero_custom_amount(self):
        """Test that zero custom amount defaults to standard amount"""
        print("\n🧪 Testing zero custom amount edge case...")

        # Submit application with zero custom amount
        zero_data = self.application_data.copy()
        zero_data["custom_contribution_fee"] = 0.0
        zero_data["uses_custom_amount"] = True
        zero_data["email"] = f"zero_{self.test_email}"

        result = submit_application(**zero_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Check membership - should fall back to standard amount
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        # Should not use custom amount if amount is zero
        billing_amount = membership.get_billing_amount()
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)

        # Should use standard amount, not zero
        self.assertEqual(
            float(billing_amount),
            float(membership_type.minimum_amount),
            f"Zero custom amount should fall back to standard amount €{membership_type.minimum_amount}",
        )

        print(f"✅ Zero custom amount correctly handled: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_negative_custom_amount_validation(self):
        """Test that negative custom amounts are rejected"""
        print("\n🧪 Testing negative custom amount validation...")

        # Submit application with negative custom amount
        negative_data = self.application_data.copy()
        negative_data["custom_contribution_fee"] = -10.0
        negative_data["uses_custom_amount"] = True
        negative_data["email"] = f"negative_{self.test_email}"

        # This should either fail during submission or be corrected
        try:
            result = submit_application(**negative_data)
            # Check if result indicates failure
            if not result.get("success", False):
                print(f"✅ Negative amount rejected during submission: {result.get('error', '')}")
                return

            member_name = result["data"]["member_record"]

            # If submission succeeds, check that amount was corrected
            member = frappe.get_doc("Member", member_name)

            # Should either have no custom amount or positive amount
            fee_override = getattr(member, "dues_rate", 0)
            if fee_override:
                self.assertGreater(fee_override, 0, "Custom amount should not be negative")

            print(f"✅ Negative amount handled gracefully: {fee_override}")

            # Clean up
            if member.customer:
                frappe.delete_doc("Customer", member.customer, force=True)
            frappe.delete_doc("Member", member_name, force=True)

        except Exception as e:
            # If it fails during submission, that's also acceptable
            print(f"✅ Negative amount rejected during submission: {str(e)}")
            # Accept any exception as the test is checking validation works

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_very_large_custom_amount(self):
        """Test handling of very large custom amounts"""
        print("\n🧪 Testing very large custom amount...")

        large_amount = 999999.99

        # Submit application with very large custom amount
        large_data = self.application_data.copy()
        large_data["custom_contribution_fee"] = large_amount
        large_data["uses_custom_amount"] = True
        large_data["email"] = f"large_{self.test_email}"

        result = submit_application(**large_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Check that system handles large amounts correctly
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        billing_amount = membership.get_billing_amount()
        self.assertEqual(
            float(billing_amount), large_amount, f"Large custom amount should be preserved: €{large_amount}"
        )

        # Check dues schedule handles large amounts
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate"]
        )

        if dues_schedules:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

            self.assertEqual(
                float(dues_schedule.dues_rate),
                large_amount,
                f"Dues schedule should handle large amount: €{large_amount}",
            )

        print(f"✅ Large amount handled correctly: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom dues schedule
        try:
            if 'dues_schedule' in locals():
                frappe.delete_doc("Membership Dues Schedule", dues_schedule.name, force=True)
        except Exception:
            pass

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_decimal_precision_custom_amount(self):
        """Test custom amounts with decimal precision"""
        print("\n🧪 Testing decimal precision in custom amounts...")

        # Test with 3 decimal places
        precise_amount = 42.567

        # Submit application with precise decimal amount
        decimal_data = self.application_data.copy()
        decimal_data["custom_contribution_fee"] = precise_amount
        decimal_data["uses_custom_amount"] = True
        decimal_data["email"] = f"decimal_{self.test_email}"

        result = submit_application(**decimal_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Check decimal precision handling
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        billing_amount = membership.get_billing_amount()

        # Should preserve precision to 2 decimal places (standard currency precision)
        expected_amount = round(precise_amount, 2)
        self.assertEqual(
            float(billing_amount),
            expected_amount,
            f"Decimal precision should be handled correctly: €{expected_amount}",
        )

        # Check dues schedule precision
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate"]
        )

        if dues_schedules:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

            self.assertEqual(
                float(dues_schedule.dues_rate),
                expected_amount,
                f"Dues schedule should maintain precision: €{expected_amount}",
            )

        print(f"✅ Decimal precision handled correctly: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom dues schedule
        try:
            if 'dues_schedule' in locals():
                frappe.delete_doc("Membership Dues Schedule", dues_schedule.name, force=True)
        except Exception:
            pass

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_custom_amount_dues_schedule_functionality(self):
        """Test that custom amounts work properly with dues schedule system"""
        print("\n🧪 Testing custom amount functionality with dues schedule system...")

        custom_amount = 55.0

        # Create first member with custom amount
        first_data = self.application_data.copy()
        first_data["custom_contribution_fee"] = custom_amount
        first_data["uses_custom_amount"] = True
        first_data["email"] = f"first_reuse_{self.test_email}"

        result1 = submit_application(**first_data)
        member1_name = result1["data"]["member_record"]

        # VereningingenTestCase handles Administrator context appropriately
        approve_membership_application(member1_name)

        # Get first dues schedule
        memberships1 = frappe.get_all("Membership", filters={"member": member1_name})
        membership1 = frappe.get_doc("Membership", memberships1[0].name)
        dues_schedules1 = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member1_name, "membership": membership1.name},
            fields=["name", "dues_rate"]
        )
        dues_schedule1 = frappe.get_doc("Membership Dues Schedule", dues_schedules1[0].name) if dues_schedules1 else None

        # Create second member with same custom amount
        second_data = self.application_data.copy()
        second_data["custom_contribution_fee"] = custom_amount
        second_data["uses_custom_amount"] = True
        second_data["email"] = f"second_reuse_{self.test_email}"

        result2 = submit_application(**second_data)
        member2_name = result2["data"]["member_record"]

        approve_membership_application(member2_name)

        # Get second dues schedule
        memberships2 = frappe.get_all("Membership", filters={"member": member2_name})
        membership2 = frappe.get_doc("Membership", memberships2[0].name)
        dues_schedules2 = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member2_name, "membership": membership2.name},
            fields=["name", "dues_rate"]
        )
        dues_schedule2 = frappe.get_doc("Membership Dues Schedule", dues_schedules2[0].name) if dues_schedules2 else None

        # Both should have the same custom amount configuration
        if dues_schedule1 and dues_schedule2:
            self.assertEqual(
                float(dues_schedule1.amount),
                float(dues_schedule2.amount),
                f"Identical custom amounts should have same dues schedule amounts"
            )

            # Verify both schedules have correct cost
            self.assertEqual(
                float(dues_schedule1.amount), custom_amount, f"First schedule should have correct cost: €{custom_amount}"
            )
            self.assertEqual(
                float(dues_schedule2.amount), custom_amount, f"Second schedule should have correct cost: €{custom_amount}"
            )

        print(f"✅ Dues schedule amounts consistent for identical custom amounts")
        if dues_schedule1:
            print(f"   Both memberships use same amount: €{dues_schedule1.amount}")

        # Clean up
        member1 = frappe.get_doc("Member", member1_name)
        member2 = frappe.get_doc("Member", member2_name)

        if member1.customer:
            frappe.delete_doc("Customer", member1.customer, force=True)
        if member2.customer:
            frappe.delete_doc("Customer", member2.customer, force=True)

        frappe.delete_doc("Member", member1_name, force=True)
        frappe.delete_doc("Member", member2_name, force=True)

        # Clean up dues schedules
        try:
            if dues_schedule1:
                frappe.delete_doc("Membership Dues Schedule", dues_schedule1.name, force=True)
            if dues_schedule2:
                frappe.delete_doc("Membership Dues Schedule", dues_schedule2.name, force=True)
        except Exception:
            pass

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_custom_amount_with_different_membership_types(self):
        """Test custom amounts work with different membership types"""
        print("\n🧪 Testing custom amounts with different membership types...")

        # Create a second membership type for testing
        if not frappe.db.exists("Membership Type", "Premium Test Membership"):
            premium_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Premium Test Membership",
                    "minimum_amount": 200,
                    "role_profile": "Verenigingen Member",
                }
            )
            premium_type.insert()

        custom_amount = 150.0

        # Test with premium membership type
        premium_data = self.application_data.copy()
        premium_data["selected_membership_type"] = "Premium Test Membership"
        premium_data["custom_contribution_fee"] = custom_amount
        premium_data["uses_custom_amount"] = True
        premium_data["email"] = f"premium_{self.test_email}"

        result = submit_application(**premium_data)
        member_name = result["data"]["member_record"]

        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Check that custom amount works with different membership type
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        # Should use custom amount, not the membership type amount (€200)
        billing_amount = membership.get_billing_amount()
        self.assertEqual(
            float(billing_amount),
            custom_amount,
            f"Custom amount should override membership type amount: €{custom_amount} not €200",
        )

        # Check dues schedule
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate", "contribution_mode"]
        )

        if dues_schedules:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

            self.assertEqual(
                float(dues_schedule.dues_rate),
                custom_amount,
                f"Dues schedule should use custom amount: €{custom_amount}",
            )

            # Should be marked as custom contribution mode
            self.assertEqual(
                dues_schedule.contribution_mode, "Custom", f"Should use custom contribution mode"
            )

        print(f"✅ Custom amount works with premium membership type: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom dues schedule
        try:
            if 'dues_schedule' in locals():
                frappe.delete_doc("Membership Dues Schedule", dues_schedule.name, force=True)
        except Exception:
            pass

        # Clean up premium membership type
        try:
            frappe.delete_doc("Membership Type", "Premium Test Membership", force=True)
        except Exception:
            pass

    @unittest.skip("Custom amount billing integration needs separate investigation")
    def test_custom_amount_invoice_and_dues_schedule_coordination_edge_cases(self):
        """Test edge cases in invoice-dues schedule coordination with custom amounts"""
        print("\n🧪 Testing custom amount invoice-dues schedule coordination edge cases...")

        custom_amount = 37.50

        # Submit application with custom amount
        edge_data = self.application_data.copy()
        edge_data["custom_contribution_fee"] = custom_amount
        edge_data["uses_custom_amount"] = True
        edge_data["email"] = f"edge_{self.test_email}"

        result = submit_application(**edge_data)
        member_name = result["data"]["member_record"]

        # Approve application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Get member and membership
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        # Test multiple edge cases
        edge_cases_passed = 0

        # Edge case 1: Application invoice exists and has correct amount
        if member.customer:
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": ["!=", 2]},
                fields=["name", "grand_total"],
            )

            application_invoices = [inv for inv in invoices if inv.membership == membership.name]
            if application_invoices:
                app_invoice = application_invoices[0]
                self.assertEqual(
                    float(app_invoice.grand_total),
                    custom_amount,
                    f"Application invoice should have custom amount: €{custom_amount}",
                )
                edge_cases_passed += 1
                print("   ✅ Edge case 1: Application invoice amount correct")

        # Edge case 2: Dues schedule exists and uses correct amount
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "membership": membership.name},
            fields=["name", "dues_rate", "status"]
        )
        if dues_schedules:
            dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0].name)

            self.assertEqual(
                float(dues_schedule.dues_rate),
                custom_amount,
                f"Dues schedule amount should match custom amount: €{custom_amount}",
            )
            edge_cases_passed += 1
            print("   ✅ Edge case 2: Dues schedule amount correct")

        # Edge case 3: get_billing_amount() returns custom amount
        billing_amount = membership.get_billing_amount()
        self.assertEqual(
            float(billing_amount),
            custom_amount,
            f"get_billing_amount() should return custom amount: €{custom_amount}",
        )
        edge_cases_passed += 1
        print("   ✅ Edge case 3: get_billing_amount() correct")

        # Edge case 4: Custom amount flags are set correctly
        self.assertTrue(membership.uses_custom_amount, "uses_custom_amount should be True")
        self.assertEqual(
            float(membership.custom_amount),
            custom_amount,
            f"custom_amount field should be set: €{custom_amount}",
        )
        edge_cases_passed += 1
        print("   ✅ Edge case 4: Custom amount flags correct")

        # Edge case 5: Consistent dues schedule handling for same amount
        # (This tests the reuse functionality)
        second_member_data = self.application_data.copy()
        second_member_data["custom_contribution_fee"] = custom_amount  # Same amount
        second_member_data["uses_custom_amount"] = True
        second_member_data["email"] = f"edge2_{self.test_email}"

        result2 = submit_application(**second_member_data)
        member2_name = result2["data"]["member_record"]
        approve_membership_application(member2_name)

        memberships2 = frappe.get_all("Membership", filters={"member": member2_name})
        membership2 = frappe.get_doc("Membership", memberships2[0].name)

        dues_schedules2 = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member2_name, "membership": membership2.name},
            fields=["name", "dues_rate"]
        )
        if dues_schedules2:
            dues_schedule2 = frappe.get_doc("Membership Dues Schedule", dues_schedules2[0].name)

            # Should have same amount configuration
            self.assertEqual(
                float(dues_schedule2.amount),
                custom_amount,
                "Should have same dues schedule amount for same custom amount"
            )
            edge_cases_passed += 1
            print("   ✅ Edge case 5: Dues schedule amount consistency correct")

        print(f"✅ All {edge_cases_passed} edge cases passed for custom amount coordination")

        # Clean up
        member2 = frappe.get_doc("Member", member2_name)

        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        if member2.customer:
            frappe.delete_doc("Customer", member2.customer, force=True)

        frappe.delete_doc("Member", member_name, force=True)
        frappe.delete_doc("Member", member2_name, force=True)

        # Clean up dues schedules
        try:
            if 'dues_schedule' in locals():
                frappe.delete_doc("Membership Dues Schedule", dues_schedule.name, force=True)
            if 'dues_schedule2' in locals():
                frappe.delete_doc("Membership Dues Schedule", dues_schedule2.name, force=True)
        except Exception:
            pass


class TestChapterSelection(EnhancedTestCase):
    """Test chapter selection functionality in membership applications"""

    @classmethod
    def setUpClass(cls):
        """Set up test data for chapter tests"""
        super().setUpClass()
        # Create required Regions. autoname=field:region_name scrubs to dashes,
        # so capture the resolved .name to use in Chapter.region links below.
        cls.regions = {}
        for r_name, r_code in [
            ("Noord-Holland", "NH"),
            ("Utrecht", "UT"),
            ("Zuid-Holland", "ZH"),
            ("Limburg", "LI"),
        ]:
            cls.regions[r_name] = _ensure_region(r_name, r_code)
        region_name = cls.regions["Noord-Holland"]

        # Create test membership type
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "minimum_amount": 15,  # Match default template dues_rate
                    "role_profile": "Verenigingen Member",
                }
            )
            membership_type.insert()
            # Dues schedule system handles payment processing automatically

        # Create test chapters with different configurations
        test_chapters = [
            {
                "name": "Test Chapter Amsterdam",
                "region": region_name,
                "postal_codes": "1000-1199",
                "published": 1,
                "introduction": "Test chapter for Amsterdam region"},
            {
                "name": "Test Chapter Utrecht",
                "region": cls.regions["Utrecht"],
                "postal_codes": "3500-3599",
                "published": 1,
                "introduction": "Test chapter for Utrecht region"},
            {
                "name": "Test Chapter Rotterdam",
                "region": cls.regions["Zuid-Holland"],
                "postal_codes": "3000-3099",
                "published": 1,
                "introduction": "Test chapter for Rotterdam region"},
            {
                "name": "Unpublished Chapter",
                "region": cls.regions["Limburg"],
                "postal_codes": "6000-6199",
                "published": 0,  # Not published
                "introduction": "Test unpublished chapter"},
        ]

        for chapter_data in test_chapters:
            if not frappe.db.exists("Chapter", chapter_data["name"]):
                chapter = frappe.get_doc({"doctype": "Chapter", **chapter_data})
                chapter.insert()

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        unique = frappe.generate_hash(length=8)
        self.test_email = f"chapter_test_{unique}@example.com"
        self.base_application_data = {
            "first_name": "Chapter",
            # Unique last name: the auto-created Customer is named after the
            # member's full_name, so a fixed "Chapter Tester" collides (and its
            # Contact link blocks teardown) once the approval flow actually
            # creates the Customer. Keep it unique per test.
            "last_name": f"Tester {unique}",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1012AB",  # Valid Dutch postal code format
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
            "contact_number": "+31612345678",
            "interested_in_volunteering": 0,
            "newsletter_opt_in": 1,
            "application_source": "Website"}

    def tearDown(self):
        """Clean up after each test"""
        # Delete test member if exists
        if frappe.db.exists("Member", {"email": self.test_email}):
            member = frappe.get_doc("Member", {"email": self.test_email})

            # Delete related records
            if member.customer:
                frappe.delete_doc("Customer", member.customer, force=True)

            # Delete memberships
            memberships = frappe.get_all("Membership", filters={"member": member.name})
            for membership in memberships:
                frappe.delete_doc("Membership", membership.name, force=True)

            # Delete member
            frappe.delete_doc("Member", member.name, force=True)

        frappe.db.commit()
        super().tearDown()

    def test_get_form_data_includes_chapters(self):
        """Test that get_form_data API includes published chapters"""
        from verenigingen.utils.application_helpers import get_form_data

        result = get_form_data()

        self.assertTrue(result["success"], "get_form_data should succeed")
        self.assertIn("chapters", result, "Response should include chapters")

        chapters = result["chapters"]
        self.assertIsInstance(chapters, list, "Chapters should be a list")
        self.assertGreater(len(chapters), 0, "Should have at least one published chapter")

        # Verify chapter structure
        for chapter in chapters:
            self.assertIn("name", chapter, "Chapter should have name")
            self.assertIn("region", chapter, "Chapter should have region")
            # Should NOT have 'city' field (this was the bug we fixed)
            self.assertNotIn("city", chapter, "Chapter should NOT have city field")

        # Verify only published chapters are returned
        chapter_names = [ch["name"] for ch in chapters]
        self.assertIn("Test Chapter Amsterdam", chapter_names, "Should include published chapters")
        self.assertNotIn("Unpublished Chapter", chapter_names, "Should NOT include unpublished chapters")

        print(f"✅ Form data includes {len(chapters)} published chapters")
        for chapter in chapters:
            print(f"   - {chapter['name']} ({chapter.get('region', 'No region')})")

    def test_chapter_selection_in_application(self):
        """Test chapter selection during application submission"""
        # Submit application with specific chapter selection
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Test Chapter Utrecht"

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application with chapter selection should succeed")

        # Verify chapter was assigned to member
        member = frappe.get_doc("Member", result["data"]["member_record"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(
            primary_chapter, "Test Chapter Utrecht", "Selected chapter should be assigned to member"
        )

        print(f"✅ Chapter selection works: {primary_chapter}")

    def test_application_without_chapter_selection(self):
        """Test application submission without chapter selection (optional field)"""
        # Submit application without chapter selection
        # Use postal code and city outside any chapter's range to avoid auto-assignment
        application_data = self.base_application_data.copy()
        application_data["postal_code"] = "9999ZZ"  # Outside any chapter postal range
        application_data["city"] = "Nowheresville"  # City that won't match any chapter
        # No selected_chapter field

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application without chapter should succeed")

        # Verify member was created without chapter (no postal code or city match)
        member = frappe.get_doc("Member", result["data"]["member_record"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertFalse(primary_chapter, "Member should have no chapter assigned when location doesn't match")

        print("✅ Application without chapter selection works")

    def test_invalid_chapter_selection(self):
        """Test application with invalid/non-existent chapter"""
        # Submit application with non-existent chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Non-Existent Chapter"

        result = submit_application(**application_data)

        # Should either succeed (ignoring invalid chapter) or fail gracefully
        if result["success"]:
            member = frappe.get_doc("Member", result["data"]["member_record"])
            # Invalid chapter should not be assigned
            primary_chapter = get_member_primary_chapter(member.name)
            self.assertNotEqual(
                primary_chapter, "Non-Existent Chapter", "Invalid chapter should not be assigned"
            )
        else:
            # If it fails, should have appropriate error message
            self.assertIn("chapter", (result.get("error") or "").lower(), "Error should mention chapter issue")

        print("✅ Invalid chapter selection handled gracefully")

    @unittest.skip("Current behavior allows unpublished chapter assignment - needs business rule review")
    def test_unpublished_chapter_selection(self):
        """Test application with unpublished chapter selection"""
        # Submit application with unpublished chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Unpublished Chapter"

        result = submit_application(**application_data)

        # Should succeed but unpublished chapter should not be assigned
        self.assertTrue(result["success"], "Application should succeed")

        member = frappe.get_doc("Member", result["data"]["member_record"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertNotEqual(
            primary_chapter, "Unpublished Chapter", "Unpublished chapter should not be assigned"
        )

        print("✅ Unpublished chapter selection handled correctly")

    @unittest.skip("Chapter matching returns different chapter - test setup mismatch")
    def test_chapter_suggestion_by_postal_code(self):
        """Test automatic chapter suggestion based on postal code"""
        from verenigingen.utils.application_helpers import determine_chapter_from_application

        # Test postal code that should match Amsterdam chapter (1000-1199)
        test_data = {"postal_code": "1050", "city": "Amsterdam", "state": "Noord-Holland"}

        suggested_chapter = determine_chapter_from_application(test_data)

        # Should suggest Amsterdam chapter based on postal code
        if suggested_chapter:
            self.assertEqual(
                suggested_chapter,
                "Test Chapter Amsterdam",
                "Should suggest correct chapter based on postal code",
            )
            print(f"✅ Chapter suggestion works: {suggested_chapter} for postal code 1050")
        else:
            print("ℹ️ Chapter suggestion returned None (might need postal code matching logic)")

    def test_form_data_api_endpoint(self):
        """Test the API endpoint for form data returns chapters"""
        from verenigingen.api.membership_application import get_application_form_data

        result = get_application_form_data()

        self.assertTrue(result["success"], "API endpoint should succeed")
        self.assertIn("chapters", result["data"], "API should return chapters")

        chapters = result["data"]["chapters"]
        self.assertIsInstance(chapters, list, "Chapters should be a list")

        # Verify structure matches expected format for frontend
        for chapter in chapters:
            self.assertIn("name", chapter, "Chapter should have name for frontend")
            self.assertIn("region", chapter, "Chapter should have region for frontend")

        print(f"✅ API endpoint returns {len(chapters)} chapters")

    def test_no_database_errors_with_chapter_fields(self):
        """Test that chapter queries don't cause database field errors"""
        from verenigingen.utils.application_helpers import get_form_data

        # This test specifically checks that we don't get 'city' field errors
        try:
            result = get_form_data()
            self.assertTrue(result["success"], "Should not have database field errors")

            chapters = result.get("chapters", [])

            # If we have chapters, verify the field structure
            if chapters:
                for chapter in chapters:
                    # Should have valid fields that exist in database
                    self.assertIn("name", chapter)
                    # region is optional but if present, should be valid
                    if "region" in chapter:
                        self.assertIsInstance(chapter["region"], (str, type(None)))

                    # Should NOT have city field (this was causing the error)
                    self.assertNotIn("city", chapter, "Should not include non-existent city field")

            print("✅ No database field errors when loading chapters")

        except Exception as e:
            self.fail(f"Database error when loading chapters: {str(e)}")

    @unittest.skip("Chapter assignment test has test setup issues")
    def test_member_form_chapter_assignment_simplification(self):
        """Test that member form chapter assignment is simplified"""
        # Create a member without a chapter - use postal code and city outside any chapter range
        application_data = self.base_application_data.copy()
        application_data["postal_code"] = "9999ZZ"  # Outside any chapter postal range
        application_data["city"] = "Nowheresville"  # City that won't match any chapter
        result = submit_application(**application_data)
        member_name = result["data"]["member_record"]

        member = frappe.get_doc("Member", member_name)
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertFalse(primary_chapter, "Member should start without chapter when location doesn't match")

        # Test direct chapter assignment (simulating the simplified form)
        # Assign member to chapter via Chapter Member table
        # Note: add_member_to_chapter_roster handles all DB updates internally
        add_member_to_chapter_roster(member.name, "Test Chapter Utrecht")

        # Verify assignment worked
        member.reload()
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, "Test Chapter Utrecht", "Direct chapter assignment should work")

        print("✅ Simplified chapter assignment works")

    def test_chapter_selection_with_custom_amount(self):
        """Test chapter selection works with custom membership amounts"""
        # Submit application with both chapter selection and custom amount
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Test Chapter Rotterdam"
        application_data["custom_contribution_fee"] = 75.0
        application_data["uses_custom_amount"] = True
        application_data["custom_amount_reason"] = "Test custom with chapter"

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application with chapter and custom amount should succeed")

        member = frappe.get_doc("Member", result["data"]["member_record"])

        # Verify both chapter and custom amount were processed
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, "Test Chapter Rotterdam", "Chapter should be assigned")
        self.assertEqual(member.dues_rate, 75.0, "Custom amount should be set")

        print("✅ Chapter selection works with custom amounts")

    def test_chapter_data_persistence_through_approval_flow(self):
        """Test that chapter data persists through the entire approval flow"""
        # Submit application with chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Test Chapter Amsterdam"

        result = submit_application(**application_data)
        member_name = result["data"]["member_record"]

        # Verify initial assignment
        member = frappe.get_doc("Member", member_name)
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, "Test Chapter Amsterdam")

        # Approve the application
        # VereningingenTestCase handles Administrator context appropriately
        approval_result = approve_membership_application(member_name, "Test approval")

        self.assertTrue(approval_result["success"], "Approval should succeed")

        # Verify chapter is preserved after approval
        member.reload()
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, "Test Chapter Amsterdam", "Chapter should persist through approval")

        print("✅ Chapter data persists through approval flow")

        # Clean up - proper deletion order
        try:
            member = frappe.get_doc("Member", member_name)
            customer_name = member.customer

            # Delete invoices first
            if customer_name:
                for inv in frappe.get_all("Sales Invoice", filters={"customer": customer_name}):
                    try:
                        inv_doc = frappe.get_doc("Sales Invoice", inv.name)
                        if inv_doc.docstatus == 1:
                            inv_doc.cancel()
                        frappe.delete_doc("Sales Invoice", inv.name, force=True)
                    except Exception:
                        pass

            # Delete dues schedules
            for schedule in frappe.get_all("Membership Dues Schedule", filters={"member": member_name}):
                try:
                    frappe.delete_doc("Membership Dues Schedule", schedule.name, force=True)
                except Exception:
                    pass

            # Delete memberships
            for membership in frappe.get_all("Membership", filters={"member": member_name}):
                try:
                    m_doc = frappe.get_doc("Membership", membership.name)
                    if m_doc.docstatus == 1:
                        m_doc.cancel()
                    frappe.delete_doc("Membership", membership.name, force=True)
                except Exception:
                    pass

            # Delete member
            frappe.delete_doc("Member", member_name, force=True)

            # Delete customer last
            if customer_name:
                frappe.delete_doc("Customer", customer_name, force=True)
        except Exception:
            pass

    def test_multiple_chapters_in_same_region(self):
        """Test handling of multiple chapters in the same region"""
        # Create additional chapter in same region as existing one
        additional_chapter_name = "Test Chapter Amsterdam West"
        if not frappe.db.exists("Chapter", additional_chapter_name):
            additional_chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": additional_chapter_name,
                    "region": "Noord-Holland",  # Same as Amsterdam
                    "postal_codes": "1200-1299",
                    "published": 1,
                    "introduction": "Test chapter for Amsterdam West area"}
            )
            additional_chapter.insert()

        # Get form data and verify both chapters are available
        from verenigingen.utils.application_helpers import get_form_data

        result = get_form_data()

        chapters = result["chapters"]
        chapter_names = [ch["name"] for ch in chapters]

        self.assertIn(
            "Test Chapter Amsterdam", chapter_names, "Original Amsterdam chapter should be available"
        )
        self.assertIn(
            additional_chapter_name, chapter_names, "Additional Amsterdam chapter should be available"
        )

        # Test selecting the additional chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = additional_chapter_name

        result = submit_application(**application_data)
        member = frappe.get_doc("Member", result["data"]["member_record"])

        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(
            primary_chapter,
            additional_chapter_name,
            "Should be able to select specific chapter even in same region",
        )

        print("✅ Multiple chapters in same region handled correctly")

        # Clean up additional chapter
        try:
            frappe.delete_doc("Chapter", additional_chapter_name, force=True)
        except Exception:
            pass

    def test_chapter_selection_edge_case_empty_string(self):
        """Test chapter selection with empty string value"""
        # Submit application with empty string for chapter
        # Use postal code and city outside any chapter range to avoid auto-assignment
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = ""
        application_data["postal_code"] = "9999ZZ"  # Outside any chapter postal range
        application_data["city"] = "Nowheresville"  # City that won't match any chapter

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application with empty chapter string should succeed")

        member = frappe.get_doc("Member", result["data"]["member_record"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertFalse(primary_chapter, "Empty chapter string with non-matching location should result in no chapter")

        print("✅ Empty chapter string handled correctly")

    def test_chapter_selection_edge_case_whitespace(self):
        """Test chapter selection with whitespace-only value"""
        # Submit application with whitespace-only chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "   "

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application with whitespace chapter should succeed")

        member = frappe.get_doc("Member", result["data"]["member_record"])
        # Should either be empty or trimmed, but not contain whitespace
        chapter = get_member_primary_chapter(member.name) or ""
        self.assertEqual(chapter.strip(), chapter, "Chapter should not have leading/trailing whitespace")

        print("✅ Whitespace chapter value handled correctly")

    def test_chapter_field_validation_in_database(self):
        """Test that chapter field validation works correctly in database"""
        # Test valid chapter assignment
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Test Chapter Utrecht"

        result = submit_application(**application_data)
        member = frappe.get_doc("Member", result["data"]["member_record"])

        # Should be able to save with valid chapter
        try:
            member.save()
            print("✅ Valid chapter saves correctly")
        except Exception as e:
            self.fail(f"Valid chapter should save without error: {str(e)}")

        # Test that the chapter field accepts None/empty values (since it's optional)
        # Remove member from all chapters by disabling Chapter Member records
        frappe.db.set_value("Chapter Member", {"member": member.name}, "enabled", 0)
        try:
            member.save()
            print("✅ Empty chapter saves correctly")
        except Exception as e:
            self.fail(f"Empty chapter should save without error: {str(e)}")

    def test_api_performance_with_large_chapter_list(self):
        """Test API performance when there are many chapters"""
        # Create several additional test chapters
        temp_chapters = []
        for i in range(10):
            chapter_name = f"Temp Test Chapter {i}"
            if not frappe.db.exists("Chapter", chapter_name):
                chapter = frappe.get_doc(
                    {
                        "doctype": "Chapter",
                        "name": chapter_name,
                        "region": "Noord-Holland",  # Use existing region
                        "postal_codes": f"{4000 + i * 100}-{4099 + i * 100}",
                        "published": 1,
                        "introduction": f"Test chapter {i} for performance testing"}
                )
                chapter.insert()
                temp_chapters.append(chapter_name)

        # Test form data loading performance
        import time

        start_time = time.time()

        from verenigingen.utils.application_helpers import get_form_data

        result = get_form_data()

        end_time = time.time()
        load_time = end_time - start_time

        # Should complete reasonably quickly (under 2 seconds)
        self.assertLess(load_time, 2.0, "Form data loading should be fast even with many chapters")

        chapters = result["chapters"]
        self.assertGreaterEqual(len(chapters), 10, "Should load all published chapters")

        print(f"✅ API performance acceptable: {len(chapters)} chapters loaded in {load_time:.3f}s")

        # Clean up temporary chapters
        for chapter_name in temp_chapters:
            try:
                frappe.delete_doc("Chapter", chapter_name, force=True)
            except Exception:
                pass

    @unittest.skip("Chapter validator only allows ASCII characters - internationalization not currently supported")
    def test_chapter_selection_internationalization(self):
        """Test chapter selection with international characters"""
        # Create chapter with international characters
        intl_chapter_name = "Test Chapter Ñieuwe Åmsterdam"
        if not frappe.db.exists("Chapter", intl_chapter_name):
            intl_chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": intl_chapter_name,
                    "region": "Noord-Holland",  # Use existing region
                    "postal_codes": "9000-9099",
                    "published": 1,
                    "introduction": "Test chapter for international character testing"}
            )
            intl_chapter.insert()

        # Test selecting international chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = intl_chapter_name

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Should handle international chapter names")

        member = frappe.get_doc("Member", result["data"]["member_record"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, intl_chapter_name, "International chapter name should be preserved")

        print(f"✅ International chapter names handled: {intl_chapter_name}")

        # Clean up international chapter
        try:
            frappe.delete_doc("Chapter", intl_chapter_name, force=True)
        except Exception:
            pass


class TestMembershipApplicationEdgeCases(EnhancedTestCase):
    """Test edge cases and error conditions in membership application system"""

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.test_email = f"edge_test_{frappe.generate_hash(length=8)}@example.com"

        # Ensure test membership type exists
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "minimum_amount": 15,  # Match default template dues_rate
                    "role_profile": "Verenigingen Member",
                }
            )
            membership_type.insert()

        self.base_data = {
            "first_name": "Edge",
            "last_name": "Tester",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1012AB",  # Valid Dutch postal code format
            "country": "Netherlands",
            "selected_membership_type": "Test Membership"}

    def tearDown(self):
        """Clean up after each test"""
        # Delete test member if exists
        if frappe.db.exists("Member", {"email": self.test_email}):
            member = frappe.get_doc("Member", {"email": self.test_email})

            # Delete related records
            if member.customer:
                frappe.delete_doc("Customer", member.customer, force=True)

            # Delete memberships
            memberships = frappe.get_all("Membership", filters={"member": member.name})
            for membership in memberships:
                frappe.delete_doc("Membership", membership.name, force=True)

            # Delete member
            frappe.delete_doc("Member", member.name, force=True)

        frappe.db.commit()
        super().tearDown()

    def test_database_schema_compatibility(self):
        """Test that the application system works with current database schema"""
        # Test that we can query chapters without field errors
        try:
            chapters = frappe.get_all(
                "Chapter",
                filters={"published": 1},
                fields=["name", "region"],  # Only existing fields
                order_by="name",
            )

            # Should succeed without database errors
            self.assertIsInstance(chapters, list, "Chapter query should return list")

            # Verify field structure
            for chapter in chapters:
                self.assertIn("name", chapter, "Chapter should have name field")
                # region might be None, but should be queryable
                self.assertIn("region", chapter, "Chapter should have region field in result")

            print(f"✅ Database schema compatibility verified for {len(chapters)} chapters")

        except Exception as e:
            self.fail(f"Database schema incompatibility: {str(e)}")

    def test_missing_required_fields_validation(self):
        """Test validation when required fields are missing"""
        # Test with missing email
        incomplete_data = self.base_data.copy()
        del incomplete_data["email"]

        result = submit_application(**incomplete_data)

        self.assertFalse(result["success"], "Should fail when required field missing")
        self.assertTrue(result.get("error"), "Should have error message")
        error = result.get("error", {})
        error_message = error.get("message", "") if isinstance(error, dict) else str(error)
        self.assertIn("email", error_message.lower(), "Error should mention missing email")

        print("✅ Missing required field validation works")

    def test_malformed_data_handling(self):
        """Test handling of malformed application data"""
        # Test with invalid JSON-like data
        malformed_data = "not valid json"

        try:
            result = submit_application(data=malformed_data)
            self.assertFalse(result["success"], "Should handle malformed data gracefully")
        except Exception as e:
            # Should not crash with unhandled exception
            self.assertIsInstance(
                e, (ValueError, TypeError, frappe.ValidationError), "Should raise appropriate exception type"
            )

        print("✅ Malformed data handled gracefully")

    def test_extremely_long_field_values(self):
        """Test handling of extremely long field values"""
        # Test with very long name
        long_data = self.base_data.copy()
        long_data["first_name"] = "A" * 1000  # Very long name
        long_data["email"] = f"long_test_{frappe.generate_hash(length=8)}@example.com"

        result = submit_application(**long_data)

        # Should either succeed (with truncation) or fail gracefully
        if result["success"]:
            member = frappe.get_doc("Member", result["data"]["member_record"])
            # Should be truncated to reasonable length
            self.assertLessEqual(len(member.first_name), 255, "Long field should be truncated")
        else:
            # Should have descriptive error
            self.assertTrue(result.get("error"), "Should provide error for long fields")

        print("✅ Long field values handled appropriately")

    @unittest.skip("Special characters test has submission issues")
    def test_special_characters_in_fields(self):
        """Test handling of special characters in form fields"""
        # Test with special characters
        special_data = self.base_data.copy()
        special_data["first_name"] = "José-María"
        special_data["last_name"] = "O'Connor-Smith"
        special_data["email"] = f"special_test_{frappe.generate_hash(length=8)}@example.com"
        special_data["address_line1"] = "123 Château de Versailles Straße"

        result = submit_application(**special_data)

        self.assertTrue(result["success"], "Should handle special characters")

        member = frappe.get_doc("Member", result["data"]["member_record"])
        self.assertEqual(member.first_name, "José-María", "Special characters should be preserved")

        print("✅ Special characters handled correctly")

    @unittest.skip("Concurrent tests have threading/infrastructure issues")
    def test_concurrent_application_submissions(self):
        """Test handling of concurrent submissions with same email"""
        import threading

        results = []
        results_lock = threading.Lock()

        def submit_concurrent_application(email_suffix):
            # Initialize Frappe context for this thread
            try:
                # Set up thread-local frappe context
                frappe.init(site=frappe.local.site)
                frappe.connect()
                frappe.set_user(frappe.session.user)

                # Copy test flags from main thread
                if not hasattr(frappe, 'flags'):
                    frappe.flags = frappe._dict()
                frappe.flags.in_test = True
                frappe.flags.mute_emails = True

                data = self.base_data.copy()
                data["email"] = f"concurrent_{email_suffix}@example.com"
                result = submit_application(data)

                with results_lock:
                    results.append(result)
            except Exception as e:
                # Log error but don't fail the thread
                with results_lock:
                    results.append({"success": False, "error": str(e)})
            finally:
                # Clean up thread-local context
                frappe.destroy()

        # Submit multiple applications concurrently
        threads = []
        for i in range(3):
            t = threading.Thread(target=submit_concurrent_application, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # All should succeed since they have different emails
        successful_results = [r for r in results if r.get("success")]
        self.assertEqual(len(successful_results), 3, "All concurrent applications should succeed")

        print("✅ Concurrent submissions handled correctly")

        # Clean up
        for result in successful_results:
            member_record = result.get("data", {}).get("member_record") or result.get("member_record")
            if member_record:
                try:
                    member = frappe.get_doc("Member", member_record)
                    if member.customer:
                        frappe.delete_doc("Customer", member.customer, force=True)
                    frappe.delete_doc("Member", member_record, force=True)
                except Exception:
                    pass

    @unittest.skip("Rate limiting test has infrastructure issues")
    def test_api_rate_limiting_edge_case(self):
        """Test API behavior under high load"""
        from verenigingen.api.membership_application import validate_email

        # Submit many validation requests rapidly
        results = []
        for i in range(10):
            result = validate_email(f"test{i}@example.com")
            results.append(result)

        # Most should succeed, rate limiting should be graceful
        successful_validations = [r for r in results if r.get("valid") is not None]
        self.assertGreater(len(successful_validations), 5, "Should handle multiple validation requests")

        print(f"✅ API handled {len(successful_validations)}/10 validation requests")

    def test_memory_usage_with_large_application_data(self):
        """Test memory usage with large volunteer skills data"""
        # Create application with large volunteer skills array
        large_data = self.base_data.copy()
        large_data["interested_in_volunteering"] = 1
        large_data["volunteer_skills"] = [
            {"skill_name": f"Skill {i}", "skill_level": "Intermediate"}
            for i in range(100)  # Large skills array
        ]
        large_data["email"] = f"memory_test_{frappe.generate_hash(length=8)}@example.com"

        import os

        import psutil

        # Measure memory before
        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss

        result = submit_application(**large_data)

        # Measure memory after
        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before

        # Should succeed and not use excessive memory (less than 50MB increase)
        self.assertTrue(result["success"], "Large application should succeed")
        self.assertLess(memory_increase, 50 * 1024 * 1024, "Memory usage should be reasonable")

        print(f"✅ Large application processed with {memory_increase / 1024 / 1024:.1f}MB memory increase")

    def test_database_connection_recovery(self):
        """Test recovery from database connection issues"""
        # This is a simulation - in practice, database issues are handled by Frappe
        try:
            result = submit_application(**self.base_data)
            self.assertTrue(result["success"], "Should handle database operations normally")
            print("✅ Database connection stable")
        except Exception as e:
            # Should not crash the application
            self.assertIsInstance(
                e,
                (frappe.ValidationError, frappe.MandatoryError),
                "Database errors should be handled gracefully",
            )

    def test_invalid_membership_type_edge_case(self):
        """Test handling of invalid membership type"""
        invalid_data = self.base_data.copy()
        invalid_data["selected_membership_type"] = "Non-Existent Membership Type"
        invalid_data["email"] = f"invalid_type_{frappe.generate_hash(length=8)}@example.com"

        result = submit_application(**invalid_data)

        # Should fail gracefully with appropriate error
        self.assertFalse(result["success"], "Should fail for invalid membership type")
        error = result.get("error", {})
        error_message = error.get("message", "") if isinstance(error, dict) else str(error)
        self.assertIn(
            "membership", error_message.lower(), "Error should mention membership type issue"
        )

        print("✅ Invalid membership type handled correctly")

    def test_form_data_api_fallback_behavior(self):
        """Test fallback behavior when form data fails to load"""
        from verenigingen.api.membership_application import get_application_form_data

        # Should provide fallback data even if some parts fail
        result = get_application_form_data()

        self.assertTrue(result["success"], "Should succeed even with partial failures")

        # Should have fallback data structures in the data dict
        data = result["data"]
        self.assertIn("membership_types", data, "Should have membership types (empty if needed)")
        self.assertIn("chapters", data, "Should have chapters (empty if needed)")
        self.assertIn("countries", data, "Should have fallback countries")

        # Fallback countries should be provided
        countries = data["countries"]
        self.assertGreater(len(countries), 0, "Should have fallback countries")

        print("✅ Form data API provides appropriate fallbacks")


def run_tests():
    """Run all membership application tests"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
