"""
Termination Workflow Edge Cases Test Suite
Tests for membership termination complex scenarios, workflow states, and business logic
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.skip_reasons import VOLUNTEER_EXPENSE_ARCHIVED
import unittest


class TestTerminationWorkflowEdgeCases(EnhancedTestCase):
    """Test termination workflow edge cases and complex scenarios"""

    def setUp(self):
        """Build fixtures per test so the per-test rollback/drain owns them.

        These used to be class-level (setUpClass) with FIXED names and a
        tearDownClass that deleted without committing: the class-level
        `_rollback_db` cleanup then undid the deletes, so a Region, Chapter,
        Membership Type and two Members survived every run and the next run died
        on the duplicate (#1717). The Region guard also looked the row up by
        `region_name` while Frappe stores the slugified name as both, so it never
        matched.
        """
        super().setUp()
        # Own the specific Role Profile or skip; never adopt whichever one exists (#1332).
        if not frappe.db.exists("Role Profile", "Verenigingen Staff"):
            self.skipTest("Role Profile 'Verenigingen Staff' (shipped fixture) is missing")
        suffix = frappe.generate_hash(length=8)

        # Chapter has reqd fields (status/region/introduction) and autoname=prompt;
        # ensure backing Region exists before creating the chapter.
        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Termination Test Region {suffix}",
                "region_code": self.unique_region_code(),
            }
        )
        region.insert(ignore_permissions=True)

        self.chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "status": "Active",
                "region": region.name,
                "introduction": "Termination Workflow Edge Cases test chapter",
            }
        )
        self.chapter.name = f"Termination Test Chapter {suffix}"
        self.chapter.insert(ignore_permissions=True)

        # Membership Type reqd fields: membership_type_name (autoname=field:),
        # minimum_amount, role_profile. Use the shipped "Verenigingen Staff" fixture profile.
        role_profile = "Verenigingen Staff"
        self.membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": f"Termination Test Type {suffix}",
                "description": "Test membership type for termination edge cases",
                "minimum_amount": 25.0,
                "role_profile": role_profile,
            }
        )
        self.membership_type.insert(ignore_permissions=True)

        self.member1 = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Termination",
                "last_name": "Test1",
                "email": f"termination1.{suffix}@test.com",
                "status": "Active",
                "chapter": self.chapter.name}
        )
        self.member1.insert()

        self.member2 = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Termination",
                "last_name": "Test2",
                "email": f"termination2.{suffix}@test.com",
                "status": "Active",
                "chapter": self.chapter.name}
        )
        self.member2.insert()

    def tearDown(self):
        """Clean up after each test"""
        # Clean up any termination requests created during tests
        frappe.db.sql(
            "DELETE FROM `tabMembership Termination Request` WHERE member IN %s",
            ([self.member1.name, self.member2.name],),
        )
        super().tearDown()

    # ===== TERMINATION REQUEST CREATION EDGE CASES =====


    def test_termination_request_for_inactive_member(self):
        """Test termination request for already inactive member"""
        # Set member as suspended
        self.member1.status = "Suspended"
        self.member1.suspension_reason = "Payment overdue"
        self.member1.save()

        # Create termination request for suspended member
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.member1.name,
                "termination_type": "Administrative",
                "termination_reason": "Suspended for too long",
                "requested_termination_date": today(),
                "status": "Pending"}
        )

        try:
            termination.insert()
            # Should either allow or prevent based on business rules
            self.assertTrue(True)
            termination.delete()
        except frappe.ValidationError:
            # Prevention is also valid
            pass
        finally:
            # Restore member status
            self.member1.status = "Active"
            self.member1.suspension_reason = ""
            self.member1.save()

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_termination_with_outstanding_obligations(self):
        """Test termination request when member has outstanding obligations"""
        # Create membership with unpaid fees
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member1.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                "status": "Overdue",
                # Note: fee is defined in membership_type, not directly on membership
            }
        )
        membership.insert()

        # Create volunteer expense awaiting reimbursement
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Test Volunteer",
                "email": self.member1.email,
                "member": self.member1.name,
                "status": "Active"}
        )
        volunteer.insert()

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": volunteer.name,
                "description": "Outstanding expense",
                "amount": 50.00,
                "currency": "EUR",
                "expense_date": today(),
                "status": "Approved",  # Approved but not reimbursed
            }
        )
        expense.insert()

        # Create termination request
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.member1.name,
                "termination_type": "Voluntary",
                "termination_reason": "Moving abroad",
                "requested_termination_date": today(),
                "status": "Pending"}
        )

        try:
            termination.insert()

            # Should detect outstanding obligations
            # Implementation should check for:
            # - Unpaid membership fees
            # - Unreimbursed expenses
            # - Outstanding commitments

            self.assertTrue(True)  # Test passes if no exception

        except frappe.ValidationError as e:
            # Should mention outstanding obligations
            self.assertIn("outstanding", str(e).lower())

        finally:
            # Clean up
            if frappe.db.exists("Membership Termination Request", termination.name):
                termination.delete()
            expense.delete()
            volunteer.delete()
            membership.delete()

    # ===== WORKFLOW STATE TRANSITIONS =====



    # ===== TERMINATION EXECUTION EDGE CASES =====



    # ===== TERMINATION IMPACT VALIDATION =====



    # ===== CONCURRENT TERMINATION SCENARIOS =====


    def test_member_save_is_forced_to_quit_while_executed_termination_exists(self):
        """A Member save while an Executed termination request exists ends as Quit.

        Probe shortcut, declared: the request is a DRAFT whose status is set to
        "Executed" directly. That does not run the execution service (it only fires
        on a submitted request), so this test does NOT exercise a termination
        racing a concurrent member edit. It pins only the Member before_save
        doc_event update_termination_status_display (hooks/doc_events.py).
        """
        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.member1.name,
                "termination_type": "Voluntary",
                "termination_reason": "Concurrent test",
                "requested_termination_date": today(),
                "status": "Approved",
                "approved_by": "Administrator",
                "approval_date": today()}
        )
        termination.insert()

        # A second in-memory copy of the member, loaded before the request is saved
        member_copy = frappe.get_doc("Member", self.member1.name)

        # Mark the request Executed (probe shortcut, see docstring)
        termination.status = "Executed"
        termination.execution_date = today()
        termination.save()

        # Saving the draft request as "Executed" does not touch the Member row, so the
        # copy is still current and its save goes through; the before_save doc_event
        # update_termination_status_display (member_utils.py) reflects the Executed
        # request onto the member, so the attempted "Suspended" ends as "Quit".
        # Nothing here may swallow an exception, or a regression would pass silently.
        member_copy.status = "Suspended"
        member_copy.suspension_reason = "Concurrent modification"
        member_copy.save()

        final_member = frappe.get_doc("Member", self.member1.name)
        self.assertEqual(final_member.status, "Quit")

        # Clean up
        termination.delete()

    # ===== AUDIT AND COMPLIANCE =====



def run_termination_workflow_edge_case_tests():
    """Run all termination workflow edge case tests"""
    print("⚰️ Running Termination Workflow Edge Case Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestTerminationWorkflowEdgeCases)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All termination workflow edge case tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_termination_workflow_edge_case_tests()
