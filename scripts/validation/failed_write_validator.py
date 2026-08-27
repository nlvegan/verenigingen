#!/usr/bin/env python3
"""Block NEW broad ``except`` handlers that hide a FAILED DATABASE WRITE.

THE BUG CLASS
-------------
A document write throws, a broad ``except`` logs it, and the caller is told the
operation succeeded. Nothing in the return value says the row was never written,
so the only evidence is an Error Log entry nobody reads -- and on CI, a database
that is deleted when the job ends.

PR #280 found NINE production defects of exactly this shape at once. Three of
them had never worked in ANY deployment: no default payment mapping was ever
created, no SEPA retry batch was ever saved, and every Volunteer Skill row
without a level was rejected on insert. Several had thorough, PASSING tests --
the tests asserted the reported outcome, and the reported outcome was "success".
The Select-field validation that raised was the trigger; the swallow is what
turned nine raised exceptions into nine silent data-loss bugs.

WHY THIS IS A SEPARATE VALIDATOR
--------------------------------
``error_swallow_validator.py`` is the sibling rule: a broad ``except`` that logs
and returns a FALSY value. It cannot see this class, and not by accident -- its
four exclusions are precisely where these defects live:

===========================================  ==============================================
error_swallow_validator.scan_file            why it hides a failed write
===========================================  ==============================================
skips functions that never return real       a void writer (MollieAuditLogger.log_event)
skips handlers containing continue/break     the dropped ROW is the bug, not the loop
skips handlers whose returns are truthy      ``return {"success": True}`` is the worst case
skips a non-trailing try with no return      execution resumes as if the write happened
===========================================  ==============================================

The two rules are complementary and must stay separate: this one deliberately
returns nothing for a handler that swallows into a falsy value, because that is
the sibling's turf and reporting it twice would double every message.

That split is drawn by two SEPARATE copies of ``_is_falsy_return`` -- one here, one
in ``error_swallow_validator`` -- and they have DIVERGED. #589 taught the sibling
that a non-empty dict of falsy literals is falsy; this copy still recognises only
``{}``, so ``return {"rows_written": 0}`` from a failed write is the sibling's turf by
the sibling's rule and ``RETURNS_TRUTHY`` by this one. Measured when they diverged:
the overlap on the 8 sites #589 added is ZERO (all read paths, none reported here),
and this rule is advisory in CI, so nothing is double-reported today. It is a
"must stay in step" hazard rather than a live defect -- widen this copy only with the
same both-directions measurement, since ``_is_falsy_return`` feeds
``_classify`` the way the sibling's feeds its condition (5). Applying #589's widening
here today was measured at 0 change (159 sites / 130 functions before and after).

WHAT IS FLAGGED
---------------
A ``try``/``except`` is reported when ALL of these hold:

1. the ``try`` body contains a PERSISTENCE call -- ``.insert()``/``.save()``/
   ``.submit()``/``.db_set()``/``.update_child_table()``,
   ``frappe.db.set_value``/``insert``/``delete``, ``frappe.delete_doc``, or a
   ``frappe.db.sql()`` whose literal statement writes;
2. the ``except`` is broad (bare, ``Exception``, ``BaseException``);
3. the failure never leaves the handler -- no ``raise``, no ``frappe.throw``, no
   ``msgprint(raise_exception=True)``, and no call to one of this repo's own
   re-raising error helpers (``handle_error``/``handle_service_error``);
4. the handler does NOT record the failure anywhere the caller can read it; and
5. the handler exits in a way that tells the caller nothing went wrong.

(5) is reported as one of four outcome classes:

``CLAIMS_SUCCESS``   the handler returns an explicit success flag -- ``True``,
                     ``{"success": True}``, ``OperationResult(success=True)``.
``RETURNS_TRUTHY``   it returns some other real value, which every caller in this
                     codebase reads as "it worked".
``LOOP_CONTINUES``   it ``continue``s, so the row is dropped and the batch still
                     reports success. This is the eBoekhouden/Mollie shape.
``FALLS_THROUGH``    no return at all, and the ``try`` is not the tail of the
                     function, so execution resumes as if the write happened.

THREE CALIBRATIONS, LEARNED THE HARD WAY
----------------------------------------
Each of these was measured; removing any one makes the rule unusable noise.

(a) ``{"success": False, "error": str(e)}`` is TRUTHY but is a CORRECT error
    report, not a swallow. So are ``OperationResult(success=False)`` and any dict
    carrying an ``error``/``errors`` key. Counting them collapsed the useful
    signal: 239 sites became 19 once they were excluded.

(b) A handler that WRITES the failure where the caller can read it is not a
    swallow, however it exits -- ``results["errors"].append(...)``,
    ``results[k]["success"] = False``. That is what cleared most ``continue``
    sites; ``services/billing/invoice_management.py:473`` and ``:747`` are FINE.

(c) A bare ``return True`` can mean FAILURE. ``_step_save_history_changes`` in
    ``services/member/history/member_history_update_service.py`` returns ``True``
    to signal "the save failed", and marks every result failed on the way out.
    Never assume a truthy constant means success: that site is excluded by (b),
    which is checked FIRST for exactly this reason.

On (b), narrowly: "records the failure" means the handler stores something
DERIVED FROM THE EXCEPTION, or writes to a target whose name is about errors, or
flips a ``success``/``ok``/``status`` field to a failing value. A blanket "any
attribute assignment or any .append()" -- which is what the prototype did -- also
swallows real findings: ``self.retry_count += 1`` or ``doc.status = "Draft"`` in
a handler says nothing to the caller about a lost write.

Unlike the sibling rule there is NO requirement that the handler logs. The sibling
excludes silent handlers to keep its own message about log-and-swallow; here the
row is gone either way, and an `except Exception: pass` over a lost write is
strictly worse than a logged one.

KNOWN FALSE POSITIVES
---------------------
``.save``/``.submit``/``.cancel`` are matched by NAME, so a non-Frappe object
with one of those methods (``executor.submit``, ``future.cancel``) reads as a
persistence call. Mark those ``# failed-write-ok: false-positive``.

RATCHET, NOT BIG-BANG
---------------------
Existing sites are recorded in ``failed_write_baseline.txt`` and do not block
anything; only a NEW site, or an extra site in an already-listed function, is
reported. The baseline is keyed ``path::qualified_function::count`` -- not line
numbers, which rot on any edit above them.

    python scripts/validation/failed_write_validator.py --update-baseline

ADVISORY BY DEFAULT. It prints findings and exits 0. Pass ``--strict`` (or set
``FAILED_WRITE_STRICT=1``) to make a new site fail the run; flip the pre-commit
hook to ``--strict`` once the inventory has been triaged.

Escape hatch, matching the ``swallow-ok`` / ``db-begin-ok`` / ``cache-guard-ok``
convention already used in this tree::

    except Exception:  # failed-write-ok: best-effort
        logger.warning(...)

Reasons: best-effort (the write genuinely does not matter and no caller depends
on it), caller-verifies (the caller re-reads the DB and detects the missing row
itself), reported-elsewhere (the failure reaches the caller by a route this
analysis cannot see, e.g. through a local variable), false-positive.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = Path(__file__).with_name("failed_write_baseline.txt")

# The roots the baseline covers. CI scans exactly these; the pre-commit hook scans
# only the files you touched, so its `files`/`exclude` must stay a SUBSET of this --
# a file the hook scans but the baseline does not cover fails spuriously on its
# first edit. `scripts/` is included because a maintenance script that drops a row
# and reports success is this bug class with nobody watching.
SCAN_ROOTS = ("verenigingen", "scripts")

# Method names that persist to the database. Matched by name, so a non-Frappe
# object with the same method reads as a write -- see KNOWN FALSE POSITIVES.
WRITE_METHODS = {
    "insert",
    "save",
    "submit",
    "cancel",
    "delete",
    "db_set",
    "db_insert",
    "db_update",
    "save_or_update",
    "update_child_table",
}

# Dotted calls that persist.
WRITE_FUNCS = {
    "frappe.db.set_value",
    "frappe.db.insert",
    "frappe.db.delete",
    "frappe.db.bulk_insert",
    "frappe.delete_doc",
    "frappe.rename_doc",
    "frappe.db.add_index",
    "frappe.db.multisql",
    "frappe.db.commit",
}

# First words of a raw SQL statement that mean it writes. A SELECT inside the try
# is not a lost write.
WRITING_SQL = ("INSERT", "UPDATE", "DELETE", "REPLACE", "ALTER", "DROP", "CREATE", "TRUNCATE")

# Receivers whose `.delete()`/`.save()` is NOT a database write. Redis lock release
# (`cache.delete(lock_key)`, `redis_conn.delete(lock_key)`) is the live shape: losing
# it costs a lock TTL, not a row. Measured -- these two alone were 2 of 139 findings.
NON_DB_RECEIVERS = ("cache", "redis", "memcach")

BROAD_EXCEPTIONS = {"Exception", "BaseException"}

# Calls that end the flow rather than swallow it. `frappe.throw` is a raise in
# disguise; `msgprint` only raises with raise_exception=True.
PROPAGATING_CALLS = {"throw", "exit", "_exit"}

# This repo's own error helpers re-raise BY DEFAULT: `handle_service_error` takes
# `raise_error=True`, and BaseService's `handle_error` delegates straight to it, so a
# bare `self.handle_error(e, op)` propagates and the failure DOES reach the caller.
# Without this the validator saw no `raise`, concluded the write was swallowed, and
# recorded the site -- inverting the one question it exists to answer.
#
# Three separate definitions share the bare attribute name `handle_error` and the AST
# cannot tell them apart, so the rule has to hold for all three:
#   services/infrastructure/base_service.py       raise_error=True default
#   verenigingen_payments/core/error_handler.py   ends in `raise error`, no off-switch
#   .../utils/financial_error_handler.py          throws only when user_facing=True
# Anything non-literal is assumed to raise, so the failure mode is a missed detection
# rather than an invented swallow where the failure actually escapes.
RAISE_UNLESS_DISABLED = {"handle_error", "handle_service_error"}

# Keyword arguments that turn one of the above back into a swallow; only a literal
# False counts. `user_facing` belongs here because of the third definition above --
# it currently appears only in tests, which this validator skips, but the rule matches
# that `handle_error` by name, so omitting it would mis-classify the first production
# caller to use it.
RAISE_DISABLING_KWARGS = {"raise_error", "user_facing"}

NESTED_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

# Methods that push a record into a collection the caller can inspect.
COLLECT_METHODS = {"append", "extend", "add", "update", "setdefault"}

# Substrings that mark a name/key as being ABOUT a failure.
ERROR_WORDS = ("error", "fail", "exception", "traceback", "problem", "warning", "skipped")

# Keys/attributes whose value is an outcome flag, e.g. results["success"] = False.
OUTCOME_KEYS = {"success", "ok", "status", "result"}
FAILING_VALUES = {False, "error", "failed", "failure", "skipped", "partial"}

VALID_REASONS = {"best-effort", "caller-verifies", "reported-elsewhere", "false-positive"}
_MARKER = re.compile(r"#\s*failed-write-ok\s*:\s*([a-z-]+)?")

OUTCOME_ORDER = ("CLAIMS_SUCCESS", "LOOP_CONTINUES", "RETURNS_TRUTHY", "FALLS_THROUGH")


# --------------------------------------------------------------------------
# AST helpers
# --------------------------------------------------------------------------
def _dotted(node: ast.AST) -> str:
    """Render an attribute/name chain as 'frappe.db.set_value'. Best effort."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _own_nodes(fn: ast.AST):
    """Walk fn's body without descending into nested function/class scopes."""
    stack = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        # Stop AT the nested scope, not inside it: _qualnames yields the nested
        # function separately, so descending here would report its handlers twice.
        if isinstance(node, NESTED_DEFS):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _qualnames(tree: ast.AST):
    """Yield (qualified_name, function_node) for every function in the module."""

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = f"{prefix}{child.name}"
                yield qn, child
                yield from walk(child, f"{qn}.")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")
            else:
                yield from walk(child, prefix)

    yield from walk(tree, "")


# --------------------------------------------------------------------------
# (1) does the try body write?
# --------------------------------------------------------------------------
def _writes_in(nodes) -> list[str]:
    """Names of persistence calls found among these nodes."""
    found = []
    for n in nodes:
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        f = n.func
        d = _dotted(f)
        if d in WRITE_FUNCS:
            found.append(d)
        elif f.attr in WRITE_METHODS:
            receiver = _target_text(f.value)
            if any(w in receiver for w in NON_DB_RECEIVERS):
                continue  # a Redis/cache handle, not the database
            found.append("." + f.attr)
        elif f.attr == "sql":
            # Only a WRITING statement counts; a SELECT is not a lost write.
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    head = a.value.strip().lstrip("(").strip().upper()
                    if head.startswith(WRITING_SQL):
                        found.append(".sql/write")
    return found


# --------------------------------------------------------------------------
# (2) + (3) broad, non-propagating
# --------------------------------------------------------------------------
def _is_broad(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return True
    names = t.elts if isinstance(t, ast.Tuple) else [t]
    return any(isinstance(e, ast.Name) and e.id in BROAD_EXCEPTIONS for e in names)


def _propagates(handler: ast.ExceptHandler) -> bool:
    """True if the failure LEAVES the handler instead of being swallowed."""
    for n in ast.walk(handler):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in PROPAGATING_CALLS:
                return True
            if name == "msgprint" and any(k.arg == "raise_exception" for k in n.keywords):
                return True
            if name in RAISE_UNLESS_DISABLED and not _disables_raise(n):
                return True
    return False


def _disables_raise(call: ast.Call) -> bool:
    """True only for a literal ``raise_error=False`` / ``user_facing=False``."""
    return any(
        k.arg in RAISE_DISABLING_KWARGS and isinstance(k.value, ast.Constant) and k.value.value is False
        for k in call.keywords
    )


# --------------------------------------------------------------------------
# (4) does the handler record the failure for the caller?
# --------------------------------------------------------------------------
def _target_text(node: ast.AST) -> str:
    """Render an assignment target, INCLUDING literal subscript keys.

    ``results["invoices"]["error"]`` -> ``results.invoices.error`` so that a
    failure recorded under a string key is as visible as one under an attribute.
    """
    parts = []
    while True:
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                parts.append(sl.value)
            node = node.value
        else:
            break
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts)).lower()


def _is_errorish(text: str) -> bool:
    return any(w in text for w in ERROR_WORDS)


def _mentions_exception(node: ast.AST | None, exc_name: str | None) -> bool:
    """Does this expression carry the caught exception (or a traceback) with it?"""
    if node is None:
        return False
    for n in ast.walk(node):
        if exc_name and isinstance(n, ast.Name) and n.id == exc_name:
            return True
        if isinstance(n, ast.Call):
            d = _dotted(n.func) if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            if d in ("traceback.format_exc", "frappe.get_traceback"):
                return True
    return False


def _flips_outcome_flag(target: str, value: ast.AST) -> bool:
    """``results[k]["success"] = False`` / ``x.status = "failed"``."""
    leaf = target.rsplit(".", 1)[-1]
    if leaf not in OUTCOME_KEYS:
        return False
    return isinstance(value, ast.Constant) and value.value in FAILING_VALUES


def _records_failure(handler: ast.ExceptHandler) -> bool:
    """Does the handler put the failure somewhere the caller can read it?

    Deliberately NARROWER than "any assignment or any .append()": a handler that
    does ``self.retry_count += 1`` or ``doc.status = "Draft"`` has told the caller
    nothing about the lost write, and treating it as a report hides real findings.
    """
    exc = handler.name
    for n in ast.walk(handler):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in COLLECT_METHODS:
                container = _target_text(n.func.value)
                if _is_errorish(container):
                    return True
                if any(_mentions_exception(a, exc) for a in n.args):
                    return True
                if any(_mentions_exception(k.value, exc) for k in n.keywords):
                    return True
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                # A plain local counts only when its NAME is about failure --
                # `error_count += 1` in a batch loop is the report the caller reads.
                if isinstance(t, ast.Name):
                    if _is_errorish(t.id.lower()):
                        return True
                    continue
                if not isinstance(t, (ast.Subscript, ast.Attribute)):
                    continue
                text = _target_text(t)
                if _is_errorish(text):
                    return True
                if _mentions_exception(n.value, exc):
                    return True
                if n.value is not None and _flips_outcome_flag(text, n.value):
                    return True
    return False


# --------------------------------------------------------------------------
# (5) how does the handler exit?
# --------------------------------------------------------------------------
def _is_falsy_return(ret: ast.Return) -> bool:
    v = ret.value
    if v is None:
        return True
    if isinstance(v, ast.Constant) and not v.value:
        return True
    if isinstance(v, ast.Dict) and not v.keys:
        return True
    if isinstance(v, (ast.List, ast.Tuple, ast.Set)) and not v.elts:
        return True
    return False


def _reports_failure(ret: ast.Return) -> bool:
    """A TRUTHY return that nonetheless tells the caller it FAILED.

    Calibration (a): ``{"success": False, "error": str(e)}`` is a non-empty dict,
    hence truthy, but it is a correct error report. Same for
    ``OperationResult(success=False)`` and any dict carrying an error key.
    """
    v = ret.value
    if isinstance(v, ast.Dict):
        for k, val in zip(v.keys, v.values):
            if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                continue
            if k.value in ("error", "errors", "exception", "traceback", "message"):
                return True
            if k.value in ("success", "ok") and isinstance(val, ast.Constant) and val.value is False:
                return True
            # `return {"action": "error", "requires_intervention": True}` -- the
            # live shape in sepa_batch_notifications. The outcome word can live
            # under any of these keys, not just "status".
            if (
                k.value in ("status", "action", "state", "outcome", "result")
                and isinstance(val, ast.Constant)
                and val.value in ("error", "failed", "failure", "skipped")
            ):
                return True
    # `return False, error_msg` -- the (ok, error) tuple this codebase uses in
    # AccountCreationService and friends. Non-empty tuple, hence truthy, but the
    # caller unpacks a failure out of it.
    if isinstance(v, ast.Tuple):
        for elt in v.elts:
            if isinstance(elt, ast.Constant) and elt.value is False:
                return True
            if isinstance(elt, (ast.Name, ast.Attribute, ast.Subscript)) and _is_errorish(
                _target_text(elt)
            ):
                return True
    if isinstance(v, ast.Call):
        for kw in v.keywords:
            if kw.arg in ("success", "ok") and isinstance(kw.value, ast.Constant):
                if kw.value.value is False:
                    return True
            if kw.arg in ("error", "errors", "message"):
                return True
        d = _dotted(v.func) if isinstance(v.func, ast.Attribute) else getattr(v.func, "id", "")
        if any(w in d.lower() for w in ("error", "fail")):
            return True
    return False


def _claims_success(ret: ast.Return) -> bool:
    """Does this return hand the caller an EXPLICIT success flag?"""
    v = ret.value
    if isinstance(v, ast.Constant) and v.value is True:
        return True
    if isinstance(v, ast.Dict):
        for k, val in zip(v.keys, v.values):
            if isinstance(k, ast.Constant) and k.value in ("success", "ok", "status"):
                if isinstance(val, ast.Constant) and val.value in (True, "success", "ok"):
                    return True
    if isinstance(v, ast.Call):
        d = _dotted(v.func) if isinstance(v.func, ast.Attribute) else getattr(v.func, "id", "")
        if "success" in d.lower():
            return True
        for kw in v.keywords:
            if kw.arg in ("success", "ok") and isinstance(kw.value, ast.Constant):
                if kw.value.value is True:
                    return True
        if d.endswith(("service_result", "OperationResult")) and v.args:
            a0 = v.args[0]
            if isinstance(a0, ast.Constant) and a0.value is True:
                return True
    return False


def _classify(handler: ast.ExceptHandler, trailing_ids: set[int]) -> str | None:
    """Which outcome class is this, or None if the failure does reach the caller.

    Calibration (b) is checked FIRST, before any reading of return values -- that
    is what keeps ``_step_save_history_changes``' ``return True`` (which MEANS
    "the save failed") from being misread as CLAIMS_SUCCESS (calibration (c)).
    """
    if _records_failure(handler):
        return None

    inner = list(ast.walk(handler))
    rets = [n for n in inner if isinstance(n, ast.Return)]
    truthy = [r for r in rets if not _is_falsy_return(r) and not _reports_failure(r)]

    if rets and not truthy and any(_reports_failure(r) for r in rets):
        return None  # a correct error report that merely happens to be truthy
    if truthy:
        if any(_claims_success(r) for r in truthy):
            return "CLAIMS_SUCCESS"
        return "RETURNS_TRUTHY"
    if any(isinstance(n, ast.Continue) for n in inner):
        return "LOOP_CONTINUES"  # row dropped, batch still reports success
    if any(isinstance(n, ast.Break) for n in inner):
        # `break` ABANDONS the loop rather than skipping one row, so control lands
        # in the post-loop code -- which in this codebase is the failure path. The
        # only such site, SEPADistributedLock._acquire_lock_internal, breaks out of
        # a retry loop straight into "Failed to acquire lock". Flagging it is noise.
        return None
    if rets:
        return None  # falsy return -> error_swallow_validator's turf
    if id(handler) in trailing_ids:
        return None  # implicit None at the tail -> error_swallow_validator's turf
    return "FALLS_THROUGH"


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------
def _suppressed(handler: ast.ExceptHandler, lines: list[str]) -> tuple[bool, str | None]:
    """Look for a `# failed-write-ok:` marker on the except line or the line above."""
    for ln in (handler.lineno, handler.lineno - 1):
        if 1 <= ln <= len(lines):
            m = _MARKER.search(lines[ln - 1])
            if m:
                reason = m.group(1)
                return True, (None if reason in VALID_REASONS else (reason or "<missing>"))
    return False, None


def scan_file(path: Path):
    """Return (findings, bad_pragmas) for one file.

    findings: list of (qualified_function, lineno, outcome_class, sorted write names)
    bad_pragmas: list of (lineno, reason) where the marker reason is not allowed
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return [], []

    lines = source.splitlines()
    findings, bad_pragmas = [], []

    for qualname, fn in _qualnames(tree):
        tail = fn.body[-1] if fn.body else None
        trailing = {id(h) for h in tail.handlers} if isinstance(tail, ast.Try) else set()

        for node in _own_nodes(fn):
            if not isinstance(node, ast.Try):
                continue
            body_nodes = [n for stmt in node.body for n in ast.walk(stmt)]
            writes = _writes_in(body_nodes)
            if not writes:
                continue

            for handler in node.handlers:
                if not _is_broad(handler) or _propagates(handler):
                    continue
                outcome = _classify(handler, trailing)
                if outcome is None:
                    continue
                ok, bad_reason = _suppressed(handler, lines)
                if ok:
                    if bad_reason:
                        bad_pragmas.append((handler.lineno, bad_reason))
                    continue
                findings.append((qualname, handler.lineno, outcome, sorted(set(writes))))

    return findings, bad_pragmas


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_py(paths: list[str]):
    """Yield the .py files under `paths`, each PHYSICAL file exactly once.

    Same dedupe, and the same reason, as `error_swallow_validator._iter_py`: a
    symlinked module and its target are two `os.walk` entries but one file, and `_rel`
    keys findings by `path.resolve()`, so both visits land on the same baseline key
    and its count DOUBLES. That cost the swallow guard four free ratchet slots (#588).

    Here it is LATENT rather than live, which is the only reason the baseline looks
    clean: this validator walks the same collision -- measured, 3227 files, one
    symlink, one same-target pair on `templates/pages/member_portal.py` -- and simply
    has no finding in that file yet. The first one to land would arrive as `::2`.
    """
    candidates: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in {"node_modules", ".git", "__pycache__", "worktrees", ".claude", "archived"}
                ]
                candidates.extend(Path(dirpath) / fn for fn in filenames if fn.endswith(".py"))
        elif p.suffix == ".py" and p.exists():
            candidates.append(p)

    seen: set[Path] = set()
    for path in sorted(candidates, key=lambda q: (q.is_symlink(), str(q))):
        target = path.resolve()
        if target in seen:
            continue
        seen.add(target)
        yield path


def _counts(paths: list[str]) -> tuple[Counter, Counter, dict[str, list], list[str]]:
    """Map 'path::qualname' -> number of sites, plus outcome totals and details."""
    counts: Counter = Counter()
    outcomes: Counter = Counter()
    details: dict[str, list] = {}
    problems: list[str] = []
    for path in _iter_py(paths):
        rel = _rel(path)
        # Tests may legitimately swallow while probing failure paths.
        if "/tests/" in "/" + rel or path.name.startswith("test_"):
            continue
        findings, bad = scan_file(path)
        for qualname, lineno, outcome, writes in findings:
            key = f"{rel}::{qualname}"
            counts[key] += 1
            outcomes[outcome] += 1
            details.setdefault(key, []).append((lineno, outcome, writes))
        for lineno, reason in bad:
            problems.append(
                f"{rel}:{lineno}: invalid `failed-write-ok` reason {reason!r}; "
                f"use one of {sorted(VALID_REASONS)}"
            )
    return counts, outcomes, details, problems


def load_baseline(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
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


def write_baseline(path: Path, counts: Counter, outcomes: Counter) -> None:
    header = [
        "# Known failed-write swallows -- the ratchet baseline for",
        "# scripts/validation/failed_write_validator.py. Format:",
        "#     <path>::<qualified function>::<number of sites>",
        "#",
        "# A site is a broad `except` over a try body that WRITES TO THE DATABASE,",
        "# where the failure never reaches the caller: the row is silently lost and",
        "# the operation reports success. PR #280 found nine production defects of",
        "# this shape at once, three of which had never worked in any deployment.",
        "#",
        "# A run reports only a site NOT covered here, or an extra site in a function",
        "# already listed. Line numbers are deliberately absent -- they rot on any",
        "# edit above them.",
        "#",
        "# This file should only ever SHRINK. Do not regenerate it to make a new",
        "# finding go away; either make the failure reach the caller or mark it",
        "# `# failed-write-ok: <reason>`. The one legitimate reason it may GROW is a",
        "# change to the validator's own detection rules, which must land in the same",
        "# commit as the regeneration.",
        "#",
        f"# Totals at generation: {sum(counts.values())} sites across {len(counts)} functions"
        + " -- "
        + ", ".join(f"{k} {outcomes[k]}" for k in OUTCOME_ORDER if outcomes[k]),
        "",
    ]
    body = [f"{k}::{v}" for k, v in sorted(counts.items())]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=list(SCAN_ROOTS))
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--stats", action="store_true", help="print totals and exit 0")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on a site not in the baseline (default: advisory, exit 0)",
    )
    args = ap.parse_args(argv[1:])

    strict = args.strict or os.environ.get("FAILED_WRITE_STRICT") == "1"
    paths = args.paths or list(SCAN_ROOTS)

    if args.update_baseline:
        counts, outcomes, _, _ = _counts([str(REPO_ROOT / root) for root in SCAN_ROOTS])
        write_baseline(args.baseline, counts, outcomes)
        print(f"baseline written: {len(counts)} functions, {sum(counts.values())} sites")
        for k in OUTCOME_ORDER:
            if outcomes[k]:
                print(f"  {k:16s} {outcomes[k]}")
        return 0

    counts, outcomes, details, problems = _counts(paths)

    if args.stats:
        print(f"{sum(counts.values())} sites across {len(counts)} functions")
        for k in OUTCOME_ORDER:
            if outcomes[k]:
                print(f"  {k:16s} {outcomes[k]}")
        return 0

    baseline = load_baseline(args.baseline)
    new = {k: v for k, v in counts.items() if v > baseline.get(k, 0)}

    if not new and not problems:
        return 0

    mode = "STRICT" if strict else "advisory"
    print(f"\n\U0001f4be Failed writes reported as success  [{mode}]\n")
    for msg in problems:
        print(f"  {msg}")
    for key, count in sorted(new.items()):
        known = baseline.get(key, 0)
        path, _, qualname = key.partition("::")
        print(f"  {path}  {qualname}()")
        for lineno, outcome, writes in details.get(key, []):
            print(f"      line {lineno}: {outcome} after [{', '.join(writes)}]")
        if known:
            print(f"      ({count - known} more than the {known} already baselined)")
    print(
        "\n  A broad `except` around a database write, whose failure never reaches the\n"
        "  caller, turns a raised exception into silent data loss: the row is not there\n"
        "  and the operation reports success. PR #280 found NINE such defects at once,\n"
        "  three of which had never worked in any deployment -- and several had\n"
        "  thorough, PASSING tests, because the tests asserted the reported outcome.\n"
        "  Fix by re-raising, or by returning/recording an explicit failure the caller\n"
        "  reads. If the write genuinely does not matter, mark it:\n"
        "      except Exception:  # failed-write-ok: best-effort\n"
    )
    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
