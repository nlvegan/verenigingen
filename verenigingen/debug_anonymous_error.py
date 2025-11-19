"""Debug the anonymous column error"""

import frappe


def debug_anonymous_error():
    """Reproduce and debug the anonymous column error"""
    print("=== DEBUGGING ANONYMOUS COLUMN ERROR ===")

    try:
        # Try to find any campaigns
        campaigns = frappe.get_all("Donation Campaign", limit=1)
        if not campaigns:
            print("No campaigns found")
            return

        campaign_name = campaigns[0].name
        print(f"Testing with campaign: {campaign_name}")

        # Get the campaign and try to update progress
        campaign = frappe.get_doc("Donation Campaign", campaign_name)
        print(f"Campaign loaded: {campaign.campaign_name}")

        print("Attempting to update progress...")
        campaign.update_progress()
        print("✓ Progress updated successfully")

    except Exception as e:
        print(f"❌ Error occurred: {str(e)}")

        # Check if this is the anonymous column error
        if "Unknown column 'anonymous'" in str(e):
            print("🔍 This is the anonymous column error!")

            # Try to debug the SQL query
            print("Checking what query might be causing this...")

            # Try a direct query to see if we can reproduce
            try:
                donations = frappe.get_all(
                    "Donation",
                    filters={"campaign": campaign_name, "paid": 1, "docstatus": 1},
                    fields=["name", "amount", "donor"],
                )
                print(f"✓ Direct donation query worked, found {len(donations)} donations")
            except Exception as query_error:
                print(f"❌ Direct query failed: {str(query_error)}")

        import traceback

        traceback.print_exc()

    return True
