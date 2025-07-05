import frappe
from frappe import _
from frappe.utils import flt, getdate, today


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
        {"label": _("Volunteer"), "fieldname": "volunteer_name", "fieldtype": "Data", "width": 150},
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
        if user_chapters is not None:  # None means see all
            if expense.get("organization_type") == "Chapter" and expense.get("chapter"):
                if expense.get("chapter") not in user_chapters:
                    continue
            elif expense.get("organization_type") == "Team" and expense.get("team"):
                # Check if team's chapter is accessible
                try:
                    team_chapter = frappe.db.get_value("Team", expense.get("team"), "chapter")
                    if team_chapter and team_chapter not in user_chapters:
                        continue
                except Exception:
                    # If Team table doesn't exist, skip this filtering
                    pass

        # Apply approval level filter if specified
        if filters and filters.get("approval_level"):
            required_level = get_approval_level_for_amount(expense.get("amount", 0))
            if required_level.lower() != filters.get("approval_level").lower():
                continue

        filtered_data.append(expense)

    return filtered_data


def get_erpnext_expense_data(filters):
    """Get data from ERPNext Expense Claims"""
    # Build base filters for ERPNext
    base_filters = {"docstatus": 1}

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
        ],
        order_by="posting_date desc, creation desc",
    )

    data = []
    for claim in expense_claims:
        # Get volunteer information by employee_id
        volunteer_name = "Unknown"
        volunteer_record = None
        organization_type = "Unknown"
        organization_name = "Unknown"

        if claim.get("employee"):
            # Try to find volunteer by employee_id
            try:
                volunteer_record = frappe.db.get_value(
                    "Volunteer",
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


def get_user_accessible_chapters():
    """Get chapters accessible to current user"""
    user = frappe.session.user

    # System managers and Association managers see all
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return None  # No filter - see all

    # For now, return None to allow all access since we may not have full volunteer/chapter setup
    # This can be enhanced later when the full verenigingen system is deployed
    return None


def get_summary(data):
    """Get summary statistics"""
    if not data:
        return []

    # Basic counts
    total_expenses = len(data)
    approved_count = len([d for d in data if d.get("status") in ["Approved", "Reimbursed"]])
    pending_count = len([d for d in data if d.get("status") == "Submitted"])
    rejected_count = len([d for d in data if d.get("status") == "Rejected"])

    # Amount calculations
    total_amount = sum(flt(d.get("amount", 0)) for d in data)
    approved_amount = sum(
        flt(d.get("amount", 0)) for d in data if d.get("status") in ["Approved", "Reimbursed"]
    )
    pending_amount = sum(flt(d.get("amount", 0)) for d in data if d.get("status") == "Submitted")

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
        {"value": approved_count, "label": _("Approved"), "datatype": "Int", "color": "green"},
        {"value": approved_amount, "label": _("Approved Amount"), "datatype": "Currency", "color": "green"},
        {
            "value": pending_count,
            "label": _("Pending Approval"),
            "datatype": "Int",
            "color": "orange" if pending_count > 0 else "green",
        },
        {
            "value": pending_amount,
            "label": _("Pending Amount"),
            "datatype": "Currency",
            "color": "orange" if pending_amount > 0 else "green",
        },
        {
            "value": rejected_count,
            "label": _("Rejected"),
            "datatype": "Int",
            "color": "red" if rejected_count > 0 else "green",
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
