#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration Tests for Public API Guest Access

These tests verify that public-facing API endpoints are correctly configured
for guest (unauthenticated) access. They catch issues like:

1. @public_api decorator used but @frappe.whitelist missing allow_guest=True
2. @standard_api used instead of @public_api on guest-accessible endpoints
3. OperationResult format consistency for frontend consumption
4. Missing Critical Operation Rule records for endpoints

Run with: bench --site dev.veganisme.net run-tests --module verenigingen.tests.integration.test_public_api_guest_access
"""

import ast
import contextlib
import inspect
import os
import re
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import frappe


@contextlib.contextmanager
def _with_user(user):
    """Switch to ``user`` for the duration of the block, restoring the
    original session user afterwards. Used by these guest-access tests so
    the Guest/Administrator switch lives in fixture context rather than
    hard-coded set_user("Administrator") in test bodies."""
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        yield
    finally:
        frappe.set_user(previous)

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.operation_result import OperationResult


def unwrap_operation_result(result):
    """
    Helper to unwrap OperationResult to get the actual data.

    Handles both:
    - OperationResult objects (direct function calls)
    - Serialized dicts (what frontend/HTTP clients see)
    """
    if isinstance(result, OperationResult):
        return result.data, result.success, result.error_message
    elif isinstance(result, dict):
        if "data" in result and "success" in result:
            # Serialized OperationResult format
            return result.get("data"), result.get("success"), result.get("error")
        else:
            # Legacy dict format - assume success
            return result, True, None
    else:
        return result, True, None


class TestPublicAPIGuestAccess(EnhancedTestCase):
    """Test that public API endpoints are accessible to guest users"""

    # Known public endpoints that MUST be guest-accessible
    # Format: (module_path, function_name, description)
    REQUIRED_GUEST_ENDPOINTS = [
        (
            "verenigingen.api.membership_application",
            "get_application_form_data",
            "Membership application form data",
        ),
        (
            "verenigingen.api.membership_application",
            "validate_email",
            "Email validation for application",
        ),
        (
            "verenigingen.api.membership_application",
            "validate_postal_code",
            "Postal code validation",
        ),
        (
            "verenigingen.api.membership_application",
            "suggest_chapters_for_postal_code",
            "Chapter suggestions by postal code",
        ),
        # `verenigingen.api.enhanced_membership_application` was deleted during the
        # application-flow refactor (submit_enhanced_application / get_membership_types_for_application /
        # get_contribution_calculator_config no longer exist). When the replacement
        # public endpoints stabilize, add their entries here.
    ]

    def test_guest_can_access_application_form_data(self):
        """Test that guests can fetch application form data without authentication"""
        with _with_user("Guest"):
            try:
                from verenigingen.api.membership_application import get_application_form_data

                result = get_application_form_data()
                data, success, error = unwrap_operation_result(result)

                self.assertTrue(success, f"API should succeed for guest: {error}")
                self.assertIsNotNone(data, "Should return data")

                # Verify data structure
                self.assertIn("membership_types", data, "Should include membership_types")
                self.assertIn("chapters", data, "Should include chapters")
            except frappe.PermissionError as e:
                self.fail(
                    f"Guest should be able to access get_application_form_data: {str(e)}"
                )

    @unittest.skip(
        "Imports verenigingen.api.enhanced_membership_application which "
        "no longer exists. Re-enable once the module is restored or the "
        "test is rewritten against the current membership-types endpoint."
    )
    def test_guest_can_access_membership_types(self):
        """Test that guests can fetch membership types without authentication"""
        # Deferred via importlib so static analyzers don't fail on the
        # missing module while the test is skipped.
        with _with_user("Guest"):
            try:
                import importlib
                get_membership_types_for_application = importlib.import_module(
                    "verenigingen.api.enhanced_membership_application"
                ).get_membership_types_for_application

                result = get_membership_types_for_application()
                data, success, error = unwrap_operation_result(result)

                self.assertTrue(
                    success,
                    f"get_membership_types_for_application should succeed for guest: {error}",
                )
                self.assertIsNotNone(data, "Should return data")
            except frappe.PermissionError as e:
                self.fail(
                    f"Guest should be able to access get_membership_types_for_application: {str(e)}"
                )

    def test_guest_can_validate_email(self):
        """Test that guests can validate email without authentication"""
        with _with_user("Guest"):
            try:
                from verenigingen.api.membership_application import validate_email

                result = validate_email("test@example.com")

                # Should not raise PermissionError
                self.assertIsNotNone(result)
            except frappe.PermissionError as e:
                self.fail(f"Guest should be able to validate email: {str(e)}")


def _build_import_aliases(tree: ast.Module) -> Dict[str, str]:
    """Map a local ``from x import y as z`` alias back to its real name ``y``.

    Needed so ``_decorator_base_name`` reports the underlying decorator name
    (e.g. "whitelist") rather than whatever local alias a file happens to
    import it under (e.g. "wl") -- an aliased ``from frappe import
    whitelist as wl`` used to make ``@wl(allow_guest=True)`` invisible to
    this scan entirely (#1063).
    """
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


def _decorator_base_name(decorator: ast.expr, import_aliases: Optional[Dict[str, str]] = None) -> str:
    """Return the bare name of a decorator regardless of call/attribute shape.

    ``@public_api`` -> "public_api", ``@public_api(...)`` -> "public_api",
    ``@frappe.whitelist`` -> "whitelist", ``@frappe.whitelist(...)`` -> "whitelist".
    ``import_aliases`` (see ``_build_import_aliases``) resolves a bare-name
    call back through an aliased import, e.g. ``@wl(...)`` where the file
    has ``from frappe import whitelist as wl`` (#1063).
    """
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return (import_aliases or {}).get(target.id, target.id)
    return ""


def _whitelist_allows_guest(decorator: ast.expr) -> Tuple[bool, bool]:
    """Return ``(allows_guest, verified)`` for a ``@frappe.whitelist(...)`` call.

    ``allow_guest`` is real ``frappe.whitelist``'s *first positional*
    parameter (``frappe/__init__.py``: ``def whitelist(allow_guest=False,
    xss_safe=False, methods=None)``), not just a keyword -- a keyword-only
    check reports the genuinely valid ``@frappe.whitelist(True)`` as
    "missing" (#1063), so a bare first positional argument is checked too.

    ``verified`` is False when the value found (keyword or positional) is
    not a literal Python can resolve statically, e.g.
    ``allow_guest=SOME_CONST``. The caller must not treat that the same as
    a confirmed-missing ``allow_guest=True`` (the value might genuinely be
    True at runtime) -- but it also must not silently treat it as fine, so
    it is surfaced as a distinct, unverifiable finding instead (#1063).
    """
    if not isinstance(decorator, ast.Call):
        return False, True

    value_node = None
    for keyword in decorator.keywords:
        if keyword.arg == "allow_guest":
            value_node = keyword.value
            break
    else:
        if decorator.args:
            value_node = decorator.args[0]

    if value_node is None:
        return False, True

    if isinstance(value_node, ast.Constant):
        return value_node.value is True, True

    return False, False


def find_public_api_allow_guest_issues(api_files: List[Path]) -> List[str]:
    """Scan ``api_files`` for @public_api functions missing allow_guest=True.

    Uses ``ast.parse`` and inspects each function's ``decorator_list`` as a
    set rather than scanning source lines forward from ``@public_api``
    looking for ``@frappe.whitelist`` on a following line. The line-based
    forward scan only ever caught the "public_api, then whitelist" order; it
    was blind to "whitelist, then public_api", which is the order used by
    34 of the 35 real @public_api occurrences in this codebase (#1046).
    Source-level decorator order carries no meaning for THIS scan (it reads
    the whole decorator_list as a set), so the check must not depend on it
    either. (This is a claim about the AST-matching mechanism only -- it is
    not a claim that this app's security decorators preserve object
    identity across every decorator order at runtime; see #1074 for a case
    where they don't, which is why this scan stays AST/literal-based rather
    than switching to a `frappe.guest_methods` runtime-membership check.)

    Deliberately does NOT resolve a decorator applied via a wrapper/factory
    (e.g. a function that internally calls
    ``frappe.whitelist(allow_guest=True)`` under a different visible name)
    -- see ``test_public_api_allow_guest_scan_wrapper_factory_is_a_known_blind_spot``
    for why that residual gap is documented rather than fixed here (#1063).
    """
    issues = []
    for api_file in api_files:
        try:
            tree = ast.parse(api_file.read_text(), filename=str(api_file))
        except SyntaxError:
            continue

        import_aliases = _build_import_aliases(tree)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            decorators = node.decorator_list
            if not any(_decorator_base_name(d, import_aliases) == "public_api" for d in decorators):
                continue

            whitelist_decorators = [
                d for d in decorators if _decorator_base_name(d, import_aliases) == "whitelist"
            ]
            if not whitelist_decorators:
                # No @frappe.whitelist at all is a different (and worse) defect
                # than the one this check exists for; out of scope here.
                continue

            results = [_whitelist_allows_guest(d) for d in whitelist_decorators]
            if any(allows for allows, _verified in results):
                continue

            if any(not verified for _allows, verified in results):
                issues.append(
                    f"{api_file.name}:{node.lineno} - @public_api on {node.name} has "
                    f"@frappe.whitelist(allow_guest=...) with a non-literal value that "
                    f"cannot be statically verified as True; review manually"
                )
            else:
                issues.append(
                    f"{api_file.name}:{node.lineno} - @public_api on {node.name} "
                    f"but @frappe.whitelist missing allow_guest=True"
                )

    return issues


def _recursive_py_files(directory: Path) -> List[Path]:
    """Recursively list ``.py`` files under ``directory``.

    Named so a test can assert the *scanning mechanism* is recursive against
    a synthetic tree it builds itself, rather than asserting a property of
    whatever ``verenigingen/api/`` happens to contain today (#1049). The
    previous guard here compared ``len(rglob) > len(glob)`` against the
    *live* api/ tree, which holds only because api/member/ happens to carry
    .py files today; a correct consolidation that flattened those files
    back into api/ would equalize the counts and fail that assertion on a
    tree with no scanning defect at all, with a misleading message blaming
    a reverted recursive scan.
    """
    return list(directory.rglob("*.py"))


# Guest/public vocabulary checked as exact underscore-delimited tokens (not
# substrings) against a @standard_api function's name -- see
# find_standard_api_guest_naming_issues() for why this exists alongside the
# phrase-based regex list below, and why token matching, not substring
# matching (#1056 measured "update_publication_status" as a false-positive
# substring hit on "public").
_GUEST_NAME_TOKENS = {"public", "guest", "signup", "widget", "anonymous"}

# Multi-word naming *phrases* that suggest an endpoint should be guest
# accessible. Necessarily a closed, hand-maintained list -- see
# find_standard_api_guest_naming_issues()'s docstring for why this cannot be
# exhaustive for a naming convention that was never formalized (#1056).
_GUEST_NAME_PHRASE_PATTERNS = [
    r"get_.*form_data",
    r"get_.*for_application",
    r"validate_email",
    r"validate_postal",
    r"suggest_chapter",
    r"get_contribution_calculator",
]


def _guest_suggestive_match(func_name: str) -> str:
    """Return the phrase/token that makes ``func_name`` look guest-accessible,
    or "" if none matches."""
    for pattern in _GUEST_NAME_PHRASE_PATTERNS:
        if re.search(pattern, func_name, re.IGNORECASE):
            return pattern
    hit = set(func_name.lower().split("_")) & _GUEST_NAME_TOKENS
    if hit:
        return "token:" + "/".join(sorted(hit))
    return ""


def find_standard_api_guest_naming_issues(api_files: List[Path]) -> List[str]:
    """Scan ``api_files`` for @standard_api functions with guest-suggestive names.

    Two independent, both-heuristic signals (#1056): a hand-maintained list
    of known naming *phrases* (regex, for multi-word conventions like
    "get_..._form_data"), and an open vocabulary of single guest/public
    *words* checked as exact underscore-delimited tokens rather than
    substrings. Neither can be exhaustive for a naming convention that was
    never formalized -- this closes the specific gap measured in #1056 (a
    name built from the token vocabulary, e.g.
    "fetch_public_signup_widget_config", that matched none of the listed
    phrases) without claiming the check is now complete. A genuinely new
    naming convention outside both signals remains invisible; that residual
    gap is inherent to a naming-based heuristic, not a bug this scan can
    close on its own.
    """
    issues = []
    for api_file in api_files:
        lines = api_file.read_text().split("\n")

        for i, line in enumerate(lines):
            if "@standard_api" not in line or line.strip().startswith("#"):
                continue

            for j in range(i + 1, min(i + 5, len(lines))):
                if not lines[j].strip().startswith("def "):
                    continue
                func_match = re.search(r"def (\w+)", lines[j])
                if func_match:
                    func_name = func_match.group(1)
                    match = _guest_suggestive_match(func_name)
                    if match:
                        issues.append(
                            f"{api_file.name}:{i + 1} - {func_name} uses @standard_api "
                            f"but name suggests it should be @public_api (guest accessible) "
                            f"[matched: {match}]"
                        )
                break

    return issues


class TestPublicAPIDecoratorConsistency(EnhancedTestCase):
    """
    Static analysis tests to verify decorator consistency.

    These tests scan API files to ensure:
    1. @public_api is always paired with @frappe.whitelist(allow_guest=True)
    2. No @standard_api on endpoints that should be public
    """

    def get_api_files(self) -> List[Path]:
        """Get all API files in the verenigingen app.

        Fails loudly if the directory cannot be resolved, instead of letting
        every caller silently pass having scanned nothing (#1027). Whether
        the scan mechanism itself is recursive is proven separately, against
        a synthetic tree, by test_api_directory_scan_is_recursive -- NOT by
        comparing file counts in this live directory (#1049: that guard
        pinned api/'s current subdirectory layout rather than the scanner's
        behaviour).
        """
        api_dir = Path(frappe.get_app_path("verenigingen")) / "api"
        files = _recursive_py_files(api_dir)
        self.assertGreater(
            len(files),
            20,
            f"Expected a substantial number of API files under {api_dir}, found "
            f"{len(files)}. A near-empty scan means api_dir failed to resolve "
            "(#1027) rather than there being genuinely few files.",
        )
        return files

    def test_api_directory_scan_is_recursive(self):
        """
        Positive control for #1049.

        Proves _recursive_py_files() (used by get_api_files() and
        get_public_api_functions()) actually finds .py files nested in a
        subdirectory, using a synthetic tree built inside the test -- not a
        property of verenigingen/api/'s current layout, which could
        legitimately change (e.g. if api/member/ were flattened back into
        api/, the old len(rglob) > len(glob) guard would fail on a tree with
        no scanning defect at all).
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "top_level.py").write_text("# top level\n")
            nested_dir = tmp_path / "nested"
            nested_dir.mkdir()
            (nested_dir / "nested_file.py").write_text("# nested\n")

            found_names = {f.name for f in _recursive_py_files(tmp_path)}

            self.assertIn("top_level.py", found_names)
            self.assertIn(
                "nested_file.py",
                found_names,
                "The scan must find .py files nested in a subdirectory, "
                "regardless of whether verenigingen/api/ currently has any "
                "(#1049).",
            )

    def test_public_api_has_allow_guest(self):
        """
        Verify that all @public_api decorators are paired with allow_guest=True

        This catches the exact bug we encountered where @public_api was used
        but @frappe.whitelist() was missing allow_guest=True.

        See find_public_api_allow_guest_issues() for why this is AST-based
        rather than a directional line scan (#1046).
        """
        issues = find_public_api_allow_guest_issues(self.get_api_files())

        if issues:
            self.fail(
                "Found @public_api decorators without allow_guest=True:\n"
                + "\n".join(issues)
            )

    def test_public_api_allow_guest_scan_is_order_independent(self):
        """
        Positive control for #1046.

        The scan in find_public_api_allow_guest_issues() must catch a
        @public_api endpoint missing allow_guest=True regardless of whether
        @frappe.whitelist appears above or below @public_api in source, and
        regardless of nesting under a subdirectory (the real scan is
        recursive since #1020/#1027). Built as a synthetic temp tree rather
        than against the real api/ directory, so this test does not depend
        on -- or get invalidated by -- future changes to real endpoints.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "member").mkdir()

            # Real codebase order (34 of 35 real occurrences): whitelist
            # above public_api. This is the order the pre-fix forward scan
            # could never see, because it hit the `def` line before it had
            # scanned backwards to find @frappe.whitelist.
            (tmp_path / "whitelist_then_public.py").write_text(
                "import frappe\n"
                "from verenigingen.utils.security.api_security_framework import (\n"
                "    OperationType,\n"
                "    public_api,\n"
                ")\n\n"
                "@frappe.whitelist()\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def broken_real_order():\n"
                "    pass\n\n"
                "@frappe.whitelist(allow_guest=True)\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def ok_real_order():\n"
                "    pass\n"
            )

            # Reversed order -- the only order the pre-fix scan could catch.
            (tmp_path / "public_then_whitelist.py").write_text(
                "import frappe\n"
                "from verenigingen.utils.security.api_security_framework import (\n"
                "    OperationType,\n"
                "    public_api,\n"
                ")\n\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "@frappe.whitelist()\n"
                "def broken_reversed_order():\n"
                "    pass\n\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "@frappe.whitelist(allow_guest=True)\n"
                "def ok_reversed_order():\n"
                "    pass\n"
            )

            # Subdirectory of api/ -- the recursive scan (#1020) must reach it.
            (tmp_path / "member" / "nested_broken.py").write_text(
                "import frappe\n"
                "from verenigingen.utils.security.api_security_framework import (\n"
                "    OperationType,\n"
                "    public_api,\n"
                ")\n\n"
                "@frappe.whitelist()\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def broken_nested():\n"
                "    pass\n"
            )

            api_files = list(tmp_path.rglob("*.py"))
            issues = find_public_api_allow_guest_issues(api_files)
            issue_text = "\n".join(issues)

            self.assertIn(
                "broken_real_order",
                issue_text,
                "The order used by 34/35 real endpoints (whitelist above "
                "public_api) must be caught.",
            )
            self.assertIn(
                "broken_reversed_order",
                issue_text,
                "The reversed order must still be caught.",
            )
            self.assertIn(
                "broken_nested",
                issue_text,
                "A violation nested under a subdirectory of api/ must be caught.",
            )
            self.assertNotIn(
                "ok_real_order",
                issue_text,
                "A correctly-configured endpoint must not be flagged.",
            )
            self.assertNotIn(
                "ok_reversed_order",
                issue_text,
                "A correctly-configured endpoint must not be flagged.",
            )
            self.assertEqual(
                len(issues),
                3,
                f"Expected exactly 3 planted violations, got: {issues}",
            )

    def test_public_api_allow_guest_scan_handles_decorator_shapes(self):
        """
        Positive control for #1063.

        Three decorator shapes the pre-fix AST scan got wrong, all
        confirmed dormant (zero live occurrences) but dangerous or
        misleading if they ever appear:

        - an aliased `frappe.whitelist` import (false negative -- the alias
          name, e.g. "wl", never matched the literal string "whitelist", so
          a genuinely unguarded `@wl()` endpoint fell into the "no
          @frappe.whitelist decorator recognized at all -- out of scope"
          branch and was silently never reported)
        - a positional `@frappe.whitelist(True)` (false positive -- the
          keyword-only check saw an empty `keywords` list and reported a
          genuinely guest-accessible endpoint as missing allow_guest=True)
        - a non-literal `allow_guest=SOME_CONST` (previously indistinguishable
          from a confirmed-missing finding, though the value might be True
          at runtime -- now worded as a distinct "cannot verify" finding)

        The fourth shape from #1063 (a wrapper/factory decorator) is a
        documented, NOT fixed, blind spot -- see
        test_public_api_allow_guest_scan_wrapper_factory_is_a_known_blind_spot.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "decorator_shapes.py").write_text(
                "import frappe\n"
                "from frappe import whitelist as wl\n"
                "from verenigingen.utils.security.api_security_framework import (\n"
                "    OperationType,\n"
                "    public_api,\n"
                ")\n\n"
                "SOME_CONST = True\n\n"
                "@wl(allow_guest=True)\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def aliased_import_ok():\n"
                "    pass\n\n"
                "@wl()\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def aliased_import_broken():\n"
                "    pass\n\n"
                "@frappe.whitelist(True)\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def positional_allow_guest_ok():\n"
                "    pass\n\n"
                "@frappe.whitelist(False)\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def positional_allow_guest_false_still_broken():\n"
                "    pass\n\n"
                "@frappe.whitelist(allow_guest=SOME_CONST)\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def nonliteral_allow_guest():\n"
                "    pass\n"
            )
            api_files = list(tmp_path.rglob("*.py"))
            issues = find_public_api_allow_guest_issues(api_files)
            issue_text = "\n".join(issues)

            self.assertNotIn(
                "aliased_import_ok",
                issue_text,
                "An aliased `from frappe import whitelist as wl` must still "
                "be recognized as @frappe.whitelist (#1063).",
            )
            self.assertIn(
                "aliased_import_broken",
                issue_text,
                "An aliased `@wl()` with no allow_guest=True is a genuine "
                "violation and must be reported, not silently skipped as "
                "'no @frappe.whitelist decorator recognized' (#1063).",
            )
            self.assertNotIn(
                "positional_allow_guest_ok",
                issue_text,
                "`@frappe.whitelist(True)` sets allow_guest positionally "
                "per frappe.whitelist(allow_guest=False, ...)'s real "
                "signature -- must not be reported as missing (#1063).",
            )
            self.assertIn(
                "positional_allow_guest_false_still_broken",
                issue_text,
                "`@frappe.whitelist(False)` genuinely does not allow "
                "guests -- positional handling must not make this pass by "
                "accident.",
            )
            nonliteral_issues = [i for i in issues if "nonliteral_allow_guest" in i]
            self.assertEqual(
                len(nonliteral_issues),
                1,
                f"Expected exactly 1 finding for nonliteral_allow_guest, got: {issues}",
            )
            self.assertNotIn(
                "missing allow_guest=True",
                nonliteral_issues[0],
                "A non-literal allow_guest value cannot be statically "
                "verified as True and must still be surfaced for review "
                "(#1063), but worded distinctly from a confirmed-missing "
                "finding, since the value might genuinely be True at "
                "runtime.",
            )
            self.assertEqual(
                len(issues),
                3,
                f"Expected exactly 3 findings (the broken alias, the false "
                f"positional, and the non-literal), got: {issues}",
            )

    def test_public_api_allow_guest_scan_wrapper_factory_is_a_known_blind_spot(self):
        """
        Documents a DELIBERATELY UNFIXED shape from #1063.

        A decorator that internally calls `frappe.whitelist(allow_guest=True)`
        under a name other than "whitelist" (a wrapper/factory) cannot be
        resolved by this AST scan -- it has no way to know what an arbitrary
        callable does internally. This is the same class of blind spot
        CLAUDE.md documents for `handle_api_error`: decorator SHAPE both
        over- and under-approximates guest-reachability; only a runtime
        membership check sidesteps it.

        #1063's fix intentionally does NOT switch to a runtime
        (`frappe.guest_methods` membership) check here, because doing so
        surfaces an unrelated, independently-verified defect in this app's
        decorator-order handling: `frappe_whitelist_adapter.py` re-syncs
        `frappe.whitelisted` for a security-wrapped function but never
        `frappe.guest_methods`, so a `@public_api` (outer) /
        `@frappe.whitelist(allow_guest=True)` (inner) function is
        (confirmed via a live `frappe.is_whitelisted()` call as Guest)
        silently NOT guest-accessible at runtime -- see #1074. Until #1074
        is resolved, a runtime-membership version of this scan would be
        unsound for any decorator order other than the one actually used by
        all 34 real @public_api endpoints today (whitelist outermost).

        This test exists so making it pass later is a deliberate decision,
        not an accidental side effect of some other change: it must engage
        with #1074 first, not silently start relying on
        `frappe.guest_methods` identity.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "wrapper_factory.py").write_text(
                "import frappe\n"
                "from verenigingen.utils.security.api_security_framework import (\n"
                "    OperationType,\n"
                "    public_api,\n"
                ")\n\n"
                "def whitelist_guest(func):\n"
                '    """A factory that whitelists+allows guest under a name '
                "the scan cannot recognize as 'whitelist' (#1063).\"\"\"\n"
                "    return frappe.whitelist(allow_guest=True)(func)\n\n"
                "@whitelist_guest\n"
                "@public_api(operation_type=OperationType.PUBLIC)\n"
                "def hidden_behind_a_wrapper():\n"
                "    pass\n"
            )
            api_files = list(tmp_path.rglob("*.py"))
            issues = find_public_api_allow_guest_issues(api_files)
            # `hidden_behind_a_wrapper` never gets a "whitelist"-named
            # decorator in its decorator_list, so `whitelist_decorators` is
            # empty and the existing "no @frappe.whitelist at all is a
            # different, worse defect -- out of scope" branch silently
            # skips it.
            self.assertEqual(
                issues,
                [],
                "This characterizes a KNOWN blind spot (#1063/#1074), not "
                "a guarantee of correctness -- if this starts failing, "
                "either the scan started catching wrapper decorators "
                "(update this test and close the referenced follow-up) or "
                "something else changed.",
            )

    def test_no_standard_api_on_guest_endpoints(self):
        """
        Verify that guest-accessible endpoints don't use @standard_api.

        @standard_api requires authentication. If an endpoint should be
        accessible to guests (like membership application form), it must
        use @public_api instead.

        See find_standard_api_guest_naming_issues() for the two heuristic
        signals used and why this check cannot be exhaustive (#1056).
        """
        issues = find_standard_api_guest_naming_issues(self.get_api_files())

        if issues:
            self.fail(
                "Found potential guest endpoints using @standard_api:\n"
                + "\n".join(issues)
            )

    def test_standard_api_guest_naming_scan_catches_token_vocabulary(self):
        """
        Positive control for #1056.

        `fetch_public_signup_widget_config` (the planted example from #1056)
        matches none of the phrase regexes, but is built entirely from the
        token vocabulary ("public", "signup", "widget") and must be caught.
        An ordinary authenticated-sounding name must not be flagged, and
        "public" must not match as a mere substring of "publication" (#1056
        measured this exact false positive against the real codebase's
        `update_publication_status`).
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "control_1056.py").write_text(
                "import frappe\n"
                "from verenigingen.utils.security.api_security_framework import standard_api\n\n"
                "@frappe.whitelist()\n"
                "@standard_api\n"
                "def fetch_public_signup_widget_config():\n"
                '    """Guest-suggestive name matching none of the phrase regexes."""\n'
                "    return {}\n\n"
                "@frappe.whitelist()\n"
                "@standard_api\n"
                "def get_dashboard_stats():\n"
                "    return {}\n\n"
                "@frappe.whitelist()\n"
                "@standard_api\n"
                "def update_publication_status(name):\n"
                '    """Contains \'public\' as a SUBSTRING of \'publication\', not a token."""\n'
                "    return {}\n"
            )
            issues = find_standard_api_guest_naming_issues([tmp_path / "control_1056.py"])
            issue_text = "\n".join(issues)

            self.assertIn(
                "fetch_public_signup_widget_config",
                issue_text,
                "A name built from the token vocabulary must be caught even "
                "though no phrase regex matches it (#1056).",
            )
            self.assertNotIn(
                "get_dashboard_stats",
                issue_text,
                "An ordinary authenticated-sounding name must not be flagged.",
            )
            self.assertNotIn(
                "update_publication_status",
                issue_text,
                "'public' must not match as a substring of 'publication' "
                "(#1056 measured this false positive against the real "
                "codebase).",
            )
            self.assertEqual(
                len(issues),
                1,
                f"Expected exactly 1 planted violation, got: {issues}",
            )


class TestOperationResultFormat(EnhancedTestCase):
    """
    Test that API endpoints return properly formatted OperationResult.

    This catches issues where the frontend JS cannot properly unwrap
    the response because the format is inconsistent.
    """

    def test_operation_result_structure(self):
        """Verify OperationResult has expected structure for JS unwrapping"""
        # Test success case
        result = OperationResult.ok({"test": "data"}, message="Success")

        self.assertTrue(hasattr(result, "success"))
        self.assertTrue(hasattr(result, "data"))
        self.assertTrue(hasattr(result, "metadata"))

        self.assertTrue(result.success)
        self.assertEqual(result.data, {"test": "data"})
        # message is passed as metadata
        self.assertEqual(result.metadata.get("message"), "Success")

    def test_operation_result_fail_structure(self):
        """Verify OperationResult.fail has expected structure"""
        result = OperationResult.fail("Error occurred", errors=["error1"])

        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        # Fail uses error_message attribute
        self.assertEqual(result.error_message, "Error occurred")
        self.assertEqual(result.errors, ["error1"])

    def test_public_api_returns_operation_result(self):
        """Test that public APIs return OperationResult format"""
        from verenigingen.api.membership_application import get_application_form_data

        result = get_application_form_data()

        # Should be OperationResult or serialized dict
        if isinstance(result, OperationResult):
            # Check it can be converted to dict (for JSON serialization)
            result_dict = result.to_dict()
        elif isinstance(result, dict):
            # Already serialized (Frappe may auto-serialize)
            result_dict = result
        else:
            self.fail(f"Unexpected result type: {type(result)}")

        # Core fields must be present
        self.assertIn("success", result_dict, "Must have success field")
        self.assertIn("data", result_dict, "Must have data field")
        self.assertIn("timestamp", result_dict, "Must have timestamp field")
        # message is optional but commonly included via metadata
        # Don't require it as it depends on how the API was called


class TestCriticalOperationRulesExist(EnhancedTestCase):
    """
    Test that Critical Operation Rules exist for all public endpoints.

    Missing COR rules cause runtime errors when the security framework
    tries to look up rate limits and other security settings.
    """

    def get_public_api_functions(self) -> List[Tuple[str, str]]:
        """Extract all @public_api decorated functions from API files.

        Fails loudly if the directory cannot be resolved, instead of
        silently returning an incomplete (or empty) list of "endpoints
        missing COR rules" (#1027). Whether the scan mechanism itself is
        recursive is proven separately, against a synthetic tree, by
        TestPublicAPIDecoratorConsistency.test_api_directory_scan_is_recursive
        -- NOT by comparing file counts in this live directory (#1049).
        """
        api_dir = Path(frappe.get_app_path("verenigingen")) / "api"
        api_files = _recursive_py_files(api_dir)
        self.assertGreater(
            len(api_files),
            20,
            f"Expected a substantial number of API files under {api_dir}, found "
            f"{len(api_files)}. A near-empty scan means api_dir failed to resolve "
            "(#1027) rather than there being genuinely few files.",
        )
        functions = []

        for api_file in api_files:
            if api_file.name.startswith("_"):
                continue

            content = api_file.read_text()
            lines = content.split("\n")

            for i, line in enumerate(lines):
                if "@public_api" in line and not line.strip().startswith("#"):
                    # Find the function name
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if lines[j].strip().startswith("def "):
                            func_match = re.search(r"def (\w+)", lines[j])
                            if func_match:
                                functions.append(
                                    (api_file.stem, func_match.group(1))
                                )
                            break

        return functions

    def test_cor_rules_exist_for_public_endpoints(self):
        """Verify Critical Operation Rules exist for all public API endpoints"""
        public_functions = self.get_public_api_functions()
        missing_rules = []

        for module_name, func_name in public_functions:
            # Check various naming conventions for COR rules
            possible_names = [
                func_name,
                f"{module_name}_{func_name}",
                f"api_{func_name}",
            ]

            found = False
            for name in possible_names:
                if frappe.db.exists("Critical Operation Rule", name):
                    found = True
                    break

            if not found:
                missing_rules.append(f"{module_name}.{func_name}")

        if missing_rules:
            # This is a warning, not a failure, since generic fallback exists
            print(
                f"\nWARNING: Missing Critical Operation Rules for {len(missing_rules)} endpoints:\n"
                + "\n".join(f"  - {r}" for r in missing_rules[:20])
            )
            if len(missing_rules) > 20:
                print(f"  ... and {len(missing_rules) - 20} more")


class TestMembershipApplicationFormAccess(EnhancedTestCase):
    """
    End-to-end test for membership application form access.

    This test simulates what happens when a guest visits /apply_for_membership
    and the page tries to load form data.
    """

    def test_full_form_data_accessible_to_guest(self):
        """
        Simulate guest accessing membership application page.

        The page calls get_application_form_data() which should:
        1. Not require authentication
        2. Return membership types
        3. Return chapters
        4. Return in OperationResult format
        """
        with _with_user("Guest"):
            try:
                from verenigingen.api.membership_application import get_application_form_data

                result = get_application_form_data()

                # Extract data from OperationResult
                if isinstance(result, OperationResult):
                    self.assertTrue(
                        result.success,
                        f"Form data fetch failed: {result.error_message}"
                    )
                    data = result.data
                elif isinstance(result, dict):
                    # Handle serialized OperationResult or legacy dict
                    if "data" in result and isinstance(result.get("data"), dict):
                        # Serialized OperationResult - unwrap
                        data = result["data"]
                    else:
                        # Legacy dict format
                        data = result
                else:
                    self.fail(f"Unexpected result type: {type(result)}")

                # Verify required data is present
                self.assertIn(
                    "membership_types",
                    data,
                    f"Form data must include membership_types. Got keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}",
                )
                self.assertIn(
                    "chapters",
                    data,
                    f"Form data must include chapters. Got keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}",
                )

                # Verify data is not empty
                # (could be empty in test env, but structure should be list)
                self.assertIsInstance(
                    data.get("membership_types"),
                    list,
                    "membership_types should be a list",
                )
                self.assertIsInstance(
                    data.get("chapters"),
                    list,
                    "chapters should be a list",
                )

            except frappe.PermissionError as e:
                self.fail(
                    f"CRITICAL: Guest cannot access form data - this breaks /apply_for_membership page!\n"
                    f"Error: {str(e)}\n"
                    f"Fix: Ensure @public_api decorator with @frappe.whitelist(allow_guest=True)"
                )
