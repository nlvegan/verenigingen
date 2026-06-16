"""
Tests for verenigingen/api/schedule_maintenance.py

Admin tools that find and (destructively) clean up orphaned / misconfigured
Membership Dues Schedules.

History note: this module was previously un-importable because it applied
`@validate_csrf_token` (a whitelisted API endpoint taking `token: str`,
csrf_protection.py:170) as a decorator, which raised FrappeTypeError at import
time under Frappe v16 runtime typing-validation. It now correctly uses the
no-op `@require_csrf_token` decorator (csrf_protection.py:197), so the module
imports cleanly and all three endpoints run. Likewise the cleanup path no
longer caps at the first 10 records: it categorises the COMPLETE set via the
shared `_categorize_active_schedules()` helper.

The behavioural tests below import the API directly and assert the real
report / cleanup / prevention behaviour, including that cleanup processes ALL
matching schedules (not just the first 10).
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


def _load_api():
    """Import the API module; returns the module."""
    import importlib

    return importlib.import_module("verenigingen.api.schedule_maintenance")


class TestScheduleMaintenanceImportHealth(VereningingenTestCase):
    """The previously-broken CSRF decorator is fixed; the module imports and
    its endpoints are live."""

    def test_module_imports_cleanly_and_endpoints_callable(self):
        api = _load_api()
        for name in (
            "get_schedule_health_report",
            "cleanup_orphaned_schedules",
            "prevent_orphaned_schedules",
        ):
            self.assertTrue(callable(getattr(api, name)), f"{name} should be callable")

    def test_uses_require_csrf_token_noop_decorator(self):
        """The module must use the no-op `require_csrf_token` decorator (not the
        `validate_csrf_token` endpoint). Verify that decorator is a pass-through."""
        from verenigingen.utils.security.csrf_protection import require_csrf_token

        def sentinel():
            return "ok"

        wrapped = require_csrf_token(sentinel)
        # require_csrf_token is a no-op compatibility decorator.
        self.assertIs(wrapped, sentinel)
        self.assertEqual(wrapped(), "ok")


class TestScheduleMaintenance(VereningingenTestCase):
    """Behavioural tests for the (now importable) report / cleanup / prevention
    endpoints and the supporting helpers."""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_member_with_membership(self, *, minimum_amount=15.0):
        mtype = self.create_test_membership_type(minimum_amount=minimum_amount)
        member = self.create_test_member()
        membership = self.create_test_membership(member=member.name, membership_type=mtype.name)
        # The dues schedule controller requires an Active, *submitted* (docstatus=1)
        # membership. The factory inserts a draft, so submit it here. Submitting a
        # Membership auto-creates a dues schedule via on_submit; suppress that so
        # the test can create/control its own schedule (otherwise the controller
        # rejects a second active schedule for the member).
        if membership.docstatus == 0:
            membership.flags.skip_dues_schedule_creation = True
            membership.submit()
        return member, mtype

    def _make_active_schedule(self, *, dues_rate=None, minimum_amount=15.0):
        # The schedule's dues_rate may not be below the membership type's minimum,
        # so create with a valid rate. The inappropriate-zero-rate scenarios zero
        # it out afterwards via _persist_zero_rate (set_value bypasses validation).
        if dues_rate is None:
            dues_rate = max(minimum_amount, 15.0)
        member, mtype = self._make_member_with_membership(minimum_amount=minimum_amount)
        schedule = self.create_test_dues_schedule(
            member=member.name,
            membership_type=mtype.name,
            dues_rate=dues_rate,
        )
        return schedule, member, mtype

    def _persist_orphaned_member(self, schedule_name):
        # Make the schedule reference a non-existent Member. We must delete the
        # Member ROW DIRECTLY (raw SQL) rather than via frappe.delete_doc: the
        # Member's on_trash cascades into
        # MemberCleanupService.handle_member_deletion(), which would delete THIS
        # schedule too and leave nothing orphaned. Deleting the row directly
        # leaves schedule.member pointing at a now-missing Member, which is
        # exactly the orphaned state under test. (Any leftover tracked docs are
        # cleaned up best-effort in teardown; a missing row is harmless there.)
        member = frappe.db.get_value("Membership Dues Schedule", schedule_name, "member")
        for mship in frappe.get_all("Membership", filters={"member": member}, pluck="name"):
            frappe.db.sql("DELETE FROM `tabMembership` WHERE name = %s", mship)
        frappe.db.sql("DELETE FROM `tabMember` WHERE name = %s", member)
        return member

    def _persist_zero_rate(self, schedule_name):
        frappe.db.set_value(
            "Membership Dues Schedule", schedule_name, "dues_rate", 0, update_modified=False
        )

    def _persist_template(self):
        mtype = self.create_test_membership_type(minimum_amount=15.0)
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.update(
            {
                "is_template": 1,
                "schedule_name": f"MaintTpl-{frappe.generate_hash(length=8)}",
                "membership_type": mtype.name,
                "dues_rate": 15.0,
                "contribution_mode": "Income-Based",
                "currency": "EUR",
                "status": "Active",
                "minimum_amount": 5.0,
                "suggested_amount": 15.0,
            }
        )
        schedule.save()
        self.track_doc("Membership Dues Schedule", schedule.name)
        return schedule

    def _schedule_status(self, name):
        return frappe.db.get_value("Membership Dues Schedule", name, "status")

    # The endpoints are @frappe.whitelist()-decorated, so an in-process call
    # returns the OperationResult SERIALIZED to a dict, not the object itself.
    # Success: {"success": True, "data": {...}, "meta"/"message": ...}
    # Failure: {"success": False, "error": {"message", "errors": [...]}, ...}
    def _ok_data(self, result):
        """Assert a serialized OperationResult dict is a success, return its data."""
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("success"), msg=str(result.get("error")))
        return result["data"]

    def _fail_errors(self, result):
        """Assert a serialized OperationResult dict is a failure, return its errors."""
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        return result.get("error", {}).get("errors", [])

    def _real_cleanup(self, api, issue_type):
        """Invoke the destructive (dry_run=False) cleanup, returning its data dict.

        The destructive path used to be dead in production: it called
        frappe.db.begin() AFTER the audit decorators had already written rows in
        the same transaction, so START TRANSACTION tripped Frappe's
        implicit-commit guard. That is now fixed (the explicit begin() was
        removed), so this exercises the real cancellation path.
        """
        # Flush pending fixture writes so we exercise the endpoint from a clean
        # transaction. The base test case tears down via tracked-doc deletion,
        # not transaction rollback, so an intermediate commit is safe.
        frappe.db.commit()
        return self._ok_data(api.cleanup_orphaned_schedules(issue_type, dry_run=False))

    # ------------------------------------------------------------------
    # get_schedule_health_report
    # ------------------------------------------------------------------
    def test_health_report_categorises_each_issue_type_exactly(self):
        api = _load_api()
        healthy, _, _ = self._make_active_schedule()

        orphan_sched, _, _ = self._make_active_schedule()
        self._persist_orphaned_member(orphan_sched.name)

        template = self._persist_template()

        zero_sched, _, _ = self._make_active_schedule()
        self._persist_zero_rate(zero_sched.name)

        data = self._ok_data(api.get_schedule_health_report())

        orphan_names = [s["name"] for s in data["issues"]["orphaned_members"]["schedules"]]
        zero_names = [s["name"] for s in data["issues"]["inappropriate_zero_rates"]["schedules"]]

        self.assertIn(orphan_sched.name, orphan_names)
        self.assertIn(zero_sched.name, zero_names)

        for key in ("orphaned_members", "orphaned_types", "inappropriate_zero_rates"):
            names = [s["name"] for s in data["issues"][key]["schedules"]]
            self.assertNotIn(healthy.name, names)
            self.assertNotIn(template.name, names)

        self.assertGreaterEqual(data["issues"]["orphaned_members"]["count"], 1)
        self.assertGreaterEqual(data["issues"]["inappropriate_zero_rates"]["count"], 1)
        self.assertGreaterEqual(data["template_schedules"], 1)

        rec_types = {r.get("params", {}).get("issue_type") for r in data["recommendations"]}
        self.assertIn("orphaned_members", rec_types)
        self.assertIn("inappropriate_zero_rates", rec_types)

    def test_health_report_zero_rate_with_free_type_is_healthy(self):
        api = _load_api()
        sched, _, _ = self._make_active_schedule(minimum_amount=0.0)
        self._persist_zero_rate(sched.name)

        data = self._ok_data(api.get_schedule_health_report())
        zero_names = [
            s["name"] for s in data["issues"]["inappropriate_zero_rates"]["schedules"]
        ]
        self.assertNotIn(sched.name, zero_names)

    # ------------------------------------------------------------------
    # cleanup_orphaned_schedules
    # ------------------------------------------------------------------
    def test_cleanup_dry_run_does_not_mutate(self):
        api = _load_api()
        sched, _, _ = self._make_active_schedule()
        self._persist_orphaned_member(sched.name)

        data = self._ok_data(api.cleanup_orphaned_schedules("orphaned_members", dry_run=True))
        self.assertTrue(data["dry_run"])
        self.assertGreaterEqual(data["processed"], 1)

        self.assertEqual(self._schedule_status(sched.name), "Active")
        self.assertEqual(
            frappe.db.count(
                "Comment",
                {"reference_doctype": "Membership Dues Schedule", "reference_name": sched.name},
            ),
            0,
        )

    def test_cleanup_real_run_cancels_and_writes_audit_comment(self):
        api = _load_api()
        sched, _, _ = self._make_active_schedule()
        self._persist_orphaned_member(sched.name)

        data = self._real_cleanup(api, "orphaned_members")
        self.assertFalse(data["dry_run"])
        self.assertEqual(self._schedule_status(sched.name), "Cancelled")

        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Membership Dues Schedule",
                "reference_name": sched.name,
                "comment_type": "Comment",
            },
            fields=["content"],
        )
        self.assertEqual(len(comments), 1)
        self.assertIn("Automatically cancelled by schedule maintenance tool", comments[0]["content"])
        self.assertIn("no longer exists", comments[0]["content"])

    def test_cleanup_invalid_issue_type_fails(self):
        api = _load_api()
        errors = self._fail_errors(api.cleanup_orphaned_schedules("not_a_real_issue", dry_run=True))
        self.assertTrue(any("Invalid issue type" in e for e in errors))

    def test_cleanup_healthy_schedule_is_not_flagged_for_cleanup(self):
        # A freshly created healthy schedule (present member + present membership
        # type, non-zero rate) must not be selected by ANY cleanup issue type.
        # Use dry_run=True so this stays deterministic regardless of other
        # schedules left in the DB by sibling tests. We assert on THIS
        # schedule rather than a global processed==0 (other tests may leave
        # unrelated problem schedules committed).
        api = _load_api()
        sched, _, _ = self._make_active_schedule()
        for issue_type in ("orphaned_members", "orphaned_types", "inappropriate_zero_rates"):
            data = self._ok_data(api.cleanup_orphaned_schedules(issue_type, dry_run=True))
            self.assertTrue(data["dry_run"])
            flagged = [a["schedule"] for a in data.get("actions", [])]
            self.assertNotIn(
                sched.name,
                flagged,
                msg=f"healthy schedule wrongly flagged for {issue_type}",
            )
        self.assertEqual(self._schedule_status(sched.name), "Active")

    def test_cleanup_zero_rate_real_run_cancels(self):
        api = _load_api()
        sched, _, _ = self._make_active_schedule()
        self._persist_zero_rate(sched.name)

        self._real_cleanup(api, "inappropriate_zero_rates")
        self.assertEqual(self._schedule_status(sched.name), "Cancelled")

    def test_cleanup_inappropriate_zero_rates_targets_ALL_not_just_first_10(self):
        """Regression guard for the (now-fixed) [:10] cap bug.

        cleanup of 'inappropriate_zero_rates' (and 'orphaned_types') previously
        read problem_schedules from the health report's display lists, which are
        sliced to the first 10, silently capping cleanup at 10. The fix routes
        cleanup through the shared `_categorize_active_schedules()` helper, which
        returns the COMPLETE list. We seed >10 and assert the cleanup SELECTS all
        of them.

        We exercise this via the dry_run path: it iterates the full problem set
        and reports every record it WOULD cancel. The dry_run action list and
        total_found are what prove the cap is gone — if cleanup still re-read the
        sliced health-report list, at most 10 of our 12 would appear.

        (Note: the health report's *display* `schedules` lists are still sliced
        to 10, but its `count` reflects the true total — that is intended.)
        """
        api = _load_api()
        seeded = []
        for _ in range(12):
            sched, _, _ = self._make_active_schedule()
            self._persist_zero_rate(sched.name)
            seeded.append(sched.name)

        # The health report COUNT (not sliced) must see all 12.
        report_data = self._ok_data(api.get_schedule_health_report())
        self.assertGreaterEqual(
            report_data["issues"]["inappropriate_zero_rates"]["count"],
            12,
            "Health report should COUNT all 12 zero-rate schedules (count is not sliced)",
        )

        # Cleanup must TARGET all 12 (not cap at 10). dry_run iterates the full
        # categorized list; `processed` (== number of cleanup_actions built) and
        # `total_found` are NOT sliced, so both must reach at least our 12. If the
        # old [:10] cap were still in place, both would be <= 10 despite 12 seeded.
        # (The response's `actions` preview IS sliced to 20, so we assert on the
        # counts, not the preview list.)
        data = self._ok_data(api.cleanup_orphaned_schedules("inappropriate_zero_rates", dry_run=True))
        self.assertTrue(data["dry_run"])
        self.assertGreaterEqual(
            data["total_found"], 12, "cleanup must find all 12 zero-rate schedules, not cap at 10"
        )
        self.assertGreaterEqual(
            data["processed"], 12, "cleanup must process all 12 zero-rate schedules, not cap at 10"
        )
        # The previewed actions are all cancellations on the destructive path.
        for action in data["actions"]:
            self.assertEqual(action["action"], "would_cancel")

    # ------------------------------------------------------------------
    # prevent_orphaned_schedules
    # ------------------------------------------------------------------
    def test_prevent_flags_member_without_active_membership(self):
        api = _load_api()
        sched, member, _ = self._make_active_schedule()
        for mship in frappe.get_all(
            "Membership", filters={"member": member.name, "status": "Active"}, pluck="name"
        ):
            frappe.db.set_value("Membership", mship, "status", "Cancelled")

        data = self._ok_data(api.prevent_orphaned_schedules())
        inactive = [w for w in data["warnings"] if w["type"] == "inactive_membership"]
        self.assertEqual(len(inactive), 1)
        self.assertIn(sched.name, [s["name"] for s in inactive[0]["schedules"]])

    def test_prevent_flags_inappropriate_zero_rate(self):
        api = _load_api()
        sched, _, _ = self._make_active_schedule()
        self._persist_zero_rate(sched.name)

        data = self._ok_data(api.prevent_orphaned_schedules())
        zero = [w for w in data["warnings"] if w["type"] == "inappropriate_zero_rates"]
        self.assertEqual(len(zero), 1)
        self.assertIn(sched.name, [s["name"] for s in zero[0]["schedules"]])

    # ------------------------------------------------------------------
    # _generate_maintenance_recommendations
    # ------------------------------------------------------------------
    def test_recommendations_each_issue_type(self):
        api = _load_api()
        recs = api._generate_maintenance_recommendations(3, 2, 1)
        by_type = {r.get("params", {}).get("issue_type"): r for r in recs if "params" in r}

        self.assertEqual(by_type["orphaned_members"]["priority"], "high")
        self.assertIn("3", by_type["orphaned_members"]["description"])
        self.assertEqual(by_type["orphaned_types"]["priority"], "medium")
        self.assertEqual(by_type["inappropriate_zero_rates"]["priority"], "medium")

    def test_recommendations_healthy_case(self):
        api = _load_api()
        recs = api._generate_maintenance_recommendations(0, 0, 0)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["priority"], "info")
        self.assertNotIn("params", recs[0])

    def test_recommendations_partial(self):
        api = _load_api()
        recs = api._generate_maintenance_recommendations(0, 0, 5)
        types = {r.get("params", {}).get("issue_type") for r in recs}
        self.assertEqual(types, {"inappropriate_zero_rates"})

    # ------------------------------------------------------------------
    # _get_cancellation_reason
    # ------------------------------------------------------------------
    def test_cancellation_reason_per_type(self):
        api = _load_api()
        sd = {"member": "MEM-X", "membership_type": "TYPE-Y"}
        self.assertIn("MEM-X", api._get_cancellation_reason(sd, "orphaned_members"))
        self.assertIn("no longer exists", api._get_cancellation_reason(sd, "orphaned_members"))
        self.assertIn("TYPE-Y", api._get_cancellation_reason(sd, "orphaned_types"))
        self.assertIn("zero rate", api._get_cancellation_reason(sd, "inappropriate_zero_rates"))
        self.assertIn("weird", api._get_cancellation_reason(sd, "weird"))
