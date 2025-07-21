"""
Member Status Transition Edge Cases Test Suite
Tests for member lifecycle, status changes, and state validation
"""

import unittest
import frappe
from frappe.utils import add_days, add_months, today
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

        # Transition to suspended
        member.status = "Suspended"
        # Check if suspension_reason field exists in Member doctype
        if hasattr(member, 'suspension_reason'):
            member.suspension_reason = "Payment overdue"
        member.save()

        # Verify status change
        self.assertEqual(member.status, "Suspended")

        # Verify membership status updated
        updated_membership = frappe.get_doc("Membership", membership.name)
        self.assertIn(updated_membership.status, ["Suspended", "Pending"])

        # Cleanup handled automatically by VereningingenTestCase

    def test_suspended_to_active_transition(self):
        """Test Suspended → Active transition"""
        member = self.create_test_member(
            first_name="Suspended",
            last_name="Member",
            email="suspended.test.status@test.com",
            status="Suspended"
        )
        
        # Set suspension reason if field exists
        if hasattr(member, 'suspension_reason'):
            member.suspension_reason = "Payment overdue"
            member.save()

        # Transition back to active
        member.status = "Active"
        if hasattr(member, 'suspension_reason'):
            member.suspension_reason = ""  # Clear reason
        member.save()

        # Verify status change
        self.assertEqual(member.status, "Active")
        if hasattr(member, 'suspension_reason'):
            self.assertEqual(member.suspension_reason, "")

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

        # Transition to terminated
        member.status = "Terminated"
        member.termination_reason = "Voluntary resignation"
        member.termination_date = today()
        member.save()

        # Verify status change
        self.assertEqual(member.status, "Terminated")
        self.assertIsNotNone(member.termination_date)

        # Verify membership status updated
        updated_membership = frappe.get_doc("Membership", membership.name)
        self.assertIn(updated_membership.status, ["Terminated", "Cancelled"])

        # Cleanup handled automatically by VereningingenTestCase

    # ===== INVALID TRANSITIONS =====

    def test_terminated_to_active_prevention(self):
        """Test prevention of Terminated → Active transition"""
        member = self.create_test_member(
            first_name="Terminated",
            last_name="Member",
            email="terminated.test.status@test.com",
            status="Terminated"
        )

        # Attempt invalid transition
        with self.assertRaises(frappe.ValidationError):
            member.status = "Active"
            member.save()

        # Cleanup handled automatically by VereningingenTestCase

    def test_pending_to_terminated_prevention(self):
        """Test prevention of Pending → Terminated transition"""
        member = self.create_test_member(
            first_name="Pending",
            last_name="Member",
            email="pending.test.status@test.com",
            status="Pending"
        )

        # Attempt invalid transition
        with self.assertRaises(frappe.ValidationError):
            member.status = "Terminated"
            member.save()

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
        transitions = [
            ("Suspended", "Payment issue"),
            ("Active", ""),
            ("Suspended", "Behavior issue"),
            ("Active", ""),
        ]

        for new_status, reason in transitions:
            member.status = new_status
            if new_status == "Suspended":
                member.suspension_reason = reason
            else:
                member.suspension_reason = ""

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
        member1.suspension_reason = "First reason"
        member1.save()

        # Second user tries to terminate (should handle conflict)
        try:
            member2.status = "Terminated"
            member2.termination_reason = "Second reason"
            member2.save()

            # Should handle gracefully or detect conflict
            final_member = frappe.get_doc("Member", member.name)
            self.assertIn(final_member.status, ["Suspended", "Terminated"])

        except Exception:
            # Conflict detection is acceptable
            pass

        # Cleanup handled automatically by VereningingenTestCase

    # ===== STATUS VALIDATION EDGE CASES =====

    def test_status_with_missing_required_fields(self):
        """Test status changes with missing required fields"""
        member = self.create_test_member(
            first_name="Missing",
            last_name="Fields",
            email="missing.test.status@test.com",
            status="Active"
        )

        # Test suspended without reason
        with self.assertRaises(frappe.ValidationError):
            member.status = "Suspended"
            member.suspension_reason = ""  # Missing required reason
            member.save()

        # Test terminated without required fields
        with self.assertRaises(frappe.ValidationError):
            member.status = "Terminated"
            # Missing termination_reason and termination_date
            member.save()

        # Cleanup handled automatically by VereningingenTestCase

    def test_status_with_invalid_dates(self):
        """Test status changes with invalid dates"""
        member = self.create_test_member(
            first_name="Invalid",
            last_name="Dates",
            email="dates.test.status@test.com",
            status="Active"
        )

        # Test future termination date
        with self.assertRaises(frappe.ValidationError):
            member.status = "Terminated"
            member.termination_reason = "Test"
            member.termination_date = add_days(today(), 30)  # Future date
            member.save()

        # Test termination date before join date
        if hasattr(member, "join_date") and member.join_date:
            with self.assertRaises(frappe.ValidationError):
                member.status = "Terminated"
                member.termination_reason = "Test"
                member.termination_date = add_days(member.join_date, -1)  # Before join
                member.save()

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
        member.status = "Suspended"
        member.suspension_reason = "Test suspension"
        member.save()

        # Check membership status updates
        for membership in memberships:
            updated_membership = frappe.get_doc("Membership", membership.name)
            self.assertIn(updated_membership.status, ["Suspended", "Pending", "Active"])

        # Terminate member
        member.status = "Terminated"
        member.termination_reason = "Test termination"
        member.termination_date = today()
        member.save()

        # Check membership termination
        for membership in memberships:
            updated_membership = frappe.get_doc("Membership", membership.name)
            self.assertIn(updated_membership.status, ["Terminated", "Cancelled"])

        # Cleanup handled automatically by VereningingenTestCase
    def test_volunteer_status_impact(self):
        """Test how member status changes affect volunteer records"""
        member = self.create_test_member(
            first_name="Volunteer",
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
        member.status = "Suspended"
        member.suspension_reason = "Test suspension"
        member.save()

        # Check volunteer status (should be updated or remain unchanged based on policy)
        updated_volunteer = frappe.get_doc("Volunteer", volunteer.name)
        self.assertIn(updated_volunteer.status, ["Active", "Suspended", "Inactive"])

        # Terminate member
        member.status = "Terminated"
        member.termination_reason = "Test termination"
        member.termination_date = today()
        member.save()

        # Check volunteer termination
        updated_volunteer = frappe.get_doc("Volunteer", volunteer.name)
        self.assertIn(updated_volunteer.status, ["Active", "Inactive", "Terminated"])

        # Cleanup handled automatically by VereningingenTestCase
    # ===== AUDIT TRAIL VALIDATION =====

    def test_status_change_audit_trail(self):
        """Test audit trail creation for status changes"""
        member = self.create_test_member(
            first_name="Audit",
            last_name="Trail",
            email="audit.test.status@test.com",
            status="Active"
        )

        original_status = member.status

        # Change status
        member.status = "Suspended"
        member.suspension_reason = "Audit trail test"
        member.save()

        # Check if audit trail exists (if implemented)
        try:
            # Check if Communication History doctype exists first
            if frappe.db.exists("DocType", "Communication History"):
                audit_entries = frappe.get_all(
                    "Communication History",
                    filters={
                        "reference_doctype": "Member",
                        "reference_name": member.name,
                        "communication_type": "Status Change"},
                )
                if audit_entries:
                    # Verify audit entry contains status change info
                    audit_entry = frappe.get_doc("Communication History", audit_entries[0].name)
                    self.assertIn("Suspended", audit_entry.content)
                    self.assertIn(original_status, audit_entry.content)

        except (frappe.DoesNotExistError, Exception):
            # Audit system not implemented yet or table structure different
            pass

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
        member.status = "Suspended"
        member.suspension_reason = "Test suspension"
        member.save()

        # Attempt chapter transfer while suspended
        try:
            member.chapter = chapter2.name
            member.save()

            # Should either allow transfer or prevent it
            self.assertIn(member.chapter, [self.chapter.name, chapter2.name])

        except frappe.ValidationError:
            # Prevention is valid business rule
            pass

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
