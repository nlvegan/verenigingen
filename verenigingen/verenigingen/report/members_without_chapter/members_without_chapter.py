import frappe
from frappe import _

from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters


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
    """Generate Members Without Chapter Report"""
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
            f"members_without_chapter report: {len(data)} rows processed in {execution_time:.2f}s"
        )

        return columns, data, None, chart, summary

    except Exception as e:
        execution_time = time.time() - start_time
        frappe.logger().error(f"members_without_chapter report failed after {execution_time:.2f}s: {str(e)}")
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

    # Validate required fields exist before proceeding
    required_member_fields = [
        "name",
        "full_name",
        "email",
        "contact_number",
        "primary_address",
        "status",
        "creation",
    ]
    required_address_fields = [
        "name",
        "city",
        "pincode",
        "country",
        "address_line1",
        "address_line2",
        "state",
    ]
    required_membership_fields = ["member", "status", "membership_type", "start_date"]

    if not all(
        [
            validate_doctype_fields("Member", required_member_fields),
            validate_doctype_fields("Address", required_address_fields),
            validate_doctype_fields("Membership", required_membership_fields),
        ]
    ):
        frappe.logger().error("Field validation failed in members_without_chapter report")
        return []  # Return empty data if validation fails

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

    # Batch load data to avoid N+1 queries
    member_names = [member.name for member in members]
    primary_addresses = [member.primary_address for member in members if member.primary_address]

    # Batch load address information
    address_data = {}
    if primary_addresses:
        addresses = frappe.get_all(
            "Address",
            filters={"name": ["in", primary_addresses]},
            fields=["name", "city", "pincode", "country", "address_line1", "address_line2", "state"],
        )
        for addr in addresses:
            address_data[addr.name] = {
                "city": addr.city,
                "pincode": addr.pincode,
                "country": addr.country,
                "address_line1": addr.address_line1,
                "address_line2": addr.address_line2,
                "state": addr.state,
            }

    # Batch load membership information
    membership_data = {}
    member_since_data = {}
    if member_names:
        # Get active memberships
        active_memberships = frappe.get_all(
            "Membership",
            filters={"member": ["in", member_names], "status": "Active"},
            fields=["member", "membership_type", "status"],
        )
        for membership in active_memberships:
            membership_data[membership.member] = f"Active ({membership.membership_type or 'Unknown Type'})"

        # Get latest memberships for members without active ones
        members_without_active = [name for name in member_names if name not in membership_data]
        if members_without_active:
            latest_memberships = frappe.db.sql(
                """
                SELECT m1.member, m1.status, m1.membership_type
                FROM `tabMembership` m1
                INNER JOIN (
                    SELECT member, MAX(creation) as max_creation
                    FROM `tabMembership`
                    WHERE member IN %(member_names)s
                    GROUP BY member
                ) m2 ON m1.member = m2.member AND m1.creation = m2.max_creation
            """,
                {"member_names": members_without_active},
                as_dict=True,
            )

            for membership in latest_memberships:
                membership_data[membership.member] = membership.status or "Unknown"

        # Set default for members with no memberships
        for member_name in member_names:
            if member_name not in membership_data:
                membership_data[member_name] = "No Membership"

        # Get member since dates (earliest membership)
        earliest_memberships = frappe.db.sql(
            """
            SELECT member, MIN(start_date) as earliest_date
            FROM `tabMembership`
            WHERE member IN %(member_names)s
            GROUP BY member
        """,
            {"member_names": member_names},
            as_dict=True,
        )

        for membership in earliest_memberships:
            member_since_data[membership.member] = membership.earliest_date

    # Pre-load chapters for suggestion logic to avoid repeated queries
    chapters_for_suggestion = frappe.get_all(
        "Chapter", filters={"published": 1}, fields=["name", "region"], order_by="name"
    )

    # OPTIMIZATION: Batch process chapter suggestions for all members at once
    member_postal_codes = []
    for member in members:
        address_info = address_data.get(member.primary_address, {})
        postal_code = address_info.get("pincode")
        if postal_code:
            member_postal_codes.append((member.name, postal_code))

    # Get all chapter suggestions in one batch operation
    try:
        from verenigingen.services.chapter.optimized_chapter_lookup import batch_suggest_chapters_for_members

        batch_chapter_suggestions = batch_suggest_chapters_for_members(member_postal_codes)
    except ImportError:
        frappe.logger().warning("Optimized batch chapter lookup not available - using individual lookups")
        batch_chapter_suggestions = {}

    data = []
    for member in members:
        # Get cached address information
        address_info = address_data.get(member.primary_address, {})

        # Apply country filter if specified
        if filters and filters.get("country"):
            if address_info.get("country") != filters.get("country"):
                continue

        # Get cached membership status
        membership_status = membership_data.get(member.name, "Unknown")

        # Get cached member since date
        member_since = member_since_data.get(member.name)
        if not member_since:
            from frappe.utils import getdate

            member_since = getdate(member.creation)  # Fallback to member creation date

        # Get suggested chapter from batch results or fallback to individual lookup
        suggested_chapter = batch_chapter_suggestions.get(member.name)
        if suggested_chapter is None and address_info.get("pincode"):
            # Fallback for members not in batch (shouldn't happen normally)
            suggested_chapter = suggest_chapter_for_member_optimized(
                member, address_info, chapters_for_suggestion
            )

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


def suggest_chapter_for_member_optimized(member, address_info, preloaded_chapters):
    """Optimized version that uses cached chapter lookup to avoid N+1 queries"""
    postal_code = address_info.get("pincode")
    if not postal_code:
        return None

    try:
        # Use the new optimized chapter lookup utility
        from verenigingen.services.chapter.optimized_chapter_lookup import get_lookup_instance

        lookup = get_lookup_instance()
        suggested_chapter = lookup.find_best_chapter_for_postal_code(postal_code)

        if suggested_chapter:
            return suggested_chapter

        return None

    except ImportError:
        frappe.logger().warning("Optimized chapter lookup not available - falling back to simple matching")
        # Fallback: use pre-loaded chapters for simple proximity matching
        try:
            # Simple heuristic: match by city/region if available
            city = address_info.get("city")
            if city and preloaded_chapters:
                for chapter in preloaded_chapters:
                    if chapter.region and city.lower() in chapter.region.lower():
                        return chapter.name

            return None
        except Exception as e:
            frappe.logger().error(
                f"Error in fallback chapter suggestion for postal code {postal_code}: {str(e)}"
            )
            return None
    except Exception as e:
        frappe.logger().error(
            f"Error in optimized chapter suggestion for postal code {postal_code}: {str(e)}"
        )
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
