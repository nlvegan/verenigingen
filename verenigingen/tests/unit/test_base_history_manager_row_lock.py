"""Guards that BaseHistoryManager locks the parent row it is about to rewrite (#436).

``_with_doc`` is a read-modify-write: it loads the parent document, hands it to a
callback that mutates a child table in memory, and writes the table back with
``safe_child_table_update``. Nothing in that sequence locked the parent row, so two
writers could both read, both compute, and the second write would win -- the classic
lost update.

``donor_history`` is the sharpest case because it has **two** writers with different
contracts: ``MemberFinancialHistoryManager.add_or_update_entry`` locks the Donor row
(#424), and ``DonationHistoryManager`` did not. An unlocked writer does not queue
behind a locked one, so #424 alone did not make that table safe.
``sync_donation_history`` is the worst of them -- its callback does
``donor.donor_history = []`` and rebuilds from ``frappe.get_all("Donation", ...)``,
so a concurrent entry is dropped wholesale rather than merely stale.

These tests probe from a SECOND database connection rather than reading the source,
for the reason named in the sibling module: a ``FOR UPDATE`` that matches zero rows
is not an error, so the only observable difference between a lock that was taken and
one that was not is whether somebody else can still take it. The probe, and the
control that proves it discriminates, live in
``verenigingen.tests.payment.test_history_manager_row_lock``.
"""

import frappe

from verenigingen.tests.payment.test_history_manager_row_lock import (
    row_is_locked_from_another_connection,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager
from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager
from verenigingen.utils.donation_history_manager import DonationHistoryManager


class TestBaseHistoryManagerLocksItsParentRow(VereningingenTestCase):
    """One test per subclass: the fix is one line in the base class, but the point of
    a base class is that every subclass gets it, and only a per-subclass assertion
    says so."""

    def _commit(self, doc):
        """Make `doc` durable and arrange for it to be removed.

        The probe runs on its own connection, so it cannot see this test's
        uncommitted rows -- and an uncommitted INSERT holds an implicit exclusive
        lock of its own, which would make every assertion below pass vacuously.
        """
        frappe.db.commit()
        self.addCleanup(self._drop, doc.doctype, doc.name)
        return doc

    def _drop(self, doctype, name):
        """Delete and commit -- the row is durable now, and the commit also releases
        whatever row lock the test itself left open."""
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True)
        frappe.db.commit()

    def test_a_donation_history_write_locks_the_donor_row(self):
        """DonationHistoryManager -> Donor. The writer that raced the one #424 fixed."""
        donor = self._commit(self.create_test_donor())
        donation = self.create_test_donation(donor=donor.name)

        result = DonationHistoryManager.add_donation_entry(donor.name, donation)
        self.assertTrue(
            result.get("success"),
            f"the history write itself failed ({result}), so this proves nothing about locking",
        )
        # A callback that skips the save still reports success, and the lock is taken
        # either way -- so without this the assertion below could pass on a write that
        # never happened.
        self.assertTrue(
            frappe.db.exists("Donation History", {"parent": donor.name, "donation_reference": donation.name}),
            "no donor_history row was written, so nothing here exercised the read-modify-write",
        )

        self.assertTrue(
            row_is_locked_from_another_connection("Donor", donor.name),
            f"Donor {donor.name} is still lockable by another connection after "
            "DonationHistoryManager rewrote its donor_history. A concurrent "
            "sync_donation_history() -- which clears the table and rebuilds it -- can "
            "therefore drop whatever the Mollie webhook just added (#436).",
        )

    def test_a_chapter_membership_history_write_locks_the_member_row(self):
        """ChapterMembershipHistoryManager -> Member."""
        member = self._commit(self.create_test_member())
        chapter = self._commit(self.create_test_chapter())

        wrote = ChapterMembershipHistoryManager.add_membership_history(
            member_id=member.name,
            chapter_name=chapter.name,
            assignment_type="Member",
            start_date=frappe.utils.nowdate(),
        )
        self.assertTrue(wrote, "the history write itself failed, so this proves nothing about locking")
        self.assertTrue(
            frappe.db.exists(
                "Chapter Membership History", {"parent": member.name, "chapter_name": chapter.name}
            ),
            "no chapter_membership_history row was written -- the callback skipped the save, "
            "so nothing here exercised the read-modify-write",
        )

        self.assertTrue(
            row_is_locked_from_another_connection("Member", member.name),
            f"Member {member.name} is still lockable by another connection after "
            "ChapterMembershipHistoryManager rewrote its chapter_membership_history (#436).",
        )

    def test_an_assignment_history_write_locks_the_volunteer_row(self):
        """AssignmentHistoryManager -> Volunteer."""
        member = self._commit(self.create_test_member())
        volunteer = self._commit(self.create_test_volunteer(member=member.name))
        # reference_name is a Dynamic Link on reference_doctype and IS validated by
        # update_child_table, so it has to point at a row that exists.
        chapter = self._commit(self.create_test_chapter())

        wrote = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=chapter.name,
            role="Lock Scope Guard",
            start_date=frappe.utils.nowdate(),
        )
        self.assertTrue(wrote, "the history write itself failed, so this proves nothing about locking")
        self.assertTrue(
            frappe.db.exists("Volunteer Assignment", {"parent": volunteer.name, "role": "Lock Scope Guard"}),
            "no assignment_history row was written -- the callback skipped the save, "
            "so nothing here exercised the read-modify-write",
        )

        self.assertTrue(
            row_is_locked_from_another_connection("Volunteer", volunteer.name),
            f"Volunteer {volunteer.name} is still lockable by another connection after "
            "AssignmentHistoryManager rewrote its assignment_history (#436).",
        )
