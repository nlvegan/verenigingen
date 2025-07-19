# Run this in bench console
# bench --site dev.veganisme.net console

from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    check_migration_data_quality,
)

# Get or create a migration record
migrations = frappe.get_all("E-Boekhouden Migration", fields=["name", "migration_status", "company"], limit=1)

if migrations:
    migration_name = migrations[0]["name"]
    print(f"Testing quality check on: {migration_name}")
else:
    # Create a test migration
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        company = companies[0]["name"] if companies else "Test Company"

    migration = frappe.new_doc("E-Boekhouden Migration")
    migration.migration_name = "Quality Check Test"
    migration.company = company
    migration.migration_status = "Completed"
    migration.migrate_accounts = 1
    migration.migrate_transactions = 1
    migration.date_from = "2024-01-01"
    migration.date_to = "2024-12-31"
    migration.save()
    migration_name = migration.name
    print(f"Created test migration: {migration_name}")

# Test the quality check
result = check_migration_data_quality(migration_name)

if result["success"]:
    report = result["report"]
    print(f"\nQuality Report Summary:")
    print(f"  - Company: {report['company']}")
    print(f"  - Issues Found: {len(report['issues'])}")
    print(f"  - Statistics: {report['statistics']}")
    if report["issues"]:
        print("\nIssues:")
        for issue in report["issues"]:
            print(f"    - {issue['type']}: {issue['description']} ({issue.get('count', 0)} records)")
else:
    print(f"Quality check failed: {result.get('error', 'Unknown error')}")
