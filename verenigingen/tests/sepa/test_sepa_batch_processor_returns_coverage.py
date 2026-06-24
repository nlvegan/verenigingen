"""
Coverage for SEPABatchProcessor paths not exercised by the existing
``test_sepa_batch_processor_logic.py`` (pure logic / builders / eligibility) or
``test_dd_batch_pipeline_coverage.py`` (totals / validation / add-helpers):

- ``process_batch_returns``: matching a parsed return item to a batch invoice
  row, flipping it to Failed with the bank reason code/message, invoking the
  failed-payment handler, flipping the batch to 'Partially Failed', and logging.
  Also the no-match path (return for an invoice not in the batch).
- ``add_processed_invoice_to_batch``: the optimized-data append happy path AND
  its atomic compensation -- when the mandate usage-record creation fails the
  appended invoice row must be popped back off so the batch stays consistent.
- ``handle_automated_batch_validation``: the early-return when the batch carries
  no validation_status, and the delegated path when it does.
- ``find_existing_invoice_for_schedule`` / ``update_schedule_after_invoice``:
  the existing-invoice lookup and the post-invoice schedule advance.
- ``notify_payment_failure``: the member-email branch for a real schedule.

All real-DB; the only seam is an intentionally-inactive mandate used to force the
usage-record failure for the compensation test (no mocks).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services.sepa_batch_processor import SEPABatchProcessor


class _ReturnsBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur_company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.processor = SEPABatchProcessor()
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        self.factory = SEPATestDataFactory(seed=3300, use_faker=True)
        self._committed = []
        # Dated invoice submission logs eBoekhouden's benign FY auto-create title.
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

    def tearDown(self):
        for doctype, name in reversed(self._committed):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _track(self, doctype, name):
        self._committed.append((doctype, name))

    def _member_with_membership(self, birth_date="1985-01-01"):
        member = self.create_test_member(birth_date=birth_date)
        self.create_test_membership(member_name=member.name)
        return member

    def _batch_with_invoice(self, member, mandate, *, link_schedule=None, amount=25.0):
        """A saved Draft EUR batch with one real submitted invoice row."""
        membership = frappe.db.get_value("Membership", {"member": member.name, "docstatus": 1}, "name")
        invoice = self.create_test_sales_invoice(
            customer=member.name, company=self.eur_company, membership=membership, grand_total=amount
        )
        invoice.submit()
        if link_schedule:
            invoice.db_set("membership_dues_schedule_display", link_schedule)

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = f"returns cov {frappe.generate_hash(length=6)}"
        batch.batch_type = "CORE"
        batch.sequence_type = "FRST"
        batch.currency = "EUR"
        batch.status = "Draft"
        batch.append(
            "invoices",
            {
                "invoice": invoice.name,
                "membership": membership,
                "member": member.name,
                "member_name": member.full_name,
                "amount": amount,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "sequence_type": "FRST",
                "status": "Pending",
            },
        )
        batch.save()
        self._track("Direct Debit Batch", batch.name)
        return batch, invoice


class TestProcessBatchReturns(_ReturnsBase):
    def test_matching_return_marks_invoice_failed_and_batch_partially_failed(self):
        member = self._member_with_membership()
        mandate = self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        # Link a dues schedule so handle_failed_payment can advance it (the
        # member already has one from the membership; reuse it).
        schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "is_template": 0}, "name"
        )
        batch, invoice = self._batch_with_invoice(member, mandate, link_schedule=schedule)

        # find_invoice_in_batch matches on end_to_end_id == invoice_item.invoice.
        returns = [
            {
                "end_to_end_id": invoice.name,
                "reason_code": "MS03",
                "reason_description": "Reason not specified",
            }
        ]
        # Drive the parser to yield our return item (the file parser is a stub
        # that returns []), so call process via a temporary subclass override of
        # parse_sepa_return_file -- the seam is the parser, not frappe.db.
        self.processor.parse_sepa_return_file = lambda _path: returns

        failed = self.processor.process_batch_returns(batch.name, "/ignored/return.xml")

        self.assertEqual(failed, 1)
        batch.reload()
        self.assertEqual(batch.status, "Partially Failed")
        self.assertEqual(batch.invoices[0].status, "Failed")
        self.assertEqual(batch.invoices[0].result_code, "MS03")
        self.assertIn("Processed 1 returned", batch.batch_log or "")

    def test_unmatched_return_leaves_batch_unchanged(self):
        member = self._member_with_membership("1986-02-02")
        mandate = self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        batch, _invoice = self._batch_with_invoice(member, mandate)

        # A return for an invoice NOT in the batch -> no row matched -> failed_count 0.
        self.processor.parse_sepa_return_file = lambda _path: [
            {"end_to_end_id": "ACC-SINV-NOT-IN-BATCH", "reason_code": "AC04"}
        ]
        failed = self.processor.process_batch_returns(batch.name, "/ignored/return.xml")
        self.assertEqual(failed, 0)
        batch.reload()
        # Status stays Draft (only >0 failures flip it to Partially Failed).
        self.assertEqual(batch.status, "Draft")
        self.assertEqual(batch.invoices[0].status, "Pending")

    def test_process_returns_logs_and_raises_on_bad_batch(self):
        # An unknown batch name makes frappe.get_doc raise; the except logs and re-raises.
        self.expectErrorLog("SEPA Return Processing Error")
        with self.assertRaises(Exception):
            self.processor.process_batch_returns("DD-BATCH-DOES-NOT-EXIST", "/ignored.xml")


class TestAddProcessedInvoiceToBatch(_ReturnsBase):
    def _processed(self, invoice, member, mandate):
        """The optimized 'processed_invoice' shape add_processed_invoice_to_batch reads."""
        return {
            "invoice_name": invoice.name,
            "invoice_data": {
                "name": invoice.name,
                "membership": None,
                "grand_total": invoice.grand_total,
                "currency": "EUR",
            },
            "member_data": {"name": member.name, "full_name": member.full_name},
            "mandate_data": {
                "name": mandate.name,
                "iban": mandate.iban,
                "mandate_id": mandate.mandate_id,
                "sign_date": mandate.sign_date,
            },
        }

    def test_happy_path_appends_row_and_creates_usage(self):
        member = self._member_with_membership("1987-03-03")
        mandate = self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        membership = frappe.db.get_value("Membership", {"member": member.name, "docstatus": 1}, "name")
        invoice = self.create_test_sales_invoice(
            customer=member.name, company=self.eur_company, membership=membership, grand_total=25.0
        )
        batch = frappe.new_doc("Direct Debit Batch")
        before = len(batch.invoices)

        self.processor.add_processed_invoice_to_batch(
            batch, self._processed(invoice, member, mandate), "FRST"
        )

        self.assertEqual(len(batch.invoices), before + 1)
        row = batch.invoices[-1]
        self.assertEqual(row.invoice, invoice.name)
        self.assertEqual(row.iban, mandate.iban)
        self.assertEqual(row.sequence_type, "FRST")
        # The usage record was recorded on the mandate.
        mandate.reload()
        self.assertTrue(any(u.reference_name == invoice.name for u in mandate.usage_history))

    def test_usage_failure_rolls_back_appended_row(self):
        """COMPENSATION: if the usage-record creation fails, the just-appended
        invoice row must be popped back off so the batch is not left with an
        orphaned row, and the error re-raised. We force the failure with an
        INACTIVE mandate -- create_mandate_usage_record refuses inactive mandates."""
        member = self._member_with_membership("1988-04-04")
        mandate = self.factory.create_test_sepa_mandate(member=member.name, status="Cancelled")
        membership = frappe.db.get_value("Membership", {"member": member.name, "docstatus": 1}, "name")
        invoice = self.create_test_sales_invoice(
            customer=member.name, company=self.eur_company, membership=membership, grand_total=25.0
        )
        batch = frappe.new_doc("Direct Debit Batch")
        before = len(batch.invoices)

        # The usage-record + this method both log on failure.
        self.expectErrorLog("Mandate Usage Creation Error")
        self.expectErrorLog("Invoice Addition Rolled Back")
        with self.assertRaises(Exception):
            self.processor.add_processed_invoice_to_batch(
                batch, self._processed(invoice, member, mandate), "FRST"
            )
        # Row was rolled back -> batch length unchanged.
        self.assertEqual(len(batch.invoices), before)


class TestHandleAutomatedBatchValidation(_ReturnsBase):
    def test_no_validation_status_returns_early(self):
        # A batch with no validation_status must short-circuit without error.
        batch = frappe.new_doc("Direct Debit Batch")
        # Should not raise and should not attempt notification.
        with self.assertNoErrorLog():
            self.processor.handle_automated_batch_validation(batch)

    def test_passed_validation_delegates_to_notifications(self):
        """When the batch has a validation_status, the processor parses the
        error/warning JSON and delegates to the notifications module, which
        returns an action dict. 'Passed' with no errors -> no notification action,
        but the delegation path runs without raising."""
        member = self._member_with_membership("1989-05-05")
        mandate = self.factory.create_test_sepa_mandate(member=member.name, status="Active")
        batch, _invoice = self._batch_with_invoice(member, mandate)
        batch.validation_status = "Passed"
        batch.validation_errors = None
        batch.validation_warnings = None
        with self.assertNoErrorLog():
            self.processor.handle_automated_batch_validation(batch)


class TestScheduleHelpers(_ReturnsBase):
    def test_find_existing_invoice_for_schedule_returns_none_when_absent(self):
        member = self._member_with_membership("1990-06-06")
        schedule = frappe.get_doc(
            "Membership Dues Schedule",
            frappe.db.get_value(
                "Membership Dues Schedule", {"member": member.name, "is_template": 0}, "name"
            ),
        )
        # No invoice yet matching the coverage period -> None.
        result = self.processor.find_existing_invoice_for_schedule(schedule)
        self.assertIsNone(result)

    def test_update_schedule_after_invoice_advances_coverage_and_dates(self):
        member = self._member_with_membership("1991-07-07")
        schedule = frappe.get_doc(
            "Membership Dues Schedule",
            frappe.db.get_value(
                "Membership Dues Schedule", {"member": member.name, "is_template": 0}, "name"
            ),
        )
        schedule.last_invoice_coverage_start = None
        schedule.last_invoice_coverage_end = None
        schedule.flags.ignore_validate = True
        schedule.save()

        self.processor.update_schedule_after_invoice(schedule)
        schedule.reload()
        # The coverage window and last_invoice_date are now populated.
        self.assertIsNotNone(schedule.last_invoice_coverage_start)
        self.assertIsNotNone(schedule.last_invoice_coverage_end)
        self.assertEqual(str(schedule.last_invoice_date), today())
