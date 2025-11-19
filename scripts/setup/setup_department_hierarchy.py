#!/usr/bin/env python3
"""
Setup and migrate to department-based expense approver hierarchy

This script:
1. Creates department structure mirroring association hierarchy
2. Assigns departments to existing volunteer employees
3. Sets up expense approvers based on board positions
4. Provides rollback capability
"""

import frappe


def setup_department_hierarchy():
    """Main setup function"""
    print("=" * 60)
    print("Department Hierarchy Setup for Expense Approvals")
    print("=" * 60)

    # Initialize
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

        manager = DepartmentHierarchyManager()

        # Step 1: Create department structure
        print("\n1. Creating department hierarchy...")
        manager.setup_association_departments()
        print("   ✓ Department structure created")

        # Step 2: Show created departments
        print("\n2. Department structure created:")
        show_department_tree()

        # Step 3: Sync approvers
        print("\n3. Syncing expense approvers...")
        manager.sync_all_approvers()
        show_approvers_summary()

        # Step 4: Update existing employees
        print("\n4. Updating existing volunteer employees...")
        updated = manager.update_employee_departments()
        print(f"   ✓ Updated {updated} employee records with departments")

        # Step 5: Show migration summary
        print("\n5. Migration Summary:")
        show_migration_summary()

        print("\n✓ Department hierarchy setup completed successfully!")

    except Exception as e:
        print(f"\n✗ Error during setup: {str(e)}")
        frappe.log_error(str(e), "Department Hierarchy Setup Error")
        return False

    finally:
        frappe.db.commit()

    return True


def show_department_tree(parent=None, level=0):
    """Display department tree structure"""
    filters = {"company": frappe.defaults.get_global_default("company")}

    if parent:
        filters["parent_department"] = parent
    else:
        filters["parent_department"] = ["is", "not set"]

    departments = frappe.get_all(
        "Department", filters=filters, fields=["name", "department_name"], order_by="department_name"
    )

    for dept in departments:
        indent = "  " * level + ("└─ " if level > 0 else "")
        print(f"{indent}{dept.department_name}")

        # Show approvers for this department
        approvers = frappe.get_all(
            "Department Approver",
            filters={"parent": dept.name, "parentfield": "expense_approvers"},
            fields=["approver"],
        )

        if approvers:
            approver_names = [a.approver for a in approvers]
            print(f"{'  ' * (level + 1)}[Approvers: {', '.join(approver_names)}]")

        # Recursively show children
        show_department_tree(dept.name, level + 1)


def show_approvers_summary():
    """Show summary of expense approvers by department"""
    print("\n   Expense Approvers by Department:")

    departments_with_approvers = frappe.db.sql(
        """
        SELECT
            d.department_name,
            GROUP_CONCAT(da.approver) as approvers
        FROM `tabDepartment` d
        JOIN `tabDepartment Approver` da ON da.parent = d.name
        WHERE da.parentfield = 'expense_approvers'
        GROUP BY d.name
        ORDER BY d.department_name
    """,
        as_dict=True,
    )

    if departments_with_approvers:
        for dept in departments_with_approvers:
            print(f"   • {dept.department_name}: {dept.approvers}")
    else:
        print("   ⚠ No expense approvers configured yet")


def show_migration_summary():
    """Show summary of the migration"""
    # Count employees by department
    dept_summary = frappe.db.sql(
        """
        SELECT
            COALESCE(e.department, 'No Department') as department,
            COUNT(*) as employee_count
        FROM `tabEmployee` e
        JOIN `tabVolunteer` v ON v.employee_id = e.name
        GROUP BY e.department
        ORDER BY employee_count DESC
    """,
        as_dict=True,
    )

    print("\n   Employees by Department:")
    for dept in dept_summary:
        print(f"   • {dept.department}: {dept.employee_count} employees")

    # Show volunteers without employees
    volunteers_without_employees = frappe.db.count("Volunteer", {"employee_id": ["is", "not set"]})

    if volunteers_without_employees > 0:
        print(f"\n   ⚠ {volunteers_without_employees} volunteers without employee records")
        print("   → These volunteers won't be able to submit expenses until employee records are created")


def rollback_departments():
    """Rollback function to remove created departments"""
    print("\nRollback: Removing department hierarchy...")

    # Get all departments created by this system
    dept_prefixes = ["National Organization", "National Board", "Chapters", "National Teams", "Chapter "]

    for prefix in dept_prefixes:
        departments = frappe.get_all("Department", filters={"department_name": ["like", f"{prefix}%"]})

        for dept in departments:
            try:
                frappe.delete_doc("Department", dept.name, force=True)
                print(f"   ✓ Removed department: {dept.name}")
            except Exception as e:
                print(f"   ✗ Error removing {dept.name}: {str(e)}")

    frappe.db.commit()
    print("   Rollback completed")


def test_expense_approval_chain(volunteer_email):
    """Test the expense approval chain for a specific volunteer"""
    print(f"\nTesting expense approval chain for: {volunteer_email}")

    # Get volunteer
    volunteer = frappe.db.get_value(
        "Volunteer", {"email": volunteer_email}, ["name", "employee_id"], as_dict=True
    )

    if not volunteer:
        print("   ✗ Volunteer not found")
        return

    if not volunteer.employee_id:
        print("   ✗ Volunteer has no employee record")
        return

    # Get employee department
    employee = frappe.get_doc("Employee", volunteer.employee_id)
    print(f"   Employee: {employee.name}")
    print(f"   Department: {employee.department or 'None'}")

    employee_dept = getattr(employee, 'department', None)
    if employee_dept:
        # Check department approvers
        dept = frappe.get_doc("Department", employee_dept)

        dept_approvers = getattr(dept, 'expense_approvers', None)
        if dept_approvers and len(dept_approvers) > 0:
            print("   Direct approvers:")
            for approver in dept.expense_approvers:
                print(f"   • {approver.approver}")
        else:
            print("   No direct approvers in department")

            # Check parent department
            parent_dept_name = getattr(dept, 'parent_department', None)
            if parent_dept_name:
                parent_dept = frappe.get_doc("Department", parent_dept_name)
                print(f"   Parent department: {parent_dept.department_name}")

                parent_approvers = getattr(parent_dept, 'expense_approvers', None)
                if parent_approvers and len(parent_approvers) > 0:
                    print("   Parent department approvers:")
                    for approver in parent_dept.expense_approvers:
                        print(f"   • {approver.approver}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "rollback":
            rollback_departments()
        elif sys.argv[1] == "test" and len(sys.argv) > 2:
            test_expense_approval_chain(sys.argv[2])
        else:
            print("Usage:")
            print("  python setup_department_hierarchy.py          # Run setup")
            print("  python setup_department_hierarchy.py rollback # Remove departments")
            print("  python setup_department_hierarchy.py test email@example.com # Test approval chain")
    else:
        setup_department_hierarchy()
