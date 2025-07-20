#!/usr/bin/env python3
"""
Test script to verify volunteer creation works when user account already exists
"""

import frappe
from frappe.utils import today


def test_volunteer_creation_with_existing_user():
    """Test that volunteer record can be created even when member has existing user account"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Find a member that has a user account but no volunteer record
        members_with_users = frappe.db.sql(
            """
            SELECT m.name, m.full_name, m.email, m.user
            FROM `tabMember` m
            WHERE m.user IS NOT NULL
            AND m.name NOT IN (
                SELECT v.member
                FROM `tabVolunteer` v
                WHERE v.member IS NOT NULL
            )
            LIMIT 1
        """,
            as_dict=True,
        )

        if not members_with_users:
            print("❌ No members found with user accounts but without volunteer records")

            # Let's create a test scenario instead
            print("Creating test scenario...")

            # Create a test member
            test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Test",
                    "last_name": "Volunteer Creation",
                    "email": f"test.volunteer.creation.{frappe.utils.random_string(5)}@example.com",
                    "contact_number": "+31612345678",
                    "payment_method": "Bank Transfer"}
            )
            test_member.insert(ignore_permissions=True)

            # Create a user account for this member
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": test_member.email,
                    "first_name": test_member.first_name,
                    "last_name": test_member.last_name,
                    "user_type": "Website User"}
            )
            user.insert(ignore_permissions=True)

            # Link user to member
            test_member.user = user.name
            test_member.save(ignore_permissions=True)

            print(f"✅ Created test member {test_member.name} with user account {user.name}")

            # Now test volunteer creation
            test_member_data = {
                "name": test_member.name,
                "full_name": test_member.full_name,
                "email": test_member.email,
                "user": test_member.user}

        else:
            test_member_data = members_with_users[0]
            print(f"Found test member: {test_member_data['full_name']} (User: {test_member_data['user']})")

        # Test volunteer creation
        print(f"\n🧪 Testing volunteer creation for member: {test_member_data['full_name']}")
        print(f"   Member has existing user account: {test_member_data['user']}")

        # Import the volunteer creation function
        from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member

        # This should now work without throwing an error
        volunteer = create_volunteer_from_member(test_member_data["name"])

        if volunteer:
            print(f"✅ SUCCESS: Volunteer record created: {volunteer.name}")
            print(f"   Volunteer name: {volunteer.volunteer_name}")
            print(f"   Organization email: {volunteer.email}")
            print(f"   Member keeps personal user: {test_member_data['user']}")

            # Verify the volunteer record
            volunteer.reload()
            print(f"   Volunteer status: {volunteer.status}")
            print(f"   Volunteer member link: {volunteer.member}")

            if volunteer.user:
                print(f"   Volunteer organization user: {volunteer.user}")
            else:
                print("   No organization user created (expected if email generation failed)")

        else:
            print("❌ FAILED: No volunteer record returned")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()

    finally:
        frappe.destroy()


if __name__ == "__main__":
    test_volunteer_creation_with_existing_user()
