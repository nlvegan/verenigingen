"""Every path takes its row locks on the history managers' parents in one canonical order (#459).

#436 gave ``BaseHistoryManager._with_doc`` a ``FOR UPDATE`` on the parent row it rewrites,
so for the first time these managers hold more than one kind of row lock at a time:

    ChapterMembershipHistoryManager -> Member
    AssignmentHistoryManager        -> Volunteer
    DonationHistoryManager          -> Donor

Two transactions that take two of them in opposite orders deadlock. Measured with the
recorder below, before the fix (first acquisition of each doctype, in order):

    Chapter save touching board_members and members       ->  Volunteer, Member  INVERTED
    termination, member still on a chapter roster         ->  Member, Volunteer  ok
    termination, member off every chapter roster          ->  Volunteer, Member  INVERTED

The two terminations run the *same* fourteen operations. Which order they lock in was
decided by the member's data: DisableChapterMemberships (idx 2) is what takes the Member
lock, and it returns before touching anything when there is no enabled Chapter Member
row -- leaving EndBoardPositions (idx 3, Volunteer) first and idx 13's ``member.save()``
as the first Member lock. So the termination was never Member-first as a property of the
list; it was Member-first as a property of the fixture you happened to test with.

The canonical order is **Donor -> Member -> Volunteer**. It is alphabetical, and it is
what every path other than the chapter save already did: the Mollie webhook and
``member_history_update_service`` both take Donor before Member.

These tests observe the running code rather than reading it -- lock order is not a
property you can see in a diff once the acquisitions are spread across two hook layers,
four managers and fourteen termination operations.

**Scope.** The invariant asserted here is the cross-doctype one: the *first* acquisition
of each doctype must come in canonical rank order. Re-locking a row the transaction
already holds is free and is deduplicated away. Two different rows of the *same* doctype
locked in a data-dependent order (two concurrent Chapter saves walking a shared
``members`` table in child-table ``idx`` order) is a real and separate defect that these
tests deliberately do not cover.
"""

import re
from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase

# Lower rank must be acquired first. Doctypes absent here take no history-manager lock.
CANONICAL_ORDER = {"Donor": 0, "Member": 1, "Volunteer": 2}

# A row lock, in the three SQL shapes this repo produces. `frappe.db.sql` is the single
# choke point: get_value(for_update=True), db.set_value, frappe.qb .for_update() and
# Document.db_update all render to a string and go through it, so hooking it here sees
# every acquisition rather than the one shape `frappe.db.get_value` happens to cover.
# That mattered: the first version of this recorder patched only get_value and reported
# the termination path as canonical, because idx 13's lock is a plain `member.save()`.
_FOR_UPDATE = re.compile(r"\bfor\s+update\b", re.IGNORECASE)
_WRITE = re.compile(r"^\s*(?:update|delete\s+from)\s+`tab([^`]+)`", re.IGNORECASE)
_TABLES = re.compile(r"`tab([^`]+)`")


class ParentLockRecorder:
    """Records every row lock taken on a Donor / Member / Volunteer row, in order.

    Patches `frappe.db.sql` rather than reading the source, because which rows a Chapter
    save or a termination ends up locking is decided at runtime by two hook layers, four
    managers and the contents of the member's chapters.
    """

    def __init__(self):
        self.locks = []

    def _locked_doctypes(self, query):
        """Which of Donor / Member / Volunteer this statement takes row locks on.

        An UPDATE / DELETE locks its target table. A `SELECT ... FOR UPDATE` locks
        rows in *every* table it reads, joins included -- so all of them are reported,
        not just the first FROM. Reporting only the first would let a path that locks a
        Volunteer through a join read as clean.
        """
        write = _WRITE.match(query)
        if write:
            return [write.group(1)] if write.group(1) in CANONICAL_ORDER else []
        if not _FOR_UPDATE.search(query):
            return []
        return [t for t in _TABLES.findall(query) if t in CANONICAL_ORDER]

    def __enter__(self):
        real = frappe.db.sql

        def spy(query, *args, **kwargs):
            text = str(query)
            for doctype in self._locked_doctypes(text):
                self.locks.append((doctype, " ".join(text.split())[:120]))
            return real(query, *args, **kwargs)

        self._patch = patch.object(frappe.db, "sql", spy)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False

    @property
    def doctypes(self):
        """First acquisition per doctype, in acquisition order.

        Deduplicated because a lock is held to the end of the transaction: the second
        time the same transaction touches `tabMember` it already owns those rows and
        cannot deadlock on them. Asserting on the raw sequence would redden on a
        Member -> Volunteer -> Member path that is in fact correct, which is exactly the
        shape the termination has once the member row is taken up front.
        """
        seen, ordered = set(), []
        for doctype, _query in self.locks:
            if doctype not in seen:
                seen.add(doctype)
                ordered.append(doctype)
        return ordered


class TestHistoryLockOrder(VereningingenTestCase):
    def _assert_canonical(self, recorder, what):
        # Without this, a path that takes NO locks -- or a recorder that silently stopped
        # working -- passes the ordering assertion vacuously. It has already happened
        # once: the first version of this recorder was never entered and reported an
        # empty list for every path, which reads exactly like "no locks are taken".
        self.assertTrue(
            recorder.locks,
            f"{what}: the recorder captured no locks at all, so the ordering assertion "
            "below would pass on nothing. The instrument is broken, not the code.",
        )

        ranks = [CANONICAL_ORDER[d] for d in recorder.doctypes]
        self.assertEqual(
            ranks,
            sorted(ranks),
            f"{what} acquires history parent locks out of canonical order "
            f"(Donor -> Member -> Volunteer): got {recorder.doctypes}. Another path taking "
            "them the other way round deadlocks against this one (#459).\n"
            + "\n".join(f"  {d}: {q}" for d, q in recorder.locks),
        )

    def _seeded_chapter(self):
        """A chapter with one board-eligible volunteer and one ordinary member, committed."""
        chapter = self.create_test_chapter()
        board_member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=board_member.name)
        plain_member = self.create_test_member()
        role = self.create_test_chapter_role()

        doc = frappe.get_doc("Chapter", chapter.name)
        doc.append("members", {"member": plain_member.name, "enabled": 1})
        doc.save()
        frappe.db.commit()
        self.addCleanup(frappe.db.commit)

        return frappe._dict(
            chapter=chapter,
            board_member=board_member,
            volunteer=volunteer,
            plain_member=plain_member,
            role=role,
        )

    def _seat_on_board(self, fixture):
        doc = frappe.get_doc("Chapter", fixture.chapter.name)
        doc.append(
            "board_members",
            {
                "volunteer": fixture.volunteer.name,
                "chapter_role": fixture.role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        return doc

    def test_a_chapter_save_touching_board_and_members_locks_in_canonical_order(self):
        """The path that was inverted. Board handlers ran before member handlers, so this
        locked a Volunteer before a Member."""
        f = self._seeded_chapter()

        doc = self._seat_on_board(f)
        for chapter_member in doc.members:
            if chapter_member.member == f.plain_member.name:
                chapter_member.enabled = 0

        with ParentLockRecorder() as recorder:
            doc.save()

        # Both kinds must actually be present, or "in order" is trivially true of a
        # sequence that only ever contains one doctype -- which is what a save that
        # silently skipped the board handlers would produce.
        self.assertIn("Volunteer", recorder.doctypes, f"no Volunteer lock taken: {recorder.locks}")
        self.assertIn("Member", recorder.doctypes, f"no Member lock taken: {recorder.locks}")
        self._assert_canonical(recorder, "a Chapter save touching board_members and members")

    def test_the_real_termination_operation_list_locks_in_canonical_order(self):
        """Drives `TerminationExecutionService.execute_system_updates`, which owns the
        real `operations = [...]`.

        An earlier version of this test called two of the *_safe helpers directly, in an
        order it chose itself. That is a wrong-target test: it never reads the production
        list, so reordering that list leaves it green while production inverts. It also
        cannot see idx 13 -- UpdateMemberStatusOperation, whose `member.save()` is the
        acquisition that makes this path non-canonical on its own.

        This fixture is the common case, and it was already canonical before the fix --
        removing the up-front lock leaves it green, because idx 2 takes the Member lock
        for a member who has a chapter membership. It is here to pin that the real list
        runs end to end and takes both kinds of lock; the sibling test below, whose member
        has no chapter membership, is the one that discriminates.
        """
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        f = self._seeded_chapter()

        # Seat the volunteer so EndBoardPositions (idx 3) has a position to end, and put
        # the terminated member in the chapter so DisableChapterMemberships (idx 2) has
        # a membership to disable. Both must be committed: the operations reload from
        # the database.
        doc = self._seat_on_board(f)
        doc.save()
        frappe.db.commit()

        request = self._termination_request(f.board_member.name)

        with ParentLockRecorder() as recorder:
            TerminationExecutionService().execute_system_updates(request)

        # The terminated member is on a board, so this path must genuinely take both
        # kinds -- otherwise the ordering assertion is about a one-doctype sequence.
        self.assertIn("Member", recorder.doctypes, f"no Member lock taken: {recorder.locks}")
        self.assertIn("Volunteer", recorder.doctypes, f"no Volunteer lock taken: {recorder.locks}")
        self._assert_canonical(recorder, "the real termination operation list")

    def _termination_request(self, member_name):
        request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member_name,
                "termination_type": "Voluntary",
                "termination_reason": "lock order (#459)",
                "member_request_date": today(),
                "termination_date": today(),
                "end_board_positions": 1,
            }
        )
        request.insert()
        self.track_doc("Membership Termination Request", request.name)
        frappe.db.commit()
        return request

    def test_a_termination_with_no_chapter_membership_still_locks_member_first(self):
        """Where the ordering is decided by data, not by the operation list.

        DisableChapterMemberships (idx 2) is the operation that happens to take the
        Member lock first -- but only when there is an *enabled* Chapter Member row to
        disable; ``disable_chapter_memberships_safe`` returns 0 before touching anything
        otherwise. A board member whose chapter row is already disabled therefore skips
        straight to EndBoardPositions (idx 3, Volunteer), and the first Member lock is
        idx 13's ``member.save()`` -- Volunteer before Member, the inversion.

        So "the termination locks Member first" was never a property of the list; it was
        a property of the fixture. The member row is taken up front to make it one.
        """
        from verenigingen.services.termination.termination_execution_service import (
            TerminationExecutionService,
        )

        f = self._seeded_chapter()

        doc = self._seat_on_board(f)
        doc.save()
        frappe.db.commit()

        # Take the board member off every chapter roster while leaving the board seat, so
        # idx 2 has nothing to disable. Every chapter, not just this one: the member
        # factory seeds a chapter of its own, and one enabled row anywhere is enough for
        # disable_chapter_memberships_safe to take the Member lock.
        for row in frappe.get_all(
            "Chapter Member", filters={"member": f.board_member.name, "enabled": 1}, fields=["name", "parent"]
        ):
            chapter_doc = frappe.get_doc("Chapter", row.parent)
            for chapter_member in chapter_doc.members:
                if chapter_member.name == row.name:
                    chapter_member.enabled = 0
            chapter_doc.save()
        frappe.db.commit()
        self.assertFalse(
            frappe.get_all("Chapter Member", filters={"member": f.board_member.name, "enabled": 1}, limit=1),
            "fixture did not disable the chapter membership, so idx 2 will take the "
            "Member lock and this test cannot see the inversion",
        )

        request = self._termination_request(f.board_member.name)

        with ParentLockRecorder() as recorder:
            TerminationExecutionService().execute_system_updates(request)

        self.assertIn("Member", recorder.doctypes, f"no Member lock taken: {recorder.locks}")
        self.assertIn("Volunteer", recorder.doctypes, f"no Volunteer lock taken: {recorder.locks}")
        self._assert_canonical(recorder, "a termination of a board member with no chapter membership")
