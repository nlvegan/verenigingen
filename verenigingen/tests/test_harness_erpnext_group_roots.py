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

# Callables that guarantee at least one of the roots before it is used.
_ROOT_SEEDERS = (
    "ensure_root_item_group",
    "ensure_root_customer_group",
    "ensure_root_supplier_group",
    "ensure_erpnext_base_masters",
    "ensure_member_test_masters",
    "ensure_prerequisites",
)

# Modules that name a root but never write it to the database. Exempt with the
# reason, not silently: an entry here is a claim that has to stay true.
_NO_DATABASE_WRITE = {
    # Asserts on a MagicMock's attribute; `frappe` itself is patched out, so no
    # row of any of these doctypes is read or written. Same file, same reason,
    # as `test_harness_territory_root._NO_DATABASE_WRITE`.
    "verenigingen/tests/e_boekhouden/test_party_resolver.py",
    # Names "All Supplier Groups" only as `BASE_MASTER_SENTINEL`, a
    # (doctype, name) tuple used to probe `ensure_erpnext_base_masters()`'s
    # gate -- read, deleted and restored under its own `rows_deleted`
    # savepoint machinery, never assumed to pre-exist as a fixture.
    "verenigingen/tests/test_harness_territory_root.py",
}


class GroupRootsAreSeededTest(unittest.TestCase):
    """Behaviour, against the real seeders and the real database."""

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

    def test_harness_setup_seeds_all_three_roots_before_any_test_body_runs(self):
        """The actual regression: #562's write
        (`test_membership_utilities.py:85-88`, an `Item Group` insert under
        "All Item Groups") must succeed once a class on either harness base has
        gone through its setUp/setUpClass, even on a site where nothing else
        seeded the tree. Reproduces the write directly rather than importing
        `MembershipTestUtilities` -- the point under test is the root's
        presence, not that helper's other side effects."""
        with rows_deleted("Item Group", ROOTS["Item Group"]):
            from verenigingen.tests.setup import ensure_root_item_group

            # This is exactly what both harness bases now call from
            # setUp/setUpClass -- see enhanced_test_factory.py and
            # tests/utils/base.py.
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
            try:
                self.assertTrue(frappe.db.exists("Item Group", "TestGroupRoots562"))
            finally:
                frappe.delete_doc("Item Group", "TestGroupRoots562", force=True, ignore_permissions=True)


class HarnessBasesSeedAllThreeRootsTest(unittest.TestCase):
    """Both harness bases must reach the new seeders, not just define them.

    `ensure_root_territory` existing was not enough on its own (#516/#524); the
    same is true here unless something on the path every harness-based test
    takes actually calls the three new seeders. This inspects the two call
    sites directly (`tests/utils/base.py` and
    `tests/fixtures/enhanced_test_factory.py`) via the same AST-call-detection
    used by the source guard below, rather than instantiating either full test
    base -- doing that from inside a test module would recurse.
    """

    def test_verenigingen_test_case_setup_class_calls_all_three_seeders(self):
        path = APP_ROOT / "verenigingen" / "tests" / "utils" / "base.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = called_names(tree)
        for seeder in ("ensure_root_item_group", "ensure_root_customer_group", "ensure_root_supplier_group"):
            with self.subTest(seeder=seeder):
                self.assertIn(seeder, calls, f"tests/utils/base.py never calls {seeder}()")

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
