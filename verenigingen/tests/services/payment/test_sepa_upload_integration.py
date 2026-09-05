"""
Integration Tests for SEPA Upload Guard in XML Generation

Tests the integration of SEPAUploadGuard into the SEPA XML generation flow,
verifying that:
1. Generating SEPA XML creates a log entry with the file hash
2. Attempting to generate the exact same XML twice is blocked

These tests use real data and the actual SEPA XML generation service
to verify end-to-end functionality of the duplicate prevention system.

Author: Verenigingen Development Team
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.payment.sepa_upload_guard import (
    SEPAUploadGuard,
    get_sepa_upload_guard,
)
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import (
    SEPAXMLGenerationService,
    sepa_xml_service,
)


def _ensure_sepa_settings_for_xml_generation():
    """Seed the minimal, VALID SEPA configuration the XML generation service
    needs so the upload-integration XML tests run deterministically.

    Without this the service either raises "Missing required SEPA settings"
    (tests skip) or resolves the creditor name to the underscore-prefixed
    "_Test Company" (invalid SEPA character set -> validation error). We point
    Verenigingen Settings at the EUR test company (whose name is SEPA-clean) and
    set creditor_id / BIC / IBAN on Verenigingen Payments Settings, then refresh
    the config service cache. Idempotent.
    """
    from verenigingen.tests.support.sepa_test_company import get_eur_test_company
    from verenigingen.verenigingen_payments.services.sepa_configuration_service import (
        sepa_config_service,
    )

    company = get_eur_test_company()
    ven_settings = frappe.get_single("Verenigingen Settings")
    if ven_settings.company != company:
        ven_settings.company = company
        ven_settings.flags.ignore_validate = True
        ven_settings.save(ignore_permissions=True)

    payments = frappe.get_single("Verenigingen Payments Settings")
    payments.company_iban = "NL91ABNA0417164300"
    payments.company_bic = "ABNANL2A"
    payments.creditor_id = "NL13ZZZ123456780000"
    payments.flags.ignore_validate = True
    payments.save(ignore_permissions=True)
    frappe.db.commit()
    sepa_config_service.refresh_settings_cache()
    frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")


class TestSEPAUploadIntegration(FrappeTestCase):
    """
    Integration tests for SEPA upload guard in XML generation flow.

    Tests verify that the upload guard is properly integrated into the
    SEPA XML generation service and prevents duplicate file generation.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures once for all tests in this class."""
        super().setUpClass()
        cls.factory = SEPATestDataFactory(seed=54321)
        _ensure_sepa_settings_for_xml_generation()

    def setUp(self):
        """Set up test fixtures for each test."""
        super().setUp()
        # The shared site's Verenigingen Settings.company can drift back to the
        # ERPNext "_Test Company" (underscore -> invalid SEPA name) between runs,
        # so re-assert valid SEPA config per test and refresh the cached settings.
        _ensure_sepa_settings_for_xml_generation()
        self.guard = get_sepa_upload_guard()
        self.service = SEPAXMLGenerationService()

        # Clean up any existing upload logs to ensure test isolation
        self._cleanup_upload_logs()

    def tearDown(self):
        """Clean up after each test."""
        self._cleanup_upload_logs()
        super().tearDown()

    def _cleanup_upload_logs(self):
        """Remove all SEPA Batch Upload Log entries created during tests."""
        frappe.db.delete("SEPA Batch Upload Log", {})
        frappe.db.commit()

    def _create_test_batch_with_invoices(self, invoice_count: int = 2):
        """
        Create a test direct debit batch with the required invoice data.

        Args:
            invoice_count: Number of test invoices to create in the batch

        Returns:
            Direct Debit Batch document ready for SEPA XML generation
        """
        return self.factory.create_test_direct_debit_batch(invoice_count=invoice_count)

    def test_sepa_generation_registers_upload_hash(self):
        """
        Verify that generating SEPA XML creates a log entry.

        When SEPA XML is successfully generated for a batch:
        - A SEPA Batch Upload Log entry should be created
        - The log entry should contain the batch name
        - The log entry should contain a valid file hash
        - The log entry should record the uploading user
        """
        # Create test batch with invoices
        batch = self._create_test_batch_with_invoices(invoice_count=2)

        # Count log entries before generation
        logs_before = frappe.db.count("SEPA Batch Upload Log")

        # Generate SEPA XML
        try:
            file_url = self.service.generate_sepa_xml_for_batch(batch)
        except frappe.ValidationError as e:
            # If SEPA configuration is missing, skip this test
            if "Missing required SEPA settings" in str(e):
                self.skipTest("SEPA configuration not available for testing")
            raise

        # Verify file was created
        self.assertIsNotNone(file_url)

        # Verify log entry was created
        logs_after = frappe.db.count("SEPA Batch Upload Log")
        self.assertEqual(
            logs_after,
            logs_before + 1,
            "Expected one new SEPA Batch Upload Log entry after generation",
        )

        # Verify log entry details
        log_entry = frappe.get_last_doc("SEPA Batch Upload Log")
        self.assertEqual(log_entry.batch_name, batch.name)
        self.assertIsNotNone(log_entry.file_hash)
        self.assertEqual(len(log_entry.file_hash), 64)  # SHA256 produces 64 hex chars
        self.assertIsNotNone(log_entry.upload_time)
        self.assertIsNotNone(log_entry.uploaded_by)

    def test_duplicate_xml_blocked(self):
        """
        Verify that generating the exact same XML twice is blocked.

        When attempting to generate SEPA XML for a batch that would produce
        identical content to an already-uploaded file:
        - The generation should fail with a ValidationError
        - The error message should indicate duplicate detection
        - No new log entry should be created
        """
        # Create test batch
        batch = self._create_test_batch_with_invoices(invoice_count=2)

        # First generation should succeed
        try:
            file_url = self.service.generate_sepa_xml_for_batch(batch)
        except frappe.ValidationError as e:
            if "Missing required SEPA settings" in str(e):
                self.skipTest("SEPA configuration not available for testing")
            raise

        self.assertIsNotNone(file_url)

        # Count logs after first generation
        logs_after_first = frappe.db.count("SEPA Batch Upload Log")

        # Reset batch status to allow regeneration attempt
        # (In production this wouldn't happen, but we need to test the guard)
        batch.db_set("status", "Draft")
        batch.db_set("sepa_file_generated", 0)
        batch.db_set("sepa_file", None)

        # Reload batch to get fresh state
        batch.reload()

        # Second generation with same content should fail
        with self.assertRaises(frappe.ValidationError) as context:
            self.service.generate_sepa_xml_for_batch(batch)

        # Verify error message indicates duplicate
        error_message = str(context.exception)
        self.assertIn("Duplicate", error_message)

        # Verify no new log entry was created
        logs_after_second = frappe.db.count("SEPA Batch Upload Log")
        self.assertEqual(
            logs_after_second,
            logs_after_first,
            "No new log entry should be created when duplicate is blocked",
        )

    def test_different_batches_allowed(self):
        """
        Verify that generating XML for different batches is allowed.

        Two different batches (with different content) should both be
        able to generate SEPA XML without triggering duplicate detection.
        """
        # Create two different test batches
        batch1 = self._create_test_batch_with_invoices(invoice_count=2)
        batch2 = self._create_test_batch_with_invoices(invoice_count=3)

        # Generate SEPA XML for first batch
        try:
            file_url1 = self.service.generate_sepa_xml_for_batch(batch1)
        except frappe.ValidationError as e:
            if "Missing required SEPA settings" in str(e):
                self.skipTest("SEPA configuration not available for testing")
            raise

        self.assertIsNotNone(file_url1)

        # Generate SEPA XML for second batch - should succeed
        file_url2 = self.service.generate_sepa_xml_for_batch(batch2)
        self.assertIsNotNone(file_url2)

        # Verify both log entries exist
        log_count = frappe.db.count("SEPA Batch Upload Log")
        self.assertEqual(log_count, 2, "Expected two log entries for two different batches")

        # Verify hashes are different
        logs = frappe.get_all(
            "SEPA Batch Upload Log",
            fields=["batch_name", "file_hash"],
            order_by="creation",
        )
        self.assertEqual(len(logs), 2)
        self.assertNotEqual(
            logs[0].file_hash,
            logs[1].file_hash,
            "Different batches should have different file hashes",
        )


class TestSEPAUploadGuardDirectIntegration(FrappeTestCase):
    """
    Direct integration tests for the SEPAUploadGuard service.

    These tests verify the guard's behavior with raw XML content,
    independent of the full SEPA XML generation service.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = SEPATestDataFactory(seed=24680)

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.guard = get_sepa_upload_guard()

        # SEPA Batch Upload Log.batch_name is a Link to Direct Debit Batch, so
        # register_upload validates it. Create real batches (Direct Debit Batch
        # validation requires at least one invoice) rather than using
        # non-existent literal names that fail link validation.
        self.batch_1 = self.factory.create_test_direct_debit_batch(invoice_count=1).name
        self.batch_2 = self.factory.create_test_direct_debit_batch(invoice_count=1).name

        # Sample SEPA XML content for testing
        self.sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08">
    <CstmrDrctDbtInitn>
        <GrpHdr>
            <MsgId>INTEGRATION-TEST-001</MsgId>
            <CreDtTm>2026-02-01T10:00:00</CreDtTm>
        </GrpHdr>
    </CstmrDrctDbtInitn>
</Document>"""

        self._cleanup_upload_logs()

    def tearDown(self):
        """Clean up after each test."""
        self._cleanup_upload_logs()
        super().tearDown()

    def _cleanup_upload_logs(self):
        """Remove test upload logs."""
        frappe.db.delete("SEPA Batch Upload Log", {})
        frappe.db.commit()

    def test_guard_check_before_register(self):
        """
        Verify check_upload_allowed returns correct results.

        Before any upload: should return success=True
        After registration: should return success=False for same content
        """
        # Initial check should allow upload
        result1 = self.guard.check_upload_allowed(self.sample_xml, self.batch_1)
        self.assertTrue(result1.success)
        self.assertIsNotNone(result1.file_hash)

        # Register the upload
        register_result = self.guard.register_upload(
            self.sample_xml,
            self.batch_1,
            uploaded_by="Administrator",
        )
        self.assertTrue(register_result.success)

        # Second check should block
        result2 = self.guard.check_upload_allowed(self.sample_xml, self.batch_2)
        self.assertFalse(result2.success)
        self.assertEqual(result2.duplicate_batch, self.batch_1)

    def test_guard_atomic_check_and_register(self):
        """
        Verify check_and_register provides atomic operation.

        First call should succeed and register.
        Second call with same content should fail.
        """
        # First atomic operation should succeed
        result1 = self.guard.check_and_register(
            self.sample_xml,
            self.batch_1,
            uploaded_by="Administrator",
        )
        self.assertTrue(result1.success)

        # Second atomic operation with same content should fail
        result2 = self.guard.check_and_register(
            self.sample_xml,
            self.batch_2,
            uploaded_by="Administrator",
        )
        self.assertFalse(result2.success)
        self.assertEqual(result2.duplicate_batch, self.batch_1)

        # Only one log entry should exist
        log_count = frappe.db.count("SEPA Batch Upload Log")
        self.assertEqual(log_count, 1)


class TestPhantomHashRetry(FrappeTestCase):
    """
    End-to-end tests for ``retry_phantom_attachment``.

    A "phantom" upload log entry is one whose file hash was reserved but whose
    file attachment failed, which blocks any legitimate re-upload of that batch.
    ``retry_phantom_attachment`` is the repair tool: regenerate the SEPA XML,
    attach it to the batch, and mark the entry Resolved.

    The endpoint had no test coverage at all, which is how it came to be broken
    for every possible input - see ``test_retry_attaches_file_and_resolves_entry``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = SEPATestDataFactory(seed=90210)
        _ensure_sepa_settings_for_xml_generation()

    def setUp(self):
        super().setUp()
        # The shared site's SEPA config can drift between runs (see the note on
        # TestSEPAUploadIntegration.setUp), so re-assert it per test.
        _ensure_sepa_settings_for_xml_generation()
        self._created_log_names = []

    def tearDown(self):
        for log_name in self._created_log_names:
            frappe.db.sql("DELETE FROM `tabSEPA Batch Upload Log` WHERE name = %s", (log_name,))
        if self._created_log_names:
            frappe.db.commit()
        super().tearDown()

    def _create_batch_awaiting_retry(self):
        """A batch that reached the upload stage but never got its file attached."""
        batch = self.factory.create_test_direct_debit_batch(invoice_count=1)
        # The endpoint feeds these straight into the XML generator; a batch that
        # reached upload already carries them.
        batch.db_set("sepa_message_id", f"MSG-{frappe.utils.random_string(8)}")
        batch.db_set("sepa_payment_info_id", f"PMT-{frappe.utils.random_string(8)}")
        batch.reload()
        frappe.db.commit()
        return batch

    def _create_phantom_log(self, batch_name):
        """Insert a phantom log entry via SQL, bypassing DocType validation.

        Mirrors the fixture approach in test_sepa_upload_guard.py: a phantom
        entry is by definition a half-written record.
        """
        log_name = f"SEPA-UPL-RETRY-{frappe.utils.random_string(8)}"
        frappe.db.sql(
            """
            INSERT INTO `tabSEPA Batch Upload Log`
                (name, creation, modified, modified_by, owner, docstatus,
                 batch_name, file_hash, upload_time, uploaded_by, file_size,
                 batch_status, bank_status, bank_error_message, is_phantom, hash_freed)
            VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', 0,
                    %s, %s, NOW(), 'Administrator', 1024,
                    'Pending Upload', 'Rejected', 'Attachment failed: fixture', 1, 0)
            """,
            (log_name, batch_name, frappe.utils.random_string(64)),
        )
        frappe.db.commit()
        self._created_log_names.append(log_name)
        return log_name

    def test_retry_attaches_file_and_resolves_entry(self):
        """
        A successful retry must attach the regenerated file to the batch and
        flip the log entry to Resolved.

        Regression: the endpoint attached the File (an uncommitted write) and
        then called ``frappe.db.begin()``, which trips Frappe's implicit-commit
        guard whenever writes are pending. Every call therefore failed, the
        error handler rolled the File insert back, and the entry was left
        stranded at "[RETRY_IN_PROGRESS]" - still blocking re-upload, which is
        the exact condition this tool exists to clear.
        """
        from verenigingen.api.sepa_phantom_hash_admin import retry_phantom_attachment

        batch = self._create_batch_awaiting_retry()
        log_name = self._create_phantom_log(batch.name)

        result = retry_phantom_attachment(log_name=log_name)

        self.assertTrue(result.get("success"), f"retry failed: {result.get('message')}")
        self.assertTrue(result.get("file_url"), "retry reported success without a file_url")

        # The file must actually be on the batch, not just reported.
        self.assertTrue(
            frappe.db.get_value("Direct Debit Batch", batch.name, "sepa_file"),
            "batch has no sepa_file after a successful retry",
        )

        # Read through SQL: the endpoint writes with db.set_value, so a cached
        # document would not show the change.
        log_row = frappe.db.sql(
            """
            SELECT bank_status, is_phantom, bank_error_message
            FROM `tabSEPA Batch Upload Log` WHERE name = %s
            """,
            (log_name,),
            as_dict=True,
        )[0]
        self.assertEqual(log_row.bank_status, "Resolved")
        self.assertEqual(log_row.is_phantom, 0)
        self.assertNotIn("[RETRY_IN_PROGRESS]", log_row.bank_error_message or "")

    def test_failed_retry_records_the_failure_and_leaves_no_orphan_file(self):
        """
        A retry that fails AFTER the file was attached must discard the file and
        record the failure on the log entry.

        This covers the frappe.db.rollback() added at the top of the endpoint's
        exception handler. Without it the handler's own set_value + commit would
        PUBLISH the half-written state: a File row (and its bytes on disk)
        attached to a batch whose log entry says the retry failed.

        The failure is injected at _acquire_row_lock's SECOND call - the
        re-acquisition after file generation - because that is the first thing
        the endpoint does once the File exists. Patching a lock helper, not
        business logic: the code under test is the error path itself.
        """
        import verenigingen.api.sepa_phantom_hash_admin as admin

        batch = self._create_batch_awaiting_retry()
        log_name = self._create_phantom_log(batch.name)

        real_acquire = admin._acquire_row_lock
        calls = {"n": 0}

        def _fail_on_reacquire(name):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("injected failure after file attachment")
            return real_acquire(name)

        admin._acquire_row_lock = _fail_on_reacquire
        self.addCleanup(setattr, admin, "_acquire_row_lock", real_acquire)

        result = admin.retry_phantom_attachment(log_name=log_name)

        self.assertFalse(result.get("success"))
        self.assertGreaterEqual(calls["n"], 2, "the injected failure point was never reached")

        # The File insert must have been rolled back, not published.
        self.assertEqual(
            frappe.db.count(
                "File", {"attached_to_doctype": "Direct Debit Batch", "attached_to_name": batch.name}
            ),
            0,
            "an orphan File survived a failed retry",
        )
        self.assertFalse(
            frappe.db.get_value("Direct Debit Batch", batch.name, "sepa_file"),
            "the batch kept a sepa_file from a failed retry",
        )

        log_row = frappe.db.sql(
            """
            SELECT bank_status, is_phantom, bank_error_message
            FROM `tabSEPA Batch Upload Log` WHERE name = %s
            """,
            (log_name,),
            as_dict=True,
        )[0]
        self.assertNotEqual(log_row.bank_status, "Resolved")
        self.assertEqual(log_row.is_phantom, 1)
        self.assertIn("Retry failed", log_row.bank_error_message or "")
        self.assertNotIn("[RETRY_IN_PROGRESS]", log_row.bank_error_message or "")


class TestSEPABatchStatusRollbackOnFailure(FrappeTestCase):
    """
    Regression tests for #796.

    ``_save_xml_file`` (called from ``generate_sepa_xml_for_batch``) writes
    ``sepa_file``, ``sepa_file_generated`` and ``status="Generated"`` via
    ``db_set`` *before* its own final step (recording the file name on the
    SEPA Batch Upload Log entry). ``db_set`` bypasses the in-memory document
    and writes straight to the DB connection with no rollback safety net, so
    if that final step throws, the exception propagates to the caller (who
    sees "generation failed") while the batch row is left claiming
    status="Generated" — an inert-but-wrong signal on a money/SEPA path.

    ``verenigingen/api/sepa_phantom_hash_admin.py::retry_phantom_attachment``
    already guards its own, analogous db_set sequence with a
    ``frappe.db.rollback()`` in its except handler (see
    ``TestPhantomHashRetry.test_failed_retry_records_the_failure_and_leaves_no_orphan_file``
    above) — this test asserts the same atomicity for
    ``generate_sepa_xml_for_batch``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = SEPATestDataFactory(seed=13579)
        _ensure_sepa_settings_for_xml_generation()

    def setUp(self):
        super().setUp()
        _ensure_sepa_settings_for_xml_generation()
        self.service = SEPAXMLGenerationService()
        self._cleanup_upload_logs()

    def tearDown(self):
        self._cleanup_upload_logs()
        super().tearDown()

    def _cleanup_upload_logs(self):
        frappe.db.delete("SEPA Batch Upload Log", {})
        frappe.db.commit()

    def test_status_not_flipped_to_generated_when_final_step_fails(self):
        """
        Inject a failure in the LAST write _save_xml_file makes (the upload
        log's file_name update, which runs after status is already set to
        "Generated") and confirm the batch is not left reporting a
        generation that did not actually complete.
        """
        batch = self.factory.create_test_direct_debit_batch(invoice_count=1)

        original_set_value = frappe.db.set_value

        def _fail_on_upload_log_update(doctype, *args, **kwargs):
            if doctype == "SEPA Batch Upload Log":
                raise RuntimeError("injected failure: upload log update failed")
            return original_set_value(doctype, *args, **kwargs)

        with patch.object(frappe.db, "set_value", side_effect=_fail_on_upload_log_update):
            with self.assertRaises(Exception):
                self.service.generate_sepa_xml_for_batch(batch)

        # Read persisted state fresh via SQL - db_set bypasses the in-memory
        # document, so batch.status here would just reflect what we set
        # in-process rather than what actually reached the database.
        persisted = frappe.db.get_value(
            "Direct Debit Batch",
            batch.name,
            ["status", "sepa_file_generated", "sepa_file"],
            as_dict=True,
        )

        self.assertNotEqual(
            persisted.status,
            "Generated",
            "batch status was left as 'Generated' even though generation failed",
        )
        self.assertFalse(
            persisted.sepa_file_generated,
            "sepa_file_generated was left set even though generation failed",
        )
        self.assertFalse(
            persisted.sepa_file,
            "sepa_file was left attached even though generation failed",
        )
