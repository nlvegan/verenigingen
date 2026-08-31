"""`dd_batch_api` conflict resolution: what the remedy actually does to the money.

**#626** -- `consolidate_entries` merged DISTINCT invoices. A member with two unpaid
invoices on one mandate is the ordinary case, and merging those two rows leaves one
child row naming only the first invoice. The SEPA XML then debits the sum, while
`batch_processing_service.mark_batch_invoices_as_paid` iterates the surviving child
rows and creates a Payment Entry per row -- so the deleted row's invoice gets none,
keeps its outstanding amount, and stays Unpaid with its money already taken.
`get_batch_conflicts` is what put that remedy in front of the operator, by reporting
"Mandate X appears 2 times in batch" as a conflict.

**#613** -- `consolidate_entries` grouped a batch's child rows by `mandate_reference`
and summed the group into its first row. Two rows naming ONE invoice therefore became
one row at 2x, so the double debit became a single double-sized debit -- and the batch
then satisfied `validate_no_duplicate_invoices` (#606), because there really was one
row per invoice afterwards. The remedy offered for a duplicate produced the defect the
guard exists to catch, in a shape the guard cannot see.

**#614** -- the child rows are deleted one at a time and the parent is saved
afterwards. `@handle_api_error` turns a throw from that save into a returned failure,
the request ends normally, and Frappe commits the deletions: the caller is told it
failed and the rows are gone.

**#615** -- `get_batch_conflicts` offered `exclude_duplicates` as a remedy and
`apply_conflict_resolutions` had no branch for it, nor any `else`. Selecting it left
`success` False with an EMPTY message inside an overall `{"success": True}` response,
so the operator's client reported the remedy as applied. `update_iban` is the sibling
the issue does not name: it is offered for every IBAN-flavoured failure and also had
no branch, so an operator correcting a wrong account number was told it worked while
the batch went on debiting the old one.

The same false report is reachable through remedies that DO have a branch, so those
are covered too: `frappe.delete_doc` defaults to `ignore_missing=True`, and nothing
tied a resolution's `entry_id` to the endpoint's `batch_id`.

## How the money consequence is measured here

Not by row counts. The tests assert the invariant that makes a batch collectable:

    sum(child row amounts)  ==  sum(outstanding of the invoices those rows name)

The left side is what the SEPA XML debits (one transaction per child row); the right
side is what `mark_batch_invoices_as_paid` can reconcile (one Payment Entry per row,
built from the row's Sales Invoice, for that invoice's own outstanding amount).

`mark_batch_invoices_as_paid` itself is NOT driven here, for the reason
`test_dd_batch_pipeline_coverage` already documents: it needs a submitted batch and
creates and submits real Payment Entries, whose commits leak across the shared shard.
So reconcilability is measured as "every euro debited is named by a row the
reconciliation loop will visit", which is the property that loop depends on -- not as
an observed Payment Entry.

## Building the duplicate

`DirectDebitBatch.validate_no_duplicate_invoices` (#606) rejects a batch listing one
invoice twice, so that state can no longer be reached through `save()`. It is planted
with `_plant_duplicate_row` (a `db_insert()` straight into the child table), which is
how a pre-guard batch already holds it -- and such a batch cannot be saved at all
until the duplicate is gone, which is why a repair path matters.
"""

import frappe
from frappe.utils import flt

from verenigingen.tests.sepa.test_dd_batch_pipeline_coverage import _BatchPipelineBase
from verenigingen.verenigingen_payments.api.dd_batch_api import (
    _resolution_outcome,
    apply_conflict_resolutions,
    get_batch_conflicts,
)


class _ConflictResolutionBase(_BatchPipelineBase):
    """A member with one Active mandate and N invoices, plus the money invariant."""

    def _batch_for_one_member(self, amounts):
        """Insert a batch holding one row per amount, all on one member/mandate."""
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        rows = [self._invoice_row(member, mandate, amount)[1] for amount in amounts]
        return self._persisted_batch(rows), member, mandate

    def _debited_vs_reconcilable(self, batch_name):
        """(what the SEPA XML collects, what the reconciliation loop can settle).

        Equal on a collectable batch. They diverge exactly when a row's amount no
        longer corresponds to the invoice that row names.
        """
        rows = frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"parent": batch_name},
            fields=["invoice", "amount"],
        )
        debited = sum(flt(row.amount) for row in rows)
        reconcilable = sum(
            flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount"))
            for invoice in {row.invoice for row in rows}
        )
        return debited, reconcilable

    def _batch_rows(self, batch_name):
        return frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"parent": batch_name},
            fields=["name", "invoice", "amount", "iban", "mandate_reference"],
            order_by="idx asc",
        )


class TestDistinctInvoicesAreNeverMerged(_ConflictResolutionBase):
    """#626: two invoices for one member are two debts and stay two debits."""

    def test_two_invoices_on_one_mandate_survive_consolidation_separately(self):
        batch, _member, mandate = self._batch_for_one_member([25.0, 30.0])
        debited_before, reconcilable_before = self._debited_vs_reconcilable(batch.name)
        self.assertEqual(debited_before, 55.0)
        self.assertEqual(reconcilable_before, 55.0)

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "mandate_reference": mandate.mandate_id}]
        )

        # The money first, because it is the claim. Before the fix this read
        # (55.0, 25.0): the batch debited 55 while only the surviving row's
        # invoice -- 25 of it -- could ever be reconciled, leaving 30 euro
        # collected against an invoice that stays Unpaid.
        debited, reconcilable = self._debited_vs_reconcilable(batch.name)
        self.assertEqual((debited, reconcilable), (55.0, 55.0))

        rows = self._batch_rows(batch.name)
        self.assertEqual(sorted(flt(row.amount) for row in rows), [25.0, 30.0])
        self.assertEqual(len({row.invoice for row in rows}), 2)

        # And the remedy refuses, and says why. Before the fix it reported
        # "Consolidated 2 entries into one" and returned success.
        outcome = result["resolution_results"][0]
        self.assertFalse(outcome["success"], outcome["message"])
        self.assertIn("Nothing to consolidate", outcome["message"])

    def test_a_refusal_leaves_the_batch_untouched_and_says_so(self):
        """`applied`/`batch_updated` must not claim a change the refusal did not make.

        The stale `entry_count` is what makes this discriminating: an unconditional
        parent save would recalculate it back to 2, so only a run that really skips
        the save leaves the planted 99 in place.
        """
        batch, _member, mandate = self._batch_for_one_member([25.0, 30.0])
        frappe.db.set_value("Direct Debit Batch", batch.name, "entry_count", 99, update_modified=False)

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "mandate_reference": mandate.mandate_id}]
        )

        self.assertTrue(result["success"], "the request itself was processed")
        self.assertFalse(result["applied"])
        self.assertFalse(result["batch_updated"])
        batch.reload()
        self.assertEqual(batch.entry_count, 99, "a refusal must not save the parent")
        self.assertEqual(flt(batch.total_amount), 55.0)

    def test_two_invoices_on_one_mandate_are_not_reported_as_a_conflict(self):
        """The trap at its source: reporting the ordinary case as a conflict is
        what put "consolidate" in front of an operator in the first place."""
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])

        conflicts = get_batch_conflicts(batch.name)["conflicts"]

        self.assertEqual(conflicts, [])

    def test_the_control_a_genuinely_duplicated_invoice_still_is_one(self):
        """Without this, deleting the duplicate detection entirely would pass the
        test above."""
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])
        duplicated_invoice = batch.invoices[0].invoice
        self._plant_duplicate_row(batch.invoices[0].name)

        conflicts = get_batch_conflicts(batch.name)["conflicts"]

        duplicate_conflicts = [c for c in conflicts if c["type"] == "duplicate_invoice"]
        self.assertEqual(len(duplicate_conflicts), 1)
        self.assertEqual(duplicate_conflicts[0]["invoice"], duplicated_invoice)
        self.assertEqual(duplicate_conflicts[0]["count"], 2)


class TestDuplicateRowsForOneInvoiceAreDeduplicated(_ConflictResolutionBase):
    """#613: the remedy for a duplicate must not double the debit instead."""

    def test_a_duplicated_invoice_becomes_one_debit_at_the_invoice_amount(self):
        batch, _member, mandate = self._batch_for_one_member([25.0])
        self._plant_duplicate_row(batch.invoices[0].name)
        batch.reload()
        self.assertEqual(len(batch.invoices), 2)
        # Both rows name one invoice, so 50 would be debited for a 25 debt.
        debited_before, reconcilable_before = self._debited_vs_reconcilable(batch.name)
        self.assertEqual(debited_before, 50.0)
        self.assertEqual(reconcilable_before, 25.0)

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "mandate_reference": mandate.mandate_id}]
        )

        # The money first. Summing was the defect: each duplicate row already
        # carries the whole invoice amount, so the sum is a single double-sized
        # debit -- which also passes validate_no_duplicate_invoices, because there
        # really is one row per invoice afterwards.
        debited, reconcilable = self._debited_vs_reconcilable(batch.name)
        self.assertEqual((debited, reconcilable), (25.0, 25.0))

        rows = self._batch_rows(batch.name)
        self.assertEqual([flt(row.amount) for row in rows], [25.0])

        outcome = result["resolution_results"][0]
        self.assertTrue(outcome["success"], outcome["message"])
        self.assertIn("Removed 1 duplicate row", outcome["message"])

        # And it persists past the parent save (the #621 regression: a stale
        # in-memory batch.save() used to revert the child-row edits).
        batch.reload()
        self.assertEqual(batch.entry_count, 1)
        self.assertEqual(flt(batch.total_amount), 25.0)

    def test_duplicates_that_disagree_about_the_amount_are_refused_not_guessed(self):
        """The control for the refusal: rows that agree ARE removed (test above),
        rows that disagree are left alone rather than resolved arbitrarily.

        The refusal message has to reach the operator, which is why the endpoint
        skips the parent save when nothing was applied: this batch still holds the
        duplicate, so saving it would raise #606's guard and that ValidationError
        would be the only thing the caller ever saw.
        """
        batch, _member, mandate = self._batch_for_one_member([25.0])
        self._plant_duplicate_row(batch.invoices[0].name, amount=40.0)

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "mandate_reference": mandate.mandate_id}]
        )

        outcome = result["resolution_results"][0]
        self.assertFalse(outcome["success"])
        self.assertIn("disagree about what to debit", outcome["message"])
        self.assertIn("amount: 25.0, 40.0", outcome["message"])
        self.assertEqual(len(self._batch_rows(batch.name)), 2)
        self.assertFalse(result["applied"])

    def test_duplicates_naming_two_different_mandates_are_refused_too(self):
        """The canonical duplicate names TWO accounts, and the amounts AGREE.

        #597/#604 measured how the pair arises: a member holding a membership
        mandate and a donation mandate made the eligible-invoice join return one row
        per Active mandate, both carrying `si.outstanding_amount` but each carrying
        its own `sm.mandate_id`/`sm.iban`. An amount-only refusal never fires here,
        so de-duplicating would keep whichever row sorted first and collect a
        membership debt on whichever account that happened to be -- the
        mandate-purpose violation #604/#605/#606 exist to prevent.
        """
        batch, _member, mandate = self._batch_for_one_member([25.0])
        original = self._batch_rows(batch.name)[0]
        self._plant_duplicate_row(
            batch.invoices[0].name,
            mandate_reference="TST-DONATION-MANDATE",
            iban="NL39RABO0300065264",
        )

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "invoice": original.invoice}]
        )

        outcome = result["resolution_results"][0]
        self.assertFalse(outcome["success"])
        self.assertIn("disagree about what to debit", outcome["message"])
        self.assertIn("mandate_reference", outcome["message"])
        self.assertIn("TST-DONATION-MANDATE", outcome["message"])
        self.assertIn("iban", outcome["message"])
        self.assertEqual(len(self._batch_rows(batch.name)), 2)

    def test_a_mandate_scope_still_sees_a_duplicate_that_names_another_mandate(self):
        """The mandate scope chooses which INVOICES to repair, not which rows.

        Filtering the rows on `mandate_reference` returns one row of the pair, and
        the endpoint would then report "one row per invoice, each once" about a
        batch that holds two and cannot be saved at all.
        """
        batch, _member, mandate = self._batch_for_one_member([25.0])
        self._plant_duplicate_row(
            batch.invoices[0].name,
            mandate_reference="TST-DONATION-MANDATE",
            iban="NL39RABO0300065264",
        )

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "mandate_reference": mandate.mandate_id}]
        )

        outcome = result["resolution_results"][0]
        self.assertNotIn(
            "each once",
            outcome["message"],
            "the batch holds two rows for one invoice; saying otherwise is false",
        )
        self.assertIn("disagree about what to debit", outcome["message"])

    def test_the_surviving_row_keeps_the_account_the_duplicates_agreed_on(self):
        """Which row survives is only immaterial because every debit-deciding field
        is identical by then. Pin that, so a change that starts picking a row
        without that guarantee is visible."""
        batch, _member, mandate = self._batch_for_one_member([25.0])
        original = self._batch_rows(batch.name)[0]
        self._plant_duplicate_row(batch.invoices[0].name)

        apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "invoice": original.invoice}]
        )

        rows = self._batch_rows(batch.name)
        self.assertEqual(len(rows), 1)
        survivor = frappe.get_doc("Direct Debit Batch Invoice", rows[0].name)
        self.assertEqual(survivor.mandate_reference, mandate.mandate_id)
        self.assertEqual(survivor.iban, original.iban)

    def test_consolidation_scoped_to_an_invoice_leaves_the_other_invoice_alone(self):
        """`consolidate_entries` also accepts an `invoice` scope, and it must not
        touch the rows of any other invoice on the same mandate."""
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])
        duplicated_invoice = batch.invoices[0].invoice
        self._plant_duplicate_row(batch.invoices[0].name)

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "invoice": duplicated_invoice}]
        )

        self.assertTrue(result["resolution_results"][0]["success"])
        rows = self._batch_rows(batch.name)
        self.assertEqual(sorted(flt(row.amount) for row in rows), [25.0, 30.0])
        debited, reconcilable = self._debited_vs_reconcilable(batch.name)
        self.assertEqual(debited, reconcilable)


class TestEveryOfferedRemedyIsImplemented(_ConflictResolutionBase):
    """#615: a remedy this endpoint advertises must not be a silent no-op."""

    def _batch_with_every_conflict_flavour(self):
        """One batch producing all of get_batch_conflicts' conflict shapes."""
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0, 35.0])
        failures = [
            "SEPA mandate revoked by the debtor",
            "IBAN is not valid for this debtor",
            "Bank rejected the transaction",
        ]
        for row, message in zip(batch.invoices, failures):
            frappe.db.set_value(
                "Direct Debit Batch Invoice",
                row.name,
                {"status": "Failed", "result_message": message},
                update_modified=False,
            )
        self._plant_duplicate_row(batch.invoices[0].name)
        return batch

    def test_exclude_duplicates_is_not_offered_anywhere(self):
        batch = self._batch_with_every_conflict_flavour()

        conflicts = get_batch_conflicts(batch.name)["conflicts"]

        offered = {option["action"] for conflict in conflicts for option in conflict["resolution_options"]}
        # Name the remedy the duplicate conflict must offer, not just "some options
        # were returned": the three failed-entry conflicts satisfy a bare
        # assertTrue, so deleting duplicate-invoice detection entirely would pass.
        self.assertIn("consolidate_entries", offered)
        self.assertNotIn("exclude_duplicates", offered)

    def test_every_offered_action_reaches_a_branch(self):
        """The class-level gate: a future remedy added to `resolution_options`
        without a handler reddens here rather than shipping as a silent no-op.

        Each (conflict, option) pair is applied for real and then rolled back to a
        savepoint, so the pairs do not consume one another's rows.
        """
        batch = self._batch_with_every_conflict_flavour()
        conflicts = get_batch_conflicts(batch.name)["conflicts"]
        checked = 0

        for conflict in conflicts:
            for option in conflict["resolution_options"]:
                resolution = {
                    "action": option["action"],
                    "entry_id": conflict.get("entry_id"),
                    "invoice": conflict.get("invoice"),
                    "mandate_reference": conflict.get("mandate_reference"),
                }
                save_point = f"offered_{checked}"
                frappe.db.savepoint(save_point)
                try:
                    outcome = _resolution_outcome(batch.name, resolution)
                finally:
                    frappe.db.rollback(save_point=save_point)

                self.assertTrue(outcome["message"], f"{option['action']} reported nothing")
                self.assertNotIn(
                    "Unknown resolution action",
                    outcome["message"],
                    f"{option['action']} is offered by get_batch_conflicts but has no branch",
                )
                checked += 1

        self.assertGreaterEqual(checked, 4, "the fixture must exercise several remedies")

    def test_the_control_an_unadvertised_action_is_reported_not_ignored(self):
        """Without this, `test_every_offered_action_reaches_a_branch` would pass on
        an endpoint that never emits the "Unknown resolution action" message at all.
        """
        batch, _member, _mandate = self._batch_for_one_member([25.0])

        outcome = _resolution_outcome(batch.name, {"action": "make_the_money_appear"})

        self.assertFalse(outcome["success"])
        self.assertIn("Unknown resolution action", outcome["message"])

    def test_update_iban_actually_writes_the_iban(self):
        """The sibling gap #615 names by implication: `update_iban` was offered for
        every IBAN-flavoured failure and had no branch, so an operator correcting a
        wrong account was told "success" while the batch still debited the old one.
        """
        batch, _member, _mandate = self._batch_for_one_member([25.0])
        row_name = batch.invoices[0].name
        new_iban = "NL39RABO0300065264"
        self.assertNotEqual(frappe.db.get_value("Direct Debit Batch Invoice", row_name, "iban"), new_iban)

        result = apply_conflict_resolutions(
            batch.name,
            [{"action": "update_iban", "entry_id": row_name, "new_iban": new_iban}],
        )

        self.assertTrue(result["resolution_results"][0]["success"])
        self.assertEqual(frappe.db.get_value("Direct Debit Batch Invoice", row_name, "iban"), new_iban)

    def test_manual_review_says_it_has_no_automated_remedy(self):
        batch, _member, _mandate = self._batch_for_one_member([25.0])

        outcome = _resolution_outcome(batch.name, {"action": "manual_review"})

        self.assertFalse(outcome["success"])
        self.assertIn("by hand", outcome["message"])


class TestAFailedResolutionLeavesNothingBehind(_ConflictResolutionBase):
    """#614: a result that says "failed" must not have committed half its work."""

    def setUp(self):
        super().setUp()
        # `@handle_api_error` writes an Error Log for every failure it converts into
        # an OperationResult, and these tests deliberately provoke that conversion.
        self.expectErrorLog("dd_batch_api: ValidationError")

    def _batch_that_cannot_be_saved(self):
        """Two collectable invoices plus a planted duplicate of the second.

        The duplicate makes every `batch.save()` throw
        (`validate_no_duplicate_invoices`), which is the condition #614 names: the
        endpoint's final save fails AFTER the child rows have already been touched.
        """
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])
        self._plant_duplicate_row(batch.invoices[1].name)
        return batch

    def test_an_excluded_row_is_still_there_when_the_batch_save_fails(self):
        batch = self._batch_that_cannot_be_saved()
        excluded = batch.invoices[0].name
        excluded_invoice = batch.invoices[0].invoice
        entry_count_before = batch.entry_count

        result = apply_conflict_resolutions(batch.name, [{"action": "exclude_entry", "entry_id": excluded}])

        # The caller is told it failed. `success` False here means the REQUEST
        # failed -- @handle_api_error's OperationResult.fail, which carries `error`
        # and no resolution_results -- and not a remedy that correctly declined,
        # which reports itself per resolution inside a success envelope.
        self.assertFalse(result["success"], result)
        self.assertIn("error", result)

        # ...and the row it was told was not excluded is still in the batch. Before
        # the savepoint the deletion was committed anyway, so this invoice silently
        # dropped out of the batch and was never collected, while entry_count and
        # total_amount still counted it.
        self.assertTrue(
            frappe.db.exists("Direct Debit Batch Invoice", excluded),
            "a failed apply_conflict_resolutions must not have deleted the row",
        )
        listed = [row.invoice for row in self._batch_rows(batch.name)]
        self.assertIn(excluded_invoice, listed)

        batch.reload()
        self.assertEqual(batch.entry_count, entry_count_before)

    def test_a_consolidation_is_undone_when_the_batch_save_fails(self):
        """The same boundary reached through the other mutating branch."""
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])
        duplicated_invoice = batch.invoices[0].invoice
        self._plant_duplicate_row(batch.invoices[0].name)
        # A SECOND, untouched duplicate keeps the parent save failing after the
        # first invoice's duplicate has been removed.
        self._plant_duplicate_row(batch.invoices[1].name)

        result = apply_conflict_resolutions(
            batch.name, [{"action": "consolidate_entries", "invoice": duplicated_invoice}]
        )

        self.assertFalse(result["success"], result)
        rows_for_invoice = [row for row in self._batch_rows(batch.name) if row.invoice == duplicated_invoice]
        self.assertEqual(len(rows_for_invoice), 2, "the removed duplicate must be back")

    def test_the_control_a_save_that_succeeds_does_apply_the_exclusion(self):
        """Without this, a change that made the endpoint apply NOTHING would pass
        every other test in this class."""
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])
        excluded = batch.invoices[0].name

        result = apply_conflict_resolutions(batch.name, [{"action": "exclude_entry", "entry_id": excluded}])

        self.assertTrue(result["success"], result)
        self.assertFalse(frappe.db.exists("Direct Debit Batch Invoice", excluded))
        batch.reload()
        self.assertEqual(batch.entry_count, 1)
        self.assertEqual(flt(batch.total_amount), 30.0)

    def test_one_failing_resolution_does_not_undo_its_siblings(self):
        """Each resolution gets its own savepoint nested inside the call's.

        A single shared savepoint would roll the successful exclusion back too when
        the second resolution throws, discarding work the caller was told succeeded.
        """
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])
        excluded = batch.invoices[0].name

        result = apply_conflict_resolutions(
            batch.name,
            [
                {"action": "exclude_entry", "entry_id": excluded},
                {"action": "exclude_entry", "entry_id": "NO-SUCH-BATCH-ROW-XYZ"},
            ],
        )

        self.assertTrue(result["success"], result)
        first, second = result["resolution_results"]
        self.assertTrue(first["success"], first["message"])
        self.assertFalse(second["success"])
        self.assertTrue(second["message"], "a failed resolution must say why")
        self.assertFalse(frappe.db.exists("Direct Debit Batch Invoice", excluded))


class TestARemedyDoesNotClaimWorkItDidNotDo(_ConflictResolutionBase):
    """#615's class reached through an IMPLEMENTED remedy rather than a missing one.

    An action with no branch reported success having done nothing. So did
    `exclude_entry` for an entry_id that does not exist, and so did one naming a
    row that belongs to a different batch -- the second was applied to that other
    batch while this batch's totals were recalculated.
    """

    def test_excluding_an_entry_that_does_not_exist_is_reported_not_claimed(self):
        """`frappe.delete_doc` defaults to ignore_missing=True, so this branch used
        to return "Entry excluded from batch" having deleted nothing."""
        batch, _member, _mandate = self._batch_for_one_member([25.0])

        result = apply_conflict_resolutions(
            batch.name, [{"action": "exclude_entry", "entry_id": "NO-SUCH-BATCH-ROW-XYZ"}]
        )

        outcome = result["resolution_results"][0]
        self.assertFalse(outcome["success"], outcome["message"])
        self.assertEqual(len(self._batch_rows(batch.name)), 1)

    def test_a_row_from_another_batch_is_refused(self):
        """The endpoint takes a batch_id and an entry_id and never checked that the
        second belonged to the first, so a resolution could delete another batch's
        row while recalculating this batch's totals."""
        batch, _member, _mandate = self._batch_for_one_member([25.0])
        other_batch, _m2, _mandate2 = self._batch_for_one_member([30.0])
        foreign_row = other_batch.invoices[0].name

        result = apply_conflict_resolutions(
            batch.name, [{"action": "exclude_entry", "entry_id": foreign_row}]
        )

        outcome = result["resolution_results"][0]
        self.assertFalse(outcome["success"])
        self.assertIn("does not belong to batch", outcome["message"])
        self.assertTrue(frappe.db.exists("Direct Debit Batch Invoice", foreign_row))

    def test_the_control_a_real_entry_is_excluded(self):
        """Without this, a change that made exclude_entry refuse everything would
        pass both tests above."""
        batch, _member, _mandate = self._batch_for_one_member([25.0, 30.0])
        excluded = batch.invoices[0].name

        result = apply_conflict_resolutions(batch.name, [{"action": "exclude_entry", "entry_id": excluded}])

        self.assertTrue(result["success"], result)
        self.assertFalse(frappe.db.exists("Direct Debit Batch Invoice", excluded))
        batch.reload()
        self.assertEqual(batch.entry_count, 1)
        self.assertEqual(flt(batch.total_amount), 30.0)
