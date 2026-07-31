"""How board role-assignment failures propagate out of a Chapter save.

Seating or unseating a board member rewrites the volunteer's ``User.roles`` child
table, which issues a ``DELETE FROM tabHas Role WHERE parent=... AND name NOT IN
(...)``. Under contention that statement can lose a deadlock (1213) or a lock-wait
(1205). Two behaviours have to hold, and they pull in opposite directions:

* an ordinary per-member failure must NOT abort the save -- one bad volunteer cannot
  be allowed to block seating the rest of the board; but
* a non-resumable DB error MUST abort it, because there is no usable transaction left
  to seat anybody in. Swallowing it lets ``chapter.save()`` report success while every
  statement after it runs against state the server discarded, so the board member
  silently does not exist afterwards.

The failures are injected rather than provoked: reliably losing a real deadlock from a
test would need a second connection racing the same ``tabHas Role`` rows, which is
slow, flaky, and would prove less. What is under test is this app's exception routing
(``BoardManager._log_or_reraise`` and ``secure_document_operation``), not MariaDB's
locking -- so raising the exact exception type Frappe raises for 1213/1205 exercises
exactly the branch that matters. No business logic is stubbed: the real Chapter save,
the real BoardManager and the real secure_document_operation all run.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.secure_operations import secure_document_operation

ASSIGN_ROLE = (
    "verenigingen.verenigingen.doctype.chapter_board_member."
    "chapter_board_member.ChapterBoardMember.assign_board_member_role"
)


class TestBoardRoleFailurePropagation(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"RoleFail Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    def _make_role(self):
        role_name = f"Role{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def _make_volunteer(self, first):
        member = self.create_test_member(
            first_name=first,
            last_name="RoleFail",
            email=f"{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        volunteer = self.create_test_volunteer(member_name=member.name)
        return member, volunteer

    def _seat_board_member(self, first):
        """Append an active board row and save, returning the reloaded Chapter."""
        _member, volunteer = self._make_volunteer(first)
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": self._make_role(),
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        return chapter, volunteer

    # ------------------------------------------------------------------ board manager

    def test_deadlock_during_role_assignment_aborts_the_chapter_save(self):
        """A 1213 must reach the caller, not be logged as a per-member warning."""
        chapter, _volunteer = self._seat_board_member("Deadlocked")

        with patch(ASSIGN_ROLE, side_effect=frappe.QueryDeadlockError("1213 deadlock")):
            with self.assertRaises(frappe.QueryDeadlockError):
                chapter.save()

    def test_lock_wait_timeout_during_role_assignment_aborts_the_chapter_save(self):
        """1205 too: the unit of work is half-applied, which no caller here handles."""
        chapter, _volunteer = self._seat_board_member("LockWait")

        with patch(ASSIGN_ROLE, side_effect=frappe.QueryTimeoutError("1205 lock wait")):
            with self.assertRaises(frappe.QueryTimeoutError):
                chapter.save()

    def test_ordinary_role_failure_is_logged_and_the_board_member_is_still_seated(self):
        """The other half of the contract: per-member problems stay non-fatal."""
        self.expectErrorLog("Failed to assign board member role")
        chapter, volunteer = self._seat_board_member("Ordinary")

        with patch(ASSIGN_ROLE, side_effect=frappe.ValidationError("no user account")):
            chapter.save()

        reloaded = frappe.get_doc("Chapter", self.chapter.name)
        seated = [b for b in reloaded.board_members if b.volunteer == volunteer.name and b.is_active]
        self.assertEqual(len(seated), 1, "an ordinary role failure must not unseat the board member")

    # ------------------------------------------------------------ bulk operations

    def _bulk_payload(self, volunteer, board_row):
        return [
            {
                "volunteer": volunteer.name,
                "chapter_role": board_row.chapter_role,
                "from_date": str(board_row.from_date),
            }
        ]

    def _seated_chapter_and_payload(self, first):
        """Seat a board member for real, then return (manager, payload) to remove them."""
        chapter, volunteer = self._seat_board_member(first)
        chapter.save()
        reloaded = frappe.get_doc("Chapter", self.chapter.name)
        row = next(b for b in reloaded.board_members if b.volunteer == volunteer.name)
        return reloaded.board_manager, self._bulk_payload(volunteer, row)

    def test_bulk_remove_propagates_a_deadlock_from_the_chapter_save(self):
        """The outer handler returns ``success=False`` for every exception.

        For a 1213 that shape is a lie in both directions: it tells the caller "this
        operation did not happen" when the transaction it would have to retry in is
        already gone, and ``processed`` reports a count of writes the server discarded.
        The MijnRood sync service reads that dict and records an ordinary handler
        failure, so a deadlock during a privilege revocation is indistinguishable from
        a bad volunteer id.
        """
        manager, payload = self._seated_chapter_and_payload("BulkDeadlock")

        with patch.object(
            type(manager),
            "_save_chapter_with_board_changes",
            side_effect=frappe.QueryDeadlockError("1213 deadlock"),
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                manager.bulk_remove_board_members(payload)

    def test_bulk_remove_propagates_a_deadlock_from_the_per_member_work(self):
        """The INNER handler is the worse of the two, and was not in the original report.

        A per-member failure is appended to ``errors`` and the method still returns
        ``success: True``. So a deadlock while updating one volunteer's assignment
        history is reported as a partial success -- the caller sees a truthy result and
        carries on against a transaction the server has thrown away.
        """
        manager, payload = self._seated_chapter_and_payload("InnerDeadlock")

        with patch(
            "verenigingen.verenigingen.doctype.chapter.managers."
            "volunteer_integration_manager.VolunteerIntegrationManager"
            ".update_volunteer_assignment_history",
            side_effect=frappe.QueryDeadlockError("1213 deadlock"),
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                manager.bulk_remove_board_members(payload)

    def test_bulk_remove_still_collects_ordinary_per_member_failures(self):
        """The other half of the contract: one bad volunteer must not abort the batch."""
        manager, _payload = self._seated_chapter_and_payload("OrdinaryBulk")

        result = manager.bulk_remove_board_members([{"volunteer": "does-not-exist"}])

        self.assertTrue(result["success"], "an ordinary per-member failure must stay non-fatal")
        self.assertTrue(result["errors"], "the failure must still be reported")

    def test_bulk_deactivate_propagates_a_deadlock_from_the_chapter_save(self):
        """Same clause, same reasoning -- fixing one without the other would be arbitrary."""
        manager, payload = self._seated_chapter_and_payload("BulkDeactDeadlock")

        with patch.object(
            type(manager),
            "_save_chapter_with_board_changes",
            side_effect=frappe.QueryTimeoutError("1205 lock wait"),
        ):
            with self.assertRaises(frappe.QueryTimeoutError):
                manager.bulk_deactivate_board_members(payload)

    # ------------------------------------------------- secure_document_operation

    def test_secure_document_operation_propagates_a_non_resumable_error(self):
        """The layer the BoardManager fix depends on.

        secure_document_operation turns every exception into ``success=False``. For a
        deadlock that is wrong twice over: the caller reads it as "this one document did
        not save" and continues on a dead transaction, and the handler's own
        frappe.log_error() is a write issued on that same dead transaction.
        """
        user = frappe.get_doc("User", "Administrator")

        with patch(
            "frappe.model.document.Document.save",
            side_effect=frappe.QueryDeadlockError("1213 deadlock"),
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                secure_document_operation(
                    operation="save",
                    doc=user,
                    justification="propagation test",
                    required_permissions=["User:write"],
                )

    def test_secure_document_operation_still_reports_ordinary_failures(self):
        """Non-fatal errors keep the existing success=False contract."""
        self.expectErrorLog("Secure Operation Failed")
        user = frappe.get_doc("User", "Administrator")

        with patch(
            "frappe.model.document.Document.save",
            side_effect=frappe.ValidationError("nope"),
        ):
            result = secure_document_operation(
                operation="save",
                doc=user,
                justification="propagation test",
                required_permissions=["User:write"],
            )

        self.assertFalse(result.success)
        self.assertTrue(any("nope" in e for e in result.errors))
