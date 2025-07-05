import frappe
from frappe import _


def execute(filters=None):
    """Generate Members Without Chapter Report"""

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
        {"label": _("Member Name"), "fieldname": "member_full_name", "fieldtype": "Data", "width": 180},
        {"label": _("Email"), "fieldname": "member_email", "fieldtype": "Data", "width": 200},
        {"label": _("Phone"), "fieldname": "mobile_no", "fieldtype": "Data", "width": 130},
        {"label": _("City"), "fieldname": "city", "fieldtype": "Data", "width": 120},
        {"label": _("Postal Code"), "fieldname": "postal_code", "fieldtype": "Data", "width": 100},
        {"label": _("Country"), "fieldname": "country", "fieldtype": "Data", "width": 120},
        {
            "label": _("Membership Status"),
            "fieldname": "membership_status",
            "fieldtype": "Data",
            "width": 130,
        },
        {"label": _("Member Since"), "fieldname": "member_since", "fieldtype": "Date", "width": 120},
        {
            "label": _("Suggested Chapter"),
            "fieldname": "suggested_chapter",
            "fieldtype": "Data",
            "width": 150,
        },
        {"label": _("Actions"), "fieldname": "actions", "fieldtype": "HTML", "width": 100},
    ]


def get_data(filters):
    """Get report data using Frappe ORM methods"""

    # Get members who are not in any Chapter Member records
    members_with_chapters = frappe.get_all(
        "Chapter Member", filters={"enabled": 1}, fields=["member"], distinct=True
    )

    excluded_members = [m.member for m in members_with_chapters]

    # Base filters for members without chapter
    member_filters = {}
    if excluded_members:
        member_filters["name"] = ["not in", excluded_members]

    # Apply additional filters
    if filters:
        if filters.get("membership_status"):
            member_filters["status"] = filters.get("membership_status")

        # Note: country filtering will be applied after getting address info

        if filters.get("from_date"):
            member_filters["creation"] = [">=", filters.get("from_date")]

        if filters.get("to_date"):
            if "creation" in member_filters:
                member_filters["creation"] = ["between", [filters.get("from_date"), filters.get("to_date")]]
            else:
                member_filters["creation"] = ["<=", filters.get("to_date")]

    # Get members without chapter assignment
    members = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=["name", "full_name", "email", "contact_number", "primary_address", "status", "creation"],
        order_by="creation desc",
    )

    if not members:
        return []

    # Apply user-based chapter filtering
    user_chapters = get_user_accessible_chapters()

    data = []
    for member in members:
        # Get address information
        address_info = get_member_address_info(member.primary_address)

        # Apply country filter if specified
        if filters and filters.get("country"):
            if address_info.get("country") != filters.get("country"):
                continue

        # Get membership status
        membership_status = get_member_membership_status(member.name)

        # Get member since date (earliest active membership)
        member_since = get_member_since_date(member.name)

        # Suggest chapter based on location
        suggested_chapter = suggest_chapter_for_member(member, address_info)

        # Apply user access filtering if needed
        if user_chapters is not None:  # None means see all
            # For members without chapters, only show if user has national access
            # or if the suggested chapter is in user's accessible chapters
            if suggested_chapter and suggested_chapter not in user_chapters:
                # Check if user has national access
                try:
                    settings = frappe.get_single("Verenigingen Settings")
                    if (
                        hasattr(settings, "national_board_chapter")
                        and settings.national_board_chapter in user_chapters
                    ):
                        pass  # User has national access
                    else:
                        continue  # Skip this member
                except Exception:
                    continue

        # Build row data
        row = {
            "member_name": member.name,
            "member_full_name": member.full_name,
            "member_email": member.email,
            "mobile_no": member.contact_number,
            "city": address_info.get("city", ""),
            "postal_code": address_info.get("pincode", ""),
            "country": address_info.get("country", ""),
            "membership_status": membership_status,
            "member_since": member_since,
            "suggested_chapter": suggested_chapter or _("No suggestion available"),
            "actions": get_action_buttons(member.name, suggested_chapter),
        }

        data.append(row)

    return data


def get_member_membership_status(member_name):
    """Get current membership status for a member"""
    try:
        active_membership = frappe.get_value(
            "Membership", {"member": member_name, "status": "Active"}, ["membership_type", "status"]
        )

        if active_membership:
            return f"Active ({active_membership[0] if active_membership[0] else 'Unknown Type'})"

        # Check for other membership statuses
        latest_membership = frappe.get_value(
            "Membership", {"member": member_name}, ["status", "membership_type"], order_by="creation desc"
        )

        if latest_membership:
            return latest_membership[0] or "Unknown"

        return "No Membership"

    except Exception:
        return "Unknown"


def get_member_address_info(primary_address):
    """Get address information from linked Address record"""
    if not primary_address:
        return {}

    try:
        address = frappe.get_doc("Address", primary_address)
        return {
            "city": address.city,
            "pincode": address.pincode,
            "country": address.country,
            "address_line1": address.address_line1,
            "address_line2": address.address_line2,
            "state": address.state,
        }
    except Exception:
        return {}


def get_member_since_date(member_name):
    """Get the date when member first became active"""
    try:
        earliest_membership = frappe.get_value(
            "Membership", {"member": member_name}, "from_date", order_by="from_date"
        )

        if earliest_membership:
            return earliest_membership

        # Fallback to member creation date
        return frappe.get_value("Member", member_name, "creation")

    except Exception:
        return None


def suggest_chapter_for_member(member, address_info):
    """Suggest appropriate chapter for member based on location"""
    postal_code = address_info.get("pincode")
    if not postal_code:
        return None

    try:
        # Use the existing chapter suggestion logic
        from verenigingen.verenigingen.doctype.member.member_utils import find_chapter_by_postal_code

        result = find_chapter_by_postal_code(postal_code)

        if result.get("success") and result.get("matching_chapters"):
            return result["matching_chapters"][0]["name"]

        return None

    except Exception:
        # Fallback: try simple proximity matching
        try:
            chapters = frappe.get_all(
                "Chapter", filters={"published": 1}, fields=["name", "region"], order_by="name"
            )

            # Simple heuristic: match by city/region if available
            city = address_info.get("city")
            if city:
                for chapter in chapters:
                    if chapter.region and city.lower() in chapter.region.lower():
                        return chapter.name

            return None
        except Exception:
            return None


def get_action_buttons(member_name, suggested_chapter):
    """Generate action buttons for each row"""
    buttons = []

    # Assign to suggested chapter button
    if suggested_chapter and suggested_chapter != "No suggestion available":
        buttons.append(
            """
            <button class="btn btn-xs btn-primary assign-chapter-btn"
                    data-member="{member_name}"
                    data-chapter="{suggested_chapter}"
                    title="Assign to {suggested_chapter}">
                <i class="fa fa-plus"></i> {suggested_chapter}
            </button>
        """
        )

    # Manual assignment button
    buttons.append(
        """
        <button class="btn btn-xs btn-secondary manual-assign-btn"
                data-member="{member_name}"
                title="Choose chapter manually">
            <i class="fa fa-edit"></i> Manual
        </button>
    """
    )

    return " ".join(buttons)


def get_user_accessible_chapters():
    """Get chapters accessible to current user"""
    user = frappe.session.user

    # System managers and Association/Membership managers see all
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return None  # No filter - see all

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return []  # No access if not a member

    # Get chapters where user has board access with membership or admin permissions
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
                    if role_doc.permissions_level in ["Admin", "Membership"]:
                        if position.parent not in user_chapters:
                            user_chapters.append(position.parent)
                except Exception:
                    continue

        # Add national chapter if configured and user has access
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "national_board_chapter") and settings.national_board_chapter:
                national_board_positions = frappe.get_all(
                    "Chapter Board Member",
                    filters={
                        "parent": settings.national_board_chapter,
                        "volunteer": [v.name for v in volunteer_records],
                        "is_active": 1,
                    },
                    fields=["chapter_role"],
                )

                for position in national_board_positions:
                    try:
                        role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                        if role_doc.permissions_level in ["Admin", "Membership"]:
                            if settings.national_board_chapter not in user_chapters:
                                user_chapters.append(settings.national_board_chapter)
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
    members_with_suggestions = len(
        [d for d in data if d.get("suggested_chapter") != "No suggestion available"]
    )
    active_members = len([d for d in data if "Active" in (d.get("membership_status") or "")])

    # Group by country
    countries = {}
    for row in data:
        country = row.get("country") or "Unknown"
        countries[country] = countries.get(country, 0) + 1

    most_common_country = max(countries.items(), key=lambda x: x[1]) if countries else ("Unknown", 0)

    return [
        {
            "value": total_members,
            "label": _("Total Members Without Chapter"),
            "datatype": "Int",
            "color": "orange",
        },
        {
            "value": members_with_suggestions,
            "label": _("Members with Chapter Suggestions"),
            "datatype": "Int",
            "color": "blue",
        },
        {
            "value": active_members,
            "label": _("Active Members Without Chapter"),
            "datatype": "Int",
            "color": "green" if active_members == 0 else "orange",
        },
        {
            "value": f"{most_common_country[0]} ({most_common_country[1]})",
            "label": _("Most Common Country"),
            "datatype": "Data",
        },
        {
            "value": round((members_with_suggestions / total_members * 100), 1) if total_members > 0 else 0,
            "label": _("% with Suggestions"),
            "datatype": "Percent",
        },
    ]


def get_chart_data(data):
    """Get chart data for visualization"""
    if not data:
        return None

    # Group by membership status
    status_counts = {}
    for row in data:
        status = row.get("membership_status") or "Unknown"
        # Simplify status for chart
        if "Active" in status:
            simple_status = "Active"
        elif "Expired" in status:
            simple_status = "Expired"
        elif "No Membership" in status:
            simple_status = "No Membership"
        else:
            simple_status = "Other"

        status_counts[simple_status] = status_counts.get(simple_status, 0) + 1

    return {
        "data": {
            "labels": list(status_counts.keys()),
            "datasets": [{"name": _("Members by Status"), "values": list(status_counts.values())}],
        },
        "type": "donut",
        "colors": ["#28a745", "#ffc107", "#dc3545", "#6c757d"],
    }
