"""
SEPA Mandate Lifecycle Manager

Complete mandate lifecycle management supporting all SEPA sequence types:
OOFF (One-off), FRST (First), RCUR (Recurring), FNAL (Final)

Implements Week 3 Day 3-4 requirements from the SEPA billing improvements project.
"""

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now, today

from verenigingen.utils.error_handling import SEPAError, ValidationError, handle_api_error
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator import SEPASequenceType

# =============================================================================
# Cache Configuration
# =============================================================================

# Cache TTL in seconds (5 minutes default - balance between freshness and performance)
MANDATE_USAGE_CACHE_TTL_SECONDS = 300


@dataclass
class CacheEntry:
    """Cache entry with TTL support"""

    data: Any
    created_at: float
    ttl_seconds: float = MANDATE_USAGE_CACHE_TTL_SECONDS

    def is_expired(self) -> bool:
        """Check if cache entry has expired"""
        return (time.time() - self.created_at) > self.ttl_seconds


class MandateStatus(Enum):
    """SEPA Mandate Status"""

    PENDING = "Pending"
    ACTIVE = "Active"
    SUSPENDED = "Suspended"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"


class MandateUsageType(Enum):
    """Mandate Usage Type"""

    NEVER_USED = "never_used"
    FIRST_USE = "first_use"
    RECURRING_USE = "recurring_use"
    FINAL_USE = "final_use"
    EXPIRED_USE = "expired_use"


@dataclass
class MandateUsageRecord:
    """Record of mandate usage"""

    usage_date: date
    sequence_type: SEPASequenceType
    amount: Decimal
    invoice_reference: str
    transaction_id: str
    status: str
    result_code: Optional[str] = None


@dataclass
class MandateValidationResult:
    """Result of mandate validation"""

    is_valid: bool
    recommended_sequence_type: Optional[SEPASequenceType]
    usage_type: MandateUsageType
    last_usage_date: Optional[date]
    usage_count: int
    warnings: List[str]
    errors: List[str]
    next_allowed_sequence_types: List[SEPASequenceType]


class SEPAMandateLifecycleManager:
    """
    Comprehensive SEPA mandate lifecycle manager

    Manages the complete lifecycle of SEPA mandates including:
    - Mandate creation and validation
    - Sequence type determination (OOFF, FRST, RCUR, FNAL)
    - Usage tracking and validation
    - Mandate expiration and renewal
    - Business rule enforcement
    """

    def __init__(self):
        self.mandate_validity_months = 36  # SEPA standard: 36 months
        self.mandate_usage_cache: Dict[str, CacheEntry] = {}
        self._cache_lock = Lock()

    # =========================================================================
    # Cache Management
    # =========================================================================

    def _get_cached_usage_history(self, mandate_id: str) -> Optional[List["MandateUsageRecord"]]:
        """
        Get usage history from cache if available and not expired.

        Args:
            mandate_id: SEPA mandate ID

        Returns:
            Cached usage history or None if not cached/expired
        """
        with self._cache_lock:
            entry = self.mandate_usage_cache.get(mandate_id)
            if entry and not entry.is_expired():
                return entry.data
            # Remove expired entry
            if entry:
                del self.mandate_usage_cache[mandate_id]
            return None

    def _set_cached_usage_history(self, mandate_id: str, usage_history: List["MandateUsageRecord"]) -> None:
        """
        Cache usage history for a mandate.

        Args:
            mandate_id: SEPA mandate ID
            usage_history: Usage history to cache
        """
        import time

        with self._cache_lock:
            self.mandate_usage_cache[mandate_id] = CacheEntry(
                data=usage_history,
                created_at=time.time(),
            )

    def invalidate_cache(self, mandate_id: str = None) -> None:
        """
        Invalidate cache for a specific mandate or all mandates.

        Call this when mandate usage records are created/updated.

        Args:
            mandate_id: Specific mandate to invalidate, or None for all
        """
        with self._cache_lock:
            if mandate_id:
                self.mandate_usage_cache.pop(mandate_id, None)
            else:
                self.mandate_usage_cache.clear()

    def _cleanup_expired_cache_entries(self) -> int:
        """
        Remove expired cache entries. Called periodically.

        Returns:
            Number of entries removed
        """
        with self._cache_lock:
            expired_keys = [key for key, entry in self.mandate_usage_cache.items() if entry.is_expired()]
            for key in expired_keys:
                del self.mandate_usage_cache[key]
            return len(expired_keys)

    @performance_monitor(threshold_ms=1000)
    def determine_sequence_type(
        self, mandate_id: str, transaction_context: Dict[str, Any] = None
    ) -> MandateValidationResult:
        """
        Determine appropriate SEPA sequence type for a mandate

        Args:
            mandate_id: SEPA mandate ID
            transaction_context: Additional context (member, amount, etc.)

        Returns:
            MandateValidationResult with sequence type recommendation
        """
        try:
            # Get mandate information
            mandate = self._get_mandate_info(mandate_id)
            if not mandate:
                return MandateValidationResult(
                    is_valid=False,
                    recommended_sequence_type=None,
                    usage_type=MandateUsageType.NEVER_USED,
                    last_usage_date=None,
                    usage_count=0,
                    warnings=[],
                    errors=[f"Mandate not found: {mandate_id}"],
                    next_allowed_sequence_types=[],
                )

            # Get usage history
            usage_history = self._get_mandate_usage_history(mandate_id)

            # Validate mandate status and age
            validation_issues = self._validate_mandate_basic_requirements(mandate)

            # Determine usage type and sequence
            usage_type, recommended_sequence = self._analyze_mandate_usage(
                mandate, usage_history, transaction_context
            )

            # Get next allowed sequence types
            next_allowed = self._get_next_allowed_sequence_types(usage_type, recommended_sequence)

            # Check for warnings
            warnings = self._generate_mandate_warnings(mandate, usage_history, usage_type)

            return MandateValidationResult(
                is_valid=len(validation_issues) == 0,
                recommended_sequence_type=recommended_sequence,
                usage_type=usage_type,
                last_usage_date=usage_history[-1].usage_date if usage_history else None,
                usage_count=len(usage_history),
                warnings=warnings,
                errors=validation_issues,
                next_allowed_sequence_types=next_allowed,
            )

        except Exception as e:
            frappe.logger().error(f"Error determining sequence type for mandate {mandate_id}: {str(e)}")
            return MandateValidationResult(
                is_valid=False,
                recommended_sequence_type=None,
                usage_type=MandateUsageType.NEVER_USED,
                last_usage_date=None,
                usage_count=0,
                warnings=[],
                errors=[f"System error: {str(e)}"],
                next_allowed_sequence_types=[],
            )

    def _get_mandate_info(self, mandate_id: str) -> Optional[Dict[str, Any]]:
        """Get mandate information from database"""
        try:
            mandate = frappe.db.get_value(
                "SEPA Mandate",
                {"mandate_id": mandate_id},
                [
                    "name",
                    "mandate_id",
                    "status",
                    "sign_date",
                    "first_collection_date",
                    "expiry_date",
                    "member",
                    "iban",
                    "bic",
                    "mandate_type",
                    "creation",
                    "modified",
                ],
                as_dict=True,
            )
            return mandate
        except Exception as e:
            frappe.logger().error(f"Error fetching mandate {mandate_id}: {str(e)}")
            return None

    def _get_mandate_usage_history(self, mandate_id: str) -> List[MandateUsageRecord]:
        """
        Get complete usage history for a mandate from authoritative SEPA Mandate Usage table.

        Uses caching with TTL to improve performance for batch processing.

        Args:
            mandate_id: SEPA mandate ID (the reference ID, not document name)

        Returns:
            List of MandateUsageRecord ordered by usage_date ascending
        """
        # Check cache first
        cached = self._get_cached_usage_history(mandate_id)
        if cached is not None:
            return cached

        try:
            # Get mandate name from mandate_id
            mandate_name = frappe.db.get_value("SEPA Mandate", {"mandate_id": mandate_id}, "name")
            if not mandate_name:
                return []

            # Query the authoritative SEPA Mandate Usage child table
            usage_records = frappe.get_all(
                "SEPA Mandate Usage",
                filters={"parent": mandate_name},
                fields=[
                    "usage_date",
                    "sequence_type",
                    "amount",
                    "reference_name",
                    "batch_reference",
                    "status",
                    "failure_reason",
                ],
                order_by="usage_date ASC",
            )

            # Map sequence type strings to enum values
            sequence_type_map = {
                "OOFF": SEPASequenceType.OOFF,
                "FRST": SEPASequenceType.FRST,
                "RCUR": SEPASequenceType.RCUR,
                "FNAL": SEPASequenceType.FNAL,
            }

            usage_history = []
            for record in usage_records:
                # Convert sequence_type string to enum, default to RCUR if unknown
                seq_type_str = record.sequence_type or "RCUR"
                seq_type = sequence_type_map.get(seq_type_str, SEPASequenceType.RCUR)

                usage_history.append(
                    MandateUsageRecord(
                        usage_date=getdate(record.usage_date),
                        sequence_type=seq_type,
                        amount=Decimal(str(record.amount or 0)),
                        invoice_reference=record.reference_name or "",
                        transaction_id=record.batch_reference or "",
                        status=record.status or "Pending",
                        result_code=record.failure_reason,
                    )
                )

            # Cache the result
            self._set_cached_usage_history(mandate_id, usage_history)

            return usage_history

        except Exception as e:
            frappe.logger().warning(f"Error fetching usage history for mandate {mandate_id}: {str(e)}")
            return []

    def _validate_mandate_basic_requirements(self, mandate: Dict[str, Any]) -> List[str]:
        """Validate basic mandate requirements"""
        errors = []

        # Status validation
        if mandate.get("status") != "Active":
            errors.append(f"Mandate status is {mandate.get('status')}, expected Active")

        # Age validation
        if mandate.get("sign_date"):
            sign_date = getdate(mandate["sign_date"])
            today_date = getdate(today())

            months_old = (today_date.year - sign_date.year) * 12 + (today_date.month - sign_date.month)

            if months_old > self.mandate_validity_months:
                errors.append(f"Mandate is {months_old} months old (maximum {self.mandate_validity_months})")

        # Expiry validation
        if mandate.get("expiry_date"):
            expiry_date = getdate(mandate["expiry_date"])
            if expiry_date < getdate(today()):
                errors.append(f"Mandate expired on {expiry_date}")

        # IBAN validation
        if not mandate.get("iban"):
            errors.append("Mandate has no IBAN")

        return errors

    def _analyze_mandate_usage(
        self,
        mandate: Dict[str, Any],
        usage_history: List[MandateUsageRecord],
        transaction_context: Dict[str, Any] = None,
    ) -> Tuple[MandateUsageType, SEPASequenceType]:
        """
        Analyze mandate usage to determine appropriate SEPA sequence type.

        Handles edge cases:
        - OOFF (one-off) mandates
        - FNAL (final) usage detection and prevention of reuse
        - Mandate renewal (sign_date > last_usage_date)
        - Expired-but-renewed mandates
        - 36-month non-use expiry

        Args:
            mandate: Mandate information dict
            usage_history: List of previous usage records
            transaction_context: Optional context (is_one_off, is_final flags)

        Returns:
            Tuple of (MandateUsageType, SEPASequenceType)
        """
        # Check for explicit mandate type (OOFF mandates)
        mandate_type = mandate.get("mandate_type", "").upper()
        if mandate_type == "OOFF":
            if usage_history:
                return MandateUsageType.EXPIRED_USE, SEPASequenceType.OOFF
            else:
                return MandateUsageType.FIRST_USE, SEPASequenceType.OOFF

        # Check transaction context for one-off indication
        if transaction_context and transaction_context.get("is_one_off"):
            if usage_history:
                return MandateUsageType.EXPIRED_USE, SEPASequenceType.OOFF
            else:
                return MandateUsageType.FIRST_USE, SEPASequenceType.OOFF

        # Check for final usage indication
        if transaction_context and transaction_context.get("is_final"):
            if usage_history:
                return MandateUsageType.FINAL_USE, SEPASequenceType.FNAL
            else:
                return MandateUsageType.FIRST_USE, SEPASequenceType.FRST

        # Standard recurring mandate logic
        if not usage_history:
            # Never used - first transaction
            return MandateUsageType.FIRST_USE, SEPASequenceType.FRST

        # Get relevant dates
        last_usage = usage_history[-1]
        last_usage_date = last_usage.usage_date
        today_date = getdate(today())
        sign_date = getdate(mandate["sign_date"]) if mandate.get("sign_date") else None

        # =================================================================
        # EDGE CASE 1: FNAL detection - mandate should not be used again
        # =================================================================
        if last_usage.sequence_type == SEPASequenceType.FNAL:
            # FNAL was sent - mandate is terminated and cannot be reused
            # A new mandate must be signed to continue collections
            frappe.logger().warning(
                f"Mandate {mandate.get('mandate_id')} was marked FNAL on {last_usage_date}. "
                "A new mandate is required for further collections."
            )
            return MandateUsageType.EXPIRED_USE, SEPASequenceType.FNAL

        # =================================================================
        # EDGE CASE 2: Mandate renewal (sign_date > last_usage_date)
        # =================================================================
        # If the mandate was re-signed after the last usage, treat as renewed
        # This handles expired-but-renewed mandates
        if sign_date and sign_date > last_usage_date:
            # Mandate was renewed - use FRST for first collection after renewal
            frappe.logger().info(
                f"Mandate {mandate.get('mandate_id')} was renewed on {sign_date} "
                f"(last usage was {last_usage_date}). Using FRST for renewed mandate."
            )
            return MandateUsageType.FIRST_USE, SEPASequenceType.FRST

        # =================================================================
        # EDGE CASE 3: 36-month non-use expiry with renewal check
        # =================================================================
        months_since_last_use = (today_date.year - last_usage_date.year) * 12 + (
            today_date.month - last_usage_date.month
        )

        if months_since_last_use > self.mandate_validity_months:
            # Mandate expired due to non-use
            # Check if mandate was renewed (sign_date is recent)
            if sign_date:
                months_since_sign = (today_date.year - sign_date.year) * 12 + (
                    today_date.month - sign_date.month
                )
                if months_since_sign <= self.mandate_validity_months:
                    # Sign date is recent - mandate was renewed, use FRST
                    frappe.logger().info(
                        f"Mandate {mandate.get('mandate_id')} expired due to non-use but "
                        f"was re-signed on {sign_date}. Using FRST for renewed mandate."
                    )
                    return MandateUsageType.FIRST_USE, SEPASequenceType.FRST

            # Mandate truly expired - cannot be used without renewal
            frappe.logger().warning(
                f"Mandate {mandate.get('mandate_id')} expired after {months_since_last_use} months "
                f"of non-use (limit: {self.mandate_validity_months} months). Renewal required."
            )
            return MandateUsageType.EXPIRED_USE, SEPASequenceType.FRST

        # Regular recurring usage
        return MandateUsageType.RECURRING_USE, SEPASequenceType.RCUR

    def _get_next_allowed_sequence_types(
        self, usage_type: MandateUsageType, current_sequence: SEPASequenceType
    ) -> List[SEPASequenceType]:
        """Get list of allowed next sequence types"""

        if usage_type == MandateUsageType.NEVER_USED:
            return [SEPASequenceType.FRST, SEPASequenceType.OOFF]

        elif usage_type == MandateUsageType.FIRST_USE:
            if current_sequence == SEPASequenceType.OOFF:
                return []  # OOFF mandates cannot be used again
            else:
                return [SEPASequenceType.RCUR, SEPASequenceType.FNAL]

        elif usage_type == MandateUsageType.RECURRING_USE:
            return [SEPASequenceType.RCUR, SEPASequenceType.FNAL]

        elif usage_type == MandateUsageType.FINAL_USE:
            return []  # No further usage allowed after FNAL

        elif usage_type == MandateUsageType.EXPIRED_USE:
            return []  # Expired mandates cannot be used

        return []

    def _generate_mandate_warnings(
        self, mandate: Dict[str, Any], usage_history: List[MandateUsageRecord], usage_type: MandateUsageType
    ) -> List[str]:
        """Generate warnings for mandate usage"""
        warnings = []

        # Age warnings
        if mandate.get("sign_date"):
            sign_date = getdate(mandate["sign_date"])
            months_old = (getdate(today()).year - sign_date.year) * 12 + (
                getdate(today()).month - sign_date.month
            )

            if months_old > 30:  # Warning at 30 months
                warnings.append(f"Mandate is {months_old} months old - consider renewal")

        # Usage pattern warnings
        if usage_history:
            last_usage = usage_history[-1]
            days_since_last = (getdate(today()) - last_usage.usage_date).days

            if days_since_last > 365:  # More than a year
                warnings.append(f"Mandate not used for {days_since_last} days - validate with debtor")

            # Check for unusual usage patterns
            if len(usage_history) > 50:  # Very frequent usage
                warnings.append("High frequency mandate usage - monitor for potential issues")

        # Expiry warnings
        if mandate.get("expiry_date"):
            expiry_date = getdate(mandate["expiry_date"])
            days_to_expiry = (expiry_date - getdate(today())).days

            if 0 < days_to_expiry <= 30:  # Expiring within 30 days
                warnings.append(f"Mandate expires in {days_to_expiry} days - arrange renewal")

        return warnings

    def record_mandate_usage(
        self,
        mandate_id: str,
        sequence_type: SEPASequenceType,
        amount: Decimal,
        invoice_reference: str,
        transaction_id: str,
    ) -> bool:
        """Record mandate usage for tracking"""
        try:
            # Update mandate usage count and last used date
            # Usage tracking is handled via the usage_history table
            # Update modified timestamp
            frappe.db.sql(
                """
                UPDATE `tabSEPA Mandate`
                SET modified = %s
                WHERE mandate_id = %s
            """,
                (now(), mandate_id),
            )

            # Handle OOFF and FNAL sequence types
            if sequence_type == SEPASequenceType.OOFF:
                # Mark OOFF mandate as used/expired
                frappe.db.set_value("SEPA Mandate", {"mandate_id": mandate_id}, "status", "Used")
            elif sequence_type == SEPASequenceType.FNAL:
                # Mark FNAL mandate as completed
                frappe.db.set_value("SEPA Mandate", {"mandate_id": mandate_id}, "status", "Completed")

            frappe.db.commit()
            return True

        except Exception as e:
            frappe.logger().error(f"Error recording mandate usage for {mandate_id}: {str(e)}")
            return False

    def validate_mandate_for_transaction(
        self, mandate_id: str, amount: Decimal, transaction_context: Dict[str, Any] = None
    ) -> MandateValidationResult:
        """
        Validate mandate for a specific transaction

        Args:
            mandate_id: SEPA mandate ID
            amount: Transaction amount
            transaction_context: Additional context

        Returns:
            MandateValidationResult with validation outcome
        """
        # Get basic sequence type determination
        result = self.determine_sequence_type(mandate_id, transaction_context)

        if not result.is_valid:
            return result

        # Additional transaction-specific validations
        additional_errors = []
        additional_warnings = []

        # Amount validation
        if amount <= 0:
            additional_errors.append("Transaction amount must be positive")
        elif amount > Decimal("999999999.99"):
            additional_errors.append("Transaction amount exceeds SEPA maximum")

        # Business rule validations
        mandate = self._get_mandate_info(mandate_id)
        if mandate:
            # Check for member-specific limits
            member_id = mandate.get("member")
            if member_id and transaction_context:
                member_validation = self._validate_member_transaction_limits(
                    member_id, amount, transaction_context
                )
                additional_errors.extend(member_validation.get("errors", []))
                additional_warnings.extend(member_validation.get("warnings", []))

        # Update result with additional validations
        result.errors.extend(additional_errors)
        result.warnings.extend(additional_warnings)
        result.is_valid = len(result.errors) == 0

        return result

    def _validate_member_transaction_limits(
        self, member_id: str, amount: Decimal, context: Dict[str, Any]
    ) -> Dict[str, List[str]]:
        """Validate member-specific transaction limits"""
        errors = []
        warnings = []

        try:
            # Get member information
            member = frappe.get_doc("Member", member_id)

            # Check member status
            if hasattr(member, "status") and member.status not in ["Active", "Current"]:
                errors.append(f"Member status is {member.status} - transaction not allowed")

            # Check for monthly/daily limits (if implemented)
            # This would be customizable based on business rules

        except Exception as e:
            warnings.append(f"Could not validate member limits: {str(e)}")

        return {"errors": errors, "warnings": warnings}

    def create_mandate_usage_report(
        self, mandate_id: str = None, member_id: str = None, date_from: str = None, date_to: str = None
    ) -> Dict[str, Any]:
        """Create comprehensive mandate usage report"""
        try:
            filters = []
            params = {}

            # Build dynamic query based on filters
            if mandate_id:
                filters.append("ddi.mandate_reference = %(mandate_id)s")
                params["mandate_id"] = mandate_id

            if member_id:
                filters.append("sm.member = %(member_id)s")
                params["member_id"] = member_id

            if date_from:
                filters.append("ddb.batch_date >= %(date_from)s")
                params["date_from"] = date_from

            if date_to:
                filters.append("ddb.batch_date <= %(date_to)s")
                params["date_to"] = date_to

            where_clause = "WHERE " + " AND ".join(filters) if filters else ""

            # Execute report query
            usage_data = frappe.db.sql(
                f"""
                SELECT
                    ddi.mandate_reference,
                    sm.member,
                    mem.full_name as member_name,
                    ddb.batch_date,
                    ddi.amount,
                    ddi.currency,
                    ddi.invoice,
                    ddi.status as transaction_status,
                    ddb.status as batch_status,
                    sm.sign_date,
                    sm.status as mandate_status,
                    COUNT(*) OVER (PARTITION BY ddi.mandate_reference) as usage_count
                FROM `tabDirect Debit Batch Invoice` ddi
                JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
                LEFT JOIN `tabSEPA Mandate` sm ON ddi.mandate_reference = sm.mandate_id
                LEFT JOIN `tabMember` mem ON sm.member = mem.name
                {where_clause}
                ORDER BY ddb.batch_date DESC, ddi.mandate_reference
            """,
                params,
                as_dict=True,
            )

            # Calculate summary statistics
            if usage_data:
                total_amount = sum(Decimal(str(row.amount)) for row in usage_data)
                unique_mandates = len(set(row.mandate_reference for row in usage_data))
                unique_members = len(set(row.member for row in usage_data if row.member))

                summary = {
                    "total_transactions": len(usage_data),
                    "total_amount": float(total_amount),
                    "unique_mandates": unique_mandates,
                    "unique_members": unique_members,
                    "date_range": (
                        {
                            "from": min(row.batch_date for row in usage_data),
                            "to": max(row.batch_date for row in usage_data),
                        }
                        if usage_data
                        else None
                    ),
                }
            else:
                summary = {
                    "total_transactions": 0,
                    "total_amount": 0,
                    "unique_mandates": 0,
                    "unique_members": 0,
                    "date_range": None,
                }

            return {
                "success": True,
                "summary": summary,
                "usage_data": [
                    {
                        "mandate_reference": row.mandate_reference,
                        "member": row.member_name,
                        "batch_date": str(row.batch_date),
                        "amount": float(row.amount),
                        "currency": row.currency,
                        "invoice": row.invoice,
                        "transaction_status": row.transaction_status,
                        "batch_status": row.batch_status,
                        "mandate_status": row.mandate_status,
                        "usage_count": row.usage_count,
                    }
                    for row in usage_data
                ],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "summary": None, "usage_data": []}

    def get_mandate_lifecycle_status(self, mandate_id: str) -> Dict[str, Any]:
        """Get comprehensive lifecycle status for a mandate"""
        try:
            mandate = self._get_mandate_info(mandate_id)
            if not mandate:
                return {"success": False, "error": "Mandate not found", "mandate_id": mandate_id}

            usage_history = self._get_mandate_usage_history(mandate_id)
            validation_result = self.determine_sequence_type(mandate_id)

            # Calculate lifecycle metrics
            if mandate.get("sign_date"):
                sign_date = getdate(mandate["sign_date"])
                age_days = (getdate(today()) - sign_date).days
                age_months = age_days // 30
            else:
                age_days = 0
                age_months = 0

            # Determine lifecycle stage
            if not usage_history:
                lifecycle_stage = "unused"
            elif validation_result.usage_type == MandateUsageType.FINAL_USE:
                lifecycle_stage = "completed"
            elif validation_result.usage_type == MandateUsageType.EXPIRED_USE:
                lifecycle_stage = "expired"
            else:
                lifecycle_stage = "active"

            return {
                "success": True,
                "mandate_id": mandate_id,
                "lifecycle_stage": lifecycle_stage,
                "current_status": mandate.get("status"),
                "age": {"days": age_days, "months": age_months},
                "usage_summary": {
                    "total_usage_count": len(usage_history),
                    "last_usage_date": str(usage_history[-1].usage_date) if usage_history else None,
                    "total_amount": float(sum(record.amount for record in usage_history)),
                    "recommended_sequence_type": (
                        validation_result.recommended_sequence_type.value
                        if validation_result.recommended_sequence_type
                        else None
                    ),
                },
                "validation": {
                    "is_valid": validation_result.is_valid,
                    "errors": validation_result.errors,
                    "warnings": validation_result.warnings,
                    "next_allowed_sequence_types": [
                        st.value for st in validation_result.next_allowed_sequence_types
                    ],
                },
                "mandate_details": {
                    "member": mandate.get("member"),
                    "iban": mandate.get("iban"),
                    "sign_date": str(mandate.get("sign_date")) if mandate.get("sign_date") else None,
                    "expiry_date": str(mandate.get("expiry_date")) if mandate.get("expiry_date") else None,
                },
            }

        except Exception as e:
            return {"success": False, "error": str(e), "mandate_id": mandate_id}


# API Functions


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def determine_mandate_sequence_type(mandate_id: str, **transaction_context) -> Dict[str, Any]:
    """
    API endpoint to determine sequence type for a mandate

    Args:
        mandate_id: SEPA mandate ID
        **transaction_context: Additional context parameters

    Returns:
        Mandate validation result with sequence type recommendation
    """
    manager = SEPAMandateLifecycleManager()
    result = manager.determine_sequence_type(mandate_id, transaction_context)

    return {
        "success": result.is_valid,
        "mandate_id": mandate_id,
        "recommended_sequence_type": (
            result.recommended_sequence_type.value if result.recommended_sequence_type else None
        ),
        "usage_type": result.usage_type.value,
        "last_usage_date": str(result.last_usage_date) if result.last_usage_date else None,
        "usage_count": result.usage_count,
        "warnings": result.warnings,
        "errors": result.errors,
        "next_allowed_sequence_types": [st.value for st in result.next_allowed_sequence_types],
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def validate_mandate_for_transaction(mandate_id: str, amount: float, **context) -> Dict[str, Any]:
    """
    API endpoint to validate mandate for specific transaction

    Args:
        mandate_id: SEPA mandate ID
        amount: Transaction amount
        **context: Additional context

    Returns:
        Transaction validation result
    """
    manager = SEPAMandateLifecycleManager()
    result = manager.validate_mandate_for_transaction(mandate_id, Decimal(str(amount)), context)

    return {
        "success": result.is_valid,
        "mandate_id": mandate_id,
        "amount": amount,
        "validation_result": {
            "is_valid": result.is_valid,
            "recommended_sequence_type": (
                result.recommended_sequence_type.value if result.recommended_sequence_type else None
            ),
            "usage_type": result.usage_type.value,
            "warnings": result.warnings,
            "errors": result.errors,
        },
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def get_mandate_usage_report(
    mandate_id: str = None, member_id: str = None, date_from: str = None, date_to: str = None
) -> Dict[str, Any]:
    """
    API endpoint to get mandate usage report

    Args:
        mandate_id: Filter by mandate ID
        member_id: Filter by member ID
        date_from: Start date filter
        date_to: End date filter

    Returns:
        Comprehensive usage report
    """
    manager = SEPAMandateLifecycleManager()
    return manager.create_mandate_usage_report(mandate_id, member_id, date_from, date_to)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
@handle_api_error
def get_mandate_lifecycle_status(mandate_id: str) -> Dict[str, Any]:
    """
    API endpoint to get mandate lifecycle status

    Args:
        mandate_id: SEPA mandate ID

    Returns:
        Comprehensive lifecycle status
    """
    manager = SEPAMandateLifecycleManager()
    return manager.get_mandate_lifecycle_status(mandate_id)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def bulk_validate_mandates(mandate_ids: str) -> Dict[str, Any]:
    """
    API endpoint to validate multiple mandates at once

    Args:
        mandate_ids: Comma-separated list of mandate IDs

    Returns:
        Bulk validation results
    """
    try:
        mandate_list = [mid.strip() for mid in mandate_ids.split(",") if mid.strip()]
        manager = SEPAMandateLifecycleManager()

        results = {}
        summary = {
            "total_mandates": len(mandate_list),
            "valid_mandates": 0,
            "invalid_mandates": 0,
            "warnings_count": 0,
        }

        for mandate_id in mandate_list:
            result = manager.determine_sequence_type(mandate_id)

            results[mandate_id] = {
                "is_valid": result.is_valid,
                "recommended_sequence_type": (
                    result.recommended_sequence_type.value if result.recommended_sequence_type else None
                ),
                "usage_type": result.usage_type.value,
                "errors": result.errors,
                "warnings": result.warnings,
            }

            if result.is_valid:
                summary["valid_mandates"] += 1
            else:
                summary["invalid_mandates"] += 1

            summary["warnings_count"] += len(result.warnings)

        return {"success": True, "summary": summary, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e), "summary": None, "results": {}}


# =============================================================================
# Reconciliation Functions
# =============================================================================


@dataclass
class ReconciliationResult:
    """Result of mandate usage reconciliation"""

    success: bool
    discrepancies: List[Dict[str, Any]]
    summary: Dict[str, int]
    errors: List[str]


def reconcile_mandate_usage_records(
    mandate_id: str = None, date_from: str = None, date_to: str = None
) -> ReconciliationResult:
    """
    Reconcile SEPA Mandate Usage records against Direct Debit Batch Invoice records.

    This helps detect discrepancies between the authoritative usage table and
    the batch invoice records for auditing and data integrity purposes.

    Args:
        mandate_id: Optional specific mandate to reconcile
        date_from: Optional start date filter
        date_to: Optional end date filter

    Returns:
        ReconciliationResult with discrepancies and summary
    """
    discrepancies = []
    errors = []
    summary = {
        "total_usage_records": 0,
        "total_batch_records": 0,
        "matched_records": 0,
        "missing_in_usage": 0,  # In batch but not in usage table
        "missing_in_batch": 0,  # In usage table but not in batch
        "amount_mismatches": 0,
        "status_mismatches": 0,
    }

    try:
        # Build filters
        usage_filters = {}
        batch_filters = []
        batch_params = {}

        if mandate_id:
            # Get mandate name from ID
            mandate_name = frappe.db.get_value("SEPA Mandate", {"mandate_id": mandate_id}, "name")
            if mandate_name:
                usage_filters["parent"] = mandate_name
                batch_filters.append("ddi.mandate_reference = %(mandate_id)s")
                batch_params["mandate_id"] = mandate_id

        if date_from:
            batch_filters.append("ddb.batch_date >= %(date_from)s")
            batch_params["date_from"] = date_from

        if date_to:
            batch_filters.append("ddb.batch_date <= %(date_to)s")
            batch_params["date_to"] = date_to

        # Get usage records from authoritative SEPA Mandate Usage table
        usage_records = frappe.get_all(
            "SEPA Mandate Usage",
            filters=usage_filters,
            fields=[
                "name",
                "parent",
                "usage_date",
                "reference_name",
                "batch_reference",
                "amount",
                "status",
                "sequence_type",
            ],
        )
        summary["total_usage_records"] = len(usage_records)

        # Build lookup by reference_name + parent
        usage_lookup = {(r.parent, r.reference_name): r for r in usage_records if r.reference_name}

        # Get batch invoice records
        where_clause = "WHERE ddb.docstatus = 1"
        if batch_filters:
            where_clause += " AND " + " AND ".join(batch_filters)

        batch_records = frappe.db.sql(
            f"""
            SELECT
                ddi.name as invoice_row_name,
                ddi.invoice as reference_name,
                ddi.mandate_reference,
                ddi.amount,
                ddi.status,
                ddb.name as batch_name,
                ddb.batch_date,
                sm.name as mandate_name
            FROM `tabDirect Debit Batch Invoice` ddi
            JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
            LEFT JOIN `tabSEPA Mandate` sm ON ddi.mandate_reference = sm.mandate_id
            {where_clause}
            """,
            batch_params,
            as_dict=True,
        )
        summary["total_batch_records"] = len(batch_records)

        # Check each batch record against usage records
        for batch_record in batch_records:
            mandate_name = batch_record.mandate_name
            ref_name = batch_record.reference_name
            key = (mandate_name, ref_name)

            if key in usage_lookup:
                usage_record = usage_lookup[key]
                summary["matched_records"] += 1

                # Check for amount mismatch
                batch_amount = Decimal(str(batch_record.amount or 0))
                usage_amount = Decimal(str(usage_record.amount or 0))

                if batch_amount != usage_amount:
                    summary["amount_mismatches"] += 1
                    discrepancies.append(
                        {
                            "type": "amount_mismatch",
                            "mandate_id": batch_record.mandate_reference,
                            "reference_name": ref_name,
                            "batch_amount": float(batch_amount),
                            "usage_amount": float(usage_amount),
                            "batch_name": batch_record.batch_name,
                        }
                    )

                # Remove from lookup to track missing_in_batch later
                del usage_lookup[key]
            else:
                # Batch record not found in usage table
                summary["missing_in_usage"] += 1
                discrepancies.append(
                    {
                        "type": "missing_in_usage",
                        "mandate_id": batch_record.mandate_reference,
                        "reference_name": ref_name,
                        "batch_amount": float(batch_record.amount or 0),
                        "batch_date": str(batch_record.batch_date),
                        "batch_name": batch_record.batch_name,
                    }
                )

        # Any remaining usage records are missing in batch
        for key, usage_record in usage_lookup.items():
            # Only flag if the usage record has a batch_reference (was meant to be batched)
            if usage_record.batch_reference:
                summary["missing_in_batch"] += 1
                mandate_id_value = frappe.db.get_value("SEPA Mandate", usage_record.parent, "mandate_id")
                discrepancies.append(
                    {
                        "type": "missing_in_batch",
                        "mandate_id": mandate_id_value,
                        "reference_name": usage_record.reference_name,
                        "usage_amount": float(usage_record.amount or 0),
                        "usage_date": str(usage_record.usage_date),
                        "expected_batch": usage_record.batch_reference,
                    }
                )

        return ReconciliationResult(
            success=True,
            discrepancies=discrepancies,
            summary=summary,
            errors=errors,
        )

    except Exception as e:
        errors.append(str(e))
        frappe.logger().error(f"Reconciliation error: {str(e)}")
        return ReconciliationResult(
            success=False,
            discrepancies=discrepancies,
            summary=summary,
            errors=errors,
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
@handle_api_error
def run_mandate_usage_reconciliation(
    mandate_id: str = None, date_from: str = None, date_to: str = None
) -> Dict[str, Any]:
    """
    API endpoint to run mandate usage reconciliation.

    Compares SEPA Mandate Usage records against Direct Debit Batch Invoice
    records to detect discrepancies.

    Args:
        mandate_id: Optional specific mandate ID to reconcile
        date_from: Optional start date filter (YYYY-MM-DD)
        date_to: Optional end date filter (YYYY-MM-DD)

    Returns:
        Reconciliation results including discrepancies and summary
    """
    result = reconcile_mandate_usage_records(mandate_id, date_from, date_to)

    return {
        "success": result.success,
        "summary": result.summary,
        "discrepancies": result.discrepancies,
        "discrepancy_count": len(result.discrepancies),
        "errors": result.errors,
    }
