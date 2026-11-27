"""#3086: the two orphan-cleanup admin tools run in production, for admins only.

``cleanup_orphaned_schedules`` and ``cleanup_orphaned_membership_data``
(``services/billing/invoice_management.py``, wired from ``admin_tools.py``) used to carry
``@development_only_api``, which refuses every call when ``developer_mode`` is off, so the tool
page could never run them in production. The maintainer ruled (2026-11-27) to lift that and gate
them as admin tools instead.

Everything is driven through the real WSGI dispatch (``run_wsgi_cases``) on a ``developer_mode=0``
site. Fixtures are real rows: one orphaned schedule (its Member row removed) and one live schedule
that must survive. ``max_cleanup`` is sent as a STRING, because ``frappe.call`` delivers every
argument over HTTP as one.

Usage:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_admin_cleanup_tools_prod_3086
"""

import json

import frappe

from verenigingen.tests.api import test_schedule_maintenance as _schedule_tests
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    operation_result,
    run_wsgi_cases,
)
from verenigingen.tests.utils.base import VereningingenTestCase

MODULE = "verenigingen.services.billing.invoice_management"
SCHEDULES = api_path(f"{MODULE}.cleanup_orphaned_schedules")
MEMBERSHIP_DATA = api_path(f"{MODULE}.cleanup_orphaned_membership_data")


class TestAdminCleanupToolsInProduction3086(
    _schedule_tests.TestScheduleMaintenance, CommittedLoginUsersMixin, VereningingenTestCase
):
    """Borrows the schedule fixtures from test_schedule_maintenance (functions, not its tests)."""

    for _name in [n for n in vars(_schedule_tests.TestScheduleMaintenance) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    def setUp(self):
        super().setUp()
        users = self._create_login_users(
            admin="Verenigingen Administrator",
            member="Verenigingen Member",
            staff="Verenigingen Staff",
            treasurer="Verenigingen Treasurer",
            sysmgr_bare=("Verenigingen Member", ("System Manager",)),
        )
        self.admin, self.member_user, self.staff = users["admin"], users["member"], users["staff"]
        self.treasurer, self.sysmgr_bare = users["treasurer"], users["sysmgr_bare"]
        self._types = []
        self.addCleanup(self._cleanup_schedules_3086)

    def _cleanup_schedules_3086(self):
        frappe.db.rollback()
        for mtype in self._types:
            for name in frappe.get_all(
                "Membership Dues Schedule", filters={"membership_type": mtype}, pluck="name"
            ):
                frappe.delete_doc("Membership Dues Schedule", name, force=True, ignore_permissions=True)
            if frappe.db.exists("Membership Type", mtype):
                frappe.delete_doc("Membership Type", mtype, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_committed_orphan_and_live_3086(self):
        orphan, _m, otype = self._make_active_schedule()
        self._persist_orphaned_member(orphan.name)
        live, _m, ltype = self._make_active_schedule()
        self._types += [otype.name, ltype.name]
        frappe.db.commit()  # the WSGI child is another DB connection
        return orphan.name, live.name

    def _create_live_schedules_3086(self, count):
        for _ in range(count):
            _s, _m, mtype = self._make_active_schedule()
            self._types.append(mtype.name)
        frappe.db.commit()  # the WSGI child is another DB connection

    def _call_3086(self, endpoint, user, payload):
        case = {
            "name": "c",
            "endpoint": endpoint,
            "login": {"usr": user, "pwd": self.password},
            "csrf": "valid",
            "json": payload,
        }
        return run_wsgi_cases(case)["c"]

    def test_the_site_is_production_like(self):
        self.assertFalse(frappe.conf.developer_mode, "@development_only_api is only refused when developer_mode=0")

    def test_admin_can_dry_run_both_tools_and_sees_the_orphan(self):
        orphan, live = self._create_committed_orphan_and_live_3086()
        for endpoint in (SCHEDULES, MEMBERSHIP_DATA):
            response = self._call_3086(endpoint, self.admin, {"dry_run": "true", "max_cleanup": "500"})
            self.assertEqual(response["status"], 200, (endpoint, response["body"][:400]))
            result = operation_result(response)
            self.assertTrue(result["success"], (endpoint, result))
            items = result["data"].get("processed_items") or result["data"]["orphaned_details"]
            names = [item["name"] for item in items]
            self.assertIn(orphan, names, endpoint)
            self.assertNotIn(live, names, endpoint)
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", orphan))  # a dry run deletes nothing

    def test_non_admins_are_refused_and_nothing_is_deleted(self):
        orphan, live = self._create_committed_orphan_and_live_3086()
        for user in (self.member_user, self.staff):
            for endpoint in (SCHEDULES, MEMBERSHIP_DATA):
                response = self._call_3086(endpoint, user, {"dry_run": "false", "max_cleanup": "500"})
                self.assertNotEqual(response["status"], 200, (user, endpoint, response["body"][:300]))
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", orphan))
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", live))

    def test_the_gate_is_critical_not_high(self):
        """Pins the decorator: critical refuses Staff and a bare System Manager role at the gate; a Treasurer passes the
        gate and is stopped by the in-function role check (417), so that check stays covered.

        high_security_api(ADMIN) admits Staff at the gate (#2774), so it would change both results.
        """
        for endpoint in (SCHEDULES, MEMBERSHIP_DATA):
            gate = self._call_3086(endpoint, self.sysmgr_bare, {"dry_run": "true"})
            self.assertEqual(gate["status"], 403, (endpoint, gate["body"][:300]))
            self.assertIn("Access denied", gate["body"], endpoint)
            # Staff is admitted by the HIGH tier (#2774) and would then reach the in-function 417.
            staff = self._call_3086(endpoint, self.staff, {"dry_run": "true"})
            self.assertEqual(staff["status"], 403, (endpoint, staff["body"][:300]))
            self.assertIn("Access denied", staff["body"], endpoint)
            inner = self._call_3086(endpoint, self.treasurer, {"dry_run": "true"})
            self.assertEqual(inner["status"], 417, (endpoint, inner["body"][:300]))
            self.assertIn("Insufficient permissions", inner["body"], endpoint)

    def test_real_run_deletes_only_the_orphan_with_a_string_max_cleanup(self):
        for endpoint in (SCHEDULES, MEMBERSHIP_DATA):
            orphan, live = self._create_committed_orphan_and_live_3086()
            response = self._call_3086(endpoint, self.admin, {"dry_run": "false", "max_cleanup": "500"})
            self.assertEqual(response["status"], 200, (endpoint, response["body"][:400]))
            self.assertTrue(operation_result(response)["success"], (endpoint, response["body"][:600]))
            frappe.db.rollback()  # drop this connection's snapshot before reading the child's commit
            self.assertFalse(frappe.db.exists("Membership Dues Schedule", orphan), endpoint)
            self.assertTrue(frappe.db.exists("Membership Dues Schedule", live), endpoint)

    def test_an_orphan_behind_many_live_schedules_is_still_found(self):
        """The scan must be an orphan query, not "look at the first N schedules".

        With ``max_cleanup=1`` the old scan read only the 3 newest non-template schedules,
        so an orphan older than 3 live ones was reported as "No orphaned dues schedules".
        """
        orphan, _live = self._create_committed_orphan_and_live_3086()
        self._create_live_schedules_3086(3)
        response = self._call_3086(SCHEDULES, self.admin, {"dry_run": "true", "max_cleanup": "1"})
        self.assertEqual(response["status"], 200, response["body"][:400])
        data = operation_result(response)["data"]
        self.assertIn(orphan, [d["name"] for d in data["orphaned_details"]], data)
