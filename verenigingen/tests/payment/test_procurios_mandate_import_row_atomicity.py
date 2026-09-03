# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""A Procurios Mandate Import row reported "skipped" must leave nothing behind (#698).

``_create_mandate`` and ``_update_cancellation`` write a SEPA Mandate with no
savepoint anywhere in the file (measured: zero hits for ``grep -n savepoint``
before this fix). ``_process_single_row``'s catch-all then reports any
post-write failure as ``("skipped", "")``, while the batch loop
(``csv_import_processor.process_import``) commits at the end of every batch
regardless -- the exact divergence #570 fixed for Member Import, filed here
because it recurs, unfixed, in these two sibling importers.

## Why the fault is injected where it is

``SEPA Mandate.after_insert``/``on_update`` (via
``sepa_mandate_lifecycle_service.handle_mandate_creation`` /
``handle_mandate_update``) catch every exception internally and return a
result dict -- measured: their own outer ``except Exception`` never
re-raises. So there is no naturally-reachable failure through that path. The
fault is instead injected by patching the hook method itself at the class
level (``SEPAMandate.after_insert`` / ``.on_update``), the same technique
``test_savepoint_rollback_cannot_mask_the_error.py`` uses to patch
``frappe.local.db.rollback`` for one test, and the membership-import
atomicity suite uses to patch ``Membership.on_submit``. This is a REAL
exception raised from a REAL Frappe hook, invoked synchronously from inside
``mandate.insert()`` / ``mandate.save()`` -- not a mock of the unit under
test. Restored via ``addCleanup``.

Cache-bookkeeping writes (``caches.existing_mandate_by_id[...] = {...}``,
``members_with_active_mandate``, ``member_to_active_count``) are deliberately
made only AFTER the savepoint is released, not before -- a DB rollback cannot
undo a plain Python dict write, so if those had happened while the write was
still unconfirmed, a later row in the same batch could read a cache entry
that does not match what actually persisted.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_procurios_mandate_import import (
    _create_active_sepa_mandate,
    _create_member_with_procurios_id,
    _empty_skip_counters,
    _make_mandate_row,
    _recent_cancellation_date,
)
from verenigingen.tests.support.non_resumable_errors import deadlock
from verenigingen.tests.support.procurios_import_stubs import _create_stub_import_doc
from verenigingen.verenigingen_payments.doctype.procurios_mandate_import import (
    procurios_mandate_import as _pmi_module,
)
from verenigingen.verenigingen_payments.doctype.sepa_mandate.sepa_mandate import SEPAMandate


def _break_after_insert(testcase, exc=None):
    """``SEPAMandate.after_insert`` raises -- AFTER the real INSERT has run."""
    original = SEPAMandate.after_insert
    error = exc or RuntimeError("boom-after-mandate-insert")

    def _boom(self):
        raise error

    SEPAMandate.after_insert = _boom
    testcase.addCleanup(setattr, SEPAMandate, "after_insert", original)


def _break_on_update(testcase, exc=None):
    """``SEPAMandate.on_update`` raises -- AFTER the real UPDATE has run."""
    original = SEPAMandate.on_update
    error = exc or RuntimeError("boom-after-mandate-save")

    def _boom(self):
        raise error

    SEPAMandate.on_update = _boom
    testcase.addCleanup(setattr, SEPAMandate, "on_update", original)


def _break_release_savepoint(testcase, exc=None):
    """``release_savepoint_if_present`` raises, as seen through the name bound
    inside ``procurios_mandate_import`` (a plain ``from ... import`` copies the
    reference into that module's namespace, so patching
    ``transaction_errors.release_savepoint_if_present`` would not be seen by
    ``_create_mandate``/``_update_cancellation`` -- this patches the copy they
    actually call).

    This is the seam that discriminates the two cache-mutation orderings
    (#698 review, finding 4): in the fixed code, `release_savepoint_if_present`
    is the FIRST statement in ``else``, before any cache write, so a raise here
    means the cache is never touched. In the pre-fix ordering (cache writes
    inside ``try``, before ``else`` even runs), the cache would already hold
    the write regardless of what this raises.
    """
    original = _pmi_module.release_savepoint_if_present
    error = exc or RuntimeError("boom-releasing-savepoint")

    def _boom(save_point):
        raise error

    _pmi_module.release_savepoint_if_present = _boom
    testcase.addCleanup(setattr, _pmi_module, "release_savepoint_if_present", original)


class TestProcuriosMandateCreateRowAtomicity(EnhancedTestCase):
    def test_a_created_mandate_reported_skipped_leaves_no_mandate_behind(self):
        """Before the fix: mandate.insert()'s INSERT succeeds, after_insert then
        throws, `_process_single_row` reports ("skipped", "") -- and the SEPA
        Mandate must not be in the database on this same connection."""
        _create_member_with_procurios_id(self, "ATOM-1")
        _break_after_insert(self)
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="ATOM-M-1", debiteur_id="ATOM-1")

        status, name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "skipped", errors)
        self.assertFalse(
            frappe.db.exists("SEPA Mandate", {"mandate_id": "ATOM-M-1"}),
            "a row the import reports as not imported must not be in the database",
        )
        self.assertEqual(counters["error"], 1)

    def test_control_a_clean_row_is_still_created(self):
        """Without this, "no mandate found" above would also pass if the savepoint
        fix had started rolling back every row, not just failing ones."""
        _create_member_with_procurios_id(self, "ATOM-2")
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="ATOM-M-2", debiteur_id="ATOM-2")

        status, name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "created", errors)
        self.assertTrue(frappe.db.exists("SEPA Mandate", {"mandate_id": "ATOM-M-2"}))
        self.assertEqual(
            caches.existing_mandate_by_id.get("ATOM-M-2", {}).get("name"),
            name,
            "the cache must still be updated on the success path",
        )

    def test_a_deadlock_during_creation_is_not_swallowed_as_skipped(self):
        """The other half: a 1213 must propagate out of `_process_single_row`
        rather than being reported as one skipped row -- #700 makes the engine
        loop abandon the import on this, but only if this layer lets it through."""
        _create_member_with_procurios_id(self, "ATOM-3")
        _break_after_insert(self, exc=deadlock())
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="ATOM-M-3", debiteur_id="ATOM-3")

        with self.assertRaises(frappe.QueryDeadlockError):
            doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(counters["error"], 0, "a deadlock must not be counted as a row error")

    def test_a_failed_release_does_not_leave_the_cache_ahead_of_the_db(self):
        """Cache mutations happen strictly AFTER the savepoint release, not
        merely alongside it on the success path (#698 review, finding 4).

        Reverting that ordering (cache writes moved back inside the `try`,
        before `else` even runs) makes this test fail: the cache would already
        hold the mandate regardless of what the release call does.
        """
        _create_member_with_procurios_id(self, "ATOM-7")
        _break_release_savepoint(self)
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="ATOM-M-7", debiteur_id="ATOM-7")

        status, _name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "skipped", errors)
        self.assertNotIn(
            "ATOM-M-7",
            caches.existing_mandate_by_id,
            "the cache must not be updated when the savepoint release itself failed",
        )


class TestProcuriosMandateUpdateRowAtomicity(EnhancedTestCase):
    def test_an_updated_mandate_reported_skipped_is_not_left_cancelled(self):
        """`_update_cancellation` calls `mandate.save()` for real; on_update then
        throws, so the mandate must stay Active."""
        member = _create_member_with_procurios_id(self, "ATOM-4")
        existing = _create_active_sepa_mandate(member.name, "ATOM-M-4", "NL91ABNA0417164300")
        _break_on_update(self)
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(
            mandate_id="ATOM-M-4", debiteur_id="ATOM-4", cancelled_date=_recent_cancellation_date()
        )

        status, _name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "skipped", errors)
        existing.reload()
        self.assertEqual(
            existing.status,
            "Active",
            "a row reported as not imported must not have altered the existing mandate",
        )
        self.assertIn(
            member.name,
            caches.members_with_active_mandate,
            "the cache must not have been decremented for a save that did not persist",
        )

    def test_control_a_clean_cancellation_still_updates(self):
        member = _create_member_with_procurios_id(self, "ATOM-5")
        existing = _create_active_sepa_mandate(member.name, "ATOM-M-5", "NL91ABNA0417164300")
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(
            mandate_id="ATOM-M-5", debiteur_id="ATOM-5", cancelled_date=_recent_cancellation_date()
        )

        status, _name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "updated", errors)
        existing.reload()
        self.assertEqual(existing.status, "Cancelled")
        self.assertNotIn(member.name, caches.members_with_active_mandate)

    def test_a_deadlock_during_update_is_not_swallowed_as_skipped(self):
        member = _create_member_with_procurios_id(self, "ATOM-6")
        _create_active_sepa_mandate(member.name, "ATOM-M-6", "NL91ABNA0417164300")
        _break_on_update(self, exc=deadlock())
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(
            mandate_id="ATOM-M-6", debiteur_id="ATOM-6", cancelled_date=_recent_cancellation_date()
        )

        with self.assertRaises(frappe.QueryDeadlockError):
            doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(counters["error"], 0, "a deadlock must not be counted as a row error")

    def test_a_failed_release_does_not_leave_the_cache_ahead_of_the_db_on_update(self):
        """The update-path twin of the create-path test in the sibling class."""
        member = _create_member_with_procurios_id(self, "ATOM-8")
        _create_active_sepa_mandate(member.name, "ATOM-M-8", "NL91ABNA0417164300")
        _break_release_savepoint(self)
        doc = _create_stub_import_doc("Procurios Mandate Import")
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(
            mandate_id="ATOM-M-8", debiteur_id="ATOM-8", cancelled_date=_recent_cancellation_date()
        )

        status, _name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "skipped", errors)
        self.assertIn(
            member.name,
            caches.members_with_active_mandate,
            "the cache must not have been decremented when the savepoint release itself failed",
        )
