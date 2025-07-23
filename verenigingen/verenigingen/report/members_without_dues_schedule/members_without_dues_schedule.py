# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    summary = get_report_summary(data, filters)
    chart = get_chart_data(data)
    return columns, data, None, chart, summary


def get_columns():
    return [
        _("Member ID") + ":Link/Member:120",
        _("Member Name") + ":Data:180",
        _("Email") + ":Data:200",
        _("Member Status") + ":Data:100",
        _("Customer") + ":Link/Customer:120",
        _("Member Since") + ":Date:100",
        _("Dues Schedule Status") + ":HTML:120",
        _("Last Invoice Date") + ":Date:100",
        _("Next Invoice Date") + ":Date:100",
        _("Days Overdue") + ":Int:80",
        _("Billing Frequency") + ":Data:100",
        _("Dues Rate") + ":Currency:100",
        _("Coverage Gap") + ":HTML:120",
        _("Recent Invoices") + ":Int:80",
        _("Action Required") + ":HTML:150",
    ]


def get_data(filters=None):
    """Get all active members and analyze their dues schedule status"""

    if not filters:
        filters = {}

    # Build member filters - default to Active members only
    member_filters = {"docstatus": ["!=", 2]}

    # If specific member status is requested, use that
    if filters.get("member_status"):
        member_filters["status"] = filters.get("member_status")
    else:
        # Default behavior: only show Active members, with options to include others
        excluded_statuses = []

        # Always exclude Terminated unless explicitly included
        if not filters.get("include_terminated"):
            excluded_statuses.append("Terminated")

        # Always exclude Suspended unless explicitly included
        if not filters.get("include_suspended"):
            excluded_statuses.append("Suspended")

        # Always exclude Pending unless explicitly included (since they shouldn't have schedules)
        if not filters.get("include_pending"):
            excluded_statuses.append("Pending")

        if excluded_statuses:
            member_filters["status"] = ["not in", excluded_statuses]
        else:
            # If all statuses are included, don't filter by status
            pass

    # Get all members
    members = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=["name", "full_name", "email", "status", "customer", "member_since"],
        order_by="member_since desc",
    )

    if not members:
        return []

    data = []
    today_date = getdate(today())

    for member in members:
        if not member.customer:
            continue

        # Get dues schedule information
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
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

        # Get recent invoices count
        recent_invoices_count = frappe.db.count(
            "Sales Invoice",
            filters={
                "customer": member.customer,
                "posting_date": [">=", frappe.utils.add_days(today(), -30)],
                "docstatus": ["!=", 2],
            },
        )

        # Analyze schedule status
        if not schedules:
            # No active dues schedule
            row = {
                "member_id": member.name,
                "member_name": member.full_name,
                "email": member.email,
                "member_status": member.status,
                "customer": member.customer,
                "member_since": member.member_since,
                "dues_schedule_status": '<span class="indicator red">No Schedule</span>',
                "last_invoice_date": None,
                "next_invoice_date": None,
                "days_overdue": 0,
                "billing_frequency": None,
                "dues_rate": None,
                "coverage_gap": '<span class="indicator red">No Coverage</span>',
                "recent_invoices": recent_invoices_count,
                "action_required": '<span class="indicator red">Create Schedule</span>',
            }
            data.append(row)
            continue

        # Analyze existing schedule
        schedule = schedules[0]
        days_overdue = 0

        if schedule.next_invoice_date:
            next_date = getdate(schedule.next_invoice_date)
            if next_date < today_date:
                days_overdue = date_diff(today_date, next_date)

        # Determine status and actions
        schedule_status = "Active"
        status_color = "green"
        coverage_gap = "Active"
        gap_color = "green"
        action_required = "None"
        action_color = "green"

        if days_overdue > 14:
            schedule_status = "Critical"
            status_color = "red"
            coverage_gap = f"Critical Gap ({days_overdue} days)"
            gap_color = "red"
            action_required = "Urgent Fix Required"
            action_color = "red"
        elif days_overdue > 7:
            schedule_status = "Overdue"
            status_color = "orange"
            coverage_gap = f"Gap ({days_overdue} days)"
            gap_color = "orange"
            action_required = "Fix Overdue"
            action_color = "orange"
        elif days_overdue > 0:
            schedule_status = "Behind"
            status_color = "yellow"
            coverage_gap = f"Minor Gap ({days_overdue} days)"
            gap_color = "yellow"
            action_required = "Check Schedule"
            action_color = "yellow"
        elif not schedule.get("auto_generate", True):
            schedule_status = "Manual"
            status_color = "blue"
            coverage_gap = "Manual Mode"
            gap_color = "blue"
            action_required = "Monitor"
            action_color = "blue"

        # Apply filters for problematic schedules only
        if filters.get("problems_only"):
            if days_overdue == 0 and schedule.get("auto_generate", True):
                continue  # Skip healthy schedules

        if filters.get("critical_only"):
            if days_overdue <= 7:
                continue  # Skip non-critical

        row = {
            "member_id": member.name,
            "member_name": member.full_name,
            "email": member.email,
            "member_status": member.status,
            "customer": member.customer,
            "member_since": member.member_since,
            "dues_schedule_status": f'<span class="indicator {status_color}">{schedule_status}</span>',
            "last_invoice_date": schedule.last_invoice_date,
            "next_invoice_date": schedule.next_invoice_date,
            "days_overdue": days_overdue,
            "billing_frequency": schedule.billing_frequency,
            "dues_rate": schedule.dues_rate,
            "coverage_gap": f'<span class="indicator {gap_color}">{coverage_gap}</span>',
            "recent_invoices": recent_invoices_count,
            "action_required": f'<span class="indicator {action_color}">{action_required}</span>',
        }
        data.append(row)

    # Sort by priority: no schedule first, then by days overdue descending
    data.sort(key=lambda x: (0 if "No Schedule" in x["dues_schedule_status"] else 1, -x["days_overdue"]))

    return data


def get_report_summary(data, filters=None):
    """Generate comprehensive summary statistics"""
    if not data:
        return []

    total_members = len(data)
    no_schedule = len([d for d in data if "No Schedule" in d["dues_schedule_status"]])
    critical_issues = len([d for d in data if d["days_overdue"] > 14])
    overdue_issues = len([d for d in data if 0 < d["days_overdue"] <= 14])
    healthy_schedules = len(
        [d for d in data if d["days_overdue"] == 0 and "Active" in d["dues_schedule_status"]]
    )

    # Calculate estimated financial impact
    total_overdue_amount = 0
    for row in data:
        if row["days_overdue"] > 0 and row["dues_rate"]:
            rate = float(row["dues_rate"] or 0)
            days = row["days_overdue"]
            billing_freq = row["billing_frequency"] or "Daily"

            if billing_freq == "Daily":
                total_overdue_amount += rate * days
            elif billing_freq == "Weekly":
                total_overdue_amount += rate * (days / 7)
            elif billing_freq == "Monthly":
                total_overdue_amount += rate * (days / 30)

    return [
        {"value": total_members, "label": _("Total Members Analyzed"), "datatype": "Int"},
        {
            "value": no_schedule,
            "label": _("Members Without Schedule"),
            "datatype": "Int",
            "color": "red" if no_schedule > 0 else "green",
        },
        {
            "value": critical_issues,
            "label": _("Critical Issues (>14 days)"),
            "datatype": "Int",
            "color": "red" if critical_issues > 0 else "green",
        },
        {
            "value": overdue_issues,
            "label": _("Overdue Issues (1-14 days)"),
            "datatype": "Int",
            "color": "orange" if overdue_issues > 0 else "green",
        },
        {"value": healthy_schedules, "label": _("Healthy Schedules"), "datatype": "Int", "color": "green"},
        {
            "value": total_overdue_amount,
            "label": _("Estimated Overdue Amount"),
            "datatype": "Currency",
            "color": "red"
            if total_overdue_amount > 100
            else "orange"
            if total_overdue_amount > 0
            else "green",
        },
    ]


def get_chart_data(data):
    """Generate chart showing schedule status distribution"""
    if not data:
        return None

    status_counts = {"No Schedule": 0, "Critical": 0, "Overdue": 0, "Behind": 0, "Active": 0, "Manual": 0}

    for row in data:
        status_html = row["dues_schedule_status"]
        if "No Schedule" in status_html:
            status_counts["No Schedule"] += 1
        elif "Critical" in status_html:
            status_counts["Critical"] += 1
        elif "Overdue" in status_html:
            status_counts["Overdue"] += 1
        elif "Behind" in status_html:
            status_counts["Behind"] += 1
        elif "Manual" in status_html:
            status_counts["Manual"] += 1
        elif "Active" in status_html:
            status_counts["Active"] += 1

    # Filter out zero values
    filtered_counts = {k: v for k, v in status_counts.items() if v > 0}

    return {
        "data": {
            "labels": list(filtered_counts.keys()),
            "datasets": [{"name": _("Member Count"), "values": list(filtered_counts.values())}],
        },
        "type": "pie",
        "colors": ["#ff4757", "#ff6348", "#ffa502", "#fffa65", "#2ed573", "#70a1ff"],
    }


@frappe.whitelist()
def fix_member_schedule_issues(member_list):
    """API function to batch fix member schedule issues or create missing memberships/schedules"""
    try:
        if isinstance(member_list, str):
            import json

            member_list = json.loads(member_list)

        results = []
        from verenigingen.api.test_fixes import fix_schedule_dates

        # Get default membership type for new schedules
        default_membership_type = frappe.db.get_value(
            "Membership Type",
            {"is_active": 1, "default_for_new_members": 1},
            ["name", "minimum_amount", "billing_period"],
        )

        if not default_membership_type:
            # Fallback to first active membership type
            default_membership_type = frappe.db.get_value(
                "Membership Type", {"is_active": 1}, ["name", "minimum_amount", "billing_period"]
            )

        for member_id in member_list:
            try:
                # Check if member exists and is active
                member_doc = frappe.get_doc("Member", member_id)

                # Only process active members - skip pending applicants and others
                if member_doc.status != "Active":
                    results.append(
                        {
                            "member": member_id,
                            "success": False,
                            "message": f"Member status is '{member_doc.status}' - only Active members can have schedules created",
                        }
                    )
                    continue

                if not member_doc.customer:
                    results.append(
                        {"member": member_id, "success": False, "message": "Member has no customer record"}
                    )
                    continue

                # Double-check for existing schedules with a fresh query to avoid race conditions
                schedules = frappe.get_all(
                    "Membership Dues Schedule",
                    filters={"member": member_id, "status": "Active"},
                    fields=["name"],
                    limit=1,
                )

                if schedules:
                    # Member has schedule - fix the dates
                    fix_result = fix_schedule_dates(schedules[0].name)
                    results.append(
                        {
                            "member": member_id,
                            "schedule": schedules[0].name,
                            "success": fix_result.get("success", False),
                            "message": f"Fixed existing schedule: {fix_result.get('message', 'Unknown result')}",
                        }
                    )
                else:
                    # Final check before creating - ensure no schedule exists
                    final_check = frappe.db.exists(
                        "Membership Dues Schedule", {"member": member_id, "status": "Active"}
                    )
                    if final_check:
                        results.append(
                            {
                                "member": member_id,
                                "success": False,
                                "message": f"Schedule already exists: {final_check}. Skipping creation.",
                            }
                        )
                    else:
                        # Member has no schedule - create membership and schedule
                        create_result = _create_membership_and_schedule(
                            member_id, member_doc, default_membership_type
                        )
                        results.append(create_result)

            except Exception as e:
                results.append({"member": member_id, "success": False, "message": str(e)})

        success_count = len([r for r in results if r["success"]])

        return {
            "success": True,
            "total_processed": len(member_list),
            "success_count": success_count,
            "results": results,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _create_membership_and_schedule(member_id, member_doc, default_membership_type):
    """Helper function to create membership and dues schedule for a member"""
    try:
        from frappe.utils import add_months, today

        # Check if member already has an active membership
        existing_membership = frappe.get_all(
            "Membership",
            filters={"member": member_id, "status": "Active", "docstatus": 1},
            fields=["name"],
            limit=1,
        )

        membership_name = None
        if existing_membership:
            membership_name = existing_membership[0].name
        else:
            # Check for any existing membership that could be activated
            any_membership = frappe.get_all(
                "Membership",
                filters={"member": member_id, "docstatus": ["!=", 2]},
                fields=["name", "status", "docstatus"],
                limit=1,
            )

            if any_membership and any_membership[0].docstatus == 0:
                # Update and submit existing draft membership
                try:
                    membership = frappe.get_doc("Membership", any_membership[0].name)
                    membership.status = "Active"
                    membership.start_date = today()
                    membership.renewal_date = add_months(today(), 12)
                    membership.save()
                    membership.submit()
                    membership_name = membership.name
                except frappe.TimestampMismatchError:
                    return {
                        "member": member_id,
                        "success": False,
                        "message": "Membership document was modified by another process during update",
                    }
            else:
                # Create new membership
                try:
                    membership = frappe.new_doc("Membership")
                    membership.member = member_id
                    membership.membership_type = (
                        default_membership_type[0] if default_membership_type else "Maandlid"
                    )
                    membership.start_date = today()
                    membership.renewal_date = add_months(today(), 12)  # 1 year from now
                    membership.status = "Active"  # Changed from "Current" to "Active"
                    membership.save()
                    membership.submit()  # Submit to make docstatus = 1
                    membership_name = membership.name
                except frappe.TimestampMismatchError:
                    return {
                        "member": member_id,
                        "success": False,
                        "message": "Membership creation failed due to document modification conflict",
                    }

        # Create dues schedule using the default membership type settings
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = (
            f"Auto-{member_id}-{default_membership_type[2] if default_membership_type else 'Monthly'}"
        )
        schedule.member = member_id
        schedule.membership = membership_name
        schedule.membership_type = (
            default_membership_type[0] if default_membership_type else "Maandlid"
        )  # Required field
        schedule.status = "Active"  # Required field

        # Use the billing frequency from the default membership type
        schedule.billing_frequency = (
            default_membership_type[2] if default_membership_type else "Monthly"
        )  # Required field
        schedule.currency = "EUR"  # Required field

        # Use the amount from the default membership type, but convert to appropriate rate
        if default_membership_type:
            base_amount = float(default_membership_type[1])
            billing_freq = default_membership_type[2]

            # Convert annual amount to appropriate billing frequency rate
            if billing_freq == "Annual":
                schedule.dues_rate = base_amount
            elif billing_freq == "Monthly":
                schedule.dues_rate = base_amount / 12  # Convert annual to monthly
            elif billing_freq == "Quarterly":
                schedule.dues_rate = base_amount / 4  # Convert annual to quarterly
            elif billing_freq == "Daily":
                schedule.dues_rate = base_amount / 365  # Convert annual to daily
            else:
                schedule.dues_rate = base_amount  # Use as-is for other frequencies
        else:
            # Fallback if no default membership type found
            schedule.dues_rate = 3.0  # €3 annual as fallback

        schedule.auto_generate = 1
        schedule.next_invoice_date = today()

        # Add final existence check before saving to prevent duplicates
        existing_schedule = frappe.db.exists(
            "Membership Dues Schedule", {"member": member_id, "status": "Active"}
        )

        if existing_schedule:
            return {
                "member": member_id,
                "success": False,
                "message": f"Schedule already exists: {existing_schedule}. Another process may have created it.",
            }

        # Save with retry logic for document modification conflicts
        max_retries = 3
        for attempt in range(max_retries):
            try:
                schedule.save()
                break  # Success, exit retry loop
            except frappe.TimestampMismatchError:
                if attempt == max_retries - 1:
                    return {
                        "member": member_id,
                        "success": False,
                        "message": "Document modification conflict after multiple retries",
                    }
                # Wait a moment and retry
                import time

                time.sleep(0.1 * (attempt + 1))
                # Reload the schedule document to get fresh timestamps
                schedule = frappe.get_doc(schedule.as_dict())
            except Exception as e:
                if "already has an active dues schedule" in str(e):
                    return {
                        "member": member_id,
                        "success": False,
                        "message": f"Schedule creation prevented: {str(e)}",
                    }
                raise  # Re-raise other exceptions

        # Calculate display rate for user feedback
        display_rate = schedule.dues_rate
        freq_display = schedule.billing_frequency.lower()
        if schedule.billing_frequency == "Annual":
            display_text = f"€{display_rate:.2f}/year"
        elif schedule.billing_frequency == "Monthly":
            display_text = f"€{display_rate:.2f}/month"
        elif schedule.billing_frequency == "Quarterly":
            display_text = f"€{display_rate:.2f}/quarter"
        elif schedule.billing_frequency == "Daily":
            display_text = f"€{display_rate:.2f}/day"
        else:
            display_text = f"€{display_rate:.2f}/{freq_display}"

        return {
            "member": member_id,
            "membership": membership_name,
            "schedule": schedule.name,
            "success": True,
            "message": f"Created membership and {schedule.billing_frequency.lower()} schedule ({display_text})",
        }

    except Exception as e:
        return {
            "member": member_id,
            "success": False,
            "message": f"Failed to create membership/schedule: {str(e)}",
        }
