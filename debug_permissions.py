#!/usr/bin/env python3
import frappe


def debug_permissions():
    """Debug current permission system state"""
    frappe.init("dev.veganisme.net")
    frappe.connect()

    print("=== EXISTING TEST USERS ===")
    users = frappe.get_all(
        "User", filters={"email": ["like", "%unittest.test%"]}, fields=["email", "enabled"]
    )
    for user in users:
        print(f"User: {user.email}, Enabled: {user.enabled}")
        user_roles = frappe.get_roles(user.email)
        print(f"  Roles: {user_roles}")

    print()
    print("=== EXISTING TEST MEMBERS ===")
    members = frappe.get_all(
        "Member", filters={"email": ["like", "%unittest.test%"]}, fields=["name", "email", "user"]
    )
    for member in members:
        print(f"Member: {member.name}, Email: {member.email}, User: {member.user}")

    print()
    print("=== EXISTING TEST DONORS ===")
    donors = frappe.get_all(
        "Donor", filters={"donor_email": ["like", "%unittest.test%"]}, fields=["name", "donor_name", "member"]
    )
    for donor in donors:
        print(f"Donor: {donor.name}, Name: {donor.donor_name}, Member: {donor.member}")

    print()
    print("=== PERMISSION QUERY TEST ===")
    from verenigingen.permissions import get_donor_permission_query

    if users:
        test_user = users[0].email
        query = get_donor_permission_query(test_user)
        print(f"Permission query for {test_user}: {query}")

        # Test the query results
        frappe.set_user(test_user)
        try:
            accessible_donors = frappe.get_all(
                "Donor", fields=["name", "donor_name", "member"], ignore_permissions=False
            )
            print(f"Accessible donors for {test_user}: {len(accessible_donors)}")
            for donor in accessible_donors[:5]:  # Show first 5
                print(f"  - {donor.name}: {donor.donor_name} (member: {donor.member})")
        except Exception as e:
            print(f"Error getting accessible donors: {e}")

    # Test with admin
    frappe.set_user("Administrator")
    all_donors = frappe.get_all("Donor", fields=["name", "donor_name", "member"])
    print(f"Total donors in system: {len(all_donors)}")


if __name__ == "__main__":
    debug_permissions()
