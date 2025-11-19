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

        # Check table structure - modernized using Frappe meta
        try:
            meta = frappe.get_meta("Contribution Amendment Request")
            fields = meta.get_valid_columns()
            print(f"\nDocType structure - {len(fields)} fields found:")
            for field in fields[:10]:  # Show first 10 fields
                field_meta = meta.get_field(field)
                if field_meta:
                    print(f"  {field}: {field_meta.fieldtype}")
                else:
                    print(f"  {field}: Standard field")
            if len(fields) > 10:
                print(f"  ... and {len(fields) - 10} more fields")
        except Exception as e:
            print(f"Could not get DocType meta: {e}")

    except Exception as e:
        print(f"Error: {e}")

        # Check if DocType exists - modernized approach
        try:
            amendment_doctypes = frappe.get_all(
                "DocType",
                filters={"name": ["like", "%Amendment%"]},
                fields=["name", "module", "custom"]
            )
            print(f"Amendment-related DocTypes: {[dt['name'] for dt in amendment_doctypes]}")
        except Exception as e2:
            print(f"Error checking DocTypes: {e2}")


if __name__ == "__main__":
    check_amendment_records()
