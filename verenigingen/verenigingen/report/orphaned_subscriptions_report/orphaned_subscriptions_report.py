import frappe
from frappe import _


def execute(filters=None):
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
        {"fieldname": "creation_date", "label": _("Creation Date"), "fieldtype": "Date", "width": 100},
        {"fieldname": "last_modified", "label": _("Last Modified"), "fieldtype": "Date", "width": 100},
        {"fieldname": "issue", "label": _("Issue"), "fieldtype": "Data", "width": 200},
    ]


def get_data(filters=None):
    data = []

    # 1. Find subscriptions without linked memberships
    orphaned_subscriptions = find_orphaned_subscriptions()
    for sub in orphaned_subscriptions:
        data.append(
            {
                "record_type": "Subscription",
                "document": sub.name,
                "status": sub.status,
                "customer": sub.party if sub.party_type == "Customer" else None,
                "creation_date": sub.creation.date(),
                "last_modified": sub.modified.date(),
                "issue": "No linked membership",
            }
        )

    # 2. Find memberships with non-existent subscriptions
    invalid_membership_links = find_invalid_membership_links()
    for mem in invalid_membership_links:
        data.append(
            {
                "record_type": "Membership",
                "document": mem.name,
                "status": mem.status,
                "member": mem.member,
                "creation_date": mem.creation.date(),
                "last_modified": mem.modified.date(),
                "issue": f"References non-existent subscription: {mem.subscription}",
            }
        )

    # 3. Find active memberships without subscriptions
    active_memberships_without_subs = find_active_memberships_without_subscriptions()
    for mem in active_memberships_without_subs:
        data.append(
            {
                "record_type": "Membership",
                "document": mem.name,
                "status": mem.status,
                "member": mem.member,
                "creation_date": mem.creation.date(),
                "last_modified": mem.modified.date(),
                "issue": "Active membership with no subscription",
            }
        )

    # 4. Find cancelled memberships with active subscriptions
    cancelled_memberships_with_active_subs = find_cancelled_memberships_with_active_subscriptions()
    for entry in cancelled_memberships_with_active_subs:
        data.append(
            {
                "record_type": "Membership",
                "document": entry.membership_name,
                "status": "Cancelled",
                "member": entry.member,
                "creation_date": entry.creation_date,
                "last_modified": entry.modified_date,
                "issue": f"Cancelled but subscription {entry.subscription_name} is still {entry.subscription_status}",
            }
        )

    return data


def find_orphaned_subscriptions():
    """Find subscriptions that have no linked memberships"""
    return frappe.db.sql(
        """
        SELECT s.*
        FROM `tabSubscription` s
        LEFT JOIN `tabMembership` m ON m.subscription = s.name
        WHERE s.status IN ('Active', 'Past Due')
        AND m.name IS NULL
        AND s.start_date >= DATE_SUB(CURDATE(), INTERVAL 2 YEAR)
    """,
        as_dict=1,
    )


def find_invalid_membership_links():
    """Find memberships that link to non-existent subscriptions"""
    return frappe.db.sql(
        """
        SELECT m.*
        FROM `tabMembership` m
        LEFT JOIN `tabSubscription` s ON m.subscription = s.name
        WHERE m.subscription IS NOT NULL
        AND s.name IS NULL
    """,
        as_dict=1,
    )


def find_active_memberships_without_subscriptions():
    """Find active memberships without subscription links"""
    return frappe.db.sql(
        """
        SELECT *
        FROM `tabMembership`
        WHERE status = 'Active'
        AND subscription IS NULL
        AND docstatus = 1
    """,
        as_dict=1,
    )


def find_cancelled_memberships_with_active_subscriptions():
    """Find cancelled memberships where the subscription is still active"""
    return frappe.db.sql(
        """
        SELECT
            m.name as membership_name,
            m.member,
            m.creation as creation_date,
            m.modified as modified_date,
            s.name as subscription_name,
            s.status as subscription_status
        FROM `tabMembership` m
        JOIN `tabSubscription` s ON m.subscription = s.name
        WHERE m.status = 'Cancelled'
        AND s.status IN ('Active', 'Past Due')
    """,
        as_dict=1,
    )
