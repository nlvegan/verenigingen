import frappe

from verenigingen.tests.fixtures.billing_transition_personas import BillingTransitionPersonas
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def run_personas_in_reverse():
    """Run billing transition personas manually in reverse order"""

    # Reverse order of persona creation
    personas = [
        "backdated_betty",
        "mid_period_switch_sam",
        "daily_to_annual_diana",
        "quarterly_to_monthly_quinn",
        "annual_to_quarterly_anna",
        "monthly_to_annual_mike",
    ]

    results = {}

    for persona_name in personas:
        frappe.logger().info(f"Creating {persona_name}")
        try:
            if persona_name == "backdated_betty":
                persona_data = BillingTransitionPersonas.create_backdated_change_betty()
            elif persona_name == "mid_period_switch_sam":
                persona_data = BillingTransitionPersonas.create_mid_period_switch_sam()
            elif persona_name == "daily_to_annual_diana":
                persona_data = BillingTransitionPersonas.create_daily_to_annual_diana()
            elif persona_name == "quarterly_to_monthly_quinn":
                persona_data = BillingTransitionPersonas.create_quarterly_to_monthly_quinn()
            elif persona_name == "annual_to_quarterly_anna":
                persona_data = BillingTransitionPersonas.create_annual_to_quarterly_anna()
            elif persona_name == "monthly_to_annual_mike":
                persona_data = BillingTransitionPersonas.create_monthly_to_annual_mike()

            # Validate the created persona
            member = persona_data["member"]
            membership = persona_data["membership"]

            # Check if member has membership
            has_membership = frappe.db.exists("Membership", {"member": member.name})

            # Check if member has dues schedules
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member.name},
                fields=["name", "membership", "status", "billing_frequency"],
            )

            results[persona_name] = {
                "success": True,
                "member": member.name,
                "membership": membership.name if membership else None,
                "membership_exists": bool(has_membership),
                "dues_schedule_count": len(dues_schedules),
                "dues_schedules": dues_schedules,
                "status": "Created successfully",
            }

            # Check for orphaned data issue
            if len(dues_schedules) > 0 and not has_membership:
                results[persona_name]["warning"] = "Has dues schedule but no membership!"

        except Exception as e:
            results[persona_name] = {"success": False, "error": str(e), "status": f"Failed: {str(e)}"}

    return results
