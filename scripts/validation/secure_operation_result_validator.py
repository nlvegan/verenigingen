#!/usr/bin/env python3
"""Require every ``secure_document_operation()`` result to be checked.

THE BUG CLASS
-------------
``secure_document_operation`` does **not** raise when a write fails. It catches
the exception, records it on an ``OperationResult``, and returns with
``success=False``. A caller that ignores the return value is therefore told
nothing, and carries on as if the row had been written.

This has produced real defects:

* ``donation_refund_journal_entry_creator`` returned the Journal Entry name even
  when its submit failed, so a reversal that never reached the ledger was
  reported as a completed refund -- and because the idempotency lookup counts any
  ``docstatus != 2``, the unposted entry claimed the reversal key and every
  redelivery answered "already processed" (fixed in PR #379).
* ``donation_journal_entry_creator`` has the same shape on the forward path,
  where it additionally makes the donation impossible to reverse (#381).

WHY A ``try``/``except`` IS NOT A CHECK
---------------------------------------
For the failure this rule is about, nothing is raised, so nothing is caught. (Three
things *do* still raise and are outside the try in ``secure_document_operation``:
``validate_justification``, the ``bypass_validations`` role gate, and a re-raised
``NON_RESUMABLE_DB_ERROR``. A handler is live for those -- and dead for the ordinary
write failure this rule exists to catch.)

Every discard this rule was written for had exception-handling wrapped around it:

===============================================  ===========================================
site                                             the machinery that never fires
===============================================  ===========================================
``base_role_profile_manager._strip_role_profile``  caller's ``except Exception`` + savepoint
``membership_dues_schedule._clear_retry_tracking`` its own ``try``/``except`` + log_error
===============================================  ===========================================

Both were written as if the function raises. It does not. The handler is dead
code for the failure mode it was written to catch, which is exactly why this
needs a validator rather than a code-review habit -- it reads as handled.

WHAT IS FLAGGED
---------------
A call to ``secure_document_operation(...)`` where the result is never examined:

1. **DISCARDED** -- the call is a bare expression statement; the result is gone.
2. **UNCHECKED** -- the result is assigned to a target (``result``, ``self.result``,
   or an annotated assignment) whose ``.success`` is never read in the enclosing
   function, and which is not returned.
3. **TRUTHINESS** -- the call is used directly as a condition, e.g.
   ``if secure_document_operation(...):``. This one always passes:
   ``SecureOperationResult`` defines no ``__bool__``, so every instance is truthy
   and the branch is taken whether the write succeeded or not.

WHAT IS NOT FLAGGED
-------------------
* ``return secure_document_operation(...)``, and a result that is assigned and then
  returned -- both hand the result to the caller, and the responsibility with it.
* Any result whose ``.success`` is read, however the failure is then handled.
  This rule is about *looking*, not about what you do next; a branch that looks
  and deliberately continues is the sibling failed-write rule's business.
* Test files. They stub, spy and provoke failures on purpose.

Known gaps, by design -- there is no cross-function analysis, so these are reported
even though a human would call them handled: ``getattr(result, "success")``, and
passing the result to a helper that checks it. Use the pragma for those.

HOW TO ACT ON A FINDING
-----------------------
Reading ``.success`` is the requirement; what to do next depends on what the failed
write costs. Roughly:

===================================================  ==================================
if the write is...                                   then
===================================================  ==================================
irreversible, security-relevant, or the thing the    **raise**. A revocation that
caller's contract promises (access revocation,       silently did not happen is worse
posting money)                                       than a loud failure.
something the caller could act on or report          **return an explicit failure** the
                                                     caller reads -- a result object, a
                                                     falsy return, an error dict.
genuinely best-effort (audit trail, comment,         **log with the consequence named**
notification, cleanup after an already-failed        and mark the call with the pragma
operation)                                           below.
===================================================  ==================================

When unsure, prefer returning a failure over raising: it keeps the contract
consistent with the surrounding code, which is mostly result-object style.

OPT-OUT
-------
A genuinely best-effort write says so on the call line or the line above::

    secure_document_operation(...)  # secure-op-ok: best-effort

The reason is required and must be one of ``best-effort``, ``caller-verifies``,
``false-positive`` -- an unrecognised or missing reason is itself reported, so the
pragma records a decision rather than waving the rule away. Prefer checking
``.success`` and logging; an opt-out documents a choice, it does not make the
failure visible.

NO BASELINE, DELIBERATELY
-------------------------
The siblings (``failed_write_validator``, ``error_swallow_validator``) ratchet
against a baseline because they inherited a large legacy inventory. This rule
starts at **zero**: the full sweep of all 218 non-test call sites found exactly
three violations, and all three are fixed in the commit that adds this file. So
there is nothing to grandfather, and any hit is a genuine regression.

Usage::

    python scripts/validation/secure_operation_result_validator.py [paths...]
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("verenigingen",)
FUNC_NAME = "secure_document_operation"
_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
OPT_OUT = "secure-op-ok:"
VALID_REASONS = ("best-effort", "caller-verifies", "false-positive")


class Finding:
    def __init__(self, path: str, lineno: int, func: str, kind: str, detail: str):
        self.path, self.lineno, self.func = path, lineno, func
        self.kind, self.detail = kind, detail

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: {self.kind} in {self.func}(): {self.detail}"


def _is_target_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == FUNC_NAME


def _opt_out_reason(lines: list[str], lineno: int):
    """The pragma's reason, if one is present on the call line or the line above.

    Returns None when there is no pragma at all, otherwise the (possibly empty or
    invalid) reason text. The caller distinguishes the three cases -- an unpoliced
    pragma is the only way a rule with no baseline can quietly die.
    """
    for idx in (lineno - 1, lineno - 2):
        if 0 <= idx < len(lines) and OPT_OUT in lines[idx]:
            return lines[idx].split(OPT_OUT, 1)[1].strip()
    return None


def scan_file(path: pathlib.Path) -> list[Finding]:
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):
        return []
    if FUNC_NAME not in source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    try:
        rel = str(path.relative_to(REPO_ROOT))
    except ValueError:
        # A path outside the repo (the validator's own tests scan temp files).
        rel = str(path)
    findings: list[Finding] = []

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Only this function's own body. ast.walk descends into nested defs, and the
        # outer walk visits those separately, so without this every finding inside a
        # nested function was reported twice -- once against each enclosing name.
        inner = {
            id(d) for n in ast.walk(fn) if isinstance(n, _FUNC_TYPES) and n is not fn for d in ast.walk(n)
        }
        nodes = [n for n in ast.walk(fn) if id(n) not in inner]

        discarded: list[ast.Call] = []
        truthiness: list[ast.Call] = []
        assigned: dict[str, int] = {}  # target expression -> lineno
        consumed: set[ast.Call] = set()

        for node in nodes:
            if isinstance(node, ast.Expr) and _is_target_call(node.value):
                discarded.append(node.value)
                consumed.add(node.value)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_target_call(node.value):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    # `result`, and `self.result` -- a service-class shape the
                    # Name-only check used to miss entirely.
                    if isinstance(target, (ast.Name, ast.Attribute)):
                        assigned[ast.unparse(target)] = node.value.lineno
                consumed.add(node.value)
            elif isinstance(node, ast.Return) and _is_target_call(node.value):
                consumed.add(node.value)  # handed to the caller

        # Used directly as a condition. SecureOperationResult defines no __bool__,
        # so this is unconditionally true -- it reads as a check and is not one.
        for node in nodes:
            tests = []
            if isinstance(node, (ast.If, ast.While)):
                tests.append(node.test)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                tests.append(node.operand)
            elif isinstance(node, ast.BoolOp):
                tests.extend(node.values)
            for test in tests:
                if _is_target_call(test) and test not in consumed:
                    truthiness.append(test)
                    consumed.add(test)

        if not discarded and not assigned and not truthiness:
            continue

        # `.success` read on the target, and targets that are returned (handing the
        # result, and the responsibility, to the caller).
        checked, handed_off = set(), set()
        for node in nodes:
            if isinstance(node, ast.Attribute) and node.attr == "success":
                owner = ast.unparse(node.value)
                if owner in assigned:
                    checked.add(owner)
            elif isinstance(node, ast.Return) and node.value is not None:
                returned = ast.unparse(node.value)
                if returned in assigned:
                    handed_off.add(returned)

        def _record(lineno: int, kind: str, detail: str) -> None:
            reason = _opt_out_reason(lines, lineno)
            if reason is None:
                findings.append(Finding(rel, lineno, fn.name, kind, detail))
            elif reason not in VALID_REASONS:
                shown = repr(reason) if reason else "no reason at all"
                findings.append(
                    Finding(
                        rel,
                        lineno,
                        fn.name,
                        "BAD_OPT_OUT",
                        f"{shown} is not an accepted reason; use one of " f"{', '.join(VALID_REASONS)}",
                    )
                )

        for call in discarded:
            _record(
                call.lineno,
                "DISCARDED",
                "the result is thrown away, so a failed write is invisible here",
            )
        for call in truthiness:
            _record(
                call.lineno,
                "TRUTHINESS",
                "used directly as a condition, but SecureOperationResult defines no "
                "__bool__ -- this is always true whether the write succeeded or not; "
                "assign it and test '.success'",
            )
        for target, lineno in sorted(assigned.items()):
            if target in checked or target in handed_off:
                continue
            _record(lineno, "UNCHECKED", f"'{target}.success' is never read")

    return findings


def _iter_files(paths: list[str]):
    for raw in paths:
        p = pathlib.Path(raw)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if p.is_dir():
            yield from sorted(p.rglob("*.py"))
        elif p.suffix == ".py":
            yield p


def _is_test(path: pathlib.Path) -> bool:
    return "/tests/" in str(path) or path.name.startswith("test_")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=list(SCAN_ROOTS))
    args = ap.parse_args(argv[1:])

    findings: list[Finding] = []
    for path in _iter_files(args.paths or list(SCAN_ROOTS)):
        if _is_test(path):
            continue
        findings.extend(scan_file(path))

    if not findings:
        return 0

    print("\n🔐 secure_document_operation results that are never checked:\n")
    for f in findings:
        print(f"  {f}")
    print(
        "\n  secure_document_operation does NOT raise. It returns success=False, so a\n"
        "  try/except around it is not a check -- every instance of this defect so far\n"
        "  had exception handling that could never fire (#379, #381).\n\n"
        "  Read `.success` and act on it. If the write is genuinely best-effort, still\n"
        "  read it and log, then mark the call:\n"
        f"      # {OPT_OUT} {'|'.join(VALID_REASONS)}\n"
    )
    print(f"  {len(findings)} unchecked result(s)\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
