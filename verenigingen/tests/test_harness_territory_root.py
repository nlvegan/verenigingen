"""The Territory root is a fixture this harness must build, not inherit.

A fresh `bench --site <site> reinstall` leaves `tabTerritory` EMPTY. The tree,
root included, comes from erpnext's `BootStrapTestData()`, which this app reaches
either through `ensure_erpnext_base_masters()` or as an import side effect of
`enhanced_test_factory` -- and the latter sits behind a bare
`except Exception: pass`. Whichever path runs, it is a neighbour's doing, and CI
shard bins re-pack on measured runtime, so nothing makes that neighbour run first
(#516).

The module that surfaced it, `verenigingen.tests.api.test_dues_invoice_workflow`,
could not have fixed it itself: the raise is inside `super().setUpClass()` --
`tests/utils/base.py` -> `ensure_netherlands_territory()` -> "Could not find
Parent Territory: All Territories" -- before a single line of the module runs.
So the guard belongs on the seeder that consumes the root, which is what the
behavioural tests below pin.

`unittest.TestCase` / `FrappeTestCase` classes reach neither harness base, so
they depend entirely on those import side effects. They are the residual class,
and the source guard at the bottom is what keeps the next one from being written
-- read its docstring for what was measured about it, which is narrower than the
shape it enforces.
"""

import ast
import unittest

import frappe

from verenigingen.tests.utils.paths import APP_ROOT
from verenigingen.tests.utils.root_probes import non_harness_test_classes, rows_deleted
from verenigingen.tests.utils.source_probes import called_names

ROOT = "All Territories"

# Callables that guarantee the root before it is used.
_ROOT_SEEDERS = (
    "ensure_root_territory",
    "ensure_erpnext_base_masters",
    "ensure_member_test_masters",
    "_ensure_territory",
)

# Modules that name the root but never write it to the database. Exempt with the
# reason, not silently: an entry here is a claim that has to stay true.
_NO_DATABASE_WRITE = {
    # Asserts on a MagicMock's attribute; `frappe` itself is patched out, so no
    # Territory row is read or written.
    "verenigingen/tests/e_boekhouden/test_party_resolver.py",
    # Names "All Territories" only in its module docstring, listing it alongside
    # the other four hardcoded ERPNext tree roots for context (#562). Its own
    # classes write and assert only the Item Group / Customer Group / Supplier
    # Group roots, never Territory.
    "verenigingen/tests/test_harness_erpnext_group_roots.py",
}


def _territories_deleted(*names):
    """Territory-shaped `rows_deleted`, which is what every caller below wants."""
    return rows_deleted("Territory", *names)


def _root_deleted():
    return _territories_deleted(ROOT)


class TerritoryRootIsSeededTest(unittest.TestCase):
    """Behaviour, against the real seeders and the real database."""

    @classmethod
    def setUpClass(cls):
        """Seed what these tests then take away.

        A plain `unittest.TestCase` reaches neither harness base, so this module
        would otherwise need the tree an earlier module left behind -- which is
        the exact order-dependence it exists to close. `ensure_netherlands_territory`
        seeds both rows and is the code under test, so a failure here is a
        failure of the fix rather than a missing fixture.
        """
        super().setUpClass()
        from verenigingen.tests.setup import ensure_netherlands_territory

        ensure_netherlands_territory()

    def test_the_probe_actually_removes_the_root(self):
        """The control. Without this, every test below could pass on a warm site
        while the code under test was never reached."""
        self.assertTrue(frappe.db.exists("Territory", ROOT), "site has no root to remove")
        with _root_deleted():
            self.assertFalse(frappe.db.exists("Territory", ROOT))
        self.assertTrue(frappe.db.exists("Territory", ROOT), "the probe must restore the root")

    def test_the_netherlands_seeder_rebuilds_a_tree_that_is_entirely_absent(self):
        """The fresh-reinstall shape: `tabTerritory` holds neither row (#516).

        This raised `LinkValidationError: Could not find Parent Territory: All
        Territories` from inside `VereningingenTestCase.setUpClass`.
        """
        from verenigingen.tests.setup import ensure_netherlands_territory

        with _territories_deleted(ROOT, "Netherlands"):
            ensure_netherlands_territory()
            self.assertTrue(
                frappe.db.exists("Territory", ROOT),
                "the seeder must build the parent it links to",
            )
            self.assertTrue(frappe.db.exists("Territory", "Netherlands"))

    def test_the_netherlands_seeder_seeds_the_root_before_its_own_early_return(self):
        """ "Netherlands" present and the root gone is not a hypothetical: any
        rollback that reaches an uncommitted root leaves exactly that state, and
        the early return then skipped the root for the whole session."""
        from verenigingen.tests.setup import ensure_netherlands_territory

        with _root_deleted():
            self.assertTrue(
                frappe.db.exists("Territory", "Netherlands"),
                "this test is only about the early-return path",
            )
            ensure_netherlands_territory()
            self.assertTrue(frappe.db.exists("Territory", ROOT))

    def test_the_root_seeder_creates_it_under_the_exact_hardcoded_name(self):
        """ "It did not raise" is not evidence the row landed under the name every
        caller hardcodes -- the `All Departments - _TC` bug was exactly that."""
        from verenigingen.tests.setup import ensure_root_territory

        with _root_deleted():
            ensure_root_territory()
            self.assertTrue(frappe.db.exists("Territory", ROOT))
            self.assertEqual(1, frappe.db.get_value("Territory", ROOT, "is_group"))

    def test_the_root_seeder_is_idempotent(self):
        """It runs from every setUp on both harness bases; a second call must not
        raise `DuplicateEntryError` or add a second row."""
        from verenigingen.tests.setup import ensure_root_territory

        with _root_deleted():
            ensure_root_territory()
            ensure_root_territory()
        ensure_root_territory()
        self.assertEqual(1, frappe.db.count("Territory", {"name": ROOT}))


BASE_MASTER_SENTINEL = ("Warehouse Type", "Transit")
#: Was `("Supplier Group", "All Supplier Groups")` until #562: that root is no
#: longer forge-proof once `ensure_root_supplier_group()` exists (both harness
#: bases now create it directly, same shape that made the Territory-only gate
#: forgeable in the first place -- see `_erpnext_base_masters_present`'s
#: docstring). `Warehouse Type` "Transit" replaces it: same
#: `get_preset_records("India")` batch, zero writes anywhere in this app.


class SeedingTheRootMustNotCloseTheBaseMasterGateTest(unittest.TestCase):
    """Seeding the root must not convince `ensure_erpnext_base_masters` it can skip.

    `ensure_erpnext_base_masters()` gates BootStrapTestData,
    `enable_all_roles_and_domains()`, `set_defaults_for_tests()` and
    `ensure_test_fiscal_year_for_all_companies()` on ONE existence check, and its
    own docstring shows that check standing for the whole master set rather than
    for itself.

    `ensure_root_territory` creates exactly that row, from three call sites that
    never reach the gate. So the order "a harness-based class first, then any of
    the 30+ modules calling `ensure_member_test_masters()` from `setUpClass`"
    would leave the gate closed over an unseeded site -- and that order is as
    reachable as #516 itself, since shard bins re-pack on measured runtime.

    Impossible before `ensure_root_territory` existed: "Netherlands" linked to a
    parent nothing created, so a missing root RAISED. Fixing the raise is what
    made the sentinel forgeable, so the pin belongs in the same change.
    """

    @classmethod
    def setUpClass(cls):
        """Same reasoning as the class above: seed what these tests take away."""
        super().setUpClass()
        from verenigingen.tests.setup import ensure_netherlands_territory

        ensure_netherlands_territory()

    def test_the_probe_actually_removes_the_sentinel(self):
        """The control. Without it, the test below could pass on a site that never
        had the sentinel, saying nothing about the gate."""
        doctype, name = BASE_MASTER_SENTINEL
        self.assertTrue(frappe.db.exists(doctype, name), f"site has no {name} to remove")
        with rows_deleted(doctype, name):
            self.assertFalse(frappe.db.exists(doctype, name))
        self.assertTrue(frappe.db.exists(doctype, name), "the probe must restore the sentinel")

    def test_a_fully_seeded_site_still_closes_the_gate(self):
        """The other control: the gate must remain cheap on a warm site, or every
        `setUpClass` in the suite starts re-running BootStrapTestData."""
        from verenigingen.tests.setup import _erpnext_base_masters_present

        self.assertTrue(_erpnext_base_masters_present())

    def test_the_root_alone_does_not_close_the_gate(self):
        """The pin. Both halves asserted together, because either alone is
        satisfied in the buggy world too: the root IS present (so a root-only gate
        would have closed and skipped the seeding) while the gate is still open.
        """
        from verenigingen.tests.setup import _erpnext_base_masters_present, ensure_root_territory

        doctype, name = BASE_MASTER_SENTINEL
        with rows_deleted(doctype, name):
            ensure_root_territory()

            self.assertTrue(
                frappe.db.exists("Territory", ROOT),
                "precondition: the root is absent, so this says nothing about a root-only gate",
            )
            self.assertFalse(
                _erpnext_base_masters_present(),
                "the base-master gate closed on the root Territory alone, so "
                "ensure_erpnext_base_masters() will early-return and seed nothing: "
                "no Customer Groups, no Chart of Accounts, no set_defaults_for_tests()",
            )

    def test_the_full_harness_seeding_path_does_not_close_the_gate(self):
        """The pin #562 needed and did not have: the ACTUAL harness call chain
        (Territory, then Item Group, Customer Group, Supplier Group -- what
        `VereningingenTestCase.setUpClass` and `EnhancedTestCase.setUp` both run)
        must not forge the sentinel between them. A pin scoped to
        `ensure_root_territory` alone stayed green while
        `ensure_root_supplier_group()` (added in the same change) broke this
        exact property for a different doctype -- MEASURED during #562's review.
        """
        from verenigingen.tests.setup import (
            _erpnext_base_masters_present,
            ensure_netherlands_territory,
            ensure_root_customer_group,
            ensure_root_item_group,
            ensure_root_supplier_group,
        )

        doctype, name = BASE_MASTER_SENTINEL
        with rows_deleted(doctype, name):
            ensure_netherlands_territory()
            ensure_root_item_group()
            ensure_root_customer_group()
            ensure_root_supplier_group()

            self.assertFalse(
                frappe.db.exists(doctype, name),
                f"precondition: {doctype} {name} must still be absent",
            )
            self.assertFalse(
                _erpnext_base_masters_present(),
                "the full harness seeding path closed the base-master gate without "
                "Warehouse Type 'Transit' present, so ensure_erpnext_base_masters() "
                "will early-return and seed nothing for every module that calls "
                "ensure_member_test_masters() afterwards",
            )

    def test_the_root_seeder_writes_nothing_that_could_forge_the_sentinel(self):
        """Scope statement, kept honest by measurement rather than by reading:
        `ensure_root_territory` must touch no doctype the gate depends on."""
        from verenigingen.tests.setup import ensure_root_territory

        doctype, name = BASE_MASTER_SENTINEL
        with rows_deleted(doctype, name):
            with _root_deleted():
                ensure_root_territory()
                self.assertFalse(
                    frappe.db.exists(doctype, name),
                    f"ensure_root_territory created a {doctype}; the gate needs a "
                    "sentinel this app never writes",
                )


class TerritoryConsumersOutsideTheHarnessAreGuardedTest(unittest.TestCase):
    """A source guard, because no behavioural test can see this one.

    A module that consumes the root and never seeds it passes on every warm site
    and on every shard where a builder ran first. It fails only when the packer
    puts it first, on a branch that never touched it (#516, and #291/#431 before
    it).

    MEASURED, and this is the honest limit of it: on a `tabTerritory` emptied to
    zero rows on test_site_1, BOTH modules this flagged -- `test_link_sanitizer`
    and `test_harness_leak_attribution` -- pass WITHOUT any guard. Something in
    each import chain builds the tree before the first Territory write (for the
    latter, `enhanced_test_factory`'s module-level `import erpnext.tests.utils`,
    which is where `BootStrapTestData()` runs); I did not isolate it for the
    former. So the guards those two now carry are defensive, not fixes of a
    measured failure. What makes them worth carrying is that the import they
    depend on is wrapped in a bare `except Exception: pass`, so losing it is
    silent -- unlike `test_dues_invoice_workflow`, which was measured red.

    What this does NOT enforce, and the third item is the one that already cost a
    defect: it cannot tell a Territory write from a string that merely mentions
    the root (hence `_NO_DATABASE_WRITE`); it says nothing about the import side
    effects above, which are the reason a flagged module can still be green; and
    it is per-FILE, so one seeder call anywhere in a module exempts every class
    in it.

    That last one is not hypothetical. `test_harness_leak_attribution.py` calls
    `ensure_root_territory()` at five sites and STILL had a sixth class linking
    to the root unguarded -- `VereningingenBaseReportsLeaksTest`, whose nested
    probe is driven as `case.run(...)`, which does not invoke `setUpClass`.
    Measured: with that class back in its unguarded state and this guard's
    call-detection in place, this module is 6/6 GREEN. Making it per-class needs
    a call graph -- the module's own `_territory()` helper seeds on behalf of
    four classes that never name a seeder themselves -- so the honest statement
    is that this guard covers modules with no seeder at all, and nothing finer.

    It catches the shape -- a class outside the harness naming the root, in a file
    with no seeder call in sight -- and nothing more.
    """

    def test_every_test_module_naming_the_root_either_inherits_it_or_seeds_it(self):
        app_root = APP_ROOT
        offenders = []
        checked = 0
        # `test_*.py` only: the harness modules that DEFINE the base classes
        # (`tests/utils/base.py`, `tests/fixtures/enhanced_test_factory.py`,
        # `tests/setup/__init__.py`) also name the root, and they are the
        # seeders rather than consumers.
        for path in sorted(app_root.glob("verenigingen/**/test_*.py")):
            source = path.read_text(encoding="utf-8")
            if ROOT not in source:
                continue
            rel = str(path.relative_to(app_root))
            if rel in _NO_DATABASE_WRITE:
                continue
            checked += 1
            tree = ast.parse(source)
            # A CALL, not a mention. `seeder in source` was satisfied by an
            # import or by a comment naming the seeder -- measured: turning both
            # real `ensure_root_territory()` calls in `tests/security/
            # test_link_sanitizer.py` into `pass  # ensure_root_territory()` left
            # this module 6/6 green, i.e. the guard could not tell a call from a
            # comment about one. Still per-FILE, though -- see the class docstring
            # for the site this consequently cannot see.
            if called_names(tree) & set(_ROOT_SEEDERS):
                continue
            unguarded = non_harness_test_classes(tree)
            if unguarded:
                offenders.append(f"{rel}: {', '.join(unguarded)}")

        self.assertEqual(
            [],
            offenders,
            "These classes reach neither harness base, so nothing seeds the "
            "Territory root for them. Call `ensure_root_territory()` in setUp, or "
            "add the file to `_NO_DATABASE_WRITE` with the reason it writes none.",
        )
        # A sweep that checked nothing would pass. This module itself names the
        # root, so the floor is not zero.
        self.assertGreater(checked, 1, "the sweep matched nothing; its glob is wrong")


if __name__ == "__main__":
    unittest.main()
