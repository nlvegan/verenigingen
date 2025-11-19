import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from verenigingen.utils.chapter_utils import get_user_accessible_chapters


def execute(filters=None):
    """Generate Chapter Expense Report"""

    columns = get_columns()
    data = get_data(filters)

    # Add summary statistics
    summary = get_summary(data)

    # Add chart data
    chart = get_chart_data(data)

    return columns, data, None, chart, summary


def get_columns():
    """Define report columns"""
    return [
        {
            "label": _("Expense ID"),
            "fieldname": "name",
            "fieldtype": "Link",
            "options": "Expense Claim",
            "width": 120,
        },
        {
            "label": _("Verenigingen Volunteer"),
            "fieldname": "volunteer_name",
            "fieldtype": "Data",
            "width": 150,
        },
        {"label": _("Description"), "fieldname": "description", "fieldtype": "Data", "width": 200},
        {"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
        {"label": _("Date"), "fieldname": "expense_date", "fieldtype": "Date", "width": 100},
        {"label": _("Category"), "fieldname": "category_name", "fieldtype": "Data", "width": 120},
        {"label": _("Organization"), "fieldname": "organization_name", "fieldtype": "Data", "width": 120},
        {"label": _("Type"), "fieldname": "organization_type", "fieldtype": "Data", "width": 80},
        {"label": _("Status"), "fieldname": "status_indicator", "fieldtype": "HTML", "width": 100},
        {"label": _("Approval Level"), "fieldname": "approval_level", "fieldtype": "Data", "width": 120},
        {"label": _("Approved By"), "fieldname": "approved_by_name", "fieldtype": "Data", "width": 120},
        {"label": _("Approved Date"), "fieldname": "approved_on", "fieldtype": "Date", "width": 120},
        {"label": _("Days to Approval"), "fieldname": "days_to_approval", "fieldtype": "Int", "width": 120},
        {"label": _("Attachments"), "fieldname": "attachment_count", "fieldtype": "Int", "width": 100},
    ]


def get_data(filters):
    """Get report data - ERPNext Expense Claims only"""

    # Get data from ERPNext Expense Claims
    erpnext_data = get_erpnext_expense_data(filters)

    # Filter by user access permissions
    user_chapters = get_user_accessible_chapters()
    filtered_data = []

    for expense in erpnext_data:
        # Apply chapter access filtering
        if user_chapters is not None:  # None means see all (admin access)
            # For Chapter-type expenses
            if expense.get("organization_type") == "Chapter":
                if not expense.get("chapter"):
                    # Unassigned chapter expense - skip for non-admins
                    continue
                if expense.get("chapter") not in user_chapters:
                    # Chapter expense not in user's accessible chapters
                    continue
            # For Team-type expenses
            elif expense.get("organization_type") == "Team":
                if not expense.get("team"):
                    # Unassigned team expense - skip for non-admins
                    continue
                # Check if team's chapter is accessible
                try:
                    team_chapter = frappe.db.get_value("Team", expense.get("team"), "chapter")
                    if not team_chapter or team_chapter not in user_chapters:
                        # Team has no chapter or chapter not accessible
                        continue
                except Exception:
                    # If Team table doesn't exist or error, skip this expense
                    continue
            # For expenses with no organization type or other types
            else:
                # For expenses without proper chapter/team assignment, skip for non-admins
                continue

        # Apply approval level filter if specified
        if filters and filters.get("approval_level"):
            required_level = get_approval_level_for_amount(expense.get("amount", 0))
            if required_level.lower() != filters.get("approval_level").lower():
                continue

        # Apply status filter if specified (after status mapping)
        # Only filter if status is explicitly set (not empty string)
        if filters and filters.get("status") and filters.get("status").strip():
            if expense.get("status") != filters.get("status"):
                continue

        # Apply organization type filter if specified
        if filters and filters.get("organization_type") and filters.get("organization_type").strip():
            if expense.get("organization_type") != filters.get("organization_type"):
                continue

        # Apply specific chapter filter if specified
        if filters and filters.get("chapter") and filters.get("chapter").strip():
            if expense.get("chapter") != filters.get("chapter"):
                continue

        # Apply specific team filter if specified
        if filters and filters.get("team") and filters.get("team").strip():
            if expense.get("team") != filters.get("team"):
                continue

        filtered_data.append(expense)

    return filtered_data


def get_erpnext_expense_data(filters):
    """Get data from ERPNext Expense Claims"""
    # Build base filters for ERPNext
    # Don't filter by docstatus - show all (Draft, Submitted, Cancelled)
    # User can filter by status using the status filter
    base_filters = {}

    # Apply date filters
    if filters:
        if filters.get("from_date"):
            base_filters["posting_date"] = [">=", filters.get("from_date")]
        if filters.get("to_date"):
            if "posting_date" in base_filters:
                base_filters["posting_date"] = ["between", [filters.get("from_date"), filters.get("to_date")]]
            else:
                base_filters["posting_date"] = ["<=", filters.get("to_date")]

    # Get ERPNext Expense Claims
    expense_claims = frappe.get_all(
        "Expense Claim",
        filters=base_filters,
        fields=[
            "name",
            "posting_date",
            "total_claimed_amount",
            "total_sanctioned_amount",
            "status",
            "approval_status",
            "employee",
            "employee_name",
            "remark",
            "company",
            "cost_center",
            "custom_organization_type",
            "custom_chapter",
            "custom_team",
            "custom_volunteer",
        ],
        order_by="posting_date desc, creation desc",
    )

    data = []
    for claim in expense_claims:
        # Get volunteer information by employee_id
        volunteer_name = "Unknown"
        volunteer_record = None

        # Get organization info from custom fields
        organization_type = claim.get("custom_organization_type") or "Unknown"
        organization_name = "Unknown"

        # Get organization name based on type
        if organization_type == "Chapter" and claim.get("custom_chapter"):
            organization_name = frappe.db.get_value(
                "Verenigingen Chapter", claim.get("custom_chapter"), "chapter_name"
            ) or claim.get("custom_chapter")
        elif organization_type == "Team" and claim.get("custom_team"):
            organization_name = frappe.db.get_value(
                "Verenigingen Volunteer Team", claim.get("custom_team"), "team_name"
            ) or claim.get("custom_team")

        if claim.get("employee"):
            # Try to find volunteer by employee_id
            try:
                volunteer_record = frappe.db.get_value(
                    "Verenigingen Volunteer",
                    {"employee_id": claim.get("employee")},
                    ["name", "volunteer_name"],
                    as_dict=True,
                )
                if volunteer_record:
                    volunteer_name = volunteer_record.volunteer_name
            except Exception:
                pass

            # Fallback to employee name if no volunteer found
            if volunteer_name == "Unknown":
                # Use employee_name from the claim first, then try database lookup
                volunteer_name = claim.get("employee_name") or "Unknown"
                if volunteer_name == "Unknown" and claim.get("employee"):
                    try:
                        volunteer_name = (
                            frappe.db.get_value("Employee", claim.get("employee"), "employee_name")
                            or "Unknown"
                        )
                    except Exception:
                        pass

        # Get expense details from Expense Claim Detail
        expense_details = []
        try:
            expense_details = frappe.get_all(
                "Expense Claim Detail",
                filters={"parent": claim.get("name")},
                fields=["expense_type", "description", "amount", "expense_date"],
                order_by="idx",
            )
        except Exception:
            # If no details found, create a summary entry
            expense_details = [
                {
                    "expense_type": "General",
                    "description": claim.get("remark") or f"Expense Claim {claim.get('name')}",
                    "amount": claim.get("total_claimed_amount"),
                    "expense_date": claim.get("posting_date"),
                }
            ]

        # Map ERPNext status to display status
        status = claim.get("status")
        approval_status = claim.get("approval_status")

        if status == "Paid":
            display_status = "Reimbursed"
        elif status == "Submitted" and approval_status == "Approved":
            display_status = "Approved"
        elif status == "Submitted" and approval_status == "Rejected":
            display_status = "Rejected"
        elif status == "Submitted":
            display_status = "Submitted"
        elif status == "Draft":
            display_status = "Awaiting Approval"
        else:
            display_status = status

        # Create row for each expense detail (or one summary row)
        for detail in expense_details:
            row = build_expense_row(
                name=claim.get("name"),
                volunteer_name=volunteer_name,
                description=detail.get("description")
                or claim.get("remark")
                or f"Expense Claim {claim.get('name')}",
                amount=detail.get("amount") or claim.get("total_claimed_amount"),
                expense_date=detail.get("expense_date") or claim.get("posting_date"),
                category_name=detail.get("expense_type") or "General",
                organization_type=organization_type,
                organization_name=organization_name,
                status=display_status,
                is_erpnext=True,
                expense_claim_id=claim.get("name"),
                chapter=claim.get("custom_chapter"),
                team=claim.get("custom_team"),
            )

            data.append(row)

    return data


def build_expense_row(
    name,
    volunteer_name,
    description,
    amount,
    expense_date,
    category_name,
    organization_type,
    organization_name,
    status,
    is_erpnext=False,
    expense_claim_id=None,
    approved_by=None,
    approved_on=None,
    chapter=None,
    team=None,
):
    """Build standardized expense row for report"""

    # Calculate approval level
    approval_level = get_approval_level_for_amount(amount)

    # Get approver name
    approved_by_name = None
    if approved_by:
        approved_by_name = frappe.db.get_value("User", approved_by, "full_name")

    # Calculate days to approval
    days_to_approval = None
    if approved_on and expense_date:
        days_to_approval = (getdate(approved_on) - getdate(expense_date)).days
    elif status == "Submitted":
        days_to_approval = (getdate(today()) - getdate(expense_date)).days

    # Get attachment count
    if is_erpnext and expense_claim_id:
        attachment_count = frappe.db.count(
            "File", {"attached_to_name": expense_claim_id, "attached_to_doctype": "Expense Claim"}
        )
    else:
        attachment_count = frappe.db.count(
            "File", {"attached_to_name": name, "attached_to_doctype": "Volunteer Expense"}
        )

    # Build row data
    row = {
        "name": name,
        "volunteer_name": volunteer_name,
        "description": description,
        "amount": flt(amount, 2),
        "currency": "EUR",  # Default currency
        "expense_date": expense_date,
        "category_name": category_name,
        "organization_name": organization_name or "Unknown",
        "organization_type": organization_type,
        "chapter": chapter,
        "team": team,
        "status": status,
        "approval_level": approval_level.title(),
        "approved_by_name": approved_by_name,
        "approved_on": approved_on,
        "days_to_approval": days_to_approval,
        "attachment_count": attachment_count,
    }

    # Add status indicator with color coding
    if status == "Approved" or status == "Reimbursed":
        row["status_indicator"] = '<span class="indicator green">Approved</span>'
    elif status == "Rejected":
        row["status_indicator"] = '<span class="indicator red">Rejected</span>'
    elif status == "Submitted":
        if days_to_approval and days_to_approval > 7:
            row["status_indicator"] = '<span class="indicator orange">Pending (Overdue)</span>'
        else:
            row["status_indicator"] = '<span class="indicator blue">Pending</span>'
    else:
        row["status_indicator"] = f'<span class="indicator grey">{status}</span>'

    return row


def get_summary(data):
    """Get summary statistics"""
    if not data:
        return []

    # Basic counts
    total_expenses = len(data)

    # Count by individual status
    awaiting_count = len([d for d in data if d.get("status") == "Awaiting Approval"])
    submitted_count = len([d for d in data if d.get("status") == "Submitted"])
    approved_count = len([d for d in data if d.get("status") == "Approved"])
    reimbursed_count = len([d for d in data if d.get("status") == "Reimbursed"])
    rejected_count = len([d for d in data if d.get("status") == "Rejected"])

    # Combined pending count
    pending_count = awaiting_count + submitted_count

    # Amount calculations by status
    total_amount = sum(flt(d.get("amount", 0)) for d in data)
    awaiting_amount = sum(flt(d.get("amount", 0)) for d in data if d.get("status") == "Awaiting Approval")
    submitted_amount = sum(flt(d.get("amount", 0)) for d in data if d.get("status") == "Submitted")
    approved_amount = sum(flt(d.get("amount", 0)) for d in data if d.get("status") == "Approved")
    reimbursed_amount = sum(flt(d.get("amount", 0)) for d in data if d.get("status") == "Reimbursed")
    rejected_amount = sum(flt(d.get("amount", 0)) for d in data if d.get("status") == "Rejected")

    # Combined pending amount
    pending_amount = awaiting_amount + submitted_amount

    # Approval time statistics
    approval_times = [
        d.get("days_to_approval")
        for d in data
        if d.get("days_to_approval") is not None and d.get("status") == "Approved"
    ]
    avg_approval_time = sum(approval_times) / len(approval_times) if approval_times else 0

    # Amount level breakdown
    basic_count = len([d for d in data if d.get("approval_level") == "Basic"])
    financial_count = len([d for d in data if d.get("approval_level") == "Financial"])
    admin_count = len([d for d in data if d.get("approval_level") == "Admin"])

    return [
        {"value": total_expenses, "label": _("Total Expenses"), "datatype": "Int"},
        {"value": total_amount, "label": _("Total Amount"), "datatype": "Currency"},
        {"value": awaiting_count, "label": _("Awaiting Approval"), "datatype": "Int", "color": "blue"},
        {"value": awaiting_amount, "label": _("Awaiting Amount"), "datatype": "Currency", "color": "blue"},
        {"value": submitted_count, "label": _("Submitted"), "datatype": "Int", "color": "orange"},
        {
            "value": submitted_amount,
            "label": _("Submitted Amount"),
            "datatype": "Currency",
            "color": "orange",
        },
        {"value": approved_count, "label": _("Approved"), "datatype": "Int", "color": "green"},
        {"value": approved_amount, "label": _("Approved Amount"), "datatype": "Currency", "color": "green"},
        {"value": reimbursed_count, "label": _("Reimbursed"), "datatype": "Int", "color": "green"},
        {
            "value": reimbursed_amount,
            "label": _("Reimbursed Amount"),
            "datatype": "Currency",
            "color": "green",
        },
        {"value": rejected_count, "label": _("Rejected"), "datatype": "Int", "color": "red"},
        {"value": rejected_amount, "label": _("Rejected Amount"), "datatype": "Currency", "color": "red"},
        {"value": pending_count, "label": _("Total Pending"), "datatype": "Int", "color": "orange"},
        {
            "value": pending_amount,
            "label": _("Total Pending Amount"),
            "datatype": "Currency",
            "color": "orange",
        },
        {"value": round(avg_approval_time, 1), "label": _("Avg. Approval Time (days)"), "datatype": "Float"},
        {"value": basic_count, "label": _("Basic Level"), "datatype": "Int"},
        {"value": financial_count, "label": _("Financial Level"), "datatype": "Int"},
        {"value": admin_count, "label": _("Admin Level"), "datatype": "Int"},
    ]


def get_chart_data(data):
    """Get chart data for visualization"""
    if not data:
        return None

    # Group by organization for chart
    org_amounts = {}
    for row in data:
        org = row.get("organization_name") or "Unassigned"
        if org not in org_amounts:
            org_amounts[org] = {"approved": 0, "pending": 0, "rejected": 0}

        amount = flt(row.get("amount", 0))
        status = row.get("status", "").lower()

        if status in ["approved", "reimbursed"]:
            org_amounts[org]["approved"] += amount
        elif status == "submitted":
            org_amounts[org]["pending"] += amount
        elif status == "rejected":
            org_amounts[org]["rejected"] += amount

    organizations = list(org_amounts.keys())
    approved_amounts = [org_amounts[org]["approved"] for org in organizations]
    pending_amounts = [org_amounts[org]["pending"] for org in organizations]
    rejected_amounts = [org_amounts[org]["rejected"] for org in organizations]

    return {
        "data": {
            "labels": organizations,
            "datasets": [
                {"name": _("Approved"), "values": approved_amounts},
                {"name": _("Pending"), "values": pending_amounts},
                {"name": _("Rejected"), "values": rejected_amounts},
            ],
        },
        "type": "bar",
        "colors": ["#28a745", "#ffc107", "#dc3545"],
    }


def get_approval_level_for_amount(amount):
    """Get approval level required for expense amount"""
    amount = flt(amount)

    if amount <= 100:
        return "Basic"
    elif amount <= 500:
        return "Financial"
    else:
        return "Admin"
