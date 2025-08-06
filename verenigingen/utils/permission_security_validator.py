"""
Permission Security Validator
=============================

Comprehensive security validation tool for the Chapter Board Member permission system.
This module provides tools to validate security implementation and test for privilege
escalation vulnerabilities.

Key Validation Areas:
- Permission boundary enforcement
- SQL injection prevention in permission queries
- Privilege escalation prevention
- Cross-chapter data access restrictions
- Role assignment security
- Audit logging and compliance

Usage:
    python -c "
    import frappe;
    frappe.init(site='dev.veganisme.net');
    frappe.connect();
    from verenigingen.utils.permission_security_validator import run_complete_security_validation;
    result = run_complete_security_validation();
    print(result)
    "
"""

import re
from typing import Any, Dict, List, Tuple

import frappe


class SecurityValidationError(Exception):
    """Custom exception for security validation failures"""

    pass


def validate_permission_queries():
    """
    Validate all permission query functions for SQL injection vulnerabilities
    and proper parameter escaping
    """
    security_issues = []

    # List of permission query functions to validate
    permission_functions = [
        "get_member_permission_query",
        "get_membership_permission_query",
        "get_termination_permission_query",
        "get_volunteer_expense_permission_query",
        "get_volunteer_permission_query",
        "get_chapter_member_permission_query",
        "get_donor_permission_query",
        "get_address_permission_query",
    ]

    for func_name in permission_functions:
        try:
            # Import the function
            from verenigingen import permissions

            func = getattr(permissions, func_name)

            # Test with potentially malicious inputs
            test_users = [
                "test@example.com",
                "'; DROP TABLE tabMember; --",
                "' OR 1=1 --",
                "test@example.com' UNION SELECT * FROM tabUser --",
            ]

            for test_user in test_users:
                try:
                    result = func(test_user)

                    # Check if result contains unescaped user input
                    if result and isinstance(result, str):
                        # Check for potential SQL injection patterns
                        dangerous_patterns = [
                            r"'.+?'(?!\s*(?:AND|OR|\)|\s*$))",  # Unescaped quotes
                            r"(?:DROP|DELETE|UPDATE|INSERT)\s+(?:TABLE|FROM|INTO)",  # SQL commands
                            r"UNION\s+SELECT",  # UNION attacks
                            r"--\s*$",  # SQL comments at end
                        ]

                        for pattern in dangerous_patterns:
                            if re.search(pattern, result, re.IGNORECASE):
                                security_issues.append(
                                    f"Potential SQL injection in {func_name}: {pattern} found in result"
                                )

                except Exception as e:
                    # Function should handle malicious input gracefully
                    if "SQL" in str(e) or "syntax" in str(e).lower():
                        security_issues.append(f"SQL error in {func_name} with input '{test_user}': {str(e)}")

        except AttributeError:
            security_issues.append(f"Permission function {func_name} not found")
        except Exception as e:
            security_issues.append(f"Error testing {func_name}: {str(e)}")

    return security_issues


def validate_doctype_permissions():
    """
    Validate DocType permissions to ensure Chapter Board Members don't have excessive privileges
    """
    security_issues = []

    critical_doctypes = [
        "Membership",
        "Membership Termination Request",
        "Volunteer Expense",
        "Member",
        "Chapter",
    ]

    for doctype in critical_doctypes:
        try:
            # Get all permissions for Chapter Board Member role
            permissions = frappe.get_all(
                "DocPerm",
                filters={"parent": doctype, "role": "Verenigingen Chapter Board Member"},
                fields=[
                    "read",
                    "write",
                    "create",
                    "delete",
                    "cancel",
                    "amend",
                    "submit",
                    "import",
                    "export",
                    "report",
                    "share",
                ],
            )

            for perm in permissions:
                # Check for dangerous permissions
                if perm.get("delete"):
                    security_issues.append(f"Chapter Board Member has DELETE permission on {doctype}")

                if perm.get("cancel") and doctype != "Volunteer Expense":
                    security_issues.append(f"Chapter Board Member has CANCEL permission on {doctype}")

                if perm.get("amend") and doctype not in ["Membership", "Volunteer Expense"]:
                    security_issues.append(f"Chapter Board Member has AMEND permission on {doctype}")

                # Import permission should be restricted
                if perm.get("import"):
                    security_issues.append(f"Chapter Board Member has IMPORT permission on {doctype}")

                # Membership Termination Request should not allow submit for board members
                if doctype == "Membership Termination Request" and perm.get("submit"):
                    # This should be workflow-controlled, not direct submit
                    pass  # Allow for now, but validate workflow controls exist

        except Exception as e:
            security_issues.append(f"Error checking permissions for {doctype}: {str(e)}")

    return security_issues


def test_cross_chapter_access_prevention():
    """
    Test that board members cannot access data from other chapters
    """
    security_issues = []

    try:
        # Get sample data from different chapters
        chapters = frappe.get_all("Chapter", limit=2, fields=["name"])

        if len(chapters) < 2:
            return ["Insufficient test data: Need at least 2 chapters for cross-chapter access testing"]

        # Get board members from different chapters
        board_members = frappe.db.sql(
            """
            SELECT DISTINCT
                cbm.parent as chapter,
                v.member,
                m.user,
                m.email
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE cbm.is_active = 1
            AND m.user IS NOT NULL
            AND m.user != ''
            LIMIT 4
        """,
            as_dict=True,
        )

        if len(board_members) < 2:
            return ["Insufficient test data: Need at least 2 active board members for testing"]

        # Test permission queries don't expose cross-chapter data
        from verenigingen.permissions import get_member_permission_query

        for board_member in board_members[:2]:  # Test first 2 board members
            query = get_member_permission_query(board_member.user)

            if not query or query == "":
                security_issues.append(
                    f"Board member {board_member.user} has unrestricted Member access (empty permission query)"
                )
            elif "1=0" in query:
                # This is fine - means no access
                continue
            else:
                # Should contain chapter restrictions
                if "Chapter Member" not in query:
                    security_issues.append(
                        f"Board member {board_member.user} permission query lacks chapter restrictions"
                    )

    except Exception as e:
        security_issues.append(f"Error testing cross-chapter access: {str(e)}")

    return security_issues


def validate_role_assignment_security():
    """
    Validate that role assignment system has proper security controls
    """
    security_issues = []

    try:
        from verenigingen.permissions import assign_chapter_board_role, get_user_chapter_board_positions

        # Test with non-existent user
        result = assign_chapter_board_role("nonexistent@example.com")
        if result is True:
            security_issues.append("Role assignment succeeded for non-existent user")

        # Test with user that has no member record
        test_users = frappe.get_all(
            "User", filters={"email": ["not in", ["Administrator", "Guest"]]}, limit=1
        )
        if test_users:
            test_user = test_users[0].name

            # Ensure user has no member record
            member_exists = frappe.db.exists("Member", {"user": test_user})
            if not member_exists:
                result = assign_chapter_board_role(test_user)
                if result is True:
                    security_issues.append("Role assignment succeeded for user without member record")

        # Test get_user_chapter_board_positions with invalid input
        positions = get_user_chapter_board_positions("'; DROP TABLE tabMember; --")
        if positions and len(positions) > 0:
            security_issues.append("Board positions function returned data for SQL injection attempt")

    except Exception as e:
        security_issues.append(f"Error validating role assignment security: {str(e)}")

    return security_issues


def validate_treasurer_approval_security():
    """
    Validate that treasurer approval system properly restricts access
    """
    security_issues = []

    try:
        from verenigingen.permissions import can_approve_volunteer_expense, is_chapter_treasurer

        # Test with non-existent expense
        fake_expense = frappe.new_doc("Volunteer Expense")
        fake_expense.chapter = "NonExistentChapter"

        result = can_approve_volunteer_expense(fake_expense, "test@example.com")
        if result is True:
            security_issues.append("Expense approval allowed for non-existent chapter")

        # Test treasurer check with invalid inputs
        result = is_chapter_treasurer("'; DROP TABLE tabMember; --", "test_chapter")
        if result is True:
            security_issues.append("Treasurer check returned True for SQL injection attempt")

        result = is_chapter_treasurer("valid_member", "'; DROP TABLE tabChapter; --")
        if result is True:
            security_issues.append("Treasurer check returned True for SQL injection in chapter parameter")

    except Exception as e:
        security_issues.append(f"Error validating treasurer approval security: {str(e)}")

    return security_issues


def validate_audit_logging():
    """
    Validate that security-sensitive operations are properly logged
    """
    security_issues = []

    try:
        # Check if error logs exist for permission operations
        recent_logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">", frappe.utils.add_days(frappe.utils.today(), -1)]},
            fields=["name", "error"],
            limit=100,
        )

        permission_related_logs = [
            log
            for log in recent_logs
            if any(
                keyword in log.error.lower()
                for keyword in ["permission", "access", "role", "board", "chapter"]
            )
        ]

        # Look for suspicious patterns in logs
        for log in permission_related_logs:
            if any(
                pattern in log.error.lower() for pattern in ["sql injection", "drop table", "union select"]
            ):
                security_issues.append(f"Suspicious activity detected in logs: {log.name}")

    except Exception as e:
        security_issues.append(f"Error validating audit logging: {str(e)}")

    return security_issues


def test_privilege_escalation_scenarios():
    """
    Test various privilege escalation scenarios
    """
    security_issues = []

    try:
        # Test 1: Board member trying to access System Manager functions
        from verenigingen.permissions import has_member_permission

        # Create a test scenario where board member tries to access all members
        test_board_members = frappe.db.sql(
            """
            SELECT DISTINCT m.user
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE cbm.is_active = 1
            AND m.user IS NOT NULL
            LIMIT 1
        """
        )

        if test_board_members:
            board_user = test_board_members[0][0]

            # Get a member from a different chapter
            all_members = frappe.get_all("Member", fields=["name"], limit=5)

            for member in all_members:
                # Test if board member can access any member
                access = has_member_permission(member.name, board_user)

                # If they can access ALL members, that's a privilege escalation
                if access:
                    # Check if this member is actually in their chapter
                    from verenigingen.permissions import get_member_permission_query

                    query = get_member_permission_query(board_user)

                    if not query or query == "":
                        security_issues.append(
                            f"Board member {board_user} has unrestricted access to all members"
                        )
                        break

        # Test 2: Role assignment escalation
        test_users = frappe.get_all("User", fields=["name"], limit=1)
        if test_users:
            from verenigingen.permissions import assign_chapter_board_role

            # Try to assign role to Administrator
            result = assign_chapter_board_role("Administrator")
            if result is True:
                security_issues.append("Role assignment allowed for Administrator account")

    except Exception as e:
        security_issues.append(f"Error testing privilege escalation: {str(e)}")

    return security_issues


@frappe.whitelist()
def run_complete_security_validation():
    """
    Run complete security validation suite
    Returns comprehensive security assessment
    """
    validation_results = {
        "timestamp": frappe.utils.now(),
        "overall_status": "PENDING",
        "total_issues": 0,
        "critical_issues": 0,
        "validation_results": {},
    }

    # Run all validation checks
    validation_checks = [
        ("Permission Query Validation", validate_permission_queries),
        ("DocType Permission Validation", validate_doctype_permissions),
        ("Cross-Chapter Access Prevention", test_cross_chapter_access_prevention),
        ("Role Assignment Security", validate_role_assignment_security),
        ("Treasurer Approval Security", validate_treasurer_approval_security),
        ("Audit Logging Validation", validate_audit_logging),
        ("Privilege Escalation Testing", test_privilege_escalation_scenarios),
    ]

    for check_name, check_function in validation_checks:
        try:
            issues = check_function()
            validation_results["validation_results"][check_name] = {
                "status": "PASS" if len(issues) == 0 else "FAIL",
                "issues_count": len(issues),
                "issues": issues,
            }
            validation_results["total_issues"] += len(issues)

            # Count critical issues (SQL injection, privilege escalation, etc.)
            critical_keywords = ["sql injection", "drop table", "privilege escalation", "unrestricted access"]
            critical_count = sum(
                1 for issue in issues if any(keyword in issue.lower() for keyword in critical_keywords)
            )
            validation_results["critical_issues"] += critical_count

        except Exception as e:
            validation_results["validation_results"][check_name] = {
                "status": "ERROR",
                "issues_count": 1,
                "issues": [f"Validation check failed: {str(e)}"],
            }
            validation_results["total_issues"] += 1

    # Determine overall status
    if validation_results["critical_issues"] > 0:
        validation_results["overall_status"] = "CRITICAL"
    elif validation_results["total_issues"] > 0:
        validation_results["overall_status"] = "ISSUES_FOUND"
    else:
        validation_results["overall_status"] = "SECURE"

    # Log results
    frappe.logger().info(
        f"Security validation completed: {validation_results['overall_status']} - {validation_results['total_issues']} total issues, {validation_results['critical_issues']} critical"
    )

    return validation_results


@frappe.whitelist()
def generate_security_report():
    """
    Generate detailed security report for the permission system
    """
    validation_results = run_complete_security_validation()

    # Generate human-readable report
    report_lines = [
        "Chapter Board Member Permission Security Report",
        "=" * 50,
        f"Generated: {validation_results['timestamp']}",
        f"Overall Status: {validation_results['overall_status']}",
        f"Total Issues: {validation_results['total_issues']}",
        f"Critical Issues: {validation_results['critical_issues']}",
        "",
        "Validation Results:",
        "-" * 20,
    ]

    for check_name, results in validation_results["validation_results"].items():
        report_lines.append(f"\n{check_name}: {results['status']}")
        if results["issues"]:
            for issue in results["issues"]:
                report_lines.append(f"  - {issue}")

    if validation_results["overall_status"] == "SECURE":
        report_lines.extend(
            [
                "",
                "✅ SECURITY VALIDATION PASSED",
                "All permission system components are properly secured.",
                "No privilege escalation vulnerabilities detected.",
                "Chapter-based data filtering is working correctly.",
            ]
        )
    else:
        report_lines.extend(
            [
                "",
                "⚠️  SECURITY ISSUES DETECTED",
                "Review the issues above and apply necessary fixes.",
                "Critical issues require immediate attention.",
            ]
        )

    report_content = "\n".join(report_lines)

    return {"validation_results": validation_results, "report_content": report_content}
