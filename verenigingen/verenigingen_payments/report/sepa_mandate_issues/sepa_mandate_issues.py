# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""
SEPA Mandate Issues Report

Query report that displays SEPA mandate synchronization issues.
Uses the same detection logic as the SEPA Mandate Diagnostics page
and the daily SEPA Mandate Sync scheduled task.
"""

import frappe
from frappe import _


def execute(filters=None):
    """Generate SEPA Mandate Issues Report"""
    columns = get_columns(filters)
    data = get_data(filters)
    summary = get_summary(data)
    chart = get_chart_data(data)
    return columns, data, None, chart, summary


def get_columns(filters=None):
    """Define report columns based on selected issue type"""
    issue_type = filters.get("issue_type") if filters else None

    base_columns = [
        {
            "label": _("Member ID"),
            "fieldname": "member_id",
            "fieldtype": "Link",
            "options": "Member",
            "width": 150,
        },
        {"label": _("Member Name"), "fieldname": "full_name", "fieldtype": "Data", "width": 180},
        {
            "label": _("Issue Type"),
            "fieldname": "issue_type",
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "label": _("Severity"),
            "fieldname": "severity",
            "fieldtype": "Data",
            "width": 100,
        },
    ]

    # Add issue-type specific columns
    if issue_type == "multiple_current_mandates":
        base_columns.extend(
            [
                {"label": _("Current Count"), "fieldname": "current_count", "fieldtype": "Int", "width": 100},
                {"label": _("Mandate IDs"), "fieldname": "mandate_ids", "fieldtype": "Data", "width": 250},
            ]
        )
    elif issue_type == "mandate_member_data_mismatch":
        base_columns.extend(
            [
                {"label": _("Mandate ID"), "fieldname": "mandate_id", "fieldtype": "Data", "width": 150},
                {
                    "label": _("Mismatch Type"),
                    "fieldname": "mismatch_type",
                    "fieldtype": "Data",
                    "width": 120,
                },
                {"label": _("Member IBAN"), "fieldname": "member_iban", "fieldtype": "Data", "width": 180},
                {"label": _("Mandate IBAN"), "fieldname": "mandate_iban", "fieldtype": "Data", "width": 180},
                {
                    "label": _("Member Account Holder"),
                    "fieldname": "member_account_holder",
                    "fieldtype": "Data",
                    "width": 180,
                },
                {
                    "label": _("Mandate Account Holder"),
                    "fieldname": "mandate_account_holder",
                    "fieldtype": "Data",
                    "width": 180,
                },
            ]
        )
    elif issue_type == "sepa_selected_no_mandate":
        base_columns.extend(
            [
                {
                    "label": _("Payment Method"),
                    "fieldname": "payment_method",
                    "fieldtype": "Data",
                    "width": 140,
                },
                {"label": _("IBAN"), "fieldname": "iban", "fieldtype": "Data", "width": 180},
                {
                    "label": _("Banking Status"),
                    "fieldname": "banking_status",
                    "fieldtype": "Data",
                    "width": 140,
                },
                {
                    "label": _("Total Mandates"),
                    "fieldname": "total_mandates",
                    "fieldtype": "Int",
                    "width": 100,
                },
                {
                    "label": _("Active Mandates"),
                    "fieldname": "active_mandates",
                    "fieldtype": "Int",
                    "width": 100,
                },
            ]
        )
    elif issue_type == "missing_child_table_entries":
        base_columns.extend(
            [
                {"label": _("Mandate Count"), "fieldname": "mandate_count", "fieldtype": "Int", "width": 100},
                {"label": _("Mandate IDs"), "fieldname": "mandate_ids", "fieldtype": "Data", "width": 250},
            ]
        )
    elif issue_type == "orphaned_child_table_entries":
        base_columns.extend(
            [
                {
                    "label": _("Orphaned Mandate Ref"),
                    "fieldname": "mandate_name",
                    "fieldtype": "Data",
                    "width": 180,
                },
                {
                    "label": _("Mandate Reference"),
                    "fieldname": "mandate_reference",
                    "fieldtype": "Data",
                    "width": 180,
                },
            ]
        )
    elif issue_type == "outdated_child_table_data":
        base_columns.extend(
            [
                {"label": _("Mandate ID"), "fieldname": "mandate_id", "fieldtype": "Data", "width": 150},
                {
                    "label": _("Current Status"),
                    "fieldname": "current_status",
                    "fieldtype": "Data",
                    "width": 120,
                },
                {
                    "label": _("Child Table Status"),
                    "fieldname": "child_table_status",
                    "fieldtype": "Data",
                    "width": 120,
                },
            ]
        )
    else:
        # Default: show a details column
        base_columns.append(
            {"label": _("Details"), "fieldname": "details", "fieldtype": "Data", "width": 300}
        )

    return base_columns


def get_data(filters):
    """Get report data using shared diagnostics function"""
    from verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics import (
        get_mandate_issues,
    )

    # Get all issues from the shared diagnostics function
    diagnostic_data = get_mandate_issues()
    issues = diagnostic_data["issues"]

    # Filter by issue type if specified
    issue_type_filter = filters.get("issue_type") if filters else None
    severity_filter = filters.get("severity") if filters else None

    data = []

    for issue_key, issue_data in issues.items():
        # Skip if filtering by issue type and this isn't it
        if issue_type_filter and issue_key != issue_type_filter:
            continue

        # Skip if filtering by severity and this doesn't match
        if severity_filter and issue_data["severity"] != severity_filter:
            continue

        # Skip if no members with this issue
        if not issue_data["members"]:
            continue

        # Add each member with this issue to the data
        for member in issue_data["members"]:
            row = {
                "member_id": member.get("member_id"),
                "full_name": member.get("full_name"),
                "issue_type": issue_data["title"],
                "severity": issue_data["severity"],
            }

            # Add issue-specific fields
            if issue_key == "multiple_current_mandates":
                row["current_count"] = member.get("current_count")
                row["mandate_ids"] = member.get("mandate_ids")
            elif issue_key == "mandate_member_data_mismatch":
                row["mandate_id"] = member.get("mandate_id")
                row["mismatch_type"] = _format_mismatch_type(member.get("mismatch_type"))
                row["member_iban"] = member.get("member_iban")
                row["mandate_iban"] = member.get("mandate_iban")
                row["member_account_holder"] = member.get("member_account_holder")
                row["mandate_account_holder"] = member.get("mandate_account_holder")
            elif issue_key == "sepa_selected_no_mandate":
                row["payment_method"] = member.get("payment_method")
                row["iban"] = member.get("iban")
                row["banking_status"] = _format_banking_status(member.get("banking_status"))
                row["total_mandates"] = member.get("total_mandates")
                row["active_mandates"] = member.get("active_mandates")
            elif issue_key == "missing_child_table_entries":
                row["mandate_count"] = member.get("mandate_count")
                row["mandate_ids"] = member.get("mandate_ids")
            elif issue_key == "orphaned_child_table_entries":
                row["mandate_name"] = member.get("mandate_name")
                row["mandate_reference"] = member.get("mandate_reference")
            elif issue_key == "outdated_child_table_data":
                row["mandate_id"] = member.get("mandate_id")
                row["current_status"] = member.get("current_status")
                row["child_table_status"] = member.get("child_table_status")
            else:
                # Build generic details string
                details_parts = []
                for key, value in member.items():
                    if key not in ("member_id", "full_name") and value:
                        details_parts.append(f"{key}: {value}")
                row["details"] = ", ".join(details_parts)

            data.append(row)

    # Sort by severity (critical first) then by member name
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    data.sort(key=lambda x: (severity_order.get(x.get("severity"), 99), x.get("full_name", "")))

    return data


def _format_mismatch_type(mismatch_type):
    """Format mismatch type for display"""
    formats = {
        "iban_mismatch": _("IBAN Mismatch"),
        "holder_mismatch": _("Account Holder Mismatch"),
        "both_mismatch": _("IBAN & Holder Mismatch"),
    }
    return formats.get(mismatch_type, mismatch_type)


def _format_banking_status(banking_status):
    """Format banking status for display"""
    formats = {
        "missing_iban": _("Missing IBAN"),
        "missing_account_name": _("Missing Account Name"),
        "has_banking_data": _("Has Banking Data"),
    }
    return formats.get(banking_status, banking_status)


def get_summary(data):
    """Generate summary statistics"""
    if not data:
        return [
            {
                "value": 0,
                "label": _("Total Issues"),
                "datatype": "Int",
                "color": "green",
            }
        ]

    total_issues = len(data)
    unique_members = len(set(row.get("member_id") for row in data if row.get("member_id")))

    # Count by severity
    critical_count = len([d for d in data if d.get("severity") == "critical"])
    high_count = len([d for d in data if d.get("severity") == "high"])
    medium_count = len([d for d in data if d.get("severity") == "medium"])
    low_count = len([d for d in data if d.get("severity") == "low"])

    summary = [
        {
            "value": total_issues,
            "label": _("Total Issues"),
            "datatype": "Int",
            "color": "red" if total_issues > 0 else "green",
        },
        {
            "value": unique_members,
            "label": _("Affected Members"),
            "datatype": "Int",
            "color": "orange" if unique_members > 0 else "green",
        },
    ]

    if critical_count > 0:
        summary.append(
            {
                "value": critical_count,
                "label": _("Critical"),
                "datatype": "Int",
                "color": "red",
            }
        )

    if high_count > 0:
        summary.append(
            {
                "value": high_count,
                "label": _("High Severity"),
                "datatype": "Int",
                "color": "orange",
            }
        )

    if medium_count > 0:
        summary.append(
            {
                "value": medium_count,
                "label": _("Medium"),
                "datatype": "Int",
                "color": "yellow",
            }
        )

    if low_count > 0:
        summary.append(
            {
                "value": low_count,
                "label": _("Low"),
                "datatype": "Int",
                "color": "blue",
            }
        )

    return summary


def get_chart_data(data):
    """Generate chart showing issue distribution"""
    if not data:
        return None

    # Count by issue type
    issue_counts = {}
    for row in data:
        issue_type = row.get("issue_type", "Unknown")
        issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1

    if not issue_counts:
        return None

    return {
        "data": {
            "labels": list(issue_counts.keys()),
            "datasets": [{"name": _("Issues"), "values": list(issue_counts.values())}],
        },
        "type": "bar",
        "colors": ["#ff6348", "#ffa502", "#ffdd59", "#7bed9f", "#70a1ff"],
    }
