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
import contextlib
import unittest

import frappe

from verenigingen.tests.utils.paths import APP_ROOT

ROOT = "All Territories"

# Bases whose setUp/setUpClass reaches `ensure_netherlands_territory()` and
# therefore, after this fix, the root. `BaseTestCase` is an alias for both
# `VereningingenTestCase` and an `EnhancedTestCase` subclass depending on the
# importing module; either way it is covered.
_HARNESS_BASES = {"VereningingenTestCase", "EnhancedTestCase", "BaseTestCase"}

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
}


@contextlib.contextmanager
def _territories_deleted(*names):
    """Take the named Territory rows away for the block, then put them back.

    Raw SQL rather than `frappe.delete_doc`: on any warm site the root has
    children and NestedSet refuses to delete it. A savepoint rollback undoes
    both the delete and whatever the code under test inserted, so the tree is
    identical afterwards -- measured on test_site_1: 9 rows before, 9 after,
    same names.
    """
    frappe.db.savepoint("territory_root_probe")
    try:
        for name in names:
            frappe.db.sql("DELETE FROM `tabTerritory` WHERE name = %s", name)
        yield
    finally:
        frappe.db.rollback(save_point="territory_root_probe")


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


def _non_harness_test_classes(tree: ast.Module) -> list:
    """Names of test classes in `tree` that reach neither harness base."""
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {
            base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "") for base in node.bases
        }
        if not any(name.endswith("TestCase") for name in base_names):
            continue
        if base_names & _HARNESS_BASES:
            continue
        offenders.append(node.name)
    return offenders


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

    What this does NOT enforce: it cannot tell a Territory write from a string
    that merely mentions the root (hence `_NO_DATABASE_WRITE`); it cannot prove a
    referenced seeder is actually called on the path that needs it; and it says
    nothing about the import side effects above, which are the reason a flagged
    module can still be green. It catches the shape -- a class outside the
    harness naming the root with no seeder in sight -- and nothing more.
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
            if any(seeder in source for seeder in _ROOT_SEEDERS):
                continue
            unguarded = _non_harness_test_classes(ast.parse(source))
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
