# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    summary = get_report_summary(data, filters)
    chart = get_chart_data(data)
    return columns, data, None, chart, summary


def get_columns():
    return [
        _("Member ID") + ":Link/Member:120",
        _("Member Name") + ":Data:180",
        _("Email") + ":Data:200",
        _("Member Status") + ":Data:100",
        _("Customer") + ":Link/Customer:120",
        _("Member Since") + ":Date:100",
        _("Dues Schedule Status") + ":HTML:120",
        _("Last Invoice Date") + ":Date:100",
        _("Next Invoice Date") + ":Date:100",
        _("Days Overdue") + ":Int:80",
        _("Billing Frequency") + ":Data:100",
        _("Dues Rate") + ":Currency:100",
        _("Coverage Gap") + ":HTML:120",
        _("Recent Invoices") + ":Int:80",
        _("Action Required") + ":HTML:150",
    ]


def get_data(filters=None):
    """Get all active members and analyze their dues schedule status"""

    if not filters:
        filters = {}

    # Build member filters
    member_filters = {"docstatus": ["!=", 2]}

    # Apply member status filter
    if not filters.get("include_terminated"):
        member_filters["status"] = ["!=", "Terminated"]
    if not filters.get("include_suspended"):
        if "status" in member_filters:
            # Handle multiple status exclusions
            member_filters["status"] = ["not in", ["Terminated", "Suspended"]]
        else:
            member_filters["status"] = ["!=", "Suspended"]

    if filters.get("member_status"):
        member_filters["status"] = filters.get("member_status")

    # Get all members
    members = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=["name", "full_name", "email", "status", "customer", "member_since"],
        order_by="member_since desc",
    )

    if not members:
        return []

    data = []
    today_date = getdate(today())

    for member in members:
        if not member.customer:
            continue

        # Get dues schedule information
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
            fields=[
                "name",
                "next_invoice_date",
                "last_invoice_date",
                "billing_frequency",
                "dues_rate",
                "auto_generate",
            ],
            order_by="modified desc",
            limit=1,
        )

        # Get recent invoices count
        recent_invoices_count = frappe.db.count(
            "Sales Invoice",
            filters={
                "customer": member.customer,
                "posting_date": [">=", frappe.utils.add_days(today(), -30)],
                "docstatus": ["!=", 2],
            },
        )

        # Analyze schedule status
        if not schedules:
            # No active dues schedule
            row = {
                "member_id": member.name,
                "member_name": member.full_name,
                "email": member.email,
                "member_status": member.status,
                "customer": member.customer,
                "member_since": member.member_since,
                "dues_schedule_status": '<span class="indicator red">No Schedule</span>',
                "last_invoice_date": None,
                "next_invoice_date": None,
                "days_overdue": 0,
                "billing_frequency": None,
                "dues_rate": None,
                "coverage_gap": '<span class="indicator red">No Coverage</span>',
                "recent_invoices": recent_invoices_count,
                "action_required": '<span class="indicator red">Create Schedule</span>',
            }
            data.append(row)
            continue

        # Analyze existing schedule
        schedule = schedules[0]
        days_overdue = 0

        if schedule.next_invoice_date:
            next_date = getdate(schedule.next_invoice_date)
            if next_date < today_date:
                days_overdue = date_diff(today_date, next_date)

        # Determine status and actions
        schedule_status = "Active"
        status_color = "green"
        coverage_gap = "Active"
        gap_color = "green"
        action_required = "None"
        action_color = "green"

        if days_overdue > 14:
            schedule_status = "Critical"
            status_color = "red"
            coverage_gap = f"Critical Gap ({days_overdue} days)"
            gap_color = "red"
            action_required = "Urgent Fix Required"
            action_color = "red"
        elif days_overdue > 7:
            schedule_status = "Overdue"
            status_color = "orange"
            coverage_gap = f"Gap ({days_overdue} days)"
            gap_color = "orange"
            action_required = "Fix Overdue"
            action_color = "orange"
        elif days_overdue > 0:
            schedule_status = "Behind"
            status_color = "yellow"
            coverage_gap = f"Minor Gap ({days_overdue} days)"
            gap_color = "yellow"
            action_required = "Check Schedule"
            action_color = "yellow"
        elif not schedule.get("auto_generate", True):
            schedule_status = "Manual"
            status_color = "blue"
            coverage_gap = "Manual Mode"
            gap_color = "blue"
            action_required = "Monitor"
            action_color = "blue"

        # Apply filters for problematic schedules only
        if filters.get("problems_only"):
            if days_overdue == 0 and schedule.get("auto_generate", True):
                continue  # Skip healthy schedules

        if filters.get("critical_only"):
            if days_overdue <= 7:
                continue  # Skip non-critical

        row = {
            "member_id": member.name,
            "member_name": member.full_name,
            "email": member.email,
            "member_status": member.status,
            "customer": member.customer,
            "member_since": member.member_since,
            "dues_schedule_status": f'<span class="indicator {status_color}">{schedule_status}</span>',
            "last_invoice_date": schedule.last_invoice_date,
            "next_invoice_date": schedule.next_invoice_date,
            "days_overdue": days_overdue,
            "billing_frequency": schedule.billing_frequency,
            "dues_rate": schedule.dues_rate,
            "coverage_gap": f'<span class="indicator {gap_color}">{coverage_gap}</span>',
            "recent_invoices": recent_invoices_count,
            "action_required": f'<span class="indicator {action_color}">{action_required}</span>',
        }
        data.append(row)

    # Sort by priority: no schedule first, then by days overdue descending
    data.sort(key=lambda x: (0 if "No Schedule" in x["dues_schedule_status"] else 1, -x["days_overdue"]))

    return data


def get_report_summary(data, filters=None):
    """Generate comprehensive summary statistics"""
    if not data:
        return []

    total_members = len(data)
    no_schedule = len([d for d in data if "No Schedule" in d["dues_schedule_status"]])
    critical_issues = len([d for d in data if d["days_overdue"] > 14])
    overdue_issues = len([d for d in data if 0 < d["days_overdue"] <= 14])
    healthy_schedules = len(
        [d for d in data if d["days_overdue"] == 0 and "Active" in d["dues_schedule_status"]]
    )

    # Calculate estimated financial impact
    total_overdue_amount = 0
    for row in data:
        if row["days_overdue"] > 0 and row["dues_rate"]:
            rate = float(row["dues_rate"] or 0)
            days = row["days_overdue"]
            billing_freq = row["billing_frequency"] or "Daily"

            if billing_freq == "Daily":
                total_overdue_amount += rate * days
            elif billing_freq == "Weekly":
                total_overdue_amount += rate * (days / 7)
            elif billing_freq == "Monthly":
                total_overdue_amount += rate * (days / 30)

    return [
        {"value": total_members, "label": _("Total Members Analyzed"), "datatype": "Int"},
        {
            "value": no_schedule,
            "label": _("Members Without Schedule"),
            "datatype": "Int",
            "color": "red" if no_schedule > 0 else "green",
        },
        {
            "value": critical_issues,
            "label": _("Critical Issues (>14 days)"),
            "datatype": "Int",
            "color": "red" if critical_issues > 0 else "green",
        },
        {
            "value": overdue_issues,
            "label": _("Overdue Issues (1-14 days)"),
            "datatype": "Int",
            "color": "orange" if overdue_issues > 0 else "green",
        },
        {"value": healthy_schedules, "label": _("Healthy Schedules"), "datatype": "Int", "color": "green"},
        {
            "value": total_overdue_amount,
            "label": _("Estimated Overdue Amount"),
            "datatype": "Currency",
            "color": "red"
            if total_overdue_amount > 100
            else "orange"
            if total_overdue_amount > 0
            else "green",
        },
    ]


def get_chart_data(data):
    """Generate chart showing schedule status distribution"""
    if not data:
        return None

    status_counts = {"No Schedule": 0, "Critical": 0, "Overdue": 0, "Behind": 0, "Active": 0, "Manual": 0}

    for row in data:
        status_html = row["dues_schedule_status"]
        if "No Schedule" in status_html:
            status_counts["No Schedule"] += 1
        elif "Critical" in status_html:
            status_counts["Critical"] += 1
        elif "Overdue" in status_html:
            status_counts["Overdue"] += 1
        elif "Behind" in status_html:
            status_counts["Behind"] += 1
        elif "Manual" in status_html:
            status_counts["Manual"] += 1
        elif "Active" in status_html:
            status_counts["Active"] += 1

    # Filter out zero values
    filtered_counts = {k: v for k, v in status_counts.items() if v > 0}

    return {
        "data": {
            "labels": list(filtered_counts.keys()),
            "datasets": [{"name": _("Member Count"), "values": list(filtered_counts.values())}],
        },
        "type": "pie",
        "colors": ["#ff4757", "#ff6348", "#ffa502", "#fffa65", "#2ed573", "#70a1ff"],
    }


@frappe.whitelist()
def get_coverage_gap_analysis():
    """API function to get detailed coverage gap analysis"""
    try:
        # Use the existing comprehensive analysis from test_fixes.py
        from verenigingen.api.test_fixes import analyze_invoice_coverage_gaps

        result = analyze_invoice_coverage_gaps()
        if result.get("success"):
            return {"success": True, "analysis": result["coverage_analysis"]}
        else:
            return {"success": False, "error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_member_schedule_issues(member_list):
    """API function to batch fix member schedule issues"""
    try:
        if isinstance(member_list, str):
            import json

            member_list = json.loads(member_list)

        results = []
        from verenigingen.api.test_fixes import fix_schedule_dates

        for member_id in member_list:
            try:
                # Get member's schedule
                schedules = frappe.get_all(
                    "Membership Dues Schedule",
                    filters={"member": member_id, "status": "Active"},
                    fields=["name"],
                    limit=1,
                )

                if schedules:
                    # Fix the schedule
                    fix_result = fix_schedule_dates(schedules[0].name)
                    results.append(
                        {
                            "member": member_id,
                            "schedule": schedules[0].name,
                            "success": fix_result.get("success", False),
                            "message": fix_result.get("message", "Unknown result"),
                        }
                    )
                else:
                    results.append(
                        {"member": member_id, "success": False, "message": "No active schedule found"}
                    )
            except Exception as e:
                results.append({"member": member_id, "success": False, "message": str(e)})

        success_count = len([r for r in results if r["success"]])

        return {
            "success": True,
            "total_processed": len(member_list),
            "success_count": success_count,
            "results": results,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
