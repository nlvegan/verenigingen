"""
SEPA Race Condition Prevention Manager

This module provides comprehensive race condition prevention for SEPA batch operations,
including distributed locking, transaction isolation, and conflict resolution.

Implements Week 3 Day 1-2 requirements from the SEPA billing improvements project.
"""

import hashlib
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now

from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import SEPAError, handle_api_error, log_error
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.verenigingen_payments.utils.shared.backoff import calculate_backoff_delay
from verenigingen.verenigingen_payments.utils.shared.db_helpers import ensure_table_exists


@dataclass
class LockInfo:
    """Information about a distributed lock"""

    lock_id: str
    resource: str
    owner: str
    acquired_at: datetime
    expires_at: datetime
    lock_type: str
    metadata: Dict[str, Any]


class SEPADistributedLock:
    """
    Distributed locking system for SEPA operations using database-backed locks

    This system prevents race conditions in batch processing by implementing
    Redis-style distributed locks using Frappe's database infrastructure.
    """

    # Lock types
    BATCH_CREATION_LOCK = "batch_creation"
    INVOICE_PROCESSING_LOCK = "invoice_processing"
    XML_GENERATION_LOCK = "xml_generation"
    BATCH_SUBMISSION_LOCK = "batch_submission"

    # Default timeouts (seconds)
    DEFAULT_TIMEOUT = 300  # 5 minutes
    ACQUISITION_TIMEOUT = 30  # 30 seconds to acquire lock
    HEARTBEAT_INTERVAL = 60  # 1 minute heartbeat

    def __init__(self):
        self.session_id = self._generate_session_id()
        self._ensure_lock_table()

    def _generate_session_id(self) -> str:
        """Generate unique session ID for this lock instance"""
        timestamp = str(int(time.time() * 1000))
        user = frappe.session.user if frappe.session else "system"
        site = frappe.local.site if frappe.local else "default"
        random_part = str(random.randint(1000, 9999))

        session_data = f"{user}:{site}:{timestamp}:{random_part}"
        return hashlib.md5(session_data.encode(), usedforsecurity=False).hexdigest()[:16]

    def _ensure_lock_table(self):
        """Ensure distributed lock table exists.

        The CREATE statement is idempotent (``IF NOT EXISTS``); the shared
        ``ensure_table_exists`` helper runs it, commits, and swallows/logs any
        benign race error -- the same behavior as the previous inline
        existence-check + create + try/except.
        """
        ensure_table_exists(
            """
            CREATE TABLE IF NOT EXISTS `tabSEPA_Distributed_Lock` (
                `name` varchar(255) NOT NULL PRIMARY KEY,
                `creation` datetime(6) DEFAULT NULL,
                `modified` datetime(6) DEFAULT NULL,
                `modified_by` varchar(255) DEFAULT NULL,
                `owner` varchar(255) DEFAULT NULL,
                `docstatus` int(1) NOT NULL DEFAULT 0,
                `lock_id` varchar(255) NOT NULL,
                `resource` varchar(255) NOT NULL,
                `lock_owner` varchar(255) NOT NULL,
                `acquired_at` datetime(6) NOT NULL,
                `expires_at` datetime(6) NOT NULL,
                `lock_type` varchar(100) NOT NULL,
                `metadata` longtext DEFAULT NULL,
                `is_active` tinyint(1) DEFAULT 1,
                INDEX `idx_resource_active` (`resource`, `is_active`),
                INDEX `idx_expires_at` (`expires_at`),
                INDEX `idx_lock_owner` (`lock_owner`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            table_name="tabSEPA_Distributed_Lock",
        )

    @contextmanager
    def acquire_lock(
        self,
        resource: str,
        lock_type: str = None,
        timeout: int = None,
        metadata: Dict[str, Any] = None,
        acquisition_timeout: int = None,
    ):
        """
        Context manager to acquire and release distributed lock

        Args:
            resource: Resource identifier to lock
            lock_type: Type of lock (batch_creation, invoice_processing, etc.)
            timeout: Lock timeout in seconds (how long the lock is held)
            metadata: Additional metadata to store with lock
            acquisition_timeout: How long to keep retrying to acquire the lock
                before giving up. Defaults to ``ACQUISITION_TIMEOUT``. Callers
                that must fail fast on contention can pass a small value.

        Yields:
            LockInfo object if lock acquired successfully

        Raises:
            SEPAError: If lock cannot be acquired
        """
        lock_info = None
        try:
            lock_info = self._acquire_lock_internal(
                resource=resource,
                lock_type=lock_type or self.BATCH_CREATION_LOCK,
                timeout=timeout or self.DEFAULT_TIMEOUT,
                metadata=metadata or {},
                acquisition_timeout=acquisition_timeout,
            )
            yield lock_info

        except Exception:
            if lock_info:
                # Ensure cleanup on error
                self._release_lock_internal(lock_info.lock_id)
            raise

        finally:
            if lock_info:
                self._release_lock_internal(lock_info.lock_id)

    def _acquire_lock_internal(
        self,
        resource: str,
        lock_type: str,
        timeout: int,
        metadata: Dict[str, Any],
        acquisition_timeout: int = None,
    ) -> LockInfo:
        """
        Internal method to acquire distributed lock

        Args:
            resource: Resource to lock
            lock_type: Type of lock
            timeout: Lock timeout in seconds
            metadata: Lock metadata
            acquisition_timeout: How long to keep retrying (defaults to
                ``ACQUISITION_TIMEOUT``).

        Returns:
            LockInfo if lock acquired

        Raises:
            SEPAError: If lock cannot be acquired
        """
        lock_id = self._generate_lock_id(resource, lock_type)
        start_time = time.time()
        attempt = 0
        max_wait = acquisition_timeout if acquisition_timeout is not None else self.ACQUISITION_TIMEOUT

        while time.time() - start_time < max_wait:
            attempt += 1

            try:
                # Clean up expired locks first
                self._cleanup_expired_locks()

                # Try to acquire lock atomically
                acquired_at = get_datetime(now())
                expires_at = acquired_at + timedelta(seconds=timeout)

                # Use INSERT ... ON DUPLICATE KEY UPDATE for atomicity
                frappe.db.sql(
                    """
                    INSERT INTO `tabSEPA_Distributed_Lock`
                    (name, creation, modified, modified_by, owner,
                     lock_id, resource, lock_owner, acquired_at, expires_at,
                     lock_type, metadata, is_active)
                    VALUES (%(name)s, %(now)s, %(now)s, %(user)s, %(user)s,
                            %(lock_id)s, %(resource)s, %(owner)s, %(acquired_at)s, %(expires_at)s,
                            %(lock_type)s, %(metadata)s, 1)
                    ON DUPLICATE KEY UPDATE
                    lock_id = IF(expires_at < %(now)s OR is_active = 0,
                                VALUES(lock_id), lock_id),
                    lock_owner = IF(expires_at < %(now)s OR is_active = 0,
                                   VALUES(lock_owner), lock_owner),
                    acquired_at = IF(expires_at < %(now)s OR is_active = 0,
                                    VALUES(acquired_at), acquired_at),
                    expires_at = IF(expires_at < %(now)s OR is_active = 0,
                                   VALUES(expires_at), expires_at),
                    modified = %(now)s,
                    is_active = IF(expires_at < %(now)s OR is_active = 0, 1, is_active)
                """,
                    {
                        "name": f"SEPA_LOCK_{resource}",
                        "now": acquired_at,
                        "user": frappe.session.user if frappe.session else "system",
                        "lock_id": lock_id,
                        "resource": resource,
                        "owner": self.session_id,
                        "acquired_at": acquired_at,
                        "expires_at": expires_at,
                        "lock_type": lock_type,
                        "metadata": frappe.as_json(metadata),
                    },
                )

                # Check if we got the lock. tabSEPA_Distributed_Lock is a raw
                # table (no registered DocType), so frappe.db.get_value raises
                # "DocType SEPA_Distributed_Lock not found" in v16 — read it with
                # raw SQL instead.
                _rows = frappe.db.sql(
                    """
                    SELECT lock_id, lock_owner, acquired_at, expires_at, is_active
                    FROM `tabSEPA_Distributed_Lock`
                    WHERE name = %s
                    """,
                    (f"SEPA_LOCK_{resource}",),
                    as_dict=True,
                )
                current_lock = _rows[0] if _rows else None

                if (
                    current_lock
                    and current_lock.lock_id == lock_id
                    and current_lock.lock_owner == self.session_id
                    and current_lock.is_active
                ):
                    # Successfully acquired lock
                    frappe.db.commit()

                    return LockInfo(
                        lock_id=lock_id,
                        resource=resource,
                        owner=self.session_id,
                        acquired_at=current_lock.acquired_at,
                        expires_at=current_lock.expires_at,
                        lock_type=lock_type,
                        metadata=metadata,
                    )

                # Lock is held by someone else
                if current_lock and current_lock.is_active:
                    owner_info = current_lock.lock_owner
                    expires_info = current_lock.expires_at

                    frappe.logger().debug(
                        f"Lock acquisition attempt {attempt} failed: "
                        f"resource={resource}, current_owner={owner_info}, "
                        f"expires_at={expires_info}"
                    )

                # Wait with exponential backoff
                wait_time = min(2**attempt * 0.1, 2.0)  # Max 2 seconds
                time.sleep(wait_time)

            except Exception as e:
                frappe.db.rollback()
                frappe.logger().error(f"Lock acquisition error on attempt {attempt}: {str(e)}")

                if attempt >= 3:  # Give up after 3 attempts on errors
                    break

                time.sleep(0.5)

        # Failed to acquire lock
        current_lock_info = self._get_current_lock_info(resource)
        error_msg = (
            f"Failed to acquire lock for resource '{resource}' after {attempt} attempts. "
            f"Lock held by: {current_lock_info.get('lock_owner', 'unknown')} "
            f"since {current_lock_info.get('acquired_at', 'unknown')}"
        )

        raise SEPAError(_(error_msg))

    def _release_lock_internal(self, lock_id: str):
        """
        Release distributed lock

        Args:
            lock_id: Lock ID to release
        """
        try:
            frappe.db.sql(
                """
                UPDATE `tabSEPA_Distributed_Lock`
                SET is_active = 0, modified = %s
                WHERE lock_id = %s AND lock_owner = %s
            """,
                (now(), lock_id, self.session_id),
            )

            frappe.db.commit()

        except Exception as e:
            frappe.logger().error(f"Error releasing lock {lock_id}: {str(e)}")

    def _generate_lock_id(self, resource: str, lock_type: str) -> str:
        """Generate unique lock ID"""
        timestamp = str(int(time.time() * 1000))
        lock_data = f"{resource}:{lock_type}:{self.session_id}:{timestamp}"
        return hashlib.md5(lock_data.encode(), usedforsecurity=False).hexdigest()

    def _cleanup_expired_locks(self):
        """Clean up expired locks"""
        try:
            current_time = now()

            # Mark expired locks as inactive
            frappe.db.sql(
                """
                UPDATE `tabSEPA_Distributed_Lock`
                SET is_active = 0, modified = %s
                WHERE expires_at < %s AND is_active = 1
            """,
                (current_time, current_time),
            )

            # Delete very old inactive locks (older than 24 hours)
            cleanup_time = add_to_date(current_time, seconds=-86400)  # 24 hours ago
            frappe.db.sql(
                """
                DELETE FROM `tabSEPA_Distributed_Lock`
                WHERE modified < %s AND is_active = 0
            """,
                (cleanup_time,),
            )

        except Exception as e:
            frappe.logger().warning(f"Lock cleanup error: {str(e)}")

    def _get_current_lock_info(self, resource: str) -> Dict[str, Any]:
        """Get information about current lock on resource"""
        try:
            # Raw table (no registered DocType) -> use raw SQL, not get_value.
            rows = frappe.db.sql(
                """
                SELECT lock_owner, acquired_at, expires_at, lock_type, is_active
                FROM `tabSEPA_Distributed_Lock`
                WHERE name = %s
                """,
                (f"SEPA_LOCK_{resource}",),
                as_dict=True,
            )
            return (rows[0] if rows else {}) or {}
        except Exception:
            return {}

    def force_release_lock(self, resource: str, admin_override: bool = False) -> bool:
        """
        Force release a lock (admin function)

        Args:
            resource: Resource to unlock
            admin_override: Allow admin to force unlock

        Returns:
            True if lock was released
        """
        if not admin_override and Roles.SYSTEM_MANAGER not in frappe.get_roles():
            raise SEPAError(_("Only system managers can force release locks"))

        try:
            frappe.db.sql(
                """
                UPDATE `tabSEPA_Distributed_Lock`
                SET is_active = 0, modified = %s
                WHERE resource = %s AND is_active = 1
            """,
                (now(), resource),
            )

            frappe.db.commit()
            return True

        except Exception as e:
            frappe.logger().error(f"Error force releasing lock for {resource}: {str(e)}")
            return False


class SEPABatchRaceConditionManager:
    """
    Main manager for preventing race conditions in SEPA batch operations

    This class orchestrates distributed locking, transaction isolation,
    and conflict detection for SEPA batch processing.
    """

    def __init__(self):
        self.lock_manager = SEPADistributedLock()
        self.retry_config = {"max_attempts": 3, "base_delay": 1.0, "max_delay": 10.0, "exponential_base": 2.0}

    @performance_monitor(threshold_ms=2000)
    def create_batch_with_race_protection(self, batch_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create SEPA batch with comprehensive race condition protection

        Args:
            batch_data: Batch creation data

        Returns:
            Result dictionary with batch information
        """
        invoice_list = batch_data.get("invoice_list", [])
        if not invoice_list:
            raise SEPAError(_("No invoices provided for batch creation"))

        # Extract invoice names for locking
        invoice_names = [inv.get("invoice") for inv in invoice_list if inv.get("invoice")]
        if not invoice_names:
            raise SEPAError(_("No valid invoice names found"))

        # Create resource identifier for this batch operation
        batch_resource = f"batch_creation_{hashlib.md5(str(sorted(invoice_names)).encode(), usedforsecurity=False).hexdigest()[:16]}"

        # Metadata for lock
        lock_metadata = {
            "batch_date": batch_data.get("batch_date"),
            "batch_type": batch_data.get("batch_type"),
            "invoice_count": len(invoice_names),
            "invoices": invoice_names[:5],  # Store first 5 for debugging
            "user": frappe.session.user if frappe.session else "system",
            "timestamp": now(),
        }

        # Use distributed lock for batch creation
        with self.lock_manager.acquire_lock(
            resource=batch_resource,
            lock_type=SEPADistributedLock.BATCH_CREATION_LOCK,
            timeout=600,  # 10 minutes for batch creation
            metadata=lock_metadata,
        ) as lock_info:
            frappe.logger().info(f"Acquired batch creation lock: {lock_info.lock_id}")

            # Execute batch creation with transaction isolation
            return self._execute_batch_creation_with_isolation(batch_data, invoice_names)

    def _execute_batch_creation_with_isolation(
        self, batch_data: Dict[str, Any], invoice_names: List[str]
    ) -> Dict[str, Any]:
        """
        Execute batch creation with transaction isolation

        Args:
            batch_data: Batch creation data
            invoice_names: List of invoice names

        Returns:
            Result dictionary
        """
        # Neither a SET TRANSACTION ISOLATION LEVEL nor a frappe.db.begin() here.
        #
        # SET TRANSACTION ISOLATION LEVEL is only legal with no transaction open,
        # and there is ALWAYS one open: frappe.db.commit() is `COMMIT` followed by
        # `begin()` (frappe/database/database.py), so even the distributed-lock
        # acquisition immediately above leaves a fresh transaction running. It
        # raised MySQL 1568 "Transaction characteristics can't be changed while a
        # transaction is in progress" on every call, and @handle_api_error on the
        # public entry point turned that into a generic failure response.
        #
        # Nothing is lost: phantom reads are prevented by the SELECT ... FOR UPDATE
        # in _lock_invoices_for_processing below, which is the real serialisation
        # mechanism. The commit()/rollback() on the exit paths still bracket the
        # work and release the row locks.
        try:
            # Step 1: Lock invoice records to prevent concurrent access
            locked_invoices = self._lock_invoices_for_processing(invoice_names)

            # Step 2: Validate invoice availability and state
            validation_result = self._validate_invoice_availability(locked_invoices, batch_data)

            if not validation_result["valid"]:
                frappe.db.rollback()
                return {
                    "success": False,
                    "errors": validation_result["errors"],
                    "message": "Invoice validation failed",
                }

            # Step 3: Check for conflicts with existing batches
            conflict_result = self._detect_batch_conflicts(invoice_names, batch_data)

            if conflict_result["conflicts"]:
                frappe.db.rollback()
                return {
                    "success": False,
                    "errors": [f"Conflicts detected: {'; '.join(conflict_result['conflicts'])}"],
                    "message": "Batch conflicts detected",
                }

            # Step 4: Create the batch document with its invoice rows. The rows
            # must be in place BEFORE insert(): Direct Debit Batch validation
            # rejects a batch with none ("No invoices added to batch"), so the old
            # insert-then-link order could never succeed.
            batch_doc = self._create_batch_document(batch_data, validation_result["validated_invoices"])

            # Commit transaction
            frappe.db.commit()

            frappe.logger().info(
                f"Successfully created batch {batch_doc.name} with {len(validation_result['validated_invoices'])} invoices"
            )

            return {
                "success": True,
                "batch_name": batch_doc.name,
                "batch_id": batch_doc.name,
                "total_amount": batch_doc.total_amount,
                "invoice_count": len(validation_result["validated_invoices"]),
                "message": f"Batch created successfully with {len(validation_result['validated_invoices'])} invoices",
            }

        except Exception as e:
            frappe.db.rollback()
            error_msg = f"Batch creation failed: {str(e)}"
            log_error(
                e,
                context={"batch_data": batch_data, "invoice_count": len(invoice_names)},
                module="sepa_race_condition_manager",
            )

            raise SEPAError(_(error_msg))

    def _lock_invoices_for_processing(self, invoice_names: List[str]) -> List[Dict[str, Any]]:
        """
        Lock invoices for processing using SELECT FOR UPDATE

        Args:
            invoice_names: List of invoice names to lock

        Returns:
            List of locked invoice records
        """
        try:
            locked_invoices = frappe.db.sql(
                """
                SELECT
                    si.name,
                    si.status,
                    si.outstanding_amount,
                    si.docstatus,
                    si.member,
                    si.membership,
                    -- Aliased explicitly: this is a Link to Membership Dues
                    -- Schedule, NOT to Membership. It used to be selected as
                    -- `membership`, which shadowed the real si.membership column
                    -- and fed a dues-schedule name into a Link->Membership field.
                    si.membership_dues_schedule_display as dues_schedule,
                    si.posting_date,
                    si.due_date
                FROM `tabSales Invoice` si
                WHERE si.name IN %(invoices)s
                AND si.docstatus = 1
                FOR UPDATE
            """,
                {"invoices": invoice_names},
                as_dict=True,
            )

            return locked_invoices

        except Exception as e:
            raise SEPAError(_(f"Failed to lock invoices for processing: {str(e)}"))

    def _validate_invoice_availability(
        self, locked_invoices: List[Dict[str, Any]], batch_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate that locked invoices are available for batch processing

        Args:
            locked_invoices: List of locked invoice records
            batch_data: Batch creation data

        Returns:
            Validation result
        """
        result = {"valid": True, "errors": [], "validated_invoices": []}

        invoice_lookup = {inv["name"]: inv for inv in locked_invoices}
        requested_invoices = {inv["invoice"]: inv for inv in batch_data.get("invoice_list", [])}

        # Check each requested invoice
        for invoice_name, invoice_data in requested_invoices.items():
            if invoice_name not in invoice_lookup:
                result["errors"].append(f"Invoice not found or not locked: {invoice_name}")
                continue

            db_invoice = invoice_lookup[invoice_name]

            # Validate invoice status
            if db_invoice["status"] not in ["Unpaid", "Overdue"]:
                result["errors"].append(
                    f"Invoice {invoice_name} is not unpaid (status: {db_invoice['status']})"
                )
                continue

            # Validate outstanding amount
            expected_amount = float(invoice_data.get("amount", 0))
            actual_amount = float(db_invoice["outstanding_amount"] or 0)

            if abs(expected_amount - actual_amount) > 0.01:  # Allow 1 cent difference
                result["errors"].append(
                    f"Amount mismatch for {invoice_name}: "
                    f"expected {expected_amount}, actual {actual_amount}"
                )
                continue

            # Invoice is valid
            validated_invoice = {**invoice_data}
            validated_invoice["db_record"] = db_invoice
            result["validated_invoices"].append(validated_invoice)

        result["valid"] = len(result["errors"]) == 0
        return result

    def _detect_batch_conflicts(self, invoice_names: List[str], batch_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect conflicts with existing batches

        Args:
            invoice_names: List of invoice names
            batch_data: Batch creation data

        Returns:
            Conflict detection result
        """
        result = {"conflicts": [], "warnings": []}

        try:
            # Check for invoices already in active batches
            existing_assignments = frappe.db.sql(
                """
                SELECT
                    ddi.invoice,
                    ddb.name as batch_name,
                    ddb.status as batch_status,
                    ddb.batch_date
                FROM `tabDirect Debit Batch Invoice` ddi
                JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
                WHERE ddi.invoice IN %(invoices)s
                AND ddb.docstatus != 2  -- Not cancelled
                AND ddb.status NOT IN ('Failed', 'Cancelled')
                FOR UPDATE
            """,
                {"invoices": invoice_names},
                as_dict=True,
            )

            if existing_assignments:
                for assignment in existing_assignments:
                    result["conflicts"].append(
                        f"Invoice {assignment.invoice} already in batch "
                        f"{assignment.batch_name} (status: {assignment.batch_status})"
                    )

            # Check for batches on the same date
            batch_date = batch_data.get("batch_date")
            if batch_date:
                same_date_batches = frappe.db.sql(
                    """
                    SELECT name, status, total_amount, entry_count
                    FROM `tabDirect Debit Batch`
                    WHERE batch_date = %s
                    AND docstatus != 2
                    AND status NOT IN ('Failed', 'Cancelled')
                """,
                    (batch_date,),
                    as_dict=True,
                )

                if same_date_batches:
                    for existing_batch in same_date_batches:
                        # #774: 'Partially Collected' is unsubmitted the same
                        # way 'Draft'/'Generated' are -- it must still warn
                        # about a same-date collision instead of silently
                        # dropping out of view.
                        if existing_batch.status in ["Draft", "Generated", "Partially Collected"]:
                            result["warnings"].append(
                                f"Another batch exists for date {batch_date}: "
                                f"{existing_batch.name} (status: {existing_batch.status})"
                            )

        except Exception as e:
            result["conflicts"].append(f"Error detecting conflicts: {str(e)}")

        return result

    def _create_batch_document(
        self, batch_data: Dict[str, Any], validated_invoices: List[Dict[str, Any]]
    ) -> Any:
        """
        Create the Direct Debit Batch document

        Args:
            batch_data: Batch creation data
            validated_invoices: List of validated invoices

        Returns:
            Created batch document
        """
        batch_doc = frappe.new_doc("Direct Debit Batch")
        batch_doc.batch_date = batch_data["batch_date"]
        batch_doc.batch_type = batch_data["batch_type"]
        # The mandatory field is batch_description; `description` is not a field on
        # Direct Debit Batch, so the old assignment was silently dropped and the
        # insert failed its mandatory check.
        batch_doc.batch_description = (
            batch_data.get("batch_description", batch_data.get("description"))
            or f"SEPA Batch {batch_data['batch_date']}"
        )
        batch_doc.currency = (
            batch_data.get("currency")
            or (validated_invoices[0].get("currency") if validated_invoices else None)
            or "EUR"
        )
        batch_doc.status = "Draft"

        # Calculate totals
        total_amount = sum(float(inv.get("amount", 0)) for inv in validated_invoices)
        batch_doc.total_amount = total_amount
        batch_doc.entry_count = len(validated_invoices)

        # Invoice rows go on BEFORE insert(): Direct Debit Batch validation
        # rejects a batch with no rows.
        self._append_invoice_rows(batch_doc, validated_invoices)

        batch_doc.insert()

        # Metadata about race-condition protection, AFTER insert() -- add_comment
        # needs a saved document to reference.
        batch_doc.add_comment(
            "Info",
            f"Batch created with race condition protection. "
            f"Processed {len(validated_invoices)} invoices. "
            f"Session: {self.lock_manager.session_id}",
        )

        return batch_doc

    def _link_invoices_to_batch(self, batch_doc: Any, validated_invoices: List[Dict[str, Any]]):
        """
        Append validated invoices to an ALREADY-SAVED batch document and save it.

        _create_batch_document populates its own rows before insert(), so the
        creation path does not call this. Kept for callers that add rows to an
        existing batch; calling it on a freshly created batch would duplicate
        every row.

        Args:
            batch_doc: Direct Debit Batch document
            validated_invoices: List of validated invoices
        """
        self._append_invoice_rows(batch_doc, validated_invoices)
        batch_doc.save()

    @staticmethod
    def _append_invoice_rows(batch_doc: Any, validated_invoices: List[Dict[str, Any]]):
        """Append invoice child rows to a batch document without saving it."""
        for invoice_data in validated_invoices:
            # member and membership are mandatory on Direct Debit Batch Invoice.
            # Prefer what the caller passed, else fall back to the locked Sales
            # Invoice row (_lock_invoices_for_processing selects both).
            db_record = invoice_data.get("db_record") or {}
            member = invoice_data.get("member") or db_record.get("member")
            membership = invoice_data.get("membership") or db_record.get("membership")
            if not member or not membership:
                # Fail with the field and the invoice named, rather than letting
                # Frappe raise a bare MandatoryError from inside insert(). No
                # deeper resolution is attempted here: deriving a Membership from
                # a dues schedule is the canonical batch builder's job
                # (api/sepa_batch_ui.py), and guessing it here would duplicate
                # that logic in a third place.
                missing = ", ".join(n for n, v in (("member", member), ("membership", membership)) if not v)
                raise SEPAError(
                    _(
                        "Invoice {0}: {1} missing. Supply it in invoice_list, or set it on the Sales Invoice."
                    ).format(invoice_data["invoice"], missing)
                )
            batch_invoice = batch_doc.append("invoices", {})
            batch_invoice.invoice = invoice_data["invoice"]
            batch_invoice.member = member
            batch_invoice.membership = membership
            batch_invoice.amount = invoice_data["amount"]
            batch_invoice.currency = invoice_data.get("currency", "EUR")
            batch_invoice.member_name = invoice_data.get("member_name", "")
            batch_invoice.iban = invoice_data.get("iban", "")
            batch_invoice.bic = invoice_data.get("bic", "")
            batch_invoice.mandate_reference = invoice_data.get("mandate_reference", "")
            batch_invoice.status = "Pending"

    @handle_api_error
    def retry_failed_operation(self, operation_func, *args, **kwargs) -> Any:
        """
        Retry failed operations with exponential backoff

        Args:
            operation_func: Function to retry
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Operation result
        """
        last_exception = None

        for attempt in range(self.retry_config["max_attempts"]):
            try:
                return operation_func(*args, **kwargs)

            except Exception as e:
                last_exception = e

                if attempt < self.retry_config["max_attempts"] - 1:
                    # Calculate delay with exponential backoff. ``attempt`` is
                    # 0-based here (attempt 0 -> base_delay); the shared helper is
                    # 1-based, so pass ``attempt + 1``. No jitter (matching the
                    # legacy inline math).
                    delay = calculate_backoff_delay(
                        attempt + 1,
                        base_delay=self.retry_config["base_delay"],
                        max_delay=self.retry_config["max_delay"],
                        strategy="exponential",
                        exponential_base=self.retry_config["exponential_base"],
                        jitter_factor=0.0,
                    )

                    frappe.logger().warning(
                        f"Operation failed on attempt {attempt + 1}, "
                        f"retrying in {delay:.2f} seconds: {str(e)}"
                    )

                    time.sleep(delay)
                else:
                    frappe.logger().error(
                        f"Operation failed after {self.retry_config['max_attempts']} attempts: {str(e)}"
                    )

        # All attempts failed
        raise SEPAError(
            _(f"Operation failed after {self.retry_config['max_attempts']} attempts: {str(last_exception)}")
        )


# API Functions


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def create_sepa_batch_with_race_protection(**batch_data) -> Dict[str, Any]:
    """
    API endpoint to create SEPA batch with race condition protection

    Args:
        **batch_data: Batch creation parameters

    Returns:
        Batch creation result
    """
    manager = SEPABatchRaceConditionManager()
    return manager.create_batch_with_race_protection(batch_data)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
@handle_api_error
def get_batch_lock_status(resource: str) -> Dict[str, Any]:
    """
    Get lock status for a batch resource

    Args:
        resource: Resource identifier

    Returns:
        Lock status information
    """
    lock_manager = SEPADistributedLock()
    lock_info = lock_manager._get_current_lock_info(resource)

    return {"locked": bool(lock_info.get("is_active")), "lock_info": lock_info}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
@handle_api_error
def force_release_batch_lock(resource: str) -> Dict[str, Any]:
    """
    Force release a batch lock (admin only)

    Args:
        resource: Resource to unlock

    Returns:
        Release result
    """
    if Roles.SYSTEM_MANAGER not in frappe.get_roles():
        raise SEPAError(_("Only system managers can force release locks"))

    lock_manager = SEPADistributedLock()
    success = lock_manager.force_release_lock(resource, admin_override=True)

    return {
        "success": success,
        "message": "Lock released successfully" if success else "Failed to release lock",
    }
