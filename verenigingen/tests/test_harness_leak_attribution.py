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

import contextlib
import io
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


class SharedFixturesAreNotCapturedTest(unittest.TestCase):
    """Where a fixture is BUILT is the stable fact; which doctypes it touches is not.

    Exempting doctypes one at a time does not converge. Building
    TEST-Payment-Integration-Company was measured to insert 94 Accounts, 5
    Warehouses, 2 Cost Centers, the Company and a Property Setter; exempting Account
    and Company left Cost Center and Warehouse to fail the next CI run with "Could
    not find Row #1: Cost Center: Main - TPIC" (65 occurrences on one shard alone).

    So the marker goes where the shared fixture is built, and covers everything that
    build touches -- now and later.
    """

    def setUp(self):
        self.suffix = frappe.generate_hash(length=6)
        self.created = []

    def tearDown(self):
        for doctype, name in reversed(self.created):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def _territory(self, label):
        doc = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": f"zz{label}-{self.suffix}",
                "parent_territory": "All Territories",
                "is_group": 0,
            }
        ).insert()
        self.created.append(("Territory", doc.name))
        return doc

    def test_capture_ignores_inserts_made_while_suspended(self):
        """Both halves asserted: suspending must not switch capture off for good."""
        from verenigingen.tests.fixtures.enhanced_test_factory import suspend_insert_capture

        probe = _probe()
        probe._captured_inserts = []
        probe._install_insert_capture()
        try:
            with suspend_insert_capture():
                shared = self._territory("shared")
            own = self._territory("own")
        finally:
            probe._uninstall_insert_capture()

        captured = [name for _doctype, name in probe._captured_inserts]
        self.assertIn(own.name, captured, "capture must resume once the block exits")
        self.assertNotIn(
            shared.name,
            captured,
            "a row created while capture is suspended belongs to the shared fixture, "
            "not to the test that happened to trigger it",
        )

    def test_the_company_builder_runs_with_capture_suspended(self):
        """Asserts the builder BODY sees the flag set.

        Calling `get_eur_test_company` and checking that nothing was captured would
        pass for the wrong reason: on any site where the company already exists the
        helper short-circuits and inserts nothing at all.
        """
        from verenigingen.tests.fixtures import enhanced_test_factory as factory_module
        from verenigingen.tests.support import sepa_test_company as company_module

        seen = {}
        original = company_module._build_and_verify

        def spy(company_name):
            seen["suspended"] = factory_module._insert_capture_suspended
            return company_name

        company_module._build_and_verify = spy
        try:
            company_module._create_eur_test_company()
        finally:
            company_module._build_and_verify = original

        self.assertTrue(
            seen.get("suspended"),
            "the whole company build -- chart of accounts, warehouses, cost centers "
            "-- must run with insert capture suspended",
        )

    def test_shared_fixture_suspends_capture_and_restores_it(self):
        from verenigingen.tests.fixtures import enhanced_test_factory as factory_module

        seen = {}

        @factory_module.shared_fixture
        def helper():
            seen["suspended"] = factory_module._insert_capture_suspended
            return "value"

        self.assertEqual("value", helper(), "the decorator must not swallow the return")
        self.assertTrue(seen.get("suspended"))
        self.assertFalse(
            factory_module._insert_capture_suspended,
            "capture must be restored afterwards, or every later test in the process "
            "silently stops being cleaned up",
        )

    def test_the_shared_master_helpers_are_declared_shared(self):
        """The accounting masters whose loss was actually observed in CI.

        Each of these is get-or-created once per site and then depended on by every
        later test: the company's income accounts (35x "no is_group Income account"),
        its cost centers (65x "Could not find Row #1: Cost Center: Main - TPIC") and
        its bank account ("no is_group Bank account").
        """
        for name in (
            "_get_or_create_income_account",
            "_get_or_create_cost_center",
            "_ensure_test_bank_account",
            "_ensure_company_chart_of_accounts",
            "_ensure_company_cost_center",
            "_ensure_company_defaults",
        ):
            method = getattr(EnhancedTestCase, name)
            self.assertTrue(
                hasattr(method, "__wrapped__"),
                f"{name} creates shared master data and must be @shared_fixture, or "
                f"the captured-insert drain will claim its rows for one test",
            )

    def test_no_shared_fixture_helper_is_decorated_in_one_copy_and_not_its_clone(self):
        """A helper family must not disagree with itself about being shared.

        `test_the_shared_master_helpers_are_declared_shared` above enforces six
        names ON `EnhancedTestCase`, so a helper copied into a test module is not
        covered by it at all. That is how #444 happened: three Mollie/donation
        account helpers existed in three modules, `@shared_fixture` in ONE of them,
        and whichever module ran first decided whether the accounts survived.

        Measured on a purged `test_site_4` with the fixtures deleted first (a run
        with them already present proves nothing -- they were never captured
        inserts, so the drain never touched them):

        ==============================================  ==========  ==============
        module                                          decorated?  after the run
        ==============================================  ==========  ==============
        test_donation_subscription_activation           no          all three GONE
        test_recurring_donation_charge                  yes         all three kept
        ==============================================  ==========  ==============

        Both were green. The decorator was the only difference.

        Deliberately narrow, so that it stays at zero and stays believable. A copy
        is only flagged when ALL of these hold:

        * some other module defines the same private helper name WITH the
          decorator -- i.e. the fix landed once and its clone was missed;
        * this copy actually calls `.insert(`, so there are rows to claim;
        * it does not build them under `suspend_insert_capture()` instead;
        * its class reaches `EnhancedTestCase`, which is the only base that
          installs the captured-insert hook. `VereningingenTestCase` is a SIBLING
          of it, not a subclass, so an undecorated helper there is exposed to
          nothing -- two of the six raw name-divergences on develop were that, and
          a third was two unrelated methods that merely share a name.
        """
        flagged = self._divergent_shared_fixture_copies()
        self.assertEqual(
            [],
            flagged,
            "these helpers are @shared_fixture in one module and undecorated in "
            "another that inserts rows into a drained class:\n  "
            + "\n  ".join(flagged),
        )

    # -- the AST walk behind the gate above ---------------------------------

    def _divergent_shared_fixture_copies(self):
        import ast
        import collections

        import verenigingen

        root = pathlib.Path(verenigingen.__file__).parent

        def is_shared(fn):
            return any(
                (d.attr if isinstance(d, ast.Attribute) else getattr(d, "id", None))
                == "shared_fixture"
                for d in fn.decorator_list
            )

        def inserts(fn):
            return any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "insert"
                for n in ast.walk(fn)
            )

        def suspends(fn):
            return any(
                isinstance(n, ast.With) and "suspend_insert_capture" in ast.unparse(n.items)
                for n in ast.walk(fn)
            )

        # (module, class) -> base names, plus (module, local name) -> (module, real
        # name) for every `from X import Y as Z`. Both are needed:
        #
        # * 253 class names in this app are defined in more than one module, so a
        #   global name -> bases map resolves some of them to the wrong class;
        # * `BaseTestCase` is a CLASS in tests/utils/test_utils.py (an
        #   EnhancedTestCase subclass) and an ALIAS for VereningingenTestCase in
        #   tests/base_test_case.py. Six modules import the alias. Resolving by
        #   ClassDef alone finds only the class -- unambiguously, and wrongly --
        #   and would fail CI on six classes that are not drained at all.
        bases = {}
        aliases = {}
        copies = collections.defaultdict(list)
        for path in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        local = alias.asname or alias.name
                        aliases[(str(path), local)] = (node.module, alias.name)
            for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
                bases[(str(path), cls.name)] = [ast.unparse(b).split("[")[0] for b in cls.bases]
                for fn in cls.body:
                    if isinstance(fn, ast.FunctionDef) and fn.name.startswith("_"):
                        copies[fn.name].append(
                            (
                                path.relative_to(root.parent),
                                cls.name,
                                fn.lineno,
                                is_shared(fn),
                                inserts(fn),
                                suspends(fn),
                            )
                        )

        def reaches_drained_base(module, cls_name, seen=None):
            """Does this class inherit from `EnhancedTestCase`?

            Resolves each base in its OWN module first, and only then repo-wide --
            and repo-wide only when the name is unambiguous. An ambiguous name
            resolves to nothing, so the gate under-reports rather than failing CI
            on a class it guessed wrong about.
            """
            seen = seen or set()
            if (module, cls_name) in seen:
                return False
            seen.add((module, cls_name))
            if cls_name == "EnhancedTestCase":
                return True

            for base in bases.get((module, cls_name), []):
                # 1. defined in this very module
                if (module, base) in bases:
                    if reaches_drained_base(module, base, seen):
                        return True
                    continue
                # 2. imported into this module -- follow the alias to its real name,
                #    which is the only way to tell `BaseTestCase` (the class) from
                #    `BaseTestCase` (an alias for a class that is NOT drained).
                target = aliases.get((module, base))
                if target:
                    real_module_suffix, real_name = target
                    if real_name == "EnhancedTestCase":
                        return True
                    candidates = [
                        m
                        for (m, c) in bases
                        if c == real_name
                        and m.endswith(real_module_suffix.replace(".", "/") + ".py")
                    ]
                    if len(candidates) == 1 and reaches_drained_base(
                        candidates[0], real_name, seen
                    ):
                        return True
                    continue
                # 3. last resort: repo-wide, and only when unambiguous
                elsewhere = [m for (m, c) in bases if c == base]
                if len(elsewhere) == 1 and reaches_drained_base(elsewhere[0], base, seen):
                    return True
            return False

        flagged = []
        for name, found in sorted(copies.items()):
            if len({c[0] for c in found}) < 2 or not any(c[3] for c in found):
                continue
            for path, cls, line, shared, ins, susp in found:
                if not shared and ins and not susp and reaches_drained_base(str(root.parent / path), cls):
                    flagged.append(f"{name}  <-  {path}:{line} ({cls})")
        return flagged


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
        self.account = None

    def tearDown(self):
        if self.name:
            try:
                frappe.delete_doc("GL Entry", self.name, force=True, ignore_permissions=True)
            except Exception:
                pass
        if self.account:
            try:
                frappe.delete_doc("Account", self.account, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def _own_account(self):
        """Create the account this test posts against, rather than borrowing one.

        Borrowing was narrowed twice and failed twice, each time on a property of
        whatever row the site happened to hand back. First an unfiltered `get_value`
        (which returns the NEWEST row) drew "Test Sales Income - _TC", a
        Profit-and-Loss account: "Cost Center is required for 'Profit and Loss'
        account" (CI 31704796808 shard 5). Adding `root_type: Asset` then drew
        "Advance Paid - TCP1" -- an Asset account whose `account_type` is Payable,
        so GL Entry demanded a party: "Supplier is required against Payable account"
        (CI 31715798775 shard 4).

        A plain leaf with no `account_type` needs neither: not P&L, so no cost
        center; not Receivable/Payable, so no party. Owning it is the only way to
        know that.
        """
        parent = None
        for row in frappe.get_all(
            "Account",
            filters={"is_group": 1, "root_type": "Asset"},
            fields=["name", "company"],
            order_by="lft",
        ):
            if frappe.db.exists("Company", row.company):
                parent = row
                break
        if not parent:
            self.skipTest("no Asset group account on this site to parent a test account under")

        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": f"zzgl-acct-{frappe.generate_hash(length=6)}",
                "parent_account": parent.name,
                "company": parent.company,
                "is_group": 0,
            }
        ).insert()
        frappe.db.commit()
        self.account = account.name
        return account

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
        account = self._own_account()

        doc = frappe.get_doc(
            {
                "doctype": "GL Entry",
                "account": account.name,
                "company": account.company,
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

    @staticmethod
    @contextlib.contextmanager
    def _swallow_stdout():
        """Keep these fabricated rows out of the shard log.

        `_finalize_leak_check` PRINTS, and `scripts/testing/check_test_leaks.py`
        greps the shard log for exactly those lines. Left uncaptured, the
        `Territory::zz-x boom` invented here is indistinguishable from a real leak
        and this module carries a permanent, fictional entry in the baseline --
        a ratchet measuring its own test data.
        """
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            yield buffer

    def test_it_raises_when_the_flag_is_set(self):
        probe = _probe()
        probe._leaked_records = [{"doctype": "Territory", "name": "zz-x", "error": "boom"}]
        os.environ[self.ENV] = "1"
        with self._swallow_stdout(), self.assertRaises(AssertionError) as caught:
            probe._finalize_leak_check()
        self.assertIn("zz-x", str(caught.exception))

    def test_it_only_warns_when_the_flag_is_unset(self):
        probe = _probe()
        probe._leaked_records = [{"doctype": "Territory", "name": "zz-x", "error": "boom"}]
        os.environ.pop(self.ENV, None)
        with self._swallow_stdout() as out:
            probe._finalize_leak_check()  # must not raise
        self.assertIn("TEST-LEAK", out.getvalue(), "warning mode still has to report")

    def test_no_leaks_is_silent(self):
        probe = _probe()
        os.environ[self.ENV] = "1"
        with self._swallow_stdout() as out:
            probe._finalize_leak_check()  # must not raise
        self.assertEqual("", out.getvalue())


class VereningingenBaseReportsLeaksTest(unittest.TestCase):
    """The OTHER test base has to report leaks in the same machine-readable form.

    `VereningingenTestCase` is not a subclass of `EnhancedTestCase` -- it is a
    parallel base (ErrorLogGuardMixin, FrappeTestCase) carrying ~450 test classes.
    It already knows which tracked documents it failed to delete: it records
    `cleanup_status == "failed"` with the error, and prints a "CLEANUP SUMMARY"
    block for a human. The ratchet greps for `TEST-LEAK`, so every one of those
    leaks was invisible to it -- a gate reading only the other base would report a
    clean suite while half of it leaked.
    """

    def setUp(self):
        self.suffix = frappe.generate_hash(length=6)
        self.created = []

    def tearDown(self):
        for doctype, name in reversed(self.created):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def _probe_case(self):
        """A real VereningingenTestCase whose tracked Territory cannot be deleted.

        `runTest` rather than `test_*`: unittest's loader collects names starting
        with "test", so this class runs only when this test drives it -- but it
        runs the REAL setUp/tearDown lifecycle, which is the point. Asserting on
        `_finalize_leak_check()` alone would pass with the tearDown wiring absent.
        """
        from verenigingen.tests.utils.base import VereningingenTestCase

        outer = self

        class _LeakingCase(VereningingenTestCase):
            def runTest(self):
                parent = frappe.get_doc(
                    {
                        "doctype": "Territory",
                        "territory_name": f"zzbase-parent-{outer.suffix}",
                        "parent_territory": "All Territories",
                        "is_group": 1,
                    }
                ).insert()
                outer.created.append(("Territory", parent.name))
                self.track_doc("Territory", parent.name)

                child = frappe.get_doc(
                    {
                        "doctype": "Territory",
                        "territory_name": f"zzbase-child-{outer.suffix}",
                        "parent_territory": parent.name,
                    }
                ).insert()
                # Untracked on purpose: the parent must still be held when cleanup
                # reaches it, or there is no leak to report.
                outer.created.append(("Territory", child.name))
                frappe.db.commit()
                outer.leaked_name = parent.name

        return _LeakingCase("runTest")

    def test_a_tracked_document_it_could_not_delete_is_reported_as_a_leak(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            self._probe_case().run(unittest.TestResult())

        # One substring, not two assertions: `_report_cleanup_summary` also prints the
        # name, so separate checks could be satisfied by two different lines.
        self.assertIn(
            f"TEST-LEAK {type(self).__module__}",
            buf.getvalue(),
            "this base's undeletable documents must be reported in the same "
            "machine-readable form as EnhancedTestCase's, or the ratchet cannot see them",
        )
        self.assertRegex(buf.getvalue(), rf"TEST-LEAK \S+ Territory::{self.leaked_name}\b")


def _base_probe():
    """A real `VereningingenTestCase` whose `setUp` is never run.

    Same trick as `_probe()` above, for the OTHER base: the drain
    (`_cleanup_document_with_retry` / `_cancel_if_submitted`) is a method on the
    real class and reads real class state (`LEDGER_DOCTYPES`), so subclassing gets
    it honestly, while never calling `setUp` keeps the harness -- and its
    master-data seeding -- out of these tests. "runTest" is the one methodName
    `TestCase` accepts without the method existing.
    """
    from verenigingen.tests.utils.base import VereningingenTestCase

    class _BaseDrainProbe(VereningingenTestCase):
        # Deliberately NO test_* methods -- see _DrainProbe above.
        pass

    return _BaseDrainProbe("runTest")


class DrainDoesNotDiscardRowsItHasNotReachedTest(unittest.TestCase):
    """Cleaning up one tracked document must not destroy the next one.

    `_cleanup_document_with_retry` issued a transaction-wide `frappe.db.rollback()`
    immediately before EVERY delete, so the first tracked document drained
    discarded every row the test had not committed -- including the link targets
    the REMAINING documents still needed. Measured on test_site_1: a Membership
    Type read `exists=True` at drain entry and `skipped` by the time the drain
    reached it (#433).

    `EnhancedTestCase`'s two drains already have the right shape --
    `_drain_tracked_documents` and `_drain_captured_inserts` roll back ONCE before
    their loop and commit ONCE after it. This one was the odd sibling.
    """

    def setUp(self):
        self.created = []

    def tearDown(self):
        for doctype, name in reversed(self.created):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_draining_one_document_leaves_an_uncommitted_sibling_alone(self):
        """Both rows are uncommitted on purpose -- that is the whole failure mode.

        A committed row survives any rollback, so a test that commits its fixtures
        cannot see this defect at all. That is exactly why the module ran green
        locally while the same code leaked in CI.
        """
        bystander = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": f"zzdrain-bystander-{frappe.generate_hash(length=6)}",
                "parent_territory": "All Territories",
            }
        ).insert()
        target = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": f"zzdrain-target-{frappe.generate_hash(length=6)}",
                "parent_territory": "All Territories",
            }
        ).insert()
        # NOT committed. The drain's own commit (after a successful delete) is what
        # persists these, so tearDown has to be able to find them either way.
        self.created.append(("Territory", bystander.name))
        self.created.append(("Territory", target.name))

        doc_info = {"doctype": "Territory", "name": target.name, "cleanup_status": None}
        _base_probe()._cleanup_document_with_retry(doc_info)

        self.assertEqual("success", doc_info["cleanup_status"])
        self.assertFalse(frappe.db.exists("Territory", target.name))
        self.assertTrue(
            frappe.db.exists("Territory", bystander.name),
            "the drain rolled the whole transaction back before its delete and "
            "discarded a row the rest of the drain still had to clean up",
        )


class CancelFailureMustNotBecomeALeakTest(unittest.TestCase):
    """Cancelling is the means; removing the row is the end.

    A submitted document cannot be force-deleted (`delete_doc` runs
    `check_permission_and_not_submitted` BEFORE its `if not force:` guard), so the
    drain cancels first. When that cancel raises, the row survived teardown and
    landed in whatever shard ran next -- the cross-shard contamination the drain
    exists to prevent (#433).

    The cancel can fail for reasons that have nothing to do with the document
    being drained. `Membership.on_cancel` pauses the member's dues schedule, and
    saving that schedule re-validates ITS OWN `membership_type` link -- so a
    Membership Type that is already gone by teardown makes the cancel raise
    `LinkValidationError`, exactly as CI reported it:

        Could not cancel Membership MEMB-26-08-0169 before delete:
          Could not find Membership Type: Test Membership Type XH1L0LOu
    """

    def setUp(self):
        self.created = []
        self.membership_type = None

    def tearDown(self):
        for doctype, name in reversed(self.created):
            try:
                if frappe.db.get_value(doctype, name, "docstatus") == 1:
                    frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def _submitted_membership(self):
        """A real, committed, submitted Membership with a dues schedule behind it."""
        suffix = frappe.generate_hash(length=8)

        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": f"zzleak Type {suffix}",
                "amount": 100,
                "currency": "EUR",
            }
        ).insert()
        self.created.append(("Membership Type", membership_type.name))
        self.membership_type = membership_type.name

        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Zzleak",
                "last_name": "Drain",
                "email": f"zzleak.{suffix}@example.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer",
                "status": "Active",
            }
        ).insert()
        self.created.append(("Member", member.name))

        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": frappe.utils.add_days(frappe.utils.today(), -180),
                "renewal_date": frappe.utils.add_days(frappe.utils.today(), 185),
                "status": "Active",
            }
        )
        membership.insert()
        membership.submit()
        self.created.append(("Membership", membership.name))
        frappe.db.commit()
        return membership.name

    def _delete_the_membership_type_row(self):
        """Remove the link target the way teardown does: the row simply stops existing.

        Raw row delete rather than `delete_doc`, because `delete_doc` refuses while
        a submitted Membership links to it -- and the state under test is precisely
        the one where it is gone anyway. The document cache has to be cleared too,
        or `frappe.get_doc` keeps handing back the deleted doc and the cancel
        succeeds for the wrong reason.
        """
        frappe.db.delete("Membership Type", {"name": self.membership_type})
        frappe.clear_document_cache("Membership Type", self.membership_type)
        frappe.db.commit()

    def test_the_control_a_cancellable_membership_is_removed(self):
        """Without this, a green run above could mean "the fixture never submitted"."""
        name = self._submitted_membership()
        self.assertEqual(1, frappe.db.get_value("Membership", name, "docstatus"))

        doc_info = {"doctype": "Membership", "name": name, "cleanup_status": None}
        _base_probe()._cleanup_document_with_retry(doc_info)

        self.assertEqual("success", doc_info["cleanup_status"])
        self.assertFalse(frappe.db.exists("Membership", name))

    def test_a_submitted_row_whose_cancel_raises_is_still_removed(self):
        name = self._submitted_membership()
        self._delete_the_membership_type_row()

        doc_info = {"doctype": "Membership", "name": name, "cleanup_status": None}
        _base_probe()._cleanup_document_with_retry(doc_info)

        self.assertEqual(
            "success",
            doc_info["cleanup_status"],
            f"cleanup reported {doc_info['cleanup_status']}: {doc_info.get('cleanup_error')}",
        )
        self.assertFalse(
            frappe.db.exists("Membership", name),
            "a submitted row the drain could not cancel survived teardown and will "
            "contaminate whatever shard runs next",
        )

    def test_a_ledger_bearing_voucher_is_still_left_submitted(self):
        """The carve-out the force-delete must NOT widen into.

        Cancelling a voucher that has posted does not remove its GL/Payment Ledger
        rows -- it WRITES reversals -- and `delete_doc` does not take them with the
        parent, so forcing one of those through would turn an honestly-reported
        leak into orphaned ledger rows pointing at a `voucher_no` that no longer
        exists (#328). `_has_ledger_rows` is stubbed rather than posting a real
        voucher: the branch under test is the guard, not the accounting.
        """
        name = self._submitted_membership()
        self._delete_the_membership_type_row()

        probe = _base_probe()
        probe._has_ledger_rows = lambda doctype, docname: True

        doc_info = {"doctype": "Membership", "name": name, "cleanup_status": None}
        probe._cleanup_document_with_retry(doc_info)

        self.assertEqual("failed", doc_info["cleanup_status"])
        self.assertEqual(1, frappe.db.get_value("Membership", name, "docstatus"))


class CustomerCleanupMustNotStrandLedgerRowsTest(unittest.TestCase):
    """A posted invoice force-deleted out from under its GL rows is worse than a leak.

    `_cleanup_member_customers` -> `_cleanup_customer_dependencies` forces
    `docstatus = 2` on every Sales Invoice / Payment Entry belonging to a tracked
    Member's Customer and force-deletes it. `delete_doc` does NOT take the
    voucher's GL / Payment Ledger rows with it unless
    `Accounts Settings.delete_linked_ledger_entries` is on, and 0 is that field's
    doctype default (measured 0 here). `revert_series_if_last` then rewinds the
    naming series, so the NEXT invoice issued that name is born already linked to
    the leftovers (#328) -- measured worker-free, one reused ACC-SINV name
    carrying 2, then 4, then 6 GL Entry rows over three consecutive runs.

    **An orphan count is the wrong instrument for this** and reads 0 either way:
    once the name is reused the rows have a live parent again. This asserts on the
    specific voucher instead.

    Everything here is COMMITTED on purpose: that is the only state in which the
    delete survives the rollback that follows it in `tearDown`.
    """

    def setUp(self):
        self.created = []
        self.vouchers = []

    def tearDown(self):
        for doctype, name in reversed(self.created):
            try:
                if frappe.db.get_value(doctype, name, "docstatus") == 1:
                    frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
                    frappe.clear_document_cache(doctype, name)
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        # The rows delete_doc will not take with it, whichever way this test went.
        for voucher in self.vouchers:
            for ledger in ("GL Entry", "Payment Ledger Entry"):
                try:
                    frappe.db.delete(ledger, {"voucher_no": voucher})
                except Exception:
                    pass
        frappe.db.commit()

    def test_a_posted_invoice_is_not_deleted_out_from_under_its_gl_rows(self):
        probe = _base_probe()
        probe._test_docs = []

        suffix = frappe.generate_hash(length=8)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Zzstrand",
                "last_name": suffix,
                "email": f"zzstrand.{suffix}@example.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer",
                "status": "Active",
            }
        ).insert()
        self.created.append(("Member", member.name))

        invoice = probe.create_test_sales_invoice(member=member.name)
        invoice.submit()
        frappe.db.commit()
        self.created.append(("Sales Invoice", invoice.name))
        self.vouchers.append(invoice.name)

        gl_before = frappe.db.count(
            "GL Entry", {"voucher_type": "Sales Invoice", "voucher_no": invoice.name}
        )
        self.assertGreater(gl_before, 0, "fixture did not post: nothing to strand, nothing to prove")

        # The method under test finds the customer through the TRACKED Member.
        probe._test_docs = [{"doctype": "Member", "name": member.name, "cleanup_status": None}]
        probe._cleanup_member_customers()

        gl_after = frappe.db.count(
            "GL Entry", {"voucher_type": "Sales Invoice", "voucher_no": invoice.name}
        )
        self.assertFalse(
            gl_after and not frappe.db.exists("Sales Invoice", invoice.name),
            f"the invoice is gone and {gl_after} GL Entry row(s) still name it -- the series "
            "will rewind and hand that name to the next invoice, which is then born owning "
            "rows it never posted (#328)",
        )
        # The intended outcome, not merely the absence of the bad one: the voucher
        # and its rows go together. Leaving the voucher instead would be a leak
        # nothing here tracks, which is why this cleanup finishes the delete.
        self.assertFalse(frappe.db.exists("Sales Invoice", invoice.name))
        self.assertEqual(0, gl_after)


class ClassFixturesSurviveTheDrainRollbackTest(unittest.TestCase):
    """A test's teardown may discard the TEST's rows. Not the CLASS's.

    `setUpClass` fixtures are routinely left uncommitted -- `FrappeTestCase`'s only
    rollback is one `addClassCleanup(_rollback_db)`, so they are cleaned up at the
    end of the class and nothing before that is supposed to touch them.

    The drain's transaction-wide rollback is reached only when a tracked document
    still exists, which is why a class whose tests track nothing has always been
    safe. Making that rollback unconditional -- an easy thing to do while moving
    it out of the per-document loop -- kills those fixtures after the FIRST test
    and every later test in the class dies on `_validate_links`. Measured in CI:
    6 of 12 shards red exactly that way, e.g.

        Could not find Chapter: Test Chapter 1 - 68755102

    So this pins the CONDITION, not the placement. It is the #330 failure mode and
    it is one line away at all times.
    """

    def setUp(self):
        self.seen = []
        self.fixture = None

    def tearDown(self):
        if self.fixture:
            try:
                frappe.delete_doc("Territory", self.fixture, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_an_uncommitted_setupclass_fixture_outlives_the_first_teardown(self):
        from verenigingen.tests.utils.base import VereningingenTestCase

        outer = self

        # Defined INSIDE the method: unittest collects TestCase subclasses by type,
        # so a module-level class with test_* methods would be run by the loader
        # as well as by this test.
        class _TwoTestsSharingAClassFixture(VereningingenTestCase):
            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                # Deliberately NOT committed -- that is the state under test, and
                # the state most setUpClass fixtures in this app are in.
                cls.fixture = frappe.get_doc(
                    {
                        "doctype": "Territory",
                        "territory_name": f"zzclassfix-{frappe.generate_hash(length=6)}",
                        "parent_territory": "All Territories",
                    }
                ).insert().name
                outer.fixture = cls.fixture

            def test_a_first(self):
                # Tracks nothing, like the six classes CI went red on.
                outer.seen.append(bool(frappe.db.exists("Territory", self.fixture)))

            def test_b_second(self):
                outer.seen.append(bool(frappe.db.exists("Territory", self.fixture)))

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_TwoTestsSharingAClassFixture).run(result)

        self.assertEqual([], result.errors + result.failures)
        self.assertEqual(
            [True, True],
            outer.seen,
            "a teardown discarded a fixture its setUpClass owns; every test after the "
            "first in that class now fails link validation on it",
        )


def _territory(name_prefix, parent="All Territories"):
    """A cheap, real, deletable document. Same fixture the drain tests above use."""
    return frappe.get_doc(
        {
            "doctype": "Territory",
            "territory_name": f"{name_prefix}-{frappe.generate_hash(length=6)}",
            "parent_territory": parent,
        }
    ).insert()


class CleanupManagerFinishesWhatItStartedTest(unittest.TestCase):
    """One undeletable document must not abandon the cleanup of every other.

    `TestCleanupManager.cleanup` (`tests/utils/factories.py`) is what
    `TestDataBuilder.cleanup()` calls, and what several suites call from their own
    `tearDown`. On the FIRST document it could not delete it issued a
    transaction-wide `frappe.db.rollback()` and **raised**, so none of the
    remaining registered documents were cleaned up at all (#483).

    The raise is worse than losing the rest of this loop. Four of the five
    `tearDown`s that call it do so BEFORE `super().tearDown()` and do not wrap it,
    so the exception also skips the base class's entire teardown: the drain, the
    Error Log capture, the leak report and the mock restoration. A cleanup that
    cannot delete one row took the whole teardown with it.

    Why the undeletable row is a parent with a child: `delete_doc` runs
    `on_trash` before it deletes anything, and `force=True` does not bypass it
    (it bypasses the *link* check). `NestedSet.on_trash` throws
    `NestedSetChildExistsError` before mutating anything, so this is a real,
    deterministic delete failure with no partial state and nothing mocked.
    """

    def setUp(self):
        self.created = []

    def tearDown(self):
        for doctype, name in reversed(self.created):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_a_failed_delete_does_not_abandon_the_remaining_documents(self):
        """Both rows are COMMITTED on purpose.

        An uncommitted row is destroyed by the transaction-wide rollback as well,
        so "the second row is gone" would read the same whether the loop deleted
        it or the rollback erased it -- a test that passes on the defect. Committed,
        only a real delete can remove it.
        """
        from verenigingen.tests.utils.factories import TestCleanupManager

        parent = _territory("zzmgr-undeletable")
        child = _territory("zzmgr-child", parent=parent.name)
        frappe.db.commit()
        self.created.append(("Territory", parent.name))
        self.created.append(("Territory", child.name))

        manager = TestCleanupManager()
        # Registration order decides attempt order: cleanup walks the stack in
        # reverse, so the parent -- the one that cannot be deleted while its child
        # exists -- is attempted first, and the child proves the loop continued.
        manager.register("Territory", child.name)
        manager.register("Territory", parent.name)

        errors = manager.cleanup()

        self.assertFalse(
            frappe.db.exists("Territory", child.name),
            "cleanup stopped at the first document it could not delete and left "
            "every other registered document on the site",
        )
        self.assertTrue(frappe.db.exists("Territory", parent.name))
        self.assertEqual(
            [parent.name],
            [e["name"] for e in errors],
            "the failure must be returned to the caller, not thrown away",
        )

    def test_a_failed_delete_is_reported_where_ci_can_read_it(self):
        """Not raising must not mean not saying anything.

        The old `raise` was destructive but loud -- an exception in `tearDown`
        errors the test. Collecting the failure and continuing trades that for
        silence unless it is announced, and all eight call sites discard the returned
        list (five tearDowns, three mid-test). `frappe.logger()` would not do: it writes only to
        `logs/frappe.log`, which CI never uploads (#485).

        Asserted on the record rather than on captured stderr: the harness
        logger's `StreamHandler` binds `sys.stderr` when it is first configured,
        which may be long before this test runs, so `redirect_stderr` here reads
        empty whether or not anything was logged -- an instrument that cannot fail.
        That the handler writes to stderr at all is pinned separately, by
        `test_harness_logger.test_writes_to_stderr_not_stdout`.
        """
        from verenigingen.tests.harness_logger import LOGGER_NAME
        from verenigingen.tests.utils.factories import TestCleanupManager

        parent = _territory("zzmgr-reported")
        child = _territory("zzmgr-reported-child", parent=parent.name)
        frappe.db.commit()
        self.created.append(("Territory", parent.name))
        self.created.append(("Territory", child.name))

        manager = TestCleanupManager()
        manager.register("Territory", parent.name)

        # No "configure the logger first" line here on purpose. `assertLogs` really does
        # take the handler away and cannot put a "configured once" flag back, but that is
        # fixed at the source now -- `harness_logger._configured_logger` guards on
        # whether OUR handler is still attached, and
        # `AssertLogsMustNotDegradeTheLoggerTest` pins it. A workaround here would only
        # protect the author who knew to write it.
        with self.assertLogs(LOGGER_NAME, level="ERROR") as logged:
            manager.cleanup()

        self.assertTrue(
            any(parent.name in line for line in logged.output),
            f"a cleanup failure nobody can read is the swallow this replaced: {logged.output}",
        )


class CleanupManagerDoesNotDiscardRowsItDoesNotOwnTest(unittest.TestCase):
    """A failed delete may undo its own work. Not the rest of the transaction.

    `frappe.db.rollback()` in a cleanup path discards every uncommitted row in the
    connection, and the rows a test's cleanup did not create are not its to
    discard: uncommitted `setUpClass` fixtures belong to the class, and
    `builder.cleanup()` is also called mid-test at three call sites, where a
    rollback takes the test's own `setUp` with it. Measured in CI when the drain's rollback
    was widened this way: 6 of 12 shards red, every failure a second-and-later
    test of a class failing `_validate_links` on its own class fixture (#330,
    re-created in #486 and reverted).

    A savepoint per delete undoes the failed attempt and nothing else.
    """

    def setUp(self):
        self.created = []

    def tearDown(self):
        for doctype, name in reversed(self.created):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_a_failed_delete_leaves_an_uncommitted_bystander_alone(self):
        """The bystander is UNCOMMITTED on purpose -- that is the whole failure mode.

        A committed row survives any rollback, so a suite that commits its fixtures
        cannot see this defect at all.
        """
        from verenigingen.tests.utils.factories import TestCleanupManager

        parent = _territory("zzmgr-bystander-blocker")
        child = _territory("zzmgr-bystander-child", parent=parent.name)
        frappe.db.commit()
        self.created.append(("Territory", parent.name))
        self.created.append(("Territory", child.name))

        bystander = _territory("zzmgr-bystander")
        self.created.append(("Territory", bystander.name))

        manager = TestCleanupManager()
        manager.register("Territory", parent.name)
        manager.cleanup()

        self.assertTrue(
            frappe.db.exists("Territory", bystander.name),
            "cleanup rolled the whole transaction back over one failed delete and "
            "discarded a row it never owned",
        )


if __name__ == "__main__":
    unittest.main()
