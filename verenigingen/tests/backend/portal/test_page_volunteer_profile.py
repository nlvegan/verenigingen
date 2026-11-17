"""
Tests for the volunteer profile portal page
(verenigingen.templates.pages.volunteer.profile).

get_context() resolves the volunteer from frappe.session.user and must:
- raise PermissionError for Guest (require_login)
- set context.error_message when there is no volunteer record
- populate context.volunteer, volunteer_profile and organizations otherwise.
"""

import frappe
from frappe.utils import today

from verenigingen.templates.pages.volunteer import profile
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerProfilePage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._make_member_with_user(
            f"vol-prof-{frappe.generate_hash()[:8]}@test.invalid"
        )
        # Use the member's STORED email (see _make_member_with_user) as the login.
        self.user_email = self.member.email
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Profile Volunteer"
        )

    def _make_member_with_user(self, email):
        # create_test_member uniquifies the address under shared-DB collision
        # avoidance (it appends a suffix when the local part's last chars hold no
        # digit), so member.email may differ from `email`. The profile page
        # resolves the volunteer via Member.email == session.user, so the User and
        # session MUST use the member's actual stored email -- otherwise the happy
        # path intermittently saw "No volunteer record found" (~0.8% of runs, when
        # the random hash triggered the suffixing). Build the member first, then
        # mint the User from its real email.
        member = self.create_test_member(
            first_name="Prof", last_name="Member", email=email, birth_date="1990-01-01"
        )
        login_email = member.email
        if not frappe.db.exists("User", login_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": login_email,
                    "first_name": "Prof",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member.db_set("user", login_email)
        return member

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                profile.get_context(ctx)

    def test_no_volunteer_record_sets_error_message(self):
        other_member = self._make_member_with_user(
            f"prof-novol-{frappe.generate_hash()[:8]}@test.invalid"
        )
        with self.as_user(other_member.email):
            ctx = frappe._dict()
            profile.get_context(ctx)
        self.assertIn("No volunteer record found", ctx.error_message)
        self.assertNotIn("volunteer", ctx)

    def test_happy_path_populates_profile_and_organizations(self):
        with self.as_user(self.user_email):
            ctx = frappe._dict()
            profile.get_context(ctx)
        self.assertEqual(ctx.volunteer["name"], self.volunteer.name)
        self.assertEqual(ctx.volunteer_profile["name"], self.volunteer.name)
        self.assertEqual(ctx.volunteer_profile["email"], self.member.email)
        self.assertIn("chapters", ctx.organizations)
        self.assertIn("teams", ctx.organizations)
        self.assertEqual(ctx.title, "Volunteer Profile")
        self.assertTrue(ctx.show_sidebar)

    def test_get_user_volunteer_record_resolves_by_member(self):
        with self.as_user(self.user_email):
            rec = profile.get_user_volunteer_record()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], self.volunteer.name)

    def test_get_volunteer_profile_member_info(self):
        prof = profile.get_volunteer_profile(self.volunteer.name)
        self.assertEqual(prof["name"], self.volunteer.name)
        self.assertIsNotNone(prof["member_info"])
        self.assertEqual(prof["member_info"]["full_name"], self.member.full_name)
        self.assertIsInstance(prof["skills"], list)

    def test_get_volunteer_organizations_includes_team(self):
        team = self.create_test_team(team_name="Profile Team")
        team.append(
            "team_members",
            {
                "volunteer": self.volunteer.name,
                "volunteer_name": self.volunteer.volunteer_name,
                "team_role": "Team Member",
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team.save()

        orgs = profile.get_volunteer_organizations(self.volunteer.name)
        self.assertIn(team.name, [t["name"] for t in orgs["teams"]])

    # ---- #2704: only an enabled AND Active Chapter Member row is a membership ----

    def test_get_volunteer_organizations_lists_only_active_chapter_rows_2704(self):
        """Rows are left by the real writers: the Member suspend writer (enabled=1/Inactive) first,
        since it flips every row the member has, then request_to_join (Pending),
        remove_member(permanent=False) (enabled=0) and a plain add (Active, the control)."""
        from verenigingen.events.subscribers.member_subscribers import _update_chapter_membership_status

        chapters = {s: self.ensure_test_chapter(f"Org2704{s}").name for s in ("active", "pending", "suspended", "removed")}

        def add(state):
            chapter_doc = frappe.get_doc("Chapter", chapters[state])
            chapter_doc.append("members", {"member": self.member.name, "enabled": 1})
            chapter_doc.save()

        add("suspended")
        _update_chapter_membership_status(self.member, "Suspended")
        add("active")
        frappe.get_doc("Chapter", chapters["pending"]).member_manager.request_to_join(
            self.member.name, notify=False
        )
        add("removed")
        frappe.get_doc("Chapter", chapters["removed"]).member_manager.remove_member(
            self.member.name, leave_reason="left", notify=False
        )
        rows = {
            state: frappe.db.get_value(
                "Chapter Member",
                {"parent": name, "member": self.member.name},
                ["enabled", "status"],
                as_dict=True,
            )
            for state, name in chapters.items()
        }
        self.assertEqual((rows["suspended"].enabled, rows["suspended"].status), (1, "Inactive"), rows)
        self.assertEqual((rows["pending"].enabled, rows["pending"].status), (1, "Pending"), rows)
        self.assertEqual(rows["removed"].enabled, 0, rows)
        self.assertEqual((rows["active"].enabled, rows["active"].status), (1, "Active"), rows)

        names = [c["name"] for c in profile.get_volunteer_organizations(self.volunteer.name)["chapters"]]
        self.assertIn(chapters["active"], names)
        for state in ("pending", "suspended", "removed"):
            self.assertNotIn(chapters[state], names, f"a {state} row must not count as membership")
