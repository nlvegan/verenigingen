import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters
from verenigingen.utils.member_utils import (
    get_active_membership_for_member,
    get_member_chapters,
    get_member_for_customer,
)
from verenigingen.utils.payment_utils import get_last_payment_date
from verenigingen.utils.validation_utilities import QueryBuilder


def validate_doctype_fields(doctype, required_fields):
    """Validate that required fields exist in DocType for defensive programming"""
    try:
        meta = frappe.get_meta(doctype)
        existing_fields = {field.fieldname for field in meta.fields if field.fieldname}
        # Add implicit fields that always exist on DocTypes
        existing_fields.update(["name", "creation", "modified", "owner", "modified_by", "docstatus"])
        missing_fields = set(required_fields) - existing_fields

        if missing_fields:
            frappe.logger().warning(f"Missing fields in {doctype}: {missing_fields}")
            return False
        return True
    except Exception as e:
        frappe.logger().error(f"Error validating {doctype} fields: {str(e)}")
        return False


def execute(filters=None):
    """Generate Overdue Member Payments Report"""
    import time

    start_time = time.time()

    try:
        columns = get_columns()
        data = get_data(filters)

        # Add summary statistics
        summary = get_summary(data)

        # Add chart data
        chart = get_chart_data(data)

        # Log performance metrics
        execution_time = time.time() - start_time
        frappe.logger().info(
            f"overdue_member_payments report: {len(data)} rows processed in {execution_time:.2f}s"
        )

        return columns, data, None, chart, summary

    except Exception as e:
        execution_time = time.time() - start_time
        frappe.logger().error(f"overdue_member_payments report failed after {execution_time:.2f}s: {str(e)}")
        raise


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
        {"label": _("Grace Period"), "fieldname": "grace_period_status", "fieldtype": "Data", "width": 120},
        {
            "label": _("Grace Period Expiry"),
            "fieldname": "grace_period_expiry",
            "fieldtype": "Date",
            "width": 120,
        },
        {"label": _("Last Payment"), "fieldname": "last_payment_date", "fieldtype": "Date", "width": 120},
    ]


def get_data(filters):
    """Get report data using Frappe ORM methods"""

    # Validate required fields exist before proceeding
    required_invoice_fields = [
        "name",
        "customer",
        "outstanding_amount",
        "posting_date",
        "due_date",
        "status",
        "docstatus",
    ]
    required_member_fields = ["name", "full_name", "email", "user"]
    required_membership_fields = [
        "member",
        "membership_type",
        "grace_period_status",
        "grace_period_expiry_date",
    ]

    if not all(
        [
            validate_doctype_fields("Sales Invoice", required_invoice_fields),
            validate_doctype_fields("Member", required_member_fields),
            validate_doctype_fields("Membership", required_membership_fields),
        ]
    ):
        frappe.logger().error("Field validation failed in overdue_member_payments report")
        return []  # Return empty data if validation fails

    # Get all overdue invoices first
    invoice_filters = {
        "status": ["in", ["Overdue", "Unpaid"]],
        "due_date": ["<", today()],
        "docstatus": 1,
        # Updated to work with dues schedule system - no longer filtering by subscription
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
    overdue_invoices = QueryBuilder.get_all_active_records(
        "Sales Invoice",
        filters=invoice_filters,
        fields=["name", "customer", "outstanding_amount", "posting_date", "due_date"],
    )

    if not overdue_invoices:
        return []

    # Use all overdue invoices for members (no subscription filtering needed)
    membership_invoices = overdue_invoices

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

    # Batch load member information to avoid N+1 queries
    customer_names = list(customer_data.keys())
    member_info_map = batch_get_member_info_by_customers(customer_names)

    # OPTIMIZATION: Batch load chapter information for all members
    member_names = [info.get("name") for info in member_info_map.values() if info.get("name")]
    member_chapters_map = batch_get_member_chapters(member_names)

    # OPTIMIZATION: Batch load last payment dates for all customers
    payment_dates_map = batch_get_last_payment_dates(customer_names)

    # Get member information for each customer
    data = []
    user_chapters = get_user_accessible_chapters()

    for customer, agg_data in customer_data.items():
        # Get pre-loaded member info
        member_info = member_info_map.get(customer)
        if not member_info:
            continue

        # OPTIMIZED: Use pre-loaded chapter data
        member_chapters = member_chapters_map.get(member_info.get("name"), [])

        # Apply chapter filtering
        if user_chapters is not None:  # None means see all
            if not any(ch in user_chapters for ch in member_chapters):
                continue

        # Apply membership type filter
        if filters and filters.get("membership_type"):
            if member_info.get("membership_type") != filters.get("membership_type"):
                continue

        # Apply chapter filter
        if filters and filters.get("chapter"):
            if filters.get("chapter") not in member_chapters:
                continue

        # Calculate days overdue
        days_overdue = (getdate(today()) - getdate(agg_data["min_due_date"])).days

        # OPTIMIZED: Use pre-loaded payment and chapter data
        last_payment_date = payment_dates_map.get(customer)
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
            "grace_period_status": member_info.get("grace_period_status"),
            "grace_period_expiry": member_info.get("grace_period_expiry_date"),
            "last_payment_date": last_payment_date,
        }

        # Add status indicator with color coding (enhanced with grace period logic)
        grace_period_status = member_info.get("grace_period_status")
        grace_period_expiry = member_info.get("grace_period_expiry_date")

        if grace_period_status == "Grace Period":
            # Check if grace period is expiring soon
            if grace_period_expiry:
                days_until_expiry = (getdate(grace_period_expiry) - getdate(today())).days
                if days_until_expiry <= 0:
                    row["status_indicator"] = '<span class="indicator red">Grace Period Expired</span>'
                elif days_until_expiry <= 7:
                    row["status_indicator"] = '<span class="indicator orange">Grace Period Expiring</span>'
                else:
                    row["status_indicator"] = '<span class="indicator blue">Grace Period</span>'
            else:
                row["status_indicator"] = '<span class="indicator blue">Grace Period</span>'
        elif days_overdue > 60:
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


def is_membership_related(document_name):
    """
    Updated to use dues schedules instead of subscriptions.
    Always returns True for membership-related payments.
    """
    # Always return True for backward compatibility
    return True


def get_members_for_customers(customer_names):
    """Get member names for multiple customers in a single query"""
    if not customer_names:
        return {}

    try:
        # Get customers and their linked member records
        customer_member_data = frappe.db.sql(
            """
            SELECT customer as customer_name, name as member_name
            FROM `tabMember`
            WHERE customer IN %(customer_names)s
            AND docstatus != 2
        """,
            {"customer_names": customer_names},
            as_dict=True,
        )

        # Create mapping from customer name to member name
        customer_member_map = {}
        for row in customer_member_data:
            if row.customer_name and row.member_name:
                customer_member_map[row.customer_name] = row.member_name

        return customer_member_map
    except Exception as e:
        frappe.logger().error(f"Error getting members for customers: {str(e)}")
        return {}


def batch_get_member_info_by_customers(customer_names):
    """Batch load member information for multiple customers to avoid N+1 queries - OPTIMIZED"""
    if not customer_names:
        return {}

    try:
        # Get member names for all customers in one query
        customer_member_map = get_members_for_customers(customer_names)

        if not customer_member_map:
            return {}

        member_names = list(customer_member_map.values())

        # OPTIMIZATION: Batch load member data with more fields
        members = frappe.get_all(
            "Member", filters={"name": ["in", member_names]}, fields=["name", "full_name", "email"]
        )

        # OPTIMIZATION: Batch load membership data for all members
        membership_data = frappe.get_all(
            "Membership",
            filters={"member": ["in", member_names], "status": "Active"},
            fields=["member", "membership_type", "grace_period_status", "grace_period_expiry_date"],
        )

        # Create membership lookup map
        membership_map = {ms.member: ms for ms in membership_data}

        # Create member info map with membership data
        member_data_map = {}
        for member in members:
            membership = membership_map.get(member.name, {})
            member_data_map[member.name] = {
                "name": member.name,
                "full_name": member.full_name,
                "email": member.email,
                "membership_type": membership.get("membership_type"),
                "grace_period_status": membership.get("grace_period_status"),
                "grace_period_expiry_date": membership.get("grace_period_expiry_date"),
            }

        # Map customers to their member info
        result = {}
        for customer, member_name in customer_member_map.items():
            if member_name in member_data_map:
                result[customer] = member_data_map[member_name]

        return result

    except Exception as e:
        frappe.logger().error(f"Error batch loading member info for customers: {str(e)}")
        return {}


def get_member_info_by_customer(customer):
    """Get member information by customer using standardized utilities"""
    try:
        # Use standardized member lookup
        member_name = get_member_for_customer(customer)
        if not member_name:
            return None

        # Get basic member info
        member = frappe.get_value("Member", member_name, ["name", "full_name", "email"], as_dict=True)

        if member:
            # Get active membership info using standardized utility
            membership = get_active_membership_for_member(
                member_name, fields=["membership_type", "grace_period_status", "grace_period_expiry_date"]
            )

            if membership:
                member.update(
                    {
                        "membership_type": membership.get("membership_type"),
                        "grace_period_status": membership.get("grace_period_status"),
                        "grace_period_expiry_date": membership.get("grace_period_expiry_date"),
                    }
                )
            else:
                member.update(
                    {"membership_type": None, "grace_period_status": None, "grace_period_expiry_date": None}
                )

        return member
    except Exception:
        return None


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


def batch_get_member_chapters(member_names):
    """Batch load chapter information for multiple members to avoid N+1 queries"""
    if not member_names:
        return {}

    try:
        # Single query to get all chapter memberships
        chapter_memberships = frappe.db.sql(
            """
            SELECT cm.member, cm.parent as chapter_name
            FROM `tabChapter Member` cm
            WHERE cm.member IN %(member_names)s
            AND cm.status = 'Active'
            ORDER BY cm.member, cm.creation DESC
        """,
            {"member_names": member_names},
            as_dict=True,
        )

        # Group chapters by member
        member_chapters_map = {}
        for cm in chapter_memberships:
            if cm.member not in member_chapters_map:
                member_chapters_map[cm.member] = []
            member_chapters_map[cm.member].append(cm.chapter_name)

        return member_chapters_map

    except Exception as e:
        frappe.logger().error(f"Error batch loading member chapters: {str(e)}")
        return {}


def batch_get_last_payment_dates(customer_names):
    """Batch load last payment dates for multiple customers to avoid N+1 queries"""
    if not customer_names:
        return {}

    try:
        # Single query to get last payment dates for all customers
        last_payments = frappe.db.sql(
            """
            SELECT
                pe.party as customer,
                MAX(pe.posting_date) as last_payment_date
            FROM `tabPayment Entry` pe
            WHERE pe.party_type = 'Customer'
                AND pe.party IN %(customer_names)s
                AND pe.docstatus = 1
            GROUP BY pe.party
        """,
            {"customer_names": customer_names},
            as_dict=True,
        )

        # Create payment dates map
        payment_dates_map = {payment.customer: payment.last_payment_date for payment in last_payments}

        return payment_dates_map

    except Exception as e:
        frappe.logger().error(f"Error batch loading last payment dates: {str(e)}")
        return {}
