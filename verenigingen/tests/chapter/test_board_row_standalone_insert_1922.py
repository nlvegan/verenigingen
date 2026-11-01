"""#1922: a standalone insert of a Chapter Board Member row must still provision the seat.

#1672 moved the board role grant from the row's own ``after_insert`` to the Chapter save:
``BoardManager`` queues the volunteer in validate and ``Chapter.on_update`` flushes the role
profile sync. ``frappe.api.v1.create_doc`` (``POST /api/resource/<doctype>``) and
``frappe.api.v2.create_doc`` (``POST /api/v2/document/<doctype>``) do
``frappe.new_doc(doctype, **data).insert()`` with no ``istable`` handling, so a row POSTed
by Administrator never passes through a Chapter save and the seated user got no role.

A row added through a Chapter save never runs the child's ``after_insert`` (Frappe skips
child controllers there), so ``after_insert`` firing means the insert was standalone.

The REST cases call the two routes' own ``create_doc`` functions in-process, as
Administrator, with the request data each reads (v1: ``form_dict.data`` JSON; v2:
``form_dict``). Both functions are literally ``new_doc(doctype, **data).insert()``; an
HTTP round trip was run once by hand (subprocess, API key) while diagnosing: both routes
returned 200 with the row created and no role on the unfixed tree. It is not repeated here
because the subprocess needs committed fixtures, whose queued jobs race this process's
teardown on a bench with RQ workers.
"""

import json
from unittest import mock

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"


class TestBoardRowStandaloneInsert1922(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Row1922 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self.chapter_role = self._chapter_role_1922()

    def _chapter_role_1922(self):
        name = f"Secretary {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person_1922(self, label):
        email = f"row1922.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="Row", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email)

    def _row_1922(self, person):
        return {
            "parent": self.chapter.name,
            "parenttype": "Chapter",
            "parentfield": "board_members",
            "volunteer": person.volunteer,
            "chapter_role": self.chapter_role,
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "email": person.email,
        }

    def _roles_1922(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    # ------------------------------------------------------------------ the bug

    def _create_via_v1(self, row):
        import frappe.api.v1

        frappe.form_dict.data = json.dumps(row)
        return frappe.api.v1.create_doc("Chapter Board Member")

    def _create_via_v2(self, row):
        import frappe.api.v2

        frappe.form_dict.update(row)
        try:
            return frappe.api.v2.create_doc("Chapter Board Member")
        finally:
            frappe.form_dict.clear()

    def test_administrator_rest_create_of_a_board_row_provisions_the_seat_on_both_routes(self):
        for label, create in (("Vone", self._create_via_v1), ("Vtwo", self._create_via_v2)):
            person = self._person_1922(label)
            self.assertNotIn(BOARD_ROLE, self._roles_1922(person.user), "control: no role before the POST")

            create(self._row_1922(person))

            self.assertEqual(
                frappe.db.count(
                    "Chapter Board Member", {"parent": self.chapter.name, "volunteer": person.volunteer}
                ),
                1,
                "the created row exists",
            )
            self.assertIn(BOARD_ROLE, self._roles_1922(person.user), label)

    def test_a_failing_flush_refuses_the_standalone_insert(self):
        """Fail closed, deliberately (N2). Chapter.on_update runs the flush inside
        _safe_manager_operation, which logs an unexpected failure and lets the save go on. Here
        the only caller is an Administrator-only REST/script insert, so an unexpected failure
        is raised: the request is refused (and rolled back) rather than a seat created with no
        role. Per-volunteer sync failures are still only logged, as in the Chapter save."""
        person = self._person_1922("Failing")
        # Mock justified: injects the failure at the flush's own boundary.
        with mock.patch(
            "verenigingen.verenigingen.doctype.chapter.managers.board_manager."
            "BoardManager._withdraw_board_role_if_unseated",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                self._create_via_v2(self._row_1922(person))

    def test_a_row_with_a_nonexistent_parent_is_refused(self):
        """A standalone row naming a Chapter that does not exist used to insert as an orphan;
        the hook now loads the parent and raises DoesNotExistError."""
        person = self._person_1922("Orphan")
        row = {**self._row_1922(person), "parent": f"No Such Chapter {frappe.generate_hash(length=6)}"}
        with self.assertRaises(frappe.DoesNotExistError):
            self._create_via_v2(row)

    def test_frappe_client_insert_still_provisions_the_seat(self):
        """The already-safe route (appends to the parent and saves it): must keep working."""
        person = self._person_1922("Client")
        frappe.client.insert(doc=json.dumps({"doctype": "Chapter Board Member", **self._row_1922(person)}))
        self.assertIn(BOARD_ROLE, self._roles_1922(person.user))

    # --------------------------------------------- the normal path is unchanged

    def test_chapter_save_syncs_once_and_the_row_hook_does_not_run(self):
        """No double work: a row added through the Chapter save does not run the row's own
        after_insert, so the profile sync runs exactly once for the seated user."""
        from verenigingen.services.member.account.user_role_profile_calculator import (
            sync_user_role_profile,
        )
        from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
            ChapterBoardMember,
        )

        person = self._person_1922("Normal")
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append("board_members", {k: v for k, v in self._row_1922(person).items() if not k.startswith("parent")})

        # Mock justified: wraps= spies on the real calls to count them; behaviour unchanged.
        with mock.patch(
            "verenigingen.services.member.account.user_role_profile_calculator.sync_user_role_profile",
            wraps=sync_user_role_profile,
        ) as sync, mock.patch.object(
            ChapterBoardMember,
            "_provision_standalone_seat",
            autospec=True,
        ) as standalone:
            chapter.save()

        seat_syncs = [c for c in sync.call_args_list if c.args and c.args[0] == person.user]
        self.assertEqual(len(seat_syncs), 1)
        standalone.assert_not_called()
        self.assertIn(BOARD_ROLE, self._roles_1922(person.user))
