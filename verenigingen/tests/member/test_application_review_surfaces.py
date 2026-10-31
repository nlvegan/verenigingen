"""#1765 task 7: the review surfaces read applications (MAS rows), not Pending Members.

Fixture shortcut, stated: the list-surface tests insert an inert Unconfirmed row and give it a
`chapter`, `confirmed_on` and `set_status("Pending Review")`, the writes application_record makes at
confirmation, instead of driving the emailed-link flow (test_application_record.py covers that). The
surfaces read only those fields. The quick-approve tests drive the real flow (submit, confirm, approve).

Every chapter-scope test seats a real board member in chapter A and puts a REAL application in chapter B
(and one with no chapter), so a surface that ignores the permission query has something to leak.
"""

import frappe
from frappe.utils import add_days, now_datetime

from verenigingen.api import chapter_dashboard_api
from verenigingen.api.admin_membership_operations import get_application_stats
from verenigingen.api.membership_application_review import get_pending_applications
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.templates.pages.chapter_dashboard import (
    get_chapter_key_metrics,
    get_member_overview,
    get_pending_actions,
)
from verenigingen.utils.error_handling import PermissionError as VerenigingenPermissionError
from verenigingen.verenigingen.report.pending_membership_applications import (
    pending_membership_applications as report,
)

SUBMISSION = "Membership Application Submission"


class SurfaceCase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter_a = self.ensure_test_chapter("TEST Surface A")
        self.chapter_b = self.ensure_test_chapter("TEST Surface B")
        self.board_a = self.create_test_board_member(self.chapter_a.name, permissions_level="Admin")

    def _application(self, chapter, status="Pending Review", days_ago=0, name="Surface Applicant"):
        email = f"surf.{frappe.generate_hash(length=8).lower()}@example.org"
        doc = frappe.get_doc(
            {
                "doctype": SUBMISSION,
                "email": email,
                "source": "Full Form",
                "applicant_name": f"{name} {frappe.generate_hash(length=4)}",
                "payload": "{}",
            }
        )
        doc.insert()
        self.track_doc(SUBMISSION, doc.name)
        doc.db_set("confirmed_on", add_days(now_datetime(), -days_ago))
        if chapter:
            doc.db_set("chapter", chapter)
        if status != "Unconfirmed":
            doc.set_status("Pending Review")
        if status in ("Approved", "Rejected"):
            doc.set_status(status)
        return doc.name

    def _seed(self):
        """Real rows in A, in B and with no chapter, plus rows in A that are not Pending Review."""
        self.app_a = self._application(self.chapter_a.name)
        self.app_a2 = self._application(self.chapter_a.name)
        self.app_b = self._application(self.chapter_b.name)
        self.app_b2 = self._application(self.chapter_b.name)
        self.app_none = self._application(None)
        self.unconfirmed_a = self._application(self.chapter_a.name, status="Unconfirmed")
        self.approved_a = self._application(self.chapter_a.name, status="Approved")


class TestPendingList(SurfaceCase):
    def test_lists_a_confirmed_application_and_no_members(self):
        member = self.create_test_member(first_name="PendingMember", status="Pending", application_status="Pending")
        self._seed()

        names = {row["name"] for row in get_pending_applications()}

        self.assertIn(self.app_a, names)
        self.assertNotIn(member.name, names, "a Pending Member is not an application")
        self.assertNotIn(self.unconfirmed_a, names)
        self.assertNotIn(self.approved_a, names)

    def test_row_keys(self):
        name = self._application(self.chapter_a.name, days_ago=3)
        row = next(r for r in get_pending_applications() if r["name"] == name)
        for key in (
            "name", "application_id", "applicant_name", "email", "membership_type", "chapter",
            "application_date", "days_pending",
        ):  # fmt: skip
            self.assertIn(key, row)
        self.assertEqual(row["chapter"], self.chapter_a.name)
        self.assertIn(row["days_pending"], (2, 3, 4))  # site tz vs server tz at midnight

    def test_board_member_sees_own_chapter_only(self):
        self._seed()
        with self.as_user(self.board_a.user):
            names = {row["name"] for row in get_pending_applications()}
        self.assertEqual(names & {self.app_a, self.app_a2}, {self.app_a, self.app_a2})
        self.assertFalse(names & {self.app_b, self.app_b2, self.app_none}, names)

    def test_chapter_filter_and_unassigned(self):
        self._seed()
        in_b = {r["name"] for r in get_pending_applications(chapter=self.chapter_b.name)}
        self.assertTrue({self.app_b, self.app_b2} <= in_b)
        self.assertFalse(in_b & {self.app_a, self.app_none})
        unassigned = {r["name"] for r in get_pending_applications(chapter="Unassigned")}
        self.assertIn(self.app_none, unassigned)
        self.assertFalse(unassigned & {self.app_a, self.app_b})

    def test_board_member_cannot_widen_scope_with_a_foreign_chapter_filter(self):
        self._seed()
        with self.as_user(self.board_a.user):
            names = {r["name"] for r in get_pending_applications(chapter=self.chapter_b.name)}
        self.assertFalse(names, "the chapter filter must not bypass the permission query")

    def test_days_overdue_filter(self):
        old = self._application(self.chapter_a.name, days_ago=20)
        recent = self._application(self.chapter_a.name, days_ago=1)
        names = {r["name"] for r in get_pending_applications(days_overdue=10)}
        self.assertIn(old, names)
        self.assertNotIn(recent, names)

    def test_a_user_without_a_seat_sees_nothing(self):
        self._seed()
        with self.as_role("Verenigingen Chapter Board Member"):
            self.assertEqual(get_pending_applications(), [])


class TestDashboardCount(SurfaceCase):
    def _count(self, chapter=None):
        return chapter_dashboard_api.get_pending_applications_count(chapter)["value"]

    def test_count_equals_pending_review_rows_in_the_chapter(self):
        self._seed()
        # A pending Chapter Member row for a Member is not an application: the old count included it.
        member = self.create_test_member(first_name="JoinRequester")
        self.add_member_to_test_chapter(member.name, self.chapter_a.name)
        frappe.db.set_value(
            "Chapter Member", {"parent": self.chapter_a.name, "member": member.name}, "status", "Pending"
        )
        expected = frappe.db.count(SUBMISSION, {"status": "Pending Review", "chapter": self.chapter_a.name})
        self.assertEqual(expected, 2)

        with self.as_user(self.board_a.user):
            self.assertEqual(self._count(self.chapter_a.name), expected)

    def test_board_member_count_excludes_other_chapters(self):
        self._seed()
        with self.as_user(self.board_a.user):
            self.assertEqual(self._count(), 2, "A's two rows, not B's two or the unassigned one")

    def test_a_chapter_the_caller_cannot_see_is_refused(self):
        self._seed()
        with self.as_user(self.board_a.user):
            with self.assertRaises(VerenigingenPermissionError):
                self._count(self.chapter_b.name)

    def test_dashboard_payload_counts_and_lists_applications(self):
        self._seed()
        with self.as_user(self.board_a.user):
            metrics = get_chapter_key_metrics(self.chapter_a.name)
            overview = get_member_overview(self.chapter_a.name)
            actions = get_pending_actions(self.chapter_a.name)
        self.assertEqual(metrics["members"]["pending"], 2)
        listed = {row["application"] for row in overview["pending_applications"]}
        self.assertEqual(listed, {self.app_a, self.app_a2})
        self.assertEqual({r["application"] for r in actions["membership_applications"]}, listed)

    def test_dashboard_payload_never_shows_another_chapters_application(self):
        self._seed()
        with self.as_user(self.board_a.user):
            overview = get_member_overview(self.chapter_b.name)
            metrics = get_chapter_key_metrics(self.chapter_b.name)
        self.assertEqual(overview["pending_applications"], [])
        self.assertEqual(metrics["members"]["pending"], 0)


class TestPendingReport(SurfaceCase):
    def test_report_lists_the_application(self):
        self._seed()
        _columns, data, _msg, _chart, summary = report.execute({})
        names = {row["name"] for row in data}
        self.assertIn(self.app_a, names)
        self.assertNotIn(self.unconfirmed_a, names)
        self.assertTrue(summary)

    def test_report_for_a_board_member_is_scoped(self):
        self._seed()
        with self.as_user(self.board_a.user):
            names = {row["name"] for row in report.execute({})[1]}
        self.assertEqual(names & {self.app_a, self.app_a2}, {self.app_a, self.app_a2})
        self.assertFalse(names & {self.app_b, self.app_b2, self.app_none}, names)

    def test_report_filters(self):
        old = self._application(self.chapter_a.name, days_ago=20)
        recent = self._application(self.chapter_a.name, days_ago=1)
        overdue = {r["name"] for r in report.execute({"overdue_only": 1})[1]}
        self.assertIn(old, overdue)
        self.assertNotIn(recent, overdue)
        in_b = {r["name"] for r in report.execute({"chapter": self.chapter_b.name})[1]}
        self.assertNotIn(old, in_b)


class TestApplicationStats(SurfaceCase):
    def test_stats_count_applications_by_status(self):
        before = get_application_stats()["by_status"].get("Pending Review", 0)
        self._seed()
        stats = get_application_stats()
        self.assertEqual(stats["by_status"].get("Pending Review", 0), before + 5)
        self.assertIn("Approved", stats["by_status"])

    def test_stats_stay_admin_only(self):
        with self.as_user(self.board_a.user):
            with self.assertRaises(frappe.ValidationError):
                get_application_stats()


class TestQuickApproveApplication(ApprovalCase):
    """The dashboard's approve button: approve_application behind the dashboard's own board gate.

    "Chapter Head" is a role NAME get_user_board_role maps to can_approve_members; the board seat
    fixture's default role name is not in that set, so the non-approver tests use the default.
    """

    def setUp(self):
        super().setUp()
        self.board = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Chapter Head"
        )

    def _quick_approve(self, name, user):
        from unittest.mock import patch

        with self.as_user(user):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                return chapter_dashboard_api.quick_approve_application(name)

    def _stable(self, result):
        payload = dict(result)
        payload.pop("timestamp", None)
        payload["meta"] = {k: v for k, v in payload.get("meta", {}).items() if k != "trace_id"}
        return payload

    def _refused(self, result):
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        return not payload.get("success")

    def test_approves_through_approve_application(self):
        name = self._stage_and_confirm()

        result = self._quick_approve(name, self.board.user)

        self.assertTrue(result["success"], result)
        member = frappe.db.get_value(
            "Member", {"email": self.email}, ["name", "status", "application_status"], as_dict=True
        )
        self.assertEqual((member.status, member.application_status), ("Active", "Approved"))
        application = frappe.db.get_value(SUBMISSION, name, ["status", "member"], as_dict=True)
        self.assertEqual((application.status, application.member), ("Approved", member.name))
        self.assertEqual(
            frappe.db.get_value("Chapter Member", {"parent": self.chapter.name, "member": member.name}, "status"),
            "Active",
        )

    def test_foreign_and_unknown_application_are_refused_identically(self):
        other = self.factory.ensure_test_chapter(
            f"Test QA Other {frappe.generate_hash(length=6)}", {"short_name": "QAO", "country": "Netherlands"}
        )
        foreign = self._stage_and_confirm(selected_chapter=other.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        self.expectErrorLog()
        self._quick_approve(unknown, self.board.user)  # warm the permission caches
        foreign_result = self._quick_approve(foreign, self.board.user)
        unknown_result = self._quick_approve(unknown, self.board.user)

        self.assertTrue(self._refused(foreign_result), foreign_result)
        # the per-call timestamp and trace id differ by design; every other channel must not
        self.assertEqual(self._stable(foreign_result), self._stable(unknown_result))
        self.assertEqual(frappe.db.get_value(SUBMISSION, foreign, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)

    def test_board_role_without_can_approve_members_is_refused(self):
        weak = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Test Board Not An Approver"
        )
        name = self._stage_and_confirm()

        self.expectErrorLog()
        result = self._quick_approve(name, weak.user)

        self.assertTrue(self._refused(result), result)
        self.assertIn("permission", str(result).lower())
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)

    def test_staff_may_not_approve_from_the_dashboard(self):
        """Staff may approve on the review page (admin-all scope) but have no board role, so the
        dashboard's own gate keeps this a board action (the safety property of the old
        test_staff_may_not_approve_members, now keyed by application)."""
        from verenigingen.services.chapter.chapter_security import can_user_manage_application_record

        name = self._stage_and_confirm()
        staff_email = f"staff.{frappe.generate_hash(length=6)}@test.invalid"
        with self.as_role("Verenigingen Staff", email=staff_email):
            self.assertTrue(
                can_user_manage_application_record(name),
                "precondition: staff pass approve_application's own check, so only the dashboard gate stops them",
            )
        self.expectErrorLog()
        result = self._quick_approve(name, staff_email)

        self.assertTrue(self._refused(result), result)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")

    def test_plain_member_is_refused_at_the_security_tier(self):
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        name = self._stage_and_confirm()
        plain = self.create_test_user_with_roles(
            email=f"plain.{frappe.generate_hash(length=6)}@example.com", roles=["Verenigingen Member"]
        )
        self.expectErrorLog()
        with self.assertRaises(VPermissionError):
            self._quick_approve(name, plain.email)
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Pending Review")
