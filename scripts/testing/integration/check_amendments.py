#!/usr/bin/env python3

import frappe


def check_amendment_records():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Check if table exists
        count = frappe.db.count("Contribution Amendment Request")
        print(f"Total Contribution Amendment Request records: {count}")

        # Get sample records
        if count > 0:
            records = frappe.db.get_all(
                "Contribution Amendment Request",
                fields=["name", "status", "member", "amendment_type"],
                limit=5,
            )
            print("Sample records:")
            for record in records:
                print(f"  {record}")
        else:
            print("No records found")

        # Check table structure
        desc = frappe.db.sql("DESCRIBE `tabContribution Amendment Request`", as_dict=True)
        print(f"\nTable structure - {len(desc)} columns found:")
        for col in desc[:10]:  # Show first 10 columns
            print(f"  {col.Field}: {col.Type}")
        if len(desc) > 10:
            print(f"  ... and {len(desc) - 10} more columns")

    except Exception as e:
        print(f"Error: {e}")

        # Check if table exists at all
        try:
            tables = frappe.db.sql("SHOW TABLES LIKE '%Amendment%'", as_dict=True)
            print(f"Amendment-related tables: {tables}")
        except Exception as e2:
            print(f"Error checking tables: {e2}")


if __name__ == "__main__":
    check_amendment_records()
