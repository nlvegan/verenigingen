#!/usr/bin/env python3
"""Minimal, stdlib-only GitHub Actions `paths:` filter matching.

Why this exists
----------------
#1113: `.github/workflows/server-tests.yml`'s `push`/`pull_request` `paths`
filters cover only `verenigingen/**/*.py` (plus a handful of workflow/setup
files). `scripts/` is a real importable package, and some `verenigingen/`
test code imports directly from it -- for example
`verenigingen/tests/test_member_import_cleanup_engine.py` does
`from scripts.migration import member_import_cleanup`. A trunk push that
touches only `scripts/migration/member_import_cleanup.py` therefore never
triggers the server test suite, even though that suite's own test exercises
the changed code.

This module answers "does this paths: filter cover this path" well enough to
write a regression guard for that gap. GitHub does not document which
library evaluates `on.push.paths`/`on.pull_request.paths` server-side --
`@actions/glob` is a different, documented mechanism (action-input file
globbing, e.g. `actions/upload-artifact`), not this one, so it is not cited
here as the implementation. What IS documented is GitHub's own path-filter
reference ("Workflow syntax for GitHub Actions" > "Path filters" / the
filter-pattern cheat sheet), and this module implements a deliberate subset
of the shapes it shows: `**` as an entire path segment (zero or more
segments, e.g. `dir/**/file.py`, `dir/**`) and `*`/`?` within a single
segment. It does NOT implement `**` glued to other characters inside one
segment (the cheat sheet's `**.js`, which crosses directory boundaries too,
matching `index.js`, `js/index.js` AND `src/js/app.js`) -- see
`UnsupportedGlobPattern`. That subset is all this repo's workflow files
actually use (checked all `paths:` entries across every `.github/workflows/*.yml`
still active, 2026-09-21). It does not depend on PyYAML: #1079 measured that
`code-validation.yml`'s validation job installs no dependencies beyond
`pathlib` (a stdlib-shadowing no-op on 3.12), so a module loaded by that
job's `unittest discover` catch-all step must survive on the standard
library alone.

`extract_trigger_paths` is a line-based scanner, not a YAML parser, and
assumes this repo's consistent 2-space-per-level indentation under `on:`.
That is a real limitation -- it would misparse a workflow written with
different indentation -- but a full YAML parse buys nothing here and would
reintroduce the PyYAML dependency this module exists to avoid.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def extract_trigger_paths(workflow_text: str, trigger: str) -> list[str]:
    """Return the `paths:` list under `on.<trigger>` in a workflow file.

    Returns an empty list if the trigger has no `paths:` key at all (i.e. it
    runs unconditionally), or if the trigger itself is absent.
    """
    lines = workflow_text.splitlines()
    in_on = False
    on_indent = None
    current_trigger = None
    in_paths = False
    collected: list[str] = []

    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if stripped.startswith("#"):
            continue  # comments carry no structure and must not end a paths: list

        if not in_on:
            if indent == 0 and re.match(r"^on:\s*$", stripped):
                in_on = True
                on_indent = indent
            continue

        if indent <= on_indent:
            break  # left the `on:` block entirely

        trigger_match = re.match(r"^(\w+):\s*$", stripped)
        if trigger_match and indent == on_indent + 2:
            current_trigger = trigger_match.group(1)
            in_paths = False
            continue

        if current_trigger != trigger:
            continue

        if re.match(r"^paths:\s*$", stripped):
            in_paths = True
            continue

        if in_paths:
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if item and item[0] in "'\"" and item[-1] == item[0]:
                    item = item[1:-1]
                collected.append(item)
                continue
            in_paths = False  # dedent/new key ends the paths: list

    return collected


class UnsupportedGlobPattern(ValueError):
    """A `paths:` pattern uses a `**` shape this module does not implement.

    Specifically: `**` glued to other characters within a single path segment
    (e.g. `**.js`, `pre**`, `**suffix`) -- GitHub's cheat sheet documents this
    shape as ALSO crossing directory boundaries (`**.js` matches `index.js`,
    `js/index.js` and `src/js/app.js`), which is a different, more permissive
    rule than a bare `*` in a segment (which never crosses `/`). Implementing
    that correctly is more than this CI-trigger regression guard needs, and
    no `paths:` entry in this repo's workflow files uses it as of 2026-09-21.
    Raising here, rather than silently falling back to the plain `*`
    (no-cross-`/`) rule, means a future pattern written in this shape gets a
    loud failure instead of a wrong answer nobody notices.
    """


def _glob_to_regex(pattern: str) -> re.Pattern:
    segments = pattern.split("/")
    regex_parts = []
    for i, segment in enumerate(segments):
        is_last = i == len(segments) - 1
        if segment == "**":
            regex_parts.append(".*" if is_last else "(?:.*/)?")
        elif "**" in segment:
            raise UnsupportedGlobPattern(
                f"pattern {pattern!r} has `**` glued to other characters in "
                f"segment {segment!r}; see UnsupportedGlobPattern's docstring"
            )
        else:
            escaped = re.escape(segment).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
            regex_parts.append(escaped)
            if not is_last:
                regex_parts.append("/")
    return re.compile("^" + "".join(regex_parts) + "$")


def path_matches_any(path: str, patterns: list[str]) -> bool:
    """True if `path` matches at least one of `patterns` (GitHub `paths:` glob subset).

    Raises `UnsupportedGlobPattern` if any pattern uses a `**` shape this
    module does not implement -- see that exception's docstring.
    """
    return any(_glob_to_regex(pattern).match(path) for pattern in patterns)
