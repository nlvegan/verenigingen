"""#2286: ``notify_chapter_board`` must reach a Chapter-profile holder whose profile is not their first.

On this Frappe ``User.role_profile_name`` mirrors only the FIRST row of the ``role_profiles`` child
table, so a ``role_profile_name LIKE '%Chapter%'`` filter misses a staffer who also holds a board
seat (#1969: such a user keeps Staff as the first profile and gains the board profile second).

The second-profile holder is built through real flows: a staff Team insert with the volunteer as a
member, then a board seat on a chapter OTHER than the one the request is for (so the seat holder is
reachable only through the site-wide profile filter, not through the chapter's own board rows).
The only probe shortcut is ``Member.user`` set with ``db_set`` (the account link an account-creation
request would write) and ``User.enabled`` flipped with ``db.set_value`` for the disabled control.
Recipients are read from the Email Queue rows the real send writes.
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import (
    allow_reminder_sends,
    ensure_outgoing_email_account,
)

STAFF = "Verenigingen Staff"


class TestChapterJoinRequestSecondProfile2286(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        suffix = frappe.generate_hash(length=6)
        self.request_chapter = self.create_test_chapter(
            chapter_name=f"Req2286 {suffix}", postal_codes="5000-5499", published=1
        )
        self.other_chapter = self.create_test_chapter(
            chapter_name=f"Other2286 {suffix}", postal_codes="5500-5999", published=1
        )
        self.applicant = self.create_test_member(
            first_name="Applicant", last_name="S2286", status="Active"
        )
        # A fresh CI site has no default outgoing account, so EmailService would refuse to queue
        # anything; without this the module passed only on sites that carry a leaked one.
        ensure_outgoing_email_account(self)
        allow_reminder_sends(keys=("chapter_join_request_submitted",))
        # Anchor: a real seat on the request's own chapter, so every send provably reaches someone.
        self.anchor = self._person_2286("Anchor")
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", self.request_chapter.name),
            self.anchor.volunteer,
            self._chapter_role_2286(),
            email=self.anchor.email,
        )

    def tearDown(self):
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _person_2286(self, label):
        email = f"jr2286.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="S2286", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email)

    def _chapter_role_2286(self):
        name = f"Secretary {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _staffer_2286(self, label):
        from verenigingen.setup import create_default_team_roles

        person = self._person_2286(label)
        sync_user_role_profile(person.user)
        create_default_team_roles()
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"J2286 Staff {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "default_role_profile": STAFF,
                "is_association_wide": 1,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        team.append(
            "team_members",
            {
                "volunteer": person.volunteer,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team.save()
        sync_user_role_profile(person.user)
        return person

    def _seat_on_other_chapter_2286(self, person):
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", self.other_chapter.name),
            person.volunteer,
            self._chapter_role_2286(),
            email=person.email,
        )

    def _second_profile_holder_2286(self, label="Second"):
        person = self._staffer_2286(label)
        self._seat_on_other_chapter_2286(person)
        rows = frappe.get_all(
            "User Role Profile",
            filters={"parent": person.user, "parenttype": "User"},
            pluck="role_profile",
            order_by="idx asc",
        )
        self.assertEqual(rows[0], STAFF, "fixture: Staff is the FIRST profile")
        self.assertIn(PROFILE_BOARD_MEMBER, rows[1:], "fixture: the board profile is a LATER profile")
        self.assertEqual(frappe.db.get_value("User", person.user, "role_profile_name"), STAFF)
        return person

    @staticmethod
    def _drop_queue_2286(names):
        if names:
            frappe.db.delete("Email Queue Recipient", {"parent": ["in", names]})
            frappe.db.delete("Email Queue", {"name": ["in", names]})

    def _notified_2286(self):
        """Recipients of the Email Queue rows the real notify_chapter_board send wrote."""
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.applicant.name,
                "chapter": self.request_chapter.name,
                "introduction": "2286",
            }
        )
        request.insert()
        self.track_doc("Chapter Join Request", request.name)
        queued = frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Chapter Join Request", "reference_name": request.name},
            pluck="name",
        )
        self._drop_queue_2286(queued)
        request.notify_chapter_board()
        queued = frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Chapter Join Request", "reference_name": request.name},
            pluck="name",
        )
        recipients = set(
            frappe.get_all("Email Queue Recipient", filters={"parent": ["in", queued or [""]]}, pluck="recipient")
        )
        self._drop_queue_2286(queued)
        self.assertIn(self.anchor.email, recipients, "control: the chapter's own board member got the mail")
        return recipients

    # ------------------------------------------------------------------ tests

    def test_second_profile_chapter_holder_is_notified(self):
        holder = self._second_profile_holder_2286()
        self.assertIn(holder.email, self._notified_2286())

    def test_staffer_without_a_chapter_profile_is_not_notified(self):
        """Control: a real staffer (Staff only) must not be swept in by the wider filter."""
        self._second_profile_holder_2286("Holder")  # a real holder exists, so the filter has a target
        staffer = self._staffer_2286("Plain")
        self.assertEqual(get_user_role_profiles(staffer.user), [STAFF], "fixture: Staff only")
        notified = self._notified_2286()
        self.assertNotIn(staffer.email, notified)

    def test_first_profile_chapter_holder_is_still_notified(self):
        """Control: the case that already worked (board profile as the only/first profile)."""
        person = self._person_2286("First")
        self._seat_on_other_chapter_2286(person)
        held = get_user_role_profiles(person.user)
        self.assertEqual(held[0], PROFILE_BOARD_MEMBER, "fixture: board profile is first")
        self.assertIn(person.email, self._notified_2286())

    def test_disabled_second_profile_holder_is_not_notified(self):
        holder = self._second_profile_holder_2286("Disabled")
        frappe.db.set_value("User", holder.user, "enabled", 0)  # probe shortcut: admin disabled the account
        self.assertNotIn(holder.email, self._notified_2286())
