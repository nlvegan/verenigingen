#!/usr/bin/env python3

import frappe

# Create a test region first
frappe.connect(site="dev.veganisme.net")

try:
    # Try to create a region if it doesn't exist
    if not frappe.db.exists("Region", "Test Region"):
        region = frappe.new_doc("Region")
        region.region_name = "Test Region"
        region.country = "Netherlands"
        region.insert()
        print("Created Test Region")
    else:
        print("Test Region already exists")

    print(f"Available regions: {[r.name for r in frappe.get_all('Region', limit=5)]}")

except Exception as e:
    print(f"Error: {e}")
    print("Trying to use existing regions...")
    try:
        regions = frappe.get_all("Region", limit=5)
        print(f"Available regions: {[r.name for r in regions]}")
        if regions:
            print(f"Using first available region: {regions[0].name}")
    except Exception as e2:
        print(f"No regions found: {e2}")
