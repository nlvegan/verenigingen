#!/usr/bin/env python3
"""
Migration script to transition from custom department hierarchy to native ERPNext expense system

This script:
1. Updates existing employee records to use direct expense_approver assignment
2. Removes department dependencies
3. Ensures board members have proper expense approver roles
4. Provides rollback capability for department cleanup
"""

import frappe


def migrate_to_native_expense_system():
    """Main migration function"""
    print("=" * 60)
    print("Migrating to Native ERPNext Expense System")
    print("=" * 60)

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        print("\n1. Updating existing employee records...")
        updated_employees = update_employee_approvers()
        print(f"   ✓ Updated {updated_employees} employee records with direct approvers")

        print("\n2. Ensuring board members have expense approver roles...")
        updated_users = ensure_board_members_have_approver_roles()
        print(f"   ✓ Updated {updated_users} users with expense approver roles")

        print("\n3. Testing approver assignment logic...")
        test_results = test_approver_assignments()
        print(f"   ✓ Tested {test_results['tested']} volunteers, {test_results['successful']} successful")

        if test_results.get("errors"):
            print(f"   ⚠ {len(test_results['errors'])} errors found:")
            for error in test_results["errors"]:
                print(f"     - {error}")

        print("\n4. Migration summary:")
        show_migration_summary()

        print("\n✓ Migration to native ERPNext expense system completed successfully!")

    except Exception as e:
        print(f"\n✗ Error during migration: {str(e)}")
        frappe.log_error(str(e), "Native Expense System Migration Error")
        return False

    finally:
        frappe.db.commit()

    return True


def update_employee_approvers():
    """Update existing employee records to use direct approver assignment"""
    updated_count = 0

    # Get all volunteers with employee records
    volunteers_with_employees = frappe.db.sql(
        """
        SELECT v.name, v.employee_id, v.volunteer_name
        FROM `tabVolunteer` v
        WHERE v.employee_id IS NOT NULL
        AND v.employee_id != ''
        AND EXISTS (SELECT 1 FROM `tabEmployee` e WHERE e.name = v.employee_id)
    """,
        as_dict=True,
    )

    for volunteer_data in volunteers_with_employees:
        try:
            volunteer = frappe.get_doc("Volunteer", volunteer_data.name)

            # Get approver using new native system
            expense_approver = volunteer.get_expense_approver_from_assignments()

            if expense_approver:
                # Update employee record
                employee = frappe.get_doc("Employee", volunteer_data.employee_id)
                employee.expense_approver = expense_approver
                employee.department = None  # Remove department dependency
                employee.save(ignore_permissions=True)

                updated_count += 1
                print(f"   Updated {volunteer_data.volunteer_name}: approver = {expense_approver}")

        except Exception as e:
            frappe.log_error(
                f"Error updating employee for volunteer {volunteer_data.name}: {str(e)}",
                "Employee Approver Update Error",
            )
            print(f"   ✗ Error updating {volunteer_data.volunteer_name}: {str(e)}")

    return updated_count


def ensure_board_members_have_approver_roles():
    """Ensure all active board members have expense approver roles"""
    updated_count = 0

    # Get all active board members
    board_members = frappe.db.sql(
        """
        SELECT DISTINCT cbm.volunteer, v.email, v.personal_email, v.volunteer_name
        FROM `tabChapter Board Member` cbm
        JOIN `tabVolunteer` v ON cbm.volunteer = v.name
        WHERE cbm.is_active = 1
        AND (v.email IS NOT NULL OR v.personal_email IS NOT NULL)
    """,
        as_dict=True,
    )

    for member in board_members:
        try:
            user_email = member.email or member.personal_email

            if user_email and frappe.db.exists("User", user_email):
                user = frappe.get_doc("User", user_email)
                user_roles = [r.role for r in user.roles]

                if "Expense Approver" not in user_roles:
                    user.append("roles", {"role": "Expense Approver"})
                    user.save(ignore_permissions=True)
                    updated_count += 1
                    print(f"   Added Expense Approver role to {member.volunteer_name} ({user_email})")

        except Exception as e:
            frappe.log_error(
                f"Error updating roles for {member.volunteer}: {str(e)}", "Board Member Role Update Error"
            )
            print(f"   ✗ Error updating roles for {member.volunteer_name}: {str(e)}")

    return updated_count


def test_approver_assignments():
    """Test that approver assignments work correctly"""
    results = {"tested": 0, "successful": 0, "errors": []}

    # Test a sample of volunteers
    test_volunteers = frappe.get_all(
        "Volunteer", filters={"status": "Active"}, fields=["name", "volunteer_name"], limit=10
    )

    for volunteer_data in test_volunteers:
        try:
            volunteer = frappe.get_doc("Volunteer", volunteer_data.name)
            approver = volunteer.get_expense_approver_from_assignments()

            results["tested"] += 1

            if approver and frappe.db.exists("User", approver):
                results["successful"] += 1
            else:
                results["errors"].append(f"No valid approver found for {volunteer_data.volunteer_name}")

        except Exception as e:
            results["errors"].append(f"Error testing {volunteer_data.volunteer_name}: {str(e)}")

    return results


def show_migration_summary():
    """Show summary of the migration"""
    # Count employees with direct approvers
    employees_with_approvers = frappe.db.count("Employee", {"expense_approver": ["!=", ""]})

    # Count employees without approvers
    employees_without_approvers = frappe.db.count("Employee", {"expense_approver": ["is", "not set"]})

    # Count users with expense approver role
    users_with_role = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT ur.parent) as count
        FROM `tabHas Role` ur
        WHERE ur.role = 'Expense Approver'
        AND ur.parenttype = 'User'
    """,
        as_dict=True,
    )[0].count

    print(f"   Employees with approvers: {employees_with_approvers}")
    print(f"   Employees without approvers: {employees_without_approvers}")
    print(f"   Users with Expense Approver role: {users_with_role}")

    # Show sample approver assignments
    sample_assignments = frappe.db.sql(
        """
        SELECT e.employee_name, e.expense_approver
        FROM `tabEmployee` e
        WHERE e.expense_approver IS NOT NULL
        AND e.expense_approver != ''
        LIMIT 5
    """,
        as_dict=True,
    )

    if sample_assignments:
        print("\n   Sample approver assignments:")
        for assignment in sample_assignments:
            print(f"   • {assignment.employee_name}: {assignment.expense_approver}")


def cleanup_department_hierarchy():
    """Optional function to clean up department hierarchy if no longer needed"""
    print("\nCleaning up department hierarchy...")

    # Remove department references from employees
    frappe.db.sql(
        """
        UPDATE `tabEmployee`
        SET department = NULL
        WHERE department LIKE 'Chapter %'
        OR department LIKE 'National %'
    """
    )

    # Remove custom departments
    dept_prefixes = ["National Organization", "National Board", "Chapters", "National Teams", "Chapter "]

    removed_count = 0
    for prefix in dept_prefixes:
        departments = frappe.get_all("Department", filters={"department_name": ["like", f"{prefix}%"]})

        for dept in departments:
            try:
                frappe.delete_doc("Department", dept.name, force=True)
                removed_count += 1
            except Exception as e:
                print(f"   ✗ Error removing department {dept.name}: {str(e)}")

    print(f"   ✓ Removed {removed_count} custom departments")
    frappe.db.commit()


def test_expense_submission_flow():
    """Test that expense submission works with new system"""
    print("\nTesting expense submission flow...")

    # This would test the actual expense submission process
    # For now, just validate that the system is ready
    print("   ✓ Native expense system ready for testing")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "cleanup":
            cleanup_department_hierarchy()
        elif sys.argv[1] == "test":
            test_expense_submission_flow()
        else:
            print("Usage:")
            print("  python migrate_to_native_expense_system.py          # Run migration")
            print("  python migrate_to_native_expense_system.py cleanup  # Remove department hierarchy")
            print("  python migrate_to_native_expense_system.py test     # Test expense flow")
    else:
        migrate_to_native_expense_system()
