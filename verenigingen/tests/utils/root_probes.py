"""Shared machinery for "is this ERPNext tree root seeded" source guards.

Extracted from `verenigingen.tests.test_harness_territory_root`, which needed this
exact shape (savepoint-scoped row deletion, "reaches a harness base" detection, an
AST walk for un-harnessed test classes) for the Territory root (#516/#524).
`test_harness_erpnext_group_roots` (#562) needs the identical shape for the Item
Group / Customer Group / Supplier Group roots, so this module is the one place it
lives rather than a second copy the duplicate-helper ratchet would (correctly) flag.
"""

import ast
import contextlib

import frappe

#: Bases whose setUp/setUpClass reaches the tree-root seeders and therefore, after
#: #524 and #562, all five hardcoded roots. `BaseTestCase` is an alias for both
#: `VereningingenTestCase` and an `EnhancedTestCase` subclass depending on the
#: importing module; either way it is covered.
HARNESS_BASES = {"VereningingenTestCase", "EnhancedTestCase", "BaseTestCase"}


@contextlib.contextmanager
def rows_deleted(doctype, *names):
    """Take the named rows away for the block, then put them back.

    Raw SQL rather than `frappe.delete_doc`: on any warm site a tree root has
    children and NestedSet refuses to delete it. A savepoint rollback undoes both
    the delete and whatever the code under test inserted, so the tree is identical
    afterwards -- measured on test_site_1: 9 rows before, 9 after, same names.

    The row count is checked rather than assumed, because the savepoint is one
    `commit()` away from being gone. `ensure_erpnext_base_masters()` -- one of the
    seeders callers wire into `_ROOT_SEEDERS` -- commits, and measured on
    test_site_1: a `frappe.db.commit()` inside a savepoint makes
    `rollback(save_point=...)` raise `OperationalError (1305, 'SAVEPOINT ... does
    not exist')` and leaves the write standing. Wire such a seeder into the chain
    below and this raw DELETE becomes PERMANENT, taking the tree away from every
    later class in the shard. Nothing on the current path commits; the check is
    here so that if one ever does, the damage is reported where it happened rather
    than as a link error in an unrelated module.
    """
    before = frappe.db.count(doctype)
    # A UNIQUE savepoint name per invocation, not a shared constant. MariaDB lets a
    # second SAVEPOINT of the SAME name replace the first, so two nested blocks
    # sharing one name make the inner `ROLLBACK TO` land on the inner point and the
    # OUTER delete stand -- measured: nesting two of these on test_site_1 deleted
    # `All Supplier Groups` permanently and the guard below is what reported it.
    # The guard caught it; the unique name is why it cannot recur.
    save_point = f"row_probe_{frappe.generate_hash(length=8)}"
    frappe.db.savepoint(save_point)
    try:
        for name in names:
            frappe.db.sql(f"DELETE FROM `tab{doctype}` WHERE name = %s", name)
        yield
    finally:
        # Nested `finally`: when the savepoint has been released the rollback
        # itself raises, so the count has to be taken in a handler that runs
        # anyway -- otherwise the only signal is a bare `OperationalError 1305`
        # naming a savepoint, which says nothing about the tree being gone.
        try:
            frappe.db.rollback(save_point=save_point)
        finally:
            after = frappe.db.count(doctype)
            if after != before:
                raise AssertionError(
                    f"this probe did not restore tab{doctype}: {before} rows before, "
                    f"{after} after. Something inside the block committed, which released "
                    "the savepoint and made the raw DELETE permanent. See this helper's "
                    "docstring."
                )


def looks_like_a_test_class(node: ast.ClassDef, base_names: set) -> bool:
    """A base ending in `TestCase`, or test methods regardless of the base name.

    The base-name half alone skips a class that inherits an imported harness
    subclass under some other name (`class X(ReconBase)`), which is exactly the
    class this guard exists to find. Test methods are the property that does not
    depend on what the author called the base.
    """
    if any(name.endswith("TestCase") for name in base_names):
        return True
    return any(
        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (child.name.startswith("test") or child.name == "runTest")
        for child in node.body
    )


def _base_names(node: ast.ClassDef) -> set:
    return {base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "") for base in node.bases}


def non_harness_test_classes(tree: ast.Module) -> list:
    """Names of test classes in `tree` that reach neither harness base.

    Resolves LOCAL inheritance chains: a module that factors a per-file base
    class out of a harness base (`class _XBase(EnhancedTestCase): ...` /
    `class TestFoo(_XBase): ...`) is common enough (#562's
    `test_application_payments_invoice_paths.py`) that checking only each
    class's own `bases` tuple flags every such subclass as unharnessed
    regardless of what the intermediate class extends. A base name that is
    NOT defined in this same file (an imported class under some other name)
    still cannot be resolved further -- see `looks_like_a_test_class`'s
    docstring for why that residual is accepted rather than chased.
    """
    class_bases = {node.name: _base_names(node) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}

    def reaches_harness(name: str, seen: set) -> bool:
        if name in HARNESS_BASES:
            return True
        if name not in class_bases or name in seen:
            return False
        seen.add(name)
        return any(reaches_harness(base, seen) for base in class_bases[name])

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = class_bases[node.name]
        if not looks_like_a_test_class(node, base_names):
            continue
        if any(reaches_harness(base, set()) for base in base_names):
            continue
        offenders.append(node.name)
    return offenders
