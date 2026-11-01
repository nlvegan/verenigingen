"""#1911: the suspension API let any caller who cleared the endpoint's security tier
read, or probe the existence of, ANY member.

- get_suspension_preview (@high_security_api) returned a member's status, linked user
  email, teams and memberships with no member-level check; "Verenigingen Chapter Board
  Member" clears HIGH on its own, so a board member of chapter B could read a member of
  chapter A.
- suspend_member / unsuspend_member / can_suspend_member / bulk_suspend_members checked
  existence BEFORE permission (or let the failed Member load queue a "not found" message),
  so an unknown name and a forbidden name answered differently.

Callers: the least-privileged real ones -- a board member seated on ANOTHER chapter
(refused) and a board member seated on the member's OWN chapter (allowed), plus an
administrator. Seats are built through create_test_board_member (real Volunteer + Chapter
Board Member + role profile), and the member is placed in its chapter with
add_member_to_test_chapter (a real Chapter Member row, no db.set_value shortcut).
"""

import frappe

from verenigingen.api import suspension_api
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin

UNKNOWN = "Member-DOES-NOT-EXIST-1911"


class TestSuspensionApiMemberScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter_a = self.create_test_chapter()
        self.chapter_b = self.create_test_chapter()
        self.member = self.create_test_member(
            first_name="Scope", last_name="Target1911", status="Active"
        )
        self.add_member_to_test_chapter(self.member.name, self.chapter_a.name)
        self.own_board = self.create_test_board_member(self.chapter_a.name)
        self.other_board = self.create_test_board_member(self.chapter_b.name)
        self.admin = self._staff_user("Scope1911Admin")
        # suspend/unsuspend/bulk are CRITICAL-tier. A board member only clears HIGH, so the
        # least-privileged real caller that reaches those bodies is a Treasurer profile
        # seated on ANOTHER chapter (no ADMIN_PAIR role, so can_terminate_member is not
        # short-circuited to True).
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        self.treasurer = self.create_test_board_member(self.chapter_b.name).user
        self.national = self.create_test_board_member(self.chapter_b.name).user
        assign_role_profile_to_user(self.national, "Verenigingen National Board Member")
        assign_role_profile_to_user(self.treasurer, "Verenigingen Treasurer")

    def _observe_channels_1911(self, call):
        """Run call() and capture every observable channel."""
        log_len = len(frappe.message_log)
        errors_before = frappe.db.count("Error Log")
        try:
            outcome = call()
        except Exception as e:  # noqa: BLE001 - the exception class IS the observation
            outcome = ("raised", type(e).__name__, str(e))
        msgs = [str(m) for m in frappe.message_log[log_len:]]
        del frappe.message_log[log_len:]
        return {
            "outcome": outcome,
            "messages": msgs,
            "errors": frappe.db.count("Error Log") - errors_before,
        }

    def _normalise_probe_1911(self, channels, name):
        """The member name is the caller's own input and may echo; timestamps/exc ids vary per call."""
        import re

        text = re.sub(r"'timestamp': '[^']*'", "'timestamp': <T>", str(channels))
        text = re.sub(r"'__frappe_exc_id': '[^']*'", "'__frappe_exc_id': <ID>", text)
        return text.replace(name, "<NAME>")

    # --- get_suspension_preview ------------------------------------------

    def test_preview_refused_for_board_member_of_another_chapter(self):
        with self.set_user(self.other_board.user):
            self.assertFalse(frappe.has_permission("Member", "read", self.member.name))
            result = suspension_api.get_suspension_preview(member_name=self.member.name)
        self.assertFalse(result["success"], msg=result)
        self.assertNotIn("member_status", str(result))
        self.assertNotIn("user_email", str(result))

    def test_preview_allowed_for_board_member_of_own_chapter(self):
        with self.set_user(self.own_board.user):
            self.assertTrue(frappe.has_permission("Member", "read", self.member.name))
            result = suspension_api.get_suspension_preview(member_name=self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["member_status"], "Active")

    def test_preview_allowed_for_admin(self):
        with self.set_user(self.admin):
            result = suspension_api.get_suspension_preview(member_name=self.member.name)
        self.assertTrue(result["success"], msg=result)

    def test_preview_unknown_and_forbidden_are_indistinguishable(self):
        self.expectErrorLog("Suspension API Error")
        with self.set_user(self.other_board.user):
            forbidden = self._observe_channels_1911(
                lambda: suspension_api.get_suspension_preview(member_name=self.member.name)
            )
            unknown = self._observe_channels_1911(lambda: suspension_api.get_suspension_preview(member_name=UNKNOWN))
        self.assertFalse(forbidden["outcome"]["success"], msg=forbidden)
        self.assertEqual(
            self._normalise_probe_1911(forbidden, self.member.name), self._normalise_probe_1911(unknown, UNKNOWN)
        )

    # --- suspend / unsuspend / can_suspend / bulk -------------------------

    def test_suspend_unknown_and_forbidden_are_indistinguishable(self):
        self.expectErrorLog("Suspension API Permission Error")
        self.expectErrorLog("Suspension API Validation Error")
        with self.set_user(self.treasurer):
            forbidden = self._observe_channels_1911(
                lambda: suspension_api.suspend_member(self.member.name, "scope test")
            )
            unknown = self._observe_channels_1911(lambda: suspension_api.suspend_member(UNKNOWN, "scope test"))
        self.assertFalse(forbidden["outcome"]["success"], msg=forbidden)
        self.assertEqual(forbidden["outcome"]["error"]["code"], "PERMISSION_DENIED")
        self.assertEqual(
            self._normalise_probe_1911(forbidden, self.member.name), self._normalise_probe_1911(unknown, UNKNOWN)
        )
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Active")

    def test_unsuspend_unknown_and_forbidden_are_indistinguishable(self):
        self.expectErrorLog("Suspension API Permission Error")
        self.expectErrorLog("Suspension API Validation Error")
        with self.set_user(self.treasurer):
            forbidden = self._observe_channels_1911(
                lambda: suspension_api.unsuspend_member(self.member.name, "scope test")
            )
            unknown = self._observe_channels_1911(lambda: suspension_api.unsuspend_member(UNKNOWN, "scope test"))
        self.assertFalse(forbidden["outcome"]["success"], msg=forbidden)
        self.assertEqual(forbidden["outcome"]["error"]["code"], "PERMISSION_DENIED")
        self.assertEqual(
            self._normalise_probe_1911(forbidden, self.member.name), self._normalise_probe_1911(unknown, UNKNOWN)
        )

    def test_can_suspend_unknown_and_forbidden_are_indistinguishable(self):
        with self.set_user(self.other_board.user):
            forbidden = self._observe_channels_1911(lambda: suspension_api.can_suspend_member(self.member.name))
            unknown = self._observe_channels_1911(lambda: suspension_api.can_suspend_member(UNKNOWN))
        self.assertFalse(forbidden["outcome"]["data"]["can_suspend"], msg=forbidden)
        self.assertEqual(
            self._normalise_probe_1911(forbidden, self.member.name), self._normalise_probe_1911(unknown, UNKNOWN)
        )

    def test_bulk_unknown_and_forbidden_are_indistinguishable(self):
        with self.set_user(self.treasurer):
            forbidden = self._observe_channels_1911(
                lambda: suspension_api.bulk_suspend_members([self.member.name], "scope test")
            )
            unknown = self._observe_channels_1911(
                lambda: suspension_api.bulk_suspend_members([UNKNOWN], "scope test")
            )
        self.assertEqual(
            self._normalise_probe_1911(forbidden, self.member.name), self._normalise_probe_1911(unknown, UNKNOWN)
        )
        self.assertIn("No permission to suspend", str(forbidden["outcome"]))

    def test_admin_unknown_name_is_does_not_exist_on_every_endpoint(self):
        """The admin pair may read every Member, so a mistyped name keeps DOES_NOT_EXIST."""
        self.expectErrorLog("Suspension API Validation Error")
        with self.set_user(self.admin):
            for label, result in (
                ("preview", suspension_api.get_suspension_preview(member_name=UNKNOWN)),
                ("can_suspend", suspension_api.can_suspend_member(UNKNOWN)),
                ("suspend", suspension_api.suspend_member(UNKNOWN, "scope test")),
                ("unsuspend", suspension_api.unsuspend_member(UNKNOWN, "scope test")),
            ):
                with self.subTest(endpoint=label):
                    self.assertFalse(result["success"], msg=result)
                    self.assertEqual(result["error"]["code"], "DOES_NOT_EXIST", msg=result)
            bulk = suspension_api.bulk_suspend_members([UNKNOWN], "scope test")
        detail = bulk["meta"]["data"]["details"][0]
        self.assertIn("does not exist", detail["error"])

    def test_bare_system_manager_without_role_profile(self):
        """A bare System Manager (no Verenigingen role profile) clears neither HIGH nor
        CRITICAL, so preview/suspend/unsuspend/bulk refuse it at the tier gate before any
        body runs; only the LOW-tier can_suspend_member is reachable, and there the admin
        pair still gets DOES_NOT_EXIST for a mistyped name and True for a real one."""
        email = f"bare-sm-{frappe.generate_hash(length=8)}0@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "BareSM",
                "send_welcome_email": 0,
                "roles": [{"role": "System Manager"}],
            }
        ).insert()
        self.factory.track_document("User", user.name, priority=2)
        with self.set_user(email):
            self.assertFalse(frappe.get_doc("User", email).role_profile_name)
            for fn, args in (
                (suspension_api.get_suspension_preview, (self.member.name,)),
                (suspension_api.suspend_member, (self.member.name, "scope test")),
                (suspension_api.unsuspend_member, (self.member.name, "scope test")),
                (suspension_api.bulk_suspend_members, ([self.member.name], "scope test")),
            ):
                with self.subTest(endpoint=fn.__name__), self.assertRaises(frappe.PermissionError):
                    fn(*args)
            missing = suspension_api.can_suspend_member(UNKNOWN)
            self.assertIs(missing["success"], False, msg=missing)
            self.assertEqual(missing["error"]["code"], "DOES_NOT_EXIST")
            self.assertTrue(suspension_api.can_suspend_member(self.member.name)["data"]["can_suspend"])

    # --- query-count channel ------------------------------------------------

    def _queries_1911(self, call):
        from verenigingen.tests.utils.query_counter import count_queries

        call()  # warm caches so only the code path differs
        with count_queries() as counter:
            call()
        return len(counter.queries)

    def _assert_same_query_count_1911(self, user, forbidden_call, unknown_call):
        """The endpoint's OWN work must not differ between a forbidden and an unknown name.

        frappe.has_permission itself costs more for a real document (it loads it and runs
        the Member permission hook) than for an unknown one (the load fails at once). That
        cost sits inside Frappe and is shared by every caller of
        permission_allowed_without_oracle, so it is measured separately and subtracted;
        what must match is everything the endpoint adds (the chapter/board lookups of
        can_terminate_member, the member/user/team reads of the preview).

        RESIDUAL, accepted: the RAW totals still differ by ~4 queries for a no-read caller,
        because frappe.has_permission loads a real document but fails fast on an unknown
        one. That is inside Frappe and shared by every permission_allowed_without_oracle
        caller (9 modules); it is not closed here (see the follow-up issue).
        """
        from verenigingen.utils.security.permission_existence_guard import permission_allowed_without_oracle

        with self.set_user(user):
            self.assertFalse(
                frappe.has_permission("Member", "read", self.member.name),
                "caller must lack Member read for the cheap-path equality to be the fix under test",
            )
            self.expectErrorLog("Suspension API Permission Error")
            self.expectErrorLog("Suspension API Validation Error")
            self.expectErrorLog("Suspension API Error")
            extra = {}
            for label, call, name in (
                ("forbidden", forbidden_call, self.member.name),
                ("unknown", unknown_call, UNKNOWN),
            ):
                total = self._queries_1911(call)
                bare = self._queries_1911(lambda: permission_allowed_without_oracle("Member", "read", name))  # noqa: B023
                extra[label] = total - bare
        self.assertEqual(extra["forbidden"], extra["unknown"], f"endpoint-added queries: {extra}")

    def test_query_count_preview_same_for_unknown_and_forbidden(self):
        self._assert_same_query_count_1911(
            self.other_board.user,
            lambda: suspension_api.get_suspension_preview(member_name=self.member.name),
            lambda: suspension_api.get_suspension_preview(member_name=UNKNOWN),
        )

    def test_query_count_can_suspend_same_for_unknown_and_forbidden(self):
        self._assert_same_query_count_1911(
            self.other_board.user,
            lambda: suspension_api.can_suspend_member(self.member.name),
            lambda: suspension_api.can_suspend_member(UNKNOWN),
        )

    def test_every_critical_tier_caller_can_read_members(self):
        """Why suspend/unsuspend/bulk have no query-count test: the only profiles that clear
        CRITICAL besides the admin pair are Treasurer and National Board Member, and both
        hold blanket Member read (measured here), so no no-read caller reaches those bodies
        and a caller who can list members learns nothing from a slower path."""
        for user in (self.treasurer, self.national):
            with self.set_user(user):
                self.assertTrue(frappe.has_permission("Member", "read", self.member.name), user)

    # --- opposite harm: legitimate callers still succeed ----------------------

    def test_own_chapter_treasurer_still_allowed(self):
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        treasurer = self.create_test_board_member(self.chapter_a.name).user
        assign_role_profile_to_user(treasurer, "Verenigingen Treasurer")
        with self.set_user(treasurer):
            self.assertTrue(suspension_api.can_suspend_member(self.member.name)["data"]["can_suspend"])
            self.assertTrue(suspension_api.get_suspension_preview(member_name=self.member.name)["success"])

    def test_own_chapter_board_member_can_suspend_check(self):
        with self.set_user(self.own_board.user):
            self.assertTrue(suspension_api.can_suspend_member(self.member.name)["data"]["can_suspend"])

    def test_admin_roles_can_suspend_and_unsuspend(self):
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        for role in ("Verenigingen Administrator", "System Manager"):
            with self.subTest(role=role):
                member = self.create_test_member(first_name="Adm", last_name=f"T{role[:3]}", status="Active")
                user = self._staff_user(f"Roles1911{role[:3]}", role=role)
                assign_role_profile_to_user(
                    user,
                    "Verenigingen System Administrator" if role == "System Manager" else "Verenigingen Administrator",
                )
                with self.set_user(user):
                    done = suspension_api.suspend_member(member.name, "scope", False, False)
                    self.assertTrue(done["success"], msg=done)
                    back = suspension_api.unsuspend_member(member.name, "scope back")
                    self.assertTrue(back["success"], msg=back)
