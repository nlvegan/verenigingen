"""The Item Group / Customer Group / Supplier Group roots are fixtures this
harness must build, not inherit -- the same shape #524 fixed for the Territory
root, for the three ERPNext tree roots that #562 found had no `ensure_root_*`
helper at all.

`erpnext`'s `after_install` creates none of the five hardcoded roots this app
depends on ("All Territories", "All Item Groups", "All Customer Groups",
"All Departments", "All Supplier Groups") -- verified against
`erpnext/setup/install.py`. Before this change only two had a dedicated seeder
(`ensure_root_territory`, `ensure_root_department`); the other three came from
`erpnext.tests.utils.BootStrapTestData()` ONLY when `ensure_erpnext_base_masters()`
actually runs its seeding branch, which a harness-based test does not reach on
its own -- `VereningingenTestCase.setUpClass` and `EnhancedTestCase.setUp` call
`ensure_netherlands_territory()` (hence the Territory root), never
`ensure_erpnext_base_masters()` itself. So a fresh site whose first test is
harness-based got "All Territories" but NOT "All Item Groups", "All Customer
Groups" or "All Supplier Groups" -- MEASURED with `tests/scratch_probe_562.py`
(deleted before commit): after wiping both trees, `ensure_prerequisites()`
self-healed "All Customer Groups" (it is written defensively, try/except and
all), but inserting an Item Group under a missing "All Item Groups" raised
`LinkValidationError: Could not find Parent Item Group: All Item Groups` --
exactly `tests/backend/components/test_membership_utilities.py:85-88`'s shape.

`tests/backend/components/test_setup_init.py:172`'s assertion, the issue's other
named instance, turned out NOT to be a bug: `test_ensure_prerequisites` calls
`setup_mod.ensure_prerequisites()` immediately before the assertion, and that
call recreates "All Customer Groups" itself when missing (see above) -- so this
specific test is self-healing regardless of what ran before it. Left untouched.
"""

import ast
import unittest

import frappe

from verenigingen.tests.utils.paths import APP_ROOT
from verenigingen.tests.utils.root_probes import non_harness_test_classes, rows_deleted
from verenigingen.tests.utils.source_probes import called_names

#: doctype -> hardcoded root name
ROOTS = {
    "Item Group": "All Item Groups",
    "Customer Group": "All Customer Groups",
    "Supplier Group": "All Supplier Groups",
}

# Callables that guarantee ALL THREE roots before any is used. Deliberately
# does NOT include `ensure_prerequisites`: it creates "All Customer Groups"
# unconditionally but "All Item Groups" only inside its own
# `if not exists("Item Group", "Services")` branch, and never touches
# "All Supplier Groups" at all -- listing it here would be a blanket claim
# this guard cannot back for two of the three roots. Its one real consumer,
# `test_setup_init.py`, is exempted below by name instead, scoped to the one
# root it actually depends on.
_ROOT_SEEDERS = (
    "ensure_root_item_group",
    "ensure_root_customer_group",
    "ensure_root_supplier_group",
    "ensure_erpnext_base_masters",
    "ensure_member_test_masters",
)

# Modules that name a root but never write it to the database. Exempt with the
# reason, not silently: an entry here is a claim that has to stay true.
_NO_DATABASE_WRITE = {
    # Asserts on a MagicMock's attribute; `frappe` itself is patched out, so no
    # row of any of these doctypes is read or written. Same file, same reason,
    # as `test_harness_territory_root._NO_DATABASE_WRITE`.
    "verenigingen/tests/e_boekhouden/test_party_resolver.py",
    # `TestSetupSeedFunctions.test_ensure_prerequisites` (the only class here
    # naming a root) calls `setup_mod.ensure_prerequisites()` immediately
    # before asserting "All Customer Groups" exists, and that call recreates
    # the row itself when missing -- MEASURED empirically during #562's
    # investigation (deleting the root and calling `ensure_prerequisites()`
    # recreated it). Not a `_ROOT_SEEDERS` entry because `ensure_prerequisites`
    # does not reliably cover the other two roots -- see the comment there.
    "verenigingen/tests/backend/components/test_setup_init.py",
}


class GroupRootsAreSeededTest(unittest.TestCase):
    """Behaviour, against the real seeders and the real database."""

    @classmethod
    def setUpClass(cls):
        """Seed what these tests then take away.

        A plain `unittest.TestCase` reaches neither harness base, so this
        module would otherwise need the tree an earlier module left behind --
        the exact order-dependence it exists to close. Without this, every
        test here that assumes a warm site passes only because
        `test_each_root_seeder_is_idempotent` (alphabetically earlier) happens
        to call each seeder first and leave the roots behind -- an
        order-dependent test whose control is satisfied by a sibling, caught
        during #562's review.
        """
        super().setUpClass()
        from verenigingen.tests.setup import (
            ensure_root_customer_group,
            ensure_root_item_group,
            ensure_root_supplier_group,
        )

        ensure_root_item_group()
        ensure_root_customer_group()
        ensure_root_supplier_group()

    def test_the_probe_actually_removes_each_root(self):
        """The control. Without this, every test below could pass on a warm
        site while the code under test was never reached."""
        for doctype, root in ROOTS.items():
            with self.subTest(doctype=doctype):
                self.assertTrue(frappe.db.exists(doctype, root), f"site has no {root} to remove")
                with rows_deleted(doctype, root):
                    self.assertFalse(frappe.db.exists(doctype, root))
                self.assertTrue(frappe.db.exists(doctype, root), "the probe must restore the root")

    def test_each_root_seeder_creates_it_under_the_exact_hardcoded_name(self):
        """ "It did not raise" is not evidence the row landed under the name
        every caller hardcodes -- the `All Departments - _TC` bug (see
        `ensure_root_department`) was exactly that."""
        from verenigingen.tests.setup import (
            ensure_root_customer_group,
            ensure_root_item_group,
            ensure_root_supplier_group,
        )

        seeders = {
            "Item Group": ensure_root_item_group,
            "Customer Group": ensure_root_customer_group,
            "Supplier Group": ensure_root_supplier_group,
        }
        for doctype, root in ROOTS.items():
            with self.subTest(doctype=doctype):
                with rows_deleted(doctype, root):
                    seeders[doctype]()
                    self.assertTrue(frappe.db.exists(doctype, root))
                    self.assertEqual(1, frappe.db.get_value(doctype, root, "is_group"))

    def test_each_root_seeder_is_idempotent(self):
        """These run from harness setUp/setUpClass on every test; a second call
        must not raise `DuplicateEntryError` or add a second row."""
        from verenigingen.tests.setup import (
            ensure_root_customer_group,
            ensure_root_item_group,
            ensure_root_supplier_group,
        )

        seeders = {
            "Item Group": ensure_root_item_group,
            "Customer Group": ensure_root_customer_group,
            "Supplier Group": ensure_root_supplier_group,
        }
        for doctype, root in ROOTS.items():
            with self.subTest(doctype=doctype):
                seeder = seeders[doctype]
                with rows_deleted(doctype, root):
                    seeder()
                    seeder()
                seeder()
                self.assertEqual(1, frappe.db.count(doctype, {"name": root}))

    def test_the_item_group_seeder_makes_a_child_insert_possible(self):
        """The actual regression: #562's write
        (`test_membership_utilities.py:85-88`, an `Item Group` insert under
        "All Item Groups") must succeed once `ensure_root_item_group()` -- what
        both harness bases now call from setUp/setUpClass, see
        `enhanced_test_factory.py` and `tests/utils/base.py` -- has run, even on
        a site where nothing else seeded the tree. Reproduces the write
        directly rather than importing `MembershipTestUtilities` -- the point
        under test is the root's presence, not that helper's other side
        effects. This test calls the seeder itself rather than going through
        either harness base; `HarnessBasesSeedAllThreeRootsTest` below is what
        pins that both bases actually reach it."""
        with rows_deleted("Item Group", ROOTS["Item Group"]):
            from verenigingen.tests.setup import ensure_root_item_group

            ensure_root_item_group()

            item_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "TestGroupRoots562",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            )
            item_group.insert(ignore_permissions=True)
            self.assertTrue(frappe.db.exists("Item Group", "TestGroupRoots562"))
            # No cleanup: the whole block is inside `rows_deleted`'s savepoint,
            # which rolls back this insert along with the root deletion above.


class HarnessBasesSeedAllThreeRootsTest(unittest.TestCase):
    """Both harness bases must reach the new seeders, not just define them.

    `ensure_root_territory` existing was not enough on its own (#516/#524); the
    same is true here unless something on the path every harness-based test
    takes actually calls the three new seeders. This inspects the call site
    directly via the same AST-call-detection used by the source guard below,
    rather than instantiating the full test base -- doing that from inside a
    test module would recurse.

    Only `tests/fixtures/enhanced_test_factory.py` is pinned here.
    `tests/utils/base.py` -> `VereningingenTestCase.setUpClass` is already
    pinned by `test_harness_setup_fatal.SetupCallsAreNotSwallowedTest.
    test_every_named_setup_call_is_still_there_to_guard` (the three seeders are
    listed in that module's `UNGUARDED_CALLS` for that file) -- a second copy
    of the same assertion here would be exactly the kind of duplicate the
    duplicate-helper ratchet exists to catch. `enhanced_test_factory.py`'s
    call is deliberately NOT in `UNGUARDED_CALLS` (its surrounding handler
    re-raises rather than swallows, so that guard's "not caught by an except"
    check would misreport a re-raise as a swallow), which is why it still
    needs its own pin here.
    """

    def test_enhanced_test_factory_calls_all_three_seeders(self):
        path = APP_ROOT / "verenigingen" / "tests" / "fixtures" / "enhanced_test_factory.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = called_names(tree)
        for seeder in ("ensure_root_item_group", "ensure_root_customer_group", "ensure_root_supplier_group"):
            with self.subTest(seeder=seeder):
                self.assertIn(seeder, calls, f"enhanced_test_factory.py never calls {seeder}()")


class GroupRootConsumersOutsideTheHarnessAreGuardedTest(unittest.TestCase):
    """A source guard, because no behavioural test can see this one.

    Same shape and same honest limits as
    `test_harness_territory_root.TerritoryConsumersOutsideTheHarnessAreGuardedTest`
    -- read that class's docstring for what this cannot see (a mention vs. a
    write, import side effects, per-file rather than per-class granularity).

    Two more, specific to this guard: the sweep globs `test_*.py` only and
    `looks_like_a_test_class` needs a `TestCase`-shaped base or a `test*`
    method, so it cannot see a plain helper class with no `unittest.TestCase`
    anywhere in reach -- which is exactly #562's own named exposure.
    `MembershipTestUtilities` (`test_membership_utilities.py`, despite the
    filename) is such a class: it defines `_create_membership_item`'s
    unguarded Item Group write but contains zero test classes itself, so this
    guard would not have flagged that file even before the fix. What actually
    closes that gap is every real caller (`test_membership_type_minimum_
    period.py`, `test_membership_controller.py`, `test_application_submission_
    validation.py`) reaching a harness base -- verified by hand, not by this
    guard.
    """

    def test_every_test_module_naming_a_root_either_inherits_it_or_seeds_it(self):
        app_root = APP_ROOT
        offenders = []
        checked = 0
        # `test_*.py` only: the harness modules that DEFINE the base classes
        # (`tests/utils/base.py`, `tests/fixtures/enhanced_test_factory.py`,
        # `tests/setup/__init__.py`) also name these roots, and they are the
        # seeders rather than consumers.
        for path in sorted(app_root.glob("verenigingen/**/test_*.py")):
            source = path.read_text(encoding="utf-8")
            if not any(root in source for root in ROOTS.values()):
                continue
            rel = str(path.relative_to(app_root))
            if rel in _NO_DATABASE_WRITE:
                continue
            checked += 1
            tree = ast.parse(source)
            if called_names(tree) & set(_ROOT_SEEDERS):
                continue
            unguarded = non_harness_test_classes(tree)
            if unguarded:
                offenders.append(f"{rel}: {', '.join(unguarded)}")

        self.assertEqual(
            [],
            offenders,
            "These classes reach neither harness base, so nothing seeds the Item "
            "Group / Customer Group / Supplier Group roots for them. Call "
            "`ensure_root_item_group()` / `ensure_root_customer_group()` / "
            "`ensure_root_supplier_group()` in setUp, or add the file to "
            "`_NO_DATABASE_WRITE` with the reason it writes none.",
        )
        # A sweep that checked nothing would pass. This module itself names the
        # roots, so the floor is not zero.
        self.assertGreater(checked, 1, "the sweep matched nothing; its glob is wrong")


if __name__ == "__main__":
    unittest.main()
