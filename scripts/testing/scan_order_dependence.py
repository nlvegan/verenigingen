"""Static scanner for test order-dependence anti-patterns.

The dynamic detector (order_dependence_detector.py) proves order-dependence by
running files, but it can only flag tests that *currently* fail in some shard
layout. This scanner is the cheap, exhaustive complement: it AST-walks every
test file and flags the source patterns that CAUSE order-dependence, whether or
not the test happens to fail today. A different shard split tomorrow turns a
latent offender into a failure -- this finds them first.

Patterns flagged (each is a way a test's result can depend on its neighbours):

  REUSE   frappe.get_all(DT, limit=1) / get_all(DT)[0] in setUp/setUpClass.
          The test reuses *whatever record already exists*, so its behaviour
          depends on what preceding files in the shard left in the DB. This is
          the exact bug in test_team_assignment_history.

  COUNT   *** STRUCTURALLY UNREACHABLE against this codebase -- see below. ***
          An assertion over len(frappe.get_all(DT)) or frappe.db.count(DT) with
          no test-scoped filter. Neighbours that add records of DT break it.

  COMMIT  A bare frappe.db.commit() in test code (outside a _cleanup_/_create_
          helper). Commits escape the per-test rollback, leaking state to later
          files in the same shard process. Blocks the CI no-growth gate.

  COMMIT_EXEMPT  The same bare commit, but inside a recognised _cleanup_*/
          _create_*/tearDown fixture helper (#820/#827 -- a legitimate,
          load-bearing pattern). Reported for visibility, never gated: see
          #825, "FIXED" section below, for why this is tracked rather than
          silently dropped.

KNOWN GAP -- COUNT reports 0 and always will (#815 review, 2026-09-04)
-------------------------------------------------------------------
COUNT fires only from ``visit_Compare``, i.e. a bare ``==``/``<`` comparison node. Every
count assertion in this codebase is written ``self.assertEqual(frappe.db.count(DT), n)`` --
an ``ast.Call``, which that visitor never inspects. Measured across all 337 scanned files:
**COUNT=0**, and a grep for the Compare shape returns zero matches. So a COUNT of 0 means
"this kind cannot fire here", NOT "no such anti-pattern exists"; real unscoped-count sites
exist and are invisible, e.g. ``tests/backend/components/test_setup_workflow_definitions.py``
(x3) and ``tests/events/test_approval_events_coverage.py``.

Recorded rather than fixed on purpose: extending detection to assertion Calls would add
findings to a baseline in the same change that introduced the gate, which is the one shape
the "Baseline did not grow" CI step is built to reject. Widen it in its own PR.

FIXED -- #851: a FILE path silently reported 0 findings
--------------------------------------------------------
``main()`` used to hand ``args.root`` straight to ``os.walk()``. ``os.walk()`` on a file
yields nothing at all, so ``scan_order_dependence.py some/test_foo.py`` printed
"Total findings: 0" -- identical output to a genuinely clean scan. That is exactly the
input a reader reaches for when a CI ratchet names one file, so it silently defeated the
gate at the moment it mattered most (see #851, and PR #844 where an agent hit this live).
``discover_findings()`` now branches on ``os.path.isfile``/``isdir`` and refuses a path
that is neither, rather than treating "not a directory" as "nothing found".

FIXED -- #825: the COMMIT exemption trusted a bare function NAME
-------------------------------------------------------------------
The exemption below (``_in_helper``) is genuine and load-bearing -- see #820/#827, where a
commit that must stay was moved into a real ``_create_*``/``_cleanup_*`` fixture builder,
which is exactly the shape it exists to allow. The bug was that trusting the name ALONE
made the exemption a rename away from erasing a finding with **no trace at all**: nothing
in the scanner's output, the baseline, or a diff distinguished "reviewed and accepted
fixture commit" from "renamed to make the gate stop complaining". #825's own comment
thread also found the exemption cannot simply be deleted (246 existing sites rely on it,
and the CI no-growth gate makes it the *only* sanctioned way to keep a legitimate fixture
commit) -- so the fix keeps the exemption but makes it a *visible, tracked* category
(``COMMIT_EXEMPT``) instead of a silent no-op: an exempted commit is still emitted as a
finding, printed in its own section, and written to the baseline (under a marker the CI
no-growth gate's grep does not match, so it stays non-blocking) instead of vanishing. A
future rename into/out of ``_create_*``/``_cleanup_*``/``tearDown`` now shows up as a
``COMMIT`` entry disappearing and a ``COMMIT_EXEMPT`` entry appearing (or vice versa) in
the baseline diff a reviewer actually sees, rather than one just disappearing.

CONTROL -- a scanner that cannot silently return zero (#851/#825 aftermath)
-----------------------------------------------------------------------------
Both bugs above produced the exact same symptom: a run that had checked nothing looked
identical to a run that found a clean tree. ``run_self_check()`` closes that class rather
than just these two instances: every invocation of ``main()`` first scans a fixed,
known-bad snippet (``_CONTROL_SOURCE``, embedded here rather than written to the scanned
tree, so it cannot be excluded by a future scan-root change) through the SAME
``discover_findings()`` codepath used for the real scan -- file-path handling included.
If the control's REUSE, COMMIT, and COMMIT_EXEMPT findings do not all come back, the
scanner exits non-zero with a loud diagnostic instead of proceeding to print a possibly
-fake "0 findings". See the module's own tests for proof this fires when the scanner is
deliberately broken.

Usage (from the app root or anywhere):
    python scripts/testing/scan_order_dependence.py [tests_root] [--json out.json]

Exit code is 0 for a normal scan (findings are reported, not gated) and non-zero ONLY when
the self-check above fails or the given root does not exist -- read stdout / the JSON for
findings either way.
"""

import argparse
import ast
import json
import os
import sys
import tempfile

SETUP_FUNCS = {"setUp", "setUpClass", "setUpModule"}
SCOPING_KW = {"filters", "name", "or_filters"}  # presence => query is (likely) scoped


def _attr_chain(node):
    """Return dotted attribute chain for a Call's func, e.g. 'frappe.get_all'."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_get_all(call):
    chain = _attr_chain(call.func)
    return chain.endswith("get_all") or chain.endswith("get_list")


def _query_is_scoped(call):
    """True if a get_all/get_list call appears scoped to specific records."""
    for kw in call.keywords:
        if kw.arg in SCOPING_KW:
            return True
    # positional filters: get_all("DT", {...}) or get_all("DT", filters=...)
    if len(call.args) >= 2 and isinstance(call.args[1], (ast.Dict, ast.List)):
        return True
    return False


def _has_limit_one(call):
    for kw in call.keywords:
        if kw.arg in ("limit", "limit_page_length") and isinstance(kw.value, ast.Constant):
            if call.keywords and str(kw.value.value) in ("1",):
                return True
    return False


class Finding:
    __slots__ = ("kind", "file", "line", "snippet")

    def __init__(self, kind, file, line, snippet):
        self.kind, self.file, self.line, self.snippet = kind, file, line, snippet

    def as_dict(self):
        return {"kind": self.kind, "file": self.file, "line": self.line, "snippet": self.snippet}


class Visitor(ast.NodeVisitor):
    def __init__(self, relpath, source_lines):
        self.rel = relpath
        self.lines = source_lines
        self.func_stack = []
        self.findings = []

    def _snip(self, node):
        return self.lines[node.lineno - 1].strip() if 0 < node.lineno <= len(self.lines) else ""

    def _add(self, kind, node):
        self.findings.append(Finding(kind, self.rel, node.lineno, self._snip(node)))

    def visit_FunctionDef(self, node):
        self.func_stack.append(node.name)
        self.generic_visit(node)
        self.func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _in_helper(self):
        # _cleanup_* / _create_* helpers are exempt (see test-quality-enforcer convention)
        return any(f.startswith(("_cleanup", "_create", "tearDown")) for f in self.func_stack)

    def visit_Call(self, node):
        chain = _attr_chain(node.func)

        # COMMIT: bare frappe.db.commit() in test code. A commit inside a
        # _cleanup_*/_create_*/tearDown helper is a recognised, legitimate pattern
        # (#820/#827) -- but #825 found that trust was purely nominal, so a helper's
        # commit is still emitted, just as the non-blocking COMMIT_EXEMPT kind, so a
        # rename into/out of that exemption is visible in the report/baseline diff
        # rather than a finding silently vanishing.
        if chain.endswith("db.commit"):
            self._add("COMMIT_EXEMPT" if self._in_helper() else "COMMIT", node)

        # REUSE: unscoped get_all/get_list in a setUp picking an arbitrary record
        if _is_get_all(node) and not _query_is_scoped(node):
            in_setup = any(f in SETUP_FUNCS for f in self.func_stack)
            if in_setup or _has_limit_one(node):
                self._add("REUSE", node)

        self.generic_visit(node)

    def visit_Compare(self, node):
        # COUNT: assert-style comparison whose operand is len(get_all(...)) / db.count(...)
        for operand in [node.left, *node.comparators]:
            if self._is_global_count(operand):
                self._add("COUNT", node)
                break
        self.generic_visit(node)

    def _is_global_count(self, node):
        # len(frappe.get_all("DT")) with no filters
        if isinstance(node, ast.Call) and _attr_chain(node.func) == "len":
            if node.args and isinstance(node.args[0], ast.Call) and _is_get_all(node.args[0]):
                return not _query_is_scoped(node.args[0])
        # frappe.db.count("DT") with no filter arg
        if isinstance(node, ast.Call) and _attr_chain(node.func).endswith("db.count"):
            scoped = any(kw.arg == "filters" for kw in node.keywords) or len(node.args) >= 2
            return not scoped
        return False


def scan_file(path, root):
    rel = os.path.relpath(path, root)
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
    except (OSError, SyntaxError):
        return []
    v = Visitor(rel, src.splitlines())
    v.visit(tree)
    return v.findings


def discover_findings(root):
    """Scan `root`: a single file, or a directory walked for test_*.py files.

    #851: the old logic handed `root` straight to os.walk(), which silently yields
    nothing for a file path -- indistinguishable from a genuinely clean directory
    scan. A single file is exactly what a reader reaches for when a CI ratchet
    names one, so support it directly instead of mis-answering it.
    """
    if os.path.isfile(root):
        return list(scan_file(root, os.path.dirname(root) or "."))
    if not os.path.isdir(root):
        sys.exit(
            f"{root}: no such file or directory -- this scanner walks a directory "
            "or scans a single file, and cannot report findings for neither."
        )
    findings = []
    for dirpath, dirs, files in os.walk(root):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for fn in files:
            if fn.startswith("test_") and fn.endswith(".py"):
                findings.extend(scan_file(os.path.join(dirpath, fn), root))
    return findings


# A fixed, known-bad snippet the scanner must ALWAYS flag -- see the module docstring's
# "CONTROL" section. Embedded here rather than committed as a file under the scanned
# tree, so it cannot rot, be excluded by a future scan-root change, or get "fixed" by
# someone cleaning up test code.
_CONTROL_SOURCE = '''\
import frappe


class ControlProbeTest:
    def setUp(self):
        # REUSE control: unscoped get_all() in setUp -- picks an arbitrary record.
        self.thing = frappe.get_all("Something")

    def test_control_probe(self):
        # COMMIT control: a bare commit directly in a test method.
        frappe.db.commit()

    def _create_control_fixture(self):
        # COMMIT_EXEMPT control: the same bare commit, but inside a helper the
        # scanner's naming convention recognises as a fixture builder (#820/#827).
        frappe.db.commit()
'''

_CONTROL_EXPECTED_KINDS = {"REUSE", "COMMIT", "COMMIT_EXEMPT"}


def run_self_check():
    """Prove the scanner still detects known-bad patterns before trusting any scan.

    #851 (a file path) and #825 (a renamed helper) both let a run that had checked
    nothing look identical to a run that found a clean tree. This scans
    ``_CONTROL_SOURCE`` -- written to a real temp file and read back through the same
    ``discover_findings()`` codepath a normal CLI invocation uses, file-path handling
    included -- and demands all three kinds come back. If any are missing, the
    scanner itself (not the tree) is broken: exit loudly here rather than proceed to
    print a possibly-fake "0 findings".
    """
    with tempfile.TemporaryDirectory() as tmp:
        control_path = os.path.join(tmp, "test_order_dependence_control.py")
        with open(control_path, "w", encoding="utf-8") as fh:
            fh.write(_CONTROL_SOURCE)
        findings = discover_findings(control_path)
    kinds = {f.kind for f in findings}
    missing = _CONTROL_EXPECTED_KINDS - kinds
    if missing:
        sys.exit(
            "ORDER-DEPENDENCE SCANNER SELF-CHECK FAILED: the known-bad control "
            f"snippet did not produce {sorted(missing)}. This scanner cannot be "
            "trusted to report a real '0 findings' -- fix the scanner (see #851, "
            "#825) before trusting this or any other run of it."
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    here = os.path.dirname(os.path.abspath(__file__))
    # The whole PACKAGE, not verenigingen/tests. The narrower default was a real blind
    # spot: test modules also live beside the code they cover
    # (verenigingen/verenigingen/doctype/*/test_*.py, verenigingen/services/*/test_*.py),
    # and measured on 7f1557af0 the default hid 179 COMMIT findings across 63 files --
    # including test_contribution_amendment_request_coverage.py, whose bare commit is what
    # #815 turned on. A scanner that exits 0 has no reason to look at less. Same class as
    # #798, where a filename exclusion hid 9 real test modules from every check.
    default_root = os.path.normpath(os.path.join(here, "..", "..", "verenigingen"))
    ap.add_argument("root", nargs="?", default=default_root, help="directory to scan")
    ap.add_argument("--json", help="write findings JSON to this path")
    ap.add_argument(
        "--update-baseline",
        metavar="PATH",
        help="rewrite PATH as a per-file census (`<KIND> <relpath>::<count>`). Growth/shrink "
             "classification is NOT done here -- scripts/validation/baseline_shrink_gate.py "
             "owns that, so this tool does not become a ninth hand-rolled copy of the "
             "read_baseline/regressions pair the other validators each carry.",
    )
    args = ap.parse_args()

    # #851/#825: prove the scanner can still find known-bad patterns BEFORE trusting
    # this run's own answer, including on the file-path codepath the two issues broke.
    run_self_check()

    findings = discover_findings(args.root)

    by_kind = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    order = ["REUSE", "COUNT", "COMMIT", "COMMIT_EXEMPT"]
    print(f"Scanned {args.root}")
    print(f"Total findings: {len(findings)}  "
          + "  ".join(f"{k}={len(by_kind.get(k, []))}" for k in order))
    files_with = {f.file for f in findings}
    print(f"Files implicated: {len(files_with)}\n")
    for kind in order:
        items = sorted(by_kind.get(kind, []), key=lambda f: (f.file, f.line))
        if not items:
            continue
        print(f"=== {kind} ({len(items)}) ===")
        for f in items:
            print(f"  {f.file}:{f.line}: {f.snippet}")
        print()

    if args.update_baseline:
        counts = {}
        for f in findings:
            counts[(f.kind, f.file)] = counts.get((f.kind, f.file), 0) + 1
        lines = [
            "# Order-dependence census -- see #815. Upward-only: growth fails, shrinkage",
            "# self-heals (scripts/validation/baseline_shrink_gate.py). Regenerate with",
            "#   python scripts/testing/scan_order_dependence.py --update-baseline <this file>",
            "# A bare commit is NOT proof of a bug: #815's commit was a TRIGGER, and removing",
            "# it broke 16 of its own module's tests because it was load-bearing for deadlock",
            "# avoidance. This ratchet exists to stop NEW ones accruing, not to demand the",
            "# existing debt be paid.",
            "# COUNT never appears below: its detector cannot fire against this codebase's",
            "# assertEqual-style assertions -- see the scanner's KNOWN GAP section.",
            "# COMMIT_EXEMPT (#825) is a commit inside a recognised _cleanup_*/_create_*/",
            "# tearDown fixture helper -- legitimate, not gated on growth (its trailing",
            "# marker deliberately does NOT match CI's '# order-dependence' grep), but",
            "# still recorded so a rename into/out of the exemption shows up as a normal",
            "# baseline diff instead of a finding vanishing with no trace.",
        ]
        for (kind, path), n in sorted(counts.items()):
            marker = "# order-dep-exempt" if kind == "COMMIT_EXEMPT" else "# order-dependence"
            lines.append(f"{kind} {path}::{n}  {marker}")
        with open(args.update_baseline, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"baseline written: {len(counts)} keys, {len(findings)} findings")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([f.as_dict() for f in findings], fh, indent=2)
        print(f"JSON written to {args.json}")


if __name__ == "__main__":
    main()
