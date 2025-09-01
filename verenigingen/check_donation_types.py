"""Check donation types and fix missing data"""

import frappe


def check_and_fix_donation_types():
    """Check existing donation types and create missing ones"""
    print("Checking donation types...")

    # Get all existing donation types
    donation_types = frappe.get_all("Donation Type", fields=["name", "donation_type"])
    print(f"Found {len(donation_types)} donation types:")
    for dt in donation_types:
        print(f"  - {dt.name}: {dt.donation_type}")

    # Check settings
    settings = frappe.get_single("Verenigingen Settings")
    print(f"\nSettings default_donation_type: {settings.default_donation_type}")

    # Create missing donation types if needed
    required_types = ["General", "Emergency", "Campaign", "Special"]

    for dt_name in required_types:
        if not frappe.db.exists("Donation Type", dt_name):
            print(f"\nCreating missing donation type: {dt_name}")
            dt_doc = frappe.new_doc("Donation Type")
            dt_doc.update(
                {"donation_type": dt_name, "description": f"{dt_name} donations for the organization"}
            )
            dt_doc.insert()
            print(f"✓ Created donation type: {dt_name}")
        else:
            print(f"✓ Donation type exists: {dt_name}")

    # Update settings if needed
    if not settings.default_donation_type:
        settings.default_donation_type = "General"
        settings.save()
        print("✓ Updated default donation type to 'General'")

    frappe.db.commit()
    print("\n✓ All donation types are now available")

    return True
