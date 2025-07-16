import frappe
from frappe.utils import add_days, getdate, today

# ===== Your existing functions from paste.txt go here =====


@frappe.whitelist()
def validate_termination_readiness(member_name):
    """
    Validate if a member is ready for termination and return impact assessment
    """
    try:
        member = frappe.get_doc("Member", member_name)

        readiness = {
            "ready": True,
            "warnings": [],
            "blockers": [],
            "impact": {
                "active_memberships": 0,
                "sepa_mandates": 0,
                "board_positions": 0,
                "outstanding_invoices": 0,
                "active_subscriptions": 0,
                "volunteer_records": 0,
                "pending_volunteer_expenses": 0,
                "employee_records": 0,
                "user_account": False,
            },
        }

        # Check active memberships
        active_memberships = frappe.db.count(
            "Membership", {"member": member_name, "status": ["in", ["Active", "Pending"]], "docstatus": 1}
        )
        readiness["impact"]["active_memberships"] = active_memberships

        if active_memberships > 1:
            readiness["warnings"].append(f"Member has {active_memberships} active memberships")

        # Check SEPA mandates
        active_mandates = frappe.db.count(
            "SEPA Mandate", {"member": member_name, "status": "Active", "is_active": 1}
        )
        readiness["impact"]["sepa_mandates"] = active_mandates

        # Check board positions - look for both volunteer-linked and direct member-linked positions
        board_positions = 0

        # Method 1: Check via volunteer records
        volunteer_records = frappe.get_all("Volunteer", filters={"member": member_name}, fields=["name"])
        for volunteer in volunteer_records:
            board_positions += frappe.db.count(
                "Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}
            )

        # Method 2: Check for direct member linkage (if Chapter Board Member has member field)
        try:
            direct_board_positions = frappe.db.count(
                "Chapter Board Member", {"member": member_name, "is_active": 1}
            )
            board_positions += direct_board_positions
        except Exception:
            # If member field doesn't exist in Chapter Board Member, that's OK
            pass

        readiness["impact"]["board_positions"] = board_positions

        if board_positions > 0:
            readiness["warnings"].append(f"Member holds {board_positions} board position(s)")

        # Check outstanding invoices and subscriptions
        if member.customer:
            outstanding_invoices = frappe.db.count(
                "Sales Invoice",
                {
                    "customer": member.customer,
                    "docstatus": 1,
                    "status": ["in", ["Unpaid", "Overdue", "Partially Paid"]],
                },
            )
            readiness["impact"]["outstanding_invoices"] = outstanding_invoices

            active_subscriptions = frappe.db.count(
                "Subscription",
                {
                    "party_type": "Customer",
                    "party": member.customer,
                    "status": ["in", ["Active", "Past Due"]],
                },
            )
            readiness["impact"]["active_subscriptions"] = active_subscriptions

            if outstanding_invoices > 5:
                readiness["warnings"].append(f"Member has {outstanding_invoices} outstanding invoices")

        # Check for existing termination requests
        existing_requests = frappe.db.count(
            "Membership Termination Request",
            {"member": member_name, "status": ["in", ["Draft", "Pending", "Approved"]]},
        )

        if existing_requests > 0:
            readiness["ready"] = False
            readiness["blockers"].append("Member already has pending termination request(s)")

        # Check volunteer records
        volunteer_records = frappe.db.count(
            "Volunteer", {"member": member_name, "status": ["in", ["Active", "On Leave"]]}
        )
        readiness["impact"]["volunteer_records"] = volunteer_records

        if volunteer_records > 0:
            readiness["warnings"].append(f"Member has {volunteer_records} active volunteer record(s)")

            # Check pending volunteer expenses
            pending_expenses = frappe.db.sql(
                """
                SELECT COUNT(*)
                FROM `tabVolunteer Expense` ve
                INNER JOIN `tabVolunteer` v ON ve.volunteer = v.name
                WHERE v.member = %s
                AND ve.docstatus = 0
                AND ve.approval_status IN ('Pending', 'Under Review')
            """,
                (member_name,),
            )[0][0]

            readiness["impact"]["pending_volunteer_expenses"] = pending_expenses
            if pending_expenses > 0:
                readiness["warnings"].append(f"Member has {pending_expenses} pending volunteer expense(s)")

        # Check employee records and user account
        user_email = frappe.db.get_value("Member", member_name, "user")
        employee_records = 0

        if user_email:
            readiness["impact"]["user_account"] = True

            # Method 1: Check via user_id linkage (existing logic)
            employee_records = frappe.db.count(
                "Employee", {"user_id": user_email, "status": ["in", ["Active", "On Leave"]]}
            )

            # If no results with user_id, try alternative field names
            if employee_records == 0:
                # Try with email field (some ERPNext versions use this)
                employee_records += frappe.db.count(
                    "Employee", {"personal_email": user_email, "status": ["in", ["Active", "On Leave"]]}
                )

                # Try with company_email field
                if employee_records == 0:
                    employee_records += frappe.db.count(
                        "Employee", {"company_email": user_email, "status": ["in", ["Active", "On Leave"]]}
                    )

        # Method 2: Check direct employee link from Member doctype
        # This handles cases where member.employee is set but member.user is not,
        # or where the employee record doesn't have the correct user_id
        direct_employee_link = frappe.db.get_value("Member", member_name, "employee")
        if direct_employee_link and frappe.db.exists("Employee", direct_employee_link):
            # Check if this employee is active
            employee_status = frappe.db.get_value("Employee", direct_employee_link, "status")
            if employee_status in ["Active", "On Leave"]:
                # Avoid double counting - check if this employee is already counted
                employee_user_id = frappe.db.get_value("Employee", direct_employee_link, "user_id")
                if not user_email or employee_user_id != user_email:
                    # Either no user email or different employee, add to count
                    employee_records += 1

        readiness["impact"]["employee_records"] = employee_records

        if employee_records > 0:
            readiness["warnings"].append(f"Member has {employee_records} active employee record(s)")

        return readiness

    except Exception as e:
        return {"ready": False, "error": str(e)}


@frappe.whitelist()
def get_termination_impact_summary(member_name):
    """
    Get a summary of what will be affected by member termination
    """
    try:
        readiness = validate_termination_readiness(member_name)
        impact = readiness.get("impact", {})

        summary = {
            "member_name": frappe.db.get_value("Member", member_name, "full_name"),
            "total_items_affected": sum(impact.values()),
            "categories": [],
        }

        if impact.get("active_memberships", 0) > 0:
            summary["categories"].append(
                {
                    "category": "Memberships",
                    "count": impact["active_memberships"],
                    "action": "Will be cancelled",
                }
            )

        if impact.get("sepa_mandates", 0) > 0:
            summary["categories"].append(
                {"category": "SEPA Mandates", "count": impact["sepa_mandates"], "action": "Will be cancelled"}
            )

        if impact.get("board_positions", 0) > 0:
            summary["categories"].append(
                {"category": "Board Positions", "count": impact["board_positions"], "action": "Will be ended"}
            )

        if impact.get("outstanding_invoices", 0) > 0:
            summary["categories"].append(
                {
                    "category": "Outstanding Invoices",
                    "count": impact["outstanding_invoices"],
                    "action": "Will be annotated",
                }
            )

        if impact.get("active_subscriptions", 0) > 0:
            summary["categories"].append(
                {
                    "category": "Active Subscriptions",
                    "count": impact["active_subscriptions"],
                    "action": "Will be cancelled",
                }
            )

        summary["warnings"] = readiness.get("warnings", [])
        summary["blockers"] = readiness.get("blockers", [])
        summary["ready_for_termination"] = readiness.get("ready", False)

        return summary

    except Exception as e:
        return {"error": str(e)}


# ===== Optional Scheduler Functions =====
# Add these if you want automated processing


def process_overdue_termination_requests():
    """
    OPTIONAL: Scheduled task to process overdue termination requests
    Called daily by scheduler if enabled in hooks.py
    """
    try:
        # Find requests that have been pending approval for more than 7 days
        overdue_requests = frappe.get_all(
            "Membership Termination Request",
            filters={"status": "Pending", "request_date": ["<", add_days(today(), -7)]},
            fields=["name", "member_name", "requested_by", "request_date", "termination_type"],
        )

        if overdue_requests:
            frappe.logger().warning(f"Found {len(overdue_requests)} overdue termination requests")

            # Send notification to administrators
            administrators = frappe.get_all(
                "User", filters={"role_profile_name": ["like", "%System Manager%"]}, fields=["email"]
            )

            if administrators:
                admin_emails = [admin.email for admin in administrators if admin.email]

                if admin_emails:
                    # Create email content
                    email_content = """
                    <h3>Overdue Termination Requests</h3>
                    <p>The following termination requests have been pending for more than 7 days:</p>
                    <table border="1" style="border-collapse: collapse;">
                        <tr>
                            <th>Request ID</th>
                            <th>Member</th>
                            <th>Type</th>
                            <th>Request Date</th>
                            <th>Days Overdue</th>
                        </tr>
                    """

                    for request in overdue_requests:
                        days_overdue = (getdate(today()) - getdate(request.request_date)).days
                        email_content += f"""
                        <tr>
                            <td>{request.name}</td>
                            <td>{request.member_name}</td>
                            <td>{request.termination_type}</td>
                            <td>{request.request_date}</td>
                            <td>{days_overdue}</td>
                        </tr>
                        """

                    email_content += "</table>"

                    # Send email
                    frappe.sendmail(
                        recipients=admin_emails,
                        subject=f"Overdue Termination Requests - {len(overdue_requests)} items",
                        message=email_content,
                    )

                    frappe.logger().info(
                        f"Sent overdue termination notification to {len(admin_emails)} administrators"
                    )

        return {"processed": len(overdue_requests)}

    except Exception as e:
        frappe.log_error(
            f"Error processing overdue termination requests: {str(e)}", "Termination Scheduler Error"
        )
        return {"error": str(e)}


def generate_weekly_termination_report():
    """
    OPTIONAL: Generate weekly termination report
    Called weekly by scheduler if enabled in hooks.py
    """
    try:
        # Get termination requests from the last week
        week_ago = add_days(today(), -7)

        weekly_requests = frappe.get_all(
            "Membership Termination Request",
            filters={"request_date": [">=", week_ago]},
            fields=["name", "member_name", "termination_type", "status", "request_date", "execution_date"],
        )

        if not weekly_requests:
            frappe.logger().info("No termination requests in the past week")
            return {"message": "No requests to report"}

        # Categorize requests
        report_data = {
            "total_requests": len(weekly_requests),
            "by_status": {},
            "by_type": {},
            "executed_count": 0,
            "pending_count": 0,
        }

        for request in weekly_requests:
            # Count by status
            status = request.status
            report_data["by_status"][status] = report_data["by_status"].get(status, 0) + 1

            # Count by type
            req_type = request.termination_type
            report_data["by_type"][req_type] = report_data["by_type"].get(req_type, 0) + 1

            # Count executed vs pending
            if status == "Executed":
                report_data["executed_count"] += 1
            elif status in ["Draft", "Pending", "Approved"]:
                report_data["pending_count"] += 1

        # Send report to administrators
        administrators = frappe.get_all(
            "User", filters={"role_profile_name": ["like", "%Verenigingen Administrator%"]}, fields=["email"]
        )

        if administrators:
            admin_emails = [admin.email for admin in administrators if admin.email]

            if admin_emails:
                # Create report content
                report_content = f"""
                <h3>Weekly Termination Report</h3>
                <p>Period: {week_ago} to {today()}</p>

                <h4>Summary</h4>
                <ul>
                    <li>Total Requests: {report_data['total_requests']}</li>
                    <li>Executed: {report_data['executed_count']}</li>
                    <li>Pending: {report_data['pending_count']}</li>
                </ul>

                <h4>By Status</h4>
                <ul>
                """

                for status, count in report_data["by_status"].items():
                    report_content += f"<li>{status}: {count}</li>"

                report_content += """
                </ul>

                <h4>By Type</h4>
                <ul>
                """

                for req_type, count in report_data["by_type"].items():
                    report_content += f"<li>{req_type}: {count}</li>"

                report_content += "</ul>"

                # Send email
                frappe.sendmail(
                    recipients=admin_emails,
                    subject=f"Weekly Termination Report - {report_data['total_requests']} requests",
                    message=report_content,
                )

                frappe.logger().info(f"Sent weekly termination report to {len(admin_emails)} administrators")

        return report_data

    except Exception as e:
        frappe.log_error(f"Error generating weekly termination report: {str(e)}", "Termination Report Error")
        return {"error": str(e)}


@frappe.whitelist()
def get_termination_statistics():
    """
    Get overall termination statistics for dashboard
    """
    try:
        stats = {
            "total_requests": frappe.db.count("Membership Termination Request"),
            "pending_requests": frappe.db.count("Membership Termination Request", {"status": "Pending"}),
            "executed_requests": frappe.db.count("Membership Termination Request", {"status": "Executed"}),
            "this_month": frappe.db.count(
                "Membership Termination Request", {"request_date": [">=", today().replace(day=1)]}
            ),
        }

        # Get breakdown by type
        type_breakdown = frappe.db.sql(
            """
            SELECT termination_type, COUNT(*) as count
            FROM `tabMembership Termination Request`
            GROUP BY termination_type
        """,
            as_dict=True,
        )

        stats["by_type"] = {row.termination_type: row.count for row in type_breakdown}

        return stats

    except Exception as e:
        return {"error": str(e)}


def audit_termination_compliance():
    """
    Daily audit of termination compliance and data integrity
    """
    try:
        audit_results = {
            "orphaned_records": 0,
            "stale_requests": 0,
            "compliance_issues": [],
            "data_integrity_issues": [],
        }

        # Check for orphaned termination requests (member doesn't exist)
        orphaned_requests = frappe.db.sql(
            """
            SELECT mtr.name, mtr.member_name
            FROM `tabMembership Termination Request` mtr
            LEFT JOIN `tabMember` m ON mtr.member_name = m.name
            WHERE m.name IS NULL
        """,
            as_dict=True,
        )

        audit_results["orphaned_records"] = len(orphaned_requests)

        if orphaned_requests:
            for request in orphaned_requests:
                audit_results["data_integrity_issues"].append(
                    f"Termination request {request.name} references non-existent member {request.member_name}"
                )

        # Check for stale requests (approved but not executed after 30 days)
        stale_requests = frappe.db.sql(
            """
            SELECT name, member_name, request_date, status
            FROM `tabMembership Termination Request`
            WHERE status = 'Approved'
            AND request_date < %s
        """,
            [add_days(today(), -30)],
            as_dict=True,
        )

        audit_results["stale_requests"] = len(stale_requests)

        if stale_requests:
            for request in stale_requests:
                audit_results["compliance_issues"].append(
                    f"Request {request.name} has been approved but not executed for over 30 days"
                )

        # Check for members with multiple active termination requests
        duplicate_requests = frappe.db.sql(
            """
            SELECT member_name, COUNT(*) as count
            FROM `tabMembership Termination Request`
            WHERE status IN ('Draft', 'Pending', 'Approved')
            GROUP BY member_name
            HAVING COUNT(*) > 1
        """,
            as_dict=True,
        )

        if duplicate_requests:
            for dup in duplicate_requests:
                audit_results["compliance_issues"].append(
                    f"Member {dup.member_name} has {dup.count} active termination requests"
                )

        # Log significant issues
        total_issues = len(audit_results["compliance_issues"]) + len(audit_results["data_integrity_issues"])

        if total_issues > 0:
            frappe.logger().warning(f"Termination compliance audit found {total_issues} issues")

            # If critical issues, notify administrators
            if audit_results["orphaned_records"] > 0 or audit_results["stale_requests"] > 5:
                administrators = frappe.get_all(
                    "User", filters={"role_profile_name": ["like", "%System Manager%"]}, fields=["email"]
                )

                if administrators:
                    admin_emails = [admin.email for admin in administrators if admin.email]

                    if admin_emails:
                        email_content = f"""
                        <h3>Termination Compliance Alert</h3>
                        <p>The daily audit has identified compliance issues that require attention:</p>

                        <h4>Summary</h4>
                        <ul>
                            <li>Orphaned Records: {audit_results['orphaned_records']}</li>
                            <li>Stale Requests: {audit_results['stale_requests']}</li>
                            <li>Total Issues: {total_issues}</li>
                        </ul>
                        """

                        if audit_results["compliance_issues"]:
                            email_content += "<h4>Compliance Issues</h4><ul>"
                            for issue in audit_results["compliance_issues"][:10]:  # Limit to first 10
                                email_content += f"<li>{issue}</li>"
                            email_content += "</ul>"

                        if audit_results["data_integrity_issues"]:
                            email_content += "<h4>Data Integrity Issues</h4><ul>"
                            for issue in audit_results["data_integrity_issues"][:10]:  # Limit to first 10
                                email_content += f"<li>{issue}</li>"
                            email_content += "</ul>"

                        frappe.sendmail(
                            recipients=admin_emails,
                            subject="Termination Compliance Issues Detected",
                            message=email_content,
                        )
        else:
            frappe.logger().info("Termination compliance audit completed - no issues found")

        return audit_results

    except Exception as e:
        frappe.log_error(
            f"Error in termination compliance audit: {str(e)}", "Termination Compliance Audit Error"
        )
        return {"error": str(e)}
