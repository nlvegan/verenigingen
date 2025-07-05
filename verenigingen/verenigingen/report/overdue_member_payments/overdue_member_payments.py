import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today


def execute(filters=None):
    """Generate Overdue Member Payments Report"""

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
            "label": _("Member ID"),
            "fieldname": "member_name",
            "fieldtype": "Link",
            "options": "Member",
            "width": 120,
        },
        {"label": _("Member Name"), "fieldname": "member_full_name", "fieldtype": "Data", "width": 150},
        {"label": _("Email"), "fieldname": "member_email", "fieldtype": "Data", "width": 150},
        {
            "label": _("Chapter"),
            "fieldname": "chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 120,
        },
        {"label": _("Overdue Invoices"), "fieldname": "overdue_count", "fieldtype": "Int", "width": 100},
        {
            "label": _("Total Overdue Amount"),
            "fieldname": "total_overdue",
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "label": _("Oldest Invoice Date"),
            "fieldname": "oldest_invoice_date",
            "fieldtype": "Date",
            "width": 120,
        },
        {"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 100},
        {"label": _("Membership Type"), "fieldname": "membership_type", "fieldtype": "Data", "width": 120},
        {"label": _("Status"), "fieldname": "status_indicator", "fieldtype": "HTML", "width": 100},
        {"label": _("Last Payment"), "fieldname": "last_payment_date", "fieldtype": "Date", "width": 120},
    ]


def get_data(filters):
    """Get report data using Frappe ORM methods"""

    # Get all overdue invoices first
    invoice_filters = {
        "status": ["in", ["Overdue", "Unpaid"]],
        "due_date": ["<", today()],
        "docstatus": 1,
        "subscription": ["is", "set"],
    }

    # Apply date filters
    if filters:
        if filters.get("from_date"):
            invoice_filters["posting_date"] = [">=", filters.get("from_date")]
        if filters.get("to_date"):
            if "posting_date" in invoice_filters:
                invoice_filters["posting_date"] = [
                    "between",
                    [filters.get("from_date"), filters.get("to_date")],
                ]
            else:
                invoice_filters["posting_date"] = ["<=", filters.get("to_date")]

        # Apply days overdue filter
        if filters.get("days_overdue"):
            cutoff_date = add_days(today(), -int(filters.get("days_overdue")))
            invoice_filters["due_date"] = ["<", cutoff_date]
        elif filters.get("critical_only"):
            critical_date = add_days(today(), -60)
            invoice_filters["due_date"] = ["<", critical_date]
        elif filters.get("urgent_only"):
            urgent_date = add_days(today(), -30)
            invoice_filters["due_date"] = ["<", urgent_date]

    # Get overdue sales invoices
    overdue_invoices = frappe.get_all(
        "Sales Invoice",
        filters=invoice_filters,
        fields=["name", "customer", "outstanding_amount", "posting_date", "due_date", "subscription"],
    )

    if not overdue_invoices:
        return []

    # Filter for membership-related subscriptions
    membership_invoices = []
    for invoice in overdue_invoices:
        if is_membership_subscription(invoice.subscription):
            membership_invoices.append(invoice)

    if not membership_invoices:
        return []

    # Group by customer and aggregate data
    customer_data = {}
    for invoice in membership_invoices:
        customer = invoice.customer
        if customer not in customer_data:
            customer_data[customer] = {
                "invoices": [],
                "total_overdue": 0,
                "overdue_count": 0,
                "oldest_invoice_date": None,
                "min_due_date": None,
            }

        customer_data[customer]["invoices"].append(invoice)
        customer_data[customer]["total_overdue"] += flt(invoice.outstanding_amount)
        customer_data[customer]["overdue_count"] += 1

        # Track oldest invoice and due dates
        if (
            not customer_data[customer]["oldest_invoice_date"]
            or invoice.posting_date < customer_data[customer]["oldest_invoice_date"]
        ):
            customer_data[customer]["oldest_invoice_date"] = invoice.posting_date

        if (
            not customer_data[customer]["min_due_date"]
            or invoice.due_date < customer_data[customer]["min_due_date"]
        ):
            customer_data[customer]["min_due_date"] = invoice.due_date

    # Get member information for each customer
    data = []
    user_chapters = get_user_accessible_chapters()

    for customer, agg_data in customer_data.items():
        # Get member info
        member_info = get_member_info_by_customer(customer)
        if not member_info:
            continue

        # Apply chapter filtering
        if user_chapters is not None:  # None means see all
            member_chapters = get_member_chapters(member_info.get("name"))
            if not any(ch in user_chapters for ch in member_chapters):
                continue

        # Apply membership type filter
        if filters and filters.get("membership_type"):
            if member_info.get("membership_type") != filters.get("membership_type"):
                continue

        # Apply chapter filter
        if filters and filters.get("chapter"):
            member_chapters = get_member_chapters(member_info.get("name"))
            if filters.get("chapter") not in member_chapters:
                continue

        # Calculate days overdue
        days_overdue = (getdate(today()) - getdate(agg_data["min_due_date"])).days

        # Get last payment date
        last_payment_date = get_last_payment_date(customer)

        # Get member's primary chapter for display
        member_chapters = get_member_chapters(member_info.get("name"))
        primary_chapter = member_chapters[0] if member_chapters else None

        # Build row data
        row = {
            "member_name": member_info.get("name"),
            "member_full_name": member_info.get("full_name"),
            "member_email": member_info.get("email"),
            "chapter": primary_chapter,
            "overdue_count": agg_data["overdue_count"],
            "total_overdue": flt(agg_data["total_overdue"], 2),
            "oldest_invoice_date": agg_data["oldest_invoice_date"],
            "days_overdue": days_overdue,
            "membership_type": member_info.get("membership_type"),
            "last_payment_date": last_payment_date,
        }

        # Add status indicator with color coding
        if days_overdue > 60:
            row["status_indicator"] = '<span class="indicator red">Critical</span>'
        elif days_overdue > 30:
            row["status_indicator"] = '<span class="indicator orange">Urgent</span>'
        elif days_overdue > 14:
            row["status_indicator"] = '<span class="indicator yellow">Overdue</span>'
        else:
            row["status_indicator"] = '<span class="indicator blue">Due</span>'

        data.append(row)

    # Sort by days overdue (descending) then by total overdue amount (descending)
    data.sort(key=lambda x: (-x["days_overdue"], -x["total_overdue"]))

    return data


def is_membership_subscription(subscription_name):
    """Check if a subscription is membership-related"""
    if not subscription_name:
        return False

    try:
        # Get subscription plans for this subscription
        subscription_plans = frappe.get_all(
            "Subscription Plan Detail", filters={"parent": subscription_name}, fields=["plan"]
        )

        for plan_detail in subscription_plans:
            # Get the item from the subscription plan
            plan = frappe.get_doc("Subscription Plan", plan_detail.plan)
            if plan.item:
                item = frappe.get_doc("Item", plan.item)
                # Check if item is membership-related
                if (
                    item.item_group == "Membership"
                    or "membership" in item.name.lower()
                    or "lidmaatschap" in item.name.lower()
                ):
                    return True

        return False
    except Exception:
        return False


def get_member_info_by_customer(customer):
    """Get member information by customer"""
    try:
        member = frappe.get_value(
            "Member", {"customer": customer}, ["name", "full_name", "email"], as_dict=True
        )

        if member:
            # Get active membership type
            membership = frappe.get_value(
                "Membership", {"member": member.name, "status": "Active"}, "membership_type"
            )
            member["membership_type"] = membership

        return member
    except Exception:
        return None


def get_last_payment_date(customer):
    """Get the last payment date for a customer"""
    try:
        # Get latest payment entry for this customer
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"party_type": "Customer", "party": customer, "docstatus": 1},
            fields=["posting_date"],
            order_by="posting_date desc",
            limit=1,
        )

        return payment_entries[0].posting_date if payment_entries else None
    except Exception:
        return None


def get_user_accessible_chapters():
    """Get chapters accessible to current user (same logic as before)"""
    user = frappe.session.user

    # System managers and Association/Membership managers see all
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return None  # No filter - see all

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return []  # No access if not a member

    # Get chapters where user has board access with membership or finance permissions
    user_chapters = []
    try:
        volunteer_records = frappe.get_all("Volunteer", filters={"member": user_member}, fields=["name"])

        for volunteer_record in volunteer_records:
            board_positions = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_record.name, "is_active": 1},
                fields=["parent", "chapter_role"],
            )

            for position in board_positions:
                try:
                    role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                    if role_doc.permissions_level in ["Admin", "Membership", "Finance"]:
                        if position.parent not in user_chapters:
                            user_chapters.append(position.parent)
                except Exception:
                    continue

        # Add national chapter if configured and user has access
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "national_chapter") and settings.national_chapter:
                national_board_positions = frappe.get_all(
                    "Chapter Board Member",
                    filters={
                        "parent": settings.national_chapter,
                        "volunteer": [v.name for v in volunteer_records],
                        "is_active": 1,
                    },
                    fields=["chapter_role"],
                )

                for position in national_board_positions:
                    try:
                        role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                        if role_doc.permissions_level in ["Admin", "Membership", "Finance"]:
                            if settings.national_chapter not in user_chapters:
                                user_chapters.append(settings.national_chapter)
                            break
                    except Exception:
                        continue
        except Exception:
            pass
    except Exception:
        pass

    return user_chapters if user_chapters else []


def get_summary(data):
    """Get summary statistics"""
    if not data:
        return []

    total_members = len(data)
    total_amount = sum(flt(d.get("total_overdue", 0)) for d in data)
    total_invoices = sum(int(d.get("overdue_count", 0)) for d in data)

    critical_count = len([d for d in data if (d.get("days_overdue") or 0) > 60])
    urgent_count = len([d for d in data if (d.get("days_overdue") or 0) > 30])

    avg_days_overdue = sum((d.get("days_overdue") or 0) for d in data) / len(data) if data else 0

    return [
        {"value": total_members, "label": _("Members with Overdue Payments"), "datatype": "Int"},
        {"value": total_invoices, "label": _("Total Overdue Invoices"), "datatype": "Int"},
        {
            "value": total_amount,
            "label": _("Total Overdue Amount"),
            "datatype": "Currency",
            "color": "red" if total_amount > 1000 else "orange" if total_amount > 500 else "green",
        },
        {
            "value": critical_count,
            "label": _("Critical (>60 days)"),
            "datatype": "Int",
            "color": "red" if critical_count > 0 else "green",
        },
        {
            "value": urgent_count,
            "label": _("Urgent (>30 days)"),
            "datatype": "Int",
            "color": "orange" if urgent_count > 0 else "green",
        },
        {"value": round(avg_days_overdue, 1), "label": _("Average Days Overdue"), "datatype": "Float"},
    ]


def get_chart_data(data):
    """Get chart data for visualization"""
    if not data:
        return None

    # Group by chapter
    chapter_amounts = {}
    for row in data:
        chapter = row.get("chapter") or "Unassigned"
        if chapter not in chapter_amounts:
            chapter_amounts[chapter] = 0
        chapter_amounts[chapter] += flt(row.get("total_overdue", 0))

    return {
        "data": {
            "labels": list(chapter_amounts.keys()),
            "datasets": [{"name": _("Overdue Amount"), "values": list(chapter_amounts.values())}],
        },
        "type": "bar",
        "colors": ["#ff6b6b"],
    }


def get_member_chapters(member_name):
    """Get list of chapters a member belongs to"""
    try:
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
        )
        return [ch.parent for ch in chapters]
    except Exception:
        return []
