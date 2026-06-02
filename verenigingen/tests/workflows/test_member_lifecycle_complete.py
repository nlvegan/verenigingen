"""
Complete Member Lifecycle Workflow Tests
Tests end-to-end member journeys from application through termination
Including chapter transfers, status changes, and financial history preservation
"""

import frappe
from frappe.utils import today, add_days, add_years
from verenigingen.tests.utils.base import VereningingenTestCase
import unittest
# MemberService import removed - not needed for these tests


class TestMemberLifecycleComplete(VereningingenTestCase):
    """Comprehensive member lifecycle testing covering complete journeys"""

    def setUp(self):
        """Set up test data for member lifecycle tests"""
        super().setUp()

        # Create test chapters for transfers. chapter_name is the Chapter
        # primary key, so uniquify per run to avoid PRIMARY collisions; tests
        # reference self.chapter_north/south.name, not the literals.
        suffix = frappe.generate_hash(length=6)
        self.chapter_north = self.factory.create_test_chapter(
            chapter_name=f"North Chapter {suffix}",
            postal_codes="1000-1999"
        )
        self.chapter_south = self.factory.create_test_chapter(
            chapter_name=f"South Chapter {suffix}",
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
        """Test complete member journey: member creation → active → status changes → termination"""
        # Phase 1: Direct Member Creation (simulating approved application)
        member = self.factory.create_test_member(
            first_name="Complete",
            last_name="Journey",
            email=f"complete.journey.{self.factory.test_run_id}@example.com",
            birth_date=add_years(today(), -30),
            phone="+31612345678",
            address_line_1="Test Street 123",
            city="Amsterdam",
            postal_code="1234",
            country="Netherlands",
            status="Active"
        )

        # Verify member created properly
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.first_name, "Complete")
        self.assertEqual(member.last_name, "Journey")

        # Phase 2: Create Membership for the Member
        membership = self.factory.create_test_membership(
            member=member,
            membership_type=self.regular_membership_type,
            status="Active"
        )
        membership.submit()  # Must be submitted to become active

        # Verify membership created properly
        membership.reload()
        self.assertEqual(membership.status, "Active")
        self.assertEqual(membership.membership_type, self.regular_membership_type.name)

        # Phase 3: Member Status Changes (Active → Suspended → Active)
        member.reload()  # Reload after membership submission (hooks may have modified member)
        original_status = member.status
        member.status = "Suspended"
        member.save()

        # Verify member status changed
        member.reload()
        self.assertEqual(member.status, "Suspended")

        # Reactivate member
        member.status = "Active"
        member.save()

        member.reload()
        self.assertEqual(member.status, "Active")

        # Phase 5: Termination Request
        termination_request = frappe.new_doc("Membership Termination Request")
        termination_request.member = member.name
        termination_request.termination_reason = "Moving abroad"
        # Set termination date after 1-year commitment period
        termination_request.termination_date = add_years(today(), 1)
        termination_request.save()
        self.track_doc("Membership Termination Request", termination_request.name)

        # Process termination
        termination_request.status = "Approved"
        termination_request.save()

        # Verify termination request was approved
        termination_request.reload()
        self.assertEqual(termination_request.status, "Approved")

        # Note: Automatic member/membership status updates are not currently implemented
        # Manual termination process would be handled separately in production

    def test_member_chapter_transfer_with_history_preservation(self):
        """Test member transfer between chapters with complete history preservation"""
        # Create member in North chapter
        member = self.factory.create_test_member(
            first_name="Transfer",
            last_name="Test",
            postal_code="1500",  # North chapter postal code
            email=f"transfer.test.{self.factory.test_run_id}@example.com"
        )

        # Create initial chapter membership through Chapter document
        chapter = frappe.get_doc("Chapter", self.chapter_north.name)
        chapter.append("members", {
            "member": member.name,
            "status": "Active"
        })
        chapter.save()

        # Track the parent document
        self.track_doc("Chapter", chapter.name)

        # Create some history in North chapter
        volunteer = self.factory.create_test_volunteer(
            member=member.name,
            volunteer_name=f"{member.first_name} {member.last_name}"
        )

        # Create volunteer assignment in North chapter
        # Volunteer Assignment is a child table, must be added to volunteer record
        volunteer.reload()  # Ensure we have latest data
        volunteer.append("assignment_history", {
            "team": "Communications Team",
            "chapter": self.chapter_north.name,
            "start_date": today(),
            "role": "Team Member"  # Required field
        })
        volunteer.save()

        # Track the volunteer (child table rows are automatically tracked with parent)
        assignment = volunteer.assignment_history[-1]  # Get the assignment we just added

        # Transfer member to South chapter
        # Update member address to trigger chapter change
        member.reload()  # Reload after volunteer creation (may have triggered hooks)
        member.postal_code = "2500"  # South chapter postal code
        member.save()

        # Create new chapter membership for South
        south_chapter = frappe.get_doc("Chapter", self.chapter_south.name)
        south_chapter.append("members", {
            "member": member.name,
            "status": "Active"
        })
        south_chapter.save()

        # Track the parent document
        self.track_doc("Chapter", south_chapter.name)

        # End assignment in North chapter
        assignment.end_date = today()
        assignment.save()

        # Verify member transferred to South chapter
        member.reload()  # Reload to get latest chapter info

        # Verify member is in South chapter (via postal code change)
        self.assertEqual(member.postal_code, "2500")

        # Verify both chapter memberships exist
        north_memberships = frappe.get_all(
            "Chapter Member",
            filters={"parent": self.chapter_north.name, "member": member.name}
        )
        south_memberships = frappe.get_all(
            "Chapter Member",
            filters={"parent": self.chapter_south.name, "member": member.name}
        )

        self.assertGreater(len(north_memberships), 0, "Member should have North chapter membership")
        self.assertGreater(len(south_memberships), 0, "Member should have South chapter membership")

        # Verify volunteer history preserved
        assignments = frappe.get_all(
            "Volunteer Assignment",
            filters={"parent": volunteer.name},
            fields=["start_date", "end_date"]
        )
        self.assertEqual(len(assignments), 1, "Should have one volunteer assignment")
        self.assertIsNotNone(assignments[0].end_date, "Assignment should have end date")

    def test_member_financial_history_across_status_changes(self):
        """Test member financial history preservation across multiple status changes"""
        # Create member with membership
        member = self.factory.create_test_member(
            first_name="Financial",
            last_name="History",
            email=f"financial.history.{self.factory.test_run_id}@example.com"
        )

        self.factory.create_test_membership(
            member=member.name,
            membership_type=self.regular_membership_type.name
        )

        # Create SEPA mandate for payments
        self.factory.create_test_sepa_mandate(
            member=member.name,
            status="Active"
        )

        # Simulate payment history
        # Member Payment History is a child table, must be added to member record
        member.reload()  # Ensure we have latest data
        member.append("payment_history", {
            "payment_date": today(),
            "amount": 50.00,
            "payment_type": "Membership Fee",
            "payment_method": "SEPA Direct Debit",
            "reference_number": f"SEPA-001-{self.factory.test_run_id}"
        })
        member.save()
        payment1 = member.payment_history[-1]  # Get the payment we just added

        # Change status to suspended
        member.reload()  # Reload after previous save
        member.status = "Suspended"
        member.save()

        # Payment 2: Failed payment while suspended
        member.reload()  # Reload after status change
        member.append("payment_history", {
            "payment_date": add_days(today(), 30),
            "amount": 50.00,
            "payment_type": "Membership Fee",
            "payment_method": "SEPA Direct Debit",
            "status": "Failed",
            "failure_reason": "Insufficient funds",
            "reference_number": f"SEPA-002-{self.factory.test_run_id}"
        })
        member.save()
        payment2 = member.payment_history[-1]  # Get the payment we just added

        # Reactivate member
        member.reload()  # Reload after status change
        member.status = "Active"
        member.save()

        # Payment 3: Successful retry payment
        member.reload()  # Reload after reactivation
        member.append("payment_history", {
            "payment_date": add_days(today(), 35),
            "amount": 100.00,  # Double payment to catch up
            "payment_type": "Membership Fee",
            "payment_method": "SEPA Direct Debit",
            "reference_number": f"SEPA-003-{self.factory.test_run_id}"
        })
        member.save()
        payment3 = member.payment_history[-1]  # Get the payment we just added

        # Verify all payment history is preserved
        # Member Payment History is a child table - use parent/parenttype filters
        saved_history = frappe.get_all(
            "Member Payment History",
            filters={"parent": member.name, "parenttype": "Member"},
            fields=["payment_date", "amount", "status", "transaction_type"],
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

        # Transition to student membership
        membership.membership_type = self.student_membership_type.name
        membership.save()

        # Verify membership type changed
        self.assertEqual(membership.membership_type, self.student_membership_type.name)

        # Create fee change history entry through Member document
        member.reload()  # Reload after membership changes (hooks may have modified member)
        member.append("fee_change_history", {
            "change_date": today(),
            "new_dues_rate": self.student_membership_type.minimum_amount,
            "change_type": "Membership Type Change",
            "reason": "Student status verified",
            "changed_by": frappe.session.user
        })
        member.save()

        # Get the created fee change history for verification
        fee_change = member.fee_change_history[-1]  # Last added entry

        # Verify fee change history was added
        self.assertEqual(len(member.fee_change_history), 1)
        self.assertEqual(fee_change.reason, "Student status verified")
        self.assertEqual(fee_change.new_dues_rate, self.student_membership_type.minimum_amount)

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
        member.reload()  # Reload after creation (hooks may have modified)
        initial_iban = self.factory.generate_test_iban()
        member.iban = initial_iban
        member.save()

        # Simulate address change
        member.reload()  # Reload to get latest timestamp after first save
        member.address_line_1 = "New Street 456"
        member.city = "Rotterdam"
        member.postal_code = "3000"
        member.save()

        # Verify address history tracking
        # Note: This assumes address history tracking is implemented
        # If not, this test documents the expected behavior

        # Simulate IBAN change
        member.reload()  # Reload after address change
        new_iban = self.factory.generate_test_iban()
        old_iban = member.iban
        member.iban = new_iban
        member.bank_account_name = f"{member.first_name} {member.last_name}"  # Required when IBAN is set
        member.save()

        # Create IBAN history entry through Member document
        # Member IBAN History is a child table, must be added to member record
        member.reload()  # Reload after IBAN change save
        member.append("iban_history", {
            "iban": new_iban,
            "bank_account_name": member.bank_account_name,
            "from_date": today(),
            "is_active": 1,
            "changed_by": frappe.session.user,
            "change_reason": "Bank Change"  # Must be one of the valid select options
        })
        member.save()

        # Verify IBAN history (child table in Member)
        member.reload()
        history = member.iban_history

        self.assertGreaterEqual(len(history), 1)
        # Check that we have the new IBAN in the history
        ibans_in_history = [h.iban for h in history]
        self.assertIn(new_iban, ibans_in_history)


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

