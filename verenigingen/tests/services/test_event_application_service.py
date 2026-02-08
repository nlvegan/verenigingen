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
