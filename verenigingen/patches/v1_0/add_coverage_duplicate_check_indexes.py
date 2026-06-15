"""
Add database indexes for invoice coverage duplicate detection performance

These indexes optimize the duplicate coverage detection queries in
Membership Dues Schedule invoice generation.
"""

import frappe


def execute():
    """Add indexes for Sales Invoice coverage duplicate detection"""

    # Index for exact duplicate and overlap detection
    # Supports queries filtering on customer + docstatus + coverage dates
    # Use sql_ddl(): CREATE INDEX autocommits in MariaDB, so running it through
    # frappe.db.sql() mid-migration raises ImplicitCommitError. sql_ddl() commits
    # the pending transaction first, then runs the DDL.
    frappe.db.sql_ddl(
        """
        CREATE INDEX IF NOT EXISTS idx_si_coverage_duplicate_check
        ON `tabSales Invoice` (
            customer,
            docstatus,
            custom_coverage_start_date,
            custom_coverage_end_date
        )
    """
    )

    # Index for latest coverage lookup
    # Supports queries finding most recent coverage for a customer
    # DESC on coverage_end_date allows efficient MAX() lookups
    frappe.db.sql_ddl(
        """
        CREATE INDEX IF NOT EXISTS idx_si_coverage_lookup
        ON `tabSales Invoice` (
            customer,
            docstatus,
            custom_coverage_end_date DESC
        )
    """
    )

    print("✓ Added coverage duplicate check indexes to Sales Invoice")
