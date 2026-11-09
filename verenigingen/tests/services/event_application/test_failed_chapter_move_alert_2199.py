"""#2199: a MijnRood division change whose chapter move FAILS must tell staff.

``RelatedRecordsOrchestrator._assign_chapter_from_division`` turned a refused or failed
``assign_with_cleanup`` into a message string appended to the event's applied message. The event was
consumed, the member's other fields updated, the member stayed in the OLD chapter and nobody was told
(MijnRood does not resend).

Real flows throughout: a real ``Changed`` admin_member event applied by the real dispatcher, the real
``assign_with_cleanup`` refusing because the source chapter fails its own validation (the #1945 shape), and
the real ``notify_administrators`` read back from Staff Alert Event rows (MyISAM: they survive rollback, so
every test deletes its own). Probe shortcuts, stated: the invalid source chapter data is written with
``db.set_value`` (that is how legacy invalid data exists; the validator refuses to save it), the lock
timeout is injected with a patch (a real one needs a second committed connection), and the event's
``linked_member`` is set directly (the field the sync itself fills; it spares building a MijnRood member id).
Only SMTP is stubbed.
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.mijnrood_sync.services.event_application.dispatcher import get_event_application_service
from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ALERT_KEY = "mijnrood_chapter_move_failed"
BAD_POSTAL = "9999-1000"  # reversed range: Chapter.validate refuses it


class TestFailedChapterMoveAlert2199(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
        from verenigingen.tests.test_notification_registry_seed_1959 import _rows

        # A site installed before the key existed has no row until migrate seeds it (#2037): seed the way
        # migrate does and put the Single's rows back exactly as they were.
        self._baseline_rows = [dict(r.as_dict()) for r in _rows().values()]
        self.addCleanup(self._restore_registry_rows_2199)
        ensure_notification_registry_rows()
        self.addCleanup(self._purge_alert_events_2199)
        self.addCleanup(self._delete_claims)
        self.addCleanup(self._delete_notifications)

        suffix = frappe.generate_hash(length=6)
        self.source = self.ensure_test_chapter(f"Test 2199 Source {suffix}")
        self.target = self.ensure_test_chapter(f"Test 2199 Target {suffix}")
        self.member = self.create_test_member(first_name="Move", last_name=f"Out{suffix}")
        ChapterMembershipManager.assign_member_to_chapter(
            member_id=self.member.name, chapter_name=self.source.name, notify=False
        )
        self.division_id = 7000000 + int(frappe.generate_hash(length=4), 16) % 900000
        frappe.db.set_value("Chapter", self.target.name, "mijnrood_division_id", self.division_id)

    def _restore_registry_rows_2199(self):
        config = frappe.get_single("Verenigingen Email Configuration")
        config.notification_types = []
        for row in self._baseline_rows:
            config.append(
                "notification_types",
                {k: v for k, v in row.items() if k not in ("name", "creation", "modified", "idx")},
            )
        config.save()

    def _purge_alert_events_2199(self):
        frappe.db.delete("Staff Alert Event", {"notification_key": ALERT_KEY})

    def _delete_claims(self):
        for key in frappe.cache.get_keys(f"*{ALERT_KEY}*"):
            frappe.cache.delete(key.decode() if isinstance(key, bytes) else key)

    def _staff_alert_events(self):
        return frappe.get_all(
            "Staff Alert Event",
            {"notification_key": ALERT_KEY},
            ["name", "subject", "outcome", "requires_action", "reference_name"],
        )

    def _sent(self, member_name):
        """Notification Log rows the alert delivered for one member. The Staff Alert Event is one row per
        member however often it is sent (its reference is stable), so it cannot show a repeat send."""
        return frappe.db.count(
            "Notification Log", {"subject": f"MijnRood chapter move failed for {member_name}"}
        )

    def _delete_notifications(self):
        frappe.db.delete("Notification Log", {"subject": ["like", "MijnRood chapter move failed for %"]})

    def _chapter_rows_2199(self):
        return {
            r.parent: r.enabled
            for r in frappe.get_all("Chapter Member", filters={"member": self.member.name}, fields=["parent", "enabled"])
        }

    def _break_source(self):
        frappe.db.set_value("Chapter", self.source.name, "postal_codes", BAD_POSTAL)
        self.expectErrorLog("Failed to remove member", "Range start 9999")

    def _apply_division_change(self):
        """A real Changed admin_member event moving the member to the target chapter's division."""
        mid = 6000000 + int(frappe.generate_hash(length=4), 16)
        event = frappe.get_doc(
            {
                "doctype": "MijnRood Sync Event",
                "mijnrood_table": "admin_member",
                "event_type": "Changed",
                "mijnrood_row_id": mid,
                "status": "Approved",
                "linked_member": self.member.name,
                "new_data": json.dumps(
                    {
                        "id": mid,
                        "first_name": self.member.first_name,
                        "last_name": self.member.last_name,
                        "email": self.member.email,
                        "current_membership_status_id": 1,
                    }
                ),
                "old_data": json.dumps({"id": mid}),
                "changed_fields": json.dumps(
                    [{"field": "division_id", "old": 1, "new": self.division_id}]
                ),
            }
        ).insert()
        self.addCleanup(self._purge_sync_event_2199, event.name)
        # Mock justified: External Service - SMTP delivery, not business logic
        with patch("frappe.sendmail"):
            return get_event_application_service().apply_event(event.name)

    def _purge_sync_event_2199(self, name):
        if frappe.db.exists("MijnRood Sync Event", name):
            frappe.delete_doc("MijnRood Sync Event", name, ignore_permissions=True, force=True)

    def test_a_failed_move_raises_one_alert_naming_member_chapters_and_reason(self):
        self._break_source()

        result = self._apply_division_change()

        self.assertIn("Chapter assignment failed", result["message"], result)
        self.assertEqual(self._chapter_rows_2199(), {self.source.name: 1}, "the member must stay in the old chapter")
        (alert,) = self._staff_alert_events()
        self.assertEqual(alert.outcome, "Delivered", alert)
        self.assertEqual(alert.requires_action, 1)
        self.assertIn(self.member.name, alert.subject + (alert.reference_name or ""))
        body = self._notification_text()
        for expected in (self.member.name, self.source.name, self.target.name, "Range start 9999"):
            self.assertIn(expected, body)

    def _notification_text(self):
        """Subject and content of the Notification Log rows the alert created."""
        rows = frappe.get_all(
            "Notification Log",
            filters={"subject": ["like", "%MijnRood chapter move failed%"]},
            fields=["subject", "email_content"],
        )
        self.assertTrue(rows, "no Notification Log row for the alert")
        return " ".join(f"{r.subject} {r.email_content}" for r in rows)

    def test_the_same_failure_again_is_deduplicated(self):
        self._break_source()
        self._apply_division_change()
        first = self._sent(self.member.name)
        self.assertGreater(first, 0, "control: the first failure must have been delivered")

        self._apply_division_change()

        self.assertEqual(self._sent(self.member.name), first, "an identical failure must not alert twice")

    def test_a_failure_for_another_member_alerts_again(self):
        """Control for the dedupe: it is per member, not one bucket for every failed move."""
        other = self.create_test_member(first_name="Other", last_name=f"Out{frappe.generate_hash(length=6)}")
        ChapterMembershipManager.assign_member_to_chapter(
            member_id=other.name, chapter_name=self.source.name, notify=False
        )
        self._break_source()  # after both members joined: an invalid chapter refuses new members too
        first_member = self.member
        self._apply_division_change()
        self.member = other

        self._apply_division_change()

        self.assertGreater(self._sent(first_member.name), 0)
        self.assertGreater(self._sent(other.name), 0, "the second member's failed move must alert too")

    def test_a_successful_move_raises_no_alert(self):
        result = self._apply_division_change()

        self.assertIn(self.target.name, result["message"], result)
        self.assertEqual(self._chapter_rows_2199()[self.target.name], 1)
        self.assertEqual(self._staff_alert_events(), [])
        self.assertEqual(self._sent(self.member.name), 0)

    def test_a_lock_timeout_during_the_move_alerts_too(self):
        # Mock justified: infrastructure fault injection; a real 1205 needs a second committed connection.
        self.expectErrorLog("MijnRood Chapter Assignment Failed")
        with patch(
            "verenigingen.verenigingen.doctype.chapter.chapter.Chapter.remove_member",
            side_effect=frappe.QueryTimeoutError("lock-2199"),
        ):
            result = self._apply_division_change()

        self.assertIn("Chapter assignment error", result["message"], result)
        self.assertEqual(self._chapter_rows_2199(), {self.source.name: 1})
        self.assertEqual(len(self._staff_alert_events()), 1)
        self.assertGreater(self._sent(self.member.name), 0)
