#!/usr/bin/env python3
"""
Optimized Query Utilities for Verenigingen App
Database Query Performance Optimization - Problem #1

This module provides optimized query functions that replace N+1 query patterns
with efficient bulk operations, joins, and caching strategies.

Based on analysis of 4,111+ individual database calls causing performance issues,
this module targets the major bottlenecks:
1. Member payment history loading
2. Payment entry/invoice processing
3. Volunteer assignment aggregation
4. SEPA mandate processing
5. Chapter management operations

Performance Goals:
- Replace individual frappe.get_doc() calls with bulk operations
- Implement strategic caching for frequently accessed data
- Use database joins instead of Python loops for related data
- Reduce database calls by 70-80% for core operations
"""

import json
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime, getdate, now, nowdate


class OptimizedMemberQueries:
    """Optimized queries for Member DocType operations"""

    @staticmethod
    @frappe.whitelist()
    def get_members_with_payment_data(filters: Dict = None) -> List[Dict]:
        """
        Optimized bulk loading of members with payment data

        Replaces N+1 pattern in member_utils.py:134-140 where individual
        frappe.get_doc() calls were made for each member.

        Returns members with pre-loaded payment history and customer data.
        """

        if filters is None:
            filters = {}

        # Build base query with joins
        query = """
        SELECT
            m.name as member_name,
            m.full_name,
            m.status as member_status,
            m.customer,
            m.member_since,
            m.mollie_customer_id,
            m.mollie_subscription_id,
            m.subscription_status,
            c.name as customer_name,
            c.customer_name as customer_display_name,
            COUNT(DISTINCT si.name) as invoice_count,
            COUNT(DISTINCT pe.name) as payment_count,
            SUM(CASE WHEN si.docstatus = 1 AND si.outstanding_amount > 0 THEN si.outstanding_amount ELSE 0 END) as total_outstanding,
            MAX(pe.posting_date) as last_payment_date,
            MAX(si.posting_date) as last_invoice_date
        FROM `tabMember` m
        LEFT JOIN `tabCustomer` c ON m.customer = c.name
        LEFT JOIN `tabSales Invoice` si ON c.name = si.customer AND si.docstatus = 1
        LEFT JOIN `tabPayment Entry` pe ON c.name = pe.party AND pe.party_type = 'Customer' AND pe.docstatus = 1
        WHERE m.docstatus < 2
        """

        # Apply filters
        filter_conditions = []
        filter_values = []

        if filters.get("status"):
            filter_conditions.append("m.status = %s")
            filter_values.append(filters["status"])

        if filters.get("customer"):
            filter_conditions.append("m.customer = %s")
            filter_values.append(filters["customer"])

        if filters.get("member_since_after"):
            filter_conditions.append("m.member_since >= %s")
            filter_values.append(filters["member_since_after"])

        if filter_conditions:
            query += " AND " + " AND ".join(filter_conditions)

        query += """
        GROUP BY m.name, m.full_name, m.status, m.customer, m.member_since,
                 m.mollie_customer_id, m.mollie_subscription_id,
                 m.subscription_status, c.name, c.customer_name
        ORDER BY m.modified DESC
        """

        return frappe.db.sql(query, filter_values, as_dict=True)

    @staticmethod
    @frappe.whitelist()
    def bulk_update_payment_history(member_names: List[str]) -> Dict[str, Any]:
        """
        Optimized bulk payment history update

        Replaces the N+1 pattern where each member's payment history
        was loaded and updated individually.

        Args:
            member_names: List of member names to update

        Returns:
            Dict with update statistics and any errors
        """

        if not member_names:
            return {"success": True, "updated_count": 0}

        results = {"success": True, "updated_count": 0, "errors": []}

        try:
            # Get all payment history data in one query using joins
            payment_history_query = """
            SELECT
                m.name as member_name,
                si.name as invoice_name,
                si.posting_date,
                si.due_date,
                si.grand_total,
                si.outstanding_amount,
                si.status as invoice_status,
                pe.name as payment_name,
                pe.posting_date as payment_date,
                pe.paid_amount,
                per.allocated_amount,
                CASE
                    WHEN si.outstanding_amount <= 0 THEN 'Paid'
                    WHEN si.due_date < CURDATE() THEN 'Overdue'
                    ELSE 'Unpaid'
                END as payment_status
            FROM `tabMember` m
            LEFT JOIN `tabCustomer` c ON m.customer = c.name
            LEFT JOIN `tabSales Invoice` si ON c.name = si.customer AND si.docstatus = 1
            LEFT JOIN `tabPayment Entry Reference` per ON si.name = per.reference_name AND per.reference_doctype = 'Sales Invoice'
            LEFT JOIN `tabPayment Entry` pe ON per.parent = pe.name AND pe.docstatus = 1
            WHERE m.name IN ({placeholders})
            ORDER BY m.name, si.posting_date DESC, pe.posting_date DESC
            """.format(
                placeholders=",".join(["%s"] * len(member_names))
            )

            payment_data = frappe.db.sql(payment_history_query, member_names, as_dict=True)

            # Group payment data by member
            member_payment_data = {}
            for row in payment_data:
                member_name = row["member_name"]
                if member_name not in member_payment_data:
                    member_payment_data[member_name] = []
                member_payment_data[member_name].append(row)

            # Bulk update member payment history child tables
            frappe.db.begin()  # Start transaction
            try:
                for member_name in member_names:
                    try:
                        member_payments = member_payment_data.get(member_name, [])
                        OptimizedMemberQueries._update_member_payment_history_bulk(
                            member_name, member_payments
                        )
                        results["updated_count"] += 1

                    except Exception as e:
                        error_msg = f"Failed to update payment history for member {member_name}: {str(e)}"
                        frappe.log_error(error_msg)
                        results["errors"].append(error_msg)
                        raise  # Re-raise to trigger rollback

                frappe.db.commit()  # Commit only if all updates succeed

            except Exception:
                frappe.db.rollback()  # Rollback on any failure
                raise

        except Exception as e:
            results["success"] = False
            results["error"] = str(e)
            frappe.log_error(f"Bulk payment history update failed: {str(e)}")

        return results

    @staticmethod
    def _update_member_payment_history_bulk(member_name: str, payment_data: List[Dict]):
        """Update a single member's payment history using bulk data"""

        try:
            # Delete existing payment history records for this member
            frappe.db.delete("Member Payment History", {"parent": member_name})

            # Prepare bulk insert data
            history_records = []

            # Process payment data and create history records
            processed_invoices = set()

            for row in payment_data:
                if not row.get("invoice_name") or row["invoice_name"] in processed_invoices:
                    continue

                processed_invoices.add(row["invoice_name"])

                history_record = {
                    "doctype": "Member Payment History",
                    "parent": member_name,
                    "parenttype": "Member",
                    "parentfield": "payment_history",
                    "reference_doctype": "Sales Invoice",
                    "reference_name": row["invoice_name"],
                    "posting_date": row["posting_date"],
                    "due_date": row["due_date"],
                    "invoice_amount": flt(row["grand_total"]),
                    "outstanding_amount": flt(row["outstanding_amount"]),
                    "payment_status": row["payment_status"],
                    "payment_date": row.get("payment_date"),
                    "amount_paid": flt(row.get("allocated_amount", 0)),
                }

                history_records.append(history_record)

            # Bulk insert payment history records
            if history_records:
                for record in history_records:
                    frappe.get_doc(record).insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(f"Failed to update payment history for member {member_name}: {str(e)}")
            raise

    @staticmethod
    @frappe.whitelist()
    def get_member_financial_summary(member_names: List[str]) -> Dict[str, Dict]:
        """
        Get financial summary for multiple members in one query

        Replaces individual queries for member financial data.
        """

        if not member_names:
            return {}

        # Single query to get financial summary for all members
        query = """
        SELECT
            m.name as member_name,
            COUNT(DISTINCT si.name) as total_invoices,
            COUNT(DISTINCT CASE WHEN si.outstanding_amount > 0 THEN si.name END) as unpaid_invoices,
            SUM(CASE WHEN si.docstatus = 1 THEN si.grand_total ELSE 0 END) as total_invoiced,
            SUM(CASE WHEN si.docstatus = 1 AND si.outstanding_amount > 0 THEN si.outstanding_amount ELSE 0 END) as total_outstanding,
            SUM(CASE WHEN pe.docstatus = 1 THEN pe.paid_amount ELSE 0 END) as total_paid,
            MAX(pe.posting_date) as last_payment_date,
            MAX(si.posting_date) as last_invoice_date,
            COUNT(DISTINCT sm.name) as active_mandates
        FROM `tabMember` m
        LEFT JOIN `tabCustomer` c ON m.customer = c.name
        LEFT JOIN `tabSales Invoice` si ON c.name = si.customer AND si.docstatus = 1
        LEFT JOIN `tabPayment Entry` pe ON c.name = pe.party AND pe.party_type = 'Customer' AND pe.docstatus = 1
        LEFT JOIN `tabSEPA Mandate` sm ON m.name = sm.member AND sm.status = 'Active'
        WHERE m.name IN ({placeholders})
        GROUP BY m.name
        """.format(
            placeholders=",".join(["%s"] * len(member_names))
        )

        results = frappe.db.sql(query, member_names, as_dict=True)

        # Convert to dict keyed by member name
        return {row["member_name"]: row for row in results}


class OptimizedVolunteerQueries:
    """Optimized queries for Volunteer DocType operations"""

    @staticmethod
    @frappe.whitelist()
    def get_volunteer_assignments_bulk(volunteer_names: List[str]) -> Dict[str, List[Dict]]:
        """
        Optimized bulk loading of volunteer assignments

        Replaces N+1 pattern in volunteer.py where individual queries
        were made for board assignments, team assignments, and activities.

        Returns all assignment data in optimized bulk queries.
        """

        if not volunteer_names:
            return {}

        assignments_by_volunteer = {}

        # Initialize result structure
        for vol_name in volunteer_names:
            assignments_by_volunteer[vol_name] = []

        try:
            # Single query for all assignment types using UNION
            assignments_query = """
            SELECT
                v.name as volunteer_name,
                'Board' as assignment_type,
                'Chapter Board Member' as source_type,
                'Chapter' as source_doctype,
                cbm.chapter as source_name,
                c.chapter_name as source_name_display,
                cbm.position as role,
                cbm.start_date,
                cbm.end_date,
                CASE WHEN cbm.end_date IS NULL OR cbm.end_date >= CURDATE() THEN 1 ELSE 0 END as is_active,
                0 as editable
            FROM `tabVolunteer` v
            LEFT JOIN `tabMember` m ON v.member = m.name
            LEFT JOIN `tabChapter Board Member` cbm ON m.name = cbm.member
            LEFT JOIN `tabChapter` c ON cbm.chapter = c.name
            WHERE v.name IN ({placeholders}) AND cbm.name IS NOT NULL

            UNION ALL

            SELECT
                v.name as volunteer_name,
                'Team' as assignment_type,
                'Team Member' as source_type,
                'Team' as source_doctype,
                tm.team as source_name,
                t.team_name as source_name_display,
                tm.role,
                tm.start_date,
                tm.end_date,
                CASE WHEN tm.end_date IS NULL OR tm.end_date >= CURDATE() THEN 1 ELSE 0 END as is_active,
                0 as editable
            FROM `tabVolunteer` v
            LEFT JOIN `tabMember` m ON v.member = m.name
            LEFT JOIN `tabTeam Member` tm ON m.name = tm.member
            LEFT JOIN `tabTeam` t ON tm.team = t.name
            WHERE v.name IN ({placeholders_2}) AND tm.name IS NOT NULL

            UNION ALL

            SELECT
                v.name as volunteer_name,
                'Activity' as assignment_type,
                'Volunteer Activity' as source_type,
                'Volunteer Activity' as source_doctype,
                va.name as source_name,
                va.activity_type as source_name_display,
                va.role,
                va.start_date,
                va.end_date,
                CASE WHEN va.end_date IS NULL OR va.end_date >= CURDATE() THEN 1 ELSE 0 END as is_active,
                1 as editable
            FROM `tabVolunteer` v
            LEFT JOIN `tabVolunteer Activity` va ON v.name = va.volunteer
            WHERE v.name IN ({placeholders_3}) AND va.name IS NOT NULL

            ORDER BY volunteer_name, start_date DESC
            """.format(
                placeholders=",".join(["%s"] * len(volunteer_names)),
                placeholders_2=",".join(["%s"] * len(volunteer_names)),
                placeholders_3=",".join(["%s"] * len(volunteer_names)),
            )

            query_params = volunteer_names * 3  # Same list 3 times for UNION queries

            assignments = frappe.db.sql(assignments_query, query_params, as_dict=True)

            # Group assignments by volunteer
            for assignment in assignments:
                volunteer_name = assignment["volunteer_name"]
                if volunteer_name in assignments_by_volunteer:
                    assignments_by_volunteer[volunteer_name].append(assignment)

        except Exception as e:
            frappe.log_error(f"Failed to load volunteer assignments: {str(e)}")

        return assignments_by_volunteer


class OptimizedSEPAQueries:
    """Optimized queries for SEPA Mandate operations"""

    @staticmethod
    @frappe.whitelist()
    def get_active_mandates_for_members(member_names: List[str]) -> Dict[str, Dict]:
        """
        Optimized bulk loading of active SEPA mandates for members

        Replaces N+1 pattern in member_utils.py where individual
        frappe.get_doc() calls were made for each mandate.
        """

        if not member_names:
            return {}

        # Single query to get active mandates for all members
        query = """
        SELECT
            sm.member,
            sm.name as mandate_name,
            sm.mandate_reference,
            sm.status,
            sm.sign_date,
            sm.first_collection_date,
            sm.expiry_date,
            sm.mandate_type,
            sm.bank_name,
            sm.iban,
            sm.account_holder_name,
            sm.is_default
        FROM `tabSEPA Mandate` sm
        WHERE sm.member IN ({placeholders})
        AND sm.status = 'Active'
        AND sm.docstatus = 1
        ORDER BY sm.member, sm.is_default DESC, sm.sign_date DESC
        """.format(
            placeholders=",".join(["%s"] * len(member_names))
        )

        results = frappe.db.sql(query, member_names, as_dict=True)

        # Group by member, taking the first (default/most recent) mandate
        mandates_by_member = {}
        for result in results:
            member = result["member"]
            if member not in mandates_by_member:
                mandates_by_member[member] = result

        return mandates_by_member

    @staticmethod
    @frappe.whitelist()
    def bulk_update_mandate_payment_history(mandate_names: List[str], payment_entries: List[str]) -> Dict:
        """
        Bulk update SEPA mandate payment history

        Optimizes the individual mandate update pattern.
        """

        if not mandate_names or not payment_entries:
            return {"success": True, "updated_count": 0}

        results = {"success": True, "updated_count": 0, "errors": []}

        try:
            # Bulk update mandate last payment dates
            for mandate_name in mandate_names:
                try:
                    # Get latest payment date for this mandate's member
                    latest_payment_query = """
                    SELECT MAX(pe.posting_date) as latest_payment
                    FROM `tabPayment Entry` pe
                    INNER JOIN `tabSEPA Mandate` sm ON pe.party = (
                        SELECT m.customer FROM `tabMember` m WHERE m.name = sm.member
                    )
                    WHERE sm.name = %s AND pe.docstatus = 1
                    """

                    latest_payment = frappe.db.sql(latest_payment_query, [mandate_name], as_dict=True)

                    if latest_payment and latest_payment[0]["latest_payment"]:
                        frappe.db.set_value(
                            "SEPA Mandate",
                            mandate_name,
                            "last_payment_date",
                            latest_payment[0]["latest_payment"],
                        )
                        results["updated_count"] += 1

                except Exception as e:
                    error_msg = f"Failed to update mandate {mandate_name}: {str(e)}"
                    results["errors"].append(error_msg)
                    frappe.log_error(error_msg)

            frappe.db.commit()

        except Exception as e:
            results["success"] = False
            results["error"] = str(e)
            frappe.log_error(f"Bulk mandate update failed: {str(e)}")

        return results


class OptimizedChapterQueries:
    """Optimized queries for Chapter operations"""

    @staticmethod
    @frappe.whitelist()
    def get_chapter_assignments_bulk(postal_codes: List[str]) -> Dict[str, str]:
        """
        Optimized bulk chapter assignment by postal codes

        Replaces N+1 pattern in member_utils.py:512-514 where individual
        frappe.get_doc() calls were made for each chapter.
        """

        if not postal_codes:
            return {}

        # Single query to match all postal codes to chapters
        query = """
        SELECT DISTINCT
            postal_code,
            c.name as chapter_name,
            c.chapter_name as chapter_display_name
        FROM (
            SELECT %s as postal_code
        ) pc
        CROSS JOIN `tabChapter` c
        WHERE c.status = 'Active'
        AND c.docstatus < 2
        AND (
            c.postal_codes IS NOT NULL
            AND c.postal_codes != ''
            AND FIND_IN_SET(pc.postal_code, REPLACE(c.postal_codes, ' ', '')) > 0
        )
        ORDER BY c.priority DESC, c.name
        """

        # Execute query for each postal code (could be optimized further with VALUES clause)
        chapter_assignments = {}

        for postal_code in postal_codes:
            results = frappe.db.sql(query, [postal_code], as_dict=True)
            if results:
                # Take the first (highest priority) chapter
                chapter_assignments[postal_code] = results[0]["chapter_name"]

        return chapter_assignments


# Caching utilities
class QueryCache:
    """Strategic caching for frequently accessed data"""

    # Cache timeouts in seconds
    MEMBER_DATA_TIMEOUT = 300  # 5 minutes
    VOLUNTEER_DATA_TIMEOUT = 600  # 10 minutes
    SEPA_DATA_TIMEOUT = 900  # 15 minutes
    CHAPTER_DATA_TIMEOUT = 1800  # 30 minutes

    @staticmethod
    def get_cached_member_data(member_name: str) -> Optional[Dict]:
        """Get cached member data if available"""
        cache_key = f"member_data:{member_name}"
        return frappe.cache().get_value(cache_key)

    @staticmethod
    def set_cached_member_data(member_name: str, data: Dict):
        """Cache member data"""
        cache_key = f"member_data:{member_name}"
        frappe.cache().set_value(cache_key, data, expires_in_sec=QueryCache.MEMBER_DATA_TIMEOUT)

    @staticmethod
    def invalidate_member_cache(member_name: str):
        """Invalidate cached member data"""
        cache_key = f"member_data:{member_name}"
        frappe.cache().delete_value(cache_key)

    @staticmethod
    def get_cached_volunteer_assignments(volunteer_name: str) -> Optional[List[Dict]]:
        """Get cached volunteer assignments if available"""
        cache_key = f"volunteer_assignments:{volunteer_name}"
        return frappe.cache().get_value(cache_key)

    @staticmethod
    def set_cached_volunteer_assignments(volunteer_name: str, assignments: List[Dict]):
        """Cache volunteer assignments"""
        cache_key = f"volunteer_assignments:{volunteer_name}"
        frappe.cache().set_value(cache_key, assignments, expires_in_sec=QueryCache.VOLUNTEER_DATA_TIMEOUT)


# Utility functions for replacing existing N+1 patterns
@frappe.whitelist()
def optimize_member_payment_history_update(payment_entry_name: str) -> Dict:
    """
    Drop-in replacement for the N+1 payment history update pattern

    Can be called from existing hooks to provide immediate performance improvement
    without changing the existing API.
    """

    try:
        # Get the payment entry
        payment_doc = frappe.get_doc("Payment Entry", payment_entry_name)

        if payment_doc.party_type != "Customer":
            return {"success": True, "message": "Not a customer payment"}

        # Find all affected members
        member_names = frappe.get_all("Member", filters={"customer": payment_doc.party}, fields=["name"])

        if not member_names:
            return {"success": True, "message": "No members found for customer"}

        member_name_list = [m.name for m in member_names]

        # Use optimized bulk update
        result = OptimizedMemberQueries.bulk_update_payment_history(member_name_list)

        return result

    except Exception as e:
        frappe.log_error(f"Optimized payment history update failed for {payment_entry_name}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def optimize_volunteer_assignment_loading(volunteer_name: str) -> List[Dict]:
    """
    Drop-in replacement for individual volunteer assignment loading

    Can replace existing get_aggregated_assignments method calls.
    """

    try:
        # Check cache first
        cached_assignments = QueryCache.get_cached_volunteer_assignments(volunteer_name)
        if cached_assignments:
            return cached_assignments

        # Use optimized bulk query
        assignments_data = OptimizedVolunteerQueries.get_volunteer_assignments_bulk([volunteer_name])
        assignments = assignments_data.get(volunteer_name, [])

        # Cache the result
        QueryCache.set_cached_volunteer_assignments(volunteer_name, assignments)

        return assignments

    except Exception as e:
        frappe.log_error(f"Optimized volunteer assignment loading failed for {volunteer_name}: {str(e)}")
        return []
