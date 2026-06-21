# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Integration tests for the MijnRood Sync Event controller.

Exercises the real status-transition methods (approve / reject / ignore_event),
the guarded apply paths (apply_event / approve_and_apply -> event application
service), and the get_member_comparison_data diff builder against real Member /
Address / Chapter Member records.

No business logic is mocked. Events are real MijnRood Sync Event documents with
JSON old_data/new_data. The apply delegation is verified against the real
event_application_service: a table NOT in its handler map ("admin_division" is
handled, so we use an unhandled-table 'reference-only' path is impossible —
instead we assert delegation by status side effects and the service's return
contract).
"""

import json

import frappe
from frappe.utils import now_datetime

from verenigingen.mijnrood_sync.doctype.mijnrood_sync_event.mijnrood_sync_event import (
    get_member_comparison_data,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMijnRoodSyncEvent(EnhancedTestCase):
    def _make_event(self, **overrides):
        """Create a Pending MijnRood Sync Event with sensible defaults."""
        data = {
            "doctype": "MijnRood Sync Event",
            "event_type": "Changed",
            "status": "Pending",
            "mijnrood_table": "admin_member",
            "mijnrood_row_id": overrides.pop("mijnrood_row_id", 999001),
            "detected_at": now_datetime(),
            "sync_run_id": "test-run",
        }
        data.update(overrides)
        event = frappe.get_doc(data)
        event.insert(ignore_permissions=True)
        self.factory.track_document("MijnRood Sync Event", event.name, priority=1)
        return event

    # ---- approve --------------------------------------------------------

    def test_approve_pending_event(self):
        event = self._make_event()
        event.approve()
        self.assertEqual(event.status, "Approved")
        self.assertEqual(event.reviewed_by, frappe.session.user)
        self.assertIsNotNone(event.reviewed_at)
        # Persisted, not just in-memory.
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event.name, "status"), "Approved")

    def test_approve_rejects_non_pending(self):
        event = self._make_event(status="Approved")
        with self.assertRaises(frappe.ValidationError):
            event.approve()

    def test_approve_rejects_already_applied(self):
        event = self._make_event(status="Applied")
        with self.assertRaises(frappe.ValidationError):
            event.approve()

    # ---- reject ---------------------------------------------------------

    def test_reject_pending_event(self):
        event = self._make_event()
        event.reject()
        self.assertEqual(event.status, "Rejected")
        self.assertEqual(event.reviewed_by, frappe.session.user)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event.name, "status"), "Rejected")

    def test_reject_rejects_non_pending(self):
        event = self._make_event(status="Rejected")
        with self.assertRaises(frappe.ValidationError):
            event.reject()

    # ---- ignore_event ---------------------------------------------------

    def test_ignore_pending_event(self):
        event = self._make_event()
        event.ignore_event()
        self.assertEqual(event.status, "Ignored")
        self.assertEqual(event.reviewed_by, frappe.session.user)
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event.name, "status"), "Ignored")

    def test_ignore_rejects_non_pending(self):
        event = self._make_event(status="Ignored")
        with self.assertRaises(frappe.ValidationError):
            event.ignore_event()

    # ---- apply_event guard ----------------------------------------------

    def test_apply_event_rejects_non_approved(self):
        event = self._make_event(status="Pending")
        with self.assertRaises(frappe.ValidationError):
            event.apply_event()

    def test_apply_event_rejects_applied(self):
        event = self._make_event(status="Applied")
        with self.assertRaises(frappe.ValidationError):
            event.apply_event()

    def test_apply_event_delegates_for_approved(self):
        """An Approved event delegates to the event application service. A
        'Changed' admin_member event with no linked member deterministically
        fails inside the service (member not found) rather than raising — so
        assert the failure contract unconditionally and that status is NOT
        flipped to Applied on failure."""
        event = self._make_event(
            status="Approved",
            event_type="Changed",
            new_data=json.dumps({"first_name": "Nobody"}),
        )
        result = event.apply_event()
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        # Failure path must not mark the event Applied.
        self.assertNotEqual(frappe.db.get_value("MijnRood Sync Event", event.name, "status"), "Applied")

    # ---- approve_and_apply ----------------------------------------------

    def test_approve_and_apply_rejects_non_pending(self):
        event = self._make_event(status="Approved")
        with self.assertRaises(frappe.ValidationError):
            event.approve_and_apply()

    def test_approve_and_apply_approves_then_delegates(self):
        """approve_and_apply first flips Pending->Approved (persisted), then
        delegates to the application service. Even if application fails, the
        event must have been approved + reviewed first."""
        event = self._make_event(
            status="Pending",
            event_type="Changed",
            new_data=json.dumps({"first_name": "Nobody"}),
        )
        result = event.approve_and_apply()
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        # reviewed_by/at were set during the approve step.
        self.assertEqual(
            frappe.db.get_value("MijnRood Sync Event", event.name, "reviewed_by"),
            frappe.session.user,
        )
        # Status is Approved (then possibly Applied on success).
        status = frappe.db.get_value("MijnRood Sync Event", event.name, "status")
        self.assertIn(status, ("Approved", "Applied"))

    def test_approve_and_apply_reference_only_table_applies(self):
        """A table NOT in the application service's handler map is treated as
        'reference only' -> the service returns success -> the event ends up
        Applied. This proves the full Pending -> Approved -> Applied path."""
        event = self._make_event(
            status="Pending",
            event_type="Changed",
            mijnrood_table="admin_support_member",
            new_data=json.dumps({"first_name": "Ref"}),
        )
        result = event.approve_and_apply()
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("MijnRood Sync Event", event.name, "status"), "Applied")


class TestGetMemberComparisonData(EnhancedTestCase):
    def _make_event(self, linked_member=None, **overrides):
        data = {
            "doctype": "MijnRood Sync Event",
            "event_type": "Changed",
            "status": "Pending",
            "mijnrood_table": "admin_member",
            "mijnrood_row_id": overrides.pop("mijnrood_row_id", 998001),
            "detected_at": now_datetime(),
            "sync_run_id": "cmp-run",
            "linked_member": linked_member,
        }
        data.update(overrides)
        event = frappe.get_doc(data)
        event.insert(ignore_permissions=True)
        self.factory.track_document("MijnRood Sync Event", event.name, priority=1)
        return event

    def test_no_linked_member_returns_empty(self):
        event = self._make_event(linked_member=None)
        self.assertEqual(get_member_comparison_data(event.name), {})

    def test_comparison_includes_basic_member_fields(self):
        member = self.create_test_member(
            first_name="Comparison",
            last_name="Tester",
            email="comparison.tester@example.com",
        )
        event = self._make_event(linked_member=member.name)
        result = get_member_comparison_data(event.name)
        # Keyed by MijnRood column names (reverse of MIJNROOD_TO_MEMBER_FIELD_MAP).
        self.assertEqual(result["email"], member.email)
        self.assertEqual(result["first_name"], "Comparison")
        # last_name is uniquified by the factory; just assert it round-trips.
        self.assertEqual(result["last_name"], member.last_name)
        # All values must be strings (the JS table compares strings).
        self.assertTrue(all(isinstance(v, str) for v in result.values()))

    def test_comparison_membership_status_resolves_to_label(self):
        """member.status (a Frappe string) gets matched to a MijnRood-style
        label so the JS comparison aligns formats. For status 'Active' this
        should resolve to the 'Active (lid)' default label."""
        member = self.create_test_member(
            first_name="Status", last_name="Person", email="status.person@example.com"
        )
        # Ensure a known status value.
        frappe.db.set_value("Member", member.name, "status", "Active")
        event = self._make_event(linked_member=member.name)
        result = get_member_comparison_data(event.name)
        self.assertIn("current_membership_status_id", result)
        # Matched against get_status_labels(): label starting with "active".
        self.assertTrue(result["current_membership_status_id"].lower().startswith("active"))

    def test_comparison_includes_address_fields(self):
        member = self.create_test_member(
            first_name="Addr",
            last_name="Person",
            email="addr.person@example.com",
            address_line1="Teststraat 1",
            city="Amsterdam",
            postal_code="1011AB",
        )
        # create_member links primary_address when address fields are supplied.
        self.assertTrue(frappe.db.get_value("Member", member.name, "primary_address"))
        event = self._make_event(linked_member=member.name)
        result = get_member_comparison_data(event.name)
        self.assertEqual(result["address"], "Teststraat 1")
        self.assertEqual(result["city"], "Amsterdam")
        self.assertEqual(result["post_code"], "1011AB")

    def test_comparison_handles_missing_primary_address_gracefully(self):
        member = self.create_test_member(
            first_name="NoAddr", last_name="Person", email="noaddr.person@example.com"
        )
        # Point primary_address at a nonexistent Address; the builder must
        # swallow DoesNotExistError and NOT crash. The address keys still come
        # from the direct member-field loop (address_line1/city/postal_code),
        # so they remain present (empty here) — the Address-document branch is
        # simply skipped on the DoesNotExistError.
        frappe.db.set_value("Member", member.name, "primary_address", "NONEXISTENT-ADDR-ZZZ")
        event = self._make_event(linked_member=member.name)
        # Must not raise despite the dangling primary_address link.
        result = get_member_comparison_data(event.name)
        # Member-level fields are still present.
        self.assertEqual(result["email"], member.email)
        # The Address-document overwrite never happened -> address stays "".
        self.assertEqual(result["address"], "")

    def test_comparison_includes_active_chapter_division(self):
        member = self.create_test_member(
            first_name="Chap", last_name="Person", email="chap.person@example.com"
        )
        chapter = self.create_test_chapter()
        # Add an Active Chapter Member row linking this member.
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append("members", {"member": member.name, "status": "Active"})
        chapter_doc.save()
        frappe.db.commit()
        event = self._make_event(linked_member=member.name)
        result = get_member_comparison_data(event.name)
        self.assertEqual(result.get("division_id"), chapter.name)

    def test_module_and_method_helpers_agree(self):
        """The doctype method get_member_comparison_data and the standalone
        whitelisted function share the same implementation — they must return
        identical results for the same event."""
        member = self.create_test_member(
            first_name="Same", last_name="Person", email="same.person@example.com"
        )
        event = self._make_event(linked_member=member.name)
        via_method = event.get_member_comparison_data()
        via_function = get_member_comparison_data(event.name)
        self.assertEqual(via_method, via_function)
