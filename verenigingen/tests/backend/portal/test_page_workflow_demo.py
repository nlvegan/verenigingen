"""
Tests for the /workflow_demo page controller
(verenigingen.templates.pages.workflow_demo).

The page demonstrates the Membership Application Workflow. get_context requires
Member read permission and tolerates the workflow being absent. The page also
exposes get_workflow_actions and execute_workflow_action (Member write).
"""

import frappe

from verenigingen.templates.pages import workflow_demo as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageWorkflowDemo(EnhancedTestCase):
    """Exercise the workflow demo page controller."""

    WORKFLOW = "Membership Application Workflow"

    def test_get_context_member_read_required(self):
        """A user without Member read permission is rejected."""
        with self.as_role("Verenigingen Volunteer"):
            if frappe.has_permission("Member", "read"):
                self.skipTest("Volunteer unexpectedly has Member read on this site")
            # Controller uses a bare frappe.throw() → frappe.ValidationError.
            with self.assertRaises(frappe.ValidationError) as ctx:
                page.get_context(frappe._dict())
            self.assertIn("permission to view this page", str(ctx.exception))

    def test_get_context_populates_workflow_and_samples(self):
        """For a privileged user the context carries title, samples, and workflow flags."""
        # Create a real member so sample_members has data to read.
        self.create_test_member(
            first_name="WFDemo",
            last_name="Sample",
            email=f"wfdemo.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
        )

        with self.as_admin_role():
            context = frappe._dict()
            result = page.get_context(context)

        self.assertIs(result, context)
        self.assertEqual(context.title, "Membership Application Workflow Demo")
        # sample_members is always a list (the controller falls back to [] on error).
        self.assertIsInstance(context.sample_members, list)
        # workflow_exists is a bool reflecting whether the workflow doc is installed.
        self.assertIn(context.workflow_exists, (True, False))

        if context.workflow_exists:
            # When present, states/transitions/stats are derived from the workflow doc.
            self.assertIsInstance(context.workflow_states, list)
            self.assertIsInstance(context.workflow_transitions, list)
            self.assertIsInstance(context.workflow_stats, dict)
        else:
            # Absent → controller sets a translated error message.
            self.assertTrue(context.error_message)

    def test_get_workflow_actions_requires_member_write(self):
        """get_workflow_actions throws for a user without Member write.

        Note: the controller uses a bare frappe.throw() for the permission
        failure, which raises frappe.ValidationError (not PermissionError).
        We assert the documented message to pin the behavior precisely.
        """
        member = self.create_test_member(
            first_name="WFActions",
            last_name="NoWrite",
            email=f"wfactions.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
        )
        with self.as_role("Verenigingen Volunteer"):
            if frappe.has_permission("Member", "write"):
                self.skipTest("Volunteer unexpectedly has Member write on this site")
            with self.assertRaises(frappe.ValidationError) as ctx:
                page.get_workflow_actions(member.name)
            self.assertIn("permission to modify members", str(ctx.exception))

    def test_get_workflow_actions_returns_state_for_privileged_user(self):
        """For a privileged user the function reports the member's current state."""
        member = self.create_test_member(
            first_name="WFActions",
            last_name="Privileged",
            email=f"wfactions.priv.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
        )
        if not frappe.db.exists("Workflow", self.WORKFLOW):
            self.skipTest("Membership Application Workflow not installed on this site")

        with self.as_admin_role():
            result = page.get_workflow_actions(member.name)

        self.assertTrue(result["success"], result)
        # current_state mirrors the member's application_status.
        self.assertEqual(result["current_state"], member.application_status)
        self.assertIsInstance(result["available_actions"], list)

    def test_execute_workflow_action_changes_state(self):
        """execute_workflow_action updates application_status and records old/new states."""
        member = self.create_test_member(
            first_name="WFExec",
            last_name="Target",
            email=f"wfexec.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
        )
        old_state = member.application_status

        with self.as_admin_role():
            result = page.execute_workflow_action(member.name, "Approve", "Approved")

        self.assertTrue(result["success"], result)
        self.assertEqual(result["old_state"], old_state)
        self.assertEqual(result["new_state"], "Approved")

        # Verify the change was actually persisted to the database.
        self.assertEqual(frappe.db.get_value("Member", member.name, "application_status"), "Approved")

    def test_execute_workflow_action_requires_member_write(self):
        """execute_workflow_action throws for a user lacking Member write."""
        member = self.create_test_member(
            first_name="WFExec",
            last_name="Denied",
            email=f"wfexec.denied.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
        )
        with self.as_role("Verenigingen Volunteer"):
            if frappe.has_permission("Member", "write"):
                self.skipTest("Volunteer unexpectedly has Member write on this site")
            with self.assertRaises(frappe.ValidationError) as ctx:
                page.execute_workflow_action(member.name, "Approve", "Approved")
            self.assertIn("permission to modify members", str(ctx.exception))
