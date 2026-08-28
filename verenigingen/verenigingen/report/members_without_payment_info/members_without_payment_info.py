# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
    """Generate Members Without Payment Info Report"""
    columns = get_columns()
    data = get_data(filters)
    summary = get_summary(data)
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
            "width": 150,
        },
        {"label": _("Member Name"), "fieldname": "full_name", "fieldtype": "Data", "width": 180},
        {"label": _("Email"), "fieldname": "email", "fieldtype": "Data", "width": 200},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Chapter(s)"), "fieldname": "chapters", "fieldtype": "Data", "width": 150},
        {
            "label": _("Payment Method"),
            "fieldname": "payment_method",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Missing Info"),
            "fieldname": "missing_info",
            "fieldtype": "HTML",
            "width": 200,
        },
        {
            "label": _("Has Mollie"),
            "fieldname": "has_mollie",
            "fieldtype": "Check",
            "width": 80,
        },
        {
            "label": _("Has SEPA"),
            "fieldname": "has_sepa",
            "fieldtype": "Check",
            "width": 80,
        },
        {
            "label": _("Has Bank Transfer"),
            "fieldname": "has_bank_transfer",
            "fieldtype": "Check",
            "width": 120,
        },
        {
            "label": _("Member Since"),
            "fieldname": "member_since",
            "fieldtype": "Date",
            "width": 100,
        },
    ]


def get_data(filters):
    """Get members without valid payment information"""

    # Base member filters
    member_filters = {"status": ["in", ["Active", "Pending"]]}

    # Apply chapter filter if specified
    if filters and filters.get("chapter"):
        # Get members in the specified chapter
        chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"parent": filters.get("chapter"), "enabled": 1, "status": "Active"},
            fields=["member"],
        )
        member_names = [cm.member for cm in chapter_members]

        if not member_names:
            return []  # No members in this chapter

        member_filters["name"] = ["in", member_names]

    # Get all members
    members = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=[
            "name",
            "full_name",
            "email",
            "status",
            "payment_method",
            "mollie_customer_id",
            "mollie_subscription_id",
            "subscription_status",
            "iban",
            "bank_account_name",
            "member_since",
        ],
        order_by="member_since desc",
    )

    if not members:
        return []

    # Batch load chapter information
    member_names = [m.name for m in members]
    chapter_data = {}
    if member_names:
        chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"member": ["in", member_names], "enabled": 1, "status": "Active"},
            fields=["member", "parent"],
        )
        for cm in chapter_members:
            if cm.member not in chapter_data:
                chapter_data[cm.member] = []
            chapter_data[cm.member].append(cm.parent)

    # Batch load SEPA mandate information
    sepa_data = {}
    if member_names:
        active_sepa_mandates = frappe.db.sql(
            """
            SELECT sm.member, sm.name, sm.status, sm.is_active
            FROM `tabSEPA Mandate` sm
            WHERE sm.member IN %(member_names)s
            AND sm.status = 'Active'
            AND sm.is_active = 1
            -- This report answers "can this member's DUES be collected", so a
            -- donation mandate is not a payment method for it (#605). Unscoped, a
            -- member with a donation mandate and no membership mandate was skipped
            -- as covered -- which is precisely the member the report exists to find.
            AND sm.used_for_memberships = 1
            """,
            {"member_names": member_names},
            as_dict=True,
        )
        for sepa in active_sepa_mandates:
            sepa_data[sepa.member] = True

    data = []
    for member in members:
        # Check Mollie credentials
        has_mollie = bool(
            member.mollie_customer_id
            and member.mollie_subscription_id
            and member.subscription_status == "active"
        )

        # Check SEPA mandate
        has_sepa = sepa_data.get(member.name, False)

        # Check Bank Transfer info
        has_bank_transfer = bool(
            member.payment_method == "Bank Transfer" and member.iban and member.bank_account_name
        )

        # Skip members who have at least one valid payment method
        if has_mollie or has_sepa or has_bank_transfer:
            continue

        # Build missing info description
        missing_parts = []
        if not has_mollie:
            if member.payment_method == "Mollie":
                if not member.mollie_customer_id:
                    missing_parts.append("Mollie Customer ID")
                if not member.mollie_subscription_id:
                    missing_parts.append("Mollie Subscription ID")
                if member.subscription_status != "active":
                    missing_parts.append(
                        f"Active Subscription (status: {member.subscription_status or 'none'})"
                    )
            else:
                missing_parts.append("Mollie setup incomplete")

        if not has_sepa:
            missing_parts.append("Active SEPA Mandate")

        if not has_bank_transfer:
            if member.payment_method == "Bank Transfer":
                if not member.iban:
                    missing_parts.append("IBAN")
                if not member.bank_account_name:
                    missing_parts.append("Account Holder Name")
            else:
                missing_parts.append("Bank Transfer setup incomplete")

        # Get chapters
        chapters = chapter_data.get(member.name, [])
        chapters_str = ", ".join(chapters) if chapters else _("No Chapter")

        # Build HTML indicator for missing info
        missing_info_html = '<span class="indicator red">' + ", ".join(missing_parts) + "</span>"

        row = {
            "member_name": member.name,
            "full_name": member.full_name,
            "email": member.email,
            "status": member.status,
            "chapters": chapters_str,
            "payment_method": member.payment_method or _("Not Set"),
            "missing_info": missing_info_html,
            "has_mollie": has_mollie,
            "has_sepa": has_sepa,
            "has_bank_transfer": has_bank_transfer,
            "member_since": member.member_since,
        }

        data.append(row)

    return data


def get_summary(data):
    """Generate summary statistics"""
    if not data:
        return []

    total_members = len(data)

    # Count by payment method
    payment_methods = {}
    for row in data:
        method = row.get("payment_method") or "Not Set"
        payment_methods[method] = payment_methods.get(method, 0) + 1

    # Count by status
    status_counts = {}
    for row in data:
        status = row.get("status")
        status_counts[status] = status_counts.get(status, 0) + 1

    # Count members without chapter
    without_chapter = len([d for d in data if d.get("chapters") == "No Chapter"])

    return [
        {
            "value": total_members,
            "label": _("Total Members Without Payment Info"),
            "datatype": "Int",
            "color": "red",
        },
        {
            "value": status_counts.get("Active", 0),
            "label": _("Active Members"),
            "datatype": "Int",
            "color": "orange",
        },
        {
            "value": status_counts.get("Pending", 0),
            "label": _("Pending Members"),
            "datatype": "Int",
            "color": "yellow",
        },
        {
            "value": without_chapter,
            "label": _("Members Without Chapter"),
            "datatype": "Int",
            "color": "blue",
        },
        {
            "value": ", ".join([f"{k}: {v}" for k, v in payment_methods.items()]),
            "label": _("Payment Method Breakdown"),
            "datatype": "Data",
        },
    ]


def get_chart_data(data):
    """Generate chart showing missing payment info distribution"""
    if not data:
        return None

    # Count by status
    status_counts = {"Active": 0, "Pending": 0, "Other": 0}

    for row in data:
        status = row.get("status")
        if status == "Active":
            status_counts["Active"] += 1
        elif status == "Pending":
            status_counts["Pending"] += 1
        else:
            status_counts["Other"] += 1

    # Filter out zero values
    filtered_counts = {k: v for k, v in status_counts.items() if v > 0}

    return {
        "data": {
            "labels": list(filtered_counts.keys()),
            "datasets": [
                {"name": _("Members Without Payment Info"), "values": list(filtered_counts.values())}
            ],
        },
        "type": "pie",
        "colors": ["#ff6348", "#ffa502", "#95afc0"],
    }
