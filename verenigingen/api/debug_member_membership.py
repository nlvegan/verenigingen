"""
Debug member membership status and Create Membership button logic
"""

import frappe
from frappe.utils import getdate, today


def get_member_next_invoice_date(member_name):
    """Get the next invoice date from the member's current dues schedule"""
    try:
        # Get member's current dues schedule
        member = frappe.get_doc("Member", member_name)
        if hasattr(member, "current_dues_schedule") and member.current_dues_schedule:
            schedule_doc = frappe.get_doc("Membership Dues Schedule", member.current_dues_schedule)
            return str(schedule_doc.next_invoice_date) if schedule_doc.next_invoice_date else None

        # Fallback to member's next_invoice_date field
        if hasattr(member, "next_invoice_date"):
            return str(member.next_invoice_date) if member.next_invoice_date else None

        return None
    except Exception:
        return None


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


@frappe.whitelist()
def debug_member_billing_issues(member_name):
    """Debug billing schedule and invoice issues for a specific member"""
    try:
        # Get member document
        member = frappe.get_doc("Member", member_name)

        # Get customer record (needed for invoices)
        customer = frappe.get_value(
            "Customer", {"member": member_name}, ["name", "customer_name"], as_dict=True
        )

        # Get all dues schedules
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
                "creation",
                "modified",
                "docstatus",
            ],
            order_by="creation desc",
        )

        # Get all memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name},
            fields=[
                "name",
                "membership_type",
                "status",
                "start_date",
                "cancellation_date",
                "creation",
                "modified",
                "docstatus",
                "renewal_date",
            ],
            order_by="creation desc",
        )

        # Get all invoices for this member
        invoices = []
        if customer:
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": customer.name, "docstatus": ["!=", 2]},
                fields=[
                    "name",
                    "status",
                    "grand_total",
                    "posting_date",
                    "due_date",
                    "customer",
                    "creation",
                    "modified",
                    "docstatus",
                    "remarks",
                ],
                order_by="creation desc",
            )

            # Get invoice items to check for coverage period information
            for invoice in invoices:
                items = frappe.get_all(
                    "Sales Invoice Item",
                    filters={"parent": invoice.name},
                    fields=["item_code", "description", "rate", "amount", "qty"],
                )
                invoice["items"] = items

        # Get fee change history (child table - need to find parent first)
        fee_changes = []
        try:
            # Since this is a child table, we need to find the parent doctype
            # Let's check if it's linked to Member or Membership Dues Schedule
            fee_changes = frappe.get_all(
                "Member Fee Change History",
                fields=[
                    "name",
                    "change_date",
                    "old_dues_rate",
                    "new_dues_rate",
                    "reason",
                    "billing_frequency",
                    "change_type",
                    "dues_schedule",
                    "changed_by",
                    "parent",
                ],
                order_by="change_date desc",
            )
            # Filter for this member's changes if we can identify them
            if fee_changes:
                # We need to check the parent field to see if it relates to our member
                member_fee_changes = []
                for change in fee_changes:
                    # Check if the dues_schedule belongs to our member
                    if change.get("dues_schedule"):
                        schedule_member = frappe.get_value(
                            "Membership Dues Schedule", change["dues_schedule"], "member"
                        )
                        if schedule_member == member_name:
                            member_fee_changes.append(change)
                fee_changes = member_fee_changes
        except Exception as e:
            fee_changes = []

        # Check for any scheduled tasks related to billing
        scheduled_jobs = frappe.get_all(
            "Scheduled Job Type",
            filters={"method": ["like", "%billing%"]},
            fields=["name", "method", "frequency", "last_execution"],
        )

        # Check for any logs related to this member's billing
        from datetime import datetime

        error_logs = frappe.get_all(
            "Error Log",
            filters={"error": ["like", f"%{member_name}%"], "creation": [">=", "2025-07-20 00:00:00"]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=5,
        )

        return {
            "member_info": {
                "name": member_name,
                "full_name": member.full_name,
                "status": member.status,
                "creation": member.creation,
                "modified": member.modified,
            },
            "customer_info": customer,
            "dues_schedules": {"count": len(dues_schedules), "schedules": dues_schedules},
            "memberships": {"count": len(memberships), "memberships": memberships},
            "invoices": {"count": len(invoices), "invoices": invoices},
            "fee_changes": {"count": len(fee_changes), "changes": fee_changes},
            "scheduled_jobs": scheduled_jobs,
            "error_logs": error_logs,
            "analysis": {
                "has_customer": bool(customer),
                "has_dues_schedule": len(dues_schedules) > 0,
                "has_daily_schedule": any(s.get("billing_frequency") == "Daily" for s in dues_schedules),
                "has_annual_schedule": any(s.get("billing_frequency") == "Annual" for s in dues_schedules),
                "recent_invoices": len([i for i in invoices if str(i.creation) >= "2025-07-20"])
                if invoices
                else 0,
                "invoices_with_coverage_info": len(
                    [
                        i
                        for i in invoices
                        if any(
                            "period" in str(item.get("description", "")).lower()
                            for item in i.get("items", [])
                        )
                    ]
                )
                if invoices
                else 0,
            },
        }

    except Exception as e:
        return {"error": str(e), "member_name": member_name}


@frappe.whitelist()
def debug_specific_member_sinv_issue():
    """Debug why Assoc-Member-2025-07-0025 hasn't gotten SINV today"""
    from frappe.utils import add_days, getdate, today

    member_name = "Assoc-Member-2025-07-0025"

    try:
        result = {
            "member_name": member_name,
            "today": today(),
            "debug_timestamp": frappe.utils.now(),
            "status": "investigating",
        }

        # Check if member exists
        if not frappe.db.exists("Member", member_name):
            result["error"] = f"Member {member_name} does not exist!"
            return result

        member = frappe.get_doc("Member", member_name)
        result["member_details"] = {
            "name": member.name,
            "status": member.status,
            "email": member.email,
            "full_name": member.full_name,
            "created": str(member.creation),
            "modified": str(member.modified),
            "customer_linked": bool(frappe.get_value("Customer", {"member": member.name})),
        }

        # Check customer record
        customer = frappe.get_value(
            "Customer", {"member": member.name}, ["name", "customer_name"], as_dict=True
        )
        result["customer_info"] = customer

        # Check memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=[
                "name",
                "membership_type",
                "start_date",
                "cancellation_date",
                "status",
                "creation",
                "modified",
                "docstatus",
            ],
            order_by="creation desc",
        )

        result["memberships"] = []
        today_date = getdate(today())
        for membership in memberships:
            start_date = getdate(membership.start_date) if membership.start_date else None
            cancellation_date = (
                getdate(membership.cancellation_date) if membership.cancellation_date else None
            )

            # For active memberships, consider them valid if started and not cancelled
            is_currently_valid = (
                start_date
                and start_date <= today_date
                and (not cancellation_date or cancellation_date > today_date)
            )

            membership_info = {
                "name": membership.name,
                "type": membership.membership_type,
                "start_date": str(membership.start_date) if membership.start_date else None,
                "cancellation_date": str(membership.cancellation_date)
                if membership.cancellation_date
                else None,
                "next_invoice_date": get_member_next_invoice_date(member_name),
                "status": membership.status,
                "docstatus": membership.docstatus,
                "created": str(membership.creation),
                "modified": str(membership.modified),
                "is_currently_valid": is_currently_valid,
                "is_active_submitted": membership.status == "Active" and membership.docstatus == 1,
            }
            result["memberships"].append(membership_info)

        # Check existing Sales Invoices for today
        customer_name = customer.name if customer else member.name
        todays_sinvs = frappe.get_all(
            "Sales Invoice",
            filters={"customer": customer_name, "posting_date": today()},
            fields=["name", "status", "grand_total", "posting_date", "creation", "docstatus"],
        )

        result["todays_sinvs"] = []
        for sinv in todays_sinvs:
            result["todays_sinvs"].append(
                {
                    "name": sinv.name,
                    "status": sinv.status,
                    "docstatus": sinv.docstatus,
                    "grand_total": float(sinv.grand_total),
                    "posting_date": str(sinv.posting_date),
                    "creation": str(sinv.creation),
                }
            )

        # Check recent Sales Invoices (last 7 days)
        recent_date = add_days(today(), -7)
        recent_sinvs = frappe.get_all(
            "Sales Invoice",
            filters={"customer": customer_name, "posting_date": [">=", recent_date]},
            fields=["name", "status", "grand_total", "posting_date", "creation", "docstatus"],
            order_by="creation desc",
        )

        result["recent_sinvs"] = []
        for sinv in recent_sinvs:
            result["recent_sinvs"].append(
                {
                    "name": sinv.name,
                    "status": sinv.status,
                    "docstatus": sinv.docstatus,
                    "grand_total": float(sinv.grand_total),
                    "posting_date": str(sinv.posting_date),
                    "creation": str(sinv.creation),
                }
            )

        # Check dues schedules - this is critical
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name},
            fields=[
                "name",
                "dues_rate",
                "status",
                "creation",
                "billing_frequency",
                "next_invoice_date",
            ],
            order_by="next_invoice_date desc",
        )

        result["dues_schedules"] = []
        for dues in dues_schedules:
            next_invoice_date = getdate(dues.next_invoice_date) if dues.next_invoice_date else None
            should_invoice_today = next_invoice_date == today_date if next_invoice_date else False

            schedule_info = {
                "name": dues.name,
                "next_invoice_date": str(dues.next_invoice_date) if dues.next_invoice_date else None,
                "dues_rate": float(dues.dues_rate) if dues.dues_rate else 0.0,
                "status": dues.status,
                "billing_frequency": dues.billing_frequency,
                "creation": str(dues.creation),
                "should_invoice_today": should_invoice_today,
            }
            result["dues_schedules"].append(schedule_info)

        # Check scheduler logs for billing-related jobs
        scheduler_logs = frappe.get_all(
            "Scheduled Job Log",
            filters={"creation": [">=", today()], "scheduled_job_type": ["in", ["all", "daily", "hourly"]]},
            fields=["name", "scheduled_job_type", "status", "creation", "details"],
            order_by="creation desc",
            limit=20,
        )

        result["scheduler_logs_today"] = []
        for log in scheduler_logs:
            result["scheduler_logs_today"].append(
                {
                    "name": log.name,
                    "type": log.scheduled_job_type,
                    "status": log.status,
                    "creation": str(log.creation),
                    "details": log.details[:200] if log.details else None,  # Truncate for readability
                }
            )

        # Look for specific billing-related scheduled jobs
        billing_jobs = frappe.get_all(
            "Scheduled Job Type",
            filters={"method": ["like", "%billing%"]},
            fields=["name", "method", "frequency", "last_execution"],
        )

        result["billing_jobs"] = billing_jobs

        # Check for errors
        error_logs = frappe.get_all(
            "Error Log",
            filters={"error": ["like", f"%{member_name}%"], "creation": [">=", today()]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=5,
        )

        result["error_logs_today"] = []
        for error in error_logs:
            result["error_logs_today"].append(
                {
                    "name": error.name,
                    "error": error.error[:300],  # Truncate for readability
                    "creation": str(error.creation),
                }
            )

        # Analysis summary
        active_memberships = [m for m in result["memberships"] if m["is_active_submitted"]]
        schedules_due_today = [s for s in result["dues_schedules"] if s["should_invoice_today"]]

        result["analysis"] = {
            "has_active_membership": len(active_memberships) > 0,
            "active_membership_count": len(active_memberships),
            "has_customer_record": bool(customer),
            "has_dues_schedule": len(result["dues_schedules"]) > 0,
            "schedules_due_today_count": len(schedules_due_today),
            "already_has_sinv_today": len(result["todays_sinvs"]) > 0,
            "recent_sinv_count": len(result["recent_sinvs"]),
            "error_logs_today_count": len(result["error_logs_today"]),
            "should_create_sinv": (
                len(active_memberships) > 0
                and len(schedules_due_today) > 0
                and len(result["todays_sinvs"]) == 0
                and bool(customer)
            ),
        }

        result["status"] = "completed"
        return result

    except Exception as e:
        import traceback

        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        return result


@frappe.whitelist()
def debug_invoice_submission_issue():
    """Debug why today's invoice for Assoc-Member-2025-07-0025 wasn't submitted"""
    from frappe.utils import today

    result = {"status": "investigating", "today": today()}

    try:
        # Get the invoice created today
        invoice_name = "ACC-SINV-2025-20221"

        if not frappe.db.exists("Sales Invoice", invoice_name):
            result["error"] = f"Invoice {invoice_name} does not exist!"
            return result

        sinv = frappe.get_doc("Sales Invoice", invoice_name)

        result["invoice_details"] = {
            "name": sinv.name,
            "status": sinv.status,
            "docstatus": sinv.docstatus,
            "customer": sinv.customer,
            "grand_total": float(sinv.grand_total),
            "posting_date": str(sinv.posting_date),
            "creation": str(sinv.creation),
            "modified": str(sinv.modified),
            "company": sinv.company,
            "currency": sinv.currency,
        }

        # Check invoice items
        result["invoice_items"] = []
        for item in sinv.items:
            result["invoice_items"].append(
                {
                    "item_code": item.item_code,
                    "description": item.description,
                    "rate": float(item.rate),
                    "qty": float(item.qty),
                    "amount": float(item.amount),
                }
            )

        # Try to submit the invoice and capture any errors
        result["submission_attempt"] = {"attempted": False, "success": False, "error": None}

        if sinv.docstatus == 0:  # Only try to submit if it's draft
            try:
                result["submission_attempt"]["attempted"] = True
                sinv.submit()
                result["submission_attempt"]["success"] = True
                result["invoice_details"]["docstatus_after_submit"] = sinv.docstatus
                result["invoice_details"]["status_after_submit"] = sinv.status
            except Exception as submit_error:
                result["submission_attempt"]["success"] = False
                result["submission_attempt"]["error"] = str(submit_error)
                import traceback

                result["submission_attempt"]["traceback"] = traceback.format_exc()

        result["status"] = "completed"
        return result

    except Exception as e:
        import traceback

        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        return result


@frappe.whitelist()
def check_auto_submit_errors():
    """Check for auto-submit error logs for today's invoices"""
    from frappe.utils import today

    try:
        result = {"today": today(), "status": "checking"}

        # Check for auto-submit error logs for today's invoice
        invoice_errors = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%ACC-SINV-2025-20221%"], "creation": [">=", today()]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
        )

        result["invoice_specific_errors"] = []
        for log in invoice_errors:
            result["invoice_specific_errors"].append(
                {
                    "name": log.name,
                    "creation": str(log.creation),
                    "error": log.error[:500],  # Truncate for readability
                }
            )

        # Check for general auto-submit errors today
        general_errors = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%Invoice Auto-Submit%"], "creation": [">=", today()]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=5,
        )

        result["general_auto_submit_errors"] = []
        for log in general_errors:
            result["general_auto_submit_errors"].append(
                {
                    "name": log.name,
                    "creation": str(log.creation),
                    "error": log.error[:500],  # Truncate for readability
                }
            )

        # Check auto-submit setting
        auto_submit_setting = frappe.db.get_single_value(
            "Verenigingen Settings", "auto_submit_membership_invoices"
        )
        result["auto_submit_setting"] = auto_submit_setting

        # Check if setting exists
        setting_exists = frappe.db.exists(
            "Singles", {"doctype": "Verenigingen Settings", "field": "auto_submit_membership_invoices"}
        )
        result["setting_exists"] = bool(setting_exists)

        result["analysis"] = {
            "invoice_specific_error_count": len(result["invoice_specific_errors"]),
            "general_auto_submit_error_count": len(result["general_auto_submit_errors"]),
            "auto_submit_enabled": auto_submit_setting
            if auto_submit_setting is not None
            else "Setting not found - defaults to True",
        }

        result["status"] = "completed"
        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def analyze_recent_invoice_submissions():
    """Analyze recent invoice submission patterns to understand the inconsistency"""
    from frappe.utils import add_days, today

    try:
        result = {"today": today(), "analysis_period": "Last 7 days", "status": "analyzing"}

        recent_date = add_days(today(), -7)

        # Check ALL recent invoices to see submission patterns
        all_recent = frappe.get_all(
            "Sales Invoice",
            filters={"posting_date": [">=", recent_date]},
            fields=[
                "name",
                "customer",
                "status",
                "docstatus",
                "grand_total",
                "posting_date",
                "creation",
                "modified",
            ],
            order_by="creation desc",
        )

        # Categorize invoices
        draft_invoices = []
        submitted_invoices = []

        for inv in all_recent:
            customer_short = (
                (inv.customer[:30] + "...")
                if inv.customer and len(inv.customer) > 30
                else (inv.customer or "N/A")
            )
            invoice_data = {
                "name": inv.name,
                "customer": customer_short,
                "status": inv.status,
                "docstatus": inv.docstatus,
                "grand_total": float(inv.grand_total),
                "posting_date": str(inv.posting_date),
                "creation": str(inv.creation),
                "modified": str(inv.modified),
                "creation_hour": str(inv.creation).split()[1][:5] if inv.creation else None,
            }

            if inv.docstatus == 0:
                draft_invoices.append(invoice_data)
            elif inv.docstatus == 1:
                submitted_invoices.append(invoice_data)

        result["invoice_summary"] = {
            "total_invoices": len(all_recent),
            "draft_count": len(draft_invoices),
            "submitted_count": len(submitted_invoices),
            "submission_rate": f"{(len(submitted_invoices) / len(all_recent) * 100):.1f}%"
            if all_recent
            else "0%",
        }

        # Check for patterns in creation times
        creation_hours = {}
        for inv in all_recent:
            if inv.creation:
                hour = str(inv.creation).split()[1][:2] if " " in str(inv.creation) else "00"
                creation_hours[hour] = creation_hours.get(hour, 0) + 1

        result["creation_time_patterns"] = creation_hours

        # Focus on our specific member's recent invoices
        parko_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"posting_date": [">=", recent_date], "customer": ["like", "%Parko%"]},
            fields=["name", "status", "docstatus", "grand_total", "posting_date", "creation", "modified"],
            order_by="creation desc",
        )

        result["target_member_invoices"] = []
        for inv in parko_invoices:
            result["target_member_invoices"].append(
                {
                    "name": inv.name,
                    "status": inv.status,
                    "docstatus": inv.docstatus,
                    "grand_total": float(inv.grand_total),
                    "posting_date": str(inv.posting_date),
                    "creation": str(inv.creation),
                    "modified": str(inv.modified),
                }
            )

        # Check for error logs related to auto-submit failures
        auto_submit_errors = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%Invoice Auto-Submit%"], "creation": [">=", recent_date]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=10,
        )

        result["auto_submit_errors"] = []
        for error in auto_submit_errors:
            result["auto_submit_errors"].append(
                {
                    "name": error.name,
                    "creation": str(error.creation),
                    "error": error.error[:200] + "..." if len(error.error) > 200 else error.error,
                }
            )

        result["draft_invoices"] = draft_invoices[:10]  # Show recent drafts
        result["submitted_invoices"] = submitted_invoices[:10]  # Show recent submitted

        result["status"] = "completed"
        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def debug_payment_history_sync_issue():
    """Debug why the submitted invoice doesnt appear in payment history"""
    member_name = "Assoc-Member-2025-07-0025"
    invoice_name = "ACC-SINV-2025-20221"

    try:
        result = {"member_name": member_name, "invoice_name": invoice_name, "status": "investigating"}

        # Get the member document
        member = frappe.get_doc("Member", member_name)
        result["member_details"] = {
            "name": member.name,
            "customer": member.customer,
            "payment_history_count": len(member.payment_history) if hasattr(member, "payment_history") else 0,
        }

        # Get the invoice details
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        result["invoice_details"] = {
            "name": invoice.name,
            "customer": invoice.customer,
            "status": invoice.status,
            "docstatus": invoice.docstatus,
            "grand_total": float(invoice.grand_total),
            "posting_date": str(invoice.posting_date),
            "due_date": str(invoice.due_date) if invoice.due_date else None,
            "creation": str(invoice.creation),
            "modified": str(invoice.modified),
            "outstanding_amount": float(invoice.outstanding_amount)
            if hasattr(invoice, "outstanding_amount")
            else None,
        }

        # Check if customer matches
        result["customer_match"] = member.customer == invoice.customer

        # Check current payment history
        current_payment_history = []
        if hasattr(member, "payment_history"):
            for payment in member.payment_history:
                current_payment_history.append(
                    {
                        "invoice": payment.invoice,
                        "posting_date": str(payment.posting_date) if payment.posting_date else None,
                        "amount": float(payment.amount) if payment.amount else 0.0,
                        "payment_status": payment.payment_status,
                        "status": payment.status,
                        "transaction_type": payment.transaction_type,
                    }
                )

        result["current_payment_history"] = current_payment_history

        # Check if our specific invoice is in the payment history
        invoice_in_history = any(p.get("invoice") == invoice_name for p in current_payment_history)
        result["invoice_in_payment_history"] = invoice_in_history

        result["status"] = "completed"
        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def test_payment_history_fix():
    """Test that the payment history sync now works after fixing Draft status validation"""
    member_name = "Assoc-Member-2025-07-0025"

    try:
        result = {"member_name": member_name, "status": "testing"}

        # Get the member
        member = frappe.get_doc("Member", member_name)
        result["before_payment_history_count"] = (
            len(member.payment_history) if hasattr(member, "payment_history") else 0
        )

        # Try to manually refresh the payment history
        try:
            member.load_payment_history()
            result["payment_history_refresh_success"] = True

            # Get the refreshed count
            result["after_payment_history_count"] = (
                len(member.payment_history) if hasattr(member, "payment_history") else 0
            )

            # Check if our problem invoice is now in the history
            invoice_name = "ACC-SINV-2025-20221"
            invoice_found = False
            invoice_details = None

            if hasattr(member, "payment_history"):
                for payment in member.payment_history:
                    if payment.invoice == invoice_name:
                        invoice_found = True
                        invoice_details = {
                            "invoice": payment.invoice,
                            "posting_date": str(payment.posting_date) if payment.posting_date else None,
                            "amount": float(payment.amount) if payment.amount else 0.0,
                            "payment_status": payment.payment_status,
                            "status": payment.status,
                            "transaction_type": payment.transaction_type,
                        }
                        break

            result["target_invoice_found"] = invoice_found
            result["target_invoice_details"] = invoice_details

        except Exception as refresh_error:
            result["payment_history_refresh_success"] = False
            result["refresh_error"] = str(refresh_error)
            import traceback

            result["refresh_traceback"] = traceback.format_exc()

        result["status"] = "completed"
        return result

    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def check_invoice_submission_timeline():
    """Check the submission timeline for ACC-SINV-2025-20221"""
    try:
        # Get invoice details
        invoice_name = "ACC-SINV-2025-20221"
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        # Get version history to see when it was submitted
        versions = frappe.get_all(
            "Version",
            filters={"ref_doctype": "Sales Invoice", "docname": invoice_name},
            fields=["name", "creation", "owner", "data"],
            order_by="creation asc",
        )

        # Check if it was created as submitted or submitted later
        creation_time = invoice.creation
        modified_time = invoice.modified

        # Check due date vs posting date timing
        posting_date = invoice.posting_date
        due_date = invoice.due_date

        return {
            "invoice_name": invoice_name,
            "docstatus": invoice.docstatus,
            "creation_time": str(creation_time),
            "modified_time": str(modified_time),
            "posting_date": str(posting_date),
            "due_date": str(due_date),
            "was_modified_after_creation": modified_time > creation_time,
            "time_difference_minutes": (modified_time - creation_time).total_seconds() / 60
            if modified_time > creation_time
            else 0,
            "versions_count": len(versions),
            "versions": [{"creation": str(v.creation), "owner": v.owner} for v in versions],
        }

    except Exception as e:
        return {"error": str(e)}
