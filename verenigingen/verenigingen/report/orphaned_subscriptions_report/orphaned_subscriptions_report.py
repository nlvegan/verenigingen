import frappe
from frappe import _


def execute(filters=None):
    """
    Orphaned Dues Schedule Report

    This report has been updated to focus on dues schedules instead of subscriptions.
    It identifies members who may have orphaned or misconfigured dues schedules.
    """
    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    return [
        {"fieldname": "record_type", "label": _("Record Type"), "fieldtype": "Data", "width": 120},
        {
            "fieldname": "document",
            "label": _("Document"),
            "fieldtype": "Dynamic Link",
            "options": "record_type",
            "width": 180,
        },
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 180,
        },
        {"fieldname": "member", "label": _("Member"), "fieldtype": "Link", "options": "Member", "width": 180},
        {"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 100},
        {"fieldname": "effective_date", "label": _("Effective Date"), "fieldtype": "Date", "width": 100},
        {
            "fieldname": "contribution_mode",
            "label": _("Contribution Mode"),
            "fieldtype": "Data",
            "width": 120,
        },
        {"fieldname": "issue_description", "label": _("Issue"), "fieldtype": "Text", "width": 200},
    ]


def get_data(filters=None):
    """
    Find orphaned or problematic dues schedules
    """
    data = []

    # 1. Find members with multiple active dues schedules
    multiple_active_schedules = frappe.db.sql(
        """
        SELECT
            member,
            COUNT(*) as count,
            GROUP_CONCAT(name) as schedule_names
        FROM `tabMembership Dues Schedule`
        WHERE status = 'Active'
        GROUP BY member
        HAVING count > 1
    """,
        as_dict=True,
    )

    for record in multiple_active_schedules:
        member_doc = frappe.get_doc("Member", record.member)
        customer = member_doc.customer if hasattr(member_doc, "customer") else None

        data.append(
            {
                "record_type": "Member",
                "document": record.member,
                "status": "Multiple Active Schedules",
                "customer": customer,
                "member": record.member,
                "amount": 0,
                "effective_date": None,
                "contribution_mode": "Multiple",
                "issue_description": f"Member has {record.count} active dues schedules: {record.schedule_names}",
            }
        )

    # 2. Find active members without any dues schedule
    members_without_schedules = frappe.db.sql(
        """
        SELECT
            m.name as member,
            m.status,
            m.membership_fee_override,
            m.customer
        FROM `tabMember` m
        LEFT JOIN `tabMembership Dues Schedule` mds ON m.name = mds.member AND mds.status = 'Active'
        WHERE m.status = 'Active'
        AND mds.member IS NULL
        AND (m.membership_fee_override IS NULL OR m.membership_fee_override = 0)
    """,
        as_dict=True,
    )

    for record in members_without_schedules:
        data.append(
            {
                "record_type": "Member",
                "document": record.member,
                "status": "No Active Schedule",
                "customer": record.customer,
                "member": record.member,
                "amount": record.membership_fee_override or 0,
                "effective_date": None,
                "contribution_mode": "None",
                "issue_description": "Active member has no dues schedule and no legacy override",
            }
        )

    # 3. Find dues schedules without valid members
    schedules_without_members = frappe.db.sql(
        """
        SELECT
            mds.name,
            mds.member,
            mds.status,
            mds.amount,
            mds.effective_date,
            mds.contribution_mode
        FROM `tabMembership Dues Schedule` mds
        LEFT JOIN `tabMember` m ON mds.member = m.name
        WHERE mds.status = 'Active'
        AND m.name IS NULL
    """,
        as_dict=True,
    )

    for record in schedules_without_members:
        data.append(
            {
                "record_type": "Membership Dues Schedule",
                "document": record.name,
                "status": "Orphaned Schedule",
                "customer": None,
                "member": record.member,
                "amount": record.amount,
                "effective_date": record.effective_date,
                "contribution_mode": record.contribution_mode,
                "issue_description": f"Dues schedule references non-existent member: {record.member}",
            }
        )

    # 4. Find dues schedules with zero amounts but no reason
    zero_amount_schedules = frappe.db.sql(
        """
        SELECT
            mds.name,
            mds.member,
            mds.status,
            mds.amount,
            mds.effective_date,
            mds.contribution_mode,
            mds.custom_amount_reason,
            m.customer
        FROM `tabMembership Dues Schedule` mds
        LEFT JOIN `tabMember` m ON mds.member = m.name
        WHERE mds.status = 'Active'
        AND mds.amount = 0
        AND (mds.custom_amount_reason IS NULL OR mds.custom_amount_reason = '')
    """,
        as_dict=True,
    )

    for record in zero_amount_schedules:
        data.append(
            {
                "record_type": "Membership Dues Schedule",
                "document": record.name,
                "status": "Zero Amount No Reason",
                "customer": record.customer,
                "member": record.member,
                "amount": record.amount,
                "effective_date": record.effective_date,
                "contribution_mode": record.contribution_mode,
                "issue_description": "Dues schedule has zero amount but no reason provided",
            }
        )

    # 5. Find dues schedules with invalid membership references
    invalid_membership_schedules = frappe.db.sql(
        """
        SELECT
            mds.name,
            mds.member,
            mds.membership,
            mds.status,
            mds.amount,
            mds.effective_date,
            mds.contribution_mode,
            m.customer
        FROM `tabMembership Dues Schedule` mds
        LEFT JOIN `tabMember` m ON mds.member = m.name
        LEFT JOIN `tabMembership` membership ON mds.membership = membership.name
        WHERE mds.status = 'Active'
        AND mds.membership IS NOT NULL
        AND membership.name IS NULL
    """,
        as_dict=True,
    )

    for record in invalid_membership_schedules:
        data.append(
            {
                "record_type": "Membership Dues Schedule",
                "document": record.name,
                "status": "Invalid Membership Reference",
                "customer": record.customer,
                "member": record.member,
                "amount": record.amount,
                "effective_date": record.effective_date,
                "contribution_mode": record.contribution_mode,
                "issue_description": f"References non-existent membership: {record.membership}",
            }
        )

    return data
