"""Every path takes its row locks on the history managers' parents in one canonical order (#459).

#436 gave ``BaseHistoryManager._with_doc`` a ``FOR UPDATE`` on the parent row it rewrites,
so for the first time these managers hold more than one kind of row lock at a time:

    ChapterMembershipHistoryManager -> Member
    AssignmentHistoryManager        -> Volunteer
    DonationHistoryManager          -> Donor

Two transactions that take two of them in opposite orders deadlock. Measured with the
recorder below, before the fix (first acquisition of each doctype, in order):

    Chapter save touching board_members and members       ->  Volunteer, Member  INVERTED
    execute_system_updates, member on a chapter roster    ->  Member, Volunteer  ok
    execute_system_updates, member off every roster       ->  Volunteer, Member  INVERTED
    execute_safe_termination (the whitelisted API)        ->  Volunteer, Member  INVERTED

There are two separate implementations of "terminate this member". The first two rows
above run the *same* fourteen operations. Which order they lock in was
decided by the member's data: DisableChapterMemberships (idx 2) is what takes the Member
lock, and it returns before touching anything when there is no enabled Chapter Member
row -- leaving EndBoardPositions (idx 3, Volunteer) first and idx 13's ``member.save()``
as the first Member lock. So the termination was never Member-first as a property of the
list; it was Member-first as a property of the fixture you happened to test with.

``api.termination_api.execute_safe_termination`` is the other implementation, reached
from two whitelisted ADMIN endpoints. It has no DisableChapterMemberships step at all,
so its inversion was unconditional. Correcting only the Chapter save would have made
things worse there, not better: before the fix that path and the Chapter save agreed
(both Volunteer-first), and flipping one of an agreeing pair creates a deadlock where
there was none. All three take the member row up front now.

The canonical order is **Donor -> Member -> Volunteer**. It is alphabetical, and it is
what every path other than the chapter save already did: the Mollie webhook and
``member_history_update_service`` both take Donor before Member.

These tests observe the running code rather than reading it -- lock order is not a
property you can see in a diff once the acquisitions are spread across two hook layers,
four managers and fourteen termination operations.

**The three paths, and how the list was derived.** ``Chapter._handle_document_changes``,
``TerminationExecutionService.execute_system_updates``, and
``api.termination_api.execute_safe_termination``. Found by listing every non-test module
that mentions BOTH a Volunteer-locking call (``AssignmentHistoryManager``,
``*_volunteer_assignment_history``, ``end_board_positions_safe``,
``suspend``/``restore_team_memberships_safe``, ``terminate_volunteer_records_safe``) and a
Member-locking one (``ChapterMembershipHistoryManager``, ``update_member_status_safe``,
``suspend``/``unsuspend_member_safe``, ``disable_chapter_memberships_safe``) -- 20 files --
then reading each for whether both are *locks* rather than plain reads. Two near misses
worth recording so nobody re-investigates them:

* ``suspend_member_safe`` / ``unsuspend_member_safe`` do ``member.save()`` before the team
  helpers, so they are already canonical.
* ``membership_application.submit_application`` calls ``create_volunteer_record`` and then
  a chapter-membership helper, but ``frappe.db.commit()`` sits between them -- and a commit
  releases every lock, so the two are never held at once.

That is what the search finds, which is not the same as what exists: any ``doc.save()`` is
a row lock, so no static grep of this can be exhaustive. The third path was missed on the
first pass at #459 and cost more than leaving it alone would have -- see
``test_the_whitelisted_termination_api_locks_member_first``.

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

from verenigingen.tests.support.termination_request import create_termination_request
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
_WRITE = re.compile(r"^\s*(?:update|delete\s+from)\s+(.*?)(?:\bset\b|\bwhere\b|$)", re.IGNORECASE | re.DOTALL)
_TABLES = re.compile(r"`tab([^`]+)`")
# `name`=<param>, in the three parameter styles frappe emits. Used for row identity;
# see ParentLockRecorder._row for what an unresolvable one means.
_NAME_EQ = re.compile(r"`name`\s*=\s*(?:%\((\w+)\)s|(%s)|'([^']*)')", re.IGNORECASE)


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

        Every table named is reported, never just the first: a `SELECT ... FOR UPDATE`
        locks rows in every table it reads, joins included, and an `UPDATE a JOIN b SET`
        locks both. Reporting only the leading table would let a path that locks a
        Volunteer through a join read as clean. For an UPDATE / DELETE only the table
        clause is scanned -- a `tabX` inside the SET or WHERE expression is read, not
        locked for write.
        """
        write = _WRITE.match(query)
        scope = write.group(1) if write else (query if _FOR_UPDATE.search(query) else None)
        if scope is None:
            return []
        return [t for t in _TABLES.findall(scope) if t in CANONICAL_ORDER]

    def _row(self, query, values):
        """Best-effort primary key of the row a statement locks.

        Row identity is not cosmetic: `Member(X) -> Volunteer -> Member(X)` is canonical
        because the third acquisition is a row this transaction already holds, while
        `Member(A) -> Volunteer -> Member(B)` is a genuine inversion -- it wants a Member
        row while holding a Volunteer. Those two are indistinguishable without the name.

        An unresolvable statement returns None, and every None is treated as its own
        distinct row, so the ordering assertion errs toward reddening rather than toward
        passing quietly.
        """
        match = _NAME_EQ.search(query)
        if not match:
            return None
        named, positional, literal = match.groups()
        if literal is not None:
            return literal
        if named is not None:
            return values.get(named) if isinstance(values, dict) else None
        if positional:
            # A single parameter is passed BARE, not wrapped: Document.load_from_db's
            # for-update fast path does `frappe.db.sql(..., (self.name), as_dict=True)`,
            # and `(x)` is not a tuple. Treating that as unresolvable reported every
            # `SELECT * FROM `tabMember` WHERE `name` = %s FOR UPDATE` as its own row and
            # turned two correct paths red -- the instrument bug, not the code.
            if not isinstance(values, (list, tuple, dict)):
                values = (values,)
            if isinstance(values, (list, tuple)):
                # A positional placeholder's index is the number of `%s` before it. A
                # `%(name)s` earlier in the query does not contain the substring `%s`, so
                # counting cannot be thrown off by a mixed style.
                index = query.count("%s", 0, match.start())
                if index < len(values):
                    return values[index]
        return None

    def __enter__(self):
        real = frappe.db.sql

        def spy(query, *args, **kwargs):
            text = str(query)
            doctypes = self._locked_doctypes(text)
            if doctypes:
                values = kwargs.get("values", args[0] if args else ())
                row = self._row(text, values)
                for doctype in doctypes:
                    self.locks.append((doctype, row, " ".join(text.split())[:120]))
            return real(query, *args, **kwargs)

        self._patch = patch.object(frappe.db, "sql", spy)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False

    @property
    def doctypes(self):
        """Acquisition order with re-locks of an already-held ROW removed.

        A lock lives to the end of the transaction, so the second time this transaction
        locks the same row it already owns it and cannot deadlock on it. Asserting on the
        raw sequence would redden on `Member(X) -> Volunteer -> Member(X)`, which is the
        shape the termination has once the member row is taken up front, and which is
        correct.

        Deduplication is by (doctype, row), NOT by doctype: `Member(A) -> Volunteer ->
        Member(B)` still reads as `[Member, Volunteer, Member]` and still fails, because
        that transaction really does want a Member row while holding a Volunteer.
        `test_the_recorder_itself` pins both halves.
        """
        seen, ordered = set(), []
        for doctype, row, _query in self.locks:
            key = (doctype, row) if row is not None else (doctype, object())
            if key not in seen:
                seen.add(key)
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
            + "\n".join(f"  {d} {r}: {q}" for d, r, q in recorder.locks),
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

    def test_the_real_termination_operation_list_runs_and_takes_both_locks(self):
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

        request = create_termination_request(self, f.board_member.name, "lock order (#459)")

        with ParentLockRecorder() as recorder:
            TerminationExecutionService().execute_system_updates(request)

        # The terminated member is on a board, so this path must genuinely take both
        # kinds -- otherwise the ordering assertion is about a one-doctype sequence.
        self.assertIn("Member", recorder.doctypes, f"no Member lock taken: {recorder.locks}")
        self.assertIn("Volunteer", recorder.doctypes, f"no Volunteer lock taken: {recorder.locks}")
        self._assert_canonical(recorder, "the real termination operation list")

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

        request = create_termination_request(self, f.board_member.name, "lock order (#459)")

        with ParentLockRecorder() as recorder:
            TerminationExecutionService().execute_system_updates(request)

        self.assertIn("Member", recorder.doctypes, f"no Member lock taken: {recorder.locks}")
        self.assertIn("Volunteer", recorder.doctypes, f"no Volunteer lock taken: {recorder.locks}")
        self._assert_canonical(recorder, "a termination of a board member with no chapter membership")

    def test_the_whitelisted_termination_api_locks_member_first(self):
        """The third multi-lock path, and the one that had no chapter-membership step.

        ``verenigingen.api.termination_api.execute_safe_termination`` is a separate
        implementation of the same termination -- reached from two whitelisted ADMIN
        endpoints, the second being
        ``membership_termination_request.execute_safe_member_termination`` -- and it has
        no DisableChapterMemberships equivalent at all. So its Member lock is always
        last: step 3 ends board positions (Volunteer) and step 6 updates member status
        (Member). Not data-dependent like the service list; inverted for every member.

        It was missed when this issue was first fixed, and missing it was worse than
        leaving it alone would have been: before the fix this path agreed with the
        Chapter save (both Volunteer-first), and correcting only the Chapter save would
        have turned an agreeing pair into a deadlocking one on every chapter save.
        """
        from verenigingen.api.termination_api import execute_safe_termination

        f = self._seeded_chapter()

        doc = self._seat_on_board(f)
        doc.save()
        frappe.db.commit()

        with ParentLockRecorder() as recorder:
            result = execute_safe_termination(f.board_member.name, "Voluntary", today())

        self.assertTrue(result.get("success"), f"the API refused to run: {result}")
        self.assertIn("Member", recorder.doctypes, f"no Member lock taken: {recorder.locks}")
        self.assertIn("Volunteer", recorder.doctypes, f"no Volunteer lock taken: {recorder.locks}")
        self._assert_canonical(recorder, "the whitelisted execute_safe_termination API")


class TestTheRecorderItself(VereningingenTestCase):
    """A control for the instrument, on the one judgement it makes that is not mechanical.

    ``doctypes`` drops re-locks, and whether a re-lock is real depends on the ROW. The
    previous version of this file deduplicated by doctype alone and justified it with an
    argument ("it already owns those rows") that is only true per row -- so it would have
    reported a genuine `Member(A) -> Volunteer -> Member(B)` inversion as canonical. No
    path under test produces that shape today, which is exactly why it needs a synthetic
    control: an instrument whose weakness is unreachable by the current fixtures is one
    nobody will notice weakening.

    The queries below are verbatim from a recorded run, in all three parameter styles
    frappe emits.
    """

    VOLUNTEER_FOR_UPDATE = (
        "SELECT `name` FROM `tabVolunteer` WHERE `name`=%(param1)s "
        "ORDER BY `creation` DESC LIMIT 1 FOR UPDATE"
    )
    MEMBER_FOR_UPDATE = "SELECT * FROM `tabMember` WHERE `name` = %s FOR UPDATE"
    MEMBER_UPDATE = "UPDATE `tabMember` SET `status`=%s WHERE `name`=%s"

    def _recorder_over(self, statements):
        recorder = ParentLockRecorder()
        for query, values in statements:
            for doctype in recorder._locked_doctypes(query):
                recorder.locks.append((doctype, recorder._row(query, values), query))
        return recorder

    def test_a_relock_of_the_same_row_is_dropped(self):
        """Member(X) -> Volunteer -> Member(X): the shape the fixed termination has."""
        recorder = self._recorder_over(
            [
                (self.MEMBER_FOR_UPDATE, ("MEM-1",)),
                (self.VOLUNTEER_FOR_UPDATE, {"param1": "VOL-1"}),
                (self.MEMBER_UPDATE, ["Quit", "MEM-1"]),
            ]
        )
        self.assertEqual(recorder.doctypes, ["Member", "Volunteer"])

    def test_a_second_row_of_the_same_doctype_is_not_dropped(self):
        """Member(A) -> Volunteer -> Member(B): a real inversion that doctype-only
        deduplication would have hidden."""
        recorder = self._recorder_over(
            [
                (self.MEMBER_FOR_UPDATE, ("MEM-1",)),
                (self.VOLUNTEER_FOR_UPDATE, {"param1": "VOL-1"}),
                (self.MEMBER_UPDATE, ["Quit", "MEM-2"]),
            ]
        )
        self.assertEqual(recorder.doctypes, ["Member", "Volunteer", "Member"])

    def test_a_bare_scalar_parameter_still_resolves(self):
        """Document.load_from_db passes `(self.name)` -- a bare string, not a 1-tuple.
        Requiring a sequence made every for-update document load look like a fresh row."""
        recorder = self._recorder_over([(self.MEMBER_FOR_UPDATE, "MEM-1")])
        self.assertEqual([r for _d, r, _q in recorder.locks], ["MEM-1"])

    def test_an_unresolvable_row_is_never_treated_as_already_held(self):
        """A statement whose row cannot be read off is its own row every time, so an
        ordering assertion over it reddens rather than passing quietly."""
        by_customer = "SELECT * FROM `tabMember` WHERE `customer` = %s FOR UPDATE"
        recorder = self._recorder_over([(by_customer, ("CUS-1",)), (by_customer, ("CUS-1",))])
        self.assertEqual([r for _d, r, _q in recorder.locks], [None, None])
        self.assertEqual(recorder.doctypes, ["Member", "Member"])

    def test_every_table_of_a_join_is_reported(self):
        """A SELECT ... FOR UPDATE locks every table it reads. Reporting only the leading
        one would let a Volunteer locked through a join read as clean."""
        joined = (
            "SELECT v.`name` FROM `tabMember` m JOIN `tabVolunteer` v ON v.`member` = m.`name` "
            "WHERE m.`name` = %s FOR UPDATE"
        )
        recorder = self._recorder_over([(joined, ("MEM-1",))])
        self.assertEqual([d for d, _r, _q in recorder.locks], ["Member", "Volunteer"])

    def test_a_table_read_inside_a_where_clause_is_not_reported_as_locked(self):
        """The other direction: an UPDATE's WHERE subquery reads a table, it does not
        take write locks on it, so scanning the whole statement would over-report."""
        query = "UPDATE `tabMember` SET `status`=%s WHERE `name` IN (SELECT `member` FROM `tabVolunteer`)"
        recorder = self._recorder_over([(query, ["Quit"])])
        self.assertEqual([d for d, _r, _q in recorder.locks], ["Member"])
