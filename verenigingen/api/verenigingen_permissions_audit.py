import json

import frappe


@frappe.whitelist()
def audit_verenigingen_permissions():
    """Audit permissions specifically for Verenigingen app DocTypes and Reports"""

    try:
        # Get all DocTypes that belong to the Verenigingen app
        verenigingen_doctypes = frappe.db.sql(
            """
            SELECT name, module, custom, is_submittable, is_tree, istable, issingle
            FROM `tabDocType`
            WHERE app = 'verenigingen'
            ORDER BY module, name
        """,
            as_dict=True,
        )

        # Get all Reports that belong to the Verenigingen app
        verenigingen_reports = frappe.db.sql(
            """
            SELECT name, ref_doctype, report_type, is_standard, disabled
            FROM `tabReport`
            WHERE module IN (
                SELECT name FROM `tabModule Def` WHERE app_name = 'verenigingen'
            )
            ORDER BY ref_doctype, name
        """,
            as_dict=True,
        )

        audit_results = {
            "metadata": {
                "total_doctypes": len(verenigingen_doctypes),
                "total_reports": len(verenigingen_reports),
                "audit_timestamp": frappe.utils.now(),
            },
            "doctype_issues": [],
            "report_issues": [],
            "priority_fixes": {"critical": [], "high": [], "medium": []},
            "modules_summary": {},
        }

        # Load hooks configuration for Verenigingen
        hooks_config = load_verenigingen_hooks()

        # Audit each DocType
        for doctype_info in verenigingen_doctypes:
            doctype_name = doctype_info["name"]

            try:
                meta = frappe.get_meta(doctype_name)
                analysis = analyze_verenigingen_doctype(doctype_name, meta, hooks_config, doctype_info)

                if analysis.get("issues"):
                    audit_results["doctype_issues"].append(analysis)

                    # Categorize by priority
                    for issue in analysis["issues"]:
                        if any(keyword in issue for keyword in ["SENSITIVE", "FINANCIAL", "UNRESTRICTED"]):
                            audit_results["priority_fixes"]["critical"].append(
                                {"doctype": doctype_name, "issue": issue}
                            )
                        elif any(keyword in issue for keyword in ["BROAD_ACCESS", "NO_READ_ACCESS"]):
                            audit_results["priority_fixes"]["high"].append(
                                {"doctype": doctype_name, "issue": issue}
                            )
                        else:
                            audit_results["priority_fixes"]["medium"].append(
                                {"doctype": doctype_name, "issue": issue}
                            )

                # Update module summary
                module = doctype_info.get("module", "Unknown")
                if module not in audit_results["modules_summary"]:
                    audit_results["modules_summary"][module] = {
                        "total_doctypes": 0,
                        "issues_count": 0,
                        "doctypes": [],
                    }
                audit_results["modules_summary"][module]["total_doctypes"] += 1
                audit_results["modules_summary"][module]["doctypes"].append(doctype_name)
                if analysis.get("issues"):
                    audit_results["modules_summary"][module]["issues_count"] += 1

            except Exception as e:
                audit_results["doctype_issues"].append(
                    {"name": doctype_name, "error": f"Analysis failed: {str(e)}"}
                )

        # Audit each Report
        for report_info in verenigingen_reports:
            report_analysis = analyze_verenigingen_report(report_info)
            if report_analysis.get("issues"):
                audit_results["report_issues"].append(report_analysis)

        # Save audit results
        audit_file = "/home/frappe/frappe-bench/apps/verenigingen/docs/VERENIGINGEN_PERMISSIONS_AUDIT.json"
        with open(audit_file, "w") as f:
            json.dump(audit_results, f, indent=2, default=str)

        # Create summary report
        create_verenigingen_summary_report(audit_results)

        return {
            "success": True,
            "total_doctypes": len(verenigingen_doctypes),
            "total_reports": len(verenigingen_reports),
            "critical_issues": len(audit_results["priority_fixes"]["critical"]),
            "high_issues": len(audit_results["priority_fixes"]["high"]),
            "medium_issues": len(audit_results["priority_fixes"]["medium"]),
            "audit_file": audit_file,
        }

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


def load_verenigingen_hooks():
    """Load permission handlers from hooks.py for Verenigingen"""
    try:
        from verenigingen import hooks

        return {
            "permission_query_conditions": getattr(hooks, "permission_query_conditions", {}),
            "has_permission": getattr(hooks, "has_permission", {}),
        }
    except Exception as e:
        return {"permission_query_conditions": {}, "has_permission": {}, "hooks_error": str(e)}


def analyze_verenigingen_doctype(doctype_name, meta, hooks_config, doctype_info):
    """Analyze permissions for a Verenigingen DocType"""

    analysis = {
        "name": doctype_name,
        "module": doctype_info.get("module"),
        "is_child_table": doctype_info.get("istable", 0),
        "is_single": doctype_info.get("issingle", 0),
        "is_submittable": doctype_info.get("is_submittable", 0),
        "permissions": [],
        "server_handlers": {
            "has_query_conditions": doctype_name in hooks_config["permission_query_conditions"],
            "has_permission_handler": doctype_name in hooks_config["has_permission"],
        },
        "issues": [],
    }

    # Analyze DocType permissions
    if hasattr(meta, "permissions") and meta.permissions:
        for perm in meta.permissions:
            perm_data = {
                "role": perm.role,
                "read": getattr(perm, "read", 0),
                "write": getattr(perm, "write", 0),
                "create": getattr(perm, "create", 0),
                "delete": getattr(perm, "delete", 0),
                "if_owner": getattr(perm, "if_owner", 0),
                "user_permission_doctypes": getattr(perm, "user_permission_doctypes", None),
            }
            analysis["permissions"].append(perm_data)

    # Identify issues specific to Verenigingen DocTypes
    identify_verenigingen_issues(analysis, doctype_name)

    return analysis


def identify_verenigingen_issues(analysis, doctype_name):
    """Identify permission issues specific to Verenigingen DocTypes"""

    issues = []

    # Define sensitive Verenigingen DocTypes
    sensitive_doctypes = [
        "Member",
        "Volunteer",
        "Donation",
        "Membership Dues Schedule",
        "Direct Debit Batch",
        "SEPA Mandate",
        "Payment Entry",
        "Membership Termination Request",
        "Chapter",
        "Team",
    ]

    financial_doctypes = [
        "Membership Dues Schedule",
        "Direct Debit Batch",
        "SEPA Mandate",
        "Donation",
        "Payment Plan",
        "Invoice",
    ]

    member_data_doctypes = [
        "Member",
        "Volunteer",
        "Chapter Member",
        "Team Member",
        "Membership Application",
        "Volunteer Application",
    ]

    # Issue 1: No read access for any role
    read_roles = [p["role"] for p in analysis["permissions"] if p["read"]]
    if not read_roles and not analysis["is_child_table"]:
        issues.append("NO_READ_ACCESS: No roles have read access to this DocType")

    # Issue 2: Sensitive data with too broad access
    if doctype_name in sensitive_doctypes:
        if len(read_roles) > 6:  # More than 6 roles might be too broad
            issues.append(
                f"BROAD_ACCESS_SENSITIVE: Sensitive DocType has {len(read_roles)} roles with read access"
            )

    # Issue 3: Financial data without proper restrictions
    if doctype_name in financial_doctypes:
        has_restrictions = any(
            p["if_owner"] or p["user_permission_doctypes"]
            for p in analysis["permissions"]
            if p["role"] not in ["System Manager", "Verenigingen Administrator"]
        )
        if not has_restrictions and not analysis["server_handlers"]["has_permission_handler"]:
            issues.append("FINANCIAL_NO_RESTRICTIONS: Financial DocType lacks proper access restrictions")

    # Issue 4: Member data without user restrictions
    if doctype_name in member_data_doctypes:
        member_roles = [p for p in analysis["permissions"] if p["role"] == "Verenigingen Member"]
        if member_roles and not any(mr["if_owner"] or mr["user_permission_doctypes"] for mr in member_roles):
            if not analysis["server_handlers"]["has_permission_handler"]:
                issues.append("MEMBER_DATA_UNRESTRICTED: Member data accessible without restrictions")

    # Issue 5: Child tables without read access (breaks parent functionality)
    if analysis["is_child_table"] and not read_roles:
        issues.append("CHILD_TABLE_NO_READ: Child table without read access may break parent DocType")

    # Issue 6: Complex permission setup
    if len(analysis["permissions"]) > 8:
        issues.append(
            f"COMPLEX_PERMISSIONS: {len(analysis['permissions'])} permission entries may be hard to maintain"
        )

    analysis["issues"] = issues


def analyze_verenigingen_report(report_info):
    """Analyze permissions for a Verenigingen Report"""

    report_name = report_info["name"]

    try:
        # Get report permissions
        report_roles = frappe.db.sql(
            """
            SELECT role
            FROM `tabHas Role`
            WHERE parent = %s AND parenttype = 'Report'
        """,
            report_name,
            as_dict=True,
        )

        analysis = {
            "name": report_name,
            "ref_doctype": report_info.get("ref_doctype"),
            "report_type": report_info.get("report_type"),
            "roles": [r["role"] for r in report_roles],
            "issues": [],
        }

        # Identify report permission issues
        if not analysis["roles"]:
            analysis["issues"].append("NO_REPORT_ROLES: Report has no assigned roles")

        # Check if sensitive data reports have appropriate restrictions
        sensitive_doctypes = ["Member", "Volunteer", "Donation", "Payment Entry"]
        if analysis["ref_doctype"] in sensitive_doctypes:
            if "All" in analysis["roles"] or len(analysis["roles"]) > 5:
                analysis["issues"].append(
                    "SENSITIVE_REPORT_BROAD_ACCESS: Sensitive data report has broad access"
                )

        return analysis

    except Exception as e:
        return {
            "name": report_name,
            "error": f"Report analysis failed: {str(e)}",
            "issues": [f"ANALYSIS_ERROR: {str(e)}"],
        }


def create_verenigingen_summary_report(audit_results):
    """Create human-readable summary report for Verenigingen permissions"""

    report_lines = [
        "# Verenigingen App Permissions Audit Summary",
        f"Generated: {audit_results['metadata']['audit_timestamp']}",
        "",
        "## Overview",
        f"- Total DocTypes: {audit_results['metadata']['total_doctypes']}",
        f"- Total Reports: {audit_results['metadata']['total_reports']}",
        f"- DocTypes with Issues: {len(audit_results['doctype_issues'])}",
        f"- Reports with Issues: {len(audit_results['report_issues'])}",
        "",
        "## Priority Issues",
        f"- Critical: {len(audit_results['priority_fixes']['critical'])}",
        f"- High: {len(audit_results['priority_fixes']['high'])}",
        f"- Medium: {len(audit_results['priority_fixes']['medium'])}",
        "",
    ]

    # Critical issues
    if audit_results["priority_fixes"]["critical"]:
        report_lines.extend(["## 🚨 CRITICAL Issues (Immediate Action Required)", ""])
        for issue in audit_results["priority_fixes"]["critical"]:
            report_lines.append(f"**{issue['doctype']}**: {issue['issue']}")
        report_lines.append("")

    # High priority issues
    if audit_results["priority_fixes"]["high"]:
        report_lines.extend(["## ⚠️ HIGH Priority Issues", ""])
        for issue in audit_results["priority_fixes"]["high"]:
            report_lines.append(f"**{issue['doctype']}**: {issue['issue']}")
        report_lines.append("")

    # Module breakdown
    report_lines.extend(["## Module Breakdown", ""])
    for module, summary in audit_results["modules_summary"].items():
        report_lines.append(f"### {module}")
        report_lines.append(f"- Total DocTypes: {summary['total_doctypes']}")
        report_lines.append(f"- DocTypes with Issues: {summary['issues_count']}")
        if summary["issues_count"] > 0:
            report_lines.append("- DocTypes: " + ", ".join(summary["doctypes"]))
        report_lines.append("")

    # Detailed issues
    if audit_results["doctype_issues"]:
        report_lines.extend(["## Detailed DocType Issues", ""])
        for doctype_issue in audit_results["doctype_issues"]:
            if doctype_issue.get("issues"):
                report_lines.append(f"### {doctype_issue['name']} ({doctype_issue.get('module', 'Unknown')})")
                for issue in doctype_issue["issues"]:
                    report_lines.append(f"- {issue}")
                report_lines.append("")

    # Report issues
    if audit_results["report_issues"]:
        report_lines.extend(["## Report Permission Issues", ""])
        for report_issue in audit_results["report_issues"]:
            if report_issue.get("issues"):
                report_lines.append(f"### {report_issue['name']}")
                for issue in report_issue["issues"]:
                    report_lines.append(f"- {issue}")
                report_lines.append("")

    # Save summary report
    summary_file = "/home/frappe/frappe-bench/apps/verenigingen/docs/VERENIGINGEN_PERMISSIONS_SUMMARY.md"
    with open(summary_file, "w") as f:
        f.write("\n".join(report_lines))
