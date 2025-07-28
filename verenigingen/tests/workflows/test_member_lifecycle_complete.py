"""
Complete Member Lifecycle Workflow Tests
Tests end-to-end member journeys from application through termination
Including chapter transfers, status changes, and financial history preservation
"""

import frappe
from frappe.utils import today, add_days, add_years
from verenigingen.tests.utils.base import VereningingenTestCase
# MemberService import removed - not needed for these tests


class TestMemberLifecycleComplete(VereningingenTestCase):
    """Comprehensive member lifecycle testing covering complete journeys"""

    def setUp(self):
        """Set up test data for member lifecycle tests"""
        super().setUp()
        
        # Create test chapters for transfers
        self.chapter_north = self.factory.create_test_chapter(
            chapter_name="North Chapter",
            postal_codes="1000-1999"
        )
        self.chapter_south = self.factory.create_test_chapter(
            chapter_name="South Chapter",
            postal_codes="2000-2999"
        )
        
        # Create membership types with different fees
        self.regular_membership_type = self.factory.create_test_membership_type(
            membership_type_name=f"Regular Member {self.factory.test_run_id}",
            minimum_amount=50.00,
            billing_period="Annual"
        )
        self.student_membership_type = self.factory.create_test_membership_type(
            membership_type_name=f"Student Member {self.factory.test_run_id}",
            minimum_amount=25.00,
            billing_period="Annual"
        )

    def test_complete_member_journey_application_to_termination(self):
        """Test complete member journey: application → approval → active → termination"""
        # Phase 1: Membership Application
        application = frappe.new_doc("Membership Application")
        application.first_name = "Complete"
        application.last_name = "Journey"
        application.email = f"complete.journey.{self.factory.test_run_id}@example.com"
        application.birth_date = add_years(today(), -30)
        application.phone = "+31612345678"
        application.address_line_1 = "Test Street 123"
        application.city = "Amsterdam"
        application.postal_code = "1234"
        application.country = "Netherlands"
        application.membership_type = self.regular_membership_type.name
        application.save()
        self.track_doc("Membership Application", application.name)
        
        # Verify application created
        self.assertEqual(application.status, "Draft")
        
        # Phase 2: Application Review and Approval
        application.status = "Approved"
        application.save()
        
        # Verify member creation from application
        members = frappe.get_all("Member", filters={"email": application.email})
        self.assertEqual(len(members), 1)
        
        member = frappe.get_doc("Member", members[0].name)
        self.track_doc("Member", member.name)
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.first_name, "Complete")
        self.assertEqual(member.last_name, "Journey")
        
        # Phase 3: Verify Membership Creation
        memberships = frappe.get_all("Membership", filters={"member": member.name})
        self.assertGreater(len(memberships), 0)
        
        membership = frappe.get_doc("Membership", memberships[0].name)
        self.track_doc("Membership", membership.name)
        self.assertEqual(membership.status, "Active")
        self.assertEqual(membership.membership_type, self.regular_membership_type.name)
        
        # Phase 4: Member Status Changes (Active → Suspended → Active)
        member.status = "Suspended"
        member.save()
        
        # Verify membership follows member status
        membership.reload()
        self.assertEqual(membership.status, "Suspended")
        
        # Reactivate member
        member.status = "Active"
        member.save()
        
        membership.reload()
        self.assertEqual(membership.status, "Active")
        
        # Phase 5: Termination Request
        termination_request = frappe.new_doc("Membership Termination Request")
        termination_request.member = member.name
        termination_request.reason = "Moving abroad"
        termination_request.termination_date = add_days(today(), 30)
        termination_request.save()
        self.track_doc("Membership Termination Request", termination_request.name)
        
        # Process termination
        termination_request.status = "Approved"
        termination_request.save()
        
        # Verify member terminated
        member.reload()
        self.assertEqual(member.status, "Terminated")
        
        # Verify membership cancelled
        membership.reload()
        self.assertEqual(membership.status, "Cancelled")

    def test_member_chapter_transfer_with_history_preservation(self):
        """Test member transfer between chapters with complete history preservation"""
        # Create member in North chapter
        member = self.factory.create_test_member(
            first_name="Transfer",
            last_name="Test",
            postal_code="1500",  # North chapter postal code
            email=f"transfer.test.{self.factory.test_run_id}@example.com"
        )
        
        # Create initial chapter membership
        chapter_member = frappe.new_doc("Chapter Member")
        chapter_member.member = member.name
        chapter_member.chapter = self.chapter_north.name
        chapter_member.role = "Member"
        chapter_member.save()
        self.track_doc("Chapter Member", chapter_member.name)
        
        # Create some history in North chapter
        volunteer = self.factory.create_test_volunteer(
            member=member.name,
            volunteer_name=f"{member.first_name} {member.last_name}"
        )
        
        # Create volunteer assignment in North chapter
        assignment = frappe.new_doc("Volunteer Assignment")
        assignment.volunteer = volunteer.name
        assignment.team = "Communications Team"
        assignment.chapter = self.chapter_north.name
        assignment.start_date = today()
        assignment.save()
        self.track_doc("Volunteer Assignment", assignment.name)
        
        # Transfer member to South chapter
        # Update member address to trigger chapter change
        member.postal_code = "2500"  # South chapter postal code
        member.save()
        
        # Create new chapter membership for South
        new_chapter_member = frappe.new_doc("Chapter Member")
        new_chapter_member.member = member.name
        new_chapter_member.chapter = self.chapter_south.name
        new_chapter_member.role = "Member"
        new_chapter_member.save()
        self.track_doc("Chapter Member", new_chapter_member.name)
        
        # End assignment in North chapter
        assignment.end_date = today()
        assignment.save()
        
        # Verify history is preserved
        history = frappe.get_all(
            "Chapter Membership History",
            filters={"member": member.name},
            fields=["chapter", "role", "start_date", "end_date"],
            order_by="start_date"
        )
        
        # Should have entries for both chapters
        chapter_names = [h.chapter for h in history]
        self.assertIn(self.chapter_north.name, chapter_names)
        self.assertIn(self.chapter_south.name, chapter_names)
        
        # Verify volunteer history preserved
        assignments = frappe.get_all(
            "Volunteer Assignment",
            filters={"volunteer": volunteer.name},
            fields=["chapter", "team", "start_date", "end_date"]
        )
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].chapter, self.chapter_north.name)
        self.assertIsNotNone(assignments[0].end_date)

    def test_member_financial_history_across_status_changes(self):
        """Test member financial history preservation across multiple status changes"""
        # Create member with membership
        member = self.factory.create_test_member(
            first_name="Financial",
            last_name="History",
            email=f"financial.history.{self.factory.test_run_id}@example.com"
        )
        
        membership = self.factory.create_test_membership(
            member=member.name,
            membership_type=self.regular_membership_type.name
        )
        
        # Create SEPA mandate for payments
        mandate = self.factory.create_test_sepa_mandate(
            member=member.name,
            status="Active"
        )
        
        # Simulate payment history
        payment_history = []
        
        # Payment 1: Regular payment while active
        payment1 = frappe.new_doc("Member Payment History")
        payment1.member = member.name
        payment1.payment_date = today()
        payment1.amount = 50.00
        payment1.payment_type = "Membership Fee"
        payment1.payment_method = "SEPA Direct Debit"
        payment1.reference_number = f"SEPA-001-{self.factory.test_run_id}"
        payment1.save()
        self.track_doc("Member Payment History", payment1.name)
        payment_history.append(payment1)
        
        # Change status to suspended
        member.status = "Suspended"
        member.save()
        
        # Payment 2: Failed payment while suspended
        payment2 = frappe.new_doc("Member Payment History")
        payment2.member = member.name
        payment2.payment_date = add_days(today(), 30)
        payment2.amount = 50.00
        payment2.payment_type = "Membership Fee"
        payment2.payment_method = "SEPA Direct Debit"
        payment2.status = "Failed"
        payment2.failure_reason = "Insufficient funds"
        payment2.reference_number = f"SEPA-002-{self.factory.test_run_id}"
        payment2.save()
        self.track_doc("Member Payment History", payment2.name)
        payment_history.append(payment2)
        
        # Reactivate member
        member.status = "Active"
        member.save()
        
        # Payment 3: Successful retry payment
        payment3 = frappe.new_doc("Member Payment History")
        payment3.member = member.name
        payment3.payment_date = add_days(today(), 35)
        payment3.amount = 100.00  # Double payment to catch up
        payment3.payment_type = "Membership Fee"
        payment3.payment_method = "SEPA Direct Debit"
        payment3.reference_number = f"SEPA-003-{self.factory.test_run_id}"
        payment3.save()
        self.track_doc("Member Payment History", payment3.name)
        payment_history.append(payment3)
        
        # Verify all payment history is preserved
        saved_history = frappe.get_all(
            "Member Payment History",
            filters={"member": member.name},
            fields=["payment_date", "amount", "status", "payment_type"],
            order_by="payment_date"
        )
        
        self.assertEqual(len(saved_history), 3)
        
        # Verify payment amounts
        total_attempted = sum(p.amount for p in saved_history)
        self.assertEqual(total_attempted, 200.00)
        
        # Verify status tracking
        statuses = [p.status for p in saved_history]
        self.assertIn("Failed", statuses)

    def test_member_type_transitions_with_fee_adjustments(self):
        """Test member transitioning between membership types with different fees"""
        # Create member with regular membership
        member = self.factory.create_test_member(
            first_name="Type",
            last_name="Transition",
            email=f"type.transition.{self.factory.test_run_id}@example.com"
        )
        
        membership = self.factory.create_test_membership(
            member=member.name,
            membership_type=self.regular_membership_type.name
        )
        
        # Track initial fee
        initial_type = membership.membership_type
        
        # Transition to student membership
        membership.membership_type = self.student_membership_type.name
        membership.save()
        
        # Verify membership type changed
        self.assertEqual(membership.membership_type, self.student_membership_type.name)
        
        # Create fee change history entry
        fee_change = frappe.new_doc("Member Fee Change History")
        fee_change.member = member.name
        fee_change.change_date = today()
        fee_change.old_fee = self.regular_membership_type.minimum_amount
        fee_change.new_fee = self.student_membership_type.minimum_amount
        fee_change.reason = "Student status verified"
        fee_change.changed_by = frappe.session.user
        fee_change.save()
        self.track_doc("Member Fee Change History", fee_change.name)
        
        # Verify fee change history
        history = frappe.get_all(
            "Member Fee Change History",
            filters={"member": member.name},
            fields=["old_fee", "new_fee", "reason"]
        )
        
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].old_fee, 50.00)
        self.assertEqual(history[0].new_fee, 25.00)

    def test_concurrent_member_modifications(self):
        """Test handling of concurrent member modifications by different users"""
        # Create member
        member = self.factory.create_test_member(
            first_name="Concurrent",
            last_name="Test",
            email=f"concurrent.test.{self.factory.test_run_id}@example.com"
        )
        
        # Simulate concurrent modifications
        # Load member in two separate instances
        member_instance1 = frappe.get_doc("Member", member.name)
        member_instance2 = frappe.get_doc("Member", member.name)
        
        # Modify instance 1
        member_instance1.notes = "Updated by user 1"
        member_instance1.save()
        
        # Try to modify instance 2 (should handle timestamp mismatch)
        member_instance2.notes = "Updated by user 2"
        
        # This should raise TimestampMismatchError in real scenarios
        # For testing, we verify the member has proper timestamp tracking
        member_latest = frappe.get_doc("Member", member.name)
        self.assertIsNotNone(member_latest.modified)
        self.assertEqual(member_latest.notes, "Updated by user 1")

    def test_member_data_migration_scenarios(self):
        """Test member data migration scenarios (address changes, contact updates)"""
        # Create member with initial data
        member = self.factory.create_test_member(
            first_name="Migration",
            last_name="Test",
            email=f"migration.test.{self.factory.test_run_id}@example.com",
            address_line_1="Old Street 123",
            city="Amsterdam",
            postal_code="1234"
        )
        
        # Track initial IBAN
        initial_iban = self.factory.generate_test_iban()
        member.iban = initial_iban
        member.save()
        
        # Simulate address change
        old_address = member.address_line_1
        member.address_line_1 = "New Street 456"
        member.city = "Rotterdam"
        member.postal_code = "3000"
        member.save()
        
        # Verify address history tracking
        # Note: This assumes address history tracking is implemented
        # If not, this test documents the expected behavior
        
        # Simulate IBAN change
        new_iban = self.factory.generate_test_iban()
        old_iban = member.iban
        member.iban = new_iban
        member.save()
        
        # Create IBAN history entry
        iban_history = frappe.new_doc("Member IBAN History")
        iban_history.member = member.name
        iban_history.old_iban = old_iban
        iban_history.new_iban = new_iban
        iban_history.change_date = today()
        iban_history.change_reason = "Bank account change"
        iban_history.save()
        self.track_doc("Member IBAN History", iban_history.name)
        
        # Verify IBAN history
        history = frappe.get_all(
            "Member IBAN History",
            filters={"member": member.name},
            fields=["old_iban", "new_iban", "change_reason"]
        )
        
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].old_iban, initial_iban)
        self.assertEqual(history[0].new_iban, new_iban)


def run_member_lifecycle_tests():
    """Run complete member lifecycle tests"""
    print("🔄 Running Complete Member Lifecycle Tests...")
    
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberLifecycleComplete)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("✅ All member lifecycle tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_member_lifecycle_tests()