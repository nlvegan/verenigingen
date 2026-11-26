"""#2959: one Chapter save with several changed seats names EVERY volunteer whose access survives.

``BoardManager.flush_pending_board_profile_syncs`` used to raise at the first volunteer whose board
access could not be withdrawn, so the operator fixed that user, saved again, and met the next one.
Maintainer ruling: keep the abort (a seat must not end while its access survives, #738/#1953), but
attempt every pending volunteer first and raise ONE ``BoardAccessWithdrawalError`` listing all.

Probe shortcut, stated: the leaked access is built by deleting the seat row straight from the
database (as ``test_board_role_withdrawal`` does), and the pending list is set directly on the
chapter doc instead of through a Chapter save, so the failure shape is exact and does not depend on
a real User.save failing. The abort-on-save itself is covered by the real-save test below.
"""

from unittest import mock

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import get_user_role_profiles
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

BOARD_PROFILE = "Verenigingen Chapter Board Member"


class TestFlushBoardSyncsCollectsFailures2959(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"R2959 {frappe.generate_hash(length=6)}", postal_codes="1000-9999", published=1
        )
        self.role_name = f"Role2959{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": self.role_name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", self.role_name)

    def _seated_2959(self, label):
        email = f"r2959.{label.lower()}.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="R2959", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        self.add_board_member_to_chapter(chapter, volunteer, self.role_name, email=user.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name)

    def _leak_2959(self, *people):
        """Vacate the seats behind every hook's back: profile and role stay attached."""
        for person in people:
            frappe.db.delete("Chapter Board Member", {"volunteer": person.volunteer})

    def _flush_2959(self, *people):
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter._pending_board_profile_syncs = [p.volunteer for p in people]
        manager = chapter.board_manager
        # Mock justified: the real sync/withdraw steps WOULD withdraw the leaked access (they work);
        # the case under test is those steps failing to, so only the post-condition remains to refuse.
        with mock.patch.object(manager, "_sync_role_profile_for_volunteer"), mock.patch.object(
            manager, "_withdraw_board_role_if_unseated"
        ):
            manager.flush_pending_board_profile_syncs()

    def test_two_failing_volunteers_are_both_named_in_one_error(self):
        first, second = self._seated_2959("One"), self._seated_2959("Two")
        self._leak_2959(first, second)
        with self.assertRaises(BoardAccessWithdrawalError) as caught:
            self._flush_2959(first, second)
        message = str(caught.exception)
        self.assertIn(first.volunteer, message)
        self.assertIn(second.volunteer, message)
        self.assertIn(first.user, message)
        self.assertIn(second.user, message)

    def test_a_clean_volunteer_between_two_failures_is_not_named(self):
        first, clean, last = self._seated_2959("A"), self._seated_2959("B"), self._seated_2959("C")
        self._leak_2959(first, last)
        with self.assertRaises(BoardAccessWithdrawalError) as caught:
            self._flush_2959(first, clean, last)
        message = str(caught.exception)
        self.assertIn(first.volunteer, message)
        self.assertIn(last.volunteer, message)
        self.assertNotIn(clean.volunteer, message)

    def test_one_failing_volunteer_raises_the_same_single_message_as_before(self):
        only = self._seated_2959("Solo")
        self._leak_2959(only)
        with self.assertRaises(BoardAccessWithdrawalError) as caught:
            self._flush_2959(only)
        message = str(caught.exception)
        self.assertIn(only.volunteer, message)
        self.assertIn(BOARD_PROFILE, message)
        self.assertEqual(message.count("access was not withdrawn"), 1)

    def test_the_aggregated_message_is_html_escaped_per_part(self):
        """The message is shown as HTML (parts joined by <br>), so markup in a part must not survive (N4)."""
        first, second = self._seated_2959("Esc1"), self._seated_2959("Esc2")
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter._pending_board_profile_syncs = [first.volunteer, second.volunteer]
        manager = chapter.board_manager
        # Mock justified: a real failing part cannot carry markup (names are docnames/emails), so the
        # post-condition's failure is injected to give the join something hostile to escape.
        with mock.patch.object(manager, "_sync_role_profile_for_volunteer"), mock.patch.object(
            manager, "_withdraw_board_role_if_unseated"
        ), mock.patch.object(
            manager,
            "_assert_board_access_withdrawn",
            side_effect=[
                BoardAccessWithdrawalError("Ann <b>Bold</b> <a@x.test>"),
                BoardAccessWithdrawalError("Bob <script>x</script>"),
            ],
        ):
            with self.assertRaises(BoardAccessWithdrawalError) as caught:
                manager.flush_pending_board_profile_syncs()
        message = str(caught.exception)
        self.assertIn("Ann &lt;b&gt;Bold&lt;/b&gt;", message)
        self.assertIn("Bob &lt;script&gt;", message)
        self.assertNotIn("<b>", message)
        self.assertNotIn("<script>", message)
        self.assertEqual(message.count("<br>"), 1, "the separator itself stays real markup")

    def test_no_failure_raises_nothing(self):
        fine = self._seated_2959("Fine")  # still seated: access is earned
        self._flush_2959(fine)

    def _ghost_2959(self, user):
        """The #2857 technique: a Has Role row naming a role that does not exist makes User.save fail
        (db_insert, because Frappe validates the roles table on a normal insert)."""
        frappe.get_doc(
            {
                "doctype": "Has Role",
                "parent": user,
                "parenttype": "User",
                "parentfield": "roles",
                "role": "Ghost Role 2959",
            }
        ).db_insert()

    def test_a_real_save_removing_three_seats_aborts_once_naming_both_failing_users_and_rolls_back(self):
        self.expectErrorLog("Board access withdrawal failed")
        self.expectErrorLog("Secure Operation Failed")
        self.expectErrorLog("Role Profile Sync Failed")
        self.expectErrorLog("Could not remove board member role")
        bad_one, good, bad_two = self._seated_2959("RealA"), self._seated_2959("RealB"), self._seated_2959("RealC")
        for person in (bad_one, bad_two):
            self._ghost_2959(person.user)
        people = (bad_one, good, bad_two)
        for person in people:
            self.assertIn(Roles.CHAPTER_BOARD_MEMBER, frappe.get_roles(person.user), "fixture: access granted")
            self.assertIn(BOARD_PROFILE, get_user_role_profiles(person.user), "fixture: profile granted")

        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.board_members = []
        # the request layer rolls back an aborted save; a savepoint stands in for it here
        frappe.db.savepoint("real_2959")
        with self.assertRaises(BoardAccessWithdrawalError) as caught:
            chapter.save()
        frappe.db.rollback(save_point="real_2959")

        message = str(caught.exception)
        self.assertIn(bad_one.user, message)
        self.assertIn(bad_two.user, message)
        for person in people:
            frappe.clear_cache(user=person.user)
            self.assertTrue(
                frappe.db.exists("Chapter Board Member", {"volunteer": person.volunteer, "is_active": 1}),
                "the seat must survive the aborted save",
            )
            self.assertTrue(
                frappe.db.exists("Has Role", {"parent": person.user, "role": Roles.CHAPTER_BOARD_MEMBER}),
                "the role must survive the aborted save",
            )
            self.assertIn(BOARD_PROFILE, get_user_role_profiles(person.user))
