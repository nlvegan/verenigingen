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
- _ensure_user_account: setting disabled, member has user, success, failure, exception
- ACR deduplication: set clearing, skip on duplicate, volunteer→ACR tracking, dual scenario
- _ensure_team_membership: no volunteer, team missing, team inactive, already member, happy path, exception
- _ensure_user_account_for_volunteer: user exists, already queued, happy path, queue failure, exception
- _ensure_employee_for_profile: no profile, no Employee role, Employee exists, profile missing,
  no member, no company, happy path, DuplicateEntryError race, unexpected exception
- _end_chapter_board_membership: unresolvable division, no volunteer, not on board,
  happy path (BoardManager delegation), BoardManager failure, exception handling
- _handle_division_contact_change: no removals, single removal, all removed,
  partial failure continues, None results skipped
- _notify_board_membership_change: correct notification key, realtime event, failure resilience
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    MijnRoodApplicationSyncService,
)
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    MijnRoodMappingService,
    get_mapping_service,
)
from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    MijnRoodMemberSyncService,
)
from verenigingen.mijnrood_sync.services.event_application_service import (
    MijnRoodEventApplicationService,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFindExistingMemberOrConflict(EnhancedTestCase):
    """Tests for _find_existing_member_or_conflict()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application.member_sync_service.frappe")
    def test_member_id_match_returns_success(self, mock_frappe):
        """When member_id matches an existing Member, return idempotent success."""
        mock_frappe.db.get_value.return_value = "MEM-001"
        mock_frappe._ = frappe._

        name, result = self.service._find_existing_member_or_conflict(42, "test@example.com")

        self.assertEqual(name, "MEM-001")
        self.assertTrue(result["success"])
        self.assertIn("member_id=42", result["message"])

    @patch("verenigingen.mijnrood_sync.services.event_application.member_sync_service.frappe")
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

    @patch("verenigingen.mijnrood_sync.services.event_application.member_sync_service.frappe")
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

    @patch("verenigingen.mijnrood_sync.services.event_application.member_sync_service.frappe")
    def test_no_match_returns_none(self, mock_frappe):
        """When nothing matches, return (None, None)."""
        mock_frappe.db.get_value.side_effect = [None, None]
        mock_frappe._ = frappe._

        name, result = self.service._find_existing_member_or_conflict(42, "new@example.com")

        self.assertIsNone(name)
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application.member_sync_service.frappe")
    def test_no_email_no_member_id(self, mock_frappe):
        """When both are None/empty, return (None, None) without DB calls."""
        name, result = self.service._find_existing_member_or_conflict(None, None)

        self.assertIsNone(name)
        self.assertIsNone(result)


class TestSetApplicationFields(EnhancedTestCase):
    """Tests for _set_application_fields() — now lives on
    MijnRoodApplicationSyncService after the PR #3 god-class split."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodApplicationSyncService()

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


class TestAssignChapterFromDivisionJoinDate(EnhancedTestCase):
    """Tests for join_date validation in _assign_chapter_from_division()."""

    PATCH_CAS = "verenigingen.services.chapter.chapter_assignment_service.ChapterAssignmentService"

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Amsterdam")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_passes_valid_join_date(self, mock_frappe, mock_resolve):
        """Valid past date is passed through to assign_with_cleanup."""
        mock_frappe.db.exists.return_value = True
        mock_frappe.ValidationError = frappe.ValidationError
        mock_svc_instance = MagicMock()
        mock_svc_instance.assign_with_cleanup.return_value = {"success": True}

        with patch(self.PATCH_CAS, return_value=mock_svc_instance):
            event = MagicMock()
            event.name = "EVT-001"
            self.service._assign_chapter_from_division("MEM-001", 5, event, join_date="2024-03-15")

        mock_svc_instance.assign_with_cleanup.assert_called_once()
        call_kwargs = mock_svc_instance.assign_with_cleanup.call_args
        self.assertEqual(call_kwargs.kwargs["join_date"], "2024-03-15")

    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Amsterdam")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_rejects_future_join_date(self, mock_frappe, mock_resolve):
        """Future date is rejected; None is passed instead."""
        mock_frappe.db.exists.return_value = True
        mock_frappe.ValidationError = frappe.ValidationError
        mock_svc_instance = MagicMock()
        mock_svc_instance.assign_with_cleanup.return_value = {"success": True}

        with patch(self.PATCH_CAS, return_value=mock_svc_instance):
            event = MagicMock()
            event.name = "EVT-001"
            self.service._assign_chapter_from_division("MEM-001", 5, event, join_date="2099-01-01")

        call_kwargs = mock_svc_instance.assign_with_cleanup.call_args
        self.assertIsNone(call_kwargs.kwargs["join_date"])

    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Amsterdam")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_rejects_invalid_join_date_format(self, mock_frappe, mock_resolve):
        """Unparseable date string is rejected; None is passed instead."""
        mock_frappe.db.exists.return_value = True
        mock_frappe.ValidationError = frappe.ValidationError
        mock_svc_instance = MagicMock()
        mock_svc_instance.assign_with_cleanup.return_value = {"success": True}

        with patch(self.PATCH_CAS, return_value=mock_svc_instance):
            event = MagicMock()
            event.name = "EVT-001"
            self.service._assign_chapter_from_division("MEM-001", 5, event, join_date="not-a-date")

        call_kwargs = mock_svc_instance.assign_with_cleanup.call_args
        self.assertIsNone(call_kwargs.kwargs["join_date"])

    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Amsterdam")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_none_join_date_passes_through(self, mock_frappe, mock_resolve):
        """None join_date is passed through (MemberManager defaults to today)."""
        mock_frappe.db.exists.return_value = True
        mock_frappe.ValidationError = frappe.ValidationError
        mock_svc_instance = MagicMock()
        mock_svc_instance.assign_with_cleanup.return_value = {"success": True}

        with patch(self.PATCH_CAS, return_value=mock_svc_instance):
            event = MagicMock()
            event.name = "EVT-001"
            self.service._assign_chapter_from_division("MEM-001", 5, event, join_date=None)

        call_kwargs = mock_svc_instance.assign_with_cleanup.call_args
        self.assertIsNone(call_kwargs.kwargs["join_date"])


class TestApplyNewMembershipApplication(EnhancedTestCase):
    """Tests for _apply_new_membership_application()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_find_existing_member_or_conflict")
    @patch.object(MijnRoodMappingService, "map_member_fields")
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
    @patch.object(MijnRoodMappingService, "map_member_fields")
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
    @patch.object(MijnRoodMappingService, "map_member_fields")
    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
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

    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
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

    @patch.object(MijnRoodMemberSyncService, "find_existing_member_or_conflict")
    @patch.object(MijnRoodMappingService, "map_member_fields")
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

    @patch.object(MijnRoodMemberSyncService, "find_existing_member_or_conflict")
    @patch.object(MijnRoodMappingService, "map_member_fields")
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

    @patch.object(MijnRoodMemberSyncService, "find_existing_member_or_conflict")
    @patch.object(MijnRoodMappingService, "map_member_fields")
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

        # Mock status mapping functions so tests don't depend on DB state.
        # Uses the hardcoded defaults: active={1,2}, terminated={3,4,5,6}.
        self._status_patches = [
            patch(
                "verenigingen.mijnrood_sync.services.event_application_service.get_terminated_status_ids",
                return_value=frozenset([3, 4, 5, 6]),
            ),
            patch(
                "verenigingen.mijnrood_sync.services.event_application_service.get_active_status_ids",
                return_value=frozenset([1, 2]),
            ),
            patch(
                "verenigingen.mijnrood_sync.services.event_application_service.get_termination_type_map",
                return_value={3: "Voluntary", 4: "Disciplinary Action", 5: "Deceased", 6: "Policy Violation"},
            ),
        ]
        for p in self._status_patches:
            p.start()

    def tearDown(self):
        for p in self._status_patches:
            p.stop()
        super().tearDown()

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
        member_doc.status = "Quit"
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
    """Tests for MijnRoodMappingService.map_member_fields() field mapping and conversions."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_contribution_period_monthly(self, mock_status_map):
        """contribution_period=0 maps to 'Maandelijks'."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields({"contribution_period": 0})
        self.assertEqual(result.get("payment_period"), "Maandelijks")

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_contribution_period_quarterly(self, mock_status_map):
        """contribution_period=1 maps to 'Per kwartaal'."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields({"contribution_period": 1})
        self.assertEqual(result.get("payment_period"), "Per kwartaal")

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_contribution_period_annually(self, mock_status_map):
        """contribution_period=2 maps to 'Jaarlijks'."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields({"contribution_period": 2})
        self.assertEqual(result.get("payment_period"), "Jaarlijks")

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_contribution_period_missing_no_payment_period(self, mock_status_map):
        """Missing contribution_period does not produce payment_period key."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields({"first_name": "Jan"})
        self.assertNotIn("payment_period", result)

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_contribution_period_string_value(self, mock_status_map):
        """contribution_period as string '1' still maps correctly (via _safe_int)."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields({"contribution_period": "1"})
        self.assertEqual(result.get("payment_period"), "Per kwartaal")

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_cents_to_euros_conversion(self, mock_status_map):
        """contribution_per_period_in_cents is converted to euros."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields(
            {"contribution_per_period_in_cents": 1250}
        )
        self.assertEqual(result.get("dues_rate"), 12.50)

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_verenigingen_membership_type_for_status_id", return_value=None)
    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_status_id_mapped_to_membership_type(self, mock_status_map, _mock_explicit):
        """current_membership_status_id is resolved via status map when no explicit mapping."""
        mock_status_map.return_value = {1: "lid", 3: "opgezegd"}
        result = get_mapping_service().map_member_fields(
            {"current_membership_status_id": 1}
        )
        self.assertEqual(result.get("membership_type"), "lid")

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_verenigingen_membership_type_for_status_id")
    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_explicit_membership_type_takes_priority(self, mock_status_map, mock_explicit):
        """Explicit verenigingen_membership_type is used when configured."""
        mock_explicit.return_value = "Lid"
        mock_status_map.return_value = {1: "lid"}
        result = get_mapping_service().map_member_fields(
            {"current_membership_status_id": 1}
        )
        self.assertEqual(result.get("membership_type"), "Lid")
        mock_status_map.assert_not_called()

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_unknown_contribution_period_logs_warning(self, mock_status_map):
        """Unknown contribution_period value logs a warning and omits payment_period."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields(
            {"id": 42, "contribution_period": 99}
        )
        self.assertNotIn("payment_period", result)

    @patch("verenigingen.mijnrood_sync.services.event_application.mapping_service.get_status_id_map")
    def test_privacy_field_mapped(self, mock_status_map):
        """accept_use_personal_information maps to accepts_optional_communications."""
        mock_status_map.return_value = {}
        result = get_mapping_service().map_member_fields(
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
        member_doc.status = "Quit"
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
            self.assertEqual(mollie_data["custom_subscription_status"], "canceled")
            # MollieSyncService now honors the canceled status from mollie_data,
            # so no post-call override on Member is needed.
            mock_frappe.db.set_value.assert_not_called()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_member_without_subscription_gets_none_status(self, mock_frappe):
        """Member without subscription_id gets status=None (no transition)."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Quit"
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
        member_doc.status = "Quit"
        mock_frappe.get_doc.return_value = member_doc

        result = self.service._ensure_membership_and_dues(
            "MEM-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
        )
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_calls_update_when_schedule_exists_and_rate_provided(self, mock_frappe):
        """Calls _update_existing_dues_schedule when schedule exists and dues_rate in row_data."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc
        mock_frappe.db.get_value.return_value = "MEMB-001"
        mock_frappe.db.exists.return_value = "SCHED-001"

        with patch.object(
            self.service, "_update_existing_dues_schedule",
            return_value="Dues schedule SCHED-001 updated: rate 10.0 → 12.5",
        ) as mock_update:
            result = self.service._ensure_membership_and_dues(
                "MEM-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
            )

        mock_update.assert_called_once_with("MEM-001", 12.50)
        self.assertIn("SCHED-001", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_skips_when_schedule_exists_but_no_rate_in_data(self, mock_frappe):
        """Returns None when schedule exists but dues_rate not in row_data."""
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc
        mock_frappe.db.get_value.return_value = "MEMB-001"
        mock_frappe.db.exists.return_value = "SCHED-001"

        result = self.service._ensure_membership_and_dues(
            "MEM-001", {"payment_period": "Per kwartaal"}
        )
        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_backfills_when_membership_exists_without_schedule(self, mock_frappe):
        """Calls _backfill_dues_schedule when membership exists but has no schedule."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Active"
        member_doc.name = "MEM-001"
        mock_frappe.get_doc.return_value = member_doc
        mock_frappe.db.get_value.return_value = "MEMB-001"
        mock_frappe.db.exists.return_value = None  # no dues schedule

        with patch.object(
            self.service, "_backfill_dues_schedule",
            return_value="Dues schedule SCHED-NEW created for existing membership",
        ) as mock_backfill:
            result = self.service._ensure_membership_and_dues(
                "MEM-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
            )

        mock_backfill.assert_called_once_with(member_doc, "MEMB-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"})
        self.assertIn("SCHED-NEW", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_creates_membership(self, mock_frappe):
        """Creates membership and returns success message when no existing membership."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.status = "Active"
        mock_frappe.get_doc.return_value = member_doc
        mock_frappe.db.get_value.return_value = None  # no existing membership

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
        mock_frappe.db.get_value.return_value = None  # no existing membership

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


class TestBackfillDuesSchedule(EnhancedTestCase):
    """Tests for _backfill_dues_schedule()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_creates_schedule(self, mock_frappe):
        """Creates dues schedule from template and returns success message."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "Regulier"
        member_doc = MagicMock()
        member_doc.name = "MEM-001"
        row_data = {"dues_rate": 12.50, "payment_period": "Per kwartaal"}

        with patch(
            "verenigingen.utils.csv.data_transformers."
            "get_dues_schedule_template_from_payment_period",
            return_value="Quarterly Template",
        ), patch(
            "verenigingen.verenigingen.doctype.membership_dues_schedule."
            "membership_dues_schedule.MembershipDuesSchedule"
        ) as mock_mds:
            mock_mds.create_from_template.return_value = "SCHED-NEW"

            result = self.service._backfill_dues_schedule(member_doc, "MEMB-001", row_data)

        self.assertIn("SCHED-NEW", result)
        mock_mds.create_from_template.assert_called_once_with(
            "MEM-001",
            template_name="Quarterly Template",
            membership_type="Regulier",
            membership_name="MEMB-001",
            custom_amount=12.50,
            custom_amount_reason="Backfilled from MijnRood sync data",
        )

    def test_skips_when_template_resolution_returns_none(self):
        """Returns None when get_dues_schedule_template_from_payment_period returns None."""
        member_doc = MagicMock()
        member_doc.name = "MEM-001"

        with patch(
            "verenigingen.utils.csv.data_transformers."
            "get_dues_schedule_template_from_payment_period",
            return_value=None,
        ):
            result = self.service._backfill_dues_schedule(
                member_doc, "MEMB-001", {"payment_period": "Per kwartaal"}
            )

        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_handles_template_resolution_error(self, mock_frappe):
        """Returns skip message when template resolution raises."""
        mock_frappe._ = frappe._
        member_doc = MagicMock()
        member_doc.name = "MEM-001"

        with patch(
            "verenigingen.utils.csv.data_transformers."
            "get_dues_schedule_template_from_payment_period",
            side_effect=Exception("No quarterly template configured"),
        ):
            result = self.service._backfill_dues_schedule(
                member_doc, "MEMB-001", {"payment_period": "Per kwartaal"}
            )

        self.assertIn("skipped", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_handles_create_from_template_error(self, mock_frappe):
        """Returns error message when create_from_template raises."""
        mock_frappe._ = frappe._
        mock_frappe.get_traceback.return_value = "traceback"
        mock_frappe.db.get_value.return_value = "Regulier"
        member_doc = MagicMock()
        member_doc.name = "MEM-001"

        with patch(
            "verenigingen.utils.csv.data_transformers."
            "get_dues_schedule_template_from_payment_period",
            return_value="Quarterly Template",
        ), patch(
            "verenigingen.verenigingen.doctype.membership_dues_schedule."
            "membership_dues_schedule.MembershipDuesSchedule"
        ) as mock_mds:
            mock_mds.create_from_template.side_effect = Exception("Template invalid")

            result = self.service._backfill_dues_schedule(
                member_doc, "MEMB-001", {"dues_rate": 12.50, "payment_period": "Per kwartaal"}
            )

        self.assertIn("failed", result)
        mock_frappe.log_error.assert_called_once()


class TestUpdateExistingDuesSchedule(EnhancedTestCase):
    """Tests for _update_existing_dues_schedule()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_returns_none_when_no_schedule_found(self):
        """Returns None when repository finds no active/paused schedule."""
        from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository

        with patch.object(DuesScheduleRepository, "get_active_or_paused_schedule", return_value=None):
            result = self.service._update_existing_dues_schedule("MEM-001", 15.0)

        self.assertIsNone(result)

    def test_returns_none_when_rate_unchanged(self):
        """Returns None when repository reports no change needed."""
        from verenigingen.repositories.dues_schedule_repository import (
            CancellationResult,
            DuesScheduleRepository,
            ScheduleInfo,
        )

        mock_schedule = ScheduleInfo(name="SCHED-001", member="MEM-001", dues_rate=15.0)
        no_change = CancellationResult(
            success=True, schedule_name="SCHED-001",
            message="Rate already matches", method_used="no_change_needed",
        )

        with patch.object(
            DuesScheduleRepository, "get_active_or_paused_schedule", return_value=mock_schedule,
        ), patch.object(
            DuesScheduleRepository, "update_schedule_rate", return_value=no_change,
        ):
            result = self.service._update_existing_dues_schedule("MEM-001", 15.0)

        self.assertIsNone(result)

    def test_returns_message_when_rate_updated(self):
        """Returns human-readable message on successful rate update."""
        from verenigingen.repositories.dues_schedule_repository import (
            CancellationResult,
            DuesScheduleRepository,
            ScheduleInfo,
        )

        mock_schedule = ScheduleInfo(name="SCHED-001", member="MEM-001", dues_rate=10.0)
        updated = CancellationResult(
            success=True, schedule_name="SCHED-001",
            message="Rate updated from 10.0 to 15.0", method_used="update",
        )

        with patch.object(
            DuesScheduleRepository, "get_active_or_paused_schedule", return_value=mock_schedule,
        ), patch.object(
            DuesScheduleRepository, "update_schedule_rate", return_value=updated,
        ) as mock_update:
            result = self.service._update_existing_dues_schedule("MEM-001", 15.0)

        mock_update.assert_called_once_with(
            schedule_name="SCHED-001", new_rate=15.0, reason="MijnRood sync",
        )
        self.assertIn("SCHED-001", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_logs_and_returns_error_on_repo_failure(self, mock_frappe):
        """Logs error and returns failure message when repository update fails."""
        mock_frappe._ = frappe._
        from verenigingen.repositories.dues_schedule_repository import (
            CancellationResult,
            DuesScheduleRepository,
            ScheduleInfo,
        )

        mock_schedule = ScheduleInfo(name="SCHED-001", member="MEM-001", dues_rate=10.0)
        failure = CancellationResult(
            success=False, schedule_name="SCHED-001",
            message="Permission denied", method_used="none",
            errors=["Permission denied"],
        )

        with patch.object(
            DuesScheduleRepository, "get_active_or_paused_schedule", return_value=mock_schedule,
        ), patch.object(
            DuesScheduleRepository, "update_schedule_rate", return_value=failure,
        ):
            result = self.service._update_existing_dues_schedule("MEM-001", 15.0)

        self.assertIn("failed", result)
        mock_frappe.log_error.assert_called_once()


class TestCreateRelatedRecords(EnhancedTestCase):
    """Tests for _create_related_records() orchestration."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_user_account", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    def test_calls_chapter_assignment_with_division_id(
        self, mock_chapter, mock_addr, mock_mollie, mock_membership, mock_account, mock_comments
    ):
        """Calls _assign_chapter_from_division when chapter (division_id) present."""
        mock_chapter.return_value = "Assigned to chapter 'Amsterdam'"
        event = MagicMock()

        messages = self.service._create_related_records(
            "MEM-001", {"chapter": "5"}, event
        )

        mock_chapter.assert_called_once_with("MEM-001", 5, event, join_date=None)
        self.assertIn("Assigned to chapter 'Amsterdam'", messages)

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_user_account", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    def test_passes_member_since_as_join_date(
        self, mock_chapter, mock_addr, mock_mollie, mock_membership, mock_account, mock_comments
    ):
        """Passes member_since as join_date for chapter assignment."""
        mock_chapter.return_value = "Assigned to chapter 'Amsterdam'"
        event = MagicMock()

        self.service._create_related_records(
            "MEM-001", {"chapter": "5", "member_since": "2024-03-15"}, event
        )

        mock_chapter.assert_called_once_with("MEM-001", 5, event, join_date="2024-03-15")

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_user_account", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_assign_chapter_from_division")
    def test_skips_chapter_when_no_event(
        self, mock_chapter, mock_addr, mock_mollie, mock_membership, mock_account, mock_comments
    ):
        """Skips chapter assignment when event is None."""
        self.service._create_related_records("MEM-001", {"chapter": "5"}, event=None)
        mock_chapter.assert_not_called()

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value="Notes added")
    @patch.object(MijnRoodEventApplicationService, "_ensure_user_account", return_value="Account creation queued (ACR-001)")
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value="Membership created")
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value="Mollie synced")
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value="Address linked")
    def test_collects_all_messages(self, mock_addr, mock_mollie, mock_membership, mock_account, mock_comments):
        """Collects messages from all sub-operations."""
        messages = self.service._create_related_records("MEM-001", {})

        self.assertEqual(len(messages), 5)
        self.assertIn("Address linked", messages)
        self.assertIn("Mollie synced", messages)
        self.assertIn("Membership created", messages)
        self.assertIn("Account creation queued (ACR-001)", messages)
        self.assertIn("Notes added", messages)

    @patch.object(MijnRoodEventApplicationService, "_apply_mijnrood_comments", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_user_account", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_membership_and_dues", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_mollie_data", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_ensure_address", return_value=None)
    def test_returns_empty_when_all_skipped(self, mock_addr, mock_mollie, mock_membership, mock_account, mock_comments):
        """Returns empty list when all sub-operations are skipped."""
        messages = self.service._create_related_records("MEM-001", {})
        self.assertEqual(messages, [])


class TestEnsureUserAccount(EnhancedTestCase):
    """Tests for _ensure_user_account()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_returns_none_when_setting_disabled(self, mock_frappe):
        """Returns None when create_member_accounts is disabled."""
        mock_frappe.db.get_single_value.return_value = 0

        result = self.service._ensure_user_account("MEM-001")

        self.assertIsNone(result)
        mock_frappe.db.get_single_value.assert_called_once_with(
            "MijnRood Sync Settings", "create_member_accounts"
        )

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_returns_none_when_member_has_user(self, mock_frappe):
        """Returns None when member already has a user account."""
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = "test@example.com"

        result = self.service._ensure_user_account("MEM-001")

        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_queues_account_creation_on_success(self, mock_frappe):
        """Queues ACR and returns message on success."""
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = None  # no user
        mock_frappe._ = frappe._

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"request_name": "ACR-001"}

        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member",
            return_value=mock_result,
        ) as mock_queue:
            result = self.service._ensure_user_account("MEM-001")

        mock_queue.assert_called_once_with(
            "MEM-001",
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            priority="Low",
        )
        self.assertIn("ACR-001", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_returns_none_on_expected_failure(self, mock_frappe):
        """Returns None when queue function returns failure (e.g., no email)."""
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = None  # no user

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "Member must have an email address"

        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member",
            return_value=mock_result,
        ):
            result = self.service._ensure_user_account("MEM-001")

        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_returns_error_message_on_exception(self, mock_frappe):
        """Returns error message when queue function raises an exception."""
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = None  # no user
        mock_frappe._ = frappe._

        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member",
            side_effect=Exception("Permission denied"),
        ):
            result = self.service._ensure_user_account("MEM-001")

        self.assertIsNotNone(result)
        self.assertIn("Permission denied", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_handles_none_result_data(self, mock_frappe):
        """Handles success result with None data gracefully."""
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = None
        mock_frappe._ = frappe._

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = None

        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member",
            return_value=mock_result,
        ):
            result = self.service._ensure_user_account("MEM-001")

        self.assertIsNotNone(result)
        self.assertIn("Account creation queued", result)


class TestAcrDeduplication(EnhancedTestCase):
    """Tests for per-run ACR deduplication via _acr_queued_members."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_acr_set_cleared_on_apply_event(self):
        """_acr_queued_members is cleared at the start of each apply_event() call."""
        self.service._acr_queued_members.add("MEM-OLD")
        # Calling apply_event on a non-existent event will fail, but the set
        # should already be cleared before the event is fetched.
        with patch(
            "verenigingen.mijnrood_sync.services.event_application_service.frappe"
        ) as mock_frappe:
            mock_frappe.get_doc.side_effect = Exception("not found")
            try:
                self.service.apply_event("FAKE-001")
            except Exception:
                pass
        self.assertEqual(len(self.service._acr_queued_members), 0)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_skips_when_already_queued(self, mock_frappe):
        """_ensure_user_account skips when member already in _acr_queued_members."""
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = None  # no user

        self.service._acr_queued_members.add("MEM-001")

        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member"
        ) as mock_queue:
            result = self.service._ensure_user_account("MEM-001")

        self.assertIsNone(result)
        mock_queue.assert_not_called()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_adds_to_set_on_success(self, mock_frappe):
        """Member added to _acr_queued_members after successful queue."""
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = None  # no user
        mock_frappe._ = frappe._

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"request_name": "ACR-001"}

        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member",
            return_value=mock_result,
        ):
            self.service._ensure_user_account("MEM-001")

        self.assertIn("MEM-001", self.service._acr_queued_members)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_volunteer_creation_marks_acr_queued(self, mock_frappe):
        """_ensure_volunteer marks member in _acr_queued_members when creating account."""
        mock_frappe._ = frappe._

        config = {"create_volunteer": True, "verenigingen_role": "Admin", "role_profile": None}

        with patch(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
            return_value=None,
        ), patch(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.create_volunteer_from_member",
            return_value={"success": True, "volunteer": "VOL-001"},
        ):
            self.service._ensure_volunteer("MEM-001", config, event=None)

        self.assertIn("MEM-001", self.service._acr_queued_members)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_dual_acr_scenario_second_call_skipped(self, mock_frappe):
        """When _ensure_volunteer queues ACR, _ensure_user_account skips for same member."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_single_value.return_value = 1
        mock_frappe.db.get_value.return_value = None  # no user

        config = {"create_volunteer": True, "verenigingen_role": "Admin", "role_profile": None}

        # First: volunteer creation marks ACR as queued
        with patch(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
            return_value=None,
        ), patch(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.create_volunteer_from_member",
            return_value={"success": True, "volunteer": "VOL-001"},
        ):
            self.service._ensure_volunteer("MEM-001", config, event=None)

        # Second: _ensure_user_account should skip
        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member"
        ) as mock_queue:
            result = self.service._ensure_user_account("MEM-001")

        self.assertIsNone(result)
        mock_queue.assert_not_called()


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
    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
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

    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
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
    @patch.object(MijnRoodMemberSyncService, "find_existing_member_or_conflict")
    @patch.object(MijnRoodMappingService, "map_member_fields")
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
    @patch.object(MijnRoodMemberSyncService, "find_existing_member_or_conflict")
    @patch.object(MijnRoodMappingService, "map_member_fields")
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
    @patch.object(MijnRoodMemberSyncService, "find_existing_member_or_conflict")
    @patch.object(MijnRoodMappingService, "map_member_fields")
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


# ─── Tests for _ensure_team_membership ────────────────────────────────


class TestEnsureTeamMembership(EnhancedTestCase):
    """Tests for _ensure_team_membership()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value=None,
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_no_volunteer_returns_error(self, mock_frappe, _mock_get_vol):
        """When member has no Volunteer record, return an error message."""
        mock_frappe._ = frappe._

        result = self.service._ensure_team_membership("MEM-001", "Secretariaat")

        self.assertIn("No Volunteer", result)
        self.assertIn("MEM-001", result)

    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_team_does_not_exist(self, mock_frappe, _mock_get_vol):
        """When team doesn't exist, return error message."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None  # Team not found

        result = self.service._ensure_team_membership("MEM-001", "Ghost Team")

        self.assertIn("does not exist", result)
        self.assertIn("Ghost Team", result)

    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_team_not_active(self, mock_frappe, _mock_get_vol):
        """When team exists but is not Active, return error message."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "Archived"

        result = self.service._ensure_team_membership("MEM-001", "Old Team")

        self.assertIn("not active", result)
        self.assertIn("Archived", result)

    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_already_active_member_returns_none(self, mock_frappe, _mock_get_vol):
        """When volunteer is already an active team member, return None (skip)."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "Active"  # Team is active
        mock_frappe.db.exists.return_value = True  # Already a team member

        result = self.service._ensure_team_membership("MEM-001", "Secretariaat")

        self.assertIsNone(result)
        mock_frappe.get_doc.assert_not_called()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.today")
    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_adds_to_team(self, mock_frappe, _mock_get_vol, mock_today):
        """Happy path: volunteer added to team, team saved."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "Active"
        mock_frappe.db.exists.return_value = False  # Not yet a member
        mock_today.return_value = "2026-02-13"

        mock_team_doc = MagicMock()
        mock_frappe.get_doc.return_value = mock_team_doc

        event = MagicMock()
        event.name = "SYNC-001"

        result = self.service._ensure_team_membership("MEM-001", "Secretariaat", event=event)

        self.assertIn("Added to team", result)
        self.assertIn("Secretariaat", result)
        mock_team_doc.append.assert_called_once_with(
            "team_members",
            {
                "volunteer": "VOL-001",
                "team_role": "Team Member",
                "from_date": "2026-02-13",
                "status": "Active",
                "is_active": 1,
                "notes": "Added via MijnRood sync (event SYNC-001)",
            },
        )
        mock_team_doc.save.assert_called_once_with(ignore_permissions=True)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.today")
    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_save_exception_returns_error(self, mock_frappe, _mock_get_vol, mock_today):
        """When team save raises an exception, return error message and log it."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "Active"
        mock_frappe.db.exists.return_value = False
        mock_today.return_value = "2026-02-13"

        mock_team_doc = MagicMock()
        mock_team_doc.save.side_effect = Exception("DB lock timeout")
        mock_frappe.get_doc.return_value = mock_team_doc

        result = self.service._ensure_team_membership("MEM-001", "Secretariaat")

        self.assertIn("Team addition failed", result)
        self.assertIn("DB lock timeout", result)
        mock_frappe.log_error.assert_called_once()


# ─── Tests for _prune_orphan_team_members ─────────────────────────────


class TestPruneOrphanTeamMembers(EnhancedTestCase):
    """Tests for the defensive child-row prune used by _ensure_team_membership."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def _make_team_doc(self, volunteer_names):
        team_doc = MagicMock()
        rows = []
        for vol in volunteer_names:
            row = MagicMock()
            row.volunteer = vol
            rows.append(row)
        team_doc.team_members = rows
        team_doc.remove = MagicMock(side_effect=lambda r: rows.remove(r))
        return team_doc, rows

    def test_no_rows_returns_zero(self):
        """Empty child table → zero pruned, no DB lookup."""
        team_doc, _rows = self._make_team_doc([])
        with patch(
            "verenigingen.mijnrood_sync.services.event_application_service.frappe"
        ) as mock_frappe:
            result = self.service._prune_orphan_team_members(team_doc, "Some Team")
        self.assertEqual(result, 0)
        mock_frappe.get_all.assert_not_called()
        team_doc.remove.assert_not_called()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_all_volunteers_exist_no_prune(self, mock_frappe):
        """When every referenced volunteer exists, nothing is removed."""
        team_doc, rows = self._make_team_doc(["VOL-A", "VOL-B"])
        mock_frappe.get_all.return_value = ["VOL-A", "VOL-B"]

        result = self.service._prune_orphan_team_members(team_doc, "Some Team")

        self.assertEqual(result, 0)
        team_doc.remove.assert_not_called()
        self.assertEqual(len(rows), 2)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_orphans_are_pruned(self, mock_frappe):
        """Rows referencing deleted volunteers are removed; the rest stay."""
        team_doc, rows = self._make_team_doc(["VOL-A", "VOL-GONE-1", "VOL-B", "VOL-GONE-2"])
        # Only VOL-A and VOL-B still exist in tabVolunteer
        mock_frappe.get_all.return_value = ["VOL-A", "VOL-B"]

        result = self.service._prune_orphan_team_members(team_doc, "Some Team")

        self.assertEqual(result, 2)
        self.assertEqual(team_doc.remove.call_count, 2)
        remaining = [r.volunteer for r in rows]
        self.assertEqual(remaining, ["VOL-A", "VOL-B"])


# ─── Tests for _handle_admin_role_change (transition-only) ────────────


class TestHandleAdminRoleChange(EnhancedTestCase):
    """Tests for transition-only admin role processing."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    def test_admin_unchanged_skips_role_actions(self):
        """ROLE_ADMIN in both old and new → no role actions fire (option 2 fix)."""
        role_config = {"ROLE_ADMIN": {"create_volunteer": 1, "add_to_team": 1, "default_team": "T"}}
        with patch.object(self.service, "_apply_role_actions") as mock_apply:
            messages = self.service._handle_admin_role_change(
                member_name="MEM-001",
                current_roles={"ROLE_ADMIN"},
                old_roles={"ROLE_ADMIN"},
                role_config=role_config,
                event=None,
            )
        mock_apply.assert_not_called()
        self.assertEqual(messages, [])

    def test_admin_added_fires_role_actions(self):
        """ROLE_ADMIN newly granted → _apply_role_actions runs."""
        role_config = {"ROLE_ADMIN": {"create_volunteer": 1}}
        with patch.object(self.service, "_apply_role_actions", return_value=["did stuff"]) as mock_apply:
            messages = self.service._handle_admin_role_change(
                member_name="MEM-001",
                current_roles={"ROLE_ADMIN"},
                old_roles=set(),
                role_config=role_config,
                event=None,
            )
        mock_apply.assert_called_once()
        self.assertIn("did stuff", messages)

    def test_admin_added_on_first_sight_no_old_data(self):
        """First sync (old_roles empty) treats ROLE_ADMIN as a transition."""
        role_config = {"ROLE_ADMIN": {"create_volunteer": 1}}
        with patch.object(self.service, "_apply_role_actions", return_value=[]) as mock_apply:
            self.service._handle_admin_role_change(
                member_name="MEM-001",
                current_roles={"ROLE_ADMIN"},
                old_roles=set(),
                role_config=role_config,
                event=None,
            )
        mock_apply.assert_called_once()

    def test_admin_removed_ends_team_membership(self):
        """ROLE_ADMIN removed → _end_team_membership runs (unchanged behavior)."""
        role_config = {
            "ROLE_ADMIN": {"add_to_team": True, "default_team": "Landelijk Beheer"}
        }
        with patch.object(self.service, "_end_team_membership", return_value="Ended") as mock_end:
            messages = self.service._handle_admin_role_change(
                member_name="MEM-001",
                current_roles=set(),
                old_roles={"ROLE_ADMIN"},
                role_config=role_config,
                event=None,
            )
        mock_end.assert_called_once_with("MEM-001", "Landelijk Beheer", event=None)
        self.assertIn("Ended", messages)


# ─── Tests for _ensure_user_account_for_volunteer ─────────────────────


class TestEnsureUserAccountForVolunteer(EnhancedTestCase):
    """Tests for _ensure_user_account_for_volunteer()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_user_already_exists_returns_none(self, mock_frappe):
        """When member already has a linked User, return None (no-op)."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "user@example.com"

        result = self.service._ensure_user_account_for_volunteer("MEM-001")

        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_acr_already_queued_returns_none(self, mock_frappe):
        """When ACR was already queued this sync run, return None."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None  # No user

        self.service._acr_queued_members.add("MEM-001")

        result = self.service._ensure_user_account_for_volunteer("MEM-001")

        self.assertIsNone(result)

    @patch(
        "verenigingen.utils.account_creation_manager.queue_account_creation_for_member"
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_queues_acr(self, mock_frappe, mock_queue):
        """Happy path: queues ACR with volunteer profile and adds to dedup set."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None  # No user

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"request_name": "ACR-00042"}
        mock_queue.return_value = mock_result

        result = self.service._ensure_user_account_for_volunteer("MEM-001")

        self.assertIn("Account creation queued", result)
        self.assertIn("ACR-00042", result)
        self.assertIn("MEM-001", self.service._acr_queued_members)
        mock_queue.assert_called_once_with(
            "MEM-001",
            roles=["Verenigingen Volunteer"],
            role_profile="Verenigingen Volunteer",
            priority="Medium",
        )

    @patch(
        "verenigingen.utils.account_creation_manager.queue_account_creation_for_member"
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_queue_returns_failure_returns_none(self, mock_frappe, mock_queue):
        """When queue_account_creation returns failure (e.g. no email), return None."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "Member has no email address"
        mock_queue.return_value = mock_result

        result = self.service._ensure_user_account_for_volunteer("MEM-001")

        self.assertIsNone(result)
        self.assertNotIn("MEM-001", self.service._acr_queued_members)

    @patch(
        "verenigingen.utils.account_creation_manager.queue_account_creation_for_member"
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_queue_exception_returns_error(self, mock_frappe, mock_queue):
        """When queue function raises an exception, return error message."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None
        mock_queue.side_effect = Exception("Redis connection refused")

        result = self.service._ensure_user_account_for_volunteer("MEM-001")

        self.assertIn("Account creation failed", result)
        self.assertIn("Redis connection refused", result)


# ─── Tests for _ensure_employee_for_profile ───────────────────────────


class TestEnsureEmployeeForProfile(EnhancedTestCase):
    """Tests for _ensure_employee_for_profile() in user_role_profile_calculator."""

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_no_profile_name_is_noop(self, mock_frappe):
        """Empty/None profile name returns immediately."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        _ensure_employee_for_profile("user@example.com", "")
        _ensure_employee_for_profile("user@example.com", None)

        mock_frappe.get_cached_doc.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_profile_without_employee_role_is_noop(self, mock_frappe):
        """When the target profile doesn't include Employee role, skip."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_profile = MagicMock()
        mock_role = MagicMock()
        mock_role.role = "Verenigingen Member"
        mock_profile.roles = [mock_role]
        mock_frappe.get_cached_doc.return_value = mock_profile

        _ensure_employee_for_profile("user@example.com", "Verenigingen Member")

        mock_frappe.db.exists.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_employee_already_exists_is_noop(self, mock_frappe):
        """When Employee already exists for the user, skip creation."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_profile = MagicMock()
        mock_role = MagicMock()
        mock_role.role = "Employee"
        mock_profile.roles = [mock_role]
        mock_frappe.get_cached_doc.return_value = mock_profile
        mock_frappe.db.exists.return_value = True

        _ensure_employee_for_profile("user@example.com", "Verenigingen Staff")

        mock_frappe.new_doc.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_profile_not_found_is_noop(self, mock_frappe):
        """When the profile doesn't exist, skip gracefully."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_frappe.DoesNotExistError = frappe.DoesNotExistError
        mock_frappe.get_cached_doc.side_effect = frappe.DoesNotExistError("Not found")

        _ensure_employee_for_profile("user@example.com", "Nonexistent Profile")

        mock_frappe.db.exists.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_no_linked_member_logs_warning(self, mock_frappe):
        """When no Member record is linked to the user, log warning and skip."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_profile = MagicMock()
        mock_role = MagicMock()
        mock_role.role = "Employee"
        mock_profile.roles = [mock_role]
        mock_frappe.get_cached_doc.return_value = mock_profile
        mock_frappe.db.exists.return_value = False
        mock_frappe.db.get_value.return_value = None  # No member

        mock_logger = MagicMock()
        mock_frappe.logger.return_value = mock_logger

        _ensure_employee_for_profile("user@example.com", "Verenigingen Staff")

        mock_logger.warning.assert_called_once()
        mock_frappe.new_doc.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_no_company_configured_logs_warning(self, mock_frappe):
        """When Verenigingen Settings has no company, log warning and skip."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_profile = MagicMock()
        mock_role = MagicMock()
        mock_role.role = "Employee"
        mock_profile.roles = [mock_role]
        mock_frappe.get_cached_doc.return_value = mock_profile
        mock_frappe.db.exists.return_value = False
        mock_frappe.db.get_value.return_value = {"first_name": "Jan", "last_name": "Bakker"}
        mock_frappe.db.get_single_value.return_value = None  # No company

        mock_logger = MagicMock()
        mock_frappe.logger.return_value = mock_logger

        _ensure_employee_for_profile("user@example.com", "Verenigingen Staff")

        mock_logger.warning.assert_called_once()
        mock_frappe.new_doc.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_happy_path_creates_employee(self, mock_frappe):
        """Happy path: creates Employee with correct fields."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_profile = MagicMock()
        mock_role = MagicMock()
        mock_role.role = "Employee"
        mock_profile.roles = [mock_role]
        mock_frappe.get_cached_doc.return_value = mock_profile
        mock_frappe.DoesNotExistError = frappe.DoesNotExistError
        mock_frappe.DuplicateEntryError = frappe.DuplicateEntryError
        mock_frappe.db.exists.return_value = False
        mock_frappe.db.get_value.return_value = frappe._dict(
            {"first_name": "Geert", "last_name": "van Schaik"}
        )
        mock_frappe.db.get_single_value.return_value = "Veganisme Vereniging"
        mock_frappe.utils.today.return_value = "2026-02-13"

        mock_emp = MagicMock()
        mock_frappe.new_doc.return_value = mock_emp

        mock_logger = MagicMock()
        mock_frappe.logger.return_value = mock_logger

        _ensure_employee_for_profile("geert@example.com", "Verenigingen Staff")

        mock_frappe.new_doc.assert_called_once_with("Employee")
        self.assertEqual(mock_emp.first_name, "Geert")
        self.assertEqual(mock_emp.last_name, "van Schaik")
        self.assertEqual(mock_emp.employee_name, "Geert van Schaik")
        self.assertEqual(mock_emp.company, "Veganisme Vereniging")
        self.assertEqual(mock_emp.user_id, "geert@example.com")
        self.assertEqual(mock_emp.status, "Active")
        # Verify Employee insert used system-level permissions (production code
        # creates Employee for role profile compatibility, not user-initiated)
        insert_kwargs = mock_emp.insert.call_args
        self.assertTrue(insert_kwargs.kwargs.get("ignore_permissions"))
        mock_logger.info.assert_called_once()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_duplicate_entry_handled_gracefully(self, mock_frappe):
        """Race condition: concurrent Employee creation doesn't raise."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_profile = MagicMock()
        mock_role = MagicMock()
        mock_role.role = "Employee"
        mock_profile.roles = [mock_role]
        mock_frappe.get_cached_doc.return_value = mock_profile
        mock_frappe.DoesNotExistError = frappe.DoesNotExistError
        mock_frappe.DuplicateEntryError = frappe.DuplicateEntryError
        mock_frappe.db.exists.return_value = False
        mock_frappe.db.get_value.return_value = frappe._dict(
            {"first_name": "Jan", "last_name": "Bakker"}
        )
        mock_frappe.db.get_single_value.return_value = "Veganisme Vereniging"
        mock_frappe.utils.today.return_value = "2026-02-13"

        mock_emp = MagicMock()
        mock_emp.insert.side_effect = frappe.DuplicateEntryError("Duplicate")
        mock_frappe.new_doc.return_value = mock_emp

        mock_logger = MagicMock()
        mock_frappe.logger.return_value = mock_logger

        # Should not raise
        _ensure_employee_for_profile("jan@example.com", "Verenigingen Staff")

        mock_logger.debug.assert_called_once()
        mock_logger.error.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.frappe")
    def test_unexpected_exception_logged_as_error(self, mock_frappe):
        """Unexpected insert failure is logged as error but doesn't raise."""
        from verenigingen.utils.user_role_profile_calculator import (
            _ensure_employee_for_profile,
        )

        mock_profile = MagicMock()
        mock_role = MagicMock()
        mock_role.role = "Employee"
        mock_profile.roles = [mock_role]
        mock_frappe.get_cached_doc.return_value = mock_profile
        mock_frappe.DoesNotExistError = frappe.DoesNotExistError
        mock_frappe.DuplicateEntryError = frappe.DuplicateEntryError
        mock_frappe.db.exists.return_value = False
        mock_frappe.db.get_value.return_value = frappe._dict(
            {"first_name": "Jan", "last_name": "Bakker"}
        )
        mock_frappe.db.get_single_value.return_value = "Veganisme Vereinigung"
        mock_frappe.utils.today.return_value = "2026-02-13"

        mock_emp = MagicMock()
        mock_emp.insert.side_effect = Exception("Something unexpected")
        mock_frappe.new_doc.return_value = mock_emp

        mock_logger = MagicMock()
        mock_frappe.logger.return_value = mock_logger

        # Should not raise
        _ensure_employee_for_profile("jan@example.com", "Verenigingen Staff")

        mock_logger.error.assert_called_once()


class TestEndChapterBoardMembership(EnhancedTestCase):
    """Tests for _end_chapter_board_membership().

    Regression tests for board member removal on division contact revocation.
    The method should delete the board member row (not just deactivate it)
    by delegating to BoardManager.bulk_remove_board_members().
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value=None)
    def test_unresolvable_division_returns_error(self, _mock_resolve):
        """When division_id doesn't resolve to a Chapter, return error message."""
        result = self.service._end_chapter_board_membership("MEM-001", 999)

        self.assertIsNotNone(result)
        self.assertIn("999", result)
        self.assertIn("does not match", result)

    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value=None,
    )
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Amsterdam")
    def test_no_volunteer_returns_none(self, _mock_resolve, _mock_get_vol):
        """When member has no Volunteer record, return None (nothing to remove)."""
        result = self.service._end_chapter_board_membership("MEM-001", 11)

        self.assertIsNone(result)

    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Amsterdam")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_not_on_board_returns_none(self, mock_frappe, _mock_resolve, _mock_get_vol):
        """When volunteer has no active board membership, return None."""
        mock_frappe._ = frappe._
        mock_chapter = MagicMock()
        mock_chapter.board_members = []  # No board members at all
        mock_frappe.get_doc.return_value = mock_chapter

        result = self.service._end_chapter_board_membership("MEM-001", 11)

        self.assertIsNone(result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.today", return_value="2026-02-18")
    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Eindhoven")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_happy_path_delegates_to_board_manager(
        self, mock_frappe, _mock_resolve, _mock_get_vol, _mock_today
    ):
        """Happy path: finds active board member, delegates removal to BoardManager."""
        mock_frappe._ = frappe._
        mock_bm = MagicMock()
        mock_bm.volunteer = "VOL-001"
        mock_bm.is_active = 1
        mock_bm.chapter_role = "Voorzitter"
        mock_bm.from_date = "2026-01-01"

        mock_chapter = MagicMock()
        mock_chapter.board_members = [mock_bm]
        mock_chapter.board_manager.bulk_remove_board_members.return_value = {
            "success": True,
            "processed": 1,
        }
        mock_frappe.get_doc.return_value = mock_chapter

        event = MagicMock()
        event.name = "MR-SYNC-2026-05523"

        result = self.service._end_chapter_board_membership("MEM-001", 11, event=event)

        self.assertIn("Removed from chapter", result)
        self.assertIn("Eindhoven", result)
        mock_chapter.board_manager.bulk_remove_board_members.assert_called_once()
        call_args = mock_chapter.board_manager.bulk_remove_board_members.call_args[0][0]
        self.assertEqual(len(call_args), 1)
        self.assertEqual(call_args[0]["volunteer"], "VOL-001")
        self.assertEqual(call_args[0]["chapter_role"], "Voorzitter")
        self.assertEqual(call_args[0]["end_date"], "2026-02-18")
        self.assertIn("MR-SYNC-2026-05523", call_args[0]["reason"])

    @patch("verenigingen.mijnrood_sync.services.event_application_service.today", return_value="2026-02-18")
    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Eindhoven")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_board_manager_failure_returns_error(
        self, mock_frappe, _mock_resolve, _mock_get_vol, _mock_today
    ):
        """When BoardManager returns failure, return error message."""
        mock_frappe._ = frappe._
        mock_bm = MagicMock()
        mock_bm.volunteer = "VOL-001"
        mock_bm.is_active = 1
        mock_bm.chapter_role = "Secretaris"
        mock_bm.from_date = "2026-01-01"

        mock_chapter = MagicMock()
        mock_chapter.board_members = [mock_bm]
        mock_chapter.board_manager.bulk_remove_board_members.return_value = {
            "success": False,
            "error": "Save failed",
        }
        mock_frappe.get_doc.return_value = mock_chapter

        result = self.service._end_chapter_board_membership("MEM-001", 11)

        self.assertIn("board removal failed", result)
        self.assertIn("Save failed", result)

    @patch("verenigingen.mijnrood_sync.services.event_application_service.today", return_value="2026-02-18")
    @patch(
        "verenigingen.verenigingen.doctype.volunteer.volunteer.get_volunteer_for_member",
        return_value="VOL-001",
    )
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Eindhoven")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_exception_returns_error_and_logs(
        self, mock_frappe, _mock_resolve, _mock_get_vol, _mock_today
    ):
        """When an exception occurs, return error message and log."""
        mock_frappe._ = frappe._
        mock_frappe.get_traceback.return_value = "traceback"
        mock_bm = MagicMock()
        mock_bm.volunteer = "VOL-001"
        mock_bm.is_active = 1
        mock_bm.chapter_role = "Penningmeester"
        mock_bm.from_date = "2026-01-01"

        mock_chapter = MagicMock()
        mock_chapter.board_members = [mock_bm]
        mock_chapter.board_manager.bulk_remove_board_members.side_effect = Exception("DB lock timeout")
        mock_frappe.get_doc.return_value = mock_chapter

        result = self.service._end_chapter_board_membership("MEM-001", 11)

        self.assertIn("board removal failed", result)
        self.assertIn("DB lock timeout", result)
        mock_frappe.log_error.assert_called_once()


class TestHandleDivisionContactChange(EnhancedTestCase):
    """Tests for _handle_division_contact_change().

    Regression tests for the division contact removal flow — verifies that
    removed divisions trigger board member deletion and notification.
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_no_removals_no_action(self, mock_frappe):
        """When no divisions were removed, no board removal or notification occurs."""
        mock_frappe._ = frappe._
        role_config = {}

        result = self.service._handle_division_contact_change(
            member_name="MEM-001",
            new_division_ids=[10, 11],
            old_division_ids=[10, 11],
            role_config=role_config,
        )

        self.assertEqual(result, [])

    @patch.object(MijnRoodEventApplicationService, "_notify_board_membership_change")
    @patch.object(
        MijnRoodEventApplicationService,
        "_end_chapter_board_membership",
        return_value="Removed from chapter 'Eindhoven' board",
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_removed_division_triggers_board_removal(
        self, mock_frappe, mock_end_board, mock_notify
    ):
        """When a division is removed, _end_chapter_board_membership is called."""
        mock_frappe._ = frappe._
        event = MagicMock()
        role_config = {}

        result = self.service._handle_division_contact_change(
            member_name="MEM-001",
            new_division_ids=[10],
            old_division_ids=[10, 11],
            role_config=role_config,
            event=event,
        )

        mock_end_board.assert_called_once_with("MEM-001", 11, event=event)
        self.assertIn("Removed from chapter 'Eindhoven' board", result)
        mock_notify.assert_called_once_with("MEM-001", {11}, event)

    @patch.object(MijnRoodEventApplicationService, "_notify_board_membership_change")
    @patch.object(
        MijnRoodEventApplicationService,
        "_end_chapter_board_membership",
        return_value="Removed from chapter 'Eindhoven' board",
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_all_divisions_removed(self, mock_frappe, mock_end_board, mock_notify):
        """When all divisions are removed, all get processed."""
        mock_frappe._ = frappe._
        role_config = {}

        result = self.service._handle_division_contact_change(
            member_name="MEM-001",
            new_division_ids=[],
            old_division_ids=[10, 11],
            role_config=role_config,
        )

        self.assertEqual(mock_end_board.call_count, 2)
        mock_notify.assert_called_once()

    @patch.object(MijnRoodEventApplicationService, "_notify_board_membership_change")
    @patch.object(
        MijnRoodEventApplicationService,
        "_end_chapter_board_membership",
        side_effect=Exception("Unexpected error"),
    )
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_partial_failure_continues(self, mock_frappe, mock_end_board, mock_notify):
        """When one division removal fails, others still process and notification fires."""
        mock_frappe._ = frappe._
        role_config = {}

        result = self.service._handle_division_contact_change(
            member_name="MEM-001",
            new_division_ids=[],
            old_division_ids=[10, 11],
            role_config=role_config,
        )

        # Both were attempted
        self.assertEqual(mock_end_board.call_count, 2)
        # Error messages captured
        self.assertEqual(len(result), 2)
        self.assertTrue(all("Failed to end board membership" in msg for msg in result))
        # Notification still sent
        mock_notify.assert_called_once()

    @patch.object(MijnRoodEventApplicationService, "_end_chapter_board_membership", return_value=None)
    @patch.object(MijnRoodEventApplicationService, "_notify_board_membership_change")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_none_result_not_appended(self, mock_frappe, mock_notify, mock_end_board):
        """When _end_chapter_board_membership returns None (not on board), no message added."""
        mock_frappe._ = frappe._
        role_config = {}

        result = self.service._handle_division_contact_change(
            member_name="MEM-001",
            new_division_ids=[10],
            old_division_ids=[10, 11],
            role_config=role_config,
        )

        self.assertEqual(result, [])
        mock_notify.assert_called_once()


class TestNotifyBoardMembershipChange(EnhancedTestCase):
    """Tests for _notify_board_membership_change().

    Verifies notification uses the Verenigingen Email Configuration system
    via notify_administrators with the chapter_board_removed key.
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch("verenigingen.utils.notification_helpers.notify_administrators")
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Eindhoven")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_sends_notification_with_correct_key(self, mock_frappe, _mock_resolve, mock_notify):
        """Notification uses chapter_board_removed key and Chapter category."""
        mock_frappe._ = frappe._
        mock_frappe.session.user = "admin@example.com"
        event = MagicMock()
        event.name = "MR-SYNC-2026-05523"

        self.service._notify_board_membership_change("MEM-001", {11}, event)

        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args[1]
        self.assertEqual(call_kwargs["notification_key"], "chapter_board_removed")
        self.assertEqual(call_kwargs["category"], "Chapter")
        self.assertEqual(call_kwargs["document_type"], "MijnRood Sync Event")
        self.assertEqual(call_kwargs["document_name"], "MR-SYNC-2026-05523")
        self.assertIn("MEM-001", call_kwargs["subject"])

    @patch("verenigingen.utils.notification_helpers.notify_administrators")
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Eindhoven")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_also_sends_realtime(self, mock_frappe, _mock_resolve, _mock_notify):
        """Also publishes a realtime event for the current session."""
        mock_frappe._ = frappe._
        mock_frappe.session.user = "admin@example.com"
        event = MagicMock()
        event.name = "SYNC-001"

        self.service._notify_board_membership_change("MEM-001", {11}, event)

        mock_frappe.publish_realtime.assert_called_once()
        call_kwargs = mock_frappe.publish_realtime.call_args
        self.assertEqual(call_kwargs[0][0], "board_membership_ended")

    @patch("verenigingen.utils.notification_helpers.notify_administrators")
    @patch.object(MijnRoodMappingService, "resolve_division_id", return_value="Eindhoven")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_notification_failure_does_not_raise(self, mock_frappe, _mock_resolve, mock_notify):
        """If notify_administrators raises, the error is logged but not re-raised."""
        mock_frappe._ = frappe._
        mock_frappe.session.user = "admin@example.com"
        mock_notify.side_effect = Exception("Email config broken")

        # Should not raise
        self.service._notify_board_membership_change("MEM-001", {11})


class TestPromoteApplicationMember(EnhancedTestCase):
    """Tests for the shared _promote_application_member() helper.

    This helper centralizes the promotion logic so both the correlator-driven
    _apply_approved path and the apply-time _try_promote_application safety net
    set member.status = "Active" (previously an omission in _try_promote_application).
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_create_related_records", return_value=[])
    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
    def test_sets_member_status_active_for_active_mijnrood_status(self, mock_frappe, mock_related):
        """When new_data.current_membership_status_id is an active id, member.status → Active."""
        mock_frappe._ = frappe._
        event = MagicMock()
        event.name = "EVT-PROMOTE-1"

        with patch(
            "verenigingen.services.csv_import.member_import_service.get_member_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_or_update_member.return_value = ("updated", "MEM-001")
            mock_get_svc.return_value = mock_svc

            old_data = {"id": 42, "email": "jane@example.com"}
            new_data = {"id": 1234, "email": "jane@example.com", "current_membership_status_id": 1}
            row_data = {"member_id": "1234", "email": "jane@example.com"}

            result = self.service._promote_application_member(
                "MEM-001", old_data, new_data, row_data, event
            )

        self.assertTrue(result["success"])
        # Verify set_value updated BOTH application_status AND status
        # (one call with a dict containing both keys)
        updates = None
        for call in mock_frappe.db.set_value.call_args_list:
            if call.args[0] == "Member" and isinstance(call.args[2], dict):
                updates = call.args[2]
                break
        self.assertIsNotNone(updates, "Expected a dict-update set_value call on Member")
        self.assertEqual(updates.get("application_status"), "Approved")
        self.assertEqual(updates.get("status"), "Active")

    @patch.object(MijnRoodEventApplicationService, "_create_related_records", return_value=[])
    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
    def test_logs_warning_for_unexpected_mijnrood_status(self, mock_frappe, mock_related):
        """An unexpected status_id (e.g. terminated during promotion) logs and does
        NOT overwrite member.status — only application_status flips."""
        mock_frappe._ = frappe._
        event = MagicMock()
        event.name = "EVT-PROMOTE-2"

        with patch(
            "verenigingen.services.csv_import.member_import_service.get_member_import_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.create_or_update_member.return_value = ("updated", "MEM-001")
            mock_get_svc.return_value = mock_svc

            old_data = {"id": 42, "email": "jane@example.com"}
            # status_id=3 is "opgezegd" (terminated) — unexpected on a promotion
            new_data = {"id": 1234, "email": "jane@example.com", "current_membership_status_id": 3}
            row_data = {"member_id": "1234", "email": "jane@example.com"}

            self.service._promote_application_member(
                "MEM-001", old_data, new_data, row_data, event
            )

        # The single set_value call should carry application_status but NOT status
        updates = None
        for call in mock_frappe.db.set_value.call_args_list:
            if call.args[0] == "Member" and isinstance(call.args[2], dict):
                updates = call.args[2]
                break
        self.assertIsNotNone(updates)
        self.assertEqual(updates.get("application_status"), "Approved")
        self.assertNotIn("status", updates)


class TestApplyApproved(EnhancedTestCase):
    """Tests for _apply_approved() — correlator-driven promotion."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodApplicationSyncService, "promote_application_member")
    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
    def test_uses_linked_member_when_set(self, mock_frappe, mock_promote):
        """When event.linked_member is set, promote that member directly."""
        mock_frappe._ = frappe._
        mock_promote.return_value = {"success": True, "message": "promoted"}

        event = MagicMock()
        event.linked_member = "MEM-001"
        event.old_data = json.dumps({"id": 42, "email": "jane@example.com", "last_name": "Doe"})
        event.new_data = json.dumps({
            "id": 1234, "email": "jane@example.com", "last_name": "Doe",
            "current_membership_status_id": 1,
        })

        result = self.service._apply_approved(event)

        self.assertTrue(result["success"])
        mock_promote.assert_called_once()
        # First arg is member_name
        self.assertEqual(mock_promote.call_args.args[0], "MEM-001")

    @patch.object(MijnRoodApplicationSyncService, "promote_application_member")
    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
    def test_falls_back_to_application_id_lookup(self, mock_frappe, mock_promote):
        """Without linked_member, locate by application_id = f'MR-APP-{old_id}'."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = "MEM-002"
        mock_promote.return_value = {"success": True, "message": "promoted"}

        event = MagicMock()
        event.linked_member = None
        event.old_data = json.dumps({"id": 99, "email": "jane@example.com", "last_name": "Doe"})
        event.new_data = json.dumps({
            "id": 5678, "email": "jane@example.com", "last_name": "Doe",
            "current_membership_status_id": 1,
        })

        result = self.service._apply_approved(event)

        self.assertTrue(result["success"])
        # First get_value call should be for application_id
        first_call = mock_frappe.db.get_value.call_args_list[0]
        self.assertEqual(first_call.args[0], "Member")
        self.assertEqual(first_call.args[1], {"application_id": "MR-APP-99"})
        self.assertEqual(mock_promote.call_args.args[0], "MEM-002")

    @patch.object(MijnRoodEventApplicationService, "_apply_new_member")
    @patch.object(MijnRoodApplicationSyncService, "promote_application_member")
    @patch("verenigingen.mijnrood_sync.services.event_application.application_sync_service.frappe")
    def test_falls_through_to_new_member_when_not_found(
        self, mock_frappe, mock_promote, mock_apply_new
    ):
        """If no existing member can be located, fall through to _apply_new_member."""
        mock_frappe._ = frappe._
        mock_frappe.db.get_value.return_value = None
        mock_apply_new.return_value = {"success": True, "message": "created"}

        event = MagicMock()
        event.linked_member = None
        event.old_data = json.dumps({"id": 99, "email": "ghost@example.com", "last_name": "Doe"})
        event.new_data = json.dumps({
            "id": 5678, "email": "ghost@example.com", "last_name": "Doe",
            "current_membership_status_id": 1,
        })

        result = self.service._apply_approved(event)

        self.assertTrue(result["success"])
        mock_apply_new.assert_called_once_with(event)
        mock_promote.assert_not_called()


class TestApplyEventDispatchesApproved(EnhancedTestCase):
    """Verify apply_event dispatches Approved events to _apply_approved."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()

    @patch.object(MijnRoodEventApplicationService, "_apply_approved")
    @patch("verenigingen.mijnrood_sync.services.event_application_service.frappe")
    def test_approved_event_routes_to_apply_approved(self, mock_frappe, mock_apply_approved):
        """apply_event('...') with event_type='Approved' calls _apply_approved."""
        mock_frappe._ = frappe._
        event_doc = MagicMock()
        event_doc.status = "Approved"
        event_doc.event_type = "Approved"
        mock_frappe.get_doc.return_value = event_doc
        mock_apply_approved.return_value = {"success": True, "message": "ok"}

        result = self.service.apply_event("EVT-APPROVED-1")

        self.assertTrue(result["success"])


class TestApprovedEventCreatesMembershipAndDues(EnhancedTestCase):
    """Integration regression test: an Approved event must result in a
    Membership + Dues Schedule being created (the bug that
    _try_promote_application forgot to flip member.status to Active,
    which _ensure_membership_and_dues requires).

    Uses real DB for the promotion pipeline. Customer creation inside
    Member.after_insert is mocked out — it's an unrelated side effect that
    depends on Selling Settings configuration (which varies across test
    environments) and is not part of this regression's scope.
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()
        # Patch out Customer creation; Member.after_insert calls this and the
        # test env has a group-type customer_group in Selling Settings that
        # would fail ERPNext's Customer validation. Out of scope for this test.
        self._customer_patcher = patch(
            "verenigingen.services.customer_handling_service.CustomerHandlingService"
            ".create_customer_for_member",
            return_value=None,
        )
        self._customer_patcher.start()
        self.addCleanup(self._customer_patcher.stop)

    def _create_pending_member(self, email="promoted@example.com", app_mijnrood_id=99):
        """Create a Pending Member analogous to what _apply_new_membership_application creates."""
        member = frappe.new_doc("Member")
        member.first_name = "Jane"
        member.last_name = "Doe"
        member.email = email
        member.application_id = f"MR-APP-{app_mijnrood_id}"
        member.application_status = "Pending"
        member.status = "Pending"
        member.application_date = frappe.utils.today()
        member._csv_import = True
        member._system_update = True
        member.flags.ignore_workflow = True
        member.insert(ignore_permissions=True)
        frappe.db.commit()
        return member.name

    def _create_approved_sync_event(self, pending_member_name, old_data, new_data):
        """Synthesize and persist an Approved MijnRood Sync Event (test factory helper)."""
        new_member_id = new_data["id"]
        event = frappe.new_doc("MijnRood Sync Event")
        event.event_type = "Approved"
        event.mijnrood_table = "admin_member"
        event.mijnrood_row_id = new_member_id
        event.status = "Approved"
        event.linked_member = pending_member_name
        event.old_data = json.dumps(old_data)
        event.new_data = json.dumps(new_data)
        event.change_summary = "Test approved event"
        event.change_tags = "Approved"
        event.detected_at = frappe.utils.now_datetime()
        event.sync_run_id = "test-run-001"
        event.insert(ignore_permissions=True)
        frappe.db.commit()
        return event.name

    def test_approved_event_flips_status_and_creates_membership(self):
        """Applying an Approved event promotes the Pending Member to Active
        AND downstream creates a Membership + Dues Schedule."""
        # Use a hash-based suffix to avoid collision with leftover test data
        suffix = frappe.generate_hash(length=8)
        email = f"promo-{suffix}@example.com"
        # Use large integers unlikely to conflict with real MijnRood IDs or other test runs
        app_id = int(suffix[:6], 16) + 9_000_000
        new_member_id = int(suffix[2:8], 16) + 8_000_000

        pending_member_name = self._create_pending_member(email=email, app_mijnrood_id=app_id)

        # Synthesize an Approved event as the correlator would.
        # contribution_period uses MijnRood's integer constants: 0=Monthly, 1=Quarterly, 2=Annually.
        old_data = {
            "id": app_id,
            "email": email,
            "first_name": "Jane",
            "last_name": "Doe",
        }
        new_data = {
            "id": new_member_id,
            "email": email,
            "first_name": "Jane",
            "last_name": "Doe",
            "current_membership_status_id": 1,  # active
            "contribution_per_period_in_cents": 1000,  # €10
            "contribution_period": 2,  # annual (2=Jaarlijks → csv_annual_dues_schedule)
        }

        event_name = self._create_approved_sync_event(pending_member_name, old_data, new_data)

        # Apply the event
        result = self.service.apply_event(event_name)
        self.assertTrue(result["success"], f"apply_event failed: {result.get('message')}")

        # Assert member state
        member = frappe.get_doc("Member", pending_member_name)
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active", "Bug regression: member.status should flip to Active")
        self.assertEqual(str(member.member_id), str(new_member_id))

        # Assert downstream: Membership created (integration proof of the fix)
        membership = frappe.db.get_value(
            "Membership",
            {"member": pending_member_name, "status": "Active", "docstatus": 1},
            "name",
        )
        self.assertIsNotNone(
            membership,
            "Regression: Membership should be created on promotion now that member.status=Active",
        )

        # Assert Dues Schedule created
        dues = frappe.db.exists(
            "Membership Dues Schedule",
            {"member": pending_member_name, "is_template": 0},
        )
        self.assertTrue(dues, "Regression: Dues Schedule should be created on promotion")
