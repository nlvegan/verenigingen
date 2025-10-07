import frappe


def check_membership_without_schedule():
    """Check members with Membership but no Dues Schedule"""

    # Count members with Membership but no Dues Schedule
    count = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT mem.member)
        FROM `tabMembership` mem
        WHERE mem.member IS NOT NULL
        AND mem.status = 'Active'
        AND NOT EXISTS (
            SELECT 1 FROM `tabMembership Dues Schedule` mds
            WHERE mds.member = mem.member
        )
    """
    )[0][0]

    print(f"Active Memberships without Dues Schedule: {count}")

    # Get the actual list
    members = frappe.db.sql(
        """
        SELECT DISTINCT mem.member, m.first_name, m.last_name, m.status
        FROM `tabMembership` mem
        INNER JOIN `tabMember` m ON m.name = mem.member
        WHERE mem.member IS NOT NULL
        AND mem.status = 'Active'
        AND NOT EXISTS (
            SELECT 1 FROM `tabMembership Dues Schedule` mds
            WHERE mds.member = mem.member
        )
    """,
        as_dict=True,
    )

    print(f"\nList of members with Membership but no Dues Schedule ({len(members)}):")
    for member in members:
        print(f"  {member.member}: {member.first_name} {member.last_name} (Member status: {member.status})")

    return count
