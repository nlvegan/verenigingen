#!/usr/bin/env python3
"""Order-dependence growth gate for a PR that EDITS the scanner (#950).

THE HOLE THIS CLOSES
--------------------
``code-validation.yml``'s "Baseline did not grow" step compares the order-dependence total
in the PR's baseline against the base branch's. It used to ``exit 0`` as soon as
``scripts/testing/scan_order_dependence.py`` differed from the base, on the sound reasoning
that a census from scanner A and one from scanner B are not comparable. Nothing took its
place, so the PRs most likely to touch the scanner were the ones where a new finding plus
``--update-baseline`` in the same PR stayed green.

WHAT THIS DOES INSTEAD
----------------------
Hold the scanner constant and scan BOTH trees with it, so the censuses ARE comparable.
It does that twice, once per scanner version:

* the PR's scanner on the base tree and on the head tree -- catches a real new finding
  under the new detection rules;
* the BASE scanner on the base tree and on the head tree -- catches a PR that blinds or
  weakens the scanner in the same diff that adds a finding (under the new scanner alone
  both censuses shrink together and show zero delta).

Findings are keyed on ``(kind, file, snippet)`` as a multiset, not on line numbers: an
unrelated edit shifts lines, and a keyed diff on lines reports the same finding as one
added and one removed (#950 measured 29/29 on #943). COMMIT_EXEMPT is not gated, matching
the baseline's own ``# order-dependence`` marker.

FAIL CLOSED: a scanner that crashes, writes no JSON, or cannot be extracted from the base
sha fails the gate. Nothing here returns 0 because a comparison was impossible.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

GATED_KINDS = ("REUSE", "COUNT", "COMMIT")
DEFAULT_SCANNER = "scripts/testing/scan_order_dependence.py"
DEFAULT_SUBDIR = "verenigingen"


def _run_git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def census_from_json(path):
    """Multiset of gated findings keyed on (kind, file, snippet)."""
    findings = json.loads(Path(path).read_text())
    return Counter((f["kind"], f["file"], f["snippet"]) for f in findings if f["kind"] in GATED_KINDS)


def grown(before, after):
    """Keys whose count rose (or that are new) in `after`, as {key: (before, after)}."""
    return {k: (before[k], n) for k, n in after.items() if n > before[k]}


def _start_scan(scanner, tree_root, out_json):
    cmd = [sys.executable, str(scanner), str(tree_root), "--json", str(out_json)]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _finish_scan(proc, label, out_json):
    output, _ = proc.communicate()
    if proc.returncode != 0 or not Path(out_json).exists():
        raise RuntimeError(f"scan '{label}' failed (exit {proc.returncode}):\n{output[-2000:]}")
    return census_from_json(out_json)


def run_scans(scanners, trees, workdir):
    """scanners/trees: {name: path}. Returns {(scanner, tree): Counter}, scans run in parallel."""
    procs = {}
    for s_name, scanner in scanners.items():
        for t_name, root in trees.items():
            out = Path(workdir) / f"{s_name}-on-{t_name}.json"
            procs[(s_name, t_name)] = (_start_scan(scanner, root, out), out)
    return {k: _finish_scan(p, f"{k[0]} scanner on {k[1]} tree", out) for k, (p, out) in procs.items()}


def evaluate(censuses):
    """Return a list of failure lines; empty means the gate passes."""
    failures = []
    for s_name in sorted({s for s, _ in censuses}):
        new = grown(censuses[(s_name, "base")], censuses[(s_name, "head")])
        for (kind, file, snippet), (b, a) in sorted(new.items()):
            failures.append(f"[{s_name} scanner] {kind} {file}: {b} -> {a}  {snippet}")
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--repo", default=".", help="the head checkout (default: cwd)")
    ap.add_argument("--scanner", default=DEFAULT_SCANNER)
    ap.add_argument("--subdir", default=DEFAULT_SUBDIR, help="directory scanned in each tree")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        base_wt = Path(tmp) / "base-tree"
        added = _run_git("worktree", "add", "--detach", str(base_wt), args.base_sha, cwd=repo)
        if added.returncode != 0:
            print(f"::error::cannot check out base tree {args.base_sha}: {added.stderr}")
            return 1
        try:
            base_scanner = base_wt / args.scanner
            if not base_scanner.exists():
                print(f"::error::base tree has no {args.scanner}; cannot compare")
                return 1
            censuses = run_scans(
                {"head": repo / args.scanner, "base": base_scanner},
                {"base": base_wt / args.subdir, "head": repo / args.subdir},
                tmp,
            )
        except RuntimeError as exc:
            print(f"::error::order-dependence scanner-edit gate failed closed: {exc}")
            return 1
        finally:
            _run_git("worktree", "remove", "--force", str(base_wt), cwd=repo)

    for (s_name, t_name), c in sorted(censuses.items()):
        print(f"{s_name} scanner on {t_name} tree: {sum(c.values())} gated findings")
    failures = evaluate(censuses)
    if failures:
        print("::error::Order-dependence findings grew in a PR that edits the scanner.")
        print("\n".join(failures))
        return 1
    print("No order-dependence growth under either scanner version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
