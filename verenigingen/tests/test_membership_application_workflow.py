"""
Test Membership Application Workflow
"""
import frappe
import unittest
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMembershipApplicationWorkflow(VereningingenTestCase):
    """Test membership application workflow states and transitions"""

    def setUp(self):
        super().setUp()
        # Ensure workflow is active
        if not frappe.db.exists("Workflow", "Membership Application Workflow"):
            # Create workflow if it doesn't exist
            from verenigingen.setup.membership_application_workflow_setup import setup_membership_application_workflow
            setup_membership_application_workflow()

    def test_workflow_exists(self):
        """Test that the membership application workflow exists"""
        workflow = frappe.get_doc("Workflow", "Membership Application Workflow")
        self.assertEqual(workflow.document_type, "Member")
        self.assertEqual(workflow.workflow_state_field, "application_status")
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
        
        # Set initial state
        member.application_status = "Pending"
        member.save()
        
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


if __name__ == "__main__":
    unittest.main()