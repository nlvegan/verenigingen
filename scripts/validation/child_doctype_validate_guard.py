#!/usr/bin/env python3
"""Hard gate: a controller for an `"istable": 1` DocType must not define `validate()`.

Frappe never runs a child DocType's `validate()`. `Document.run_before_save_methods`
(`frappe/model/document.py`) calls `self.run_method("validate")` on the **parent
only**; `Document._validate()` iterates children calling framework helpers
exclusively (`_validate_data_fields`, `_validate_selects`, `_validate_non_negative`,
...) -- there is no `d.run_method("validate")` anywhere in that path, for either
`insert()` or `save()`. Measured on `test_site_1`: spying `MemberSEPAMandateLink
.validate` across two `Member.save()` calls that each appended a new child row
counted 0 invocations, with the parent's own `validate()` (the control, in the same
run) firing once per save -- see #596.

A `def validate` on a child controller is therefore dead code. It is either
harmless (the rule it states is enforced elsewhere) or a SILENT GAP -- the only
statement of a rule that consequently never runs. #596 found 15 of these; one, on
`Member SEPA Mandate Link`, was the documented mechanism behind another DocType's
behaviour and the fix for #584 had to work around its absence.

This is a HARD GATE, not a ratchet: #596 emptied the census to zero by moving each
real rule into its parent's `validate()` (iterating the child table there) and
deleting the rest, so any new hit is a fresh instance of the same class of bug, not
inherited debt. There is nothing to grandfather in.

A deliberate exception -- a child controller intentionally invoked directly, never
through `parent.save()` -- is exempted by putting a `# child-validate-ok: <reason>`
comment on the `def validate` line itself.

Usage:
    python scripts/validation/child_doctype_validate_guard.py             # whole tree
    python scripts/validation/child_doctype_validate_guard.py <files...>  # pre-commit
"""

import argparse
import ast
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ["verenigingen"]
EXCLUDE_DIR_NAMES = {
    "node_modules",
    ".git",
    "__pycache__",
    "worktrees",
    ".claude",
    "archived",
    "archived_unused",
    "archived_deleted",
    "archived_removal",
}
EXEMPT_MARKER = "child-validate-ok:"


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _iter_doctype_py(paths: list[str]):
    """Yield each PHYSICAL `.py` file under a `doctype/<name>/` directory in `paths`,
    exactly once.

    Deduping by `path.resolve()` avoids the trap a sibling validator (error_swallow)
    was bitten by (#588): a symlinked module and its target are two `os.walk`
    entries for one file, which would double the finding under two different
    reported paths, or -- for a ratchet keyed by count -- silently mask a second
    real occurrence. This gate has no ratchet/count semantics (it fails on any
    finding), but reporting the same physical file twice under two names would
    still be a wrong, confusing report.
    """
    candidates: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
                posix_dir = Path(dirpath).as_posix() + "/"
                if "/doctype/" not in posix_dir:
                    continue
                candidates.extend(Path(dirpath) / fn for fn in filenames if fn.endswith(".py"))
        elif p.suffix == ".py" and p.exists():
            if "/doctype/" in p.resolve().as_posix():
                candidates.append(p)

    seen: set[Path] = set()
    for path in sorted(candidates, key=lambda q: (q.is_symlink(), str(q))):
        target = path.resolve()
        if target in seen:
            continue
        seen.add(target)
        yield path


def _sibling_json(py_path: Path) -> Path | None:
    json_path = py_path.with_suffix(".json")
    return json_path if json_path.exists() else None


def is_child_doctype_json(json_path: Path) -> bool:
    """True if `json_path` is a DocType definition with `"istable": 1`."""
    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return data.get("doctype") == "DocType" and data.get("istable") == 1


def find_validate_defs(py_path: Path) -> list[tuple[int, bool]]:
    """Return `(lineno, exempt)` for each `def validate(self, ...)` directly in a
    class body of `py_path` (nested functions, e.g. a local helper named
    `validate` inside some other method, do not count -- only a real controller
    method does)."""
    try:
        source = py_path.read_text()
        tree = ast.parse(source, filename=str(py_path))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []
    lines = source.splitlines()
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != "validate":
                continue
            args = item.args.args
            if not args or args[0].arg != "self":
                continue
            line = lines[item.lineno - 1] if 0 <= item.lineno - 1 < len(lines) else ""
            hits.append((item.lineno, EXEMPT_MARKER in line))
    return hits


def census(paths: list[str]) -> list[tuple[str, int]]:
    """[(relpath, lineno), ...] for every non-exempt `def validate` on an
    `istable: 1` controller under `paths`."""
    findings = []
    for py_path in _iter_doctype_py(paths):
        json_path = _sibling_json(py_path)
        if not json_path or not is_child_doctype_json(json_path):
            continue
        for lineno, exempt in find_validate_defs(py_path):
            if exempt:
                continue
            findings.append((_rel(py_path), lineno))
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="*", help="Specific files to check (pre-commit passes the touched files)"
    )
    args = parser.parse_args(argv)

    if args.files:
        paths = [f for f in args.files if "/doctype/" in Path(f).as_posix()]
        if not paths:
            return 0
    else:
        paths = SCAN_ROOTS

    findings = census(paths)
    if findings:
        print(
            "Child DocType Validate Guard: def validate() on an \"istable\": 1 controller "
            "is DEAD CODE."
        )
        print(
            "Frappe never calls it (see #596) -- there is no d.run_method(\"validate\") for "
            "children anywhere in insert()/save(). Move the rule into the PARENT's validate(), "
            "iterating the child table there, or delete it if the rule is already enforced "
            "elsewhere."
        )
        print(
            f'Deliberate exception: `def validate(self):  # {EXEMPT_MARKER} <reason>`\n'
        )
        for rel, lineno in findings:
            print(f"  {rel}:{lineno}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
