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

import os
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
