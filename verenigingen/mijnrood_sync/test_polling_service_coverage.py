# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Coverage for the remaining MijnRood polling-service gaps.

The polling service is largely covered already; this file targets the
error/lease/concurrency branches and the pure transformation helpers
(compute_change_tags, _compute_changed_fields, _resolve_division_name,
_summary_for_*, _find_linked_member) without standing up a remote MijnRood
DB connection.

Concurrency: the run lock is a real frappe.cache() lease — acquire/release are
exercised against the live cache, including the "second run sees lock held"
branch of run_sync(). No business logic is mocked. The remote
MijnRoodDatabaseClient boundary is never reached in these tests because the
lock-held path returns before any connection is attempted.
"""

import json

import frappe
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.services.polling_service import (
    _SYNC_LOCK_KEY,
    MijnRoodPollingService,
    acquire_sync_lock,
    compute_change_tags,
    get_polling_service,
    release_sync_lock,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSyncLock(EnhancedTestCase):
    """Cache-based cross-run concurrency lease."""

    def setUp(self):
        super().setUp()
        # Ensure a clean lock slate for deterministic acquire/release tests.
        release_sync_lock()

    def tearDown(self):
        release_sync_lock()
        super().tearDown()

    def test_acquire_then_second_acquire_blocked(self):
        self.assertTrue(acquire_sync_lock("run-A"))
        # Lock now held -> a second run cannot acquire it.
        self.assertFalse(acquire_sync_lock("run-B"))

    def test_lock_stores_run_id(self):
        acquire_sync_lock("run-XYZ")
        self.assertEqual(frappe.cache().get_value(_SYNC_LOCK_KEY), "run-XYZ")

    def test_release_allows_reacquire(self):
        self.assertTrue(acquire_sync_lock("run-1"))
        release_sync_lock()
        # After release the slot is free again.
        self.assertTrue(acquire_sync_lock("run-2"))

    def test_release_is_safe_when_not_held(self):
        release_sync_lock()
        # Idempotent — calling release twice must not raise.
        release_sync_lock()
        self.assertIsNone(frappe.cache().get_value(_SYNC_LOCK_KEY))

    def test_run_sync_skips_when_lock_already_held(self):
        """The concurrency guard: if a previous run still holds the lease,
        run_sync() returns the skip sentinel WITHOUT attempting a remote
        connection (no MijnRoodDatabaseClient is built)."""
        # Pre-acquire the lock to simulate an in-flight run.
        self.assertTrue(acquire_sync_lock("in-flight-run"))
        svc = MijnRoodPollingService()
        result = svc.run_sync()
        self.assertEqual(result, {"skipped": True, "reason": "lock_held"})
        # The lock is still held by the simulated in-flight run — run_sync()
        # must NOT have released someone else's lease.
        self.assertEqual(frappe.cache().get_value(_SYNC_LOCK_KEY), "in-flight-run")


class TestComputeChangeTags(EnhancedTestCase):
    """Pure: maps event type + changed fields to triage category tags."""

    def test_new_member_table_label(self):
        self.assertEqual(compute_change_tags("New", "admin_member", None), "New Member")

    def test_new_application_table_label(self):
        self.assertEqual(compute_change_tags("New", "admin_membership_application", None), "New Application")

    def test_new_division_table_label(self):
        self.assertEqual(compute_change_tags("New", "admin_division", None), "New Division")

    def test_new_unknown_table_falls_back_to_new(self):
        self.assertEqual(compute_change_tags("New", "admin_support_member", None), "New")

    def test_deleted_tag(self):
        self.assertEqual(compute_change_tags("Deleted", "admin_member", None), "Deleted")

    def test_approved_tag(self):
        self.assertEqual(compute_change_tags("Approved", "admin_member", None), "Approved")

    def test_changed_with_no_fields_is_empty(self):
        self.assertEqual(compute_change_tags("Changed", "admin_member", None), "")
        self.assertEqual(compute_change_tags("Changed", "admin_member", []), "")

    def test_changed_unmapped_field_is_other(self):
        # A field with no FIELD_TAG_MAP entry -> "Other".
        tags = compute_change_tags("Changed", "admin_member", [{"field": "totally_unknown"}])
        self.assertEqual(tags, "Other")

    def test_changed_tags_follow_priority_order(self):
        """Multiple categories are emitted in TAG_ORDER (Status before Contact
        before Personal), regardless of the input field order."""
        changed = [
            {"field": "first_name"},  # Personal
            {"field": "email"},  # Contact
            {"field": "current_membership_status_id"},  # Status
        ]
        self.assertEqual(compute_change_tags("Changed", "admin_member", changed), "Status,Contact,Personal")

    def test_changed_accepts_plain_string_fields(self):
        # changed_fields entries may be bare strings, not dicts.
        self.assertEqual(compute_change_tags("Changed", "admin_member", ["iban"]), "Financial")


class TestPollingHelpers(EnhancedTestCase):
    """Instance helper methods that don't need a remote connection."""

    def setUp(self):
        super().setUp()
        self.svc = get_polling_service()

    # ---- _compute_changed_fields ----------------------------------------

    def test_compute_changed_fields_detects_diff(self):
        old = {"first_name": "Alice", "city": "Utrecht"}
        new = {"first_name": "Bob", "city": "Utrecht"}
        changed = self.svc._compute_changed_fields(old, new)
        fields = {c["field"] for c in changed}
        self.assertEqual(fields, {"first_name"})
        entry = changed[0]
        self.assertEqual(entry["old"], "Alice")
        self.assertEqual(entry["new"], "Bob")
        self.assertEqual(entry["label"], "First Name")

    def test_compute_changed_fields_normalizes_none_vs_empty(self):
        # None and "" are treated as equal -> no spurious change.
        changed = self.svc._compute_changed_fields({"phone": None}, {"phone": ""})
        self.assertEqual(changed, [])

    def test_compute_changed_fields_added_key(self):
        changed = self.svc._compute_changed_fields({}, {"email": "x@y.z"})
        self.assertEqual(changed[0]["field"], "email")
        self.assertEqual(changed[0]["old"], "")
        self.assertEqual(changed[0]["new"], "x@y.z")

    def test_compute_changed_fields_status_resolves_display(self):
        """current_membership_status_id gets old_display/new_display resolved
        from the status labels map."""
        changed = self.svc._compute_changed_fields(
            {"current_membership_status_id": 1},
            {"current_membership_status_id": 3},
        )
        self.assertEqual(len(changed), 1)
        entry = changed[0]
        self.assertIn("old_display", entry)
        self.assertIn("new_display", entry)
        # Default labels: 1 -> Active, 3 -> Resigned.
        self.assertTrue(entry["old_display"].lower().startswith("active"))
        self.assertTrue(entry["new_display"].lower().startswith("resigned"))

    # ---- _resolve_division_name -----------------------------------------

    def test_resolve_division_name_none_for_invalid_id(self):
        self.assertIsNone(self.svc._resolve_division_name("not-a-number"))
        self.assertIsNone(self.svc._resolve_division_name(None))

    def test_resolve_division_name_none_when_state_missing(self):
        # No admin_division sync state for this id -> None.
        self.assertIsNone(self.svc._resolve_division_name(987654))

    def test_resolve_division_name_reads_state(self):
        """Resolves division id -> human name from the admin_division sync state
        raw_data JSON."""
        div_id = 770077
        state_key = f"admin_division-{div_id}"
        if frappe.db.exists("MijnRood Sync State", state_key):
            frappe.delete_doc("MijnRood Sync State", state_key)
        state = frappe.get_doc(
            {
                "doctype": "MijnRood Sync State",
                "state_key": state_key,
                "mijnrood_table": "admin_division",
                "mijnrood_row_id": div_id,
                "raw_data": json.dumps({"name": "Afdeling Noord"}),
                "last_seen": now_datetime(),
            }
        )
        state.insert()
        self.factory.track_document("MijnRood Sync State", state.name, priority=1)
        frappe.db.commit()
        self.assertEqual(self.svc._resolve_division_name(div_id), "Afdeling Noord")

    # ---- _summary_for_new / _compute_change_summary ---------------------

    def test_summary_for_new_empty_data(self):
        self.assertEqual(self.svc._summary_for_new("admin_member", None), "New admin_member record")

    def test_summary_for_new_with_name_and_details(self):
        summary = self.svc._compute_change_summary(
            "New",
            "admin_member",
            None,
            {"first_name": "Jan", "last_name": "Jansen", "email": "jan@x.nl", "city": "Den Haag"},
            None,
        )
        self.assertIn("Jan Jansen", summary)
        self.assertIn("jan@x.nl", summary)
        self.assertIn("Den Haag", summary)

    def test_summary_for_deleted_with_name(self):
        summary = self.svc._compute_change_summary(
            "Deleted", "admin_member", {"first_name": "Piet", "last_name": "P"}, None, None
        )
        self.assertEqual(summary, "Deleted admin_member record: Piet P")

    def test_summary_for_deleted_unknown_name(self):
        summary = self.svc._compute_change_summary("Deleted", "admin_member", {}, None, None)
        self.assertIn("unknown", summary)

    def test_summary_for_changed_truncation_and_overflow(self):
        # >5 changes -> the "(+N more)" suffix branch.
        changed = [{"field": f"f{i}", "label": f"L{i}", "old": "a", "new": "b"} for i in range(7)]
        summary = self.svc._summary_for_changed(changed)
        self.assertIn("(+2 more)", summary)

    def test_summary_for_changed_empty_to_value(self):
        summary = self.svc._summary_for_changed(
            [{"field": "email", "label": "Email", "old": "", "new": "new@x.nl"}]
        )
        self.assertIn("(empty) → new@x.nl", summary)

    def test_summary_for_changed_value_to_empty(self):
        summary = self.svc._summary_for_changed(
            [{"field": "email", "label": "Email", "old": "old@x.nl", "new": ""}]
        )
        self.assertIn("old@x.nl → (empty)", summary)

    def test_compute_change_summary_fallback_branch(self):
        # event_type without specific handling -> generic fallback.
        summary = self.svc._compute_change_summary("Approved", "admin_member", None, None, None)
        self.assertEqual(summary, "Approved event for admin_member")

    # ---- _find_linked_member --------------------------------------------

    def test_find_linked_member_ignores_non_member_table(self):
        self.assertIsNone(self.svc._find_linked_member("admin_division", 5))

    def test_find_linked_member_by_member_id(self):
        # Pin a numeric member_id so the lookup matches the MijnRood row_id
        # (an int from the remote DB) exactly as production would.
        member = self.create_test_member(
            first_name="Linked", last_name="ByID", email="linked.byid@example.com"
        )
        frappe.db.set_value("Member", member.name, "member_id", "55667788")
        frappe.db.commit()
        found = self.svc._find_linked_member("admin_member", 55667788)
        self.assertEqual(found, member.name)

    def test_find_linked_member_email_fallback(self):
        """When member_id lookup misses, fall back to email match from row_data."""
        member = self.create_test_member(
            first_name="Linked", last_name="ByEmail", email="linked.byemail@example.com"
        )
        member_email = frappe.db.get_value("Member", member.name, "email")
        # Use a row id that won't match any member_id, but supply the email.
        found = self.svc._find_linked_member("admin_member", 99887766, row_data={"email": member_email})
        self.assertEqual(found, member.name)

    def test_find_linked_member_returns_none_when_no_match(self):
        found = self.svc._find_linked_member(
            "admin_member", 99887767, row_data={"email": "nobody.matches.zzz@example.com"}
        )
        self.assertIsNone(found)
