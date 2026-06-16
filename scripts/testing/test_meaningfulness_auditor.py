#!/usr/bin/env python3
"""Fast mechanical audit of test *meaningfulness*.

Coverage tells you a line was executed; it does NOT tell you the test asserts
anything about the outcome. This auditor statically scans test files and flags
the patterns that make a test unable to catch a regression:

  NO_ASSERTION   - the test body has no assertion of any kind ("didn't raise"
                   smoke tests). The single biggest source of coverage padding.
  TAUTOLOGY      - assertEqual(a, a) / assertTrue(<constant>) / assertIsNone(None)
                   and friends -- always true regardless of product behaviour.
  BROAD_RAISES   - assertRaises(Exception) / pytest.raises(Exception): so broad
                   it would pass on an unrelated error (often legitimate for
                   parser "malformed input raises" tests -- eyeball each).
  MOCK_ONLY      - the only assertions are mock introspection (assert_called*),
                   so the test checks the mock, not real product state.

It is deliberately conservative to keep the false-positive rate low:

  * Assertion-bearing HELPER methods are resolved transitively. A test that
    delegates its checks to e.g. ``self._ok(...)`` (whose body asserts) is NOT
    flagged NO_ASSERTION. Without this, helper-delegating suites light up with
    false positives.
  * ``assertRaises``/``pytest.raises`` (call form and context-manager form),
    bare ``assert`` statements, and ``self.assertX(...)`` all count as assertions.

What it CANNOT tell you: whether an assertion that *exists* checks the *right*
thing. That needs a human/agent deep read. Use this to triage, then deep-review
the files it flags.

Usage:
    # scan explicit files / directories (dirs are recursed for test_*.py)
    python scripts/testing/test_meaningfulness_auditor.py verenigingen/tests/e_boekhouden
    python scripts/testing/test_meaningfulness_auditor.py path/to/test_foo.py path/to/test_bar.py

    # scan every test file changed since a git ref (e.g. a sweep baseline)
    python scripts/testing/test_meaningfulness_auditor.py --changed-since 4716acae

    # read a newline-delimited file list (the original interface)
    python scripts/testing/test_meaningfulness_auditor.py --from-list /tmp/files.txt

Exit code is 0 always (it is an advisory tool, not a gate); parse the report.

History: written 2026-06-15 for the coverage-sweep meaningfulness review
(docs/plans/2026-06-15-test-meaningfulness-review-inventory.md).
"""
import argparse
import ast
import os
import subprocess
import sys

ASSERT_METHODS_MOCK = {
    "assert_called", "assert_called_once", "assert_called_with",
    "assert_called_once_with", "assert_not_called", "assert_any_call",
    "assert_has_calls",
}
BROAD_EXC = {"Exception", "BaseException"}
FLAGS = ("NO_ASSERTION", "TAUTOLOGY", "BROAD_RAISES", "MOCK_ONLY", "PARSE_ERROR")


def is_self_assert(call):
    f = call.func
    if not isinstance(f, ast.Attribute):
        return False
    # self.fail()/failUnless()/failIf() are unittest's explicit-failure assertions
    # (commonly used as `self.fail(...)` inside an except block to assert "did not
    # raise X"); treat them as assertion-bearing.
    if f.attr in ("fail", "failUnless", "failIf", "failUnlessRaises"):
        return True
    return f.attr.startswith("assert") and f.attr not in ASSERT_METHODS_MOCK


def is_mock_assert(call):
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr in ASSERT_METHODS_MOCK


def const_truthiness(node):
    """('const' truthiness) for a literal node, else None."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return len(node.elts) > 0
    if isinstance(node, ast.Dict):
        return len(node.keys) > 0
    return None


def _check_tautology(call, flags):
    name = call.func.attr
    args = call.args
    if name in ("assertEqual", "assertIs", "assertNotEqual", "assertIsNot", "assertEquals") \
            and len(args) >= 2:
        if ast.dump(args[0]) == ast.dump(args[1]):
            flags.add("TAUTOLOGY")
    elif name in ("assertTrue", "assertFalse") and len(args) >= 1:
        t = const_truthiness(args[0])
        if t is not None and ((name == "assertTrue") == t):
            flags.add("TAUTOLOGY")
    elif name in ("assertIsNone", "assertIsNotNone") and len(args) >= 1:
        if isinstance(args[0], ast.Constant):
            flags.add("TAUTOLOGY")


def direct_asserts(fn):
    """(has_self_assert, has_bare_or_raises, has_mock, self_helper_calls)."""
    has_self = has_bare = has_raises = has_mock = False
    helper_calls = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            has_bare = True
        if isinstance(node, ast.Call):
            f = node.func
            attr = f.attr if isinstance(f, ast.Attribute) else None
            if attr in ("assertRaises", "assertRaisesRegex", "raises"):
                has_raises = True
            elif is_self_assert(node):
                has_self = True
            elif is_mock_assert(node):
                has_mock = True
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
                helper_calls.add(f.attr)
    return has_self, has_bare or has_raises, has_mock, helper_calls


def asserting_helpers(tree):
    """Method names that (transitively) contain assertions -> treated as assert helpers."""
    methods = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[node.name] = direct_asserts(node)
    asserts = {n for n, (sa, ba, mk, _hc) in methods.items() if sa or ba or mk}
    changed = True
    while changed:
        changed = False
        for n, (_sa, _ba, _mk, hc) in methods.items():
            if n not in asserts and (hc & asserts):
                asserts.add(n)
                changed = True
    return asserts


def analyze_func(fn, helper_asserts=frozenset()):
    flags = set()
    has_self = has_bare = has_raises = has_mock = calls_helper = non_mock = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            has_bare = non_mock = True
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                    and f.value.id == "self" and f.attr in helper_asserts:
                calls_helper = non_mock = True
            attr = f.attr if isinstance(f, ast.Attribute) else None
            if attr in ("assertRaises", "assertRaisesRegex", "raises"):
                has_raises = non_mock = True
                if node.args:
                    a0 = node.args[0]
                    nm = a0.id if isinstance(a0, ast.Name) else (a0.attr if isinstance(a0, ast.Attribute) else None)
                    if nm in BROAD_EXC:
                        flags.add("BROAD_RAISES")
            elif is_self_assert(node):
                has_self = non_mock = True
                _check_tautology(node, flags)
            elif is_mock_assert(node):
                has_mock = True
    has_any = has_self or has_bare or has_raises or has_mock or calls_helper
    if not has_any:
        flags.add("NO_ASSERTION")
    elif has_mock and not non_mock:
        flags.add("MOCK_ONLY")
    return flags


def scan(files):
    summary = {k: 0 for k in FLAGS}
    detail = []
    total = 0
    for path in files:
        if not os.path.isfile(path):
            continue
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as e:
            summary["PARSE_ERROR"] += 1
            detail.append((path, "PARSE_ERROR", str(e)))
            continue
        helpers = asserting_helpers(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                total += 1
                for fl in analyze_func(node, helpers):
                    summary[fl] += 1
                    detail.append((path, fl, f"{node.name}:{node.lineno}"))
    return summary, detail, total


def collect_paths(args):
    """Expand CLI args into a concrete list of test_*.py files."""
    if args.from_list:
        return [l.strip() for l in open(args.from_list, encoding="utf-8") if l.strip()]
    if args.changed_since:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{args.changed_since}..HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        return [f for f in out if _is_test_file(f) and os.path.isfile(f)]
    files = []
    for p in args.paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                files += [os.path.join(root, n) for n in names if _is_test_file(n)]
        elif _is_test_file(p):
            files.append(p)
    return sorted(set(files))


def _is_test_file(name):
    base = os.path.basename(name)
    return base.startswith("test_") and base.endswith(".py")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit test files for meaningfulness smells.")
    ap.add_argument("paths", nargs="*", help="test files or directories (dirs recursed for test_*.py)")
    ap.add_argument("--changed-since", metavar="REF", help="scan test files changed since a git ref")
    ap.add_argument("--from-list", metavar="FILE", help="read a newline-delimited file list")
    ap.add_argument("--detail", action="store_true", default=True, help="print per-test detail (default on)")
    ap.add_argument("--no-detail", dest="detail", action="store_false", help="counts only")
    args = ap.parse_args(argv)

    files = collect_paths(args)
    if not files:
        print("No test files found. Pass paths, a directory, --changed-since REF, or --from-list FILE.")
        return 0

    summary, detail, total = scan(files)
    print(f"# Scanned {len(files)} files, {total} test functions\n")
    print("## Flag counts")
    for k in FLAGS:
        print(f"  {k:14} {summary[k]}")
    if args.detail:
        print("\n## Detail (file | flag | test:line)")
        for path, fl, where in sorted(detail, key=lambda r: (r[1], r[0], r[2])):
            print(f"{fl:13} {path}  {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
