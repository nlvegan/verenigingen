#!/usr/bin/env python3
"""
Admin and Diagnostic Utilities for Verenigingen

This file contains reusable functions for diagnosing and fixing
common issues with dues schedules, invoices, and member data.
All functions are whitelisted for CLI debugging access.
"""

import frappe


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
def find_members_without_schedules():
    """Find members who have no active dues schedules"""
    try:
        # Get all active members
        members = frappe.get_all(
            "Member",
            filters={"docstatus": ["!=", 2], "status": ["not in", ["Terminated", "Suspended"]]},
            fields=["name", "full_name", "customer"],
            limit=10,
        )

        members_without_schedules = []
        for member in members:
            if not member.customer:
                continue

            schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member.name, "status": "Active"},
                fields=["name"],
                limit=1,
            )

            if not schedules:
                members_without_schedules.append(
                    {
                        "member": member.name,
                        "full_name": member.full_name,
                        "has_customer": bool(member.customer),
                    }
                )

        return {
            "success": True,
            "total_checked": len(members),
            "without_schedules": len(members_without_schedules),
            "members": members_without_schedules,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_default_membership_type_logic():
    """Test the default membership type logic for schedule creation"""
    try:
        # Get default membership type (same logic as the fix function)
        default_membership_type = frappe.db.get_value(
            "Membership Type",
            {"is_active": 1, "default_for_new_members": 1},
            ["name", "amount", "billing_frequency"],
        )

        if not default_membership_type:
            # Fallback to first active membership type
            default_membership_type = frappe.db.get_value(
                "Membership Type", {"is_active": 1}, ["name", "amount", "billing_frequency"]
            )

        # Calculate what the dues rate would be
        calculated_rate = None
        display_text = None

        if default_membership_type:
            base_amount = float(default_membership_type[1])
            billing_freq = default_membership_type[2]

            # Convert annual amount to appropriate billing frequency rate
            if billing_freq == "Annual":
                calculated_rate = base_amount
                display_text = f"€{calculated_rate:.2f}/year"
            elif billing_freq == "Monthly":
                calculated_rate = base_amount / 12
                display_text = f"€{calculated_rate:.2f}/month"
            elif billing_freq == "Quarterly":
                calculated_rate = base_amount / 4
                display_text = f"€{calculated_rate:.2f}/quarter"
            elif billing_freq == "Daily":
                calculated_rate = base_amount / 365
                display_text = f"€{calculated_rate:.2f}/day"
            else:
                calculated_rate = base_amount
                display_text = f"€{calculated_rate:.2f}/{billing_freq.lower()}"

        return {
            "success": True,
            "default_membership_type": {
                "name": default_membership_type[0] if default_membership_type else None,
                "base_amount": float(default_membership_type[1]) if default_membership_type else None,
                "billing_frequency": default_membership_type[2] if default_membership_type else None,
            },
            "calculated_schedule": {
                "dues_rate": calculated_rate,
                "display_text": display_text,
                "billing_frequency": default_membership_type[2] if default_membership_type else "Monthly",
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
