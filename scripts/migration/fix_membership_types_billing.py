import frappe

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def fix_membership_types_billing_period():
    """Fix membership types to have appropriate billing periods"""

    # Define the correct billing frequencies for each membership type
    billing_fixes = {
        "Monthly Standard": "Monthly",
        "Annual Premium": "Annual",
        "Quarterly Basic": "Quarterly",
        "Daily Access": "Daily",
        "Annual Standard": "Annual",
        "Flexible Membership": "Monthly",  # Default to monthly for flexible
        "Annual Access": "Annual",
    }

    results = []
    for membership_type, correct_frequency in billing_fixes.items():
        if frappe.db.exists("Membership Type", membership_type):
            try:
                # Update the billing period
                frappe.db.set_value(
                    "Membership Type", membership_type, "billing_period", correct_frequency
                )
                results.append(
                    {"membership_type": membership_type, "updated_to": correct_frequency, "success": True}
                )
            except Exception as e:
                results.append({"membership_type": membership_type, "error": str(e), "success": False})
        else:
            results.append(
                {
                    "membership_type": membership_type,
                    "error": "Membership type does not exist",
                    "success": False,
                }
            )

    frappe.db.commit()
    return results


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def verify_membership_types_fixed():
    """Verify that membership types now have correct billing frequencies"""
    membership_types = [
        "Monthly Standard",
        "Annual Premium",
        "Quarterly Basic",
        "Daily Access",
        "Annual Standard",
        "Flexible Membership",
        "Annual Access",
    ]

    results = []
    for mt_name in membership_types:
        if frappe.db.exists("Membership Type", mt_name):
            billing_period = frappe.db.get_value("Membership Type", mt_name, "billing_period")
            results.append({"name": mt_name, "billing_period": billing_period})

    return results
