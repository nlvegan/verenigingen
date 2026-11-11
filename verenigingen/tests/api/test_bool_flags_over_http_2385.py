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
from verenigingen.utils.boolean_utils import is_confirmed, is_dry_run

# Not-a-yes values. "nan"/"inf"/"0.5"/"1e-5" and an Arabic-Indic digit parse as a non-zero float, so
# ``cbool`` would have let them through a confirmation guard.
FALSE_FLAGS = ("0", "false", 0, False, "maybe", "", "nan", "inf", "0.5", "1e-5", "\u0661")

# critical_api rate limits are tight (the truncate endpoints allow 2 per user per hour, others 5):
# each test user makes at most that many calls to one endpoint, so adding a case to a loop over
# HTTP here can trip the limit. Put extra values in the direct-call tests instead.

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


class TestIsConfirmed(VereningingenTestCase):
    def test_only_an_explicit_yes_confirms(self):
        for value in (True, "1", "true", "TRUE", "yes", "on", " true ", 1):
            self.assertTrue(is_confirmed(value), repr(value))
        for value in FALSE_FLAGS + (None, "2", "-1", "truee"):
            self.assertFalse(is_confirmed(value), repr(value))


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
            response = self._run(key, {"confirm_nuclear_truncate": "nan", "dry_run": True})
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
        """Control for the above: a recognised "no" is a real run.

        Only ``cleanup_test_members_only`` with a pattern that matches no Member: every other
        endpoint here acts site-wide, so a real-run control would strip other tests' rows.
        """
        extra = {"email_patterns": ["zz-no-such-member-%@nowhere.invalid"]}
        for flag in ("false", "0", False):
            response = self._run("test_members", {**extra, "dry_run": flag})
            self.assertEqual(response["status"], 200, (flag, response["body"][:300]))
            body = json.loads(response["body"])["message"]
            data = body.get("data", body) if isinstance(body, dict) else body
            self.assertIs(data["dry_run"], False, (flag, data))


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

    def _cleanup_seeded_chapter(self, name):
        frappe.db.rollback()
        if frappe.db.exists("Chapter", name):
            frappe.delete_doc("Chapter", name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def _seed_orphans(self):
        """One Chapter with an orphan Chapter Member row and a dangling Chapter Role reference.

        Inserted with db_insert (link validation would refuse them); rolled back at teardown.
        """
        chapter = self.create_test_chapter()
        self.addCleanup(self._cleanup_seeded_chapter, chapter.name)
        member_row = frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "members",
                "name": f"orphan-{frappe.generate_hash(length=8)}",
                "member": "NO-SUCH-MEMBER-2385",
            }
        )
        member_row.db_insert()
        board_row = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "name": f"dangling-{frappe.generate_hash(length=8)}",
                "volunteer": "NO-SUCH-VOLUNTEER-2385",
                "chapter_role": "NO-SUCH-ROLE-2385",
            }
        )
        board_row.db_insert()
        return chapter.name, member_row.name, board_row.name

    def test_unrecognised_dry_run_leaves_seeded_orphans_alone(self):
        """A real row for the wrong behaviour to find: the dry run sees it and must not touch it.

        No real-run control: both endpoints act on every Chapter on the site (and commit), which
        cannot be scoped to this fixture.
        """
        from scripts.migration import member_import_cleanup as module

        chapter, member_row, board_row = self._seed_orphans()
        for flag in ("maybe", "", "true", "1"):
            found = module.cleanup_orphaned_chapter_members(dry_run=flag)
            self.assertIs(found["dry_run"], True, flag)
            self.assertIn(chapter, [c["chapter"] for c in found["chapters_affected"]], flag)  # seen
            self.assertEqual(found["orphaned_removed"], 0, flag)
            self.assertTrue(frappe.db.exists("Chapter Member", member_row), flag)  # not removed
            scan = module.scan_and_clear_broken_links(target_doctypes=["Chapter Role"], dry_run=flag)
            scan = scan.get("data", scan)
            self.assertIs(scan["dry_run"], True, flag)
            self.assertGreaterEqual(scan["total_broken"], 1, flag)  # seen
            self.assertEqual(
                frappe.db.get_value("Chapter Board Member", board_row, "chapter_role"),
                "NO-SUCH-ROLE-2385",
                flag,
            )  # not cleared

    def test_other_dry_run_endpoints_fail_closed(self):
        """No side effects: the deleting helper is stubbed and the inputs name nothing real."""
        from verenigingen.utils import orphaned_child_table_cleanup as orphans

        with patch.object(orphans, "_batch_delete_orphans", return_value=0) as delete:
            for func in (
                orphans.cleanup_orphaned_child_tables,
                orphans.cleanup_member_child_tables_only,
                orphans.cleanup_volunteer_child_tables_only,
            ):
                for flag in ("maybe", "", "true"):
                    result = func(dry_run=flag)
                    data = result.get("data", result) if isinstance(result, dict) else result.data
                    self.assertIs(data["dry_run"], True, (func.__name__, flag, data))
            delete.assert_not_called()

    def test_mollie_debug_dry_run_fails_closed(self):
        """process_discovered_payments creates Payment Entries: the checker is stubbed."""
        from verenigingen.templates.pages import mollie_payments_debug as page

        checker = "verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker.BulkPaymentChecker"
        service = "verenigingen.templates.pages.mollie_payments_debug.MollieDebugService"
        with patch.object(page, "has_mollie_debug_access", return_value=True), patch(
            checker + ".process_discovered_payments", return_value={}
        ) as process, patch(service + ".sync_membership_end_dates_from_mollie", return_value={}) as sync:
            for flag in ("maybe", "", "true"):
                frappe.cache().delete(f"bulk_payment_process_limit:{frappe.session.user}")
                page.process_discovered_payments(["tr_7UhSN1zuXS"], dry_run=flag)
                self.assertIs(process.call_args.kwargs["dry_run"], True, flag)
                page.sync_membership_end_dates_from_mollie(dry_run=flag)
                self.assertIs(sync.call_args.kwargs["dry_run"], True, flag)
