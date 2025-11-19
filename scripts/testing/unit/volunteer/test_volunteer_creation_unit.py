import frappe
from frappe.utils import today
from verenigingen.tests.utils.base import VereningingenTestCase

from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member


class TestVolunteerCreationFix(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # test_docs tracking handled automatically by VereningingenTestCase

    # tearDown handled automatically by VereningingenTestCase

    def test_volunteer_creation_with_existing_user(self):
        """Test that volunteer can be created when member already has user account"""

        # Create test member using factory method
        member = self.create_test_member(
            first_name="Test",
            last_name="ExistingUser",
            email=f"test.existing.user.{frappe.utils.random_string(5)}@example.com"
        )

        # Create user account for member using factory method
        user = self.create_test_user(
            email=member.email,
            roles=["Member"]
        )

        # Link user to member
        member.user = user.name
        member.save()

        # Verify member has user account
        self.assertTrue(member.user, "Member should have user account")

        # Now test volunteer creation - this should NOT throw an error
        try:
            volunteer = create_volunteer_from_member(member.name)
            self.assertIsNotNone(volunteer, "Volunteer should be created")
            self.assertEqual(volunteer.member, member.name, "Volunteer should be linked to member")
            # Volunteer cleanup handled automatically by VereningingenTestCase

            # Member should still have their original user account
            member.reload()
            self.assertEqual(member.user, user.name, "Member should keep original user account")

            print(f"✅ SUCCESS: Volunteer created even with existing user account")
            print(f"   Member: {member.full_name} (User: {member.user})")
            print(f"   Volunteer: {volunteer.name} (Org Email: {volunteer.email})")

        except Exception as e:
            self.fail(f"Volunteer creation should not fail when user account exists: {e}")


def run_volunteer_creation_unit_tests():
    """Run volunteer creation unit tests"""
    import unittest
    
    print("👤 Running Volunteer Creation Unit Tests...")
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestVolunteerCreationFix)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("✅ All volunteer creation unit tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False

if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    run_volunteer_creation_unit_tests()
