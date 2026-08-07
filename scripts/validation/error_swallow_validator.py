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
2. the handler never re-raises;
3. its body is only logging calls and returns;
4. every return in it is falsy (``None``/``False``/``{}``/``[]``); and
5. the ENCLOSING FUNCTION elsewhere returns a real value.

(5) is what separates a dangerous swallow from a harmless one. A function that
never returns anything meaningful (fire-and-forget cache invalidation, a
best-effort notification) is not reported: its falsy return is not load-bearing,
because no caller can branch on it.

RATCHET, NOT BIG-BANG
---------------------
There are ~393 such sites today. Failing on all of them would block every commit,
and pragma-ing 393 sites in one diff would be unreviewable. So this validator
fails only on sites NOT already recorded in the baseline.

The baseline is keyed ``path::qualified_function::count`` -- deliberately NOT line
numbers, which rot on any edit above them. The count means a new swallow added to
an ALREADY-baselined function is still caught.

    python scripts/validation/error_swallow_validator.py --update-baseline

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

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = Path(__file__).with_name("error_swallow_baseline.txt")

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
}
BROAD_EXCEPTIONS = {"Exception", "BaseException"}

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
    if isinstance(v, ast.Constant) and v.value in (None, False):
        return True
    if isinstance(v, ast.Dict) and not v.keys:
        return True
    if isinstance(v, (ast.List, ast.Tuple, ast.Set)) and not v.elts:
        return True
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
        # (5) does this function elsewhere return a REAL value?
        returns_real = any(
            isinstance(n, ast.Return) and n.value is not None and not _is_falsy_return(n)
            for n in _own_nodes(fn)
        )
        if not returns_real:
            continue

        for node in _own_nodes(fn):
            if not isinstance(node, ast.ExceptHandler) or not _is_broad(node):
                continue
            if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
                continue

            body = [n for n in node.body if not isinstance(n, ast.Pass)]
            logs = [n for n in body if _is_log_call(n)]
            rets = [n for n in body if isinstance(n, ast.Return)]
            if not logs or not rets:
                continue
            if not all(_is_log_call(n) or isinstance(n, ast.Return) for n in body):
                continue
            if not all(_is_falsy_return(r) for r in rets):
                continue

            ok, bad_reason = _suppressed(node, lines)
            if ok:
                if bad_reason:
                    bad_pragmas.append((node.lineno, bad_reason))
                continue
            findings.append((qualname, node.lineno))

    return findings, bad_pragmas


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_py(paths: list[str]):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in {"node_modules", ".git", "__pycache__", "worktrees", ".claude", "archived"}
                ]
                for fn in filenames:
                    if fn.endswith(".py"):
                        yield Path(dirpath) / fn
        elif p.suffix == ".py" and p.exists():
            yield p


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
        "",
    ]
    body = [f"{k}::{v}" for k, v in sorted(counts.items())]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=["verenigingen"])
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--stats", action="store_true", help="print totals and exit 0")
    args = ap.parse_args(argv[1:])

    paths = args.paths or ["verenigingen"]

    if args.update_baseline:
        counts, _ = _counts([str(REPO_ROOT / "verenigingen")])
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
