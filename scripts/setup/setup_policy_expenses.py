#!/usr/bin/env python3
"""
Set up policy-covered expense categories
"""

import frappe


def setup_policy_covered_expenses():
    """Mark appropriate expense categories as policy-covered"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    print("🔧 Setting up policy-covered expense categories...")

    # Categories that should be policy-covered (available to all volunteers)
    policy_categories = ["Travel", "Materials", "Office Supplies", "events"]

    updated_count = 0

    for category_name in policy_categories:
        try:
            # Check if category exists
            if frappe.db.exists("Expense Category", category_name):
                category_doc = frappe.get_doc("Expense Category", category_name)

                if not category_doc.policy_covered:
                    category_doc.policy_covered = 1
                    category_doc.save()
                    print(f"   ✅ Marked '{category_name}' as policy-covered")
                    updated_count += 1
                else:
                    print(f"   ✓ '{category_name}' already policy-covered")
            else:
                print(f"   ⚠️  Category '{category_name}' not found")

        except Exception as e:
            print(f"   ❌ Error updating '{category_name}': {str(e)}")

    print(f"\n📊 Summary:")
    print(f"   - Updated {updated_count} categories")
    print(f"   - Policy-covered categories allow all volunteers to submit national expenses")
    print(f"   - Non-policy categories require national board membership for national expenses")

    # Show current policy-covered categories
    policy_covered = frappe.get_all(
        "Expense Category", filters={"policy_covered": 1}, fields=["category_name"]
    )

    if policy_covered:
        print(f"\n✅ Current policy-covered categories:")
        for cat in policy_covered:
            print(f"   - {cat.category_name}")

    frappe.db.commit()
    frappe.destroy()


if __name__ == "__main__":
    setup_policy_covered_expenses()
