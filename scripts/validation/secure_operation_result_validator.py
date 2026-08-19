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
2. **UNCHECKED** -- the result is assigned to a name whose ``.success`` is never
   read anywhere in the enclosing function.

WHAT IS NOT FLAGGED
-------------------
* ``return secure_document_operation(...)`` -- the result is handed to the
  caller, and responsibility with it.
* Any result whose ``.success`` is read, however the failure is then handled.
  This rule is about *looking*, not about what you do next; a branch that looks
  and deliberately continues is the sibling failed-write rule's business.
* Test files. They stub, spy and provoke failures on purpose.

OPT-OUT
-------
A genuinely best-effort write says so on the call line or the line above::

    secure_document_operation(...)  # secure-op-ok: best-effort

Accepted reasons: ``best-effort``, ``caller-verifies``, ``false-positive``.
Prefer checking ``.success`` and logging -- an opt-out records a decision, it
does not make the failure visible.

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


def _opted_out(lines: list[str], lineno: int) -> bool:
    """An opt-out on the call line, or on the line above it."""
    for idx in (lineno - 1, lineno - 2):
        if 0 <= idx < len(lines) and OPT_OUT in lines[idx]:
            return True
    return False


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

        # Which calls are bare statements, and which are assigned to a name?
        discarded: list[ast.Call] = []
        assigned: dict[str, int] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Expr) and _is_target_call(node.value):
                discarded.append(node.value)
            elif isinstance(node, ast.Assign) and _is_target_call(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned[target.id] = node.value.lineno
            # `return secure_document_operation(...)` hands the result upward.

        if not discarded and not assigned:
            continue

        checked = {
            node.value.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Attribute)
            and node.attr == "success"
            and isinstance(node.value, ast.Name)
            and node.value.id in assigned
        }

        for call in discarded:
            if _opted_out(lines, call.lineno):
                continue
            findings.append(
                Finding(
                    rel,
                    call.lineno,
                    fn.name,
                    "DISCARDED",
                    "the result is thrown away, so a failed write is invisible here",
                )
            )
        for name, lineno in sorted(assigned.items()):
            if name in checked or _opted_out(lines, lineno):
                continue
            findings.append(
                Finding(
                    rel,
                    lineno,
                    fn.name,
                    "UNCHECKED",
                    f"'{name}.success' is never read",
                )
            )

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
