#!/usr/bin/env python3
"""Unit tests for scripts/validation/submittability_drift_validator.py (#987).

Pure-Python (no bench/site needed): each case builds a small synthetic tree
(a `verenigingen/` package with real DocType JSONs and a real
`hooks/doc_events.py`) under a temp dir and runs it through `scan()`. Run with:
    python -m pytest scripts/validation/tests/test_submittability_drift_validator.py
or plain:
    python scripts/validation/tests/test_submittability_drift_validator.py
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "submittability_drift_validator.py"
_spec = importlib.util.spec_from_file_location("submittability_drift_validator", _MOD_PATH)
sdv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sdv
_spec.loader.exec_module(sdv)


_DEFAULT_HOOKS = """
doc_events = {
    "*": {
        "on_change": "verenigingen.utils.x.y",
    },
}
"""


def _doctype_json_path(name: str) -> str:
    slug = name.lower().replace(" ", "_")
    return f"verenigingen/verenigingen/doctype/{slug}/{slug}.json"


def _build(root: Path, doctypes: dict, hooks_src: str, files: dict):
    """`doctypes`: name -> {"is_submittable": 0|1, "istable": 0|1} (defaults 0).
    `files`: relative path (str) -> source. `hooks_src` becomes
    verenigingen/hooks/doc_events.py."""
    for name, attrs in doctypes.items():
        rel = _doctype_json_path(name)
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "doctype": "DocType",
            "name": name,
            "is_submittable": attrs.get("is_submittable", 0),
            "istable": attrs.get("istable", 0),
        }
        p.write_text(json.dumps(data))

    hooks_path = root / "verenigingen" / "hooks" / "doc_events.py"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(hooks_src)

    for rel, src in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)


def _scan(doctypes: dict, hooks_src: str = _DEFAULT_HOOKS, files: dict = None):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _build(root, doctypes, hooks_src, files or {})
        return sdv.scan(root, extra_app_dirs=[])


# --------------------------------------------------------------------------- #
# Rule 1: hooks/doc_events.py
# --------------------------------------------------------------------------- #


class HookRuleTest(unittest.TestCase):
    def test_hook_on_non_submittable_doctype_is_flagged(self):
        hooks = """
doc_events = {
    "Donation": {
        "on_submit": "verenigingen.a.b",
        "on_cancel": "verenigingen.a.c",
    },
}
"""
        result = _scan({"Donation": {"is_submittable": 0}}, hooks_src=hooks)
        self.assertEqual(1, len(result.hook_violations))
        v = result.hook_violations[0]
        self.assertEqual("Donation", v.doctype)
        self.assertEqual(["on_cancel", "on_submit"], v.events)

    def test_hook_on_submittable_doctype_is_the_negative_control(self):
        """A genuinely submittable doctype registering the SAME hooks must
        NOT be flagged -- without this, a validator reporting zero findings
        and one that is simply broken look identical (CLAUDE.md's rule)."""
        hooks = """
doc_events = {
    "Membership": {
        "on_submit": "verenigingen.a.b",
        "on_cancel": "verenigingen.a.c",
    },
}
"""
        result = _scan({"Membership": {"is_submittable": 1}}, hooks_src=hooks)
        self.assertEqual([], result.hook_violations)

    def test_wildcard_key_is_never_flagged(self):
        result = _scan({}, hooks_src=_DEFAULT_HOOKS)
        self.assertEqual([], result.hook_violations)

    def test_unresolvable_doctype_is_unresolved_not_a_violation(self):
        hooks = """
doc_events = {
    "Sales Invoice": {
        "on_submit": "verenigingen.a.b",
    },
}
"""
        result = _scan({}, hooks_src=hooks)  # no app anywhere defines Sales Invoice here
        self.assertEqual([], result.hook_violations)
        self.assertEqual(1, len(result.hook_unresolved))
        self.assertEqual("Sales Invoice", result.hook_unresolved[0][0])


# --------------------------------------------------------------------------- #
# Rule 2: .submit() / .cancel()
# --------------------------------------------------------------------------- #


class SubmitCancelRuleTest(unittest.TestCase):
    def test_submit_on_non_submittable_doctype_via_get_doc_is_flagged(self):
        src = (
            "import frappe\n\n"
            "def make():\n"
            "    mandate = frappe.get_doc({'doctype': 'SEPA Mandate', 'member': 'x'})\n"
            "    mandate.submit()\n"
        )
        result = _scan(
            {"SEPA Mandate": {"is_submittable": 0}},
            files={"verenigingen/mod/x.py": src},
        )
        self.assertEqual(1, len(result.submit_cancel_violations))
        v = result.submit_cancel_violations[0]
        self.assertEqual("SEPA Mandate", v.doctype)
        self.assertEqual("submit", v.method)
        self.assertFalse(v.in_test)

    def test_submit_via_insert_chain_is_resolved(self):
        """The confirmed #987 defect shape: `x = frappe.get_doc({...}).insert()`
        then `x.submit()` -- the doctype must be traced THROUGH the .insert()
        call, which returns the document itself, not a fresh unrelated object."""
        src = (
            "import frappe\n\n"
            "def make():\n"
            "    donation = frappe.get_doc({'doctype': 'Donation', 'donor': 'x'}).insert()\n"
            "    donation.submit()\n"
            "    return donation\n"
        )
        result = _scan(
            {"Donation": {"is_submittable": 0}},
            files={"verenigingen/services/donation/financial_service.py": src},
        )
        self.assertEqual(1, len(result.submit_cancel_violations))
        self.assertEqual("Donation", result.submit_cancel_violations[0].doctype)

    def test_cancel_on_non_submittable_doctype_is_flagged(self):
        src = (
            "import frappe\n\n"
            "def cancel_it(name):\n"
            "    mandate = frappe.get_doc('ING Checkout Mandate', name)\n"
            "    mandate.cancel()\n"
        )
        result = _scan(
            {"ING Checkout Mandate": {"is_submittable": 0}},
            files={"verenigingen/mod/y.py": src},
        )
        self.assertEqual(1, len(result.submit_cancel_violations))
        self.assertEqual("cancel", result.submit_cancel_violations[0].method)

    def test_submit_on_submittable_doctype_is_the_negative_control(self):
        """The exact same code shape against a genuinely submittable doctype
        (Sales Invoice, Payment Entry, ... -- here a synthetic 'Membership')
        must NOT be flagged."""
        src = (
            "import frappe\n\n"
            "def make():\n"
            "    membership = frappe.get_doc({'doctype': 'Membership', 'member': 'x'})\n"
            "    membership.submit()\n"
        )
        result = _scan(
            {"Membership": {"is_submittable": 1}},
            files={"verenigingen/mod/z.py": src},
        )
        self.assertEqual([], result.submit_cancel_violations)

    def test_unresolvable_receiver_is_unresolved_not_a_violation(self):
        """`self.mandate.submit()` -- an attribute chain, not a locally
        tracked variable -- is honestly reported as unresolved, never guessed
        into a finding either way."""
        src = (
            "class Service:\n"
            "    def go(self):\n"
            "        self.mandate.submit()\n"
        )
        result = _scan({"SEPA Mandate": {"is_submittable": 0}}, files={"verenigingen/mod/w.py": src})
        self.assertEqual([], result.submit_cancel_violations)
        self.assertEqual(1, result.submit_cancel_unresolved)

    def test_test_code_is_scanned_too(self):
        """Decision 3 (#987): production AND test code are both in scope."""
        src = (
            "import frappe\n\n"
            "def test_it():\n"
            "    donation = frappe.get_doc({'doctype': 'Donation'})\n"
            "    donation.submit()\n"
        )
        result = _scan(
            {"Donation": {"is_submittable": 0}},
            files={"verenigingen/tests/test_donation.py": src},
        )
        self.assertEqual(1, len(result.submit_cancel_violations))
        self.assertTrue(result.submit_cancel_violations[0].in_test)


# --------------------------------------------------------------------------- #
# Rule 3: docstatus predicates
# --------------------------------------------------------------------------- #


class DocstatusPredicateRuleTest(unittest.TestCase):
    def test_dict_filter_shape_is_flagged(self):
        src = "import frappe\nfrappe.get_all('SEPA Mandate', {'member': 'x', 'docstatus': 1}, 'name')\n"
        result = _scan({"SEPA Mandate": {"is_submittable": 0}}, files={"verenigingen/mod/a.py": src})
        self.assertEqual(1, len(result.docstatus_violations))
        self.assertEqual("filter", result.docstatus_violations[0].shape)

    def test_operator_pair_filter_shape_is_flagged(self):
        src = "import frappe\nfrappe.db.count('Donation', {'docstatus': ['=', 1]})\n"
        result = _scan({"Donation": {"is_submittable": 0}}, files={"verenigingen/mod/b.py": src})
        self.assertEqual(1, len(result.docstatus_violations))

    def test_list_of_lists_filter_shape_is_flagged(self):
        src = "import frappe\nfrappe.get_all('Donation', filters=[['docstatus', '=', 1]])\n"
        result = _scan({"Donation": {"is_submittable": 0}}, files={"verenigingen/mod/c.py": src})
        self.assertEqual(1, len(result.docstatus_violations))

    def test_attribute_compare_shape_is_flagged(self):
        src = (
            "import frappe\n\n"
            "def check():\n"
            "    donation = frappe.get_doc('Donation', 'D-1')\n"
            "    if donation.docstatus == 1:\n"
            "        pass\n"
        )
        result = _scan({"Donation": {"is_submittable": 0}}, files={"verenigingen/mod/d.py": src})
        self.assertEqual(1, len(result.docstatus_violations))
        self.assertEqual("compare", result.docstatus_violations[0].shape)

    def test_sql_text_single_table_shape_is_flagged(self):
        src = (
            "import frappe\n\n"
            "def q():\n"
            "    return frappe.db.sql('''SELECT name FROM `tabDonation` WHERE docstatus = 1''')\n"
        )
        result = _scan({"Donation": {"is_submittable": 0}}, files={"verenigingen/mod/e.py": src})
        self.assertEqual(1, len(result.docstatus_violations))
        self.assertEqual("sql_text", result.docstatus_violations[0].shape)

    def test_sql_text_aliased_shape_is_flagged(self):
        src = (
            "import frappe\n\n"
            "def q():\n"
            "    return frappe.db.sql('''SELECT d.name FROM `tabDonation` d "
            "WHERE d.docstatus = 1''')\n"
        )
        result = _scan({"Donation": {"is_submittable": 0}}, files={"verenigingen/mod/f.py": src})
        self.assertEqual(1, len(result.docstatus_violations))

    def test_dict_filter_on_submittable_doctype_is_the_negative_control(self):
        src = "import frappe\nfrappe.get_all('Membership', {'docstatus': 1}, 'name')\n"
        result = _scan({"Membership": {"is_submittable": 1}}, files={"verenigingen/mod/g.py": src})
        self.assertEqual([], result.docstatus_violations)

    def test_multijoin_sql_with_unrelated_submittable_alias_is_not_flagged(self):
        """The regression this heuristic must not reintroduce: a multi-join
        query legitimately filters `si.docstatus = 1` (Sales Invoice, a
        SUBMITTABLE doctype in this fixture) while also JOINing a
        non-submittable table (`tabMember`) that carries no docstatus
        predicate of its own. Correlating by mere co-occurrence in the same
        string (the FIRST version of this heuristic) flagged 'Member' here
        too -- measured on the real tree as ~90 false positives across
        similar queries. It must not recur."""
        src = (
            "import frappe\n\n"
            "def q():\n"
            "    return frappe.db.sql('''\n"
            "        SELECT si.name FROM `tabMember` mem\n"
            "        JOIN `tabSales Invoice` si ON si.customer = mem.customer\n"
            "        WHERE si.docstatus = 1\n"
            "    ''')\n"
        )
        result = _scan(
            {"Member": {"is_submittable": 0}, "Sales Invoice": {"is_submittable": 1}},
            files={"verenigingen/mod/h.py": src},
        )
        self.assertEqual([], result.docstatus_violations)

    def test_docstatus_lt_2_is_not_flagged(self):
        """The CORRECT predicate (#350's own fix) must never be a finding."""
        src = "import frappe\nfrappe.get_all('Donation', {'docstatus': ['<', 2]}, 'name')\n"
        result = _scan({"Donation": {"is_submittable": 0}}, files={"verenigingen/mod/i.py": src})
        self.assertEqual([], result.docstatus_violations)

        sql_src = (
            "import frappe\n\n"
            "def q():\n"
            "    return frappe.db.sql('''SELECT name FROM `tabDonation` WHERE docstatus < 2''')\n"
        )
        result2 = _scan({"Donation": {"is_submittable": 0}}, files={"verenigingen/mod/j.py": sql_src})
        self.assertEqual([], result2.docstatus_violations)

    def test_ledger_convention_allowlist_is_not_flagged(self):
        """GL Entry etc. carry docstatus=1 by ERPNext's own established
        accounting convention, independent of is_submittable -- see the
        module docstring. Must stay silent even though GL Entry genuinely is
        is_submittable=0 in this fixture."""
        src = "import frappe\nfrappe.db.count('GL Entry', {'docstatus': 1})\n"
        result = _scan({"GL Entry": {"is_submittable": 0}}, files={"verenigingen/mod/k.py": src})
        self.assertEqual([], result.docstatus_violations)

    def test_child_table_docstatus_is_not_flagged(self):
        """A child table's docstatus column mirrors its PARENT's -- filtering
        it is standard usage, not the #987/#350 drift. `istable=1` alone
        (regardless of name) must exempt it from rule 3."""
        src = "import frappe\nfrappe.get_all('Team Member', {'docstatus': 1}, 'name')\n"
        result = _scan(
            {"Team Member": {"is_submittable": 0, "istable": 1}},
            files={"verenigingen/mod/l.py": src},
        )
        self.assertEqual([], result.docstatus_violations)

    def test_unresolvable_doctype_is_unresolved_not_a_violation(self):
        src = "import frappe\nfrappe.get_all('Sales Invoice', {'docstatus': 1}, 'name')\n"
        result = _scan({}, files={"verenigingen/mod/m.py": src})  # Sales Invoice unknown here
        self.assertEqual([], result.docstatus_violations)
        self.assertEqual(1, result.docstatus_unresolved)


# --------------------------------------------------------------------------- #
# Baseline (ratchet) machinery
# --------------------------------------------------------------------------- #


class BaselineRatchetTest(unittest.TestCase):
    def test_a_key_not_in_the_baseline_is_new_growth(self):
        counts = {"a.py::submit::Donation": 1}
        self.assertEqual(counts, sdv.new_findings(counts, baseline={}))

    def test_a_key_at_or_below_its_baselined_count_is_not_growth(self):
        counts = {"a.py::submit::Donation": 1}
        baseline = {"a.py::submit::Donation": 1}
        self.assertEqual({}, sdv.new_findings(counts, baseline))

    def test_a_higher_count_for_an_existing_key_is_growth(self):
        counts = {"a.py::submit::Donation": 2}
        baseline = {"a.py::submit::Donation": 1}
        self.assertEqual(counts, sdv.new_findings(counts, baseline))

    def test_write_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "baseline.txt"
            counts = {"a.py::submit::Donation": 2, "b.py::hook::SEPA Mandate": 1}
            sdv.write_baseline(path, counts)
            self.assertEqual(counts, sdv.load_baseline(path))

    def test_missing_baseline_file_loads_as_empty(self):
        self.assertEqual({}, sdv.load_baseline(Path("/nonexistent/path/baseline.txt")))

    def test_end_to_end_a_new_call_site_fails_the_gate_a_known_one_does_not(self):
        """The gate itself, not just the comparison helper: a fresh finding
        with no baseline is reported as NEW; the identical finding, once
        baselined, is silent (still counted, but not blocking)."""
        src = (
            "import frappe\n\n"
            "def make():\n"
            "    donation = frappe.get_doc({'doctype': 'Donation'})\n"
            "    donation.submit()\n"
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build(root, {"Donation": {"is_submittable": 0}}, _DEFAULT_HOOKS, {"verenigingen/mod/probe.py": src})
            result = sdv.scan(root, extra_app_dirs=[])
            counts = sdv._counts_from_result(result, root)

        # No baseline at all -> this is growth.
        self.assertTrue(sdv.new_findings(counts, {}))
        # Baselined at the same count -> no growth.
        self.assertEqual({}, sdv.new_findings(counts, baseline=counts))


if __name__ == "__main__":
    unittest.main()
