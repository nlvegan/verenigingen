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


class TestInvalidInvoiceCountIsDistinctNotErrorLines(_MixedValidityBase):
    """#1455 independent review: `validate_batch_invoices_optimized`'s
    `errors` is a list of ERROR LINES (also capped at 10), not of invoices.
    One invoice can fail more than one check (a zero `outstanding_amount`
    fails BOTH the required-field check, since 0 is falsy, AND the
    amount > 0 check), so counting `len(errors)` reported a single
    doubly-invalid invoice as "2 invalid invoice(s)". Both the count and the
    omitted-detail note must be computed over DISTINCT invoice names, from
    the FULL (uncapped) error set -- not the capped `errors` list used for
    the displayed detail.
    """

    def test_one_invoice_two_failures_reports_one_invalid_invoice(self):
        _good_invoice, good_row = self._valid_row(25.0, "1990-01-01")
        bad_invoice, bad_row = self._valid_row(30.0, "1997-08-08")
        # One invoice, two independent failures: outstanding_amount=0 is
        # falsy (fails the required-field check) AND fails the amount>0
        # check -- two error lines, ONE invalid invoice.
        bad_invoice.db_set("outstanding_amount", 0)

        message = self._insert_and_expect_refusal([good_row, bad_row])

        self.assertIn("1 invalid invoice(s)", message)
        self.assertNotIn("2 invalid invoice(s)", message)
        self.assertIn(bad_invoice.name, message)

    def test_more_than_ten_invalid_invoices_reports_true_count_and_omission(self):
        """11 invalid invoices, each with a SINGLE-error defect (an invoice
        status SEPA doesn't collect from, with currency/amount left alone) --
        so error-line count and invoice count coincide here, isolating the
        >10 CAPPING concern from the multi-error-per-invoice concern the
        sibling test covers. `errors` is capped at 10 error lines / 10
        invoices, so the 11th invoice's detail is omitted. The message must
        still say 11 invalid (mixed with 1 valid row, so this hits
        DirectDebitBatch's "This batch contains N invalid invoice(s)"
        message, not the all-invalid one), plus an explicit note that 1 more
        isn't shown."""
        _good_invoice, good_row = self._valid_row(25.0, "1990-01-01")
        rows = [good_row]
        bad_invoices = []
        for i in range(11):
            invoice, row = self._valid_row(10.0 + i, frappe.utils.add_days("1980-01-01", i))
            # A status SEPA does not collect from -- the ONLY check this trips
            # (currency stays EUR, amount stays positive).
            invoice.db_set("status", "Paid")
            bad_invoices.append(invoice)
            rows.append(row)

        message = self._insert_and_expect_refusal(rows)

        self.assertIn("This batch contains 11 invalid invoice(s)", message)
        self.assertIn("1 more invalid invoice(s) not shown", message)
        # The 11th (omitted) invoice's own name need not appear in the capped
        # detail -- that is the point of the omission note -- but the first
        # ten's error lines must still be there.
        for invoice in bad_invoices[:10]:
            self.assertIn(invoice.name, message)
        self.assertNotIn(bad_invoices[10].name, message)


class TestAllValidBatchStillSaves(_MixedValidityBase):
    def test_all_valid_batch_saves_without_refusal(self):
        """The control: without it, a guard that refused EVERY batch would
        pass every refusal test in this module."""
        _invoice_1, row_1 = self._valid_row(25.0, "1990-01-01")
        _invoice_2, row_2 = self._valid_row(30.0, "1996-07-07")

        batch = self._persisted_batch([row_1, row_2])

        self.assertEqual(len(batch.invoices), 2)
        self.assertEqual(batch.entry_count, 2)
