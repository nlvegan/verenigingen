#!/usr/bin/env python3
"""
Create employee records for completed account creation requests that have users but no employees.

Usage:
    bench --site dev.veganisme.net execute verenigingen.utils.create_employees_for_requests.create_employees --args "['2025-10-29 19:00:00']"
"""

import frappe

from verenigingen.utils.account_creation_manager import AccountCreationManager


def create_employees(since_date):
    """Create employee records for requests that need them."""

    print(f"\n{'=' * 80}")
    print(f"CREATING EMPLOYEES FOR COMPLETED REQUESTS (since {since_date})")
    print("=" * 80)

    # First, set create_employee_record=1 on the requests
    updated = frappe.db.sql(
        """
        UPDATE `tabAccount Creation Request`
        SET create_employee_record = 1
        WHERE creation > %s
            AND status = 'Completed'
            AND created_user IS NOT NULL
            AND created_user != ''
            AND (created_employee IS NULL OR created_employee = '')
    """,
        (since_date,),
    )

    frappe.db.commit()

    print(f"Updated {updated} requests to have create_employee_record=1")

    # Find completed requests with users but no employees
    requests = frappe.db.sql(
        """
        SELECT
            acr.name,
            acr.source_record,
            acr.created_user,
            m.first_name,
            m.last_name,
            m.employee as current_employee
        FROM `tabAccount Creation Request` acr
        INNER JOIN `tabMember` m ON m.name = acr.source_record
        WHERE acr.creation > %s
            AND acr.status = 'Completed'
            AND acr.created_user IS NOT NULL
            AND acr.created_user != ''
            AND (acr.created_employee IS NULL OR acr.created_employee = '')
            AND (m.employee IS NULL OR m.employee = '')
    """,
        (since_date,),
        as_dict=True,
    )

    print(f"\nFound {len(requests)} requests needing employee creation")

    if not requests:
        print("✅ No employees need to be created!")
        return

    created_count = 0
    error_count = 0
    already_has_count = 0

    for idx, row in enumerate(requests, 1):
        try:
            # Create AccountCreationManager instance
            manager = AccountCreationManager(row.name)
            manager.load_request()

            # Populate created_user from the request (it's set during pipeline but we're running standalone)
            manager.created_user = manager.request.created_user

            # Use the manager's request doc to avoid timestamp conflicts
            request_doc = manager.request

            # Check if employee creation is needed
            if not manager.requires_employee_creation():
                print(f"  [{idx}/{len(requests)}] {row.source_record}: Employee not required, skipping")
                continue

            # Check if employee already exists for this user
            existing_employee = frappe.db.get_value("Employee", {"user_id": row.created_user}, "name")
            if existing_employee:
                print(
                    f"  [{idx}/{len(requests)}] {row.source_record}: Employee already exists ({existing_employee}), linking..."
                )

                # Link to member
                frappe.db.set_value(
                    "Member", row.source_record, "employee", existing_employee, update_modified=False
                )

                # Mark request as completed
                request_doc.mark_completed(user=row.created_user, employee=existing_employee)

                already_has_count += 1
                continue

            # Create employee
            print(
                f"  [{idx}/{len(requests)}] {row.source_record}: Creating employee for {row.first_name} {row.last_name}..."
            )

            manager.create_employee_record()

            if manager.created_employee:
                # Link employee to member
                frappe.db.set_value(
                    "Member", row.source_record, "employee", manager.created_employee, update_modified=False
                )

                # Mark request as completed (sets both status and pipeline_stage)
                request_doc.mark_completed(user=manager.created_user, employee=manager.created_employee)

                created_count += 1
                print(f"       ✅ Created employee: {manager.created_employee}")
            else:
                print("       ⚠️  Employee creation returned None")
                error_count += 1

            # Commit every 20 records
            if (idx % 20) == 0:
                frappe.db.commit()
                print(
                    f"\n  Progress: {created_count} created, {already_has_count} linked, {error_count} errors\n"
                )

        except Exception as e:
            print(f"  [{idx}/{len(requests)}] ❌ Error for {row.source_record}: {str(e)}")
            frappe.logger().error(f"Employee creation error for {row.name}: {str(e)}", exc_info=True)
            error_count += 1

    # Final commit
    frappe.db.commit()

    print(f"\n{'=' * 80}")
    print("RESULTS")
    print("=" * 80)
    print(f"✅ Employees created: {created_count}")
    print(f"🔗 Employees linked (already existed): {already_has_count}")
    print(f"❌ Errors: {error_count}")
    print(f"\n{'=' * 80}\n")

    # Show updated counts
    total_with_employee = frappe.db.count("Member", {"employee": ["!=", ""], "creation": [">", since_date]})
    total_members = frappe.db.count("Member", {"creation": [">", since_date]})

    print("Updated Stats:")
    print(
        f"  Members with employee records: {total_with_employee}/{total_members} ({total_with_employee / total_members * 100:.1f}%)"
    )


if __name__ == "__main__":
    create_employees("2025-10-29 19:00:00")
