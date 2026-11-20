"""#2857: one broken board holder must not hold a Chapter Role edit hostage.

After #2718, ``assign_chapter_board_role`` raises ``BoardAccessWithdrawalError`` when a User's board
access cannot be withdrawn, and ``on_chapter_role_on_update`` re-raised the first one: a ghost
``Has Role`` row on ONE holder rolled back a ``permissions_level`` edit for every holder.

Maintainer ruling (2026-11-19): each holder is processed under its own savepoint; the Chapter Role
save succeeds; every failure stays loud (an Error Log row per user, ONE registered staff alert
listing the failed users).

Probe shortcuts, stated: the ghost ``Has Role`` row is written with ``db_insert`` (a Role deleted
after it was granted leaves exactly this), and each holder's board role is granted by a direct
``Has Role`` write, because an email-only holder (no ``Member.user``) is never granted it by the
seat flow and the handler's job is to withdraw it.
"""

from unittest import mock

import frappe

from verenigingen.services.chapter import chapter_role_events
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"
GHOST_ROLE = "Ghost Role 2857"
ALERT_SUBJECT = "Board access was not withdrawn"


class TestChapterRoleHolderFailures2857(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"R2857 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self.role_name = f"Role2857 {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": self.role_name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", self.role_name)

    def tearDown(self):
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _holder_2857(self, label, broken=False):
        """An email-only holder: a Member WITHOUT ``Member.user``, seated on the role, whose User
        holds the board role (and, if ``broken``, a Has Role row naming a role that does not exist)."""
        email = f"r2857.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="R2857", email=email, status="Active")
        volunteer = self.create_test_volunteer(member=member.name)
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        self.add_board_member_to_chapter(chapter, volunteer.name, self.role_name, email=email)
        self._grant_2857(user.name, BOARD_ROLE)
        if broken:
            self._grant_2857(user.name, GHOST_ROLE)
        self.assertFalse(frappe.db.get_value("Member", member.name, "user"), "fixture: email-only")
        return frappe._dict(user=user.name, member=member.name, volunteer=volunteer.name)

    def _grant_2857(self, user, role):
        if not frappe.db.exists("Has Role", {"parent": user, "role": role}):
            frappe.get_doc(
                {
                    "doctype": "Has Role",
                    "parent": user,
                    "parenttype": "User",
                    "parentfield": "roles",
                    "role": role,
                }
            ).db_insert()

    def _roles_2857(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _edit_level_2857(self, level="Admin"):
        role = frappe.get_doc("Chapter Role", self.role_name)
        role.permissions_level = level
        role.save()

    def _staff_2857(self):
        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows

        ensure_notification_registry_rows()
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"r2857.staff.{frappe.generate_hash(length=8).lower()}@example.org",
                "first_name": "Staff",
                "send_welcome_email": 0,
                "enabled": 1,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()
        self.track_doc("User", user.name)
        return user.name

    def _alerts_2857(self, staff):
        return frappe.get_all(
            "Notification Log",
            {"for_user": staff, "subject": ["like", f"{ALERT_SUBJECT}%"]},
            ["name", "email_content"],
        )

    def _errors_2857(self, user):
        return frappe.get_all(
            "Error Log",
            filters={"method": ["like", "Chapter Role holder withdrawal failed%"], "error": ["like", f"%{user}%"]},
            pluck="name",
        )

    # ------------------------------------------------------------------ the fix

    def test_one_broken_holder_does_not_block_the_edit_for_the_others(self):
        self.expectErrorLog("Board access withdrawal failed")
        self.expectErrorLog("Chapter Role holder withdrawal failed")
        staff = self._staff_2857()
        bad = self._holder_2857("Bad", broken=True)
        good = self._holder_2857("Good")

        self._edit_level_2857("Admin")  # must not raise

        self.assertEqual(frappe.db.get_value("Chapter Role", self.role_name, "permissions_level"), "Admin")
        self.assertNotIn(BOARD_ROLE, self._roles_2857(good.user), "the good holder was not re-evaluated")
        self.assertIn(BOARD_ROLE, self._roles_2857(bad.user), "the broken holder is rolled back, not half-done")
        self.assertEqual(len(self._errors_2857(bad.user)), 1, "one Error Log row for the broken user")
        self.assertEqual(self._errors_2857(good.user), [])
        alerts = self._alerts_2857(staff)
        self.assertEqual(len(alerts), 1, "ONE alert for staff")
        self.assertIn(bad.user, alerts[0].email_content)
        self.assertNotIn(good.user, alerts[0].email_content)

    def test_two_broken_holders_make_one_alert_naming_both(self):
        self.expectErrorLog("Board access withdrawal failed")
        self.expectErrorLog("Chapter Role holder withdrawal failed")
        staff = self._staff_2857()
        first, second = self._holder_2857("One", broken=True), self._holder_2857("Two", broken=True)

        self._edit_level_2857("Admin")

        alerts = self._alerts_2857(staff)
        self.assertEqual(len(alerts), 1)
        for person in (first, second):
            self.assertIn(person.user, alerts[0].email_content)
            self.assertEqual(len(self._errors_2857(person.user)), 1)

    def test_no_failure_means_no_alert_and_no_error_log(self):
        staff = self._staff_2857()
        good = self._holder_2857("Fine")

        self._edit_level_2857("Admin")

        self.assertNotIn(BOARD_ROLE, self._roles_2857(good.user))
        self.assertEqual(self._alerts_2857(staff), [])
        self.assertEqual(self._errors_2857(good.user), [])

    def test_a_partial_write_of_the_failing_user_is_rolled_back(self):
        """The refusal comes AFTER the real strip removed the board role, so only the per-user
        savepoint can restore it: a bare try/except would leave the user half-withdrawn."""
        self.expectErrorLog("Chapter Role holder withdrawal failed")
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        holder = self._holder_2857("Half")
        real_strip = __import__("verenigingen.permissions", fromlist=["x"])._strip_board_profiles_and_role

        def strip_then_refuse(user_email):
            real_strip(user_email)
            self.assertNotIn(BOARD_ROLE, self._roles_2857(user_email), "fixture: the write happened first")
            raise BoardAccessWithdrawalError("refused after writing")

        # Mock justified: refuses after the writes, the shape of the post-condition failing.
        with mock.patch("verenigingen.permissions._strip_board_profiles_and_role", side_effect=strip_then_refuse):
            self._edit_level_2857("Admin")

        self.assertIn(BOARD_ROLE, self._roles_2857(holder.user), "the failed holder was left half-withdrawn")

    def test_an_alert_side_failure_does_not_undo_the_save(self):
        self.expectErrorLog("Board access withdrawal failed")
        self.expectErrorLog("Chapter Role holder withdrawal failed")
        self.expectErrorLog("Chapter Role holder alert failed")
        good_before = self._holder_2857("Alert")
        self._holder_2857("AlertBad", broken=True)

        # Mock justified: the staff alert itself blows up.
        with mock.patch.object(chapter_role_events, "notify_administrators", side_effect=ConnectionError("x")):
            self._edit_level_2857("Admin")  # must not raise

        self.assertEqual(frappe.db.get_value("Chapter Role", self.role_name, "permissions_level"), "Admin")
        self.assertNotIn(BOARD_ROLE, self._roles_2857(good_before.user))

    def test_a_deadlock_inside_a_users_savepoint_propagates(self):
        """1213 destroys every savepoint: it must reach the transaction owner, not be collected."""
        self._holder_2857("Dead")
        # Mock justified: a real deadlock cannot be provoked deterministically.
        with mock.patch.object(chapter_role_events, "assign_chapter_board_role", side_effect=frappe.QueryDeadlockError):
            with self.assertRaises(frappe.QueryDeadlockError):
                self._edit_level_2857("Admin")

    def test_a_lock_timeout_inside_a_users_savepoint_propagates(self):
        self._holder_2857("Timeout")
        # Mock justified: a real lock wait timeout cannot be provoked deterministically.
        with mock.patch.object(chapter_role_events, "assign_chapter_board_role", side_effect=frappe.QueryTimeoutError):
            with self.assertRaises(frappe.QueryTimeoutError):
                self._edit_level_2857("Admin")
