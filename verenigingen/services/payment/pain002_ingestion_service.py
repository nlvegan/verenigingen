"""
Automated pain.002 (Bank Status Report) ingestion service.

Scans a configured directory for pain.002 XML files, parses them,
updates batch status in SEPA Batch Upload Log, and archives processed files.

Configuration (site_config.json):
    sepa_pain002_inbox: Path to scan for incoming files (default: /var/sepa/inbox)
    sepa_pain002_archive: Path to move processed files (default: /var/sepa/archive)
    sepa_pain002_error: Path for files that failed processing (default: /var/sepa/error)

Architecture:
    - Uses defusedxml for secure XML parsing (XXE protection)
    - Extends StatelessService for metrics and logging
    - Returns OperationResult for consistent error handling
    - Archives processed files with timestamps for audit trail

Usage:
    from verenigingen.services.payment.pain002_ingestion_service import (
        get_pain002_ingestion_service,
    )

    # Manual invocation
    service = get_pain002_ingestion_service()
    result = service.run_ingestion_job()
    print(f"Processed {result['processed']} files")

    # Scheduled via hooks (hourly)
    # Configured in verenigingen/hooks/lifecycle.py

Author: Verenigingen Development Team
"""

import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_xml import XMLSecurityError, parse_xml_safely

# Default directory paths
DEFAULT_INBOX_DIR = "/var/sepa/inbox"
DEFAULT_ARCHIVE_DIR = "/var/sepa/archive"
DEFAULT_ERROR_DIR = "/var/sepa/error"

# pain.002 XML namespace
PAIN002_NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.03"

# Group status to batch/bank status mapping
# Bank Status (GrpSts) -> (SEPA Batch Upload Log Status, bank_status field)
STATUS_MAPPING = {
    "ACCP": ("Acknowledged", "Accepted"),  # Accepted Customer Profile
    "ACSP": ("Acknowledged", "Accepted"),  # Accepted Settlement in Process
    "ACTC": ("Acknowledged", "Accepted"),  # Accepted Technical Validation
    "PART": ("Acknowledged", "Partially Accepted"),  # Partially Accepted
    "RJCT": ("Rejected", "Rejected"),  # Rejected
}


class Pain002IngestionService(StatelessService):
    """
    Service for automated pain.002 file ingestion.

    This service scans a configured inbox directory for pain.002 XML files
    (bank status reports), parses them to extract batch status, updates
    the corresponding SEPA Batch Upload Log entries, and archives processed files.

    Thread Safety:
        Each file is processed independently. Database updates use explicit
        transactions for atomicity.

    Error Handling:
        - Invalid XML files are moved to error directory
        - Missing batch logs are logged but don't stop processing
        - All errors are logged for monitoring
    """

    def __init__(
        self,
        inbox_dir: Optional[str] = None,
        archive_dir: Optional[str] = None,
        error_dir: Optional[str] = None,
    ):
        """
        Initialize the Pain002IngestionService.

        Args:
            inbox_dir: Directory to scan for incoming pain.002 files.
                      Defaults to site config or /var/sepa/inbox.
            archive_dir: Directory to move processed files.
                        Defaults to site config or /var/sepa/archive.
            error_dir: Directory for files that failed processing.
                      Defaults to site config or /var/sepa/error.
        """
        super().__init__(service_name="Pain002IngestionService")

        # Load from site config or use provided/default values
        self.inbox_dir = inbox_dir or self._get_config_value("sepa_pain002_inbox", DEFAULT_INBOX_DIR)
        self.archive_dir = archive_dir or self._get_config_value("sepa_pain002_archive", DEFAULT_ARCHIVE_DIR)
        self.error_dir = error_dir or self._get_config_value("sepa_pain002_error", DEFAULT_ERROR_DIR)

    def _get_config_value(self, key: str, default: str) -> str:
        """Get configuration value from site config with fallback to default."""
        try:
            return frappe.conf.get(key, default)
        except Exception:
            return default

    def scan_directory(self, directory: Optional[str] = None) -> List[str]:
        """
        Find XML files in the specified directory.

        Scans the directory for files with .xml extension (case-insensitive).
        Returns absolute paths to allow safe file operations.

        Args:
            directory: Directory to scan. Defaults to configured inbox_dir.

        Returns:
            List of absolute file paths for XML files found.
            Empty list if directory doesn't exist or contains no XML files.
        """
        scan_dir = directory or self.inbox_dir

        if not os.path.exists(scan_dir):
            self.logger.warning(f"Inbox directory does not exist: {scan_dir}")
            return []

        if not os.path.isdir(scan_dir):
            self.logger.warning(f"Inbox path is not a directory: {scan_dir}")
            return []

        xml_files = []
        try:
            for filename in os.listdir(scan_dir):
                if filename.lower().endswith(".xml"):
                    xml_files.append(os.path.join(scan_dir, filename))
        except PermissionError as e:
            self.logger.error(f"Permission denied scanning directory {scan_dir}: {e}")

        self.logger.info(f"Found {len(xml_files)} XML files in {scan_dir}")
        return xml_files

    def process_file(self, file_path: str) -> OperationResult[dict]:
        """
        Parse a pain.002 file and extract batch status information.

        Securely parses the XML file using defusedxml, extracts the
        OrgnlGrpInfAndSts element, and maps the group status to
        SEPA Batch Upload Log status values.

        Args:
            file_path: Absolute path to the pain.002 XML file.

        Returns:
            OperationResult with parsed data on success:
            - original_message_id: OrgnlMsgId from the file
            - group_status: Raw GrpSts value (ACCP, RJCT, etc.)
            - batch_status: Mapped status for SEPA Batch Upload Log
            - bank_status: Mapped bank_status field value
            - file_path: Original file path for reference

            OperationResult with error on failure.
        """
        if not os.path.exists(file_path):
            return OperationResult.fail(
                message=_("File not found: {0}").format(file_path),
                error_code="PAIN002_FILE_NOT_FOUND",
            )

        try:
            # Read file content
            with open(file_path, "rb") as f:
                xml_content = f.read()

            # Parse XML securely
            root = parse_xml_safely(
                xml_content,
                max_size=10 * 1024 * 1024,  # 10MB max
                source_description="pain.002 status report",
            )

            # Extract status information
            extraction_result = self._extract_group_status(root)
            if not extraction_result.success:
                return extraction_result

            data = extraction_result.data
            data["file_path"] = file_path

            self.logger.info(
                f"Parsed pain.002 file: {file_path}, "
                f"OrgnlMsgId={data['original_message_id']}, "
                f"GrpSts={data['group_status']}"
            )

            return OperationResult.ok(data)

        except XMLSecurityError as e:
            self.logger.error(f"XML security violation in {file_path}: {e}")
            return OperationResult.fail(
                message=_("XML security violation: {0}").format(str(e)),
                error_code="PAIN002_XML_SECURITY_ERROR",
            )
        except ValueError as e:
            self.logger.error(f"Invalid XML in {file_path}: {e}")
            return OperationResult.fail(
                message=_("Invalid XML: {0}").format(str(e)),
                error_code="PAIN002_INVALID_XML",
            )
        except Exception as e:
            self.logger.error(f"Failed to process pain.002 file {file_path}: {e}")
            return OperationResult.from_exception(
                e,
                message=_("Failed to process pain.002 file: {0}").format(str(e)),
                error_code="PAIN002_PROCESS_ERROR",
            )

    def _extract_group_status(self, root) -> OperationResult[dict]:
        """
        Extract OrgnlMsgId and GrpSts from parsed XML.

        Navigates the pain.002 structure:
        Document > CstmrPmtStsRpt > OrgnlGrpInfAndSts > {OrgnlMsgId, GrpSts}

        Args:
            root: Parsed XML root element.

        Returns:
            OperationResult with extracted data or error.
        """
        # Detect namespace from root element
        namespace = self._detect_namespace(root)
        ns = {"ns": namespace} if namespace else {}
        ns_prefix = "ns:" if namespace else ""

        # Find OrgnlGrpInfAndSts element
        # Try with namespace first, then without
        grp_inf_elem = root.find(f".//{ns_prefix}OrgnlGrpInfAndSts", ns)

        if grp_inf_elem is None and namespace:
            # Try without namespace prefix
            grp_inf_elem = root.find(".//OrgnlGrpInfAndSts")

        if grp_inf_elem is None:
            return OperationResult.fail(
                message=_("OrgnlGrpInfAndSts element not found in pain.002 file"),
                error_code="PAIN002_MISSING_GROUP_STATUS",
            )

        # Extract OrgnlMsgId
        orgnl_msg_id_elem = grp_inf_elem.find(f"{ns_prefix}OrgnlMsgId", ns)
        if orgnl_msg_id_elem is None and namespace:
            orgnl_msg_id_elem = grp_inf_elem.find("OrgnlMsgId")

        if orgnl_msg_id_elem is None or not orgnl_msg_id_elem.text:
            return OperationResult.fail(
                message=_("OrgnlMsgId not found in pain.002 file"),
                error_code="PAIN002_MISSING_MESSAGE_ID",
            )

        original_message_id = orgnl_msg_id_elem.text.strip()

        # Extract GrpSts
        grp_sts_elem = grp_inf_elem.find(f"{ns_prefix}GrpSts", ns)
        if grp_sts_elem is None and namespace:
            grp_sts_elem = grp_inf_elem.find("GrpSts")

        if grp_sts_elem is None or not grp_sts_elem.text:
            return OperationResult.fail(
                message=_("GrpSts not found in pain.002 file"),
                error_code="PAIN002_MISSING_GROUP_STATUS_CODE",
            )

        group_status = grp_sts_elem.text.strip()

        # Map to batch/bank status
        batch_status, bank_status = self._map_group_status(group_status)

        if batch_status is None:
            self.logger.warning(f"Unknown group status: {group_status}")
            batch_status = "Uploaded"  # Keep as uploaded if status unknown
            bank_status = group_status  # Store raw value

        return OperationResult.ok(
            {
                "original_message_id": original_message_id,
                "group_status": group_status,
                "batch_status": batch_status,
                "bank_status": bank_status,
            }
        )

    def _detect_namespace(self, root) -> Optional[str]:
        """Detect the pain.002 namespace from root element."""
        tag = root.tag

        # Tag format: {namespace}localname
        if tag.startswith("{"):
            ns_end = tag.find("}")
            if ns_end > 0:
                return tag[1:ns_end]

        return None

    def _map_group_status(self, group_status: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Map pain.002 group status to SEPA Batch Upload Log status values.

        Args:
            group_status: Raw GrpSts value from pain.002 (ACCP, RJCT, etc.)

        Returns:
            Tuple of (batch_status, bank_status) or (None, None) if unknown.
        """
        return STATUS_MAPPING.get(group_status, (None, None))

    def update_batch_status(self, data: dict) -> OperationResult[str]:
        """
        Update SEPA Batch Upload Log with parsed status information.

        Finds the log entry where file_name matches the original_message_id
        from the pain.002 file, then updates the batch_status, bank_status,
        and bank_acknowledgement_time fields.

        Args:
            data: Parsed data from process_file containing:
                - original_message_id: Matches file_name in log
                - batch_status: New batch status value
                - bank_status: New bank status value

        Returns:
            OperationResult with log entry name on success, error on failure.
        """
        original_message_id = data.get("original_message_id")
        batch_status = data.get("batch_status")
        bank_status = data.get("bank_status")

        if not original_message_id:
            return OperationResult.fail(
                message=_("Missing original_message_id in data"),
                error_code="PAIN002_MISSING_MESSAGE_ID",
            )

        try:
            # Find log entry by file_name matching original_message_id
            log_name = frappe.db.get_value(
                "SEPA Batch Upload Log",
                filters={"file_name": original_message_id},
                fieldname="name",
            )

            if not log_name:
                return OperationResult.fail(
                    message=_("SEPA Batch Upload Log not found for message ID: {0}").format(
                        original_message_id
                    ),
                    error_code="PAIN002_LOG_NOT_FOUND",
                )

            # Update the log entry
            frappe.db.begin()
            try:
                frappe.db.set_value(
                    "SEPA Batch Upload Log",
                    log_name,
                    {
                        "batch_status": batch_status,
                        "bank_status": bank_status,
                        "bank_acknowledgement_time": frappe.utils.now_datetime(),
                    },
                    update_modified=True,
                )
                frappe.db.commit()

                self.logger.info(
                    f"Updated SEPA Batch Upload Log {log_name}: "
                    f"batch_status={batch_status}, bank_status={bank_status}"
                )

                return OperationResult.ok(log_name)

            except Exception as e:
                frappe.db.rollback()
                raise

        except Exception as e:
            self.logger.error(f"Failed to update batch status: {e}")
            return OperationResult.from_exception(
                e,
                message=_("Failed to update batch status: {0}").format(str(e)),
                error_code="PAIN002_UPDATE_ERROR",
            )

    def process_and_archive(
        self,
        file_path: str,
        archive_dir: Optional[str] = None,
    ) -> OperationResult[dict]:
        """
        Process a pain.002 file and archive it after processing.

        This is the main entry point for processing a single file:
        1. Parse the file to extract status
        2. Update the SEPA Batch Upload Log
        3. Move file to archive (success) or error (failure) directory

        Args:
            file_path: Absolute path to the pain.002 XML file.
            archive_dir: Override archive directory (for testing).

        Returns:
            OperationResult with processing summary on success:
            - file_path: Original file path
            - archived_path: Where the file was moved
            - original_message_id: Extracted message ID
            - status: Applied status

            OperationResult with error on failure (file moved to error dir).
        """
        archive_to = archive_dir or self.archive_dir
        file_name = os.path.basename(file_path)

        # Step 1: Parse the file
        parse_result = self.process_file(file_path)

        if not parse_result.success:
            # Move to error directory
            error_path = self._move_to_directory(file_path, self.error_dir)
            self.logger.error(f"Failed to parse {file_path}, moved to {error_path}")
            return OperationResult.fail(
                message=parse_result.error_message,
                error_code=parse_result.error_code,
                errors=parse_result.errors,
                file_path=file_path,
                error_path=error_path,
            )

        # Step 2: Update batch status
        update_result = self.update_batch_status(parse_result.data)

        if not update_result.success:
            # Move to error directory - batch log not found or update failed
            error_path = self._move_to_directory(file_path, self.error_dir)
            self.logger.error(f"Failed to update batch status for {file_path}, moved to {error_path}")
            return OperationResult.fail(
                message=update_result.error_message,
                error_code=update_result.error_code,
                errors=update_result.errors,
                file_path=file_path,
                error_path=error_path,
            )

        # Step 3: Archive the file
        archived_path = self._move_to_directory(file_path, archive_to)

        self.logger.info(f"Successfully processed {file_path}, archived to {archived_path}")

        return OperationResult.ok(
            {
                "file_path": file_path,
                "archived_path": archived_path,
                "original_message_id": parse_result.data["original_message_id"],
                "status": parse_result.data["batch_status"],
            }
        )

    def _move_to_directory(self, file_path: str, target_dir: str) -> str:
        """
        Move a file to target directory with timestamp prefix.

        Args:
            file_path: Source file path.
            target_dir: Destination directory.

        Returns:
            New file path in target directory.
        """
        # Ensure target directory exists
        os.makedirs(target_dir, exist_ok=True)

        file_name = os.path.basename(file_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{timestamp}_{file_name}"
        new_path = os.path.join(target_dir, new_name)

        shutil.move(file_path, new_path)
        return new_path

    def run_ingestion_job(self) -> dict:
        """
        Run the full ingestion job.

        This is the main entry point for scheduled execution:
        1. Scan inbox for XML files
        2. Process each file
        3. Archive or move to error based on result
        4. Return summary

        Returns:
            Dictionary with ingestion summary:
            - total_files: Number of files found
            - processed: Number successfully processed
            - failed: Number that failed
            - errors: List of error messages for failed files
        """
        self.logger.info("Starting pain.002 ingestion job")

        # Ensure directories exist
        for dir_path in [self.inbox_dir, self.archive_dir, self.error_dir]:
            os.makedirs(dir_path, exist_ok=True)

        # Scan for files
        xml_files = self.scan_directory()

        summary = {
            "total_files": len(xml_files),
            "processed": 0,
            "failed": 0,
            "errors": [],
        }

        # Process each file
        for file_path in xml_files:
            result = self.process_and_archive(file_path)

            if result.success:
                summary["processed"] += 1
            else:
                summary["failed"] += 1
                summary["errors"].append(
                    {
                        "file": file_path,
                        "error": result.error_message,
                    }
                )

        self.logger.info(
            f"Pain.002 ingestion complete: "
            f"{summary['processed']}/{summary['total_files']} processed, "
            f"{summary['failed']} failed"
        )

        return summary


# Module-level singleton instance
_pain002_ingestion_service_instance: Optional[Pain002IngestionService] = None


def get_pain002_ingestion_service() -> Pain002IngestionService:
    """
    Get the Pain002IngestionService instance.

    Returns a singleton instance of the service for efficiency.

    Returns:
        Pain002IngestionService instance configured from site config.
    """
    global _pain002_ingestion_service_instance
    if _pain002_ingestion_service_instance is None:
        _pain002_ingestion_service_instance = Pain002IngestionService()
    return _pain002_ingestion_service_instance


def run_pain002_ingestion() -> dict:
    """
    Entry point for scheduled task.

    This function is called by the scheduler (hourly) to run the
    pain.002 ingestion job.

    Returns:
        Ingestion summary dictionary.
    """
    service = get_pain002_ingestion_service()
    return service.run_ingestion_job()


__all__ = [
    "Pain002IngestionService",
    "get_pain002_ingestion_service",
    "run_pain002_ingestion",
]
