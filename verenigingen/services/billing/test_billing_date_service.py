# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/billing_date_service.py

  - calculate_next_invoice_date: pure delegation (stub schedule OK; only reads attrs)
  - set_billing_day / initialize_next_invoice_date: branch logic
  - update_schedule_dates / advance_schedule_dates / _update_member_next_invoice_date:
    operate on REAL persisted schedules + members (these call .save()/db.set_value)

No business logic mocked.
"""

import frappe
from frappe.utils import add_years, getdate, today

from verenigingen.services.billing.billing_date_service import (
    BillingDateService,
    get_billing_date_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _sched_stub(**kwargs):
    defaults = {
        "name": "TEST-BDS-SCHED",
        "billing_frequency": "Monthly",
        "next_invoice_date": None,
        "last_invoice_date": None,
        "last_invoice_coverage_end": None,
        "custom_frequency_number": None,
        "custom_frequency_unit": None,
        "member": None,
        "billing_day": None,
        "is_template": 0,
        "doctype": "Membership Dues Schedule",
    }
    defaults.update(kwargs)
    d = frappe._dict(defaults)
    return d


class TestCalculateNextInvoiceDate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_billing_date_service()

    def test_factory_returns_service(self):
        self.assertIsInstance(self.service, BillingDateService)

    def test_explicit_from_date_monthly(self):
        sched = _sched_stub(billing_frequency="Monthly")
        self.assertEqual(
            self.service.calculate_next_invoice_date(sched, from_date="2025-01-15"),
            getdate("2025-02-15"),
        )

    def test_uses_next_invoice_date_when_no_from_date(self):
        sched = _sched_stub(billing_frequency="Quarterly", next_invoice_date="2025-01-15")
        self.assertEqual(self.service.calculate_next_invoice_date(sched), getdate("2025-04-15"))

    def test_defaults_to_today_when_no_dates(self):
        sched = _sched_stub(billing_frequency="Annual", next_invoice_date=None)
        self.assertEqual(self.service.calculate_next_invoice_date(sched), add_years(getdate(today()), 1))

    def test_custom_frequency_passthrough(self):
        sched = _sched_stub(
            billing_frequency="Custom",
            next_invoice_date="2025-01-10",
            custom_frequency_number=2,
            custom_frequency_unit="Weeks",
        )
        self.assertEqual(self.service.calculate_next_invoice_date(sched), getdate("2025-01-24"))


class TestSetBillingDayAndInit(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_billing_date_service()
        self._committed = []

    def tearDown(self):
        for doctype, name in self._committed:
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def test_set_billing_day_no_member_defaults_to_one(self):
        sched = _sched_stub(member=None, billing_day=0)
        self.service.set_billing_day(sched)
        self.assertEqual(sched.billing_day, 1)

    def test_set_billing_day_uses_member_since_day(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        frappe.db.set_value("Member", member.name, "member_since", "2024-03-17")
        sched = _sched_stub(member=member.name, billing_day=0)
        self.service.set_billing_day(sched)
        self.assertEqual(sched.billing_day, 17)

    def test_set_billing_day_member_no_member_since_defaults_one(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        frappe.db.set_value("Member", member.name, "member_since", None)
        sched = _sched_stub(member=member.name, billing_day=0)
        self.service.set_billing_day(sched)
        self.assertEqual(sched.billing_day, 1)

    def test_set_billing_day_already_set_unchanged(self):
        sched = _sched_stub(member=None, billing_day=25)
        self.service.set_billing_day(sched)
        self.assertEqual(sched.billing_day, 25)


class TestSchedulePersistingMethods(EnhancedTestCase):
    """update_schedule_dates / advance_schedule_dates / member sync use real docs."""

    def setUp(self):
        super().setUp()
        self.service = get_billing_date_service()
        self._committed = []

    def tearDown(self):
        order = {"Membership Dues Schedule": 0, "Membership": 1, "Member": 2}
        for doctype, name in sorted(self._committed, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def _member_with_schedule(self, billing_frequency="Monthly"):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        membership = self.create_test_membership(member_name=member.name)
        self._committed.append(("Membership", membership.name))
        sched_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self._committed.append(("Membership Dues Schedule", sched_name))
        frappe.db.set_value(
            "Membership Dues Schedule",
            sched_name,
            {"billing_frequency": billing_frequency, "next_invoice_date": getdate("2025-01-15")},
        )
        frappe.db.commit()
        return member, frappe.get_doc("Membership Dues Schedule", sched_name)

    def test_update_schedule_dates_with_actual_invoice_date(self):
        member, sched = self._member_with_schedule("Monthly")
        self.service.update_schedule_dates(sched, actual_invoice_date="2025-02-10")
        sched.reload()
        self.assertEqual(getdate(sched.last_invoice_date), getdate("2025-02-10"))
        # monthly: next = posting + 1 month
        self.assertEqual(getdate(sched.next_invoice_date), getdate("2025-03-10"))
        # member next_invoice_date synced
        self.assertEqual(
            getdate(frappe.db.get_value("Member", member.name, "next_invoice_date")),
            getdate("2025-03-10"),
        )

    def test_update_schedule_dates_daily_uses_coverage_end(self):
        member, sched = self._member_with_schedule("Daily")
        frappe.db.set_value(
            "Membership Dues Schedule", sched.name, "last_invoice_coverage_end", getdate("2025-02-20")
        )
        sched.reload()
        self.service.update_schedule_dates(sched, actual_invoice_date="2025-02-10")
        sched.reload()
        # daily: next = coverage_end + 1 day = 2025-02-21
        self.assertEqual(getdate(sched.next_invoice_date), getdate("2025-02-21"))

    def test_update_schedule_dates_test_mode_fallback(self):
        member, sched = self._member_with_schedule("Monthly")
        # no actual_invoice_date -> fallback: last = old next; next = old next + 1 month
        self.service.update_schedule_dates(sched, actual_invoice_date=None)
        sched.reload()
        self.assertEqual(getdate(sched.last_invoice_date), getdate("2025-01-15"))
        self.assertEqual(getdate(sched.next_invoice_date), getdate("2025-02-15"))

    def test_advance_schedule_dates(self):
        member, sched = self._member_with_schedule("Monthly")
        self.service.advance_schedule_dates(sched)
        # in-memory updated
        self.assertEqual(getdate(sched.last_invoice_date), getdate("2025-01-15"))
        self.assertEqual(getdate(sched.next_invoice_date), getdate("2025-02-15"))
        # persisted
        self.assertEqual(
            getdate(frappe.db.get_value("Membership Dues Schedule", sched.name, "next_invoice_date")),
            getdate("2025-02-15"),
        )

    def test_advance_schedule_dates_no_next_date_is_noop(self):
        member, sched = self._member_with_schedule("Monthly")
        frappe.db.set_value("Membership Dues Schedule", sched.name, "next_invoice_date", None)
        sched.reload()
        # Should warn and return without raising or changing dates
        self.service.advance_schedule_dates(sched)
        self.assertIsNone(sched.next_invoice_date)

    def test_member_date_update_skipped_for_quit_member(self):
        member, sched = self._member_with_schedule("Monthly")
        frappe.db.set_value("Member", member.name, "status", "Quit")
        frappe.db.set_value("Member", member.name, "next_invoice_date", None)
        sched.reload()
        self.service.update_schedule_dates(sched, actual_invoice_date="2025-02-10")
        # member next_invoice_date should NOT be updated for Quit members
        self.assertIsNone(frappe.db.get_value("Member", member.name, "next_invoice_date"))


class TestInitializeNextInvoiceDate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_billing_date_service()

    def test_initialize_sets_today_for_new_non_template(self):
        # Build a brand-new (unsaved) schedule doc
        sched = frappe.new_doc("Membership Dues Schedule")
        sched.is_template = 0
        sched.next_invoice_date = None
        self.service.initialize_next_invoice_date(sched)
        self.assertEqual(getdate(sched.next_invoice_date), getdate(today()))

    def test_initialize_skips_template(self):
        sched = frappe.new_doc("Membership Dues Schedule")
        sched.is_template = 1
        sched.next_invoice_date = None
        self.service.initialize_next_invoice_date(sched)
        self.assertIsNone(sched.next_invoice_date)

    def test_initialize_skips_when_already_set(self):
        sched = frappe.new_doc("Membership Dues Schedule")
        sched.is_template = 0
        sched.next_invoice_date = getdate("2030-06-01")
        self.service.initialize_next_invoice_date(sched)
        self.assertEqual(getdate(sched.next_invoice_date), getdate("2030-06-01"))
