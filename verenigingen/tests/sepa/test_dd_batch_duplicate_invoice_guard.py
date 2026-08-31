"""A Direct Debit Batch must not list the same Sales Invoice twice (#606).

Every `Direct Debit Batch Invoice` child row becomes one transaction in the SEPA
XML, so two rows for one invoice are two debits of one member's account for one
debt. Before this guard nothing between "a query returned two rows for one
invoice" and "the member is debited twice" rejected the duplicate:

- `DirectDebitBatch.validate` never compared the rows to each other;
- `batch_processing_service.validate_batch_invoices_optimized` validates each row's
  Sales Invoice in isolation (customer, amount, currency, status) and is blind to
  the row set as a whole -- `test_validate_invoices_is_blind_to_a_duplicate` is the
  control that measures this, and it is also why the old comment in
  `validate_sequence_types` claiming `validate_invoices` catches a missing
  `mandate_reference` was wrong;
- `batch_performance_optimizer.process_batch_invoices_optimized` iterates its
  `invoice_names` argument as a list;
- `dd_batch_optimizer`'s `processed_invoices` set removes invoices already claimed
  by an EARLIER batching strategy, never duplicates within one group.

The fixtures here build the duplicate the way the pipeline would: two child rows
carrying the same `invoice`, both otherwise complete and valid. No
`frappe.db.set_value` bypass is involved -- the state was reachable through an
ordinary `save()`, which is the point.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.sepa.test_dd_batch_pipeline_coverage import _BatchPipelineBase


class _DuplicateInvoiceBase(_BatchPipelineBase):
    def _unsaved_batch(self, rows, automated=False):
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = f"dup-guard {frappe.generate_hash(length=6)}"
        batch.batch_type = "CORE"
        batch.sequence_type = "FRST"
        batch.currency = "EUR"
        batch.status = "Draft"
        if automated:
            batch._automated_processing = True
        for row in rows:
            batch.append("invoices", dict(row))
        return batch

    def _member_mandate_row(self, amount=25.0, birth_date="1990-01-01"):
        member = self._member_with_membership(birth_date)
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _invoice, row = self._invoice_row(member, mandate, amount)
        return row


class TestDuplicateInvoiceRejected(_DuplicateInvoiceBase):
    def test_the_same_invoice_twice_is_rejected_on_insert(self):
        """The whole point: a batch listing one invoice twice must not persist."""
        row = self._member_mandate_row()
        batch = self._unsaved_batch([row, row])

        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.insert()

        message = str(ctx.exception)
        self.assertIn(row["invoice"], message)
        self.assertIn("more than once", message.lower())

    def test_duplicate_is_rejected_in_automated_processing_too(self):
        """`_automated_processing` downgrades sequence-type criticals to a recorded
        `validation_status`, which `handle_automated_batch_validation` then acts on.
        A duplicate must NOT take that route: `dd_batch_optimizer.create_dd_batch_document`
        inserts the batch and never reads `validation_status`, so a recorded-but-not-thrown
        duplicate would still be collected."""
        row = self._member_mandate_row()
        batch = self._unsaved_batch([row, row], automated=True)

        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.insert()

        # Assert the reason, not just the exception type: ValidationError is what
        # every other guard on this document throws too, so a bare assertRaises
        # would be satisfied by an unrelated refusal.
        self.assertIn("more than once", str(ctx.exception).lower())

    def test_three_rows_for_one_invoice_name_the_row_numbers(self):
        """The operator has to find the rows to delete, so the refusal names them."""
        row = self._member_mandate_row()
        batch = self._unsaved_batch([row, row, row])

        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.validate_no_duplicate_invoices()

        # Assert the rendered list, not the digits: an invoice name such as
        # ACC-SINV-2026-00123 contains "1", "2" and "3" on its own, so digit-wise
        # assertions would pass with the row numbers removed entirely.
        self.assertIn("rows 1, 2, 3", str(ctx.exception))

    def test_distinct_invoices_still_pass(self):
        """The control. Without it, a guard that rejected EVERY batch would pass
        every other test in this class."""
        row_a = self._member_mandate_row(25.0, "1990-01-01")
        row_b = self._member_mandate_row(35.0, "1991-02-02")
        batch = self._unsaved_batch([row_a, row_b])

        batch.insert()
        self._track("Direct Debit Batch", batch.name)

        self.assertEqual(len(batch.invoices), 2)
        self.assertEqual(batch.entry_count, 2)
        self.assertEqual(batch.total_amount, 60.0)


class TestValidateInvoicesIsBlindToTheDuplicate(_DuplicateInvoiceBase):
    """The control for WHY the guard has to live on the batch document.

    `validate_batch_invoices_optimized` was the function the old
    `validate_sequence_types` comment named as the one that "catches" bad rows. It
    validates each row's Sales Invoice on its own, so it reports a duplicated
    invoice as two perfectly valid rows -- and never reads `mandate_reference` at
    all. These two tests measure that directly; if either ever fails, the guard
    added on the batch has become redundant and this module should say so.

    Narrowly: the duplicate case pins that the SERVICE's per-row loop is blind,
    not that the whole call chain is. A dedup inserted at the service's
    `invoice_names = [i.invoice for i in batch_doc.invoices]` line would leave
    this green, because the bulk lookup still resolves on both iterations of the
    loop over `batch_doc.invoices`. What it does catch is a dedup of
    `batch_doc.invoices` itself, which is the shape that would make the batch-level
    guard unreachable.
    """

    def test_validate_invoices_is_blind_to_a_duplicate(self):
        row = self._member_mandate_row()
        batch = self._unsaved_batch([row, row])

        result = self.service.validate_batch_invoices_optimized(batch)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["valid_invoices"], 2)
        self.assertEqual(result["total_invoices"], 2)

    def test_validate_invoices_is_blind_to_a_missing_mandate_reference(self):
        row = self._member_mandate_row()
        row["mandate_reference"] = None
        batch = self._unsaved_batch([row])

        result = self.service.validate_batch_invoices_optimized(batch)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["valid_invoices"], 1)
        self.assertEqual(result["errors"], [])


class TestMissingMandateReferenceIsCritical(_DuplicateInvoiceBase):
    """A batch row with no mandate reference cannot be collected.

    The SEPA XML has no `MndtId` to present for it, and
    `validate_batch_invoices_optimized` -- which the old comment claimed caught
    this -- never reads the field (measured above). So it is a critical error,
    handled through the same automated/manual split as every other critical error
    in `validate_sequence_types`.

    Both tests call `validate_sequence_types()` DIRECTLY, and that is deliberate,
    because the state is not reachable through `save()`: `mandate_reference` is
    `reqd: 1` on Direct Debit Batch Invoice, so the insert dies on MandatoryError
    (measured) before anything reads `validation_status`. What this change buys is
    the message in the manual path, where `validate` runs before
    `_validate_mandatory` and so this error is what the operator sees. The
    recorded-critical branch is pinned here for completeness; no caller observes
    it today.
    """

    def test_manual_context_throws(self):
        row = self._member_mandate_row()
        row["mandate_reference"] = None
        batch = self._unsaved_batch([row])

        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.validate_sequence_types()

        self.assertIn(row["invoice"], str(ctx.exception))

    def test_automated_context_records_a_critical_error(self):
        row = self._member_mandate_row()
        row["mandate_reference"] = None
        batch = self._unsaved_batch([row], automated=True)

        batch.validate_sequence_types()

        self.assertEqual(batch.validation_status, "Critical Errors")
        errors = frappe.parse_json(batch.validation_errors)
        self.assertEqual([e["invoice"] for e in errors], [row["invoice"]])
        self.assertIn("mandate reference", errors[0]["issue"].lower())


class TestWhichExistingBatchesTheGuardCanStrand(_DuplicateInvoiceBase):
    """How far a pre-guard batch holding a duplicate stays serviceable. Two cases,
    and only one of them is safe.

    `sepa_batch_processor.process_batch_returns` and
    `dd_batch_api.apply_conflict_resolutions` both LOAD an existing batch and call
    `save()` on it. Bank returns for a batch that already debited twice matter more
    than the duplicate does -- the money has already moved.

    SUBMITTED (docstatus 1): safe. Frappe runs `validate` only for
    `_action in ("save", "submit")`; an update to a submitted document runs
    `before_update_after_submit` instead. Measured below rather than reasoned from
    that source, by planting the duplicate row directly in the child table.

    DRAFT (docstatus 0): NOT safe, and this is a known gap rather than an oversight.
    `validate` does run, so the guard fires and those calls fail. It matters because
    the automated pipelines never submit: measured on veg11 2026-08-27, 11 of 29
    batches are docstatus 0 and 6 of those are in status "Generated" -- the SEPA file
    was produced and the document was never submitted. `dd_batch_workflow_controller.
    reject_batch` is affected the same way: it saves before its `db_set`, so the
    operator's remedy path would be blocked too.

    What bounds the gap is that no such batch exists to strand. Census 2026-08-27:
    zero `Direct Debit Batch Invoice` rows duplicate an invoice on veg11 or on
    test_site_1/2/3/5, and zero rows have an empty `mandate_reference` -- and after
    this guard none can be created. That bounds those five sites, not every install.
    """

    def test_a_submitted_batch_with_a_planted_duplicate_still_saves(self):
        row = self._member_mandate_row()
        batch = self._unsaved_batch([row])
        # Declare the SEPA file already produced so submit() does not run
        # generate_sepa_xml(); this test is about WHICH lifecycle methods run on a
        # submitted document, not about XML generation.
        batch.sepa_file_generated = 1
        batch.insert()
        self._track("Direct Debit Batch", batch.name)
        batch.submit()
        self.assertEqual(batch.docstatus, 1)

        # Plant the duplicate the way a pre-guard batch would already hold it:
        # straight into the child table, bypassing the parent document.
        self._plant_duplicate_row(batch.invoices[0].name)
        batch.reload()
        listed = [child.invoice for child in batch.invoices]
        self.assertEqual(len(listed), 2)
        self.assertEqual(len(set(listed)), 1)  # the duplicate really is there

        batch.status = "Partially Failed"  # allow_on_submit
        batch.save()  # must NOT raise

        batch.reload()
        self.assertEqual(batch.status, "Partially Failed")

    def test_a_draft_batch_with_a_planted_duplicate_can_no_longer_be_saved(self):
        """The gap, pinned so it is a decision rather than a surprise.

        A DRAFT batch runs `validate` on save, so a duplicate that predates the
        guard blocks every later save of that batch -- including
        `process_batch_returns` and `reject_batch`. If this ever needs to change,
        this test is the one to change, and the message it asserts is what an
        operator would see.
        """
        row = self._member_mandate_row()
        batch = self._unsaved_batch([row])
        batch.insert()
        self._track("Direct Debit Batch", batch.name)
        self.assertEqual(batch.docstatus, 0)

        clone = frappe.copy_doc(frappe.get_doc("Direct Debit Batch Invoice", batch.invoices[0].name))
        clone.name = None
        clone.idx = 99
        clone.db_insert()
        batch.reload()

        batch.status = "Failed"
        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.save()
        self.assertIn(row["invoice"], str(ctx.exception))
