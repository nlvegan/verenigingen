"""`dd_batch_api` conflict resolution: what the remedy actually does to the money.

**#613** -- `consolidate_entries` grouped a batch's child rows by `mandate_reference`
and summed the group into its first row. Two rows naming ONE invoice therefore became
one row at 2x, so the double debit became a single double-sized debit -- and the batch
then satisfied `validate_no_duplicate_invoices` (#606), because there really was one
row per invoice afterwards. The remedy offered for a duplicate produced the defect the
guard exists to catch, in a shape the guard cannot see.

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
            fields=["name", "invoice", "amount"],
            order_by="idx asc",
        )


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
        self.assertIn("disagree about the amount", outcome["message"])
        self.assertIn("25.0", outcome["message"])
        self.assertIn("40.0", outcome["message"])
        self.assertEqual(len(self._batch_rows(batch.name)), 2)
        self.assertFalse(result["batch_updated"])

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
        self.assertTrue(offered, "the fixture must actually produce conflicts")
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
