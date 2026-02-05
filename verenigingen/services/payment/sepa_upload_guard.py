"""
SEPA Upload Guard Service

Prevents duplicate SEPA batch uploads by tracking file hashes. When an operator
uploads a pain.008 XML file to the bank portal, this service detects if the same
file was already uploaded to prevent duplicate debits.

Architecture:
    - Uses SHA256 hash of file content for duplicate detection
    - Stores upload records in "SEPA Batch Upload Log" DocType
    - Provides atomic check-and-register operation to prevent race conditions

Usage:
    from verenigingen.services.payment.sepa_upload_guard import (
        get_sepa_upload_guard,
        UploadCheckResult,
    )

    guard = get_sepa_upload_guard()

    # Check if upload is allowed before processing
    result = guard.check_upload_allowed(file_content, batch_name)
    if not result.success:
        print(f"Duplicate detected: already uploaded as {result.duplicate_batch}")

    # Or use atomic check-and-register
    result = guard.check_and_register(file_content, batch_name, uploaded_by)
    if result.success:
        # Proceed with bank upload
        pass

Author: Verenigingen Development Team
"""

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.sepa_sandbox import get_sandbox


class UploadBlockReason(str, Enum):
    """Machine-readable reason codes for upload blocking."""

    NONE = "NONE"  # Upload allowed
    SANDBOX_MODE = "SANDBOX_MODE"  # Blocked by sandbox mode
    DUPLICATE_HASH = "DUPLICATE_HASH"  # Same file already uploaded
    REGISTRATION_FAILED = "REGISTRATION_FAILED"  # Failed to register upload
    INTEGRITY_ERROR = "INTEGRITY_ERROR"  # DB constraint violation (race condition)


@dataclass
class UploadCheckResult:
    """
    Result of checking whether a SEPA batch upload is allowed.

    Attributes:
        success: True if upload is allowed (no duplicate found)
        file_hash: SHA256 hash of the file content
        reason_code: Machine-readable reason for blocking (for automation)
        duplicate_batch: Name of the batch that was already uploaded (if duplicate)
        duplicate_upload_time: When the duplicate was uploaded (if duplicate)
        message: Human-readable message explaining the result
    """

    success: bool
    file_hash: str
    reason_code: UploadBlockReason = UploadBlockReason.NONE
    duplicate_batch: Optional[str] = None
    duplicate_upload_time: Optional[str] = None
    message: str = ""


class SEPAUploadGuard(StatelessService):
    """
    Service to prevent duplicate SEPA batch uploads.

    This service protects against accidental double-debiting of member bank
    accounts by tracking file hashes of uploaded SEPA pain.008 XML files.

    The service maintains a log of all uploaded files and their hashes. Before
    an operator uploads a file to the bank portal, this service can check if
    the same file was already uploaded.

    Thread Safety:
        The check_and_register method uses database transactions to ensure
        atomic check-and-insert operations, preventing race conditions.
    """

    # DocType name for upload log entries
    UPLOAD_LOG_DOCTYPE = "SEPA Batch Upload Log"

    def __init__(self):
        """Initialize the SEPAUploadGuard service."""
        super().__init__(service_name="SEPAUploadGuard")

    def _compute_file_hash(self, content: bytes) -> str:
        """
        Compute SHA256 hash of canonicalized XML content.

        Uses C14N (Canonical XML) to ensure semantically identical XML
        always produces the same hash, regardless of whitespace or
        attribute ordering differences.

        Production Behavior:
            In production (developer_mode=False), canonicalization failures
            raise an exception to ensure consistent hashing. Inconsistent
            hashes could allow duplicate uploads.

        Development Behavior:
            In developer_mode, falls back to raw hash with a warning to
            allow testing with malformed XML.

        Args:
            content: XML file content as bytes

        Returns:
            Hexadecimal string of SHA256 hash (64 characters)

        Raises:
            frappe.ValidationError: In production, if canonicalization fails
        """
        try:
            # Use C14N canonicalization for consistent hashing
            from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAXMLCanonicalizer

            return SEPAXMLCanonicalizer.compute_canonical_hash(content)
        except (ImportError, ValueError) as e:
            # In production, fail fast - inconsistent hashing is dangerous
            if not frappe.conf.get("developer_mode"):
                self.logger.error(f"XML canonicalization failed in production: {e}")
                frappe.throw(
                    _(
                        "SEPA XML canonicalization failed. This is required for consistent "
                        "duplicate detection. Please check the XML format. Error: {0}"
                    ).format(str(e)),
                    title=_("XML Processing Error"),
                )

            # In developer_mode only, allow fallback to raw hash for testing
            self.logger.warning(f"XML canonicalization failed (dev mode fallback to raw hash): {e}")
            return hashlib.sha256(content).hexdigest()

    def _find_existing_upload(self, file_hash: str) -> Optional[dict]:
        """
        Find an existing upload log entry by file hash.

        Excludes entries where hash_freed=1 (abandoned phantom entries),
        allowing the same content to be re-uploaded after manual investigation.

        Args:
            file_hash: SHA256 hash to search for

        Returns:
            Dict with batch_name and upload_time if found, None otherwise
        """
        existing = frappe.db.get_value(
            self.UPLOAD_LOG_DOCTYPE,
            filters={
                "file_hash": file_hash,
                "hash_freed": 0,  # Ignore freed hashes (abandoned phantom entries)
            },
            fieldname=["batch_name", "upload_time"],
            as_dict=True,
        )
        return existing

    def check_upload_allowed(
        self,
        file_content: bytes,
        batch_name: str,
    ) -> UploadCheckResult:
        """
        Check if uploading a file is allowed (no duplicate exists).

        This method only checks for duplicates; it does not register the upload.
        Use register_upload() to record the upload after successful bank submission.

        WARNING - Race Condition Risk:
            This method is NOT atomic. When used separately from register_upload(),
            a race condition exists where two concurrent requests might both pass
            the check and then both register, defeating duplicate detection.

            For production use, ALWAYS use check_and_register() instead of calling
            this method followed by register_upload(). Only use this method if you:
            - Are in a single-threaded context
            - Will not call register_upload() based on the result
            - Are displaying information to a user in a non-critical context

        Args:
            file_content: The pain.008 XML file content as bytes
            batch_name: Name/identifier of the SEPA batch (for logging)

        Returns:
            UploadCheckResult with success=True if upload allowed,
            or success=False with duplicate information if blocked
        """
        # Check sandbox mode first - block uploads in sandbox mode
        sandbox = get_sandbox()
        sandbox_result = sandbox.check_upload_allowed()
        if not sandbox_result.allowed:
            return UploadCheckResult(
                success=False,
                file_hash=self._compute_file_hash(file_content),
                reason_code=UploadBlockReason.SANDBOX_MODE,
                message=sandbox_result.message,
            )

        file_hash = self._compute_file_hash(file_content)

        existing = self._find_existing_upload(file_hash)

        if existing:
            return UploadCheckResult(
                success=False,
                file_hash=file_hash,
                reason_code=UploadBlockReason.DUPLICATE_HASH,
                duplicate_batch=existing.get("batch_name"),
                duplicate_upload_time=str(existing.get("upload_time"))
                if existing.get("upload_time")
                else None,
                message=_(
                    "Duplicate file detected. This file was already uploaded as batch '{0}' on {1}."
                ).format(existing.get("batch_name"), existing.get("upload_time")),
            )

        return UploadCheckResult(
            success=True,
            file_hash=file_hash,
            reason_code=UploadBlockReason.NONE,
            message=_("File has not been uploaded before. Upload is allowed."),
        )

    def register_upload(
        self,
        file_content: bytes,
        batch_name: str,
        uploaded_by: Optional[str] = None,
    ) -> OperationResult[str]:
        """
        Register a SEPA batch upload in the log.

        This creates a record of the upload to prevent future duplicates.
        Call this after successfully uploading the file to the bank portal.

        WARNING - Document Hook Unsafe:
            This method calls frappe.db.commit() directly, which breaks transaction
            semantics if called from document hooks (validate, before_save, etc.).
            During document hooks, Frappe manages a single implicit transaction that
            commits at request end. Calling commit() here would:
            - Commit data prematurely
            - Prevent proper rollback if validation fails later
            - Break hook chain ordering

            Do NOT call this from document hooks. Call it from:
            - Whitelisted API methods (transaction committed at request end)
            - Background jobs (independent transactions)
            - check_and_register() (which manages its own transaction)

        WARNING - Race Condition Risk:
            When used separately from check_upload_allowed(), this method is NOT
            protected against concurrent duplicate uploads. Always validate with
            check_upload_allowed() BEFORE calling this, and in production use
            check_and_register() instead for atomic check-and-register.

        Args:
            file_content: The pain.008 XML file content as bytes
            batch_name: Name/identifier of the SEPA batch
            uploaded_by: User who performed the upload (defaults to current user)

        Returns:
            OperationResult with the log entry name on success,
            or error information on failure
        """
        file_hash = self._compute_file_hash(file_content)

        if uploaded_by is None:
            uploaded_by = frappe.session.user

        try:
            log_entry = frappe.get_doc(
                {
                    "doctype": self.UPLOAD_LOG_DOCTYPE,
                    "batch_name": batch_name,
                    "file_hash": file_hash,
                    "upload_time": frappe.utils.now_datetime(),
                    "uploaded_by": uploaded_by,
                    "file_size": len(file_content),
                }
            )
            # Security: Audit log entry for SEPA upload - system tracks all uploads with user context
            log_entry.insert(ignore_permissions=True)
            frappe.db.commit()

            self.logger.info(f"Registered SEPA batch upload: batch={batch_name}, hash={file_hash[:16]}...")

            return OperationResult.ok(log_entry.name)

        except Exception as e:
            self.logger.error(f"Failed to register SEPA upload: {e}")
            return OperationResult.from_exception(
                e,
                message=_("Failed to register upload: {0}").format(str(e)),
                error_code="SEPA_UPLOAD_REGISTER_FAILED",
            )

    def check_and_register(
        self,
        file_content: bytes,
        batch_name: str,
        uploaded_by: Optional[str] = None,
    ) -> UploadCheckResult:
        """
        Atomically check for duplicates and register the upload.

        This combines check_upload_allowed and register_upload into a single
        atomic operation. Use this to prevent race conditions when multiple
        operators might upload the same file simultaneously.

        This is the RECOMMENDED method for all production use cases. It:
        - Acquires a transaction lock
        - Checks for duplicates
        - Registers the upload
        - Commits atomically
        - All within a single database transaction

        Return Type Note:
            This method returns UploadCheckResult (not OperationResult) because:
            - It's the user-facing API method with rich result information
            - Callers need detailed duplicate info (batch name, upload time)
            - register_upload() returns OperationResult for internal orchestration
            This distinction is intentional and serves different use cases.

        Args:
            file_content: The pain.008 XML file content as bytes
            batch_name: Name/identifier of the SEPA batch
            uploaded_by: User who performed the upload (defaults to current user)

        Returns:
            UploadCheckResult with success=True if registered successfully,
            or success=False if duplicate detected (with detailed duplicate info)
        """
        # Check sandbox mode first - block uploads in sandbox mode
        sandbox = get_sandbox()
        sandbox_result = sandbox.check_upload_allowed()
        if not sandbox_result.allowed:
            return UploadCheckResult(
                success=False,
                file_hash=self._compute_file_hash(file_content),
                reason_code=UploadBlockReason.SANDBOX_MODE,
                message=sandbox_result.message,
            )

        file_hash = self._compute_file_hash(file_content)

        if uploaded_by is None:
            uploaded_by = frappe.session.user

        # Use transaction to ensure atomicity
        frappe.db.begin()
        try:
            # Check for existing upload within transaction
            existing = self._find_existing_upload(file_hash)

            if existing:
                frappe.db.rollback()
                return UploadCheckResult(
                    success=False,
                    file_hash=file_hash,
                    reason_code=UploadBlockReason.DUPLICATE_HASH,
                    duplicate_batch=existing.get("batch_name"),
                    duplicate_upload_time=str(existing.get("upload_time"))
                    if existing.get("upload_time")
                    else None,
                    message=_(
                        "Duplicate file detected. This file was already uploaded as batch '{0}' on {1}."
                    ).format(existing.get("batch_name"), existing.get("upload_time")),
                )

            # No duplicate found, register the upload
            log_entry = frappe.get_doc(
                {
                    "doctype": self.UPLOAD_LOG_DOCTYPE,
                    "batch_name": batch_name,
                    "file_hash": file_hash,
                    "upload_time": frappe.utils.now_datetime(),
                    "uploaded_by": uploaded_by,
                    "file_size": len(file_content),
                }
            )
            # Security: Audit log entry for SEPA upload - atomic operation with transaction isolation
            log_entry.insert(ignore_permissions=True)
            frappe.db.commit()

            self.logger.info(
                f"Atomically registered SEPA batch upload: batch={batch_name}, hash={file_hash[:16]}..."
            )

            return UploadCheckResult(
                success=True,
                file_hash=file_hash,
                reason_code=UploadBlockReason.NONE,
                message=_("Upload registered successfully."),
            )

        except frappe.DuplicateEntryError:
            # DB unique constraint caught the race condition - another worker won
            frappe.db.rollback()
            self.logger.warning(
                f"DuplicateEntryError in check_and_register (race condition caught by DB): hash={file_hash[:16]}..."
            )

            # Look up the winning entry to provide duplicate info
            existing = self._find_existing_upload(file_hash)
            if existing:
                return UploadCheckResult(
                    success=False,
                    file_hash=file_hash,
                    reason_code=UploadBlockReason.INTEGRITY_ERROR,
                    duplicate_batch=existing.get("batch_name"),
                    duplicate_upload_time=str(existing.get("upload_time"))
                    if existing.get("upload_time")
                    else None,
                    message=_(
                        "Duplicate file detected (concurrent upload). "
                        "This file was already uploaded as batch '{0}' on {1}."
                    ).format(existing.get("batch_name"), existing.get("upload_time")),
                )
            else:
                # Shouldn't happen, but handle gracefully
                return UploadCheckResult(
                    success=False,
                    file_hash=file_hash,
                    reason_code=UploadBlockReason.INTEGRITY_ERROR,
                    message=_("Duplicate file detected by database constraint."),
                )

        except Exception as e:
            frappe.db.rollback()

            # Check if this is a DB integrity error (pymysql.IntegrityError, etc.)
            # These indicate constraint violations not caught by frappe.DuplicateEntryError
            error_str = str(e).lower()
            if "duplicate" in error_str or "integrity" in error_str or "unique" in error_str:
                self.logger.warning(
                    f"DB integrity error in check_and_register (possible race condition): "
                    f"hash={file_hash[:16]}..., error={e}"
                )

                # Try to find the existing entry
                existing = self._find_existing_upload(file_hash)
                if existing:
                    return UploadCheckResult(
                        success=False,
                        file_hash=file_hash,
                        reason_code=UploadBlockReason.INTEGRITY_ERROR,
                        duplicate_batch=existing.get("batch_name"),
                        duplicate_upload_time=str(existing.get("upload_time"))
                        if existing.get("upload_time")
                        else None,
                        message=_(
                            "Duplicate file detected (database constraint). "
                            "This file was already uploaded as batch '{0}' on {1}."
                        ).format(existing.get("batch_name"), existing.get("upload_time")),
                    )
                else:
                    return UploadCheckResult(
                        success=False,
                        file_hash=file_hash,
                        reason_code=UploadBlockReason.INTEGRITY_ERROR,
                        message=_("Database constraint violation during upload registration."),
                    )

            # Generic error - not an integrity constraint
            self.logger.error(f"Failed in check_and_register: {e}")
            return UploadCheckResult(
                success=False,
                file_hash=file_hash,
                reason_code=UploadBlockReason.REGISTRATION_FAILED,
                message=_("Failed to register upload: {0}").format(str(e)),
            )


# Module-level singleton instance
_sepa_upload_guard_instance: Optional[SEPAUploadGuard] = None


def get_sepa_upload_guard() -> SEPAUploadGuard:
    """
    Get the SEPAUploadGuard service instance.

    Returns a singleton instance of the service for efficiency.

    Returns:
        SEPAUploadGuard service instance
    """
    global _sepa_upload_guard_instance
    if _sepa_upload_guard_instance is None:
        _sepa_upload_guard_instance = SEPAUploadGuard()
    return _sepa_upload_guard_instance


__all__ = [
    "SEPAUploadGuard",
    "UploadBlockReason",
    "UploadCheckResult",
    "get_sepa_upload_guard",
]
