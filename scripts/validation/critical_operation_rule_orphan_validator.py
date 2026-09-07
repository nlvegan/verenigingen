#!/usr/bin/env python3
"""Block NEW orphaned ``Critical Operation Rule`` fixture entries.

THE BUG CLASS
-------------
``Critical Operation Rule.operation_name`` is autonamed ``field:operation_name``
(see ``verenigingen/verenigingen/doctype/critical_operation_rule/critical_operation_rule.json``)
and, at rate-limit-check time, is matched against the BARE function name of the
currently-executing endpoint::

    # verenigingen/utils/security/api_security_framework.py:964
    operation_key = f"{func.__module__}.{func.__name__}"
    framework.validate_rate_limits(profile, operation_key)

    # verenigingen/utils/security/rate_limit_engine.py:96
    operation_name = operation_key.split(".")[-1] if "." in operation_key else operation_key
    cor_record = self._get_cor_config(operation_name)   # exact match, else _generic_api_fallback

A fixture row whose ``operation_name`` no longer matches any ``def`` in the app
can only mean one of two things: the function it once named was renamed (in
which case the RENAMED function is now silently uncovered, falling through to
``_generic_api_fallback`` instead of whatever limit was actually chosen for
it), or the function was deleted outright (in which case the row is inert
dead weight -- see the precedent prune patches under ``verenigingen/patches/
v2_2/remove_*_critical_operation_rules.py``).

Issue #1033's triage (four fixture files, 2124 distinct ``operation_name``
rows) found: 1012 resolve directly, 249 are harmless variants of a resolving
sibling rule, and 797 are orphans in the sense above. Of those, a 65-row
subset had a plausibly-renamed live candidate; reading each by hand found
zero currently guest-exposed endpoints riding the shared-Guest fallback
bucket, but did find two real authenticated endpoints (``debug_payment``,
``export_all_financial_data``) with no rule at all under their current name.
See the PR body for the full breakdown -- this validator's job is only to
stop the population from growing further, not to re-litigate that census.

WHAT IS FLAGGED
----------------
Every distinct ``operation_name`` across the four COR fixture files
(``critical_operation_rule.json`` and its three sibling files -- see
``FIXTURE_FILES``) that is NOT ``_generic_api_fallback`` (the one hardcoded,
deliberately-nameless fallback key -- see ``ALLOWLIST``) and does not match
the bare name of any ``def``/``async def`` anywhere under ``SCAN_ROOTS``
(``verenigingen/`` and ``scripts/`` -- the latter is a real importable
package at the app root with its own whitelisted, security-decorated
endpoints; missing it mislabelled 122 live functions as orphans, see
``SCAN_ROOTS``'s own comment).

WHY A RATCHET, NOT A BIG-BANG FIX
-----------------------------------
797 pre-existing orphans (per the census above) is not a single-PR cleanup,
and most of them are inert dead weight rather than a live gap -- see the
`check_critical_operation_integration` docstring in api_security_framework.py:
"Absence of a per-operation Critical Operation Rule is the normal, expected
state ... keep this quiet so sparse rules stay sustainable." This validator
freezes the CURRENT population and blocks only a NEW orphan being added
(a fixture row for a function that does not exist, or a rename that leaves
the old row behind uncleaned), exactly like the sibling ratchets in this
directory (``log_error_arg_order_validator.py``, ``duplicate_helper_validator.py``, ...).

The baseline is keyed ``<fixture file>::<operation_name>::1`` -- always 1,
since ``operation_name`` is the doctype's own unique/autoname field (one row
per name, enforced by the doctype itself, not by this validator)::

    python scripts/validation/critical_operation_rule_orphan_validator.py --update-baseline

There is no per-line suppression pragma (these are JSON fixture rows, not
source lines a comment can sit beside): the one legitimate reason a orphan is
not a bug is ``_generic_api_fallback`` itself, already on ``ALLOWLIST``. Any
other deliberate case belongs in ``ALLOWLIST`` too, with a comment saying why.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = Path(__file__).with_name("critical_operation_rule_orphan_baseline.txt")

FIXTURE_FILES = (
    "critical_operation_rule.json",
    "critical_operation_rule_ponto_debug.json",
    "critical_operation_rule_balance_transactions.json",
    "critical_operation_rule_payment_recovery.json",
)

# _generic_api_fallback is the one COR row with no corresponding `def` by
# design -- rate_limit_engine._get_cor_config() falls back to it BY LITERAL
# NAME when no specific rule matches (see the module docstring). It is a
# deliberate sentinel, not a stale rename.
ALLOWLIST = {"_generic_api_fallback"}

# The roots that can define a function `frappe.get_attr`/an operation_key can
# ever name. `scripts/` is a real importable package at the app root (it has
# its own `__init__.py`, confirmed by `import scripts` resolving from
# <bench>/sites) holding whitelisted, security-framework-decorated endpoints
# of its own (`scripts.database.create_sepa_indexes.create_sepa_indexes_api`,
# `scripts.job_management.cancel_job`, ...) -- exactly the sibling ratchet's
# own SCAN_ROOTS (log_error_arg_order_validator.py). Scanning `verenigingen/`
# alone mislabelled 122 of these as orphans (11% of the baseline), several of
# them live FINANCIAL/ADMIN `critical_api` endpoints -- following this
# validator's own "prune the row" remediation on one of those would have
# DELETED a real rate limit and dropped a live endpoint onto the shared
# `_generic_api_fallback` bucket, reproducing #1033's bug via the fix meant
# to close it. Caught by a skeptical review before merge; see the PR.
SCAN_ROOTS = ("verenigingen", "scripts")

# Directories never worth scanning for `def`s: they hold no application code,
# only noise that would slow the walk down.
_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__"}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_operation_names(repo_root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """Map operation_name -> list of fixture files it appears in (normally one)."""
    names: dict[str, list[str]] = {}
    for fname in FIXTURE_FILES:
        path = repo_root / "verenigingen" / "fixtures" / fname
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        for row in rows:
            op = row.get("operation_name")
            if op:
                names.setdefault(op, []).append(fname)
    return names


def collect_def_names(root: Path) -> set[str]:
    """Every bare function/method name defined anywhere under `root`.

    Matching the rate-limit engine's own lookup: it keys off the bare
    ``func.__name__``, not a fully-qualified path, so this deliberately does
    the same -- a name collision between two unrelated functions is a false
    negative here (an orphan that happens to share a name elsewhere), which
    is the direction that avoids flagging a live rename as broken.
    """
    names: set[str] = set()
    for py in root.rglob("*.py"):
        if any(part in _SKIP_DIR_NAMES for part in py.parts):
            continue
        try:
            source = py.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py))
        except (OSError, SyntaxError, ValueError) as exc:
            # A file that fails to parse contributes NO defs -- silently
            # dropping this would manufacture false orphans for every real
            # function it contains. Zero files hit this today (confirmed by
            # a skeptical review), but a future encoding/syntax problem
            # should be visible, not absorbed into the orphan count.
            print(f"::warning file={py}::could not parse for def collection: {exc}", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    return names


def find_orphans(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Return {f"{fixture_file}::{operation_name}": operation_name} for every orphan."""
    operation_names = load_operation_names(repo_root)
    def_names: set[str] = set()
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if root.exists():
            def_names |= collect_def_names(root)

    orphans: dict[str, str] = {}
    for op, fixture_files in sorted(operation_names.items()):
        if op in ALLOWLIST or op in def_names:
            continue
        for fname in fixture_files:
            orphans[f"{fname}::{op}"] = op
    return orphans


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


def write_baseline(path: Path, orphans: dict[str, str]) -> None:
    header = [
        "# Known orphaned Critical Operation Rule fixture entries -- the ratchet",
        "# baseline for scripts/validation/critical_operation_rule_orphan_validator.py.",
        "# Format:",
        "#     <fixture file>::<operation_name>::1",
        "#",
        "# operation_name is matched against the BARE name of a currently-live `def`",
        "# (see rate_limit_engine.py:96) -- a row here has no matching function",
        "# anywhere in the app, meaning either the function it once guarded was",
        "# renamed (the RENAMED function is now silently uncovered, falling through",
        "# to _generic_api_fallback) or deleted outright (inert dead weight). See",
        "# issue #1033 for the full triage of the population this file freezes.",
        "#",
        "# This file should only ever SHRINK. Do not regenerate it to hide a NEW",
        "# orphan; either add/rename the matching Critical Operation Rule row, or",
        "# (if the function was deleted for good) prune the fixture row via a patch",
        "# like verenigingen/patches/v2_2/remove_workflow_demo_critical_operation_rules.py",
        "# -- Critical Operation Rule is excluded from the `fixtures` hook, so editing",
        "# the fixture file alone does not delete an already-installed row.",
        "",
    ]
    body = [f"{key}::1" for key in sorted(orphans)]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def new_findings(orphans: dict[str, str], baseline: dict[str, int]) -> dict[str, str]:
    """Keys present now that are not already accounted for in the baseline.

    Every orphan's count is always 1 (operation_name is the doctype's own
    unique/autoname field), so "new" here just means "not in the baseline at
    all" -- there is no >1 count to grow.
    """
    return {k: v for k, v in orphans.items() if k not in baseline}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--stats", action="store_true", help="print totals and exit 0")
    args = ap.parse_args(argv[1:])

    orphans = find_orphans()

    if args.stats:
        print(f"{len(orphans)} orphaned operation_name entries across {len(FIXTURE_FILES)} fixture files")
        return 0

    if args.update_baseline:
        write_baseline(args.baseline, orphans)
        print(f"baseline written: {len(orphans)} orphans")
        return 0

    baseline = load_baseline(args.baseline)
    new = new_findings(orphans, baseline)

    if not new:
        return 0

    print("\n\U0001f6d1 New orphaned Critical Operation Rule entries\n")
    for key in sorted(new):
        fixture_file, _, op = key.partition("::")
        print(f"  {fixture_file}  operation_name={op!r}")
    print(
        "\n  This operation_name does not match any `def`/`async def` anywhere under\n"
        "  verenigingen/, and is not on this validator's ALLOWLIST. If this is a fixture\n"
        "  row for a function that was just RENAMED, add a new row (or rename this one)\n"
        "  to match the function's new bare name -- otherwise it silently falls through\n"
        "  to _generic_api_fallback at rate-limit-check time (see rate_limit_engine.py).\n"
        "  If the function was deleted for good, prune the row via a patch (Critical\n"
        "  Operation Rule is excluded from the `fixtures` hook, so a bare fixture-file\n"
        "  edit alone does not delete an already-installed row) -- see\n"
        "  verenigingen/patches/v2_2/remove_workflow_demo_critical_operation_rules.py\n"
        "  for the precedent shape.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
