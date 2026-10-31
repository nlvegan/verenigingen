"""#1765 task 7: the review surfaces read applications (MAS rows), not Pending Members.

Fixture shortcut, stated: the list-surface tests insert an inert Unconfirmed row and give it a
`chapter`, `confirmed_on` and `set_status("Pending Review")`, the writes application_record makes at
confirmation, instead of driving the emailed-link flow (test_application_record.py covers that). The
surfaces read only those fields. The quick-approve tests drive the real flow (submit, confirm, approve).

Every chapter-scope test seats a real board member in chapter A and puts a REAL application in chapter B
(and one with no chapter), so a surface that ignores the permission query has something to leak.
"""

import json

import frappe
import frappe.handler
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
        payload = dict(result.to_dict() if hasattr(result, "to_dict") else result)
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

    def _probe(self, name):
        """(refusal payload minus per-call ids, new message_log entries, Error Log delta) for a board caller."""
        errors = frappe.db.count("Error Log")
        frappe.clear_messages()
        before = len(frappe.local.message_log)
        result = self._quick_approve(name, self.board.user)
        log = []
        for entry in list(frappe.local.message_log)[before:]:
            entry = json.loads(entry) if isinstance(entry, str) else dict(entry)
            entry.pop("__frappe_exc_id", None)
            log.append(entry)
        return self._stable(result), log, frappe.db.count("Error Log") - errors

    def test_foreign_and_unknown_application_are_refused_identically(self):
        other = self.factory.ensure_test_chapter(
            f"Test QA Other {frappe.generate_hash(length=6)}", {"short_name": "QAO", "country": "Netherlands"}
        )
        foreign = self._stage_and_confirm(selected_chapter=other.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        self.expectErrorLog()
        self._probe(unknown)  # warm the permission caches
        foreign_result = self._probe(foreign)
        unknown_result = self._probe(unknown)

        self.assertFalse(foreign_result[0]["success"], foreign_result)
        # payload (minus the per-call timestamp and trace id), message_log and Error Log delta all match
        self.assertEqual(foreign_result, unknown_result)
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


class TestStaffAndNationalBoardRead(SurfaceCase):
    """Ruling AD: Staff and the National Board role read applications (doctype permissions, not a
    Custom DocPerm), and a caller who may not read gets a refusal, never an empty list or a 0."""

    def _staff_email(self):
        return f"staff.{frappe.generate_hash(length=6)}@test.invalid"

    def test_staff_sees_the_real_rows_and_count(self):
        self._seed()
        with self.as_role("Verenigingen Staff", email=self._staff_email()):
            names = {row["name"] for row in get_pending_applications()}
            count = chapter_dashboard_api.get_pending_applications_count(self.chapter_a.name)["value"]
            overview = get_member_overview(self.chapter_a.name)["pending_applications"]
        self.assertTrue({self.app_a, self.app_a2, self.app_b, self.app_b2, self.app_none} <= names)
        self.assertEqual(count, 2, "staff read the real count, not a swallowed refusal")
        self.assertEqual({r["application"] for r in overview}, {self.app_a, self.app_a2})

    def test_the_national_board_role_alone_reads_every_application(self):
        """The ROLE alone, without the profile's other roles (the profile also carries Chapter Board
        Member, which would read through its own DocPerm and mask a missing one): read through get_list,
        below the endpoint tier gates."""
        self._seed()
        email = self._staff_email()
        self.create_test_user(email, roles=["Verenigingen National Board Member"])
        with self.as_user(email):
            names = set(frappe.get_list(SUBMISSION, pluck="name", limit_page_length=0))
        self.assertTrue({self.app_a, self.app_b, self.app_none} <= names)

    def test_a_caller_who_may_not_read_gets_a_refusal_not_an_empty_list(self):
        self._seed()
        # A Volunteer clears the list endpoint's security tier but holds no MAS read permission.
        with self.as_role("Verenigingen Volunteer", email=self._staff_email()):
            with self.assertRaises(Exception) as caught:
                get_pending_applications()
        self.assertIsInstance(caught.exception, (frappe.PermissionError, VerenigingenPermissionError))

    def test_a_viewer_who_may_not_read_applications_loses_only_that_section(self):
        """The refusal is said in the applications section (and the card shows no number); the rest of the
        dashboard still renders. A 0 or an empty list would read as "nothing pending"; raising would take the
        whole page down (get_context turns any error into 'Error loading dashboard data')."""
        from verenigingen.templates.pages.chapter_dashboard import _chapter_dashboard_payload

        self._seed()
        with self.as_role("Verenigingen Volunteer", email=self._staff_email()):
            payload = _chapter_dashboard_payload(self.chapter_a.name)

        self.assertTrue(payload["pending_actions"]["applications_refusal"])
        self.assertEqual(payload["pending_actions"]["membership_applications"], [])
        self.assertIsNone(payload["key_metrics"]["members"]["pending"], "no number: not a fabricated 0")
        self.assertTrue(payload["key_metrics"]["applications_refusal"])
        self.assertTrue(payload["member_overview"]["applications_refusal"])
        # the rest of the dashboard is there
        for section in ("chapter_info", "key_metrics", "member_overview", "pending_actions", "board_info"):
            self.assertIn(section, payload)
        self.assertIn("active", payload["key_metrics"]["members"])

    def test_a_reader_gets_no_refusal_message(self):
        """Control: a real reader's payload carries the real count and no refusal."""
        from verenigingen.templates.pages.chapter_dashboard import _chapter_dashboard_payload

        self._seed()
        with self.as_user(self.board_a.user):
            payload = _chapter_dashboard_payload(self.chapter_a.name)
        self.assertIsNone(payload["pending_actions"]["applications_refusal"])
        self.assertEqual(payload["key_metrics"]["members"]["pending"], 2)


class TestJoinRequests(SurfaceCase):
    """Ruling AA (#1867): a chapter JOIN request from an existing member is its own dashboard list
    and its own approve action. The request is made through the real Chapter.join_chapter."""

    def setUp(self):
        super().setUp()
        self.head_board = self.create_test_board_member(
            self.chapter_a.name, permissions_level="Admin", role_name="Chapter Head"
        )
        self.requester = self.create_test_member(first_name="JoinRequester")
        self.requester.db_set({"status": "Active", "application_status": "Approved"})
        from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter

        result = join_chapter(
            member_name=self.requester.name, chapter_name=self.chapter_a.name, introduction="join test"
        )
        self.assertTrue(result.get("success"), result)

    def _row(self):
        return frappe.db.get_value(
            "Chapter Member",
            {"parent": self.chapter_a.name, "member": self.requester.name},
            ["status", "enabled"],
            as_dict=True,
        )

    def test_the_real_request_is_a_pending_row_listed_separately(self):
        self.assertEqual((self._row().status, self._row().enabled), ("Pending", 1))
        with self.as_user(self.head_board.user):
            actions = get_pending_actions(self.chapter_a.name)
        self.assertEqual([r["member"] for r in actions["join_requests"]], [self.requester.name])
        self.assertFalse(
            {r["application"] for r in actions["membership_applications"]} & {self.requester.name},
            "a join request is not an application",
        )

    def test_a_legacy_pending_applicant_is_not_listed_as_a_join_request(self):
        """A Pending Member's own Pending Chapter Member row is an application, which this action
        would approve by flipping only the chapter row (the #1765 bug); it must not be offered."""
        applicant = self.create_test_member(first_name="LegacyApplicant")
        applicant.db_set({"status": "Pending", "application_status": "Pending"})
        self.add_member_to_test_chapter(applicant.name, self.chapter_a.name)
        frappe.db.set_value(
            "Chapter Member", {"parent": self.chapter_a.name, "member": applicant.name}, "status", "Pending"
        )
        with self.as_user(self.head_board.user):
            listed = {r["member"] for r in get_pending_actions(self.chapter_a.name)["join_requests"]}
        self.assertIn(self.requester.name, listed)
        self.assertNotIn(applicant.name, listed)

    def test_board_head_approves_the_join_request(self):
        with self.as_user(self.head_board.user):
            self.expectErrorLog()
            result = chapter_dashboard_api.quick_approve_join_request(self.requester.name, self.chapter_a.name)
        self.assertTrue(result.get("success"), result)
        self.assertEqual((self._row().status, self._row().enabled), ("Active", 1))

    def test_board_role_without_can_approve_members_is_refused(self):
        weak = self.create_test_board_member(
            self.chapter_a.name, permissions_level="Admin", role_name="Test Board Not An Approver"
        )
        with self.as_user(weak.user):
            self.expectErrorLog()
            result = chapter_dashboard_api.quick_approve_join_request(self.requester.name, self.chapter_a.name)
        self.assertFalse(result.get("success"), result)
        self.assertEqual(self._row().status, "Pending")
        # The browser shows the reason from `error.message`: `error` is an object, not a string (N1).
        self.assertIsInstance(result["error"], dict)
        self.assertIn("permission", result["error"]["message"].lower())

    def test_a_failed_audit_comment_is_logged_as_an_error_log_row(self):
        """The audit comment is best-effort, but its failure goes to the Error Log (frappe.logger() writes
        nothing anyone reads). Mock justified: the secure-operation boundary cannot be made to fail for a
        board user on demand."""
        from unittest.mock import patch

        title = "Chapter Dashboard approval audit comment failed"
        before = frappe.db.count("Error Log", {"method": title})
        failed = frappe._dict(success=False, errors=["no comment permission"])
        with self.as_user(self.head_board.user):
            self.expectErrorLog()
            with patch("verenigingen.utils.secure_operations.secure_document_operation", return_value=failed):
                result = chapter_dashboard_api.quick_approve_join_request(
                    self.requester.name, self.chapter_a.name
                )
        self.assertTrue(result.get("success"), "the approval is not blocked by its audit comment")
        self.assertEqual(frappe.db.count("Error Log", {"method": title}), before + 1)

    def test_a_member_of_another_chapter_cannot_approve_it(self):
        other_board = self.create_test_board_member(
            self.chapter_b.name, permissions_level="Admin", role_name="Chapter Head"
        )
        with self.as_user(other_board.user):
            self.expectErrorLog()
            result = chapter_dashboard_api.quick_approve_join_request(self.requester.name, self.chapter_a.name)
        self.assertFalse(result.get("success"), result)
        self.assertEqual(self._row().status, "Pending")


class TestDashboardWiring(EnhancedTestCase):
    """Rulings AE: the dashboard's Review link opens the review page focused on the application and
    its Approve button calls quick_approve_application. Source check: the dashboard is a website
    page whose buttons no Python test can click."""

    def _read(self, relative):
        import os

        with open(os.path.join(frappe.get_app_path("verenigingen"), relative)) as handle:
            return handle.read()

    def test_review_link_opens_the_review_page_focused_on_the_application(self):
        template = self._read("templates/pages/chapter_dashboard.html")
        script = self._read("public/js/chapter_dashboard.js")
        self.assertIn("/app/membership-application-review?application=", template)
        self.assertIn("/app/membership-application-review?application=", script)
        self.assertNotIn("/app/membership-application-submission/", template + script)

    def test_the_dialog_reads_the_payload_where_standard_api_puts_it(self):
        self.assertIn("result?.message?.data", self._read(
            "verenigingen/page/membership_application_review/membership_application_review.js"
        ))
        script = self._read("public/js/chapter_dashboard.js")
        self.assertIn("function refusalText(", script)
        self.assertIn("metrics.members.pending ?? '--'", script, "the refresh keeps the server-rendered '--'")
        self.assertNotIn("r.message.error || r.message.message", script)

    def test_staff_may_open_the_review_page(self):
        import json
        import os

        path = os.path.join(
            frappe.get_app_path("verenigingen"),
            "verenigingen/page/membership_application_review/membership_application_review.json",
        )
        with open(path) as handle:
            roles = {row["role"] for row in json.load(handle)["roles"]}
        self.assertIn("Verenigingen Staff", roles)

    # Expressions in chapter_dashboard.html that may print without `|e`. Everything else must end in `|e`
    # (or `|urlencode|e`). Each entry says why it is safe; add to it only with a reason.
    _NUMERIC = {
        # integer counts and sums computed server-side
        "year", "overdue_count", "doc_count.total", "documents|length",
        'expenses.pending_count if expenses_ok else "--"',
        "dashboard_data.board_documents.total_count",
        "dashboard_data.key_metrics.members.new_this_month",
        "dashboard_data.key_metrics.members.pending",  # an int; None is guarded by the {% if %} around it
        "dashboard_data.member_overview.recent_members|length",
        "dashboard_data.pending_actions.expense_approvals|length",
        "dashboard_data.pending_actions.join_requests|length",
        "dashboard_data.pending_actions.total_pending if dashboard_data and dashboard_data.pending_actions else 0",
        "dashboard_data.key_metrics.members.active if dashboard_data and dashboard_data.key_metrics and dashboard_data.key_metrics.members else 0",
        "dashboard_data.financial_summary.ytd.total_claims if dashboard_data.financial_summary.ytd else 0",
        "dashboard_data.dues_payment_status.all_outstanding if dashboard_data.dues_payment_status else 0",
    }  # fmt: skip
    _SAFE_PATTERNS = (
        (r"_\((\"[^\"]*\"|'[^']*')\)", "a literal translation string from our own source"),
        (r"_\(\"[^\"]*\{0\}[^\"]*\"\)\.format\(\w+\.days_pending\)", "literal + an integer day count"),
        (r"\"[^\"]*\"\|format\(.*", "a %-formatted number (money)"),
        (r"dashboard_data\.(dues_payment_status|financial_summary)\.[\w.]+", "numeric dues/financial summary field"),
        (r"dashboard_data\.pending_actions\.membership_applications\|length.*", "an integer count"),
        (r"(format_date|format_datetime)\(.*", "a formatted date"),
        (r"date_val(\.strftime\(format\))?", "a date value inside the date macros"),
        (r".*\|\s*tojson(\s*\|\s*safe)?.*", "tojson escapes < > & ' for a <script> context"),
        (r"brand_css\(\)", "deliberate HTML: our own macro"),
        (r"dashboard_data\.board_documents\.category_icons\.get\(.*", "deliberate HTML: icon markup from a server constant"),
        (r"'bg-[\w -]+' if [\w.]+ else 'bg-[\w -]+'", "constant CSS class names"),
    )  # fmt: skip

    def test_every_expression_in_the_dashboard_template_is_escaped_or_allowlisted(self):
        """Jinja autoescape is OFF in Frappe's environment (measured below), so a name printed without `|e` is
        stored XSS from guest input (the application form). The scan reads EVERY `{{ }}` in the template, not
        a list of field names: an expression passes only if it ends in `|e` / `|urlencode|e`, or matches the
        reasoned allowlist above."""
        import re

        probe = frappe.render_template("{{ x }}", {"x": "<b>&"})
        self.assertEqual(probe, "<b>&", "premise: autoescape is off, so escaping must be explicit")

        template = self._read("templates/pages/chapter_dashboard.html")
        expressions = [e.strip() for e in re.findall(r"\{\{(.*?)\}\}", template, re.S)]
        self.assertGreater(len(expressions), 100, "the scan must find the template's expressions")

        def allowed(expression):
            if expression.endswith("|e") or expression.endswith("|urlencode|e"):
                return True
            if expression in self._NUMERIC:
                return True
            return any(re.fullmatch(pattern, expression, re.S) for pattern, _why in self._SAFE_PATTERNS)

        self.assertEqual([e for e in expressions if not allowed(e)], [])

    def test_approve_buttons_are_wired_to_the_application_and_join_endpoints(self):
        template = self._read("templates/pages/chapter_dashboard.html")
        script = self._read("public/js/chapter_dashboard.js")
        self.assertIn("approveApplication(", template)
        self.assertIn("approveJoinRequest(", template)
        self.assertIn("chapter_dashboard_api.quick_approve_application", script)
        self.assertIn("chapter_dashboard_api.quick_approve_join_request", script)


class TestDuplicateWarning(ApprovalCase):
    """Ruling AB (#1870): the approve dialog's duplicate warning is fed by the APPLICATION's own name,
    email, birth date and IBAN (no Member exists yet)."""

    def _check(self, name, user=None):
        from verenigingen.services.member.validation.member_duplicate_detection_service import (
            check_duplicate_for_application,
        )

        with self.as_user(user or self.admin_user.email):
            return check_duplicate_for_application(name)

    def test_a_lookalike_member_is_reported_and_an_exact_email_match_is_not(self):
        birth_date = add_days(frappe.utils.today(), -365 * 31)
        first, last = "Dupe", f"Lookalike{frappe.generate_hash(length=6)}"
        lookalike = self.create_test_member(
            first_name=first, last_name=last, birth_date=birth_date,
            email=f"lookalike.{frappe.generate_hash(length=6)}@example.org",
        )  # fmt: skip
        name = self._stage_and_confirm(first_name=first, last_name=last, birth_date=birth_date)

        result = self._check(name)
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        data = payload.get("data", payload)
        matched = {m["member_name"] for m in data["duplicates"]}

        self.assertTrue(data["has_duplicates"], payload)
        self.assertIn(lookalike.name, matched)

    def test_the_response_has_the_shape_the_dialog_reads(self):
        """Dispatched the way the browser does it (frappe.handler.execute_cmd), because @standard_api
        serialises the OperationResult under `data` and a direct call hides that: the dialog read
        `message.has_duplicates` and so never showed the warning."""
        birth_date = add_days(frappe.utils.today(), -365 * 31)
        first, last = "Shape", f"Lookalike{frappe.generate_hash(length=6)}"
        self.create_test_member(
            first_name=first, last_name=last, birth_date=birth_date,
            email=f"shape.{frappe.generate_hash(length=6)}@example.org",
        )  # fmt: skip
        name = self._stage_and_confirm(first_name=first, last_name=last, birth_date=birth_date)
        cmd = "verenigingen.services.member.validation.member_duplicate_detection_service.check_duplicate_for_application"

        self._request_from_fresh_ip("POST")
        with self.as_user(self.admin_user.email):
            frappe.local.form_dict = frappe._dict(cmd=cmd, application_name=name)  # after set_user resets it
            message = frappe.handler.execute_cmd(cmd)  # what the browser receives as `r.message`

        self.assertNotIn("has_duplicates", message, "not at the top level, where the old dialog looked")
        self.assertTrue(message["data"]["has_duplicates"], message)
        self.assertTrue(message["data"]["summary"]["medium"] + message["data"]["summary"]["high"])

    def test_matches_the_caller_cannot_read_are_counted_never_described(self):
        """O2: a board member of the application's chapter sees a lookalike in ANOTHER chapter only as
        'a possible duplicate exists': no name, email or birth date. The control: the same lookalike in the
        caller's own chapter is described."""
        other = self.factory.ensure_test_chapter(
            f"Test Dup Hidden {frappe.generate_hash(length=6)}", {"short_name": "DUH", "country": "Netherlands"}
        )
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        birth_date = add_days(frappe.utils.today(), -365 * 33)
        first, last = "Hidden", f"Lookalike{frappe.generate_hash(length=6)}"
        hidden_email = f"hidden.{frappe.generate_hash(length=6)}@example.org"
        hidden = self.create_test_member(
            first_name=first, last_name=last, birth_date=birth_date, email=hidden_email
        )
        self.add_member_to_test_chapter(hidden.name, other.name)
        name = self._stage_and_confirm(first_name=first, last_name=last, birth_date=birth_date)

        with self.as_user(board.user):
            self.assertFalse(
                frappe.has_permission("Member", "read", doc=hidden.name),
                "precondition: the lookalike is in a chapter the caller cannot read",
            )
            payload = self._check(name, board.user)
        payload = payload.to_dict() if hasattr(payload, "to_dict") else payload
        data = payload.get("data", payload)

        self.assertTrue(data["has_duplicates"])
        self.assertEqual(data["restricted_count"], 1)
        self.assertEqual(data["duplicates"], [])
        leaked = json.dumps(payload, default=str)
        for secret in (hidden.name, hidden_email, str(birth_date), last):
            self.assertNotIn(secret, leaked)

    def test_a_readable_match_is_still_described(self):
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        birth_date = add_days(frappe.utils.today(), -365 * 34)
        first, last = "Visible", f"Lookalike{frappe.generate_hash(length=6)}"
        visible = self.create_test_member(
            first_name=first, last_name=last, birth_date=birth_date,
            email=f"visible.{frappe.generate_hash(length=6)}@example.org",
        )  # fmt: skip
        self.add_member_to_test_chapter(visible.name, self.chapter.name)
        name = self._stage_and_confirm(first_name=first, last_name=last, birth_date=birth_date)

        payload = self._check(name, board.user)
        payload = payload.to_dict() if hasattr(payload, "to_dict") else payload
        data = payload.get("data", payload)

        self.assertEqual(data["restricted_count"], 0)
        self.assertIn(visible.name, {m["member_name"] for m in data["duplicates"]})

    def test_the_applicants_own_member_is_not_a_duplicate_of_itself(self):
        existing = self.create_test_member(first_name="Same", last_name="Person", email=self.email)
        name = self._stage_and_confirm(first_name="Same", last_name="Person")

        data = self._check(name)
        data = data.to_dict() if hasattr(data, "to_dict") else data
        data = data.get("data", data)

        self.assertNotIn(existing.name, {m["member_name"] for m in data["duplicates"]})

    def test_unknown_and_foreign_applications_are_refused_identically(self):
        other = self.factory.ensure_test_chapter(
            f"Test Dup Other {frappe.generate_hash(length=6)}", {"short_name": "DUO", "country": "Netherlands"}
        )
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        foreign = self._stage_and_confirm(selected_chapter=other.name)
        unknown = f"nonexistent-{frappe.generate_hash(length=8)}"

        outcomes = []
        for name in (unknown, foreign, unknown):  # the first call warms the caches
            with self.assertRaises(frappe.PermissionError) as caught:
                self._check(name, board.user)
            outcomes.append(str(caught.exception))
        self.assertEqual(outcomes[1], outcomes[2])


class TestReportOrder(SurfaceCase):
    def test_report_lists_the_oldest_application_first(self):
        newest = self._application(self.chapter_a.name, days_ago=1)
        oldest = self._application(self.chapter_a.name, days_ago=20)
        middle = self._application(self.chapter_a.name, days_ago=9)
        names = [row["name"] for row in report.execute({"chapter": self.chapter_a.name})[1]]
        self.assertEqual(names, [oldest, middle, newest])
