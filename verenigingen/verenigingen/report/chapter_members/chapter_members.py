import frappe


def execute(filters=None):
    if not filters:
        filters = {}

    chapter = filters.get("chapter")
    if not chapter:
        frappe.throw("Chapter parameter is required")

    status_filter = filters.get("status")

    # Security check: Only allow board members to see their own chapter
    # or administrators to see any chapter
    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
    ):
        # Check if user is a board member of this chapter
        user_email = frappe.session.user
        member = frappe.db.get_value("Member", {"user": user_email}, "name")

        if member:
            # Check via volunteer relationship
            volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")

            if volunteer:
                is_board_member = frappe.db.exists(
                    "Chapter Board Member", {"parent": chapter, "volunteer": volunteer, "is_active": 1}
                )

                if not is_board_member:
                    frappe.throw("You can only view members of chapters where you are a board member")
            else:
                frappe.throw("You must be registered as a volunteer to access this report")
        else:
            frappe.throw("You must be a member to access this report")

    columns = [
        {"fieldname": "member", "label": "Member", "fieldtype": "Link", "options": "Member", "width": 150},
        {"fieldname": "full_name", "label": "Full Name", "fieldtype": "Data", "width": 180},
        {"fieldname": "email", "label": "Email", "fieldtype": "Data", "width": 180},
        {"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 100},
        {"fieldname": "chapter_join_date", "label": "Join Date", "fieldtype": "Date", "width": 120},
        {"fieldname": "enabled", "label": "Active", "fieldtype": "Check", "width": 80},
        {"fieldname": "leave_reason", "label": "Leave Reason", "fieldtype": "Data", "width": 150},
    ]

    # Determine filtering based on user roles
    user_roles = frappe.get_roles()
    can_view_pending = (
        "System Manager" in user_roles
        or "Verenigingen Administrator" in user_roles
        or frappe.session.user == "Administrator"
    )

    # Check if user is a board member of this chapter (can also view pending members)
    if not can_view_pending:
        user_email = frappe.session.user
        member = frappe.db.get_value("Member", {"user": user_email}, "name")
        if member:
            volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
            if volunteer:
                is_board_member = frappe.db.exists(
                    "Chapter Board Member", {"parent": chapter, "volunteer": volunteer, "is_active": 1}
                )
                can_view_pending = bool(is_board_member)

    # Build SQL query with appropriate filtering
    where_conditions = ["cm.parent = %(chapter)s"]
    query_params = {"chapter": chapter}

    # If user cannot view pending members, only show active and enabled members
    if not can_view_pending:
        where_conditions.append("cm.enabled = 1")
        where_conditions.append("(cm.status IS NULL OR cm.status = 'Active')")

    # Add status filter if provided (only if user can view pending members)
    if status_filter and can_view_pending:
        if status_filter == "Pending":
            where_conditions.append("cm.status = %(status)s")
        elif status_filter == "Active":
            where_conditions.append("(cm.status IS NULL OR cm.status = %(status)s)")
        elif status_filter == "Inactive":
            where_conditions.append("cm.status = %(status)s")
        query_params["status"] = status_filter

    " AND ".join(where_conditions)

    data = frappe.db.sql(
        """
        SELECT
            cm.member,
            m.full_name,
            m.email,
            COALESCE(cm.status, 'Active') as status,
            cm.chapter_join_date,
            cm.enabled,
            cm.leave_reason
        FROM
            `tabChapter Member` cm
        INNER JOIN
            `tabMember` m ON cm.member = m.name
        WHERE
            {where_clause}
        ORDER BY
            CASE
                WHEN COALESCE(cm.status, 'Active') = 'Pending' THEN 1
                WHEN COALESCE(cm.status, 'Active') = 'Active' THEN 2
                ELSE 3
            END,
            cm.chapter_join_date DESC
    """,
        query_params,
        as_dict=True,
    )

    return columns, data
