#!/usr/bin/env python3
"""Blocks a doctype's submit/cancel workflow from being reachable, called, or
filtered on when its own DocType JSON says `is_submittable = 0`.

Why this exists (#987, ancestor #350)
--------------------------------------
Nothing in Frappe stops `doc.submit()` / `doc.cancel()` from running against a
doctype whose JSON carries `is_submittable = 0` -- `Document._submit()` and
`._cancel()` do not check the meta flag. So code, hooks, tests and fixtures can
(and did) drift into disagreeing about which docstatus values are actually
possible for a given doctype. #350 was one symptom: two production report
queries filtered Donation (is_submittable=0) by `docstatus = 1` and therefore
aggregated nothing, on every deployment, silently. #987's own measurement found
a SECOND, independent shape of the same drift: `hooks/doc_events.py` registers
`on_submit`/`on_cancel` for both Donation and SEPA Mandate even though neither
is submittable, and a shared test factory's get-or-create filter
(`{"docstatus": 1}` against SEPA Mandate) can never match a real row, so it
silently never reuses an existing mandate.

Three rules
-----------
1. HOOK: `on_submit` / `on_cancel` / `before_submit` / `before_cancel` /
   `on_update_after_submit` registered in `hooks/doc_events.py` for a doctype
   whose JSON says `is_submittable = 0`.
2. SUBMIT_CANCEL: `.submit()` / `.cancel()` called on a doc of a non-submittable
   doctype, in production AND test code. Resolution is a best-effort, per-function,
   in-order AST walk: a variable is "known" to hold a doctype only when it was
   most recently assigned from `frappe.get_doc("X", ...)`, `frappe.get_doc({"doctype":
   "X", ...})` or `frappe.new_doc("X")` in the SAME function/method (no cross-function,
   cross-file, or attribute-chain tracking -- `self.mandate.submit()` is NOT
   resolved). Anything the resolver cannot pin down is counted as UNRESOLVED and
   reported separately, never silently dropped and never guessed into a finding.
3. DOCSTATUS_PREDICATE: a `docstatus == 1` comparison, a `{"docstatus": 1}` (or
   `{"docstatus": ["=", 1]}`) filter dict, or a `["docstatus", "=", 1]` list-filter
   triple, correlated with a doctype the same way: the first positional argument
   (or `doctype=` keyword) of a recognized frappe read API (`frappe.get_all`,
   `frappe.get_list`, `frappe.get_value`, `frappe.db.get_value`, `frappe.db.get_list`,
   `frappe.db.get_all`, `frappe.db.count`, `frappe.db.get_values`,
   `frappe.client.get_list`) for the dict/list shapes, or a variable's tracked
   doctype (see rule 2) for the `x.docstatus == 1` shape. A fourth, deliberately
   separate heuristic reproduces #350's own original shape -- raw SQL text: any
   string literal that looks like a SQL query (contains a bare `FROM`) is searched
   for `` `tab<DocType>` `` alongside a `docstatus = 1` predicate NOT already
   qualified as `< 2` / `!= 1`. This is coarser than the AST shapes (it cannot
   tell which table in a multi-join query the predicate binds to) and is
   reported as its own shape (`sql_text`) so a false positive is easy to spot
   and dismiss.

Known false-positive risk, and the allowlist that closes it
-------------------------------------------------------------
ERPNext writes `docstatus = 1` directly (never through `.submit()`) onto rows of
several of its OWN non-submittable "ledger" doctypes as an established
convention independent of the submit/cancel workflow -- `general_ledger.py`
literally calls `gle.submit()` on GL Entry, which is `is_submittable = 0`
(documented at length in `verenigingen/tests/test_harness_leak_attribution.py`,
which exists precisely because a leak-detection routine here once assumed
`docstatus == 1` meant "submitted" and broke on exactly this doctype). A rule 3
scan with no exception would fire on every legitimate `frappe.db.count("GL
Entry", {"docstatus": 1})` in this app. `DOCSTATUS_CONVENTION_ALLOWLIST` below
names the doctypes where this is documented, established behaviour, not drift --
deliberately a short, explicit list, not a way to silence a real finding.

Resolving doctypes across installed apps
------------------------------------------
This app's own DocType JSONs are authoritative for anything named in them. For
a doctype this app does not define (Sales Invoice, Payment Entry, Journal Entry,
Bank Transaction, Unreconcile Payment, Expense Claim, ...), the validator also
looks under the OTHER apps on the bench (frappe, erpnext, hrms, payments -- the
same fixed list `doctype_name_validator.py` uses, and for the same reason: an
app installed on this dev machine but not declared by this app or CI, e.g.
`owl_theme`, must not change the verdict). When no bench is reachable (the
`Code Validation` CI job checks this app out standalone, with no bench
ancestor), a doctype this app does not define is UNKNOWN, not "safe" and not
"a violation" -- it is reported as unresolved so the gap is visible rather than
silently either crying wolf or missing something.

Usage:
    python scripts/validation/submittability_drift_validator.py            # check
    python scripts/validation/submittability_drift_validator.py --report   # verbose
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_resolution import find_bench_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT_NAME = "verenigingen"
HOOKS_FILE_REL = Path("verenigingen") / "hooks" / "doc_events.py"

# Same fixed list as doctype_name_validator.py, and for the same documented
# reason: "every app under apps/" makes the verdict depend on which apps
# happen to be installed on the machine running this, which is exactly the
# non-determinism that made a gate pass locally and fail in CI on a
# byte-identical tree.
REQUIRED_APPS = ("frappe", "erpnext", "hrms", "payments", "verenigingen")

SKIP_DIR_PARTS = {
    "node_modules", ".git", "__pycache__", ".pytest_cache", "sites", "env",
    "archived_unused", "archived_deleted", "archived_removal", "archived",
}

EVENT_NAMES = {
    "on_submit",
    "on_cancel",
    "before_submit",
    "before_cancel",
    "on_update_after_submit",
}

# frappe read APIs whose first positional argument (or `doctype=` keyword) is a
# doctype name, and whose filters can carry a docstatus predicate.
READ_API_DOTTED = {
    "frappe.get_all",
    "frappe.get_list",
    "frappe.get_value",
    "frappe.db.get_value",
    "frappe.db.get_list",
    "frappe.db.get_all",
    "frappe.db.count",
    "frappe.db.get_values",
    "frappe.client.get_list",
}

# Established, documented exception to rule 3 (see module docstring): ERPNext
# writes docstatus=1 directly onto rows of these non-submittable "ledger"
# doctypes as part of its own accounting engine, independent of the
# submit/cancel workflow. Not a place for a real finding to hide -- if this
# app ever calls `.submit()`/`.cancel()` on one of these (rule 2), that is
# still flagged; only the docstatus-PREDICATE rule exempts them.
DOCSTATUS_CONVENTION_ALLOWLIST = {"GL Entry", "Stock Ledger Entry", "Payment Ledger Entry"}


def _rule3_exempt(doctype: str, child_tables: set) -> bool:
    """True when `doctype` is a documented, legitimate exception to rule 3
    (docstatus predicates): either the small ledger-convention allowlist
    above, or ANY child table (`istable=1`) -- see `build_submittable_map`'s
    docstring for why a child table's docstatus column is not this drift."""
    return doctype in DOCSTATUS_CONVENTION_ALLOWLIST or doctype in child_tables


# ---------------------------------------------------------------------------
# Submittable map
# ---------------------------------------------------------------------------


def _iter_doctype_jsons(app_dir: Path):
    for dirpath, dirnames, filenames in os.walk(app_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS and not d.startswith(".")]
        parent_name = Path(dirpath).name
        for fn in filenames:
            if fn.endswith(".json") and Path(fn).stem == parent_name:
                # Only a doctype's OWN json (path/.../doctype/<name>/<name>.json),
                # not an arbitrary same-named json elsewhere.
                if Path(dirpath).parent.name == "doctype":
                    yield Path(dirpath) / fn


def build_submittable_map(scan_root: Path, extra_app_dirs: list[Path] | None = None) -> tuple:
    """Return (submittable, child_tables).

    `submittable`: doctype name -> is_submittable (bool). `scan_root` (this
    app) wins on any name collision; `extra_app_dirs` only fill in names not
    already known.

    `child_tables`: the set of doctype names with `istable=1`. A child table
    ALWAYS has `is_submittable=0` (only its parent can be submitted), but
    Frappe still writes the parent's docstatus onto every child row as a
    plain mirrored column, and filtering a child table by that column is
    completely standard, correct usage -- NOT the #987/#350 drift rule 3
    exists to catch. Measured on this tree: `Payment Entry Reference` and
    `Team Member` are both child tables filtered by `docstatus = 1`/`= 1` in
    several places, and every one of those is filtering "rows whose PARENT
    document is submitted", which is exactly what that column is for.
    """
    submittable: dict = {}
    child_tables: set = set()

    def _record(data, name):
        submittable[name] = bool(int(data.get("is_submittable", 0) or 0))
        if int(data.get("istable", 0) or 0):
            child_tables.add(name)

    app_dir = scan_root / SCAN_ROOT_NAME
    for path in _iter_doctype_jsons(app_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        _record(data, data.get("name") or path.stem)

    for extra_dir in extra_app_dirs or []:
        if not extra_dir.is_dir():
            continue
        for path in _iter_doctype_jsons(extra_dir):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = data.get("name") or path.stem
            if name in submittable:
                continue  # this app's own definition already won
            _record(data, name)

    return submittable, child_tables


def _find_bench_apps(start: Path) -> Path | None:
    override = os.environ.get("BENCH_APPS")
    if override:
        return Path(override)
    bench_root = find_bench_root(start)
    if bench_root is not None:
        return bench_root / "apps"
    return None


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _iter_python_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_PARTS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _str_const(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _int_const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _dotted_name(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_test_path(rel_path: Path) -> bool:
    parts = rel_path.parts
    return "tests" in parts or any(p.startswith("test_") for p in parts) or rel_path.name.startswith("test_")


# ---------------------------------------------------------------------------
# Rule 1: hooks/doc_events.py
# ---------------------------------------------------------------------------


@dataclass
class HookViolation:
    doctype: str
    events: list
    file_path: Path
    lineno: int


def _extract_doc_events_dict(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "doc_events" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    return None


def scan_hooks(hooks_file: Path, submittable: dict):
    """Return (violations, unresolved) for hooks/doc_events.py.

    `unresolved` entries are (doctype, sorted(events), lineno) for a doctype
    with submit/cancel-family hooks that this run could not resolve at all
    (not in `submittable` -- e.g. an app not on this bench)."""
    violations, unresolved = [], []
    tree = _parse(hooks_file)
    if tree is None:
        return violations, unresolved
    outer = _extract_doc_events_dict(tree)
    if outer is None:
        return violations, unresolved

    for key_node, value_node in zip(outer.keys, outer.values):
        doctype = _str_const(key_node)
        if doctype is None or doctype == "*" or not isinstance(value_node, ast.Dict):
            continue
        found_events = []
        first_lineno = None
        for ev_key, _ev_val in zip(value_node.keys, value_node.values):
            ev_name = _str_const(ev_key)
            if ev_name in EVENT_NAMES:
                found_events.append(ev_name)
                if first_lineno is None:
                    first_lineno = ev_key.lineno
        if not found_events:
            continue
        is_sub = submittable.get(doctype)
        if is_sub is False:
            violations.append(
                HookViolation(
                    doctype=doctype,
                    events=sorted(set(found_events)),
                    file_path=hooks_file,
                    lineno=first_lineno or key_node.lineno,
                )
            )
        elif is_sub is None:
            unresolved.append((doctype, sorted(set(found_events)), first_lineno or key_node.lineno))
    return violations, unresolved


# ---------------------------------------------------------------------------
# Rules 2 & 3: per-function AST resolver
# ---------------------------------------------------------------------------

COMPOUND_BODY_FIELDS = ("body", "orelse", "finalbody")
COMPOUND_TYPES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)
_TryStar = getattr(ast, "TryStar", None)
if _TryStar is not None:
    COMPOUND_TYPES = COMPOUND_TYPES + (_TryStar,)


def _flatten_stmts(body):
    """Yield statements in roughly execution order, descending into compound
    statement bodies (if/for/while/with/try) but NOT into nested function or
    class definitions -- those get their own top-level scope elsewhere."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, COMPOUND_TYPES):
            for attr in COMPOUND_BODY_FIELDS:
                sub = getattr(stmt, attr, None)
                if sub:
                    yield from _flatten_stmts(sub)
            handlers = getattr(stmt, "handlers", None)
            if handlers:
                for handler in handlers:
                    yield from _flatten_stmts(handler.body)


_SELF_RETURNING_METHODS = ("insert", "save")


def _doctype_from_call(call_node) -> str | None:
    """`frappe.get_doc("X", ...)` / `frappe.get_doc({"doctype": "X", ...})` /
    `frappe.new_doc("X")` -> "X". Also sees through a trailing `.insert()` /
    `.save()` -- both return the document itself, and `frappe.get_doc({...}).
    insert()` (assigning the INSERT call's return value, not the bare
    get_doc()) is the standard construction idiom in this app: the confirmed
    #987 defect at `financial_service.py:59` is exactly `donation =
    frappe.get_doc({...}).insert()` followed by `donation.submit()`, which a
    resolver that only looked at `get_doc`/`new_doc` directly would silently
    miss (measured: it did, until this was added). Anything else -> None
    (unresolved)."""
    if not isinstance(call_node, ast.Call):
        return None
    func = call_node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr in _SELF_RETURNING_METHODS:
        return _doctype_from_call(func.value)
    if func.attr not in ("get_doc", "new_doc"):
        return None
    if not (isinstance(func.value, ast.Name) and func.value.id == "frappe"):
        return None
    if not call_node.args:
        return None
    first = call_node.args[0]
    s = _str_const(first)
    if s is not None:
        return s
    if isinstance(first, ast.Dict):
        for k, v in zip(first.keys, first.values):
            if _str_const(k) == "doctype":
                return _str_const(v)
    return None


def _dict_or_list_has_docstatus_1(node) -> bool:
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if _str_const(k) != "docstatus":
                continue
            if _int_const(v) == 1:
                return True
            if isinstance(v, (ast.List, ast.Tuple)) and len(v.elts) == 2:
                op = _str_const(v.elts[0])
                if op == "=" and _int_const(v.elts[1]) == 1:
                    return True
        return False
    if isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            if isinstance(elt, (ast.List, ast.Tuple)) and len(elt.elts) == 3:
                fld, op, val = elt.elts
                if _str_const(fld) == "docstatus" and _str_const(op) == "=" and _int_const(val) == 1:
                    return True
        return False
    return False


@dataclass
class SubmitCancelViolation:
    file_path: Path
    lineno: int
    method: str
    doctype: str
    in_test: bool


@dataclass
class DocstatusViolation:
    file_path: Path
    lineno: int
    shape: str  # "compare" | "filter" | "sql_text"
    doctype: str
    in_test: bool


@dataclass
class ScopeFindings:
    submit_cancel: list = field(default_factory=list)
    submit_cancel_unresolved: int = 0
    docstatus: list = field(default_factory=list)
    docstatus_unresolved: int = 0


class _ScopeResolver(ast.NodeVisitor):
    """Best-effort, function-local variable -> doctype tracking. A fresh
    instance is used for EACH function/method body (and separately for
    module-level code), so nothing leaks across scopes."""

    def __init__(self, submittable: dict, child_tables: set, file_path: Path, in_test: bool):
        self.submittable = submittable
        self.child_tables = child_tables
        self.file_path = file_path
        self.in_test = in_test
        self.var_doctype: dict = {}
        self.findings = ScopeFindings()

    def _resolve_receiver(self, node) -> tuple:
        """Return (doctype_or_None, resolved: bool)."""
        if isinstance(node, ast.Name):
            if node.id in self.var_doctype:
                return self.var_doctype[node.id], True
            return None, False
        if isinstance(node, ast.Call):
            dt = _doctype_from_call(node)
            return dt, dt is not None
        return None, False

    def run(self, stmts):
        for stmt in _flatten_stmts(stmts):
            self._handle_statement(stmt)

    def _handle_statement(self, stmt):
        if isinstance(stmt, ast.Assign):
            self._track_assignment(stmt.targets, stmt.value)
            self._scan_expr(stmt.value)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            self._track_assignment([stmt.target], stmt.value)
            self._scan_expr(stmt.value)
        elif isinstance(stmt, COMPOUND_TYPES):
            test = getattr(stmt, "test", None)
            if test is not None:
                self._scan_expr(test)
            items = getattr(stmt, "items", None)  # With
            if items:
                for it in items:
                    self._scan_expr(it.context_expr)
        else:
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(child, ast.expr):
                    self._scan_expr(child)

    def _track_assignment(self, targets, value_node):
        doctype = None
        if isinstance(value_node, ast.Call):
            doctype = _doctype_from_call(value_node)
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                self.var_doctype[tgt.id] = doctype

    def _scan_expr(self, node):
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            if isinstance(sub, ast.Call):
                self._check_submit_cancel(sub)
                self._check_read_api_docstatus(sub)
            elif isinstance(sub, ast.Compare):
                self._check_docstatus_compare(sub)

    def _check_submit_cancel(self, call_node):
        func = call_node.func
        if not (isinstance(func, ast.Attribute) and func.attr in ("submit", "cancel")):
            return
        doctype, resolved = self._resolve_receiver(func.value)
        if not resolved:
            self.findings.submit_cancel_unresolved += 1
            return
        if doctype is None:
            self.findings.submit_cancel_unresolved += 1
            return
        is_sub = self.submittable.get(doctype)
        if is_sub is False:
            self.findings.submit_cancel.append(
                SubmitCancelViolation(
                    file_path=self.file_path,
                    lineno=call_node.lineno,
                    method=func.attr,
                    doctype=doctype,
                    in_test=self.in_test,
                )
            )

    def _check_read_api_docstatus(self, call_node):
        dotted = _dotted_name(call_node.func)
        if dotted not in READ_API_DOTTED:
            return
        doctype = None
        if call_node.args:
            doctype = _str_const(call_node.args[0])
        if doctype is None:
            for kw in call_node.keywords:
                if kw.arg == "doctype":
                    doctype = _str_const(kw.value)
        if doctype is None:
            return  # non-literal doctype arg -- not our call to make

        filter_node = None
        for kw in call_node.keywords:
            if kw.arg == "filters":
                filter_node = kw.value
                break
        if filter_node is None and len(call_node.args) >= 2:
            filter_node = call_node.args[1]
        if filter_node is None:
            return

        if not _dict_or_list_has_docstatus_1(filter_node):
            return

        is_sub = self.submittable.get(doctype)
        if is_sub is False and not _rule3_exempt(doctype, self.child_tables):
            self.findings.docstatus.append(
                DocstatusViolation(
                    file_path=self.file_path,
                    lineno=call_node.lineno,
                    shape="filter",
                    doctype=doctype,
                    in_test=self.in_test,
                )
            )
        elif is_sub is None:
            self.findings.docstatus_unresolved += 1

    def _check_docstatus_compare(self, compare_node):
        if len(compare_node.ops) != 1 or not isinstance(compare_node.ops[0], ast.Eq):
            return
        left, right = compare_node.left, compare_node.comparators[0]
        receiver = None
        if isinstance(left, ast.Attribute) and left.attr == "docstatus" and _int_const(right) == 1:
            receiver = left.value
        elif isinstance(right, ast.Attribute) and right.attr == "docstatus" and _int_const(left) == 1:
            receiver = right.value
        else:
            return

        doctype, resolved = self._resolve_receiver(receiver)
        if not resolved or doctype is None:
            self.findings.docstatus_unresolved += 1
            return
        is_sub = self.submittable.get(doctype)
        if is_sub is False and not _rule3_exempt(doctype, self.child_tables):
            self.findings.docstatus.append(
                DocstatusViolation(
                    file_path=self.file_path,
                    lineno=compare_node.lineno,
                    shape="compare",
                    doctype=doctype,
                    in_test=self.in_test,
                )
            )
        elif is_sub is None:
            self.findings.docstatus_unresolved += 1


def _iter_function_scopes(tree):
    """Every FunctionDef/AsyncFunctionDef in the module, PLUS a synthetic
    module-level scope for top-level code. Nested defs are found here too
    (ast.walk reaches them), each getting its own independent resolver."""
    yield tree.body  # module level
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.body


_SQL_LIKE = re.compile(r"\bFROM\b", re.IGNORECASE)
_DOCSTATUS_LT_2 = re.compile(r"(?:\b[A-Za-z_][A-Za-z0-9_]*\.)?docstatus\s*<\s*2\b", re.IGNORECASE)
_DOCSTATUS_NE_1 = re.compile(r"(?:\b[A-Za-z_][A-Za-z0-9_]*\.)?docstatus\s*!=\s*1\b", re.IGNORECASE)
# Captures an optional `<alias>.` prefix so a predicate can be correlated back
# to the specific table it binds to in a multi-join query -- see below.
_DOCSTATUS_EQ_1 = re.compile(r"\b(?:([A-Za-z_][A-Za-z0-9_]*)\.)?docstatus\s*=\s*1\b", re.IGNORECASE)
# `` `tabDonation` d `` / `` `tabDonation` AS d `` -- an alias declared for a
# table. Excludes SQL keywords that can legally follow a table reference with
# no alias at all (`` `tabMember`\nWHERE ...``), which would otherwise be
# mis-captured as an "alias".
_SQL_KEYWORDS_AFTER_TABLE = {
    "where", "and", "or", "on", "group", "order", "left", "right", "inner",
    "outer", "join", "union", "set", "values", "limit", "having", "as",
}
_ALIAS_TABLE = re.compile(r"`tab([A-Za-z][A-Za-z0-9 _]*)`\s+(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)
_TAB_NAME = re.compile(r"`tab([A-Za-z][A-Za-z0-9 _]*)`")


def _scan_sql_text(tree, file_path: Path, submittable: dict, child_tables: set, in_test: bool):
    """Find `docstatus = 1` predicates in raw SQL text and correlate each one
    back to the SPECIFIC table it binds to -- not merely any table mentioned
    anywhere in the same query string.

    A multi-join query legitimately has `si.docstatus = 1` (Sales Invoice,
    submittable) sitting beside unrelated `` `tabMember` ``/`` `tabSEPA
    Mandate` `` joins; correlating by mere co-occurrence flagged those as if
    THEY were being filtered by docstatus, which they are not (measured: this
    produced ~90 false positives on the current tree, one per unrelated table
    in each such query -- exactly the "cries wolf" failure mode this module's
    own docstring warns about). So: an aliased predicate (`alias.docstatus =
    1`) is resolved ONLY against a table this same string declares that alias
    for; a bare, unaliased predicate (`docstatus = 1`) is resolved only when
    the string references exactly ONE table, where there is no ambiguity."""
    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        text = node.value
        if not _SQL_LIKE.search(text):
            continue

        eq_matches = [m for m in _DOCSTATUS_EQ_1.finditer(text)]
        if not eq_matches:
            continue

        alias_to_table = {
            alias: table
            for table, alias in _ALIAS_TABLE.findall(text)
            if alias.lower() not in _SQL_KEYWORDS_AFTER_TABLE
        }
        all_tables = _TAB_NAME.findall(text)

        for m in eq_matches:
            # Reject only a NE/LT guard for the SAME alias (or the same bare
            # form) so an aliased "< 2" elsewhere in the query cannot mask an
            # unrelated aliased "= 1".
            alias = m.group(1)
            prefix = re.escape(alias + ".") if alias else ""
            lt2 = re.search(rf"{prefix}docstatus\s*<\s*2\b", text, re.IGNORECASE)
            ne1 = re.search(rf"{prefix}docstatus\s*!=\s*1\b", text, re.IGNORECASE)
            if lt2 or ne1:
                continue

            if alias:
                doctype = alias_to_table.get(alias)
                if doctype is None:
                    continue  # alias not declared in this string -- unresolved, not a finding
            elif len(set(all_tables)) == 1:
                doctype = all_tables[0]
            else:
                continue  # bare predicate, ambiguous multi-table query -- unresolved

            is_sub = submittable.get(doctype)
            if is_sub is False and not _rule3_exempt(doctype, child_tables):
                violations.append(
                    DocstatusViolation(
                        file_path=file_path,
                        lineno=getattr(node, "lineno", 0),
                        shape="sql_text",
                        doctype=doctype,
                        in_test=in_test,
                    )
                )
    return violations


# Files carrying PLANTED bad-shape source-code-as-STRING fixtures for a
# narrower, pre-existing scanner: `test_donation_docstatus_filters.py`'s own
# `DonationQueryScanner` (built for #350) tests itself with literal Python
# strings like `'frappe.db.sql("SELECT name FROM `tabDonation` WHERE
# docstatus = 1")'` -- text meant as INPUT to that other scanner's tests, not
# a real query this app executes. This module's own text-based rule 3 shapes
# (`sql_text` especially, since it scans every string constant in a file) hit
# those same substrings and reported them as if they were live queries.
# Measured: every one of this file's ~19 `sql_text`/`filter` hits traced back
# to a planted `_SQL_BAD_PREDICATE`-shaped fixture, not a real call site.
SELF_TEST_FIXTURE_FILES = {Path("verenigingen/tests/test_donation_docstatus_filters.py")}


def scan_file(path: Path, rel_path: Path, submittable: dict, child_tables: set):
    if rel_path in SELF_TEST_FIXTURE_FILES:
        return ScopeFindings()
    tree = _parse(path)
    if tree is None:
        return ScopeFindings()
    in_test = _is_test_path(rel_path)
    combined = ScopeFindings()
    for scope_body in _iter_function_scopes(tree):
        resolver = _ScopeResolver(submittable, child_tables, path, in_test)
        resolver.run(scope_body)
        combined.submit_cancel.extend(resolver.findings.submit_cancel)
        combined.submit_cancel_unresolved += resolver.findings.submit_cancel_unresolved
        combined.docstatus.extend(resolver.findings.docstatus)
        combined.docstatus_unresolved += resolver.findings.docstatus_unresolved
    combined.docstatus.extend(_scan_sql_text(tree, path, submittable, child_tables, in_test))
    return combined


# ---------------------------------------------------------------------------
# Top-level scan
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    hook_violations: list
    hook_unresolved: list
    submit_cancel_violations: list
    submit_cancel_unresolved: int
    docstatus_violations: list
    docstatus_unresolved: int
    submittable_map: dict
    bench_resolved: bool


def scan(scan_root: Path, extra_app_dirs: list | None = None) -> ScanResult:
    """`scan_root` is the directory CONTAINING the `verenigingen/` package
    (i.e. the repo root, or a synthetic tree shaped like it for tests).
    `extra_app_dirs` are sibling app roots (frappe/erpnext/hrms/payments) to
    resolve doctypes this app does not define; pass None/[] to scan this app
    alone (what CI's standalone checkout gets)."""
    submittable, child_tables = build_submittable_map(scan_root, extra_app_dirs)

    hooks_file = scan_root / HOOKS_FILE_REL
    hook_violations, hook_unresolved = scan_hooks(hooks_file, submittable)

    submit_cancel_violations = []
    submit_cancel_unresolved = 0
    docstatus_violations = []
    docstatus_unresolved = 0

    app_dir = scan_root / SCAN_ROOT_NAME
    for path in _iter_python_files(app_dir):
        rel = path.relative_to(scan_root)
        findings = scan_file(path, rel, submittable, child_tables)
        submit_cancel_violations.extend(findings.submit_cancel)
        submit_cancel_unresolved += findings.submit_cancel_unresolved
        docstatus_violations.extend(findings.docstatus)
        docstatus_unresolved += findings.docstatus_unresolved

    return ScanResult(
        hook_violations=hook_violations,
        hook_unresolved=hook_unresolved,
        submit_cancel_violations=submit_cancel_violations,
        submit_cancel_unresolved=submit_cancel_unresolved,
        docstatus_violations=docstatus_violations,
        docstatus_unresolved=docstatus_unresolved,
        submittable_map=submittable,
        bench_resolved=bool(extra_app_dirs),
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Baseline (ratchet) -- same shape as log_error_arg_order_validator.py's
# ---------------------------------------------------------------------------
#
# This app already has known, pre-existing findings (production `.submit()`
# calls on Payment Plan and ING Checkout Mandate; docstatus predicates in two
# debug scripts and two live production reports -- see #987's own PR for the
# measured list). A zero-tolerance gate (the shape harness_method_shadow_
# validator.py uses) would fail on every commit from day one; a ratchet keyed
# by (file, rule, doctype) blocks anything NEW without demanding every
# existing site be fixed in this one change. Unlike log_error_arg_order_
# validator.py's baseline, this one does NOT ship the shrink-explanation /
# --check-shrink machinery -- proportionate to a validator with a much
# smaller known-violation count; add it if this baseline grows large enough
# to need it.

DEFAULT_BASELINE = Path(__file__).with_name("submittability_drift_baseline.txt")

BASELINE_HEADER = [
    "# Known submittability-drift sites (#987) -- the ratchet baseline for",
    "# scripts/validation/submittability_drift_validator.py. Format:",
    "#     <path>::<rule>::<doctype>::<count>",
    "#",
    "# A commit fails only if it introduces a NEW key here, or raises an",
    "# existing key's count. This file should only ever SHRINK: fix a site and",
    "# regenerate with --update-baseline, or remove the entry by hand once its",
    "# count is genuinely zero. Do not raise a count to silence a new finding.",
]


def _finding_key(rel_path: str, rule: str, doctype: str) -> str:
    return f"{rel_path}::{rule}::{doctype}"


def _counts_from_result(result: ScanResult, root: Path) -> dict:
    counts: dict = {}
    for v in result.hook_violations:
        key = _finding_key(_rel(v.file_path, root), "hook", v.doctype)
        counts[key] = counts.get(key, 0) + 1
    for v in result.submit_cancel_violations:
        key = _finding_key(_rel(v.file_path, root), v.method, v.doctype)
        counts[key] = counts.get(key, 0) + 1
    for v in result.docstatus_violations:
        key = _finding_key(_rel(v.file_path, root), f"docstatus:{v.shape}", v.doctype)
        counts[key] = counts.get(key, 0) + 1
    return counts


def load_baseline(path: Path) -> dict:
    out: dict = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, count = line.rpartition("::")
        if key and count.isdigit():
            out[key] = int(count)
    return out


def new_findings(counts: dict, baseline: dict) -> dict:
    """The ratchet comparison: which counted keys exceed the baseline."""
    return {k: v for k, v in counts.items() if v > baseline.get(k, 0)}


def write_baseline(path: Path, counts: dict) -> None:
    lines = list(BASELINE_HEADER) + [f"{key}::{count}" for key, count in sorted(counts.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="Print every finding, including unresolved counts and known-baselined sites.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update-baseline", action="store_true", help="Regenerate the baseline from the current tree and exit.")
    args = parser.parse_args(argv)

    root = REPO_ROOT
    bench_apps = _find_bench_apps(root)
    extra_app_dirs = []
    if bench_apps is not None:
        extra_app_dirs = [bench_apps / app for app in REQUIRED_APPS if app != "verenigingen"]

    result = scan(root, extra_app_dirs)
    counts = _counts_from_result(result, root)

    if args.update_baseline:
        write_baseline(args.baseline, counts)
        print(f"Wrote {len(counts)} key(s) to {args.baseline}.")
        return 0

    baseline = load_baseline(args.baseline)
    growth = new_findings(counts, baseline)

    total = len(result.hook_violations) + len(result.submit_cancel_violations) + len(result.docstatus_violations)

    if args.report or total:
        print(
            f"Submittability Drift Guard: {len(result.submittable_map)} doctypes resolved "
            f"({'bench found' if result.bench_resolved else 'this app only, no bench ancestor'})."
        )
        print(
            f"  rule 1 (doc_events hooks):      {len(result.hook_violations)} violation(s), "
            f"{len(result.hook_unresolved)} unresolved doctype(s)"
        )
        print(
            f"  rule 2 (.submit()/.cancel()):   {len(result.submit_cancel_violations)} violation(s), "
            f"{result.submit_cancel_unresolved} unresolved call(s)"
        )
        print(
            f"  rule 3 (docstatus predicates):  {len(result.docstatus_violations)} violation(s), "
            f"{result.docstatus_unresolved} unresolved predicate(s)"
        )
        print(f"  {len(growth)} of the above are NEW (not in {args.baseline.name}).")
        print()

    if not total:
        print("Submittability Drift Guard: no submit/cancel hooks, calls, or docstatus predicates against a non-submittable doctype.")
        return 0

    def _key_for(v, rule=None, doctype=None):
        return _finding_key(_rel(v.file_path, root), rule, doctype)

    for v in sorted(result.hook_violations, key=lambda v: (str(v.file_path), v.lineno)):
        key = _key_for(v, "hook", v.doctype)
        if args.report or key in growth:
            tag = "NEW" if key in growth else "known"
            print(
                f"  [{tag}][hook] {_rel(v.file_path, root)}:{v.lineno} {v.doctype!r} is_submittable=0 "
                f"but registers {', '.join(v.events)}"
            )
    for v in sorted(result.submit_cancel_violations, key=lambda v: (str(v.file_path), v.lineno)):
        key = _key_for(v, v.method, v.doctype)
        if args.report or key in growth:
            tag = "NEW" if key in growth else "known"
            kind = "test" if v.in_test else "production"
            print(
                f"  [{tag}][{v.method}] {_rel(v.file_path, root)}:{v.lineno} .{v.method}() on "
                f"{v.doctype!r} ({kind}, is_submittable=0)"
            )
    for v in sorted(result.docstatus_violations, key=lambda v: (str(v.file_path), v.lineno)):
        key = _key_for(v, f"docstatus:{v.shape}", v.doctype)
        if args.report or key in growth:
            tag = "NEW" if key in growth else "known"
            kind = "test" if v.in_test else "production"
            print(
                f"  [{tag}][docstatus:{v.shape}] {_rel(v.file_path, root)}:{v.lineno} against "
                f"{v.doctype!r} ({kind}, is_submittable=0)"
            )

    if args.report:
        for doctype, events, lineno in result.hook_unresolved:
            print(f"  [hook, unresolved] {HOOKS_FILE_REL}:{lineno} {doctype!r} ({', '.join(events)}) -- doctype not found in any resolved app")

    if not growth:
        print(
            f"\nNo NEW submittability drift (#987, ancestor #350) beyond what {args.baseline.name} "
            "already tracks. Existing baselined sites are reported above only with --report."
        )
        return 0

    print(
        "\nEach of the NEW findings above lets a doctype's docstatus reach or be checked against a "
        "submit/cancel-only value (1 or 2) while its own DocType JSON says is_submittable=0 (#987, "
        "ancestor #350). Either remove the submit()/cancel() call and the docstatus predicate, or make "
        "the doctype genuinely submittable (is_submittable=1) and mean it. If this is a deliberate, "
        "reviewed exception, regenerate the baseline with --update-baseline."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
