"""
Unified SEPA Mandate Lookup Service
Consolidates all SEPA mandate operations for better performance and consistency
"""

from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import getdate, today


class SEPAMandateService:
    """Centralized service for SEPA mandate operations with caching and batch processing"""

    def __init__(self):
        self._mandate_cache = {}
        self._sequence_cache = {}

    def get_active_mandate_batch(self, member_names: List[str]) -> Dict[str, Optional[Dict]]:
        """
        Get active SEPA mandates for multiple members in a single query
        Returns dict with member_name as key and mandate info as value
        """
        if not member_names:
            return {}

        # Check cache first
        cached_results = {}
        uncached_members = []

        for member in member_names:
            if member in self._mandate_cache:
                cached_results[member] = self._mandate_cache[member]
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
            ORDER BY sm.member, sm.creation DESC
        """,
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
            self._mandate_cache[member] = member_mandate
            results[member] = member_mandate

        return results

    def get_active_mandate(self, member_name: str) -> Optional[Dict]:
        """Get active SEPA mandate for a single member (uses batch service)"""
        result = self.get_active_mandate_batch([member_name])
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
        from verenigingen.verenigingen.doctype.sepa_mandate_usage.sepa_mandate_usage import (
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
                si.custom_membership_dues_schedule as schedule_name,
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
                `tabSales Invoice` si USE INDEX (idx_sepa_invoice_lookup)
            JOIN `tabMembership Dues Schedule` mds ON si.custom_membership_dues_schedule = mds.name
            JOIN `tabMember` mem ON mds.member = mem.name
            LEFT JOIN `tabMember` paying_member ON si.custom_paying_for_member = paying_member.name
            JOIN `tabSEPA Mandate` sm ON sm.member = mem.name AND sm.status = 'Active'
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
                    WHERE ddi.invoice = si.name AND ddb.docstatus != 2
                )
            ORDER BY
                si.posting_date ASC,
                si.grand_total DESC
            LIMIT 1000  -- Pagination limit
        """,
            {"lookback_date": lookback_date},
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

        # Query all mandates at once
        mandates = frappe.db.sql(
            """
            SELECT
                name,
                status,
                iban,
                bic,
                mandate_id,
                valid_from,
                valid_until,
                date_signed,
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

            # Check validity period
            if mandate.valid_from and getdate(mandate.valid_from) > today_date:
                validation_result["valid"] = False
                validation_result["issues"].append("Mandate not yet valid")

            if mandate.valid_until and getdate(mandate.valid_until) < today_date:
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

    def clear_cache(self):
        """Clear the mandate and sequence type caches"""
        self._mandate_cache.clear()
        self._sequence_cache.clear()
        frappe.logger().info("SEPA Mandate Service cache cleared")

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
def clear_sepa_mandate_cache():
    """API to clear SEPA mandate cache"""
    service = get_sepa_mandate_service()
    service.clear_cache()
    return {"success": True, "message": "SEPA mandate cache cleared"}


@frappe.whitelist()
def get_sepa_cache_stats():
    """API to get SEPA cache statistics"""
    service = get_sepa_mandate_service()
    return service.get_cache_stats()
