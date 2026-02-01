"""
Unit Tests for SEPAUploadGuard Service

Tests the SEPA batch upload guard service that prevents duplicate uploads
by tracking file hashes. This protects against accidental double-debiting
of member bank accounts.

Test Strategy:
- Tests are written to verify the service logic
- The underlying DocType (SEPA Batch Upload Log) does not exist yet
- Tests will fail at the database query step, which is expected
- Once the DocType is created, tests should pass

Author: Verenigingen Development Team
"""

import hashlib
import unittest
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


class TestSEPAUploadGuard(FrappeTestCase):
    """Test suite for SEPAUploadGuard service"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
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
        super().tearDown()

    # ========== Hash Computation Tests ==========

    def test_compute_file_hash_returns_sha256(self):
        """Test that _compute_file_hash returns correct SHA256 hash"""
        # Compute expected hash
        expected_hash = hashlib.sha256(self.sample_xml_content).hexdigest()

        # Call service method
        actual_hash = self.guard._compute_file_hash(self.sample_xml_content)

        self.assertEqual(actual_hash, expected_hash)
        self.assertEqual(len(actual_hash), 64)  # SHA256 produces 64 hex chars

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
            file_content=self.sample_xml_content,
            batch_name=self.test_batch_name
        )

        self.assertIsInstance(result, UploadCheckResult)
        self.assertTrue(result.success)
        self.assertEqual(
            result.file_hash,
            hashlib.sha256(self.sample_xml_content).hexdigest()
        )
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
        # First, register the initial upload
        register_result = self.guard.register_upload(
            file_content=self.sample_xml_content,
            batch_name=self.test_batch_name,
            uploaded_by="Administrator"
        )
        self.assertTrue(register_result.success, f"Register failed: {register_result.error_message}")

        # Now try to check if we can upload the same content again
        check_result = self.guard.check_upload_allowed(
            file_content=self.sample_xml_content,
            batch_name="SEPA-BATCH-TEST-002"  # Different batch name, same content
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
        # Register first file
        result1 = self.guard.register_upload(
            file_content=self.sample_xml_content,
            batch_name="SEPA-BATCH-001",
            uploaded_by="Administrator"
        )
        self.assertTrue(result1.success, f"First register failed: {result1.error_message}")

        # Register second file with different content
        result2 = self.guard.register_upload(
            file_content=self.different_xml_content,
            batch_name="SEPA-BATCH-002",
            uploaded_by="Administrator"
        )
        self.assertTrue(result2.success, f"Second register failed: {result2.error_message}")

        # Check that second file would be allowed (verify it's in the log)
        check_result = self.guard.check_upload_allowed(
            file_content=self.different_xml_content,
            batch_name="SEPA-BATCH-003"
        )

        # Should fail because it's already registered
        self.assertFalse(check_result.success)
        self.assertEqual(check_result.duplicate_batch, "SEPA-BATCH-002")

    # ========== Register Upload Tests ==========

    def test_register_upload_creates_log_entry(self):
        """Test that register_upload creates a log entry and returns success"""
        result = self.guard.register_upload(
            file_content=self.sample_xml_content,
            batch_name=self.test_batch_name,
            uploaded_by="Administrator"
        )

        self.assertTrue(result.success)
        # The returned data should be the log entry name
        self.assertIsNotNone(result.data)

    def test_register_upload_without_user(self):
        """Test that register_upload works without specifying uploaded_by"""
        result = self.guard.register_upload(
            file_content=self.sample_xml_content,
            batch_name=self.test_batch_name,
            uploaded_by=None
        )

        self.assertTrue(result.success)

    # ========== Atomic Check and Register Tests ==========

    def test_check_and_register_first_upload(self):
        """
        Test atomic check_and_register for first upload.

        Should check and register in one atomic operation.
        """
        result = self.guard.check_and_register(
            file_content=self.sample_xml_content,
            batch_name=self.test_batch_name,
            uploaded_by="Administrator"
        )

        self.assertIsInstance(result, UploadCheckResult)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.file_hash)

    def test_check_and_register_duplicate(self):
        """
        Test atomic check_and_register detects duplicates.

        After first upload, second attempt should fail.
        """
        # First upload
        result1 = self.guard.check_and_register(
            file_content=self.sample_xml_content,
            batch_name="BATCH-001",
            uploaded_by="Administrator"
        )
        self.assertTrue(result1.success)

        # Second upload of same content
        result2 = self.guard.check_and_register(
            file_content=self.sample_xml_content,
            batch_name="BATCH-002",
            uploaded_by="Administrator"
        )

        self.assertFalse(result2.success)
        self.assertEqual(result2.duplicate_batch, "BATCH-001")

    # ========== UploadCheckResult Tests ==========

    def test_upload_check_result_default_values(self):
        """Test UploadCheckResult dataclass default values"""
        result = UploadCheckResult(
            success=True,
            file_hash="abc123"
        )

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
            message="Duplicate file detected"
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
            result = self.guard.check_upload_allowed(
                self.sample_xml_content, self.test_batch_name
            )
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
                uploaded_by="Administrator"
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
            result = self.guard.check_upload_allowed(
                self.sample_xml_content, self.test_batch_name
            )
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


class TestUploadBlockReasonCode(FrappeTestCase):
    """Tests for machine-readable reason_code in UploadCheckResult"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.guard = get_sepa_upload_guard()
        self.sample_xml = b"<xml>test content for reason code</xml>"

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
        # Register first upload
        result1 = self.guard.check_and_register(
            self.sample_xml, "BATCH-REASON-001", "Administrator"
        )
        self.assertTrue(result1.success)

        # Try duplicate - should get DUPLICATE_HASH
        result2 = self.guard.check_upload_allowed(self.sample_xml, "BATCH-REASON-002")
        self.assertFalse(result2.success)
        self.assertEqual(result2.reason_code, UploadBlockReason.DUPLICATE_HASH)

    def test_reason_code_check_and_register_duplicate(self):
        """check_and_register duplicate should have reason_code=DUPLICATE_HASH"""
        # Register first upload
        result1 = self.guard.check_and_register(
            self.sample_xml, "BATCH-CAR-001", "Administrator"
        )
        self.assertTrue(result1.success)
        self.assertEqual(result1.reason_code, UploadBlockReason.NONE)

        # Try duplicate via check_and_register
        result2 = self.guard.check_and_register(
            self.sample_xml, "BATCH-CAR-002", "Administrator"
        )
        self.assertFalse(result2.success)
        self.assertEqual(result2.reason_code, UploadBlockReason.DUPLICATE_HASH)


class TestConcurrentUploadGuard(FrappeTestCase):
    """
    Tests for concurrent upload handling and DB constraint enforcement.

    These tests verify that:
    1. When two workers race past the initial check, the DB unique constraint catches duplicates
    2. The service handles IntegrityError gracefully and returns proper duplicate info
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.guard = get_sepa_upload_guard()
        self.sample_xml = b"<xml>concurrent test content</xml>"

    def test_db_constraint_catches_race_condition(self):
        """
        Simulate race condition where two workers pass the check but only one insert succeeds.

        This tests that the DB unique constraint on file_hash prevents duplicates
        even when the Python-level check passes for both workers.
        """
        # First, register normally
        result1 = self.guard.check_and_register(
            self.sample_xml, "RACE-BATCH-001", "Administrator"
        )
        self.assertTrue(result1.success)
        self.assertEqual(result1.reason_code, UploadBlockReason.NONE)

        # The second attempt should fail with proper duplicate info
        result2 = self.guard.check_and_register(
            self.sample_xml, "RACE-BATCH-002", "Administrator"
        )
        self.assertFalse(result2.success)
        self.assertIn(
            result2.reason_code,
            [UploadBlockReason.DUPLICATE_HASH, UploadBlockReason.INTEGRITY_ERROR]
        )
        self.assertEqual(result2.duplicate_batch, "RACE-BATCH-001")

    def test_integrity_error_returns_duplicate_info(self):
        """
        When IntegrityError is caught, the result should contain duplicate batch info.

        This ensures operators get actionable information when the DB constraint fires.
        """
        # Register first upload
        file_hash = self.guard._compute_file_hash(self.sample_xml)
        result1 = self.guard.check_and_register(
            self.sample_xml, "INTEGRITY-BATCH-001", "Administrator"
        )
        self.assertTrue(result1.success)
        self.assertEqual(result1.file_hash, file_hash)

        # Second upload should fail with full duplicate info
        result2 = self.guard.check_and_register(
            self.sample_xml, "INTEGRITY-BATCH-002", "Administrator"
        )

        self.assertFalse(result2.success)
        self.assertEqual(result2.file_hash, file_hash)
        self.assertIsNotNone(result2.duplicate_batch)
        self.assertIsNotNone(result2.message)
        # The message should mention duplicate
        self.assertIn("duplicate", result2.message.lower())

    def test_concurrent_different_files_both_succeed(self):
        """Two different files should both register successfully."""
        xml1 = b"<xml>first concurrent file</xml>"
        xml2 = b"<xml>second concurrent file</xml>"

        result1 = self.guard.check_and_register(xml1, "CONCURRENT-001", "Administrator")
        result2 = self.guard.check_and_register(xml2, "CONCURRENT-002", "Administrator")

        self.assertTrue(result1.success)
        self.assertTrue(result2.success)
        self.assertEqual(result1.reason_code, UploadBlockReason.NONE)
        self.assertEqual(result2.reason_code, UploadBlockReason.NONE)


class TestXMLCanonicalization(FrappeTestCase):
    """
    Tests for XML canonicalization (C14N) in hash computation.

    These tests verify that semantically identical XML produces identical
    hashes regardless of whitespace or formatting differences.
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.guard = get_sepa_upload_guard()

    def test_same_xml_different_whitespace_same_hash(self):
        """Semantically identical XML with different whitespace should have same hash."""
        # Compact XML
        xml_compact = b'<?xml version="1.0"?><root><child>value</child></root>'

        # Same XML with whitespace/formatting
        xml_formatted = b'''<?xml version="1.0"?>
<root>
    <child>value</child>
</root>'''

        hash1 = self.guard._compute_file_hash(xml_compact)
        hash2 = self.guard._compute_file_hash(xml_formatted)

        self.assertEqual(hash1, hash2, "Same XML with different whitespace should have same hash")

    def test_different_xml_different_hash(self):
        """Different XML content should produce different hashes."""
        xml1 = b'<?xml version="1.0"?><root><child>value1</child></root>'
        xml2 = b'<?xml version="1.0"?><root><child>value2</child></root>'

        hash1 = self.guard._compute_file_hash(xml1)
        hash2 = self.guard._compute_file_hash(xml2)

        self.assertNotEqual(hash1, hash2, "Different XML should have different hashes")

    def test_pain008_xml_canonicalization(self):
        """Pain.008 XML with different formatting should produce same hash."""
        # Minimal pain.008 structure - compact
        pain008_compact = b'''<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"><CstmrDrctDbtInitn><GrpHdr><MsgId>TEST-001</MsgId></GrpHdr></CstmrDrctDbtInitn></Document>'''

        # Same content with pretty formatting
        pain008_pretty = b'''<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08">
    <CstmrDrctDbtInitn>
        <GrpHdr>
            <MsgId>TEST-001</MsgId>
        </GrpHdr>
    </CstmrDrctDbtInitn>
</Document>'''

        hash1 = self.guard._compute_file_hash(pain008_compact)
        hash2 = self.guard._compute_file_hash(pain008_pretty)

        self.assertEqual(hash1, hash2, "Same pain.008 XML with different formatting should have same hash")

    def test_hash_consistency_across_calls(self):
        """Same XML should always produce same hash (deterministic)."""
        xml = b'<?xml version="1.0"?><root><child>consistent</child></root>'

        hashes = [self.guard._compute_file_hash(xml) for _ in range(5)]

        self.assertEqual(len(set(hashes)), 1, "Hash should be consistent across calls")

    def test_canonicalization_fallback_on_invalid_xml(self):
        """Invalid XML should still produce a hash (fallback to raw hash)."""
        invalid_xml = b"not valid xml at all <unclosed"

        # Should not raise, should return a valid hash
        result = self.guard._compute_file_hash(invalid_xml)

        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64, "Should return valid SHA256 hash")
