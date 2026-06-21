# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Integration tests for the MijnRood event-application dispatcher.

Drives MijnRoodEventApplicationService.apply_event end-to-end against the real
database: builds a MijnRood Sync Event doc, approves it, applies it, and asserts
the resulting Member/Chapter records and event status transitions.

No business logic is mocked. frappe.enqueue / frappe.publish_realtime (the only
true I/O boundaries) are patched in the batch tests purely to assert they are
called and to run the worker loop synchronously.

Covers:
- _dispatch routing for each table + the reference-only branch.
- _sync_division_to_chapter: ID-match, name fallback, first-time linking,
  ID-conflict error, published-flag update, already-up-to-date, auto-create.
- _apply_deleted (records, never auto-applies) and _apply_approved (promotion).
- apply_event guards (only Approved events apply; exception path records error).
- batch_approve, batch_apply/batch_approve_and_apply enqueue, _batch_event_worker.
"""

import json
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.services.event_application.dispatcher import (
    _batch_event_worker,
    batch_apply,
    batch_approve,
    batch_approve_and_apply,
    get_event_application_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _next_id():
    """Return a process-unique MijnRood row id to avoid member_id collisions."""
    _next_id.counter += 1
    return 900000 + _next_id.counter


_next_id.counter = 0


class TestDispatcherBase(EnhancedTestCase):
    """Shared helpers for building and applying sync events."""

    def _make_event(
        self,
        event_type,
        mijnrood_table,
        new_data=None,
        old_data=None,
        changed_fields=None,
        status="Pending",
        linked_member=None,
        row_id=None,
    ):
        ev = frappe.new_doc("MijnRood Sync Event")
        ev.event_type = event_type
        ev.status = status
        ev.mijnrood_table = mijnrood_table
        ev.mijnrood_row_id = row_id if row_id is not None else _next_id()
        ev.detected_at = now_datetime()
        if new_data is not None:
            ev.new_data = json.dumps(new_data)
        if old_data is not None:
            ev.old_data = json.dumps(old_data)
        if changed_fields is not None:
            ev.changed_fields = json.dumps(changed_fields)
        if linked_member:
            ev.linked_member = linked_member
        ev.insert(ignore_permissions=True)
        return ev

    def _apply(self, ev):
        """Approve (if pending) and apply an event, returning the result dict."""
        if ev.status == "Pending":
            ev.approve()
        result = get_event_application_service().apply_event(ev.name)
        ev.reload()
        return result


class TestApplyEventGuards(TestDispatcherBase):
    """apply_event status guards + exception recording."""

    def test_non_approved_event_is_not_applied(self):
        ev = self._make_event(
            "New",
            "admin_member",
            new_data={"id": _next_id(), "first_name": "Guard", "last_name": "Test"},
            status="Pending",
        )
        # Pending — apply_event must refuse without touching the record.
        result = get_event_application_service().apply_event(ev.name)
        self.assertFalse(result["success"])
        self.assertIn("Only Approved", result["message"])
        ev.reload()
        self.assertEqual(ev.status, "Pending")
        self.assertIsNone(ev.linked_member)

    def test_approved_new_member_applies_and_transitions_to_applied(self):
        mid = _next_id()
        ev = self._make_event(
            "New",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "Applied",
                "last_name": "Member",
                "email": f"applied.{mid}@example.com",
                "current_membership_status_id": 1,
            },
        )
        result = self._apply(ev)
        self.assertTrue(result["success"], result)
        self.assertEqual(ev.status, "Applied")
        self.assertIsNotNone(ev.applied_at)
        self.assertIsNone(ev.error_message)
        # A real Member was created with the MijnRood id and Active status.
        member = frappe.get_doc("Member", ev.linked_member)
        self.assertEqual(str(member.member_id), str(mid))
        self.assertEqual(member.status, "Active")

    def test_exception_path_records_error_message(self):
        # An unmapped status id forces map_member_fields to raise ValueError,
        # which apply_event catches and records on error_message. The catch
        # path deliberately writes an Error Log — mark it expected.
        self.expectErrorLog("MijnRood Event Application Failed")
        ev = self._make_event(
            "New",
            "admin_member",
            new_data={
                "id": _next_id(),
                "first_name": "Boom",
                "last_name": "Error",
                "current_membership_status_id": 99999,  # no mapping
            },
        )
        result = self._apply(ev)
        self.assertFalse(result["success"])
        self.assertIn("99999", result["message"])
        # Status stays Approved (not Applied) and the error is persisted.
        self.assertEqual(ev.status, "Approved")
        self.assertTrue(ev.error_message)
        self.assertIn("99999", ev.error_message)

    def test_unknown_event_type_returns_failure(self):
        # event_type is a Select field; build a valid doc then poke a bad value
        # straight onto the loaded doc the service reads (bypassing validation).
        ev = self._make_event("New", "admin_member", new_data={"id": _next_id()})
        ev.approve()
        frappe.db.set_value("MijnRood Sync Event", ev.name, "event_type", "Frobnicate")
        result = get_event_application_service().apply_event(ev.name)
        self.assertFalse(result["success"])
        self.assertIn("Unknown event type", result["message"])


class TestDispatchRouting(TestDispatcherBase):
    """_dispatch table routing + reference-only branch."""

    def test_unknown_table_recorded_for_reference_only(self):
        ev = self._make_event(
            "New",
            "admin_support_member",  # not in _TABLE_HANDLERS
            new_data={"id": _next_id(), "first_name": "Ref"},
        )
        result = self._apply(ev)
        self.assertTrue(result["success"])
        self.assertIn("recorded for reference only", result["message"])
        self.assertEqual(ev.status, "Applied")
        # No member was linked for a reference-only table.
        self.assertIsNone(ev.linked_member)

    def test_changed_routes_to_member_handler(self):
        # Create a member first via a New event, then a Changed event updating it.
        mid = _next_id()
        new = self._make_event(
            "New",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "Orig",
                "last_name": "Name",
                "email": f"orig.{mid}@example.com",
                "current_membership_status_id": 1,
            },
        )
        self._apply(new)
        member_name = new.linked_member
        self.assertTrue(member_name)

        changed = self._make_event(
            "Changed",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "Changed",
                "last_name": "Name",
                "email": f"orig.{mid}@example.com",
                "current_membership_status_id": 1,
            },
            old_data={"id": mid, "first_name": "Orig", "email": f"orig.{mid}@example.com"},
            changed_fields=[{"field": "first_name", "old": "Orig", "new": "Changed"}],
            linked_member=member_name,
        )
        result = self._apply(changed)
        self.assertTrue(result["success"], result)
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.first_name, "Changed")


class TestApplyDeleted(TestDispatcherBase):
    """Deleted events are recorded, never auto-applied."""

    def test_deleted_member_records_only(self):
        ev = self._make_event(
            "Deleted",
            "admin_member",
            old_data={"id": _next_id(), "first_name": "Gone"},
        )
        result = self._apply(ev)
        self.assertTrue(result["success"])
        self.assertIn("manual review", result["message"])
        self.assertEqual(ev.status, "Applied")
        # Crucially: no member deleted/created.
        self.assertIsNone(ev.linked_member)


class TestApplyApproved(TestDispatcherBase):
    """Correlator-synthesized Approved promotion path."""

    def _create_pending_application(self, app_id, email):
        """Create a Pending Member as the application sync would."""
        ev = self._make_event(
            "New",
            "admin_membership_application",
            new_data={
                "id": app_id,
                "first_name": "Pending",
                "last_name": "Applicant",
                "email": email,
                "current_membership_status_id": 1,
            },
        )
        result = self._apply(ev)
        self.assertTrue(result["success"], result)
        return ev.linked_member

    def test_approved_promotes_linked_pending_member(self):
        app_id = _next_id()
        new_member_id = _next_id()
        email = f"promote.{app_id}@example.com"
        member_name = self._create_pending_application(app_id, email)
        self.assertEqual(frappe.db.get_value("Member", member_name, "application_status"), "Pending")

        approved = self._make_event(
            "Approved",
            "admin_member",
            old_data={"id": app_id, "email": email},
            new_data={
                "id": new_member_id,
                "first_name": "Pending",
                "last_name": "Applicant",
                "email": email,
                "current_membership_status_id": 1,
            },
            linked_member=member_name,
        )
        result = self._apply(approved)
        self.assertTrue(result["success"], result)
        self.assertIn("promoted", result["message"])

        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active")
        # member_id updated to the new admin_member id.
        self.assertEqual(str(member.member_id), str(new_member_id))

    def test_approved_no_new_data_fails(self):
        ev = self._make_event(
            "Approved",
            "admin_member",
            old_data={"id": _next_id()},
        )
        result = self._apply(ev)
        self.assertFalse(result["success"])
        self.assertIn("No new data", result["message"])


class TestSyncDivisionToChapter(TestDispatcherBase):
    """Rich branch coverage for _sync_division_to_chapter."""

    def _division_event(self, name, div_id=None, selectable=True, event_type="New"):
        return self._make_event(
            event_type,
            "admin_division",
            new_data={
                "id": div_id,
                "name": name,
                "can_be_selected_on_application": 1 if selectable else 0,
            },
        )

    def test_auto_create_chapter_stores_division_id(self):
        div_id = _next_id()
        name = f"AutoChapter {div_id}"
        ev = self._division_event(name, div_id=div_id, selectable=True)
        result = self._apply(ev)
        self.assertTrue(result["success"], result)
        self.assertIn("created from MijnRood division", result["message"])
        self.assertTrue(frappe.db.exists("Chapter", name))
        self.assertEqual(str(frappe.db.get_value("Chapter", name, "mijnrood_division_id")), str(div_id))
        self.assertEqual(frappe.db.get_value("Chapter", name, "published"), 1)

    def test_division_no_name_fails(self):
        ev = self._make_event(
            "New",
            "admin_division",
            new_data={"id": _next_id(), "can_be_selected_on_application": 1},
        )
        result = self._apply(ev)
        self.assertFalse(result["success"])
        self.assertIn("no name", result["message"].lower())

    def test_first_time_linking_stores_id_on_existing_chapter(self):
        # Chapter exists by name but has no mijnrood_division_id yet.
        chapter = self.create_test_chapter()
        div_id = _next_id()
        ev = self._division_event(chapter.name, div_id=div_id, selectable=True)
        result = self._apply(ev)
        self.assertTrue(result["success"], result)
        self.assertEqual(
            str(frappe.db.get_value("Chapter", chapter.name, "mijnrood_division_id")),
            str(div_id),
        )

    def test_match_by_division_id_after_rename(self):
        # Chapter already linked to div_id; division name differs (rename).
        chapter = self.create_test_chapter()
        div_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", div_id)
        frappe.db.commit()

        ev = self._make_event(
            "Changed",
            "admin_division",
            new_data={
                "id": div_id,
                "name": f"Renamed Division {div_id}",  # different from chapter name
                "can_be_selected_on_application": 0,
            },
        )
        result = self._apply(ev)
        self.assertTrue(result["success"], result)
        # Resolved by ID (not by the new name) and published flag updated to 0.
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "published"), 0)

    def test_published_flag_update_when_changed(self):
        chapter = self.create_test_chapter()
        div_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, {"mijnrood_division_id": div_id, "published": 0})
        frappe.db.commit()
        ev = self._division_event(chapter.name, div_id=div_id, selectable=True)
        result = self._apply(ev)
        self.assertTrue(result["success"])
        self.assertIn("updated", result["message"])
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "published"), 1)

    def test_already_up_to_date_is_noop(self):
        chapter = self.create_test_chapter()
        div_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, {"mijnrood_division_id": div_id, "published": 1})
        frappe.db.commit()
        ev = self._division_event(chapter.name, div_id=div_id, selectable=True)
        result = self._apply(ev)
        self.assertTrue(result["success"])
        self.assertIn("already up to date", result["message"])

    def test_division_id_conflict_returns_error(self):
        # Chapter linked to one div id; incoming event carries a different id
        # but matches the chapter by NAME -> conflict.
        chapter = self.create_test_chapter()
        existing_id = _next_id()
        incoming_id = _next_id()
        frappe.db.set_value("Chapter", chapter.name, "mijnrood_division_id", existing_id)
        frappe.db.commit()

        ev = self._make_event(
            "Changed",
            "admin_division",
            new_data={
                "id": incoming_id,
                "name": chapter.name,  # name match
                "can_be_selected_on_application": 1,
            },
        )
        result = self._apply(ev)
        self.assertFalse(result["success"])
        self.assertIn("conflict", result["message"].lower())
        # Existing link untouched.
        self.assertEqual(
            str(frappe.db.get_value("Chapter", chapter.name, "mijnrood_division_id")),
            str(existing_id),
        )

    def test_changed_division_no_new_data_fails(self):
        ev = self._make_event("Changed", "admin_division", old_data={"id": _next_id()})
        result = self._apply(ev)
        self.assertFalse(result["success"])
        self.assertIn("No new data", result["message"])


class TestBatchApprove(TestDispatcherBase):
    """batch_approve whitelist endpoint."""

    def test_batch_approve_counts_pending_only(self):
        e1 = self._make_event("New", "admin_member", new_data={"id": _next_id()})
        e2 = self._make_event("New", "admin_member", new_data={"id": _next_id()})
        # e3 is already Approved -> not counted, not re-approved.
        e3 = self._make_event("New", "admin_member", new_data={"id": _next_id()}, status="Pending")
        e3.approve()

        result = batch_approve(json.dumps([e1.name, e2.name, e3.name]))
        self.assertEqual(result["approved"], 2)
        self.assertEqual(result["errors"], [])
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", e1.name, "status"), "Approved")
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", e2.name, "status"), "Approved")

    def test_batch_approve_captures_errors_for_missing_event(self):
        e1 = self._make_event("New", "admin_member", new_data={"id": _next_id()})
        result = batch_approve(json.dumps([e1.name, "NONEXISTENT-EVENT-ZZZ"]))
        self.assertEqual(result["approved"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("NONEXISTENT-EVENT-ZZZ", result["errors"][0])

    def test_batch_approve_accepts_list_argument(self):
        e1 = self._make_event("New", "admin_member", new_data={"id": _next_id()})
        result = batch_approve([e1.name])
        self.assertEqual(result["approved"], 1)


class TestBatchEnqueue(TestDispatcherBase):
    """batch_apply / batch_approve_and_apply enqueue at the I/O boundary."""

    def test_batch_apply_enqueues_worker(self):
        e1 = self._make_event("New", "admin_member", new_data={"id": _next_id()})
        with patch(
            "verenigingen.mijnrood_sync.services.event_application.dispatcher.frappe.enqueue"
        ) as mock_enqueue:
            result = batch_apply([e1.name])
        self.assertEqual(result["total"], 1)
        self.assertIn("batch_id", result)
        mock_enqueue.assert_called_once()
        # Worker target is _batch_apply_worker, queued long.
        args, kwargs = mock_enqueue.call_args
        self.assertEqual(kwargs.get("queue"), "long")
        self.assertEqual(kwargs.get("event_names"), [e1.name])

    def test_batch_approve_and_apply_enqueues_worker(self):
        e1 = self._make_event("New", "admin_member", new_data={"id": _next_id()})
        with patch(
            "verenigingen.mijnrood_sync.services.event_application.dispatcher.frappe.enqueue"
        ) as mock_enqueue:
            result = batch_approve_and_apply([e1.name])
        self.assertEqual(result["total"], 1)
        mock_enqueue.assert_called_once()


class TestBatchEventWorker(TestDispatcherBase):
    """_batch_event_worker loop: table-priority sort, approve_first, counting."""

    def test_worker_sorts_by_table_priority_and_applies(self):
        # A member event and a division event; division (priority 0) must be
        # processed before the member (priority 1). Both already approved.
        div_id = _next_id()
        div_name = f"WorkerDiv {div_id}"
        div_ev = self._make_event(
            "New",
            "admin_division",
            new_data={
                "id": div_id,
                "name": div_name,
                "can_be_selected_on_application": 1,
            },
        )
        div_ev.approve()

        mid = _next_id()
        mem_ev = self._make_event(
            "New",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "Worker",
                "last_name": "Member",
                "email": f"worker.{mid}@example.com",
                "current_membership_status_id": 1,
                "division_id": div_id,  # references the chapter created above
            },
        )
        mem_ev.approve()

        processed_order = []
        real_apply = get_event_application_service().apply_event

        def _tracking_apply(name):
            processed_order.append(frappe.db.get_value("MijnRood Sync Event", name, "mijnrood_table"))
            return real_apply(name)

        with (
            patch("verenigingen.mijnrood_sync.services.event_application.dispatcher.frappe.publish_realtime"),
            patch.object(get_event_application_service(), "apply_event", side_effect=_tracking_apply),
        ):
            # Pass member first to prove the worker re-sorts to division-first.
            _batch_event_worker([mem_ev.name, div_ev.name], batch_id="testbatch")

        self.assertEqual(processed_order, ["admin_division", "admin_member"])
        self.assertTrue(frappe.db.exists("Chapter", div_name))
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", mem_ev.name, "status"), "Applied")

    def test_worker_approve_first_approves_pending(self):
        mid = _next_id()
        ev = self._make_event(
            "New",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "ApproveFirst",
                "last_name": "Member",
                "email": f"af.{mid}@example.com",
                "current_membership_status_id": 1,
            },
            status="Pending",
        )
        with patch(
            "verenigingen.mijnrood_sync.services.event_application.dispatcher.frappe.publish_realtime"
        ):
            _batch_event_worker([ev.name], batch_id="b2", approve_first=True)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", ev.name, "status"), "Applied")

    def test_worker_approve_first_skips_already_applied(self):
        # An already-Applied event must be skipped (status not in Pending/Approved).
        mid = _next_id()
        ev = self._make_event(
            "New",
            "admin_member",
            new_data={
                "id": mid,
                "first_name": "Skip",
                "last_name": "Member",
                "email": f"skip.{mid}@example.com",
                "current_membership_status_id": 1,
            },
        )
        # Apply it once.
        self._apply(ev)
        self.assertEqual(ev.status, "Applied")

        with (
            patch("verenigingen.mijnrood_sync.services.event_application.dispatcher.frappe.publish_realtime"),
            patch.object(get_event_application_service(), "apply_event") as mock_apply,
        ):
            _batch_event_worker([ev.name], batch_id="b3", approve_first=True)
            # apply_event must NOT be called for an already-Applied event.
            mock_apply.assert_not_called()
