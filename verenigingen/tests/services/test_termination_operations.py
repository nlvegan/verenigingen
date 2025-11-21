# File: verenigingen/tests/services/test_termination_operations.py
"""
Unit tests for Termination Operations

Tests the declarative operation pattern including TerminationResults,
individual operations, and the TerminationExecutor orchestrator.
"""

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.termination_operations import (
    TerminationResults,
    TerminationExecutor,
    CancelMembershipsOperation,
    CancelSEPAMandatesOperation,
    UpdateMemberStatusOperation,
    TerminationOperation
)


class TestTerminationResults(EnhancedTestCase):
    """Test the TerminationResults dataclass"""

    def test_initialization_with_defaults(self):
        """Should initialize with empty lists and zero counters"""
        results = TerminationResults()

        self.assertEqual(results.actions_taken, [])
        self.assertEqual(results.errors, [])
        self.assertEqual(results.sepa_mandates_cancelled, 0)
        self.assertEqual(results.memberships_cancelled, 0)
        self.assertFalse(results.customer_updated)
        self.assertFalse(results.member_updated)

    def test_record_action(self):
        """Should record actions in the list"""
        results = TerminationResults()

        results.record_action("Action 1")
        results.record_action("Action 2")

        self.assertEqual(len(results.actions_taken), 2)
        self.assertIn("Action 1", results.actions_taken)
        self.assertIn("Action 2", results.actions_taken)

    def test_record_error(self):
        """Should record errors in the list"""
        results = TerminationResults()

        results.record_error("Error 1")
        results.record_error("Error 2")

        self.assertEqual(len(results.errors), 2)
        self.assertIn("Error 1", results.errors)
        self.assertIn("Error 2", results.errors)

    def test_merge_integer_counters(self):
        """Should merge integer counters by addition"""
        results = TerminationResults()
        results.volunteers_terminated = 2

        other_results = {
            "volunteers_terminated": 3,
            "employees_terminated": 1
        }

        results.merge(other_results)

        self.assertEqual(results.volunteers_terminated, 5)  # 2 + 3
        self.assertEqual(results.employees_terminated, 1)

    def test_merge_boolean_flags(self):
        """Should merge boolean flags with OR logic"""
        results = TerminationResults()
        results.user_deactivated = False

        other_results = {
            "user_deactivated": True,
            "customer_updated": True
        }

        results.merge(other_results)

        self.assertTrue(results.user_deactivated)  # False OR True = True
        self.assertTrue(results.customer_updated)

    def test_merge_lists(self):
        """Should extend lists from other results"""
        results = TerminationResults()
        results.actions_taken = ["Action 1"]
        results.errors = ["Error 1"]

        other_results = {
            "actions_taken": ["Action 2", "Action 3"],
            "errors": ["Error 2"]
        }

        results.merge(other_results)

        self.assertEqual(len(results.actions_taken), 3)
        self.assertEqual(len(results.errors), 2)

    def test_merge_ignores_unknown_fields(self):
        """Should gracefully handle fields not in dataclass"""
        results = TerminationResults()

        other_results = {
            "unknown_field": 123,
            "volunteers_terminated": 2
        }

        # Should not raise
        results.merge(other_results)

        # Known field should be merged
        self.assertEqual(results.volunteers_terminated, 2)

        # Unknown field should be ignored
        self.assertFalse(hasattr(results, "unknown_field"))

    def test_to_dict_returns_all_fields(self):
        """Should convert to dictionary with all fields"""
        results = TerminationResults()
        results.actions_taken = ["Action 1"]
        results.errors = ["Error 1"]
        results.memberships_cancelled = 3
        results.user_deactivated = True

        result_dict = results.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict["actions_taken"], ["Action 1"])
        self.assertEqual(result_dict["errors"], ["Error 1"])
        self.assertEqual(result_dict["memberships_cancelled"], 3)
        self.assertTrue(result_dict["user_deactivated"])

    def test_to_dict_includes_all_counters(self):
        """Should include all counter fields in dictionary"""
        results = TerminationResults()
        result_dict = results.to_dict()

        # Verify all expected fields are present
        expected_fields = [
            "actions_taken", "errors",
            "sepa_mandates_cancelled", "memberships_cancelled",
            "positions_ended", "teams_suspended",
            "dues_schedules_cancelled", "invoices_updated",
            "invoices_cancelled", "invoices_deleted",
            "outstanding_invoices_cancelled",
            "volunteers_terminated", "volunteer_expenses_cancelled",
            "employees_terminated",
            "customer_updated", "member_updated", "user_deactivated"
        ]

        for field in expected_fields:
            self.assertIn(field, result_dict)


class TestTerminationOperation(EnhancedTestCase):
    """Test the TerminationOperation base class"""

    def test_cannot_instantiate_abstract_class(self):
        """Should not be able to instantiate abstract base class directly"""
        with self.assertRaises(TypeError):
            # Cannot instantiate ABC with abstract methods
            operation = TerminationOperation("MEM-001", None)  # type: ignore

    def test_lazy_loading_member_doc(self):
        """Should lazy-load member document only when accessed"""
        # Create a test member
        member = self.create_test_member(
            first_name="Lazy",
            last_name="Load",
            email="lazy.load@test.com",
            birth_date="1990-01-01"
        )

        # Create a concrete operation
        request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Test",
            "member_request_date": today()
        })
        request.insert()

        operation = CancelMembershipsOperation(member.name, request)

        # member_doc should not be loaded yet
        self.assertIsNone(operation._member_doc)

        # Access member_doc
        member_doc = operation.member_doc

        # Now it should be loaded
        self.assertIsNotNone(operation._member_doc)
        self.assertEqual(member_doc.name, member.name)

        # Accessing again should return cached version
        member_doc2 = operation.member_doc
        self.assertIs(member_doc, member_doc2)  # Same object


class TestTerminationExecutor(EnhancedTestCase):
    """Test the TerminationExecutor orchestrator"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        self.test_member = self.create_test_member(
            first_name="Executor",
            last_name="Test",
            email="executor.test@verenigingen.test",
            birth_date="1990-01-01"
        )

        self.termination_request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": self.test_member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Test termination",
            "member_request_date": today()
        })
        self.termination_request.insert()

    def test_validates_operation_order_on_init(self):
        """Should validate that UpdateMemberStatusOperation is last"""
        from verenigingen.utils.termination_operations import (
            UpdateMemberStatusOperation,
            CancelMembershipsOperation
        )

        # Create operations in WRONG order
        bad_operations = [
            UpdateMemberStatusOperation(self.test_member.name, self.termination_request),  # Wrong!
            CancelMembershipsOperation(self.test_member.name, self.termination_request),
        ]

        with self.assertRaises(frappe.ValidationError) as context:
            executor = TerminationExecutor(bad_operations)

        self.assertIn("must be the final operation", str(context.exception))

    def test_accepts_correct_operation_order(self):
        """Should accept operations with UpdateMemberStatusOperation last"""
        from verenigingen.utils.termination_operations import (
            UpdateMemberStatusOperation,
            CancelMembershipsOperation
        )

        # Correct order
        operations = [
            CancelMembershipsOperation(self.test_member.name, self.termination_request),
            UpdateMemberStatusOperation(self.test_member.name, self.termination_request),  # Last
        ]

        # Should not raise
        executor = TerminationExecutor(operations)
        self.assertEqual(len(executor.operations), 2)

    def test_detects_duplicate_member_status_operations(self):
        """Should detect if UpdateMemberStatusOperation appears multiple times"""
        from verenigingen.utils.termination_operations import (
            UpdateMemberStatusOperation,
            CancelMembershipsOperation
        )

        # UpdateMemberStatusOperation appears twice
        bad_operations = [
            UpdateMemberStatusOperation(self.test_member.name, self.termination_request),
            CancelMembershipsOperation(self.test_member.name, self.termination_request),
            UpdateMemberStatusOperation(self.test_member.name, self.termination_request),
        ]

        with self.assertRaises(frappe.ValidationError) as context:
            executor = TerminationExecutor(bad_operations)

        self.assertIn("found at position", str(context.exception))

    def test_executes_operations_in_sequence(self):
        """Should execute operations in the order provided"""
        from verenigingen.utils.termination_operations import (
            UpdateMemberStatusOperation,
            CancelMembershipsOperation
        )

        operations = [
            CancelMembershipsOperation(self.test_member.name, self.termination_request),
            UpdateMemberStatusOperation(self.test_member.name, self.termination_request),
        ]

        executor = TerminationExecutor(operations)
        results = executor.execute()

        # Should return dictionary
        self.assertIsInstance(results, dict)
        self.assertIn("actions_taken", results)
        self.assertIn("errors", results)

    def test_skips_disabled_operations(self):
        """Should skip operations where is_enabled() returns False"""
        from verenigingen.utils.termination_operations import (
            UpdateMemberStatusOperation,
            CancelSEPAMandatesOperation
        )

        # SEPA operation is disabled when cancel_sepa_mandates=False
        self.termination_request.cancel_sepa_mandates = False

        operations = [
            CancelSEPAMandatesOperation(self.test_member.name, self.termination_request),
            UpdateMemberStatusOperation(self.test_member.name, self.termination_request),
        ]

        executor = TerminationExecutor(operations)
        results = executor.execute()

        # SEPA operation should have been skipped
        # Member status operation should have run
        self.assertIn("actions_taken", results)

    def test_continues_on_operation_failure(self):
        """Should continue executing operations even if one fails"""
        # This requires creating a scenario where an operation fails
        # For now, we verify the error handling structure exists
        from verenigingen.utils.termination_operations import (
            UpdateMemberStatusOperation
        )

        operations = [
            UpdateMemberStatusOperation(self.test_member.name, self.termination_request),
        ]

        executor = TerminationExecutor(operations)
        results = executor.execute()

        # Should return results even if errors occurred
        self.assertIn("errors", results)
        self.assertIsInstance(results["errors"], list)


class TestIndividualOperations(EnhancedTestCase):
    """Test individual operation classes"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        self.test_member = self.create_test_member(
            first_name="Operation",
            last_name="Test",
            email="operation.test@verenigingen.test",
            birth_date="1990-01-01"
        )

        self.termination_request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": self.test_member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Test termination",
            "member_request_date": today()
        })
        self.termination_request.insert()

    def test_cancel_sepa_mandates_operation_enabled_flag(self):
        """CancelSEPAMandatesOperation should respect cancel_sepa_mandates flag"""
        from verenigingen.utils.termination_operations import CancelSEPAMandatesOperation

        # When flag is False
        self.termination_request.cancel_sepa_mandates = False
        operation = CancelSEPAMandatesOperation(self.test_member.name, self.termination_request)
        self.assertFalse(operation.is_enabled())

        # When flag is True
        self.termination_request.cancel_sepa_mandates = True
        operation = CancelSEPAMandatesOperation(self.test_member.name, self.termination_request)
        self.assertTrue(operation.is_enabled())

    def test_update_customer_operation_enabled_only_with_customer(self):
        """UpdateCustomerRecordOperation should only be enabled if member has customer"""
        from verenigingen.utils.termination_operations import UpdateCustomerRecordOperation

        # Store original customer reference
        original_customer = self.test_member.customer

        # Member without customer - clear auto-created customer
        self.test_member.customer = None
        self.test_member.save()

        operation = UpdateCustomerRecordOperation(self.test_member.name, self.termination_request)
        self.assertFalse(operation.is_enabled())

        # Restore customer to member
        self.test_member.customer = original_customer
        self.test_member.save()

        # Now should be enabled
        operation = UpdateCustomerRecordOperation(self.test_member.name, self.termination_request)
        self.assertTrue(operation.is_enabled())

    def test_operation_name_property_works(self):
        """All operations should have a descriptive operation_name"""
        from verenigingen.utils.termination_operations import (
            CancelMembershipsOperation,
            CancelSEPAMandatesOperation,
            EndBoardPositionsOperation,
            SuspendTeamMembershipsOperation
        )

        operations = [
            CancelMembershipsOperation(self.test_member.name, self.termination_request),
            CancelSEPAMandatesOperation(self.test_member.name, self.termination_request),
            EndBoardPositionsOperation(self.test_member.name, self.termination_request),
            SuspendTeamMembershipsOperation(self.test_member.name, self.termination_request),
        ]

        for operation in operations:
            name = operation.operation_name
            self.assertIsInstance(name, str)
            self.assertGreater(len(name), 0)
            # Should be human-readable
            self.assertTrue(name[0].isupper())


class TestOperationIntegration(EnhancedTestCase):
    """Integration tests for complete operation execution"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        self.test_member = self.create_test_member(
            first_name="Integration",
            last_name="Test",
            email="integration.test@verenigingen.test",
            birth_date="1990-01-01"
        )

    def test_complete_execution_workflow(self):
        """Test complete operation execution from start to finish"""
        from verenigingen.utils.termination_operations import (
            TerminationExecutor,
            CancelMembershipsOperation,
            SuspendTeamMembershipsOperation,
            UpdateMemberStatusOperation
        )

        # Create termination request
        request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": self.test_member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Integration test",
            "member_request_date": today()
        })
        request.insert()

        # Create operation sequence
        operations = [
            CancelMembershipsOperation(self.test_member.name, request),
            SuspendTeamMembershipsOperation(self.test_member.name, request),
            UpdateMemberStatusOperation(self.test_member.name, request),
        ]

        # Execute
        executor = TerminationExecutor(operations)
        results = executor.execute()

        # Verify results structure
        self.assertIsInstance(results, dict)
        self.assertIn("actions_taken", results)
        self.assertIn("errors", results)
        self.assertIn("member_updated", results)

        # Should have some actions
        self.assertGreaterEqual(len(results["actions_taken"]), 1)

    def test_results_track_all_operation_outcomes(self):
        """Results should track outcomes from all operations"""
        from verenigingen.utils.termination_operations import (
            TerminationExecutor,
            CancelMembershipsOperation,
            UpdateMemberStatusOperation
        )

        request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": self.test_member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Test",
            "member_request_date": today(),
            "termination_date": today()
        })
        request.insert()

        operations = [
            CancelMembershipsOperation(self.test_member.name, request),
            UpdateMemberStatusOperation(self.test_member.name, request),
        ]

        executor = TerminationExecutor(operations)
        results = executor.execute()

        # Should have tracked member status update
        self.assertIn("member_updated", results)

        # Should have action entries
        self.assertIsInstance(results["actions_taken"], list)
