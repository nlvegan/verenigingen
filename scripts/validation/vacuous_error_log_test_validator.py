#!/usr/bin/env python3
"""Block tests that CLAIM an Error Log write in their name but assert nothing.

THE BUG CLASS
-------------
``expectErrorLog(*patterns)`` (``verenigingen/tests/utils/error_log_guard.py``)
is a MUTE BUTTON, not an assertion. Its own docstring says so: it marks
substrings so the harness's automatic tearDown check ignores matching rows.
It records patterns, asserts nothing, and cannot fail.

So a test shaped like this passes whether or not the log is ever written::

    def test_validate_disallowed_doctype_logs_security_event(self):
        \"\"\"A disallowed doctype is rejected AND writes a security Error Log.\"\"\"
        self.expectErrorLog("Payment Status Security")
        is_valid, result = validate_payment_document_access("ToDo", "x", "tr_x")
        self.assertFalse(is_valid)

#1112 found this the expensive way: #1105 DELETED a security-relevant
``frappe.log_error`` and the test named after it stayed green -- 33/33, with
the write gone. #1116 then converted 17 such tests to the new positive
``assertErrorLog()`` helper and renamed an 18th whose claimed write never
existed at all. Nothing prevented the 19th, which is what this gate is for:
the finding was a CLASS, and closing a class means keeping it closed.

WHAT IS FLAGGED
---------------
A ``def test_*`` method is reported when ALL of these hold:

1. its NAME claims an Error Log write -- a whole ``_``-delimited segment from
   ``log/logs/logged/logging/error_log/audit_log``. See ``AUDIT_NAME_PATTERN``
   for the wider pattern #1116 classified with, why the gate does not use it,
   and the one real shape this narrowness misses;
2. its body calls ``self.expectErrorLog(...)``; and
3. its body contains NOTHING that asserts anything about the Error Log:
   no ``assertErrorLog`` / ``assertNoErrorLog``, no call whose name mentions
   ``error_log`` (a local helper such as ``_assert_error_log_written``), and
   no reference to the ``"Error Log"`` doctype or the ``tabError Log`` table
   -- which is how the ~45 already-sound candidates in #1116's classification
   do their asserting.

WHY CONDITION 2 IS PART OF THE RULE, NOT AN OVERSIGHT
------------------------------------------------------
Without ``expectErrorLog``, the harness's AUTOMATIC tearDown check is live:
a test that writes a row and does not declare it FAILS. So the vacuous shape
cannot hide there -- the declaration is precisely what buys the silence.

The complement (a name claiming a log, no ``expectErrorLog``, no assertion)
is a real but DIFFERENT class: those tests are not silently passing while a
row is written; they are at most MISNAMED, like the one #1116 renamed. That
population is large (measured 220 on ``fa440fcd6``, under a narrow name
pattern, and heavily contaminated by tests about domain audit-log doctypes
rather than ``tabError Log``). It has never been classified and is
deliberately out of scope here rather than silently included.

NO BASELINE, DELIBERATELY
-------------------------
Every known instance is fixed (#1116, and #1103 for the two in
``test_page_payment_success_coverage.py``), so the population is ZERO and
this gate is zero-tolerance. A baseline file would be new ratchet debt
(#985) and would inherit the shrink-gate defect in #1110, for no benefit.
If a legitimate exception ever appears, mark it rather than baselining it::

    def test_audit_something(self):  # vacuous-log-test-ok: false-positive

Reasons: ``false-positive`` (the name does not actually claim an Error Log
write -- e.g. a file that prefixes unrelated tests ``test_audit_*``),
``intentional`` (the author has a documented reason the claim is not
asserted).
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]

# Both scan roots hold test files. `scripts/` is live code with its own tests
# (#1044/#1076/#1083), so leaving it out would repeat the scope-drift class
# those issues are about.
SCAN_ROOTS = ("verenigingen", "scripts")

# Whole `_`-delimited name segments that claim a log write. A SUBSTRING match
# instead of segments is what made an earlier attempt match
# `test_replay_attack_prevention` on "pre-vent-ion".
# `error_log`/`audit_log` are NOT listed: as whole segments they always contain
# the `log` segment already matched here (`..._error_log_...` holds `_log_`).
NAME_CLAIMS_LOG = re.compile(r"(?:^|_)(?:log|logs|logged|logging)(?:_|$)")

# The wider pattern #1116 used to CLASSIFY, kept for `--audit` only. It adds
# record/report/audit/security_event segments, answering #1112's worry that a
# `..._records_security_event` name would be missed.
#
# It is deliberately NOT what the gate matches. Measured on `fa440fcd6`:
#
#     pattern   pre-#1116 tree   develop   real instances caught   tree-wide residue
#     WIDENED         20            2               18                    40
#     NARROW          17            0               17                     9
#
# (both counts over the files #1116 touched, plus a tree-wide scan). The 18th
# instance the widened pattern catches is real -- `test_audit_run_audit_no_
# mollie_key_returns_failure`, whose name claims a log only via "audit" -- so
# THAT SHAPE IS A KNOWN GAP IN THIS GATE, stated rather than hidden. It is not
# worth the trade: the widened pattern's extra 31 tree-wide hits are tests
# asserting a DIFFERENT claim (`..._reports_partial_write` asserting a
# `partial_write` flag; `..._is_audited` asserting a SEPA Audit Log row), and
# every one would need a permanent pragma. A sweep can afford to over-collect
# because a person rules each one out once; a gate cannot.
AUDIT_NAME_PATTERN = re.compile(
    r"(?:^|_)(?:log|logs|logged|logging|error_log|audit_log"
    r"|record|records|recorded|report|reports|reported"
    r"|audit|audits|audited|security_event)(?:_|$)"
)

VALID_REASONS = {"false-positive", "intentional"}
_MARKER = re.compile(r"#\s*vacuous-log-test-ok\s*:\s*([a-z-]+)?")

_EXPECT = "expectErrorLog"
# Names that mean the test really does assert something about the log. Checked
# as call-name substrings (case-folded) so a local helper like
# `_assert_error_log_written` counts -- #1103 shipped exactly that shape while
# the shared helper was still in flight on another branch.
# KNOWN LIMIT, stated rather than silent: this matches ANY called name
# containing "errorlog"/"error_log", not only assertion helpers. A test calling
# an unrelated `clear_error_log_cache()` would be treated as sound. It is
# deliberately generous because this repo has several local spellings
# (`assert_error_log`, `_capture_error_logs`) and a narrow list would flag
# sound tests, each then needing a permanent pragma. Swept on `fa440fcd6`:
# every test relying on this signal today uses a real assertion helper or a
# real query, so the gap has ZERO live population -- it is a structural risk,
# not a present hole. Narrow it if that ever stops being true.
_ASSERTING_CALL = re.compile(r"error_?log", re.IGNORECASE)
_DOCTYPE_REFS = ("Error Log", "tabError Log")


class Finding(NamedTuple):
    file: str
    test: str
    lineno: int


def _call_name(node: ast.Call) -> str:
    """The called name as written -- ``self.foo(...)`` -> ``foo``.

    ONE source of truth. There were two once; they drifted, and the mute call's
    own argument became evidence that the test checked the log.
    """
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _own_calls(fn: ast.AST):
    """Yield ``(name, node)`` for calls textually inside `fn`, EXCLUDING the
    bodies of nested functions and lambdas.

    A call that is only ever *defined* is not evidence that anything was
    checked. ``ast.walk`` descends into nested bodies, so this passed::

        def test_rejection_logs_the_event(self):
            self.expectErrorLog("Some Title")
            def _unused_checker():
                self.assertErrorLog("Some Title")   # never called
            do_it()

    Found by the fourth review, and it is the likeliest way a "fix" to a
    flagged test goes wrong: bolt on a checker, forget to call it. Same
    traversal, and the same reason for it, as
    ``log_error_arg_order_validator._own_calls``.

    Decorators are not in ``fn.body``, so a decorator argument is out of scope
    here by construction rather than by a special case.
    """
    stack = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            yield _call_name(node), node
        stack.extend(ast.iter_child_nodes(node))


def _carries_doctype_literal(node: ast.Call) -> bool:
    """Is the Error Log doctype or its table named in this call's arguments?"""
    for operand in list(node.args) + [kw.value for kw in node.keywords]:
        for sub in ast.walk(operand):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if sub.value.strip() == "Error Log" or "tabError Log" in sub.value:
                    return True
    return False


# Callables that actually READ the Error Log. The soundness signal is the
# doctype literal sitting in one of THESE calls' arguments -- not merely inside
# some call's arguments, which is a different and much weaker claim.
_QUERY_CALL = re.compile(
    r"^(?:sql|sql_list|count|exists|get_all|get_list|get_value|get_values"
    r"|get_doc|get_last_doc|get_single_value)$"
)

_SETUP_METHODS = {"setUp", "setUpClass", "asyncSetUp"}


def _class_mutes(cls: ast.ClassDef) -> bool:
    """Does this class's own setUp/setUpClass call ``expectErrorLog``?

    THE PREMISE THIS EXISTS FOR WAS WRONG. This gate only flags tests that mute
    the harness, on the stated grounds that an unmuted test cannot silently pass
    -- the automatic tearDown check fails it. That is true only when the mute is
    where the checker looks. Calling ``self.expectErrorLog(...)`` from ``setUp``
    mutes every test in the class just as effectively, and 20 test files in this
    repo already do it. A textbook-vacuous test in such a class scored ZERO
    findings until this function existed. Found by the fourth review; live
    exploited population at the time was 0, by luck rather than design.
    """
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _SETUP_METHODS:
            if any(name == _EXPECT for name, _ in _own_calls(node)):
                return True
    return False


def _is_vacuous(fn: ast.AST, muted_by_class: bool = False) -> bool:
    """Does `fn` mute the harness check and then assert nothing about the log?

    One walk, one rule: the ``expectErrorLog`` call is excluded ONCE, here, so
    no sibling loop can forget to. Evidence that the test really checks the
    Error Log is any OTHER call that either

    * names an assertion/capture helper (``_ASSERTING_CALL``), or
    * is a read (``_QUERY_CALL``) carrying the doctype literal.

    Four rounds of review, every finding the same mistake -- accepting a signal
    that does not mean what it claims:

    1. any string constant anywhere -> the test's own DOCSTRING exempted it.
    2. any string in any call's arguments -> an assertion MESSAGE did, and so
       did ``print(...)`` and a ``@unittest.skip`` argument. The prose is not
       exotic: the "``tabError Log`` is MyISAM" remark recurs in 13 test files.
    3. the mute call itself counted as evidence -> ``expectErrorLog("Error
       Log")``, because ``_ASSERTING_CALL`` matches "expectErrorLog" and only
       one of the two duplicated walks skipped it.
    4. the mute had to be in the test BODY, and a call that was merely defined
       counted as evidence -> a class muting in ``setUp`` was invisible
       (``_class_mutes``), and a never-invoked nested checker scored as sound
       (``_own_calls``).

    KNOWN LIMITS, stated because this file states its limits:

    * A read whose RESULT IS DISCARDED still counts -- ``frappe.get_all("Error
      Log", ...)`` on a line by itself makes a vacuous test look sound. Closing
      it needs dataflow, not AST position. Pinned.
    * ``_ASSERTING_CALL`` is deliberately generous (any name containing
      "error_log"), so a harmless ``clear_error_log_cache()`` exempts too.
      Narrowing it would flag the real local helpers (``assert_error_log``,
      ``_capture_error_logs``), which carry no doctype literal. Pinned.
    * The doctype must be a literal AT the query; hoisting it to a name is a
      FALSE POSITIVE needing a pragma. Pinned.
    * The mute must be a call spelled ``expectErrorLog``. Aliasing it
      (``mute = self.expectErrorLog``) or reaching it through ``getattr``
      hides it, as does inheriting a muting ``setUp`` from a base class in
      ANOTHER file -- cross-file resolution is out of scope for an AST gate.
      Pinned.

    Every one of these fails in a stated direction with a measured live
    population of zero. That is the most this gate claims.
    """
    calls = list(_own_calls(fn))
    if not (muted_by_class or any(name == _EXPECT for name, _ in calls)):
        return False
    for name, node in calls:
        if name == _EXPECT:
            continue
        if _ASSERTING_CALL.search(name):
            return False
        if _QUERY_CALL.match(name) and _carries_doctype_literal(node):
            return False
    return True


def _test_methods(tree: ast.AST):
    """Yield ``(fn, muted_by_class)`` for every runnable ``test_*``.

    Only methods sitting DIRECTLY in a class body, and module-level functions
    (``pytest.ini`` sets ``python_functions = test_*``). A ``def test_...``
    nested inside another function is not collectable by unittest or pytest and
    is no longer reported -- it used to be, via ``ast.walk``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            muted = _class_mutes(node)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("test_"):
                        yield child, muted
        elif isinstance(node, ast.Module):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("test_"):
                        yield child, False


def _suppressed(fn: ast.AST, lines: list[str]) -> tuple[bool, str | None]:
    """A `# vacuous-log-test-ok:` marker anywhere in the test's own lines.

    Same raw-text approach, and the same known limits, as
    ``error_swallow_validator._suppressed``: a marker spelled inside a string
    literal would also suppress. Scanning the whole method (not just its
    ``def`` line) is intentional -- the pragma marks the TEST, and authors put
    it next to the line that explains why.
    """
    for ln in range(fn.lineno, (fn.end_lineno or fn.lineno) + 1):
        if 1 <= ln <= len(lines):
            m = _MARKER.search(lines[ln - 1])
            if m:
                reason = m.group(1)
                return True, (None if reason in VALID_REASONS else (reason or "<missing>"))
    return False, None


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def scan_file(path: Path, name_pattern=None) -> tuple[list[Finding], list[tuple[int, str]]]:
    """Return (findings, bad_pragmas) for one test file.

    `name_pattern` defaults to the GATE's pattern. It is threaded through as an
    argument rather than read from a module global so `--audit` cannot leave the
    wider pattern latched on for everything after it.
    """
    name_pattern = name_pattern or NAME_CLAIMS_LOG
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return [], []

    lines = source.splitlines()
    findings: list[Finding] = []
    bad_pragmas: list[tuple[int, str]] = []

    for fn, muted_by_class in _test_methods(tree):
        if not name_pattern.search(fn.name):
            continue
        if not _is_vacuous(fn, muted_by_class):
            continue
        ok, bad_reason = _suppressed(fn, lines)
        if ok:
            if bad_reason:
                bad_pragmas.append((fn.lineno, f"invalid reason {bad_reason!r}"))
            continue
        findings.append(Finding(_rel(path), fn.name, fn.lineno))

    return findings, bad_pragmas


def _iter_test_files(paths):
    """Yield each PHYSICAL ``test_*.py`` under `paths` exactly once.

    Same symlink dedupe, and the same excluded directories, as the sibling
    ratchets -- a symlinked module and its target are two ``os.walk`` entries
    but one file, and would otherwise be reported twice.
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
                candidates.extend(
                    Path(dirpath) / fn
                    for fn in filenames
                    if fn.startswith("test_") and fn.endswith(".py")
                )
        elif p.name.startswith("test_") and p.suffix == ".py" and p.exists():
            candidates.append(p)

    seen: set[Path] = set()
    for path in sorted(candidates, key=lambda q: (q.is_symlink(), str(q))):
        target = path.resolve()
        if target in seen:
            continue
        seen.add(target)
        yield path


def default_paths() -> list[str]:
    return [str(REPO_ROOT / root) for root in SCAN_ROOTS]


def scan(paths, name_pattern=None) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_test_files(paths):
        found, _bad = scan_file(path, name_pattern)
        findings.extend(found)
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=default_paths())
    ap.add_argument("--stats", action="store_true", help="print the total and exit 0")
    ap.add_argument(
        "--audit",
        action="store_true",
        help="scan with the wider #1116 classification pattern and exit 0 -- a "
        "review aid, never a gate: most of its extra hits assert a different claim",
    )
    args = ap.parse_args(argv[1:])

    pattern = AUDIT_NAME_PATTERN if args.audit else NAME_CLAIMS_LOG

    paths = args.paths or default_paths()
    # pre-commit passes the changed files and invokes the hook in BATCHES, so a
    # success line printed per call appears once per batch. Only say "clean" for
    # a whole-tree run, which is the claim that actually means something.
    whole_tree = paths == default_paths()

    findings: list[Finding] = []
    problems: list[str] = []
    for path in _iter_test_files(paths):
        found, bad = scan_file(path, pattern)
        findings.extend(found)
        problems.extend(f"{_rel(path)}:{ln}: {msg}" for ln, msg in bad)

    if args.stats or args.audit:
        label = "candidates (wide classification pattern)" if args.audit else "vacuous log-claiming tests"
        print(f"{label}: {len(findings)}")
        for f in findings:
            print(f"  {f.file}:{f.lineno}  {f.test}")
        return 0

    if problems:
        print("\n\U0001f6d1 Invalid `vacuous-log-test-ok` pragmas\n")
        for p in problems:
            print(f"  {p}")
        print(f"\n  Valid reasons: {sorted(VALID_REASONS)}")

    if findings:
        print("\n\U0001f6d1 Tests whose name claims an Error Log write but which assert nothing\n")
        for f in findings:
            print(f"  {f.file}:{f.lineno}  {f.test}")
        print(
            "\n  expectErrorLog() only MUTES the harness's automatic check -- it asserts"
            "\n  nothing, so each test above passes whether or not the log is written"
            "\n  (#1112). Fix by using the positive helper:"
            "\n"
            '\n      with self.assertErrorLog("Some Title"):'
            "\n          ..."
            "\n"
            "\n  If the write is not supposed to happen, assert that instead with"
            "\n  assertNoErrorLog() and rename the test. If the name does not really"
            "\n  claim a log write, mark it `# vacuous-log-test-ok: false-positive`."
        )
        return 1

    if problems:
        return 1

    if whole_tree:
        print("✅ No vacuous log-claiming tests found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
