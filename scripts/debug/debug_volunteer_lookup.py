#!/usr/bin/env python3

import frappe


def debug_volunteer_lookup(user_email=None):
    """Debug volunteer lookup for a specific user email"""

    if not user_email:
        user_email = frappe.session.user

    print(f"=== Debugging Volunteer Lookup for: {user_email} ===")

    # Check if user exists
    user_exists = frappe.db.exists("User", user_email)
    print(f"User exists: {user_exists}")

    # Check for Member record with this email
    member = frappe.db.get_value(
        "Member", {"email": user_email}, ["name", "first_name", "last_name", "email"], as_dict=True
    )
    if member:
        print(f"Found Member: {member.name} - {member.first_name} {member.last_name} ({member.email})")

        # Check for Volunteer linked to this member
        volunteer_by_member = frappe.db.get_value(
            "Volunteer", {"member": member.name}, ["name", "volunteer_name", "email", "member"], as_dict=True
        )
        if volunteer_by_member:
            print(
                f"Found Volunteer via Member: {volunteer_by_member.name} - {volunteer_by_member.volunteer_name}"
            )
            print(f"  Volunteer email: {volunteer_by_member.email}")
            print(f"  Linked member: {volunteer_by_member.member}")
        else:
            print("No Volunteer record linked to this Member")
    else:
        print("No Member record found with this email")

    # Check for Volunteer record with direct email match
    volunteer_direct = frappe.db.get_value(
        "Volunteer", {"email": user_email}, ["name", "volunteer_name", "email", "member"], as_dict=True
    )
    if volunteer_direct:
        print(
            f"Found Volunteer via direct email: {volunteer_direct.name} - {volunteer_direct.volunteer_name}"
        )
        print(f"  Volunteer email: {volunteer_direct.email}")
        print(f"  Linked member: {volunteer_direct.member}")
    else:
        print("No Volunteer record found with direct email match")

    # Check for similar email patterns
    print("\n=== Checking for similar emails ===")

    # Get all members with similar emails
    similar_members = frappe.db.sql(
        """
        SELECT name, first_name, last_name, email
        FROM `tabMember`
        WHERE email LIKE %s
        ORDER BY email
    """,
        f"%{user_email.split('@')[0]}%",
        as_dict=True,
    )

    if similar_members:
        print("Similar Member emails found:")
        for member in similar_members[:5]:  # Limit to 5 results
            print(f"  {member.name}: {member.first_name} {member.last_name} - {member.email}")

    # Get all volunteers with similar emails
    similar_volunteers = frappe.db.sql(
        """
        SELECT name, volunteer_name, email, member
        FROM `tabVolunteer`
        WHERE email LIKE %s
        ORDER BY email
    """,
        f"%{user_email.split('@')[0]}%",
        as_dict=True,
    )

    if similar_volunteers:
        print("Similar Volunteer emails found:")
        for volunteer in similar_volunteers[:5]:  # Limit to 5 results
            print(
                f"  {volunteer.name}: {volunteer.volunteer_name} - {volunteer.email} (member: {volunteer.member})"
            )

    return {
        "user_email": user_email,
        "user_exists": user_exists,
        "member": member,
        "volunteer_by_member": volunteer_by_member if member else None,
        "volunteer_direct": volunteer_direct,
        "similar_members": similar_members,
        "similar_volunteers": similar_volunteers,
    }


@frappe.whitelist()
def debug_current_user_volunteer_lookup():
    """Debug volunteer lookup for current user - can be called from web"""
    return debug_volunteer_lookup()


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Test with current session user
    result = debug_volunteer_lookup()
    print("\n=== Summary ===")
    print(f"User: {result['user_email']}")
    print(f"Has Member record: {'Yes' if result['member'] else 'No'}")
    print(f"Has Volunteer via Member: {'Yes' if result['volunteer_by_member'] else 'No'}")
    print(f"Has Volunteer via direct email: {'Yes' if result['volunteer_direct'] else 'No'}")

    frappe.destroy()
