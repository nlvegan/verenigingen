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
layer cannot build SQL from.

Four of the eight sites RAISE now, and so does one sibling the validator could
not see (`get_chapter_key_metrics`'s member half). Two carry the cause instead
because their caller would otherwise error-page a whole dashboard over one tile
(`get_basic_expense_stats`, and its money-block neighbour
`get_financial_summary`), and both are covered here.

Not covered: `get_alert_summary`,
`MonitoringMetricsService._get_member_growth_rate` and
`ChapterQueryService.get_user_permissions_optimized` take no argument that
reaches their query, so they have NO mock-free failure trigger. They carry the
cause in the returned dict, and the error_swallow ratchet is what holds them.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestQueryFailureIsNotAZero(EnhancedTestCase):
    """A swallowed query failure must be distinguishable from an honest zero."""

    # ---- bulk_retry_processor.process_single_retry_queue --------------------
    #
    # The headline site: on failure the caller told the user "No retry requests
    # to process", and reported `"failed": 0` precisely when everything failed.

    def _make_bulk_operation_tracker(self):
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

        result = process_single_retry_queue(self._make_bulk_operation_tracker().name)
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
        # layer, before any SQL is built, so it is not passing by accident on a
        # site whose custom fields are missing.
        self.expectErrorLog("Error calculating expense statistics")
        stats = get_basic_expense_stats(["a", "b", "c"])
        self.assertIn("error", stats)
        # All four counts must survive beside it: chapter_dashboard.html indexes
        # pending_amount, pending_count and ytd_total, and prints "--" off "error".
        for key in ("pending_amount", "pending_count", "ytd_total", "this_month"):
            self.assertEqual(stats[key], 0, key)

    def test_a_crashed_financial_summary_carries_the_cause(self):
        """The money block beside those tiles, on the same column, same failure.

        Invisible to the swallow validator because its zeros are NESTED dicts
        (#601), so nothing would have caught this one going the other way.
        """
        from verenigingen.templates.pages.chapter_dashboard import get_financial_summary

        self.expectErrorLog("Error calculating financial summary")
        summary = get_financial_summary(["a", "b", "c"])
        self.assertIn("error", summary)
        self.assertEqual(summary["this_month"]["expenses_submitted"], 0)
        self.assertEqual(summary["ytd"]["total_expenses"], 0)

    def test_a_chapter_without_expenses_reports_zeros_and_no_error(self):
        """CONTROL: a chapter with no expense claims is a real zero.

        Skips only where the seven Expense Claim `custom_*` fields are absent --
        which is NOT "every test site": they ship in
        fixtures/expense_claim_custom_fields.json, and `bench migrate` imports
        them. A site that installed verenigingen before hrms lacks them until its
        next migrate, and that is the case this skip covers (see #600).
        """
        from verenigingen.templates.pages.chapter_dashboard import get_basic_expense_stats

        if not frappe.db.exists("Custom Field", "Expense Claim-custom_chapter"):
            self.skipTest("Expense Claim-custom_chapter absent; run `bench migrate` on this site")

        chapter = self.ensure_test_chapter("Test Zero Stats Chapter")
        stats = get_basic_expense_stats(chapter.name)
        self.assertNotIn("error", stats)
        self.assertEqual(stats["pending_count"], 0)
        self.assertEqual(stats["ytd_total"], 0)

    def test_a_crashed_member_metric_query_raises(self):
        """The sibling swallow removed in the same function, in its own right.

        The member half of get_chapter_key_metrics zeroed into a VARIABLE rather
        than returning, so the validator never saw it (#601). Measured against the
        base tree, this same call returned members={...all zeros...}.
        """
        from verenigingen.templates.pages.chapter_dashboard import get_chapter_key_metrics

        with self.assertRaises(ValueError):
            get_chapter_key_metrics(["a", "b", "c"])

    def test_member_metrics_for_a_fresh_chapter_are_zero(self):
        """CONTROL for the test above: an empty chapter is a real zero.

        Needs no custom field, so unlike the expense control it runs everywhere.
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
