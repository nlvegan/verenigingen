"""
#2385: more whitelisted endpoints that test a boolean flag with a bare ``if <arg>:``.

Follow-up to #2377. Over HTTP a flag arrives as a string and ``"0"`` / ``"false"`` are truthy in
Python, so a guard flag (``force``, ``force_enable``, ``confirm*``) was passed by a client that said
"no". Each test sends the flag through the real WSGI app (``wsgi_http_session``) so the string
arrives exactly as ``frappe.call`` would deliver it.

* ``scripts/`` is a top-level package, not an installed app, so dispatch refuses
  ``scripts.*`` paths ("App scripts is not installed", measured). The member_import_cleanup
  endpoints are HTTP-reachable through the ``verenigingen.utils.member_import_cleanup`` shim
  (same function objects); ``install_eboekhouden_workspace`` and ``cleanup_invalid_schedules``
  have no such path (nor do ``cleanup_orphaned_chapter_members`` / ``..._addresses_and_contacts``, which the
  shim does not export) and are tested with the strings called in-process.
* guard flags (widening direction): ``"0"`` / ``"false"`` / an unrecognised string must NOT pass.
* ``dry_run`` (destructive direction): an unrecognised string must stay a dry run, and ``"false"``
  must be able to ask for the real run (``is_dry_run``, shared with #2377).

The destructive endpoints are only ever driven with a dry run or a flag that must be refused;
``execute_clean_import`` and the workspace install are exercised with the callee stubbed in the
child (``patches``), so the red run cannot delete financial data.

Usage:
    bench --site test_site_9 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_bool_flags_over_http_2385
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.tests.api import test_schedule_maintenance as _schedule_tests
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    run_wsgi_cases,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.boolean_utils import is_dry_run

FALSE_FLAGS = ("0", "false", 0, False, "maybe", "")

ENDPOINTS = {
    "stuck": api_path("verenigingen.api.fix_stuck_dues_schedule.fix_stuck_schedule"),
    "truncate_members": api_path("verenigingen.utils.member_import_cleanup.nuclear_truncate_member_tables"),
    "truncate_versions": api_path("verenigingen.utils.version_cleanup.nuclear_truncate_version_and_deleted_tables"),
    "nuclear_members": api_path("verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members"),
    "clean_import": api_path("verenigingen.e_boekhouden.api.eboekhouden_clean_reimport.execute_clean_import"),
    "scan": api_path("verenigingen.utils.member_import_cleanup.scan_and_clear_broken_links"),
    "schedule_orphans": api_path("verenigingen.utils.member_import_cleanup.force_cleanup_orphaned_schedules_and_invoices"),
    "test_members": api_path("verenigingen.utils.member_import_cleanup.cleanup_test_members_only"),
}


def _case(name, endpoint, user, password, payload):
    return {
        "name": name,
        "endpoint": endpoint,
        "login": {"usr": user, "pwd": password},
        "csrf": "valid",
        "json": payload,
    }


class TestIsDryRun(VereningingenTestCase):
    def test_fails_closed(self):
        for value in (True, "true", "1", 1, "maybe", "", None, "TRUE", "garbage"):
            self.assertTrue(is_dry_run(value), repr(value))
        for value in (False, "false", "False", "0", 0, "no", " off "):
            self.assertFalse(is_dry_run(value), repr(value))


class TestGuardFlagsOverHttp(CommittedLoginUsersMixin, VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.user = self._create_login_users(admin="Verenigingen Administrator")["admin"]

    def _run(self, key, payload, patches=()):
        out = run_wsgi_cases(_case("c", ENDPOINTS[key], self.user, self.password, payload), patches=patches)
        return out["c"]

    def _message(self, response):
        self.assertEqual(response["status"], 200, response)
        return json.loads(response["body"])["message"]

    def test_nuclear_truncate_refuses_a_false_confirmation_over_http(self):
        """One refused and one accepted call each: critical_api rate-limits these to 2 per hour.

        Dry run only, so the red run (which lets "0" through) truncates nothing.
        """
        for key in ("truncate_members", "truncate_versions"):
            response = self._run(key, {"confirm_nuclear_truncate": "0", "dry_run": True})
            self.assertNotEqual(response["status"], 200, (key, response["body"][:300]))
            self.assertIn("confirm_nuclear_truncate=True", response["body"], key)
            result = self._message(self._run(key, {"confirm_nuclear_truncate": "true", "dry_run": True}))
            self.assertTrue(result["dry_run"], (key, result))  # control: a real confirmation passes

    def test_nuclear_cleanup_all_members_refuses_without_a_real_confirmation(self):
        for flag in FALSE_FLAGS:
            response = self._run("nuclear_members", {"confirm_nuclear_cleanup": flag, "dry_run": True})
            self.assertNotEqual(response["status"], 200, (flag, response["body"][:300]))
            self.assertIn("confirm_nuclear_cleanup=True", response["body"], flag)
        result = self._message(self._run("nuclear_members", {"confirm_nuclear_cleanup": "true", "dry_run": True}))
        self.assertTrue(result["dry_run"], result)

    def test_clean_import_not_run_for_false_confirm(self):
        """The import manager is stubbed in the child, so even the red run deletes nothing."""
        stub = ["verenigingen.e_boekhouden.utils.import_manager.EBoekhoudenImportManager"]
        for flag in FALSE_FLAGS:
            message = self._message(self._run("clean_import", {"confirm": flag}, patches=stub))
            self.assertIsInstance(message, dict, (flag, message))  # a MagicMock answer means it ran
            self.assertEqual(message.get("error"), "Safety check failed", (flag, message))

    def test_unrecognised_dry_run_stays_a_dry_run(self):
        """A string can never ask for the destructive run unless it is a recognised "no".

        ``scan_and_clear_broken_links`` and ``cleanup_test_members_only`` treated an unrecognised
        string as False (a real run). The narrow targets / patterns select nothing, so even the
        red run changes no data.
        """
        cases = {
            "scan": {"target_doctypes": ["Chapter Role"]},
            "test_members": {"email_patterns": ["zz-no-such-member-%@nowhere.invalid"]},
            "schedule_orphans": {},
        }
        for key, extra in cases.items():
            for flag in ("maybe", "", "true", "1"):
                response = self._run(key, {**extra, "dry_run": flag})
                self.assertEqual(response["status"], 200, (key, flag, response["body"][:300]))
                body = json.loads(response["body"])["message"]
                data = body.get("data", body) if isinstance(body, dict) else body
                self.assertIs(data["dry_run"], True, (key, flag, data))

    def test_false_dry_run_strings_can_ask_for_the_real_run(self):
        """Control for the above: a recognised "no" is a real run (narrow selection, nothing to delete)."""
        for key, extra in {
            "scan": {"target_doctypes": ["Chapter Role"]},
            "test_members": {"email_patterns": ["zz-no-such-member-%@nowhere.invalid"]},
        }.items():
            for flag in ("false", "0", False):
                response = self._run(key, {**extra, "dry_run": flag})
                self.assertEqual(response["status"], 200, (key, flag, response["body"][:300]))
                body = json.loads(response["body"])["message"]
                data = body.get("data", body) if isinstance(body, dict) else body
                self.assertIs(data["dry_run"], False, (key, flag, data))


class TestFixStuckScheduleForceOverHttp(
    _schedule_tests.TestScheduleMaintenance, CommittedLoginUsersMixin, VereningingenTestCase
):
    """Borrows the schedule fixtures from test_schedule_maintenance (functions, not its tests)."""

    for _name in [n for n in vars(_schedule_tests.TestScheduleMaintenance) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    def setUp(self):
        super().setUp()
        self.user = self._create_login_users(fixer="Verenigingen Administrator")["fixer"]
        self._types = []
        self.addCleanup(self._cleanup_schedules)

    def _cleanup_schedules(self):
        frappe.db.rollback()
        for mtype in self._types:
            for name in frappe.get_all(
                "Membership Dues Schedule", filters={"membership_type": mtype}, pluck="name"
            ):
                frappe.delete_doc("Membership Dues Schedule", name, force=True, ignore_permissions=True)
            if frappe.db.exists("Membership Type", mtype):
                frappe.delete_doc("Membership Type", mtype, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_committed_schedule(self):
        schedule, _member, mtype = self._make_active_schedule()
        self._types.append(mtype.name)
        frappe.db.commit()  # the WSGI child is another DB connection
        return schedule

    def test_false_force_does_not_bypass_the_no_issues_guard(self):
        schedule = self._create_committed_schedule()

        def call(flag):
            out = run_wsgi_cases(
                _case("c", ENDPOINTS["stuck"], self.user, self.password,
                      {"schedule_name": schedule.name, "force": flag})
            )["c"]
            self.assertEqual(out["status"], 200, out)
            return json.loads(out["body"])["message"]

        for flag in FALSE_FLAGS:
            message = call(flag)
            self.assertFalse(message["diagnosis"]["issues_found"], (flag, message))  # real healthy row
            self.assertEqual(message["message"], "No issues found with this schedule", flag)
        for flag in ("1", "true"):  # control: a real force gets past the guard
            self.assertNotEqual(call(flag)["message"], "No issues found with this schedule", flag)


class TestStringFlagsCalledDirectly(VereningingenTestCase):
    """Endpoints no HTTP dispatch path reaches (or that are rate-limited): the strings, called directly."""

    def test_nuclear_truncate_refuses_every_false_confirmation(self):
        from scripts.migration import member_import_cleanup
        from verenigingen.utils import version_cleanup

        for func in (
            member_import_cleanup.nuclear_truncate_member_tables,
            version_cleanup.nuclear_truncate_version_and_deleted_tables,
        ):
            for flag in FALSE_FLAGS:
                with self.assertRaises(frappe.ValidationError, msg=(func.__name__, flag)):
                    func(confirm_nuclear_truncate=flag, dry_run=True)

    def test_install_workspace_stays_disabled_for_false_flags(self):
        from scripts.api_maintenance.fix_workspace import install_eboekhouden_workspace

        # A flag that wrongly passes reaches the file lookup; point it at nothing so the red run
        # cannot delete and recreate the Workspace.
        with patch("frappe.get_app_path", return_value="/nonexistent/e_boekhouden.json"):
            for flag in FALSE_FLAGS:
                result = install_eboekhouden_workspace(force_enable=flag)
                self.assertFalse(result["success"], flag)
                self.assertIn("DISABLED FOR SAFETY", result["message"], flag)
            result = install_eboekhouden_workspace(force_enable="true")  # control: the guard is passed
            self.assertIn("Workspace file not found", result["message"])

    def test_cleanup_invalid_schedules_dry_run_fails_closed(self):
        from scripts.cleanup import cleanup_invalid_member_schedules as module

        fake = {"details": [{"name": "NO-SUCH-SCHEDULE-2385", "member": "NO-SUCH-MEMBER"}]}
        with patch.object(module, "identify_invalid_schedules", return_value=fake):
            for flag in ("maybe", "", "true", "1", None):
                result = module.cleanup_invalid_schedules(dry_run=flag)
                self.assertTrue(result["success"], (flag, result))
                self.assertIs(result["dry_run"], True, (flag, result))
            # Control: a recognised "no" takes the real path, which fails on the missing schedule.
            for flag in ("false", "0"):
                result = module.cleanup_invalid_schedules(dry_run=flag)
                self.assertFalse(result["success"], (flag, result))

    def test_orphan_cleanups_dry_run_strings(self):
        """A recognised "no" asks for the real run; anything else stays a dry run.

        Called directly (an HTTP real run would commit deletions from the child). The real run only
        removes orphaned rows, which is what these endpoints are for.
        """
        from scripts.migration import member_import_cleanup as module

        for func in (
            module.cleanup_orphaned_chapter_members,
            module.cleanup_orphaned_addresses_and_contacts,
            module.force_cleanup_orphaned_schedules_and_invoices,
        ):
            for flag in ("maybe", "", "true", "1"):
                self.assertIs(func(dry_run=flag)["dry_run"], True, (func.__name__, flag))
            for flag in ("false", "0"):
                self.assertIs(func(dry_run=flag)["dry_run"], False, (func.__name__, flag))
