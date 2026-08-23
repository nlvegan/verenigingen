"""No code in this app may resolve a ``Company`` by scanning for a currency.

The bug class
-------------
Test setup that says "give me a company whose ``default_currency`` is EUR" is the #394
anti-pattern -- borrowing a fixture instead of owning one -- with an ordering trap on top:
``frappe.db.get_value`` takes no ``order_by`` and defaults to ``creation DESC``, so the
expression returns the **newest** match, i.e. whatever EUR company a co-tenant suite in the
shard created last. Shard bins re-pack on measured runtime, so editing any test file can
change which company that is.

Measured on ``test_site_2``, 2026-08-23: 30 EUR companies present;
``get_value("Company", {"default_currency": "EUR"}, "name")`` returned
``'TEST EBkh Cleanup Cov Co'`` while ``get_eur_test_company()`` returned the app's own
``'TEST-Payment-Integration-Company'``. One of the 30 (``'EBH Migration Test Co'``) carries
neither ``default_receivable_account`` nor ``default_income_account`` -- the chart-less
company whose borrow produced 101 failures across two shards (#237).

Why a guard and not just the fixes
----------------------------------
This exact class has now been fixed three times and grown back twice. The #394 sweep fixed
two copies of ``_persist_eur_company``, missed a third, and the count turned out to be
eight; ``test_processors_base`` was the copy that sweep still missed, and it was found by
this change. "Add the file to the guard in the same commit as the fix" is the rule that was
missing, so this is the guard.

What it does NOT enforce
------------------------
It is a **shape** check, not a behaviour check. It cannot tell a legitimate resolution from
a borrow that happens to use a different shape:

* resolving a Company by any other attribute -- ``{"abbr": ...}``, ``{"company_name": ...}``,
  ``{"country": ...}`` -- is not checked here;
* ``get_all("Company", limit=1)`` / ``get_value("Company", {}, "name")`` -- "scan by nothing
  at all" -- is a much larger sibling class (measured on develop: ~115 occurrences) and is
  deliberately out of scope; and
* it says nothing about whether an owned fixture is *correct*, only that a currency scan is
  absent.

The behavioural pins are the other half:
``verenigingen/tests/support/test_eur_company_decoy.py`` (the control),
``test_processors_base.test_persist_eur_company_ignores_a_newer_eur_company``,
``test_termination_integration_extra_coverage.test_get_company_never_borrows_by_currency``,
and ``test_sepa_xml_compliance.test_invoice_company_is_owned_not_the_newest_eur_company``.
"""

import ast
import os
import unittest

import verenigingen

# Paths are relative to the `verenigingen` package root. Each entry needs a reason, and the
# reason has to be about why the scan is CORRECT there -- not about it being inconvenient
# to change.
ALLOWED = {
    # The harness's own site-level heal for `Verenigingen Settings.company` in
    # `before_tests`, run when that single is unset or points at a company that no longer
    # exists. Not a test's own fixture: its blast radius is every test that reads the
    # single, and the EUR preference is load-bearing for the plain-`unittest.TestCase`
    # classes that need a EUR company and have no harness to pin one. Making it own a
    # company by name is the right change and it needs its own CI-proved commit, because no
    # local site can exercise the branch (all of them have the single set).
    "tests/setup/__init__.py": "site-level heal in before_tests; see module docstring",
    # The defect itself, isolated in one place so the pins above can name what they pin.
    # Called by nothing except those pins.
    "tests/support/eur_company_decoy.py": "the defect under test, quarantined for pins",
}


def _dict_mentions_currency(node) -> bool:
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "default_currency" for key in node.keys
    )


def _first_arg_is_company(call: ast.Call) -> bool:
    return bool(call.args) and isinstance(call.args[0], ast.Constant) and call.args[0].value == "Company"


def _currency_scans(tree: ast.AST):
    """Yield line numbers of calls that resolve a Company from a currency filter.

    AST rather than a text search on purpose: several of the fixes in this change quote the
    defective expression verbatim in a docstring or comment, to say what was wrong and what
    it resolved to. A regex over source would flag that prose and push the next author into
    deleting the explanation to appease the guard.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _first_arg_is_company(node):
            continue
        candidates = list(node.args[1:]) + [kw.value for kw in node.keywords]
        if any(_dict_mentions_currency(arg) for arg in candidates):
            yield node.lineno


class TestNoCompanyScanByCurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.dirname(os.path.abspath(verenigingen.__file__))

    def _walk_app(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in {"node_modules", "__pycache__"}]
            for filename in filenames:
                if filename.endswith(".py"):
                    path = os.path.join(dirpath, filename)
                    yield os.path.relpath(path, self.root), path

    def test_no_company_is_resolved_by_currency(self):
        found = {}
        for rel, path in self._walk_app():
            with open(path, encoding="utf-8") as handle:
                try:
                    tree = ast.parse(handle.read(), filename=path)
                except SyntaxError:
                    continue  # not this guard's job to police parse errors
            lines = sorted(set(_currency_scans(tree)))
            if lines and rel not in ALLOWED:
                found[rel] = lines

        self.assertEqual(
            found,
            {},
            "These resolve a Company by scanning for a currency. `db.get_value` orders by "
            "`creation DESC`, so the winner is whatever EUR company a co-tenant suite "
            "created last. Own the fixture by name instead -- "
            "`verenigingen.tests.support.sepa_test_company.get_eur_test_company()` for a "
            "EUR company with a usable chart of accounts, or `self._get_test_company()` on "
            "an EnhancedTestCase. If a scan really is right here, add the path to ALLOWED "
            "with a reason.",
        )

    def test_the_guard_can_actually_see_the_pattern(self):
        """A guard without a control proves nothing.

        The quarantined copy in ``tests/support/eur_company_decoy.py`` is a live instance of
        exactly the shape this guard exists to reject. If the detector stops recognising it
        -- a refactor, a Frappe API change, an AST assumption that stopped holding -- this
        test goes red while ``test_no_company_is_resolved_by_currency`` would go quietly,
        permanently green.
        """
        path = os.path.join(self.root, "tests", "support", "eur_company_decoy.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        self.assertTrue(
            list(_currency_scans(tree)),
            "the detector no longer recognises the pattern it exists to find",
        )

    def test_every_allowlist_entry_still_exists_and_still_scans(self):
        """An allowlist entry that no longer needs to be there is a hole, not a comment."""
        for rel in ALLOWED:
            path = os.path.join(self.root, rel)
            self.assertTrue(os.path.exists(path), f"ALLOWED names a file that is gone: {rel}")
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            self.assertTrue(
                list(_currency_scans(tree)),
                f"{rel} no longer scans by currency -- remove it from ALLOWED",
            )
