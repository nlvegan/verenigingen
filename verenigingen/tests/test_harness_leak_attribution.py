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
import pathlib
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

    def test_the_tracked_drain_skips_an_exempt_doctype(self):
        """Behavioural: asserting the source merely mentions the set is not enough.

        An earlier version of this test checked `inspect.getsource(...)` for the
        constant's name. It passed with the fix fully reverted, because the name
        still appeared in a comment.
        """
        removed = []

        probe = _probe()
        probe.factory = _FakeFactory(
            created_documents=[
                {"doctype": "Mollie Audit Log", "name": "zz-audit", "priority": 5},
                {"doctype": "Customer", "name": "zz-cust", "priority": 3},
            ]
        )
        probe._remove_drained_record = lambda doctype, name: removed.append(doctype)

        probe._drain_tracked_documents()

        self.assertEqual(
            ["Customer"],
            removed,
            "a doctype whose controller refuses deletion must not be retried by the "
            "tracked drain either",
        )

    def test_ledger_derivatives_are_NOT_exempt(self):
        """They are force-deletable, and were only ever blocked by our own bug.

        Both are `is_submittable = 0` with `docstatus = 1`, so a cancel-first check
        that keys on docstatus alone tries to cancel them and fails. Exempting them
        would hide rows the drain can genuinely remove.
        """
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        for doctype in ("GL Entry", "Payment Ledger Entry"):
            self.assertNotIn(doctype, EnhancedTestCase.DRAIN_EXEMPT_DOCTYPES)

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


class NonSubmittableRowsAreNotCancelledTest(unittest.TestCase):
    """`docstatus == 1` alone is not a test for "submitted".

    The framework gate is `meta.is_submittable and docstatus.is_submitted()`.
    Rows carry docstatus=1 on NON-submittable doctypes all the time -- erpnext
    calls `gle.submit()` on GL Entry, which is `is_submittable = 0`
    (erpnext/accounts/general_ledger.py:436), and child rows inherit docstatus
    from their parent.

    A cancel-first check keyed on docstatus alone tried to cancel those and
    failed, turning a force-delete that had always worked into a leak. This
    reproduces that shape without needing accounting fixtures: Territory is
    non-submittable, and the docstatus is written directly, exactly as erpnext
    does it to GL Entry.
    """

    def setUp(self):
        self.name = None

    def tearDown(self):
        if self.name:
            try:
                frappe.delete_doc("GL Entry", self.name, force=True, ignore_permissions=True)
            except Exception:
                pass
            frappe.db.commit()

    def test_a_non_submittable_row_with_docstatus_1_is_deleted_not_cancelled(self):
        """Uses a real GL Entry, because a generic stand-in does not reproduce this.

        A first version of this test used a Territory with docstatus forced to 1.
        It passed with the fix reverted -- `Document.cancel()` merely sets
        docstatus=2 and saves, with no submittable check, so cancelling a Territory
        SUCCEEDS and nothing leaks. The failure needs a controller that refuses,
        and GL Entry is the real one: `on_cancel` throws "Individual GL Entry
        cannot be cancelled" (erpnext/.../gl_entry.py:324) while the doctype is
        `is_submittable = 0` and erpnext still gives it docstatus=1.
        """
        doc = frappe.get_doc(
            {
                "doctype": "GL Entry",
                "account": frappe.db.get_value("Account", {"is_group": 0}, "name"),
                "company": frappe.db.get_value("Company", {}, "name"),
                "posting_date": frappe.utils.today(),
                "voucher_type": "Journal Entry",
                "voucher_no": f"zzgl-{frappe.generate_hash(length=8)}",
                # GL Entry requires one of these to be non-zero.
                "debit": 1,
                "credit": 0,
            }
        )
        # voucher_no is a dynamic link to a real Journal Entry. This row only has to
        # EXIST for the drain to act on it, so skip link validation rather than
        # building an entire voucher for a cleanup test.
        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        self.name = doc.name
        # Exactly what erpnext does to GL Entry: docstatus=1 on a non-submittable
        # doctype (general_ledger.py calls gle.submit()).
        frappe.db.set_value("GL Entry", doc.name, "docstatus", 1, update_modified=False)
        frappe.db.commit()

        probe = _probe()
        probe._captured_inserts = [("GL Entry", doc.name)]
        probe._drain_captured_inserts()

        self.assertEqual(
            [],
            list(probe.leaked_records),
            "a non-submittable row must be force-deleted, never routed through cancel",
        )
        self.assertFalse(frappe.db.exists("GL Entry", doc.name))
        self.name = None


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

    def test_the_factory_tracks_transactions_above_the_records_they_pin(self):
        """Reads the factory's OWN tracking priorities, from its source.

        A behavioural version of this test supplied its own priorities to a fake
        factory, so it exercised the drain's sort and nothing else -- reverting the
        factory's `priority=6` back to 4 left it green. The value that matters is
        the literal at the tracking call site, because `_drain_priority_for` is
        consulted only for core records that are NOT already tracked, so the map
        cannot correct an enhanced-factory record tracked too low.

        Parsed structurally rather than grepped: this asserts the argument's value,
        not that some string appears somewhere.
        """
        import ast as _ast

        from verenigingen.tests.fixtures import enhanced_test_factory as factory_module

        tree = _ast.parse(pathlib.Path(factory_module.__file__).read_text(encoding="utf-8"))
        tracked = {}
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            name = getattr(node.func, "attr", None)
            if name not in ("_track_test_document", "track_document"):
                continue
            if not node.args or not isinstance(node.args[0], _ast.Constant):
                continue
            doctype = node.args[0].value
            for kw in node.keywords:
                if kw.arg == "priority" and isinstance(kw.value, _ast.Constant):
                    tracked.setdefault(doctype, []).append(kw.value.value)

        member_priority = max(tracked.get("Member", [5]))
        for doctype in ("Sales Invoice", "Payment Entry"):
            self.assertTrue(tracked.get(doctype), f"no tracked priority found for {doctype}")
            self.assertTrue(
                all(p > member_priority for p in tracked[doctype]),
                f"{doctype} is tracked at {tracked[doctype]}, not above Member at "
                f"{member_priority}. MemberCleanupService keeps the Customer while the "
                f"Member still has either, so the Customer stays pinned.",
            )

    def test_an_unknown_doctype_still_gets_a_priority(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

        self.assertEqual(0, EnhancedTestCase._drain_priority_for("Some Unknown DocType"))


class DrainRunsAsAdministratorTest(unittest.TestCase):
    """tearDown drained as whatever user the test left behind.

    At least one controller refuses deletion based on `frappe.session.user`
    (`SEPA Audit Log`), and cleanup should not depend on which user a test
    happened to finish as. The drain asserts its own context (#328).
    """

    def setUp(self):
        """Leave the session as a non-Administrator, the way a real test can."""
        self._original_user = frappe.session.user
        frappe.set_user("Guest")

    def tearDown(self):
        frappe.set_user(self._original_user)

    def test_the_drain_switches_to_administrator(self):
        """Behavioural, and named for what the code does: it switches, not restores.

        The previous version asserted the literal `set_user("Administrator")`
        appeared in the source. That passed with the call deleted, as long as the
        string survived in a comment -- it could not fail for its stated reason.
        """
        probe = _probe()
        probe._captured_inserts = [("Territory", "zz-does-not-exist")]

        self.assertNotEqual("Administrator", frappe.session.user, "precondition")
        probe._drain_captured_inserts()

        self.assertEqual(
            "Administrator",
            frappe.session.user,
            "the drain must not inherit the session user the test finished as",
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
