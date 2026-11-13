"""The termination `*_safe` helpers record a failed step instead of hiding it (#2517).

#832 fixed `end_board_positions_safe`. Its siblings had the same shape: a failed save went
to `frappe.logger()` (a rotating file nobody reads), the helper returned a bare count, and
the termination reached Executed with `errors: []` while the step had not been done.

Every test here drives the REAL path (`TerminationExecutionService.execute_system_updates`,
`suspend_member_safe` / `unsuspend_member_safe`, `execute_safe_termination`) and injects the
failure BELOW every layer that swallows: the document `save()` / the `Team Member`
`set_value` write, never a stub of the helper itself.

Probe shortcuts, stated: none of the fixtures sets a status directly to stand in for a flow
except `test_restore_*`, which reaches "suspended" through the real `suspend_member_safe`.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.support.termination_request import create_termination_request
from verenigingen.tests.utils.base import VereningingenTestCase

ANY_2517_TITLE = "Termination:"


class _Base(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Volunteer insert queues an Account Creation Request that nothing here needs (#2338).
        self._skip_flag_was_set = "skip_volunteer_account_creation" in frappe.flags
        self._skip_flag_before = frappe.flags.get("skip_volunteer_account_creation")
        frappe.flags.update({"skip_volunteer_account_creation": True})

        def restore_flag():
            if self._skip_flag_was_set:
                frappe.flags.update({"skip_volunteer_account_creation": self._skip_flag_before})
            else:
                frappe.flags.pop("skip_volunteer_account_creation", None)

        self.addCleanup(restore_flag)
        # The injected failures now write Error Log rows on purpose; the Team controller also
        # logs (and swallows) unrelated "not found" errors against the uncommitted team.
        self.expectErrorLog(
            ANY_2517_TITLE,
            "Team Assignment History Error",
            "Team Notification Error",
            "Team Event Emission Error",
        )
        self.member = self.create_test_member()
        self.volunteer = self.create_test_volunteer(member=self.member.name)
        self.chapter = self._chapter_with_member(self.member.name)
        self.team, self.team_row = self._team_with_volunteer(self.volunteer)
        self.request = create_termination_request(self, self.member.name, "#2517 failed step")

    # -- fixtures ------------------------------------------------------------------

    def _chapter_with_member(self, member_name):
        chapter = frappe.get_doc("Chapter", self.create_test_chapter().name)
        chapter.append("members", {"member": member_name, "enabled": 1})
        chapter.save()
        return chapter

    def _team_with_volunteer(self, volunteer):
        team = self.factory.create_test_team()
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": self.factory.get_or_create_team_role("Team Member").name,
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team_doc.save()
        return team, team_doc.team_members[-1].name

    # -- helpers -------------------------------------------------------------------

    def _execute_updates(self):
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        return TerminationExecutionService().execute_system_updates(self.request)

    def _audit_errors(self):
        return [r.details for r in self.request.audit_trail if r.action == "System Update Error"]

    def _chapter_row(self, chapter_name=None):
        return frappe.db.get_value(
            "Chapter Member",
            {"parent": chapter_name or self.chapter.name, "member": self.member.name},
            ["enabled", "status"],
            as_dict=True,
        )

    def _team_row_state(self):
        return frappe.db.get_value(
            "Team Member", self.team_row, ["is_active", "status", "to_date"], as_dict=True
        )

    def _error_log_count(self, title):
        return frappe.db.count("Error Log", {"method": title})

    def _failing_set_value(self, error, when=lambda values: True):
        """Patch the write the Team Member helpers make, failing only for a Team Member row."""
        original = frappe.db.set_value

        def fake(doctype, name, field=None, value=None, *args, **kwargs):
            values = field if isinstance(field, dict) else {field: value}
            if doctype == "Team Member" and when(values):
                raise error
            return original(doctype, name, field, value, *args, **kwargs)

        return patch.object(frappe.db, "set_value", side_effect=fake)

    def _failing_save_for(self, doctype_cls, names, error):
        """Fail `save()` only for the named docs of one doctype; others save for real."""
        original = doctype_cls.save

        def fake(doc, *args, **kwargs):
            if doc.name in names:
                raise error
            return original(doc, *args, **kwargs)

        return patch.object(doctype_cls, "save", fake)


class TestDisableChapterMembershipsReportsFailures2517(_Base):
    def _chapter_cls(self):
        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        return Chapter

    def test_a_failed_chapter_save_reaches_the_termination_errors_and_audit_trail(self):
        """develop: errors == [] while the membership is still enabled (the red)."""
        before = self._error_log_count("Termination: chapter memberships not disabled")
        with self._failing_save_for(self._chapter_cls(), {self.chapter.name}, Exception("save boom")):
            results = self._execute_updates()

        mine = [e for e in results["errors"] if self.chapter.name in e and "chapter" in e.lower()]
        self.assertEqual(len(mine), 1, results["errors"])
        self.assertTrue(any(self.chapter.name in d for d in self._audit_errors()), self._audit_errors())
        self.assertEqual(self._chapter_row().enabled, 1)
        self.assertEqual(
            self._error_log_count("Termination: chapter memberships not disabled"), before + 1
        )

    def test_a_permission_failure_saving_the_chapter_is_also_reported(self):
        with self._failing_save_for(self._chapter_cls(), {self.chapter.name}, frappe.PermissionError("no")):
            results = self._execute_updates()

        self.assertEqual(
            len([e for e in results["errors"] if self.chapter.name in e and "permission" in e.lower()]),
            1,
            results["errors"],
        )
        self.assertEqual(self._chapter_row().enabled, 1)

    def test_a_failure_after_the_row_write_is_rolled_back_not_half_applied(self):
        """The Chapter save fails in on_update, AFTER the Chapter Member row was written.

        `frappe.db.rollback_to_savepoint` does not exist, so on develop the rollback raised
        AttributeError inside the handler, nothing was undone, and the row stayed
        enabled=0 in the transaction the termination commits while the helper reported 0.
        """
        Chapter = self._chapter_cls()
        failures = []
        from verenigingen.services.termination.termination_integration import (
            disable_chapter_memberships_safe,
        )

        with patch.object(Chapter, "on_update", side_effect=Exception("late failure"), create=True):
            kwargs = {"failures": failures} if self._supports_failures() else {}
            result = disable_chapter_memberships_safe(self.member.name, today(), "late", **kwargs)

        self.assertEqual(result, 0)
        row = self._chapter_row()
        self.assertEqual((row.enabled, row.status), (1, "Active"), "half-applied chapter write")

    def _supports_failures(self):
        import inspect

        from verenigingen.services.termination.termination_integration import (
            disable_chapter_memberships_safe,
        )

        return "failures" in inspect.signature(disable_chapter_memberships_safe).parameters

    def test_the_rollback_helper_is_reached_and_does_not_raise_attribute_error(self):
        """Names the defect itself: the savepoint rollback line must be one that exists."""
        from verenigingen.services.termination import termination_integration as ti

        seen = []
        real = getattr(ti, "rollback_to_savepoint", None)
        self.assertIsNotNone(real, "the app's rollback helper is not imported by the module")

        def spy(name):
            seen.append(name)
            return real(name)

        with patch.object(ti, "rollback_to_savepoint", side_effect=spy):
            with self._failing_save_for(self._chapter_cls(), {self.chapter.name}, Exception("boom")):
                ti.disable_chapter_memberships_safe(self.member.name, today(), "spy")

        self.assertEqual(len(seen), 1, seen)

    def test_one_failing_chapter_does_not_stop_the_other_chapter_or_the_other_steps(self):
        """Opposite harm: a failure in one chapter must not undo the others, nor the other
        termination steps (#832: record, do not raise)."""
        second = self._chapter_with_member(self.member.name)
        # Derive the expected count from the fixture: the member factory may seat the
        # member in further chapters of its own.
        other_enabled = frappe.db.count(
            "Chapter Member",
            {"member": self.member.name, "enabled": 1, "parent": ["!=", self.chapter.name]},
        )
        self.assertGreaterEqual(other_enabled, 1)
        with self._failing_save_for(self._chapter_cls(), {self.chapter.name}, Exception("one bad")):
            results = self._execute_updates()

        self.assertEqual(self._chapter_row(self.chapter.name).enabled, 1)
        other = self._chapter_row(second.name)
        self.assertEqual((other.enabled, other.status), (0, "Inactive"))
        self.assertEqual(len([e for e in results["errors"] if self.chapter.name in e]), 1)
        self.assertFalse([e for e in results["errors"] if second.name in e], results["errors"])
        self.assertTrue(
            f"Disabled {other_enabled} chapter membership(s)" in results["actions_taken"],
            results["actions_taken"],
        )
        self.assertEqual(frappe.db.get_value("Volunteer", self.volunteer.name, "status"), "Inactive")
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Quit")

    def test_a_failed_history_update_is_reported(self):
        from verenigingen.utils.chapter_membership_history_manager import (
            ChapterMembershipHistoryManager,
        )

        with patch.object(
            ChapterMembershipHistoryManager,
            "terminate_chapter_membership",
            side_effect=Exception("history boom"),
        ):
            results = self._execute_updates()

        self.assertEqual(
            len([e for e in results["errors"] if "history" in e.lower() and self.chapter.name in e]),
            1,
            results["errors"],
        )
        # The row write itself succeeded and stays: the message must not say it did not.
        self.assertEqual(self._chapter_row().enabled, 0)

    def test_history_of_a_chapter_that_did_not_save_is_left_open(self):
        """The membership there is still enabled, so its history must not be ended."""
        from verenigingen.utils.chapter_membership_history_manager import (
            ChapterMembershipHistoryManager,
        )

        real = ChapterMembershipHistoryManager.terminate_chapter_membership
        ended = []

        def spy(*args, **kwargs):
            ended.append(kwargs.get("chapter_name"))
            return real(*args, **kwargs)

        second = self._chapter_with_member(self.member.name)
        with patch.object(ChapterMembershipHistoryManager, "terminate_chapter_membership", side_effect=spy):
            with self._failing_save_for(self._chapter_cls(), {self.chapter.name}, Exception("one bad")):
                self._execute_updates()

        self.assertIn(second.name, ended, "control: the chapter that saved had its history ended")
        self.assertNotIn(self.chapter.name, ended)

    def test_a_clean_termination_records_no_chapter_error(self):
        """CONTROL: a real row exists for a wrong report to find."""
        results = self._execute_updates()

        self.assertEqual(self._chapter_row().enabled, 0)
        self.assertFalse(
            [e for e in results["errors"] if "chapter" in e.lower() and "board" not in e.lower()],
            results["errors"],
        )


class TestSuspendTeamMembershipsReportsFailures2517(_Base):
    def test_a_failed_team_member_write_reaches_the_termination_errors(self):
        """develop: errors == [] while the row is still active (the red)."""
        before = self._error_log_count("Termination: team membership not suspended")
        with self._failing_set_value(Exception("write boom")):
            results = self._execute_updates()

        self.assertEqual(
            len([e for e in results["errors"] if self.team.name in e and "team" in e.lower()]),
            1,
            results["errors"],
        )
        self.assertTrue(any(self.team.name in d for d in self._audit_errors()), self._audit_errors())
        self.assertEqual(self._team_row_state().is_active, 1)
        self.assertEqual(self._error_log_count("Termination: team membership not suspended"), before + 1)

    def test_a_permission_failure_on_the_write_is_also_reported(self):
        with self._failing_set_value(frappe.PermissionError("no")):
            results = self._execute_updates()

        self.assertEqual(
            len([e for e in results["errors"] if self.team.name in e and "permission" in e.lower()]),
            1,
            results["errors"],
        )
        self.assertEqual(self._team_row_state().is_active, 1)

    def test_a_failed_team_does_not_stop_the_next_team_or_the_other_steps(self):
        second_team, second_row = self._team_with_volunteer(self.volunteer)

        original = frappe.db.set_value

        def fake(doctype, name, field=None, value=None, *args, **kwargs):
            if doctype == "Team Member" and name == self.team_row:
                raise Exception("first row only")
            return original(doctype, name, field, value, *args, **kwargs)

        with patch.object(frappe.db, "set_value", side_effect=fake):
            results = self._execute_updates()

        self.assertEqual(self._team_row_state().is_active, 1)
        self.assertEqual(frappe.db.get_value("Team Member", second_row, "is_active"), 0)
        self.assertEqual(results["teams_suspended"], 1)
        self.assertEqual(len([e for e in results["errors"] if self.team.name in e]), 1)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Quit")

    def test_a_failed_team_lead_removal_is_reported_and_rolled_back_after_the_row_write(self):
        """Team.save fails in on_update AFTER team_lead was written: reported, and undone."""
        from verenigingen.verenigingen.doctype.team.team import Team

        # Fixture shortcut: Member.user and Team.team_lead are set directly; the
        # termination under test is what removes the lead.
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"t2517-{frappe.generate_hash(length=8)}@example.com",
                "first_name": "T2517",
                "enabled": 1,
                "send_welcome_email": 0,
            }
        ).insert()
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        frappe.db.set_value("Team", self.team.name, "team_lead", user.name)

        with patch.object(Team, "on_update", side_effect=Exception("late team failure")):
            results = self._execute_updates()

        self.assertEqual(
            len([e for e in results["errors"] if self.team.name in e and "lead" in e.lower()]),
            1,
            results["errors"],
        )
        self.assertEqual(frappe.db.get_value("Team", self.team.name, "team_lead"), user.name)

    def test_the_api_path_reports_a_failed_team_write(self):
        from verenigingen.api.termination_api import execute_safe_termination

        with self._failing_set_value(Exception("write boom")):
            result = execute_safe_termination(self.member.name, "Voluntary", today())

        self.assertTrue(
            any(self.team.name in e for e in result.get("errors", [])),
            f"the API result does not name the unsuspended team: {result}",
        )

    def test_suspend_member_safe_reports_a_failed_team_write(self):
        from verenigingen.services.termination.termination_integration import suspend_member_safe

        with self._failing_set_value(Exception("write boom")):
            results = suspend_member_safe(self.member.name, "policy", suspend_teams=True)

        self.assertTrue(any(self.team.name in e for e in results["errors"]), results)

    def test_a_clean_suspension_records_no_team_error(self):
        """CONTROL: the row is really suspended, and nothing is reported."""
        results = self._execute_updates()

        self.assertEqual(self._team_row_state().is_active, 0)
        self.assertFalse([e for e in results["errors"] if self.team.name in e], results["errors"])


class TestRestoreTeamMembershipsReportsFailures2517(_Base):
    def _suspend_for_real(self):
        from verenigingen.services.termination.termination_integration import suspend_member_safe

        result = suspend_member_safe(self.member.name, "policy", suspend_teams=True)
        self.assertEqual(result["teams_suspended"], 1, result)
        self.assertEqual(self._team_row_state().is_active, 0)

    def test_a_failed_restore_write_is_reported_by_unsuspend(self):
        """develop: errors == [] while the team row is still inactive (the red)."""
        from verenigingen.services.termination.termination_integration import unsuspend_member_safe

        self._suspend_for_real()
        before = self._error_log_count("Termination: team membership not restored")
        with self._failing_set_value(Exception("restore boom"), when=lambda v: v.get("is_active") == 1):
            results = unsuspend_member_safe(self.member.name, "appeal", restore_teams=True)

        self.assertEqual(
            len([e for e in results["errors"] if self.team.name in e and "restore" in e.lower()]),
            1,
            results,
        )
        self.assertEqual(self._team_row_state().is_active, 0)
        self.assertEqual(self._error_log_count("Termination: team membership not restored"), before + 1)
        # Opposite harm: the member is still unsuspended; the failure is recorded, not raised.
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Active")

    def test_a_permission_failure_on_restore_is_reported(self):
        from verenigingen.services.termination.termination_integration import unsuspend_member_safe

        self._suspend_for_real()
        with self._failing_set_value(frappe.PermissionError("no"), when=lambda v: v.get("is_active") == 1):
            results = unsuspend_member_safe(self.member.name, "appeal", restore_teams=True)

        self.assertEqual(
            len([e for e in results["errors"] if self.team.name in e and "permission" in e.lower()]),
            1,
            results,
        )

    def test_a_clean_restore_records_no_team_error(self):
        """CONTROL."""
        from verenigingen.services.termination.termination_integration import unsuspend_member_safe

        self._suspend_for_real()
        results = unsuspend_member_safe(self.member.name, "appeal", restore_teams=True)

        self.assertEqual(self._team_row_state().is_active, 1)
        self.assertFalse([e for e in results["errors"] if self.team.name in e], results)


class TestTerminateVolunteerReportsFailures2517(_Base):
    def _volunteer_cls(self):
        from verenigingen.verenigingen.doctype.volunteer.volunteer import Volunteer

        return Volunteer

    def _volunteer_status(self):
        return frappe.db.get_value("Volunteer", self.volunteer.name, "status")

    def test_a_permission_failure_saving_the_volunteer_reaches_the_termination_errors(self):
        """develop: the PermissionError is logger-only; errors == [] (the red)."""
        before = self._error_log_count("Termination: volunteer record not terminated (permission)")
        start = self._volunteer_status()
        with self._failing_save_for(self._volunteer_cls(), {self.volunteer.name}, frappe.PermissionError("no")):
            results = self._execute_updates()

        self.assertEqual(
            len([e for e in results["errors"] if self.volunteer.name in e and "permission" in e.lower()]),
            1,
            results["errors"],
        )
        self.assertTrue(any(self.volunteer.name in d for d in self._audit_errors()), self._audit_errors())
        self.assertEqual(self._volunteer_status(), start)
        self.assertEqual(
            self._error_log_count("Termination: volunteer record not terminated (permission)"), before + 1
        )
        # Opposite harm: the rest of the termination still ran.
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "status"), "Quit")

    def test_a_failure_after_the_row_write_is_rolled_back_and_reported(self):
        """Volunteer.on_update fails AFTER the status row was written: the status must not
        stay Inactive in the committed transaction while the error says it was not done."""
        start = self._volunteer_status()
        with patch.object(self._volunteer_cls(), "on_update", side_effect=Exception("late vol failure")):
            results = self._execute_updates()

        self.assertEqual(
            len([e for e in results["errors"] if self.volunteer.name in e]), 1, results["errors"]
        )
        self.assertEqual(self._volunteer_status(), start, "half-applied volunteer termination")

    def test_a_clean_termination_inactivates_the_volunteer_and_records_no_error(self):
        """CONTROL."""
        results = self._execute_updates()

        self.assertEqual(self._volunteer_status(), "Inactive")
        self.assertFalse([e for e in results["errors"] if self.volunteer.name in e], results["errors"])

