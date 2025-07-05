import unittest

import frappe
from frappe.utils import today

from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member


class TestVolunteerCreationFix(unittest.TestCase):
    def setUp(self):
        self.test_docs = []

    def tearDown(self):
        # Clean up test documents
        for doctype, name in reversed(self.test_docs):
            try:
                frappe.delete_doc(doctype, name, force=True)
            except:
                pass

    def test_volunteer_creation_with_existing_user(self):
        """Test that volunteer can be created when member already has user account"""

        # Create test member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "ExistingUser",
                "email": f"test.existing.user.{frappe.utils.random_string(5)}@example.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer",
            }
        )
        member.insert(ignore_permissions=True)
        self.test_docs.append(("Member", member.name))

        # Create user account for member
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": member.email,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "user_type": "Website User",
            }
        )
        user.insert(ignore_permissions=True)
        self.test_docs.append(("User", user.name))

        # Link user to member
        member.user = user.name
        member.save(ignore_permissions=True)

        # Verify member has user account
        self.assertTrue(member.user, "Member should have user account")

        # Now test volunteer creation - this should NOT throw an error
        try:
            volunteer = create_volunteer_from_member(member.name)
            self.assertIsNotNone(volunteer, "Volunteer should be created")
            self.assertEqual(volunteer.member, member.name, "Volunteer should be linked to member")
            self.test_docs.append(("Volunteer", volunteer.name))

            # Member should still have their original user account
            member.reload()
            self.assertEqual(member.user, user.name, "Member should keep original user account")

            print(f"✅ SUCCESS: Volunteer created even with existing user account")
            print(f"   Member: {member.full_name} (User: {member.user})")
            print(f"   Volunteer: {volunteer.name} (Org Email: {volunteer.email})")

        except Exception as e:
            self.fail(f"Volunteer creation should not fail when user account exists: {e}")


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    unittest.main()
