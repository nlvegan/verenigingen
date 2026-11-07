"""#2208: VereningingenTestCase.create_test_volunteer(member_name=...) must link that member.

The core factory takes ``member=``. ``member_name`` used to fall into the Volunteer field
overrides, so the factory auto-built a SECOND Member and linked the Volunteer to it.
EnhancedTestCase.create_test_volunteer already honours ``member_name``; this pins the
VereningingenTestCase twin to the same contract.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestCreateTestVolunteerMemberName(VereningingenTestCase):
    def test_member_name_links_the_volunteer_to_that_member(self):
        member = self.create_test_member()

        volunteer = self.create_test_volunteer(member_name=member.name)

        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "member"), member.name)

    def test_member_name_does_not_build_a_second_member(self):
        member = self.create_test_member()
        before = frappe.db.count("Member")

        self.create_test_volunteer(member_name=member.name)

        self.assertEqual(frappe.db.count("Member"), before)

    def test_member_kwarg_still_links(self):
        # Control: the pre-existing spelling keeps working.
        member = self.create_test_member()

        volunteer = self.create_test_volunteer(member=member.name)

        self.assertEqual(volunteer.member, member.name)

    def test_no_member_still_auto_creates_one(self):
        # Control: omitting both still builds a Member, so the fix is not "never create".
        before = frappe.db.count("Member")

        volunteer = self.create_test_volunteer()

        self.assertTrue(frappe.db.exists("Member", volunteer.member))
        self.assertEqual(frappe.db.count("Member"), before + 1)

    def test_explicit_member_wins_over_member_name(self):
        # Conflict: member= is the factory's own spelling and takes precedence.
        wanted = self.create_test_member()
        other = self.create_test_member()

        volunteer = self.create_test_volunteer(member=wanted.name, member_name=other.name)

        self.assertEqual(volunteer.member, wanted.name)
