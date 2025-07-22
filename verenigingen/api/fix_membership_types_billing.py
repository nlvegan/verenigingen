import frappe


@frappe.whitelist()
def fix_membership_types_billing_frequency():
    """Fix membership types to have appropriate billing frequencies"""

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
                # Update the billing frequency
                frappe.db.set_value(
                    "Membership Type", membership_type, "billing_frequency", correct_frequency
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
            billing_frequency = frappe.db.get_value("Membership Type", mt_name, "billing_frequency")
            results.append({"name": mt_name, "billing_frequency": billing_frequency})

    return results
