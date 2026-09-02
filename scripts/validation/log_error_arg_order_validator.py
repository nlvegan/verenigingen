#!/usr/bin/env python3
"""Block NEW two-argument positional ``frappe.log_error(message, title)`` calls.

THE BUG CLASS
-------------
``frappe.log_error`` is ``(title, message)`` -- ``frappe/utils/error.py:44``. This
app calls it the other way round, positionally, at over a thousand sites::

    frappe.log_error(f"Error processing retry queue for {tracker_name}: {e}",
                      "Retry Queue Processing Error")

Frappe tries to be smart about the swap, and only half succeeds
(``frappe/utils/error.py:61-66``)::

    traceback = None
    if message:
        if "\\n" in title:          # traceback sent as title
            traceback, title = title, message
        else:
            traceback = message    # <- our case

Because the swapped "title" (the first positional argument -- here the dynamic
message) is a single line, the heuristic does not fire. The passed message
becomes the **title**, and the passed title becomes the **traceback** -- so
``frappe.get_traceback(with_context=True)`` is never called and the real stack
is never recorded. The cause survives only in the title, truncated at 140
characters. Most of these sit in ``except`` blocks, exactly where the stack
was worth having. See #602.

WHAT IS FLAGGED
---------------
A call to ``log_error`` (bare name or any ``x.log_error`` attribute access,
matched by name only -- the framework's own function is the overwhelming
majority of call sites, and a false positive here is cheap: a keyword rewrite
that changes nothing) is reported when ALL of these hold:

1. it takes two or more POSITIONAL arguments and no keyword arguments -- a
   call already using ``title=``/``message=`` is self-documenting and cannot
   be silently re-inverted, so it is out of scope by construction;
2. the FIRST argument is "message-shaped": an f-string (``ast.JoinedStr``), a
   string concatenation (``ast.BinOp`` with ``ast.Add``), or a bare
   ``str(...)`` call -- the three shapes named in #602's fix order; and
3. the SECOND argument is a plain string literal -- the shape of a short,
   hand-written title.

A THIRD (or fourth) positional argument is frappe's own
``reference_doctype``/``reference_name``, so it does not by itself change
whether (1)-(3) describe a swap -- except that this repo also has several
same-named LOCAL methods with a genuinely different 3-argument convention,
``log_error(message, record_type, record_data)`` (``self.log_error``,
``PaymentLogger.log_error``, ...), which can accidentally match the same
(message-shaped, literal) shape. So a call with 3+ positional arguments is
flagged only when the receiver is unambiguously frappe's own function --
literally ``frappe.log_error(...)`` or a bare ``log_error(...)`` name; see
``_is_unambiguously_frappes``. A call with exactly 2 positional arguments
keeps the broader by-name match, unchanged.

A bare variable in the first position (``log_error(some_var, "Title")``) is
DELIBERATELY not flagged: unlike an f-string or a ``str()`` call, a name gives
no static evidence of which parameter the author meant it for, and this
repo's own code has legitimate ``log_error(title_var, message_var)`` calls
where flagging by shape alone would be pure guesswork. #602's directory sweep
handled the ones it could find manually; the validator's job is only to stop
new EASILY-CONFIRMED swaps from arriving in the code that has not been swept
yet.

Two arguments that are BOTH dynamic (``log_error(f"...", get_message())``) are
not flagged either: there is no literal-title shape here to say which one the
author meant as the label, so guessing would just be noise.

WHY A RATCHET, NOT A BIG-BANG FIX
----------------------------------
#602 measured roughly 1100 non-test sites tree-wide. Converting all of them in
one PR would be the largest diff in the repo's history against dozens of
in-flight worktrees. This validator instead freezes the CURRENT count (after a
first sweep of the highest-value directories -- payment/SEPA/Mollie/
eBoekhouden money paths) and blocks only NEW occurrences, exactly like
``error_swallow_validator.py`` and ``failed_write_validator.py`` before it.

The baseline is keyed ``path::qualified_function::count`` -- deliberately NOT
line numbers, which rot on any edit above them::

    python scripts/validation/log_error_arg_order_validator.py --update-baseline

Escape hatch, matching the ``swallow-ok`` / ``failed-write-ok`` convention
already used in this tree::

    frappe.log_error(f"...", "Title")  # log-error-args-ok: false-positive

Reasons: false-positive (the shape looks like a swap but is not -- e.g. a
receiver named `log_error` that is not ``frappe.log_error``), intentional (the
author has a documented reason the literal is genuinely the message and the
f-string genuinely the title).
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter
from typing import NamedTuple
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = Path(__file__).with_name("log_error_arg_order_baseline.txt")

# The roots the baseline covers. CI scans exactly these; the pre-commit hook
# scans only the files you touched, so its `exclude` must stay a SUBSET of
# this -- a file the hook scans but the baseline does not cover fails
# spuriously on its first edit.
SCAN_ROOTS = ("verenigingen", "scripts")

VALID_REASONS = {"false-positive", "intentional"}
_MARKER = re.compile(r"#\s*log-error-args-ok\s*:\s*([a-z-]+)?")


def _is_message_shaped(node: ast.AST) -> bool:
    """First-argument shapes named in #602: f-string, concatenation, str().

    ``str(...)`` is matched only as a bare call (``ast.Name``) -- an attribute
    call that merely happens to be spelled ``.str(...)`` on some other object
    (e.g. a builder's own `.str()` method) is not the stdlib coercion this is
    meant to catch, and treating it as one would be a pure false-positive risk
    with no compensating true positive: the shape this branch exists for is
    always the bare name.
    """
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return True
    if isinstance(node, ast.Call):
        return isinstance(node.func, ast.Name) and node.func.id == "str"
    return False


def _is_title_shaped(node: ast.AST) -> bool:
    """Second-argument shape: a plain string literal."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_log_error_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr == "log_error"
    if isinstance(f, ast.Name):
        return f.id == "log_error"
    return False


def _is_unambiguously_frappes(node: ast.Call) -> bool:
    """True only for `frappe.log_error(...)` or a bare `log_error(...)` name.

    Frappe's own signature is ``(title, message, reference_doctype,
    reference_name)``, so a THIRD or fourth positional argument is still
    plausibly a swap -- but this repo also has same-named LOCAL methods with a
    totally different, legitimate 3-argument shape: ``log_error(message,
    record_type, record_data)`` on several classes (``self.log_error``,
    ``PaymentLogger.log_error``, ``error_handler.log_error``...). Measured
    tree-wide: 15 calls to something named `log_error` take 3+ positional
    args, and exactly ONE of them is `frappe.log_error` itself
    (`sepa_memory_optimizer.py`) -- the other 14 are that local convention,
    and 3 of those 14 have the identical (f-string, literal) argument shape
    this validator looks for. Widening the 3+-arg case to any receiver would
    have reported those 3 as false positives. Restricting it to a receiver
    that unambiguously names frappe's own function catches the real site
    without them.
    """
    f = node.func
    if isinstance(f, ast.Name):
        return f.id == "log_error"
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "log_error"
        and isinstance(f.value, ast.Name)
        and f.value.id == "frappe"
    )


def _is_swapped(node: ast.Call) -> bool:
    if node.keywords or len(node.args) < 2:
        return False
    if not (_is_message_shaped(node.args[0]) and _is_title_shaped(node.args[1])):
        return False
    if len(node.args) == 2:
        return True
    # A 3rd+ positional argument: only trust the shape when the receiver is
    # unambiguously frappe's own log_error -- see _is_unambiguously_frappes.
    return _is_unambiguously_frappes(node)


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
    # Calls at module level (outside any function) are attributed to the
    # module itself so they are not silently invisible to the scan.
    yield "<module>", tree


def _own_calls(fn: ast.AST):
    """Calls textually inside `fn`, excluding nested function/class bodies.

    Works on any node carrying a `.body` -- a function, OR the module itself
    (`ast.Module`), which is what lets `scan_file` treat the `<module>`
    pseudo-scope from `_qualnames` uniformly with every real function: no
    double-counting guard needed, because this never revisits a call that
    belongs to a nested def/class in the first place. An earlier version
    instead re-walked the WHOLE tree for `<module>` and de-duplicated against
    calls already attributed to a real function -- correct only because
    `_qualnames` happened to yield `<module>` LAST, an invariant nothing
    enforced. This version has no such ordering dependency.

    A call sitting directly in a class body (not inside any method) is
    invisible to this walk, same as before: `_qualnames` never yields a class
    itself as a scope, and stopping at `ast.ClassDef` here is what keeps a
    method's calls from being counted twice once under the method and again
    under `<module>`. That combination is a real, known gap -- log_error
    is not called from a bare class-body statement anywhere in this repo
    today -- rather than a silent one.
    """
    stack = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _suppressed(node: ast.Call, lines: list[str]) -> tuple[bool, str | None]:
    """Look for a `# log-error-args-ok:` marker on the call's line(s).

    A raw text search over the call's own lines, matching the identical
    convention (and identical limits) of `error_swallow_validator._suppressed`
    / `failed_write_validator._suppressed`: a marker spelled inside a STRING
    literal on the same line would also suppress, and a trailing marker on a
    line holding two calls (`a(); b()`) suppresses both. Neither has been
    observed in this tree; tokenizing to tell a comment from a string literal
    is the fix if it ever is.
    """
    start = node.lineno
    end = node.end_lineno or node.lineno
    for ln in range(start, end + 1):
        if 1 <= ln <= len(lines):
            m = _MARKER.search(lines[ln - 1])
            if m:
                reason = m.group(1)
                return True, (None if reason in VALID_REASONS else (reason or "<missing>"))
    return False, None


def _iter_matches(tree: ast.AST):
    """Yield (qualname, node) for every swap-shaped log_error call in `tree`,
    regardless of any suppression marker -- shared by `scan_file` (which then
    applies suppression) and `scan_file_all` (which does not, for
    `explain_shrink` below)."""
    for qualname, fn in _qualnames(tree):
        for node in _own_calls(fn):
            if _is_log_error_call(node) and _is_swapped(node):
                yield qualname, node


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

    for qualname, node in _iter_matches(tree):
        ok, bad_reason = _suppressed(node, lines)
        if ok:
            if bad_reason:
                bad_pragmas.append((node.lineno, bad_reason))
            continue
        findings.append((qualname, node.lineno))

    return findings, bad_pragmas


def scan_file_all(path: Path) -> list[tuple[str, int]]:
    """Every swap-shaped call in `path`, INCLUDING pragma-suppressed ones.

    Used only by `explain_shrink`: an ordinary `scan_file()` cannot tell "this
    was genuinely fixed" from "a `# log-error-args-ok:` pragma was added on a
    call that still matches the swap shape" -- it already excludes suppressed
    sites, so a pragma on a previously-baselined site makes the baseline
    shrink exactly like a real fix does.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []
    return [(qualname, node.lineno) for qualname, node in _iter_matches(tree)]


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_py(paths: list[str]):
    """Yield the .py files under `paths`, each PHYSICAL file exactly once.

    A symlinked module and its target are two `os.walk` entries but one file,
    and `_rel` keys findings by `path.resolve()` -- so both visits would land
    on the same baseline key and double its count. Same dedupe, same reason,
    as `error_swallow_validator._iter_py` / `failed_write_validator._iter_py`.
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
    """Map 'path::qualname' -> number of swapped-call sites; plus bad-pragma messages."""
    counts: Counter = Counter()
    problems: list[str] = []
    for path in _iter_py(paths):
        rel = _rel(path)
        # Tests may legitimately construct a swapped call to probe the defect itself.
        if "/tests/" in "/" + rel or path.name.startswith("test_"):
            continue
        findings, bad = scan_file(path)
        for qualname, _lineno in findings:
            counts[f"{rel}::{qualname}"] += 1
        for lineno, reason in bad:
            problems.append(
                f"{rel}:{lineno}: invalid `log-error-args-ok` reason {reason!r}; "
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
    """The ratchet comparison itself: which counted sites exceed the baseline.

    Pulled out of `main()` so a test can exercise the actual comparison `main`
    runs, rather than a second copy of the same one-line dict comprehension
    that would pass even if this function's `>` silently became `>=`.
    """
    return {k: v for k, v in counts.items() if v > baseline.get(k, 0)}


def write_baseline(path: Path, counts: Counter) -> None:
    header = [
        "# Known swapped log_error(message, title) sites -- the ratchet baseline",
        "# for scripts/validation/log_error_arg_order_validator.py. Format:",
        "#     <path>::<qualified function>::<number of swapped sites>",
        "#",
        "# frappe.log_error is (title, message) -- calling it the other way round",
        "# truncates the real cause into a 140-char title and NEVER records the",
        "# stack (#602). A commit fails only if it introduces a site not covered",
        "# here, or raises the count for a function already listed.",
        "#",
        "# This file should only ever SHRINK. Do not regenerate it to make a new",
        "# finding go away; either fix the call (prefer explicit keyword arguments",
        "# -- log_error(title=..., message=...) -- so it cannot be re-inverted) or",
        "# mark it `# log-error-args-ok: <reason>`. The one legitimate reason it",
        "# may GROW is a change to the validator's own detection rules, which must",
        "# land in the same commit as the regeneration.",
        "",
    ]
    body = [f"{k}::{v}" for k, v in sorted(counts.items())]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


class UnexplainedShrink(NamedTuple):
    """A baseline entry that left without the swap actually being fixed."""

    key: str
    lineno: int
    reason: str


def explain_shrink(baseline: dict[str, int], paths: list[str]) -> list[UnexplainedShrink]:
    """Baseline entries whose count DROPPED without the swap being fixed.

    A shrink is the one direction this ratchet would otherwise accept without
    question -- and the remedy `--update-baseline` prints for an out-of-sync
    baseline produces a REMOVED line either way, so nothing in a plain diff
    tells a real fix apart from one of these:

    ``suppressed``
        a `# log-error-args-ok:` pragma was added on a call that still
        matches the swap shape structurally. `_counts` (and so the ordinary
        ratchet) excludes a suppressed site entirely, so pragma-ing an
        EXISTING baselined site shrinks the baseline exactly like fixing it
        would -- the growth check only catches a NEW site being hidden, not
        an old one.
    ``unscanned``
        the call is still there, unsuppressed, but the file no longer falls
        under `SCAN_ROOTS` (or `_iter_py`'s exclusions) -- the code never
        changed, only what gets scanned did.

    A genuine fix -- converted to keyword arguments, or the shape no longer
    matches (e.g. the title stopped being a plain literal) -- leaves no trace
    in `scan_file_all` either and is correctly not reported here.
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
            continue  # file deleted or unparseable: that explains itself
        lines = source.splitlines()
        still_matching = {qn: [] for qn in dict(by_path[rel])}
        for qualname, node in _iter_matches(tree):
            if qualname in still_matching:
                still_matching[qualname].append(node)

        for qualname, missing in sorted(by_path[rel]):
            for node in sorted(still_matching[qualname], key=lambda n: n.lineno)[:missing]:
                ok, _bad = _suppressed(node, lines)
                reason = "suppressed" if ok else "unscanned"
                out.append(UnexplainedShrink(f"{rel}::{qualname}", node.lineno, reason))
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
        help="report baseline entries that LEFT without the swap being fixed",
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
            "suppressed": "a `# log-error-args-ok:` pragma was added -- the call still matches the swap shape",
            "unscanned": "the file left SCAN_ROOTS; the call itself never changed",
        }
        print("\n\U0001f6d1 Baseline entries that LEFT without the swap being fixed\n")
        for u in unexplained:
            print(f"  {u.key}  (line {u.lineno})  [{u.reason}] -> {why[u.reason]}")
        print(
            "\n  Each call above still matches the swap shape (message-shaped first argument,\n"
            "  literal-title second) but no longer counts against the baseline. If the\n"
            "  pragma is deliberate, that's fine -- but it should be a conscious choice made\n"
            "  in the PR that added it, not an accidental way to make the ratchet shrink.\n"
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
    new = new_findings(counts, baseline)

    if not new and not problems:
        return 0

    print("\n\U0001f504 log_error(message, title) called backwards\n")
    for msg in problems:
        print(f"  {msg}")
    for key, count in sorted(new.items()):
        known = baseline.get(key, 0)
        path, _, qualname = key.partition("::")
        extra = count - known
        where = f"{path}  {qualname}()"
        print(f"  {where}\n      {extra} new swapped log_error call(s) (known: {known})")
    print(
        "\n  frappe.log_error is (title, message) -- frappe/utils/error.py:44. Calling it\n"
        "  the other way round truncates the real cause into a 140-char title and NEVER\n"
        "  records the traceback, because the swap-detection heuristic only fires when\n"
        "  the (wrongly positioned) title argument contains a newline. If this call is\n"
        "  frappe.log_error (or a bare log_error re-exporting it), fix by naming the\n"
        "  arguments explicitly:\n"
        "      frappe.log_error(title=\"Short Label\", message=f\"...\")\n"
        "  This is matched by NAME ONLY -- a same-named local helper with a DIFFERENT\n"
        "  signature (e.g. this repo's own log_error(error, context=None, module=None)\n"
        "  in verenigingen/utils/error_handling.py) can also match this shape. Use that\n"
        "  function's own correct argument order in that case, not title=/message=.\n"
        "  If this really is not a swap, mark it:\n"
        "      frappe.log_error(f\"...\", \"Label\")  # log-error-args-ok: false-positive\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
