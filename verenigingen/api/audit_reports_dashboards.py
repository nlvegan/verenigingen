import json

import frappe


@frappe.whitelist()
def audit_verenigingen_reports_and_dashboards():
    """Comprehensive audit of Verenigingen Reports and Dashboards permissions"""

    try:
        # Get all Reports that belong to Verenigingen modules
        verenigingen_reports = frappe.db.sql(
            """
            SELECT r.name, r.ref_doctype, r.report_type, r.is_standard, r.disabled, r.module
            FROM `tabReport` r
            WHERE r.module IN (
                SELECT name FROM `tabModule Def` WHERE app_name = 'verenigingen'
            )
            ORDER BY r.module, r.name
        """,
            as_dict=True,
        )

        # Get all Dashboards that belong to Verenigingen
        verenigingen_dashboards = frappe.db.sql(
            """
            SELECT name, module, dashboard_name
            FROM `tabDashboard`
            WHERE module IN (
                SELECT name FROM `tabModule Def` WHERE app_name = 'verenigingen'
            )
            ORDER BY module, name
        """,
            as_dict=True,
        )

        audit_results = {
            "metadata": {
                "total_reports": len(verenigingen_reports),
                "total_dashboards": len(verenigingen_dashboards),
                "audit_timestamp": frappe.utils.now(),
            },
            "report_issues": [],
            "dashboard_issues": [],
            "priority_fixes": {
                "critical": [],  # Public access to sensitive data
                "high": [],  # Broad access to sensitive reports
                "medium": [],  # Missing role assignments
            },
            "summary": {
                "reports_with_issues": 0,
                "dashboards_with_issues": 0,
                "reports_by_module": {},
                "dashboards_by_module": {},
            },
        }

        # Audit each Report
        for report_info in verenigingen_reports:
            report_analysis = analyze_verenigingen_report(report_info)

            # Update module summary
            module = report_info.get("module", "Unknown")
            if module not in audit_results["summary"]["reports_by_module"]:
                audit_results["summary"]["reports_by_module"][module] = []
            audit_results["summary"]["reports_by_module"][module].append(report_info["name"])

            if report_analysis.get("issues"):
                audit_results["report_issues"].append(report_analysis)
                audit_results["summary"]["reports_with_issues"] += 1

                # Categorize issues
                for issue in report_analysis["issues"]:
                    if any(keyword in issue for keyword in ["PUBLIC_ACCESS", "UNRESTRICTED", "SENSITIVE"]):
                        audit_results["priority_fixes"]["critical"].append(
                            {"type": "Report", "name": report_info["name"], "issue": issue}
                        )
                    elif any(keyword in issue for keyword in ["BROAD_ACCESS", "TOO_MANY_ROLES"]):
                        audit_results["priority_fixes"]["high"].append(
                            {"type": "Report", "name": report_info["name"], "issue": issue}
                        )
                    else:
                        audit_results["priority_fixes"]["medium"].append(
                            {"type": "Report", "name": report_info["name"], "issue": issue}
                        )

        # Audit each Dashboard
        for dashboard_info in verenigingen_dashboards:
            dashboard_analysis = analyze_verenigingen_dashboard(dashboard_info)

            # Update module summary
            module = dashboard_info.get("module", "Unknown")
            if module not in audit_results["summary"]["dashboards_by_module"]:
                audit_results["summary"]["dashboards_by_module"][module] = []
            audit_results["summary"]["dashboards_by_module"][module].append(dashboard_info["name"])

            if dashboard_analysis.get("issues"):
                audit_results["dashboard_issues"].append(dashboard_analysis)
                audit_results["summary"]["dashboards_with_issues"] += 1

                # Categorize issues
                for issue in dashboard_analysis["issues"]:
                    if any(keyword in issue for keyword in ["PUBLIC_ACCESS", "UNRESTRICTED", "SENSITIVE"]):
                        audit_results["priority_fixes"]["critical"].append(
                            {"type": "Dashboard", "name": dashboard_info["name"], "issue": issue}
                        )
                    elif any(keyword in issue for keyword in ["BROAD_ACCESS", "TOO_MANY_ROLES"]):
                        audit_results["priority_fixes"]["high"].append(
                            {"type": "Dashboard", "name": dashboard_info["name"], "issue": issue}
                        )
                    else:
                        audit_results["priority_fixes"]["medium"].append(
                            {"type": "Dashboard", "name": dashboard_info["name"], "issue": issue}
                        )

        # Save audit results
        audit_file = (
            "/home/frappe/frappe-bench/apps/verenigingen/docs/VERENIGINGEN_REPORTS_DASHBOARDS_AUDIT.json"
        )
        with open(audit_file, "w") as f:
            json.dump(audit_results, f, indent=2, default=str)

        # Create summary report
        create_reports_dashboards_summary(audit_results)

        return {
            "success": True,
            "total_reports": len(verenigingen_reports),
            "total_dashboards": len(verenigingen_dashboards),
            "reports_with_issues": audit_results["summary"]["reports_with_issues"],
            "dashboards_with_issues": audit_results["summary"]["dashboards_with_issues"],
            "critical_issues": len(audit_results["priority_fixes"]["critical"]),
            "high_issues": len(audit_results["priority_fixes"]["high"]),
            "medium_issues": len(audit_results["priority_fixes"]["medium"]),
            "audit_file": audit_file,
        }

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


def analyze_verenigingen_report(report_info):
    """Analyze permissions for a Verenigingen Report"""

    report_name = report_info["name"]

    try:
        # Get report roles
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
            "module": report_info.get("module"),
            "ref_doctype": report_info.get("ref_doctype"),
            "report_type": report_info.get("report_type"),
            "is_standard": report_info.get("is_standard"),
            "disabled": report_info.get("disabled"),
            "roles": [r["role"] for r in report_roles],
            "issues": [],
        }

        roles = analysis["roles"]

        # Issue 1: No roles assigned
        if not roles:
            analysis["issues"].append("NO_ROLES: Report has no assigned roles, may be inaccessible")

        # Issue 2: Public access to sensitive data
        if "All" in roles or "Guest" in roles:
            sensitive_doctypes = [
                "Member",
                "Volunteer",
                "Donation",
                "Payment Entry",
                "SEPA Mandate",
                "Direct Debit Batch",
            ]
            if analysis["ref_doctype"] in sensitive_doctypes:
                analysis["issues"].append(
                    f"PUBLIC_ACCESS_SENSITIVE: Report on {analysis['ref_doctype']} has public access"
                )
            else:
                analysis["issues"].append("PUBLIC_ACCESS: Report has public access")

        # Issue 3: Too many roles for sensitive reports
        sensitive_doctypes = [
            "Member",
            "Volunteer",
            "Donation",
            "Payment Entry",
            "SEPA Mandate",
            "Direct Debit Batch",
        ]
        if analysis["ref_doctype"] in sensitive_doctypes and len(roles) > 5:
            analysis["issues"].append(
                f"BROAD_ACCESS_SENSITIVE: Report on sensitive data ({analysis['ref_doctype']}) has {len(roles)} roles"
            )

        # Issue 4: Member-related reports accessible to too many roles
        member_related_doctypes = ["Member", "Volunteer", "Chapter Member", "Team Member", "Membership"]
        if analysis["ref_doctype"] in member_related_doctypes:
            non_admin_roles = [
                r
                for r in roles
                if r not in ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
            ]
            if len(non_admin_roles) > 3:
                analysis["issues"].append(
                    f"TOO_MANY_NON_ADMIN_ROLES: Member-related report has {len(non_admin_roles)} non-admin roles"
                )

        # Issue 5: Financial reports with broad access
        financial_keywords = ["payment", "donation", "invoice", "sepa", "debit", "financial"]
        if any(keyword in report_name.lower() for keyword in financial_keywords):
            if len(roles) > 4:
                analysis["issues"].append(f"FINANCIAL_BROAD_ACCESS: Financial report has {len(roles)} roles")

        return analysis

    except Exception as e:
        return {
            "name": report_name,
            "error": f"Report analysis failed: {str(e)}",
            "issues": [f"ANALYSIS_ERROR: {str(e)}"],
        }


def analyze_verenigingen_dashboard(dashboard_info):
    """Analyze permissions for a Verenigingen Dashboard"""

    dashboard_name = dashboard_info["name"]

    try:
        # Get dashboard roles
        dashboard_roles = frappe.db.sql(
            """
            SELECT role
            FROM `tabHas Role`
            WHERE parent = %s AND parenttype = 'Dashboard'
        """,
            dashboard_name,
            as_dict=True,
        )

        # Get dashboard charts and their data sources
        dashboard_charts = frappe.db.sql(
            """
            SELECT chart_name, chart
            FROM `tabDashboard Chart Link`
            WHERE parent = %s
        """,
            dashboard_name,
            as_dict=True,
        )

        analysis = {
            "name": dashboard_name,
            "module": dashboard_info.get("module"),
            "dashboard_name": dashboard_info.get("dashboard_name"),
            "roles": [r["role"] for r in dashboard_roles],
            "charts": [c["chart_name"] for c in dashboard_charts],
            "chart_count": len(dashboard_charts),
            "issues": [],
        }

        roles = analysis["roles"]

        # Issue 1: No roles assigned
        if not roles:
            analysis["issues"].append("NO_ROLES: Dashboard has no assigned roles, may be inaccessible")

        # Issue 2: Public access
        if "All" in roles or "Guest" in roles:
            # Check if dashboard contains sensitive data
            sensitive_keywords = ["member", "volunteer", "donation", "payment", "financial", "sepa"]
            if any(keyword in dashboard_name.lower() for keyword in sensitive_keywords):
                analysis["issues"].append(
                    "PUBLIC_ACCESS_SENSITIVE: Dashboard with sensitive data has public access"
                )
            else:
                analysis["issues"].append("PUBLIC_ACCESS: Dashboard has public access")

        # Issue 3: Too many roles for sensitive dashboards
        sensitive_keywords = ["member", "volunteer", "donation", "payment", "financial", "sepa", "board"]
        if any(keyword in dashboard_name.lower() for keyword in sensitive_keywords) and len(roles) > 6:
            analysis["issues"].append(f"BROAD_ACCESS_SENSITIVE: Sensitive dashboard has {len(roles)} roles")

        # Issue 4: Dashboards with many charts but broad access
        if analysis["chart_count"] > 5 and len(roles) > 8:
            analysis["issues"].append(
                f"COMPLEX_DASHBOARD_BROAD_ACCESS: Dashboard with {analysis['chart_count']} charts has {len(roles)} roles"
            )

        return analysis

    except Exception as e:
        return {
            "name": dashboard_name,
            "error": f"Dashboard analysis failed: {str(e)}",
            "issues": [f"ANALYSIS_ERROR: {str(e)}"],
        }


def create_reports_dashboards_summary(audit_results):
    """Create human-readable summary report for Reports and Dashboards"""

    report_lines = [
        "# Verenigingen Reports & Dashboards Permissions Audit",
        f"Generated: {audit_results['metadata']['audit_timestamp']}",
        "",
        "## Overview",
        f"- Total Reports: {audit_results['metadata']['total_reports']}",
        f"- Total Dashboards: {audit_results['metadata']['total_dashboards']}",
        f"- Reports with Issues: {audit_results['summary']['reports_with_issues']}",
        f"- Dashboards with Issues: {audit_results['summary']['dashboards_with_issues']}",
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
            report_lines.append(f"**{issue['type']}: {issue['name']}** - {issue['issue']}")
        report_lines.append("")

    # High priority issues
    if audit_results["priority_fixes"]["high"]:
        report_lines.extend(["## ⚠️ HIGH Priority Issues", ""])
        for issue in audit_results["priority_fixes"]["high"]:
            report_lines.append(f"**{issue['type']}: {issue['name']}** - {issue['issue']}")
        report_lines.append("")

    # Module breakdown for reports
    if audit_results["summary"]["reports_by_module"]:
        report_lines.extend(["## Reports by Module", ""])
        for module, reports in audit_results["summary"]["reports_by_module"].items():
            report_lines.append(f"### {module} ({len(reports)} reports)")
            for report in reports:
                has_issues = any(r["name"] == report for r in audit_results["report_issues"])
                status = " ⚠️" if has_issues else " ✅"
                report_lines.append(f"- {report}{status}")
            report_lines.append("")

    # Module breakdown for dashboards
    if audit_results["summary"]["dashboards_by_module"]:
        report_lines.extend(["## Dashboards by Module", ""])
        for module, dashboards in audit_results["summary"]["dashboards_by_module"].items():
            report_lines.append(f"### {module} ({len(dashboards)} dashboards)")
            for dashboard in dashboards:
                has_issues = any(d["name"] == dashboard for d in audit_results["dashboard_issues"])
                status = " ⚠️" if has_issues else " ✅"
                report_lines.append(f"- {dashboard}{status}")
            report_lines.append("")

    # Detailed issues
    if audit_results["report_issues"]:
        report_lines.extend(["## Detailed Report Issues", ""])
        for report_issue in audit_results["report_issues"]:
            if report_issue.get("issues"):
                report_lines.append(f"### {report_issue['name']} ({report_issue.get('module', 'Unknown')})")
                if report_issue.get("ref_doctype"):
                    report_lines.append(f"**Reference DocType**: {report_issue['ref_doctype']}")
                if report_issue.get("roles"):
                    report_lines.append(f"**Current Roles**: {', '.join(report_issue['roles'])}")
                report_lines.append("**Issues**:")
                for issue in report_issue["issues"]:
                    report_lines.append(f"- {issue}")
                report_lines.append("")

    if audit_results["dashboard_issues"]:
        report_lines.extend(["## Detailed Dashboard Issues", ""])
        for dashboard_issue in audit_results["dashboard_issues"]:
            if dashboard_issue.get("issues"):
                report_lines.append(
                    f"### {dashboard_issue['name']} ({dashboard_issue.get('module', 'Unknown')})"
                )
                if dashboard_issue.get("roles"):
                    report_lines.append(f"**Current Roles**: {', '.join(dashboard_issue['roles'])}")
                if dashboard_issue.get("chart_count"):
                    report_lines.append(f"**Chart Count**: {dashboard_issue['chart_count']}")
                report_lines.append("**Issues**:")
                for issue in dashboard_issue["issues"]:
                    report_lines.append(f"- {issue}")
                report_lines.append("")

    # Save summary report
    summary_file = (
        "/home/frappe/frappe-bench/apps/verenigingen/docs/VERENIGINGEN_REPORTS_DASHBOARDS_SUMMARY.md"
    )
    with open(summary_file, "w") as f:
        f.write("\n".join(report_lines))
