#!/usr/bin/env python3
"""Hard gate: a literal `.append("<child_table>", {...})` dict that sets a Dynamic
Link field's value must also set that field's companion doctype field, in the same
literal.

## The mechanism (#667)

A child table row created via `parent.append(fieldname, {...})` and persisted
through anything that bypasses `Document._save()`'s normal validate flow --
`update_child_table()`, and this app's own `safe_child_table_update()` wrapper
around it -- skips `Document._set_defaults()`. That is the ONE place a DocField's
`"default"` gets copied onto a new child row (`update_if_missing()`); it runs
before `_validate_links()` on the ordinary `.save()`/`.insert()` path, which is why
some of these appends "work" today even without the field set explicitly. But
`update_child_table()` calls `d.db_update()` directly -- no defaults, no
`_validate_links()`, no controller hooks at all (`db_update_all`'s own docstring:
"DOES NOT VALIDATE AND CALL TRIGGERS") -- so a Dynamic Link's companion field left
unset is written as a literal SQL NULL, silently, with no exception of any kind.
Measured on `test_site_3`: `Member.update_child_table("sepa_mandates")` on a row
appended without `sepa_mandate_doctype` persisted `sepa_mandate_doctype = NULL` and
returned normally; the member was then unable to save at all -- the very next
ordinary `Member.save()` throws "SEPA Mandate DocType must be set first" from
`frappe/model/base_document.py`'s `_validate_links()`, pointing at a field nobody
touched in that call.

Whether the OTHER, `.save()`-routed appends of the same shape need the field set
explicitly depends on `_set_defaults()` actually running, which depends on the
field carrying a DocField-level `"default"` and on nothing upstream skipping that
step (`frappe.flags.in_import`, `ignore_validate`, ...) -- both are call-site
details a static check cannot see. Requiring it always, regardless of which
persistence path a given call site happens to use today, is the position this gate
takes: the two sites that already set it explicitly
(`verenigingen_payments/api/sepa_mandate_management.py`,
`verenigingen_payments/services/sepa_mandate_member_integration_service.py`) did
so before this gate existed, for exactly this reason.

## Scope, deliberately

Only a literal `ast.Dict` with **all string-literal keys** is checked. A `**spread`
key (`{"sepa_mandate": x, **link_values}`) or a non-dict argument
(`member.append("sepa_mandates", entry)`) makes it impossible to tell statically
whether the companion field is set inside the spread/variable, so those calls are
SKIPPED rather than guessed at -- a false negative, not a false positive. Only a
`fieldname` that maps to exactly ONE child DocType across the whole app is
checked; an ambiguous fieldname (used as a Table field by more than one parent
DocType, with different child DocTypes) is skipped for the same reason. Test code
(any path containing a `/tests/` segment, or a `test_*.py` / `*_test.py`
filename) is excluded: a test deliberately constructing a broken/incomplete row to
exercise error handling is not this bug.

A HARD GATE, not a ratchet: the census on this branch is zero after fixing #667's
four sites, so there is nothing to grandfather in. A new hit is a fresh instance
of the same class of bug.

Usage:
    python scripts/validation/dynamic_link_append_validator.py             # whole tree
    python scripts/validation/dynamic_link_append_validator.py <files...>  # pre-commit
"""

import argparse
import ast
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Absolute, not relative: a relative root resolves against the CALLER's cwd, not
# this file's location (see child_doctype_validate_guard.py's identical note).
SCAN_ROOT = REPO_ROOT / "verenigingen"
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


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _is_test_path(path: Path) -> bool:
    posix = path.as_posix()
    if "/tests/" in f"/{posix}/":
        return True
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def _iter_json(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        for fn in filenames:
            if fn.endswith(".json"):
                yield Path(dirpath) / fn


def _iter_py(paths: list[str]):
    """Yield each `.py` file under any directory in `paths`, or the file itself,
    excluding test code."""
    candidates: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
                candidates.extend(Path(dirpath) / fn for fn in filenames if fn.endswith(".py"))
        elif p.suffix == ".py" and p.exists():
            candidates.append(p)

    seen: set[Path] = set()
    for path in sorted(candidates, key=lambda q: (q.is_symlink(), str(q))):
        if _is_test_path(path):
            continue
        target = path.resolve()
        if target in seen:
            continue
        seen.add(target)
        yield path


def load_doctype_json(json_path: Path) -> dict | None:
    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("doctype") != "DocType":
        return None
    return data


def build_schema_maps(root: Path) -> tuple[dict[str, set[str]], dict[str, list[tuple[str, str]]]]:
    """Return (table_field -> {child doctype names}, doctype name -> [(dynlink
    field, companion field), ...]), scanned from every DocType JSON under `root`."""
    table_fields: dict[str, set[str]] = {}
    dynlink_fields: dict[str, list[tuple[str, str]]] = {}

    for json_path in _iter_json(root):
        data = load_doctype_json(json_path)
        if not data:
            continue
        doctype_name = data.get("name")
        fields = data.get("fields", [])
        if not isinstance(fields, list):
            continue

        for fl in fields:
            if not isinstance(fl, dict):
                continue
            fieldtype = fl.get("fieldtype")
            fieldname = fl.get("fieldname")
            if fieldtype in ("Table", "Table MultiSelect") and fl.get("options"):
                table_fields.setdefault(fieldname, set()).add(fl["options"])
            elif fieldtype == "Dynamic Link" and fieldname and fl.get("options") and doctype_name:
                dynlink_fields.setdefault(doctype_name, []).append((fieldname, fl["options"]))

    return table_fields, dynlink_fields


def _dict_literal_keys(node: ast.Dict) -> set[str] | None:
    """String keys of a literal dict with no `**spread` and no non-literal keys,
    or None if the dict cannot be read statically (spread, computed key, ...)."""
    keys = set()
    for key in node.keys:
        if key is None:  # a `**spread` entry
            return None
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.add(key.value)
    return keys


def find_offending_appends(
    py_path: Path,
    table_fields: dict[str, set[str]],
    dynlink_fields: dict[str, list[tuple[str, str]]],
) -> list[tuple[int, str, str, str]]:
    """[(lineno, child_doctype, dynlink_field, companion_field), ...] for each
    `.append("<table_field>", {...})` call in `py_path` that sets a Dynamic Link
    field's value without its companion doctype field, in the same literal dict."""
    try:
        source = py_path.read_text()
        tree = ast.parse(source, filename=str(py_path))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return []

    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "append":
            continue
        if len(node.args) < 2:
            continue

        field_arg, dict_arg = node.args[0], node.args[1]
        if not (isinstance(field_arg, ast.Constant) and isinstance(field_arg.value, str)):
            continue
        if not isinstance(dict_arg, ast.Dict):
            continue

        child_doctypes = table_fields.get(field_arg.value)
        if not child_doctypes or len(child_doctypes) != 1:
            continue  # unknown or ambiguous table fieldname
        (child_doctype,) = child_doctypes

        pairs = dynlink_fields.get(child_doctype)
        if not pairs:
            continue

        literal_keys = _dict_literal_keys(dict_arg)
        if literal_keys is None:
            continue  # spread or computed key: cannot verify statically

        for dynlink_field, companion_field in pairs:
            if dynlink_field in literal_keys and companion_field not in literal_keys:
                findings.append((node.lineno, child_doctype, dynlink_field, companion_field))

    return findings


def census(paths: list[str]) -> list[tuple[str, int, str, str, str]]:
    table_fields, dynlink_fields = build_schema_maps(SCAN_ROOT)
    findings = []
    for py_path in _iter_py(paths):
        for lineno, child_doctype, dynlink_field, companion_field in find_offending_appends(
            py_path, table_fields, dynlink_fields
        ):
            findings.append((_rel(py_path), lineno, child_doctype, dynlink_field, companion_field))
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="*", help="Specific files to check (pre-commit passes the touched files)"
    )
    args = parser.parse_args(argv)

    paths = [f for f in args.files if f.endswith(".py")] if args.files else [str(SCAN_ROOT)]
    if args.files and not paths:
        return 0

    findings = census(paths)
    if findings:
        print(
            "Dynamic Link Append Guard: a literal .append() dict sets a Dynamic Link "
            "field's value without its companion doctype field (see #667)."
        )
        print(
            "update_child_table() / safe_child_table_update() write this row with NO "
            "defaults and NO link validation at all -- the companion field is persisted "
            "as a silent NULL, and the parent becomes un-saveable on its next ordinary "
            "save(). Set the companion field explicitly in the same literal."
        )
        for rel, lineno, child_doctype, dynlink_field, companion_field in findings:
            print(
                f"  {rel}:{lineno}: {child_doctype} row sets '{dynlink_field}' "
                f"without '{companion_field}'"
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
