#!/usr/bin/env python3
"""Block NEW SQL date-window predicates built from the DATABASE clock.

THE BUG CLASS (#668, read side of #453)
----------------------------------------
Frappe writes ``creation``/``modified`` from ``frappe.utils.now()`` -- the
**site** clock (``System Settings.time_zone``). A predicate like::

    WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)

builds its boundary from MariaDB's own ``NOW()``/``CURDATE()`` -- the
**database server's** clock. Nothing keeps the two in step. Measured on
``test_site_4`` (2026-08-31): a 3h30m skew between them, so
``DATE_SUB(NOW(), INTERVAL 1 HOUR)`` selected a window 4h30m wide instead of
one hour -- 4.5x too wide, and EMPTY if the skew runs the other way.

The fix is to compute the boundary in Python with ``frappe.utils`` --
``add_to_date(now_datetime(), hours=-1)``, ``add_days(today(), -7)`` -- and pass
it as a bound parameter, never let the database compute "now" itself. Same
shape #453 landed on for the write side (see
``verenigingen_payments/utils/sepa_constants.py::stranded_batch_exclusion`` and
its ``%(today)s`` parameter for a fixed example).

WHAT IS FLAGGED
---------------
A line (outside a `#`-comment and outside `tests/`) whose SQL text calls the
database's ``NOW()`` or ``CURDATE()`` -- ALL-CAPS, the spelling this app's raw
SQL strings use throughout -- in a way that builds or compares a date/time
boundary:

* ``DATE_SUB(NOW()...)`` / ``DATE_ADD(NOW()...)`` / `` (CURDATE()...)``
* ``DATEDIFF(..., NOW()/CURDATE())`` / ``TIMESTAMPDIFF(..., NOW()/CURDATE())``
* ``CURDATE() - INTERVAL ...`` (the same DATE_SUB arithmetic spelled inline)
* a direct comparison against a column: ``col > NOW()``, ``NOW() <= col``, etc.
* ``YEAR(CURDATE())`` / ``YEAR(NOW())`` equality (e.g. "same fiscal year as now")

WHAT IS DELIBERATELY NOT FLAGGED
---------------------------------
* lowercase ``now()`` -- that is Python's ``frappe.utils.now``, the SITE clock,
  used correctly.
* a bare ``NOW()``/``CURDATE()`` used only as an instant with no comparison or
  arithmetic around it (e.g. ``SELECT NOW()`` as a health-check probe) -- not a
  date WINDOW, nothing to get wrong.
* a mixed-case query-builder spelling (``CurDate()`` via ``frappe.qb`` /
  pypika) -- a real instance of this bug class exists this way
  (``membership_analytics.py`` builds ``DateDiff(CurDate(), ...)``), but this
  validator's case-sensitive, string-oriented matching cannot see it without a
  real risk of matching unrelated PascalCase identifiers. Known gap, not an
  oversight -- like the ``__import__("datetime").datetime.now()`` gap named in
  ``tests/test_site_timezone_naive_now.py``.
* a raw ``INSERT ... VALUES (..., NOW(), NOW(), ...)`` writing ``creation``/
  ``modified`` directly -- that is #453's WRITE-side bug (a different clock
  fix: ``NOW(6)`` or, better, stop hand-writing the columns at all), not this
  validator's read-side predicates.

WHY A RATCHET, NOT A BIG-BANG FIX
----------------------------------
#668 measured 94 occurrences across 30 files. Converting all of them in one PR
is not reviewable and is explicitly out of scope for the fix that introduced
this validator (see the PR body for which subset WAS fixed and why). This
freezes the CURRENT count and blocks only NEW occurrences, exactly like
``log_error_arg_order_validator.py`` before it.

The baseline is keyed ``path::qualified_function::count`` -- NOT line numbers,
which rot on any edit above them::

    python scripts/validation/db_clock_date_window_validator.py --update-baseline

Escape hatch, matching the ``log-error-args-ok`` convention already used in
this tree::

    # creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)  # db-clock-window-ok: false-positive
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
DEFAULT_BASELINE = Path(__file__).with_name("db_clock_date_window_baseline.txt")

# The roots the baseline covers. CI scans exactly these; the pre-commit hook
# scans only the files you touched, so its `exclude` must stay a SUBSET of
# this -- a file the hook scans but the baseline does not cover fails
# spuriously on its first edit.
SCAN_ROOTS = ("verenigingen", "scripts")

VALID_REASONS = {"false-positive", "intentional"}
_MARKER = re.compile(r"#\s*db-clock-window-ok\s*:\s*([a-z-]+)?")

# ALL-CAPS only: this app's raw SQL strings spell the MySQL functions
# uppercase throughout (94/94 occurrences named in #668 are). Lowercase
# `now()` is Python's `frappe.utils.now` -- the SITE clock, correctly used --
# and must never trip this.
_CLOCK = r"(?:NOW|CURDATE)"

_PATTERNS = [
    re.compile(rf"DATE_SUB\s*\(\s*{_CLOCK}\s*\(\s*\)"),
    re.compile(rf"DATE_ADD\s*\(\s*{_CLOCK}\s*\(\s*\)"),
    re.compile(rf"DATEDIFF\s*\([^)]*\b{_CLOCK}\s*\(\s*\)"),
    re.compile(rf"TIMESTAMPDIFF\s*\([^)]*\b{_CLOCK}\s*\(\s*\)"),
    re.compile(rf"\b{_CLOCK}\s*\(\s*\)\s*[-+]\s*INTERVAL"),
    re.compile(rf"[<>=!]=?\s*{_CLOCK}\s*\(\s*\)"),
    re.compile(rf"\b{_CLOCK}\s*\(\s*\)\s*[<>=!]"),
    re.compile(rf"\bYEAR\s*\(\s*{_CLOCK}\s*\(\s*\)\s*\)"),
]


def _matches_line(line: str) -> bool:
    """True if `line` contains a date-window predicate built on NOW()/CURDATE()."""
    return any(p.search(line) for p in _PATTERNS)


def line_findings(path: Path) -> list[int]:
    """Line numbers in `path` carrying a database-clock date-window predicate.

    A line whose first non-whitespace character is `#` is a pure comment and
    is skipped -- both the prose in module docstrings that merely MENTIONS
    ``NOW()``/``CURDATE()`` (e.g. ``payment_retry.py``'s own writeup of this
    exact bug class) and a `# ...` note above a query are not findings. A
    trailing inline comment on a real predicate line is not specially
    stripped -- none of the 94 occurrences this validator was built against
    carry one, so the extra complexity of a real tokenizer is not justified
    yet; see `_suppressed` below for the one inline marker this DOES honour.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for lineno, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            continue
        if _matches_line(line):
            found.append(lineno)
    return found


def _suppressed(lineno: int, lines: list[str]) -> tuple[bool, str | None]:
    """Look for a `# db-clock-window-ok:` marker on the finding's own line."""
    if not (1 <= lineno <= len(lines)):
        return False, None
    m = _MARKER.search(lines[lineno - 1])
    if not m:
        return False, None
    reason = m.group(1)
    return True, (None if reason in VALID_REASONS else (reason or "<missing>"))


def _qualnames(tree: ast.AST):
    """Yield (qualified_name, start_line, end_line) for every function, plus
    the whole module as `<module>` -- same shape as
    ``log_error_arg_order_validator._qualnames``, adapted to give line RANGES
    rather than visiting call nodes, since a finding here is a line of SQL
    text, not a parsed Python call.
    """

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = f"{prefix}{child.name}"
                yield qn, child.lineno, getattr(child, "end_lineno", child.lineno)
                yield from walk(child, f"{qn}.")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")
            else:
                yield from walk(child, prefix)

    yield from walk(tree, "")
    yield "<module>", tree.lineno if hasattr(tree, "lineno") else 1, getattr(
        tree, "end_lineno", 10**9
    )


def _enclosing_qualname(lineno: int, scopes: list[tuple[str, int, int]]) -> str:
    """The INNERMOST function whose line range contains `lineno`, else `<module>`."""
    best = "<module>"
    best_width = None
    for qualname, start, end in scopes:
        if qualname == "<module>":
            continue
        if start <= lineno <= end:
            width = end - start
            if best_width is None or width < best_width:
                best, best_width = qualname, width
    return best


def scan_file(path: Path) -> tuple[list[tuple[str, int]], list[tuple[int, str]]]:
    """Return (findings, bad_pragmas) for one file.

    findings: list of (qualified_function, lineno)
    bad_pragmas: list of (lineno, reason) where the marker reason is invalid
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], []

    lines = source.splitlines()
    raw_findings = line_findings(path)
    if not raw_findings:
        return [], []

    try:
        tree = ast.parse(source)
        scopes = list(_qualnames(tree))
    except SyntaxError:
        scopes = []

    findings, bad_pragmas = [], []
    for lineno in raw_findings:
        ok, bad_reason = _suppressed(lineno, lines)
        if ok:
            if bad_reason:
                bad_pragmas.append((lineno, bad_reason))
            continue
        qualname = _enclosing_qualname(lineno, scopes) if scopes else "<module>"
        findings.append((qualname, lineno))
    return findings, bad_pragmas


def scan_file_all(path: Path) -> list[tuple[str, int]]:
    """Every finding in `path`, INCLUDING pragma-suppressed ones.

    Used only by `explain_shrink`, mirroring
    ``log_error_arg_order_validator.scan_file_all``.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    raw_findings = line_findings(path)
    if not raw_findings:
        return []
    try:
        tree = ast.parse(source)
        scopes = list(_qualnames(tree))
    except SyntaxError:
        scopes = []
    return [
        (_enclosing_qualname(lineno, scopes) if scopes else "<module>", lineno)
        for lineno in raw_findings
    ]


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_py(paths: list[str]):
    """Yield the .py files under `paths`, each PHYSICAL file exactly once.

    Same dedupe (and same reason -- a symlinked module and its target are two
    `os.walk` entries but one file) as
    ``log_error_arg_order_validator._iter_py``.
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
    """Map 'path::qualname' -> number of finding sites; plus bad-pragma messages."""
    counts: Counter = Counter()
    problems: list[str] = []
    for path in _iter_py(paths):
        rel = _rel(path)
        # Tests may legitimately construct the bad shape to probe the defect itself.
        if "/tests/" in "/" + rel or path.name.startswith("test_"):
            continue
        # This validator's own docstrings quote the bad shape as worked examples
        # (unlike an AST-based detector, a line-regex scanner has no way to tell
        # "prose describing the pattern" from "the pattern" within its own file).
        if path.name == "db_clock_date_window_validator.py":
            continue
        findings, bad = scan_file(path)
        for qualname, _lineno in findings:
            counts[f"{rel}::{qualname}"] += 1
        for lineno, reason in bad:
            problems.append(
                f"{rel}:{lineno}: invalid `db-clock-window-ok` reason {reason!r}; "
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


def new_findings(counts: Counter, baseline: dict[str, int]) -> dict[str, int]:
    """The ratchet comparison itself: which counted sites exceed the baseline."""
    return {k: v for k, v in counts.items() if v > baseline.get(k, 0)}


def write_baseline(path: Path, counts: Counter) -> None:
    header = [
        "# Known DATABASE-clock date-window predicates -- the ratchet baseline for",
        "# scripts/validation/db_clock_date_window_validator.py. Format:",
        "#     <path>::<qualified function>::<number of finding sites>",
        "#",
        "# Frappe writes creation/modified from the SITE clock (frappe.utils.now()),",
        "# not the database server's NOW()/CURDATE() -- the two drift independently",
        "# (#668, measured 3h30m skew on test_site_4). A commit fails only if it",
        "# introduces a site not covered here, or raises the count for a function",
        "# already listed.",
        "#",
        "# This file should only ever SHRINK. Do not regenerate it to make a new",
        "# finding go away; either fix the predicate (compute the boundary with",
        "# frappe.utils.add_to_date()/now_datetime()/today() and pass it as a bound",
        "# parameter) or mark it `# db-clock-window-ok: <reason>`. The one legitimate",
        "# reason it may GROW is a change to the validator's own detection rules,",
        "# which must land in the same commit as the regeneration.",
        "",
    ]
    body = [f"{k}::{v}" for k, v in sorted(counts.items())]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


class UnexplainedShrink(NamedTuple):
    """A baseline entry that left without the predicate actually being fixed."""

    key: str
    lineno: int
    reason: str


def explain_shrink(baseline: dict[str, int], paths: list[str]) -> list[UnexplainedShrink]:
    """Baseline entries whose count DROPPED without the predicate being fixed.

    Mirrors ``log_error_arg_order_validator.explain_shrink``: a shrink is the
    one direction this ratchet would otherwise accept without question, and
    it can happen two ways that are NOT a real fix -- a suppression pragma
    added on a still-matching line, or the file leaving SCAN_ROOTS.
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
        if not full.exists():
            continue  # file deleted: that explains itself
        lines = full.read_text(encoding="utf-8").splitlines()
        all_findings = scan_file_all(full)
        still_matching: dict[str, list[int]] = {qn: [] for qn, _ in by_path[rel]}
        for qualname, lineno in all_findings:
            if qualname in still_matching:
                still_matching[qualname].append(lineno)

        for qualname, missing in sorted(by_path[rel]):
            for lineno in sorted(still_matching[qualname])[:missing]:
                ok, _bad = _suppressed(lineno, lines)
                reason = "suppressed" if ok else "unscanned"
                out.append(UnexplainedShrink(f"{rel}::{qualname}", lineno, reason))
    return out


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
        help="report baseline entries that LEFT without the predicate being fixed",
    )
    args = ap.parse_args(argv[1:])

    paths = args.paths or list(SCAN_ROOTS)

    if args.check_shrink:
        unexplained = explain_shrink(
            load_baseline(args.check_shrink), [str(REPO_ROOT / root) for root in SCAN_ROOTS]
        )
        if not unexplained:
            print("Every entry that left the baseline was fixed, deleted, or moved out of scan range.")
            return 0
        why = {
            "suppressed": "a `# db-clock-window-ok:` pragma was added -- the line still matches",
            "unscanned": "the file left SCAN_ROOTS; the predicate itself never changed",
        }
        print("\n\U0001f6d1 Baseline entries that LEFT without the predicate being fixed\n")
        for u in unexplained:
            print(f"  {u.key}  (line {u.lineno})  [{u.reason}] -> {why[u.reason]}")
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
    new = new_findings(counts, baseline)

    if not new and not problems:
        return 0

    print("\n\U0001f504 SQL date window built from the DATABASE clock (NOW()/CURDATE())\n")
    for msg in problems:
        print(f"  {msg}")
    for key, count in sorted(new.items()):
        known = baseline.get(key, 0)
        path, _, qualname = key.partition("::")
        extra = count - known
        where = f"{path}  {qualname}()"
        print(f"  {where}\n      {extra} new database-clock date-window site(s) (known: {known})")
    print(
        "\n  Frappe writes creation/modified from the SITE clock (frappe.utils.now()), not\n"
        "  the database server's NOW()/CURDATE() -- the two drift independently (#668,\n"
        "  measured 3h30m skew on test_site_4). Compute the boundary in Python and pass\n"
        "  it as a bound parameter instead:\n"
        "      from frappe.utils import add_to_date, now_datetime\n"
        "      cutoff = add_to_date(now_datetime(), hours=-1)\n"
        "      frappe.db.sql('... WHERE creation > %s', (cutoff,))\n"
        "  If this really is not a date-window predicate (e.g. a plain health-check\n"
        "  ``SELECT NOW()`` with no comparison), mark it:\n"
        "      WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)  # db-clock-window-ok: false-positive\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
