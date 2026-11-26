"""An INACTIVE Chapter Role confers nothing on the chapter dashboard (#3315, class #3183/#2958).

``get_user_board_chapters`` is the chapter gate of the dashboard endpoints (and the dashboard and
skills pages). It used to filter only ``Chapter Board Member.is_active``, so a board member whose seat
sits on a deactivated Chapter Role still read the chapter's member emails.

Every case dispatches through ``frappe.handler.execute_cmd`` with a real werkzeug POST and
``frappe.flags.in_test = False``, as the web server does. Callers are real board members seated through
``create_test_board_member`` (Verenigingen Chapter Board Member profile, which clears the HIGH tier, no
blanket doctype access), so the chapter gate is what decides. The role is deactivated through a real
Chapter Role save (the Desk path), not a ``db.set_value`` shortcut.
"""

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.services.chapter.chapter_permission_service import get_user_board_chapters
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

EMAILS_CMD = "verenigingen.api.chapter_dashboard_api.get_chapter_member_emails"
COUNT_CMD = "verenigingen.api.chapter_dashboard_api.get_active_members_count"


class TestDashboardInactiveRole3315(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=6)
        self.chapter_a = self.create_test_chapter(chapter_name=f"TEST 3315 A {run}")
        self.chapter_b = self.create_test_chapter(chapter_name=f"TEST 3315 B {run}")
        # Tokenized role names: the fixture's default role row is shared across tests and we deactivate ours.
        self.live = self.create_test_board_member(
            self.chapter_a.name, role_name=f"Seat 3315 live {run}", first_name="Live"
        )
        self.dead = self.create_test_board_member(
            self.chapter_a.name, role_name=f"Seat 3315 dead {run}", first_name="Dead"
        )
        # Another chapter's board member: the baseline "forbidden" caller whose refusal we must match.
        self.other = self.create_test_board_member(
            self.chapter_b.name, role_name=f"Seat 3315 other {run}", first_name="Other"
        )
        for who in (self.live, self.dead):
            self.add_member_to_test_chapter(who.member, self.chapter_a.name)

    def _deactivate_role(self, role_name):
        role = frappe.get_doc("Chapter Role", role_name)
        role.is_active = 0
        with self.as_user("Administrator"):
            role.save()
        self.assertEqual(frappe.db.get_value("Chapter Role", role_name, "is_active"), 0)
        # Deactivating the role resyncs its holders' role profiles, which can drop the board profile
        # and with it the HIGH tier: the call would then be refused by the TIER gate, a refusal for
        # the wrong reason. Hand the profile back so the chapter gate is the only thing under test.
        # Probe shortcut: this models a holder who still clears HIGH (stale profile, second profile).
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        for user in frappe.get_all("User", filters={"name": ["in", [self.dead.user, self.live.user]]}, pluck="name"):
            assign_role_profile_to_user(user, "Verenigingen Chapter Board Member")

    def _dispatch_3315(self, user, cmd, args):
        """Real dispatch. Returns (outcome, message_log_delta, error_log_delta, http_status)."""
        env = EnvironBuilder(path=f"/api/method/{cmd}", data=args, method="POST").get_environ()
        original, in_test = frappe.session.user, frappe.flags.in_test
        frappe.set_user(user)
        frappe.flags.in_test = False
        # Mock justified: Infrastructure - the request context the web server sets before execute_cmd.
        frappe.local.request = Request(env)
        frappe.local.form_dict = frappe._dict(args)
        frappe.local.response = frappe._dict()
        # Mock justified: Infrastructure - empty request-local log so the delta is this call's.
        frappe.local.message_log = []
        errors_before = frappe.db.count("Error Log")
        try:
            try:
                outcome = ("ok", frappe.handler.execute_cmd(cmd))
            except Exception as exc:
                outcome = (type(exc).__name__, str(exc))
            return (
                outcome,
                list(frappe.local.message_log),
                frappe.db.count("Error Log") - errors_before,
                frappe.local.response.get("http_status_code"),
            )
        finally:
            # Mock justified: Infrastructure - restore the test-mode flag turned off for dispatch.
            frappe.flags.in_test = in_test
            frappe.set_user(original)

    def _emails_for(self, who):
        return self._dispatch_3315(who.user, EMAILS_CMD, {"chapter_name": self.chapter_a.name})

    @staticmethod
    def _without_per_call_noise(result):
        """Drop the envelope's timestamp and trace_id, which differ on every call by design."""
        (kind, payload), *rest = result
        if isinstance(payload, dict) and payload.get("success") is False:
            payload = {k: v for k, v in payload.items() if k not in ("timestamp", "meta")}
        return ((kind, payload), *rest)

    def test_active_role_board_member_is_admitted(self):
        """Control: the same call by a live-role seat returns the chapter's emails (a real row exists)."""
        (kind, payload), *_ = self._emails_for(self.live)
        self.assertEqual(kind, "ok", f"live-role board member was refused: {payload}")
        self.assertIn(frappe.db.get_value("Member", self.live.member, "email"), payload)

    def test_inactive_role_board_member_is_refused_like_a_forbidden_caller(self):
        self._deactivate_role(self.dead.chapter_role)
        forbidden = self._emails_for(self.other)
        refused = self._emails_for(self.dead)
        (kind, message), *_ = forbidden
        self.assertFalse(isinstance(message, list), f"baseline forbidden caller must be refused: {forbidden}")
        self.assertEqual(
            self._without_per_call_noise(refused),
            self._without_per_call_noise(forbidden),
            "inactive-role refusal differs from the existing refusal",
        )
        self.assertEqual(refused[2], forbidden[2], "Error Log row count differs")

    def test_inactive_role_loses_the_other_dashboard_readers_too(self):
        """get_active_members_count(chapter=...) shares the gate through _dashboard_chapter_scope."""
        args = {"chapter": self.chapter_a.name}
        self.assertEqual(self._dispatch_3315(self.dead.user, COUNT_CMD, args)[0][0], "ok")
        self._deactivate_role(self.dead.chapter_role)
        self.assertEqual(
            self._dispatch_3315(self.dead.user, COUNT_CMD, args),
            self._dispatch_3315(self.other.user, COUNT_CMD, args),
        )
        self.assertEqual(self._dispatch_3315(self.live.user, COUNT_CMD, args)[0][0], "ok")

    def test_one_inactive_seat_does_not_hide_a_live_seat(self):
        """Control with two seats for one volunteer: only the live-role chapter stays."""
        self._deactivate_role(self.dead.chapter_role)
        live_role = frappe.get_doc("Chapter Role", self.live.chapter_role)
        chapter_b = frappe.get_doc("Chapter", self.chapter_b.name)
        chapter_b.append(
            "board_members",
            {
                "volunteer": self.dead.volunteer,
                "chapter_role": live_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        with self.as_user("Administrator"):
            chapter_b.save()
        with self.as_user(self.dead.user):
            names = {row["chapter_name"] for row in get_user_board_chapters()}
        self.assertEqual(names, {self.chapter_b.name})

    def test_manageable_chapters_gate_follows(self):
        from verenigingen.services.chapter.chapter_security import get_user_manageable_chapters

        self.assertEqual(get_user_manageable_chapters(self.dead.user), [self.chapter_a.name])
        self._deactivate_role(self.dead.chapter_role)
        self.assertEqual(get_user_manageable_chapters(self.dead.user), [])
        self.assertEqual(get_user_manageable_chapters(self.live.user), [self.chapter_a.name])
