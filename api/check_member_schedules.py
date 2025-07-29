import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def check_member_2910_schedules():
    """Check the dues schedules for member 2910"""
    member_name = "Assoc-Member-2025-07-2910"

    try:
        member = frappe.get_doc("Member", member_name)
        result = {
            "member": {
                "name": member.name,
                "full_name": f"{member.first_name} {member.last_name}",
                "email": member.email,
                "created": str(member.creation),
            },
            "schedules": [],
            "amendments": [],
        }

        # Check dues schedules
        schedules = frappe.db.sql(
            """
            SELECT name, status, billing_frequency, dues_rate, creation,
                   schedule_name, next_invoice_date, last_invoice_date
            FROM `tabMembership Dues Schedule`
            WHERE member = %s
            ORDER BY creation DESC
        """,
            member_name,
            as_dict=True,
        )

        for schedule in schedules:
            result["schedules"].append(
                {
                    "name": schedule.name,
                    "schedule_name": schedule.schedule_name,
                    "status": schedule.status,
                    "billing_frequency": schedule.billing_frequency,
                    "amount": float(schedule.dues_rate) if schedule.dues_rate else 0,
                    "next_invoice_date": str(schedule.next_invoice_date)
                    if schedule.next_invoice_date
                    else None,
                    "last_invoice_date": str(schedule.last_invoice_date)
                    if schedule.last_invoice_date
                    else None,
                    "created": str(schedule.creation),
                }
            )

        # Check for amendment requests
        amendments = frappe.db.sql(
            """
            SELECT name, status, amendment_type, current_billing_frequency,
                   requested_billing_frequency, creation, approved_date
            FROM `tabContribution Amendment Request`
            WHERE member = %s
            ORDER BY creation DESC
        """,
            member_name,
            as_dict=True,
        )

        for amendment in amendments:
            result["amendments"].append(
                {
                    "name": amendment.name,
                    "status": amendment.status,
                    "type": amendment.amendment_type,
                    "change": f"{amendment.current_billing_frequency} -> {amendment.requested_billing_frequency}",
                    "created": str(amendment.creation),
                    "approved": str(amendment.approved_date) if amendment.approved_date else None,
                }
            )

        # Check if this is a test member - improved pattern for development
        test_patterns = ["@test.com", "@example.com", "test@", "+test"]
        result["is_test_member"] = any(pattern in member.email.lower() for pattern in test_patterns)

        return result

    except frappe.DoesNotExistError:
        return {"error": f"Member {member_name} not found"}
    except frappe.ValidationError as e:
        return {"error": f"Validation error: {str(e)}"}
    except Exception as e:
        # Re-raise with more context for development debugging
        frappe.log_error(f"Unexpected error in check_member_2910_schedules: {str(e)}")
        raise
