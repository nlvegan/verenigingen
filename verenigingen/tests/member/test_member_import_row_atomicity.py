"""A Member Import row reported "skipped" must leave nothing behind (issue #570).

``MemberImport._process_single_member`` inserts a Member and, on any failure,
appends a line to the import's error log and returns ``("skipped", "")``. The
batch loop in ``csv_import_processor.process_import`` then **commits** -- its
``if batch_commit: frappe.db.commit()``, and ``process_import_background`` passes
``batch_commit=True``. ``Document.insert()`` has no savepoint of its own, so a
throw from anything downstream of the row write -- ``Member.after_insert``
creating the ERPNext Customer is the live one -- left the Member row written and
committed while the operator was told the row was skipped.

The consequence is not one stray row. A *systematic* misconfiguration (a missing
Customer Group, a deleted Territory, an import user without Customer/Contact
create permission) fails every row the same way, so a 5,000-row import reports
"created: 0, skipped: 5000" while creating 5,000 orphaned Members.

## What the assertions actually discriminate

The property under test is **written versus rolled back**, and a query on the
same connection answers that whether or not a commit has happened -- so the
absence assertions below would discriminate even with no commit at all. The real
importer is driven anyway, with production's own ``batch_commit=True``, because
that is the code path an operator runs: the batch commit is what turns "written"
into "durable and nobody's rollback will take it away", which is what made #570 a
data-integrity bug rather than a reporting one. It is fidelity, not the source of
the tests' discriminating power, and this app's harness isolates by *deletion*
rather than rollback, so the committed rows are still drained at teardown
(measured: 0 rows matching ``procurios_id LIKE 'P570-%'`` after a full run).

## The controls

Every assertion below that something is *absent* is paired with one that
something is *present*, because "no Member found" is equally consistent with the
fix working and with the import having quietly stopped inserting anything:

* ``test_control_a_clean_row_is_imported_and_is_still_there`` -- an
  uninjured row really is created and really does persist past the same commit.
* ``test_a_mixed_batch_reports_exactly_the_members_that_persist`` -- one failing
  and one succeeding row in a single batch, so a fix that rolled back *both*
  would be caught.
* ``test_control_a_genuine_duplicate_is_skipped_and_adds_nothing`` -- the
  outcome that always was a true skip stays one, and the pre-existing member it
  collided with is not taken down with it.

The fault is injected by swapping a module attribute (``resolve_non_group_customer_group``)
rather than by mocking the unit under test, matching
``test_customer_creation_failure_survives_member_insert``: the Member insert, the
``after_insert`` hook and the real Customer/Contact creation all run.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.member.test_member_import import _create_stub_member_import_doc
from verenigingen.tests.support.customer_creation_faults import (
    BROKEN_CUSTOMER_GROUP,
    break_customer_group,
    break_customer_group_after_eating_the_savepoints,
)
from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor


class _MemberImportRowBase(EnhancedTestCase):
    """Drives the real background-import path against hand-built mapped rows."""

    def setUp(self):
        super().setUp()
        self.import_doc = _create_stub_member_import_doc()
        self.tag = frappe.generate_hash(length=10)

    # --------------------------------------------------------------- rows

    def _row(self, row_number=1, with_email=True, member_id=None):
        """One mapped row in the shape ``_validate_and_map_data`` produces.

        ``with_email=False`` is not a convenience: ``after_insert`` only attempts
        Customer creation ``if not self.customer and self.email``, so an
        email-less row is a row the injected fault cannot reach. That is what
        makes a mixed batch possible with a single site-wide fault.
        """
        marker = f"{self.tag}-{row_number}"
        row = {
            "row_number": row_number,
            "member_id": member_id if member_id is not None else f"MI570-{marker}",
            "procurios_id": f"P570-{marker}",
            "first_name": "Import570",
            "last_name": marker,
            "procurios_data": [],
            "addresses": [],
        }
        if with_email:
            row["email"] = f"import570.{marker}@test.invalid"
        return row

    # ------------------------------------------------------------ running

    def _run_import(self, rows):
        """Exactly what ``process_import_background`` does, minus the CSV read.

        ``batch_commit=True`` is the production setting (``process_import_background``)
        and is the whole point: it is the commit that makes a failed row durable.
        """
        processor = CSVImportBackgroundProcessor(self.import_doc.name, "Member Import")
        processor.load_import_doc()
        return processor.process_import(
            data_rows=rows,
            process_row_callback=self.import_doc._process_single_member,
            finalize_callback=self.import_doc._finalize_import_results,
            batch_size=50,
            batch_commit=True,
        )

    # ----------------------------------------------------------- querying

    def _members_from_this_import(self):
        """Every Member row this test's import actually left in the database."""
        return frappe.get_all(
            "Member",
            filters={"procurios_id": ["like", f"P570-{self.tag}-%"]},
            fields=["name", "procurios_id"],
            order_by="procurios_id asc",
        )

    def _reported_counts(self):
        """What the operator is shown, read back from the persisted import doc."""
        self.import_doc.reload()
        return (self.import_doc.members_created, self.import_doc.members_skipped)


class TestMemberImportRowAtomicity(_MemberImportRowBase):
    def test_a_row_reported_skipped_leaves_no_member_behind(self):
        """The report and the database must not disagree.

        Before the fix this read ``members in database: 1`` against a report of
        ``created 0 / skipped 1`` -- the row was committed and reported away.
        """
        self.expectErrorLog(
            "Customer Creation Error",
            "customer_handling Error",
            "Customer Contact Creation Error",
        )
        break_customer_group(self)

        result = self._run_import([self._row(1)])

        self.assertEqual((result["created"], result["skipped"]), (0, 1), result)
        self.assertEqual(self._reported_counts(), (0, 1))
        self.assertEqual(
            self._members_from_this_import(),
            [],
            "a row the import reports as not imported must not be in the database",
        )

    def test_the_reason_reaches_the_operator(self):
        """A rolled-back row is useless to the operator without the reason.

        Not a #570 test: this passed before the fix too, because the old handler
        appended the same sanitized reason. It is here as a guard on
        ``_rejected_row_message`` -- the function that now composes that line
        could drop the reason while every other test stayed green.
        """
        self.expectErrorLog(
            "Customer Creation Error",
            "customer_handling Error",
            "Customer Contact Creation Error",
        )
        break_customer_group(self)

        self._run_import([self._row(1)])

        self.import_doc.reload()
        self.assertIn("Row 1", self.import_doc.error_log or "")
        self.assertIn(BROKEN_CUSTOMER_GROUP, self.import_doc.error_log or "")

    def test_control_a_clean_row_is_imported_and_is_still_there(self):
        """Without this, "no Member found" above would also pass if the importer
        had stopped inserting anything at all."""
        result = self._run_import([self._row(1)])

        self.assertEqual((result["created"], result["skipped"]), (1, 0), result)
        self.assertEqual(self._reported_counts(), (1, 0))
        self.assertEqual(len(self._members_from_this_import()), 1)

    def test_a_mixed_batch_reports_exactly_the_members_that_persist(self):
        """One failing row and one succeeding row share a batch and a commit.

        This is the report-versus-database claim stated directly: the number the
        operator is shown as created equals the number of Member rows the import
        left behind, and they are the same rows. A fix that rolled the whole
        batch back would report (1, 1) against an empty database and fail here.
        """
        self.expectErrorLog(
            "Customer Creation Error",
            "customer_handling Error",
            "Customer Contact Creation Error",
        )
        break_customer_group(self)

        result = self._run_import(
            [self._row(1, with_email=True), self._row(2, with_email=False)]
        )

        self.assertEqual((result["created"], result["skipped"]), (1, 1), result)
        self.assertEqual(self._reported_counts(), (1, 1))

        persisted = self._members_from_this_import()
        self.assertEqual(
            [row.procurios_id for row in persisted],
            [f"P570-{self.tag}-2"],
            "only the row reported created may be in the database",
        )

    def test_a_row_that_could_not_be_rolled_back_says_so_and_names_the_member(self):
        """The residual case, where a savepoint alone would still leave a false report.

        A rollback to a savepoint a nested commit already took does nothing, and
        ``rollback_to_savepoint`` reports that by returning False rather than by
        raising 1305 over the real error. Reporting the row as "not imported"
        anyway would restore exactly the divergence #570 is about, so the surviving
        Member is named instead.

        Deliberately not asserted: that the Member is gone. It is not, and that is
        the point of this test.
        """
        self.expectErrorLog(
            "Customer Creation Error",
            "customer_handling Error",
            "Customer Contact Creation Error",
            "Savepoint rollback skipped",
        )
        break_customer_group_after_eating_the_savepoints(self)

        result = self._run_import([self._row(1)])

        self.assertEqual((result["created"], result["skipped"]), (0, 1), result)
        self.assertEqual(
            len(self._members_from_this_import()),
            1,
            "premise of this test: with the savepoint gone the row is still written",
        )
        self.import_doc.reload()
        surviving = self._members_from_this_import()[0].name
        self.assertIn("could NOT be rolled back", self.import_doc.error_log or "")
        self.assertIn(surviving, self.import_doc.error_log or "")

    def test_a_member_name_with_no_row_is_not_reported_as_a_survivor(self):
        """The other half of ``_rejected_row_message``, and it is not symmetric.

        ``member_doc.name`` is assigned in ``set_new_name``, BEFORE ``db_insert()``.
        Measured on test_site_4: a duplicate ``member_id`` raises
        ``UniqueValidationError`` with ``dup.name == 'Assoc-Member-2026-08-15520'``
        while ``frappe.db.exists(...)`` is None. So a rejected row routinely hands
        this function a member NAME with no row behind it, and without the
        existence check the importer would tell the operator to go and review a
        Member that was never written -- #570's divergence pointing the other way,
        produced by the function added to prevent it.

        Driven directly rather than through an import, and deliberately so: the
        end-to-end route needs ``rolled_back`` False AND a missing row, i.e. a
        nested commit landing between the savepoint and a failing insert. Nothing
        in this app's Member insert path commits there, so the honest test of the
        guard is the guard. The reachable half is covered end-to-end by
        ``test_a_row_that_could_not_be_rolled_back_says_so_and_names_the_member``,
        which is the control for this one: same ``rolled_back=False``, row present,
        and it must name the member.
        """
        orphan = frappe.new_doc("Member")
        orphan.name = f"Assoc-Member-2026-08-{self.tag}"
        self.assertFalse(frappe.db.exists("Member", orphan.name), "premise: no such row")

        message = self.import_doc._rejected_row_message(
            {"row_number": 7}, "Duplicate member_id X", orphan, rolled_back=False
        )

        self.assertEqual(message, "Row 7: Duplicate member_id X")

    def test_a_rejected_duplicate_does_not_consume_a_member_number(self):
        """Why the duplicate branch rolls back at all -- it undoes a real write.

        ``Member.autoname`` is ``format:Assoc-Member-{YYYY}-{MM}-{####}``, and
        ``{####}`` increments the shared ``tabSeries`` row named '' inside
        ``set_new_name``, BEFORE ``db_insert()``. InnoDB rolls back only the failed
        statement, so that increment SURVIVES the constraint violation. Measured on
        test_site_4: 15519 -> 15520 on the failed insert, back to 15519 after
        ``ROLLBACK TO SAVEPOINT``.

        So without this rollback every rejected row burns a member number, and
        re-running a mostly-duplicate import advances the series by the size of the
        file. The rows here are email-less on purpose: that skips Customer/Contact
        creation, which is the only other thing in the row that could touch a
        naming series between the two members being compared.
        """
        first = self._run_import([self._row(1, with_email=False)])
        self.assertEqual(first["created"], 1, first)
        planted = self._members_from_this_import()[0].name

        rejected = self._run_import([self._row(2, with_email=False, member_id=f"MI570-{self.tag}-1")])
        self.assertEqual((rejected["created"], rejected["skipped"]), (0, 1), rejected)

        third = self._run_import([self._row(3, with_email=False)])
        self.assertEqual(third["created"], 1, third)

        numbers = sorted(int(row.name.rsplit("-", 1)[-1]) for row in self._members_from_this_import())
        self.assertEqual(
            numbers,
            [int(planted.rsplit("-", 1)[-1]), int(planted.rsplit("-", 1)[-1]) + 1],
            "the rejected row gave its member number back, so the next row reuses it",
        )

    def test_control_a_genuine_duplicate_is_skipped_and_adds_nothing(self):
        """``member_id`` is unique, so a repeated one always was a true skip.

        The control on the control: the member it collided with must still be
        there afterwards, so "skipped and nothing added" is not satisfied by a
        rollback that ate the pre-existing row too.
        """
        first = self._run_import([self._row(1)])
        self.assertEqual(first["created"], 1, first)
        existing = self._members_from_this_import()[0]

        duplicate = self._row(2, member_id=f"MI570-{self.tag}-1")
        second = self._run_import([duplicate])

        self.assertEqual((second["created"], second["skipped"]), (0, 1), second)
        self.assertEqual(
            [row.name for row in self._members_from_this_import()],
            [existing.name],
            "a duplicate must add nothing and remove nothing",
        )
        self.import_doc.reload()
        self.assertIn("Duplicate member_id", self.import_doc.error_log or "")
