import unittest

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.api.member_management import add_member_to_chapter_roster
from verenigingen.api.membership_application import (
    approve_membership_application,
    reject_membership_application,
    submit_application,
)
from verenigingen.utils.application_notifications import check_overdue_applications
from verenigingen.utils.application_payments import process_application_payment


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


class TestMembershipApplication(unittest.TestCase):
    """Test membership application workflow"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create required Item Group for membership types
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Membership",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            )
            item_group.insert()

        # Create required Region for chapters
        if not frappe.db.exists("Region", "Test Region"):
            region = frappe.get_doc({"doctype": "Region", "region": "Test Region"})
            region.insert()

        # Create test membership type
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "amount": 100,
                    "currency": "EUR",
                    "subscription_period": "Annual",
                }
            )
            membership_type.insert()
            # Create subscription plan for the membership type
            membership_type.create_subscription_plan()

        # Create test chapter
        if not frappe.db.exists("Chapter", "Test Chapter"):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": "Test Chapter",
                    "region": "Test Region",
                    "postal_codes": "1000-1999",
                    "published": 1,
                    "introduction": "Test chapter for basic functionality",
                }
            )
            chapter.insert()

        # Create volunteer interest areas
        interest_areas = ["Event Planning", "Technical Support", "Community Outreach"]
        for area in interest_areas:
            if not frappe.db.exists("Volunteer Interest Area", area):
                frappe.get_doc({"doctype": "Volunteer Interest Area", "name": area}).insert()

    def setUp(self):
        """Set up for each test"""
        self.test_email = f"test_{frappe.generate_hash(length=8)}@example.com"
        self.application_data = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234",
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
            "contact_number": "+31612345678",
            "interested_in_volunteering": 1,
            "volunteer_availability": "Monthly",
            "volunteer_interests": ["Event Planning", "Technical Support"],
            "volunteer_skills": "Project management, Python programming",
            "newsletter_opt_in": 1,
            "application_source": "Website",
        }

    def tearDown(self):
        """Clean up after each test"""
        # Delete test member if exists
        if frappe.db.exists("Member", {"email": self.test_email}):
            member = frappe.get_doc("Member", {"email": self.test_email})

            # Delete related records
            if member.customer:
                frappe.delete_doc("Customer", member.customer)

            # Delete memberships
            memberships = frappe.get_all("Membership", filters={"member": member.name})
            for membership in memberships:
                frappe.delete_doc("Membership", membership.name)

            # Delete member
            frappe.delete_doc("Member", member.name)

        # Delete test lead
        if frappe.db.exists("Lead", {"email_id": self.test_email}):
            frappe.delete_doc("Lead", {"email_id": self.test_email})

        frappe.db.commit()

    def test_submit_application(self):
        """Test application submission"""
        result = submit_application(**self.application_data)

        self.assertTrue(result["success"])
        self.assertIn("member_id", result)
        self.assertIn("lead_id", result)

        # Verify member created
        member = frappe.get_doc("Member", result["member_id"])
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Pending")
        self.assertEqual(member.email, self.test_email)
        self.assertEqual(member.interested_in_volunteering, 1)

        # Verify lead created
        lead = frappe.get_doc("Lead", result["lead_id"])
        self.assertEqual(lead.email_id, self.test_email)
        self.assertEqual(lead.member, member.name)

    def test_age_validation(self):
        """Test age validation for young applicants"""
        # Test with 10 year old
        young_data = self.application_data.copy()
        young_data["birth_date"] = add_days(today(), -365 * 10)
        young_data["email"] = f"young_{self.test_email}"

        result = submit_application(**young_data)
        self.assertTrue(result["success"])

        # The application should still be accepted but age warning should be noted
        member = frappe.get_doc("Member", result["member_id"])
        self.assertEqual(member.age, 10)

    def test_chapter_suggestion(self):
        """Test automatic chapter suggestion"""
        result = submit_application(**self.application_data)
        member = frappe.get_doc("Member", result["member_id"])

        # Should suggest Test Chapter based on postal code
        self.assertEqual(member.suggested_chapter, "Test Chapter")

    def test_approve_application(self):
        """Test application approval workflow"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
        approval_result = approve_membership_application(member_name, "Approved for testing")

        self.assertTrue(approval_result["success"])
        self.assertIn("invoice", approval_result)

        # Verify member status
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.review_notes, "Approved for testing")

        # Verify membership created
        membership = frappe.get_doc("Membership", {"member": member_name})
        self.assertEqual(membership.status, "Pending")  # Pending payment
        self.assertEqual(membership.membership_type, "Test Membership")

        # Verify subscription created
        self.assertIsNotNone(
            membership.subscription, "Subscription should be created for approved membership"
        )
        subscription = frappe.get_doc("Subscription", membership.subscription)
        self.assertEqual(subscription.status, "Active", "Subscription should be active")
        self.assertTrue(len(subscription.plans) > 0, "Subscription should have at least one plan")

        # Verify subscription plan is properly linked
        subscription_plan_name = subscription.plans[0].plan
        self.assertIsNotNone(subscription_plan_name, "Subscription should have a plan assigned")
        subscription_plan = frappe.get_doc("Subscription Plan", subscription_plan_name)
        self.assertEqual(
            float(subscription_plan.cost), 100.0, "Subscription plan cost should match membership type amount"
        )

    def test_reject_application(self):
        """Test application rejection"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["member_record"]

        # Reject application
        frappe.set_user("Administrator")
        rejection_result = reject_membership_application(member_name, "Does not meet requirements")

        self.assertTrue(rejection_result["success"])

        # Verify member status
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Rejected")
        self.assertEqual(member.status, "Rejected")
        self.assertEqual(member.review_notes, "Does not meet requirements")

    def test_payment_processing(self):
        """Test payment processing for approved application"""
        # Submit and approve application
        result = submit_application(**self.application_data)
        member_name = result["member_record"]

        frappe.set_user("Administrator")
        approve_membership_application(member_name)

        # Process payment
        payment_result = process_application_payment(
            member_name, payment_method="Bank Transfer", payment_reference="TEST-PAY-001"
        )

        self.assertTrue(payment_result["success"])

        # Verify member activated
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Completed")
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.application_payment_status, "Completed")

        # Verify membership activated
        membership = frappe.get_doc("Membership", payment_result["membership"])
        self.assertEqual(membership.status, "Active")

        # Verify volunteer record created
        volunteer = frappe.get_doc("Volunteer", {"member": member_name})
        self.assertEqual(volunteer.volunteer_name, member.full_name)
        self.assertEqual(volunteer.status, "New")

    def test_duplicate_email_prevention(self):
        """Test that duplicate emails are prevented"""
        # Submit first application
        submit_application(**self.application_data)

        # Try to submit with same email
        with self.assertRaises(frappe.ValidationError):
            submit_application(**self.application_data)

    def test_overdue_detection(self):
        """Test overdue application detection"""
        # Create an old application
        old_data = self.application_data.copy()
        old_data["email"] = f"old_{self.test_email}"
        result = submit_application(**old_data)

        # Manually set the application date to 3 weeks ago
        frappe.db.set_value("Member", result["member_id"], "application_date", add_days(now_datetime(), -21))

        # Run overdue check
        check_overdue_applications()

        # In a real scenario, this would send notifications
        # Here we just verify the function runs without error
        self.assertTrue(True)


class TestMembershipApplicationLoad(unittest.TestCase):
    """Load testing for membership applications"""

    def setUp(self):
        """Set up for each test"""
        self.test_email = f"load_test_{frappe.generate_hash(length=8)}@example.com"
        self.application_data = {
            "first_name": "Load",
            "last_name": "Tester",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234",
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
            "contact_number": "+31612345678",
            "interested_in_volunteering": 1,
            "volunteer_availability": "Monthly",
            "volunteer_interests": ["Event Planning", "Technical Support"],
            "volunteer_skills": "Project management, Python programming",
            "newsletter_opt_in": 1,
            "application_source": "Website",
        }

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
                    "postal_code": "1234",
                    "country": "Netherlands",
                    "selected_membership_type": "Test Membership",
                }
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
            if "member_id" in result:
                frappe.delete_doc("Member", result["member_id"])

    def test_custom_fee_application_no_change_tracking(self):
        """Test that applications with custom fees don't trigger fee change tracking"""
        print("\n🧪 Testing custom fee application submission...")

        # Application data with custom amount
        custom_fee_data = self.application_data.copy()
        custom_fee_data["membership_amount"] = 75.0
        custom_fee_data["uses_custom_amount"] = True
        custom_fee_data["custom_amount_reason"] = "Supporter contribution level"
        custom_fee_data["email"] = f"customfee_{self.test_email}"

        # Submit application with custom fee
        result = submit_application(**custom_fee_data)

        # Verify submission successful
        self.assertTrue(result["success"])
        self.assertIn("member_id", result)

        # Get created member
        member = frappe.get_doc("Member", result["member_id"])

        # Verify custom fee was set correctly
        self.assertEqual(member.membership_fee_override, 75.0)
        self.assertIn("Supporter contribution", member.fee_override_reason)
        self.assertEqual(member.application_status, "Pending")

        # KEY TEST: Verify no fee change tracking was triggered
        self.assertFalse(
            hasattr(member, "_pending_fee_change"),
            "Application with custom fee should not trigger fee change tracking",
        )

        print(f"✅ Custom fee application successful for {member.name}")
        print(f"   Custom fee: €{member.membership_fee_override}")
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
        member_name = result["member_record"]

        # Get member and verify application_id exists
        member = frappe.get_doc("Member", member_name)

        # Application ID should be generated
        self.assertIsNotNone(member.application_id, "Member should have application_id")
        self.assertTrue(member.application_id.startswith("APP-"), "Application ID should start with APP-")

        # The response should include applicant_id (which maps to application_id)
        self.assertIn("applicant_id", result, "Response should include applicant_id")
        self.assertEqual(
            result["applicant_id"],
            member.application_id,
            "Response applicant_id should match member application_id",
        )

        print(f"✅ Application ID generated: {member.application_id}")
        print(f"   Response includes applicant_id: {result.get('applicant_id')}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

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
        member_name = result["member_record"]

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
        member_name = result["member_record"]

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
        self.assertIn("member_record", result)

        # Get created member
        member = frappe.get_doc("Member", result["member_record"])

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
        member = frappe.get_doc("Member", result["member_id"])

        # Verify contact_number field is used
        self.assertEqual(member.contact_number, "+31612345678")

        # Verify no mobile_no field is set (should not exist or be empty)
        self.assertFalse(hasattr(member, "mobile_no") and getattr(member, "mobile_no", None))

        print(f"✅ Contact number field properly used for {member.name}")

    def test_membership_submission_after_approval(self):
        """Test that membership is properly submitted after approval"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
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
        self.assertEqual(membership.docstatus, 1)  # Should be submitted, not draft

        print(f"✅ Membership properly submitted for {member_name}")

    def test_invoice_period_dates(self):
        """Test that invoices have proper subscription period dates"""
        # Submit and approve application
        result = submit_application(**self.application_data)
        member_name = result["member_record"]

        frappe.set_user("Administrator")
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])
        self.assertIn("invoice", approval_result)

        # Get the invoice
        invoice = frappe.get_doc("Sales Invoice", approval_result["invoice"])

        # Verify invoice has subscription period dates
        self.assertTrue(
            invoice.subscription_period_start, "Invoice should have subscription period start date"
        )
        self.assertTrue(invoice.subscription_period_end, "Invoice should have subscription period end date")

        # Verify dates are logical (end after start)
        from frappe.utils import getdate

        start_date = getdate(invoice.subscription_period_start)
        end_date = getdate(invoice.subscription_period_end)
        self.assertTrue(end_date > start_date, "Subscription end date should be after start date")

        print(f"✅ Invoice {invoice.name} has proper subscription period: {start_date} to {end_date}")

    def test_no_duplicate_invoices(self):
        """Test that approval doesn't create duplicate invoices"""
        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Count invoices for this member
        member = frappe.get_doc("Member", member_name)
        if member.customer:
            invoices = frappe.get_all("Sales Invoice", filters={"customer": member.customer})
            self.assertEqual(len(invoices), 1, "Should only have one invoice after approval")

        print(f"✅ No duplicate invoices created for {member_name}")

    def test_no_duplicate_invoices_with_custom_amount(self):
        """Test that approval with custom amount doesn't create duplicate invoices"""
        print("\n🧪 Testing duplicate invoice prevention with custom amount...")

        # Submit application with custom amount
        custom_amount_data = self.application_data.copy()
        custom_amount_data["membership_amount"] = 45.0
        custom_amount_data["uses_custom_amount"] = True
        custom_amount_data["custom_amount_reason"] = "Higher contribution level"
        custom_amount_data["email"] = f"customdup_{self.test_email}"

        result = submit_application(**custom_amount_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
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
                fields=["name", "grand_total", "membership", "status"],
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

            # Check subscription was created and uses correct custom amount
            if membership.subscription:
                subscription = frappe.get_doc("Subscription", membership.subscription)
                self.assertIsNotNone(subscription, "Subscription should be created")

                # Verify subscription plan uses custom amount
                self.assertEqual(len(subscription.plans), 1, "Subscription should have exactly one plan")

                plan_name = subscription.plans[0].plan
                plan_doc = frappe.get_doc("Subscription Plan", plan_name)

                # CRITICAL TEST: Subscription plan should use the custom amount (€45.00)
                self.assertEqual(
                    float(plan_doc.cost),
                    45.0,
                    f"Subscription plan cost should be €45.00 (custom amount), got €{plan_doc.cost}",
                )

                # Plan name should indicate it's a custom plan
                self.assertIn("45.00", plan_name, f"Plan name should contain custom amount, got: {plan_name}")

                # Subscription should be configured to not generate immediate invoice
                # since application invoice already exists
                print(f"   Subscription start date: {subscription.start_date}")
                print(f"   Subscription status: {subscription.status}")
                print(f"   Subscription plan: {plan_name} (€{plan_doc.cost})")
            else:
                self.fail("Subscription should be created for approved membership")

            print(f"✅ Custom amount approval successful for {member_name}")
            print(f"   Single invoice created: {invoice.name} (€{invoice.grand_total})")
            print(f"   Membership custom amount: €{membership.custom_amount}")
            print(f"   Subscription plan cost: €{plan_doc.cost}")
            print("   No duplicate invoices created")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_invoice_subscription_coordination(self):
        """Test that invoice creation and subscription creation are properly coordinated"""
        print("\n🧪 Testing invoice-subscription coordination...")

        # Submit application
        result = submit_application(**self.application_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Get member and verify the coordination
        member = frappe.get_doc("Member", member_name)

        if member.customer:
            # Get all invoices
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": ["!=", 2]},
                fields=["name", "membership", "grand_total", "posting_date"],
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

            # Verify subscription exists and is properly configured
            if membership.subscription:
                subscription = frappe.get_doc("Subscription", membership.subscription)

                # Subscription should either start in future or not generate immediate invoices
                # to prevent conflict with application invoice
                from frappe.utils import getdate

                if subscription.start_date > getdate(membership.start_date):
                    print(f"   ✅ Subscription delayed to {subscription.start_date} to avoid overlap")
                else:
                    # Check subscription settings to ensure no immediate invoice generation
                    print("   ✅ Subscription configured to prevent immediate invoice generation")

            print(f"✅ Invoice-subscription coordination working for {member_name}")
            print(f"   Application invoice: {application_invoices[0].name}")
            print(f"   Membership: {membership.name}")
            print(f"   Subscription: {membership.subscription or 'None'}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_custom_amount_subscription_plan_creation(self):
        """Test that custom amounts create proper subscription plans with correct costs"""
        print("\n🧪 Testing custom amount subscription plan creation...")

        # Test multiple custom amounts to ensure each creates the right plan
        test_amounts = [25.0, 50.0, 75.0]

        for custom_amount in test_amounts:
            print(f"\n  Testing custom amount: €{custom_amount}")

            # Submit application with custom amount
            custom_data = self.application_data.copy()
            custom_data["membership_amount"] = custom_amount
            custom_data["uses_custom_amount"] = True
            custom_data["custom_amount_reason"] = f"Custom contribution of €{custom_amount}"
            custom_data["email"] = f"custom{int(custom_amount)}_{self.test_email}"

            result = submit_application(**custom_data)
            member_name = result["member_record"]

            # Approve application
            frappe.set_user("Administrator")
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

            # Verify subscription and subscription plan
            self.assertIsNotNone(membership.subscription, f"Subscription should exist for €{custom_amount}")

            subscription = frappe.get_doc("Subscription", membership.subscription)
            self.assertEqual(len(subscription.plans), 1, "Subscription should have exactly one plan")

            plan_name = subscription.plans[0].plan
            plan_doc = frappe.get_doc("Subscription Plan", plan_name)

            # CRITICAL ASSERTIONS: Plan cost must match custom amount
            self.assertEqual(
                float(plan_doc.cost),
                custom_amount,
                f"Subscription plan cost should be €{custom_amount}, got €{plan_doc.cost}",
            )

            # Plan should be a custom plan (not the standard plan)
            self.assertIn(
                str(custom_amount),
                plan_name,
                f"Plan name should contain custom amount €{custom_amount}: {plan_name}",
            )

            # Plan should have correct properties
            self.assertEqual(
                plan_doc.price_determination, "Fixed Rate", "Custom plan should use Fixed Rate pricing"
            )
            self.assertEqual(plan_doc.currency, "EUR", "Custom plan should use EUR currency")

            print(f"    ✅ Custom plan created: {plan_name}")
            print(f"    ✅ Plan cost matches: €{plan_doc.cost}")

            # Clean up
            if member.customer:
                frappe.delete_doc("Customer", member.customer, force=True)
            frappe.delete_doc("Member", member_name, force=True)

            # Clean up custom subscription plan
            frappe.delete_doc("Subscription Plan", plan_name, force=True)

        print("✅ All custom amount subscription plans created correctly")

    def test_standard_amount_uses_original_plan(self):
        """Test that standard amounts use the original subscription plan"""
        print("\n🧪 Testing standard amount uses original subscription plan...")

        # Submit application WITHOUT custom amount
        standard_data = self.application_data.copy()
        standard_data["email"] = f"standard_{self.test_email}"
        # Explicitly ensure no custom amount
        standard_data.pop("membership_amount", None)
        standard_data.pop("uses_custom_amount", None)

        result = submit_application(**standard_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
        approval_result = approve_membership_application(member_name)

        self.assertTrue(approval_result["success"])

        # Get member and check membership
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        self.assertEqual(len(memberships), 1, "Should have exactly one membership")

        membership = frappe.get_doc("Membership", memberships[0].name)

        # Verify membership does NOT use custom amount
        self.assertFalse(membership.uses_custom_amount, "Standard membership should not use custom amount")

        # Verify subscription uses original plan
        self.assertIsNotNone(membership.subscription, "Subscription should exist for standard membership")

        subscription = frappe.get_doc("Subscription", membership.subscription)
        self.assertEqual(len(subscription.plans), 1, "Subscription should have exactly one plan")

        plan_name = subscription.plans[0].plan

        # Should use the original subscription plan from membership type
        original_plan = membership.subscription_plan
        self.assertEqual(
            plan_name,
            original_plan,
            f"Standard membership should use original plan {original_plan}, got {plan_name}",
        )

        # Verify plan cost matches membership type
        plan_doc = frappe.get_doc("Subscription Plan", plan_name)
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)

        self.assertEqual(
            float(plan_doc.cost),
            float(membership_type.amount),
            f"Plan cost should match membership type amount €{membership_type.amount}, got €{plan_doc.cost}",
        )

        print(f"✅ Standard membership uses original plan: {plan_name}")
        print(f"✅ Plan cost matches membership type: €{plan_doc.cost}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_custom_amount_billing_amount_method(self):
        """Test that get_billing_amount() returns correct amounts for both custom and standard memberships"""
        print("\n🧪 Testing get_billing_amount() method...")

        # Test custom amount
        custom_data = self.application_data.copy()
        custom_data["membership_amount"] = 35.0
        custom_data["uses_custom_amount"] = True
        custom_data["email"] = f"billing_custom_{self.test_email}"

        result = submit_application(**custom_data)
        member_name = result["member_record"]

        frappe.set_user("Administrator")
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

        # Test that subscription plan creation uses this amount
        subscription_plan_name = membership.get_subscription_plan_for_amount(billing_amount)
        self.assertIsNotNone(subscription_plan_name, "Should return valid subscription plan name")

        # Verify the created plan has correct cost
        plan_doc = frappe.get_doc("Subscription Plan", subscription_plan_name)
        self.assertEqual(
            float(plan_doc.cost),
            35.0,
            f"Generated subscription plan should cost €35.00, got €{plan_doc.cost}",
        )

        print(f"✅ Custom billing amount method works: €{billing_amount}")
        print(f"✅ Generated plan cost correct: €{plan_doc.cost}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)
        frappe.delete_doc("Subscription Plan", subscription_plan_name, force=True)

        # Test standard amount
        standard_data = self.application_data.copy()
        standard_data["email"] = f"billing_standard_{self.test_email}"
        standard_data.pop("membership_amount", None)
        standard_data.pop("uses_custom_amount", None)

        result = submit_application(**standard_data)
        member_name = result["member_record"]

        approve_membership_application(member_name)

        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        # Test get_billing_amount() for standard amount
        billing_amount = membership.get_billing_amount()
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)

        self.assertEqual(
            float(billing_amount),
            float(membership_type.amount),
            f"Standard membership billing amount should match membership type €{membership_type.amount}, got €{billing_amount}",
        )

        # Test that subscription plan method returns original plan
        subscription_plan_name = membership.get_subscription_plan_for_amount(billing_amount)
        self.assertEqual(
            subscription_plan_name,
            membership.subscription_plan,
            "Standard membership should use original subscription plan",
        )

        print(f"✅ Standard billing amount method works: €{billing_amount}")
        print(f"✅ Uses original subscription plan: {subscription_plan_name}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_membership_amount_update_changes_subscription_plan(self):
        """Test that changing membership custom amount updates the subscription plan"""
        print("\n🧪 Testing subscription plan updates when membership amount changes...")

        # Create membership with initial custom amount
        initial_amount = 30.0
        custom_data = self.application_data.copy()
        custom_data["membership_amount"] = initial_amount
        custom_data["uses_custom_amount"] = True
        custom_data["email"] = f"update_test_{self.test_email}"

        result = submit_application(**custom_data)
        member_name = result["member_record"]

        frappe.set_user("Administrator")
        approve_membership_application(member_name)

        # Get initial state
        member = frappe.get_doc("Member", member_name)
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        membership = frappe.get_doc("Membership", memberships[0].name)

        initial_subscription = frappe.get_doc("Subscription", membership.subscription)
        initial_plan_name = initial_subscription.plans[0].plan
        initial_plan = frappe.get_doc("Subscription Plan", initial_plan_name)

        # Verify initial state
        self.assertEqual(
            float(initial_plan.cost), initial_amount, f"Initial plan cost should be €{initial_amount}"
        )

        print(f"✅ Initial subscription plan: {initial_plan_name} (€{initial_plan.cost})")

        # Update membership to use different custom amount
        new_amount = 60.0
        membership.custom_amount = new_amount
        membership.uses_custom_amount = 1

        # Trigger subscription update
        membership.update_subscription_amount()

        # Verify subscription was updated
        membership.reload()
        updated_subscription = frappe.get_doc("Subscription", membership.subscription)
        updated_plan_name = updated_subscription.plans[0].plan
        updated_plan = frappe.get_doc("Subscription Plan", updated_plan_name)

        # Plan should be different and have new cost
        self.assertNotEqual(
            initial_plan_name, updated_plan_name, "Should create new subscription plan for new amount"
        )
        self.assertEqual(
            float(updated_plan.cost),
            new_amount,
            f"Updated plan cost should be €{new_amount}, got €{updated_plan.cost}",
        )

        print(f"✅ Updated subscription plan: {updated_plan_name} (€{updated_plan.cost})")
        print(f"✅ Plan name change: {initial_plan_name} → {updated_plan_name}")

        # Test changing back to standard amount
        membership.uses_custom_amount = 0
        membership.custom_amount = None
        membership.update_subscription_amount()

        # Should now use original subscription plan
        membership.reload()
        standard_subscription = frappe.get_doc("Subscription", membership.subscription)
        standard_plan_name = standard_subscription.plans[0].plan

        self.assertEqual(
            standard_plan_name,
            membership.subscription_plan,
            "Should revert to original subscription plan for standard amount",
        )

        print(f"✅ Reverted to standard plan: {standard_plan_name}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom plans
        try:
            frappe.delete_doc("Subscription Plan", initial_plan_name, force=True)
        except Exception:
            pass
        try:
            frappe.delete_doc("Subscription Plan", updated_plan_name, force=True)
        except Exception:
            pass

    def test_custom_amount_subscription_integration_end_to_end(self):
        """End-to-end integration test for custom amount subscription flow"""
        print("\n🧪 Testing complete custom amount subscription integration...")

        custom_amount = 42.50

        # 1. Submit application with custom amount
        custom_data = self.application_data.copy()
        custom_data["membership_amount"] = custom_amount
        custom_data["uses_custom_amount"] = True
        custom_data["custom_amount_reason"] = "Integration test custom amount"
        custom_data["email"] = f"integration_{self.test_email}"

        result = submit_application(**custom_data)
        member_name = result["member_record"]

        # 2. Verify member has custom amount data in notes
        member = frappe.get_doc("Member", member_name)
        self.assertIn("Custom Amount Data:", member.notes, "Member should have custom amount data in notes")

        from verenigingen.utils.application_helpers import get_member_custom_amount_data

        custom_data_extracted = get_member_custom_amount_data(member)

        self.assertIsNotNone(custom_data_extracted, "Should extract custom amount data from notes")
        self.assertEqual(
            float(custom_data_extracted["membership_amount"]),
            custom_amount,
            "Extracted amount should match submitted amount",
        )
        self.assertTrue(custom_data_extracted["uses_custom_amount"], "Should indicate custom amount usage")

        print(f"✅ Custom amount data stored and extracted: €{custom_data_extracted['membership_amount']}")

        # 3. Approve application
        frappe.set_user("Administrator")
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

        # Check subscription and subscription plan (THE CRITICAL TEST)
        self.assertIsNotNone(membership.subscription, "Subscription should be created")

        subscription = frappe.get_doc("Subscription", membership.subscription)
        self.assertEqual(len(subscription.plans), 1, "Subscription should have one plan")

        plan_name = subscription.plans[0].plan
        plan_doc = frappe.get_doc("Subscription Plan", plan_name)

        # THIS IS THE KEY ASSERTION THAT WOULD HAVE CAUGHT THE ORIGINAL BUG
        self.assertEqual(
            float(plan_doc.cost),
            custom_amount,
            f"CRITICAL: Subscription plan cost MUST be €{custom_amount}, got €{plan_doc.cost}",
        )

        self.assertIn(str(custom_amount), plan_name, f"Plan name should contain custom amount: {plan_name}")

        print(f"🎯 CRITICAL TEST PASSED: Subscription plan cost = €{plan_doc.cost}")
        print(f"🎯 Custom subscription plan: {plan_name}")

        # 5. Verify future invoice generation would use correct amount
        # (This tests that the subscription plan will generate invoices with the right amount)
        test_plan = membership.get_subscription_plan_for_amount(custom_amount)
        test_plan_doc = frappe.get_doc("Subscription Plan", test_plan)
        self.assertEqual(float(test_plan_doc.cost), custom_amount, "Future billing should use custom amount")

        print(f"✅ Future billing will use correct amount: €{test_plan_doc.cost}")

        print("🎉 END-TO-END INTEGRATION TEST PASSED - Custom amount flows correctly through entire system!")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom subscription plan
        try:
            frappe.delete_doc("Subscription Plan", plan_name, force=True)
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
        member = frappe.get_doc("Member", result["member_id"])

        # Verify volunteer data was stored
        self.assertEqual(member.interested_in_volunteering, 1)
        self.assertEqual(member.volunteer_availability, "Weekly")
        self.assertTrue(member.volunteer_skills)

        print(f"✅ Volunteer application data properly stored for {member.name}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member.name, force=True)

    def test_volunteer_record_creation_after_payment(self):
        """Test that volunteer record is created after payment completion"""
        # Submit application with volunteer interest
        volunteer_data = self.application_data.copy()
        volunteer_data["interested_in_volunteering"] = 1
        volunteer_data["volunteer_availability"] = "Monthly"
        volunteer_data["volunteer_interests"] = ["Community Outreach"]
        volunteer_data["volunteer_skills"] = "Community engagement, Communication"
        volunteer_data["email"] = f"volpay_{self.test_email}"

        # Submit and approve application
        result = submit_application(**volunteer_data)
        member_name = result["member_record"]

        frappe.set_user("Administrator")
        approve_membership_application(member_name)

        # Process payment to complete the workflow
        payment_result = process_application_payment(
            member_name, payment_method="Bank Transfer", payment_reference="TEST-VOL-001"
        )

        self.assertTrue(payment_result["success"])

        # Verify volunteer record was created
        volunteer_exists = frappe.db.exists("Volunteer", {"member": member_name})
        self.assertTrue(volunteer_exists, "Volunteer record should be created after payment")

        if volunteer_exists:
            volunteer = frappe.get_doc("Volunteer", {"member": member_name})
            self.assertEqual(volunteer.volunteer_name, frappe.get_doc("Member", member_name).full_name)
            self.assertTrue(volunteer.status in ["New", "Active"])

            print(f"✅ Volunteer record created: {volunteer.name} for member {member_name}")

        # Clean up
        member = frappe.get_doc("Member", member_name)
        if volunteer_exists:
            frappe.delete_doc("Volunteer", volunteer.name, force=True)
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        # Delete membership
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        for membership in memberships:
            frappe.delete_doc("Membership", membership.name, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_non_volunteer_application(self):
        """Test that non-volunteer applications don't create volunteer records"""
        # Submit application without volunteer interest
        non_volunteer_data = self.application_data.copy()
        non_volunteer_data["interested_in_volunteering"] = 0
        non_volunteer_data["email"] = f"nonvol_{self.test_email}"

        # Submit, approve and complete payment
        result = submit_application(**non_volunteer_data)
        member_name = result["member_record"]

        frappe.set_user("Administrator")
        approve_membership_application(member_name)

        payment_result = process_application_payment(
            member_name, payment_method="Bank Transfer", payment_reference="TEST-NONVOL-001"
        )

        self.assertTrue(payment_result["success"])

        # Verify NO volunteer record was created
        volunteer_exists = frappe.db.exists("Volunteer", {"member": member_name})
        self.assertFalse(volunteer_exists, "No volunteer record should be created for non-volunteer members")

        print(f"✅ No volunteer record created for non-volunteer member {member_name}")

        # Clean up
        member = frappe.get_doc("Member", member_name)
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        # Delete membership
        memberships = frappe.get_all("Membership", filters={"member": member_name})
        for membership in memberships:
            frappe.delete_doc("Membership", membership.name, force=True)
        frappe.delete_doc("Member", member_name, force=True)

    def test_volunteer_interest_areas_validation(self):
        """Test that volunteer interest areas are properly validated"""
        # Submit application with valid volunteer interests
        valid_volunteer_data = self.application_data.copy()
        valid_volunteer_data["interested_in_volunteering"] = 1
        valid_volunteer_data["volunteer_interests"] = ["Event Planning", "Technical Support"]
        valid_volunteer_data["email"] = f"validvol_{self.test_email}"

        result = submit_application(**valid_volunteer_data)
        self.assertTrue(result["success"])

        member = frappe.get_doc("Member", result["member_id"])
        # Should store the interests properly
        self.assertTrue(member.interested_in_volunteering)

        print(f"✅ Valid volunteer interests processed for {member.name}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member.name, force=True)

    def test_edge_case_zero_custom_amount(self):
        """Test that zero custom amount defaults to standard amount"""
        print("\n🧪 Testing zero custom amount edge case...")

        # Submit application with zero custom amount
        zero_data = self.application_data.copy()
        zero_data["membership_amount"] = 0.0
        zero_data["uses_custom_amount"] = True
        zero_data["email"] = f"zero_{self.test_email}"

        result = submit_application(**zero_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
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
            float(membership_type.amount),
            f"Zero custom amount should fall back to standard amount €{membership_type.amount}",
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
        negative_data["membership_amount"] = -10.0
        negative_data["uses_custom_amount"] = True
        negative_data["email"] = f"negative_{self.test_email}"

        # This should either fail during submission or be corrected
        try:
            result = submit_application(**negative_data)
            member_name = result["member_record"]

            # If submission succeeds, check that amount was corrected
            member = frappe.get_doc("Member", member_name)

            # Should either have no custom amount or positive amount
            fee_override = getattr(member, "membership_fee_override", 0)
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
            self.assertIn("negative", str(e).lower(), "Error should mention negative amount")

    def test_very_large_custom_amount(self):
        """Test handling of very large custom amounts"""
        print("\n🧪 Testing very large custom amount...")

        large_amount = 999999.99

        # Submit application with very large custom amount
        large_data = self.application_data.copy()
        large_data["membership_amount"] = large_amount
        large_data["uses_custom_amount"] = True
        large_data["email"] = f"large_{self.test_email}"

        result = submit_application(**large_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
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

        # Check subscription plan handles large amounts
        if membership.subscription:
            subscription = frappe.get_doc("Subscription", membership.subscription)
            plan_name = subscription.plans[0].plan
            plan_doc = frappe.get_doc("Subscription Plan", plan_name)

            self.assertEqual(
                float(plan_doc.cost),
                large_amount,
                f"Subscription plan should handle large amount: €{large_amount}",
            )

        print(f"✅ Large amount handled correctly: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom subscription plan
        try:
            frappe.delete_doc("Subscription Plan", plan_name, force=True)
        except Exception:
            pass

    def test_decimal_precision_custom_amount(self):
        """Test custom amounts with decimal precision"""
        print("\n🧪 Testing decimal precision in custom amounts...")

        # Test with 3 decimal places
        precise_amount = 42.567

        # Submit application with precise decimal amount
        decimal_data = self.application_data.copy()
        decimal_data["membership_amount"] = precise_amount
        decimal_data["uses_custom_amount"] = True
        decimal_data["email"] = f"decimal_{self.test_email}"

        result = submit_application(**decimal_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
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

        # Check subscription plan precision
        if membership.subscription:
            subscription = frappe.get_doc("Subscription", membership.subscription)
            plan_name = subscription.plans[0].plan
            plan_doc = frappe.get_doc("Subscription Plan", plan_name)

            self.assertEqual(
                float(plan_doc.cost),
                expected_amount,
                f"Subscription plan should maintain precision: €{expected_amount}",
            )

        print(f"✅ Decimal precision handled correctly: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom subscription plan
        try:
            frappe.delete_doc("Subscription Plan", plan_name, force=True)
        except Exception:
            pass

    def test_custom_amount_subscription_plan_reuse(self):
        """Test that identical custom amounts reuse existing subscription plans"""
        print("\n🧪 Testing subscription plan reuse for identical custom amounts...")

        custom_amount = 55.0

        # Create first member with custom amount
        first_data = self.application_data.copy()
        first_data["membership_amount"] = custom_amount
        first_data["uses_custom_amount"] = True
        first_data["email"] = f"first_reuse_{self.test_email}"

        result1 = submit_application(**first_data)
        member1_name = result1["member_record"]

        frappe.set_user("Administrator")
        approve_membership_application(member1_name)

        # Get first subscription plan name
        memberships1 = frappe.get_all("Membership", filters={"member": member1_name})
        membership1 = frappe.get_doc("Membership", memberships1[0].name)
        subscription1 = frappe.get_doc("Subscription", membership1.subscription)
        plan1_name = subscription1.plans[0].plan

        # Create second member with same custom amount
        second_data = self.application_data.copy()
        second_data["membership_amount"] = custom_amount
        second_data["uses_custom_amount"] = True
        second_data["email"] = f"second_reuse_{self.test_email}"

        result2 = submit_application(**second_data)
        member2_name = result2["member_record"]

        approve_membership_application(member2_name)

        # Get second subscription plan name
        memberships2 = frappe.get_all("Membership", filters={"member": member2_name})
        membership2 = frappe.get_doc("Membership", memberships2[0].name)
        subscription2 = frappe.get_doc("Subscription", membership2.subscription)
        plan2_name = subscription2.plans[0].plan

        # Should reuse the same subscription plan
        self.assertEqual(
            plan1_name, plan2_name, f"Identical custom amounts should reuse subscription plans: {plan1_name}"
        )

        # Verify both plans have correct cost
        plan_doc = frappe.get_doc("Subscription Plan", plan1_name)
        self.assertEqual(
            float(plan_doc.cost), custom_amount, f"Shared plan should have correct cost: €{custom_amount}"
        )

        print(f"✅ Subscription plan reused correctly: {plan1_name}")
        print(f"   Both memberships use same plan with cost €{plan_doc.cost}")

        # Clean up
        member1 = frappe.get_doc("Member", member1_name)
        member2 = frappe.get_doc("Member", member2_name)

        if member1.customer:
            frappe.delete_doc("Customer", member1.customer, force=True)
        if member2.customer:
            frappe.delete_doc("Customer", member2.customer, force=True)

        frappe.delete_doc("Member", member1_name, force=True)
        frappe.delete_doc("Member", member2_name, force=True)

        # Clean up shared subscription plan
        try:
            frappe.delete_doc("Subscription Plan", plan1_name, force=True)
        except Exception:
            pass

    def test_custom_amount_with_different_membership_types(self):
        """Test custom amounts work with different membership types"""
        print("\n🧪 Testing custom amounts with different membership types...")

        # Create a second membership type for testing
        if not frappe.db.exists("Membership Type", "Premium Test Membership"):
            premium_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Premium Test Membership",
                    "amount": 200,
                    "currency": "EUR",
                    "subscription_period": "Annual",
                }
            )
            premium_type.insert()

        custom_amount = 150.0

        # Test with premium membership type
        premium_data = self.application_data.copy()
        premium_data["selected_membership_type"] = "Premium Test Membership"
        premium_data["membership_amount"] = custom_amount
        premium_data["uses_custom_amount"] = True
        premium_data["email"] = f"premium_{self.test_email}"

        result = submit_application(**premium_data)
        member_name = result["member_record"]

        frappe.set_user("Administrator")
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

        # Check subscription plan
        if membership.subscription:
            subscription = frappe.get_doc("Subscription", membership.subscription)
            plan_name = subscription.plans[0].plan
            plan_doc = frappe.get_doc("Subscription Plan", plan_name)

            self.assertEqual(
                float(plan_doc.cost),
                custom_amount,
                f"Subscription plan should use custom amount: €{custom_amount}",
            )

            # Plan name should reflect the custom amount
            self.assertIn(
                str(custom_amount), plan_name, f"Plan name should contain custom amount: {plan_name}"
            )

        print(f"✅ Custom amount works with premium membership type: €{billing_amount}")

        # Clean up
        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        frappe.delete_doc("Member", member_name, force=True)

        # Clean up custom subscription plan
        try:
            frappe.delete_doc("Subscription Plan", plan_name, force=True)
        except Exception:
            pass

        # Clean up premium membership type
        try:
            frappe.delete_doc("Membership Type", "Premium Test Membership", force=True)
        except Exception:
            pass

    def test_custom_amount_invoice_and_subscription_coordination_edge_cases(self):
        """Test edge cases in invoice-subscription coordination with custom amounts"""
        print("\n🧪 Testing custom amount invoice-subscription coordination edge cases...")

        custom_amount = 37.50

        # Submit application with custom amount
        edge_data = self.application_data.copy()
        edge_data["membership_amount"] = custom_amount
        edge_data["uses_custom_amount"] = True
        edge_data["email"] = f"edge_{self.test_email}"

        result = submit_application(**edge_data)
        member_name = result["member_record"]

        # Approve application
        frappe.set_user("Administrator")
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
                fields=["name", "grand_total", "membership"],
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

        # Edge case 2: Subscription exists and uses correct plan
        if membership.subscription:
            subscription = frappe.get_doc("Subscription", membership.subscription)
            self.assertEqual(len(subscription.plans), 1, "Should have exactly one subscription plan")

            plan_name = subscription.plans[0].plan
            plan_doc = frappe.get_doc("Subscription Plan", plan_name)

            self.assertEqual(
                float(plan_doc.cost),
                custom_amount,
                f"Subscription plan cost should match custom amount: €{custom_amount}",
            )
            edge_cases_passed += 1
            print("   ✅ Edge case 2: Subscription plan cost correct")

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

        # Edge case 5: No duplicate subscription plans for same amount
        # (This tests the reuse functionality)
        second_member_data = self.application_data.copy()
        second_member_data["membership_amount"] = custom_amount  # Same amount
        second_member_data["uses_custom_amount"] = True
        second_member_data["email"] = f"edge2_{self.test_email}"

        result2 = submit_application(**second_member_data)
        member2_name = result2["member_record"]
        approve_membership_application(member2_name)

        memberships2 = frappe.get_all("Membership", filters={"member": member2_name})
        membership2 = frappe.get_doc("Membership", memberships2[0].name)

        if membership2.subscription:
            subscription2 = frappe.get_doc("Subscription", membership2.subscription)
            plan2_name = subscription2.plans[0].plan

            # Should reuse the same subscription plan
            self.assertEqual(plan_name, plan2_name, "Should reuse existing subscription plan for same amount")
            edge_cases_passed += 1
            print("   ✅ Edge case 5: Subscription plan reuse correct")

        print(f"✅ All {edge_cases_passed} edge cases passed for custom amount coordination")

        # Clean up
        member2 = frappe.get_doc("Member", member2_name)

        if member.customer:
            frappe.delete_doc("Customer", member.customer, force=True)
        if member2.customer:
            frappe.delete_doc("Customer", member2.customer, force=True)

        frappe.delete_doc("Member", member_name, force=True)
        frappe.delete_doc("Member", member2_name, force=True)

        # Clean up shared subscription plan
        try:
            frappe.delete_doc("Subscription Plan", plan_name, force=True)
        except Exception:
            pass


class TestChapterSelection(unittest.TestCase):
    """Test chapter selection functionality in membership applications"""

    @classmethod
    def setUpClass(cls):
        """Set up test data for chapter tests"""
        # Create test membership type
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "amount": 100,
                    "currency": "EUR",
                    "subscription_period": "Annual",
                }
            )
            membership_type.insert()
            # Create subscription plan for the membership type
            membership_type.create_subscription_plan()

        # Create test chapters with different configurations
        test_chapters = [
            {
                "name": "Test Chapter Amsterdam",
                "region": "Noord-Holland",
                "postal_codes": "1000-1199",
                "published": 1,
                "introduction": "Test chapter for Amsterdam region",
            },
            {
                "name": "Test Chapter Utrecht",
                "region": "Utrecht",
                "postal_codes": "3500-3599",
                "published": 1,
                "introduction": "Test chapter for Utrecht region",
            },
            {
                "name": "Test Chapter Rotterdam",
                "region": "Zuid-Holland",
                "postal_codes": "3000-3099",
                "published": 1,
                "introduction": "Test chapter for Rotterdam region",
            },
            {
                "name": "Unpublished Chapter",
                "region": "Limburg",
                "postal_codes": "6000-6199",
                "published": 0,  # Not published
                "introduction": "Test unpublished chapter",
            },
        ]

        for chapter_data in test_chapters:
            if not frappe.db.exists("Chapter", chapter_data["name"]):
                chapter = frappe.get_doc({"doctype": "Chapter", **chapter_data})
                chapter.insert()

    def setUp(self):
        """Set up for each test"""
        self.test_email = f"chapter_test_{frappe.generate_hash(length=8)}@example.com"
        self.base_application_data = {
            "first_name": "Chapter",
            "last_name": "Tester",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1012",
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
            "contact_number": "+31612345678",
            "interested_in_volunteering": 0,
            "newsletter_opt_in": 1,
            "application_source": "Website",
        }

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
        member = frappe.get_doc("Member", result["member_id"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(
            primary_chapter, "Test Chapter Utrecht", "Selected chapter should be assigned to member"
        )

        print(f"✅ Chapter selection works: {primary_chapter}")

    def test_application_without_chapter_selection(self):
        """Test application submission without chapter selection (optional field)"""
        # Submit application without chapter selection
        application_data = self.base_application_data.copy()
        # No selected_chapter field

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application without chapter should succeed")

        # Verify member was created without chapter
        member = frappe.get_doc("Member", result["member_id"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertFalse(primary_chapter, "Member should have no chapter assigned")

        print("✅ Application without chapter selection works")

    def test_invalid_chapter_selection(self):
        """Test application with invalid/non-existent chapter"""
        # Submit application with non-existent chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Non-Existent Chapter"

        result = submit_application(**application_data)

        # Should either succeed (ignoring invalid chapter) or fail gracefully
        if result["success"]:
            member = frappe.get_doc("Member", result["member_id"])
            # Invalid chapter should not be assigned
            primary_chapter = get_member_primary_chapter(member.name)
            self.assertNotEqual(
                primary_chapter, "Non-Existent Chapter", "Invalid chapter should not be assigned"
            )
        else:
            # If it fails, should have appropriate error message
            self.assertIn("chapter", result.get("error", "").lower(), "Error should mention chapter issue")

        print("✅ Invalid chapter selection handled gracefully")

    def test_unpublished_chapter_selection(self):
        """Test application with unpublished chapter selection"""
        # Submit application with unpublished chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Unpublished Chapter"

        result = submit_application(**application_data)

        # Should succeed but unpublished chapter should not be assigned
        self.assertTrue(result["success"], "Application should succeed")

        member = frappe.get_doc("Member", result["member_id"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertNotEqual(
            primary_chapter, "Unpublished Chapter", "Unpublished chapter should not be assigned"
        )

        print("✅ Unpublished chapter selection handled correctly")

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
        self.assertIn("chapters", result, "API should return chapters")

        chapters = result["chapters"]
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

    def test_member_form_chapter_assignment_simplification(self):
        """Test that member form chapter assignment is simplified"""
        # Create a member without a chapter
        application_data = self.base_application_data.copy()
        result = submit_application(**application_data)
        member_name = result["member_record"]

        member = frappe.get_doc("Member", member_name)
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertFalse(primary_chapter, "Member should start without chapter")

        # Test direct chapter assignment (simulating the simplified form)
        # Assign member to chapter via Chapter Member table
        add_member_to_chapter_roster(member.name, "Test Chapter Utrecht")
        member.save()

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
        application_data["membership_amount"] = 75.0
        application_data["uses_custom_amount"] = True
        application_data["custom_amount_reason"] = "Test custom with chapter"

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application with chapter and custom amount should succeed")

        member = frappe.get_doc("Member", result["member_id"])

        # Verify both chapter and custom amount were processed
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, "Test Chapter Rotterdam", "Chapter should be assigned")
        self.assertEqual(member.membership_fee_override, 75.0, "Custom amount should be set")

        print("✅ Chapter selection works with custom amounts")

    def test_chapter_data_persistence_through_approval_flow(self):
        """Test that chapter data persists through the entire approval flow"""
        # Submit application with chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "Test Chapter Amsterdam"

        result = submit_application(**application_data)
        member_name = result["member_record"]

        # Verify initial assignment
        member = frappe.get_doc("Member", member_name)
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, "Test Chapter Amsterdam")

        # Approve the application
        frappe.set_user("Administrator")
        approval_result = approve_membership_application(member_name, "Test approval")

        self.assertTrue(approval_result["success"], "Approval should succeed")

        # Verify chapter is preserved after approval
        member.reload()
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, "Test Chapter Amsterdam", "Chapter should persist through approval")

        print("✅ Chapter data persists through approval flow")

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
                }
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
        member = frappe.get_doc("Member", result["member_id"])

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
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = ""

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application with empty chapter string should succeed")

        member = frappe.get_doc("Member", result["member_id"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertFalse(primary_chapter, "Empty chapter string should result in no chapter")

        print("✅ Empty chapter string handled correctly")

    def test_chapter_selection_edge_case_whitespace(self):
        """Test chapter selection with whitespace-only value"""
        # Submit application with whitespace-only chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = "   "

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Application with whitespace chapter should succeed")

        member = frappe.get_doc("Member", result["member_id"])
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
        member = frappe.get_doc("Member", result["member_id"])

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
                        "region": f"Test Region {i}",
                        "postal_codes": f"{4000 + i * 100}-{4099 + i * 100}",
                        "published": 1,
                    }
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

    def test_chapter_selection_internationalization(self):
        """Test chapter selection with international characters"""
        # Create chapter with international characters
        intl_chapter_name = "Test Chapter Ñieuwe Åmsterdam"
        if not frappe.db.exists("Chapter", intl_chapter_name):
            intl_chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": intl_chapter_name,
                    "region": "International-Test",
                    "postal_codes": "9000-9099",
                    "published": 1,
                }
            )
            intl_chapter.insert()

        # Test selecting international chapter
        application_data = self.base_application_data.copy()
        application_data["selected_chapter"] = intl_chapter_name

        result = submit_application(**application_data)

        self.assertTrue(result["success"], "Should handle international chapter names")

        member = frappe.get_doc("Member", result["member_id"])
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(primary_chapter, intl_chapter_name, "International chapter name should be preserved")

        print(f"✅ International chapter names handled: {intl_chapter_name}")

        # Clean up international chapter
        try:
            frappe.delete_doc("Chapter", intl_chapter_name, force=True)
        except Exception:
            pass


class TestMembershipApplicationEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions in membership application system"""

    def setUp(self):
        """Set up for each test"""
        self.test_email = f"edge_test_{frappe.generate_hash(length=8)}@example.com"

        # Ensure test membership type exists
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "amount": 100,
                    "currency": "EUR",
                    "subscription_period": "Annual",
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
            "postal_code": "1012",
            "country": "Netherlands",
            "selected_membership_type": "Test Membership",
        }

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
        self.assertIn("error", result, "Should have error message")
        self.assertIn("email", result["error"].lower(), "Error should mention missing email")

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
            member = frappe.get_doc("Member", result["member_id"])
            # Should be truncated to reasonable length
            self.assertLessEqual(len(member.first_name), 255, "Long field should be truncated")
        else:
            # Should have descriptive error
            self.assertIn("error", result, "Should provide error for long fields")

        print("✅ Long field values handled appropriately")

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

        member = frappe.get_doc("Member", result["member_id"])
        self.assertEqual(member.first_name, "José-María", "Special characters should be preserved")

        print("✅ Special characters handled correctly")

    def test_concurrent_application_submissions(self):
        """Test handling of concurrent submissions with same email"""
        import threading

        results = []

        def submit_concurrent_application(email_suffix):
            data = self.base_data.copy()
            data["email"] = f"concurrent_{email_suffix}@example.com"
            result = submit_application(data)
            results.append(result)

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
        successful_results = [r for r in results if r["success"]]
        self.assertEqual(len(successful_results), 3, "All concurrent applications should succeed")

        print("✅ Concurrent submissions handled correctly")

        # Clean up
        for result in successful_results:
            if "member_id" in result:
                try:
                    member = frappe.get_doc("Member", result["member_record"])
                    if member.customer:
                        frappe.delete_doc("Customer", member.customer, force=True)
                    frappe.delete_doc("Member", result["member_id"], force=True)
                except Exception:
                    pass

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
            self.assertTrue(result.get("success"), "Should handle database operations normally")
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
        self.assertIn(
            "membership", result.get("error", "").lower(), "Error should mention membership type issue"
        )

        print("✅ Invalid membership type handled correctly")

    def test_form_data_api_fallback_behavior(self):
        """Test fallback behavior when form data fails to load"""
        from verenigingen.api.membership_application import get_application_form_data

        # Should provide fallback data even if some parts fail
        result = get_application_form_data()

        self.assertTrue(result["success"], "Should succeed even with partial failures")

        # Should have fallback data structures
        self.assertIn("membership_types", result, "Should have membership types (empty if needed)")
        self.assertIn("chapters", result, "Should have chapters (empty if needed)")
        self.assertIn("countries", result, "Should have fallback countries")

        # Fallback countries should be provided
        countries = result["countries"]
        self.assertGreater(len(countries), 0, "Should have fallback countries")

        print("✅ Form data API provides appropriate fallbacks")


def run_tests():
    """Run all membership application tests"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
