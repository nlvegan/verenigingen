import frappe


@frappe.whitelist()
def check_sensitive_report_permissions():
    """Check permissions for specific sensitive reports"""

    # Define sensitive reports to check
    sensitive_reports = [
        "Chapter Members",
        "New Members",
        "Overdue Member Payments",
        "ANBI Donation Summary",
        "Membership Dues Coverage Analysis",
        "Pending Membership Applications",
        "Team Members",
    ]

    results = {}

    for report_name in sensitive_reports:
        try:
            # Check if report exists
            if not frappe.db.exists("Report", report_name):
                results[report_name] = {"error": "Report does not exist"}
                continue

            # Get report details
            report_doc = frappe.get_doc("Report", report_name)

            # Get roles that have access to this report
            report_roles = frappe.db.sql(
                """
                SELECT role
                FROM `tabHas Role`
                WHERE parent = %s AND parenttype = 'Report'
                ORDER BY role
            """,
                report_name,
                as_dict=True,
            )

            roles = [r["role"] for r in report_roles]

            results[report_name] = {
                "ref_doctype": report_doc.ref_doctype,
                "report_type": report_doc.report_type,
                "roles": roles,
                "role_count": len(roles),
                "has_public_access": "All" in roles or "Guest" in roles,
                "has_member_role": "Verenigingen Member" in roles,
                "analysis": analyze_report_security(report_name, roles, report_doc.ref_doctype),
            }

        except Exception as e:
            results[report_name] = {"error": str(e)}

    return results


def analyze_report_security(report_name, roles, ref_doctype):
    """Analyze security level of a report"""

    analysis = {"security_level": "UNKNOWN", "concerns": [], "recommendations": []}

    # Security level assessment
    if not roles:
        analysis["security_level"] = "NO_ACCESS"
        analysis["concerns"].append("Report has no assigned roles")
        analysis["recommendations"].append("Assign appropriate roles to make report accessible")
    elif "All" in roles or "Guest" in roles:
        analysis["security_level"] = "PUBLIC"
        analysis["concerns"].append("Report has public access")
        if ref_doctype in ["Member", "Volunteer", "Donation", "Payment Entry"]:
            analysis["concerns"].append("Public access to sensitive data")
            analysis["recommendations"].append("Remove public access and restrict to admin roles only")
    elif len(roles) > 6:
        analysis["security_level"] = "BROAD"
        analysis["concerns"].append(f"Report accessible to {len(roles)} roles")
        analysis["recommendations"].append("Consider reducing number of roles with access")
    elif any(role in roles for role in ["System Manager", "Verenigingen Administrator"]):
        if len(roles) <= 4:
            analysis["security_level"] = "SECURE"
        else:
            analysis["security_level"] = "MODERATE"
    else:
        analysis["security_level"] = "RESTRICTED"

    # Specific concerns for member data
    if ref_doctype in ["Member", "Volunteer"] and "Verenigingen Member" in roles:
        analysis["concerns"].append("Members can access reports about other members")
        analysis["recommendations"].append("Restrict member access or ensure report shows only own data")

    # Financial data concerns
    financial_keywords = ["payment", "donation", "dues", "financial"]
    if any(keyword in report_name.lower() for keyword in financial_keywords):
        non_financial_roles = [
            r
            for r in roles
            if r
            not in [
                "System Manager",
                "Verenigingen Administrator",
                "Verenigingen Manager",
                "Accounts Manager",
            ]
        ]
        if non_financial_roles:
            analysis["concerns"].append("Financial report accessible to non-financial roles")
            analysis["recommendations"].append("Restrict to financial and admin roles only")

    return analysis


@frappe.whitelist()
def get_all_report_permissions():
    """Get permissions for all Verenigingen reports"""

    # Get all Verenigingen reports
    reports = frappe.db.sql(
        """
        SELECT name, ref_doctype, report_type, module
        FROM `tabReport`
        WHERE module IN (
            SELECT name FROM `tabModule Def` WHERE app_name = 'verenigingen'
        )
        ORDER BY name
    """,
        as_dict=True,
    )

    results = {}

    for report in reports:
        # Get roles for this report
        roles = frappe.db.sql(
            """
            SELECT role
            FROM `tabHas Role`
            WHERE parent = %s AND parenttype = 'Report'
            ORDER BY role
        """,
            report["name"],
            as_dict=True,
        )

        results[report["name"]] = {
            "module": report["module"],
            "ref_doctype": report["ref_doctype"],
            "report_type": report["report_type"],
            "roles": [r["role"] for r in roles],
        }

    return results
