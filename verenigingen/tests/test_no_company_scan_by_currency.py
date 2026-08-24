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
  ``{"country": ...}`` -- is not checked here (measured on develop: 4 such sites, #532);
* it only sees filters written as **literals in the call**. Confirmed still invisible, and
  each of these is a working way to write the same borrow: a filter dict held in a variable
  (``f = {"default_currency": "EUR"}; get_value("Company", f, "name")``), a ``frappe.qb``
  query, raw ``frappe.db.sql``, and a Python-side ``if c.default_currency == "EUR"`` after
  an unfiltered ``get_all``. A shape check cannot reach any of them; the behavioural pins
  below are what covers that ground;
* it checks the ``filters``/``or_filters`` positions only, so a filter smuggled through
  some other keyword would be missed;
* ``get_all("Company", limit=1)`` / ``get_value("Company", {}, "name")`` -- "scan by nothing
  at all" -- is a much larger sibling class (measured on develop: **109** occurrences) and
  is deliberately out of scope, tracked as #532. It needs its own triage because the two
  halves do not even agree with each other. Measured on ``test_site_2``, 50 companies:

  ================================================  ==========================  =========
  expression                                        resolves to                 direction
  ================================================  ==========================  =========
  ``get_value("Company", {}, "name")``              ``TEST EBkh Cleanup Cov``   newest
  ``get_all("Company", limit=1)``                   ``_Test Company``           oldest
  ================================================  ==========================  =========

  ``db.get_value`` has no ``order_by`` and falls back to ``creation DESC``, while
  ``get_all`` is meta-driven and ``Company`` sorts ``creation ASC``. #532's body describes
  the whole class as taking the oldest; that is true of the ``get_all`` half only. A fix
  that is right for one half is not automatically right for the other;
* it says nothing about whether an owned fixture is *correct*, only that a currency scan is
  absent.

The behavioural pins are the other half:
``verenigingen/tests/support/test_eur_company_decoy.py`` (the control),
``test_processors_base.test_persist_eur_company_ignores_a_newer_eur_company``,
``test_termination_integration_extra_coverage.test_get_company_never_borrows_by_currency``,
``test_sepa_xml_compliance``'s
``test_invoices_are_posted_under_the_owned_company_not_the_newest_eur_one``, and
``test_chapter_cost_center_seeding.test_seeder_heals_by_name_not_to_the_newest_eur_company``
-- the last one covering ``tests/setup/__init__.py``, which this guard used to allowlist.
"""

import ast
import os
import unittest

import verenigingen

# Paths are relative to the `verenigingen` package root. Each entry needs a reason, and the
# reason has to be about why the scan is CORRECT there -- not about it being inconvenient
# to change.
ALLOWED = {
    # The defect itself, isolated in one place so the pins above can name what they pin.
    # Called by nothing except those pins.
    "tests/support/eur_company_decoy.py": "the defect under test, quarantined for pins",
}


# The keyword arguments that carry a filter. `fields=` and `pluck=` are deliberately NOT
# here: `get_all("Company", fields=["name", "default_currency"])` READS the currency, it
# does not constrain on it, and treating any list containing the string as a filter turns
# that into a false positive.
_FILTER_KEYWORDS = frozenset({"filters", "or_filters"})


def _is_currency_condition(node) -> bool:
    """A single list/tuple filter condition constraining ``default_currency``.

    Covers ``["default_currency", "=", "EUR"]`` and the four-element
    ``["Company", "default_currency", "=", "EUR"]``, in list or tuple form. Checks the
    node's own elements only -- never a recursive walk for the bare string, which would
    also match ``get_value("Company", name, "default_currency")`` (a read, not a filter):
    measured over the app, a recursive walk adds **58** such false positives while this
    adds **zero**.
    """
    return isinstance(node, (ast.List, ast.Tuple)) and any(
        isinstance(element, ast.Constant) and element.value == "default_currency" for element in node.elts
    )


def _mentions_currency(node) -> bool:
    """Does this filter argument constrain ``default_currency``, in any of its shapes?

    ``{"default_currency": "EUR"}``, ``[["default_currency", "=", "EUR"]]`` and
    ``[{"default_currency": "EUR"}]`` are all the same query to Frappe, and the list form
    is the one a future author reaches for first. The original guard understood only the
    dict, so it would have gone quietly green on either list shape.
    """
    if isinstance(node, ast.Dict):
        return any(isinstance(key, ast.Constant) and key.value == "default_currency" for key in node.keys)
    if isinstance(node, (ast.List, ast.Tuple)):
        return _is_currency_condition(node) or any(_mentions_currency(el) for el in node.elts)
    return False


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
        # Only the filter POSITIONS, not every argument. In `get_value`/`get_all`/`exists`
        # the second positional argument is the name-or-filters slot and the third is the
        # fieldname, so widening past `args[1]` only buys false positives once lists are
        # in scope. Measured: this loses none of the sites the dict-only guard found.
        candidates = list(node.args[1:2]) + [kw.value for kw in node.keywords if kw.arg in _FILTER_KEYWORDS]
        if any(_mentions_currency(arg) for arg in candidates):
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

    def test_the_guard_sees_every_filter_shape_and_no_read(self):
        """The detector's own control: the shapes it must catch, and the ones it must not.

        The quarantined copy in ``eur_company_decoy.py`` is only the dict shape, so
        ``test_the_guard_can_actually_see_the_pattern`` above says nothing about the list
        forms -- and the list form is the one a future author reaches for first, because it
        is what Frappe's own docs use. The negative half matters just as much: a recursive
        walk for the bare string ``"default_currency"`` catches all of these AND **58**
        legitimate reads across this app (measured), which is a guard nobody can keep
        green.
        """
        must_flag = [
            'frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")',
            'frappe.get_all("Company", filters=[["default_currency", "=", "EUR"]])',
            'frappe.get_all("Company", filters=[{"default_currency": "EUR"}])',
            'frappe.get_all("Company", filters=[["Company", "default_currency", "=", "EUR"]])',
            'frappe.db.exists("Company", {"default_currency": "EUR"})',
            'frappe.get_all("Company", or_filters=[("default_currency", "=", "EUR")])',
        ]
        must_not_flag = [
            # reads the field, does not constrain on it
            'frappe.db.get_value("Company", name, "default_currency")',
            'frappe.get_all("Company", fields=["name", "default_currency"])',
            'frappe.get_all("Company", filters={"abbr": "TPIC"}, fields=["default_currency"])',
            # a different doctype entirely
            'frappe.db.get_value("Currency", {"default_currency": "EUR"}, "name")',
        ]
        for source in must_flag:
            with self.subTest(source=source):
                self.assertTrue(list(_currency_scans(ast.parse(source))), "not detected")
        for source in must_not_flag:
            with self.subTest(source=source):
                self.assertFalse(list(_currency_scans(ast.parse(source))), "false positive")

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
