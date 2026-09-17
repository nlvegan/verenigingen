#!/usr/bin/env python3
"""
veg11 Destructive-Command Validator
====================================

Catches the bug pattern from issue #1127: a doc, README, or test-file "how to
run this" comment pairs the destructive test-suite commands with
``veg11.veganisme.org`` -- the site that carries a **copy of production
data** and is served straight out of the git working tree. Running the
suite there (``run-tests``, ``run-parallel-tests``, ``run-ui-tests``) or
reinstalling it destroys data worth keeping; see ``CLAUDE.md``'s "Working
with Sites" section.

The rule is narrow and zero-tolerance (no baseline): a line naming
``veg11.veganisme.org`` together with one of the destructive verbs is
always wrong, everywhere this validator is asked to check. It never fires
on the *legitimate* veg11 operations (``console``, ``mariadb``, ``migrate``,
``backup``) because those verbs are not in the trigger list.

Historical documents (dated plans/handoffs under ``docs/plans/`` and
``docs/superpowers/plans/``, plus the stale, already-superseded
``docs/eboekhouden/consolidation-plan.md``) are deliberately excluded via
``.pre-commit-config.yaml``'s ``exclude`` pattern, not by this script --
they are a record of what someone ran at the time, not live instructions,
and rewriting them would falsify that record. Any file this script is
actually asked to scan is treated as live guidance.

Usage
-----
    python scripts/validation/veg11_destructive_command_validator.py FILE [FILE ...]

Returns non-zero exit code if violations are found.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

DESTRUCTIVE_VERBS = (
    "run-parallel-tests",
    "run-ui-tests",
    "run-tests",
    "reinstall",
)

_PATTERN = re.compile(
    r"veg11\.veganisme\.org.*\b(?:" + "|".join(DESTRUCTIVE_VERBS) + r")\b"
)


@dataclass
class Violation:
    file_path: str
    line_number: int
    line: str


def check_file(path: Path) -> list[Violation]:
    violations = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return violations

    for lineno, line in enumerate(text.splitlines(), start=1):
        if _PATTERN.search(line):
            violations.append(
                Violation(file_path=str(path), line_number=lineno, line=line.strip())
            )
    return violations


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]]
    if not paths:
        print(
            "usage: veg11_destructive_command_validator.py FILE [FILE ...]",
            file=sys.stderr,
        )
        return 2

    total_violations = 0
    for path in paths:
        if not path.is_file():
            continue
        for v in check_file(path):
            total_violations += 1
            print(f"{v.file_path}:{v.line_number}: {v.line}")

    if total_violations:
        print(
            f"\n{total_violations} instance(s) of a destructive test command aimed at "
            f"veg11.veganisme.org (the production-data-copy site). Point it at a "
            f"disposable site instead -- test_site_1 .. test_site_13 -- see issue #1127.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
