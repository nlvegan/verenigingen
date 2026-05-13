"""Real-DB integration tests for MijnRoodMemberSyncService.

find_existing_member_or_conflict is a pure DB lookup — exercised against
real Member rows created via the factory. apply_new_member and
apply_changed_member integrate against MijnRood Sync Event +
MemberImportService and use a stub orchestrator for the not-yet-extracted
cross-cutting helpers (create_related_records, process_member_roles,
try_promote_application, check_and_handle_termination,
handle_division_field_change).
"""

import json
from unittest.mock import MagicMock

import frappe

from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFindExistingMemberOrConflict(EnhancedTestCase):
    """Lookup-by-member_id-then-email-then-conflict logic."""

    def test_returns_none_when_no_member_matches(self):
        result_name, result_dict = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="999999999", email="ghost-does-not-exist@example.org"
        )
        self.assertIsNone(result_name)
        self.assertIsNone(result_dict)

    def test_matches_by_member_id_first(self):
        member = self.factory.create_member(
            first_name="Bob",
            last_name="Example",
            email="bob-mid@example.org",
            member_id="MR-12345",
        )

        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="MR-12345", email="completely-different@example.org"
        )

        self.assertEqual(name, member.name)
        self.assertTrue(result["success"])
        self.assertIn("MR-12345", result["message"])

    def test_matches_by_email_when_member_id_absent(self):
        member = self.factory.create_member(
            first_name="Carol",
            last_name="Example",
            email="carol-email@example.org",
        )

        # EnhancedTestDataFactory uniquifies emails — use the stored value
        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id=None, email=member.email
        )

        self.assertEqual(name, member.name)
        self.assertTrue(result["success"])

    def test_email_match_with_conflicting_member_id_returns_conflict(self):
        existing = self.factory.create_member(
            first_name="Dan",
            last_name="Example",
            email="dan-conflict@example.org",
            member_id="MR-AAA",
        )

        # EnhancedTestDataFactory uniquifies emails — use the stored value
        name, result = get_member_sync_service().find_existing_member_or_conflict(
            mijnrood_id="MR-BBB", email=existing.email
        )

        self.assertIsNone(name)
        self.assertFalse(result["success"])
        self.assertIn("MR-AAA", result["message"])
        self.assertIn("MR-BBB", result["message"])


class _FakeOrchestrator:
    """Stand-in for MijnRoodEventApplicationService.

    Records calls to the cross-cutting helpers that haven't been
    extracted yet (related records, role processing, promotion fallback,
    termination handling, chapter reassignment). Each helper returns a
    safe default unless overridden per-test.
    """

    def __init__(self):
        self._create_related_records = MagicMock(return_value=[])
        self._process_member_roles = MagicMock(return_value=[])
        self._try_promote_application = MagicMock(return_value=None)
        self._check_and_handle_termination = MagicMock(return_value=None)
        self._handle_division_field_change = MagicMock(return_value=None)


# Counter to ensure unique mijnrood_row_id per inserted event.
_event_row_counter = {"n": 100000}


def _make_event(
    *,
    table: str = "admin_member",
    event_type: str = "New",
    new_data: dict | None = None,
    old_data: dict | None = None,
    changed_fields: list | None = None,
) -> "frappe.Document":
    """Insert a MijnRood Sync Event doc and return it."""
    _event_row_counter["n"] += 1
    doc = frappe.get_doc({
        "doctype": "MijnRood Sync Event",
        "mijnrood_table": table,
        "event_type": event_type,
        "mijnrood_row_id": _event_row_counter["n"],
        "status": "Approved",
        "new_data": json.dumps(new_data or {}),
        "old_data": json.dumps(old_data or {}),
        "changed_fields": json.dumps(changed_fields or []),
    }).insert(ignore_permissions=True)
    return doc


class TestApplyNewMember(EnhancedTestCase):
    """Happy path, idempotent re-apply, and promotion fallback."""

    def setUp(self):
        super().setUp()
        # Status mapping needed so map_member_fields doesn't raise
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Member Sync Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 7001,
            "label": "Member Sync Test",
            "membership_type_string": "test",
            "is_active": 1,
            "verenigingen_membership_type": membership_type.name,
        })
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")

        def _cleanup_status_mapping():
            s = frappe.get_single("MijnRood Sync Settings")
            s.status_mapping = self._original_status_mapping
            s.save(ignore_permissions=True)
            frappe.db.commit()
            frappe.cache().delete_value("mijnrood_status_mapping")

        self.addCleanup(_cleanup_status_mapping)

    def _cleanup_event(self, event_name):
        """Test cleanup helper — force-deletes a MijnRood Sync Event."""
        frappe.delete_doc("MijnRood Sync Event", event_name, ignore_permissions=True, force=True)

    def _cleanup_member_by_member_id(self, member_id):
        """Test cleanup helper — force-deletes a Member by member_id.

        MemberImportService.create_or_update_member commits, so the row
        survives EnhancedTestCase's transaction rollback and pollutes
        subsequent runs.
        """
        name = frappe.db.get_value("Member", {"member_id": member_id}, "name")
        if name:
            frappe.delete_doc("Member", name, ignore_permissions=True, force=True)

    def test_creates_new_member_when_none_exists(self):
        # Pre-clean to handle prior-run leftovers (MemberImportService commits)
        self._cleanup_member_by_member_id("MR-NEW-1")
        event = _make_event(new_data={
            "id": "MR-NEW-1",
            "first_name": "Eve",
            "last_name": "NewMember",
            "email": "eve-new@example.org",
            "current_membership_status_id": 7001,
        })
        self.addCleanup(self._cleanup_event, event.name)
        self.addCleanup(self._cleanup_member_by_member_id, "MR-NEW-1")

        orchestrator = _FakeOrchestrator()
        result = get_member_sync_service().apply_new_member(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertTrue(event.linked_member)
        # Verify the Member row was created
        member = frappe.db.get_value(
            "Member", {"member_id": "MR-NEW-1"}, ["first_name", "last_name", "email"], as_dict=True
        )
        self.assertEqual(member.first_name, "Eve")
        self.assertEqual(member.email, "eve-new@example.org")
        # Cross-cutting helpers were called
        orchestrator._create_related_records.assert_called_once()
        orchestrator._process_member_roles.assert_called_once()

    def test_idempotent_when_member_already_exists_by_member_id(self):
        existing = self.factory.create_member(
            first_name="Frank",
            last_name="Existing",
            email="frank-existing@example.org",
            member_id="MR-EXIST-1",
        )

        # EnhancedTestDataFactory uniquifies emails — use the stored value in the event
        event = _make_event(new_data={
            "id": "MR-EXIST-1",
            "first_name": "Frank",
            "last_name": "Existing",
            "email": existing.email,
            "current_membership_status_id": 7001,
        })
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_member_sync_service().apply_new_member(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertIn("already exists", result["message"])
        self.assertEqual(event.linked_member, existing.name)
        # No new member was created; cross-cutting helpers were NOT called
        orchestrator._create_related_records.assert_not_called()
        orchestrator._process_member_roles.assert_not_called()

    def test_email_conflict_invokes_promotion_fallback(self):
        # Pre-existing member with a different MijnRood id but same email
        # — simulates an application that was promoted on the MijnRood side
        # but never correlated on our end.
        existing = self.factory.create_member(
            first_name="Grace",
            last_name="Promotable",
            email="grace-promo@example.org",
            member_id="MR-OLD-9",
        )

        # EnhancedTestDataFactory uniquifies emails — use the stored value in the event
        event = _make_event(new_data={
            "id": "MR-NEW-9",
            "first_name": "Grace",
            "last_name": "Promotable",
            "email": existing.email,
            "current_membership_status_id": 7001,
        })
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        orchestrator._try_promote_application = MagicMock(
            return_value={"success": True, "message": "Promoted via test stub"}
        )

        result = get_member_sync_service().apply_new_member(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertIn("Promoted", result["message"])
        orchestrator._try_promote_application.assert_called_once()
