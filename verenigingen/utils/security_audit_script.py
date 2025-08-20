"""
Security Audit Script for frappe.get_roles() Usage

This script identifies all locations in the codebase where frappe.get_roles() is used
without proper validation, which could lead to the systemic vulnerability where
frappe.get_roles(None) returns all system roles.

Key Security Issues Detected:
1. Direct calls to frappe.get_roles() without user validation
2. Calls to frappe.get_roles() with potentially None user parameters
3. Missing error handling around role checking functions
4. Inconsistent security patterns across the codebase

Security Analysis Features:
- Comprehensive grep-based code analysis
- Risk level assessment for each usage
- Recommendations for security fixes
- Integration with security wrapper migration
- Detailed reporting for audit compliance

Usage:
    bench --site dev.veganisme.net execute verenigingen.utils.security_audit_script.run_comprehensive_audit
    bench --site dev.veganisme.net execute verenigingen.utils.security_audit_script.generate_security_report

Author: Security Team
Date: 2025-08-20
Version: 1.0
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

import frappe


class SecurityAuditResult:
    """Data class for security audit findings"""

    def __init__(self, file_path: str, line_number: int, line_content: str, risk_level: str, issue_type: str):
        self.file_path = file_path
        self.line_number = line_number
        self.line_content = line_content.strip()
        self.risk_level = risk_level
        self.issue_type = issue_type
        self.recommendation = self._generate_recommendation()

    def _generate_recommendation(self) -> str:
        """Generate specific recommendation based on the security issue"""
        if "frappe.get_roles(None)" in self.line_content:
            return "CRITICAL: Replace with safe_get_roles(None) immediately"
        elif "frappe.get_roles()" in self.line_content and "user" not in self.line_content:
            return "HIGH: Replace with safe_get_roles() for current user"
        elif "frappe.get_roles(" in self.line_content:
            return "MEDIUM: Validate user parameter and replace with safe_get_roles(user)"
        else:
            return "LOW: Review for security best practices"


def get_app_directory() -> str:
    """Get the verenigingen app directory path"""
    return frappe.get_app_path("verenigingen")


def run_grep_analysis() -> List[Tuple[str, int, str]]:
    """
    Run comprehensive grep analysis to find frappe.get_roles() usage

    Returns:
        List of tuples (file_path, line_number, line_content)
    """
    app_dir = get_app_directory()
    results = []

    try:
        # Use ripgrep (rg) for fast searching if available, otherwise use grep
        grep_command = [
            "rg",
            "-n",  # line numbers
            r"frappe\.get_roles\(",  # pattern
            app_dir,  # directory
            "--type",
            "py",  # only Python files
        ]

        try:
            result = subprocess.run(grep_command, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                output = result.stdout
            else:
                # Fallback to regular grep
                grep_command = ["grep", "-rn", r"frappe\.get_roles(", app_dir, "--include=*.py"]
                result = subprocess.run(grep_command, capture_output=True, text=True, timeout=30)
                output = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Manual fallback if grep tools are not available
            return _manual_file_scan(app_dir)

        # Parse grep output
        for line in output.split("\n"):
            if line.strip():
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    file_path = parts[0]
                    try:
                        line_number = int(parts[1])
                        line_content = parts[2]
                        results.append((file_path, line_number, line_content))
                    except ValueError:
                        continue

    except Exception as e:
        frappe.logger().error(f"Error in grep analysis: {str(e)}")
        return _manual_file_scan(app_dir)

    return results


def _manual_file_scan(app_dir: str) -> List[Tuple[str, int, str]]:
    """
    Manual file scanning fallback when grep tools are not available

    Args:
        app_dir: Directory to scan

    Returns:
        List of tuples (file_path, line_number, line_content)
    """
    results = []
    pattern = re.compile(r"frappe\.get_roles\(")

    try:
        for root, dirs, files in os.walk(app_dir):
            # Skip common non-code directories
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".pytest_cache"}]

            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line_number, line in enumerate(f, 1):
                                if pattern.search(line):
                                    results.append((file_path, line_number, line))
                    except (IOError, UnicodeDecodeError):
                        continue

    except Exception as e:
        frappe.logger().error(f"Error in manual file scan: {str(e)}")

    return results


def analyze_security_risk(file_path: str, line_number: int, line_content: str) -> SecurityAuditResult:
    """
    Analyze the security risk level of a frappe.get_roles() usage

    Args:
        file_path: Path to the file
        line_number: Line number in the file
        line_content: Content of the line

    Returns:
        SecurityAuditResult with risk assessment
    """
    line_lower = line_content.lower().strip()

    # CRITICAL: Direct call with None
    if "frappe.get_roles(none)" in line_lower or "frappe.get_roles(null)" in line_lower:
        return SecurityAuditResult(file_path, line_number, line_content, "CRITICAL", "Direct None parameter")

    # HIGH: Call without any parameters (relies on session user)
    if re.search(r"frappe\.get_roles\(\s*\)", line_content):
        return SecurityAuditResult(
            file_path, line_number, line_content, "HIGH", "No user parameter validation"
        )

    # HIGH: Variable that could be None
    if re.search(r"frappe\.get_roles\([^)]*user[^)]*\)", line_content):
        # Check if there's validation nearby
        if any(keyword in line_lower for keyword in ["if", "validate", "check", "not"]):
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        return SecurityAuditResult(
            file_path, line_number, line_content, risk_level, "User parameter without validation"
        )

    # MEDIUM: Other parameter patterns
    return SecurityAuditResult(file_path, line_number, line_content, "MEDIUM", "Requires manual review")


def generate_migration_script(audit_results: List[SecurityAuditResult]) -> str:
    """
    Generate a migration script to fix security issues

    Args:
        audit_results: List of audit findings

    Returns:
        Python script content for automated migration
    """
    script_lines = [
        "#!/usr/bin/env python3",
        '"""',
        "Automated migration script for frappe.get_roles() security fixes",
        "Generated by security audit script",
        '"""',
        "",
        "import re",
        "import os",
        "from pathlib import Path",
        "",
        "def migrate_file(file_path):",
        '    """Migrate a single file to use security wrappers"""',
        "    try:",
        "        with open(file_path, 'r', encoding='utf-8') as f:",
        "            content = f.read()",
        "",
        "        # Add import if not present",
        "        if 'from verenigingen.utils.security_wrappers import safe_get_roles' not in content:",
        "            import_pattern = r'(import frappe\\n|from frappe import [^\\n]+\\n)'",
        "            replacement = r'\\1from verenigingen.utils.security_wrappers import safe_get_roles\\n'",
        "            content = re.sub(import_pattern, replacement, content, count=1)",
        "",
        "        # Replace frappe.get_roles calls",
        "        content = re.sub(r'frappe\\.get_roles\\(', 'safe_get_roles(', content)",
        "",
        "        with open(file_path, 'w', encoding='utf-8') as f:",
        "            f.write(content)",
        "",
        "        print(f'✓ Migrated {file_path}')",
        "        return True",
        "",
        "    except Exception as e:",
        "        print(f'✗ Error migrating {file_path}: {e}')",
        "        return False",
        "",
        "def main():",
        '    """Run migration on all identified files"""',
        "    files_to_migrate = [",
    ]

    # Add files that need migration
    unique_files = set(
        result.file_path for result in audit_results if result.risk_level in ["CRITICAL", "HIGH"]
    )
    for file_path in sorted(unique_files):
        script_lines.append(f'        "{file_path}",')

    script_lines.extend(
        [
            "    ]",
            "",
            "    success_count = 0",
            "    for file_path in files_to_migrate:",
            "        if migrate_file(file_path):",
            "            success_count += 1",
            "",
            "    print(f'Migration completed: {success_count}/{len(files_to_migrate)} files migrated')",
            "",
            "if __name__ == '__main__':",
            "    main()",
        ]
    )

    return "\n".join(script_lines)


@frappe.whitelist()
def run_comprehensive_audit():
    """
    Run comprehensive security audit and return results

    Returns:
        Dictionary with audit results and recommendations
    """
    try:
        frappe.logger().info("Starting comprehensive security audit for frappe.get_roles() usage")

        # Run grep analysis
        grep_results = run_grep_analysis()

        # Analyze each result
        audit_results = []
        for file_path, line_number, line_content in grep_results:
            result = analyze_security_risk(file_path, line_number, line_content)
            audit_results.append(result)

        # Categorize results by risk level
        results_by_risk = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}

        for result in audit_results:
            results_by_risk[result.risk_level].append(result)

        # Generate summary
        summary = {
            "total_files_scanned": len(set(result.file_path for result in audit_results)),
            "total_issues_found": len(audit_results),
            "critical_issues": len(results_by_risk["CRITICAL"]),
            "high_risk_issues": len(results_by_risk["HIGH"]),
            "medium_risk_issues": len(results_by_risk["MEDIUM"]),
            "low_risk_issues": len(results_by_risk["LOW"]),
            "requires_immediate_attention": len(results_by_risk["CRITICAL"]) + len(results_by_risk["HIGH"]),
        }

        frappe.logger().info(f"Security audit completed: {summary}")

        return {
            "summary": summary,
            "results_by_risk": {
                risk: [
                    {
                        "file_path": r.file_path,
                        "line_number": r.line_number,
                        "line_content": r.line_content,
                        "issue_type": r.issue_type,
                        "recommendation": r.recommendation,
                    }
                    for r in results
                ]
                for risk, results in results_by_risk.items()
            },
            "migration_script": generate_migration_script(audit_results),
        }

    except Exception as e:
        frappe.logger().error(f"Error in comprehensive security audit: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def generate_security_report():
    """
    Generate a detailed security report in markdown format

    Returns:
        Markdown-formatted security report
    """
    try:
        audit_data = run_comprehensive_audit()

        if "error" in audit_data:
            return f"# Security Audit Error\n\n{audit_data['error']}"

        summary = audit_data["summary"]
        results_by_risk = audit_data["results_by_risk"]

        report_lines = [
            "# Verenigingen Security Audit Report",
            "",
            f"**Date Generated:** {frappe.utils.now()}",
            "**Audit Scope:** frappe.get_roles() usage analysis",
            "",
            "## Executive Summary",
            "",
            f"- **Total Files Scanned:** {summary['total_files_scanned']}",
            f"- **Total Issues Found:** {summary['total_issues_found']}",
            f"- **Critical Issues:** {summary['critical_issues']}",
            f"- **High Risk Issues:** {summary['high_risk_issues']}",
            f"- **Medium Risk Issues:** {summary['medium_risk_issues']}",
            f"- **Low Risk Issues:** {summary['low_risk_issues']}",
            "",
            f"**⚠️ Requires Immediate Attention:** {summary['requires_immediate_attention']} issues",
            "",
        ]

        # Add detailed findings for each risk level
        for risk_level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            results = results_by_risk[risk_level]
            if results:
                report_lines.extend([f"## {risk_level} Risk Issues ({len(results)})", ""])

                for i, result in enumerate(results, 1):
                    report_lines.extend(
                        [
                            f"### {i}. {result['issue_type']}",
                            "",
                            f"**File:** `{result['file_path']}`",
                            f"**Line:** {result['line_number']}",
                            f"**Code:** `{result['line_content']}`",
                            f"**Recommendation:** {result['recommendation']}",
                            "",
                        ]
                    )

        # Add remediation guidelines
        report_lines.extend(
            [
                "## Remediation Guidelines",
                "",
                "### Immediate Actions Required",
                "",
                "1. **Critical Issues:** Fix immediately before production deployment",
                "2. **High Risk Issues:** Schedule for next sprint/release",
                "3. **Medium Risk Issues:** Include in security backlog",
                "4. **Low Risk Issues:** Address during code refactoring",
                "",
                "### Migration Strategy",
                "",
                "1. Import security wrapper: `from verenigingen.utils.security_wrappers import safe_get_roles`",
                "2. Replace calls: `frappe.get_roles(user)` → `safe_get_roles(user)`",
                "3. Test thoroughly in development environment",
                "4. Deploy with monitoring for security events",
                "",
                "### Security Best Practices",
                "",
                "- Always validate user parameters before role checking",
                "- Use safe_get_roles() instead of frappe.get_roles()",
                "- Log security-sensitive operations for audit",
                "- Implement automated security testing",
                "",
                "---",
                "",
                "*Report generated by Verenigingen Security Audit Script v1.0*",
            ]
        )

        return "\n".join(report_lines)

    except Exception as e:
        frappe.logger().error(f"Error generating security report: {str(e)}")
        return f"# Security Report Generation Error\n\n{str(e)}"


if __name__ == "__main__":
    # Command-line usage for development
    print("Running security audit...")
    results = run_comprehensive_audit()
    print(f"Found {results.get('summary', {}).get('total_issues_found', 0)} security issues")

    # Generate and save report
    report = generate_security_report()
    with open("/tmp/verenigingen_security_audit.md", "w") as f:
        f.write(report)
    print("Report saved to /tmp/verenigingen_security_audit.md")
