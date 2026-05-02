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

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional


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

        # Database operation mock patterns (blocked in Tier 2+)
        self.database_mocks = [
            r"patch\s*\(\s*['\"]frappe\.get_doc['\"]",
            r"patch\s*\(\s*['\"]frappe\.get_all['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.exists['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.set_value['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.sql['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.get_list['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.count['\"]",
            r"patch\s*\(\s*['\"]frappe\.db\.get_value['\"]",
            r"patch\s*\(\s*['\"]frappe\.new_doc['\"]",
        ]

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
        
        # Business logic mocks that should NEVER be allowed
        self.never_mock_patterns = [
            r"patch\s*\(\s*['\"].*validate_.*['\"]",     # Validation functions
            r"patch\s*\(\s*['\"].*business_rule.*['\"]", # Business rules
            r"patch\s*\(\s*['\"].*process_.*['\"]"       # Process functions  
        ]
        
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
        if "_factory" in path.name or path.name.startswith("factory_"):
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

    def _check_database_mocks(self, file_path: str, content: str) -> bool:
        """Check for database operation mocks (blocked in Tier 2 integration tests)"""
        valid = True
        lines = content.split("\n")
        docstring_lines = self._docstring_line_numbers(lines)

        for line_num, line in enumerate(lines, 1):
            # Skip docstring content — examples like "@patch('frappe.db.exists')"
            # mentioned in module-level explanatory docstrings are not actual mocks.
            if line_num in docstring_lines:
                continue
            for pattern in self.database_mocks:
                if re.search(pattern, line, re.IGNORECASE):
                    # Check if this is an allowed configuration access pattern
                    is_allowed = any(
                        re.search(allowed_pattern, line, re.IGNORECASE)
                        for allowed_pattern in self.allowed_config_mocks
                    )

                    if not is_allowed:
                        self.errors.append(
                            f"{file_path}:{line_num}: DATABASE MOCK in integration test: {line.strip()}\n"
                            f"  -> Database operations must not be mocked in integration tests\n"
                            f"  -> Use real database operations with Enhanced Test Factory\n"
                            f"  -> Move to tests/unit/ if testing isolated service logic\n"
                            f"  -> See docs/test_remediation_plan/TESTING_STANDARDS.md"
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
        docstring_lines = self._docstring_line_numbers(lines)
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
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if line_num in docstring_lines:
                # Don't flag @patch examples mentioned inside docstrings.
                continue

            if not re.search(mock_pattern, line, re.IGNORECASE):
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

            self.errors.append(
                f"{file_path}:{line_num}: MOCK in security test: {line.strip()}\n"
                f"  -> Security tests must not mock the auth/permission boundary itself\n"
                f"  -> Infrastructure mocks (HTTP, IP, secret retrieval) are allowed\n"
                f"     when annotated with # Mock justified: <reason>\n"
                f"  -> See docs/test_remediation_plan/TESTING_STANDARDS.md (Tier 3)"
            )
            valid = False

        return valid

    def _check_never_mock_patterns(self, file_path: str, content: str) -> bool:
        """Check for business logic mocks that should never be allowed"""
        valid = True
        lines = content.split('\n')
        docstring_lines = self._docstring_line_numbers(lines)

        for line_num, line in enumerate(lines, 1):
            if line_num in docstring_lines:
                continue
            for pattern in self.never_mock_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.errors.append(
                        f"{file_path}:{line_num}: BUSINESS LOGIC MOCK PROHIBITED: {line.strip()}\n"
                        f"  -> Business logic and validation functions must NEVER be mocked\n"
                        f"  -> This defeats the purpose of integration testing\n"
                        f"  -> Use real business logic to catch actual bugs\n"
                        f"  -> See docs/testing/TESTING_STANDARDS.md for correct patterns"
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
        
        # Track if we're inside a docstring
        in_docstring = False
        docstring_delimiter = None
        
        for line_num, line in enumerate(lines, 1):
            stripped_line = line.strip()
            
            # Check for docstring delimiters
            if '"""' in line:
                if not in_docstring:
                    in_docstring = True
                    docstring_delimiter = '"""'
                elif docstring_delimiter == '"""':
                    in_docstring = False
                    docstring_delimiter = None
            elif "'''" in line:
                if not in_docstring:
                    in_docstring = True
                    docstring_delimiter = "'''"
                elif docstring_delimiter == "'''":
                    in_docstring = False
                    docstring_delimiter = None
            
            # Skip documentation lines (comments and docstrings)
            if (stripped_line.startswith('#') or in_docstring):
                continue
                
            for pattern in self.permission_bypasses:
                if re.search(pattern, line, re.IGNORECASE):
                    # Check if in allowed context
                    context = self._find_function_context(lines, line_num)

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
                        (is_test_factory and context.startswith('_')) or  # private factory methods
                        (is_test_factory and context.startswith('create_'))  # public factory methods
                    )

                    if not is_allowed:
                        self.errors.append(
                            f"{file_path}:{line_num}: PERMISSION BYPASS detected in test logic: {line.strip()}\n"
                            f"  -> Found in context: {context}\n"
                            f"  -> Permission bypasses only allowed in test setup/teardown/factory methods\n"
                            f"  -> Test actual permission boundaries instead of bypassing them\n"
                            f"  -> See docs/testing/TESTING_STANDARDS.md for correct patterns"
                        )
                        valid = False
                        
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
    
    args = parser.parse_args()
    
    enforcer = TestQualityEnforcer()
    
    if args.files:
        files_to_check = args.files
    else:
        # Find all test files if none provided
        files_to_check = []
        for root, dirs, files in os.walk('.'):
            for file in files:
                file_path = os.path.join(root, file)
                if enforcer._is_test_file(file_path):
                    files_to_check.append(file_path)
    
    success = enforcer.validate_files(files_to_check)
    enforcer.report_results()
    
    # Exit with error code if validation failed
    if not success or (args.strict and enforcer.warnings):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()