"""
A failed query must not be indistinguishable from a genuine zero (#593).

PR #592 taught the swallow guard to recognise a dict whose every value is a falsy
literal and RECORDED the 8 sites it found; this module is the behavioural half.
Each site returned zero-stats from inside a broad ``except``, so its caller could
not tell "there is no data" from "the query blew up" -- and in four of the eight
the caller ALREADY had a correct handler that the inner swallow made unreachable.

Every test here pairs the failure with its CONTROL: the genuine no-data path,
which must still answer zeros. Without that pair "it raises now" would be
consistent with "it raises on everything", which is not the fix.

Triggers are real, not mocked -- a missing document, a filter value the query
layer cannot build SQL from. Five sites raise now; a sixth
(`get_basic_expense_stats`) keeps its zeros and adds "error", for the reason
given at its tests below. The remaining two (`get_alert_summary`,
`MonitoringMetricsService._get_member_growth_rate`) and
`ChapterQueryService.get_user_permissions_optimized` take no argument that
reaches their query, so they have NO mock-free failure trigger and are not
covered here; they carry the cause in the returned dict, and the error_swallow
ratchet is what holds them.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestQueryFailureIsNotAZero(EnhancedTestCase):
    """A swallowed query failure must be distinguishable from an honest zero."""

    # ---- bulk_retry_processor.process_single_retry_queue --------------------
    #
    # The headline site: on failure the caller told the user "No retry requests
    # to process", and reported `"failed": 0` precisely when everything failed.

    def _make_tracker(self):
        tracker = frappe.get_doc(
            {
                "doctype": "Bulk Operation Tracker",
                "operation_type": "Account Creation",
                "status": "Completed",
                "total_records": 0,
                "total_batches": 0,
            }
        )
        tracker.insert(ignore_permissions=True)
        return tracker

    def test_a_crashed_retry_queue_raises_instead_of_returning_zeros(self):
        from verenigingen.utils.bulk_retry_processor import process_single_retry_queue

        with self.assertRaises(frappe.DoesNotExistError):
            process_single_retry_queue("Nonexistent-Tracker-XYZ")

    def test_a_tracker_with_nothing_to_retry_still_returns_zeros(self):
        """CONTROL: the honest no-data answer is unchanged."""
        from verenigingen.utils.bulk_retry_processor import process_single_retry_queue

        result = process_single_retry_queue(self._make_tracker().name)
        self.assertEqual(result, {"processed": 0, "succeeded": 0, "failed": 0})

    def test_the_user_is_not_told_there_was_nothing_to_do(self):
        """The lie itself: a crash rendered as "No retry requests to process"."""
        from verenigingen.utils.bulk_retry_processor import manual_retry_failed_requests

        self.expectErrorLog("Manual Retry Error")
        frappe.clear_messages()

        with self.assertRaises(frappe.ValidationError) as caught:
            manual_retry_failed_requests("Nonexistent-Tracker-XYZ")

        self.assertIn("Retry processing failed", str(caught.exception))
        shown = " ".join(str(m.get("message", "")) for m in (frappe.local.message_log or []))
        self.assertNotIn("No retry requests to process", shown)

    # ---- templates/pages/volunteer/dashboard.get_expense_summary -----------
    #
    # dashboard.py already wraps this call, logs, and sets context.error_message
    # ("Some dashboard data could not be loaded") -- which dashboard.html
    # renders and which the inner swallow made unreachable.

    def test_a_crashed_expense_summary_raises_instead_of_returning_zeros(self):
        from verenigingen.templates.pages.volunteer import dashboard

        with self.assertRaises(frappe.DoesNotExistError):
            dashboard.get_expense_summary("Nonexistent-Volunteer-XYZ")

    def test_a_volunteer_without_an_employee_still_returns_zeros(self):
        """CONTROL: no employee record is a real answer, not a failure."""
        from verenigingen.templates.pages.volunteer import dashboard

        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        summary = dashboard.get_expense_summary(volunteer.name)
        self.assertEqual(summary["total_submitted"], 0)
        self.assertEqual(summary["pending_count"], 0)

    # ---- templates/pages/manage_donations.get_donation_summary -------------
    #
    # get_donation_stats already returns {"error": ...}; the inner swallow made it
    # answer {"status": "success", "data": {zeros}} instead.

    def test_a_crashed_donation_summary_raises_instead_of_returning_zeros(self):
        from verenigingen.templates.pages.manage_donations import get_donation_summary

        with self.assertRaises(frappe.DoesNotExistError):
            get_donation_summary("Nonexistent-Member-XYZ")

    def test_a_member_without_donations_still_returns_zeros(self):
        """CONTROL: no donations is a real answer."""
        from verenigingen.templates.pages.manage_donations import get_donation_summary

        member = self.create_test_member()
        summary = get_donation_summary(member.name)
        self.assertEqual(summary["total_donated"], 0)
        self.assertEqual(summary["total_donations"], 0)

    # ---- templates/pages/chapter_dashboard.get_basic_expense_stats ---------
    #
    # The one site that CARRIES the cause rather than raising: `custom_chapter` is
    # one of seven Expense Claim `custom_*` fields that exist on the live site and
    # are shipped by nothing, so on a fresh install this query fails every time
    # and raising would replace the whole dashboard with an error page. The
    # template shows "--" for the expense tiles when "error" is present.

    def test_a_crashed_expense_stat_query_carries_the_cause(self):
        from verenigingen.templates.pages.chapter_dashboard import get_basic_expense_stats

        # A 3-element list reaches frappe.get_all as a filter and cannot be
        # unpacked into (operator, value) -- a real ValueError from the query
        # layer, no mock.
        self.expectErrorLog("Error calculating expense statistics")
        stats = get_basic_expense_stats(["a", "b", "c"])
        self.assertIn("error", stats)
        self.assertEqual(stats["pending_count"], 0)

    def test_a_chapter_without_expenses_reports_zeros_and_no_error(self):
        """CONTROL: a chapter with no expense claims is a real zero.

        Skipped where the Custom Field is missing -- which is every test site and
        CI, and is itself the finding: this query has never once run there.
        """
        from verenigingen.templates.pages.chapter_dashboard import get_basic_expense_stats

        if not frappe.db.exists("Custom Field", "Expense Claim-custom_chapter"):
            self.skipTest("Expense Claim-custom_chapter exists on the live site only")

        chapter = self.ensure_test_chapter("Test Zero Stats Chapter")
        stats = get_basic_expense_stats(chapter.name)
        self.assertNotIn("error", stats)
        self.assertEqual(stats["pending_count"], 0)
        self.assertEqual(stats["ytd_total"], 0)

    def test_member_metrics_for_a_fresh_chapter_are_zero(self):
        """CONTROL for the sibling swallow removed in the same function.

        The member half of get_chapter_key_metrics zeroed into a VARIABLE rather
        than returning, so the validator never saw it; it now propagates. This
        control needs no custom field, so unlike the one above it runs everywhere.
        """
        from verenigingen.templates.pages.chapter_dashboard import get_chapter_key_metrics

        self.expectErrorLog("Error calculating expense statistics")
        chapter = self.ensure_test_chapter("Test Zero Metrics Chapter")
        metrics = get_chapter_key_metrics(chapter.name)
        self.assertEqual(metrics["members"]["total"], 0)
        self.assertEqual(metrics["members"]["active"], 0)

    # ---- templates/pages/volunteer/skills.get_skills_statistics ------------

    def test_a_crashed_skills_statistics_query_raises_instead_of_returning_zeros(self):
        from verenigingen.templates.pages.volunteer.skills import get_skills_statistics

        # A set of member ids is the natural thing for a caller to build and the
        # one shape this `IN %(member_ids)s` query cannot render -- measured, a
        # real ProgrammingError from MariaDB.
        with self.assertRaises(frappe.db.ProgrammingError):
            get_skills_statistics(member_ids={"MEM-A", "MEM-B"})

    def test_no_members_still_returns_zero_statistics(self):
        """CONTROL: an empty member list is a real zero, and never queried."""
        from verenigingen.templates.pages.volunteer.skills import get_skills_statistics

        stats = get_skills_statistics(member_ids=[])
        self.assertEqual(stats["total_unique_skills"], 0)
        self.assertEqual(stats["skill_categories"], 0)
