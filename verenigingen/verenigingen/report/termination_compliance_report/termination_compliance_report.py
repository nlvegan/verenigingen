# Query Report: Termination Compliance Report
# File: verenigingen/verenigingen/report/termination_compliance_report/termination_compliance_report.py

import frappe
from frappe import _
from frappe.utils import getdate, today


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "fieldname": "request_id",
            "label": _("Request ID"),
            "fieldtype": "Link",
            "options": "Membership Termination Request",
            "width": 150,
        },
        {"fieldname": "member_name", "label": _("Member"), "fieldtype": "Data", "width": 200},
        {"fieldname": "termination_type", "label": _("Type"), "fieldtype": "Data", "width": 120},
        {"fieldname": "request_date", "label": _("Request Date"), "fieldtype": "Date", "width": 100},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 120},
        {"fieldname": "days_pending", "label": _("Days Pending"), "fieldtype": "Int", "width": 100},
        {"fieldname": "compliance_issue", "label": _("Compliance Issue"), "fieldtype": "Data", "width": 200},
        {"fieldname": "priority", "label": _("Priority"), "fieldtype": "Data", "width": 100},
        {"fieldname": "requested_by", "label": _("Requested By"), "fieldtype": "Data", "width": 150},
        {"fieldname": "secondary_approver", "label": _("Approver"), "fieldtype": "Data", "width": 150},
    ]


def get_data(filters):
    conditions = []
    values = {}

    if filters.get("from_date"):
        conditions.append("mtr.request_date >= %(from_date)s")
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions.append("mtr.request_date <= %(to_date)s")
        values["to_date"] = filters["to_date"]

    if filters.get("termination_type"):
        conditions.append("mtr.termination_type = %(termination_type)s")
        values["termination_type"] = filters["termination_type"]

    if filters.get("chapter"):
        conditions.append(
            """
            EXISTS (
                SELECT 1 FROM `tabChapter Member` cm
                WHERE cm.member = m.name
                AND cm.parent = %(chapter)s
                AND cm.enabled = 1
            )
        """
        )
        values["chapter"] = filters["chapter"]

    if conditions:
        "WHERE " + " AND ".join(conditions)

    query = """
        SELECT
            mtr.name as request_id,
            mtr.member_name,
            mtr.termination_type,
            mtr.request_date,
            mtr.status,
            mtr.requested_by,
            mtr.secondary_approver,
            mtr.disciplinary_documentation,
            mtr.approved_by,
            mtr.approval_date,
            (
                SELECT cm.parent
                FROM `tabChapter Member` cm
                WHERE cm.member = m.name
                AND cm.enabled = 1
                ORDER BY cm.chapter_join_date DESC
                LIMIT 1
            ) as primary_chapter
        FROM `tabMembership Termination Request` mtr
        LEFT JOIN `tabMember` m ON mtr.member = m.name
        {where_clause}
        ORDER BY mtr.request_date DESC
    """

    results = frappe.db.sql(query, values, as_dict=True)

    data = []
    for row in results:
        days_pending = 0
        compliance_issue = ""
        priority = "Normal"

        # Calculate days pending
        if row.status in ["Pending Approval", "Approved"]:
            if row.status == "Pending Approval":
                days_pending = (getdate(today()) - getdate(row.request_date)).days
            elif row.status == "Approved" and row.approval_date:
                days_pending = (getdate(today()) - getdate(row.approval_date)).days

        # Identify compliance issues
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]

        if row.termination_type in disciplinary_types:
            if not row.disciplinary_documentation:
                compliance_issue = "Missing Documentation"
                priority = "High"
            elif row.status == "Pending Approval" and days_pending > 7:
                compliance_issue = "Overdue Approval"
                priority = "High"
            elif not row.approved_by and row.status == "Executed":
                compliance_issue = "Missing Secondary Approval"
                priority = "Critical"

        if row.status == "Approved" and days_pending > 3:
            if compliance_issue:
                compliance_issue += ", Delayed Execution"
            else:
                compliance_issue = "Delayed Execution"
            priority = "Medium"

        if not compliance_issue:
            compliance_issue = "Compliant"
            priority = "Normal"

        data.append(
            {
                "request_id": row.request_id,
                "member_name": row.member_name,
                "termination_type": row.termination_type,
                "request_date": row.request_date,
                "status": row.status,
                "days_pending": days_pending if days_pending > 0 else "",
                "compliance_issue": compliance_issue,
                "priority": priority,
                "requested_by": row.requested_by,
                "secondary_approver": row.secondary_approver or "",
            }
        )

    return data
