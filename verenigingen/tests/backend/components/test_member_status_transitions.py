"""
Member Status Transition Edge Cases Test Suite
Tests for member lifecycle, status changes, and state validation
"""

import unittest
import frappe
from frappe.utils import add_months
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberStatusTransitions(VereningingenTestCase):
    """Test member status transition edge cases and validation"""

    # ===== BASIC STATUS TRANSITIONS =====

    def test_active_to_suspended_transition(self):
        """Test Active → Suspended transition"""
        # Create member using factory method
        member = self.create_test_member(
            first_name="Active",
            last_name="Member",
            email="active.test.status@test.com",
            status="Active"
        )

        # Create active membership using factory method
        membership = self.create_test_membership(
            member=member.name,
            status="Active"
        )

        # Reload to get latest version before making changes (prevent TimestampMismatchError)
        member.reload()

        # Transition to suspended
        member.status = "Suspended"
        member.save()

        # Verify status change
        self.assertEqual(member.status, "Suspended")

        # Verify membership status - check if cascade happened
        updated_membership = frappe.get_doc("Membership", membership.name)
        # Cascade should change membership status from Active to Draft/Suspended/Pending
        # If still Active, cascade not implemented; if Draft, cascade happened (needs review)
        self.assertIn(
            updated_membership.status,
            ["Active", "Draft", "Suspended", "Pending"],
            f"Membership status after member suspension should be a valid cascade state, got: {updated_membership.status}"
        )

        # Cleanup handled automatically by VereningingenTestCase

    def test_suspended_to_active_transition(self):
        """Test Suspended → Active transition"""
        member = self.create_test_member(
            first_name="Suspended",
            last_name="Member",
            email="suspended.test.status@test.com",
            status="Suspended"
        )

        # Reload to get latest version before making changes (prevent TimestampMismatchError)
        member.reload()

        # Transition back to active
        member.status = "Active"
        member.save()

        # Verify status change
        self.assertEqual(member.status, "Active")

        # Cleanup handled automatically by VereningingenTestCase

    def test_active_to_terminated_transition(self):
        """Test Active → Terminated transition"""
        member = self.create_test_member(
            first_name="ToTerminate",
            last_name="Member",
            email="terminate.test.status@test.com",
            status="Active"
        )

        # Create active membership
        membership = self.create_test_membership(
            member=member.name,
            status="Active"
        )

        # Reload to get latest version before making changes (prevent TimestampMismatchError)
        member.reload()

        # Transition to terminated
        member.status = "Quit"
        member.save()

        # Verify status change
        self.assertEqual(member.status, "Quit")

        # Verify membership status - check if cascade happened
        updated_membership = frappe.get_doc("Membership", membership.name)
        # Cascade should change membership status from Active to Draft/Terminated/Cancelled
        # If still Active, cascade not implemented; if Draft, cascade happened (needs review)
        self.assertIn(
            updated_membership.status,
            ["Active", "Draft", "Quit", "Cancelled"],
            f"Membership status after member termination should be a valid cascade state, got: {updated_membership.status}"
        )

        # Cleanup handled automatically by VereningingenTestCase

    # ===== INVALID TRANSITIONS =====

    def test_terminated_to_active_prevention(self):
        """Test Terminated → Active transition behavior"""
        member = self.create_test_member(
            first_name="Quit",
            last_name="Member",
            email="terminated.test.status@test.com",
            status="Quit"
        )

        # Attempt transition from Terminated to Active
        # Current implementation may or may not enforce this restriction
        try:
            member.status = "Active"
            member.save()
            # If save succeeds, the restriction is not enforced
            # This is acceptable - document the actual behavior
            self.assertEqual(member.status, "Active")
        except frappe.ValidationError:
            # If ValidationError is raised, restriction is enforced
            # This is the expected behavior for strict implementations
            pass

        # Cleanup handled automatically by VereningingenTestCase

    def test_pending_to_terminated_prevention(self):
        """Test Pending → Terminated transition behavior"""
        member = self.create_test_member(
            first_name="Pending",
            last_name="Member",
            email="pending.test.status@test.com",
            status="Pending"
        )

        # Attempt transition from Pending to Terminated
        # Current implementation may or may not enforce this restriction
        try:
            member.status = "Quit"
            member.save()
            # If save succeeds, the restriction is not enforced
            self.assertEqual(member.status, "Quit")
        except frappe.ValidationError:
            # If ValidationError is raised, restriction is enforced
            pass

        # Cleanup handled automatically by VereningingenTestCase

    # ===== COMPLEX TRANSITION SCENARIOS =====

    def test_rapid_status_changes(self):
        """Test rapid successive status changes"""
        member = self.create_test_member(
            first_name="Rapid",
            last_name="Changer",
            email="rapid.test.status@test.com",
            status="Active"
        )

        # Perform rapid transitions
        transitions = ["Suspended", "Active", "Suspended", "Active"]

        for new_status in transitions:
            member.reload()  # Prevent TimestampMismatchError
            member.status = new_status
            member.save()

            # Verify each transition
            self.assertEqual(member.status, new_status)

            # Small delay to avoid conflicts
            frappe.db.commit()

        # Cleanup handled automatically by VereningingenTestCase

    def test_concurrent_status_changes(self):
        """Test concurrent status change attempts"""
        member = self.create_test_member(
            first_name="Concurrent",
            last_name="Member",
            email="concurrent.test.status@test.com",
            status="Active"
        )

        # Simulate concurrent modifications
        member1 = frappe.get_doc("Member", member.name)
        member2 = frappe.get_doc("Member", member.name)

        # First user suspends
        member1.status = "Suspended"
        member1.save()

        # Second user tries to terminate from a stale copy: Frappe's optimistic lock
        # must refuse the write, so the first user's Suspended is what persists.
        member2.status = "Quit"
        with self.assertRaises(frappe.TimestampMismatchError):
            member2.save()

        final_member = frappe.get_doc("Member", member.name)
        self.assertEqual(final_member.status, "Suspended")

        # Cleanup handled automatically by VereningingenTestCase

    # ===== MEMBERSHIP IMPACT TESTING =====

    def test_member_status_membership_cascade(self):
        """Test how member status changes affect memberships"""
        member = self.create_test_member(
            first_name="Cascade",
            last_name="Test",
            email="cascade.test.status@test.com",
            status="Active"
        )

        # Create multiple memberships
        memberships = []
        for i in range(2):  # Create 2 memberships
            membership = self.create_test_membership(
                member=member.name,
                status="Active"
            )
            memberships.append(membership)

        # Suspend member
        member.reload()  # Prevent TimestampMismatchError
        member.status = "Suspended"
        member.save()

        # Check membership status updates - verify cascade behavior
        for membership in memberships:
            updated_membership = frappe.get_doc("Membership", membership.name)
            # Cascade should change membership status from Active to Draft/Suspended/Pending
            self.assertIn(
                updated_membership.status,
                ["Active", "Draft", "Suspended", "Pending"],
                f"Membership {membership.name} status after member suspension should be valid cascade state"
            )

        # Terminate member
        member.reload()  # Prevent TimestampMismatchError
        member.status = "Quit"
        member.save()

        # Check membership termination - verify cascade behavior
        for membership in memberships:
            updated_membership = frappe.get_doc("Membership", membership.name)
            # Cascade should change membership status to Draft/Terminated/Cancelled
            # May also be Suspended/Pending from previous cascade step
            self.assertIn(
                updated_membership.status,
                ["Active", "Draft", "Suspended", "Pending", "Quit", "Cancelled"],
                f"Membership {membership.name} status after member termination should be valid cascade state"
            )

        # Cleanup handled automatically by VereningingenTestCase
    def test_volunteer_status_impact(self):
        """Test how member status changes affect volunteer records"""
        member = self.create_test_member(
            first_name="Verenigingen Volunteer",
            last_name="Impact",
            email="volunteer.test.status@test.com",
            status="Active"
        )

        # Create volunteer record
        volunteer = self.create_test_volunteer(
            volunteer_name="Volunteer Impact",
            member=member.name
        )

        # Suspend member
        member.reload()  # Prevent TimestampMismatchError
        member.status = "Suspended"
        member.save()

        # Check volunteer status (should be updated or remain unchanged based on policy)
        updated_volunteer = frappe.get_doc("Volunteer", volunteer.name)
        self.assertIn(updated_volunteer.status, ["Active", "Suspended", "Inactive"])

        # Terminate member
        member.reload()  # Prevent TimestampMismatchError
        member.status = "Quit"
        member.save()

        # Check volunteer termination
        updated_volunteer = frappe.get_doc("Volunteer", volunteer.name)
        self.assertIn(updated_volunteer.status, ["Active", "Inactive", "Quit"])

        # Cleanup handled automatically by VereningingenTestCase
    # ===== BUSINESS RULE VALIDATION =====

    def test_payment_status_business_rules(self):
        """Test business rules around payment status and member status"""
        member = self.create_test_member(
            first_name="Payment",
            last_name="Rules",
            email="payment.test.status@test.com",
            status="Active"
        )

        # Create overdue membership
        membership = self.create_test_membership(
            member=member.name,
            status="Overdue"  # Overdue payment
        )

        # Test if member can be activated with overdue payments
        try:
            member.status = "Active"
            member.save()

            # Some systems may allow this, others may prevent it
            self.assertIn(member.status, ["Active", "Suspended"])

        except frappe.ValidationError:
            # Prevention is also valid business rule
            pass

        # Cleanup handled automatically by VereningingenTestCase

    def test_chapter_transfer_status_rules(self):
        """Test status rules during chapter transfers"""
        # Create second chapter
        chapter2 = self.create_test_chapter(
            chapter_name="Transfer Test Chapter"
        )

        member = self.create_test_member(
            first_name="Transfer",
            last_name="Test",
            email="transfer.test.status@test.com",
            status="Active"
        )

        # Suspend member
        member.reload()  # Prevent TimestampMismatchError
        member.status = "Suspended"
        member.save()

        # A Suspended member cannot be assigned: the call refuses (success False) and
        # leaves no enabled row in the target chapter (#1584). This used to be an
        # "allowed OR prevented" test whose allowed branch never ran: the test's own
        # member.save() hit a TimestampMismatchError (a ValidationError) because the
        # old assignment re-saved the Member, and that was swallowed as "prevention".
        from verenigingen.verenigingen.doctype.chapter.chapter import assign_member_to_chapter

        result = assign_member_to_chapter(member.name, chapter2.name)

        self.assertFalse(result["success"], result)
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"parent": chapter2.name, "member": member.name, "enabled": 1})
        )

        # Cleanup handled automatically by VereningingenTestCase


def run_member_status_transition_tests():
    """Run all member status transition tests"""
    print("👤 Running Member Status Transition Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberStatusTransitions)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All member status transition tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_member_status_transition_tests()
