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

1. it takes exactly two POSITIONAL arguments and no keyword arguments -- a call
   already using ``title=``/``message=`` is self-documenting and cannot be
   silently re-inverted, so it is out of scope by construction;
2. the FIRST argument is "message-shaped": an f-string (``ast.JoinedStr``), a
   string concatenation (``ast.BinOp`` with ``ast.Add``), or a ``str(...)``
   call -- the three shapes named in #602's fix order; and
3. the SECOND argument is a plain string literal -- the shape of a short,
   hand-written title.

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
    """First-argument shapes named in #602: f-string, concatenation, str()."""
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return True
    if isinstance(node, ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        return name == "str"
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


def _is_swapped(node: ast.Call) -> bool:
    if node.keywords:
        return False
    if len(node.args) != 2:
        return False
    return _is_message_shaped(node.args[0]) and _is_title_shaped(node.args[1])


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

    For the `<module>` pseudo-scope this instead walks the WHOLE tree and the
    caller is responsible for not double-counting -- see `scan_file`.
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
    """Look for a `# log-error-args-ok:` marker on the call's line(s)."""
    start = node.lineno
    end = node.end_lineno or node.lineno
    for ln in range(start, end + 1):
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
    seen_calls: set[int] = set()

    for qualname, fn in _qualnames(tree):
        is_module = qualname == "<module>"
        calls = ast.walk(fn) if is_module else _own_calls(fn)
        for node in calls:
            if not isinstance(node, ast.Call) or id(node) in seen_calls:
                continue
            if not _is_log_error_call(node) or not _is_swapped(node):
                continue
            if not is_module:
                seen_calls.add(id(node))
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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=list(SCAN_ROOTS))
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--stats", action="store_true", help="print totals and exit 0")
    args = ap.parse_args(argv[1:])

    paths = args.paths or list(SCAN_ROOTS)

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
        "  the (wrongly positioned) title argument contains a newline. Fix by naming the\n"
        "  arguments explicitly:\n"
        "      frappe.log_error(title=\"Short Label\", message=f\"...\")\n"
        "  If this really is not a swap, mark it:\n"
        "      frappe.log_error(f\"...\", \"Label\")  # log-error-args-ok: false-positive\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
