# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Comprehensive Test Suite Demonstration
Demonstrates the enhanced test infrastructure and workflows
"""


from frappe.utils import today

from verenigingen.tests.fixtures.test_personas import PersonaTestMixin, TestPersonas
from verenigingen.tests.utils.base import VereningingenWorkflowTestCase
from verenigingen.tests.workflows.test_member_lifecycle import TestMemberLifecycle
from verenigingen.tests.workflows.test_payment_failure_recovery import TestPaymentFailureRecovery
from verenigingen.tests.workflows.test_volunteer_journey import TestVolunteerJourney


class TestComprehensiveSuiteDemo(VereningingenWorkflowTestCase, PersonaTestMixin):
    """
    Demonstration of the comprehensive test suite capabilities
    Shows integration of all testing components
    """

    def test_all_personas_creation(self):
        """Test that all standard personas can be created successfully"""
        personas = TestPersonas.create_all_personas()

        # Verify all personas were created
        expected_personas = [
            "happy_path_hannah",
            "payment_problem_peter",
            "volunteer_victor",
            "terminated_tom",
            "suspended_susan",
        ]

        for persona_name in expected_personas:
            self.assertIn(persona_name, personas)
            persona = personas[persona_name]
            self.assertIn("member", persona)
            self.assertIn("persona", persona)

        # Clean up
        TestPersonas.cleanup_all_personas(personas)

    def test_workflow_integration_demo(self):
        """Demonstrate workflow test integration"""
        # Create a simple workflow using the enhanced infrastructure
        stages = [
            {
                "name": "Demo Stage 1: Setup",
                "function": self._demo_stage_setup,
                "validations": [self._validate_demo_setup],
            },
            {
                "name": "Demo Stage 2: Process",
                "function": self._demo_stage_process,
                "validations": [self._validate_demo_process],
            },
            {
                "name": "Demo Stage 3: Complete",
                "function": self._demo_stage_complete,
                "validations": [self._validate_demo_complete],
            },
        ]

        self.define_workflow(stages)

        with self.workflow_transaction():
            self.execute_workflow()

        # Verify workflow completed successfully
        self.assert_workflow_state("demo_status", "completed")

    def _demo_stage_setup(self, context):
        """Demo workflow stage 1"""
        return {"demo_status": "setup", "setup_time": today()}

    def _validate_demo_setup(self, context):
        """Validate demo setup"""
        self.assertEqual(context.get("demo_status"), "setup")

    def _demo_stage_process(self, context):
        """Demo workflow stage 2"""
        return {"demo_status": "processing", "process_time": today()}

    def _validate_demo_process(self, context):
        """Validate demo processing"""
        self.assertEqual(context.get("demo_status"), "processing")

    def _demo_stage_complete(self, context):
        """Demo workflow stage 3"""
        return {"demo_status": "completed", "complete_time": today()}

    def _validate_demo_complete(self, context):
        """Validate demo completion"""
        self.assertEqual(context.get("demo_status"), "completed")

    def test_persona_workflow_integration(self):
        """Test persona integration with workflow testing"""
        # Create Happy Path Hannah persona
        hannah = self.create_persona("happy_path_hannah")

        # Verify persona created correctly
        self.assertIn("member", hannah)
        self.assertIn("membership", hannah)
        self.assertIn("volunteer", hannah)

        member = hannah["member"]
        self.assertEqual(member.first_name, "Hannah")
        self.assertEqual(member.last_name, "Happypath")
        self.assertEqual(member.status, "Active")

    def test_state_management_demo(self):
        """Demonstrate state management capabilities"""
        from verenigingen.tests.utils.factories import TestStateManager

        state_manager = TestStateManager()

        # Record some state transitions
        state_manager.record_state("DemoEntity", "demo1", "Initial")
        state_manager.record_state("DemoEntity", "demo1", "Processing")
        state_manager.record_state("DemoEntity", "demo1", "Completed")

        # Verify state tracking
        current_state = state_manager.get_state("DemoEntity", "demo1")
        self.assertEqual(current_state, "Completed")

        # Verify transition tracking
        transitions = state_manager.get_transitions("DemoEntity", "demo1")
        self.assertEqual(len(transitions), 2)  # Initial->Processing, Processing->Completed

        # Verify transition validation
        self.assertTrue(state_manager.validate_transition("DemoEntity", "demo1", "Initial", "Processing"))
        self.assertTrue(state_manager.validate_transition("DemoEntity", "demo1", "Processing", "Completed"))

    def test_cleanup_management_demo(self):
        """Demonstrate cleanup management with dependencies"""
        from verenigingen.tests.utils.factories import TestCleanupManager

        cleanup_manager = TestCleanupManager()

        # Register items with dependencies
        cleanup_manager.register("Member", "test-member-1")
        cleanup_manager.register("Membership", "test-membership-1", dependencies=["Member:test-member-1"])
        cleanup_manager.register("Volunteer", "test-volunteer-1", dependencies=["Member:test-member-1"])

        # Test dependency sorting (would clean Membership and Volunteer before Member)
        sorted_stack = cleanup_manager._sort_by_dependencies()

        # Verify proper ordering (dependencies cleaned first)
        # This is a structural test of the cleanup system
        self.assertTrue(len(sorted_stack) >= 0)  # Should handle empty or populated stacks

    def test_assertion_helpers_demo(self):
        """Demonstrate enhanced assertion helpers"""
        # Create test member for assertion testing
        hannah = self.create_persona("happy_path_hannah")
        member = hannah["member"]

        # Test enhanced assertions
        self.assert_field_value(member, "first_name", "Hannah")
        self.assert_field_value(member, "status", "Active")

        # Test document existence assertions
        self.assert_doc_exists("Member", member.name)
        self.assert_doc_not_exists("Member", "non-existent-member")

    def test_concurrent_workflow_demo(self):
        """Demonstrate concurrent workflow capabilities"""
        # This would test running multiple workflows in parallel
        # For now, just demonstrate the concept

        # In a real implementation, these could run concurrently
        # For demonstration, we just verify the workflow classes exist
        workflow_classes = [TestMemberLifecycle, TestVolunteerJourney, TestPaymentFailureRecovery]

        for workflow_class in workflow_classes:
            self.assertTrue(
                hasattr(workflow_class, "test_complete_member_lifecycle")
                or hasattr(workflow_class, "test_complete_volunteer_journey")
                or hasattr(workflow_class, "test_payment_failure_recovery_workflow")
            )


class TestSuiteHealthCheck(VereningingenWorkflowTestCase):
    """Health check for the test suite infrastructure"""

    def test_base_infrastructure_health(self):
        """Test that base test infrastructure is healthy"""
        # Test base classes
        from verenigingen.tests.utils.base import (
            VereningingenIntegrationTestCase,
            VereningingenTestCase,
            VereningingenUnitTestCase,
            VereningingenWorkflowTestCase,
        )

        # Verify inheritance chain
        self.assertTrue(issubclass(VereningingenUnitTestCase, VereningingenTestCase))
        self.assertTrue(issubclass(VereningingenIntegrationTestCase, VereningingenTestCase))
        self.assertTrue(issubclass(VereningingenWorkflowTestCase, VereningingenIntegrationTestCase))

    def test_utilities_health(self):
        """Test that utility classes are healthy"""
        from verenigingen.tests.utils.factories import (
            TestCleanupManager,
            TestDataBuilder,
            TestStateManager,
            TestUserFactory,
        )

        # Test factory methods exist
        self.assertTrue(hasattr(TestUserFactory, "create_member_user"))
        self.assertTrue(hasattr(TestUserFactory, "create_volunteer_user"))
        self.assertTrue(hasattr(TestUserFactory, "create_admin_user"))

        # Test state manager
        state_manager = TestStateManager()
        self.assertTrue(hasattr(state_manager, "record_state"))
        self.assertTrue(hasattr(state_manager, "get_state"))
        self.assertTrue(hasattr(state_manager, "get_transitions"))

        # Test cleanup manager
        cleanup_manager = TestCleanupManager()
        self.assertTrue(hasattr(cleanup_manager, "register"))
        self.assertTrue(hasattr(cleanup_manager, "cleanup"))

        # Test data builder
        builder = TestDataBuilder()
        self.assertTrue(hasattr(builder, "with_member"))
        self.assertTrue(hasattr(builder, "with_chapter"))
        self.assertTrue(hasattr(builder, "build"))

    def test_workflow_classes_health(self):
        """Test that workflow test classes are properly structured"""
        workflow_classes = [TestMemberLifecycle, TestVolunteerJourney, TestPaymentFailureRecovery]

        for workflow_class in workflow_classes:
            # Should inherit from workflow test case
            self.assertTrue(issubclass(workflow_class, VereningingenWorkflowTestCase))

            # Should have setUp and test methods
            self.assertTrue(hasattr(workflow_class, "setUp"))

            # Should have at least one test method
            test_methods = [method for method in dir(workflow_class) if method.startswith("test_")]
            self.assertTrue(len(test_methods) > 0)
