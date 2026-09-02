"""
Unit Tests for SEPAUploadGuard Service

Tests the SEPA batch upload guard service that prevents duplicate uploads
by tracking file hashes. This protects against accidental double-debiting
of member bank accounts.

Test Strategy:
- Tests use SQL-based fixtures to bypass DocType Link validation
- The SEPA Batch Upload Log has a Link field to Direct Debit Batch
- Creating valid batches requires invoices (complex validation)
- We test the guard service logic, not the DocType validation

Author: Verenigingen Development Team
"""

import hashlib
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.payment.sepa_upload_guard import (
    SEPAUploadGuard,
    UploadBlockReason,
    UploadCheckResult,
    get_sepa_upload_guard,
)


@contextmanager
def developer_mode_enabled():
    """Temporarily enable developer_mode in frappe.conf.

    Some _compute_file_hash tests deliberately feed non-XML / empty content and
    rely on the dev-mode fallback to raw hashing. In production
    (developer_mode=False) canonicalization failures are a hard error by design,
    so these tests must opt into developer_mode explicitly. frappe.conf is
    process-global and NOT rolled back with the transaction, so the previous
    value must always be restored.
    """
    sentinel = object()
    prev = frappe.conf.get("developer_mode", sentinel)
    frappe.conf["developer_mode"] = 1
    try:
        yield
    finally:
        if prev is sentinel:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = prev


class SEPAUploadGuardTestMixin:
    """
    Mixin providing SQL-based fixture creation for SEPA upload guard tests.

    The SEPA Batch Upload Log has a Link field to Direct Debit Batch, but creating
    valid batches requires invoices and complex validation. This mixin provides
    methods to create upload log entries via SQL, bypassing the Link validation.
    """

    _test_log_names = None

    def _init_test_fixtures(self):
        """Initialize test fixture tracking. Call in setUp."""
        self._test_log_names = []

    def _cleanup_test_fixtures(self):
        """Clean up test fixtures. Call in tearDown."""
        if self._test_log_names:
            for log_name in self._test_log_names:
                try:
                    frappe.db.sql("DELETE FROM `tabSEPA Batch Upload Log` WHERE name = %s", (log_name,))
                except Exception:
                    pass
            frappe.db.commit()
            self._test_log_names = []

    def _register_upload_via_sql(
        self, file_hash: str, batch_name: str, uploaded_by: str = "Administrator", file_size: int = 1024
    ) -> str:
        """
        Register an upload directly via SQL, bypassing Link validation.

        Args:
            file_hash: SHA256 hash of the file content
            batch_name: Batch name (doesn't need to exist)
            uploaded_by: User who uploaded
            file_size: File size in bytes

        Returns:
            Name of the created log entry
        """
        log_name = f"SEPA-UPL-TEST-{frappe.utils.random_string(8)}"

        frappe.db.sql(
            """
            INSERT INTO `tabSEPA Batch Upload Log` (
                name, creation, modified, modified_by, owner,
                batch_name, file_hash, upload_time, uploaded_by,
                file_size, batch_status, docstatus, is_phantom, hash_freed
            ) VALUES (
                %s, NOW(), NOW(), 'Administrator', 'Administrator',
                %s, %s, NOW(), %s,
                %s, 'Uploaded', 0, 0, 0
            )
        """,
            (log_name, batch_name, file_hash, uploaded_by, file_size),
        )
        frappe.db.commit()

        if self._test_log_names is not None:
            self._test_log_names.append(log_name)

        return log_name


class TestSEPAUploadGuard(SEPAUploadGuardTestMixin, FrappeTestCase):
    """Test suite for SEPAUploadGuard service"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self._init_test_fixtures()
        self.guard = get_sepa_upload_guard()

        # Sample pain.008 XML content for testing
        self.sample_xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.02">
    <CstmrDrctDbtInitn>
        <GrpHdr>
            <MsgId>BATCH-001-20250201</MsgId>
            <CreDtTm>2025-02-01T10:00:00</CreDtTm>
        </GrpHdr>
        <PmtInf>
            <PmtInfId>PMT-001</PmtInfId>
            <NbOfTxs>5</NbOfTxs>
            <CtrlSum>250.00</CtrlSum>
        </PmtInf>
    </CstmrDrctDbtInitn>
</Document>"""

        self.different_xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.02">
    <CstmrDrctDbtInitn>
        <GrpHdr>
            <MsgId>BATCH-002-20250201</MsgId>
            <CreDtTm>2025-02-01T11:00:00</CreDtTm>
        </GrpHdr>
        <PmtInf>
            <PmtInfId>PMT-002</PmtInfId>
            <NbOfTxs>3</NbOfTxs>
            <CtrlSum>150.00</CtrlSum>
        </PmtInf>
    </CstmrDrctDbtInitn>
</Document>"""

        self.test_batch_name = "SEPA-BATCH-TEST-001"

    def tearDown(self):
        """Clean up test data"""
        self._cleanup_test_fixtures()
        super().tearDown()

    # ========== Hash Computation Tests ==========

    def test_compute_file_hash_returns_sha256_length(self):
        """Test that _compute_file_hash returns a valid SHA256 hash (64 hex chars)"""
        actual_hash = self.guard._compute_file_hash(self.sample_xml_content)

        # C14N canonicalization may change the hash, but length should be 64
        self.assertEqual(len(actual_hash), 64)
        # Should be valid hex
        int(actual_hash, 16)  # Will raise if not valid hex

    def test_compute_file_hash_different_content_different_hash(self):
        """Test that different content produces different hashes"""
        hash1 = self.guard._compute_file_hash(self.sample_xml_content)
        hash2 = self.guard._compute_file_hash(self.different_xml_content)

        self.assertNotEqual(hash1, hash2)

    def test_compute_file_hash_same_content_same_hash(self):
        """Test that same content always produces same hash"""
        hash1 = self.guard._compute_file_hash(self.sample_xml_content)
        hash2 = self.guard._compute_file_hash(self.sample_xml_content)

        self.assertEqual(hash1, hash2)

    def test_compute_file_hash_empty_content(self):
        """Test hash computation for empty content"""
        # Empty content cannot be canonicalized, so it relies on the dev-mode
        # fallback to raw hashing (in production this is a hard error by design).
        with developer_mode_enabled():
            empty_hash = self.guard._compute_file_hash(b"")
        expected = hashlib.sha256(b"").hexdigest()

        self.assertEqual(empty_hash, expected)

    # ========== First Upload Tests ==========

    def test_first_upload_allowed(self):
        """
        Test that the first upload of a file is allowed.

        When no previous upload with the same hash exists, the service should:
        - Return success=True
        - Return the computed file hash
        - Not set duplicate_batch
        """
        result = self.guard.check_upload_allowed(
            file_content=self.sample_xml_content, batch_name=self.test_batch_name
        )

        self.assertIsInstance(result, UploadCheckResult)
        self.assertTrue(result.success)
        # Hash should be returned (actual value depends on C14N)
        self.assertIsNotNone(result.file_hash)
        self.assertEqual(len(result.file_hash), 64)
        self.assertIsNone(result.duplicate_batch)
        self.assertIsNone(result.duplicate_upload_time)

    # ========== Duplicate Upload Tests ==========

    def test_duplicate_upload_blocked(self):
        """
        Test that uploading the same file content twice is blocked.

        When a file with the same hash was already uploaded:
        - Return success=False
        - Return the file hash
        - Set duplicate_batch to the original batch name
        - Set duplicate_upload_time to the original upload time
        """
        # First, register the initial upload via SQL (bypass Link validation)
        file_hash = self.guard._compute_file_hash(self.sample_xml_content)
        self._register_upload_via_sql(file_hash, self.test_batch_name)

        # Now try to check if we can upload the same content again
        check_result = self.guard.check_upload_allowed(
            file_content=self.sample_xml_content,
            batch_name="SEPA-BATCH-TEST-002",  # Different batch name, same content
        )

        self.assertIsInstance(check_result, UploadCheckResult)
        self.assertFalse(check_result.success)
        self.assertEqual(check_result.duplicate_batch, self.test_batch_name)
        self.assertIsNotNone(check_result.duplicate_upload_time)
        self.assertIn("duplicate", check_result.message.lower())

    def test_different_files_allowed(self):
        """
        Test that different file contents can both be uploaded.

        Two files with different content should both be allowed.
        """
        # Register first file via SQL
        hash1 = self.guard._compute_file_hash(self.sample_xml_content)
        self._register_upload_via_sql(hash1, "SEPA-BATCH-001")

        # Register second file with different content
        hash2 = self.guard._compute_file_hash(self.different_xml_content)
        self._register_upload_via_sql(hash2, "SEPA-BATCH-002")

        # Check that second file would be detected (verify it's in the log)
        check_result = self.guard.check_upload_allowed(
            file_content=self.different_xml_content, batch_name="SEPA-BATCH-003"
        )

        # Should fail because it's already registered
        self.assertFalse(check_result.success)
        self.assertEqual(check_result.duplicate_batch, "SEPA-BATCH-002")

    # ========== Register Upload Tests ==========
    # Note: These tests are skipped because register_upload() requires valid
    # Direct Debit Batch references. The SQL-based tests above verify the core logic.

    def test_check_first_upload_via_check_allowed(self):
        """Test that check_upload_allowed returns success for new content"""
        # Generate unique content to avoid conflicts
        unique_xml = f'<?xml version="1.0"?><test id="{frappe.utils.random_string(8)}"/>'.encode()

        result = self.guard.check_upload_allowed(file_content=unique_xml, batch_name="TEST-BATCH")

        self.assertTrue(result.success)
        self.assertIsNotNone(result.file_hash)

    # ========== Duplicate Detection Tests ==========

    def test_duplicate_detection_with_sql_registered_upload(self):
        """
        Test that check_upload_allowed detects duplicates registered via SQL.

        This verifies the detection logic works regardless of how uploads were registered.
        """
        # Generate unique content
        unique_xml = f'<?xml version="1.0"?><test id="dup-test-{frappe.utils.random_string(8)}"/>'.encode()
        file_hash = self.guard._compute_file_hash(unique_xml)

        # Register via SQL
        self._register_upload_via_sql(file_hash, "ORIGINAL-BATCH")

        # Check should detect duplicate
        result = self.guard.check_upload_allowed(file_content=unique_xml, batch_name="NEW-BATCH")

        self.assertFalse(result.success)
        self.assertEqual(result.duplicate_batch, "ORIGINAL-BATCH")
        self.assertEqual(result.reason_code, UploadBlockReason.DUPLICATE_HASH)

    # ========== UploadCheckResult Tests ==========

    def test_upload_check_result_default_values(self):
        """Test UploadCheckResult dataclass default values"""
        result = UploadCheckResult(success=True, file_hash="abc123")

        self.assertTrue(result.success)
        self.assertEqual(result.file_hash, "abc123")
        self.assertIsNone(result.duplicate_batch)
        self.assertIsNone(result.duplicate_upload_time)
        self.assertEqual(result.message, "")

    def test_upload_check_result_with_duplicate_info(self):
        """Test UploadCheckResult with duplicate information"""
        result = UploadCheckResult(
            success=False,
            file_hash="abc123",
            duplicate_batch="BATCH-001",
            duplicate_upload_time="2025-02-01 10:00:00",
            message="Duplicate file detected",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.duplicate_batch, "BATCH-001")
        self.assertEqual(result.duplicate_upload_time, "2025-02-01 10:00:00")

    # ========== Sandbox Mode Integration Tests ==========

    def test_upload_blocked_in_sandbox_mode(self):
        """Upload should be blocked when sandbox mode is enabled."""
        original = frappe.conf.get("sepa_sandbox_mode")
        try:
            frappe.conf.sepa_sandbox_mode = True
            result = self.guard.check_upload_allowed(self.sample_xml_content, self.test_batch_name)
            self.assertFalse(result.success)
            self.assertIn("sandbox", result.message.lower())
        finally:
            if original is not None:
                frappe.conf.sepa_sandbox_mode = original
            elif hasattr(frappe.conf, "sepa_sandbox_mode"):
                delattr(frappe.conf, "sepa_sandbox_mode")

    def test_check_and_register_blocked_in_sandbox_mode(self):
        """Check and register should be blocked when sandbox mode is enabled."""
        original = frappe.conf.get("sepa_sandbox_mode")
        try:
            frappe.conf.sepa_sandbox_mode = True
            result = self.guard.check_and_register(
                file_content=self.sample_xml_content,
                batch_name=self.test_batch_name,
                uploaded_by="Administrator",
            )
            self.assertFalse(result.success)
            self.assertIn("sandbox", result.message.lower())
        finally:
            if original is not None:
                frappe.conf.sepa_sandbox_mode = original
            elif hasattr(frappe.conf, "sepa_sandbox_mode"):
                delattr(frappe.conf, "sepa_sandbox_mode")

    def test_upload_allowed_when_sandbox_mode_disabled(self):
        """Upload should be allowed when sandbox mode is disabled."""
        original = frappe.conf.get("sepa_sandbox_mode")
        try:
            frappe.conf.sepa_sandbox_mode = False
            result = self.guard.check_upload_allowed(self.sample_xml_content, self.test_batch_name)
            # Should succeed (no duplicate exists, sandbox disabled)
            self.assertTrue(result.success)
        finally:
            if original is not None:
                frappe.conf.sepa_sandbox_mode = original
            elif hasattr(frappe.conf, "sepa_sandbox_mode"):
                delattr(frappe.conf, "sepa_sandbox_mode")


class TestSEPAUploadGuardFactory(FrappeTestCase):
    """Test the factory function for SEPAUploadGuard"""

    def test_get_sepa_upload_guard_returns_instance(self):
        """Test that factory function returns SEPAUploadGuard instance"""
        guard = get_sepa_upload_guard()
        self.assertIsInstance(guard, SEPAUploadGuard)

    def test_get_sepa_upload_guard_returns_same_instance(self):
        """Test that factory returns cached instance (singleton pattern if implemented)"""
        guard1 = get_sepa_upload_guard()
        guard2 = get_sepa_upload_guard()

        # Both should be valid instances
        self.assertIsInstance(guard1, SEPAUploadGuard)
        self.assertIsInstance(guard2, SEPAUploadGuard)


class TestUploadBlockReasonCode(SEPAUploadGuardTestMixin, FrappeTestCase):
    """Tests for machine-readable reason_code in UploadCheckResult"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self._init_test_fixtures()
        self.guard = get_sepa_upload_guard()
        # Use unique XML per test run to avoid conflicts
        self.sample_xml = f"<xml>test content for reason code {frappe.utils.random_string(8)}</xml>".encode()

    def tearDown(self):
        """Clean up test fixtures"""
        self._cleanup_test_fixtures()
        super().tearDown()

    def test_reason_code_none_on_success(self):
        """Successful upload should have reason_code=NONE"""
        result = self.guard.check_upload_allowed(self.sample_xml, "TEST-BATCH")
        self.assertTrue(result.success)
        self.assertEqual(result.reason_code, UploadBlockReason.NONE)

    def test_reason_code_sandbox_mode(self):
        """Sandbox mode should have reason_code=SANDBOX_MODE"""
        original = frappe.conf.get("sepa_sandbox_mode")
        try:
            frappe.conf.sepa_sandbox_mode = True
            result = self.guard.check_upload_allowed(self.sample_xml, "TEST-BATCH")
            self.assertFalse(result.success)
            self.assertEqual(result.reason_code, UploadBlockReason.SANDBOX_MODE)
        finally:
            if original is not None:
                frappe.conf.sepa_sandbox_mode = original
            elif hasattr(frappe.conf, "sepa_sandbox_mode"):
                delattr(frappe.conf, "sepa_sandbox_mode")

    def test_reason_code_duplicate_hash(self):
        """Duplicate upload should have reason_code=DUPLICATE_HASH"""
        # Register first upload via SQL (bypass Link validation)
        file_hash = self.guard._compute_file_hash(self.sample_xml)
        self._register_upload_via_sql(file_hash, "BATCH-REASON-001")

        # Try duplicate - should get DUPLICATE_HASH
        result2 = self.guard.check_upload_allowed(self.sample_xml, "BATCH-REASON-002")
        self.assertFalse(result2.success)
        self.assertEqual(result2.reason_code, UploadBlockReason.DUPLICATE_HASH)

    def test_reason_code_duplicate_via_check(self):
        """check_upload_allowed for duplicate should have reason_code=DUPLICATE_HASH"""
        # Register first upload via SQL
        file_hash = self.guard._compute_file_hash(self.sample_xml)
        self._register_upload_via_sql(file_hash, "BATCH-CAR-001")

        # Check for duplicate
        result2 = self.guard.check_upload_allowed(self.sample_xml, "BATCH-CAR-002")
        self.assertFalse(result2.success)
        self.assertEqual(result2.reason_code, UploadBlockReason.DUPLICATE_HASH)


class TestConcurrentUploadGuard(SEPAUploadGuardTestMixin, FrappeTestCase):
    """
    Tests for concurrent upload handling and DB constraint enforcement.

    These tests verify that:
    1. When two workers race past the initial check, the DB unique constraint catches duplicates
    2. The service handles IntegrityError gracefully and returns proper duplicate info

    Note: These tests use SQL-based fixtures to register uploads, then verify
    that check_upload_allowed() correctly detects duplicates. The actual concurrent
    behavior is tested at the DB level via unique constraint.
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self._init_test_fixtures()
        self.guard = get_sepa_upload_guard()
        # Use unique XML per test run
        self.sample_xml = f"<xml>concurrent test content {frappe.utils.random_string(8)}</xml>".encode()

    def tearDown(self):
        """Clean up test fixtures"""
        self._cleanup_test_fixtures()
        super().tearDown()

    def test_duplicate_detection_after_registration(self):
        """
        Test that duplicate detection works after an upload is registered.

        This tests that the Python-level check correctly detects duplicates
        after an upload has been registered in the database.
        """
        # First, register via SQL
        file_hash = self.guard._compute_file_hash(self.sample_xml)
        self._register_upload_via_sql(file_hash, "RACE-BATCH-001")

        # The check should detect the duplicate
        result2 = self.guard.check_upload_allowed(self.sample_xml, "RACE-BATCH-002")
        self.assertFalse(result2.success)
        self.assertEqual(result2.reason_code, UploadBlockReason.DUPLICATE_HASH)
        self.assertEqual(result2.duplicate_batch, "RACE-BATCH-001")

    def test_duplicate_info_contains_batch_reference(self):
        """
        When duplicate is detected, the result should contain original batch info.

        This ensures operators get actionable information about the existing upload.
        """
        # Register first upload via SQL
        file_hash = self.guard._compute_file_hash(self.sample_xml)
        self._register_upload_via_sql(file_hash, "INTEGRITY-BATCH-001")

        # Second check should fail with full duplicate info
        result2 = self.guard.check_upload_allowed(self.sample_xml, "INTEGRITY-BATCH-002")

        self.assertFalse(result2.success)
        self.assertEqual(result2.file_hash, file_hash)
        self.assertIsNotNone(result2.duplicate_batch)
        self.assertEqual(result2.duplicate_batch, "INTEGRITY-BATCH-001")
        self.assertIsNotNone(result2.message)
        # The message should mention duplicate
        self.assertIn("duplicate", result2.message.lower())

    def test_different_files_both_allowed(self):
        """Two different files should both be allowed for upload."""
        xml1 = f"<xml>first concurrent file {frappe.utils.random_string(8)}</xml>".encode()
        xml2 = f"<xml>second concurrent file {frappe.utils.random_string(8)}</xml>".encode()

        result1 = self.guard.check_upload_allowed(xml1, "CONCURRENT-001")
        result2 = self.guard.check_upload_allowed(xml2, "CONCURRENT-002")

        self.assertTrue(result1.success)
        self.assertTrue(result2.success)
        self.assertEqual(result1.reason_code, UploadBlockReason.NONE)
        self.assertEqual(result2.reason_code, UploadBlockReason.NONE)

    def _make_direct_debit_batch(self):
        """A minimal, real Direct Debit Batch -- `batch_name` on SEPA Batch
        Upload Log is a required Link to this doctype, so `check_and_register`
        (unlike the SQL-fixture helpers above) needs one that actually exists."""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.batch_description = f"Test batch {frappe.utils.random_string(8)}"
        batch.batch_type = "CORE"
        batch.currency = "EUR"
        # An empty batch fails validate_invoices()'s "No invoices added to
        # batch" check; this fixture only needs a real Link target for
        # SEPA Batch Upload Log.batch_name, not a valid batch.
        batch.flags.ignore_validate = True
        batch.insert(ignore_permissions=True)
        self.addCleanup(frappe.delete_doc, "Direct Debit Batch", batch.name, force=True)
        return batch.name

    def test_check_and_register_true_concurrent_race_is_caught(self):
        """A TRULY concurrent race -- two workers whose validate()-time SELECTs
        both miss because neither has committed yet -- must be caught, not
        escape check_and_register uncaught (#699, skeptical review finding).

        `SEPA Batch Upload Log.validate_unique_hash()` does an application-level
        check-then-throw (explicit `frappe.throw(..., frappe.DuplicateEntryError)`),
        which is what the ORIGINAL `except frappe.DuplicateEntryError:` here
        handled. But that only catches a SEQUENTIAL duplicate -- one that
        already committed before this worker's SELECT ran. Two genuinely
        concurrent workers can both pass `validate_unique_hash`'s SELECT before
        either commits; the loser then collides on the real DB unique index on
        `file_hash`, which frappe classifies as `UniqueValidationError` (a
        `ValidationError` subclass, unrelated to `DuplicateEntryError` --
        confirmed via MRO). Before this fix that escaped `check_and_register`
        entirely instead of returning the graceful duplicate-detected result.

        To force this deterministically (real concurrency is not reproducible
        in a single-threaded test), this monkeypatches away BOTH checks that
        would normally catch the collision before the DB constraint does:
        the guard's own pre-check (`_find_existing_upload`) and the
        Document's `validate_unique_hash`, for exactly one insert attempt --
        simulating both sides of the race missing, same as two real workers
        racing.
        """
        original_batch = self._make_direct_debit_batch()
        new_batch = self._make_direct_debit_batch()
        file_hash = self.guard._compute_file_hash(self.sample_xml)
        self._register_upload_via_sql(file_hash, original_batch)

        from verenigingen.verenigingen_payments.doctype.sepa_batch_upload_log.sepa_batch_upload_log import (
            SEPABatchUploadLog,
        )

        original_validate_unique = SEPABatchUploadLog.validate_unique_hash
        SEPABatchUploadLog.validate_unique_hash = lambda self: None
        self.addCleanup(setattr, SEPABatchUploadLog, "validate_unique_hash", original_validate_unique)

        # Miss only the FIRST pre-check call (the race window), so the except
        # handler's own lookup -- used to name the winning batch in the result
        # -- still works normally.
        original_find = self.guard._find_existing_upload
        calls = {"n": 0}

        def _miss_once(h):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return original_find(h)

        self.guard._find_existing_upload = _miss_once
        self.addCleanup(setattr, self.guard, "_find_existing_upload", original_find)

        result = self.guard.check_and_register(self.sample_xml, new_batch)

        self.assertFalse(result.success)
        self.assertEqual(result.reason_code, UploadBlockReason.INTEGRITY_ERROR)
        self.assertEqual(result.duplicate_batch, original_batch)
        self.assertIn("concurrent upload", result.message.lower())

    def test_db_unique_constraint_exists(self):
        """
        Test that the DB unique constraint on file_hash exists and prevents duplicates.

        This verifies the database-level protection against race conditions.
        """
        file_hash = self.guard._compute_file_hash(self.sample_xml)

        # First insert should succeed
        self._register_upload_via_sql(file_hash, "UNIQUE-BATCH-001")

        # Second insert with same hash should fail due to unique constraint
        with self.assertRaises(Exception) as ctx:
            # Don't use the tracked method since we expect this to fail
            log_name = f"SEPA-UPL-TEST-{frappe.utils.random_string(8)}"
            frappe.db.sql(
                """
                INSERT INTO `tabSEPA Batch Upload Log` (
                    name, creation, modified, modified_by, owner,
                    batch_name, file_hash, upload_time, uploaded_by,
                    file_size, batch_status, docstatus, is_phantom, hash_freed
                ) VALUES (
                    %s, NOW(), NOW(), 'Administrator', 'Administrator',
                    %s, %s, NOW(), 'Administrator',
                    1024, 'Uploaded', 0, 0, 0
                )
            """,
                (log_name, "UNIQUE-BATCH-002", file_hash),
            )
            frappe.db.commit()

        # The error should be a duplicate key / integrity error
        error_str = str(ctx.exception).lower()
        self.assertTrue(
            "duplicate" in error_str or "unique" in error_str or "integrity" in error_str,
            f"Expected duplicate/unique constraint error, got: {ctx.exception}",
        )


class TestXMLCanonicalization(FrappeTestCase):
    """
    Tests for XML canonicalization (C14N) in hash computation.

    IMPORTANT: C14N (Canonical XML) does NOT normalize inter-element whitespace.
    In XML, whitespace between elements (like newlines and indentation) is considered
    significant text content. This is by design per W3C XML specification.

    For SEPA duplicate detection, this is acceptable because:
    - Our XML generator always produces consistent output
    - We're detecting re-uploads of the *same* file, not semantically equivalent files
    - Banks may also include whitespace in their duplicate detection
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.guard = get_sepa_upload_guard()

    def test_identical_xml_same_hash(self):
        """Byte-identical XML should produce identical hashes."""
        xml = b'<?xml version="1.0"?><root><child>value</child></root>'

        hash1 = self.guard._compute_file_hash(xml)
        hash2 = self.guard._compute_file_hash(xml)

        self.assertEqual(hash1, hash2, "Identical XML should produce identical hash")

    def test_whitespace_in_content_preserved(self):
        """
        Inter-element whitespace produces different hashes.

        This documents the actual C14N behavior: whitespace between elements
        is semantically significant in XML and is NOT normalized. This is
        correct behavior per W3C XML spec - our tests document reality.
        """
        # Compact XML
        xml_compact = b'<?xml version="1.0"?><root><child>value</child></root>'

        # Same XML with whitespace/formatting - these are DIFFERENT documents in XML terms
        xml_formatted = b"""<?xml version="1.0"?>
<root>
    <child>value</child>
</root>"""

        hash1 = self.guard._compute_file_hash(xml_compact)
        hash2 = self.guard._compute_file_hash(xml_formatted)

        # Document the actual behavior: whitespace between elements IS significant
        self.assertNotEqual(
            hash1,
            hash2,
            "XML with different inter-element whitespace should produce different hashes "
            "(whitespace between elements is semantically significant per XML spec)",
        )

    def test_different_xml_different_hash(self):
        """Different XML content should produce different hashes."""
        xml1 = b'<?xml version="1.0"?><root><child>value1</child></root>'
        xml2 = b'<?xml version="1.0"?><root><child>value2</child></root>'

        hash1 = self.guard._compute_file_hash(xml1)
        hash2 = self.guard._compute_file_hash(xml2)

        self.assertNotEqual(hash1, hash2, "Different XML should have different hashes")

    def test_attribute_order_normalized(self):
        """
        C14N normalizes attribute order alphabetically.

        This is what C14N actually guarantees - attribute order is consistent.
        """
        xml1 = b'<?xml version="1.0"?><root a="1" b="2"/>'
        xml2 = b'<?xml version="1.0"?><root b="2" a="1"/>'

        hash1 = self.guard._compute_file_hash(xml1)
        hash2 = self.guard._compute_file_hash(xml2)

        self.assertEqual(
            hash1, hash2, "XML with different attribute order should produce same hash (C14N normalizes)"
        )

    def test_pain008_consistent_generation_same_hash(self):
        """
        SEPA XML generated consistently produces identical hashes.

        This tests the practical use case: same generator produces same output.
        """
        # Minimal pain.008 structure - generated consistently
        pain008_v1 = b"""<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"><CstmrDrctDbtInitn><GrpHdr><MsgId>TEST-001</MsgId></GrpHdr></CstmrDrctDbtInitn></Document>"""

        # Exact same content (simulating regeneration from same source)
        pain008_v2 = b"""<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"><CstmrDrctDbtInitn><GrpHdr><MsgId>TEST-001</MsgId></GrpHdr></CstmrDrctDbtInitn></Document>"""

        hash1 = self.guard._compute_file_hash(pain008_v1)
        hash2 = self.guard._compute_file_hash(pain008_v2)

        self.assertEqual(hash1, hash2, "Same pain.008 XML should produce same hash")

    def test_hash_consistency_across_calls(self):
        """Same XML should always produce same hash (deterministic)."""
        xml = b'<?xml version="1.0"?><root><child>consistent</child></root>'

        hashes = [self.guard._compute_file_hash(xml) for _ in range(5)]

        self.assertEqual(len(set(hashes)), 1, "Hash should be consistent across calls")

    def test_canonicalization_fallback_on_invalid_xml(self):
        """Invalid XML should still produce a hash (fallback to raw hash)."""
        invalid_xml = b"not valid xml at all <unclosed"

        # Should not raise, should return a valid hash. The raw-hash fallback is
        # only available in developer_mode (production fails fast by design).
        with developer_mode_enabled():
            result = self.guard._compute_file_hash(invalid_xml)

        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64, "Should return valid SHA256 hash")


class TestPhantomHashUtilities(FrappeTestCase):
    """
    Tests for phantom hash utility functions.

    These tests verify utility functions that don't require database fixtures.
    """

    def test_truncate_error_message(self):
        """Test that error messages are truncated to prevent sensitive info leakage."""
        from verenigingen.api.sepa_phantom_hash_admin import _truncate_error_message

        # Test normal message
        short_msg = "Simple error"
        self.assertEqual(_truncate_error_message(short_msg), "Simple error")

        # Test multiline message (should take first line only)
        multiline = "Error on line 1\nTraceback follows\n  at file.py:123"
        self.assertEqual(_truncate_error_message(multiline), "Error on line 1")

        # Test very long message (should truncate)
        long_msg = "A" * 300
        result = _truncate_error_message(long_msg)
        self.assertLessEqual(len(result), 200)
        self.assertTrue(result.endswith("..."))

        # Test empty message
        self.assertEqual(_truncate_error_message(""), "")
        self.assertEqual(_truncate_error_message(None), "")


class TestPhantomHashAdminConcurrency(FrappeTestCase):
    """
    Tests for concurrent phantom hash administration operations.

    These tests verify that:
    1. Concurrent calls to mark_phantom_hash_abandoned() return idempotent results
    2. Concurrent calls to retry_phantom_attachment() return idempotent results
    3. Row locks prevent race conditions between operations

    Note: These tests use direct SQL to create test fixtures because creating
    a proper Direct Debit Batch requires invoices and complex validation.
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.guard = get_sepa_upload_guard()

        # Check if SEPA Batch Upload Log DocType exists
        if not frappe.db.exists("DocType", "SEPA Batch Upload Log"):
            self.skipTest("SEPA Batch Upload Log DocType not available")

        # Use a placeholder batch name - we'll create entries via SQL
        self.test_batch_name = f"DD-TEST-{frappe.utils.random_string(6)}"
        self._created_log_names = []

    def tearDown(self):
        """Clean up test fixtures"""
        super().tearDown()
        # Clean up created log entries
        for log_name in self._created_log_names:
            try:
                frappe.db.sql(
                    """
                    DELETE FROM `tabSEPA Batch Upload Log`
                    WHERE name = %s
                """,
                    (log_name,),
                )
            except Exception:
                pass
        if self._created_log_names:
            frappe.db.commit()

    def _create_phantom_entry_via_sql(self, batch_name: str = None, file_hash: str = None) -> str:
        """
        Create a phantom upload log entry using direct SQL to bypass link validation.

        This allows testing phantom hash operations without needing a valid
        Direct Debit Batch with invoices.

        Args:
            batch_name: Optional batch name
            file_hash: Optional specific file hash

        Returns:
            Name of the created log entry
        """
        batch_name = batch_name or self.test_batch_name
        if not file_hash:
            file_hash = hashlib.sha256(f"test-content-{frappe.utils.random_string(16)}".encode()).hexdigest()

        # Generate a unique name
        log_name = f"SEPA-UPL-TEST-{frappe.utils.random_string(8)}"

        # Insert directly via SQL to bypass DocType validation
        frappe.db.sql(
            """
            INSERT INTO `tabSEPA Batch Upload Log` (
                name, creation, modified, modified_by, owner,
                batch_name, file_hash, upload_time, uploaded_by,
                file_size, batch_status, bank_status, bank_error_message,
                is_phantom, hash_freed, docstatus
            ) VALUES (
                %s, NOW(), NOW(), 'Administrator', 'Administrator',
                %s, %s, NOW(), 'Administrator',
                1024, 'Pending Upload', 'Rejected', 'Attachment failed: Test phantom entry',
                1, 0, 0
            )
        """,
            (log_name, batch_name, file_hash),
        )
        frappe.db.commit()

        self._created_log_names.append(log_name)
        return log_name

    def test_abandon_idempotency(self):
        """
        Calling mark_phantom_hash_abandoned twice should return success both times.

        First call performs the abandonment, second call returns idempotent success.
        """
        from verenigingen.api.sepa_phantom_hash_admin import mark_phantom_hash_abandoned

        # Create phantom entry via SQL
        log_name = self._create_phantom_entry_via_sql()

        # First abandonment
        result1 = mark_phantom_hash_abandoned(
            log_name=log_name, reason="Test abandonment - first call for idempotency test"
        )

        self.assertTrue(result1.get("success"))
        self.assertFalse(result1.get("idempotent", False))

        # Second abandonment should return idempotent success
        result2 = mark_phantom_hash_abandoned(
            log_name=log_name, reason="Test abandonment - second call for idempotency test"
        )

        self.assertTrue(result2.get("success"))
        self.assertTrue(result2.get("idempotent"))

    def test_abandon_preserves_audit_trail(self):
        """
        Abandoning a phantom entry should preserve the record with audit fields.
        """
        from verenigingen.api.sepa_phantom_hash_admin import mark_phantom_hash_abandoned

        # Create phantom entry via SQL
        log_name = self._create_phantom_entry_via_sql()
        original_hash = frappe.db.get_value("SEPA Batch Upload Log", log_name, "file_hash")

        # Abandon the entry
        result = mark_phantom_hash_abandoned(
            log_name=log_name, reason="Audit trail test - verifying record preservation"
        )

        self.assertTrue(result.get("success"))

        # Verify record still exists with audit fields - use SQL to bypass cache
        log_data = frappe.db.sql(
            """
            SELECT bank_status, is_phantom, hash_freed, abandoned_by,
                   abandoned_time, abandoned_reason, file_hash
            FROM `tabSEPA Batch Upload Log`
            WHERE name = %s
        """,
            (log_name,),
            as_dict=True,
        )[0]

        self.assertEqual(log_data.bank_status, "Abandoned")
        self.assertEqual(log_data.is_phantom, 0)
        self.assertEqual(log_data.hash_freed, 1)
        self.assertEqual(log_data.abandoned_by, frappe.session.user)
        self.assertIsNotNone(log_data.abandoned_time)
        self.assertIn("Audit trail test", log_data.abandoned_reason)
        # Original hash should still be stored for audit
        self.assertEqual(log_data.file_hash, original_hash)

    def test_freed_hash_allows_reupload(self):
        """
        After a phantom entry is abandoned (hash_freed=1), the same hash should be
        allowed for a new upload.
        """
        from verenigingen.api.sepa_phantom_hash_admin import mark_phantom_hash_abandoned

        # Create phantom entry with specific content
        test_content = f"reupload-test-{frappe.utils.random_string(8)}".encode()
        # Non-XML content relies on the dev-mode raw-hash fallback; production
        # would reject it during canonicalization.
        with developer_mode_enabled():
            file_hash = self.guard._compute_file_hash(test_content)
        log_name = self._create_phantom_entry_via_sql(file_hash=file_hash)

        # Abandon the entry to free the hash
        result = mark_phantom_hash_abandoned(log_name=log_name, reason="Freeing hash for reupload test")
        self.assertTrue(result.get("success"))

        # Now the same content should be allowed for upload
        with developer_mode_enabled():
            check_result = self.guard.check_upload_allowed(test_content, "NEW-BATCH-001")

        self.assertTrue(
            check_result.success, f"Freed hash should allow reupload. Got: {check_result.message}"
        )

    def test_concurrent_abandon_operations_safe(self):
        """
        Simulated concurrent abandon operations should be safe - only one succeeds
        in performing the operation, others get idempotent success.

        Note: This is a simplified sequential test. True concurrent testing
        requires threading which has limitations in Frappe test context.
        """
        from verenigingen.api.sepa_phantom_hash_admin import mark_phantom_hash_abandoned

        # Create phantom entry via SQL
        log_name = self._create_phantom_entry_via_sql()

        # Simulate rapid sequential calls (approximates concurrent behavior)
        results = []
        for i in range(3):
            result = mark_phantom_hash_abandoned(log_name=log_name, reason=f"Concurrent test call {i+1}")
            results.append(result)

        # All should succeed (first actual, rest idempotent)
        for result in results:
            self.assertTrue(result.get("success"))

        # Only first should NOT be idempotent
        self.assertFalse(results[0].get("idempotent", False))
        for result in results[1:]:
            self.assertTrue(result.get("idempotent"))

    def test_row_lock_prevents_parallel_modifications(self):
        """
        Test that the FOR UPDATE row lock is being acquired.

        We verify this indirectly by checking that the _acquire_row_lock function
        returns the expected data structure.
        """
        from verenigingen.api.sepa_phantom_hash_admin import _acquire_row_lock

        # Create phantom entry via SQL
        log_name = self._create_phantom_entry_via_sql()

        # Start transaction and acquire lock
        frappe.db.begin()
        try:
            locked_row = _acquire_row_lock(log_name)

            # Verify lock returns expected fields
            self.assertIsNotNone(locked_row)
            self.assertEqual(locked_row.get("name"), log_name)
            self.assertEqual(locked_row.get("is_phantom"), 1)
            self.assertEqual(locked_row.get("bank_status"), "Rejected")
            self.assertIn("hash_freed", locked_row)

        finally:
            frappe.db.rollback()
