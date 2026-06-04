"""
Unit Tests for Pain002IngestionService

Tests the automated pain.002 (Bank Status Report) ingestion service that:
1. Scans a configured directory for pain.002 XML files
2. Parses them to extract batch status (ACCP, RJCT, PART)
3. Updates SEPA Batch Upload Log with bank response
4. Archives processed files

Test Strategy:
    - Uses temporary directories for inbox/archive/error paths
    - Creates sample pain.002 XML files for parsing tests
    - Tests file operations (scan, archive, error handling)
    - Tests status extraction and batch log updates

Author: Verenigingen Development Team
"""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.payment.pain002_ingestion_service import (
    Pain002IngestionService,
    get_pain002_ingestion_service,
)
from verenigingen.utils.operation_result import OperationResult


class TestPain002IngestionService(FrappeTestCase):
    """Test suite for Pain002IngestionService"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()

        # Create temporary directories for testing
        self.temp_dir = tempfile.mkdtemp()
        self.inbox_dir = os.path.join(self.temp_dir, "inbox")
        self.archive_dir = os.path.join(self.temp_dir, "archive")
        self.error_dir = os.path.join(self.temp_dir, "error")

        os.makedirs(self.inbox_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)
        os.makedirs(self.error_dir, exist_ok=True)

        # Create service instance with test directories
        self.service = Pain002IngestionService(
            inbox_dir=self.inbox_dir,
            archive_dir=self.archive_dir,
            error_dir=self.error_dir,
        )

        # Sample pain.002 XML with ACCP (Accepted) status
        self.accepted_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
    <CstmrPmtStsRpt>
        <GrpHdr>
            <MsgId>RESP-001</MsgId>
            <CreDtTm>2026-02-01T10:00:00</CreDtTm>
        </GrpHdr>
        <OrgnlGrpInfAndSts>
            <OrgnlMsgId>BATCH-ACCEPTED-001</OrgnlMsgId>
            <OrgnlMsgNmId>pain.008.001.08</OrgnlMsgNmId>
            <GrpSts>ACCP</GrpSts>
        </OrgnlGrpInfAndSts>
    </CstmrPmtStsRpt>
</Document>"""

        # Sample pain.002 XML with RJCT (Rejected) status
        self.rejected_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
    <CstmrPmtStsRpt>
        <GrpHdr>
            <MsgId>RESP-002</MsgId>
            <CreDtTm>2026-02-01T11:00:00</CreDtTm>
        </GrpHdr>
        <OrgnlGrpInfAndSts>
            <OrgnlMsgId>BATCH-REJECTED-001</OrgnlMsgId>
            <OrgnlMsgNmId>pain.008.001.08</OrgnlMsgNmId>
            <GrpSts>RJCT</GrpSts>
        </OrgnlGrpInfAndSts>
    </CstmrPmtStsRpt>
</Document>"""

        # Sample pain.002 XML with PART (Partially Accepted) status
        self.partial_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
    <CstmrPmtStsRpt>
        <GrpHdr>
            <MsgId>RESP-003</MsgId>
            <CreDtTm>2026-02-01T12:00:00</CreDtTm>
        </GrpHdr>
        <OrgnlGrpInfAndSts>
            <OrgnlMsgId>BATCH-PARTIAL-001</OrgnlMsgId>
            <OrgnlMsgNmId>pain.008.001.08</OrgnlMsgNmId>
            <GrpSts>PART</GrpSts>
        </OrgnlGrpInfAndSts>
    </CstmrPmtStsRpt>
</Document>"""

        # Invalid XML (malformed)
        self.invalid_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
    <CstmrPmtStsRpt>
        <GrpHdr>
            <!-- Missing closing tags -->
"""

        # XML without required elements
        self.missing_status_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
    <CstmrPmtStsRpt>
        <GrpHdr>
            <MsgId>RESP-004</MsgId>
        </GrpHdr>
    </CstmrPmtStsRpt>
</Document>"""

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()
        # Remove temporary directories
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    # ========== Directory Scanning Tests ==========

    def test_scan_directory_finds_pain002_files(self):
        """
        Test that scan_directory finds XML files in the inbox.

        The service should:
        - Return a list of file paths for XML files
        - Only include .xml files (case-insensitive)
        - Return absolute paths
        """
        # Create test files
        file1 = os.path.join(self.inbox_dir, "pain002_001.xml")
        file2 = os.path.join(self.inbox_dir, "pain002_002.XML")  # uppercase
        file3 = os.path.join(self.inbox_dir, "readme.txt")  # not XML

        with open(file1, "wb") as f:
            f.write(self.accepted_xml)
        with open(file2, "wb") as f:
            f.write(self.rejected_xml)
        with open(file3, "w") as f:
            f.write("Not an XML file")

        # Scan directory
        files = self.service.scan_directory(self.inbox_dir)

        # Should find exactly 2 XML files
        self.assertEqual(len(files), 2)
        self.assertIn(file1, files)
        self.assertIn(file2, files)
        self.assertNotIn(file3, files)

    def test_scan_directory_empty_returns_empty_list(self):
        """Test that scan_directory returns empty list for empty directory"""
        files = self.service.scan_directory(self.inbox_dir)
        self.assertEqual(files, [])

    def test_scan_directory_nonexistent_returns_empty_list(self):
        """Test that scan_directory handles nonexistent directory gracefully"""
        files = self.service.scan_directory("/nonexistent/path")
        self.assertEqual(files, [])

    def test_scan_directory_uses_default_inbox(self):
        """Test that scan_directory uses configured inbox when path not specified"""
        # Create file in configured inbox
        file1 = os.path.join(self.inbox_dir, "test.xml")
        with open(file1, "wb") as f:
            f.write(self.accepted_xml)

        # Scan without specifying directory
        files = self.service.scan_directory()
        self.assertEqual(len(files), 1)
        self.assertIn(file1, files)

    # ========== File Parsing Tests ==========

    def test_process_file_parses_accepted_status(self):
        """
        Test that process_file correctly extracts ACCP status.

        Should return:
        - success=True
        - data with original_message_id and group_status
        - group_status mapped to "Accepted"
        """
        file_path = os.path.join(self.inbox_dir, "accepted.xml")
        with open(file_path, "wb") as f:
            f.write(self.accepted_xml)

        result = self.service.process_file(file_path)

        self.assertTrue(result.success)
        self.assertEqual(result.data["original_message_id"], "BATCH-ACCEPTED-001")
        self.assertEqual(result.data["group_status"], "ACCP")
        self.assertEqual(result.data["batch_status"], "Acknowledged")
        self.assertEqual(result.data["bank_status"], "Accepted")

    def test_process_file_parses_rejected_status(self):
        """Test that process_file correctly extracts RJCT status"""
        file_path = os.path.join(self.inbox_dir, "rejected.xml")
        with open(file_path, "wb") as f:
            f.write(self.rejected_xml)

        result = self.service.process_file(file_path)

        self.assertTrue(result.success)
        self.assertEqual(result.data["original_message_id"], "BATCH-REJECTED-001")
        self.assertEqual(result.data["group_status"], "RJCT")
        self.assertEqual(result.data["batch_status"], "Rejected")
        self.assertEqual(result.data["bank_status"], "Rejected")

    def test_process_file_parses_partial_status(self):
        """Test that process_file correctly extracts PART status"""
        file_path = os.path.join(self.inbox_dir, "partial.xml")
        with open(file_path, "wb") as f:
            f.write(self.partial_xml)

        result = self.service.process_file(file_path)

        self.assertTrue(result.success)
        self.assertEqual(result.data["original_message_id"], "BATCH-PARTIAL-001")
        self.assertEqual(result.data["group_status"], "PART")
        self.assertEqual(result.data["batch_status"], "Acknowledged")
        self.assertEqual(result.data["bank_status"], "Partially Accepted")

    def test_process_file_handles_invalid_xml(self):
        """Test that process_file fails gracefully for malformed XML"""
        file_path = os.path.join(self.inbox_dir, "invalid.xml")
        with open(file_path, "wb") as f:
            f.write(self.invalid_xml)

        result = self.service.process_file(file_path)

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_code)

    def test_process_file_handles_missing_status(self):
        """Test that process_file fails when OrgnlGrpInfAndSts is missing"""
        file_path = os.path.join(self.inbox_dir, "missing_status.xml")
        with open(file_path, "wb") as f:
            f.write(self.missing_status_xml)

        result = self.service.process_file(file_path)

        self.assertFalse(result.success)

    def test_process_file_handles_nonexistent_file(self):
        """Test that process_file fails for nonexistent file"""
        result = self.service.process_file("/nonexistent/file.xml")

        self.assertFalse(result.success)

    # ========== Status Mapping Tests ==========

    def test_status_mapping_accp(self):
        """Test ACCP maps to Acknowledged/Accepted"""
        batch_status, bank_status = self.service._map_group_status("ACCP")
        self.assertEqual(batch_status, "Acknowledged")
        self.assertEqual(bank_status, "Accepted")

    def test_status_mapping_acsp(self):
        """Test ACSP maps to Acknowledged/Accepted"""
        batch_status, bank_status = self.service._map_group_status("ACSP")
        self.assertEqual(batch_status, "Acknowledged")
        self.assertEqual(bank_status, "Accepted")

    def test_status_mapping_actc(self):
        """Test ACTC maps to Acknowledged/Accepted"""
        batch_status, bank_status = self.service._map_group_status("ACTC")
        self.assertEqual(batch_status, "Acknowledged")
        self.assertEqual(bank_status, "Accepted")

    def test_status_mapping_part(self):
        """Test PART maps to Acknowledged/Partially Accepted"""
        batch_status, bank_status = self.service._map_group_status("PART")
        self.assertEqual(batch_status, "Acknowledged")
        self.assertEqual(bank_status, "Partially Accepted")

    def test_status_mapping_rjct(self):
        """Test RJCT maps to Rejected/Rejected"""
        batch_status, bank_status = self.service._map_group_status("RJCT")
        self.assertEqual(batch_status, "Rejected")
        self.assertEqual(bank_status, "Rejected")

    def test_status_mapping_unknown(self):
        """Test unknown status returns None/None"""
        batch_status, bank_status = self.service._map_group_status("UNKNOWN")
        self.assertIsNone(batch_status)
        self.assertIsNone(bank_status)

    # ========== Batch Log Update Tests ==========

    def _create_test_batch_and_log(self, file_name: str):
        """
        Helper to create test Direct Debit Batch and SEPA Batch Upload Log.

        Uses frappe.db.sql for direct insertion to bypass validation.
        """
        # Create batch directly in database to bypass validation.
        # Direct Debit Batch has no batch_name/collection_date columns; the real
        # fields are batch_description / batch_date (plus required batch_type).
        batch_name = frappe.generate_hash(length=10)
        frappe.db.sql(
            """
            INSERT INTO `tabDirect Debit Batch`
            (name, batch_description, batch_date, batch_type, status, docstatus,
             creation, modified, owner, modified_by)
            VALUES (%s, %s, %s, %s, %s, 0, NOW(), NOW(), 'Administrator', 'Administrator')
        """,
            (batch_name, f"Test Batch {batch_name}", frappe.utils.today(), "RCUR", "Generated"),
        )

        # update_batch_status() looks up the log by file_name. The helper commits
        # its rows and does not clean them up, so a fixed file_name accumulates
        # across runs and the service would lock/update a STALE prior row instead
        # of the one created here. Delete any pre-existing rows with this
        # file_name first so exactly one matches.
        frappe.db.delete("SEPA Batch Upload Log", {"file_name": file_name})

        log_name = frappe.generate_hash(length=10)
        frappe.db.sql(
            """
            INSERT INTO `tabSEPA Batch Upload Log`
            (name, batch_name, batch_status, file_name, upload_time, uploaded_by, creation, modified, owner, modified_by)
            VALUES (%s, %s, %s, %s, NOW(), %s, NOW(), NOW(), 'Administrator', 'Administrator')
        """,
            (log_name, batch_name, "Uploaded", file_name, "Administrator"),
        )

        frappe.db.commit()
        return batch_name, log_name

    def test_update_batch_status_updates_log(self):
        """
        Test that update_batch_status updates SEPA Batch Upload Log.

        Should:
        - Find the log entry by original_message_id matching file_name
        - Update batch_status, bank_status, bank_acknowledgement_time
        - Return success with the updated log name
        """
        # Create test data
        batch_name, log_name = self._create_test_batch_and_log("BATCH-ACCEPTED-001")

        # Update with parsed data
        data = {
            "original_message_id": "BATCH-ACCEPTED-001",
            "group_status": "ACCP",
            "batch_status": "Acknowledged",
            "bank_status": "Accepted",
            "file_path": "/test/path.xml",
        }

        result = self.service.update_batch_status(data)

        self.assertTrue(result.success, f"Update failed: {result.error_message}")

        # Verify the log was updated
        log_entry = frappe.get_doc("SEPA Batch Upload Log", log_name)
        self.assertEqual(log_entry.batch_status, "Acknowledged")
        self.assertEqual(log_entry.bank_status, "Accepted")
        self.assertIsNotNone(log_entry.bank_acknowledgement_time)

    def test_update_batch_status_no_matching_log(self):
        """Test that update_batch_status handles missing log entry"""
        data = {
            "original_message_id": "NONEXISTENT-BATCH",
            "group_status": "ACCP",
            "batch_status": "Acknowledged",
            "bank_status": "Accepted",
            "file_path": "/test/path.xml",
        }

        result = self.service.update_batch_status(data)

        # Should fail because no matching log exists
        self.assertFalse(result.success)
        self.assertIn("not found", result.error_message.lower())

    # ========== Archive Tests ==========

    def test_processed_file_moved_to_archive(self):
        """
        Test that processed files are moved to archive directory.

        After successful processing:
        - File should no longer exist in inbox
        - File should exist in archive with timestamp prefix
        """
        # Create test file
        file_name = "pain002_test.xml"
        file_path = os.path.join(self.inbox_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(self.accepted_xml)

        # Create matching batch log for update to succeed
        self._create_test_batch_and_log("BATCH-ACCEPTED-001")

        # Process and archive
        result = self.service.process_and_archive(file_path)

        self.assertTrue(result.success, f"Process failed: {result.error_message}")

        # File should be gone from inbox
        self.assertFalse(os.path.exists(file_path))

        # File should be in archive
        archived_files = os.listdir(self.archive_dir)
        self.assertEqual(len(archived_files), 1)
        self.assertIn(file_name, archived_files[0])  # Original name in archived name

    def test_failed_file_moved_to_error_directory(self):
        """
        Test that files that fail processing are moved to error directory.

        After failed processing:
        - File should no longer exist in inbox
        - File should exist in error directory
        """
        # Create invalid test file
        file_name = "invalid_pain002.xml"
        file_path = os.path.join(self.inbox_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(self.invalid_xml)

        # Process (should fail)
        result = self.service.process_and_archive(file_path)

        # Processing should fail
        self.assertFalse(result.success)

        # File should be gone from inbox
        self.assertFalse(os.path.exists(file_path))

        # File should be in error directory
        error_files = os.listdir(self.error_dir)
        self.assertEqual(len(error_files), 1)
        self.assertIn(file_name, error_files[0])

    # ========== Full Ingestion Job Tests ==========

    def test_run_ingestion_job_processes_all_files(self):
        """
        Test that run_ingestion_job processes all files in inbox.

        Should:
        - Find all XML files
        - Process each one
        - Archive successful ones
        - Move failed ones to error
        - Return summary
        """
        # Create test files
        file1 = os.path.join(self.inbox_dir, "accepted.xml")
        file2 = os.path.join(self.inbox_dir, "invalid.xml")

        with open(file1, "wb") as f:
            f.write(self.accepted_xml)
        with open(file2, "wb") as f:
            f.write(self.invalid_xml)

        # Create matching batch log for accepted file
        self._create_test_batch_and_log("BATCH-ACCEPTED-001")

        # Run ingestion job
        summary = self.service.run_ingestion_job()

        # Check summary
        self.assertEqual(summary["total_files"], 2)
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["failed"], 1)

        # Inbox should be empty
        inbox_files = os.listdir(self.inbox_dir)
        self.assertEqual(len(inbox_files), 0)

        # Archive should have 1 file
        archived_files = os.listdir(self.archive_dir)
        self.assertEqual(len(archived_files), 1)

        # Error should have 1 file
        error_files = os.listdir(self.error_dir)
        self.assertEqual(len(error_files), 1)

    def test_run_ingestion_job_empty_inbox(self):
        """Test that run_ingestion_job handles empty inbox gracefully"""
        summary = self.service.run_ingestion_job()

        self.assertEqual(summary["total_files"], 0)
        self.assertEqual(summary["processed"], 0)
        self.assertEqual(summary["failed"], 0)


class TestPain002IngestionServiceFactory(FrappeTestCase):
    """Test the factory function for Pain002IngestionService"""

    def test_get_pain002_ingestion_service_returns_instance(self):
        """Test that factory function returns Pain002IngestionService instance"""
        service = get_pain002_ingestion_service()
        self.assertIsInstance(service, Pain002IngestionService)

    def test_get_pain002_ingestion_service_uses_site_config(self):
        """Test that factory uses site config for directories if available"""
        service = get_pain002_ingestion_service()
        # Service should be created with some directories configured
        self.assertIsNotNone(service.inbox_dir)
        self.assertIsNotNone(service.archive_dir)
        self.assertIsNotNone(service.error_dir)
