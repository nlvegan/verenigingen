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

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
API endpoints return OperationResult[Dict] with type-safe error handling.
Never throw exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- validate_mandate_creation_api: Returns OperationResult[Dict] (validation results)
- create_mandate_api: Returns OperationResult[Dict] (mandate creation results)
- deactivate_mandates_for_iban_change_api: Returns OperationResult[Dict] (deactivation results)

Migration Status: ✅ COMPLETE (2025-11-24)
- All 3 critical API endpoints migrated from dict-based to OperationResult pattern
- FINANCIAL operation classification preserved
- Type-safe error handling with comprehensive mandate metadata

See: docs/patterns/OPERATION_RESULT_PATTERN.md

Author: Verenigingen Development Team
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.payment.validation_service import ValidationResult, get_payment_validation_service
from verenigingen.utils.operation_result import OperationResult
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
    # Third purpose checkbox on SEPA Mandate. Present so that every value in
    # `mandate_candidates.PURPOSE_FLAGS` can be filtered on a MandateInfo -- without
    # it, `get_default_mandate(purpose="used_for_other")` silently matched nothing.
    used_for_other: bool = False
    mandate_type: str = "RCUR"  # Recurring mandate by default


class SEPAMandateManager(StatelessService):
    """
    Service for managing SEPA mandates across the application.

    Inherits from StatelessService for consistent logging, metrics, and error handling.
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
        super().__init__(service_name="SEPAMandateManager")
        self.validation_service = get_payment_validation_service()

    def _normalize_iban(self, iban: str) -> str:
        """
        Normalize IBAN for comparison.

        Removes all whitespace, hyphens, and converts to uppercase.
        This is used for comparing IBANs where formatting may differ.

        Args:
            iban: IBAN to normalize

        Returns:
            Normalized IBAN string (no spaces, uppercase)

        Examples:
            >>> SEPAMandateManager()._normalize_iban("NL91 ABNA 0417 1643 00")
            'NL91ABNA0417164300'
            >>> SEPAMandateManager()._normalize_iban("nl91-abna-0417-1643-00")
            'NL91ABNA0417164300'
        """
        import re

        if not iban:
            return ""
        # Remove all whitespace and hyphens, convert to uppercase
        return re.sub(r"[\s\-]", "", iban).upper()

    # ========== Mandate Retrieval Methods ==========

    def get_active_mandates(
        self, member: str, iban: Optional[str] = None, purpose: Optional[str] = None
    ) -> List[MandateInfo]:
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
        # Resolved OUTSIDE the try below, which returns [] on any exception.
        # `resolve_purpose_flag` raises on an unknown purpose precisely so a typo
        # cannot silently degrade to purpose-blind resolution; swallowed into an
        # empty list it would do worse than that, since callers read [] as "no
        # mandate" and go on to create or allow one.
        #
        # `purpose` is opt-in: this method's job is "every Active mandate of this
        # member", which the discrepancy check and the payment dashboard
        # legitimately want. Callers deciding something about ONE purpose pass it,
        # rather than taking [0] of an unscoped list (#605).
        from verenigingen.verenigingen_payments.utils.mandate_candidates import resolve_purpose_flag

        purpose_flag = resolve_purpose_flag(purpose)

        try:
            filters = {"member": member, "status": "Active", "is_active": 1}

            if purpose_flag is not None:
                filters[purpose_flag] = 1

            if iban:
                # Format IBAN to match database storage (IBANs are stored formatted with spaces)
                from verenigingen.utils.validation.iban_validator import format_iban

                filters["iban"] = format_iban(iban) or iban

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
                    "used_for_other",
                    "mandate_type",
                ],
                order_by="creation desc",
            )

            return [MandateInfo(**mandate) for mandate in mandate_records]

        except Exception as e:
            # Retrieval failures don't need Error Log documents - use logger
            self.logger.error(f"Error getting active mandates for member {member}: {e}")
            return []

    def get_default_mandate(
        self, member: str, purpose: str = "used_for_memberships"
    ) -> Optional[MandateInfo]:
        """
        Get the member's single Active SEPA mandate FOR A PURPOSE, or None.

        Consolidates:
        - sepa_mixin.py:28 get_default_sepa_mandate()

        This used to return ``mandates[0]`` from a list ordered ``creation desc``
        with no purpose filter, i.e. "whichever Active mandate was created last"
        (#597). That is not a default, it is a tiebreak with money behind it:
        `SEPAMandate.validate_single_active_mandate_per_purpose` permits a member
        to hold an Active membership mandate AND an Active donation mandate at
        once, so the newer donation-only mandate won for every caller asking about
        memberships.

        The divergence was already documented and worked around locally rather than
        fixed here -- `payment_history_service._get_default_mandate` queries with
        `used_for_memberships = 1` itself and explains in its docstring that this
        helper "picks the single most-recently-created ACTIVE mandate with NO
        purpose filter at all". `financial_mixin.get_financial_summary` shows the
        cost of that: it gates on `has_active_sepa_mandate()`, which IS
        memberships-scoped, and then reported this mandate's `mandate_id`, `status`
        and `expiry_date` -- the donation mandate's, labelled as the membership one.

        More than one Active mandate WITHIN a purpose is refused rather than
        ordered, and logged with its candidates, matching
        `mandate_candidates.unambiguous_active_mandate`. Both consumers of this
        value (`financial_mixin`, `payment_mixin`) only display or warn, so None is
        safe for them; a caller that would CREATE the missing mandate must
        distinguish the two, and should use `unambiguous_active_mandate` instead --
        it carries the refusal as its own state.

        Args:
            member: Member name/ID
            purpose: One of PURPOSE_FLAGS, or None to ask "any Active mandate",
                which is almost never what a collection wants.

        Returns:
            MandateInfo for the one mandate serving `purpose`, or None if there is
            none -- or if there is more than one and choosing would be a guess.

        Examples:
            >>> manager = SEPAMandateManager()
            >>> mandate = manager.get_default_mandate("Assoc-Member-001")
            >>> mandate.mandate_id if mandate else None
            'M-001-20251014-001'
        """
        from verenigingen.verenigingen_payments.utils.mandate_candidates import (
            log_ambiguous_mandate_refusal,
            resolve_purpose_flag,
        )

        purpose = resolve_purpose_flag(purpose)
        mandates = self.get_active_mandates(member)
        if purpose is not None:
            mandates = [m for m in mandates if getattr(m, purpose, 0)]

        if not mandates:
            return None
        if len(mandates) > 1:
            log_ambiguous_mandate_refusal(member, mandates, purpose, "Ambiguous default SEPA mandate")
            return None
        return mandates[0]

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
        from verenigingen.verenigingen_payments.utils.mandate_candidates import (
            resolve_purpose_flag,
        )

        # Raises on an unknown purpose rather than applying NO filter. The old
        # if/elif fell through silently, so `has_active_mandate(m, "other")` and
        # `has_active_mandate(m, "used_for_memberships")` -- the OTHER vocabulary
        # used by every resolver in this class -- both answered "does this member
        # have ANY Active mandate", which is the question this method exists not to
        # ask. `resolve_purpose_flag` accepts both spellings (#597).
        purpose_flag = resolve_purpose_flag(purpose)

        try:
            filters = {"member": member, "status": "Active", "is_active": 1}
            if purpose_flag is not None:
                filters[purpose_flag] = 1

            return bool(frappe.db.exists("SEPA Mandate", filters))

        except Exception as e:
            # Retrieval failures don't need Error Log documents - use logger
            self.logger.error(f"Error checking mandate existence for member {member}: {e}")
            return False

    # ========== Mandate Validation Methods ==========

    def validate_mandate_creation(
        self,
        member: str,
        iban: str,
        mandate_id: str,
        allow_duplicate_iban: bool = False,
        purposes=("used_for_memberships",),
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
            purposes: The purposes the NEW mandate will serve. Only an existing
                Active mandate overlapping them counts as a duplicate: a member
                may hold one Active mandate PER PURPOSE (#584), and paying dues
                and donating from the same account is the ordinary case, not a
                clash. Pass None to treat any Active mandate on the IBAN as a
                duplicate.

                The default is memberships because that is what every caller of
                THIS method is creating -- `create_mandate` passes the flags it is
                about to set, and the two API wrappers create membership mandates.
                It is not a claim about the app as a whole: `create_mandate` and
                `create_and_link_mandate_enhanced` both accept donation-only
                arguments, and `payment_gateways._create_sepa_mandate` builds a
                donation mandate without coming through here at all (#605).

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
        from verenigingen.verenigingen_payments.utils.mandate_candidates import (
            resolve_purpose_flag,
        )

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
            if purposes:
                wanted = [resolve_purpose_flag(p) for p in purposes]
                existing_mandates = [
                    m for m in existing_mandates if any(getattr(m, flag, 0) for flag in wanted)
                ]
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
                    self.logger.warning(
                        f"Deadlock generating mandate reference (attempt {retry + 1}/{self.MANDATE_REFERENCE_RETRIES}), "
                        f"retrying in {wait_time:.1f}s"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # Not a deadlock or max retries exceeded
                    self.logger.error(f"Database error generating mandate reference: {e}")
                    raise frappe.ValidationError(_("Unable to generate mandate reference. Please try again."))

            except Exception as e:
                self.logger.error(f"Unexpected error generating mandate reference: {e}")
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
        allow_duplicate_iban: bool = False,
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
            validation_result = self.validate_mandate_creation(
                member,
                validated_iban,
                mandate_id,
                allow_duplicate_iban=allow_duplicate_iban,
                # The purposes THIS mandate will carry (set at Step 5 below), so a
                # member's donation mandate does not block their membership one.
                purposes=[
                    flag
                    for flag, on in (
                        ("used_for_memberships", used_for_memberships),
                        ("used_for_donations", used_for_donations),
                    )
                    if on
                ]
                or None,
            )
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
            self.logger.error(f"Error creating SEPA mandate for member {member}: {e}")
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
                    self.logger.info(f"Mandate {mandate_doc.name} already linked to member {member.name}")
                    return

                member.append(
                    "sepa_mandates",
                    {
                        "sepa_mandate": mandate_doc.name,
                        "mandate_reference": mandate_doc.mandate_id,
                        "status": mandate_doc.status,
                        "is_current": 0,  # Will be set to 1 when mandate is activated
                        "valid_from": mandate_doc.sign_date,
                        "valid_until": (
                            mandate_doc.expiry_date if hasattr(mandate_doc, "expiry_date") else None
                        ),
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
                    self.logger.warning(
                        f"Timestamp mismatch on attempt {attempt + 1}, "
                        f"retrying member link for {member_doc.name}"
                    )
                    # Brief exponential backoff
                    import time

                    time.sleep(0.1 * (2**attempt))  # 0.1s, 0.2s, 0.4s
                    continue
                else:
                    # Final attempt failed
                    self.logger.error(f"Failed to link mandate after {MAX_RETRIES} attempts: {e}")
                    raise frappe.ValidationError(
                        _(
                            "Unable to link mandate to member due to concurrent modifications. "
                            "Please try again."
                        )
                    )

            except Exception as e:
                self.logger.error(f"Error linking mandate to member {member_doc.name}: {e}")
                raise

    # ========== Member Mandate Sync Methods ==========

    def sync_member_mandates(self, member: str) -> ValidationResult:
        """
        Sync member's sepa_mandates child table with actual SEPA Mandate documents.

        Consolidates:
        - sepa_mixin.py:96 refresh_sepa_mandates_table()

        This method rebuilds the member's sepa_mandates child table from the
        actual SEPA Mandate documents, ensuring consistency.

        Args:
            member: Member name/ID

        Returns:
            ValidationResult with sync statistics

        Examples:
            >>> manager = SEPAMandateManager()
            >>> result = manager.sync_member_mandates("Assoc-Member-001")
            >>> result.valid
            True
            >>> result.data["mandates_count"]
            2
        """
        try:
            # Get all SEPA mandates for this member
            mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": member},
                fields=["name", "mandate_id", "status", "is_active", "sign_date", "expiry_date"],
                order_by="creation desc",
            )

            # Get member document
            member_doc = frappe.get_doc("Member", member)

            # Clear existing links
            member_doc.sepa_mandates = []

            # Rebuild the child table from actual mandates
            for mandate in mandates:
                member_doc.append(
                    "sepa_mandates",
                    {
                        "sepa_mandate": mandate.name,
                        "mandate_reference": mandate.mandate_id,
                        "status": mandate.status,
                        "is_current": 1 if mandate.status == "Active" and mandate.is_active else 0,
                        "valid_from": mandate.sign_date,
                        "valid_until": mandate.expiry_date,
                    },
                )

            # Save using native update_child_table to avoid timestamp conflicts
            member_doc.update_child_table("sepa_mandates")
            frappe.db.commit()

            self.logger.info(f"Synced {len(mandates)} SEPA mandate(s) for member {member}")

            return ValidationResult.success(
                _("Refreshed {0} SEPA mandate(s)").format(len(mandates)),
                data={"mandates_count": len(mandates), "member": member},
            )

        except Exception as e:
            self.logger.error(f"Error syncing SEPA mandates for member {member}: {e}")
            return ValidationResult.failure(_("Error syncing SEPA mandates: {0}").format(str(e)))

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
                        self.logger.error(
                            f"Failed to deactivate mandate {mandate_info.mandate_id}: {'; '.join(deactivation_result.errors)}"
                        )
                        continue  # Skip this mandate and continue with others

                    deactivated_count += 1
                    deactivated_mandates.append(
                        {"mandate_id": mandate_info.mandate_id, "old_iban": mandate_info.iban}
                    )

                    self.logger.info(
                        f"Deactivated SEPA mandate {mandate_info.mandate_id} for member {member} due to IBAN change"
                    )

            return ValidationResult.success(
                _("Deactivated {0} mandate(s) due to IBAN change").format(deactivated_count),
                data={"deactivated_count": deactivated_count, "deactivated_mandates": deactivated_mandates},
            )

        except Exception as e:
            self.logger.error(f"Error deactivating mandates for member {member}: {e}")
            return ValidationResult.failure(_("Error deactivating mandates: {0}").format(str(e)))

    # ========== Discrepancy Detection Methods ==========

    def check_discrepancies(self) -> Dict[str, Any]:
        """
        Check for SEPA mandate discrepancies across all members with SEPA Direct Debit.

        Consolidates:
        - sepa_mixin.py:200 check_sepa_mandate_discrepancies()

        This is typically called as a scheduled task to detect and optionally
        auto-fix mandate issues like IBAN mismatches or missing mandates.

        Returns:
            Dict with discrepancy check results including:
            - total_checked: Number of members checked
            - missing_mandates: Members with SEPA but no active mandate
            - iban_mismatches: Mandates where IBAN differs from member's IBAN
            - name_mismatches: Mandates where account name differs
            - auto_fixed: Issues automatically resolved
            - errors: Processing errors

        Examples:
            >>> manager = SEPAMandateManager()
            >>> results = manager.check_discrepancies()
            >>> results["total_checked"]
            150
        """
        import time

        from verenigingen.utils.settings_utils import get_payments_settings

        start_time = time.time()

        self.logger.info("Starting scheduled SEPA mandate discrepancy check")

        try:
            # First check company SEPA settings
            company_settings_status = self._check_company_sepa_settings()
            if company_settings_status:
                self.logger.warning(f"SEPA Settings Issue: {company_settings_status}")

            # Find members with SEPA Direct Debit payment method
            members_with_direct_debit = frappe.get_all(
                "Member",
                filters={"payment_method": "SEPA Direct Debit", "docstatus": ["!=", 2]},
                fields=["name", "full_name", "iban", "bic", "bank_account_name"],
            )

            results = {
                "total_checked": len(members_with_direct_debit),
                "missing_mandates": [],
                "iban_mismatches": [],
                "name_mismatches": [],
                "auto_fixed": [],
                "manual_review_needed": [],
                "errors": [],
            }

            for member_data in members_with_direct_debit:
                try:
                    self._check_member_mandate_discrepancies(member_data, results)
                except Exception as e:
                    results["errors"].append(
                        {"member": member_data.name, "error": str(e), "action": "member_processing_failed"}
                    )

            # Log results
            end_time = time.time()
            processing_time = round(end_time - start_time, 2)

            self.logger.info(f"SEPA mandate discrepancy check completed in {processing_time}s")
            self.logger.info(
                f"Results: {results['total_checked']} checked, "
                f"{len(results['missing_mandates'])} missing mandates, "
                f"{len(results['iban_mismatches'])} IBAN mismatches, "
                f"{len(results['name_mismatches'])} name mismatches, "
                f"{len(results['auto_fixed'])} auto-fixed, "
                f"{len(results['errors'])} errors"
            )

            # Create a log entry for significant issues
            self._create_discrepancy_log(results)

            return results

        except Exception as e:
            self.logger.error(f"Error in scheduled SEPA mandate discrepancy check: {e}")
            return {"error": str(e)}

    def _check_member_mandate_discrepancies(self, member_data: Dict, results: Dict) -> None:
        """Check a single member for mandate discrepancies."""
        member_name = member_data.name
        member_iban = member_data.iban
        member_account_name = member_data.bank_account_name

        # Skip if no IBAN set
        if not member_iban:
            return

        # Every Active mandate: the IBAN/name comparison below is about whichever
        # accounts the member has registered, whatever each is used for.
        active_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member_name, "status": "Active", "is_active": 1},
            fields=["name", "mandate_id", "iban", "account_holder_name", "used_for_memberships"],
        )

        # "Missing", though, is a per-purpose question, and this bucket names the
        # members an operator then goes and creates a mandate for -- the same
        # population `members_without_payment_info` reports and
        # `create_missing_sepa_mandates` acts on, both membership-scoped (#605).
        # Unscoped, a member holding only a donation mandate was reported as an
        # IBAN mismatch rather than as missing the mandate their dues need.
        if not any(m.used_for_memberships for m in active_mandates):
            results["missing_mandates"].append(
                {"member": member_name, "member_name": member_data.full_name, "iban": member_iban}
            )

        if not active_mandates:
            return

        # Check for discrepancies with existing mandates
        for mandate in active_mandates:
            mandate_iban = self._normalize_iban(mandate.iban)
            current_iban = self._normalize_iban(member_iban)

            # Check IBAN mismatch
            if mandate_iban != current_iban:
                discrepancy = {
                    "member": member_name,
                    "member_name": member_data.full_name,
                    "mandate_id": mandate.mandate_id,
                    "mandate_iban": mandate.iban,
                    "current_iban": member_iban,
                }

                # Auto-fix: Deactivate old mandate if IBAN changed significantly
                if self._should_auto_fix_iban_change(mandate_iban, current_iban):
                    try:
                        self._deactivate_mandate_for_iban_change(mandate.name, mandate.iban, member_iban)
                        results["auto_fixed"].append(
                            {**discrepancy, "action": "deactivated_old_mandate", "reason": "IBAN changed"}
                        )
                    except Exception as e:
                        results["errors"].append(
                            {**discrepancy, "error": str(e), "action": "failed_to_deactivate"}
                        )
                else:
                    results["iban_mismatches"].append(discrepancy)

            # Check account holder name mismatch
            if member_account_name and mandate.account_holder_name:
                if self._names_significantly_different(member_account_name, mandate.account_holder_name):
                    discrepancy = {
                        "member": member_name,
                        "member_name": member_data.full_name,
                        "mandate_id": mandate.mandate_id,
                        "mandate_name": mandate.account_holder_name,
                        "current_name": member_account_name,
                    }

                    # Auto-fix: Update mandate name if it's a minor difference
                    if self._should_auto_fix_name_change(mandate.account_holder_name, member_account_name):
                        try:
                            self._update_mandate_account_name(mandate.name, member_account_name)
                            results["auto_fixed"].append(
                                {
                                    **discrepancy,
                                    "action": "updated_account_name",
                                    "reason": "minor_name_difference",
                                }
                            )
                        except Exception as e:
                            results["errors"].append(
                                {**discrepancy, "error": str(e), "action": "failed_to_update_name"}
                            )
                    else:
                        results["name_mismatches"].append(discrepancy)

    def _should_auto_fix_iban_change(self, old_iban: str, new_iban: str) -> bool:
        """Determine if IBAN change should be auto-fixed."""
        if not old_iban or not new_iban:
            return False

        # Don't auto-fix if IBANs are too similar (might be typo)
        if self._strings_too_similar(old_iban, new_iban):
            return False

        return True

    def _should_auto_fix_name_change(self, old_name: str, new_name: str) -> bool:
        """Determine if account name change should be auto-fixed."""
        if not old_name or not new_name:
            return False

        # Auto-fix if names are very similar (minor differences)
        return self._names_slightly_different(old_name, new_name)

    def _names_significantly_different(self, name1: str, name2: str) -> bool:
        """Check if two names are significantly different."""
        if not name1 or not name2:
            return True

        # Normalize names for comparison
        name1_norm = name1.lower().strip()
        name2_norm = name2.lower().strip()

        # If exact match, not different
        if name1_norm == name2_norm:
            return False

        # Check if one name contains the other
        if name1_norm in name2_norm or name2_norm in name1_norm:
            return False

        # Use simple word overlap check
        words1 = set(name1_norm.split())
        words2 = set(name2_norm.split())

        # If more than 50% word overlap, consider similar
        overlap = len(words1.intersection(words2))
        min_words = min(len(words1), len(words2))

        if min_words > 0 and (overlap / min_words) > 0.5:
            return False

        return True

    def _names_slightly_different(self, name1: str, name2: str) -> bool:
        """Check if two names are only slightly different (for auto-fix)."""
        if not name1 or not name2:
            return False

        import re

        # Normalize names
        name1_norm = name1.lower().strip()
        name2_norm = name2.lower().strip()

        # Check if difference is minimal (like punctuation, spacing, case)
        name1_clean = re.sub(r"[^\w\s]", "", name1_norm)
        name2_clean = re.sub(r"[^\w\s]", "", name2_norm)

        # Remove extra spaces
        name1_clean = " ".join(name1_clean.split())
        name2_clean = " ".join(name2_clean.split())

        return name1_clean == name2_clean

    def _strings_too_similar(self, str1: str, str2: str) -> bool:
        """Check if two strings are suspiciously similar (might indicate typo)."""
        if not str1 or not str2:
            return False

        # Simple character difference check
        if len(str1) == len(str2):
            differences = sum(c1 != c2 for c1, c2 in zip(str1, str2))
            return differences <= 2  # 2 or fewer character differences

        return False

    def _deactivate_mandate_for_iban_change(self, mandate_name: str, old_iban: str, new_iban: str) -> None:
        """Deactivate a mandate due to IBAN change."""
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        mandate.status = "Cancelled"
        mandate.is_active = 0
        mandate.cancelled_date = today()
        mandate.cancellation_reason = f"IBAN changed from {old_iban} to {new_iban} (auto-deactivated)"
        mandate.save()

        self.logger.info(f"Auto-deactivated SEPA mandate {mandate.mandate_id} due to IBAN change")

    def _update_mandate_account_name(self, mandate_name: str, new_account_name: str) -> None:
        """Update mandate account holder name."""
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        old_name = mandate.account_holder_name
        mandate.account_holder_name = new_account_name
        mandate.save()

        self.logger.info(
            f"Auto-updated SEPA mandate {mandate.mandate_id} account name from '{old_name}' to '{new_account_name}'"
        )

    def _check_company_sepa_settings(self) -> str:
        """Check if company SEPA settings are configured."""
        try:
            from verenigingen.utils.settings_utils import get_payments_settings

            payments_settings = get_payments_settings()
            general_settings = frappe.get_single("Verenigingen Settings")
            missing_settings = []

            # Check required SEPA settings (from Payments Settings)
            if not getattr(payments_settings, "company_iban", None):
                missing_settings.append("Company IBAN")
            if not getattr(payments_settings, "company_account_holder", None):
                missing_settings.append("Bank Account Holder Name")
            if not getattr(payments_settings, "creditor_id", None):
                missing_settings.append("SEPA Creditor ID (Incassant ID)")
            if not getattr(general_settings, "company_name", None):
                missing_settings.append("Company Name")

            if missing_settings:
                settings_list = "\n".join(f"- {setting}" for setting in missing_settings)
                return f"""
WARNING: Missing Company SEPA Settings!
The following settings are required for SEPA processing but are not configured:
{settings_list}

Please configure these in Verenigingen Payments Settings before processing SEPA mandates.
"""
            return ""
        except Exception as e:
            return f"\nWARNING: Could not check company SEPA settings: {str(e)}\n"

    def _create_discrepancy_log(self, results: Dict) -> None:
        """Create a log entry for discrepancies that need manual review."""
        significant_issues = (
            len(results.get("missing_mandates", []))
            + len(results.get("iban_mismatches", []))
            + len(results.get("name_mismatches", []))
            + len(results.get("errors", []))
        )

        if significant_issues > 0:
            company_settings_warning = self._check_company_sepa_settings()

            log_message = f"""SEPA Mandate Discrepancy Check Results:

Total Members Checked: {results['total_checked']}
Auto-Fixed Issues: {len(results.get('auto_fixed', []))}
{company_settings_warning}
MANUAL REVIEW NEEDED:
- Missing Mandates: {len(results.get('missing_mandates', []))}
- IBAN Mismatches: {len(results.get('iban_mismatches', []))}
- Name Mismatches: {len(results.get('name_mismatches', []))}
- Processing Errors: {len(results.get('errors', []))}

Missing Mandates:
{self._format_issue_list(results.get('missing_mandates', []), ['member', 'member_name', 'iban'])}

IBAN Mismatches:
{self._format_issue_list(results.get('iban_mismatches', []), ['member', 'member_name', 'mandate_id', 'mandate_iban', 'current_iban'])}

Name Mismatches:
{self._format_issue_list(results.get('name_mismatches', []), ['member', 'member_name', 'mandate_id', 'mandate_name', 'current_name'])}

Errors:
{self._format_issue_list(results.get('errors', []), ['member', 'error', 'action'])}
"""

            frappe.log_error(log_message, "SEPA Mandate Discrepancies - Manual Review Required")

    def _format_issue_list(self, issues: List[Dict], fields: List[str]) -> str:
        """Format a list of issues for logging."""
        if not issues:
            return "None"

        formatted = []
        for issue in issues[:10]:  # Limit to first 10 to avoid huge logs
            formatted.append(" | ".join([f"{field}: {issue.get(field, 'N/A')}" for field in fields]))

        if len(issues) > 10:
            formatted.append(f"... and {len(issues) - 10} more")

        return "\n".join(formatted)


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
def validate_mandate_creation_api(member: str, iban: str, mandate_id: str) -> OperationResult[Dict[str, Any]]:
    """
    API endpoint to validate mandate creation parameters.

    Args:
        member: Member name/ID
        iban: IBAN for the mandate
        mandate_id: Proposed mandate ID

    Returns:
        OperationResult[Dict]: Validation result with mandate data

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - Critical API with FINANCIAL operation classification
    """
    manager = get_sepa_mandate_manager()
    result = manager.validate_mandate_creation(member, iban, mandate_id)

    if result.valid:
        return OperationResult.ok(result.data or {}, message=result.message)
    else:
        return OperationResult.fail(result.message, errors=result.errors, data=result.data)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_mandate_api(
    member: str,
    iban: str,
    bic: Optional[str] = None,
    account_holder_name: Optional[str] = None,
    mandate_id: Optional[str] = None,
) -> OperationResult[Dict[str, Any]]:
    """
    API endpoint to create a new SEPA mandate.

    Args:
        member: Member name/ID
        iban: IBAN for the mandate
        bic: Optional BIC code
        account_holder_name: Optional account holder name
        mandate_id: Optional custom mandate ID

    Returns:
        OperationResult[Dict]: Creation result with mandate data

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - Critical API with FINANCIAL operation classification
    """
    manager = get_sepa_mandate_manager()
    result = manager.create_mandate(
        member=member, iban=iban, bic=bic, account_holder_name=account_holder_name, mandate_id=mandate_id
    )

    if result.valid:
        return OperationResult.ok(result.data or {}, message=result.message)
    else:
        return OperationResult.fail(result.message, errors=result.errors, data=result.data)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def deactivate_mandates_for_iban_change_api(member: str, new_iban: str) -> OperationResult[Dict[str, Any]]:
    """
    API endpoint to deactivate old mandates when IBAN changes.

    Args:
        member: Member name/ID
        new_iban: New IBAN

    Returns:
        OperationResult[Dict]: Deactivation result with affected mandates

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - Critical API with FINANCIAL operation classification
    """
    manager = get_sepa_mandate_manager()
    result = manager.deactivate_mandates_for_iban_change(member, new_iban)

    if result.valid:
        return OperationResult.ok(result.data or {}, message=result.message)
    else:
        return OperationResult.fail(result.message, errors=result.errors, data=result.data)


# =============================================================================
# Standalone utility functions (previously in bank_details.py)
# =============================================================================


def get_active_sepa_mandate(
    member_name: str, purpose: str = "used_for_memberships"
) -> Optional[Dict[str, Any]]:
    """
    Get the member's single Active SEPA mandate for a purpose.

    Two defects fixed here (#597):

    1. **Purpose-blind.** The filter was `status = 'Active'` only, and a member may
       legitimately hold an Active membership mandate alongside an Active donation
       mandate (`SEPAMandate.validate_single_active_mandate_per_purpose`). Its
       consumer, `templates/pages/payment_dashboard.py`, shows the result as *the*
       member's mandate on the dues dashboard, so a donation mandate could be
       displayed as the membership one.

    2. **`limit=1` with no `order_by`.** Not even recency -- the row returned was
       whatever the database offered first, so the same member could get different
       answers on two page loads. More than one candidate within a purpose is now
       refused and logged rather than resolved arbitrarily.

    The bare `except Exception: return None` is also gone. It collapsed *failure*
    into *absence*, which is the trap #581 already paid for: a caller reading falsy
    as "nothing here" goes on to create what is missing, and this repo has billed a
    member a third period that way. A query that cannot run is not the same fact as
    a member without a mandate, and the dashboard is better off erroring than
    quietly claiming there is no mandate.

    Args:
        member_name: Member document name
        purpose: One of PURPOSE_FLAGS, or None to ask "any Active mandate".

    Returns:
        Dict with mandate info, or None if there is none -- or if there is more than
        one and choosing would be a guess.
    """
    from verenigingen.verenigingen_payments.utils.mandate_candidates import (
        log_ambiguous_mandate_refusal,
        resolve_purpose_flag,
    )

    purpose = resolve_purpose_flag(purpose)
    filters = {"member": member_name, "status": "Active", "is_active": 1}
    if purpose is not None:
        filters[purpose] = 1

    mandates = frappe.get_all(
        "SEPA Mandate",
        filters=filters,
        fields=["name", "mandate_id", "iban", "account_holder_name", "status"],
        order_by="creation desc",
    )

    if not mandates:
        return None
    if len(mandates) > 1:
        log_ambiguous_mandate_refusal(member_name, mandates, purpose, "Ambiguous active SEPA mandate")
        return None
    return mandates[0]


def determine_mandate_action(
    current_mandate: Optional[Dict], current_payment_method: str, enable_dd: bool, bank_details_changed: bool
) -> str:
    """
    Determine what action is needed for SEPA mandate based on current state.

    Args:
        current_mandate: Current active mandate dict or None
        current_payment_method: Current payment method string
        enable_dd: Whether direct debit should be enabled
        bank_details_changed: Whether bank details have changed

    Returns:
        Action string: 'create_mandate', 'replace_mandate', 'keep_mandate',
                      'cancel_mandate', 'no_mandate', or 'no_action'
    """
    if enable_dd:
        if current_mandate:
            if bank_details_changed:
                return "replace_mandate"  # Cancel current, create new
            else:
                return "keep_mandate"  # Keep existing
        else:
            return "create_mandate"  # Create new
    else:
        if current_mandate:
            return "cancel_mandate"  # Cancel existing
        else:
            return "no_mandate"  # No mandate needed

    return "no_action"
