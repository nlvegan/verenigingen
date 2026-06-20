"""
Real-integration tests for ``verenigingen/api/fix_stuck_dues_schedule.py``
(admin remediation tooling — was ~13% covered, 112 missed lines).

These tests build a real Member + Membership Dues Schedule, then force the
classic "stuck" state (``last_invoice_date == next_invoice_date`` with no
matching Sales Invoice) by writing the dates directly to the DB so the
controller's ``validate`` does not normalise them away. The diagnose / fix /
find / notify endpoints are then driven end to end against that real data and
the resulting dict (the @*_api decorators authorize Administrator in test
context and return plain dicts) is asserted against values derived from the
fixtures.

No business logic is mocked. ``frappe.enqueue`` is never triggered by these
endpoints, so no queue guard is needed.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.api import fix_stuck_dues_schedule as api
from verenigingen.tests.utils.base import VereningingenTestCase


class TestFixStuckDuesScheduleAPI(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Stuck",
            last_name="Schedule",
            email=f"stuck.sched.{frappe.generate_hash(length=6)}@example.com",
        )
        self.membership_type = self.create_test_membership_type()
        # An ACTIVE membership is required by the dues-schedule validation.
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self.track_doc("Membership", membership.name)
        self.membership = membership

    # -------------------------------------------------------------- helpers

    def _deactivate_auto_schedules(self):
        """Submitting a Membership auto-creates an Active schedule; cancel it so
        the explicit test schedule is the sole active one (one active per member)."""
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def _make_schedule(self, billing_frequency="Daily", **kwargs):
        self._deactivate_auto_schedules()
        sched = frappe.new_doc("Membership Dues Schedule")
        sched.schedule_name = f"Stuck-{self.member.name}-{frappe.generate_hash(length=8)}"
        sched.member = self.member.name
        sched.membership = self.membership.name
        sched.membership_type = self.membership_type.name
        sched.currency = "EUR"
        sched.contribution_mode = "Income-Based"
        sched.dues_rate = self.membership_type.minimum_amount or 15.00
        sched.billing_frequency = billing_frequency
        sched.payment_method = "Bank Transfer"
        sched.status = "Active"
        sched.auto_generate = 1
        for key, value in kwargs.items():
            setattr(sched, key, value)
        sched.save()
        self.track_doc("Membership Dues Schedule", sched.name)
        return sched

    def _force_stuck(self, sched, on_date=None):
        """Write last == next directly, bypassing validate, to simulate the
        real stuck condition observed in production."""
        on_date = on_date or add_days(today(), -3)
        frappe.db.set_value(
            "Membership Dues Schedule",
            sched.name,
            {"last_invoice_date": on_date, "next_invoice_date": on_date},
            update_modified=False,
        )
        frappe.db.commit()
        return frappe.get_doc("Membership Dues Schedule", sched.name)

    # -------------------------------------------------------------- diagnose

    def test_diagnose_clean_schedule_reports_no_stuck_issue(self):
        sched = self._make_schedule()
        diag = api.diagnose_stuck_schedule(sched.name)
        self.assertEqual(diag["schedule_name"], sched.name)
        self.assertEqual(diag["member"], self.member.name)
        # A freshly created schedule has no last_invoice_date -> not stuck.
        self.assertFalse(diag["dates_equal"])
        self.assertNotIn("STUCK: last_invoice_date equals next_invoice_date", diag["issues_found"])
        # can_generate check always runs and is reported.
        self.assertIn("can_generate", diag)
        self.assertIn("can_generate_reason", diag)

    def test_diagnose_detects_stuck_no_invoice(self):
        sched = self._force_stuck(self._make_schedule())
        diag = api.diagnose_stuck_schedule(sched.name)
        self.assertTrue(diag["dates_equal"])
        self.assertIn("STUCK: last_invoice_date equals next_invoice_date", diag["issues_found"])
        # Member has a customer but no invoice on that date -> the "NO INVOICE
        # EXISTS" branch and recommended fix are populated.
        self.assertEqual(diag["customer"], self.member.customer)
        self.assertIn("NO INVOICE EXISTS for the last_invoice_date", diag["issues_found"])
        self.assertEqual(diag["recommended_fix"], "Reset dates to allow invoice generation")
        # generate-on-date math runs because next_invoice_date is set.
        self.assertIn("should_generate_today", diag)
        days_before = sched.invoice_days_before if sched.invoice_days_before is not None else 30
        expected_gen = add_days(getdate(sched.next_invoice_date), -days_before)
        self.assertEqual(diag["generate_on_date"], str(expected_gen))

    def test_diagnose_stuck_with_existing_invoice_omits_no_invoice_flag(self):
        sched = self._make_schedule()
        stuck_date = add_days(today(), -2)
        # Create a real Sales Invoice on the stuck date for the member's customer
        inv = self.create_test_sales_invoice(
            customer=self.member.customer, posting_date=stuck_date
        )
        self.assertEqual(frappe.db.get_value("Sales Invoice", inv.name, "customer"), self.member.customer)
        sched = self._force_stuck(sched, on_date=stuck_date)
        diag = api.diagnose_stuck_schedule(sched.name)
        self.assertIn("STUCK: last_invoice_date equals next_invoice_date", diag["issues_found"])
        # Invoice exists -> the "NO INVOICE EXISTS" branch must NOT fire.
        self.assertNotIn("NO INVOICE EXISTS for the last_invoice_date", diag["issues_found"])
        self.assertNotIn("recommended_fix", diag)

    # -------------------------------------------------------------- fix_stuck_schedule

    def test_fix_clean_schedule_without_force_is_noop(self):
        sched = self._make_schedule()
        res = api.fix_stuck_schedule(sched.name)
        self.assertFalse(res["success"])
        self.assertEqual(res["message"], "No issues found with this schedule")
        self.assertIn("diagnosis", res)

    def test_fix_stuck_daily_resets_dates(self):
        sched = self._force_stuck(self._make_schedule(billing_frequency="Daily"))
        res = api.fix_stuck_schedule(sched.name)
        self.assertTrue(res["success"])
        self.assertEqual(res["message"], "Schedule dates have been fixed")
        # Daily + last_invoice_date in the past -> next is moved to today and
        # last is cleared so generation can resume.
        self.assertEqual(res["changes"]["new_next_invoice_date"], str(getdate(today())))
        self.assertIsNone(res["changes"]["new_last_invoice_date"])
        reloaded = frappe.get_doc("Membership Dues Schedule", sched.name)
        self.assertIsNone(reloaded.last_invoice_date)
        self.assertEqual(getdate(reloaded.next_invoice_date), getdate(today()))

    def test_fix_stuck_monthly_advances_via_frequency(self):
        sched = self._force_stuck(
            self._make_schedule(billing_frequency="Monthly"), on_date=add_days(today(), -10)
        )
        old_date = sched.next_invoice_date
        res = api.fix_stuck_schedule(sched.name)
        self.assertTrue(res["success"])
        self.assertEqual(res["message"], "Schedule dates have been fixed")
        # Non-daily path uses calculate_next_invoice_date(old last_invoice_date).
        expected = sched.calculate_next_invoice_date(old_date)
        self.assertEqual(res["changes"]["new_next_invoice_date"], str(expected))
        self.assertIsNone(res["changes"]["new_last_invoice_date"])

    def test_fix_stuck_with_invoice_advances_period(self):
        sched = self._make_schedule(billing_frequency="Monthly")
        stuck_date = add_days(today(), -1)
        self.create_test_sales_invoice(
            customer=self.member.customer, posting_date=stuck_date
        )
        sched = self._force_stuck(sched, on_date=stuck_date)
        res = api.fix_stuck_schedule(sched.name)
        self.assertTrue(res["success"])
        # Invoice exists for the date -> advance to next period, do NOT clear last.
        self.assertEqual(res["message"], "Schedule advanced to next period")
        expected = sched.calculate_next_invoice_date(stuck_date)
        self.assertEqual(res["changes"]["new_next_invoice_date"], str(expected))
        self.assertIn("invoice_exists", res)

    def test_fix_force_on_clean_schedule_finds_no_fix(self):
        # force=True bypasses the "no issues" early return, but with dates not
        # equal there is nothing to fix -> "Unable to determine appropriate fix".
        sched = self._make_schedule()
        res = api.fix_stuck_schedule(sched.name, force=True)
        self.assertFalse(res["success"])
        self.assertEqual(res["message"], "Unable to determine appropriate fix")
        self.assertIn("diagnosis", res)

    # -------------------------------------------------------------- find_all_stuck_schedules

    def test_find_all_stuck_schedules_includes_type_a(self):
        sched = self._force_stuck(self._make_schedule(billing_frequency="Daily"))
        result = api.find_all_stuck_schedules()
        self.assertIn("total_stuck", result)
        self.assertIn("type_a_count", result)
        self.assertIn("type_b_count", result)
        names = [s["name"] for s in result["schedules"]]
        self.assertIn(sched.name, names)
        ours = next(s for s in result["schedules"] if s["name"] == sched.name)
        self.assertEqual(ours["stuck_type"], "Type A: Equal Dates")
        self.assertEqual(ours["severity"], "MEDIUM")
        # No invoice exists for that date -> invoice_exists is False (customer set).
        self.assertFalse(ours["invoice_exists"])

    def test_find_all_stuck_schedules_includes_type_b_overdue(self):
        # next far in the past, last different -> Type B (overdue). Monthly needs
        # >= 5 days overdue.
        sched = self._make_schedule(billing_frequency="Monthly")
        frappe.db.set_value(
            "Membership Dues Schedule",
            sched.name,
            {
                "last_invoice_date": add_days(today(), -60),
                "next_invoice_date": add_days(today(), -40),
            },
            update_modified=False,
        )
        frappe.db.commit()
        result = api.find_all_stuck_schedules()
        ours = [s for s in result["schedules"] if s["name"] == sched.name]
        self.assertTrue(ours, "overdue schedule should be detected as Type B")
        ours = ours[0]
        self.assertTrue(ours["stuck_type"].startswith("Type B"))
        # 40 days overdue -> CRITICAL severity.
        self.assertEqual(ours["severity"], "CRITICAL")
        self.assertGreaterEqual(ours["days_overdue"], 30)

    # -------------------------------------------------------------- check_and_notify_stuck_schedules

    def test_check_and_notify_runs_and_returns_structured_result(self):
        # Build one critical (Type A, no invoice) stuck schedule and run the
        # notifier. The endpoint always writes an Error Log "alert" (used as its
        # admin status channel), so mark those titles as expected.
        self._force_stuck(self._make_schedule(billing_frequency="Daily"))
        self.expectErrorLog(
            "Stuck Schedule",
            "Enhanced Stuck Schedule Alert Sent",
        )
        result = api.check_and_notify_stuck_schedules()
        self.assertTrue(result["success"])
        self.assertIn("type_breakdown", result)
        # At least our one critical schedule should be counted.
        self.assertGreaterEqual(result.get("stuck_count", 0), 1)
        self.assertIn("total_found", result)
