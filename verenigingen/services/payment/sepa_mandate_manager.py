"""
SEPA Mandate Manager Service

Centralized service for SEPA mandate operations, consolidating fragmented logic
from member.py, sepa_mixin.py, and member_utils.py.

This service provides:
- Mandate retrieval and validation
- Mandate creation with reference generation
- Mandate lifecycle management (activation, deactivation)
- Discrepancy detection and resolution

Design Principles:
- Single source of truth for SEPA mandate operations
- Consistent error handling using Result pattern
- Delegates to PaymentValidationService for IBAN/BIC validation
- Type-safe with comprehensive type hints
- Clear separation between business logic and data access

Author: Verenigingen Development Team
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.services.payment.validation_service import ValidationResult, get_payment_validation_service
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


@dataclass
class MandateInfo:
    """Data class for SEPA mandate information"""

    name: str
    mandate_id: str
    status: str
    iban: str
    bic: Optional[str] = None
    account_holder_name: Optional[str] = None
    member: Optional[str] = None
    sign_date: Optional[date] = None
    expiry_date: Optional[date] = None
    is_active: bool = True
    used_for_memberships: bool = True
    used_for_donations: bool = False
    mandate_type: str = "RCUR"  # Recurring mandate by default


class SEPAMandateManager:
    """
    Service for managing SEPA mandates across the application.

    Consolidates mandate operations that were previously scattered across:
    - verenigingen/doctype/member/member.py
    - verenigingen/doctype/member/mixins/sepa_mixin.py
    - verenigingen/doctype/member/member_utils.py
    """

    # Configuration constants
    MAX_MANDATES_PER_MEMBER_PER_DAY = 999  # Maximum sequence number
    MANDATE_SEQUENCE_DIGITS = 3  # Zero-padding for sequence (supports 001-999)
    MANDATE_REFERENCE_RETRIES = 5  # Max retries for deadlock handling

    def __init__(self):
        """Initialize the SEPA Mandate Manager"""
        self.validation_service = get_payment_validation_service()

    @staticmethod
    def _normalize_iban(iban: str) -> str:
        """
        Normalize IBAN for comparison.

        Removes all whitespace, hyphens, and converts to uppercase.
        This is used for comparing IBANs where formatting may differ.

        Args:
            iban: IBAN to normalize

        Returns:
            Normalized IBAN string (no spaces, uppercase)

        Examples:
            >>> SEPAMandateManager._normalize_iban("NL91 ABNA 0417 1643 00")
            'NL91ABNA0417164300'
            >>> SEPAMandateManager._normalize_iban("nl91-abna-0417-1643-00")
            'NL91ABNA0417164300'
        """
        import re

        if not iban:
            return ""
        # Remove all whitespace and hyphens, convert to uppercase
        return re.sub(r"[\s\-]", "", iban).upper()

    # ========== Mandate Retrieval Methods ==========

    def get_active_mandates(self, member: str, iban: Optional[str] = None) -> List[MandateInfo]:
        """
        Get all active SEPA mandates for a member.

        Consolidates:
        - sepa_mixin.py:13 get_active_sepa_mandates()
        - member.py:2699 get_active_sepa_mandate()

        Args:
            member: Member name/ID
            iban: Optional IBAN filter

        Returns:
            List of MandateInfo objects for active mandates

        Examples:
            >>> manager = SEPAMandateManager()
            >>> mandates = manager.get_active_mandates("Assoc-Member-001")
            >>> len(mandates)
            1
            >>> mandates[0].mandate_id
            'M-001-20251014-001'
        """
        try:
            filters = {"member": member, "status": "Active", "is_active": 1}

            if iban:
                # Normalize IBAN for comparison
                filters["iban"] = self._normalize_iban(iban)

            mandate_records = frappe.get_all(
                "SEPA Mandate",
                filters=filters,
                fields=[
                    "name",
                    "mandate_id",
                    "status",
                    "iban",
                    "bic",
                    "account_holder_name",
                    "member",
                    "sign_date",
                    "expiry_date",
                    "is_active",
                    "used_for_memberships",
                    "used_for_donations",
                    "mandate_type",
                ],
                order_by="creation desc",
            )

            return [MandateInfo(**mandate) for mandate in mandate_records]

        except Exception as e:
            # Retrieval failures don't need Error Log documents - use logger
            frappe.logger().error(f"Error getting active mandates for member {member}: {e}")
            return []

    def get_default_mandate(self, member: str) -> Optional[MandateInfo]:
        """
        Get the default (most recent active) SEPA mandate for a member.

        Consolidates:
        - sepa_mixin.py:28 get_default_sepa_mandate()

        Args:
            member: Member name/ID

        Returns:
            MandateInfo for default mandate, or None if no active mandate exists

        Examples:
            >>> manager = SEPAMandateManager()
            >>> mandate = manager.get_default_mandate("Assoc-Member-001")
            >>> mandate.mandate_id if mandate else None
            'M-001-20251014-001'
        """
        mandates = self.get_active_mandates(member)
        return mandates[0] if mandates else None

    def has_active_mandate(self, member: str, purpose: str = "memberships") -> bool:
        """
        Check if member has an active SEPA mandate for a specific purpose.

        Consolidates:
        - sepa_mixin.py:50 has_active_sepa_mandate()

        Args:
            member: Member name/ID
            purpose: "memberships" or "donations"

        Returns:
            True if member has active mandate for the purpose

        Examples:
            >>> manager = SEPAMandateManager()
            >>> manager.has_active_mandate("Assoc-Member-001", "memberships")
            True
        """
        try:
            filters = {"member": member, "status": "Active", "is_active": 1}

            if purpose == "memberships":
                filters["used_for_memberships"] = 1
            elif purpose == "donations":
                filters["used_for_donations"] = 1

            return bool(frappe.db.exists("SEPA Mandate", filters))

        except Exception as e:
            # Retrieval failures don't need Error Log documents - use logger
            frappe.logger().error(f"Error checking mandate existence for member {member}: {e}")
            return False

    # ========== Mandate Validation Methods ==========

    def validate_mandate_creation(
        self, member: str, iban: str, mandate_id: str, allow_duplicate_iban: bool = False
    ) -> ValidationResult:
        """
        Validate mandate creation parameters comprehensively.

        Consolidates:
        - member.py:2582 validate_mandate_creation()

        Args:
            member: Member name/ID
            iban: IBAN for the mandate
            mandate_id: Proposed mandate ID
            allow_duplicate_iban: Whether to allow duplicate IBANs (default: False)

        Returns:
            ValidationResult with validation details

        Examples:
            >>> manager = SEPAMandateManager()
            >>> result = manager.validate_mandate_creation(
            ...     "Assoc-Member-001",
            ...     "NL91ABNA0417164300",
            ...     "M-001-20251014-001"
            ... )
            >>> result.valid
            True
        """
        errors = []

        # Step 1: Validate member exists
        if not frappe.db.exists("Member", member):
            return ValidationResult.failure(_("Member {0} does not exist").format(member))

        # Step 2: Validate IBAN format
        iban_result = self.validation_service.validate_iban_with_context(iban, context="sepa_mandate")
        if not iban_result.valid:
            return iban_result

        # Step 3: Check if mandate ID already exists
        if frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id}):
            return ValidationResult.failure(_("Mandate ID {0} already exists").format(mandate_id))

        # Step 4: Check for existing active mandates with same IBAN
        if not allow_duplicate_iban:
            existing_mandates = self.get_active_mandates(member, iban=iban)
            if existing_mandates:
                existing_ids = [m.mandate_id for m in existing_mandates]
                return ValidationResult.failure(
                    _("An active mandate already exists for this IBAN"),
                    errors=[_("Existing mandate(s): {0}").format(", ".join(existing_ids))],
                )

        return ValidationResult.success(
            _("Mandate creation validation passed"),
            data={"member": member, "iban": iban_result.data["formatted_iban"], "mandate_id": mandate_id},
        )

    def generate_mandate_reference(self, member: str, member_id: Optional[str] = None) -> str:
        """
        Generate a unique mandate reference for a member with atomic sequence allocation.

        Consolidates:
        - sepa_mixin.py:159 _generate_mandate_reference()
        - member.py:2752 (embedded in create_and_link_mandate_enhanced)

        Format: M-{member_id}-{YYYYMMDD}-{sequence}
        Example: M-001-20251014-001

        This method uses database-level locking to prevent race conditions when
        multiple mandate creations happen concurrently.

        Args:
            member: Member name/ID
            member_id: Optional member ID (will be retrieved if not provided)

        Returns:
            Generated mandate reference string

        Raises:
            frappe.ValidationError: If unable to generate unique reference after retries

        Examples:
            >>> manager = SEPAMandateManager()
            >>> ref = manager.generate_mandate_reference("Assoc-Member-001", "001")
            >>> ref.startswith("M-001-")
            True
        """
        # Get member ID if not provided
        if not member_id:
            member_id = frappe.db.get_value("Member", member, "member_id")
            if not member_id:
                # Fallback: use sanitized member name
                member_id = member.replace("Assoc-Member-", "").replace("-", "")

        # Sanitize member_id to prevent SQL injection in LIKE clause
        # Replace SQL wildcards that could be used maliciously
        member_id_safe = str(member_id).replace("%", "\\%").replace("_", "\\_").replace("\\", "\\\\")

        # Format date as YYYYMMDD
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        base_pattern = f"M-{member_id_safe}-{date_str}"

        # Atomic sequence allocation with deadlock retry
        for retry in range(self.MANDATE_REFERENCE_RETRIES):
            try:
                # Use FOR UPDATE to lock rows and prevent concurrent reads
                # This prevents race conditions where two threads get the same sequence
                result = frappe.db.sql(
                    """
                    SELECT mandate_id
                    FROM `tabSEPA Mandate`
                    WHERE mandate_id LIKE %s
                    ORDER BY mandate_id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (f"{base_pattern}-%",),
                    as_dict=1,
                )

                # Calculate next sequence number
                if result and result[0].mandate_id:
                    try:
                        last_seq = int(result[0].mandate_id.split("-")[-1])
                        sequence = last_seq + 1
                    except (ValueError, IndexError):
                        # Malformed mandate_id, start from 1
                        sequence = 1
                else:
                    # No existing mandates for this member today
                    sequence = 1

                # Check sequence limit
                if sequence > self.MAX_MANDATES_PER_MEMBER_PER_DAY:
                    raise frappe.ValidationError(
                        _(
                            "Maximum mandate limit ({0}) exceeded for member {1} on {2}. "
                            "Please contact support."
                        ).format(self.MAX_MANDATES_PER_MEMBER_PER_DAY, member_id, date_str)
                    )

                # Format with zero-padding
                sequence_str = str(sequence).zfill(self.MANDATE_SEQUENCE_DIGITS)
                return f"M-{member_id}-{date_str}-{sequence_str}"

            except frappe.InternalError as e:
                # Database deadlock - retry with exponential backoff
                if "Deadlock" in str(e) and retry < self.MANDATE_REFERENCE_RETRIES - 1:
                    import time

                    wait_time = 0.1 * (2**retry)  # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                    frappe.logger().warning(
                        f"Deadlock generating mandate reference (attempt {retry + 1}/{self.MANDATE_REFERENCE_RETRIES}), "
                        f"retrying in {wait_time:.1f}s"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # Not a deadlock or max retries exceeded
                    frappe.log_error(
                        f"Database error generating mandate reference: {e}", "SEPA Reference Generation"
                    )
                    raise frappe.ValidationError(_("Unable to generate mandate reference. Please try again."))

            except Exception as e:
                frappe.log_error(
                    f"Unexpected error generating mandate reference: {e}", "SEPA Reference Generation"
                )
                raise frappe.ValidationError(_("Unable to generate mandate reference: {0}").format(str(e)))

        # Should never reach here, but just in case
        raise frappe.ValidationError(
            _("Unable to generate unique mandate reference after {0} attempts").format(
                self.MANDATE_REFERENCE_RETRIES
            )
        )

    # ========== Mandate Creation Methods ==========

    def create_mandate(
        self,
        member: str,
        iban: str,
        bic: Optional[str] = None,
        account_holder_name: Optional[str] = None,
        mandate_id: Optional[str] = None,
        sign_date: Optional[date] = None,
        used_for_memberships: bool = True,
        used_for_donations: bool = False,
        mandate_type: str = "RCUR",
        notes: Optional[str] = None,
    ) -> ValidationResult:
        """
        Create a new SEPA mandate with comprehensive validation.

        Consolidates:
        - sepa_mixin.py:105 create_sepa_mandate()
        - sepa_mixin.py:541 create_sepa_mandate_via_service()
        - member_utils.py:639 create_and_link_mandate_enhanced()

        Args:
            member: Member name/ID
            iban: IBAN for the mandate
            bic: Optional BIC (will be auto-derived for Dutch IBANs)
            account_holder_name: Optional account holder name
            mandate_id: Optional custom mandate ID (generated if not provided)
            sign_date: Mandate sign date (defaults to today)
            used_for_memberships: Whether mandate is used for membership payments
            used_for_donations: Whether mandate is used for donation payments
            mandate_type: Mandate type (RCUR for recurring, OOFF for one-off)
            notes: Optional notes for the mandate

        Returns:
            ValidationResult with created mandate info in data

        Examples:
            >>> manager = SEPAMandateManager()
            >>> result = manager.create_mandate(
            ...     "Assoc-Member-001",
            ...     "NL91ABNA0417164300",
            ...     account_holder_name="John Doe"
            ... )
            >>> result.valid
            True
            >>> result.data["mandate_id"]
            'M-001-20251014-001'
        """
        try:
            # Step 1: Validate bank details (includes IBAN validation and BIC derivation)
            bank_validation = self.validation_service.validate_bank_details(
                iban=iban,
                bic=bic,
                account_holder_name=account_holder_name,
                auto_derive_bic=True,
                require_bic=False,
            )

            if not bank_validation.valid:
                return bank_validation

            # Extract validated/derived values
            validated_iban = bank_validation.data["formatted_iban"]
            validated_bic = bank_validation.data.get("bic")
            validated_holder = bank_validation.data.get("account_holder_name", account_holder_name)

            # Step 2: Generate mandate reference if not provided
            if not mandate_id:
                mandate_id = self.generate_mandate_reference(member)

            # Step 3: Validate mandate creation
            validation_result = self.validate_mandate_creation(member, validated_iban, mandate_id)
            if not validation_result.valid:
                return validation_result

            # Step 4: Get member details for prefilling
            member_doc = frappe.get_doc("Member", member)

            # Use member's full name if account holder name not provided
            if not validated_holder:
                validated_holder = member_doc.full_name

            # Step 5: Create the SEPA Mandate document
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.member = member
            mandate.member_name = member_doc.full_name
            mandate.mandate_id = mandate_id
            mandate.iban = validated_iban
            mandate.bic = validated_bic
            mandate.account_holder_name = validated_holder
            mandate.sign_date = sign_date or today()
            mandate.used_for_memberships = used_for_memberships
            mandate.used_for_donations = used_for_donations
            mandate.mandate_type = mandate_type
            mandate.status = "Draft"  # Start as Draft, must be activated separately
            mandate.is_active = 0
            mandate.notes = notes or f"Created via SEPAMandateManager for member {member} on {today()}"

            # Save using secure operations
            mandate_result = secure_document_operation(
                operation="insert",
                doc=mandate,
                justification=f"Create SEPA mandate {mandate_id} for member {member}",
                required_permissions=["SEPA Mandate:create"],
            )

            if not mandate_result.success:
                return ValidationResult.failure(
                    _("Failed to create SEPA mandate"), errors=mandate_result.errors
                )

            # Step 6: Link mandate to member's sepa_mandates child table
            self._link_mandate_to_member(member_doc, mandate)

            return ValidationResult.success(
                _("SEPA mandate {0} created successfully").format(mandate_id),
                data={
                    "mandate_name": mandate.name,
                    "mandate_id": mandate_id,
                    "iban": validated_iban,
                    "bic": validated_bic,
                    "status": mandate.status,
                },
            )

        except Exception as e:
            frappe.log_error(f"Error creating SEPA mandate for member {member}: {e}", "SEPA Mandate Creation")
            return ValidationResult.failure(_("Error creating SEPA mandate: {0}").format(str(e)))

    def _link_mandate_to_member(self, member_doc, mandate_doc):
        """
        Link a mandate to the member's sepa_mandates child table with retry logic.

        Uses exponential backoff retry to handle concurrent modifications that cause
        timestamp mismatch errors. This ensures mandate linking succeeds even under
        high-concurrency scenarios.

        Args:
            member_doc: Member document object
            mandate_doc: SEPA Mandate document object

        Raises:
            frappe.ValidationError: If unable to link after all retries
        """
        MAX_RETRIES = 3

        for attempt in range(MAX_RETRIES):
            try:
                # Always get fresh copy to avoid stale data
                member = frappe.get_doc("Member", member_doc.name)

                # Check if already linked (idempotency)
                existing = [m for m in member.sepa_mandates if m.sepa_mandate == mandate_doc.name]
                if existing:
                    frappe.logger().info(f"Mandate {mandate_doc.name} already linked to member {member.name}")
                    return

                member.append(
                    "sepa_mandates",
                    {
                        "sepa_mandate": mandate_doc.name,
                        "mandate_reference": mandate_doc.mandate_id,
                        "status": mandate_doc.status,
                        "is_current": 0,  # Will be set to 1 when mandate is activated
                        "valid_from": mandate_doc.sign_date,
                        "valid_until": mandate_doc.expiry_date
                        if hasattr(mandate_doc, "expiry_date")
                        else None,
                    },
                )

                # Save member with secure operations
                member_result = secure_document_operation(
                    operation="save",
                    doc=member,
                    justification=f"Link SEPA mandate {mandate_doc.mandate_id} to member {member.name}",
                    required_permissions=["Member:write"],
                )

                if not member_result.success:
                    raise frappe.ValidationError(f"Failed to link mandate: {'; '.join(member_result.errors)}")

                # Success - exit retry loop
                return

            except frappe.TimestampMismatchError as e:
                if attempt < MAX_RETRIES - 1:
                    frappe.logger().warning(
                        f"Timestamp mismatch on attempt {attempt + 1}, "
                        f"retrying member link for {member_doc.name}"
                    )
                    # Brief exponential backoff
                    import time

                    time.sleep(0.1 * (2**attempt))  # 0.1s, 0.2s, 0.4s
                    continue
                else:
                    # Final attempt failed
                    frappe.logger().error(f"Failed to link mandate after {MAX_RETRIES} attempts: {e}")
                    raise frappe.ValidationError(
                        _(
                            "Unable to link mandate to member due to concurrent modifications. "
                            "Please try again."
                        )
                    )

            except Exception as e:
                frappe.logger().error(f"Error linking mandate to member {member_doc.name}: {e}")
                raise

    # ========== Mandate Lifecycle Methods ==========

    def deactivate_mandates_for_iban_change(self, member: str, new_iban: str) -> ValidationResult:
        """
        Deactivate old SEPA mandates when member's IBAN changes.

        Consolidates:
        - member.py:2639 deactivate_old_sepa_mandates()

        Args:
            member: Member name/ID
            new_iban: New IBAN (mandates with different IBANs will be deactivated)

        Returns:
            ValidationResult with deactivation details

        Examples:
            >>> manager = SEPAMandateManager()
            >>> result = manager.deactivate_mandates_for_iban_change(
            ...     "Assoc-Member-001",
            ...     "NL91ABNA0417164300"
            ... )
            >>> result.valid
            True
            >>> result.data["deactivated_count"]
            2
        """
        try:
            # Normalize new IBAN for comparison
            new_iban_normalized = self._normalize_iban(new_iban)

            # Get all active mandates
            active_mandates = self.get_active_mandates(member)

            deactivated_count = 0
            deactivated_mandates = []

            for mandate_info in active_mandates:
                # Only deactivate mandates with different IBAN
                mandate_iban_normalized = self._normalize_iban(mandate_info.iban)

                if mandate_iban_normalized != new_iban_normalized:
                    mandate_doc = frappe.get_doc("SEPA Mandate", mandate_info.name)

                    # Deactivate the mandate
                    # Note: Field name is 'cancelled_date' not 'cancellation_date' per DocType schema
                    mandate_doc.status = "Cancelled"
                    mandate_doc.is_active = 0
                    mandate_doc.cancelled_date = today()
                    mandate_doc.cancellation_reason = (
                        f"IBAN changed from {mandate_info.iban} to {new_iban} on {today()}"
                    )

                    # Save with audit trail using secure operations
                    deactivation_result = secure_document_operation(
                        operation="save",
                        doc=mandate_doc,
                        justification=f"Deactivate SEPA mandate {mandate_info.mandate_id} due to IBAN change for member {member}",
                        required_permissions=["SEPA Mandate:write"],
                    )

                    if not deactivation_result.success:
                        frappe.logger().error(
                            f"Failed to deactivate mandate {mandate_info.mandate_id}: {'; '.join(deactivation_result.errors)}"
                        )
                        continue  # Skip this mandate and continue with others

                    deactivated_count += 1
                    deactivated_mandates.append(
                        {"mandate_id": mandate_info.mandate_id, "old_iban": mandate_info.iban}
                    )

                    frappe.logger().info(
                        f"Deactivated SEPA mandate {mandate_info.mandate_id} for member {member} due to IBAN change"
                    )

            return ValidationResult.success(
                _("Deactivated {0} mandate(s) due to IBAN change").format(deactivated_count),
                data={"deactivated_count": deactivated_count, "deactivated_mandates": deactivated_mandates},
            )

        except Exception as e:
            frappe.log_error(
                f"Error deactivating mandates for member {member}: {e}", "SEPA Mandate Deactivation"
            )
            return ValidationResult.failure(_("Error deactivating mandates: {0}").format(str(e)))


# ========== Service Factory ==========


def get_sepa_mandate_manager() -> SEPAMandateManager:
    """
    Get SEPAMandateManager instance (singleton pattern).

    Returns:
        SEPAMandateManager instance

    Examples:
        >>> manager = get_sepa_mandate_manager()
        >>> mandates = manager.get_active_mandates("Assoc-Member-001")
    """
    return SEPAMandateManager()


# ========== Whitelisted API Endpoints ==========


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_active_mandates_api(member: str, iban: Optional[str] = None) -> Dict[str, Any]:
    """
    API endpoint to get active SEPA mandates for a member.

    Args:
        member: Member name/ID
        iban: Optional IBAN filter

    Returns:
        dict with mandate list

    Examples:
        >>> result = get_active_mandates_api("Assoc-Member-001")
        >>> len(result["mandates"])
        1
    """
    manager = get_sepa_mandate_manager()
    mandates = manager.get_active_mandates(member, iban)

    # Convert MandateInfo objects to dicts for JSON serialization
    mandate_dicts = [
        {
            "name": m.name,
            "mandate_id": m.mandate_id,
            "status": m.status,
            "iban": m.iban,
            "bic": m.bic,
            "account_holder_name": m.account_holder_name,
            "sign_date": m.sign_date,
            "is_active": m.is_active,
        }
        for m in mandates
    ]

    return {"mandates": mandate_dicts, "count": len(mandate_dicts)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def validate_mandate_creation_api(member: str, iban: str, mandate_id: str) -> Dict[str, Any]:
    """
    API endpoint to validate mandate creation parameters.

    Args:
        member: Member name/ID
        iban: IBAN for the mandate
        mandate_id: Proposed mandate ID

    Returns:
        dict with validation result
    """
    manager = get_sepa_mandate_manager()
    result = manager.validate_mandate_creation(member, iban, mandate_id)

    return {"valid": result.valid, "message": result.message, "errors": result.errors, "data": result.data}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_mandate_api(
    member: str,
    iban: str,
    bic: Optional[str] = None,
    account_holder_name: Optional[str] = None,
    mandate_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    API endpoint to create a new SEPA mandate.

    Args:
        member: Member name/ID
        iban: IBAN for the mandate
        bic: Optional BIC code
        account_holder_name: Optional account holder name
        mandate_id: Optional custom mandate ID

    Returns:
        dict with creation result
    """
    manager = get_sepa_mandate_manager()
    result = manager.create_mandate(
        member=member, iban=iban, bic=bic, account_holder_name=account_holder_name, mandate_id=mandate_id
    )

    return {"success": result.valid, "message": result.message, "errors": result.errors, "data": result.data}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def deactivate_mandates_for_iban_change_api(member: str, new_iban: str) -> Dict[str, Any]:
    """
    API endpoint to deactivate old mandates when IBAN changes.

    Args:
        member: Member name/ID
        new_iban: New IBAN

    Returns:
        dict with deactivation result
    """
    manager = get_sepa_mandate_manager()
    result = manager.deactivate_mandates_for_iban_change(member, new_iban)

    return {"success": result.valid, "message": result.message, "errors": result.errors, "data": result.data}
