"""
Real-integration tests for the member scheduler module
``verenigingen/verenigingen/doctype/member/scheduler.py``.

Covers the genuine scheduled-task and admin logic: the financial-history
refresh family (refresh_all / batch / specific / status / single-member test),
the duration helpers, and the scheduler-event registration. Members are created
via the test factory (with real Customer records) and run as Administrator.

The four dead ``*_chapter_assignment_test`` debug runners that used to live here
were deleted (whitelisted, no callers, and two mutated production data), so they
are intentionally not tested.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member import scheduler


class TestMemberScheduler(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Scheduler",
            last_name="Member",
            email="scheduler.member@test.invalid",
            status="Active",
        )
        # The financial-history refresh path needs a Customer record.
        self.assertTrue(
            frappe.get_doc("Member", self.member.name).customer,
            "factory member should have a customer",
        )

    def _member_rows(self, *member_names):
        return frappe.get_all(
            "Member", filters={"name": ["in", member_names]}, fields=["name", "full_name", "customer"]
        )

    # ------------------------------------------------------------------ scheduler registration

    def test_setup_member_scheduler_events(self):
        events = scheduler.setup_member_scheduler_events()
        self.assertIn("daily", events)
        self.assertIn(
            "verenigingen.verenigingen.doctype.member.scheduler.refresh_all_member_financial_histories",
            events["daily"],
        )

    # ------------------------------------------------------------------ batch processing

    def test_process_member_history_batch_success(self):
        result = scheduler.process_member_history_batch(self._member_rows(self.member.name))
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["total"], 1)

    def test_enqueue_member_history_refresh_returns_dict(self):
        # Must return a dict (not the raw RQ Job) so refresh_all can read
        # result.get("success"); under frappe.flags.in_test enqueue runs inline.
        result = scheduler.enqueue_member_history_refresh(self._member_rows(self.member.name))
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertTrue(result["enqueued"])
        self.assertEqual(result["total"], 1)

    def test_process_member_history_batch_tolerates_bad_member(self):
        # A nonexistent member must be counted as an error, not abort the batch.
        rows = self._member_rows(self.member.name)
        rows.append(frappe._dict(name="NONEXISTENT-MEMBER-XYZ", full_name="Ghost", customer="X"))
        result = scheduler.process_member_history_batch(rows)
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertTrue(result["error_details"])

    # ------------------------------------------------------------------ refresh_specific

    def test_refresh_specific_member_histories_single_string(self):
        result = scheduler.refresh_specific_member_histories(self.member.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)

    def test_refresh_specific_member_histories_list(self):
        result = scheduler.refresh_specific_member_histories([self.member.name])
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)

    def test_refresh_specific_member_histories_no_valid(self):
        result = scheduler.refresh_specific_member_histories(["NONEXISTENT-MEMBER-XYZ"])
        self.assertFalse(result["success"])
        self.assertIn("No valid members", result["message"])

    # ------------------------------------------------------------------ status / single-member test

    def test_get_member_history_refresh_status(self):
        status = scheduler.get_member_history_refresh_status()
        self.assertNotIn("error", status)
        for key in (
            "total_members_with_customers",
            "members_with_payment_history",
            "recent_updates_24h",
            "coverage_percentage",
        ):
            self.assertIn(key, status)
        self.assertGreaterEqual(status["total_members_with_customers"], 1)

    def test_test_member_history_refresh_with_member(self):
        result = scheduler.test_member_history_refresh(self.member.name)
        self.assertEqual(result["member_name"], self.member.name)
        self.assertIn("initial_payment_history_count", result)
        self.assertIn("final_payment_history_count", result)
        self.assertIn("history_updated", result)

    def test_test_member_history_refresh_autoselect(self):
        # setUp guarantees at least one member-with-customer exists, so autoselect
        # must resolve a member and return the structured result (not the
        # no-members-found branch).
        result = scheduler.test_member_history_refresh()
        self.assertIn("success", result)
        self.assertTrue(result.get("member_name"), "autoselect should resolve a member")
        self.assertIn("final_payment_history_count", result)

    # ------------------------------------------------------------------ duration helpers

    def test_update_single_member_duration(self):
        result = scheduler.update_single_member_duration(self.member.name)
        self.assertIsInstance(result, dict)
        # Happy path: the member resolved and the duration service ran without
        # hitting the except branch (which would surface an "error" key).
        self.assertIn("success", result)
        self.assertNotIn("error", result)

    def test_update_single_member_duration_nonexistent(self):
        result = scheduler.update_single_member_duration("NONEXISTENT-MEMBER-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_update_all_membership_durations_deprecated_stub(self):
        result = scheduler.update_all_membership_durations()
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 0)

    def test_get_duration_update_stats(self):
        stats = scheduler.get_duration_update_stats()
        self.assertNotIn("error", stats)
        self.assertIn("total_members", stats)
        self.assertIn("members_with_duration", stats)
        self.assertIn("coverage_percentage", stats)

    # ------------------------------------------------------------------ refresh_all (skip path)

    def test_refresh_all_skips_when_run_recently(self):
        # A recent last-run (1 hour ago) is < the 10-hour threshold, so the task
        # must skip without processing. This is the only safe branch to exercise:
        # the run branch commits (frappe.db.commit) and processes every member.
        original = frappe.db.get_single_value("Verenigingen Settings", "last_member_history_refresh")
        try:
            frappe.db.set_single_value(
                "Verenigingen Settings",
                "last_member_history_refresh",
                add_to_date(now_datetime(), hours=-1),
            )
            result = scheduler.refresh_all_member_financial_histories()
            self.assertTrue(result["success"])
            self.assertTrue(result.get("skipped"))
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "last_member_history_refresh", original)
