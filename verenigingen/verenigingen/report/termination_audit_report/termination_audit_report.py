import json

import frappe
from frappe import _
from frappe.utils import today


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    summary = get_summary(data, filters)
    chart = get_chart_data(data)

    return columns, data, None, chart, summary


def get_columns():
    return [
        {
            "fieldname": "request_id",
            "label": _("Request ID"),
            "fieldtype": "Link",
            "options": "Membership Termination Request",
            "width": 180,
        },
        {"fieldname": "member_name", "label": _("Member"), "fieldtype": "Data", "width": 200},
        {"fieldname": "termination_type", "label": _("Type"), "fieldtype": "Data", "width": 120},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        {"fieldname": "request_date", "label": _("Request Date"), "fieldtype": "Date", "width": 100},
        {"fieldname": "requested_by", "label": _("Requested By"), "fieldtype": "Data", "width": 150},
        {"fieldname": "approval_date", "label": _("Approval Date"), "fieldtype": "Datetime", "width": 140},
        {"fieldname": "approved_by", "label": _("Approved By"), "fieldtype": "Data", "width": 150},
        {"fieldname": "execution_date", "label": _("Execution Date"), "fieldtype": "Datetime", "width": 140},
        {"fieldname": "executed_by", "label": _("Executed By"), "fieldtype": "Data", "width": 150},
        {"fieldname": "processing_days", "label": _("Processing Days"), "fieldtype": "Int", "width": 120},
        {"fieldname": "audit_entries", "label": _("Audit Entries"), "fieldtype": "Int", "width": 100},
        {"fieldname": "system_updates", "label": _("System Updates"), "fieldtype": "Data", "width": 150},
        {"fieldname": "compliance_status", "label": _("Compliance"), "fieldtype": "Data", "width": 120},
    ]


def get_data(filters):
    conditions = []
    values = {}

    # Apply date filters
    if filters.get("from_date"):
        conditions.append("mtr.request_date >= %(from_date)s")
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("mtr.request_date <= %(to_date)s")
        values["to_date"] = filters["to_date"]

    # Apply other filters
    if filters.get("status"):
        conditions.append("mtr.status = %(status)s")
        values["status"] = filters["status"]

    if filters.get("termination_type"):
        conditions.append("mtr.termination_type = %(termination_type)s")
        values["termination_type"] = filters["termination_type"]

    if filters.get("requested_by"):
        conditions.append("mtr.requested_by = %(requested_by)s")
        values["requested_by"] = filters["requested_by"]

    if filters.get("member"):
        conditions.append("mtr.member = %(member)s")
        values["member"] = filters["member"]

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    else:
        where_clause = ""

    # Main query to get termination requests
    query = f"""
        SELECT
            mtr.name as request_id,
            mtr.member,
            mtr.member_name,
            mtr.termination_type,
            mtr.status,
            mtr.request_date,
            mtr.requested_by,
            mtr.approved_by,
            mtr.approval_date,
            mtr.executed_by,
            mtr.execution_date,
            mtr.sepa_mandates_cancelled,
            mtr.positions_ended,
            mtr.newsletters_updated,
            mtr.requires_secondary_approval,
            mtr.secondary_approver,
            mtr.disciplinary_documentation,
            mtr.termination_reason,
            CASE
                WHEN mtr.execution_date IS NOT NULL AND mtr.request_date IS NOT NULL
                THEN DATEDIFF(mtr.execution_date, mtr.request_date)
                ELSE NULL
            END as processing_days
        FROM `tabMembership Termination Request` mtr
        {where_clause}
        ORDER BY mtr.request_date DESC
    """

    results = frappe.db.sql(query, values, as_dict=True)

    # Process and enhance data
    data = []
    for row in results:
        # Get audit entry count
        audit_count = frappe.db.count(
            "Termination Audit Entry",
            {"parent": row.request_id, "parenttype": "Membership Termination Request"},
        )

        # Build system updates summary
        system_updates = []
        if row.sepa_mandates_cancelled:
            system_updates.append(f"{row.sepa_mandates_cancelled} SEPA")
        if row.positions_ended:
            system_updates.append(f"{row.positions_ended} Positions")
        if row.newsletters_updated:
            system_updates.append("Newsletters")

        # Check compliance status
        compliance_issues = []
        compliance_status = "Compliant"

        # Check for disciplinary terminations without documentation
        if row.termination_type in ["Policy Violation", "Disciplinary Action", "Expulsion"]:
            if not row.disciplinary_documentation:
                compliance_issues.append("Missing Documentation")
                compliance_status = "Non-Compliant"

            # Check for missing secondary approval
            if row.requires_secondary_approval and not row.approved_by:
                compliance_issues.append("Missing Approval")
                compliance_status = "Critical"

        # Check for long processing times
        if row.processing_days and row.processing_days > 30:
            compliance_issues.append("Delayed Processing")
            if compliance_status == "Compliant":
                compliance_status = "Warning"

        # Format dates
        approval_date = row.approval_date
        execution_date = row.execution_date

        data.append(
            {
                "request_id": row.request_id,
                "member": row.member,
                "member_name": row.member_name,
                "termination_type": row.termination_type,
                "status": row.status,
                "request_date": row.request_date,
                "requested_by": row.requested_by,
                "approval_date": approval_date,
                "approved_by": row.approved_by or "",
                "execution_date": execution_date,
                "executed_by": row.executed_by or "",
                "processing_days": row.processing_days or "",
                "audit_entries": audit_count,
                "system_updates": ", ".join(system_updates) if system_updates else "-",
                "compliance_status": compliance_status,
                "compliance_issues": compliance_issues,
                "termination_reason": row.termination_reason,
            }
        )

    return data


def get_summary(data, filters):
    """Generate summary statistics"""
    total_requests = len(data)

    if total_requests == 0:
        return []

    # Status breakdown
    status_counts = {}
    for row in data:
        status = row["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    # Compliance breakdown
    compliant = len([r for r in data if r["compliance_status"] == "Compliant"])
    len([r for r in data if r["compliance_status"] in ["Non-Compliant", "Critical"]])
    # warnings = len([r for r in data if r["compliance_status"] == "Warning"])

    # Calculate average processing time
    processing_times = [r["processing_days"] for r in data if r["processing_days"]]
    avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0

    # Type breakdown
    type_counts = {}
    for row in data:
        term_type = row["termination_type"]
        type_counts[term_type] = type_counts.get(term_type, 0) + 1

    # Find most active requester
    requester_counts = {}
    for row in data:
        requester = row["requested_by"]
        requester_counts[requester] = requester_counts.get(requester, 0) + 1

    most_active_requester = (
        max(requester_counts.items(), key=lambda x: x[1])[0] if requester_counts else "N/A"
    )

    summary = [
        {"label": _("Total Requests"), "value": total_requests, "indicator": "blue"},
        {
            "label": _("Compliance Rate"),
            "value": f"{(compliant / total_requests * 100):.1f}%" if total_requests > 0 else "0%",
            "indicator": "green" if compliant / total_requests > 0.8 else "red",
        },
        {
            "label": _("Avg. Processing Time"),
            "value": f"{avg_processing_time:.1f} days",
            "indicator": "green"
            if avg_processing_time <= 7
            else "orange"
            if avg_processing_time <= 14
            else "red",
        },
        {"label": _("Executed"), "value": status_counts.get("Executed", 0), "indicator": "gray"},
        {
            "label": _("Pending"),
            "value": status_counts.get("Pending Approval", 0) + status_counts.get("Approved", 0),
            "indicator": "orange",
        },
        {"label": _("Most Active Requester"), "value": most_active_requester, "indicator": "blue"},
    ]

    return summary


def get_chart_data(data):
    """Generate chart data for the report"""

    # Prepare data for chart
    type_counts = {}
    status_counts = {}
    monthly_counts = {}

    for row in data:
        # Type distribution
        term_type = row["termination_type"]
        type_counts[term_type] = type_counts.get(term_type, 0) + 1

        # Status distribution
        status = row["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

        # Monthly trend
        if row["request_date"]:
            month_key = row["request_date"].strftime("%Y-%m")
            monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1

    # Create chart configuration
    chart = {
        "data": {
            "labels": list(type_counts.keys()),
            "datasets": [{"name": "Termination Types", "values": list(type_counts.values())}],
        },
        "type": "bar",
        "colors": ["#5e64ff"],
        "title": "Terminations by Type",
    }

    return chart


@frappe.whitelist()
def get_audit_trail_details(request_id):
    """Get detailed audit trail for a specific termination request"""

    audit_entries = frappe.get_all(
        "Termination Audit Entry",
        filters={"parent": request_id, "parenttype": "Membership Termination Request"},
        fields=["timestamp", "action", "user", "details", "system_action"],
        order_by="timestamp desc",
    )

    return audit_entries


@frappe.whitelist()
def export_audit_report(filters=None):
    """Export audit report to Excel with enhanced formatting"""

    columns, data, _, _, summary = execute(filters)

    # Prepare enhanced data for export
    export_data = []

    for row in data:
        export_row = row.copy()

        # Add compliance issues as separate column
        if "compliance_issues" in row:
            export_row["compliance_issues"] = ", ".join(row["compliance_issues"])

        export_data.append(export_row)

    # Add summary row
    if summary:
        summary_row = {"request_id": "SUMMARY"}
        for item in summary:
            summary_row[item["label"].replace(" ", "_").lower()] = item["value"]
        export_data.append(summary_row)

    return {"columns": columns, "data": export_data, "file_name": f"termination_audit_report_{today()}.xlsx"}


@frappe.whitelist()
def get_compliance_statistics(filters=None):
    """Get compliance statistics for dashboard"""

    if isinstance(filters, str):
        filters = json.loads(filters)

    _, data, _, _, _ = execute(filters)

    # Calculate compliance statistics
    total = len(data)
    compliant = len([r for r in data if r["compliance_status"] == "Compliant"])
    critical = len([r for r in data if r["compliance_status"] == "Critical"])
    # warnings = len([r for r in data if r["compliance_status"] == "Warning"])

    # Type-based compliance
    type_compliance = {}
    for row in data:
        term_type = row["termination_type"]
        if term_type not in type_compliance:
            type_compliance[term_type] = {"total": 0, "compliant": 0}

        type_compliance[term_type]["total"] += 1
        if row["compliance_status"] == "Compliant":
            type_compliance[term_type]["compliant"] += 1

    # Calculate compliance rate by type
    for term_type in type_compliance:
        total_type = type_compliance[term_type]["total"]
        compliant_type = type_compliance[term_type]["compliant"]
        type_compliance[term_type]["rate"] = (compliant_type / total_type * 100) if total_type > 0 else 0

    return {
        "overall_compliance_rate": (compliant / total * 100) if total > 0 else 0,
        "critical_issues": critical,
        "warnings": warnings,
        "type_compliance": type_compliance,
        "total_audited": total,
    }
