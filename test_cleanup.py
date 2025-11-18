# Initialize Frappe
import os

import frappe

from verenigingen.utils.cleanup_duplicate_assignments import (
    clean_duplicate_assignments,
    find_duplicate_assignments,
)

os.chdir("/home/frappe/frappe-bench")
frappe.init(site="dev.veganisme.net")
frappe.connect()

try:
    # Check specific volunteer
    duplicates = find_duplicate_assignments("Assoc-Vol-2025-10-101174")
    if "Assoc-Vol-2025-10-101174" in duplicates:
        print("\n✓ Found duplicates for Assoc-Vol-2025-10-101174:")
        for dup_set in duplicates["Assoc-Vol-2025-10-101174"]:
            print(f"  - {dup_set['count']} duplicates of: {dup_set['key']}")
            print(f"    Indices: {dup_set['indices']}\n")

        # Clean up (dry run first)
        print("\nRunning cleanup (DRY RUN):")
        clean_duplicate_assignments("Assoc-Vol-2025-10-101174", dry_run=True)
    else:
        print("No duplicates found for Assoc-Vol-2025-10-101174")
finally:
    frappe.destroy()
