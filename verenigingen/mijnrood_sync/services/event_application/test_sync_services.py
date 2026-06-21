# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Integration tests for the MijnRood event-application sibling services.

Covers member_sync_service, application_sync_service, volunteer_sync_service,
termination_sync_service, related_records_orchestrator, and mapping_service.

Everything runs against the real database. The only mock used is at the true
I/O boundary (frappe.publish_realtime in the board-removal notification path).
No business logic is mocked.
"""

import json

import frappe
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    extract_email,
    get_mapping_service,
)
from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    get_termination_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _next_id():
    _next_id.counter += 1
    return 800000 + _next_id.counter


_next_id.counter = 0


class SyncServiceBase(EnhancedTestCase):
    """Shared event-builder + member fixture helpers."""

    def _make_event(self, event_type, table, **fields):
        ev = frappe.new_doc("MijnRood Sync Event")
        ev.event_type = event_type
        ev.status = "Approved"
        ev.mijnrood_table = table
        ev.mijnrood_row_id = fields.pop("row_id", None) or _next_id()
        ev.detected_at = now_datetime()
        for key in ("new_data", "old_data", "changed_fields"):
            if key in fields:
                ev.set(key, json.dumps(fields.pop(key)))
        if fields.get("linked_member"):
            ev.linked_member = fields["linked_member"]
        ev.insert(ignore_permissions=True)
        return ev

    def _make_member(self, **kwargs):
        """Create a Member directly (bypassing workflow) for lookups."""
        m = frappe.new_doc("Member")
        m._csv_import = True
        m.flags.ignore_workflow = True
        m.first_name = kwargs.pop("first_name", "Sync")
        m.last_name = kwargs.pop("last_name", "Member")
        m.status = kwargs.pop("status", "Active")
        for k, v in kwargs.items():
            m.set(k, v)
        m.insert(ignore_permissions=True)
        return m


# ─────────────────────────────────────────────────────────────────────
# mapping_service
# ─────────────────────────────────────────────────────────────────────
class TestMappingService(SyncServiceBase):
    def test_extract_email_valid(self):
        self.assertEqual(extract_email("a@b.com"), "a@b.com")

    def test_extract_email_rejects_non_email(self):
        # MijnRood's email_id column may hold a numeric FK, not an address.
        self.assertIsNone(extract_email("12345"))
        self.assertIsNone(extract_email(12345))
        self.assertIsNone(extract_email(None))
        self.assertIsNone(extract_email(""))

    def test_map_member_fields_basic(self):
        row = get_mapping_service().map_member_fields(
            {
                "id": 555,
                "first_name": "Map",
                "last_name": "Test",
                "email": "map@example.com",
                "current_membership_status_id": 1,
                "contribution_per_period_in_cents": 1500,
                "contribution_period": 1,
            }
        )
        self.assertEqual(row["member_id"], 555)
        self.assertEqual(row["first_name"], "Map")
        self.assertEqual(row["membership_type"], "lid")  # status 1 -> lid (default map)
        self.assertEqual(row["dues_rate"], 15.0)  # cents -> euros
        self.assertEqual(row["payment_period"], "Per kwartaal")  # 1 -> quarterly

    def test_map_member_fields_unmapped_status_raises(self):
        with self.assertRaises(ValueError):
            get_mapping_service().map_member_fields({"id": 1, "current_membership_status_id": 91234})

    def test_map_member_fields_unknown_period_skips_field(self):
        row = get_mapping_service().map_member_fields({"id": 1, "first_name": "X", "contribution_period": 99})
        self.assertNotIn("payment_period", row)

    def test_resolve_division_id_via_chapter_field(self):
        chapter = self.create_test_chapter()
        div_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", div_id)
        frappe.db.commit()
        self.assertEqual(get_mapping_service().resolve_division_id(div_id), chapter.name)

    def test_resolve_division_id_unknown_returns_none(self):
        self.assertIsNone(get_mapping_service().resolve_division_id(_next_id()))


# ─────────────────────────────────────────────────────────────────────
# member_sync_service: find_existing_member_or_conflict
# ─────────────────────────────────────────────────────────────────────
class TestFindExistingMemberOrConflict(SyncServiceBase):
    def test_no_match_returns_none_none(self):
        name, result = get_member_sync_service().find_existing_member_or_conflict(
            _next_id(), f"nomatch.{_next_id()}@example.com"
        )
        self.assertIsNone(name)
        self.assertIsNone(result)

    def test_match_by_member_id(self):
        mid = _next_id()
        m = self._make_member(member_id=str(mid), email=f"byid.{mid}@example.com")
        name, result = get_member_sync_service().find_existing_member_or_conflict(mid, None)
        self.assertEqual(name, m.name)
        self.assertTrue(result["success"])
        self.assertIn("member_id", result["message"])

    def test_match_by_email_when_no_member_id(self):
        email = f"byemail.{_next_id()}@example.com"
        m = self._make_member(email=email)
        name, result = get_member_sync_service().find_existing_member_or_conflict(None, email)
        self.assertEqual(name, m.name)
        self.assertTrue(result["success"])

    def test_email_conflict_with_different_member_id(self):
        # Existing member has member_id A; incoming has member_id B but same email.
        email = f"conflict.{_next_id()}@example.com"
        existing_id = _next_id()
        self._make_member(member_id=str(existing_id), email=email)
        incoming_id = _next_id()
        name, result = get_member_sync_service().find_existing_member_or_conflict(incoming_id, email)
        self.assertIsNone(name)
        self.assertFalse(result["success"])
        self.assertIn("conflicts", result["message"])


# ─────────────────────────────────────────────────────────────────────
# member_sync_service: apply_new_member / apply_changed_member
# ─────────────────────────────────────────────────────────────────────
class TestMemberSyncService(SyncServiceBase):
    def test_apply_new_member_no_data_fails(self):
        ev = self._make_event("New", "admin_member")
        result = get_member_sync_service().apply_new_member(ev)
        self.assertFalse(result["success"])
        self.assertIn("No new data", result["message"])

    def test_apply_new_member_idempotent_when_exists(self):
        mid = _next_id()
        email = f"exists.{mid}@example.com"
        self._make_member(member_id=str(mid), email=email)
        ev = self._make_event(
            "New",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "Dup",
                "last_name": "Member",
                "email": email,
                "current_membership_status_id": 1,
            },
        )
        result = get_member_sync_service().apply_new_member(ev)
        self.assertTrue(result["success"])
        self.assertIn("already exists", result["message"])
        self.assertEqual(ev.linked_member, frappe.db.get_value("Member", {"member_id": str(mid)}, "name"))

    def test_apply_changed_member_no_linked_member_fails(self):
        mid = _next_id()
        ev = self._make_event(
            "Changed",
            "admin_member",
            new_data={"id": mid, "first_name": "Ghost", "current_membership_status_id": 1},
            old_data={"id": mid, "email": f"ghost.{mid}@example.com"},
            changed_fields=[{"field": "first_name", "old": "X", "new": "Ghost"}],
        )
        result = get_member_sync_service().apply_changed_member(ev)
        self.assertFalse(result["success"])
        self.assertIn("No linked member", result["message"])

    def test_apply_changed_member_resolves_by_member_id(self):
        mid = _next_id()
        m = self._make_member(member_id=str(mid), email=f"res.{mid}@example.com", first_name="Before")
        ev = self._make_event(
            "Changed",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "After",
                "last_name": "Member",
                "email": f"res.{mid}@example.com",
                "current_membership_status_id": 1,
            },
            old_data={"id": mid, "email": f"res.{mid}@example.com"},
            changed_fields=[{"field": "first_name", "old": "Before", "new": "After"}],
        )
        result = get_member_sync_service().apply_changed_member(ev)
        self.assertTrue(result["success"], result)
        m.reload()
        self.assertEqual(m.first_name, "After")


# ─────────────────────────────────────────────────────────────────────
# application_sync_service
# ─────────────────────────────────────────────────────────────────────
class TestApplicationSyncService(SyncServiceBase):
    def test_apply_new_application_creates_pending_member(self):
        app_id = _next_id()
        email = f"app.{app_id}@example.com"
        ev = self._make_event(
            "New",
            "admin_membership_application",
            new_data={
                "id": app_id,
                "first_name": "Appl",
                "last_name": "Icant",
                "email": email,
                "current_membership_status_id": 1,
            },
        )
        result = get_application_sync_service().apply_new_membership_application(ev)
        self.assertTrue(result["success"], result)
        member = frappe.get_doc("Member", ev.linked_member)
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Pending")
        self.assertEqual(member.application_id, f"MR-APP-{app_id}")

    def test_apply_new_application_no_data_fails(self):
        ev = self._make_event("New", "admin_membership_application")
        result = get_application_sync_service().apply_new_membership_application(ev)
        self.assertFalse(result["success"])

    def test_apply_changed_application_updates_pending_fields(self):
        app_id = _next_id()
        email = f"appchg.{app_id}@example.com"
        member = self._make_member(
            application_id=f"MR-APP-{app_id}",
            application_status="Pending",
            status="Pending",
            email=email,
            first_name="Old",
        )
        ev = self._make_event(
            "Changed",
            "admin_membership_application",
            new_data={
                "id": app_id,
                "first_name": "New",
                "last_name": "Name",
                "email": email,
                "current_membership_status_id": 1,
            },
            changed_fields=[{"field": "first_name", "old": "Old", "new": "New"}],
            linked_member=member.name,
        )
        result = get_application_sync_service().apply_changed_membership_application(ev)
        self.assertTrue(result["success"], result)
        member.reload()
        self.assertEqual(member.first_name, "New")

    def test_apply_changed_application_skips_already_approved(self):
        # Guard: don't overwrite data on an already-approved application.
        app_id = _next_id()
        email = f"appapproved.{app_id}@example.com"
        member = self._make_member(
            application_id=f"MR-APP-{app_id}",
            status="Active",
            email=email,
            first_name="Keep",
        )
        # The Member controller forces application_status to Pending on insert,
        # so stamp the approved state directly (matching a real approved app).
        frappe.db.set_value("Member", member.name, "application_status", "Approved")
        frappe.db.commit()
        ev = self._make_event(
            "Changed",
            "admin_membership_application",
            new_data={
                "id": app_id,
                "first_name": "ShouldNotApply",
                "email": email,
                "current_membership_status_id": 1,
            },
            changed_fields=[{"field": "first_name", "old": "Keep", "new": "ShouldNotApply"}],
            linked_member=member.name,
        )
        result = get_application_sync_service().apply_changed_membership_application(ev)
        self.assertTrue(result["success"])
        self.assertIn("already", result["message"])
        member.reload()
        self.assertEqual(member.first_name, "Keep")

    def test_apply_approved_falls_through_to_new_member_when_unlocatable(self):
        # No pending member exists matching old/new data -> defensive fallback
        # creates a brand-new member via apply_new_member.
        new_id = _next_id()
        email = f"fallthrough.{new_id}@example.com"
        ev = self._make_event(
            "Approved",
            "admin_member",
            old_data={"id": _next_id()},
            new_data={
                "id": new_id,
                "first_name": "Fall",
                "last_name": "Through",
                "email": email,
                "current_membership_status_id": 1,
            },
        )
        result = get_application_sync_service().apply_approved(ev)
        self.assertTrue(result["success"], result)
        self.assertTrue(frappe.db.exists("Member", {"member_id": str(new_id)}))

    def test_locate_application_member_by_application_id(self):
        app_id = _next_id()
        member = self._make_member(application_id=f"MR-APP-{app_id}", status="Pending")
        located = get_application_sync_service()._locate_application_member(
            {"id": app_id}, {"email": ""}, None
        )
        self.assertEqual(located, member.name)


# ─────────────────────────────────────────────────────────────────────
# termination_sync_service
# ─────────────────────────────────────────────────────────────────────
class TestTerminationSyncService(SyncServiceBase):
    def test_no_status_change_returns_none(self):
        ev = self._make_event("Changed", "admin_member")
        result = get_termination_sync_service()._check_and_handle_termination(
            ev, {}, {"id": 1}, [{"field": "first_name", "old": "A", "new": "B"}]
        )
        self.assertIsNone(result)

    def test_non_terminated_target_status_returns_none(self):
        ev = self._make_event("Changed", "admin_member")
        # active(1) -> active(2): not a termination.
        result = get_termination_sync_service()._check_and_handle_termination(
            ev,
            {},
            {"id": 1},
            [{"field": "current_membership_status_id", "old": 1, "new": 2}],
        )
        self.assertIsNone(result)

    def test_from_non_active_status_returns_none(self):
        ev = self._make_event("Changed", "admin_member")
        # already terminated(3) -> terminated(4): not from active, skip.
        result = get_termination_sync_service()._check_and_handle_termination(
            ev,
            {},
            {"id": 1},
            [{"field": "current_membership_status_id", "old": 3, "new": 4}],
        )
        self.assertIsNone(result)

    def test_no_linked_member_returns_failure(self):
        mid = _next_id()
        ev = self._make_event("Changed", "admin_member")
        result = get_termination_sync_service()._check_and_handle_termination(
            ev,
            {"id": mid, "email": f"missing.{mid}@example.com"},
            {"id": mid},
            [{"field": "current_membership_status_id", "old": 1, "new": 3}],
        )
        self.assertFalse(result["success"])
        self.assertIn("no linked member", result["message"].lower())

    def test_already_terminal_member_skips(self):
        mid = _next_id()
        member = self._make_member(member_id=str(mid), status="Quit")
        ev = self._make_event("Changed", "admin_member", linked_member=member.name)
        result = get_termination_sync_service()._check_and_handle_termination(
            ev,
            {"id": mid},
            {"id": mid},
            [{"field": "current_membership_status_id", "old": 1, "new": 3}],
        )
        self.assertTrue(result["success"])
        self.assertIn("already has status", result["message"])

    def test_active_to_terminated_creates_and_executes_mtr(self):
        mid = _next_id()
        member = self._make_member(member_id=str(mid), status="Active")
        ev = self._make_event("Changed", "admin_member", linked_member=member.name)
        result = get_termination_sync_service()._check_and_handle_termination(
            ev,
            {"id": mid},
            {"id": mid},
            [{"field": "current_membership_status_id", "old": 1, "new": 3}],
        )
        self.assertTrue(result["success"], result)
        self.assertIn("executed", result["message"])
        mtr = frappe.get_all(
            "Membership Termination Request",
            filters={"member": member.name},
            fields=["name", "termination_type", "status"],
        )
        self.assertEqual(len(mtr), 1)
        self.assertEqual(mtr[0].termination_type, "Voluntary")  # status 3 -> Voluntary
        member.reload()
        self.assertEqual(member.status, "Quit")


# ─────────────────────────────────────────────────────────────────────
# related_records_orchestrator
# ─────────────────────────────────────────────────────────────────────
class TestRelatedRecordsOrchestrator(SyncServiceBase):
    def test_acr_dedup_lifecycle(self):
        orch = get_related_records_orchestrator()
        orch.reset_acr_dedup()
        self.assertFalse(orch.is_acr_queued("Member-X"))
        orch.mark_acr_queued("Member-X")
        self.assertTrue(orch.is_acr_queued("Member-X"))
        orch.reset_acr_dedup()
        self.assertFalse(orch.is_acr_queued("Member-X"))

    def test_apply_mijnrood_comments_appends_to_notes(self):
        member = self._make_member()
        msg = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "Belangrijke notitie"}
        )
        self.assertIsNotNone(msg)
        notes = frappe.db.get_value("Member", member.name, "notes")
        self.assertIn("Belangrijke notitie", notes)

    def test_apply_mijnrood_comments_idempotent(self):
        member = self._make_member()
        orch = get_related_records_orchestrator()
        orch._apply_mijnrood_comments(member.name, {"mijnrood_comments": "Once only"})
        # Second call with the same comment is a no-op (already present).
        msg2 = orch._apply_mijnrood_comments(member.name, {"mijnrood_comments": "Once only"})
        self.assertIsNone(msg2)
        notes = frappe.db.get_value("Member", member.name, "notes")
        self.assertEqual(notes.count("Once only"), 1)

    def test_apply_mijnrood_comments_blank_skips(self):
        member = self._make_member()
        msg = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "   "}
        )
        self.assertIsNone(msg)

    def test_assign_chapter_unknown_division_returns_message(self):
        member = self._make_member()
        ev = self._make_event("New", "admin_member")
        msg = get_related_records_orchestrator()._assign_chapter_from_division(member.name, _next_id(), ev)
        self.assertIsNotNone(msg)
        self.assertIn("does not match any Chapter", msg)

    def test_assign_chapter_success(self):
        member = self._make_member()
        chapter = self.create_test_chapter()
        div_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", div_id)
        frappe.db.commit()
        ev = self._make_event("New", "admin_member")
        msg = get_related_records_orchestrator()._assign_chapter_from_division(member.name, div_id, ev)
        self.assertIsNotNone(msg)
        self.assertIn(chapter.name, msg)
        # Member is now an active member of that chapter.
        self.assertTrue(
            frappe.db.exists(
                "Chapter Member",
                {"parent": chapter.name, "member": member.name, "status": "Active"},
            )
        )

    def test_assign_chapter_future_join_date_falls_back_to_today(self):
        member = self._make_member()
        chapter = self.create_test_chapter()
        div_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", div_id)
        frappe.db.commit()
        ev = self._make_event("New", "admin_member")
        # A future join_date must be rejected (falls back to today), not stored.
        msg = get_related_records_orchestrator()._assign_chapter_from_division(
            member.name, div_id, ev, join_date="2099-01-01"
        )
        self.assertIsNotNone(msg)

    def test_handle_division_field_change_no_change_returns_none(self):
        member = self._make_member()
        ev = self._make_event("Changed", "admin_member")
        msg = get_related_records_orchestrator()._handle_division_field_change(
            member.name, [{"field": "first_name", "old": "A", "new": "B"}], ev
        )
        self.assertIsNone(msg)

    def test_handle_division_field_change_reassigns(self):
        member = self._make_member()
        chapter = self.create_test_chapter()
        div_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", div_id)
        frappe.db.commit()
        ev = self._make_event("Changed", "admin_member")
        msg = get_related_records_orchestrator()._handle_division_field_change(
            member.name,
            [{"field": "division_id", "old": None, "new": div_id}],
            ev,
        )
        self.assertIsNotNone(msg)
        self.assertIn(chapter.name, msg)


# ─────────────────────────────────────────────────────────────────────
# volunteer_sync_service: pure parsing + role transitions
# ─────────────────────────────────────────────────────────────────────
class TestVolunteerSyncRoleParsing(SyncServiceBase):
    def setUp(self):
        super().setUp()
        # Run these tests with an empty role mapping so role-processing
        # short-circuits deterministically regardless of the live site config.
        settings = frappe.get_single("MijnRood Sync Settings")
        self._role_snapshot = [r.as_dict() for r in (settings.role_mapping or [])]
        settings.set("role_mapping", [])
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache.delete_value("mijnrood_role_mapping")

    def tearDown(self):
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.set("role_mapping", [])
        for row in self._role_snapshot:
            settings.append("role_mapping", row)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache.delete_value("mijnrood_role_mapping")
        super().tearDown()

    def test_parse_roles_json_string(self):
        self.assertEqual(
            get_volunteer_sync_service()._parse_mijnrood_roles('["ROLE_ADMIN", "OTHER"]'),
            {"ROLE_ADMIN"},
        )

    def test_parse_roles_list_input(self):
        self.assertEqual(
            get_volunteer_sync_service()._parse_mijnrood_roles(["ROLE_FOO", "bar"]),
            {"ROLE_FOO"},
        )

    def test_parse_roles_invalid_json_returns_empty(self):
        self.assertEqual(get_volunteer_sync_service()._parse_mijnrood_roles("nope"), set())

    def test_parse_roles_none_and_non_string(self):
        self.assertEqual(get_volunteer_sync_service()._parse_mijnrood_roles(None), set())
        self.assertEqual(get_volunteer_sync_service()._parse_mijnrood_roles(42), set())

    def test_process_member_roles_empty_config_returns_empty(self):
        # With no role mapping configured (cleared in setUp),
        # _process_member_roles short-circuits and applies no actions.
        member = self._make_member()
        msgs = get_volunteer_sync_service()._process_member_roles(
            member.name, {"id": 1, "roles": '["ROLE_ADMIN"]'}
        )
        self.assertEqual(msgs, [])

    def test_ensure_user_role_no_user_returns_none(self):
        member = self._make_member()  # no linked user
        self.assertIsNone(get_volunteer_sync_service()._ensure_user_role(member.name, "System Manager"))

    def test_ensure_team_membership_nonexistent_team(self):
        member = self._make_member()
        vol = self.create_test_volunteer(member_name=member.name)
        msg = get_volunteer_sync_service()._ensure_team_membership(
            member.name, "Definitely Nonexistent Team ZZZ"
        )
        self.assertIn("does not exist", msg)

    def test_ensure_team_membership_no_volunteer(self):
        member = self._make_member()  # no volunteer record
        msg = get_volunteer_sync_service()._ensure_team_membership(member.name, "AnyTeam")
        self.assertIn("No Volunteer record", msg)


class TestVolunteerSyncWithRoleMapping(SyncServiceBase):
    """Tests that need a configured role mapping. Snapshot + restore the Single."""

    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("MijnRood Sync Settings")
        self._role_snapshot = [r.as_dict() for r in (self.settings.role_mapping or [])]
        self.settings.set("role_mapping", [])

    def tearDown(self):
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.set("role_mapping", [])
        for row in self._role_snapshot:
            settings.append("role_mapping", row)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache.delete_value("mijnrood_role_mapping")
        super().tearDown()

    def _setup_role_mapping(self, **fields):
        self.settings.append("role_mapping", fields)
        self.settings.flags.ignore_validate = True
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache.delete_value("mijnrood_role_mapping")

    def test_admin_role_added_creates_volunteer(self):
        self._setup_role_mapping(mijnrood_role="ROLE_ADMIN", label="Admin", create_volunteer=1)
        member = self._make_member(email=f"adminrole.{_next_id()}@example.com")
        msgs = get_volunteer_sync_service()._process_member_roles(
            member.name, {"id": 1, "roles": '["ROLE_ADMIN"]'}, old_data={"roles": None}
        )
        self.assertTrue(any("Volunteer" in m for m in msgs), msgs)
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        self.assertTrue(get_volunteer_for_member(member.name))

    def test_admin_role_unchanged_skips_actions(self):
        # ROLE_ADMIN present in both old and new -> no transition, no volunteer.
        self._setup_role_mapping(mijnrood_role="ROLE_ADMIN", label="Admin", create_volunteer=1)
        member = self._make_member(email=f"noop.{_next_id()}@example.com")
        msgs = get_volunteer_sync_service()._process_member_roles(
            member.name,
            {"id": 1, "roles": '["ROLE_ADMIN"]'},
            old_data={"roles": '["ROLE_ADMIN"]'},
        )
        self.assertEqual(msgs, [])
        from verenigingen.verenigingen.doctype.volunteer.volunteer import (
            get_volunteer_for_member,
        )

        self.assertIsNone(get_volunteer_for_member(member.name))

    def test_admin_role_removed_reports_removal(self):
        self._setup_role_mapping(mijnrood_role="ROLE_ADMIN", label="Admin", create_volunteer=1)
        member = self._make_member(email=f"removed.{_next_id()}@example.com")
        msgs = get_volunteer_sync_service()._process_member_roles(
            member.name,
            {"id": 1, "roles": "[]"},
            old_data={"roles": '["ROLE_ADMIN"]'},
        )
        self.assertTrue(any("ROLE_ADMIN removed" in m for m in msgs), msgs)
