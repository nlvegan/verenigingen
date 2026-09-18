#!/usr/bin/env python3
r"""
veg11 Destructive-Command Validator
====================================

Catches the bug pattern from issue #1127: a doc, README, or test-file "how to
run this" comment pairs a destructive bench command with
``veg11.veganisme.org`` -- the site that carries a **copy of production
data** and is served straight out of the git working tree. Running the
suite there (``run-tests``, ``run-parallel-tests``, ``run-ui-tests``),
dropping it (``drop-site``), or reinstalling it (``reinstall``) destroys
data worth keeping; see ``CLAUDE.md``'s "Working with Sites" section.

The rule is narrow and zero-tolerance (no baseline): a line naming
``veg11.veganisme.org`` together with one of the destructive verbs is
always wrong, everywhere this validator is asked to check. It never fires
on the *legitimate* veg11 operations (``console``, ``mariadb``, ``migrate``,
``backup``) because those verbs are not in the trigger list.

``restore`` is deliberately excluded too, as a stated decision rather than
an omission: CLAUDE.md's own site-operations examples show
``bench --site veg11.veganisme.org restore ...`` as ordinary maintenance,
paired with ``backup`` -- and restoring TO veg11 is how an operator
recovers it after a mistake, not how one is made. Unlike ``drop-site`` /
``reinstall`` (unconditional, irreversible wipes triggered by the command
alone) or ``run-tests`` (a teardown drain that runs automatically),
``restore`` requires an operator to already hold a specific backup file
and deliberately choose to apply it. If that judgment call is wrong, see
issue #1146 to revisit it.

Historical documents are deliberately excluded via
``.pre-commit-config.yaml``'s ``exclude`` pattern, not by this script:
everything under ``docs/plans/`` and ``docs/superpowers/plans/`` (by this
repo's convention, dated -- ``YYYY-MM-DD-...`` -- plans and handoffs,
though the exclude itself is a plain directory-prefix match and does not
check the filename for a date), plus the stale, already-superseded
``docs/eboekhouden/consolidation-plan.md``. These are a record of what
someone ran at the time, not live instructions, and rewriting them would
falsify that record. Any file this script is actually asked to scan is
treated as live guidance.

Known evasions this validator does NOT catch (filed as #1146, not silently
accepted): ``bench use veg11.veganisme.org`` on one line
followed by a bare ``bench run-tests`` on a later, unrelated line (the
site is set as session/shell state, not repeated on the command itself --
exactly the idiom CLAUDE.md itself teaches for ``bench use``); prose that
names the destructive verb before the site
("run the suite against the veg11 ... site"); and a bare "veg11" without
the ``.veganisme.org`` domain. This validator only recognises the
site-plus-verb-on-one-logical-line shape.

A line split by a trailing ``\`` shell continuation is joined back into one
logical line before matching, so a site named on one physical line and a
verb named on the next (or vice versa) is still caught. The site and verb
may appear in either order on that logical line -- ``drop-site`` in
particular takes the site as a bare positional argument straight after the
verb rather than after ``--site``, e.g. against veg11.veganisme.org the
literal invocation is ``bench drop-site <site-name> --force``.

(Note for anyone editing this docstring: keep any site name and verb this
paragraph names on separate physical lines, as they are above -- this file
is itself scanned by the hook it defines, and a line naming both would be
a real self-inflicted violation, not a bug in the pattern.)

An unreadable file is treated as a hard failure (fail-closed), not a
silent pass -- a zero-tolerance safety gate must not report "clean" for a
file it could not actually check.

Usage
-----
    python scripts/validation/veg11_destructive_command_validator.py FILE [FILE ...]

Returns non-zero exit code if violations are found, or if any file could
not be read.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

DESTRUCTIVE_VERBS = (
    "run-parallel-tests",
    "run-ui-tests",
    "run-tests",
    "drop-site",
    "reinstall",
)

_VERB_ALTERNATION = "|".join(DESTRUCTIVE_VERBS)

# The site and verb may appear in either order on the logical line: most
# commands read "--site <site> run-tests ..." with the site first, but
# `drop-site` takes the site as a bare positional argument straight after
# the verb: "bench drop-site <site> --force" -- see the module docstring
# for a concrete example against veg11.veganisme.org.
_PATTERN = re.compile(
    r"(?:veg11\.veganisme\.org.*\b(?:" + _VERB_ALTERNATION + r")\b"
    r"|\b(?:" + _VERB_ALTERNATION + r")\b.*veg11\.veganisme\.org)",
    re.IGNORECASE,
)


@dataclass
class Violation:
    file_path: str
    line_number: int
    line: str


class UnreadableFileError(Exception):
    """Raised when a file cannot be read, so it can be a hard failure
    rather than silently reporting zero violations for it."""


def _iter_logical_lines(text: str):
    r"""Yield (starting_line_number, logical_line) pairs.

    A physical line ending in a trailing ``\`` shell continuation is
    joined with the line(s) that follow into a single logical line, so a
    site named on one physical line and a verb named on the next is still
    visible to the pattern as one string.
    """
    start = None
    buffer: list[str] = []
    for lineno, physical_line in enumerate(text.splitlines(), start=1):
        if start is None:
            start = lineno
        stripped = physical_line.rstrip()
        if stripped.endswith("\\"):
            buffer.append(stripped[:-1])
            continue
        buffer.append(physical_line)
        yield start, " ".join(buffer)
        start = None
        buffer = []
    if buffer:
        yield start, " ".join(buffer)


def check_file(path: Path) -> list[Violation]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise UnreadableFileError(f"{path}: could not be read ({exc})") from exc

    violations = []
    for lineno, logical_line in _iter_logical_lines(text):
        if _PATTERN.search(logical_line):
            violations.append(
                Violation(
                    file_path=str(path), line_number=lineno, line=logical_line.strip()
                )
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
    unreadable: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            file_violations = check_file(path)
        except UnreadableFileError as exc:
            unreadable.append(str(exc))
            continue
        for v in file_violations:
            total_violations += 1
            print(f"{v.file_path}:{v.line_number}: {v.line}")

    if unreadable:
        for message in unreadable:
            print(f"UNREADABLE: {message}", file=sys.stderr)
        print(
            f"\n{len(unreadable)} file(s) could not be read and cannot be verified "
            f"clean of veg11 destructive-command violations -- failing closed rather "
            f"than reporting them as passing.",
            file=sys.stderr,
        )

    if total_violations:
        print(
            f"\n{total_violations} instance(s) of a destructive bench command aimed at "
            f"veg11.veganisme.org (the production-data-copy site). Point it at a "
            f"disposable site instead -- test_site_1 .. test_site_13 -- see issue #1127.",
            file=sys.stderr,
        )

    if total_violations or unreadable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
