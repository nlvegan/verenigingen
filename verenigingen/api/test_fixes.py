#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def test_member_payment_history(member_id="Assoc-Member-2025-07-0020"):
    """Test payment history loading for a specific member"""

    try:
        member = frappe.get_doc("Member", member_id)

        # Clear existing payment history
        member.payment_history = []

        # Load payment history using the updated method
        member._load_payment_history_without_save()

        entries_details = []
        for entry in member.payment_history:
            entry_info = {
                "invoice": entry.invoice,
                "transaction_type": entry.transaction_type,
                "payment_status": entry.payment_status,
                "amount": float(entry.amount) if entry.amount else 0,
                "outstanding_amount": float(entry.outstanding_amount) if entry.outstanding_amount else 0,
                "posting_date": str(entry.posting_date),
            }
            entries_details.append(entry_info)

        return {
            "success": True,
            "member": member.name,
            "customer": member.customer,
            "entries": len(member.payment_history),
            "details": entries_details,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def submit_draft_invoice(invoice_name):
    """Submit a draft invoice"""

    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        if invoice.docstatus == 0:
            invoice.submit()
            return {"success": True, "message": f"Invoice {invoice.name} submitted successfully"}
        else:
            return {
                "success": True,
                "message": f"Invoice {invoice.name} was already submitted (docstatus: {invoice.docstatus})",
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def diagnose_dues_schedule_issue(member_id):
    """Diagnose dues schedule issues for a specific member"""

    try:
        # Get member's dues schedules
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_id, "status": "Active"},
            fields=[
                "name",
                "next_invoice_date",
                "last_invoice_date",
                "billing_frequency",
                "dues_rate",
                "modified",
            ],
        )

        if not schedules:
            return {"success": False, "error": f"No active dues schedules found for member {member_id}"}

        schedule_data = schedules[0]
        schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule_data["name"])

        # Get member's invoices
        member = frappe.get_doc("Member", member_id)
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer},
            fields=["name", "docstatus", "status", "posting_date", "grand_total"],
            order_by="posting_date desc",
        )

        # Calculate what the next_invoice_date should be
        from frappe.utils import add_days, today

        expected_next_date = None
        if schedule_doc.billing_frequency == "Daily":
            expected_next_date = add_days(schedule_doc.next_invoice_date, 1)
        elif schedule_doc.billing_frequency == "Weekly":
            expected_next_date = add_days(schedule_doc.next_invoice_date, 7)
        elif schedule_doc.billing_frequency == "Monthly":
            expected_next_date = add_days(schedule_doc.next_invoice_date, 30)

        return {
            "success": True,
            "member": member_id,
            "customer": member.customer,
            "schedule": {
                "name": schedule_doc.name,
                "next_invoice_date": str(schedule_doc.next_invoice_date),
                "last_invoice_date": str(schedule_doc.last_invoice_date)
                if schedule_doc.last_invoice_date
                else None,
                "billing_frequency": schedule_doc.billing_frequency,
                "dues_rate": float(schedule_doc.dues_rate),
                "expected_next_date": str(expected_next_date) if expected_next_date else None,
                "today": today(),
                "is_overdue": str(schedule_doc.next_invoice_date) < today()
                if schedule_doc.next_invoice_date
                else False,
            },
            "invoices": [
                {
                    "name": inv.name,
                    "docstatus": inv.docstatus,
                    "status": inv.status,
                    "posting_date": str(inv.posting_date),
                    "amount": float(inv.grand_total),
                }
                for inv in invoices
            ],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_schedule_dates(schedule_name):
    """Fix schedule dates by calling update_schedule_dates"""

    try:
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        old_next = str(schedule.next_invoice_date) if schedule.next_invoice_date else None
        old_last = str(schedule.last_invoice_date) if schedule.last_invoice_date else None

        # Call the update method
        schedule.update_schedule_dates()

        return {
            "success": True,
            "message": f"Updated schedule dates for {schedule_name}",
            "old_next_date": old_next,
            "new_next_date": str(schedule.next_invoice_date),
            "old_last_date": old_last,
            "new_last_date": str(schedule.last_invoice_date),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_all_overdue_schedules():
    """Find all schedules that are overdue and should have updated dates"""

    try:
        from frappe.utils import getdate, today

        # Find all active schedules where next_invoice_date is in the past
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "auto_generate": 1},
            fields=[
                "name",
                "member",
                "next_invoice_date",
                "last_invoice_date",
                "billing_frequency",
                "dues_rate",
            ],
        )

        overdue_schedules = []
        today_date = getdate(today())

        for schedule_data in schedules:
            next_date = getdate(schedule_data.next_invoice_date) if schedule_data.next_invoice_date else None
            if next_date and next_date < today_date:
                # Check if there are draft invoices for this member's customer
                try:
                    member = frappe.get_doc("Member", schedule_data.member)
                except frappe.DoesNotExistError:
                    continue  # Skip orphaned schedules

                if member.customer:
                    draft_invoices = frappe.get_all(
                        "Sales Invoice",
                        filters={"customer": member.customer, "docstatus": 0},
                        fields=["name", "posting_date", "grand_total"],
                        order_by="posting_date desc",
                    )

                    overdue_schedules.append(
                        {
                            "schedule_name": schedule_data.name,
                            "member": schedule_data.member,
                            "customer": member.customer,
                            "next_invoice_date": str(schedule_data.next_invoice_date),
                            "last_invoice_date": str(schedule_data.last_invoice_date)
                            if schedule_data.last_invoice_date
                            else None,
                            "billing_frequency": schedule_data.billing_frequency,
                            "days_overdue": (today_date - next_date).days,
                            "has_draft_invoices": len(draft_invoices) > 0,
                            "draft_invoices": [
                                {
                                    "name": inv.name,
                                    "posting_date": str(inv.posting_date),
                                    "amount": float(inv.grand_total),
                                }
                                for inv in draft_invoices
                            ],
                        }
                    )

        return {
            "success": True,
            "today": today(),
            "total_schedules": len(schedules),
            "overdue_count": len(overdue_schedules),
            "overdue_schedules": overdue_schedules,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_all_overdue_schedules():
    """Fix all overdue schedules by updating their dates"""

    try:
        # Get all overdue schedules first
        overdue_result = test_all_overdue_schedules()
        if not overdue_result["success"]:
            return overdue_result

        fixed_schedules = []
        errors = []

        for schedule_info in overdue_result["overdue_schedules"]:
            schedule_name = schedule_info["schedule_name"]

            try:
                # Fix the schedule dates
                fix_result = fix_schedule_dates(schedule_name)
                if fix_result["success"]:
                    fixed_schedules.append(
                        {
                            "schedule": schedule_name,
                            "member": schedule_info["member"],
                            "old_next_date": fix_result["old_next_date"],
                            "new_next_date": fix_result["new_next_date"],
                        }
                    )
                else:
                    errors.append(f"{schedule_name}: {fix_result['error']}")

            except Exception as e:
                errors.append(f"{schedule_name}: {str(e)}")

        return {
            "success": len(errors) == 0,
            "total_overdue": len(overdue_result["overdue_schedules"]),
            "fixed_count": len(fixed_schedules),
            "fixed_schedules": fixed_schedules,
            "errors": errors,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def analyze_invoice_coverage_gaps():
    """Comprehensive analysis of invoice coverage gaps and missing invoices"""

    try:
        from frappe.utils import add_days, date_diff, getdate, today

        # Get all active daily billing schedules
        daily_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "billing_frequency": "Daily", "auto_generate": 1},
            fields=["name", "member", "next_invoice_date", "last_invoice_date", "dues_rate", "modified"],
        )

        today_date = getdate(today())
        coverage_analysis = {
            "analysis_date": today(),
            "total_daily_schedules": len(daily_schedules),
            "schedules_with_gaps": [],
            "healthy_schedules": [],
            "critical_gaps": [],
            "summary": {},
        }

        for schedule_data in daily_schedules:
            try:
                # Skip orphaned schedules
                try:
                    member = frappe.get_doc("Member", schedule_data.member)
                except frappe.DoesNotExistError:
                    continue

                if not member.customer:
                    continue

                schedule = {
                    "schedule_name": schedule_data.name,
                    "member": schedule_data.member,
                    "customer": member.customer,
                    "next_invoice_date": str(schedule_data.next_invoice_date),
                    "last_invoice_date": str(schedule_data.last_invoice_date)
                    if schedule_data.last_invoice_date
                    else None,
                    "dues_rate": float(schedule_data.dues_rate),
                }

                # Calculate expected vs actual coverage
                if schedule_data.last_invoice_date and schedule_data.next_invoice_date:
                    last_date = getdate(schedule_data.last_invoice_date)
                    next_date = getdate(schedule_data.next_invoice_date)

                    # For daily billing, last_invoice_date and next_invoice_date should be consecutive days
                    expected_gap = 1  # 1 day between invoices
                    actual_gap = date_diff(next_date, last_date)

                    schedule["expected_gap_days"] = expected_gap
                    schedule["actual_gap_days"] = actual_gap
                    schedule["gap_variance"] = actual_gap - expected_gap

                    # Check if next_invoice_date is in the past (overdue)
                    days_overdue = date_diff(today_date, next_date)
                    schedule["days_overdue"] = days_overdue if days_overdue > 0 else 0

                    # Get recent invoices for this customer
                    recent_invoices = frappe.get_all(
                        "Sales Invoice",
                        filters={
                            "customer": member.customer,
                            "posting_date": [">=", add_days(today(), -30)],  # Last 30 days
                        },
                        fields=["name", "posting_date", "docstatus", "status", "grand_total"],
                        order_by="posting_date desc",
                    )

                    schedule["recent_invoices_count"] = len(recent_invoices)
                    schedule["recent_invoices"] = [
                        {
                            "name": inv.name,
                            "posting_date": str(inv.posting_date),
                            "docstatus": inv.docstatus,
                            "status": inv.status,
                            "amount": float(inv.grand_total),
                        }
                        for inv in recent_invoices[:5]  # Last 5 invoices
                    ]

                    # Determine if this schedule has issues
                    has_issues = False
                    issues = []

                    if actual_gap > expected_gap:
                        has_issues = True
                        issues.append(f"Gap too large: {actual_gap} days instead of {expected_gap}")

                    if days_overdue > 0:
                        has_issues = True
                        issues.append(f"Overdue by {days_overdue} days")

                    # Check for missing invoices based on expected daily pattern
                    if schedule_data.last_invoice_date:
                        expected_invoices_count = date_diff(today_date, last_date)
                        if expected_invoices_count > len(recent_invoices) and expected_invoices_count > 1:
                            has_issues = True
                            issues.append(
                                f"Missing invoices: expected ~{expected_invoices_count}, found {len(recent_invoices)}"
                            )

                    schedule["has_issues"] = has_issues
                    schedule["issues"] = issues

                    if has_issues:
                        if days_overdue > 7 or actual_gap > 7:  # Critical: more than a week
                            coverage_analysis["critical_gaps"].append(schedule)
                        else:
                            coverage_analysis["schedules_with_gaps"].append(schedule)
                    else:
                        coverage_analysis["healthy_schedules"].append(schedule)

            except Exception as e:
                # Skip individual schedule errors
                continue

        # Generate summary statistics
        coverage_analysis["summary"] = {
            "healthy_count": len(coverage_analysis["healthy_schedules"]),
            "gap_count": len(coverage_analysis["schedules_with_gaps"]),
            "critical_count": len(coverage_analysis["critical_gaps"]),
            "total_with_issues": len(coverage_analysis["schedules_with_gaps"])
            + len(coverage_analysis["critical_gaps"]),
            "health_percentage": round(
                (len(coverage_analysis["healthy_schedules"]) / max(len(daily_schedules), 1)) * 100, 1
            ),
        }

        return {"success": True, "coverage_analysis": coverage_analysis}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_member_next_invoice_display(member_name):
    """Get comprehensive next invoice date information for a specific member"""

    try:
        # Get member's dues schedule
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active"},
            fields=[
                "name",
                "next_invoice_date",
                "last_invoice_date",
                "billing_frequency",
                "dues_rate",
                "auto_generate",
            ],
            order_by="modified desc",
        )

        if not schedules:
            return {"success": True, "has_schedule": False, "message": "No active dues schedule found"}

        schedule_data = schedules[0]
        from frappe.utils import date_diff, getdate, today

        result = {
            "success": True,
            "has_schedule": True,
            "schedule_name": schedule_data.name,
            "next_invoice_date": str(schedule_data.next_invoice_date),
            "last_invoice_date": str(schedule_data.last_invoice_date)
            if schedule_data.last_invoice_date
            else None,
            "billing_frequency": schedule_data.billing_frequency,
            "dues_rate": float(schedule_data.dues_rate),
            "auto_generate": bool(schedule_data.auto_generate),
            "today": today(),
        }

        # Calculate status information
        if schedule_data.next_invoice_date:
            next_date = getdate(schedule_data.next_invoice_date)
            today_date = getdate(today())
            days_until_next = date_diff(next_date, today_date)

            result["days_until_next"] = days_until_next
            result["is_overdue"] = days_until_next < 0
            result["days_overdue"] = abs(days_until_next) if days_until_next < 0 else 0

            if days_until_next < 0:
                result["status"] = "Overdue"
                result["status_color"] = "red"
            elif days_until_next == 0:
                result["status"] = "Due Today"
                result["status_color"] = "orange"
            elif days_until_next <= 3:
                result["status"] = "Due Soon"
                result["status_color"] = "yellow"
            else:
                result["status"] = "Scheduled"
                result["status_color"] = "green"

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_member_next_invoice_date(member_name):
    """Update the next_invoice_date field on a member record"""

    try:
        # Get the member document
        member_doc = frappe.get_doc("Member", member_name)

        # Get dues schedule details
        from verenigingen.verenigingen.doctype.member.member import get_current_dues_schedule_details

        schedule_details = get_current_dues_schedule_details(member_name)

        if schedule_details.get("has_schedule") and schedule_details.get("next_invoice_date"):
            # Update the next_invoice_date field
            member_doc.next_invoice_date = schedule_details["next_invoice_date"]
            member_doc.save(ignore_permissions=True)

            return {
                "success": True,
                "message": f"Updated next invoice date to {schedule_details['next_invoice_date']}",
                "next_invoice_date": str(schedule_details["next_invoice_date"]),
            }
        else:
            # Clear the field if no schedule
            member_doc.next_invoice_date = None
            member_doc.save(ignore_permissions=True)

            return {
                "success": True,
                "message": "Cleared next invoice date (no active schedule)",
                "next_invoice_date": None,
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_member_dues_schedule():
    """Debug why the member with dues schedule is not appearing"""

    # Check specific member
    target_member = "Assoc-Member-2025-07-1943"

    result = {"debug": f"Debugging member: {target_member}"}

    # 1. Check if member exists and has customer
    member = frappe.db.get_value(
        "Member", target_member, ["name", "full_name", "status", "customer"], as_dict=True
    )
    result["member_data"] = member

    if not member or not member.customer:
        result["error"] = "Member not found or has no customer"
        return result

    # 2. Check if member has dues schedule
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"member": target_member, "status": "Active"},
        fields=[
            "name",
            "next_invoice_date",
            "last_invoice_date",
            "billing_frequency",
            "dues_rate",
            "auto_generate",
        ],
        order_by="modified desc",
        limit=1,
    )
    result["schedules_found"] = schedules

    # 3. Test the filtering logic from the report
    member_filters = {"docstatus": ["!=", 2]}
    # Apply standard filters (same as report)
    member_filters["status"] = ["not in", ["Terminated", "Suspended"]]

    result["filters"] = member_filters

    # 4. Get members using same logic as report
    members = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=["name", "full_name", "email", "status", "customer", "member_since"],
        order_by="member_since desc",
    )

    # Find our target member
    target_found = [m for m in members if m.name == target_member]
    result["target_found"] = len(target_found) > 0
    if target_found:
        result["target_data"] = target_found[0]

    # 5. Check total members returned
    result["total_members"] = len(members)

    # 6. Check members with schedules (sample first 5)
    members_with_schedules = []
    for member in members[:5]:
        schedules_check = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
            fields=["name"],
            limit=1,
        )
        if schedules_check:
            members_with_schedules.append({"member": member.name, "schedule": schedules_check[0].name})

    result["members_with_schedules_sample"] = members_with_schedules

    return result


@frappe.whitelist()
def test_report_with_schedules_first():
    """Test the report but show members with schedules first to verify it's working"""

    try:
        from verenigingen.verenigingen.report.members_without_dues_schedule.members_without_dues_schedule import (
            get_data,
        )

        # Get data with no filters
        filters = {"problems_only": 0}
        data = get_data(filters)

        # Sort to show members WITH schedules first (reverse the normal sort)
        data_with_schedules_first = sorted(
            data,
            key=lambda x: (
                1 if "No Schedule" in x["dues_schedule_status"] else 0,  # Reverse order
                -x["days_overdue"],
            ),
        )

        # Return first 10 members to see if we get ones with schedules
        sample = data_with_schedules_first[:10]

        return {
            "success": True,
            "total_members": len(data),
            "sample_size": len(sample),
            "sample": sample,
            "members_with_schedules": len(
                [m for m in data if "No Schedule" not in m["dues_schedule_status"]]
            ),
            "members_without_schedules": len([m for m in data if "No Schedule" in m["dues_schedule_status"]]),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
