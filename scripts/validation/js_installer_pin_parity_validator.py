#!/usr/bin/env python3
r"""
JS installer / pin-parity check (#272)
=======================================

Two things have to stay true together, or CI and a local ``npm install`` pick
different transitive-dependency pins without anyone noticing:

1. **The CI installer must pick the package manager per-app, not globally.**
   ``.github/actions/setup/action.yml`` installs JS deps for every app in the
   workspace in one loop. ``frappe``/``erpnext``/``hrms``/``builder`` ship a
   committed ``yarn.lock``; this app does not (dropped in ``1ed8cd0d``,
   "finish yarn->npm migration"). Real Yarn 1.22.22 is what GitHub-hosted
   runners have (measured on runs 32164620192 / 31948786616 -- the local
   ``/usr/bin/yarn`` is a broken cmdtest stub that exits 0 silently and does
   not generalise to CI). An *unconditional* ``yarn --check-files || npm
   install`` therefore runs real yarn for every app, including this one, and
   Yarn 1 reads ``resolutions`` and ignores ``overrides`` -- the opposite of
   local npm. The installer has to gate on the presence of that app's own
   ``yarn.lock`` so this app is npm-managed in CI exactly as it is locally.

2. **Once that gate is in place, ``package.json`` must not carry a
   ``resolutions`` block.** With the installer fixed, this app is npm-managed
   everywhere, so ``resolutions`` is dead in every environment -- keeping it
   around is exactly the drift #272 reported (four packages had already
   diverged between the two blocks; eleven were pinned in ``overrides``
   only). Deleting it is only safe *after* fix (1); deleting it first would
   have taken CI from 17 security pins to zero, which is what issue #272's
   original "just delete resolutions" suggestion would have done (see the
   issue's own corrective comment).

This script checks both, independently, so either one regressing fails CI:

* ``check_installer_gates_on_lockfile`` -- parses the "Install JS
  Dependencies" step out of ``action.yml`` and requires it to test for a
  per-app ``yarn.lock`` before ever invoking yarn, and rejects the old
  unconditional ``yarn --check-files || npm install`` line appearing
  unguarded.
* ``check_no_dead_resolutions_block`` -- requires ``package.json`` to have no
  top-level ``resolutions`` key.

Exit 0 if both hold, 1 otherwise (with a one-line reason each).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTION_YML = REPO_ROOT / ".github" / "actions" / "setup" / "action.yml"
DEFAULT_PACKAGE_JSON = REPO_ROOT / "package.json"

STEP_NAME = "Install JS Dependencies"
YARN_INVOCATION = re.compile(r"\byarn --check-files\b")
LOCKFILE_TEST = re.compile(r"\byarn\.lock\b")


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_guarded_by_lockfile_test(lines: list[str], idx: int) -> bool:
    """Is line ``idx`` nested under an ``if``/``elif`` whose condition tests
    for a lockfile, anywhere in its ancestor chain (by indentation)?

    Walks upward, tracking the smallest indentation seen so far; each time a
    strictly shallower line is found it is an enclosing ancestor. Stops at
    the top of the block. This is a plain indentation heuristic (bash has no
    real block nesting) but is enough for the consistently-indented YAML
    ``run:`` blocks this file parses.
    """
    min_indent = _leading_spaces(lines[idx])
    for i in range(idx - 1, -1, -1):
        line = lines[i]
        if not line.strip():
            continue
        indent = _leading_spaces(line)
        if indent < min_indent:
            if re.match(r"^\s*(if|elif)\b", line) and LOCKFILE_TEST.search(line):
                return True
            min_indent = indent
            if min_indent == 0:
                break
    return False


def _extract_step_block(action_yml_text: str, step_name: str) -> str | None:
    """Return the run: block belonging to the named step, or None if absent."""
    lines = action_yml_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*- name:\s*{re.escape(step_name)}\s*$", line):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^\s*- name:\s*\S", lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def check_installer_gates_on_lockfile(action_yml_text: str) -> list[str]:
    """Return a list of problems (empty if the installer is safe)."""
    block = _extract_step_block(action_yml_text, STEP_NAME)
    if block is None:
        return [f"could not find a {STEP_NAME!r} step in action.yml"]

    problems = []
    lines = block.splitlines()

    # Every invocation of real yarn must be nested under an if/elif that
    # tests for a lockfile -- otherwise it runs unconditionally, which is
    # exactly "try real yarn for every app, including the ones with no
    # yarn.lock" (real yarn reads `resolutions`, not `overrides`).
    unguarded = [
        i for i, line in enumerate(lines)
        if not line.strip().startswith("#")
        and YARN_INVOCATION.search(line)
        and not _is_guarded_by_lockfile_test(lines, i)
    ]
    if unguarded:
        problems.append(
            "action.yml invokes `yarn --check-files` without first testing for "
            "that app's own yarn.lock -- this runs real yarn (which reads "
            "`resolutions`, not `overrides`) for apps that ship no yarn.lock, "
            "including this one"
        )

    if not LOCKFILE_TEST.search(block):
        problems.append(
            "the 'Install JS Dependencies' step never tests for a per-app "
            "yarn.lock, so it cannot tell an app without one (this one) from "
            "frappe/erpnext/hrms/builder (which have one)"
        )

    return problems


def check_no_dead_resolutions_block(package_json: dict) -> list[str]:
    if "resolutions" in package_json:
        return [
            "package.json still has a top-level 'resolutions' block -- once the "
            "installer is npm-managed for this app in every environment, that "
            "block is read nowhere and only drifts from 'overrides' (#272)"
        ]
    return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-yml", type=Path, default=DEFAULT_ACTION_YML)
    parser.add_argument("--package-json", type=Path, default=DEFAULT_PACKAGE_JSON)
    args = parser.parse_args(argv[1:])

    problems = []
    problems += check_installer_gates_on_lockfile(args.action_yml.read_text())
    problems += check_no_dead_resolutions_block(json.loads(args.package_json.read_text()))

    if not problems:
        print("OK: installer is lockfile-gated and package.json carries no dead resolutions block")
        return 0

    print("\U0001f6d1 JS installer / pin-parity check failed (#272)\n")
    for p in problems:
        print(f"  - {p}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
