#!/usr/bin/env python3
"""
Test Quality Enforcement Script
==============================

Pre-commit hook to enforce tiered testing standards based on test type.
Implements the testing strategy from TESTING_STANDARDS.md.

Usage:
    python scripts/validation/test_quality_enforcer.py [files...]

Exit codes:
    0: All files pass validation
    1: Validation failures found
    2: Script error

Tiered Validation Rules:
- Tier 1 (Unit tests): Mocks allowed for isolated service testing
  - Path: tests/unit/ or *_unit.py or *_unit_test.py
  - Database mocks permitted for testing pure business logic

- Tier 2 (Integration tests): External mocks only
  - Path: tests/integration/ or tests/ (default) or *_integration.py
  - Database mocks BLOCKED - use real operations with Enhanced Test Factory
  - External service mocks (email, HTTP, etc.) allowed with justification

- Tier 3 (Security tests): No mocking permitted
  - Path: tests/security/ or *_security.py or *_permission*.py
  - ALL mocks blocked - must test real permission boundaries
"""

import ast
import io
import os
import re
import sys
import argparse
import tokenize
import warnings
from collections import Counter, namedtuple
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_BASELINE = Path(__file__).with_name("test_quality_baseline.txt")

# Mirrors error_swallow_validator.py. Without this, --update-baseline walks agent
# worktrees: measured 12,574 test files against 1,398, the difference being copies
# under .claude/worktrees/. A locally regenerated baseline then cannot match CI's.
PRUNE_DIRS = {"node_modules", ".git", "__pycache__", "worktrees", ".claude", "archived"}

# A single violation, in the form the baseline is keyed on. `qualname` is resolved
# from the AST, not by scanning backwards for `def ` -- see _scope_map.
Finding = namedtuple("Finding", "path lineno qualname kind message")


def _rel(path) -> str:
    """Repo-relative path, whatever form the caller passed.

    pre-commit passes bare repo-relative paths; the whole-tree walk produced
    './'-prefixed ones. Without normalising here, every key the hook computes is
    absent from the baseline and reads as a brand-new violation.
    """
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def iter_test_files(root: str = ".") -> Iterator[str]:
    """Yield test files under `root`, skipping vendor and worktree copies.

    This is a strict SUPERSET of what the pre-commit hook sees -- the hook's
    `exclude` in .pre-commit-config.yaml drops `scripts/.*` and `*debug*`, which are
    scanned here. That direction is deliberate and must be preserved: the hook can
    then never compute a key the baseline does not cover, which would read as a
    brand-new violation on untouched code. Narrowing this walk to match the hook
    would invert that, and a later widening of the hook would break every branch.
    """
    enforcer = TestQualityEnforcer()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for name in filenames:
            candidate = os.path.join(dirpath, name)
            if enforcer._is_test_file(candidate):
                yield candidate


def _scope_map(content: str) -> List[Tuple[str, int, int]]:
    """Return (qualified name, first line, last line) for every function.

    Replaces a backward scan for `def `, which got four things wrong: it attributed
    decorator lines to the PREVIOUS function (and mock findings land on decorator
    lines by construction), attributed module-level code to the last `def` seen,
    bled from an outer function into a nested one, and never qualified by class.

    The nested case was not cosmetic: a bypass written in an allowlisted
    `_ensure_user` was reported against a nested `_apply_role_profile`, which is not
    allowlisted -- so the old helper manufactured a violation.

    Ranges include `decorator_list`, so a finding on `@patch(...)` belongs to the
    function it decorates.
    """
    try:
        # Parsing someone else's source re-emits their SyntaxWarnings (e.g. an
        # invalid escape in a non-raw string). That is their file's business, not
        # a finding, and it would pollute this tool's output.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(content)
    except SyntaxError:
        return []

    scopes: List[Tuple[str, int, int]] = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = f"{prefix}{child.name}"
                start = min(
                    [child.lineno] + [d.lineno for d in getattr(child, "decorator_list", [])]
                )
                scopes.append((qn, start, child.end_lineno or start))
                walk(child, f"{qn}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return scopes


def _qualname_for(scopes: List[Tuple[str, int, int]], lineno: int) -> str:
    """Innermost function containing `lineno`, or '<module>'."""
    best = None
    for qn, start, end in scopes:
        if start <= lineno <= end:
            if best is None or (start >= best[1] and end <= best[2]):
                best = (qn, start, end)
    return best[0] if best else "<module>"


def _protected_spans(content: str) -> Dict[int, List[Tuple[int, int]]]:
    """Per-line column spans covered by a comment or a string literal.

    Used to drop a match that lies ENTIRELY inside one of these. The distinction
    matters more than it looks: 14 of this file's 18 patterns require a quote --
    every database mock, every never-mock pattern, and `set_user("Administrator")`
    -- so they match inside a STRING token by construction. Suppressing any match
    that merely touches a string would silence 58 of 120 real findings and leave
    every false-positive test passing.

    A quote-requiring pattern's match STARTS at the call (`patch(`, `set_user(`),
    outside the string, so it survives. A bare mention inside a literal, e.g.
    `banned = ["NO ignore_permissions=True"]`, is contained and is dropped.
    """
    spans: Dict[int, List[Tuple[int, int]]] = {}

    def add(line: int, start: int, end: int):
        spans.setdefault(line, []).append((start, end))

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: fall back to the line-based docstring tracker rather
        # than returning no protection at all, which would turn every documented
        # example of a banned pattern into a finding.
        for lineno in TestQualityEnforcer._docstring_line_numbers(None, content.split("\n")):
            add(lineno, 0, 10**6)
        return spans

    for tok in tokens:
        if tok.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        if srow == erow:
            add(srow, scol, ecol)
        else:
            # Multi-line string: the first and last lines are partly covered, the
            # ones between entirely.
            add(srow, scol, 10**6)
            for line in range(srow + 1, erow):
                add(line, 0, 10**6)
            add(erow, 0, ecol)
    return spans


def _patch_alias_names(tree) -> set:
    """Local names bound to unittest.mock.patch, including aliased imports."""
    names = {"patch"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("unittest.mock", "mock"):
            for a in node.names:
                if a.name == "patch":
                    names.add(a.asname or a.name)
    return names


def _target_of(node) -> str:
    """The patched target as a string, or "" if it cannot be resolved statically.

    An f-string yields only its LITERAL segments joined, e.g.
    f"{MODULE}.frappe.get_doc" -> ".frappe.get_doc". That is enough for the
    suffix-anchored rules, and it is why those rules must stay suffix-anchored.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # Only when the string ENDS in a literal. Every rule here is
        # suffix-anchored, so a trailing {placeholder} means the real target
        # continues past what is visible and the anchor would match the wrong
        # thing: f"frappe.get_doc{suffix}" would otherwise resolve to exactly
        # "frappe.get_doc" and be flagged, even though at runtime it may be
        # frappe.get_doc_helper. Refusing to resolve it is a false negative;
        # resolving it is a false positive that fails an innocent PR.
        if not (node.values and isinstance(node.values[-1], ast.Constant)
                and isinstance(node.values[-1].value, str)):
            return ""
        return "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    return ""


def _patch_targets(content: str) -> List[Tuple[int, str]]:
    """Every statically-resolvable mock target, as (line of the call, target).

    This is the ONLY way mock targets are found. The rules used to be line
    regexes anchored on `patch(` immediately followed by a quote, which missed a
    Black-wrapped decorator, `patch.object`, and an f-string target. Measured
    before that changed: 225 mocks in the app named a prohibited target, the line
    regexes saw 167, and the hook nominally responsible for blocking them --
    scripts/validation/archived/block_inappropriate_mocks.py, since deleted --
    reported 1.

    Keeping BOTH mechanisms was itself a defect: the line loop reports only the
    first pattern that matches a line, so `with patch("frappe.get_doc"),
    patch("frappe.get_all"):` recorded one finding and suppressed the other.
    Two detectors to reconcile is the same dual-maintenance hazard that produced
    #793, so there is now one.

    Deliberately NOT resolved, because the target is not statically knowable or
    the call is not a target-and-attribute patch:
      * a target built from a variable  -- patch(some_module_path)
      * a target built by concatenation -- patch("a." + "b")  (ast.BinOp)
      * an f-string ending in a placeholder -- see _target_of
      * `patch.multiple(...)`           -- attributes arrive as kwargs
      * `patch.dict(...)`               -- patches a mapping, not an attribute
    An f-string IS resolved, via its literal segments (see _target_of).
    """
    out: List[Tuple[int, str]] = []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return out

    aliases = _patch_alias_names(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_object = False
        if isinstance(func, ast.Name):
            if func.id not in aliases:
                continue
        elif isinstance(func, ast.Attribute):
            if func.attr == "object":
                base = func.value
                base_name = (
                    base.attr if isinstance(base, ast.Attribute)
                    else base.id if isinstance(base, ast.Name) else None
                )
                if base_name not in aliases:
                    continue
                is_object = True
            elif func.attr in aliases:
                pass  # mock.patch(...) / unittest.mock.patch(...)
            else:
                continue
        else:
            continue

        if is_object:
            # patch.object(SomeClass, "attr") -> "SomeClass.attr", so a rule keyed
            # on the attribute still matches.
            parts = []
            if node.args:
                first = node.args[0]
                parts.append(
                    first.id if isinstance(first, ast.Name)
                    else first.attr if isinstance(first, ast.Attribute) else ""
                )
            if len(node.args) > 1:
                parts.append(_target_of(node.args[1]))
            target = ".".join(x for x in parts if x)
        else:
            target = _target_of(node.args[0]) if node.args else ""

        if target:
            out.append((node.lineno, target))

    return out


def counts_of(findings) -> Dict[str, int]:
    """Collapse findings to the baseline's `path::qualname::kind` -> count."""
    return Counter(f"{f.path}::{f.qualname}::{f.kind}" for f in findings)


def regressions(counts: Dict[str, int], baseline: Dict[str, int]) -> Dict[str, int]:
    """Keys that are new, or whose count rose above the baseline.

    Fires upward only. A file absent from a partial (pre-commit) scan contributes
    no key at all, so a partial scan can never read as "count decreased".
    """
    return {k: v for k, v in counts.items() if v > baseline.get(k, 0)}


def load_baseline(path: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
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


def write_baseline(path: Path, counts: Dict[str, int]) -> None:
    header = [
        "# Known test-quality violations -- the ratchet baseline for",
        "# scripts/validation/test_quality_enforcer.py. Format:",
        "#     <path>::<qualified function>::<kind>::<count>",
        "#",
        "# A change fails only if it introduces a key NOT covered here, or raises the",
        "# count for a key already listed. Line numbers are deliberately absent --",
        "# they rot on any edit above them.",
        "#",
        "# This file should only ever SHRINK. Do not regenerate it to make a new",
        "# finding go away; fix the test instead. The one legitimate reason it may",
        "# GROW is a change to the enforcer's own detection rules, which must land in",
        "# the same commit as the regeneration.",
        "#",
        "# UNDERSTATES the real debt: _check_all_mocks_blocked still honours an",
        "# unpoliced escape hatch (`# Mock justified:` / `# External service` /",
        "# `# Infrastructure` within 3 lines), used 361 times across 77 files. Whatever",
        "# those suppress is invisible here. Policing them would change these counts and",
        "# so must not be entangled with generating this file.",
        "",
    ]
    body = [f"{k}::{v}" for k, v in sorted(counts.items())]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


class TestTier:
    """Test tier enumeration"""
    UNIT = 1        # Unit tests - mocks allowed
    INTEGRATION = 2  # Integration tests - external mocks only
    SECURITY = 3     # Security tests - no mocks allowed


class TestQualityEnforcer:
    """Enforces tiered test quality standards"""

    def __init__(self):
        self.errors = []
        self.warnings = []
        # Structured twin of self.errors, carrying the baseline key. self.errors
        # stays the human-readable channel; nothing downstream parses it.
        self.findings: List[Finding] = []
        self._scopes: List[Tuple[str, int, int]] = []
        self._protected: Dict[int, List[Tuple[int, int]]] = {}


        # Configuration access patterns (always allowed - external service config)
        self.allowed_config_mocks = [
            r"frappe\.db\.get_single_value.*Settings",
            r"frappe\.db\.get_global_config",
            r"frappe\.db\.get_single.*Settings",
        ]

        # External service mocks (allowed in Tier 1 & 2, blocked in Tier 3)
        self.external_service_mocks = [
            r"patch\s*\(\s*['\"]frappe\.sendmail['\"]",  # Email service
            r"patch\s*\(\s*['\"]requests\.post['\"]",    # HTTP requests
            r"patch\s*\(\s*['\"]requests\.get['\"]",     # HTTP requests
            r"patch\s*\(\s*['\"]smtplib\.",              # SMTP service
            r"patch\s*\(\s*['\"]urllib\."                # URL operations
        ]
        
        self.infrastructure_mocks = [
            r"patch\s*\(\s*['\"]redis\.Redis['\"]",      # Redis cache
            r"patch\s*\(\s*['\"]frappe\.cache['\"]",     # Frappe cache
            r"patch\s*\(\s*['\"]celery\.",               # Background tasks
            r"patch\s*\(\s*['\"]frappe\.publish_realtime['\"]"  # WebSocket
        ]
        

        self.business_workflow_mock_targets = [
            r"send_payment_reminder_email", r"create_membership_invoice",
            r"suspend_member", r"get_member_suspension_status",
            r"(?:^|\.)frappe\.render_template$",
        ]

        # The same rules keyed on the TARGET STRING alone, for the AST pass in
        # _matching_ast_targets(). The patterns above need `patch(` and the quoted
        # target on ONE line, which is exactly the blind spot #793 is about.
        # SUFFIX-anchored, not exact. The line patterns above require the quote
        # immediately before `frappe`, so they only ever match a bare
        # patch("frappe.db.sql") -- while the idiomatic form patches where the name
        # is looked up: patch("verenigingen.<...>.donation_summary.frappe.db.sql").
        # That module-qualified shape was the ONE finding the deleted
        # block_inappropriate_mocks.py still reported (its patterns carried a
        # `[^'\"]*` prefix), so anchoring these to the start would have dropped it
        # along with the hook. Anchoring to the END keeps `my_frappe.get_doc_helper`
        # from matching while catching every module path. #793
        self.database_mock_targets = [
            r"(?:^|\.)frappe\.get_doc$", r"(?:^|\.)frappe\.get_all$",
            r"(?:^|\.)frappe\.db\.exists$", r"(?:^|\.)frappe\.db\.set_value$",
            r"(?:^|\.)frappe\.db\.sql$", r"(?:^|\.)frappe\.db\.get_list$",
            r"(?:^|\.)frappe\.db\.count$", r"(?:^|\.)frappe\.db\.get_value$",
            r"(?:^|\.)frappe\.new_doc$",
        ]
        self.never_mock_targets = [r"validate_", r"business_rule", r"process_"]
        
        # Permission bypass patterns (including hidden bypasses)
        self.permission_bypasses = [
            r"ignore_permissions\s*=\s*True",
            r"\.insert\s*\(\s*ignore_permissions\s*=\s*True",
            r"\.save\s*\(\s*ignore_permissions\s*=\s*True",
            r"\.delete\s*\(\s*ignore_permissions\s*=\s*True",
            r"frappe\.set_user\s*\(\s*['\"]Administrator['\"]",  # Hidden bypass via user switching
            r"frappe\.session\.user\s*=\s*['\"]Administrator['\"]" # Direct session manipulation
        ]

    def _determine_test_tier(self, file_path: str) -> int:
        """
        Determine which testing tier a file belongs to.

        Tier 1 (Unit): tests/unit/, tests/**/unit/, *_unit.py, *_unit_test.py
        Tier 2 (Integration): tests/integration/, tests/, *_integration.py (default)
        Tier 3 (Security): tests/security/, tests/**/security/, *_security.py, *_permission*.py
        """
        path_lower = file_path.lower()
        name = Path(file_path).name.lower()

        # Tier 3: Security tests - most restrictive
        # Match any "/security/" segment under a tests dir (e.g. tests/security/,
        # tests/backend/security/) so layout variants share the same rules.
        if any([
            "/tests/security/" in path_lower,
            "/security/tests/" in path_lower,
            "/tests/backend/security/" in path_lower,
            name.endswith("_security.py"),
            name.endswith("_security_test.py"),
            "permission" in name and "test" in name,
        ]):
            return TestTier.SECURITY

        # Tier 1: Unit tests - least restrictive
        # Same pattern: any "/unit/" segment under a tests dir counts.
        if any([
            "/tests/unit/" in path_lower,
            "/unit/tests/" in path_lower,
            "/tests/backend/unit/" in path_lower,
            name.endswith("_unit.py"),
            name.endswith("_unit_test.py"),
        ]):
            return TestTier.UNIT

        # Tier 2: Integration tests - default for everything else
        return TestTier.INTEGRATION

    def _get_tier_name(self, tier: int) -> str:
        """Get human-readable tier name"""
        return {
            TestTier.UNIT: "Unit (Tier 1)",
            TestTier.INTEGRATION: "Integration (Tier 2)",
            TestTier.SECURITY: "Security (Tier 3)",
        }.get(tier, "Unknown")

    def validate_file(self, file_path: str) -> bool:
        """Validate a single test file against tiered quality standards"""
        if not self._is_test_file(file_path):
            return True

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Resolved once per file: both are needed by every check below.
            self._scopes = _scope_map(content)
            self._protected = _protected_spans(content)

            # Determine which tier this test belongs to
            tier = self._determine_test_tier(file_path)
            file_valid = True

            # Apply tier-specific validation rules
            if tier == TestTier.SECURITY:
                # Tier 3: Block ALL mocks
                file_valid &= self._check_all_mocks_blocked(file_path, content)
            elif tier == TestTier.INTEGRATION:
                # Tier 2: Block database mocks, allow external service mocks
                file_valid &= self._check_database_mocks(file_path, content)
                file_valid &= self._check_business_workflow_mocks(file_path, content)
                file_valid &= self._check_mock_justifications(file_path, content)
            # Tier 1 (Unit): All mocks allowed - no mock checks

            # Always check for business logic mocks (never allowed in any tier)
            file_valid &= self._check_never_mock_patterns(file_path, content)

            # Check for permission bypasses (context-aware)
            file_valid &= self._check_permission_bypasses(file_path, content)

            # Check Enhanced Test Factory usage for integration tests
            if tier == TestTier.INTEGRATION:
                file_valid &= self._check_enhanced_test_factory_usage(file_path, content)

            # Validate field references
            file_valid &= self._check_field_references(file_path, content)

            return file_valid

        except Exception as e:
            self.errors.append(f"{file_path}: Error reading file - {str(e)}")
            return False

    def _is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file that should be validated"""
        path = Path(file_path)
        path_str = str(path).replace("\\", "/")

        # Skip fixture / helper / conftest files even if they live under tests/.
        # These provide infrastructure for tests rather than being tests themselves,
        # and their use of permission bypasses or DB writes is appropriate.
        helper_path_markers = [
            "/tests/fixtures/",
            "/tests/conftest",
            "/tests/setup/",
            "/tests/config/",
            "/tests/utils/",
        ]
        if any(marker in path_str for marker in helper_path_markers):
            return False
        if path.name == "conftest.py":
            return False
        # A file whose SUBJECT is a factory (e.g. `test_payment_entry_factory.py`)
        # is a real test module by this repo's `test_`-prefix convention, not a
        # fixture helper -- #798. Only a name that does NOT start with `test_`
        # (`enhanced_test_factory.py`, `factory_helper.py`, `sepa_test_factory.py`)
        # is the helper shape this rule exists to skip.
        if not path.name.startswith("test_") and (
            "_factory" in path.name or path.name.startswith("factory_")
        ):
            return False

        # Check for test file patterns
        test_indicators = [
            path.name.startswith('test_'),
            '/tests/' in path_str,
            path.name.endswith('_test.py'),
            'TestCase' in path.name
        ]

        return any(test_indicators) and path.suffix == '.py'

    def _docstring_line_numbers(self, lines: list) -> set:
        """Return 1-based line numbers contained in any triple-quoted docstring.

        We track both \"\"\" and ''' delimiters so the various mock-pattern
        scans can ignore @patch examples that appear inside module / class /
        function docstrings (typically used to describe what was eliminated
        or refactored away).
        """
        inside = False
        delim = None
        result = set()
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            opened_or_closed = False
            for d in ('"""', "'''"):
                if d in stripped:
                    count = stripped.count(d)
                    if not inside:
                        if count % 2 == 1:
                            inside = True
                            delim = d
                            result.add(idx)
                            opened_or_closed = True
                    elif delim == d:
                        if count % 2 == 1:
                            result.add(idx)
                            inside = False
                            delim = None
                            opened_or_closed = True
                    break
            if inside and not opened_or_closed:
                result.add(idx)
        return result

    def _match_is_protected(self, line_num: int, match) -> bool:
        """True when the match lies ENTIRELY inside a comment or string literal.

        Containment, not overlap. A pattern that requires a quote --
        `patch("frappe.db.sql")`, `set_user("Administrator")` -- starts at the call,
        outside the literal, so it is never protected. A bare mention inside a
        literal is.
        """
        for start, end in self._protected.get(line_num, ()):
            if match.start() >= start and match.end() <= end:
                return True
        return False

    def _search(self, pattern: str, line: str, line_num: int):
        """re.search, ignoring matches that are only quoted or commented text."""
        match = re.search(pattern, line, re.IGNORECASE)
        if match is not None and self._match_is_protected(line_num, match):
            return None
        return match

    def _record(self, file_path: str, line_num: int, kind: str, message: str) -> None:
        """Append to both the human channel and the structured, keyed one."""
        self.errors.append(message)
        self.findings.append(
            Finding(
                path=_rel(file_path),
                lineno=line_num,
                qualname=_qualname_for(self._scopes, line_num),
                kind=kind,
                message=message,
            )
        )

    def _matching_ast_targets(self, content, target_patterns):
        """Mock targets matching `target_patterns`, found structurally.

        The single source of mock findings. See _patch_targets for what is and is
        not statically resolvable, and why keeping a second line-regex detector
        alongside this was itself a defect.
        """
        return [
            (lineno, target)
            for lineno, target in _patch_targets(content)
            if any(re.search(pat, target) for pat in target_patterns)
        ]
    def _check_database_mocks(self, file_path: str, content: str) -> bool:
        """Database operation mocks (blocked in Tier 2 integration tests)."""
        valid = True
        for line_num, target in self._matching_ast_targets(
            content, self.database_mock_targets
        ):
            if any(re.search(a, target, re.IGNORECASE) for a in self.allowed_config_mocks):
                continue
            self._record(
                file_path,
                line_num,
                "DATABASE MOCK",
                f"{file_path}:{line_num}: DATABASE MOCK in integration test: "
                f'patch("{target}")\n'
                f"  -> Database operations must not be mocked in integration tests\n"
                f"  -> Use real database operations with Enhanced Test Factory\n"
                f"  -> Move to tests/unit/ if testing isolated service logic\n"
                f"  -> See docs/test_remediation_plan/TESTING_STANDARDS.md",
            )
            valid = False
        return valid
    def _check_business_workflow_mocks(self, file_path: str, content: str) -> bool:
        """Business workflow mocks (Tier 2; Tier 1 may mock, Tier 3 blocks all)."""
        valid = True
        for line_num, target in self._matching_ast_targets(
            content, self.business_workflow_mock_targets
        ):
            self._record(
                file_path,
                line_num,
                "BUSINESS WORKFLOW MOCK",
                f"{file_path}:{line_num}: BUSINESS WORKFLOW MOCK in integration test: "
                f'patch("{target}")\n'
                f"  -> This builds a document or drives a workflow; mocking it\n"
                f"     removes the thing under test\n"
                f"  -> Mock only the external boundary (e.g. frappe.sendmail)\n"
                f"  -> Move to tests/unit/ if testing isolated service logic",
            )
            valid = False
        return valid
    def _check_all_mocks_blocked(self, file_path: str, content: str) -> bool:
        """Check that the security-sensitive boundary isn't mocked (Tier 3).

        Security tests must NOT mock the auth/permission/signature layer they
        are supposed to verify. They MAY mock external infrastructure (HTTP
        clients, IP/secret retrievers, cache) so the test can drive the
        boundary code with controlled inputs — provided the mock carries a
        ``# Mock justified:`` comment within 3 lines, mirroring Tier 2.
        """
        valid = True
        lines = content.split("\n")
        mock_pattern = r"(?<![A-Za-z0-9_])@?patch\s*\("

        # Patterns that name external infrastructure or Frappe runtime context
        # rather than the boundary under test (auth check, permission boundary,
        # signature verification). These mirror the Tier 2 allowed lists plus
        # the Frappe context plumbing security tests typically need to drive
        # the boundary code through scenarios.
        infrastructure_for_security = (
            self.external_service_mocks
            + self.infrastructure_mocks
            + [
                # External lookups used by security boundary code
                r"patch\s*\(\s*['\"][^'\"]*\.fetch_[^'\"]+['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.get_request_ip['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.get_webhook_secret['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.verify_webhook_ip['\"]",
                # Frappe runtime context: session, request, response, roles, db.
                # Mocking these is plumbing — the boundary itself (permission
                # check, auth hook, signature verification) is not what's being
                # faked.
                r"patch\s*\(\s*['\"]frappe\.session(['\"\.])",
                r"patch\s*\(\s*['\"]frappe\.local\.",
                r"patch\s*\(\s*['\"]frappe\.request(['\"\.])",
                r"patch\s*\(\s*['\"]frappe\.db\.",
                r"patch\s*\(\s*['\"]frappe\.get_roles['\"]",
                r"patch\s*\(\s*['\"]frappe\.get_doc['\"]",
                r"patch\s*\(\s*['\"]frappe\.get_all['\"]",
                r"patch\s*\(\s*['\"]frappe\.get_single['\"]",
                r"patch\s*\(\s*['\"]frappe\.new_doc['\"]",
                r"patch\s*\(\s*['\"]frappe\.get_site_config['\"]",
                r"patch\s*\(\s*['\"]frappe\.installer\.",
                r"patch\s*\(\s*['\"]frappe\.log_error['\"]",
                r"patch\s*\(\s*['\"]frappe\.throw['\"]",
                # Standard library plumbing
                r"patch\s*\(\s*['\"]importlib\.",
                r"patch\s*\(\s*['\"]subprocess\.",
                r"patch\s*\(\s*['\"]json\.",
                # External API clients (Mollie, eBoekhouden, etc.)
                r"patch\s*\(\s*['\"]mollie\.",
                r"patch\s*\(\s*['\"]eboekhouden\.",
                # Audit / observability helpers — not the security boundary
                r"patch\s*\(\s*['\"][^'\"]*log_security_audit['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.audit_log['\"]",
                r"patch\s*\(\s*['\"]frappe\.logger['\"]",
                r"patch\s*\(\s*['\"]frappe\.get_request_header['\"]",
                r"patch\s*\(\s*['\"]frappe\.get_meta['\"]",
                r"patch\s*\(\s*['\"]secrets\.",
                # Security wrappers / status helpers around the boundary, not
                # the boundary's own check itself. (frappe.has_permission,
                # frappe.auth.*, verify_webhook_signature etc. remain banned.)
                r"patch\s*\(\s*['\"][^'\"]*\.secure_document_operation['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.check_security_status['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.check_current_security_status['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.generate_session_secret['\"]",
                r"patch\s*\(\s*['\"][^'\"]*\.verify_document_integrity['\"]",
                r"patch\s*\(\s*['\"][^'\"]*secure_operations\.[a-zA-Z_]+['\"]",
            ]
        )

        for line_num, line in enumerate(lines, 1):
            if not self._search(mock_pattern, line, line_num):
                continue

            # For multi-line patch(...) calls, the target string sits on a
            # later line. Stitch together up to the next 3 lines so the
            # infrastructure-pattern regex can see the full target.
            scan_window = line
            for offset in (1, 2, 3):
                if "(" in line and ")" in line[line.index("("):]:
                    break
                idx = (line_num - 1) + offset
                if idx < len(lines):
                    scan_window += " " + lines[idx]

            # Allow if the patch target is infrastructure AND has a justification
            # comment within 3 lines on either side.
            is_infrastructure = any(
                re.search(p, scan_window, re.IGNORECASE) for p in infrastructure_for_security
            )
            justification_found = False
            if is_infrastructure:
                start = max(0, line_num - 4)
                end = min(len(lines), line_num + 3)
                for i in range(start, end):
                    if i < len(lines) and (
                        "# Mock justified:" in lines[i]
                        or "# External service" in lines[i]
                        or "# Infrastructure" in lines[i]
                    ):
                        justification_found = True
                        break

            if is_infrastructure and justification_found:
                continue

            self._record(
                file_path,
                line_num,
                "MOCK",
                f"{file_path}:{line_num}: MOCK in security test: {line.strip()}\n"
                f"  -> Security tests must not mock the auth/permission boundary itself\n"
                f"  -> Infrastructure mocks (HTTP, IP, secret retrieval) are allowed\n"
                f"     when annotated with # Mock justified: <reason>\n"
                f"  -> See docs/test_remediation_plan/TESTING_STANDARDS.md (Tier 3)",
            )
            valid = False

        return valid

    def _check_never_mock_patterns(self, file_path: str, content: str) -> bool:
        """Business logic mocks that should never be allowed, in any tier."""
        valid = True
        for line_num, target in self._matching_ast_targets(
            content, self.never_mock_targets
        ):
            self._record(
                file_path,
                line_num,
                "BUSINESS LOGIC MOCK PROHIBITED",
                f"{file_path}:{line_num}: BUSINESS LOGIC MOCK PROHIBITED: "
                f'patch("{target}")\n'
                f"  -> Business logic and validation functions must NEVER be mocked\n"
                f"  -> This defeats the purpose of integration testing\n"
                f"  -> Use real business logic to catch actual bugs\n"
                f"  -> See docs/testing/TESTING_STANDARDS.md for correct patterns",
            )
            valid = False
        return valid
    def _check_permission_bypasses(self, file_path: str, content: str) -> bool:
        """Check for permission bypasses in test files"""
        valid = True
        lines = content.split('\n')

        # Check if this is a test factory infrastructure file
        is_test_factory = '_factory' in os.path.basename(file_path)

        # Allow permission bypasses only in specific contexts
        allowed_contexts = [
            'setUp',
            'setUpClass',
            'create_test_data',
            'tearDown',
            'cleanup'
        ]
        
        # Pre-compute docstring line numbers via the shared helper, which
        # correctly handles single-line """text""" docstrings (the previous
        # inline tracker flipped the flag once and stayed "inside" forever).

        # Mock-assertion patterns that mention ignore_permissions=True as a
        # called-with argument, not as a real bypass (e.g. asserting that
        # production code was invoked with the flag).
        mock_assertion_patterns = [
            re.compile(r"assert_called(_once)?(_with)?\s*\("),
            re.compile(r"\.call_args"),
            re.compile(r"\.call_args_list"),
        ]

        for line_num, line in enumerate(lines, 1):
            # Skip mock-call assertions — these reference ignore_permissions=True
            # as the expected argument to a mocked function, not as a real bypass.
            if any(p.search(line) for p in mock_assertion_patterns):
                continue

            # Skip ``frappe.delete_doc(..., force=True, ignore_permissions=True)``
            # — that combination is the canonical "force-delete a test fixture"
            # call. The force flag itself signals cleanup intent, and these
            # frequently appear inside ``finally:`` blocks of test methods that
            # otherwise can't satisfy the function-name allowlist.
            if re.search(
                r"frappe\.delete_doc\s*\([^)]*\bforce\s*=\s*True[^)]*\bignore_permissions\s*=\s*True",
                line,
            ) or re.search(
                r"frappe\.delete_doc\s*\([^)]*\bignore_permissions\s*=\s*True[^)]*\bforce\s*=\s*True",
                line,
            ):
                continue

            for pattern in self.permission_bypasses:
                if self._search(pattern, line, line_num):
                    # The allowlist below matches on the BARE function name, as it
                    # always has; only the baseline key is qualified. Resolving via
                    # the AST also fixes the case where a bypass in an allowlisted
                    # outer function was attributed to a nested helper that is not
                    # allowlisted -- a violation the old backward scan invented.
                    qualname = _qualname_for(self._scopes, line_num)
                    context = qualname.rsplit(".", 1)[-1]

                    # Check if context is allowed (static list or pattern match).
                    # Test setup helpers come in many naming conventions in this
                    # repo — broaden beyond the canonical setUp/tearDown to catch
                    # legitimate fixture creation in private/utility helpers.
                    context_lower = context.lower()
                    is_allowed = (
                        context in allowed_contexts or
                        'cleanup' in context_lower or       # cleanup methods
                        'teardown' in context_lower or      # teardown variants
                        context.startswith('create_test') or  # test data creation
                        context.startswith('ensure_test') or  # test setup utilities
                        context.startswith('ensure_') or    # get-or-create fixture helpers
                        context.startswith('make_') or      # factory-style helpers
                        context.startswith('build_') or     # builder helpers
                        context.startswith('setup_') or     # public setup helpers
                        context.startswith('fixture_') or   # fixture loaders
                        context.startswith('load_') or      # data loaders
                        '_ensure_' in context or            # utility methods
                        '_create_' in context or            # factory methods
                        '_make_' in context or              # private builders
                        '_build_' in context or             # private builders
                        '_setup_' in context or             # private setup helpers
                        '_fixture_' in context or           # private fixture loaders
                        '_load_' in context or              # private data loaders
                        '_restore_' in context or           # restore helpers (cleanup-like)
                        '_backup_' in context or            # backup helpers
                        '_with_' in context or              # _with_admin_user, _with_role
                        '_as_' in context or                # _as_admin, _as_user
                        '_insert_' in context or            # _insert_test_doc, _insert_for_test
                        '_persist_' in context or           # _persist_test_data
                        '_link_' in context or              # _link_member_to_user
                        '_register_' in context or          # _register_test_user
                        '_grant_' in context or             # _grant_test_role
                        (is_test_factory and context.startswith('_')) or  # private factory methods
                        (is_test_factory and context.startswith('create_'))  # public factory methods
                    )

                    if not is_allowed:
                        self._record(
                            file_path,
                            line_num,
                            "PERMISSION BYPASS",
                            f"{file_path}:{line_num}: PERMISSION BYPASS detected in test logic: {line.strip()}\n"
                            f"  -> Found in context: {context}\n"
                            f"  -> Permission bypasses only allowed in test setup/teardown/factory methods\n"
                            f"  -> Test actual permission boundaries instead of bypassing them\n"
                            f"  -> See docs/testing/TESTING_STANDARDS.md for correct patterns",
                        )
                        valid = False

                    # One finding per line. `ignore_permissions\s*=\s*True` is a
                    # strict superset of the .insert/.save/.delete variants below
                    # it, so without this every such site was reported twice --
                    # 53 of 174 raw findings on develop.
                    break

        return valid

    def _check_mock_justifications(self, file_path: str, content: str) -> bool:
        """Check that external service and infrastructure mocks have proper justification"""
        valid = True
        lines = content.split('\n')
        
        # Combined list of all patterns requiring justification
        all_mock_patterns = self.external_service_mocks + self.infrastructure_mocks
        
        for line_num, line in enumerate(lines, 1):
            for pattern in all_mock_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    # Determine mock category for better error messages
                    mock_category = "external service" if pattern in self.external_service_mocks else "infrastructure"
                    
                    # Check for justification comment within 3 lines before or after
                    justification_found = False
                    
                    start_line = max(0, line_num - 4)
                    end_line = min(len(lines), line_num + 3)
                    
                    for check_line in range(start_line, end_line):
                        if check_line < len(lines):
                            comment_line = lines[check_line]
                            if ('# Mock justified:' in comment_line or
                                '# External service' in comment_line or
                                '# Mock external' in comment_line or
                                '# Infrastructure' in comment_line):
                                justification_found = True
                                break
                    
                    if not justification_found:
                        self.warnings.append(
                            f"{file_path}:{line_num}: {mock_category.title()} mock lacks justification: {line.strip()}\n"
                            f"  -> Add comment: # Mock justified: <reason>\n"
                            f"  -> Example: # Mock justified: {mock_category.title()} - email service, not business logic\n"
                            f"  -> See docs/testing/TESTING_STANDARDS.md for examples"
                        )
                        
        return valid

    def _check_enhanced_test_factory_usage(self, file_path: str, content: str) -> bool:
        """Check that integration tests use Enhanced Test Factory (Tier 2 only)"""
        valid = True

        # Check for Enhanced Test Factory usage in integration tests
        has_test_class = "class Test" in content and "TestCase" in content
        has_enhanced_factory = (
            "from verenigingen.tests.fixtures.enhanced_test_factory import" in content
            or "EnhancedTestCase" in content
            or "IntegrationTestCase" in content
        )

        if has_test_class and not has_enhanced_factory:
            self.warnings.append(
                f"{file_path}: Integration test should use Enhanced Test Factory\n"
                f"  -> Import: from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase\n"
                f"  -> Or use IntegrationTestCase base class\n"
                f"  -> See docs/test_remediation_plan/TESTING_STANDARDS.md"
            )
            # Downgrade to warning - not blocking

        return valid

    def _check_field_references(self, file_path: str, content: str) -> bool:
        """Basic field reference validation (enhanced validation in separate script)"""
        valid = True
        
        # Look for obvious field reference errors
        problematic_patterns = [
            # Note: member_name = member.name is actually CORRECT (getting document ID)
            # Removed overly broad pattern that flagged legitimate .name field usage
            r'source_record.*=.*member_name', # Opposite error: assigning string to doc variable
            r'\.non_existent_field',          # Obviously wrong field name
            r'\.fake_field',                  # Test field that doesn't exist
            r'\.test_field_123'               # Clearly made up field names
        ]
        
        lines = content.split('\n')
        for line_num, line in enumerate(lines, 1):
            for pattern in problematic_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.warnings.append(
                        f"{file_path}:{line_num}: Suspicious field reference: {line.strip()}\n"
                        f"  -> Verify field exists in DocType schema\n"
                        f"  -> Use Enhanced Test Factory for validated field references"
                    )
                    
        return valid

    def _find_function_context(self, lines: List[str], line_num: int) -> str:
        """Find which function contains the given line number"""
        for i in range(line_num - 1, -1, -1):
            line = lines[i].strip()
            if line.startswith('def '):
                match = re.search(r'def\s+(\w+)\s*\(', line)
                if match:
                    return match.group(1)
        return "unknown"

    def validate_files(self, file_paths: List[str]) -> bool:
        """Validate multiple files"""
        all_valid = True
        
        for file_path in file_paths:
            if os.path.exists(file_path):
                file_valid = self.validate_file(file_path)
                all_valid &= file_valid
            else:
                self.errors.append(f"File not found: {file_path}")
                all_valid = False
                
        return all_valid

    def report_warnings(self):
        """Print only the warnings channel.

        The ratchet reports errors itself, keyed and diffed against the baseline,
        so it needs the warnings half separately.
        """
        if not self.warnings:
            return
        print("\n🟡 TEST QUALITY WARNINGS:")
        print("=" * 60)
        for warning in self.warnings:
            print(f"\nWARNING: {warning}")

    def report_results(self):
        """Print validation results"""
        if self.errors:
            print("\n🔴 TEST QUALITY VIOLATIONS FOUND:")
            print("=" * 60)
            for error in self.errors:
                print(f"\nERROR: {error}")
                
        if self.warnings:
            print("\n🟡 TEST QUALITY WARNINGS:")
            print("=" * 60)
            for warning in self.warnings:
                print(f"\nWARNING: {warning}")
                
        if not self.errors and not self.warnings:
            print("✅ All files pass test quality validation")
        elif not self.errors:
            print(f"\n✅ No critical errors found ({len(self.warnings)} warnings)")
        else:
            print(f"\n❌ {len(self.errors)} critical errors, {len(self.warnings)} warnings")
            print("\nFIX REQUIRED: Address errors before committing")
            print("See docs/testing/TESTING_STANDARDS.md for correct patterns")


def main():
    """Main entry point for pre-commit hook"""
    parser = argparse.ArgumentParser(
        description="Enforce test quality standards for Verenigingen"
    )
    parser.add_argument(
        'files', 
        nargs='*', 
        help='Files to validate (if none provided, validates all test files)'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat warnings as errors'
    )
    parser.add_argument(
        '--baseline',
        type=Path,
        default=DEFAULT_BASELINE,
        help='Ratchet baseline of already-known violations',
    )
    parser.add_argument(
        '--update-baseline',
        action='store_true',
        help='Rewrite the baseline from a full scan (ignores any files given)',
    )

    args = parser.parse_args()

    enforcer = TestQualityEnforcer()

    # Deliberately ignores args.files: pre-commit passes only the changed files, and
    # regenerating from those would truncate the baseline to whatever happened to be
    # in the last commit.
    if args.update_baseline:
        enforcer.validate_files(sorted(iter_test_files(str(REPO_ROOT))))
        counts = counts_of(enforcer.findings)
        write_baseline(args.baseline, counts)
        print(
            f"baseline written: {len(counts)} keys, "
            f"{sum(counts.values())} findings, {len(enforcer.findings)} raw"
        )
        sys.exit(0)

    if args.files:
        files_to_check = args.files
    else:
        files_to_check = sorted(iter_test_files(str(REPO_ROOT)))

    enforcer.validate_files(files_to_check)

    baseline = load_baseline(args.baseline)
    new = regressions(counts_of(enforcer.findings), baseline)

    if new:
        print("\n🔴 NEW TEST QUALITY VIOLATIONS (not in the baseline):")
        print("=" * 60)
        by_key = {}
        for finding in enforcer.findings:
            by_key.setdefault(
                f"{finding.path}::{finding.qualname}::{finding.kind}", []
            ).append(finding)
        for key, count in sorted(new.items()):
            known = baseline.get(key, 0)
            print(f"\n{key}  (now {count}, baseline {known})")
            for finding in by_key.get(key, []):
                print(f"  {finding.path}:{finding.lineno}")
        print(
            "\nFIX REQUIRED: fix the test, or -- only when the enforcer's own rules "
            "changed --\nregenerate with: python scripts/validation/test_quality_enforcer.py "
            "--update-baseline"
        )

    if enforcer.warnings:
        enforcer.report_warnings()

    if new or (args.strict and enforcer.warnings):
        sys.exit(1)
    print(
        f"✅ No new test quality violations "
        f"({sum(baseline.values())} known, recorded in {args.baseline.name})"
    )
    sys.exit(0)


if __name__ == '__main__':
    main()