"""A record the drain could not delete must name the test that created it.

The drain already knew how much it leaked -- it counted `delete_failures` and
logged "N record(s) could not be deleted" -- but it discarded *which* records,
so the count was unusable. The cost then landed somewhere else entirely: a
later test in the same shard collides with the leftover and fails, naming
neither the record nor the test that produced it. Five failures across #326 and
#327 were of exactly that shape (a Bank Account, a Region, two row counts, a
Payment Ledger Entry), and none of them named a cause.

Attribution has to happen where the leak happens, because by the time it does
damage the responsible test has finished and the evidence is a row in a table
nobody is looking at (#328).
"""

import inspect
import os
import types
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _DrainProbe(EnhancedTestCase):
    """A real EnhancedTestCase whose `setUp` is never run.

    The drain is a method on the real class and depends on real class state
    (`DRAIN_EXEMPT_DOCTYPES`, the logger). Subclassing gets all of that
    honestly; instantiating without calling `setUp` keeps the harness -- and its
    master-data seeding -- out of these tests.
    """

    # Deliberately NO test_* methods: unittest collects TestCase subclasses by
    # type, not by name, so a `test_noop` here would be discovered and run --
    # dragging the whole EnhancedTestCase setUp in with it.


def _probe():
    # "runTest" is the one methodName TestCase accepts without the method
    # existing, which is what lets this class stay uncollected.
    probe = _DrainProbe("runTest")
    probe._captured_inserts = []
    probe._leaked_records = []
    return probe


class DrainRecordsWhatItCouldNotDeleteTest(unittest.TestCase):
    def setUp(self):
        self.suffix = frappe.generate_hash(length=6)
        self.created = []

    def tearDown(self):
        # Reverse order: the child has to go before its parent.
        for doctype, name in reversed(self.created):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def _make_undeletable_territory(self):
        """A Territory with a child resists even `force=True`.

        Verified rather than assumed: `frappe.delete_doc(..., force=True)` on it
        raises `NestedSetChildExistsError`. A Role held by a User, the other
        obvious candidate, deletes cleanly -- so it would have made this test
        pass for the wrong reason.
        """
        parent = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": f"zzleak-parent-{self.suffix}",
                "parent_territory": "All Territories",
                "is_group": 1,
            }
        ).insert()
        self.created.append(("Territory", parent.name))
        child = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": f"zzleak-child-{self.suffix}",
                "parent_territory": parent.name,
            }
        ).insert()
        self.created.append(("Territory", child.name))
        frappe.db.commit()
        return parent.name

    def test_a_record_that_survives_the_drain_is_recorded_by_name(self):
        parent = self._make_undeletable_territory()

        probe = _probe()
        probe._captured_inserts = [("Territory", parent)]
        probe._drain_captured_inserts()

        leaked = [(row["doctype"], row["name"]) for row in probe.leaked_records]
        self.assertIn(
            ("Territory", parent),
            leaked,
            "the drain could not delete this record and must say which one it was",
        )

    def test_the_recorded_leak_carries_the_reason(self):
        parent = self._make_undeletable_territory()

        probe = _probe()
        probe._captured_inserts = [("Territory", parent)]
        probe._drain_captured_inserts()

        row = next(r for r in probe.leaked_records if r["name"] == parent)
        self.assertTrue(row.get("error"), "a leak with no reason cannot be triaged")

    def test_a_drain_that_deletes_everything_records_nothing(self):
        """Guards the other direction: this must not report leaks that did not happen."""
        doc = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": f"zzleak-solo-{self.suffix}",
                "parent_territory": "All Territories",
            }
        ).insert()
        frappe.db.commit()

        probe = _probe()
        probe._captured_inserts = [("Territory", doc.name)]
        probe._drain_captured_inserts()

        self.assertEqual([], list(probe.leaked_records))
        self.assertFalse(frappe.db.exists("Territory", doc.name))


class _FakeFactory:
    """Minimal stand-in for the factory the tracked drain reads from."""

    def __init__(self, created_documents=None, core_records=None):
        self.created_documents = created_documents or []
        self.core = None
        if core_records is not None:
            self.core = types.SimpleNamespace(created_records=core_records)


class DrainSkipsUndeletableByDesignTest(unittest.TestCase):
    """Doctypes whose controller refuses deletion must not be retried forever.

    `SEPA Operation Audit Log`, `SEPA Batch Upload Log` and `Mollie Audit Log`
    each raise unconditionally in `on_trash` ("compliance requirement"). No
    cleanup can ever remove them, so every teardown re-attempts the delete and
    re-reports the same record -- permanent noise that would be frozen into any
    leak baseline.

    The exemption set existed but was consulted by only ONE of the two drains
    (#328).
    """

    def test_both_drains_honour_the_exemption_set(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        source = inspect.getsource(EnhancedTestCase._drain_tracked_documents)
        self.assertIn(
            "DRAIN_EXEMPT_DOCTYPES",
            source,
            "_drain_tracked_documents deletes without checking the exemption set, so "
            "adding a doctype to it silences only the captured-insert drain (#328)",
        )

    def test_ledger_derivatives_are_exempt(self):
        """GL Entry and Payment Ledger Entry have no independent existence.

        ERPNext refuses to cancel them individually ("Individual GL Entry cannot
        be cancelled. Please cancel related transaction.") because they belong to
        their parent voucher. Draining them directly can only fail; cancelling the
        parent is what removes them. Measured: exempting these took one module
        from 21 leaks to 2 (#328).
        """
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        for doctype in ("GL Entry", "Payment Ledger Entry"):
            self.assertIn(doctype, EnhancedTestCase.DRAIN_EXEMPT_DOCTYPES)

    def test_the_unconditional_refusers_are_exempt(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        for doctype in (
            "SEPA Operation Audit Log",
            "SEPA Batch Upload Log",
            "Mollie Audit Log",
        ):
            self.assertIn(
                doctype,
                EnhancedTestCase.DRAIN_EXEMPT_DOCTYPES,
                f"{doctype} refuses deletion in its own controller; draining it can "
                f"never succeed",
            )


class DrainCancelsSubmittedDocumentsTest(unittest.TestCase):
    """`force=True` does not bypass the submitted check.

    `frappe.model.delete_doc` runs `check_permission_and_not_submitted(doc)`
    BEFORE its `if not force:` guard, so a submitted document can never be
    force-deleted. It has to be cancelled first. This was the single largest
    leak class in the census (#328).
    """

    def setUp(self):
        self.created = []

    def tearDown(self):
        for name in self.created:
            try:
                doc = frappe.get_doc("Performance Optimization Setup", name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Performance Optimization Setup", name, force=True)
            except Exception:
                pass
        frappe.db.commit()

    def _submitted_doc(self):
        """A submittable doctype with one required field and a no-op on_submit."""
        doc = frappe.get_doc(
            {
                "doctype": "Performance Optimization Setup",
                "optimization_name": f"zzleak-{frappe.generate_hash(length=8)}",
            }
        ).insert()
        doc.submit()
        frappe.db.commit()
        self.created.append(doc.name)
        return doc.name

    def test_a_submitted_document_is_cancelled_and_deleted(self):
        name = self._submitted_doc()

        probe = _probe()
        probe._captured_inserts = [("Performance Optimization Setup", name)]
        probe._drain_captured_inserts()

        self.assertEqual(
            [], list(probe.leaked_records), "a submitted record must be cancelled, then deleted"
        )
        self.assertFalse(frappe.db.exists("Performance Optimization Setup", name))


class CoreFactoryRecordsAreOrderedTest(unittest.TestCase):
    """Core-factory records were drained LAST, after what depends on them.

    `test_data_factory.track_doc` records no priority, and the drain assigned
    core records `priority = 0` -- below Customer (3) and Address (3). So a
    core-created Sales Invoice outlived the Customer whose deletion it blocks,
    which is why 44 Customers leaked with "You can disable this Address instead
    of deleting it" (#328).
    """

    def test_a_core_tracked_invoice_drains_before_the_customer(self):
        """Observes the ORDER the drain actually removes in.

        Asserting only that the priority map ranks Sales Invoice above Customer
        would pass even with the fix reverted -- the map can be correct while the
        drain ignores it for core records, which is precisely the bug. So this
        drives the real `_drain_tracked_documents` and records what it removes,
        in order.
        """
        removed = []

        probe = _probe()
        probe.factory = _FakeFactory(
            created_documents=[{"doctype": "Customer", "name": "zz-cust", "priority": 3}],
            core_records=[{"doctype": "Sales Invoice", "name": "zz-si"}],
        )
        probe._remove_drained_record = lambda doctype, name: removed.append(doctype)

        probe._drain_tracked_documents()

        self.assertEqual(
            ["Sales Invoice", "Customer"],
            removed,
            "a core-tracked Sales Invoice pins the Customer's Address via "
            "customer_address, so it must be removed first",
        )

    def test_an_unknown_doctype_still_gets_a_priority(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        self.assertIsInstance(EnhancedTestCase._drain_priority_for("Some Unknown DocType"), int)


class DrainRunsAsAdministratorTest(unittest.TestCase):
    """tearDown drained as whatever user the test left behind.

    At least one controller refuses deletion based on `frappe.session.user`
    (`SEPA Audit Log`), and cleanup should not depend on which user a test
    happened to finish as. The drain asserts its own context (#328).
    """

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_the_drain_restores_administrator(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        source = inspect.getsource(EnhancedTestCase._drain_captured_inserts)
        self.assertIn(
            'set_user("Administrator")',
            source,
            "the drain must not depend on the session user the test left behind",
        )


class LeakCheckReportingTest(unittest.TestCase):
    """Warn by default, fail under the env flag -- the ErrorLogGuard contract.

    Deliberately the same shape as VERENIGINGEN_FAIL_ON_ERROR_LOG so the ratchet
    can be turned on for one CI job without reddening every local run.
    """

    ENV = "VERENIGINGEN_FAIL_ON_TEST_LEAK"

    def setUp(self):
        self._orig = os.environ.get(self.ENV)

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(self.ENV, None)
        else:
            os.environ[self.ENV] = self._orig

    def test_it_raises_when_the_flag_is_set(self):
        probe = _probe()
        probe._leaked_records = [{"doctype": "Territory", "name": "zz-x", "error": "boom"}]
        os.environ[self.ENV] = "1"
        with self.assertRaises(AssertionError) as caught:
            probe._finalize_leak_check()
        self.assertIn("zz-x", str(caught.exception))

    def test_it_only_warns_when_the_flag_is_unset(self):
        probe = _probe()
        probe._leaked_records = [{"doctype": "Territory", "name": "zz-x", "error": "boom"}]
        os.environ.pop(self.ENV, None)
        probe._finalize_leak_check()  # must not raise

    def test_no_leaks_is_silent(self):
        probe = _probe()
        os.environ[self.ENV] = "1"
        probe._finalize_leak_check()  # must not raise


if __name__ == "__main__":
    unittest.main()
