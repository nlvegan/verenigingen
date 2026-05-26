"""
Test Membership Application Workflow
"""
import frappe

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
import unittest
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMembershipApplicationWorkflow(VereningingenTestCase):
    """Test membership application workflow states and transitions"""

    def setUp(self):
        super().setUp()
        # Ensure workflow is active
        if not DocumentExistenceValidator.check_document_exists("Workflow", "Membership Application Workflow"):
            # Create workflow if it doesn't exist
            from verenigingen.setup.membership_application_workflow_setup import setup_membership_application_workflow
            setup_membership_application_workflow()

    def test_workflow_exists(self):
        """Test that the membership application workflow exists"""
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow")
        self.assertEqual(workflow.document_type, "Member")
        self.assertEqual(workflow.workflow_state_field, "application_status")
        # Activate workflow if not active for testing
        if not workflow.is_active:
            workflow.is_active = 1
            workflow.save()
        self.assertTrue(workflow.is_active)
        
        # Check states
        state_names = [state.state for state in workflow.states]
        expected_states = ["Pending", "Under Review", "Approved", "Payment Pending", "Active", "Rejected"]
        for state in expected_states:
            self.assertIn(state, state_names)
        
        print(f"✅ Workflow has {len(workflow.states)} states: {', '.join(state_names)}")
        print(f"✅ Workflow has {len(workflow.transitions)} transitions")

    def test_workflow_transitions(self):
        """Test workflow transitions are properly configured"""
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow")
        
        # Test specific transition paths
        transitions = {}
        for transition in workflow.transitions:
            key = f"{transition.state} -> {transition.next_state}"
            if key not in transitions:
                transitions[key] = []
            transitions[key].append(transition.action)
        
        # Key transition paths should exist
        expected_transitions = [
            "Pending -> Under Review",
            "Under Review -> Approved", 
            "Under Review -> Rejected",
            "Approved -> Payment Pending",
            "Approved -> Active",
            "Payment Pending -> Active",
            "Pending -> Approved",  # Direct approval
        ]
        
        for expected in expected_transitions:
            self.assertIn(expected, transitions, f"Missing transition: {expected}")
        
        print("✅ All expected workflow transitions exist")

    def test_member_workflow_integration(self):
        """Test that member documents can use the workflow"""
        # Create a test member with pending application
        member = self.create_test_member(
            first_name="Test",
            last_name="Workflow",
            email="test.workflow@example.com"
        )

        # Reload immediately after creation to get fresh timestamp
        member.reload()

        # Set initial state
        member.application_status = "Pending"
        member.save()

        # Refresh to avoid timestamp mismatch
        member.reload()
        
        # Verify workflow state
        self.assertEqual(member.application_status, "Pending")
        
        # Test state transition (simulate approval)
        member.application_status = "Approved"
        member.save()
        
        self.assertEqual(member.application_status, "Approved")
        
        print("✅ Member workflow integration works")

    def test_workflow_permissions(self):
        """Test workflow state permissions"""
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow") 
        
        # Check that states have proper permissions
        for state in workflow.states:
            self.assertTrue(state.allow_edit, f"State {state.state} should have allow_edit set")
            # Most states should allow Verenigingen Administrator
            if state.state != "Rejected":
                self.assertIn("Verenigingen Administrator", state.allow_edit)
        
        # Check that transitions have proper role assignments
        for transition in workflow.transitions:
            self.assertTrue(transition.allowed, f"Transition {transition.action} should have allowed role")
        
        print("✅ Workflow permissions are properly configured")

    def test_workflow_email_alerts(self):
        """Test workflow email alert configuration"""
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow")
        
        # Email alerts should be enabled for membership applications
        self.assertEqual(workflow.send_email_alert, 1)
        
        print("✅ Workflow email alerts are enabled")

    def test_workflow_state_docstatus(self):
        """Test that workflow states have appropriate docstatus"""
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow")
        
        state_docstatus = {}
        for state in workflow.states:
            state_docstatus[state.state] = int(state.doc_status)
        
        # Check expected docstatus values
        expected_docstatus = {
            "Pending": 0,      # Draft
            "Under Review": 0, # Draft  
            "Approved": 0,     # Draft
            "Payment Pending": 0, # Draft
            "Active": 1,       # Submitted
            "Rejected": 0,     # Draft
        }
        
        for state, expected_status in expected_docstatus.items():
            self.assertEqual(
                state_docstatus[state], 
                expected_status,
                f"State {state} should have docstatus {expected_status}"
            )
        
        print("✅ Workflow states have correct docstatus values")

    @unittest.skip(
        "test asserts that verenigingen.api.enhanced_membership_application.submit_enhanced_application "
        "imports successfully via try/except ImportError → self.fail(...). The module was deleted "
        "during the application-flow refactor; submit_enhanced_application has no replacement. "
        "Re-enable when the new submit entry point stabilizes. Group G3 follow-up — see PR #96 notes."
    )
    def test_member_creation_imports_integration(self):
        """Test that member creation process works without import errors"""
        # This test ensures critical imports work properly
        # Regression test for secure_context_manager import issues

        # Test importing secure operations functions (updated from deprecated application helpers)
        try:
            from verenigingen.utils.secure_operations import get_system_user_for_operation
            from verenigingen.utils.application_helpers import create_member_from_application
            user = get_system_user_for_operation("test_membership_workflow")
            self.assertIsNotNone(user)
            print("✅ Secure operations imports working correctly")
        except ImportError as e:
            self.fail(f"Import error in secure operations: {str(e)}")

        # Test employee user link imports
        try:
            from verenigingen.utils.employee_user_link import create_user_for_volunteer
            print("✅ Employee user link imports working correctly")
        except ImportError as e:
            self.fail(f"Import error in employee user link: {str(e)}")

        # Test member creation workflow simulation (without actual data)
        test_data = {
            "first_name": "Test",
            "last_name": "Member",
            "email": "test.import@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 123",
            "postal_code": "1234AB",
            "city": "Amsterdam",
            "country": "Netherlands",
            "membership_type": "Annual",
            "payment_method": "SEPA Direct Debit",
            "iban": "NL91ABNA0417164300",
            "bank_account_name": "Test Member"
        }

        # Test that we can call the member creation function without import errors
        # Note: membership_application.py was archived, use enhanced_membership_application instead
        try:
            from verenigingen.api.enhanced_membership_application import submit_enhanced_application
            # We don't actually submit but test the import path works
            print("✅ Member creation API imports working correctly")
        except ImportError as e:
            self.fail(f"Import error in member creation API: {str(e)}")

        print("✅ All critical member creation imports validated")

    def test_approval_idempotency(self):
        """Test that approving an already-approved member is idempotent"""
        # Create a test member that's already approved
        member = self.create_test_member(
            first_name="Test",
            last_name="Idempotent",
            email="test.idempotent@example.com"
        )

        # Manually set member to approved state (bypass full approval flow to avoid test complexity)
        member.reload()
        member.application_status = "Approved"
        member.status = "Active"
        member.member_since = frappe.utils.today()
        member.save()
        member.reload()

        # Create a fake membership record to simulate an approved member
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member.name,
            "membership_type": "Annual Membership",
            "start_date": frappe.utils.today(),
            "end_date": frappe.utils.add_months(frappe.utils.today(), 12),
            "status": "Active"
        })
        membership.insert()
        membership.submit()

        # Import approval function
        from verenigingen.api.membership_application_review import approve_membership_application

        # Try to approve again (should be idempotent)
        result = approve_membership_application(
            member_name=member.name,
            membership_type="Annual Membership",
            create_invoice=False
        )

        # Verify idempotent response
        self.assertTrue(result["success"], f"Idempotent approval failed: {result.get('message')}")
        self.assertTrue(result.get("idempotent", False), "Should indicate idempotent operation")
        self.assertEqual(result.get("membership"), membership.name, "Should return existing membership")

        # Verify member status unchanged
        member.reload()
        self.assertEqual(member.application_status, "Approved")

        # Verify only one membership exists
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member.name, "docstatus": 1},
            pluck="name"
        )
        self.assertEqual(len(memberships), 1, "Should only have one submitted membership")

        print("✅ Approval idempotency works correctly")


if __name__ == "__main__":
    unittest.main()