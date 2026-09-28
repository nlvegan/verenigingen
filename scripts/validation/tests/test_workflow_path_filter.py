#!/usr/bin/env python3
"""Regression guard for #1113: server-tests.yml must trigger on the
scripts/ files verenigingen's own test suite imports.

Pure-Python (no bench, no site, no PyYAML) -- runs in the Code Validation
workflow's stdlib-only job alongside its siblings. Run with:
    python -m unittest scripts.validation.tests.test_workflow_path_filter
or plain:
    python scripts/validation/tests/test_workflow_path_filter.py

The coverage assertions below do NOT hardcode the files verenigingen/tests/
imports from scripts/ -- an earlier version of this guard did, and a
reviewer correctly flagged that a hardcoded list only closes today's 3
instances, not the class: a future `from scripts.<new_module> import x`
added under verenigingen/tests/ would (a) not be in the workflow filter --
today's bug again -- and (b) not be caught by a guard that only checks the
names it already knows. `_scripts_files_imported_under_tests` instead
AST-walks every file under `verenigingen/tests/` for `from scripts...`/
`import scripts...` and resolves each to the `.py` file(s) it actually
names, so a new import shows up here automatically the next time this test
runs.

#1550: a dotted `from scripts... import x` / `import scripts...` is not the
only way a test reaches `scripts/` -- `scripts/` is not an importable
package from `verenigingen/tests/`, so the established idiom for reaching
it (`test_doctype_name_ratchet.py`, `test_except_order_validator.py`, the
Zabbix churn test, ...) is `sys.path.insert(0, <dir under scripts/>)`
followed by a BARE `import <name>` (or `from <name> import ...`), which
spells neither shape above -- there is no AST node whose module string
contains "scripts" at all. A second idiom loads a `scripts/` file by path
with `importlib.util.spec_from_file_location(name, <path under scripts/>)`
and never has an `ast.Import`/`ast.ImportFrom` node to find in the first
place. Both are now detected: `_scripts_targets_from_syspath_hacks` pairs
each `sys.path.insert`/`.append` call that resolves (via literal path
segments only -- see `_literal_path_segments`) to a directory under
`scripts/` with the *next* statement in the same block; if that statement
is a bare import, it must resolve under that directory or the scan raises
loudly (never silently omits the file, which would look identical to "no
scripts/ dependency at all"). `_scripts_targets_from_spec_from_file_location`
resolves the file-location call's path argument the same way and adds it
if the target file exists on disk (quietly skipped if it does not, matching
this module's existing `_module_to_path(...).is_file()` convention for a
reference to a file that was never created, e.g. `field_validator.py` in
`verenigingen/tests/backend/validation/test_validation_regression.py`).
Deliberately narrow: it does not try to model arbitrary path arithmetic
(`frappe.get_app_path(...)`, `Path(__file__).resolve().parents[N]`, `os.path
.join`'s dynamic leading arguments are all treated as an opaque, ignored
prefix) -- only the LITERAL string segments in the expression are read, and
a match requires one of them to equal "scripts" exactly (never a substring
match against arbitrary file text, which would flag e.g. a docstring merely
*mentioning* "scripts").

Scoped to `verenigingen/tests/`, not all of `verenigingen/`: any import in a
file under `verenigingen/tests/` -- module-level or inside a test method --
is reachable by `bench run-parallel-tests` merely by that file/method being
collected and run, so a break in the imported `scripts/` code is guaranteed
to surface there. `verenigingen/commands/workspace.py`'s import of
`scripts/workspace_debugging_toolkit.py` (the fourth `scripts/` import in
the app, found while investigating #1113) is deliberately outside that
scope: it is a deferred import inside a bench CLI command body that no test
calls, so including `scripts/workspace_debugging_toolkit.py` in the
workflow filter would run the suite on a change to it and verify nothing.
That is a judgment call this scan cannot make for a future case either --
if `verenigingen/`'s non-test code grows a new `scripts/` import that IS
reachable by some test indirectly (without the test file itself naming
`scripts` in an import statement), this scan will not see it. It catches
the class of bug #1113 was actually filed for: a test file that itself
imports scripts/ code.
"""
import ast
import importlib.util
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "workflow_path_filter.py"
_spec = importlib.util.spec_from_file_location("workflow_path_filter", _MOD_PATH)
wpf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = wpf
_spec.loader.exec_module(wpf)

_WORKFLOW_PATH = wpf.REPO_ROOT / ".github" / "workflows" / "server-tests.yml"
_TESTS_DIR = wpf.REPO_ROOT / "verenigingen" / "tests"

# Known-good set as of 2026-09-21 (see module docstring). This is a CONTROL,
# not the source of truth for the coverage assertions below -- if the dynamic
# scan ever finds something different, this test fails and forces a human to
# look at *why* (a new import needing a filter entry, or a scan bug), rather
# than the coverage tests silently starting to check a different set with no
# visible diff.
#
# #1189 added the last two entries: this guard caught them for real, a few
# hours after #1184 merged -- PR #1189 added
# `verenigingen/tests/unit/test_savepoint_rollback_cannot_mask_the_error.py`
# imports of two new scripts/validation/ modules, and this test's dynamic
# scan found them where the workflow's paths filter did not cover them yet.
# That is the exact mechanism this guard exists for: a hardcoded list would
# have stayed green and let the gap through.
_KNOWN_SCRIPTS_FILES_IMPORTED_UNDER_TESTS = {
    "scripts/migration/member_import_cleanup.py",
    "scripts/migration/create_period_closing_vouchers.py",
    "scripts/migration/migrate_fee_overrides_to_dues_schedules.py",
    "scripts/validation/non_resumable_ast.py",
    "scripts/validation/savepoint_rollback_validator.py",
    # #1528/#1539: added by
    # verenigingen/tests/unit/test_performance_profiler_current_chapter_display.py
    "scripts/performance/performance_profiler.py",
    # #1550: the six entries below were already imported under verenigingen/tests/
    # before this scan could see the `sys.path.insert` + bare-import and
    # `importlib.util.spec_from_file_location` shapes -- they were invisible to the
    # scan, not new imports, which is why the scan being extended finds them all at
    # once rather than one at a time.
    "scripts/monitoring/zabbix_integration.py",  # tests/unit/test_zabbix_churn_metric.py (#1541)
    "scripts/validation/except_order_validator.py",  # tests/test_except_order_validator.py
    "scripts/validation/doctype_name_validator.py",  # tests/test_doctype_name_ratchet.py
    "scripts/validation/secure_operation_result_validator.py",  # tests/test_secure_operation_result_validator.py
    "scripts/testing/check_new_test_failures.py",  # tests/test_check_new_test_failures.py
    "scripts/validation/hooks_parser.py",  # tests/backend/validation/test_import_validation_integration.py
    "scripts/validation/test_quality_enforcer.py",  # tests/integration/test_permission_bypass_elimination_validation.py
}


def _module_to_path(dotted: str) -> Path:
    return wpf.REPO_ROOT / Path(*dotted.split(".")).with_suffix(".py")


def _path_to_dotted(path: Path) -> str:
    rel = path.relative_to(wpf.REPO_ROOT)
    return ".".join(rel.with_suffix("").parts)


def _literal_path_segments(node: ast.AST, aliases: dict) -> list[str]:
    """Best-effort literal string components of a path-building expression.

    Handles `a / "b" / "c"` (pathlib division), `os.path.join(a, "b", "c")`,
    `Path(x)`/`str(x)` wrappers, and a same-file `NAME = <expr>` alias. Any
    other node (an f-string, a call this does not know, `__file__`,
    `frappe.get_app_path(...)`, `.resolve()`, `.parents[N]`, ...) contributes
    NO segments rather than guessing -- callers only care about the literal
    tail after a "scripts" segment, and an unresolvable *prefix* is fine to
    drop since it is never that tail.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _literal_path_segments(node.left, aliases) + _literal_path_segments(
            node.right, aliases
        )
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in ("Path", "str") and node.args:
            return _literal_path_segments(node.args[0], aliases)
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "path"
        ):
            if func.attr == "join":
                segments: list[str] = []
                for arg in node.args:
                    segments += _literal_path_segments(arg, aliases)
                return segments
            # os.path.abspath/normpath/realpath: transparent single-arg wrappers --
            # `os.path.abspath(os.path.join(x, "scripts", "y"))` is exactly the shape
            # test_permission_bypass_elimination_validation.py uses.
            if func.attr in ("abspath", "normpath", "realpath") and node.args:
                return _literal_path_segments(node.args[0], aliases)
        return []
    if isinstance(node, ast.Name):
        if node.id in aliases:
            return _literal_path_segments(aliases[node.id], aliases)
        return []
    return []


def _scripts_subpath_after_marker(segments: list[str]) -> list[str] | None:
    """Everything after a literal `"scripts"` segment, or None if absent.

    A `".."` appearing AFTER the marker would reach above `scripts/` itself,
    which is out of scope here -- treated as unresolvable rather than guessed.
    """
    if "scripts" not in segments:
        return None
    tail = segments[segments.index("scripts") + 1 :]
    return None if ".." in tail else tail


def _collect_name_aliases(tree: ast.AST) -> dict:
    """Map `NAME` -> its assigned expression, for every simple `NAME = <expr>`
    in the file (module- or function-level). Good enough for the one-shot
    `scripts_path = ...; validator_path = scripts_path / '...'` shape these
    files use; a name assigned more than once keeps its last assignment."""
    aliases: dict = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            aliases[node.targets[0].id] = node.value
    return aliases


def _is_sys_path_mutation_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("insert", "append")
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "path"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "sys"
        and bool(node.args)
    )


def _scripts_dir_from_syspath_call(call: ast.Call, aliases: dict) -> Path | None:
    segments = _literal_path_segments(call.args[-1], aliases)
    tail = _scripts_subpath_after_marker(segments)
    if tail is None:
        return None
    return wpf.REPO_ROOT / "scripts" / Path(*tail) if tail else wpf.REPO_ROOT / "scripts"


def _bare_import_name(stmt: ast.AST) -> str | None:
    """The single, dot-free name a bare `import x` / `from x import y` names,
    or None if `stmt` is not that shape (a dotted/relative import is already
    handled by the existing dotted-import scan above, not this path)."""
    if isinstance(stmt, ast.Import) and len(stmt.names) == 1 and "." not in stmt.names[0].name:
        return stmt.names[0].name
    if (
        isinstance(stmt, ast.ImportFrom)
        and stmt.module
        and stmt.level == 0
        and "." not in stmt.module
    ):
        return stmt.module
    return None


def _scripts_targets_from_syspath_hacks(
    py_file: Path, tree: ast.AST, aliases: dict
) -> set[str]:
    """Pair each scripts-targeting `sys.path.insert`/`.append` call with the
    NEXT statement in its own block. Fail LOUD (raise) if that statement is a
    bare import that does not resolve under the targeted directory -- the
    whole point of #1550 is that silently finding nothing here looks
    identical to "this file has no scripts/ dependency", which is exactly
    the gap the workflow's paths: filter needs to never have again."""
    found: set[str] = set()

    def visit_block(stmts: list, next_after: ast.AST | None = None) -> None:
        for i, stmt in enumerate(stmts):
            # The statement textually following `stmt`, climbing out of an
            # enclosing block via `next_after` when `stmt` is last in `stmts` --
            # the codebase's `if X not in sys.path: sys.path.insert(...)`
            # guard idiom (verenigingen/tests/unit/test_zabbix_churn_metric.py)
            # puts the sys.path call alone in a 1-statement `If` body, with the
            # paired bare import as the `If` node's own next SIBLING, not
            # inside the `If` body at all.
            local_next = stmts[i + 1] if i + 1 < len(stmts) else next_after

            for field in ("body", "orelse", "finalbody"):
                child = getattr(stmt, field, None)
                if isinstance(child, list):
                    visit_block(child, next_after=local_next)
            for handler in getattr(stmt, "handlers", []) or []:
                visit_block(handler.body, next_after=local_next)

            if not (isinstance(stmt, ast.Expr) and _is_sys_path_mutation_call(stmt.value)):
                continue
            directory = _scripts_dir_from_syspath_call(stmt.value, aliases)
            if directory is None:
                continue

            name = _bare_import_name(local_next) if local_next is not None else None
            if name is None:
                continue  # nothing importable immediately follows -- not our concern

            resolved = directory / f"{name}.py"
            if not resolved.is_file():
                raise AssertionError(
                    f"{py_file}: sys.path hack targets {directory} (a directory under "
                    f"scripts/), but the very next import, {name!r}, does not resolve "
                    f"to a file there ({resolved} does not exist). Either the import is "
                    f"broken or this scan's pairing assumption is wrong -- a human needs "
                    f"to look, not have this silently count as no scripts/ dependency."
                )
            found.add(_path_to_dotted(resolved))

    visit_block(tree.body)
    return found


def _scripts_targets_from_spec_from_file_location(tree: ast.AST, aliases: dict) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_spec_call = (isinstance(func, ast.Attribute) and func.attr == "spec_from_file_location") or (
            isinstance(func, ast.Name) and func.id == "spec_from_file_location"
        )
        if not is_spec_call:
            continue
        path_arg = node.args[1] if len(node.args) >= 2 else None
        if path_arg is None:
            for kw in node.keywords:
                if kw.arg == "location":
                    path_arg = kw.value
        if path_arg is None:
            continue
        segments = _literal_path_segments(path_arg, aliases)
        tail = _scripts_subpath_after_marker(segments)
        if not tail:
            continue
        candidate = wpf.REPO_ROOT / "scripts" / Path(*tail)
        if candidate.is_file():
            found.add(_path_to_dotted(candidate))
    return found


def _scripts_files_imported_by(py_file: Path) -> set[str]:
    """Dotted-module -> `.py` file resolution for `scripts` imports in one file.

    `from scripts.migration import member_import_cleanup` names a package
    (`scripts.migration`) and a NAME imported from it, which is ambiguous
    from syntax alone: `member_import_cleanup` could be a submodule
    (`scripts/migration/member_import_cleanup.py`) or an attribute defined
    inside `scripts/migration/__init__.py`. Resolved against the real
    filesystem rather than guessed, preferring the deeper (submodule) path
    when it exists.
    """
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module != "scripts" and not node.module.startswith("scripts."):
                continue
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                if _module_to_path(submodule).is_file():
                    found.add(submodule)
                elif _module_to_path(node.module).is_file():
                    found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "scripts" or alias.name.startswith("scripts."):
                    if _module_to_path(alias.name).is_file():
                        found.add(alias.name)

    aliases = _collect_name_aliases(tree)
    found |= _scripts_targets_from_syspath_hacks(py_file, tree, aliases)
    found |= _scripts_targets_from_spec_from_file_location(tree, aliases)

    return found


def _scripts_files_imported_under_tests() -> list[str]:
    modules: set[str] = set()
    for py_file in _TESTS_DIR.rglob("*.py"):
        modules |= _scripts_files_imported_by(py_file)
    return sorted(str(_module_to_path(m).relative_to(wpf.REPO_ROOT)) for m in modules)


class TestGlobMatching(unittest.TestCase):
    """Sanity-check the matcher itself before trusting it on the real file."""

    def test_double_star_matches_zero_middle_segments(self):
        self.assertTrue(wpf.path_matches_any("verenigingen/foo.py", ["verenigingen/**/*.py"]))

    def test_double_star_matches_nested_segments(self):
        self.assertTrue(
            wpf.path_matches_any("verenigingen/a/b/foo.py", ["verenigingen/**/*.py"])
        )

    def test_trailing_double_star_matches_direct_child(self):
        self.assertTrue(
            wpf.path_matches_any(".github/actions/setup/action.yml", [".github/actions/setup/**"])
        )

    def test_control_unrelated_path_does_not_match(self):
        """A path with no relation to any pattern must NOT match -- otherwise
        the matcher could be trivially permissive and every assertion below
        would pass for the wrong reason."""
        self.assertFalse(
            wpf.path_matches_any("scripts/analysis/unrelated_scanner.py", ["verenigingen/**/*.py"])
        )

    def test_double_star_glued_to_a_suffix_raises(self):
        """`**.js` is a documented GitHub shape this module does not
        implement (see UnsupportedGlobPattern) -- it must fail loudly, not
        silently fall back to the plain, non-cross-`/` `*` rule."""
        with self.assertRaises(wpf.UnsupportedGlobPattern):
            wpf.path_matches_any("src/js/app.js", ["**.js"])


class TestExtractTriggerPaths(unittest.TestCase):
    def test_comment_lines_inside_a_paths_list_do_not_truncate_it(self):
        """A `#`-comment between two `- pattern` list items must not look
        like a dedent that ends the list -- server-tests.yml's push.paths
        has exactly this shape (a multi-line comment sits between the `.js`
        pattern and the scripts/migration/ pattern added for #1113)."""
        text = (
            "on:\n"
            "  push:\n"
            "    paths:\n"
            "      - 'verenigingen/**/*.py'\n"
            "      # a comment explaining the next line\n"
            "      - 'scripts/migration/**/*.py'\n"
            "  pull_request:\n"
            "    paths:\n"
            "      - 'verenigingen/**/*.py'\n"
        )
        self.assertEqual(
            wpf.extract_trigger_paths(text, "push"),
            ["verenigingen/**/*.py", "scripts/migration/**/*.py"],
        )


class TestSysPathHackAndImportlibDetection(unittest.TestCase):
    """#1550: unit-level coverage for the two new shapes `_scripts_files_imported_by`
    can now see, isolated from the real repo tree (a fake `scripts/` under a tempdir,
    with `wpf.REPO_ROOT` patched to it) so a real file moving/disappearing can never
    flip these for the wrong reason, and so the resolution TARGET is one this test
    controls rather than borrowing a real validator that could change shape."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)
        (self.root / "scripts" / "validation").mkdir(parents=True)
        (self.root / "scripts" / "validation" / "widget_validator.py").write_text("VALUE = 1\n")
        patcher = unittest.mock.patch.object(wpf, "REPO_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _scan(self, source: str) -> set[str]:
        probe = self.root / "probe_test.py"
        probe.write_text(source)
        return _scripts_files_imported_by(probe)

    def test_sys_path_hack_plus_bare_import_is_detected(self):
        found = self._scan(
            "import sys\n"
            "from pathlib import Path\n"
            'APP_ROOT = Path(__file__).resolve().parents[1]\n'
            'sys.path.insert(0, str(APP_ROOT / "scripts" / "validation"))\n'
            "import widget_validator  # noqa: E402\n"
        )
        self.assertEqual(found, {"scripts.validation.widget_validator"})

    def test_sys_path_hack_plus_bare_from_import_is_detected(self):
        found = self._scan(
            "import sys\n"
            "from pathlib import Path\n"
            'APP_ROOT = Path(__file__).resolve().parents[1]\n'
            'sys.path.insert(0, str(APP_ROOT / "scripts" / "validation"))\n'
            "from widget_validator import VALUE  # noqa: E402\n"
        )
        self.assertEqual(found, {"scripts.validation.widget_validator"})

    def test_if_guarded_insert_pairs_with_the_statement_after_the_if(self):
        """Mirrors verenigingen/tests/unit/test_zabbix_churn_metric.py's
        `if _DIR not in sys.path: sys.path.insert(...)` idiom, where the paired
        bare import is the `If` node's own next SIBLING, not inside its body."""
        found = self._scan(
            "import sys\n"
            "from pathlib import Path\n"
            'APP_ROOT = Path(__file__).resolve().parents[1]\n'
            '_DIR = str(APP_ROOT / "scripts" / "validation")\n'
            "if _DIR not in sys.path:\n"
            "    sys.path.insert(0, _DIR)\n"
            "\n"
            "import widget_validator  # noqa: E402\n"
        )
        self.assertEqual(found, {"scripts.validation.widget_validator"})

    def test_os_path_join_and_abspath_wrapper_is_detected(self):
        """Mirrors verenigingen/tests/integration/
        test_permission_bypass_elimination_validation.py's
        `os.path.abspath(os.path.join(..., "..", "scripts", "validation"))` shape."""
        found = self._scan(
            "import os\n"
            "import sys\n"
            "validation_dir = os.path.abspath(\n"
            '    os.path.join("/some/opaque/prefix", "..", "scripts", "validation")\n'
            ")\n"
            "sys.path.append(validation_dir)\n"
            "\n"
            "from widget_validator import VALUE\n"
        )
        self.assertEqual(found, {"scripts.validation.widget_validator"})

    def test_control_a_literal_scripts_substring_with_no_real_syspath_hack_is_not_flagged(self):
        """The plausible WRONG fix is matching the literal string "scripts" anywhere
        in the file. Here "scripts/validation" appears only inside a string constant
        (never inside a `sys.path` call), and the `sys.path.insert` call that DOES run
        targets an unrelated directory -- a substring-matching scan would wrongly flag
        `widget_validator` anyway; the structural scan must not."""
        found = self._scan(
            "import sys\n"
            'DESCRIPTION = "See scripts/validation for details."\n'
            'sys.path.insert(0, "/some/unrelated/dir")\n'
            "import widget_validator\n"
        )
        self.assertEqual(found, set())

    def test_fails_loud_when_the_paired_bare_import_does_not_resolve(self):
        """Fail-loud principle (#1550): a sys.path hack that structurally targets a
        scripts/ directory, paired with a bare import that does NOT resolve under it,
        must never silently look like "no scripts/ dependency" -- that is exactly the
        gap #1550 was filed for, one level further in."""
        with self.assertRaises(AssertionError):
            self._scan(
                "import sys\n"
                "from pathlib import Path\n"
                'APP_ROOT = Path(__file__).resolve().parents[1]\n'
                'sys.path.insert(0, str(APP_ROOT / "scripts" / "validation"))\n'
                "import totally_nonexistent_validator  # noqa: E402\n"
            )

    def test_importlib_spec_from_file_location_is_detected(self):
        found = self._scan(
            "import importlib.util\n"
            "from pathlib import Path\n"
            'APP_ROOT = Path(__file__).resolve().parents[1]\n'
            '_PATH = APP_ROOT / "scripts" / "validation" / "widget_validator.py"\n'
            '_spec = importlib.util.spec_from_file_location("widget_validator", _PATH)\n'
        )
        self.assertEqual(found, {"scripts.validation.widget_validator"})

    def test_importlib_spec_from_file_location_for_a_missing_file_is_not_flagged(self):
        """Mirrors verenigingen/tests/backend/validation/test_validation_regression.py's
        reference to a `field_validator.py` that was never created: the path is fully
        literal and resolvable, it just does not exist on disk, matching this module's
        existing quiet-skip convention for `_module_to_path(...).is_file()`."""
        found = self._scan(
            "import importlib.util\n"
            "from pathlib import Path\n"
            'APP_ROOT = Path(__file__).resolve().parents[1]\n'
            '_PATH = APP_ROOT / "scripts" / "validation" / "does_not_exist.py"\n'
            '_spec = importlib.util.spec_from_file_location("x", _PATH)\n'
        )
        self.assertEqual(found, set())


class TestServerTestsWorkflowCoversScriptsImportedByTests(unittest.TestCase):
    def setUp(self):
        self.text = _WORKFLOW_PATH.read_text()
        self.targets = _scripts_files_imported_under_tests()

    def test_control_known_import_set_has_not_silently_changed(self):
        """Guards the scan itself: if this ever fails, either a new
        scripts/ import needs a filter entry (update the known set once
        you've added it below AND to the workflow), or the AST scan broke
        and is no longer finding the real imports -- either way, a human
        needs to look, not have the coverage tests below start silently
        checking a different (possibly empty) set."""
        self.assertEqual(
            set(self.targets), _KNOWN_SCRIPTS_FILES_IMPORTED_UNDER_TESTS
        )

    def test_push_paths_cover_every_scripts_file_tests_import(self):
        paths = wpf.extract_trigger_paths(self.text, "push")
        for target in self.targets:
            with self.subTest(target=target):
                self.assertTrue(
                    wpf.path_matches_any(target, paths),
                    f"push.paths does not cover {target!r} -- a trunk push touching only "
                    f"this file would not run the server suite that tests it",
                )

    def test_pull_request_paths_cover_every_scripts_file_tests_import(self):
        paths = wpf.extract_trigger_paths(self.text, "pull_request")
        for target in self.targets:
            with self.subTest(target=target):
                self.assertTrue(
                    wpf.path_matches_any(target, paths),
                    f"pull_request.paths does not cover {target!r}",
                )


if __name__ == "__main__":
    unittest.main()
