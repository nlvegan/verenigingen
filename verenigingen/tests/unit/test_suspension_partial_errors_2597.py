"""A suspension that left a team row active must not answer a plain success (#2597).

#2517 made `suspend_team_memberships_safe` / `restore_team_memberships_safe` append to
`results["errors"]` while `success` stays True. The callers branched on `success` alone and
said "Member suspended successfully". These tests drive the REAL endpoints and mixin and
inject the failure BELOW the helper (the `Team Member` `set_value` write), never by
hand-setting `results`.

Probe shortcuts, stated: `test_unsuspend_*` reaches "suspended" through the real
`suspend_member_safe`. The volunteer test patches `sync_user_role_profile` itself to raise
(that call is the thing under test, it has no lower seam worth injecting at).
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.unit.test_termination_safe_helpers_report_failures_2517 import _Base


def _as_dict(result):
    return result.to_dict() if hasattr(result, "to_dict") else result


class _SuspensionBase(_Base):
    def _payload(self, result):
        body = _as_dict(result)
        self.assertTrue(body.get("success"), f"the member IS suspended, so success stays True: {body}")
        return body.get("data") or {}


class TestSuspensionApiReportsPartialResult2597(_SuspensionBase):
    def test_suspend_member_names_the_team_that_was_not_suspended(self):
        from verenigingen.api.suspension_api import suspend_member

        with self._failing_set_value(Exception("write boom")):
            result = suspend_member(self.member.name, "policy")

        data = self._payload(result)
        self.assertTrue(data.get("partial"), data)
        self.assertEqual(len([e for e in data["errors"] if self.team.name in e]), 1, data)
        self.assertEqual(self._team_row_state().is_active, 1)
        body = _as_dict(result)
        self.assertNotIn("suspended successfully", str(body.get("meta", {})) + str(body.get("message", "")))
        # Not suspending the team does not undo the suspension itself.
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Suspended")

    def test_a_permission_failure_on_the_team_write_is_also_partial(self):
        """The PermissionError catch branch of suspend_team_memberships_safe surfaces too."""
        from verenigingen.api.suspension_api import suspend_member

        with self._failing_set_value(frappe.PermissionError("no")):
            result = suspend_member(self.member.name, "policy")

        data = self._payload(result)
        self.assertTrue(data.get("partial"), data)
        self.assertEqual(
            len([e for e in data["errors"] if self.team.name in e and "permission" in e.lower()]), 1, data
        )
        self.assertEqual(self._team_row_state().is_active, 1)

    def test_a_clean_suspend_member_stays_a_plain_success(self):
        """CONTROL: the team row really is suspended and no partial marker appears."""
        from verenigingen.api.suspension_api import suspend_member

        data = self._payload(suspend_member(self.member.name, "policy"))

        self.assertEqual(self._team_row_state().is_active, 0)
        self.assertFalse(data.get("partial"), data)
        self.assertFalse(data.get("errors"), data)

    def test_unsuspend_member_names_the_team_that_was_not_restored(self):
        from verenigingen.api.suspension_api import suspend_member, unsuspend_member

        self._payload(suspend_member(self.member.name, "policy"))
        self.assertEqual(self._team_row_state().is_active, 0)
        with self._failing_set_value(Exception("restore boom"), when=lambda v: v.get("is_active") == 1):
            result = unsuspend_member(self.member.name, "appeal")

        data = self._payload(result)
        self.assertTrue(data.get("partial"), data)
        self.assertEqual(len([e for e in data["errors"] if self.team.name in e]), 1, data)
        self.assertEqual(self._team_row_state().is_active, 0)

    def test_a_clean_unsuspend_member_stays_a_plain_success(self):
        """CONTROL."""
        from verenigingen.api.suspension_api import suspend_member, unsuspend_member

        self._payload(suspend_member(self.member.name, "policy"))
        data = self._payload(unsuspend_member(self.member.name, "appeal"))

        self.assertEqual(self._team_row_state().is_active, 1)
        self.assertFalse(data.get("partial"), data)

    def test_bulk_suspend_members_flags_the_member_with_a_failed_team_write(self):
        from verenigingen.api.suspension_api import bulk_suspend_members

        with self._failing_set_value(Exception("write boom")):
            result = bulk_suspend_members(frappe.as_json([self.member.name]), "policy")

        body = _as_dict(result)
        self.assertTrue(body.get("success"), body)
        detail = body["data"]["details"][0]
        self.assertTrue(detail["success"], detail)
        self.assertEqual(len([e for e in detail.get("errors", []) if self.team.name in e]), 1, detail)
        self.assertEqual(body["data"].get("partial"), 1, body["data"])

    def test_bulk_suspend_members_control_clean_member_has_no_errors(self):
        """CONTROL."""
        from verenigingen.api.suspension_api import bulk_suspend_members

        body = _as_dict(bulk_suspend_members(frappe.as_json([self.member.name]), "policy"))

        detail = body["data"]["details"][0]
        self.assertFalse(detail.get("errors"), detail)
        self.assertFalse(body["data"].get("partial"), body["data"])


class TestMemberMixinReportsPartialResult2597(_SuspensionBase):
    def test_member_suspend_member_marks_a_partial_result_and_warns(self):
        member = frappe.get_doc("Member", self.member.name)
        with self._failing_set_value(Exception("write boom")):
            results = member.suspend_member("policy")

        self.assertTrue(results["success"], results)
        self.assertTrue(results.get("partial"), results)
        self.assertEqual(len([e for e in results["errors"] if self.team.name in e]), 1, results)
        warned = [m for m in frappe.message_log if self.team.name in str(m)]
        self.assertTrue(warned, "no desk message names the team that is still active")

    def test_the_desk_message_escapes_html_in_a_team_name(self):
        """A team whose name is markup must reach the msgprint escaped, not as HTML."""
        hostile = "<b>x2597</b>"
        frappe.db.sql("UPDATE `tabTeam Member` SET parent=%s WHERE name=%s", (hostile, self.team_row))
        member = frappe.get_doc("Member", self.member.name)
        with self._failing_set_value(Exception("write boom")):
            results = member.suspend_member("policy")

        self.assertTrue(any(hostile in e for e in results["errors"]), results)
        shown = " ".join(str(m) for m in frappe.message_log)
        self.assertIn("&lt;b&gt;x2597&lt;/b&gt;", shown)
        self.assertNotIn(hostile, shown)

    def test_member_suspend_member_control_clean_is_not_partial(self):
        """CONTROL."""
        results = frappe.get_doc("Member", self.member.name).suspend_member("policy")

        self.assertTrue(results["success"], results)
        self.assertFalse(results.get("partial"), results)

    def test_member_unsuspend_member_marks_a_partial_result(self):
        member = frappe.get_doc("Member", self.member.name)
        member.suspend_member("policy")
        member = frappe.get_doc("Member", self.member.name)
        with self._failing_set_value(Exception("restore boom"), when=lambda v: v.get("is_active") == 1):
            results = member.unsuspend_member("appeal")

        self.assertTrue(results.get("partial"), results)
        self.assertEqual(len([e for e in results["errors"] if self.team.name in e]), 1, results)


class TestTerminateVolunteerKeepsCountWhenRoleSyncRaises2597(_Base):
    def test_a_raising_role_profile_sync_does_not_zero_the_count(self):
        from verenigingen.services.termination.termination_integration import (
            terminate_volunteer_records_safe,
        )

        user = self.create_test_user(f"vol2597.{frappe.generate_hash(length=6)}@example.com")
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        with patch(
            "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile",
            side_effect=RuntimeError("sync boom"),
        ):
            results = terminate_volunteer_records_safe(self.member.name, "Voluntary", None, "r")

        self.assertEqual(frappe.db.get_value("Volunteer", self.volunteer.name, "status"), "Inactive")
        self.assertEqual(results["volunteers_terminated"], 1, results)
        self.assertTrue(any("sync boom" in e for e in results["errors"]), results)
        self.assertTrue(any(self.volunteer.name in a or "volunteer" in a.lower() for a in results["actions_taken"]), results)

    def test_a_non_resumable_db_error_in_the_role_sync_still_propagates(self):
        """The new wrap must not swallow a 1213/1205: the transaction is already gone."""
        from verenigingen.services.termination.termination_integration import (
            terminate_volunteer_records_safe,
        )

        user = self.create_test_user(f"vol2597b.{frappe.generate_hash(length=6)}@example.com")
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        for error in (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
            with self.subTest(error=error.__name__):
                with patch(
                    "verenigingen.services.member.account.user_role_profile_calculator."
                    "sync_user_role_profile",
                    side_effect=error,
                ):
                    with self.assertRaises(error):
                        terminate_volunteer_records_safe(self.member.name, "Voluntary", None, "r")
