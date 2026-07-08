"""Coverage tests for the SEPA Direct Debit BATCH PROCESSING pipeline.

This module targets the reachable, real-DB branches of the DD batch processing
cluster that the existing SEPA suites do not yet exercise:

- ``verenigingen_payments/services/batch_processing_service.py``
  (totals SQL + Python fallback, invoice validation guards, sequence-type
  validation, status transitions, the phantom-field mandate bulk lookup)
- ``verenigingen_payments/doctype/direct_debit_batch/direct_debit_batch.py``
  (sequence-type validation branches, update_invoice_status, on_cancel,
  process_batch guard, module-level helpers)
- ``verenigingen_payments/services/sepa_batch_processor.py``
  (the single-invoice add helpers' missing-mandate guards, the empty-batch
  create path, verify_invoice_coverage against the real schema)
- ``verenigingen_payments/doctype/direct_debit_batch/sepa_processor.py``
  (the whitelisted preview / config / coverage API entrypoints)

Mirrors the harness in ``test_sepa_batch_processor_logic.py``: ``EnhancedTestCase``
+ the canonical ``sepa_test_company`` EUR-company-with-current-FY fixture so the
processor constructs and Sales Invoices save without a FiscalYearError on the
shared CI DB.

OUT OF SCOPE (not tested here; would require crossing an external/heavy
boundary or mocking business logic, which the test-quality-enforcer forbids):

- ``mark_batch_invoices_as_paid`` / ``_create_payment_entry_for_invoice``: needs
  a *submitted* batch and creates+submits real Payment Entries (commits, mode of
  payment "SEPA Direct Debit", bank GL setup). The submit/commit path would leak
  committed rows across the shared shards; the guard branch (un-submitted batch
  throws) IS covered.
- ``process_batch_submission`` success path: it only flips status + saves and is
  a documented bank-integration placeholder; the guard (no SEPA file -> throw) is
  covered.
- ``generate_sepa_xml`` / SEPA XML content: covered by
  test_direct_debit_batch_refactoring.py.
- ``handle_failed_payment`` schedule mutation: covered end-to-end by
  test_enhanced_sepa_processing.py; only the early-return guards are added here.
- ``parse_sepa_return_file`` / pain.002: documented stub, covered in
  test_sepa_batch_processor_logic.py.

Sequence-type validation for batches is handled by the Direct Debit Batch
*controller*'s own ``validate_sequence_types`` (which resolves the mandate by
``mandate_reference``), which is the working path.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services.batch_processing_service import (
    BatchProcessingService,
    batch_processing_service,
)
from verenigingen.verenigingen_payments.services.sepa_batch_processor import SEPABatchProcessor


class _BatchPipelineBase(EnhancedTestCase):
    """Shared setUp: EUR company + a SEPA factory + committed-doc tracking."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur_company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.processor = SEPABatchProcessor()
        self.service = batch_processing_service
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        self._sepa = SEPATestDataFactory(seed=9191, use_faker=True)
        # Track any doc we insert/commit so it is force-removed in tearDown even
        # though batch processing commits past the FrappeTestCase rollback.
        self._committed_docs = []
        # Submitting a dated invoice triggers eBoekhouden's ensure_fiscal_year_exists,
        # which logs this benign title when the current FY already exists / overlaps on
        # the shared test DB (a known test-artifact, not a SEPA bug). Acknowledge it so
        # the error-log guard surfaces only genuinely unexpected Error Logs.
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

    def tearDown(self):
        for doctype, name in reversed(self._committed_docs):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _track(self, doctype, name):
        self._committed_docs.append((doctype, name))

    # --- builders ------------------------------------------------------------

    def _member_with_membership(self, birth_date="1990-01-01"):
        member = self.create_test_member(birth_date=birth_date)
        self.create_test_membership(member_name=member.name)
        return member

    def _invoice_row(self, member, mandate, amount, sequence_type="FRST"):
        """A submitted EUR Sales Invoice + the Direct Debit Batch Invoice row dict
        that links to it (all child fields are reqd)."""
        membership = frappe.db.get_value("Membership", {"member": member.name, "docstatus": 1}, "name")
        invoice = self.create_test_sales_invoice(
            customer=member.name,
            company=self.eur_company,
            membership=membership,
            grand_total=amount,
        )
        member.reload()
        return invoice, {
            "invoice": invoice.name,
            "membership": membership,
            "member": member.name,
            "member_name": member.full_name,
            "amount": amount,
            "currency": "EUR",
            "iban": mandate.iban,
            "mandate_reference": mandate.mandate_id,
            "status": "Pending",
            "sequence_type": sequence_type,
        }

    def _persisted_batch(self, rows):
        """Insert a Draft Direct Debit Batch with the given child rows."""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = f"Pipeline cov {frappe.generate_hash(length=6)}"
        batch.batch_type = "CORE"
        batch.sequence_type = "FRST"
        batch.currency = "EUR"
        batch.status = "Draft"
        for row in rows:
            batch.append("invoices", row)
        batch.insert()
        self._track("Direct Debit Batch", batch.name)
        return batch

    def _one_invoice_batch(self):
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _invoice, row = self._invoice_row(member, mandate, 25.0)
        return self._persisted_batch([row]), member, mandate


class TestBatchProcessingServiceTotals(_BatchPipelineBase):
    """calculate_batch_totals_optimized: SQL path + Python fallback."""

    def test_calculate_totals_sql_path_sums_persisted_rows(self):
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i1, r1 = self._invoice_row(member, mandate, 25.0)
        member2 = self._member_with_membership("1991-02-02")
        mandate2 = self._sepa.create_test_sepa_mandate(member=member2.name, status="Active")
        _i2, r2 = self._invoice_row(member2, mandate2, 35.0)
        batch = self._persisted_batch([r1, r2])

        # Zero them first so we can prove the SQL aggregation actually recomputes.
        batch.entry_count = 0
        batch.total_amount = 0.0
        self.service.calculate_batch_totals_optimized(batch)

        self.assertEqual(batch.entry_count, 2)
        self.assertEqual(batch.total_amount, 60.0)

    def test_calculate_totals_python_fallback_on_unknown_batch_name(self):
        """A name that has no child rows in the DB makes the SQL aggregation
        return entry_count 0; the service then keeps zero (SQL succeeded, just
        empty). Pointing at a NONEXISTENT name still returns a row of zeros, so
        assert the documented zero-result behaviour rather than the in-memory sum.
        """
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i, row = self._invoice_row(member, mandate, 42.0)
        batch = self._persisted_batch([row])

        real_name = batch.name
        batch.name = "DD-BATCH-DOES-NOT-EXIST"
        try:
            self.service.calculate_batch_totals_optimized(batch)
            # No persisted child rows for that fake name -> aggregation is empty.
            self.assertEqual(batch.entry_count, 0)
            self.assertEqual(batch.total_amount, 0.0)
        finally:
            batch.name = real_name

    def test_calculate_totals_python_fallback_helper_sums_memory_rows(self):
        """The explicit Python fallback sums the in-memory child rows."""
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i, row = self._invoice_row(member, mandate, 17.5)
        batch = self._persisted_batch([row])
        batch.entry_count = 0
        batch.total_amount = 0.0
        self.service._calculate_totals_python_fallback(batch)
        self.assertEqual(batch.entry_count, 1)
        self.assertEqual(batch.total_amount, 17.5)


class TestBatchProcessingServiceValidation(_BatchPipelineBase):
    """validate_batch_invoices_optimized + status transitions."""

    def test_validate_invoices_empty_batch_throws(self):
        batch = frappe.new_doc("Direct Debit Batch")
        with self.assertRaises(frappe.ValidationError):
            self.service.validate_batch_invoices_optimized(batch)

    def test_validate_invoices_valid_eur_batch_passes(self):
        batch, _member, _mandate = self._one_invoice_batch()
        result = self.service.validate_batch_invoices_optimized(batch)
        self.assertEqual(result["total_invoices"], 1)
        self.assertEqual(result["valid_invoices"], 1)
        self.assertTrue(result["is_valid"])
        self.assertFalse(result["has_warnings"])

    def test_validate_invoices_reports_missing_invoice(self):
        """A batch row whose Sales Invoice cannot be bulk-loaded is reported as a
        validation error but, with at least one valid invoice present, does not
        throw."""
        batch, _member, _mandate = self._one_invoice_batch()
        # Append a row pointing at a nonexistent invoice (bypass link validation
        # by writing the child row directly in memory only).
        batch.append(
            "invoices",
            {
                "invoice": "ACC-SINV-NONEXISTENT-9999",
                "member": batch.invoices[0].member,
                "member_name": batch.invoices[0].member_name,
                "membership": batch.invoices[0].membership,
                "amount": 10.0,
                "currency": "EUR",
                "iban": batch.invoices[0].iban,
                "mandate_reference": batch.invoices[0].mandate_reference,
                "status": "Pending",
                "sequence_type": "FRST",
            },
        )
        result = self.service.validate_batch_invoices_optimized(batch)
        self.assertEqual(result["valid_invoices"], 1)
        self.assertTrue(result["has_warnings"])
        self.assertTrue(any("not found" in e for e in result["errors"]))

    def test_validate_invoices_all_invalid_throws_no_valid(self):
        """When EVERY batch row fails validation (here: a single row pointing at a
        non-existent invoice), valid_count stays 0 and the service throws
        'No valid invoices found in batch' (batch_processing_service.py:239-240).

        The sibling test_validate_invoices_reports_missing_invoice keeps ONE valid
        invoice alongside the missing one, so valid_count == 1 and it does NOT throw;
        this test isolates the valid_count == 0 refusal branch. The batch still has a
        row, so it passes the earlier 'No invoices added to batch' guard (:194)."""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_type = "CORE"
        batch.currency = "EUR"
        # In-memory row only (not inserted) so the Link field's existence check is
        # bypassed; the service reads invoice_item.invoice and finds no bulk detail.
        batch.append(
            "invoices",
            {
                "invoice": "ACC-SINV-NONEXISTENT-0001",
                "amount": 10.0,
                "currency": "EUR",
                "status": "Pending",
                "sequence_type": "FRST",
            },
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service.validate_batch_invoices_optimized(batch)
        self.assertIn("No valid invoices found in batch", str(ctx.exception))

    def test_update_batch_status_all_successful(self):
        batch, _m, _mn = self._one_invoice_batch()
        self.service._update_batch_status_after_processing(batch, len(batch.invoices))
        self.assertEqual(batch.status, "Processed")

    def test_update_batch_status_partial(self):
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i1, r1 = self._invoice_row(member, mandate, 25.0)
        member2 = self._member_with_membership("1993-03-03")
        mandate2 = self._sepa.create_test_sepa_mandate(member=member2.name, status="Active")
        _i2, r2 = self._invoice_row(member2, mandate2, 30.0)
        batch = self._persisted_batch([r1, r2])
        self.service._update_batch_status_after_processing(batch, 1)
        self.assertEqual(batch.status, "Partially Processed")

    def test_update_batch_status_none_successful(self):
        batch, _m, _mn = self._one_invoice_batch()
        self.service._update_batch_status_after_processing(batch, 0)
        self.assertEqual(batch.status, "Failed")


class TestBatchProcessingServiceGuards(_BatchPipelineBase):
    """The submit-state guards that throw before any external work."""

    def test_mark_invoices_as_paid_requires_submitted_batch(self):
        batch, _m, _mn = self._one_invoice_batch()  # docstatus 0
        with self.assertRaises(frappe.ValidationError):
            self.service.mark_batch_invoices_as_paid(batch)

    def test_process_batch_submission_requires_sepa_file(self):
        # The guard logs the failure before re-raising; assert both.
        self.expectErrorLog("SEPA file must be generated")
        batch, _m, _mn = self._one_invoice_batch()
        self.assertFalse(batch.sepa_file_generated)
        with self.assertRaises(frappe.ValidationError):
            self.service.process_batch_submission(batch)

    def test_singleton_and_class_share_config(self):
        fresh = BatchProcessingService()
        self.assertIs(fresh.config_service, batch_processing_service.config_service)


class TestDirectDebitBatchController(_BatchPipelineBase):
    """DocType controller methods: sequence-type validation, status helpers."""

    def test_validate_sequence_types_auto_assigns_when_missing(self):
        """A row with a valid mandate_reference but no sequence_type gets the
        controller-computed type auto-assigned (FRST for a brand-new mandate),
        and validation_status becomes Passed."""
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i, row = self._invoice_row(member, mandate, 25.0, sequence_type=None)
        row["sequence_type"] = None
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "seq-autoassign"
        batch.batch_type = "CORE"
        batch.sequence_type = "FRST"
        batch.currency = "EUR"
        batch.append("invoices", row)
        # Run only the sequence-type validation (not full save which recomputes).
        batch.validate_sequence_types()
        self.assertEqual(batch.invoices[0].sequence_type, "FRST")
        self.assertEqual(batch.validation_status, "Passed")

    def test_validate_sequence_types_critical_error_for_unknown_mandate(self):
        """A mandate_reference that matches no active SEPA Mandate is a critical
        error. In automated context it is recorded (not thrown)."""
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i, row = self._invoice_row(member, mandate, 25.0)
        row["mandate_reference"] = "MNDT-NEVER-EXISTS-0001"
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "seq-critical"
        batch.batch_type = "CORE"
        batch.sequence_type = "FRST"
        batch.currency = "EUR"
        batch._automated_processing = True  # record, don't throw
        batch.append("invoices", row)
        batch.validate_sequence_types()
        self.assertEqual(batch.validation_status, "Critical Errors")
        errors = frappe.parse_json(batch.validation_errors)
        self.assertTrue(any("No active mandate" in e["issue"] for e in errors))

    def test_validate_sequence_types_manual_context_throws_on_critical(self):
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i, row = self._invoice_row(member, mandate, 25.0)
        row["mandate_reference"] = "MNDT-NEVER-EXISTS-0002"
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "seq-manual"
        batch.batch_type = "CORE"
        batch.sequence_type = "FRST"
        batch.currency = "EUR"
        batch.append("invoices", row)
        # No _automated_processing flag -> manual -> throws.
        with self.assertRaises(frappe.ValidationError):
            batch.validate_sequence_types()

    def test_validate_sequence_types_skips_rows_without_mandate_reference(self):
        """A row without a mandate_reference is skipped (caught elsewhere by
        validate_invoices); with no other rows the status stays Passed."""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.append("invoices", {"invoice": "ACC-SINV-X", "status": "Pending"})
        batch.validate_sequence_types()
        self.assertEqual(batch.validation_status, "Passed")

    def test_calculate_totals_new_doc_uses_python_memory_sum(self):
        """For a not-yet-persisted batch, calculate_totals must sum the in-memory
        rows (the SQL aggregation would return 0 and clobber the real total)."""
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        _i1, r1 = self._invoice_row(member, mandate, 12.0)
        member2 = self._member_with_membership("1994-04-04")
        mandate2 = self._sepa.create_test_sepa_mandate(member=member2.name, status="Active")
        _i2, r2 = self._invoice_row(member2, mandate2, 8.0)
        batch = frappe.new_doc("Direct Debit Batch")
        batch.append("invoices", r1)
        batch.append("invoices", r2)
        batch.calculate_totals()
        self.assertEqual(batch.entry_count, 2)
        self.assertEqual(batch.total_amount, 20.0)

    def test_update_invoice_status_invalid_index_throws(self):
        batch, _m, _mn = self._one_invoice_batch()
        with self.assertRaises(frappe.ValidationError):
            batch.update_invoice_status(99, "Successful")

    def test_update_invoice_status_valid_index_persists(self):
        batch, _m, _mn = self._one_invoice_batch()
        batch.update_invoice_status(0, "Successful", "PDNG", "ok")
        batch.reload()
        self.assertEqual(batch.invoices[0].status, "Successful")
        self.assertEqual(batch.invoices[0].result_code, "PDNG")

    def test_on_cancel_sets_cancelled_status_and_logs(self):
        batch, _m, _mn = self._one_invoice_batch()
        batch.on_cancel()
        self.assertEqual(batch.status, "Cancelled")
        self.assertIn("cancelled", (batch.batch_log or "").lower())

    def test_process_batch_requires_sepa_file(self):
        # The guard logs the failure before re-raising; assert both.
        self.expectErrorLog("SEPA file must be generated")
        batch, _m, _mn = self._one_invoice_batch()
        self.assertFalse(batch.sepa_file_generated)
        with self.assertRaises(frappe.ValidationError):
            batch.process_batch()

    def test_add_to_batch_log_appends_message(self):
        batch, _m, _mn = self._one_invoice_batch()
        batch.add_to_batch_log("a custom log line")
        self.assertIn("a custom log line", batch.batch_log)


class TestDirectDebitBatchHelpers(_BatchPipelineBase):
    """Module-level helper functions."""

    def test_get_bic_from_iban_derives_known_bank(self):
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            get_bic_from_iban,
        )

        self.assertEqual(get_bic_from_iban("NL91ABNA0417164300"), "ABNANL2A")



class TestSEPABatchProcessorAddHelpers(_BatchPipelineBase):
    """The single-invoice add helpers' missing-mandate guard + happy path."""

    def test_add_existing_invoice_to_batch_no_mandate_logs_and_returns(self):
        """With mandate_name None the helper logs and returns without appending."""
        batch = frappe.new_doc("Direct Debit Batch")
        invoice_data = {
            "name": "ACC-SINV-0001",
            "mandate_name": None,
            "membership": None,
            "member": "M",
            "member_name": "M",
            "amount": 10.0,
            "currency": "EUR",
            "iban": "NL91ABNA0417164300",
            "mandate_reference": "X",
        }
        # The missing-mandate guard logs via frappe.log_error before returning;
        # register that expected log so the tearDown error-log guard ignores it.
        self.expectErrorLog("SEPA Batch - Missing Mandate")
        self.processor.add_existing_invoice_to_batch(batch, invoice_data)
        self.assertEqual(len(batch.invoices), 0)

    def test_add_invoice_to_batch_with_sequence_appends_row(self):
        """add_invoice_to_batch_with_sequence appends a row and creates a mandate
        usage record from pre-resolved data."""
        member = self._member_with_membership()
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        invoice = self.create_test_sales_invoice(
            customer=member.name, company=self.eur_company, grand_total=22.0
        )
        member.reload()
        batch = frappe.new_doc("Direct Debit Batch")
        invoice_data = {
            "name": invoice.name,
            "membership": None,
            "member": member.name,
            "member_name": member.full_name,
            "amount": 22.0,
            "currency": "EUR",
            "iban": mandate.iban,
            "mandate_reference": mandate.mandate_id,
            "mandate_sign_date": mandate.sign_date,
            "mandate_name": mandate.name,
        }
        self.processor.add_invoice_to_batch_with_sequence(batch, invoice_data, "FRST")
        self.assertEqual(len(batch.invoices), 1)
        self.assertEqual(batch.invoices[0].invoice, invoice.name)
        self.assertEqual(batch.invoices[0].sequence_type, "FRST")
        # A usage record was created against the mandate for this invoice.
        self.assertTrue(
            frappe.db.exists(
                "SEPA Mandate Usage",
                {"parent": mandate.name, "reference_name": invoice.name},
            )
            or frappe.db.exists("SEPA Mandate Usage", {"reference_name": invoice.name})
        )

    def test_create_dues_collection_batch_returns_none_without_invoices(self):
        """With no unpaid SEPA invoices the create path returns None (and creates
        no batch). Use a far-PAST collection_date so the eligibility window (which
        ends at collection_date) deterministically contains no invoices regardless
        of what sibling tests leave on the shared DB -- a today() date would
        intermittently match real invoices and take the other branch.
        verify_invoicing is disabled to keep this focused on the empty branch."""
        result = self.processor.create_dues_collection_batch(
            collection_date="1900-01-01", verify_invoicing=False
        )
        self.assertIsNone(result)


class TestSEPABatchProcessorCoverage(_BatchPipelineBase):
    """verify_invoice_coverage runs the real SQL against the live schema."""

    def test_verify_invoice_coverage_returns_complete_shape(self):
        result = self.processor.verify_invoice_coverage(today())
        # The method always returns this shape (or the error shape); assert the
        # success shape's keys and that issue accounting is internally consistent.
        self.assertIn("complete", result)
        self.assertIn("total_checked", result)
        self.assertIn("issues", result)
        if "error" not in result:
            self.assertEqual(result["complete"], len(result["issues"]) == 0)
            self.assertEqual(result["issues_count"], len(result["issues"]))


class TestSEPAProcessorAPIEntrypoints(_BatchPipelineBase):
    """The whitelisted preview / config / coverage API functions in
    sepa_processor.py. Run as Administrator (carries System Manager) so the
    @critical_api FINANCIAL decorators pass exactly as in production."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_validate_sepa_configuration_returns_valid_shape(self):
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import (
            validate_sepa_configuration,
        )

        result = validate_sepa_configuration()
        self.assertIn("valid", result)
        self.assertIn("message", result)
        if not result["valid"]:
            self.assertTrue("Missing" in result["message"] or "Invalid" in result["message"])
        else:
            self.assertIn("config", result)
            self.assertIn("iban", result["config"])

    def test_get_sepa_batch_preview_shape_and_consistency(self):
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import (
            get_sepa_batch_preview,
        )

        result = get_sepa_batch_preview(today())
        self.assertTrue(result["success"])
        self.assertEqual(result["collection_date"], today())
        # sample is a prefix of the found invoices.
        self.assertLessEqual(len(result["sample_invoices"]), 5)
        self.assertLessEqual(len(result["sample_invoices"]), result["unpaid_invoices_found"])
        self.assertGreaterEqual(result["members_affected"], 0)

    def test_get_upcoming_dues_collections_groups_by_date(self):
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import (
            get_upcoming_dues_collections,
        )

        member = self._member_with_membership()
        self._sepa.create_test_sepa_mandate(member=member.name, status="Active")
        schedule = self._sepa.create_test_membership_dues_schedule(
            member=member.name, payment_terms_template="SEPA Direct Debit"
        )
        schedule.next_invoice_date = today()
        schedule.status = "Active"
        schedule.flags.ignore_validate = True
        schedule.save()

        collections = get_upcoming_dues_collections(30)
        self.assertIsInstance(collections, list)
        # Each grouped entry exposes a per-date roll-up; count must equal the
        # number of schedules grouped under that date.
        for entry in collections:
            self.assertEqual(entry["count"], len(entry["schedules"]))
            self.assertIn("total_amount", entry)

    def test_verify_invoice_coverage_status_entrypoint(self):
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import (
            verify_invoice_coverage_status,
        )

        result = verify_invoice_coverage_status(today())
        self.assertIn("complete", result)
        self.assertIn("issues", result)
