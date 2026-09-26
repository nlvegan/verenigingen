"""A Direct Debit Batch must be refused at save if ANY invoice fails SEPA
validation, not just when EVERY invoice does (#1455).

Before this fix, ``DirectDebitBatch.validate_invoices()`` only threw when
``valid_invoices == 0`` -- a batch with 1 valid EUR invoice and 1 invalid
(non-EUR, blank-currency, zero-outstanding, ...) invoice passed ``insert()``/
``save()`` silently, with the only signal a transient ``frappe.msgprint`` and a
``batch_log`` entry that never reaches the operator because the batch persists
either way. Measured blast radius (see #1455's issue comment): SEPA XML
generation later aborts for the WHOLE batch on the first non-EUR transaction it
finds, so the realistic failure is a stuck batch -- legitimate invoices can't
be collected because of one bad row nobody was told about at save time.

Maintainer ruling (recorded on #1455, Option A): refuse the WHOLE batch at
save if ANY invoice is invalid, naming each invalid invoice and its reason.
No silent exclusion of the bad row and no silent pass-through.

Why the fixtures build the invalid invoice by mutating a REAL, otherwise-valid
Sales Invoice (``db_set``) rather than a fake invoice name: the validator this
guard depends on (``batch_processing_service.validate_batch_invoices_optimized``
-> ``InvoiceManagementUtilities.validate_invoice_for_sepa``) reads the
invoice's OWN currency/status/outstanding_amount from a bulk SQL SELECT
against ``tabSales Invoice`` -- never the Direct Debit Batch Invoice child
row's own (separately, redundantly stored) ``currency`` field. A row whose
OWN ``currency`` field says "EUR" is still caught if the underlying invoice
is not, which is exactly the shape a real producer bug or race would produce,
so that is the shape reproduced here.
"""

import frappe

from verenigingen.tests.sepa.test_dd_batch_pipeline_coverage import _BatchPipelineBase


class _MixedValidityBase(_BatchPipelineBase):
    def _valid_row(self, amount=25.0, birth_date="1990-01-01"):
        member = self._member_with_membership(birth_date)
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        invoice, row = self._invoice_row(member, mandate, amount)
        return invoice, row

    def _insert_and_expect_refusal(self, rows):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._persisted_batch(rows)
        return str(ctx.exception)


class TestMixedBatchWithNonEurInvoiceIsRefused(_MixedValidityBase):
    def test_valid_then_invalid_is_refused(self):
        """The exact shape #1455 reported: a good invoice first, a bad one
        second. Also the mutant discriminator for 'checking only the first
        invoice' -- that mutant would see a valid invoices[0] and never look
        at invoices[1], so it would NOT throw here."""
        good_invoice, good_row = self._valid_row(25.0, "1990-01-01")
        bad_invoice, bad_row = self._valid_row(35.0, "1991-02-02")
        bad_invoice.db_set("currency", "USD")

        message = self._insert_and_expect_refusal([good_row, bad_row])

        self.assertIn(bad_invoice.name, message)
        self.assertIn("Unsupported currency", message)
        self.assertNotIn(good_invoice.name, message)

    def test_invalid_then_valid_is_also_refused(self):
        """Order must not matter: the bad invoice listed first, the good one
        second."""
        bad_invoice, bad_row = self._valid_row(35.0, "1991-02-02")
        bad_invoice.db_set("currency", "USD")
        good_invoice, good_row = self._valid_row(25.0, "1990-01-01")

        message = self._insert_and_expect_refusal([bad_row, good_row])

        self.assertIn(bad_invoice.name, message)
        self.assertNotIn(good_invoice.name, message)


class TestMixedBatchWithNonCurrencyDefectIsRefused(_MixedValidityBase):
    def test_valid_plus_zero_outstanding_amount_is_refused(self):
        """The mutant discriminator for 'currency-only check': the invalid
        invoice here has a perfectly fine EUR currency, so a fix that only
        compares currency would let this batch save."""
        good_invoice, good_row = self._valid_row(25.0, "1990-01-01")
        bad_invoice, bad_row = self._valid_row(30.0, "1992-03-03")
        bad_invoice.db_set("outstanding_amount", 0)

        message = self._insert_and_expect_refusal([good_row, bad_row])

        self.assertIn(bad_invoice.name, message)
        self.assertIn("Outstanding amount must be greater than zero", message)
        self.assertNotIn(good_invoice.name, message)


class TestMixedBatchBlankCurrencyFailsClosed(_MixedValidityBase):
    def test_blank_currency_invoice_is_refused(self):
        """#1469's rule: a blank/None currency must fail CLOSED (be treated as
        invalid), never fall through as EUR-safe. Here it must also refuse the
        WHOLE batch, not just be silently excluded."""
        good_invoice, good_row = self._valid_row(25.0, "1990-01-01")
        bad_invoice, bad_row = self._valid_row(30.0, "1993-04-04")
        bad_invoice.db_set("currency", "")

        message = self._insert_and_expect_refusal([good_row, bad_row])

        self.assertIn(bad_invoice.name, message)
        self.assertNotIn(good_invoice.name, message)


class TestMinorityInvalidBatchStillRefused(_MixedValidityBase):
    def test_one_invalid_of_three_is_refused(self):
        """Mutant discriminator for 'refuse only when more than half are
        invalid': here only 1 of 3 (a minority) is invalid, so that mutant
        would NOT throw."""
        good_invoice_1, good_row_1 = self._valid_row(20.0, "1990-01-01")
        good_invoice_2, good_row_2 = self._valid_row(22.0, "1994-05-05")
        bad_invoice, bad_row = self._valid_row(24.0, "1995-06-06")
        bad_invoice.db_set("currency", "USD")

        message = self._insert_and_expect_refusal([good_row_1, good_row_2, bad_row])

        self.assertIn(bad_invoice.name, message)
        self.assertNotIn(good_invoice_1.name, message)
        self.assertNotIn(good_invoice_2.name, message)


class TestAllValidBatchStillSaves(_MixedValidityBase):
    def test_all_valid_batch_saves_without_refusal(self):
        """The control: without it, a guard that refused EVERY batch would
        pass every refusal test in this module."""
        _invoice_1, row_1 = self._valid_row(25.0, "1990-01-01")
        _invoice_2, row_2 = self._valid_row(30.0, "1996-07-07")

        batch = self._persisted_batch([row_1, row_2])

        self.assertEqual(len(batch.invoices), 2)
        self.assertEqual(batch.entry_count, 2)
