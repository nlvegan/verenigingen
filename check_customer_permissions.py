#!/usr/bin/env python3
"""
Check Customer DocType permissions
"""

import frappe

frappe.init(site="dev.veganisme.net")
frappe.connect()

try:
    # Check Custom DocPerm for Customer
    custom_perms = frappe.db.sql(
        """
        SELECT role, `read`, `write`, `create`, `delete`
        FROM `tabCustom DocPerm`
        WHERE parent = 'Customer'
        ORDER BY role
    """,
        as_dict=True,
    )

    print("=== CUSTOM Customer Permissions ===")
    if custom_perms:
        for perm in custom_perms:
            print(
                f"Role: {perm['role']}, Read: {perm['read']}, Write: {perm['write']}, Create: {perm['create']}, Delete: {perm['delete']}"
            )
    else:
        print("No custom permissions found for Customer")

    # Check standard DocPerm for Customer
    std_perms = frappe.db.sql(
        """
        SELECT role, `read`, `write`, `create`, `delete`
        FROM `tabDocPerm`
        WHERE parent = 'Customer'
        ORDER BY role
    """,
        as_dict=True,
    )

    print("\n=== STANDARD Customer Permissions ===")
    if std_perms:
        for perm in std_perms:
            print(
                f"Role: {perm['role']}, Read: {perm['read']}, Write: {perm['write']}, Create: {perm['create']}, Delete: {perm['delete']}"
            )
    else:
        print("No standard permissions found for Customer")

    # Check if Verenigingen Administrator has Customer access
    print("\n=== Verenigingen Administrator Role Check ===")
    verenigingen_admin_perm = frappe.db.sql(
        """
        SELECT `read`, `write`, `create`, `delete`
        FROM `tabDocPerm`
        WHERE parent = 'Customer' AND role = 'Verenigingen Administrator'
    """,
        as_dict=True,
    )

    if verenigingen_admin_perm:
        perm = verenigingen_admin_perm[0]
        print(
            f"Verenigingen Administrator has: Read: {perm['read']}, Write: {perm['write']}, Create: {perm['create']}, Delete: {perm['delete']}"
        )
    else:
        print("Verenigingen Administrator has NO permissions on Customer DocType")

    # Check what roles have Customer read access
    print("\n=== Roles with Customer Read Access ===")
    customer_read_roles = frappe.db.sql(
        """
        SELECT DISTINCT role
        FROM `tabDocPerm`
        WHERE parent = 'Customer' AND `read` = 1
        ORDER BY role
    """
    )

    for role in customer_read_roles:
        print(f"- {role[0]}")

except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()

frappe.destroy()
