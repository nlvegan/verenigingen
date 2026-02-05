#!/usr/bin/env python3
"""
Permission Bypass Validator

Detects new ignore_permissions=True usages in code changes.
Flags additions that lack security justification comments.

This validator ensures that permission bypasses are:
1. Intentional and documented
2. In appropriate locations (tests, patches, setup are LOW risk)
3. Accompanied by security justification comments for HIGH risk code

Risk Classification:
- LOW: Tests, patches, setup files, fixtures
- MEDIUM: Background jobs, webhooks with auth, admin utilities
- HIGH: API endpoints, services, user-facing code

Usage:
    # Check staged files (pre-commit)
    python permission_bypass_validator.py --pre-commit

    # Check specific files
    python permission_bypass_validator.py file1.py file2.py

    # Check all files (full scan)
    python permission_bypass_validator.py --all

    # Check with baseline (only new additions)
    python permission_bypass_validator.py --baseline

Exit Codes:
    0 - No issues found
    1 - Issues found (new permission bypasses without justification)
    2 - Error during execution
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class RiskLevel(Enum):
    """Risk classification for permission bypass locations"""
    LOW = "low"       # Tests, patches, setup
    MEDIUM = "medium" # Background jobs, webhooks
    HIGH = "high"     # API, services, user-facing


@dataclass
class PermissionBypassFinding:
    """Represents a found permission bypass instance"""
    file_path: str
    line_number: int
    line_content: str
    risk_level: RiskLevel
    has_justification: bool
    justification_text: Optional[str] = None


# Patterns that indicate security justification comments
JUSTIFICATION_PATTERNS = [
    r'#\s*Security:',
    r'#\s*SECURITY:',
    r'#\s*security\s+justification',
    r'#\s*Security\s+justification',
    r'#\s*ignore_permissions\s+acceptable',
    r'#\s*Permission\s+bypass\s+justified',
    r'""".*Security.*ignore_permissions.*"""',
    r"'''.*Security.*ignore_permissions.*'''",
]

# LOW risk path patterns (acceptable with minimal review)
LOW_RISK_PATTERNS = [
    r'/tests/',
    r'/test_',
    r'_test\.py$',
    r'/patches/',
    r'/setup/',
    r'/fixtures/',
    r'setup\.py$',
    r'install\.py$',
    r'/migration/',
]

# MEDIUM risk path patterns (acceptable with authentication/admin context)
MEDIUM_RISK_PATTERNS = [
    r'/utils/background',
    r'/utils/bulk_',
    r'/utils/cleanup',
    r'/utils/migration',
    r'/email/',
    r'_sync\.py$',
    r'/e_boekhouden/',
    r'/workspace_',
    r'webhook.*\.py$',
]

# HIGH risk path patterns (require explicit justification)
HIGH_RISK_PATTERNS = [
    r'/api/',
    r'/services/',
    r'/web_form/',
    r'/www/',
    r'/templates/pages/',
    r'permissions\.py$',
    r'/doctype/.*/[^/]+\.py$',  # DocType controllers
]


def classify_risk_level(file_path: str) -> RiskLevel:
    """Classify risk level based on file path"""
    path_str = str(file_path)

    # Check LOW risk first
    for pattern in LOW_RISK_PATTERNS:
        if re.search(pattern, path_str):
            return RiskLevel.LOW

    # Check HIGH risk
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, path_str):
            return RiskLevel.HIGH

    # Check MEDIUM risk
    for pattern in MEDIUM_RISK_PATTERNS:
        if re.search(pattern, path_str):
            return RiskLevel.MEDIUM

    # Default to MEDIUM for unclassified
    return RiskLevel.MEDIUM


def has_security_justification(lines: List[str], line_number: int) -> Tuple[bool, Optional[str]]:
    """
    Check if there's a security justification comment near the permission bypass.

    Looks for justification in:
    - Same line (inline comment)
    - Previous 5 lines (comment block before)
    - Docstring of containing function
    """
    # Check same line
    current_line = lines[line_number - 1] if line_number <= len(lines) else ""
    for pattern in JUSTIFICATION_PATTERNS:
        if re.search(pattern, current_line, re.IGNORECASE):
            match = re.search(r'#\s*(.+)$', current_line)
            return True, match.group(1) if match else current_line

    # Check previous 5 lines
    start_idx = max(0, line_number - 6)
    for i in range(line_number - 2, start_idx - 1, -1):
        if i < 0 or i >= len(lines):
            continue
        line = lines[i]
        for pattern in JUSTIFICATION_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Extract the justification text
                match = re.search(r'#\s*(.+)$', line)
                return True, match.group(1) if match else line

    # Check for docstring justification (look back for def/class and docstring)
    for i in range(line_number - 2, max(0, line_number - 30), -1):
        line = lines[i].strip()
        if line.startswith('"""') or line.startswith("'''"):
            # Found a docstring, check for security mention
            docstring_lines = []
            for j in range(i, min(len(lines), i + 20)):
                docstring_lines.append(lines[j])
                if (lines[j].strip().endswith('"""') or lines[j].strip().endswith("'''")) and j > i:
                    break
            docstring = '\n'.join(docstring_lines)
            if 'security' in docstring.lower() and 'ignore_permissions' in docstring.lower():
                return True, "Documented in docstring"

    return False, None


def find_permission_bypasses(file_path: str) -> List[PermissionBypassFinding]:
    """Find all ignore_permissions=True usages in a file"""
    findings = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.split('\n')
    except (IOError, OSError) as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
        return findings

    risk_level = classify_risk_level(file_path)

    # Pattern to find ignore_permissions=True
    pattern = r'ignore_permissions\s*=\s*True'

    for i, line in enumerate(lines, 1):
        if re.search(pattern, line):
            # Skip commented lines
            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            has_justification, justification_text = has_security_justification(lines, i)

            finding = PermissionBypassFinding(
                file_path=file_path,
                line_number=i,
                line_content=line.strip(),
                risk_level=risk_level,
                has_justification=has_justification,
                justification_text=justification_text,
            )
            findings.append(finding)

    return findings


def get_staged_files() -> List[str]:
    """Get list of staged Python files for pre-commit"""
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR'],
            capture_output=True,
            text=True,
            check=True
        )
        files = result.stdout.strip().split('\n')
        return [f for f in files if f.endswith('.py') and f]
    except subprocess.CalledProcessError:
        return []


def get_changed_files() -> List[str]:
    """Get list of changed Python files (staged + unstaged)"""
    try:
        result = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD'],
            capture_output=True,
            text=True,
            check=True
        )
        files = result.stdout.strip().split('\n')
        return [f for f in files if f.endswith('.py') and f]
    except subprocess.CalledProcessError:
        return []


def get_all_python_files(base_path: str = 'verenigingen') -> List[str]:
    """Get all Python files in the codebase"""
    files = []
    base = Path(base_path)

    if not base.exists():
        return files

    for path in base.rglob('*.py'):
        # Skip archived directories
        path_str = str(path)
        if any(skip in path_str for skip in ['archived_', '/archived/', '__pycache__']):
            continue
        files.append(str(path))

    return files


def format_findings(findings: List[PermissionBypassFinding], verbose: bool = False) -> str:
    """Format findings for display"""
    if not findings:
        return "✅ No permission bypass issues found.\n"

    output = []

    # Group by risk level
    high_risk = [f for f in findings if f.risk_level == RiskLevel.HIGH and not f.has_justification]
    medium_risk = [f for f in findings if f.risk_level == RiskLevel.MEDIUM and not f.has_justification]
    low_risk = [f for f in findings if f.risk_level == RiskLevel.LOW and not f.has_justification]
    documented = [f for f in findings if f.has_justification]

    # Report HIGH risk issues (blocking)
    if high_risk:
        output.append("\n🚨 HIGH RISK - Permission bypasses requiring security justification:")
        output.append("-" * 70)
        for f in high_risk:
            output.append(f"  {f.file_path}:{f.line_number}")
            output.append(f"    {f.line_content}")
            output.append(f"    ⚠️  Add security justification comment: # Security: <reason>")
            output.append("")

    # Report MEDIUM risk issues (warning)
    if medium_risk:
        output.append("\n⚠️  MEDIUM RISK - Permission bypasses (consider adding justification):")
        output.append("-" * 70)
        for f in medium_risk:
            output.append(f"  {f.file_path}:{f.line_number}")
            output.append(f"    {f.line_content}")
            output.append("")

    # Report LOW risk (info only in verbose mode)
    if verbose and low_risk:
        output.append("\nℹ️  LOW RISK - Permission bypasses (tests/patches/setup):")
        output.append("-" * 70)
        for f in low_risk:
            output.append(f"  {f.file_path}:{f.line_number}")
            output.append("")

    # Report documented items in verbose mode
    if verbose and documented:
        output.append("\n✅ DOCUMENTED - Permission bypasses with security justification:")
        output.append("-" * 70)
        for f in documented:
            output.append(f"  {f.file_path}:{f.line_number}")
            if f.justification_text:
                output.append(f"    Justification: {f.justification_text[:80]}...")
            output.append("")

    # Summary
    output.append("\n" + "=" * 70)
    output.append("SUMMARY:")
    output.append(f"  🚨 HIGH risk without justification: {len(high_risk)}")
    output.append(f"  ⚠️  MEDIUM risk without justification: {len(medium_risk)}")
    output.append(f"  ℹ️  LOW risk (acceptable): {len(low_risk)}")
    output.append(f"  ✅ Documented: {len(documented)}")
    output.append("")

    if high_risk:
        output.append("❌ FAILED: Add security justification comments to HIGH risk files.")
        output.append("   Example: # Security: Authenticated via webhook HMAC signature")
    else:
        output.append("✅ PASSED: No undocumented HIGH risk permission bypasses found.")

    return '\n'.join(output)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Validate permission bypass usages (ignore_permissions=True)'
    )
    parser.add_argument(
        '--pre-commit',
        action='store_true',
        help='Check only staged files (for pre-commit hook)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Check all Python files in codebase'
    )
    parser.add_argument(
        '--baseline',
        action='store_true',
        help='Check only changed files (staged + unstaged)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show all findings including LOW risk and documented'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Fail on MEDIUM risk findings too'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='Specific files to check'
    )

    args = parser.parse_args()

    # Determine which files to check
    if args.files:
        files_to_check = [f for f in args.files if f.endswith('.py')]
    elif args.pre_commit:
        files_to_check = get_staged_files()
        if not files_to_check:
            print("ℹ️  No staged Python files to check.")
            return 0
    elif args.all:
        files_to_check = get_all_python_files()
    elif args.baseline:
        files_to_check = get_changed_files()
    else:
        # Default: check staged files
        files_to_check = get_staged_files()
        if not files_to_check:
            print("ℹ️  No staged Python files. Use --all for full scan.")
            return 0

    print(f"🔍 Checking {len(files_to_check)} Python file(s) for permission bypass issues...\n")

    # Find all permission bypass usages
    all_findings: List[PermissionBypassFinding] = []
    for file_path in files_to_check:
        if os.path.exists(file_path):
            findings = find_permission_bypasses(file_path)
            all_findings.extend(findings)

    # Format and print results
    print(format_findings(all_findings, verbose=args.verbose))

    # Determine exit code
    high_risk_issues = [f for f in all_findings if f.risk_level == RiskLevel.HIGH and not f.has_justification]
    medium_risk_issues = [f for f in all_findings if f.risk_level == RiskLevel.MEDIUM and not f.has_justification]

    if high_risk_issues:
        return 1
    if args.strict and medium_risk_issues:
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
