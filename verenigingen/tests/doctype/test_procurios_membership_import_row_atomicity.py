# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""A Procurios Membership Import row reported "skipped" must leave nothing
behind (#698).

Both write paths -- ``_create_active_membership`` (a service call, an
existence check, then a `frappe.db.set_value` idempotency tag) and
``_create_historical_membership`` (``insert()`` then ``submit()``) -- have no
savepoint anywhere in the file (measured: zero hits for ``grep -n savepoint``
before this fix). ``_process_single_member``'s catch-all reports any
post-write failure as ``("skipped", "")`` while the batch loop commits at the
end of every batch regardless -- the same divergence #570 fixed for Member
Import.

## Where each fault is injected, and why

* **Active path**: `frappe.db.set_value` is patched to raise ONLY for
  `(doctype="Membership", fieldname="procurios_membership_id")` -- the exact
  write named in the issue (`:311`). Everything before it (the service call
  that creates the real Membership + real dues schedule) runs for real.

* **Historical path**: `Membership.on_submit` is patched to raise. By the time
  `on_submit` runs, `db_update()` has already written `docstatus=1` for this
  row -- so `membership.insert()` (a real write) and the docstatus flip (also
  a real write) have both landed before the fault fires, matching
  `transaction_errors.insert_and_submit_atomically`'s documented "throw inside
  on_submit leaves docstatus=1 written" scenario exactly. This mirrors the
  same technique `test_savepoint_rollback_cannot_mask_the_error.py` uses to
  patch `frappe.local.db.rollback` for one test, scoped and restored the same
  way.

Both patches are restored via ``addCleanup``.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.non_resumable_errors import deadlock
from verenigingen.tests.support.procurios_import_stubs import _create_stub_import_doc
from verenigingen.utils.csv.procurios_membership_validator import ProcuriosMembershipRow
from verenigingen.verenigingen.doctype.membership.membership import Membership

SETTINGS_FIELDS = (
    "csv_monthly_dues_schedule",
    "csv_quarterly_dues_schedule",
    "csv_annual_dues_schedule",
)


def _make_membership_row(**kw):
    defaults = dict(
        row_number=1,
        debiteur_id="ATOM-1",
        debiteur_naam="Atom Test",
        procurios_type="Maandlid",
        payment_period="Maandelijks",
        start_date="2022-11-27",
        dues_rate=2.5,
        procurios_membership_id="ATOM-MSHIP-1",
        status="Active",
        cancellation_date=None,
    )
    defaults.update(kw)
    return ProcuriosMembershipRow(**defaults)


def _break_membership_tag_write(testcase, exc=None):
    """`frappe.db.set_value` raises ONLY for `(dt="Membership", field="procurios_membership_id")`."""
    real_set_value = frappe.db.set_value
    error = exc or RuntimeError("boom-after-membership-create")

    def _boom(dt, dn, field=None, *args, **kwargs):
        if dt == "Membership" and field == "procurios_membership_id":
            raise error
        return real_set_value(dt, dn, field, *args, **kwargs)

    frappe.db.set_value = _boom
    testcase.addCleanup(setattr, frappe.db, "set_value", real_set_value)


def _break_active_submit(testcase, exc=None):
    """`Membership.on_submit` raises from INSIDE the active-creation service call.

    Unlike `_break_membership_tag_write` (which faults the outermost step of
    `_create_active_membership`), this fires several layers down the real call
    chain: `create_membership_from_csv` -> `_create_membership_unified_path`
    -> `create_membership_on_approval` -> `_get_or_create_membership` ->
    `membership.submit()` -> `on_submit`. That reaches (and proves the guard
    on) `create_membership_from_csv` and `create_membership_on_approval` --
    the fault fires during Step 3 of `create_membership_on_approval`, so
    Step 4's `_ensure_dues_schedule_exists` is never entered here; ITS guard
    is covered separately, by
    `TestEnsureDuesScheduleExistsNonResumableGuard` in
    `test_membership_creation_service.py`. Both used to catch this with a
    bare `except Exception` and either convert it to `frappe.ValidationError`
    (`create_membership_on_approval`) or swallow it (`create_membership_from_csv`)
    -- so a 1213 from deep inside a normal active-row import never reached
    `_process_single_member`'s guard at all.
    """
    original = Membership.on_submit
    error = exc or RuntimeError("boom-during-active-submit")

    def _boom(self):
        raise error

    Membership.on_submit = _boom
    testcase.addCleanup(setattr, Membership, "on_submit", original)


def _break_historical_submit(testcase, exc=None):
    """`Membership.on_submit` raises, AFTER `insert()` and the docstatus write."""
    original = Membership.on_submit
    error = exc or RuntimeError("boom-during-historical-submit")

    def _boom(self):
        raise error

    Membership.on_submit = _boom
    testcase.addCleanup(setattr, Membership, "on_submit", original)


class TestProcuriosMembershipActiveRowAtomicity(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.monthly_type = self.create_test_membership_type("AtomAct", amount=2.5)
        self._saved_settings = {
            f: frappe.db.get_single_value("Verenigingen Settings", f) for f in SETTINGS_FIELDS
        }
        settings = frappe.get_single("Verenigingen Settings")
        self.monthly_template = self.ensure_dues_schedule_template(
            f"Atom Active {self.monthly_type.name}",
            {
                "membership_type": self.monthly_type.name,
                "billing_frequency": "Monthly",
                "dues_rate": 2.5,
                "suggested_amount": 2.5,
                "minimum_amount": 1.25,
            },
        )
        settings.csv_monthly_dues_schedule = self.monthly_template.name
        settings.csv_quarterly_dues_schedule = self.ensure_dues_schedule_template("Atom Active Quarterly").name
        settings.csv_annual_dues_schedule = self.ensure_dues_schedule_template("Atom Active Annual").name
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in self._saved_settings.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    def _caches(self, doc):
        caches = doc._build_caches()
        caches.type_mapping = {"Maandlid": self.monthly_type.name}
        return caches

    def test_an_active_membership_reported_skipped_leaves_no_membership_behind(self):
        member = self.create_test_member(procurios_id="ATOM-ACT-1")
        _break_membership_tag_write(self)
        doc = _create_stub_import_doc("Procurios Membership Import")
        caches = self._caches(doc)
        counters = {"no_member": 0, "ambiguous_member": 0, "duplicate": 0, "already_active": 0, "error": 0}
        errors = []
        row = _make_membership_row(debiteur_id="ATOM-ACT-1", procurios_membership_id="ATOM-MSHIP-ACT-1")

        status, name = doc._process_single_member(row, errors, caches, counters)

        self.assertEqual(status, "skipped", errors)
        self.assertFalse(
            frappe.db.exists("Membership", {"member": member.name}),
            "a row the import reports as not imported must not be in the database",
        )
        self.assertEqual(counters["error"], 1)

    def test_control_a_clean_active_row_is_still_created(self):
        member = self.create_test_member(procurios_id="ATOM-ACT-2")
        doc = _create_stub_import_doc("Procurios Membership Import")
        caches = self._caches(doc)
        counters = {"no_member": 0, "ambiguous_member": 0, "duplicate": 0, "already_active": 0, "error": 0}
        errors = []
        row = _make_membership_row(debiteur_id="ATOM-ACT-2", procurios_membership_id="ATOM-MSHIP-ACT-2")

        status, name = doc._process_single_member(row, errors, caches, counters)

        self.assertEqual(status, "created", errors)
        self.assertTrue(frappe.db.exists("Membership", {"member": member.name, "status": "Active"}))

    def test_a_deadlock_during_active_creation_is_not_swallowed_as_skipped(self):
        member = self.create_test_member(procurios_id="ATOM-ACT-3")
        _break_membership_tag_write(self, exc=deadlock())
        doc = _create_stub_import_doc("Procurios Membership Import")
        caches = self._caches(doc)
        counters = {"no_member": 0, "ambiguous_member": 0, "duplicate": 0, "already_active": 0, "error": 0}
        errors = []
        row = _make_membership_row(debiteur_id="ATOM-ACT-3", procurios_membership_id="ATOM-MSHIP-ACT-3")

        with self.assertRaises(frappe.QueryDeadlockError):
            doc._process_single_member(row, errors, caches, counters)

        self.assertEqual(counters["error"], 0, "a deadlock must not be counted as a row error")

    def test_a_deadlock_three_layers_inside_active_creation_is_not_swallowed_either(self):
        """The deep-chain case: a deadlock from inside `Membership.submit()`,
        reached via `create_membership_from_csv` -> `_create_membership_unified_path`
        -> `create_membership_on_approval` -> `membership.submit()`.

        Proves the guards on `create_membership_from_csv` and
        `create_membership_on_approval` -- both used to have a bare
        `except Exception` with no `NON_RESUMABLE_DB_ERRORS` guard above it, so
        this deadlock never reached `_create_active_membership`'s own guard at
        all (swallowed, or converted to `ValidationError`, several frames
        below it). `_ensure_dues_schedule_exists`'s own guard is NOT exercised
        here -- the fault fires before Step 4 is reached -- see
        `TestEnsureDuesScheduleExistsNonResumableGuard` for that one.
        """
        member = self.create_test_member(procurios_id="ATOM-ACT-4")
        _break_active_submit(self, exc=deadlock())
        doc = _create_stub_import_doc("Procurios Membership Import")
        caches = self._caches(doc)
        counters = {"no_member": 0, "ambiguous_member": 0, "duplicate": 0, "already_active": 0, "error": 0}
        errors = []
        row = _make_membership_row(debiteur_id="ATOM-ACT-4", procurios_membership_id="ATOM-MSHIP-ACT-4")

        with self.assertRaises(frappe.QueryDeadlockError):
            doc._process_single_member(row, errors, caches, counters)

        # Not asserting absence of the Membership here: a REAL 1213 has the
        # database roll the whole transaction back before Python ever sees the
        # exception, but this is a Python-level simulation of that error (same
        # as `test_savepoint_rollback_cannot_mask_the_error.py`'s own deadlock
        # tests) -- nothing actually told MariaDB to roll back, so the row is
        # still visible on this connection. What matters, and is real here, is
        # that the exception reaches this far as itself rather than being
        # counted as an ordinary row error.
        self.assertEqual(counters["error"], 0, "a deadlock must not be counted as a row error")


class TestProcuriosMembershipHistoricalRowAtomicity(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.annual_type = self.create_test_membership_type("AtomHist", amount=20.0)

    def _caches(self, doc):
        caches = doc._build_caches()
        caches.type_mapping = {"Jaarlid": self.annual_type.name}
        return caches

    def _historical_row(self, **kw):
        defaults = dict(
            debiteur_naam="Atom Historical",
            procurios_type="Jaarlid",
            payment_period="Jaarlijks",
            start_date="2018-01-01",
            dues_rate=20.0,
            status="Cancelled",
            cancellation_date="2020-06-01",
        )
        defaults.update(kw)
        return _make_membership_row(**defaults)

    def test_a_historical_membership_reported_skipped_leaves_no_membership_behind(self):
        member = self.create_test_member(procurios_id="ATOM-HIST-1")
        _break_historical_submit(self)
        doc = _create_stub_import_doc("Procurios Membership Import")
        caches = self._caches(doc)
        counters = {"no_member": 0, "ambiguous_member": 0, "duplicate": 0, "already_active": 0, "error": 0}
        errors = []
        row = self._historical_row(debiteur_id="ATOM-HIST-1", procurios_membership_id="ATOM-MSHIP-HIST-1")

        status, name = doc._process_single_member(row, errors, caches, counters)

        self.assertEqual(status, "skipped", errors)
        self.assertFalse(
            frappe.db.exists("Membership", {"member": member.name}),
            "a row the import reports as not imported must not be in the database, "
            "docstatus=1 or not",
        )
        self.assertEqual(counters["error"], 1)

    def test_control_a_clean_historical_row_is_still_created(self):
        member = self.create_test_member(procurios_id="ATOM-HIST-2")
        doc = _create_stub_import_doc("Procurios Membership Import")
        caches = self._caches(doc)
        counters = {"no_member": 0, "ambiguous_member": 0, "duplicate": 0, "already_active": 0, "error": 0}
        errors = []
        row = self._historical_row(debiteur_id="ATOM-HIST-2", procurios_membership_id="ATOM-MSHIP-HIST-2")

        status, name = doc._process_single_member(row, errors, caches, counters)

        self.assertEqual(status, "created", errors)
        self.assertTrue(frappe.db.exists("Membership", {"member": member.name, "status": "Cancelled"}))

    def test_a_deadlock_during_historical_submit_is_not_swallowed_as_skipped(self):
        member = self.create_test_member(procurios_id="ATOM-HIST-3")
        _break_historical_submit(self, exc=deadlock())
        doc = _create_stub_import_doc("Procurios Membership Import")
        caches = self._caches(doc)
        counters = {"no_member": 0, "ambiguous_member": 0, "duplicate": 0, "already_active": 0, "error": 0}
        errors = []
        row = self._historical_row(debiteur_id="ATOM-HIST-3", procurios_membership_id="ATOM-MSHIP-HIST-3")

        with self.assertRaises(frappe.QueryDeadlockError):
            doc._process_single_member(row, errors, caches, counters)

        self.assertEqual(counters["error"], 0, "a deadlock must not be counted as a row error")
