"""
Unified SEPA Mandate Lookup Service
Consolidates all SEPA mandate operations for better performance and consistency
"""

from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import getdate, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.verenigingen_payments.utils.sepa_constants import stranded_batch_exclusion

# Cache TTL in seconds (5 minutes)
CACHE_TTL_SECONDS = 300
CACHE_KEY_PREFIX = "sepa_mandate_service:"


class SEPAMandateService:
    """Centralized service for SEPA mandate operations with caching and batch processing

    Cache Strategy:
    - Uses Redis via frappe.cache() for multi-process safety
    - 5-minute TTL to prevent stale data
    - Automatic invalidation on mandate updates via invalidate_member_cache()
    """

    def __init__(self):
        # In-process cache as fallback/fast path (cleared on invalidation)
        self._mandate_cache = {}
        self._sequence_cache = {}

    @staticmethod
    def mandate_cache_key(member: str, purpose="used_for_memberships"):
        """Key for `_mandate_cache`: member AND purpose.

        The purpose is part of the key, not a detail -- one member can hold an
        Active membership mandate and an Active donation mandate at once (#597), so
        a member-only key would answer a donations lookup with the memberships
        result. Exposed as a method because three places construct it (read, write,
        invalidate) and a fourth shape would reintroduce that bug silently.
        """
        return (member, purpose)

    def get_active_mandate_batch(
        self, member_names: List[str], purpose: str = "used_for_memberships"
    ) -> Dict[str, Optional[Dict]]:
        """
        Get active SEPA mandates for multiple members in a single query
        Returns dict with member_name as key and mandate info as value

        Scoped by PURPOSE (#597). This used to order `sm.member, sm.creation DESC`
        and `break` on the first row per member with no purpose filter, so a member
        holding an Active membership mandate and a newer Active donation mandate --
        a combination `validate_single_active_mandate_per_purpose` explicitly
        permits -- got the donation one. `purpose=None` asks for any Active mandate.

        The cache key includes the purpose. Without that, a lookup for one purpose
        would answer a later lookup for another from the same entry, which is the
        same wrong-mandate bug arriving by a different route.
        """
        if not member_names:
            return {}

        from verenigingen.verenigingen_payments.utils.mandate_candidates import (
            resolve_purpose_flag,
        )

        purpose = resolve_purpose_flag(purpose)

        # Check cache first
        cached_results = {}
        uncached_members = []

        for member in member_names:
            cache_key = self.mandate_cache_key(member, purpose)
            if cache_key in self._mandate_cache:
                cached_results[member] = self._mandate_cache[cache_key]
            else:
                uncached_members.append(member)

        if not uncached_members:
            return cached_results

        # Batch query for uncached members
        mandates = frappe.db.sql(
            """
            SELECT
                sm.name,
                sm.member,
                sm.iban,
                sm.bic,
                sm.mandate_id,
                sm.status,
                sm.creation as date_signed,
                mem.full_name as member_name
            FROM `tabSEPA Mandate` sm
            JOIN `tabMember` mem ON sm.member = mem.name
            WHERE sm.member IN %(members)s
                AND sm.status = 'Active'
                {purpose_clause}
            ORDER BY sm.member, sm.creation DESC
        """.format(
                # Interpolating a value from PURPOSE_FLAGS, validated above -- never
                # caller text. Kept out of the parameter dict because a column name
                # cannot be bound as a parameter.
                purpose_clause=f"AND sm.{purpose} = 1"
                if purpose is not None
                else ""
            ),
            {"members": uncached_members, "today": today()},
            as_dict=True,
        )

        # Process results and cache
        results = cached_results.copy()

        for member in uncached_members:
            member_mandate = None
            for mandate in mandates:
                if mandate.member == member:
                    member_mandate = mandate
                    break

            # Cache the result (even if None)
            self._mandate_cache[self.mandate_cache_key(member, purpose)] = member_mandate
            results[member] = member_mandate

        return results

    def get_active_mandate(self, member_name: str, purpose: str = "used_for_memberships") -> Optional[Dict]:
        """Get active SEPA mandate for a single member (uses batch service)"""
        result = self.get_active_mandate_batch([member_name], purpose=purpose)
        return result.get(member_name)

    def get_sequence_types_batch(self, mandate_invoice_pairs: List[Tuple[str, str]]) -> Dict[str, str]:
        """
        Determine sequence types for multiple mandate-invoice pairs
        Returns dict with 'mandate_name:invoice_name' as key and sequence type as value
        """
        if not mandate_invoice_pairs:
            return {}

        # Check cache first
        cached_results = {}
        uncached_pairs = []

        for mandate_name, invoice_name in mandate_invoice_pairs:
            cache_key = f"{mandate_name}:{invoice_name}"
            if cache_key in self._sequence_cache:
                cached_results[cache_key] = self._sequence_cache[cache_key]
            else:
                uncached_pairs.append((mandate_name, invoice_name))

        if not uncached_pairs:
            return cached_results

        # Import here to avoid circular imports
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            get_mandate_sequence_type,
        )

        # Batch process uncached pairs
        results = cached_results.copy()

        for mandate_name, invoice_name in uncached_pairs:
            try:
                sequence_info = get_mandate_sequence_type(mandate_name, invoice_name)
                sequence_type = sequence_info["sequence_type"]

                cache_key = f"{mandate_name}:{invoice_name}"
                self._sequence_cache[cache_key] = sequence_type
                results[cache_key] = sequence_type

            except Exception as e:
                # Log error but continue processing
                frappe.log_error(
                    f"Error determining sequence type for mandate {mandate_name}, invoice {invoice_name}: {str(e)}",
                    "SEPA Mandate Service - Sequence Type Error",
                )
                # Default to RCUR for safety
                cache_key = f"{mandate_name}:{invoice_name}"
                self._sequence_cache[cache_key] = "RCUR"
                results[cache_key] = "RCUR"

        return results

    def get_sepa_invoices_with_mandates(self, collection_date: str, lookback_days: int = 60) -> List[Dict]:
        """
        Optimized query to get SEPA invoices with mandate information
        Includes pagination support and proper indexing hints
        """
        from frappe.utils import add_days

        lookback_date = add_days(collection_date, -lookback_days)

        # Optimized query with explicit joins and index hints
        invoices = frappe.db.sql(
            """
            SELECT
                si.name,
                si.customer,
                si.grand_total as amount,
                si.currency,
                si.posting_date,
                si.due_date,
                si.membership_dues_schedule_display as schedule_name,
                si.custom_coverage_start_date,
                si.custom_coverage_end_date,
                si.custom_paying_for_member,
                mds.member,
                mds.membership,
                COALESCE(paying_member.full_name, mem.full_name) as member_name,
                sm.name as mandate_name,
                sm.iban,
                sm.bic,
                sm.mandate_id as mandate_reference
            FROM
                -- No forced index hint: idx_sepa_invoice_lookup is created by the
                -- v15_0 SEPA-performance patch, which fresh installs mark applied
                -- without running, so a hard `USE INDEX` raised error 1176 and failed
                -- the whole query. The optimizer still uses the index when present.
                `tabSales Invoice` si
            JOIN `tabMembership Dues Schedule` mds ON si.membership_dues_schedule_display = mds.name
            JOIN `tabMember` mem ON mds.member = mem.name
            LEFT JOIN `tabMember` paying_member ON si.custom_paying_for_member = paying_member.name
            -- Purpose filter (#597). Without it this join produced one row PER
            -- Active mandate, so a member holding a membership mandate and a
            -- donation mandate -- permitted by
            -- `validate_single_active_mandate_per_purpose` -- yielded TWO rows for
            -- ONE invoice, and `sm.mandate_id`/`sm.iban` below go straight into the
            -- Direct Debit Batch child rows. Measured: a EUR 25 invoice collected
            -- twice, both legs on the donation IBAN. This is the automated monthly
            -- path (`sepa_processor.create_monthly_dues_collection_batch`), so no
            -- operator sees the list before it is submitted.
            JOIN `tabSEPA Mandate` sm
                ON sm.member = mem.name
                AND sm.status = 'Active'
                AND sm.used_for_memberships = 1
            WHERE
                si.docstatus = 1
                AND si.status IN ('Unpaid', 'Overdue')
                AND si.outstanding_amount > 0
                AND si.posting_date >= %(lookback_date)s
                AND mds.payment_terms_template = 'SEPA Direct Debit'
                AND sm.iban IS NOT NULL
                AND sm.iban != ''
                AND sm.mandate_id IS NOT NULL
                -- Exclude invoices already in other batches
                AND NOT EXISTS (
                    SELECT 1
                    FROM `tabDirect Debit Batch Invoice` ddi
                    JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
                    WHERE ddi.invoice = si.name
                      AND ddb.docstatus != 2
                      AND {stranded}
                )
            ORDER BY
                si.posting_date ASC,
                si.grand_total DESC
            LIMIT 1000  -- Pagination limit
        """.format(
                stranded=stranded_batch_exclusion("ddb")
            ),
            {"lookback_date": lookback_date, "today": getdate(today())},
            as_dict=True,
        )

        return invoices

    def validate_mandate_status_batch(self, mandate_names: List[str]) -> Dict[str, Dict]:
        """
        Validate multiple mandates in batch
        Returns dict with mandate_name as key and validation result as value
        """
        if not mandate_names:
            return {}

        # Query all mandates at once.
        # Columns match the SEPA Mandate schema: sign_date / expiry_date (NOT the
        # non-existent valid_from / valid_until / date_signed this used to select,
        # which made any non-empty call raise OperationalError 1054). Validity
        # semantics mirror sepa_mandate_lifecycle_service / _validation_service.
        mandates = frappe.db.sql(
            """
            SELECT
                name,
                status,
                iban,
                bic,
                mandate_id,
                sign_date,
                expiry_date,
                member
            FROM `tabSEPA Mandate`
            WHERE name IN %(mandate_names)s
        """,
            {"mandate_names": mandate_names},
            as_dict=True,
        )

        results = {}
        today_date = getdate(today())

        for mandate in mandates:
            validation_result = {"valid": True, "issues": []}

            # Check status
            if mandate.status != "Active":
                validation_result["valid"] = False
                validation_result["issues"].append(f"Mandate status is {mandate.status}, not Active")

            # Check validity period (a future sign_date is not yet valid; a past
            # expiry_date is expired) — same rule as sepa_mandate_lifecycle_service.
            if mandate.sign_date and getdate(mandate.sign_date) > today_date:
                validation_result["valid"] = False
                validation_result["issues"].append("Mandate not yet valid")

            if mandate.expiry_date and getdate(mandate.expiry_date) < today_date:
                validation_result["valid"] = False
                validation_result["issues"].append("Mandate has expired")

            # Check required fields
            if not mandate.iban:
                validation_result["valid"] = False
                validation_result["issues"].append("Missing IBAN")

            if not mandate.mandate_id:
                validation_result["valid"] = False
                validation_result["issues"].append("Missing mandate ID")

            results[mandate.name] = validation_result

        return results

    def invalidate_member_cache(self, member_name: str) -> None:
        """
        Invalidate cache for a specific member.

        Should be called when a member's mandate is created, updated, or deleted.

        Args:
            member_name: Name of the member whose cache should be invalidated
        """
        if not member_name:
            return

        # Clear in-process cache. Keys are (member, purpose) tuples since #597, so
        # every purpose held for this member has to go -- popping the bare member name
        # matches no key at all and would silently stop invalidating anything.
        for key in [k for k in self._mandate_cache if k[0] == member_name]:
            self._mandate_cache.pop(key, None)

        # Clear Redis cache
        cache_key = f"{CACHE_KEY_PREFIX}mandate:{member_name}"
        try:
            frappe.cache().delete_value(cache_key)
        except Exception:
            pass  # Redis may not be available in all environments

        frappe.logger().debug(f"SEPA mandate cache invalidated for member: {member_name}")

    def invalidate_mandate_cache(self, mandate_name: str) -> None:
        """
        Invalidate cache entries related to a specific mandate.

        Args:
            mandate_name: Name of the mandate
        """
        # Clear sequence cache entries containing this mandate
        keys_to_remove = [k for k in self._sequence_cache.keys() if k.startswith(f"{mandate_name}:")]
        for key in keys_to_remove:
            self._sequence_cache.pop(key, None)

        # Clear Redis sequence cache
        try:
            cache_key = f"{CACHE_KEY_PREFIX}sequence:{mandate_name}:*"
            frappe.cache().delete_keys(cache_key)
        except Exception:
            pass  # Redis may not be available

    def clear_cache(self):
        """Clear all mandate and sequence type caches (in-process and Redis)"""
        # Clear in-process caches
        self._mandate_cache.clear()
        self._sequence_cache.clear()

        # Clear Redis caches
        try:
            frappe.cache().delete_keys(f"{CACHE_KEY_PREFIX}*")
        except Exception:
            pass  # Redis may not be available

        frappe.logger().info("SEPA Mandate Service cache cleared (all)")

    def get_cache_stats(self) -> Dict:
        """Get cache statistics for monitoring"""
        return {
            "mandate_cache_size": len(self._mandate_cache),
            "sequence_cache_size": len(self._sequence_cache),
            "total_cached_items": len(self._mandate_cache) + len(self._sequence_cache),
        }


# Global service instance
_sepa_service = None


def get_sepa_mandate_service() -> SEPAMandateService:
    """Get the global SEPA mandate service instance"""
    global _sepa_service
    if _sepa_service is None:
        _sepa_service = SEPAMandateService()
    return _sepa_service


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def clear_sepa_mandate_cache():
    """API to clear SEPA mandate cache"""
    service = get_sepa_mandate_service()
    service.clear_cache()
    return {"success": True, "message": "SEPA mandate cache cleared"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_sepa_cache_stats():
    """API to get SEPA cache statistics"""
    service = get_sepa_mandate_service()
    return service.get_cache_stats()


def invalidate_mandate_cache_for_member(member_name: str) -> None:
    """
    Helper function to invalidate cache for a member.

    Call this from SEPA Mandate document hooks (after_insert, on_update, on_trash)
    to ensure cache consistency.

    Args:
        member_name: Name of the member whose mandate was modified
    """
    try:
        service = get_sepa_mandate_service()
        service.invalidate_member_cache(member_name)
    except Exception:
        # Don't let cache invalidation failures break document saves
        pass


def invalidate_mandate_sequence_cache(mandate_name: str) -> None:
    """
    Helper function to invalidate sequence type cache for a mandate.

    Call this when mandate usage history changes.

    Args:
        mandate_name: Name of the mandate
    """
    try:
        service = get_sepa_mandate_service()
        service.invalidate_mandate_cache(mandate_name)
    except Exception:
        # Don't let cache invalidation failures break document saves
        pass
