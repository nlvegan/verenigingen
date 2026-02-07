# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberImportService - Service for creating/updating members during CSV import.

Extracts core member creation and update logic from MijnRood CSV Import DocType
into a dedicated service for better separation of concerns and testability.

Usage:
    from verenigingen.services.import.member_import_service import (
        get_member_import_service,
    )

    service = get_member_import_service()
    result, member_name = service.create_or_update_member(
        row_data={"first_name": "John", ...},
        import_doc_name="MEMBER-IMPORT-2025-00001",
    )
"""

import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional, Tuple

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.member.member_lookup_service import get_member_lookup_service
from verenigingen.utils.csv.data_transformers import clean_phone_number
from verenigingen.utils.csv_import_processor import ensure_bulk_import_members_set
from verenigingen.utils.safe_member_optimizer import safe_member_optimizer

# Advisory lock configuration defaults (can be overridden via site_config)
# To override, add to site_config.json:
#   "member_import_lock_timeout": 15,
#   "member_import_lock_retries": 5,
#   "member_import_lock_base_delay": 1.0
_DEFAULT_LOCK_TIMEOUT_SECONDS = 10
_DEFAULT_LOCK_MAX_RETRIES = 3
_DEFAULT_LOCK_RETRY_BASE_DELAY = 0.5


def _get_lock_config() -> tuple:
    """Get lock configuration from site_config with fallbacks to defaults.

    Returns:
        Tuple of (timeout_seconds, max_retries, base_delay)
    """
    site_config = frappe.get_site_config()
    timeout = site_config.get("member_import_lock_timeout", _DEFAULT_LOCK_TIMEOUT_SECONDS)
    retries = site_config.get("member_import_lock_retries", _DEFAULT_LOCK_MAX_RETRIES)
    base_delay = site_config.get("member_import_lock_base_delay", _DEFAULT_LOCK_RETRY_BASE_DELAY)
    return (timeout, retries, base_delay)


# Module-level constants for backward compatibility (read from site_config at import time)
# Note: For dynamic config, use _get_lock_config() instead
LOCK_TIMEOUT_SECONDS = _DEFAULT_LOCK_TIMEOUT_SECONDS
LOCK_MAX_RETRIES = _DEFAULT_LOCK_MAX_RETRIES
LOCK_RETRY_BASE_DELAY = _DEFAULT_LOCK_RETRY_BASE_DELAY


class MemberImportService(StatelessService):
    """Service for creating/updating members during CSV import.

    Handles the core member creation and update logic previously embedded
    in the MijnRood CSV Import DocType. This service:

    - Maps CSV row data to Member document fields
    - Determines member status from membership type
    - Handles both creation and update paths with transaction safety
    - Sets appropriate system flags for CSV import context

    Attributes:
        STATUS_MAP: Mapping of membership types to (status, is_aspirant) tuples
        TERMINATED_TYPES: Membership types that indicate terminated status
    """

    # Mapping of membership type to (status, is_aspirant)
    STATUS_MAP = {
        "lid": ("Active", False),
        "standard": ("Active", False),
        "aspirant": ("Active", True),
        "overleden": ("Deceased", False),
        "deceased": ("Deceased", False),
        "opgezegd": ("Terminated", False),
        "terminated": ("Terminated", False),
        "uitgeschreven": ("Terminated", False),
        "geroyeerd": ("Banned", False),
        "expelled": ("Banned", False),
        "dubbel": ("Rejected", False),
        "geschorst": ("Suspended", False),
    }

    TERMINATED_TYPES = frozenset(
        [
            "opgezegd",
            "terminated",
            "uitgeschreven",
            "geroyeerd",
            "expelled",
            "geschorst",
            "overleden",
            "deceased",
        ]
    )

    def __init__(self):
        """Initialize the MemberImportService."""
        super().__init__(service_name="MemberImportService")

    def determine_member_status(self, membership_type: Optional[str]) -> Tuple[str, bool]:
        """Determine member status and aspirant flag from membership type.

        Maps CSV membership types (Dutch terms like 'lid', 'overleden', etc.)
        to Member document status values.

        Args:
            membership_type: Membership type from CSV (e.g., 'lid', 'aspirant', 'opgezegd')

        Returns:
            Tuple of (status, is_aspirant) where:
            - status: Member status ('Active', 'Terminated', 'Deceased', etc.)
            - is_aspirant: Boolean indicating if member is aspirant
        """
        if not membership_type:
            return ("Active", False)

        normalized = membership_type.lower().strip()
        return self.STATUS_MAP.get(normalized, ("Active", False))

    def update_member_fields(
        self,
        member_doc: Document,
        row_data: Dict[str, Any],
        import_doc_name: str,
        create_volunteer_records: bool = False,
    ) -> None:
        """Update member document fields from CSV row data.

        Sets all appropriate fields on the member document and prepares
        temporary data for related record creation (address, Mollie, etc.).

        Args:
            member_doc: Member document to update (new or existing)
            row_data: Dictionary containing CSV row data
            import_doc_name: Name of the import document for tracking
            create_volunteer_records: Whether to create volunteer records
        """
        # Set system flags first to bypass workflow validation
        member_doc.flags.ignore_workflow = True
        member_doc._system_update = True
        member_doc._csv_import = True
        member_doc._skip_workflow_validation = True
        member_doc._skip_status_validation = True
        member_doc.flags.ignore_validate = False
        member_doc.flags.ignore_mandatory = False

        # Clear application_id for CSV imported members
        member_doc.application_id = None

        # Set status based on membership type
        membership_type = (row_data.get("membership_type") or "").lower()
        status, is_aspirant = self.determine_member_status(membership_type)
        member_doc.status = status
        member_doc.is_aspirant = 1 if is_aspirant else 0

        # Basic member information
        if row_data.get("member_id"):
            member_doc.member_id = row_data["member_id"]
        if row_data.get("first_name"):
            member_doc.first_name = row_data["first_name"]
        if row_data.get("tussenvoegsel"):
            member_doc.tussenvoegsel = row_data["tussenvoegsel"]
        if row_data.get("last_name"):
            member_doc.last_name = row_data["last_name"]
        if row_data.get("birth_date"):
            member_doc.birth_date = row_data["birth_date"]
        if row_data.get("email"):
            member_doc.email = row_data["email"]
        if row_data.get("contact_number"):
            cleaned_phone = clean_phone_number(row_data["contact_number"])
            if cleaned_phone:
                member_doc.contact_number = cleaned_phone
        if row_data.get("member_since"):
            member_doc.member_since = row_data["member_since"]

        # Financial information - IBAN
        if row_data.get("iban"):
            member_doc.iban = row_data["iban"]
            member_doc.payment_method = "Bank Transfer"

        # Handle dues rate
        self._set_dues_rate_fields(member_doc, row_data)

        # Mollie data - store for later Customer update
        if row_data.get("custom_mollie_customer_id") or row_data.get("custom_mollie_subscription_id"):
            member_doc.payment_method = "Mollie"
            member_doc._mollie_data = {
                "custom_mollie_customer_id": row_data.get("custom_mollie_customer_id"),
                "custom_mollie_subscription_id": row_data.get("custom_mollie_subscription_id"),
                "custom_subscription_status": (
                    "active" if row_data.get("custom_mollie_subscription_id") else None
                ),
            }

        # Address data - store for later creation
        if any(row_data.get(field) for field in ["address_line1", "city", "postal_code"]):
            member_doc._pending_address_data = row_data

        # Termination data for terminated/deceased members
        if membership_type in self.TERMINATED_TYPES:
            member_doc._pending_termination_data = {
                "membership_type": membership_type,
                "member_since": row_data.get("member_since"),
                "termination_reason": self._get_termination_reason(membership_type),
            }

        # Chapter assignment
        if row_data.get("chapter"):
            chapter_raw = str(row_data["chapter"]).strip()
            chapter_name = chapter_raw.rstrip("*").strip()
            if chapter_name:
                member_doc._pending_chapter_assignment = chapter_name

        # Handle member_since date - preserve oldest date when updating
        self._set_member_since_date(member_doc, row_data)

        # Add import tracking to review_notes
        import_note = f"Imported from Mijnrood CSV (Import: {import_doc_name})"
        if member_doc.review_notes:
            member_doc.review_notes = f"{member_doc.review_notes}\n{import_note}"
        else:
            member_doc.review_notes = import_note

        # Volunteering flag
        if create_volunteer_records:
            member_doc.interested_in_volunteering = 1

    @contextmanager
    def _bulk_context(self) -> Generator[None, None, None]:
        """Context manager ensuring bulk operation flags are set and restored.

        This defensive context manager guards against the service being called
        outside of the expected bulk import context. Without these flags:
        - Notifications may spam users during bulk import
        - Version tracking may flood the activity log
        - Chapter events may overflow the event queue

        The context manager:
        1. Saves the previous flag values
        2. Sets the required flags if not already set (with warning)
        3. Restores previous values on exit to avoid side effects

        Usage:
            with self._bulk_context():
                # Bulk operations here
                pass

        Yields:
            None
        """
        required_flags = ["bulk_member_operations", "in_bulk_import"]

        # Save previous values
        previous_values = {}
        flags_were_missing = []

        for flag_name in required_flags:
            previous_values[flag_name] = getattr(frappe.flags, flag_name, None)
            if not previous_values[flag_name]:
                flags_were_missing.append(flag_name)
                setattr(frappe.flags, flag_name, True)

        # Log warning once if any flags were missing
        if flags_were_missing:
            self.logger.warning(
                f"MemberImportService called without bulk context flags: "
                f"{', '.join(flags_were_missing)}. Setting them defensively."
            )

        try:
            yield
        finally:
            # Restore previous values to avoid side effects
            for flag_name, previous_value in previous_values.items():
                if previous_value is None:
                    # Flag didn't exist before, remove it
                    frappe.flags.pop(flag_name, None)
                else:
                    setattr(frappe.flags, flag_name, previous_value)

    def create_or_update_member(
        self,
        row_data: Dict[str, Any],
        import_doc_name: str,
        create_volunteer_records: bool = False,
    ) -> Tuple[str, Optional[str]]:
        """Create or update a member from CSV row data.

        Main entry point for member import. Handles both creation and update
        paths with appropriate transaction safety via savepoints.

        Args:
            row_data: Dictionary containing CSV row data with fields like
                'member_id', 'first_name', 'email', etc.
            import_doc_name: Name of the import document for tracking
            create_volunteer_records: Whether to create volunteer records

        Returns:
            Tuple of (status, member_name_or_none) where:
            - status: 'created', 'updated', 'skipped', or 'failed'
            - member_name_or_none: Member document name or None on failure
        """
        # Use context manager to ensure bulk flags are set and restored
        with self._bulk_context():
            row_num = row_data.get("row_number", "?")

            # Check if member exists using cascade lookup (member_id -> email)
            lookup_service = get_member_lookup_service()
            existing_member_doc, matched_strategy = lookup_service.find_member_with_strategy(
                row_data, strategies=lookup_service.MIJNROOD_STRATEGIES
            )

            if existing_member_doc:
                # Log at INFO level for audit trail
                self.logger.info(
                    f"Row {row_num}: Found existing member {existing_member_doc.name} "
                    f"via {matched_strategy.value if matched_strategy else 'unknown'}"
                )
                return self._update_existing_member(
                    existing_member_doc.name,
                    row_data,
                    import_doc_name,
                    create_volunteer_records,
                    row_num,
                )
            else:
                return self._create_new_member(
                    row_data,
                    import_doc_name,
                    create_volunteer_records,
                    row_num,
                )

    def _update_existing_member(
        self,
        member_name: str,
        row_data: Dict[str, Any],
        import_doc_name: str,
        create_volunteer_records: bool,
        row_num: Any,
    ) -> Tuple[str, Optional[str]]:
        """Update an existing member with row data."""
        savepoint_name = f"member_update_{row_num}_{int(time.time() * 1000)}"

        try:
            frappe.db.sql(f"SAVEPOINT {savepoint_name}")

            member = frappe.get_doc("Member", member_name)

            # Log the update
            match_reason = "member_id" if row_data.get("member_id") else "email"
            match_value = row_data.get("member_id") or row_data.get("email")
            self.logger.info(
                f"Updating existing member {member.name} (matched by {match_reason}: {match_value})"
            )

            self.update_member_fields(member, row_data, import_doc_name, create_volunteer_records)
            member._system_update = True
            member.save()
            frappe.db.commit()

            return "updated", member.name

        except frappe.ValidationError as e:
            frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            self.logger.error(f"Row {row_num}: Update validation error for {member_name} - {str(e)[:200]}")
            return "failed", member_name

        except Exception as e:
            try:
                frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            except Exception:
                pass
            self.logger.error(f"Row {row_num}: Update failed for {member_name} - {str(e)[:200]}")
            frappe.log_error(frappe.get_traceback(), f"CSV Import Update Error Row {row_num}")
            return "failed", member_name

    def _acquire_advisory_lock(self, lock_name: str, row_num: Any) -> bool:
        """Acquire MySQL advisory lock with exponential backoff.

        Args:
            lock_name: Name of the lock to acquire
            row_num: Row number for logging

        Returns:
            True if lock was acquired, False otherwise
        """
        # Get dynamic config (allows runtime override via site_config)
        timeout, max_retries, base_delay = _get_lock_config()
        retries_needed = 0

        for attempt in range(max_retries):
            lock_result = frappe.db.sql(
                "SELECT GET_LOCK(%s, %s) as acquired",
                (lock_name, timeout),
                as_dict=True,
            )
            if lock_result and lock_result[0].acquired == 1:
                # Log contention metric if retries were needed
                if retries_needed > 0:
                    self.logger.info(
                        f"Row {row_num}: Lock acquired after {retries_needed} retries "
                        f"(contention detected for {lock_name})"
                    )
                return True

            retries_needed += 1
            # Exponential backoff: base * 2^attempt (e.g., 0.5s, 1.0s, 2.0s)
            delay = base_delay * (2**attempt)
            self.logger.warning(
                f"Row {row_num}: Lock acquisition attempt {attempt + 1}/{max_retries} "
                f"failed for {lock_name}, retrying in {delay}s"
            )
            time.sleep(delay)

        # Log contention metric on failure
        self.logger.error(
            f"Row {row_num}: Lock contention - failed to acquire {lock_name} "
            f"after {max_retries} attempts (total wait: ~{sum(base_delay * (2**i) for i in range(max_retries)):.1f}s)"
        )
        return False

    def _release_advisory_lock(self, lock_name: str, row_num: Any) -> None:
        """Release MySQL advisory lock with verification.

        Verifies that RELEASE_LOCK returns 1 (success). If it returns 0 or NULL,
        logs a warning as this indicates a potential connection issue.

        Args:
            lock_name: Name of the lock to release
            row_num: Row number for logging
        """
        try:
            release_result = frappe.db.sql(
                "SELECT RELEASE_LOCK(%s) as released",
                (lock_name,),
                as_dict=True,
            )
            if release_result:
                released = release_result[0].released
                if released != 1:
                    # released=0 means lock wasn't held by this connection
                    # released=NULL means lock doesn't exist
                    self.logger.warning(
                        f"Row {row_num}: RELEASE_LOCK returned {released} for {lock_name}. "
                        "This may indicate the lock was released on a different connection "
                        "or the connection changed during the operation."
                    )
        except Exception as e:
            self.logger.error(f"Row {row_num}: Failed to release lock {lock_name}: {e}")

    def _create_new_member(
        self,
        row_data: Dict[str, Any],
        import_doc_name: str,
        create_volunteer_records: bool,
        row_num: Any,
    ) -> Tuple[str, Optional[str]]:
        """Create a new member with row data.

        Uses advisory lock to prevent race conditions when concurrent imports
        try to create the same member simultaneously. The lock acquisition uses
        exponential backoff for resilience under high load.

        Advisory Lock Connection Semantics:
        -----------------------------------
        MySQL GET_LOCK/RELEASE_LOCK are connection-scoped. In Frappe, frappe.db.sql()
        uses the same connection (frappe.local.db) within a request. We verify that
        RELEASE_LOCK returns 1 to detect any connection issues.
        """
        import hashlib

        # Generate lock key from canonical identifier (member_id or email)
        lock_key = row_data.get("member_id") or row_data.get("email", "")
        if lock_key:
            # Hash to ensure safe lock name (no special chars, bounded length)
            lock_hash = hashlib.md5(lock_key.lower().strip().encode()).hexdigest()[:16]
            lock_name = f"member_create_{lock_hash}"
        else:
            # Fallback to row-based lock if no identifier
            lock_name = f"member_create_row_{row_num}_{int(time.time() * 1000)}"

        savepoint_name = f"sp_member_{row_num}_{int(time.time() * 1000)}"
        lock_acquired = False

        try:
            # Acquire advisory lock with exponential backoff
            lock_acquired = self._acquire_advisory_lock(lock_name, row_num)

            if not lock_acquired:
                # Fail-safe: without a lock, we cannot safely create a member
                # Check if another process already created this member
                lookup_service = get_member_lookup_service()
                existing = lookup_service.find_member(row_data, strategies=lookup_service.MIJNROOD_STRATEGIES)
                if existing:
                    self.logger.info(
                        f"Row {row_num}: Member {existing.name} was created by concurrent process"
                    )
                    return "skipped", existing.name
                # No lock and no existing member - fail to prevent potential duplicate
                # This is fail-safe behavior: better to fail and retry than create duplicates
                self.logger.error(
                    f"Row {row_num}: Lock acquisition failed and no existing member found. "
                    "Failing to prevent potential duplicate creation."
                )
                return "failed", None

            # Re-check if member exists after acquiring lock (TOCTOU prevention)
            # Uses same strategies as initial lookup for consistency
            lookup_service = get_member_lookup_service()
            existing_after_lock = lookup_service.find_member(
                row_data, strategies=lookup_service.MIJNROOD_STRATEGIES
            )
            if existing_after_lock:
                self.logger.info(
                    f"Row {row_num}: Member {existing_after_lock.name} found after lock "
                    "(created by concurrent process)"
                )
                return "skipped", existing_after_lock.name

            # Create savepoint for atomic creation
            frappe.db.sql(f"SAVEPOINT {savepoint_name}")

            member = frappe.new_doc("Member")
            self.update_member_fields(member, row_data, import_doc_name, create_volunteer_records)

            member.flags.ignore_validate = False
            member._csv_import = True

            member.insert()

            # IMPORTANT: Release lock BEFORE commit to ensure same connection
            #
            # MySQL advisory locks (GET_LOCK/RELEASE_LOCK) are connection-scoped:
            # - RELEASE_LOCK must be called on the SAME connection that called GET_LOCK
            # - If the connection changes between GET_LOCK and RELEASE_LOCK, the lock
            #   will NOT be released (RELEASE_LOCK returns 0 or NULL)
            #
            # Frappe's frappe.db.commit() typically preserves the connection, but to be
            # defensive against any connection pool behavior or future changes, we
            # release the lock while we're certain we're on the same connection that
            # acquired it. The member.insert() has already written to the DB; the
            # commit() just makes it durable.
            #
            # Sequence: GET_LOCK -> insert -> RELEASE_LOCK -> commit
            # This ensures the lock is released even if commit() somehow fails.
            if lock_acquired:
                self._release_advisory_lock(lock_name, row_num)
                lock_acquired = False  # Mark as released so finally doesn't retry

            frappe.db.commit()

            # Add member to bulk import tracking set
            ensure_bulk_import_members_set().add(member.name)

            return "created", member.name

        except frappe.DuplicateEntryError as e:
            try:
                frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            except Exception:
                pass
            self.logger.warning(f"Row {row_num}: Duplicate member - {str(e)[:100]}")
            return "skipped", None

        except frappe.ValidationError as e:
            try:
                frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            except Exception:
                pass
            self.logger.error(f"Row {row_num}: Validation error - {str(e)[:200]}")
            frappe.log_error(frappe.get_traceback(), f"CSV Import Validation Error Row {row_num}")
            return "failed", None

        except Exception as e:
            try:
                frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            except Exception:
                pass
            self.logger.error(f"Row {row_num}: Creation failed - {str(e)[:200]}")
            frappe.log_error(frappe.get_traceback(), f"CSV Import Error Row {row_num}")
            return "failed", None

        finally:
            # Release lock if still held (e.g., on exception before normal release)
            if lock_acquired:
                self._release_advisory_lock(lock_name, row_num)

    def _set_dues_rate_fields(self, member_doc: Document, row_data: Dict[str, Any]) -> None:
        """Set dues rate related fields on member document."""
        dues_rate = None
        if "dues_rate" in row_data:
            dues_rate = row_data["dues_rate"]
            # Only look up membership type rate if dues_rate is None or empty string
            if dues_rate is None or (isinstance(dues_rate, str) and not dues_rate.strip()):
                membership_type = self._determine_membership_type(row_data)
                try:
                    mt_doc = frappe.get_doc("Membership Type", membership_type)
                    dues_rate = mt_doc.minimum_amount
                    self.logger.info(f"Using membership type '{membership_type}' minimum amount: {dues_rate}")
                except frappe.DoesNotExistError:
                    self.logger.error(f"Membership type '{membership_type}' not found")
                    dues_rate = None

        if dues_rate is not None:
            member_doc.csv_import_custom_fee = dues_rate
            member_doc.csv_import_custom_fee_reason = "MijnRood CSV import"
            member_doc._pending_dues_schedule_data = {
                "dues_rate": dues_rate,
                "payment_period": row_data.get("payment_period"),
                "override_reason": (
                    "Imported from CSV with custom rate"
                    if row_data.get("dues_rate")
                    else "Default membership type rate"
                ),
            }

    def _determine_membership_type(self, row_data: Dict[str, Any]) -> str:
        """Determine membership type for dues lookup."""
        # Default to Regular membership type
        return "Regular"

    def _set_member_since_date(self, member_doc: Document, row_data: Dict[str, Any]) -> None:
        """Set member_since date, preserving oldest date when updating."""
        new_member_since = row_data.get("member_since")
        if new_member_since:
            if member_doc.member_since:
                existing_date = getdate(member_doc.member_since)
                new_date = getdate(new_member_since)
                member_doc.member_since = min(existing_date, new_date)
            else:
                member_doc.member_since = new_member_since
        elif not member_doc.member_since:
            member_doc.member_since = today()

    def _get_termination_reason(self, membership_type: str) -> str:
        """Get termination reason based on membership type."""
        reason_map = {
            "opgezegd": "Resigned",
            "terminated": "Terminated",
            "uitgeschreven": "Unregistered",
            "geroyeerd": "Expelled",
            "expelled": "Expelled",
            "geschorst": "Suspended",
            "overleden": "Deceased",
            "deceased": "Deceased",
        }
        return reason_map.get(membership_type.lower(), "Other")


# Module-level singleton accessor
_service_instance: Optional[MemberImportService] = None


def get_member_import_service() -> MemberImportService:
    """Get singleton instance of MemberImportService.

    Returns:
        MemberImportService: The singleton instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberImportService()
    return _service_instance
