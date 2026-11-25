"""#3286: who may approve a Membership Termination Request.

Maintainer ruling (2026-11-25): chapter board members (for members of their OWN chapter),
national board members, and staff and up (Verenigingen Staff, Verenigingen Administrator,
System Manager). TerminationApprovalService.APPROVAL_ROLES named "Board Member" and
"Chapter Administrator", neither of which is a Role, and the whitelisted approve_request was
critical_api (CRITICAL tier), which no board or plain Staff profile clears.

Every case is the real flow: a real werkzeug POST through frappe.handler.execute_cmd
(``run_doc_method``), first ``submit_for_approval`` as an administrator, then
``approve_request`` as the caller under test, with ``frappe.flags.in_test = False`` so the
security wrapper is not short-circuited. Callers are real users with real Role Profiles and
real board seats (create_test_board_member); the member sits in chapter A through a real
Chapter Member row.

Probe shortcut, stated: the national-board user is a chapter-B seat holder that is then
given the "Verenigingen National Board Member" profile (assign_role_profile_to_user), the
call the role-profile sync makes for a seat on the national chapter, rather than a seat on
the configured national chapter.

Layers: a board member of ANOTHER chapter is already refused earlier, by the doctype's
controller permission check (run_doc_method loads the doc with check_permission=True); the
service-level test below is what pins the scope check of validate_approver_permissions
itself, for internal and queued callers that never pass through run_doc_method.
"""

import json

import frappe
from frappe.utils import today
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.services.approval import TerminationApprovalService
from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.utils.constants import Roles

DT = "Membership Termination Request"
UNKNOWN_REQUEST = "MTR-DOES-NOT-EXIST-3286"


class TestTerminationApproverRoles3286(MemberOwnershipProbeMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.chapter_a = self.create_test_chapter()
        self.chapter_b = self.create_test_chapter()
        self.member = self.create_test_member(first_name="Term", last_name="Target3286", status="Active")
        self.add_member_to_test_chapter(self.member.name, self.chapter_a.name)

        self.own_board = self.create_test_board_member(self.chapter_a.name).user
        self.other_board = self.create_test_board_member(self.chapter_b.name).user
        self.national = self.create_test_board_member(self.chapter_b.name).user
        assign_role_profile_to_user(self.national, "Verenigingen National Board Member")
        self.staff = self._staff_user("Staff3286", role=Roles.VERENIGINGEN_STAFF)
        self.admin = self._staff_user("Admin3286")
        self.plain_member = self._plain_member_linked_user("Plain3286")[0]
        self.volunteer = self._volunteer_without_seat_3286()

    # --- fixtures -----------------------------------------------------------

    def _volunteer_without_seat_3286(self):
        email, member = self._user_linked_to_own_member(
            "Vol3286", "Verenigingen Volunteer", "Verenigingen Volunteer"
        )
        self.create_test_volunteer(member_name=member.name)
        return email

    def _pending_request_3286(self, member=None):
        """A disciplinary request, created and submitted by the admin (the real submit path)."""
        with self.set_user(self.admin):
            doc = self._insert_request_3286(member)
        self.factory.track_document(DT, doc.name, priority=3)
        result = self._dispatch_3286(self.admin, doc.name, "submit_for_approval", {})
        self.assertEqual(result["outcome"], ("ok", ""), msg=result)
        self.assertEqual(frappe.db.get_value(DT, doc.name, "status"), "Pending")
        return doc.name

    def _insert_request_3286(self, member):
        return frappe.get_doc(
            {
                "doctype": DT,
                "member": (member or self.member).name,
                "termination_type": "Policy Violation",
                "termination_reason": "test",
                "disciplinary_documentation": "documented",
                "requested_by": self.admin,
                "request_date": today(),
                "secondary_approver": self.admin,
            }
        ).insert()

    def _dispatch_3286(self, user, name, method, args):
        """Real dispatch; returns every observable channel."""
        form = {"dt": DT, "dn": name, "method": method}
        if args:
            form["args"] = json.dumps(args)
        env = EnvironBuilder(path="/api/method/run_doc_method", data=form, method="POST").get_environ()
        original, in_test = frappe.session.user, frappe.flags.in_test
        frappe.set_user(user)
        frappe.flags.in_test = False
        # Mock justified: Infrastructure - the request context the web server sets before execute_cmd
        frappe.local.request = Request(env)
        # Mock justified: Infrastructure - request-local form the web server sets before execute_cmd
        frappe.local.form_dict = frappe._dict(form)
        frappe.local.response = frappe._dict(docs=[])
        frappe.local.message_log = []
        errors_before = frappe.db.count("Error Log")
        try:
            try:
                frappe.handler.execute_cmd("run_doc_method")
                outcome = ("ok", "")
            except Exception as exc:  # noqa: BLE001 - the exception class IS the observation
                outcome = (type(exc).__name__, str(exc))
            return {
                "outcome": outcome,
                "messages": [str(m) for m in frappe.local.message_log],
                "errors": frappe.db.count("Error Log") - errors_before,
                "http": frappe.local.response.get("http_status_code"),
            }
        finally:
            # Mock justified: Infrastructure - restore the test-mode flag turned off for dispatch
            frappe.flags.in_test = in_test
            frappe.set_user(original)

    def _approve_3286(self, user, name, decision="approved"):
        return self._dispatch_3286(user, name, "approve_request", {"decision": decision, "notes": "n"})

    def _status_3286(self, name):
        return frappe.db.get_value(DT, name, ["status", "approved_by"], as_dict=True)

    def _assert_allowed_3286(self, user, label, decision="approved"):
        name = self._pending_request_3286()
        result = self._approve_3286(user, name, decision)
        self.assertEqual(result["outcome"], ("ok", ""), msg=f"{label}: {result}")
        state = self._status_3286(name)
        self.assertEqual(state.status, "Approved" if decision == "approved" else "Rejected", msg=label)
        self.assertEqual(state.approved_by, user, msg=label)

    def _assert_refused_3286(self, user, label, name=None):
        name = name or self._pending_request_3286()
        result = self._approve_3286(user, name)
        self.assertEqual(result["outcome"][0], "PermissionError", msg=f"{label}: {result}")
        state = self._status_3286(name)
        self.assertEqual(state.status, "Pending", msg=f"{label}: state changed")
        self.assertFalse(state.approved_by, msg=f"{label}: approver recorded")
        return result

    # --- the allowed set -----------------------------------------------------

    def test_board_member_of_the_members_own_chapter_may_approve(self):
        self._assert_allowed_3286(self.own_board, "own chapter board")

    def test_board_member_of_the_members_own_chapter_may_reject(self):
        self._assert_allowed_3286(self.own_board, "own chapter board (reject)", "rejected")

    def test_national_board_member_may_approve_any_member(self):
        self._assert_allowed_3286(self.national, "national board")

    def test_staff_may_approve(self):
        self._assert_allowed_3286(self.staff, "staff")

    def test_administrator_may_approve(self):
        self._assert_allowed_3286(self.admin, "administrator")

    # --- the refused set (state must not change) ----------------------------------

    def test_board_member_of_a_different_chapter_is_refused(self):
        self._assert_refused_3286(self.other_board, "other chapter board")

    def test_plain_member_is_refused(self):
        self._assert_refused_3286(self.plain_member, "plain member")

    def test_volunteer_without_a_board_seat_is_refused(self):
        self._assert_refused_3286(self.volunteer, "volunteer, no seat")

    def test_refused_caller_cannot_reject_either(self):
        name = self._pending_request_3286()
        result = self._approve_3286(self.other_board, name, "rejected")
        self.assertEqual(result["outcome"][0], "PermissionError", msg=result)
        self.assertEqual(self._status_3286(name).status, "Pending")

    def test_service_call_refuses_a_wrong_chapter_board_member(self):
        """The service itself refuses, not only the whitelisted wrapper (background / internal callers)."""
        name = self._pending_request_3286()
        with self.set_user(self.other_board):
            request = frappe.get_doc(DT, name)
            with self.assertRaises(frappe.ValidationError):
                TerminationApprovalService(request).approve_request("approved", "n")
        self.assertEqual(self._status_3286(name).status, "Pending")

    def test_service_accepts_the_national_board_role_on_its_own(self):
        """A user holding the National Board Member role (and no staff role) validates for any
        member. A real National profile also carries Staff, so only the service call isolates the
        role's own entry in the approver set."""
        user = self.create_test_user(
            f"natonly-3286-{frappe.generate_hash(length=6)}@example.org", roles=[Roles.NATIONAL_BOARD_MEMBER]
        ).name
        self.assertFalse(set(frappe.get_roles(user)) & Roles.ADMIN_ROLES)
        TerminationApprovalService().validate_approver_permissions(user, self.member.name)

    def test_service_refuses_a_chapter_board_user_without_a_member_context(self):
        """Scoped roles fail closed when no member is known."""
        with self.assertRaises(frappe.ValidationError):
            TerminationApprovalService().validate_approver_permissions(self.own_board)
        TerminationApprovalService().validate_approver_permissions(self.own_board, self.member.name)

    def test_the_approver_roles_are_real_roles(self):
        """The dead names ('Board Member', 'Chapter Administrator') are gone: every entry exists."""
        for role in TerminationApprovalService.APPROVAL_ROLES:
            self.assertTrue(frappe.db.exists("Role", role), msg=f"{role} is not a Role")

    # --- existence oracle -----------------------------------------------------------

    def test_refusal_does_not_depend_on_the_callers_chapter_for_an_unknown_request(self):
        """Control for the oracle comparison: what a forbidden caller sees for a REAL request and for
        an UNKNOWN one. Recorded, not equalised: a Frappe doc-method call loads the doc before any
        app code runs, so a missing name answers DoesNotExistError for every caller (framework
        behaviour, outside this change). What must hold is that the forbidden answer for a real
        request carries no request data and leaves no Error Log row."""
        name = self._pending_request_3286()
        for user in (self.other_board, self.plain_member, self.volunteer):
            with self.subTest(user=user):
                forbidden = self._approve_3286(user, name)
                self.assertEqual(forbidden["outcome"][0], "PermissionError", msg=forbidden)
                self.assertNotIn(self.member.name, str(forbidden))
                self.assertEqual(forbidden["errors"], 0, msg=forbidden)
                self.assertEqual(
                    forbidden["outcome"],
                    self._approve_3286(user, name)["outcome"],
                    "refusal text must be stable across repeats",
                )
