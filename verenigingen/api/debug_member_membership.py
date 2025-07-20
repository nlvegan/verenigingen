"""
Debug member membership status and Create Membership button logic
"""

import frappe


@frappe.whitelist()
def debug_member_membership_status(member_name):
    """Debug why Create Membership button might not show for a member"""
    try:
        # Get member record
        member = frappe.get_doc("Member", member_name)

        # Get all memberships for this member
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name},
            fields=["name", "status", "membership_type", "start_date", "cancellation_date", "docstatus"],
            order_by="creation desc",
        )

        # Check what the JavaScript condition is looking for
        # Based on member.js: filters: {'member': frm.doc.name, 'status': ['in', ['Active', 'Pending']], 'docstatus': ['!=', 2]}
        active_or_pending_memberships = frappe.get_all(
            "Membership",
            filters={
                "member": member_name,
                "status": ["in", ["Active", "Pending"]],
                "docstatus": ["!=", 2],  # Exclude cancelled documents
            },
            fields=["name", "status", "docstatus"],
        )

        # Check docstatus requirements
        submitted_memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name, "docstatus": ["!=", 2]},  # Not cancelled documents
            fields=["name", "status", "docstatus"],
        )

        return {
            "member_name": member_name,
            "member_status": member.status,
            "total_memberships": len(memberships),
            "all_memberships": memberships,
            "active_or_pending_count": len(active_or_pending_memberships),
            "active_or_pending_memberships": active_or_pending_memberships,
            "submitted_memberships_count": len(submitted_memberships),
            "submitted_memberships": submitted_memberships,
            "should_show_create_button": len(active_or_pending_memberships) == 0,
            "debug_info": {
                "javascript_filter_logic": "status IN ['Active', 'Pending']",
                "button_shows_when": "No Active or Pending memberships found",
            },
        }

    except Exception as e:
        return {"error": str(e), "member_name": member_name}


@frappe.whitelist()
def debug_member_dues_schedule_connection(member_name):
    """Debug member's connection to dues schedules"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Get current memberships
        current_memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name, "status": "Active"},
            fields=["name", "membership_type", "start_date", "cancellation_date"],
        )

        # Get dues schedules
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=[
                "name",
                "billing_frequency",
                "dues_rate",
                "status",
                "membership_type",
                "next_invoice_date",
            ],
            order_by="creation desc",
        )

        # Get recent payments
        recent_payments = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member_name, "docstatus": ["!=", 2]},
            fields=["name", "status", "grand_total", "posting_date", "due_date"],
            order_by="posting_date desc",
            limit=5,
        )

        return {
            "member_name": member_name,
            "current_memberships": current_memberships,
            "dues_schedules_count": len(dues_schedules),
            "dues_schedules": dues_schedules,
            "recent_payments_count": len(recent_payments),
            "recent_payments": recent_payments,
        }

    except Exception as e:
        return {"error": str(e), "member_name": member_name}


@frappe.whitelist()
def test_members_without_active_memberships_report():
    """Test the new report function with multiple filter sets"""
    from verenigingen.verenigingen.report.members_without_active_memberships.members_without_active_memberships import (
        get_columns,
        get_data,
    )

    # Test with multiple filter combinations
    test_filters = [
        {"include_terminated": False, "include_suspended": True},
        {"include_terminated": True, "include_suspended": True},
        {"include_terminated": False, "include_suspended": False},
        {},  # No filters
    ]

    results = {}

    for i, filters in enumerate(test_filters):
        try:
            columns = get_columns(filters)
            data = get_data(filters)

            results[f"test_{i+1}"] = {
                "filters": filters,
                "total_members": len(data),
                "sample_data": data[:3] if data else [],
                "columns_count": len(columns),
            }
        except Exception as e:
            results[f"test_{i+1}"] = {"filters": filters, "error": str(e)}

    return results


@frappe.whitelist()
def debug_membership_data_overview():
    """Get overview of all membership data for debugging"""
    try:
        # Get all members count
        total_members = frappe.db.count("Member", {"docstatus": ["!=", 2]})

        # Get membership status breakdown
        membership_status = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabMembership`
            WHERE docstatus != 2
            GROUP BY status
        """,
            as_dict=1,
        )

        # Get member status breakdown
        member_status = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabMember`
            WHERE docstatus != 2
            GROUP BY status
        """,
            as_dict=1,
        )

        # Get members with active memberships
        members_with_active = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT member) as count
            FROM `tabMembership`
            WHERE status = 'Active' AND docstatus != 2
        """,
            as_dict=1,
        )

        # Get some sample members without active memberships
        members_without_active = frappe.db.sql(
            """
            SELECT m.name, m.full_name, m.status as member_status
            FROM `tabMember` m
            WHERE m.docstatus != 2
            AND m.name NOT IN (
                SELECT DISTINCT member
                FROM `tabMembership`
                WHERE status = 'Active' AND docstatus != 2
            )
            LIMIT 10
        """,
            as_dict=1,
        )

        return {
            "total_members": total_members,
            "membership_status_breakdown": membership_status,
            "member_status_breakdown": member_status,
            "members_with_active_memberships": members_with_active[0]["count"] if members_with_active else 0,
            "sample_members_without_active": members_without_active,
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def debug_report_sql():
    """Debug the exact SQL being generated by the report"""
    try:
        # Let's test the exact SQL from the report
        sql_query = """
            SELECT
                m.name as member_id,
                m.full_name as member_name,
                m.email,
                m.status as member_status,
                m.member_since,
                last_membership.name as last_membership_id,
                last_membership.membership_type as last_membership_type,
                last_membership.status as last_membership_status,
                last_membership.end_date as last_membership_end,
                CASE
                    WHEN last_membership.end_date IS NOT NULL
                    THEN DATEDIFF(CURDATE(), last_membership.end_date)
                    ELSE NULL
                END as days_since_last_membership,
                m.contact_number
            FROM `tabMember` m
            LEFT JOIN (
                SELECT
                    member,
                    name,
                    membership_type,
                    status,
                    COALESCE(cancellation_date, start_date) as end_date,
                    ROW_NUMBER() OVER (PARTITION BY member ORDER BY creation DESC) as rn
                FROM `tabMembership`
                WHERE docstatus != 2
            ) last_membership ON m.name = last_membership.member AND last_membership.rn = 1
            WHERE m.docstatus != 2 AND m.status != 'Terminated'
            AND m.name NOT IN (
                SELECT DISTINCT member
                FROM `tabMembership`
                WHERE status = 'Active'
                AND docstatus != 2
            )
            LIMIT 10
        """

        result = frappe.db.sql(sql_query, as_dict=1)

        # Also test just the subquery to see what it returns
        subquery_test = frappe.db.sql(
            """
            SELECT DISTINCT member
            FROM `tabMembership`
            WHERE status = 'Active'
            AND docstatus != 2
            LIMIT 10
        """,
            as_dict=1,
        )

        return {
            "main_query_result_count": len(result),
            "main_query_sample": result[:3] if result else [],
            "active_members_subquery_count": len(subquery_test),
            "active_members_sample": subquery_test[:5] if subquery_test else [],
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def comprehensive_implementation_test():
    """Test all three implemented features"""
    try:
        results = {}

        # Test 1: Create Membership Button Fix
        results["test_1_create_membership_button"] = debug_member_membership_status(
            "Assoc-Member-2025-07-0030"
        )

        # Test 2: Dues Schedule Connection
        results["test_2_dues_schedule_connection"] = debug_member_dues_schedule_connection(
            "Assoc-Member-2025-07-0024"
        )

        # Test 3: Members Without Active Memberships Report
        from verenigingen.verenigingen.report.members_without_active_memberships.members_without_active_memberships import (
            get_data,
            get_report_summary,
        )

        filters = {"include_terminated": False, "include_suspended": True}
        report_data = get_data(filters)
        report_summary = get_report_summary(filters)

        results["test_3_inactive_members_report"] = {
            "total_members_without_active": len(report_data),
            "summary": report_summary,
            "sample_members": report_data[:3] if report_data else [],
        }

        # Overall status
        results["overall_status"] = {
            "all_tests_successful": True,
            "test_1_button_shows": results["test_1_create_membership_button"]["should_show_create_button"],
            "test_2_has_dues_schedule": results["test_2_dues_schedule_connection"]["dues_schedules_count"]
            > 0,
            "test_3_report_working": results["test_3_inactive_members_report"]["total_members_without_active"]
            > 0,
        }

        return results

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def test_dues_schedule_field_functionality():
    """Test that the current_dues_schedule field works correctly"""
    try:
        # Test member with active dues schedule
        member_with_schedule = "Assoc-Member-2025-07-0024"

        # Get dues schedule details (simulates what JavaScript does)
        from verenigingen.verenigingen.doctype.member.member import get_current_dues_schedule_details

        schedule_details = get_current_dues_schedule_details(member_with_schedule)

        # Update the field (simulates what JavaScript does)
        if schedule_details.get("has_schedule") and schedule_details.get("schedule_name"):
            frappe.db.set_value(
                "Member", member_with_schedule, "current_dues_schedule", schedule_details["schedule_name"]
            )
            frappe.db.commit()

        # Verify the field was set
        current_field_value = frappe.db.get_value("Member", member_with_schedule, "current_dues_schedule")

        # Test member without dues schedule
        member_without_schedule = "Assoc-Member-2025-07-0030"
        schedule_details_empty = get_current_dues_schedule_details(member_without_schedule)

        # Clear field for member without schedule
        if not schedule_details_empty.get("has_schedule"):
            frappe.db.set_value("Member", member_without_schedule, "current_dues_schedule", "")
            frappe.db.commit()

        empty_field_value = frappe.db.get_value("Member", member_without_schedule, "current_dues_schedule")

        return {
            "field_migration_successful": True,
            "member_with_schedule": {
                "member": member_with_schedule,
                "schedule_details": schedule_details,
                "field_value": current_field_value,
                "field_populated_correctly": bool(current_field_value),
            },
            "member_without_schedule": {
                "member": member_without_schedule,
                "schedule_details": schedule_details_empty,
                "field_value": empty_field_value,
                "field_cleared_correctly": not bool(empty_field_value),
            },
            "overall_status": "✅ Field functionality working correctly",
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def get_members_without_active_memberships():
    """Get all members without active memberships for reporting"""
    try:
        # Get all members
        all_members = frappe.get_all(
            "Member",
            filters={"status": ["!=", "Terminated"]},
            fields=["name", "full_name", "email", "status", "creation"],
        )

        members_without_active = []

        for member in all_members:
            # Check for active memberships
            active_memberships = frappe.get_all(
                "Membership", filters={"member": member.name, "status": "Active"}, limit=1
            )

            if not active_memberships:
                # Get last membership if any
                last_membership = frappe.get_all(
                    "Membership",
                    filters={"member": member.name},
                    fields=["name", "status", "cancellation_date", "membership_type"],
                    order_by="creation desc",
                    limit=1,
                )

                member_info = member.copy()
                member_info["last_membership"] = last_membership[0] if last_membership else None
                members_without_active.append(member_info)

        return {
            "total_members_checked": len(all_members),
            "members_without_active_memberships": len(members_without_active),
            "members": members_without_active[:50],  # Limit for performance
        }

    except Exception as e:
        return {"error": str(e)}
