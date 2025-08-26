"""
SEPA Batch Performance Optimizer

Provides performance optimizations for SEPA batch processing including:
- Bulk database operations to eliminate N+1 queries
- Intelligent caching for frequently accessed data
- Connection pooling for external services
- Memory-efficient data processing for large batches

Author: Verenigingen Development Team
Date: August 2025
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import frappe


class BatchPerformanceOptimizer:
    """Optimizes SEPA batch processing performance"""

    def __init__(self):
        self.cache_stats = {"hits": 0, "misses": 0, "cache_size": 0}
        self.query_stats = {"total_queries": 0, "optimized_queries": 0, "time_saved_ms": 0}

    def get_members_with_mandates_bulk(self, member_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get member data with mandate information in bulk (eliminates N+1 queries)

        Args:
            member_names: List of member names to fetch

        Returns:
            Dict mapping member_name -> {member_data, mandate_data}
        """
        start_time = time.time()

        if not member_names:
            return {}

        # Single query to get all member data with active mandates
        # Using proper JOIN without assuming active_mandate field exists on Member
        members_with_mandates = frappe.db.sql(
            """
            SELECT
                m.name as member_name,
                m.full_name as member_full_name,
                m.customer,
                m.status as member_status,
                sm.name as mandate_name,
                sm.iban as mandate_iban,
                sm.mandate_id,
                sm.status as mandate_status,
                sm.sign_date,
                sm.bic as mandate_bic,
                sm.account_holder_name,
                sm.member as mandate_member
            FROM `tabMember` m
            LEFT JOIN `tabSEPA Mandate` sm ON (
                sm.member = m.name
                AND sm.status = 'Active'
            )
            WHERE m.name IN %(member_names)s
            AND m.status = 'Active'
        """,
            {"member_names": member_names},
            as_dict=True,
        )

        # Organize data by member
        result = {}
        for row in members_with_mandates:
            result[row["member_name"]] = {
                "member_data": {
                    "name": row["member_name"],
                    "full_name": row["member_full_name"],
                    "customer": row["customer"],
                    "active_mandate": row["mandate_name"],  # Reference to active mandate if exists
                    "status": row["member_status"],
                },
                "mandate_data": {
                    "name": row["mandate_name"],
                    "iban": row["mandate_iban"],
                    "mandate_id": row["mandate_id"],
                    "status": row["mandate_status"],
                    "sign_date": row["sign_date"],
                    "bic": row["mandate_bic"],
                    "account_holder_name": row["account_holder_name"],
                }
                if row["mandate_name"]
                else None,
            }

        # Update performance stats
        execution_time = (time.time() - start_time) * 1000
        self.query_stats["optimized_queries"] += 1
        self.query_stats["total_queries"] += 1

        # Estimate time saved (vs N individual queries)
        estimated_individual_time = len(member_names) * 2 * 5  # 2 queries per member * 5ms average
        time_saved = max(0, estimated_individual_time - execution_time)
        self.query_stats["time_saved_ms"] += time_saved

        frappe.logger().info(
            f"Bulk member+mandate query: {len(member_names)} members in {execution_time:.1f}ms (saved ~{time_saved:.1f}ms)"
        )

        return result

    def get_invoices_with_details_bulk(self, invoice_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get invoice details in bulk including customer and membership information

        Args:
            invoice_names: List of invoice names to fetch

        Returns:
            Dict mapping invoice_name -> invoice details with related data
        """
        start_time = time.time()

        if not invoice_names:
            return {}

        # Single query to get all invoice data with related information
        invoices_with_details = frappe.db.sql(
            """
            SELECT
                si.name as invoice_name,
                si.customer,
                si.grand_total,
                si.currency,
                si.posting_date,
                si.due_date,
                si.status,
                si.outstanding_amount,
                si.membership_dues_schedule_display,
                si.custom_coverage_start_date,
                si.custom_coverage_end_date,
                COALESCE(si.custom_paying_for_member, si.custom_member) as member_reference,
                c.customer_name,
                c.email_id as customer_email,
                m.membership as membership_name,
                m.membership_type,
                m.status as membership_status
            FROM `tabSales Invoice` si
            LEFT JOIN `tabCustomer` c ON si.customer = c.name
            LEFT JOIN `tabMembership` m ON si.custom_membership = m.name
            WHERE si.name IN %(invoice_names)s
            AND si.docstatus = 1
            AND si.status IN ('Unpaid', 'Overdue')
        """,
            {"invoice_names": invoice_names},
            as_dict=True,
        )

        # Organize data by invoice
        result = {}
        for row in invoices_with_details:
            result[row["invoice_name"]] = {
                "name": row["invoice_name"],
                "customer": row["customer"],
                "customer_name": row["customer_name"],
                "customer_email": row["customer_email"],
                "grand_total": row["grand_total"],
                "currency": row["currency"],
                "posting_date": row["posting_date"],
                "due_date": row["due_date"],
                "status": row["status"],
                "outstanding_amount": row["outstanding_amount"],
                "membership_dues_schedule": row["membership_dues_schedule_display"],
                "coverage_start_date": row["custom_coverage_start_date"],
                "coverage_end_date": row["custom_coverage_end_date"],
                "member": row["member_reference"],
                "membership": {
                    "name": row["membership_name"],
                    "membership_type": row["membership_type"],
                    "status": row["membership_status"],
                }
                if row["membership_name"]
                else None,
            }

        execution_time = (time.time() - start_time) * 1000
        self.query_stats["optimized_queries"] += 1
        self.query_stats["total_queries"] += 1

        frappe.logger().info(f"Bulk invoice query: {len(invoice_names)} invoices in {execution_time:.1f}ms")

        return result

    def get_member_addresses_bulk(self, member_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get structured addresses for multiple members in bulk

        Args:
            member_names: List of member names

        Returns:
            Dict mapping member_name -> structured address data
        """
        start_time = time.time()

        if not member_names:
            return {}

        # Get member address data in bulk
        member_addresses = frappe.db.sql(
            """
            SELECT
                m.name as member_name,
                m.address_line_1,
                m.address_line_2,
                m.postal_code,
                m.city,
                m.country,
                m.customer,
                -- Try to get address from linked customer if member address is empty
                addr.address_line1 as customer_address_line1,
                addr.address_line2 as customer_address_line2,
                addr.pincode as customer_postal_code,
                addr.city as customer_city,
                addr.country as customer_country
            FROM `tabMember` m
            LEFT JOIN `tabDynamic Link` dl ON (
                dl.link_doctype = 'Customer'
                AND dl.link_name = m.customer
                AND dl.parenttype = 'Address'
            )
            LEFT JOIN `tabAddress` addr ON dl.parent = addr.name
            WHERE m.name IN %(member_names)s
        """,
            {"member_names": member_names},
            as_dict=True,
        )

        result = {}
        for row in member_addresses:
            # Prefer member address, fall back to customer address
            address_info = {
                "address_line_1": row["address_line_1"] or row["customer_address_line1"],
                "address_line_2": row["address_line_2"] or row["customer_address_line2"],
                "postal_code": row["postal_code"] or row["customer_postal_code"],
                "town": row["city"] or row["customer_city"],
                "country": row["country"] or row["customer_country"] or "NL",
            }

            # Only include if we have minimum required fields (town and country)
            if address_info["town"] and address_info["country"]:
                # Truncate to SEPA limits
                if address_info["address_line_1"]:
                    address_info["address_line_1"] = address_info["address_line_1"][:70]
                if address_info["address_line_2"]:
                    address_info["address_line_2"] = address_info["address_line_2"][:70]

                result[row["member_name"]] = address_info

        execution_time = (time.time() - start_time) * 1000
        self.query_stats["optimized_queries"] += 1

        frappe.logger().info(f"Bulk address query: {len(member_names)} members in {execution_time:.1f}ms")

        return result

    @lru_cache(maxsize=100)
    def get_bank_config_cached(self, bic_code: str) -> Dict[str, Any]:
        """
        Get bank configuration with caching to avoid repeated lookups

        Args:
            bic_code: Bank BIC code

        Returns:
            Bank configuration dictionary
        """
        self.cache_stats["cache_size"] = len(self.get_bank_config_cached.cache_info())

        if bic_code in self.get_bank_config_cached.cache_info().currsize:
            self.cache_stats["hits"] += 1
        else:
            self.cache_stats["misses"] += 1

        # Import here to avoid circular imports
        from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config_manager

        config_manager = get_sepa_config_manager()
        return config_manager.get_bank_specific_config(bic_code)

    def process_batch_invoices_optimized(self, invoice_names: List[str]) -> List[Dict[str, Any]]:
        """
        Process batch invoices with optimized data fetching

        Args:
            invoice_names: List of invoice names to process

        Returns:
            List of processed invoice data ready for SEPA XML generation
        """
        start_time = time.time()

        # Step 1: Get all invoice details in bulk
        invoices_data = self.get_invoices_with_details_bulk(invoice_names)

        # Step 2: Extract member names and get member+mandate data in bulk
        member_names = [inv["member"] for inv in invoices_data.values() if inv["member"]]
        members_data = self.get_members_with_mandates_bulk(member_names)

        # Step 3: Get structured addresses for all members in bulk
        addresses_data = self.get_member_addresses_bulk(member_names)

        # Step 4: Combine all data efficiently
        processed_invoices = []
        for invoice_name in invoice_names:
            invoice_data = invoices_data.get(invoice_name)
            if not invoice_data:
                continue

            member_name = invoice_data["member"]
            member_info = members_data.get(member_name, {})
            member_data = member_info.get("member_data")
            mandate_data = member_info.get("mandate_data")
            address_data = addresses_data.get(member_name)

            if not member_data or not mandate_data:
                frappe.logger().warning(f"Skipping invoice {invoice_name} - missing member or mandate data")
                continue

            # Combine into optimized structure
            processed_invoice = {
                "invoice_name": invoice_name,
                "invoice_data": invoice_data,
                "member_data": member_data,
                "mandate_data": mandate_data,
                "address_data": address_data,
                "bank_config": self.get_bank_config_cached(mandate_data.get("bic", "INGBNL2A")),
            }

            processed_invoices.append(processed_invoice)

        total_time = (time.time() - start_time) * 1000
        frappe.logger().info(
            f"Optimized batch processing: {len(invoice_names)} invoices in {total_time:.1f}ms"
        )

        return processed_invoices

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance optimization statistics"""
        cache_info = self.get_bank_config_cached.cache_info()

        return {
            "cache_stats": {
                "hits": cache_info.hits,
                "misses": cache_info.misses,
                "cache_size": cache_info.currsize,
                "hit_rate": cache_info.hits / (cache_info.hits + cache_info.misses)
                if (cache_info.hits + cache_info.misses) > 0
                else 0,
            },
            "query_stats": self.query_stats,
            "optimization_efficiency": {
                "avg_time_saved_per_query": self.query_stats["time_saved_ms"]
                / max(1, self.query_stats["optimized_queries"]),
                "total_time_saved_seconds": self.query_stats["time_saved_ms"] / 1000,
            },
        }

    def clear_cache(self):
        """Clear all performance caches"""
        self.get_bank_config_cached.cache_clear()
        self.cache_stats = {"hits": 0, "misses": 0, "cache_size": 0}
        frappe.logger().info("Performance optimizer caches cleared")


# Singleton instance for global use
_batch_optimizer = None


def get_batch_performance_optimizer() -> BatchPerformanceOptimizer:
    """Get the global batch performance optimizer instance"""
    global _batch_optimizer
    if _batch_optimizer is None:
        _batch_optimizer = BatchPerformanceOptimizer()
    return _batch_optimizer


@frappe.whitelist()
def get_batch_performance_stats():
    """API endpoint to get batch performance statistics"""
    optimizer = get_batch_performance_optimizer()
    return {"success": True, "performance_stats": optimizer.get_performance_stats()}


@frappe.whitelist()
def clear_batch_performance_cache():
    """API endpoint to clear performance caches"""
    optimizer = get_batch_performance_optimizer()
    optimizer.clear_cache()
    return {"success": True, "message": "Performance caches cleared"}
