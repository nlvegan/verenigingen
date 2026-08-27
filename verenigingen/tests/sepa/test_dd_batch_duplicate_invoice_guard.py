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

        with self.assertRaises(frappe.ValidationError):
            batch.insert()

    def test_three_rows_for_one_invoice_name_the_row_numbers(self):
        """The operator has to find the rows to delete, so the refusal names them."""
        row = self._member_mandate_row()
        batch = self._unsaved_batch([row, row, row])

        with self.assertRaises(frappe.ValidationError) as ctx:
            batch.validate_no_duplicate_invoices()

        message = str(ctx.exception)
        self.assertIn("1", message)
        self.assertIn("2", message)
        self.assertIn("3", message)

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


class TestTheGuardCannotStrandAnExistingBatch(_DuplicateInvoiceBase):
    """A batch created before the guard must stay serviceable.

    `sepa_batch_processor.process_sepa_return_file` and
    `dd_batch_api.apply_conflict_resolutions` both LOAD an existing batch and call
    `save()` on it. If the guard fired there, a pre-guard batch holding a duplicate
    could never have its bank returns recorded -- a worse outcome than the duplicate
    itself, since the money has already moved.

    It does not, because `Direct Debit Batch` is submittable and Frappe runs
    `validate` only for `_action in ("save", "submit")`; an update to a SUBMITTED
    document runs `before_update_after_submit` instead. Measured here rather than
    reasoned from that source: the duplicate row is planted directly in the DB under
    a submitted batch, and the save is asserted to succeed.

    Census taken 2026-08-27 for the remaining Draft case: zero `Direct Debit Batch
    Invoice` rows duplicate an invoice on veg11 or on test_site_1/2/3/5, and zero
    rows have an empty `mandate_reference`. That bounds those five sites, not every
    install.
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
        clone = frappe.copy_doc(frappe.get_doc("Direct Debit Batch Invoice", batch.invoices[0].name))
        clone.name = None
        clone.idx = 99
        clone.db_insert()
        batch.reload()
        listed = [child.invoice for child in batch.invoices]
        self.assertEqual(len(listed), 2)
        self.assertEqual(len(set(listed)), 1)  # the duplicate really is there

        batch.status = "Partially Failed"  # allow_on_submit
        batch.save()  # must NOT raise

        batch.reload()
        self.assertEqual(batch.status, "Partially Failed")
