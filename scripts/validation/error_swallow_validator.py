#!/usr/bin/env python3
"""Block NEW exception handlers that swallow a failure into a falsy return.

THE BUG CLASS
-------------
A broad ``except`` whose body only logs and then returns ``None``/``False``/``{}``
destroys the cause. The caller cannot distinguish "this failed" from "there is
legitimately nothing here", and the real exception ends up only in the Error Log
DocType -- on CI, a database that is deleted when the job ends.

This is not hypothetical in this repo:

* ``get_project_permission_query_conditions`` returned ``""``, which ERPNext reads
  as UNRESTRICTED rather than "no access" -- board members got org-wide project
  access (PR #191, a security fix).
* ``None`` from ``get_user_accessible_chapters`` means "admin -- sees ALL
  chapters", so caching a swallowed failure would have turned a database outage
  into full access for every caller.
* ``chapter_utils`` swallowed a DB error into "no volunteer exists", and the
  callers use that as a DUPLICATE GUARD -- so a database error silently inserted
  a SECOND Volunteer for a member who already had one.
* ``create_contact_for_customer`` returns ``None`` on any exception and the
  caller throws a generic "Failed to create Contact for Customer". A CI failure
  in ``test_chapter_members_enhanced`` could not be diagnosed at all, because the
  only copy of the real error died with the CI database.

WHAT IS FLAGGED
---------------
A handler is reported only when ALL of these hold, which is the load-bearing case:

1. the ``except`` is broad (bare, ``Exception``, or ``BaseException``);
2. the failure never leaves the handler -- no ``raise``, and no call that raises
   on its behalf (``frappe.throw``, ``msgprint(raise_exception=True)``,
   ``sys.exit``);
3. the handler logs, and does nothing that lets the caller learn the cause or
   resume real work: no ``continue``/``break``, no nested ``def``/``class``, and
   no return of a real value on ANY branch;
4. it hands the caller a falsy value -- either every return in it is a falsy
   literal (``None``/``False``/``{}``/``[]``/``""``/``0``), or it has no return at
   all and the ``try`` is the LAST statement of the function, so falling off the
   end of the handler is an implicit ``return None``; and
5. the ENCLOSING FUNCTION elsewhere returns a real value.

On (4): the falsy test is "any falsy literal", not a list of blessed ones,
because ``""`` is precisely the value ERPNext reads as UNRESTRICTED in the
permission-hook incident above. The implicit-``None`` arm is restricted to a
trailing ``try`` on purpose -- falling off a handler in the MIDDLE of a function
resumes it, so the caller still gets a real value and flagging it would be a
false positive.

Also on (4): a falsy-MEANING sentinel counts, not only a falsy-SHAPED literal. A
handler changed from ``return None`` to ``return InvoiceChoice(None, 0)`` -- same
swallow, still logging -- and the site silently LEFT the baseline. Two arms follow
from that: a call whose arguments are ALL falsy literals (given at least one
argument), and a SEQUENCE holding nothing but falsy literals -- ``return None,
None`` two lines below an identical no-data ``return None, None``. A call carrying
the cause -- ``Result(False, str(e))`` -- is not a swallow, for the same reason a
non-empty dict never was.

A non-empty DICT whose every value is a falsy literal (``{"today": 0, "week": 0}``)
is now in scope too, 8 sites (#589). A non-empty dict was the shape this validator
always let through, because ``{"success": False, "error": str(e)}`` is the remedy it
prints -- but that dict has somewhere to put the cause and a dict of zeros does not.
The caller cannot tell "no activity" from "the query blew up"; one of the 8 is an
all-``False`` PERMISSION dict. An error report is still let through, because a value
that is not a falsy literal is a place the cause can live.

Two shapes with 0 occurrences today are closed alongside it rather than waited for:
an empty f-string (``return f""`` parses as ``ast.JoinedStr``, not ``ast.Constant``,
so the falsy-literal arm never saw it), and the argument-less falsy constructors
``dict()``/``list()``/``tuple()``/``set()``/``frappe._dict()``, which the ``>= 1
argument`` guard below necessarily excludes -- reachable only through a NAME
allowlist, never by dropping that guard.

On (3): this is a set of DISQUALIFIERS, not a whitelist of allowed statements.
It used to require a body of only logging calls and returns, which meant a single
``cleanup()`` call or an ``error_msg = str(e)[:100]`` truncation hid the site
completely -- 56 live sites, including a report whose handler is commented
"Return empty result instead of crashing", and a metadata helper that writes the
failure INTO ITS CACHE (``self._doctype_cache[doctype] = None``), making one
transient error permanent for the life of the process.

Widening (3) is what makes (2) load-bearing. ``frappe.throw`` is a raise in
disguise, and 85 live handlers propagate through it; under the old rule the throw
call was itself a non-logging statement, so those were excluded by accident. Drop
the whitelist without teaching (2) about ``throw`` and they all become false
positives.

(5) is what separates a dangerous swallow from a harmless one. A function that
never returns anything meaningful (fire-and-forget cache invalidation, a
best-effort notification) is not reported: its falsy return is not load-bearing,
because no caller can branch on it. Measured on this repo, (5) is what makes the
rule usable: conditions 1-4 alone match 929 sites, and (5) cuts that to 449.

KNOWN FALSE NEGATIVES
---------------------
A handler that returns a falsy value INDIRECTLY (``result = None`` ...
``return result``) is not detected: the returns are matched syntactically, so a
value reaching the caller through a local variable is invisible. A clean report
is therefore not proof of absence.

Handlers that log nothing at all are also out of scope. That is a different and
worse bug class -- a silent swallow -- and reporting it here would bury this one.

RATCHET, NOT BIG-BANG
---------------------
There are 449 such sites today, across ``verenigingen/`` and ``scripts/``.
Failing on all of them would block every commit, and pragma-ing 449 sites in one
diff would be unreviewable. So this validator fails only on sites NOT already
recorded in the baseline.

Run over the whole tree by the ``Code Validation`` workflow, so ``git commit -n``
does not bypass it, and as a pre-commit hook on touched files for fast feedback.

The baseline is keyed ``path::qualified_function::count`` -- deliberately NOT line
numbers, which rot on any edit above them. The count means a new swallow added to
an ALREADY-baselined function is still caught.

    python scripts/validation/error_swallow_validator.py --update-baseline

A SHRINK is the one direction this ratchet used to accept without question, which
is how the sentinel gap above nearly shipped: nothing in the output distinguishes
"this swallow was fixed" from "this swallow became unrecognisable", and the diff
shows a REMOVED line either way. ``--check-shrink`` re-reads every entry whose count
dropped and names one of three reasons it left without being fixed -- the falsy test
no longer recognises the return (``unrecognised``), the logging call was deleted so
this detector's own silent-swallow exemption now hides it (``silent``), or the file
stopped being SCANNED at all (``unscanned``)::

    python scripts/validation/error_swallow_validator.py \
        --check-shrink base_baseline.txt --base-tree /path/to/base/checkout

``--base-tree`` is a checkout of the base commit. Without it the ``silent`` reason is
not reported at all: a deleted logging call and a function that has ALWAYS had a
silent sibling look identical from the head tree, and 2 of the 435 baselined
functions have such a sibling -- so guessing turns the CORRECT fix into a red gate
citing a deletion that never happened.

Escape hatch, matching the ``cache-guard-ok`` convention already used by
``cache_guard_validator.py``::

    except Exception:  # swallow-ok: best-effort
        logger.warning(...)
        return None

Reasons: best-effort (failure genuinely does not matter), caller-checks (the
caller distinguishes the falsy value some other way), false-positive.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = Path(__file__).with_name("error_swallow_baseline.txt")

# The roots the baseline covers. CI scans exactly these; the pre-commit hook scans
# only the files you touched, so its `exclude` must stay a SUBSET of this -- a file
# that the hook scans but the baseline does not cover fails spuriously on its first
# edit. `scripts/` is included because a dev tool that swallows an error into "no
# findings" is a gate that silently passes, which is this bug class at its worst.
SCAN_ROOTS = ("verenigingen", "scripts")

# Attribute/name fragments that mark a call as "just logging".
LOG_NAMES = {
    "log_error",
    "logger",
    "warning",
    "error",
    "info",
    "debug",
    "exception",
    "msgprint",
    "print",
    # This repo's own error helpers. Without these the validator only recognised
    # the framework's names, so a handler recording its failure through the
    # service layer looked like it logged NOTHING and was skipped entirely --
    # 25 log-and-swallow sites hidden behind the project's own conventions.
    # A bare `log` was deliberately NOT added: too generic to attribute.
    "handle_error",
    "handle_service_error",
    "log_action",
    "safe_log_error",
    "_log_error_with_traceback",
}
BROAD_EXCEPTIONS = {"Exception", "BaseException"}

# Calls that end the flow rather than swallow it. `frappe.throw` is a raise in
# disguise: 85 live handlers propagate through it and would otherwise be reported
# the moment condition (3) stopped excluding them for having a non-logging
# statement. `msgprint` counts as logging everywhere else, but raise_exception=True
# makes it raise too.
PROPAGATING_CALLS = {"throw", "exit", "_exit"}

# `handle_service_error(..., raise_error=True)` is the DEFAULT, and BaseService's
# `handle_error` delegates straight to it -- so a bare `self.handle_error(e, op)`
# re-raises. These names log AND propagate, which is why they appear in LOG_NAMES
# too. Only an explicit `raise_error=False` makes them a swallow; anything
# non-literal is assumed to raise, which errs toward a false negative rather than
# inventing a swallow where the failure actually escapes.
RAISE_UNLESS_DISABLED = {"handle_error", "handle_service_error"}

# Argument-less constructors that ARE a falsy value. `all([])` is True, so the
# `v.args or v.keywords` guard in `_is_falsy_return` excludes every zero-argument
# call -- which is what keeps `get_fallback_cost_center()` and
# `_get_empty_statistics()` out, and must keep doing so. A NAME allowlist is the
# narrow way back in for the handful of calls whose value is falsy by definition.
# Measured over both scan roots: the 11 distinct zero-argument calls returned from
# inside a broad `except` are all of that fallback/retry kind, and NOT ONE is one of
# these names -- so this reintroduces none of the 7 false positives (#589).
FALSY_EMPTY_CONSTRUCTORS = {"dict", "list", "tuple", "set", "frappe._dict", "_dict"}

# A def inside a handler puts real returns out of reach of this analysis.
NESTED_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

VALID_REASONS = {"best-effort", "caller-checks", "false-positive"}
_MARKER = re.compile(r"#\s*swallow-ok\s*:\s*([a-z-]+)?")

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _own_nodes(fn: ast.AST):
    """Walk fn's body without descending into nested function/class scopes."""
    stack = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, SCOPES):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _is_log_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    parts = []
    f = node.value.func
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return bool(set(parts) & LOG_NAMES)


def _is_falsy_return(node: ast.AST) -> bool:
    if not isinstance(node, ast.Return):
        return False
    v = node.value
    if v is None:
        return True
    # Any falsy literal, NOT just None/False: `return ""` is the flagship incident
    # (ERPNext reads "" from a permission hook as UNRESTRICTED), and `return 0`
    # only used to be caught here by the accident of `0 == False`.
    if isinstance(v, ast.Constant) and not v.value:
        return True
    # `return f""` parses as a JoinedStr, not a Constant, so the arm above never sees
    # it -- and `""` is the flagship incident. An f-string with no parts, or with only
    # empty constant parts, IS `""`. 0 occurrences today (#589); the shape is closed
    # here rather than waited for, because the cost of closing it is one branch.
    if isinstance(v, ast.JoinedStr):
        return all(isinstance(part, ast.Constant) and not part.value for part in v.values)
    # An empty dict, or a non-empty one whose every value is a falsy LITERAL. The
    # second half is new (#589) and reverses a deliberate exclusion: a non-empty dict
    # was always let through because `{"success": False, "error": str(e)}` is the
    # remedy this validator prints. That dict has somewhere to put the cause;
    # `{"today": 0, "week": 0, "daily_average": 0}` does not, and its caller cannot
    # tell "no activity" from "the query blew up". One of the 8 sites this adds
    # returns an all-`False` PERMISSION dict. Measured over both scan roots, against
    # the shipped rule and in BOTH directions: adds exactly 8 sites, removes none.
    #
    # A value that is not a falsy literal -- `str(e)`, a list of errors, a real count
    # -- still makes the whole dict unflagged, which is what keeps an error report an
    # error report.
    if isinstance(v, ast.Dict):
        return not v.keys or all(
            isinstance(d, ast.Constant) and not d.value for d in v.values
        )
    # An EMPTY sequence, or one holding nothing but falsy literals -- the same
    # argument, one step out. `return None, None` sits two lines below an identical
    # no-data `return None, None` in `MT940Import.get_transaction_date_range`, so the
    # caller cannot tell "no transactions in range" from "the query blew up" (#586).
    # Measured: extending this branch adds exactly 3 sites and removes none.
    if isinstance(v, (ast.List, ast.Tuple, ast.Set)):
        return all(isinstance(e, ast.Constant) and not e.value for e in v.elts)
    # A falsy-MEANING sentinel is not a falsy-SHAPED literal. One handler was
    # changed from `return None` to `return InvoiceChoice(None, 0)` -- the same
    # swallow, still logging, no behavioural change at all -- and the site silently
    # LEFT the baseline, which reads as progress (#586).
    #
    # The `v.args or v.keywords` guard is the load-bearing part. "A call whose
    # arguments are all falsy" -- the shape the issue itself suggested -- is satisfied
    # VACUOUSLY by a call with no arguments, because `all([])` is True. Measured
    # against this rule over both scan roots, dropping the guard would:
    #
    #   ADD    7 false findings -- `get_fallback_cost_center()`,
    #          `_get_empty_statistics()`, `get_empty_coverage_analysis()`,
    #          `self._load_payment_history_original()` and friends: real fallbacks
    #          and retries, plus `OperationResult.fail(...).to_dict()` chains whose
    #          OUTER call is the argument-less `to_dict()`;
    #   REMOVE 6 findings that are in the baseline TODAY, because this predicate also
    #          feeds condition (5): `get_mollie_settings` returns only
    #          `settings.as_dict()`, `get_chapter_stats` only
    #          `chapter.get_chapter_statistics()`, so both would read as "never
    #          returns a real value" and their swallows would vanish.
    #
    # That second half is the standing hazard, and it applies to ANY future widening
    # here: check both directions. Every arm added since -- the sequence arm, the
    # dict-of-falsy-values arm, the f-string arm, the allowlisted constructors --
    # was measured against the shipped rule in BOTH directions and removes nothing.
    #
    # A call carrying the cause -- `Result(False, str(e))` -- stays unflagged for the
    # same reason a dict with a real value in it is: the caller can learn WHY it failed.
    if isinstance(v, ast.Call):
        if v.args or v.keywords:
            return all(isinstance(a, ast.Constant) and not a.value for a in v.args) and all(
                isinstance(k.value, ast.Constant) and not k.value.value for k in v.keywords
            )
        # The zero-argument case the guard above excludes wholesale. `dict()` IS `{}`,
        # so losing it is a real gap -- but it is closed by NAMING the constructors,
        # never by relaxing the guard, which is what the 7-for-6 measurement above
        # forbids. 0 occurrences today (#589).
        return ast.unparse(v.func) in FALSY_EMPTY_CONSTRUCTORS
    return False


def _is_broad(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return True
    if isinstance(t, ast.Name):
        return t.id in BROAD_EXCEPTIONS
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in BROAD_EXCEPTIONS for e in t.elts)
    return False


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
    """True only for a literal ``raise_error=False``."""
    return any(
        k.arg == "raise_error" and isinstance(k.value, ast.Constant) and k.value.value is False
        for k in call.keywords
    )


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


def _suppressed(handler: ast.ExceptHandler, lines: list[str]) -> tuple[bool, str | None]:
    """Look for a `# swallow-ok:` marker on the except line or the line above."""
    for ln in (handler.lineno, handler.lineno - 1):
        if 1 <= ln <= len(lines):
            m = _MARKER.search(lines[ln - 1])
            if m:
                reason = m.group(1)
                return True, (None if reason in VALID_REASONS else (reason or "<missing>"))
    return False, None


def _returns_real_value(fn: ast.AST) -> bool:
    """(5): does this function hand a caller a real value somewhere else?

    A function that never returns anything meaningful (fire-and-forget cache
    invalidation, a best-effort notification) is not reported: no caller can branch
    on its falsy return.
    """
    return any(
        isinstance(n, ast.Return) and n.value is not None and not _is_falsy_return(n)
        for n in _own_nodes(fn)
    )


def _is_structural_swallow(node: ast.AST, *, require_log: bool = True) -> bool:
    """Conditions (1), (2) and (3) for one handler -- everything except the returns.

    Condition (5) is a function-level question and lives in ``_returns_real_value``;
    (4) is the returns, which is what the two callers ask differently. Shared by
    ``scan_file`` and ``_falsy_swallow_handlers`` on purpose. They used to
    carry two copies of this ladder, which is a "must stay in step" hazard of exactly
    the kind this repo keeps paying for: add a condition to the detector and the
    shrink explainer silently stops explaining.

    ``require_log`` is the one place they legitimately differ. The detector skips a
    handler that logs nothing, because a SILENT swallow is a different and worse bug
    class and reporting it here would bury this one. The explainer must NOT skip it:
    deleting the logging call is otherwise an accepted "fix" that drops the entry out
    of the baseline while making the code worse.
    """
    if not isinstance(node, ast.ExceptHandler) or not _is_broad(node):
        return False
    # (2) the failure must not leave the handler -- `raise`, but also `frappe.throw`
    # and `msgprint(raise_exception=True)`, which raise.
    if _propagates(node):
        return False
    # (3) the handler must not do anything that lets the caller learn the cause or
    # resume real work. This is a set of disqualifiers rather than a whitelist of
    # allowed statements: requiring a body of ONLY logs and returns meant a single
    # `cleanup()` call hid the site completely.
    inner = list(ast.walk(node))
    if require_log and not any(_is_log_call(n) for n in inner):
        return False
    if any(isinstance(n, NESTED_DEFS) for n in inner):
        return False
    if any(isinstance(n, (ast.Continue, ast.Break)) for n in inner):
        return False
    return True


def scan_file(path: Path):
    """Return (findings, bad_pragmas) for one file.

    findings: list of (qualified_function, lineno)
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
        if not _returns_real_value(fn):
            continue

        # Handlers of a `try` that is the LAST statement of the function: falling off
        # the end of one is an implicit `return None`. Anywhere else, falling off
        # resumes the function, so the caller still gets a real value.
        tail = fn.body[-1] if fn.body else None
        trailing = {id(h) for h in tail.handlers} if isinstance(tail, ast.Try) else set()

        for node in _own_nodes(fn):
            if not _is_structural_swallow(node):
                continue

            # Returns at ANY depth, now that an `if` no longer disqualifies the
            # handler: one real return on one branch means the caller can still
            # get a usable value, so the handler is not a swallow.
            rets = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
            if not all(_is_falsy_return(r) for r in rets):
                continue

            # (4) no return at all is an implicit `return None` only if falling off
            # the handler ends the function.
            if not rets and id(node) not in trailing:
                continue

            ok, bad_reason = _suppressed(node, lines)
            if ok:
                if bad_reason:
                    bad_pragmas.append((node.lineno, bad_reason))
                continue
            findings.append((qualname, node.lineno))

    return findings, bad_pragmas


class UnexplainedShrink(NamedTuple):
    """A baseline entry that left while its handler still looks like a swallow."""

    key: str
    lineno: int
    source: str
    reason: str


def _is_bound_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _returns_the_cause(handler: ast.ExceptHandler) -> bool:
    """True if what the caller receives can carry the cause.

    `except Exception as e: ... return {"success": False, "error": str(e)}` is the
    remedy this validator PRINTS, so an entry leaving the baseline because it changed
    into that shape is a real fix. A handler with no `as` binding cannot name the
    cause in its return at all, so it never qualifies.

    The bound name must reach the returned VALUE -- as a call argument, through an
    attribute (`e.args`), or interpolated into an f-string. An earlier version matched
    the name anywhere inside any return, which made `return None if e else None` a
    one-token bypass; 480 of the 492 broad handlers in baselined functions bind a name
    (467 of them literally `e`),
    so that predicate was doing far too much work to be that loose.

    Known limits, in BOTH directions -- the false-alarm ones matter more, because only
    they can redden CI:

    * a genuine fix can still be reported. A return built from `frappe.get_traceback()`
      in a handler with no `as` binding carries the cause and is called
      `unrecognised`; so does a container holding the BARE name (`{"error": e}`,
      `return e`, `(None, e)`), which the older, looser predicate did accept. Measured
      as a class: `"error": e` occurs 0 times in `verenigingen/` and `scripts/`,
      against 719 occurrences of `"error": str(e)`, and tree-wide this narrowing
      produces zero new findings -- so the exposure is real but currently empty.
    * a swallow can still slip through: `Choice(None, len(str(e)))` counts as carrying
      the cause, because the name does reach a call argument. Distinguishing
      informative uses from decorative ones is not something an AST can settle.
    """
    if not handler.name:
        return False
    name = handler.name
    for r in ast.walk(handler):
        if not isinstance(r, ast.Return) or r.value is None:
            continue
        for n in ast.walk(r.value):
            if isinstance(n, ast.Call) and (
                any(_is_bound_name(a, name) for a in n.args)
                or any(_is_bound_name(k.value, name) for k in n.keywords)
            ):
                return True
            if isinstance(n, ast.Attribute) and _is_bound_name(n.value, name):
                return True
            if isinstance(n, ast.FormattedValue) and _is_bound_name(n.value, name):
                return True
    return False


def _falsy_swallow_handlers(fn: ast.AST, lines: list[str]) -> list[ast.ExceptHandler]:
    """Handlers that swallow into a falsy value, whether or not they log.

    Conditions (1), (2), (3-minus-logging), (4) and (5). The detector adds "and it
    logs"; splitting that out is what lets the shrink explainer see a handler the
    detector deliberately ignores.
    """
    if not _returns_real_value(fn):
        return []

    tail = fn.body[-1] if getattr(fn, "body", None) else None
    trailing = {id(h) for h in tail.handlers} if isinstance(tail, ast.Try) else set()

    out: list[ast.ExceptHandler] = []
    for node in _own_nodes(fn):
        if not _is_structural_swallow(node, require_log=False):
            continue
        if _suppressed(node, lines)[0]:
            continue
        rets = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        if not rets and id(node) not in trailing:
            continue  # falling off mid-function resumes it: never was a swallow
        if not all(_is_falsy_return(r) for r in rets):
            continue
        out.append(node)
    return out


def _handler_fingerprint(handler: ast.ExceptHandler) -> str:
    """A line-independent identity for one handler: its exception type and its returns.

    Line numbers rot, so the base and head trees are matched on this instead. Two
    handlers in the same function that catch the same thing and return the same
    expression are interchangeable for this purpose -- which is the right granularity,
    because what is being asked is "did a NEW silent falsy handler appear here".
    """
    kind = ast.unparse(handler.type) if handler.type is not None else "bare"
    rets = tuple(
        ast.unparse(n.value) if n.value is not None else "None"
        for n in ast.walk(handler)
        if isinstance(n, ast.Return)
    )
    return f"{kind}|{'&'.join(rets)}"


def _silent_handlers(fn: ast.AST, lines: list[str]) -> list[ast.ExceptHandler]:
    """Falsy swallows in `fn` that log NOTHING, so the detector cannot see them."""
    return [
        h
        for h in _falsy_swallow_handlers(fn, lines)
        if not any(_is_log_call(n) for n in ast.walk(h))
    ]


def _silent_census(root: Path, rel: str) -> dict[str, Counter]:
    """Per-function count of falsy swallows that log NOTHING, in the tree at `root`.

    The base tree is the only thing that can tell "the logging call was deleted" from
    "this function has always had a silent sibling". Without it the two are
    indistinguishable, so `explain_shrink` refuses to report `silent` rather than
    accuse: measured, 2 of 435 baselined functions carry a pre-existing silent
    sibling, and reporting those turns the CORRECT fix into a red gate with a false
    reason.
    """
    try:
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return {}
    lines = source.splitlines()
    out: dict[str, Counter] = {}
    for qualname, fn in _qualnames(tree):
        silent = _silent_handlers(fn, lines)
        if silent:
            out[qualname] = Counter(_handler_fingerprint(h) for h in silent)
    return out


def _shrink_causes(
    fn: ast.AST, lines: list[str], base_silent: Counter | None
) -> list[tuple[ast.ExceptHandler, str]]:
    """Handlers that could explain why this function LEFT the baseline, with a reason.

    Conditions (1), (2) and (3) come from `_is_structural_swallow` and (5) from
    `_returns_real_value`, both shared with the detector so that adding a condition
    to one cannot silently stop the other explaining. What this asks differently:

    ``unrecognised``
        the falsy test is the heuristic, so a handler that still swallows but is no
        longer RECOGNISED as falsy has not been fixed. Handlers whose return can carry
        the cause are excluded -- that is the remedy this validator prints.
    ``silent``
        the detector skips a handler that logs nothing, because a silent swallow is a
        different and worse bug class. That exemption is a hole here: deleting the
        logging call takes the entry out of the baseline while making the code worse.
        Reported only for a handler whose fingerprint is absent from ``base_silent``
        -- see `_silent_census` for why the base tree is required rather than nice to
        have, and `_handler_fingerprint` for why the match is not by line or position.

    Measured with the shipped predicates, tree-wide over both scan roots (tests
    excluded, 1705 files): 483 handlers in 462 functions. That is why this is a shrink
    explainer and not a second detector -- it is only ever asked about the handful of
    entries a PR actually removes, so its precision has to hold there and nowhere else.
    """
    falsy = _falsy_swallow_handlers(fn, lines)
    out: list[tuple[ast.ExceptHandler, str]] = []

    if base_silent is not None:
        # Only handlers whose fingerprint is NEW. A pre-existing silent sibling
        # explains nothing, and picking by position would report the right COUNT
        # against the wrong handler.
        appeared = Counter(_handler_fingerprint(h) for h in _silent_handlers(fn, lines))
        appeared.subtract(base_silent)
        for handler in _silent_handlers(fn, lines):
            key = _handler_fingerprint(handler)
            if appeared[key] > 0:
                appeared[key] -= 1
                out.append((handler, "silent"))

    for node in _own_nodes(fn):
        if node in falsy or not _is_structural_swallow(node, require_log=False):
            continue
        if _suppressed(node, lines)[0]:
            continue  # deliberately marked, which is a reviewable exit
        if not _returns_real_value(fn):
            continue  # (5) gone: the falsy return is no longer load-bearing
        rets = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        if not rets:
            continue
        if _returns_the_cause(node):
            continue  # the caller can learn WHY: a real fix
        out.append((node, "unrecognised"))
    return sorted(out, key=lambda pair: pair[0].lineno)


def explain_shrink(
    baseline: dict[str, int], paths: list[str], base_root: Path | None = None
) -> list[UnexplainedShrink]:
    """Baseline entries whose count DROPPED without the swallow being fixed.

    A shrink was the one direction this ratchet accepted without question, and that is
    how #586 nearly shipped: a handler's return changed from ``None`` to
    ``InvoiceChoice(None, 0)`` and the entry left the baseline. The instruction printed
    on that failure is ``--update-baseline``, and the resulting diff shows a REMOVED
    line -- both read as progress.

    Three reasons an entry can leave without being fixed, each reported distinctly:

    ``unscanned``
        the file stopped being SCANNED rather than stopping being a swallow. Narrowing
        `SCAN_ROOTS`, or adding a directory to `_iter_py`'s exclusions, silently drops
        every entry under it -- measured on this tree, adding ``templates`` drops 10
        and dropping ``scripts`` drops 33. `scan_file` is the control: a site it still
        finds that `_counts` no longer reports left the scan, not the code.
    ``silent``
        the logging call was deleted. Requires ``base_root``; see `_silent_census`.
    ``unrecognised``
        the falsy test stopped recognising what it hands back.

    The report is capped at ``missing`` per key, so a function holding several swallows
    cannot report more than actually went away. The cap is NOT what prevents the common
    false alarm of fixing one of two swallows -- a survivor that still logs and is still
    recognised is still COUNTED, so it never enters `_shrink_causes` at all.
    """
    counts, _ = _counts(paths)
    by_path: dict[str, list[tuple[str, int]]] = {}
    for key, known in baseline.items():
        missing = known - counts.get(key, 0)
        if missing <= 0:
            continue
        rel, _, qualname = key.partition("::")
        by_path.setdefault(rel, []).append((qualname, missing))

    out: list[UnexplainedShrink] = []
    for rel in sorted(by_path):
        full = REPO_ROOT / rel
        try:
            source = full.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue  # the file is gone or unparseable: the shrink explains itself
        lines = source.splitlines()
        fns = dict(_qualnames(tree))
        still_scanned, _ = scan_file(full)
        base_silent = _silent_census(base_root, rel) if base_root is not None else None

        for qualname, missing in sorted(by_path[rel]):
            fn = fns.get(qualname)
            if fn is None:
                continue  # deleted or renamed: explained

            # Does a direct scan of the file still find sites `_counts` did not
            # report? Then the file left the SCAN, and the code never changed.
            direct = sorted(ln for qn, ln in still_scanned if qn == qualname)
            unscanned = len(direct) - counts.get(f"{rel}::{qualname}", 0)
            causes = [(ln, "unscanned") for ln in direct[: max(unscanned, 0)]]
            causes += [
                (h.lineno, reason)
                for h, reason in _shrink_causes(
                    fn, lines, None if base_silent is None else base_silent.get(qualname, Counter())
                )
            ]

            for lineno, reason in causes[:missing]:
                segment = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
                out.append(
                    UnexplainedShrink(f"{rel}::{qualname}", lineno, segment.strip(), reason)
                )
    return out


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_py(paths: list[str]):
    """Yield the .py files under `paths`, each PHYSICAL file exactly once.

    A symlinked module and its target are two `os.walk` entries but one file, and
    `_rel` keys findings by `path.resolve()` -- so both visits land on the SAME
    baseline key and its count doubles. `templates/pages/me.py` is a symlink to
    `member_portal.py`, which is why all four of that file's swallow sites were
    recorded as `::2`: the gate fires on `count > baseline`, so `2 > 2` is false and
    a second real swallow could be added to any of those four functions unnoticed
    (#588).

    Neither CI gate could see it. "Baseline is in sync with the tree" regenerates
    and diffs, and the doubling is deterministic, so the regenerated file is
    byte-identical. "Baseline did not grow" compares totals that were already
    inflated on both sides.

    Deduping here rather than in `_rel` also means the file is parsed once instead
    of twice and merged. The real file is preferred over the link so the baseline
    key names a path a reader can open, and the walk is sorted so which of two
    links to the same target wins does not depend on directory order.
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


def _counts(paths: list[str]) -> tuple[Counter, list[str]]:
    """Map 'path::qualname' -> number of swallow sites; plus bad-pragma messages."""
    counts: Counter = Counter()
    problems: list[str] = []
    for path in _iter_py(paths):
        rel = _rel(path)
        # Tests may legitimately swallow while probing failure paths.
        if "/tests/" in "/" + rel or path.name.startswith("test_"):
            continue
        findings, bad = scan_file(path)
        for qualname, _lineno in findings:
            counts[f"{rel}::{qualname}"] += 1
        for lineno, reason in bad:
            problems.append(
                f"{rel}:{lineno}: invalid `swallow-ok` reason {reason!r}; "
                f"use one of {sorted(VALID_REASONS)}"
            )
    return counts, problems


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


def write_baseline(path: Path, counts: Counter) -> None:
    header = [
        "# Known log-and-swallow sites -- the ratchet baseline for",
        "# scripts/validation/error_swallow_validator.py. Format:",
        "#     <path>::<qualified function>::<number of swallow sites>",
        "#",
        "# A commit fails only if it introduces a site NOT covered here, or raises the",
        "# count for a function already listed. Line numbers are deliberately absent --",
        "# they rot on any edit above them.",
        "#",
        "# This file should only ever SHRINK. Do not regenerate it to make a new",
        "# finding go away; either fix the swallow or mark it `# swallow-ok: <reason>`.",
        "# The one legitimate reason it may GROW is a change to the validator's own",
        "# detection rules, which must land in the same commit as the regeneration.",
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
        "--check-shrink",
        type=Path,
        metavar="BASE_BASELINE",
        help="report entries that LEFT that baseline without the swallow being fixed",
    )
    ap.add_argument(
        "--base-tree",
        type=Path,
        metavar="DIR",
        help="a checkout of the base commit; required to report a DELETED logging call, "
        "which is otherwise indistinguishable from a pre-existing silent sibling",
    )
    args = ap.parse_args(argv[1:])

    paths = args.paths or list(SCAN_ROOTS)

    if args.check_shrink:
        unexplained = explain_shrink(
            load_baseline(args.check_shrink),
            [str(REPO_ROOT / root) for root in SCAN_ROOTS],
            base_root=args.base_tree,
        )
        if args.base_tree is None:
            print("note: no --base-tree, so a DELETED logging call cannot be reported.")
        if not unexplained:
            print("Every entry that left the baseline was fixed, deleted or marked.")
            return 0
        why = {
            "unrecognised": "the falsy test no longer recognises what it hands back",
            "silent": "the logging call was DELETED -- this is now a silent swallow, which is worse",
            "unscanned": "the file stopped being SCANNED; the handler never changed",
        }
        print("\n\U0001f6d1 Baseline entries that LEFT without the swallow being fixed\n")
        for u in unexplained:
            print(f"  {u.key}  (line {u.lineno})  [{u.reason}]")
            print(f"      {u.source}\n      -> {why[u.reason]}")
        print(
            "\n  Each handler above is still broad, still never propagates, and still sits in\n"
            "  a function that returns real values. Nothing in a baseline diff distinguishes\n"
            "  that from a fix -- a REMOVED line reads as progress either way.\n\n"
            "  To resolve one:\n"
            "    * include the cause in what you return (`str(e)`, `repr(e)`, `e.args`) --\n"
            "      that is the fix this guard exists to ask for, and it goes quiet;\n"
            "    * or re-raise / `frappe.throw`;\n"
            "    * or teach `_is_falsy_return` the new shape IN THE SAME COMMIT as the\n"
            "      regeneration, if the shape really is falsy;\n"
            "    * `# swallow-ok: <reason>` only if the failure genuinely does not matter.\n"
        )
        return 1

    if args.update_baseline:
        counts, _ = _counts([str(REPO_ROOT / root) for root in SCAN_ROOTS])
        write_baseline(args.baseline, counts)
        print(f"baseline written: {len(counts)} functions, {sum(counts.values())} sites")
        return 0

    counts, problems = _counts(paths)

    if args.stats:
        print(f"{sum(counts.values())} sites across {len(counts)} functions")
        return 0

    baseline = load_baseline(args.baseline)
    new = {k: v for k, v in counts.items() if v > baseline.get(k, 0)}

    if not new and not problems:
        return 0

    print("\n\U0001f6d1 Swallowed exceptions that destroy the failure cause\n")
    for msg in problems:
        print(f"  {msg}")
    for key, count in sorted(new.items()):
        known = baseline.get(key, 0)
        path, _, qualname = key.partition("::")
        extra = count - known
        where = f"{path}  {qualname}()"
        print(f"  {where}\n      {extra} new log-and-swallow site(s) (known: {known})")
    print(
        "\n  A broad `except` that only logs and returns a falsy value hides WHY it failed.\n"
        "  The caller cannot tell failure from 'legitimately nothing', and on CI the real\n"
        "  error dies with the database. Prefer re-raising, or return an explicit error.\n"
        "  If the failure genuinely does not matter, mark it:\n"
        "      except Exception:  # swallow-ok: best-effort\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
