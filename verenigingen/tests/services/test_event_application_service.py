# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for MijnRoodEventApplicationService application handlers.

Tests cover:
- _find_existing_member_or_conflict: member_id match, email match, email conflict, no match
- _set_application_fields: field mapping, member_id stringification, Mollie override, no-change
- _handle_division_field_change: field found, field not found, invalid division_id
- _apply_new_membership_application: idempotent, email conflict, email match
- _apply_changed_membership_application: approved guard, email conflict, no-change skip
- _apply_new_member: idempotency via _find_existing_member_or_conflict
- _check_and_handle_termination: status routing, auto-execution, execution failure
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.mijnrood_sync.services.event_application_service import (
    MijnRoodEventApplicationService,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFindExistingMemberOrConflict(EnhancedTestCase):
    """Tests for _find_existing_member_or_conflict()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_member_id_match_returns_success(self, mock_frappe):
        """When member_id matches an existing Member, return idempotent success."""
        mock_frappe.db.get_value.return_value = "MEM-001"
        mock_frappe._ = frappe._

        name, result = self.service._find_existing_member_or_conflict(42, "test@example.com")

        self.assertEqual(name, "MEM-001")
        self.assertTrue(result["success"])
        self.assertIn("member_id=42", result["message"])

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_email_match_no_conflict(self, mock_frappe):
        """When email matches and member_ids don't conflict, return success."""
        # member_id lookup returns None
        mock_frappe.db.get_value.side_effect = [
            None,  # member_id lookup
            frappe._dict({"name": "MEM-002", "member_id": None}),  # email lookup
        ]
        mock_frappe._ = frappe._

        name, result = self.service._find_existing_member_or_conflict(42, "test@example.com")

        self.assertEqual(name, "MEM-002")
        self.assertTrue(result["success"])
        self.assertIn("email=test@example.com", result["message"])

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_email_conflict_different_member_id(self, mock_frappe):
        """When email matches but member_id differs, return conflict error."""
        mock_frappe.db.get_value.side_effect = [
            None,  # member_id lookup
            frappe._dict({"name": "MEM-003", "member_id": "99"}),  # email lookup with different member_id
        ]
        mock_frappe._ = frappe._

        name, result = self.service._find_existing_member_or_conflict(42, "test@example.com")

        self.assertIsNone(name)
        self.assertFalse(result["success"])
        self.assertIn("conflicts", result["message"])

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_no_match_returns_none(self, mock_frappe):
        """When nothing matches, return (None, None)."""
        mock_frappe.db.get_value.side_effect = [None, None]
        mock_frappe._ = frappe._

        name, result = self.service._find_existing_member_or_conflict(42, "new@example.com")

        self.assertIsNone(name)
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_no_email_no_member_id(self, mock_frappe):
        """When both are None/empty, return (None, None) without DB calls."""
        name, result = self.service._find_existing_member_or_conflict(None, None)

        self.assertIsNone(name)
        self.assertIsNone(result)


class TestSetApplicationFields(EnhancedTestCase):
    """Tests for _set_application_fields()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_maps_fields_correctly(self):
        """Fields from row_data are mapped to member document."""
        member = MagicMock()
        member.get.return_value = None

        row_data = {
            "first_name": "Jan",
            "last_name": "de Vries",
            "email": "jan@example.com",
            "member_id": 42,
        }

        changed = self.service._set_application_fields(member, row_data)

        self.assertTrue(changed)
        # member_id should be stringified
        member.set.assert_any_call("member_id", "42")
        member.set.assert_any_call("first_name", "Jan")
        member.set.assert_any_call("last_name", "de Vries")
        member.set.assert_any_call("email", "jan@example.com")

    def test_no_change_when_values_match(self):
        """Returns False when all values already match."""
        member = MagicMock()
        # Return current values that match the row_data
        member.get.side_effect = lambda field: {
            "first_name": "Jan",
            "member_id": "42",
        }.get(field)

        row_data = {"first_name": "Jan", "member_id": 42}

        changed = self.service._set_application_fields(member, row_data)

        self.assertFalse(changed)
        member.set.assert_not_called()

    def test_mollie_override(self):
        """Mollie customer ID overrides payment method to 'Mollie'."""
        member = MagicMock()
        member.get.return_value = None
        member.mollie_customer_id = None

        row_data = {"custom_mollie_customer_id": "cus_abc123"}

        changed = self.service._set_application_fields(member, row_data)

        self.assertTrue(changed)
        self.assertEqual(member.mollie_customer_id, "cus_abc123")
        self.assertEqual(member.payment_method, "Mollie")

    def test_new_application_infers_bank_transfer(self):
        """For new applications, IBAN presence infers Bank Transfer."""
        member = MagicMock()
        member.get.return_value = None
        member.iban = "NL91ABNA0417164300"
        member.payment_method = None

        row_data = {"iban": "NL91ABNA0417164300"}

        self.service._set_application_fields(member, row_data, is_new=True)

        self.assertEqual(member.payment_method, "Bank Transfer")

    def test_skips_empty_values(self):
        """Empty/None values in row_data are skipped."""
        member = MagicMock()
        member.get.return_value = "Existing"

        row_data = {"first_name": "", "last_name": None, "email": "test@example.com"}

        self.service._set_application_fields(member, row_data)

        # first_name and last_name should not be set (empty/None)
        set_calls = {call.args[0] for call in member.set.call_args_list}
        self.assertNotIn("first_name", set_calls)
        self.assertNotIn("last_name", set_calls)


class TestHandleDivisionFieldChange(EnhancedTestCase):
    """Tests for _handle_division_field_change()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_returns_none_when_field_not_in_changes(self):
        """Returns None when the target field is not in changed_fields."""
        changed_fields = [{"field": "first_name", "old": "A", "new": "B"}]
        event = MagicMock()

        result = self.service._handle_division_field_change(
            "MEM-001", changed_fields, event, field_name="division_id"
        )

        self.assertIsNone(result)

    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    def test_delegates_to_assign_chapter(self, mock_assign):
        """When field found, delegates to _assign_chapter_from_division."""
        mock_assign.return_value = "Assigned to chapter 'Amsterdam'"
        changed_fields = [{"field": "division_id", "old": "1", "new": "2"}]
        event = MagicMock()

        result = self.service._handle_division_field_change(
            "MEM-001", changed_fields, event, field_name="division_id"
        )

        self.assertEqual(result, "Assigned to chapter 'Amsterdam'")
        mock_assign.assert_called_once_with("MEM-001", 2, event)

    def test_returns_none_for_invalid_division_id(self):
        """Returns None when new division_id is not a valid int."""
        changed_fields = [{"field": "division_id", "old": "1", "new": "invalid"}]
        event = MagicMock()

        result = self.service._handle_division_field_change(
            "MEM-001", changed_fields, event, field_name="division_id"
        )

        self.assertIsNone(result)


class TestApplyNewMembershipApplication(EnhancedTestCase):
    """Tests for _apply_new_membership_application()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_idempotent_existing_member_id(self, mock_map, mock_find):
        """Existing member_id match returns idempotent success."""
        mock_map.return_value = {"member_id": "42", "email": "test@example.com"}
        mock_find.return_value = (
            "MEM-001",
            {"success": True, "message": "Already exists"},
        )

        event = MagicMock()
        event.new_data = json.dumps({"id": 42, "email": "test@example.com"})

        result = self.service._apply_new_membership_application(event)

        self.assertTrue(result["success"])
        self.assertEqual(event.linked_member, "MEM-001")

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_email_conflict_returns_error(self, mock_map, mock_find):
        """Email conflict with different member_id returns error."""
        mock_map.return_value = {"member_id": "42", "email": "test@example.com"}
        mock_find.return_value = (
            None,
            {"success": False, "message": "Email conflicts with MijnRood ID 99"},
        )

        event = MagicMock()
        event.new_data = json.dumps({"id": 42, "email": "test@example.com"})

        result = self.service._apply_new_membership_application(event)

        self.assertFalse(result["success"])
        self.assertIn("conflicts", result["message"])

    def test_no_data_returns_error(self):
        """Empty new_data returns error."""
        event = MagicMock()
        event.new_data = None

        result = self.service._apply_new_membership_application(event)

        self.assertFalse(result["success"])
        self.assertIn("No new data", result["message"])

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_sets_application_id_to_prevent_user_creation(self, mock_frappe, mock_chapter, mock_map, mock_find):
        """New application sets application_id so is_application_member() returns True.

        Without application_id, after_save creates a User account (wrong for
        pending applications). Regression test for MR-APP ID assignment.
        """
        mock_find.return_value = (None, None)
        mock_map.return_value = {
            "member_id": "99",
            "first_name": "Jan",
            "last_name": "Test",
            "email": "jan@test.nl",
        }
        mock_frappe._ = frappe._
        mock_frappe.utils.today = lambda: "2026-01-01"

        # Capture the Member doc passed to insert
        inserted_doc = MagicMock()
        mock_frappe.new_doc.return_value = inserted_doc
        inserted_doc.name = "MEM-099"

        event = MagicMock()
        event.name = "EVT-001"
        event.new_data = json.dumps({"id": 99, "email": "jan@test.nl"})

        self.service._apply_new_membership_application(event)

        # Verify application_id was set before insert
        self.assertEqual(inserted_doc.application_id, "MR-APP-99")
        self.assertEqual(inserted_doc.application_status, "Pending")


class TestApplyChangedMembershipApplication(EnhancedTestCase):
    """Tests for _apply_changed_membership_application()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_approved_guard_skips_update(self, mock_frappe):
        """Already-approved application returns skip success."""
        mock_frappe._ = frappe._
        # linked_member lookup
        mock_frappe.db.get_value.return_value = "Approved"

        event = MagicMock()
        event.linked_member = "MEM-001"
        event.new_data = json.dumps({"id": 42, "first_name": "Jan"})
        event.changed_fields = json.dumps([{"field": "first_name", "old": "Piet", "new": "Jan"}])

        result = self.service._apply_changed_membership_application(event)

        self.assertTrue(result["success"])
        self.assertIn("already Approved", result["message"])

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_email_conflict_returns_error(self, mock_frappe, mock_find):
        """Email conflict when looking up unlinked member returns error."""
        mock_frappe._ = frappe._
        mock_find.return_value = (
            None,
            {"success": False, "message": "Email conflicts with MijnRood ID 99"},
        )

        event = MagicMock()
        event.linked_member = None  # No linked member — triggers email lookup
        event.new_data = json.dumps({"id": 42, "email": "conflict@example.com"})
        event.changed_fields = json.dumps([{"field": "email", "old": "old@example.com", "new": "conflict@example.com"}])

        result = self.service._apply_changed_membership_application(event)

        self.assertFalse(result["success"])
        self.assertIn("conflicts", result["message"])

    def test_no_data_returns_error(self):
        """Empty new_data returns error."""
        event = MagicMock()
        event.new_data = None
        event.changed_fields = None

        result = self.service._apply_changed_membership_application(event)

        self.assertFalse(result["success"])
        self.assertIn("No new data", result["message"])


class TestApplyNewMember(EnhancedTestCase):
    """Tests for _apply_new_member() idempotency fix."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_idempotent_existing_member(self, mock_map, mock_find):
        """Existing member by member_id returns idempotent success."""
        mock_map.return_value = {"member_id": "42", "email": "test@example.com"}
        mock_find.return_value = (
            "MEM-001",
            {"success": True, "message": "Member MEM-001 already exists (member_id=42)"},
        )

        event = MagicMock()
        event.new_data = json.dumps({"id": 42, "email": "test@example.com"})

        result = self.service._apply_new_member(event)

        self.assertTrue(result["success"])
        self.assertEqual(event.linked_member, "MEM-001")

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_email_conflict_returns_error(self, mock_map, mock_find):
        """Email conflict returns error instead of silently updating wrong member."""
        mock_map.return_value = {"member_id": "42", "email": "conflict@example.com"}
        mock_find.return_value = (
            None,
            {"success": False, "message": "Email conflict@example.com conflicts with MijnRood ID 99"},
        )

        event = MagicMock()
        event.new_data = json.dumps({"id": 42, "email": "conflict@example.com"})

        result = self.service._apply_new_member(event)

        self.assertFalse(result["success"])
        self.assertIn("conflicts", result["message"])

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_no_match_delegates_to_import_service(self, mock_map, mock_find):
        """No existing member delegates to MemberImportService for creation."""
        mock_map.return_value = {"member_id": "42", "email": "new@example.com"}
        mock_find.return_value = (None, None)

        mock_svc = MagicMock()
        mock_svc.create_or_update_member.return_value = ("created", "MEM-NEW")

        event = MagicMock()
        event.name = "EVT-001"
        event.new_data = json.dumps({"id": 42, "email": "new@example.com"})

        # Patch the local import inside the method
        with patch(
            "verenigingen.services.csv_import.member_import_service.get_member_import_service",
            return_value=mock_svc,
        ):
            result = self.service._apply_new_member(event)

        self.assertTrue(result["success"])
        self.assertEqual(event.linked_member, "MEM-NEW")

    def test_no_data_returns_error(self):
        """Empty new_data returns error."""
        event = MagicMock()
        event.new_data = None

        result = self.service._apply_new_member(event)

        self.assertFalse(result["success"])
        self.assertIn("No new data", result["message"])


class TestDispatchRouting(EnhancedTestCase):
    """Tests for _dispatch() table routing."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_unknown_table_returns_reference_only(self):
        """Unrecognized tables return a reference-only success."""
        event = MagicMock()
        event.mijnrood_table = "admin_contribution_payment"

        result = self.service._dispatch(event, "new")

        self.assertTrue(result["success"])
        self.assertIn("reference only", result["message"])

    @patch.object(MijnRoodEventApplicationService, "_apply_new_member")
    def test_admin_member_routes_to_member_handler(self, mock_handler):
        """admin_member table routes to _apply_new_member."""
        mock_handler.return_value = {"success": True, "message": "OK"}
        event = MagicMock()
        event.mijnrood_table = "admin_member"

        result = self.service._dispatch(event, "new")

        mock_handler.assert_called_once_with(event)
        self.assertTrue(result["success"])

    @patch.object(MijnRoodEventApplicationService, "_apply_new_membership_application")
    def test_application_table_routes_to_application_handler(self, mock_handler):
        """admin_membership_application routes to _apply_new_membership_application."""
        mock_handler.return_value = {"success": True, "message": "OK"}
        event = MagicMock()
        event.mijnrood_table = "admin_membership_application"

        result = self.service._dispatch(event, "new")

        mock_handler.assert_called_once_with(event)
        self.assertTrue(result["success"])


class TestCheckAndHandleTermination(EnhancedTestCase):
    """Tests for _check_and_handle_termination() and auto-execution."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def _make_status_change(self, old_id, new_id):
        """Helper: build a changed_fields list with a status change."""
        return [{"field": "current_membership_status_id", "old": str(old_id), "new": str(new_id)}]

    def test_no_status_change_returns_none(self):
        """When changed_fields has no status change, returns None (not handled)."""
        changed_fields = [{"field": "first_name", "old": "A", "new": "B"}]
        event = MagicMock()

        result = self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        self.assertIsNone(result)

    def test_non_terminated_target_returns_none(self):
        """Status change to an active status (not terminated) returns None."""
        # 1 and 2 are active status IDs
        changed_fields = self._make_status_change(1, 2)
        event = MagicMock()

        result = self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        self.assertIsNone(result)

    def test_non_active_source_returns_none(self):
        """Status change FROM a non-active state returns None (already non-active)."""
        # old=3 (terminated) → new=5 (deceased) — both non-active
        changed_fields = self._make_status_change(3, 5)
        event = MagicMock()

        result = self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_no_linked_member_returns_error(self, mock_frappe):
        """When no member can be found, returns error."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None  # No member found by member_id

        changed_fields = self._make_status_change(1, 3)  # active → terminated
        event = MagicMock()
        event.linked_member = None

        result = self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        self.assertFalse(result["success"])
        self.assertIn("no linked member", result["message"])

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_already_terminated_member_skips(self, mock_frappe):
        """When member is already Terminated, returns skip success."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Terminated"
        mock_frappe.get_doc.return_value = member_doc

        changed_fields = self._make_status_change(1, 3)  # active → terminated
        event = MagicMock()
        event.linked_member = "MEM-001"

        result = self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        self.assertTrue(result["success"])
        self.assertIn("already has status Terminated", result["message"])

    @patch("verenigingen.services.termination.TerminationExecutionService")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_creates_and_executes_termination(self, mock_frappe, mock_exec_cls):
        """Happy path: creates termination request AND auto-executes it."""
        mock_frappe._ = frappe._
        mock_frappe.utils.today.return_value = "2026-02-08"

        # Member is active
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc

        # Termination request doc
        term_doc = MagicMock()
        term_doc.name = "TR-001"
        mock_frappe.new_doc.return_value = term_doc

        # Execution succeeds
        mock_exec_instance = MagicMock()
        mock_exec_cls.return_value = mock_exec_instance

        changed_fields = self._make_status_change(1, 3)  # active → voluntary termination
        event = MagicMock()
        event.name = "EVT-001"
        event.linked_member = "MEM-001"

        result = self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        # Verify request was created with correct fields
        self.assertEqual(term_doc.member, "MEM-001")
        self.assertEqual(term_doc.status, "Approved")
        self.assertEqual(term_doc.termination_type, "Voluntary")
        self.assertTrue(term_doc.flags.skip_termination_validation)
        term_doc.insert.assert_called_once()

        # Verify auto-execution was called
        mock_exec_instance.execute.assert_called_once_with(term_doc)

        # Verify success result
        self.assertTrue(result["success"])
        self.assertIn("executed", result["message"])

    @patch("verenigingen.services.termination.TerminationExecutionService")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_execution_failure_returns_error(self, mock_frappe, mock_exec_cls):
        """When execution fails, request is created but error is returned."""
        mock_frappe._ = frappe._
        mock_frappe.utils.today.return_value = "2026-02-08"
        mock_frappe.get_traceback.return_value = "traceback"

        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc

        term_doc = MagicMock()
        term_doc.name = "TR-002"
        mock_frappe.new_doc.return_value = term_doc

        # Execution fails
        mock_exec_instance = MagicMock()
        mock_exec_instance.execute.side_effect = Exception("DB lock timeout")
        mock_exec_cls.return_value = mock_exec_instance

        changed_fields = self._make_status_change(1, 4)  # active → disciplinary
        event = MagicMock()
        event.name = "EVT-002"
        event.linked_member = "MEM-002"

        result = self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        # Request was still inserted
        term_doc.insert.assert_called_once()
        # But result is failure
        self.assertFalse(result["success"])
        self.assertIn("execution failed", result["message"])
        self.assertIn("DB lock timeout", result["message"])
        # Error was logged
        mock_frappe.log_error.assert_called_once()

    @patch("verenigingen.services.termination.TerminationExecutionService")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_deceased_sets_member_request_date(self, mock_frappe, mock_exec_cls):
        """Deceased termination type sets member_request_date."""
        mock_frappe._ = frappe._
        mock_frappe.utils.today.return_value = "2026-02-08"

        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc

        term_doc = MagicMock()
        term_doc.name = "TR-003"
        mock_frappe.new_doc.return_value = term_doc

        mock_exec_cls.return_value = MagicMock()

        changed_fields = self._make_status_change(1, 5)  # active → deceased
        event = MagicMock()
        event.name = "EVT-003"
        event.linked_member = "MEM-003"

        self.service._check_and_handle_termination(
            event, {}, {"id": 42}, changed_fields
        )

        self.assertEqual(term_doc.termination_type, "Deceased")
        # member_request_date should be set for Deceased type
        self.assertIsNotNone(term_doc.member_request_date)


class TestMapMijnRoodToMemberFields(EnhancedTestCase):
    """Tests for _map_mijnrood_to_member_fields() field mapping and conversions."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_contribution_period_monthly(self, mock_status_map):
        """contribution_period=0 maps to 'Maandelijks'."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields({"contribution_period": 0})
        self.assertEqual(result.get("payment_period"), "Maandelijks")

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_contribution_period_quarterly(self, mock_status_map):
        """contribution_period=1 maps to 'Per kwartaal'."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields({"contribution_period": 1})
        self.assertEqual(result.get("payment_period"), "Per kwartaal")

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_contribution_period_annually(self, mock_status_map):
        """contribution_period=2 maps to 'Jaarlijks'."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields({"contribution_period": 2})
        self.assertEqual(result.get("payment_period"), "Jaarlijks")

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_contribution_period_missing_no_payment_period(self, mock_status_map):
        """Missing contribution_period does not produce payment_period key."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields({"first_name": "Jan"})
        self.assertNotIn("payment_period", result)

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_contribution_period_string_value(self, mock_status_map):
        """contribution_period as string '1' still maps correctly (via _safe_int)."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields({"contribution_period": "1"})
        self.assertEqual(result.get("payment_period"), "Per kwartaal")

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_cents_to_euros_conversion(self, mock_status_map):
        """contribution_per_period_in_cents is converted to euros."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields(
            {"contribution_per_period_in_cents": 1250}
        )
        self.assertEqual(result.get("dues_rate"), 12.50)

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_status_id_mapped_to_membership_type(self, mock_status_map):
        """current_membership_status_id is resolved via status map."""
        mock_status_map.return_value = {1: "lid", 3: "opgezegd"}
        result = self.service._map_mijnrood_to_member_fields(
            {"current_membership_status_id": 1}
        )
        self.assertEqual(result.get("membership_type"), "lid")

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_unknown_contribution_period_logs_warning(self, mock_status_map):
        """Unknown contribution_period value logs a warning and omits payment_period."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields(
            {"id": 42, "contribution_period": 99}
        )
        self.assertNotIn("payment_period", result)

    @patch("verenigingen.mijnrood_sync.field_mapping.get_status_id_map")
    def test_privacy_field_mapped(self, mock_status_map):
        """accept_use_personal_information maps to accepts_optional_communications."""
        mock_status_map.return_value = {}
        result = self.service._map_mijnrood_to_member_fields(
            {"accept_use_personal_information": 1}
        )
        self.assertEqual(result.get("accepts_optional_communications"), 1)


class TestApplyMijnRoodComments(EnhancedTestCase):
    """Tests for _apply_mijnrood_comments()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_skips_empty_comment(self, mock_frappe):
        """Returns None when comment is empty."""
        result = self.service._apply_mijnrood_comments("MEM-001", {"mijnrood_comments": ""})
        self.assertIsNone(result)
        mock_frappe.db.set_value.assert_not_called()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_skips_missing_comment(self, mock_frappe):
        """Returns None when mijnrood_comments key is missing."""
        result = self.service._apply_mijnrood_comments("MEM-001", {})
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_skips_duplicate_comment(self, mock_frappe):
        """Returns None when comment already exists in notes (idempotent)."""
        mock_frappe.db.get_value.return_value = "MijnRood notitie: test comment"
        result = self.service._apply_mijnrood_comments("MEM-001", {"mijnrood_comments": "test comment"})
        self.assertIsNone(result)
        mock_frappe.db.set_value.assert_not_called()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_appends_comment_to_existing_notes(self, mock_frappe):
        """Appends comment to existing notes with <br> separator."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "Existing note"
        self.service._apply_mijnrood_comments("MEM-001", {"mijnrood_comments": "new comment"})
        mock_frappe.db.set_value.assert_called_once()
        args = mock_frappe.db.set_value.call_args
        new_notes = args[0][3]
        self.assertIn("Existing note", new_notes)
        self.assertIn("<br>", new_notes)
        self.assertIn("new comment", new_notes)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_creates_notes_when_empty(self, mock_frappe):
        """Creates notes from scratch when member has no notes."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = ""
        result = self.service._apply_mijnrood_comments("MEM-001", {"mijnrood_comments": "first comment"})
        self.assertIsNotNone(result)
        args = mock_frappe.db.set_value.call_args
        new_notes = args[0][3]
        self.assertNotIn("<br>", new_notes)  # No separator for first note
        self.assertIn("first comment", new_notes)


class TestEnsureAddress(EnhancedTestCase):
    """Tests for _ensure_address()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_skips_when_no_address(self):
        """Returns None when address_line1 is missing."""
        result = self.service._ensure_address("MEM-001", {"city": "Amsterdam"})
        self.assertIsNone(result)

    def test_skips_when_no_city(self):
        """Returns None when city is missing."""
        result = self.service._ensure_address("MEM-001", {"address_line1": "Kerkstraat 1"})
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_creates_address(self, mock_frappe):
        """Creates address via AddressImportService and links to member."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        mock_frappe.get_doc.return_value = member_doc

        with patch(
            "verenigingen.services.csv_import.address_import_service.get_address_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_or_update_address.return_value = "ADDR-001"
            mock_get_svc.return_value = mock_svc

            result = self.service._ensure_address(
                "MEM-001", {"address_line1": "Kerkstraat 1", "city": "Amsterdam"}
            )

        self.assertIsNotNone(result)
        self.assertIn("ADDR-001", result)
        mock_frappe.db.set_value.assert_called_once()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_handles_service_error(self, mock_frappe):
        """Returns error message when address service throws."""
        mock_frappe._ = frappe._
        mock_frappe.get_traceback.return_value = "traceback"
        mock_frappe.get_doc.side_effect = Exception("DB error")

        result = self.service._ensure_address(
            "MEM-001", {"address_line1": "Kerkstraat 1", "city": "Amsterdam"}
        )

        self.assertIn("failed", result)
        mock_frappe.log_error.assert_called_once()


class TestEnsureMollieData(EnhancedTestCase):
    """Tests for _ensure_mollie_data() including subscription_status logic."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_skips_when_no_mollie_ids(self):
        """Returns None when neither customer_id nor subscription_id present."""
        result = self.service._ensure_mollie_data("MEM-001", {})
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_active_member_with_subscription_gets_active_status(self, mock_frappe):
        """Active member with subscription_id gets status='active'."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc

        with patch(
            "verenigingen.services.csv_import.mollie_sync_service.get_mollie_sync_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_get_svc.return_value = mock_svc

            self.service._ensure_mollie_data("MEM-001", {
                "custom_mollie_customer_id": "cus_abc",
                "custom_mollie_subscription_id": "sub_123",
            })

            # Verify sync was called with status="active"
            call_args = mock_svc.sync_mollie_data.call_args
            mollie_data = call_args[0][1]
            self.assertEqual(mollie_data["custom_subscription_status"], "active")

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_terminated_member_with_subscription_gets_cancelled_status(self, mock_frappe):
        """Terminated member with subscription_id gets status='cancelled'."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Terminated"
        mock_frappe.get_doc.return_value = member_doc

        with patch(
            "verenigingen.services.csv_import.mollie_sync_service.get_mollie_sync_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_get_svc.return_value = mock_svc

            self.service._ensure_mollie_data("MEM-001", {
                "custom_mollie_customer_id": "cus_abc",
                "custom_mollie_subscription_id": "sub_123",
            })

            call_args = mock_svc.sync_mollie_data.call_args
            mollie_data = call_args[0][1]
            self.assertEqual(mollie_data["custom_subscription_status"], "cancelled")

            # Also verify subscription_status overridden on Member
            mock_frappe.db.set_value.assert_called_once_with(
                "Member", "MEM-001", "subscription_status", "cancelled",
                update_modified=False,
            )

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_member_without_subscription_gets_none_status(self, mock_frappe):
        """Member without subscription_id gets status=None (no transition)."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Terminated"
        mock_frappe.get_doc.return_value = member_doc

        with patch(
            "verenigingen.services.csv_import.mollie_sync_service.get_mollie_sync_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_get_svc.return_value = mock_svc

            self.service._ensure_mollie_data("MEM-001", {
                "custom_mollie_customer_id": "cus_abc",
            })

            call_args = mock_svc.sync_mollie_data.call_args
            mollie_data = call_args[0][1]
            self.assertIsNone(mollie_data["custom_subscription_status"])

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_handles_service_error(self, mock_frappe):
        """Returns error message when Mollie sync throws."""
        mock_frappe._ = frappe._
        mock_frappe.get_traceback.return_value = "traceback"
        mock_frappe.get_doc.side_effect = Exception("Mollie API error")

        result = self.service._ensure_mollie_data("MEM-001", {
            "custom_mollie_customer_id": "cus_abc",
        })

        self.assertIn("failed", result)
        mock_frappe.log_error.assert_called_once()


class TestEnsureMembershipAndDues(EnhancedTestCase):
    """Tests for _ensure_membership_and_dues()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_skips_when_no_dues_rate(self):
        """Returns None when dues_rate not in row_data."""
        result = self.service._ensure_membership_and_dues("MEM-001", {"first_name": "Jan"})
        self.assertIsNone(result)

    def test_skips_when_no_payment_period(self):
        """Returns None when payment_period not in row_data (no defaults)."""
        result = self.service._ensure_membership_and_dues(
            "MEM-001", {"dues_rate": 12.50}
        )
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_skips_when_member_not_active(self, mock_frappe):
        """Returns None when member status is not Active."""
        member_doc = MagicMock()
        member_doc.status = "Terminated"
        mock_frappe.get_doc.return_value = member_doc

        result = self.service._ensure_membership_and_dues(
            "MEM-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
        )
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_skips_when_existing_active_membership(self, mock_frappe):
        """Returns None when member already has an active submitted Membership."""
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc
        mock_frappe.db.exists.return_value = "MEMB-001"

        result = self.service._ensure_membership_and_dues(
            "MEM-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
        )
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_creates_membership(self, mock_frappe):
        """Creates membership and returns success message."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc
        mock_frappe.db.exists.return_value = None

        with patch(
            "verenigingen.services.csv_import.membership_import_service.get_membership_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_membership_from_csv.return_value = "MEMB-NEW"
            mock_get_svc.return_value = mock_svc

            result = self.service._ensure_membership_and_dues(
                "MEM-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
            )

        self.assertIsNotNone(result)
        self.assertIn("MEMB-NEW", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_handles_creation_error(self, mock_frappe):
        """Returns error message when membership creation throws."""
        mock_frappe._ = frappe._
        mock_frappe.get_traceback.return_value = "traceback"
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc
        mock_frappe.db.exists.return_value = None

        with patch(
            "verenigingen.services.csv_import.membership_import_service.get_membership_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_membership_from_csv.side_effect = Exception("Template not found")
            mock_get_svc.return_value = mock_svc

            result = self.service._ensure_membership_and_dues(
                "MEM-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
            )

        self.assertIn("failed", result)
        mock_frappe.log_error.assert_called_once()


class TestCreateRelatedRecords(EnhancedTestCase):
    """Tests for _create_related_records() orchestration."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    def test_calls_chapter_assignment_with_division_id(
        self, mock_chapter, mock_addr, mock_mollie, mock_membership, mock_comments
    ):
        """Calls _assign_chapter_from_division when chapter (division_id) present."""
        mock_chapter.return_value = "Assigned to chapter 'Amsterdam'"
        event = MagicMock()

        messages = self.service._create_related_records(
            "MEM-001", {"chapter": "5"}, event
        )

        mock_chapter.assert_called_once_with("MEM-001", 5, event)
        self.assertIn("Assigned to chapter 'Amsterdam'", messages)

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    def test_skips_chapter_when_no_event(
        self, mock_chapter, mock_addr, mock_mollie, mock_membership, mock_comments
    ):
        """Skips chapter assignment when event is None."""
        self.service._create_related_records("MEM-001", {"chapter": "5"}, event=None)
        mock_chapter.assert_not_called()

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value="Notes added")
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value="Membership created")
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value="Mollie synced")
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value="Address linked")
    def test_collects_all_messages(self, mock_addr, mock_mollie, mock_membership, mock_comments):
        """Collects messages from all sub-operations."""
        messages = self.service._create_related_records("MEM-001", {})

        self.assertEqual(len(messages), 4)
        self.assertIn("Address linked", messages)
        self.assertIn("Mollie synced", messages)
        self.assertIn("Membership created", messages)
        self.assertIn("Notes added", messages)

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value=None)
    def test_returns_empty_when_all_skipped(self, mock_addr, mock_mollie, mock_membership, mock_comments):
        """Returns empty list when all sub-operations are skipped."""
        messages = self.service._create_related_records("MEM-001", {})
        self.assertEqual(messages, [])


class TestTryPromoteApplication(EnhancedTestCase):
    """Tests for _try_promote_application()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_returns_none_when_no_email_match(self, mock_frappe):
        """Returns None when no member found by email."""
        mock_frappe.db.get_value.return_value = None
        event = MagicMock()

        result = self.service._try_promote_application(event, {"email": "new@example.com"})
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_returns_none_when_not_pending(self, mock_frappe):
        """Returns None when existing member's application_status is not Pending."""
        mock_frappe.db.get_value.return_value = frappe._dict({
            "name": "MEM-001",
            "member_id": "813",
            "application_status": "Approved",
        })
        event = MagicMock()

        result = self.service._try_promote_application(
            event, {"email": "test@example.com", "member_id": "1700"}
        )
        self.assertIsNone(result)

    @patch.object(MijnRoodEventApplicationService, "_create_related_records", return_value=[])
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_promotes_and_updates(self, mock_frappe, mock_related):
        """Promotes pending application: updates member_id, clears app status, creates records."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = frappe._dict({
            "name": "MEM-001",
            "member_id": "813",
            "application_status": "Pending",
        })

        event = MagicMock()
        event.name = "EVT-001"

        with patch(
            "verenigingen.services.csv_import.member_import_service.get_member_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_or_update_member.return_value = ("updated", "MEM-001")
            mock_get_svc.return_value = mock_svc

            result = self.service._try_promote_application(
                event, {"email": "test@example.com", "member_id": "1700"}
            )

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertIn("promoted", result["message"])
        self.assertEqual(event.linked_member, "MEM-001")

        # Verify application_status was set to Approved
        set_value_call = mock_frappe.db.set_value.call_args
        self.assertEqual(set_value_call[0][1], "MEM-001")
        self.assertEqual(set_value_call[0][2]["application_status"], "Approved")

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_returns_error_on_import_failure(self, mock_frappe):
        """Returns error when MemberImportService fails during promotion."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = frappe._dict({
            "name": "MEM-001",
            "member_id": "813",
            "application_status": "Pending",
        })

        event = MagicMock()
        event.name = "EVT-001"

        with patch(
            "verenigingen.services.csv_import.member_import_service.get_member_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_or_update_member.return_value = ("error", None)
            mock_get_svc.return_value = mock_svc

            result = self.service._try_promote_application(
                event, {"email": "test@example.com", "member_id": "1700"}
            )

        self.assertFalse(result["success"])
        self.assertIn("failed", result["message"])


class TestApplyNewMemberPromotionPath(EnhancedTestCase):
    """Tests for _apply_new_member() promotion via _try_promote_application()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_try_promote_application")
    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_conflict_triggers_promotion_check(self, mock_map, mock_find, mock_promote):
        """Email conflict calls _try_promote_application before returning error."""
        mock_map.return_value = {"member_id": "1700", "email": "test@example.com"}
        mock_find.return_value = (
            None,
            {"success": False, "message": "Email conflicts with MijnRood ID 813"},
        )
        mock_promote.return_value = {
            "success": True,
            "message": "Application promoted",
        }

        event = MagicMock()
        event.new_data = json.dumps({"id": 1700, "email": "test@example.com"})

        result = self.service._apply_new_member(event)

        mock_promote.assert_called_once()
        self.assertTrue(result["success"])
        self.assertIn("promoted", result["message"])

    @patch.object(MijnRoodEventApplicationService, "_try_promote_application")
    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_conflict_without_promotion_returns_error(self, mock_map, mock_find, mock_promote):
        """Email conflict returns error when promotion is not applicable."""
        mock_map.return_value = {"member_id": "1700", "email": "test@example.com"}
        mock_find.return_value = (
            None,
            {"success": False, "message": "Email conflicts with MijnRood ID 813"},
        )
        mock_promote.return_value = None  # Not a promotion

        event = MagicMock()
        event.new_data = json.dumps({"id": 1700, "email": "test@example.com"})

        result = self.service._apply_new_member(event)

        self.assertFalse(result["success"])
        self.assertIn("conflicts", result["message"])

    @patch.object(MijnRoodEventApplicationService, "_try_promote_application")
    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodEventApplicationService, "_map_mijnrood_to_member_fields")
    def test_idempotent_success_does_not_trigger_promotion(self, mock_map, mock_find, mock_promote):
        """Existing member match (success) does NOT trigger promotion check."""
        mock_map.return_value = {"member_id": "42", "email": "test@example.com"}
        mock_find.return_value = (
            "MEM-001",
            {"success": True, "message": "Already exists"},
        )

        event = MagicMock()
        event.new_data = json.dumps({"id": 42, "email": "test@example.com"})

        result = self.service._apply_new_member(event)

        mock_promote.assert_not_called()
        self.assertTrue(result["success"])
