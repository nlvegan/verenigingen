#!/usr/bin/env python3
"""Block a real CI/tooling SETTING of ``VERENIGINGEN_FAIL_ON_ERROR_LOG`` without a
matching documentation update.

THE CLAIM THIS GUARDS
----------------------
``verenigingen/tests/utils/error_log_guard.py``'s module docstring records a
decision: ``VERENIGINGEN_FAIL_ON_ERROR_LOG`` is deliberately **not** set anywhere
in ``.github/`` or ``scripts/``, so the harness's automatic tearDown check only
WARNS in the configuration CI actually runs -- a green CI run is NOT evidence
that a test declared its Error Log writes. That claim is now load-bearing:
#1118 records the decision and its measured basis, and #1123 / #1125 both cite
it as the reason a green suite says nothing about the guard's blind spot.
``scripts/validation/vacuous_error_log_test_validator.py``'s own docstring
repeats it as the justification for one of its conditions.

**Nothing pinned that fact** (#1132). If someone later wires the flag into a
workflow -- a reasonable thing to do, e.g. as a nightly audit job -- all four
of those documents go silently false. This gate does not forbid that change:
the decision is revisable. It forces the four documents to be updated in the
same commit that makes the claim false.

WHAT COUNTS AS "SETTING" THE FLAG, AND WHAT DOES NOT
-----------------------------------------------------
A grep for the bare name is wrong on day one: this file's own docstring, and
``vacuous_error_log_test_validator.py``'s, both NAME the variable in prose
without setting it. The distinction this gate draws is syntactic, not lexical:

DETECTED (a real setting, at the point CI/tooling would read it):

* a YAML mapping key at the start of a (post `#`-strip) line, e.g. an ``env:``
  block entry: ``VERENIGINGEN_FAIL_ON_ERROR_LOG: "1"``;
* a shell assignment at the start of a (post `#`-strip) line, with or without
  ``export``: ``VERENIGINGEN_FAIL_ON_ERROR_LOG=1`` or
  ``export VERENIGINGEN_FAIL_ON_ERROR_LOG=1`` -- including the inline-prefix
  form used to invoke one test run (``VERENIGINGEN_FAIL_ON_ERROR_LOG=1 bench
  --site ... run-tests``);
* the same shell-assignment shape as a YAML sequence entry (a docker-style
  ``environment:`` list): ``- VERENIGINGEN_FAIL_ON_ERROR_LOG=1``;
* in a ``.py`` file, an AST-level mutation of ``os.environ`` for this exact
  key: ``os.environ["VERENIGINGEN_FAIL_ON_ERROR_LOG"] = ...``,
  ``os.environ.setdefault("VERENIGINGEN_FAIL_ON_ERROR_LOG", ...)``,
  ``os.putenv("VERENIGINGEN_FAIL_ON_ERROR_LOG", ...)``, or a dict literal
  carrying the key as one of its own keys (``env={"VERENIGINGEN_FAIL_ON_ERROR_LOG": "1"}``,
  the ``subprocess.run(..., env=...)`` shape).

NOT DETECTED, stated rather than silently missed:

* a single-line YAML mapping (``run: VERENIGINGEN_FAIL_ON_ERROR_LOG=1 cmd``)
  where the key/assignment is not the first token on its own physical line --
  the line-based scan only anchors at line start;
* YAML flow mappings (``env: {VERENIGINGEN_FAIL_ON_ERROR_LOG: '1'}``);
* the variable name built dynamically (string concatenation, an f-string, a
  name held in another variable) in either YAML or Python;
* a non-``os.environ`` mechanism -- a custom ``set_env(name, value)`` helper,
  a site-config write, a ``frappe.flags`` write, or a ``.env`` file consumed by
  a tool this gate does not itself parse;
* a prose value that happens to spell the full ``NAME=value``/``NAME: value``
  text INSIDE a non-comment string (e.g. a YAML ``description:`` field quoting
  an example) -- the ``#``-strip only removes what a real ``#`` comment would.
  Use the pragma below if this ever produces a false positive; weakening the
  pattern to avoid it would reopen the gap this gate exists to close.

Comments are excluded for non-Python files by stripping everything from the
first unescaped ``#`` on each physical line before matching -- so a comment
line, or a trailing comment on a code line, is never mistaken for a setting.
Python files are analysed by AST instead of text, so a docstring, a comment or
a plain string constant naming the variable is never a match by construction
(there is no ``os.environ`` mutation there) -- see the two guarding docstrings
above, which are exactly this shape and score zero findings.

SCOPE
-----
``.github/`` and ``scripts/`` -- the same two roots #1132 named, and the same
reasoning ``vacuous_error_log_test_validator.py`` already gives: ``scripts/``
is live code (121 whitelisted endpoints, every ratchet in this suite), and a
validator that only looks at ``.github/`` would miss a wrapper script under
``scripts/`` that sets the flag before invoking a test run.

SUPPRESSING A FALSE POSITIVE
-----------------------------
Mark the line ``# error-log-flag-setter-ok: <reason>`` (any text as the
reason). There is no fixed vocabulary, unlike the sibling gates -- the only
legitimate use is "this is prose describing the flag, not setting it", which a
free-text reason can say as well as an enum.

WHY A DOCUMENTATION-UPDATE MESSAGE, NOT A BLOCK
------------------------------------------------
Per #1132: the June 2026-06-20 decision (kept in ``error_log_guard.py``'s
docstring) is an audit-tool choice, not a law. Wiring the flag into CI is a
perfectly reasonable future change. This gate's failure message says what
went stale and where to fix it; it never says the change itself is wrong.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]

# The exact env var #1132 is about. Kept as one constant so the docstring's own
# mentions of it (above) and the detection logic (below) cannot drift apart --
# but note the constant's VALUE never appears as a bare grep target: every
# check below asks "is this a setting", not "does this text contain the name".
TARGET_VAR = "VERENIGINGEN_FAIL_ON_ERROR_LOG"

SCAN_ROOTS = (".github", "scripts")

# This validator's own file: it names TARGET_VAR throughout its docstring and
# holds the string as a plain constant, neither of which is an os.environ
# mutation -- but excluding it outright removes any doubt and matches the
# convention of not scanning a gate's own known-clean fixture-shaped source.
_SELF_PATH = Path(__file__).resolve()

DOCS_TO_UPDATE = (
    "verenigingen/tests/utils/error_log_guard.py (module docstring)",
    "scripts/validation/vacuous_error_log_test_validator.py (module docstring)",
    "issue #1118",
    "issue #1123",
    "issue #1125",
)

_PRAGMA = "error-log-flag-setter-ok:"

# Extensions treated as text and line-scanned when not Python. Anything else
# (binary, or an extension outside this list) is skipped rather than guessed
# at -- a .pkl/.patch/.json blob under scripts/ is not where CI wiring lives.
_TEXT_EXTENSIONS = {".yml", ".yaml", ".sh", ".bash", ".env", ".cfg", ".ini", ".disabled"}


class Finding(NamedTuple):
    file: str
    lineno: int
    snippet: str


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _strip_comment(line: str) -> str:
    """Drop everything from the first ``#`` onward.

    Deliberately naive -- no quote-awareness -- which is a documented
    limitation (see the module docstring's NOT DETECTED list): a ``#`` inside
    a quoted string on the same line would truncate too early and could hide
    a real setting after it. Every workflow/shell line in this repo that sets
    an env var puts the assignment before any trailing comment, so the live
    false-negative rate is zero; noted rather than silently assumed.
    """
    idx = line.find("#")
    return line if idx == -1 else line[:idx]


def _line_is_setting(code_part: str) -> bool:
    """Is `code_part` (comment already stripped) a YAML-key or shell-assignment
    setting of TARGET_VAR, anchored at the start of the line?

    Anchoring at line start (after stripping whitespace and an optional YAML
    list ``- `` marker, and an optional leading ``export ``) is what tells a
    real ``env:`` key or assignment apart from the variable name merely
    appearing later in a prose line -- see NOT DETECTED for what that anchor
    costs.
    """
    stripped = code_part.strip()
    if stripped.startswith("- "):
        stripped = stripped[2:].strip()
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if not stripped.startswith(TARGET_VAR):
        return False
    rest = stripped[len(TARGET_VAR) :]
    return bool(rest) and rest[0] in ":="


def _scan_text_file(path: Path) -> list[Finding]:
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    findings = []
    for i, raw in enumerate(lines, start=1):
        if _PRAGMA in raw:
            continue
        code_part = _strip_comment(raw)
        if _line_is_setting(code_part):
            findings.append(Finding(_rel(path), i, raw.strip()[:160]))
    return findings


# ---------------------------------------------------------------------------
# Python (.py) files: AST-based, so comments/docstrings/plain string constants
# are never a match by construction -- only an actual os.environ mutation is.
# ---------------------------------------------------------------------------

_ENVIRON_SETTER_ATTRS = {"setdefault", "update"}
_ENVIRON_FUNCS = {"putenv"}  # os.putenv(key, value)


def _str_const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _dict_has_target_key(node: ast.AST) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    for key in node.keys:
        if key is not None and _str_const(key) == TARGET_VAR:
            return True
    return False


def _assign_targets_environ(assign: ast.Assign) -> bool:
    for target in assign.targets:
        if (
            isinstance(target, ast.Subscript)
            and _is_os_environ(target.value)
            and _str_const_from_subscript(target) == TARGET_VAR
        ):
            return True
    return False


def _str_const_from_subscript(sub: ast.Subscript) -> str | None:
    sl = sub.slice
    # Py3.9+: Subscript.slice is the index expression directly.
    return _str_const(sl)


def _call_sets_target(call: ast.Call) -> bool:
    func = call.func
    # os.environ.setdefault("KEY", ...) / os.environ.update({"KEY": ...})
    if isinstance(func, ast.Attribute) and func.attr in _ENVIRON_SETTER_ATTRS and _is_os_environ(func.value):
        if func.attr == "setdefault":
            return bool(call.args) and _str_const(call.args[0]) == TARGET_VAR
        if func.attr == "update":
            for arg in call.args:
                if _dict_has_target_key(arg):
                    return True
            for kw in call.keywords:
                if kw.value is not None and _dict_has_target_key(kw.value):
                    return True
            return False
    # os.putenv("KEY", ...)
    if (
        isinstance(func, ast.Attribute)
        and func.attr in _ENVIRON_FUNCS
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    ):
        return bool(call.args) and _str_const(call.args[0]) == TARGET_VAR
    # anything(..., env={...}) -- e.g. subprocess.run(cmd, env={...}) -- where
    # the dict literal carries the key. Deliberately not restricted to
    # subprocess so a local wrapper with the same env= convention is caught.
    for kw in call.keywords:
        if kw.arg == "env" and kw.value is not None and _dict_has_target_key(kw.value):
            return True
    return False


def _scan_python_file(path: Path) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    lines = source.splitlines()
    findings = []
    for node in ast.walk(tree):
        hit = False
        if isinstance(node, ast.Assign) and _assign_targets_environ(node):
            hit = True
        elif isinstance(node, ast.Call) and _call_sets_target(node):
            hit = True
        if hit:
            lineno = getattr(node, "lineno", 0)
            if 1 <= lineno <= len(lines) and _PRAGMA in lines[lineno - 1]:
                continue
            snippet = lines[lineno - 1].strip()[:160] if 1 <= lineno <= len(lines) else ""
            findings.append(Finding(_rel(path), lineno, snippet))
    return findings


def _iter_files(paths: list[str]):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file():
                    yield child
        elif p.is_file():
            yield p


def scan(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files(paths):
        resolved = path.resolve()
        if resolved == _SELF_PATH:
            continue
        if resolved.suffix == ".py":
            findings.extend(_scan_python_file(path))
        elif resolved.suffix in _TEXT_EXTENSIONS or resolved.name.endswith(".disabled"):
            findings.extend(_scan_text_file(path))
    return findings


def default_paths() -> list[str]:
    return [str(REPO_ROOT / root) for root in SCAN_ROOTS]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=default_paths())
    ap.add_argument("--stats", action="store_true", help="print the total and exit 0")
    args = ap.parse_args(argv[1:])

    paths = args.paths or default_paths()
    # pre-commit invokes a `files:`-filtered hook in BATCHES of changed files,
    # so only a whole-tree run (no explicit paths, or the two scan roots
    # spelled out) can honestly claim "clean everywhere" -- same reasoning as
    # vacuous_error_log_test_validator's `whole_tree` flag.
    whole_tree = paths == default_paths()
    findings = scan(paths)

    if args.stats:
        print(f"real settings of {TARGET_VAR}: {len(findings)}")
        for f in findings:
            print(f"  {f.file}:{f.lineno}  {f.snippet}")
        return 0

    if findings:
        print(
            f"\n\U0001f6d1 {TARGET_VAR} is now SET somewhere in .github/ or scripts/\n"
        )
        for f in findings:
            print(f"  {f.file}:{f.lineno}  {f.snippet}")
        print(
            "\n  This flag is documented, in several places, as deliberately unset in CI\n"
            "  (#1118): a green CI run is cited as NOT being evidence that a test\n"
            "  declared its Error Log writes, because the automatic check only warns\n"
            "  while the flag is absent. That claim is now false. This is not a\n"
            "  block -- wiring the flag in (e.g. a nightly audit job) is a legitimate,\n"
            "  revisable choice -- but the following now need to be updated to match:\n"
        )
        for doc in DOCS_TO_UPDATE:
            print(f"    - {doc}")
        print(
            "\n  If this is a false positive (prose that spells out the assignment\n"
            f"  syntax without setting it), mark the line `# {_PRAGMA} <reason>`."
        )
        return 1

    if whole_tree:
        print(f"✅ {TARGET_VAR} is not set anywhere in .github/ or scripts/.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
