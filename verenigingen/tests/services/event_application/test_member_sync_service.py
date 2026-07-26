"""Real-DB integration tests for MijnRoodMemberSyncService.

find_existing_member_or_conflict is a pure DB lookup — exercised against
real Member rows created via the factory. apply_new_member and
apply_changed_member integrate against MijnRood Sync Event +
MemberImportService; their calls into the peer services
(related_records, volunteer, termination, application) are patched at the
peer service class level — those peers are covered by their own suites.
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    MijnRoodApplicationSyncService,
)
from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    MijnRoodRelatedRecordsOrchestrator,
)
from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    MijnRoodTerminationSyncService,
)
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    MijnRoodVolunteerSyncService,
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


# Counter to ensure unique mijnrood_row_id per inserted event.
_event_row_counter = {"n": 100000}


def _make_event(
    *,
    table: str = "admin_member",
    event_type: str = "New",
    new_data: dict | None = None,
    old_data: dict | None = None,
    changed_fields: list | None = None,
    linked_member: str | None = None,
) -> "frappe.Document":
    """Insert a MijnRood Sync Event doc and return it."""
    _event_row_counter["n"] += 1
    payload = {
        "doctype": "MijnRood Sync Event",
        "mijnrood_table": table,
        "event_type": event_type,
        "mijnrood_row_id": _event_row_counter["n"],
        "status": "Approved",
        "new_data": json.dumps(new_data or {}),
        "old_data": json.dumps(old_data or {}),
        "changed_fields": json.dumps(changed_fields or []),
    }
    if linked_member:
        payload["linked_member"] = linked_member
    doc = frappe.get_doc(payload).insert(ignore_permissions=True)
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

    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodVolunteerSyncService, "_process_member_roles", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodRelatedRecordsOrchestrator, "_create_related_records", return_value=[])
    def test_creates_new_member_when_none_exists(self, mock_create_related, mock_process_roles):
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

        result = get_member_sync_service().apply_new_member(event)

        self.assertTrue(result["success"])
        self.assertTrue(event.linked_member)
        # Verify the Member row was created
        member = frappe.db.get_value(
            "Member", {"member_id": "MR-NEW-1"}, ["first_name", "last_name", "email"], as_dict=True
        )
        self.assertEqual(member.first_name, "Eve")
        self.assertEqual(member.email, "eve-new@example.org")
        # Cross-cutting helpers were called
        mock_create_related.assert_called_once()
        mock_process_roles.assert_called_once()

    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodVolunteerSyncService, "_process_member_roles", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodRelatedRecordsOrchestrator, "_create_related_records", return_value=[])
    def test_idempotent_when_member_already_exists_by_member_id(
        self, mock_create_related, mock_process_roles
    ):
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

        result = get_member_sync_service().apply_new_member(event)

        self.assertTrue(result["success"])
        self.assertIn("already exists", result["message"])
        self.assertEqual(event.linked_member, existing.name)
        # No new member was created; cross-cutting helpers were NOT called
        mock_create_related.assert_not_called()
        mock_process_roles.assert_not_called()

    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(
        MijnRoodApplicationSyncService,
        "try_promote_application",
        return_value={"success": True, "message": "Promoted via test stub"},
    )
    def test_email_conflict_invokes_promotion_fallback(self, mock_promote):
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

        result = get_member_sync_service().apply_new_member(event)

        self.assertTrue(result["success"])
        self.assertIn("Promoted", result["message"])
        mock_promote.assert_called_once()


class TestApplyChangedMember(EnhancedTestCase):
    """Field update happy path, termination short-circuit, and missing-member error."""

    def setUp(self):
        super().setUp()
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Member Sync Change Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 7002,
            "label": "Member Sync Change Test",
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

    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodVolunteerSyncService, "_process_member_roles", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodRelatedRecordsOrchestrator, "_create_related_records", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodRelatedRecordsOrchestrator, "_handle_division_field_change", return_value=None)
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodTerminationSyncService, "_check_and_handle_termination", return_value=None)
    def test_updates_existing_member_fields(
        self, mock_termination, mock_division, mock_create_related, mock_process_roles
    ):
        # Pre-clean to handle prior-run leftovers (MemberImportService commits)
        self._cleanup_member_by_member_id("MR-CHG-1")
        member = self.factory.create_member(
            first_name="Henry",
            last_name="OldName",
            email="henry-change@example.org",
            member_id="MR-CHG-1",
        )
        self.addCleanup(self._cleanup_member_by_member_id, "MR-CHG-1")

        # EnhancedTestDataFactory uniquifies emails — use the stored value in the event.
        # EnhancedTestDataFactory also appends a unique suffix to last_name, so the
        # original "OldName" gets suffixed (e.g. "OldName1"). Use the stored value
        # for old_data and a fresh literal for new_data.
        event = _make_event(
            event_type="Changed",
            new_data={
                "id": "MR-CHG-1",
                "first_name": "Henry",
                "last_name": "NewName",
                "email": member.email,
                "current_membership_status_id": 7002,
            },
            old_data={"id": "MR-CHG-1", "last_name": member.last_name},
            changed_fields=["last_name"],
            linked_member=member.name,
        )
        self.addCleanup(self._cleanup_event, event.name)

        result = get_member_sync_service().apply_changed_member(event)

        self.assertTrue(result["success"])
        updated_last = frappe.db.get_value("Member", member.name, "last_name")
        self.assertEqual(updated_last, "NewName")
        # member_id unchanged here, so no renumber notice
        self.assertNotIn("Member number changed", result["message"])

    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodVolunteerSyncService, "_process_member_roles", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodRelatedRecordsOrchestrator, "_create_related_records", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodRelatedRecordsOrchestrator, "_handle_division_field_change", return_value=None)
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodTerminationSyncService, "_check_and_handle_termination", return_value=None)
    def test_member_id_renumber_is_reported_in_the_message(
        self, mock_termination, mock_division, mock_create_related, mock_process_roles
    ):
        """Applying an event that renumbers the member must say so.

        MijnRood renumbers on application approval (applicant series → member
        series), so the change is legitimate — but the event's changed_fields
        never lists it, because MijnRood's own row id did not change. Without
        this notice the member number is rewritten with nothing to show it.
        """
        self._cleanup_member_by_member_id("MR-CHG-OLD-ID")
        self._cleanup_member_by_member_id("MR-CHG-NEW-ID")
        member = self.factory.create_member(
            first_name="Renumber",
            last_name="Target",
            email="renumber-target@example.org",
            member_id="MR-CHG-OLD-ID",
        )
        self.addCleanup(self._cleanup_member_by_member_id, "MR-CHG-NEW-ID")
        self.addCleanup(self._cleanup_member_by_member_id, "MR-CHG-OLD-ID")

        event = _make_event(
            event_type="Changed",
            new_data={
                "id": "MR-CHG-NEW-ID",
                "first_name": "Renumber",
                "last_name": "Target",
                "email": member.email,
                "current_membership_status_id": 7002,
            },
            old_data={"id": "MR-CHG-OLD-ID", "email": member.email},
            changed_fields=["id"],
            linked_member=member.name,
        )
        self.addCleanup(self._cleanup_event, event.name)

        result = get_member_sync_service().apply_changed_member(event)

        self.assertTrue(result["success"], result.get("message"))
        self.assertIn("Member number changed from MR-CHG-OLD-ID to MR-CHG-NEW-ID", result["message"])
        self.assertEqual(frappe.db.get_value("Member", member.name, "member_id"), "MR-CHG-NEW-ID")

    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodVolunteerSyncService, "_process_member_roles", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodRelatedRecordsOrchestrator, "_create_related_records", return_value=[])
    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(
        MijnRoodTerminationSyncService,
        "_check_and_handle_termination",
        return_value={"success": True, "message": "Termination handled (stub)"},
    )
    def test_termination_short_circuits_field_update(
        self, mock_termination, mock_create_related, mock_process_roles
    ):
        # Pre-clean to handle prior-run leftovers
        self._cleanup_member_by_member_id("MR-CHG-2")
        member = self.factory.create_member(
            first_name="Iris",
            last_name="Terminator",
            email="iris-term@example.org",
            member_id="MR-CHG-2",
        )
        self.addCleanup(self._cleanup_member_by_member_id, "MR-CHG-2")

        event = _make_event(
            event_type="Changed",
            new_data={
                "id": "MR-CHG-2",
                "current_membership_status_id": 7002,
            },
            old_data={"id": "MR-CHG-2"},
            changed_fields=["current_membership_status_id"],
            linked_member=member.name,
        )
        self.addCleanup(self._cleanup_event, event.name)

        result = get_member_sync_service().apply_changed_member(event)

        self.assertTrue(result["success"])
        self.assertIn("Termination handled", result["message"])
        # Other helpers should NOT have been called because termination short-circuited
        mock_process_roles.assert_not_called()
        mock_create_related.assert_not_called()

    # Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites
    @patch.object(MijnRoodTerminationSyncService, "_check_and_handle_termination", return_value=None)
    def test_returns_failure_when_no_linked_member_found(self, mock_termination):
        event = _make_event(
            event_type="Changed",
            new_data={
                "id": "MR-CHG-MISSING",
                "current_membership_status_id": 7002,
            },
        )
        self.addCleanup(self._cleanup_event, event.name)

        result = get_member_sync_service().apply_changed_member(event)

        self.assertFalse(result["success"])
        self.assertIn("No linked member found", result["message"])
