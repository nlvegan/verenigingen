#!/usr/bin/env python3
r"""
Unknown-DocType-Name Guard (ratchet)
====================================

Blocks a NEW string literal being passed as a DocType name to a framework call
when no DocType by that name exists anywhere on the bench.

Why this exists
---------------

A doctype name is a string, and **every framework call that takes one answers
"no" rather than "that is not a doctype"**. That is the whole bug class behind
#491 and #677, and the reason both survived for months in production code.

Measured on ``test_site_5`` (not read from the source -- the issue that reported
#677 predicted two of these wrong)::

    frappe.db.exists("Verenigingen Chapter", {...})        -> None
    frappe.db.exists("Verenigingen Chapter", "x")          -> None
    frappe.db.get_value("Verenigingen Chapter", "x", "y")  -> ProgrammingError 1146
    frappe.db.set_value("Verenigingen Volunteer", ...)     -> ProgrammingError 1146
    frappe.db.count("Verenigingen Chapter")                -> ProgrammingError 1146
    frappe.get_all("Verenigingen Chapter")                 -> DoesNotExistError
    frappe.new_doc("Verenigingen Chapter")                 -> ImportError

So the failure mode is not one thing. ``frappe.db.exists`` goes through
``frappe.db.sql(..., ignore=True)``, which swallows the missing-table 1146 and
returns ``None`` -- indistinguishable from "no such row", which is how a
permission gate in the *Chapter Members* report answered "not a board member"
for every user for nine months. The others raise, which is louder but lands in
a broad ``except`` often enough (#677 found one under ``except Exception: pass``
and one under a handler that returned ``{"success": False}`` after leaving an
orphan Employee behind).

What is checked
---------------

Every **string literal** in a doctype-name position of a call this file knows
about (``frappe.get_doc``, ``get_all``, ``db.exists``, ``db.get_value``,
``new_doc``, ... plus ``{"doctype": "X"}`` dict literals and this app's own
cleanup registries), resolved against the name of every DocType JSON in every
app on the bench. Non-literals are ignored: a variable's value is not knowable
here, and guessing is how a validator starts lying.

The authority, and its error bars
---------------------------------

The authority is the **DocType JSONs in the tree**, not ``tabDocType`` on a
site, so this runs in CI with no database. Cross-checked once, on 2026-08-31
against ``test_site_5``:

===============================================  =====
DocType JSONs across the bench                    1134
rows in ``tabDocType``                            1139
in ``tabDocType`` but in no JSON                     6   all ``custom=1``, created in the UI
in a JSON but not in ``tabDocType``                  1   ``Bank Integration Settings`` (unmigrated)
===============================================  =====

So the JSON authority can produce a false positive only for a site-local custom
DocType that app code names in a literal -- none of the 6 is named anywhere in
this tree. It can produce a false *negative* for a doctype whose app is not
installed on a given site; that is deliberate. "Correct but conditionally
installed" is not this bug, and the code that does it guards with
``frappe.db.exists("DocType", X)`` -- which this file treats as a probe, exempts,
and also exempts other calls on the same name in the same file.

Ratchet, not a gate
-------------------

The tree had unknown-name sites already when this was written. Failing on all of
them would just get the gate turned off, so they are baselined in
``doctype_name_baseline.txt`` and only an INCREASE fails. The baseline is keyed
``path::doctype::count`` -- deliberately not line numbers, which rot on any edit
above them.

**The count is not written here on purpose.** An earlier draft of this docstring
said "89 sites, 33 names" and was stale within the same branch that added it,
while the baseline, the hook description and the ratchet test all said something
else. Run it instead::

    python scripts/validation/doctype_name_validator.py --stats

A deliberate use -- a negative test that *wants* an unknown doctype -- is marked
inline with ``# doctype-ok: <reason>``.

What this cannot see
--------------------

Say this out loud rather than letting a green run be over-trusted. The scan is
literal-and-call-shaped, so these carry the same bug invisibly:

* **Tuple / list elements.** ``[("Verenigingen Volunteer", "volunteer_name"), ...]``
  fed to a loop that calls ``validate_field(doctype, field)`` -- the call's
  arguments are variables by then. This shape was live in
  ``tests/fixtures/test_secure_factory.py`` and had to be found by reading.
* **Filter *values*.** ``{"attached_to_doctype": "Volunteer Expense"}`` names a
  doctype in a position this does not model.
* **Raw SQL.** ``SELECT ... FROM `tabVerenigingen Volunteer` `` is a string.
  ``patches/v2_2/drop_orphan_volunteer_doctype_rows.py`` does this deliberately.
* **Prose.** Docstrings, ``docs/*.md`` and migration guides are where the next
  copy-paste comes from; four of them carried these names.
* **Non-literals**, by design -- a variable's value is not knowable statically,
  and guessing is how a gate starts lying.

The probe exemption is also file-wide, not scope-aware: one
``frappe.db.exists("DocType", X)`` anywhere in a file exempts *every* mention of
X in it. That is deliberate -- ``api/chapter_dashboard_api.py:511`` probes once
and then uses the name several times below -- but it does mean an unguarded use
in a file that happens to probe elsewhere is not reported.

Usage
-----
    python scripts/validation/doctype_name_validator.py                # whole tree vs baseline
    python scripts/validation/doctype_name_validator.py FILE...        # pre-commit mode
    python scripts/validation/doctype_name_validator.py --report       # human-readable census
    python scripts/validation/doctype_name_validator.py --stats
    python scripts/validation/doctype_name_validator.py --self-check   # the control
    python scripts/validation/doctype_name_validator.py --update-baseline

Exit codes
----------
    0  no unknown doctype name beyond what the baseline records
    1  a new unknown doctype name (or a new occurrence in a baselined file)
    2  usage / IO error, or --self-check failed
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_bench_apps(start: Path = REPO_ROOT) -> Path:
    """The bench's ``apps/`` directory.

    Not ``REPO_ROOT.parent``: this app is routinely checked out into a git
    worktree under ``.claude/worktrees/``, where that is a directory containing
    one app. The authority would then be this app alone and every frappe /
    erpnext / hrms doctype would read as unknown -- a validator that fires on
    ``frappe.get_doc("User", ...)``. Walk up to the bench instead, and let
    ``self_check`` prove a core-framework doctype was actually loaded.
    """
    for candidate in [start, *start.parents]:
        if (candidate / "apps").is_dir() and (candidate / "sites").is_dir():
            return candidate / "apps"
    return start.parent


BENCH_APPS = _find_bench_apps()
DEFAULT_BASELINE = Path(__file__).with_name("doctype_name_baseline.txt")

# The roots the baseline covers. The pre-commit hook sees only the files you
# touched, so its `exclude` must stay a SUBSET of this: a file the hook scans
# but the baseline does not cover fails spuriously on its first edit.
SCAN_ROOTS = ("verenigingen", "scripts")

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".pytest_cache", "sites", "env",
    "archived_unused", "archived_deleted", "archived_removal", "archived",
}

# Frappe APIs whose FIRST positional argument is a doctype name.
DOCTYPE_ARG0 = {
    "frappe.get_doc", "frappe.get_all", "frappe.get_list", "frappe.new_doc",
    "frappe.get_value", "frappe.get_cached_doc", "frappe.get_cached_value",
    "frappe.get_last_doc", "frappe.get_single", "frappe.get_single_value",
    "frappe.get_meta", "frappe.delete_doc", "frappe.rename_doc",
    "frappe.db.exists", "frappe.db.get_value", "frappe.db.set_value",
    "frappe.db.get_values", "frappe.db.get_all", "frappe.db.get_list",
    "frappe.db.count", "frappe.db.delete", "frappe.db.get_single_value",
    "frappe.db.get_cached_value", "frappe.client.get_list",
}

# APIs where `("DocType", X)` makes X the doctype being asked about. This is the
# feature-probe shape -- `if frappe.db.exists("DocType", "Volunteer Expense")` --
# and asking whether something exists is never the bug.
META_ARG1 = {
    "frappe.db.exists", "frappe.db.get_value", "frappe.get_value",
    "frappe.db.set_value", "frappe.get_cached_value", "frappe.db.get_cached_value",
    "frappe.db.count",
}

# This app's own registries that take a doctype name first. These are exactly
# where #491 lived, and no frappe-shaped grep would have found them.
APP_ARG0_SUFFIXES = (
    ".register", ".track_doc", ".track_document", "._track_test_document",
    ".add_cleanup_record",
    # This app's own schema validator. `validate_field("Verenigingen Volunteer",
    # "volunteer_name")` raises FieldValidationError, which the caller swallows
    # into {"success": False} -- a whitelisted endpoint that has never passed.
    ".validate_field", ".validate_field_exists", ".validate_link_field_value",
)

# hooks.py mappings whose DICT KEYS are doctype names. A wrong key is not an
# error anywhere -- `frappe.get_doc_hooks()` simply never looks it up -- so four
# `on_update` handlers sat registered and dead under "Verenigingen Volunteer",
# while `Volunteer` had no entry at all. Measured on test_site_5:
#     'Verenigingen Volunteer' in get_hooks("doc_events")  -> True
#     'Volunteer'              in get_hooks("doc_events")  -> False
#     get_doc_hooks()['Volunteer']                         -> None
HOOK_DICTS_KEYED_BY_DOCTYPE = {
    "doc_events", "permission_query_conditions", "has_permission",
    "has_website_permission", "override_doctype_class",
    "override_doctype_dashboards", "doctype_js", "doctype_list_js",
    "doctype_tree_js", "doctype_calendar_js",
}

# frappe's own wildcard key in doc_events: "every doctype", not a doctype name.
HOOK_WILDCARD_KEYS = {"*"}

# Physical tables that are not DocTypes. `frappe.db.delete` on these is correct.
RAW_TABLES = {"__Auth", "Singles", "Series", "__global_search", "__UserSettings"}

SUPPRESS = "doctype-ok:"


# --------------------------------------------------------------------------
# the authority


def known_doctypes(bench_apps: Path = BENCH_APPS) -> dict[str, str]:
    """Every DocType name defined by a JSON in any app on the bench -> its app."""
    known: dict[str, str] = {}
    for app_dir in sorted(bench_apps.iterdir()):
        if not (app_dir / "pyproject.toml").exists():
            continue
        for json_file in app_dir.rglob("**/doctype/*/*.json"):
            if SKIP_DIRS & set(json_file.parts):
                continue
            if json_file.name != json_file.parent.name + ".json":
                continue
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("doctype") == "DocType" and data.get("name"):
                known.setdefault(data["name"], app_dir.name)
    return known


# --------------------------------------------------------------------------
# the scan


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _Finding:
    __slots__ = ("lineno", "api", "name", "kind")

    def __init__(self, lineno, api, name, kind):
        self.lineno, self.api, self.name, self.kind = lineno, api, name, kind


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.found: list[_Finding] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        """`doc_events = {"Some DocType": {...}}` -- the KEYS are doctype names."""
        for target in node.targets:
            name = target.id if isinstance(target, ast.Name) else None
            if name in HOOK_DICTS_KEYED_BY_DOCTYPE and isinstance(node.value, ast.Dict):
                for key in node.value.keys:
                    literal = _literal(key)
                    if literal is not None and literal not in HOOK_WILDCARD_KEYS:
                        self.found.append(_Finding(key.lineno, name + "[X]", literal, "call"))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        api = _dotted(node.func)
        if api:
            if api in META_ARG1 and len(node.args) > 1 and _literal(node.args[0]) == "DocType":
                probed = _literal(node.args[1])
                if probed is not None:
                    self.found.append(_Finding(node.lineno, api, probed, "probe"))
            elif api in DOCTYPE_ARG0 and node.args:
                first = _literal(node.args[0])
                if first is not None:
                    self.found.append(_Finding(node.lineno, api, first, "call"))
            elif api.endswith(APP_ARG0_SUFFIXES) and node.args:
                first = _literal(node.args[0])
                if first is not None:
                    self.found.append(_Finding(node.lineno, api, first, "call"))
            if api.startswith("frappe"):
                for kw in node.keywords:
                    if kw.arg == "doctype":
                        value = _literal(kw.value)
                        if value is not None:
                            self.found.append(_Finding(node.lineno, api + "(doctype=)", value, "call"))
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, ast.Dict):
                for key, value in zip(arg.keys, arg.values):
                    if _literal(key) == "doctype":
                        literal = _literal(value)
                        if literal is not None:
                            self.found.append(
                                _Finding(node.lineno, (api or "?") + "({'doctype': X})", literal, "call")
                            )
        self.generic_visit(node)


def scan_source(source: str) -> list[_Finding]:
    visitor = _Visitor()
    # A few files in the tree contain invalid string escapes, which ast.parse
    # re-emits as a SyntaxWarning attributed to "<unknown>". That is noise from
    # somebody else's file on every run of this gate, so drop it.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    visitor.visit(tree)
    return visitor.found


def unknown_in_file(path: Path, known: dict[str, str]) -> list[_Finding]:
    """Unknown-doctype findings in one file, probes and probe-guarded names removed."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        found = scan_source(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    probed = {f.name for f in found if f.kind == "probe"}
    out = []
    for finding in found:
        if finding.kind == "probe" or finding.name in known or finding.name in RAW_TABLES:
            continue
        if finding.name in probed:
            continue
        line = lines[finding.lineno - 1] if 0 < finding.lineno <= len(lines) else ""
        if SUPPRESS in line:
            continue
        out.append(finding)
    return out


def iter_python_files(paths) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_file():
            if path.suffix == ".py" and not (SKIP_DIRS & set(path.parts)):
                files.append(path)
            continue
        for candidate in path.rglob("*.py"):
            if SKIP_DIRS & set(candidate.parts):
                continue
            files.append(candidate)
    return sorted(set(files))


def census(paths) -> tuple[Counter, dict[str, list[_Finding]]]:
    """(Counter of `path::doctype` -> count, detail keyed by the same)."""
    known = known_doctypes()
    counts: Counter = Counter()
    detail: dict[str, list[_Finding]] = defaultdict(list)
    for path in iter_python_files(paths):
        for finding in unknown_in_file(path, known):
            try:
                rel = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel = path.as_posix()
            key = f"{rel}::{finding.name}"
            counts[key] += 1
            detail[key].append(finding)
    return counts, detail


# --------------------------------------------------------------------------
# baseline


def load_baseline(path: Path) -> dict[str, int]:
    baseline: dict[str, int] = {}
    if not path.exists():
        return baseline
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, count = line.rpartition("::")
        if key:
            baseline[key] = int(count)
    return baseline


def write_baseline(path: Path, counts: Counter) -> None:
    header = [
        "# Known unknown-DocType-name call sites -- the ratchet baseline for",
        "# scripts/validation/doctype_name_validator.py. Regenerate with",
        "# --update-baseline. Keyed path::doctype::count; line numbers are",
        "# deliberately absent because they rot on any edit above them.",
        "#",
        "# Every entry is a string in a doctype-name position naming something that is",
        "# not a DocType in any app on this bench. Most are aspirational doctypes in",
        "# tests. An entry LEAVING this file is progress and does not fail the gate;",
        "# a new one, or a new occurrence in a file already listed, does.",
        "#",
        "# A deliberate unknown name -- a negative test -- goes in the source as",
        "# `# doctype-ok: <reason>` and never reaches this file.",
    ]
    body = [f"{key}::{count}" for key, count in sorted(counts.items())]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# the control


SELF_CHECK_SOURCE = '''
import frappe

def f():
    frappe.db.exists("Member", {"name": "x"})                       # valid
    frappe.get_all("Chapter Board Member", filters={})              # valid
    frappe.db.exists("Verenigingen Chapter Board Member", {})       # INVALID (a Role)
    frappe.get_doc({"doctype": "Totally Not A DocType"})            # INVALID
    if frappe.db.exists("DocType", "Volunteer Expense"):            # probe, exempt
        frappe.db.count("Volunteer Expense")                        # guarded by the probe
    frappe.new_doc("Another Fake DocType")  # doctype-ok: negative test
    frappe.db.delete("__Auth", {})                                  # raw table, exempt
'''


def self_check() -> int:
    """A sweep that flags nothing, including its own control, is not a passing sweep."""
    known = known_doctypes()
    # "User" and "Sales Invoice" are the load-bearing ones: they come from OTHER
    # apps, so they fail if BENCH_APPS resolved to this checkout instead of the
    # bench -- the exact way a git worktree breaks the authority, and a failure
    # that would otherwise show up as the validator flagging frappe's own APIs.
    for required in ("Member", "Chapter Board Member", "Chapter", "Volunteer", "Team",
                     "User", "DocType", "Sales Invoice"):
        if required not in known:
            print(f"SELF-CHECK FAILED: the authority does not know {required!r} "
                  f"({len(known)} doctypes loaded from {BENCH_APPS}) -- "
                  f"BENCH_APPS did not resolve to the bench's apps/ directory.")
            return 2
    lines = SELF_CHECK_SOURCE.splitlines()
    flagged = set()
    for finding in scan_source(SELF_CHECK_SOURCE):
        if finding.kind == "probe" or finding.name in known or finding.name in RAW_TABLES:
            continue
        if SUPPRESS in lines[finding.lineno - 1]:
            continue
        flagged.add(finding.name)
    probed = {f.name for f in scan_source(SELF_CHECK_SOURCE) if f.kind == "probe"}
    flagged -= probed

    expected_flagged = {"Verenigingen Chapter Board Member", "Totally Not A DocType"}
    expected_clean = {
        "Member", "Chapter Board Member", "Volunteer Expense",
        "Another Fake DocType", "__Auth",
    }
    problems = []
    for name in sorted(expected_flagged - flagged):
        problems.append(f"  MISSED an invalid name: {name!r}")
    for name in sorted(flagged & expected_clean):
        problems.append(f"  FALSE POSITIVE on: {name!r}")
    if problems:
        print("SELF-CHECK FAILED -- the instrument does not separate valid from invalid:")
        print("\n".join(problems))
        return 2
    print(f"self-check OK: {len(known)} doctypes known; "
          f"flagged {sorted(expected_flagged)}; clean on {sorted(expected_clean)}")
    return 0


# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--report", action="store_true", help="human-readable census, exit 0")
    parser.add_argument("--stats", action="store_true", help="totals only, exit 0")
    parser.add_argument("--self-check", action="store_true", help="run the control, exit 0/2")
    args = parser.parse_args(argv[1:])

    if args.self_check:
        return self_check()

    if args.update_baseline:
        counts, _ = census(SCAN_ROOTS)
        write_baseline(args.baseline, counts)
        print(f"baseline written: {len(counts)} entries, {sum(counts.values())} sites")
        return 0

    if args.report or args.stats:
        counts, detail = census(args.paths or SCAN_ROOTS)
        by_name: dict[str, int] = Counter()
        for key, count in counts.items():
            by_name[key.split("::", 1)[1]] += count
        print(f"{sum(counts.values())} unknown-doctype sites across {len(by_name)} distinct names")
        if args.stats:
            return 0
        for name, total in sorted(by_name.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"\n--- {name!r} ({total})")
            for key in sorted(k for k in counts if k.split("::", 1)[1] == name):
                path = key.split("::", 1)[0]
                for finding in detail[key]:
                    print(f"    {path}:{finding.lineno}  {finding.api}")
        return 0

    counts, detail = census(args.paths or SCAN_ROOTS)
    baseline = load_baseline(args.baseline)
    problems = [(key, count) for key, count in sorted(counts.items()) if count > baseline.get(key, 0)]
    if not problems:
        return 0

    print("\n\U0001f6d1 DocType name that is not a DocType\n")
    for key, count in problems:
        path, _, name = key.partition("::")
        was = baseline.get(key, 0)
        for finding in detail[key]:
            print(f"  {path}:{finding.lineno}  {finding.api}({name!r}, ...)")
        print(f"      -> {name!r} is not a DocType in any app on this bench "
              f"({was} known here, now {count})\n")
    print(
        "  Nothing raises a useful error for this. frappe.db.exists returns None (the same\n"
        "  answer as 'no such row'); the others raise 1146/DoesNotExistError somewhere a\n"
        "  broad `except` is usually waiting. A permission gate spelled this way denied\n"
        "  every chapter board member for nine months (#677).\n\n"
        "  Fix it, or -- if the unknown name is the point (a negative test, a doctype you\n"
        "  are about to create) -- mark the line `# doctype-ok: <reason>`.\n"
        "  Probing with `frappe.db.exists(\"DocType\", X)` first also exempts X in that file.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
