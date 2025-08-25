#!/usr/bin/env python3
"""
Membership Coverage Analysis Debug Module
=========================================

Comprehensive debugging utilities for the membership dues coverage analysis system.
This module provides detailed diagnostic tools to troubleshoot and validate the
coverage analysis functionality, including database structure verification,
data integrity checks, and system integration testing.

Primary Purpose:
    Debug and validate the membership dues coverage analysis system by examining:
    - Database schema and custom field configurations
    - Sample data quality and relationships
    - Coverage calculation accuracy and performance

Key Features:
    * Database structure validation for coverage-related fields
    * Sample data analysis for members, memberships, and invoices
    * Coverage calculation function testing with real data
    * Integration workflow validation and error diagnosis
    * Detailed diagnostic reporting for troubleshooting

Coverage Analysis Components:
    * Sales Invoice custom coverage date fields verification
    * Member and membership relationship validation
    * Dues schedule configuration and status checking
    * Invoice-to-membership period mapping accuracy
    * Coverage gap identification and analysis

Usage Context:
    Used during development, testing, and production troubleshooting to:
    - Validate coverage analysis report functionality
    - Diagnose data quality issues affecting coverage calculations
    - Test performance of coverage analysis with real member data
    - Verify proper integration between membership and billing systems

Technical Implementation:
    Provides both simplified and comprehensive debugging functions that can be
    called via Frappe's whitelist API for real-time system diagnosis.
"""

import frappe
from frappe.utils import getdate, today


@frappe.whitelist()
def debug_coverage_analysis():
    """
    Perform simplified coverage analysis debugging with database structure validation.

    This streamlined debugging function focuses on core database structure verification
    for the membership coverage analysis system. It validates the presence and
    configuration of coverage-related database columns and custom fields.

    Diagnostic Areas:
        * Sales Invoice table structure examination
        * Coverage-related column detection and validation
        * Custom field configuration verification
        * Database schema compliance checking

    Returns:
        str: Formatted diagnostic report containing:
            - Database structure analysis results
            - Coverage column configuration details
            - Custom field presence verification
            - Schema compliance status

    Usage:
        Called via Frappe API for quick database structure validation:
        /api/method/verenigingen.debug_coverage.debug_coverage_analysis

    Note:
        This is the simplified version focusing on database structure.
        Use debug_coverage_analysis_original() for comprehensive data analysis.
    """

    results = []
    results.append("=== MEMBERSHIP DUES COVERAGE ANALYSIS DEBUGGING ===\n")

    # Check database structure first
    results.append("0. CHECKING DATABASE STRUCTURE:")
    results.append("-" * 50)

    try:
        # Get all columns from Sales Invoice table
        columns = frappe.db.sql(
            """
            DESCRIBE `tabSales Invoice`
        """,
            as_dict=True,
        )

        coverage_columns = []
        for col in columns:
            if "coverage" in col.Field.lower():
                coverage_columns.append(col)

        if coverage_columns:
            results.append(f"Found {len(coverage_columns)} coverage-related columns:")
            for col in coverage_columns:
                results.append(f"  - {col.Field}: {col.Type} (Null: {col.Null}, Default: {col.Default})")
        else:
            results.append("❌ No coverage-related columns found in Sales Invoice table!")

        # Show some custom columns
        custom_columns = [col for col in columns if col.Field.startswith("custom_")]
        results.append(f"\nCustom columns found: {len(custom_columns)}")
        if custom_columns:
            results.append("First 10 custom columns:")
            for col in custom_columns[:10]:
                results.append(f"  - {col.Field}: {col.Type}")

    except Exception as e:
        results.append(f"Error checking database structure: {e}")

    results.append("\n" + "=" * 60)


@frappe.whitelist()
def debug_coverage_analysis_original():
    """
    Comprehensive coverage analysis debugging with full data integrity validation.

    This comprehensive debugging function performs extensive validation of the entire
    membership dues coverage analysis system, including database structure, sample
    data quality, relationship integrity, and function testing with real data.

    Diagnostic Phases:
        1. Sales Invoice custom field validation and metadata analysis
        2. Member and membership relationship data quality checking
        3. Membership dues schedule configuration and status validation
        4. Sales invoice coverage data examination and integrity testing
        5. Core coverage calculation function testing with real member data

    Analysis Components:
        * Complete database schema and custom field verification
        * Sample member data examination with relationship validation
        * Active dues schedule configuration and billing frequency analysis
        * Invoice coverage date mapping and data quality assessment
        * End-to-end coverage calculation testing with real member scenarios

    Returns:
        str: Comprehensive diagnostic report containing:
            - Detailed database structure analysis
            - Sample data quality assessment with statistics
            - Relationship integrity validation results
            - Coverage calculation function test results
            - Detailed error diagnostics and troubleshooting guidance

    Usage:
        Called via Frappe API for comprehensive system diagnosis:
        /api/method/verenigingen.debug_coverage.debug_coverage_analysis_original

    Performance Note:
        This function performs extensive data analysis and may take longer
        to execute than the simplified debug_coverage_analysis() function.

    Error Handling:
        Includes comprehensive exception handling with detailed traceback
        information for troubleshooting integration issues.
    """

    results = []
    results.append("=== MEMBERSHIP DUES COVERAGE ANALYSIS DEBUGGING ===\n")

    # 1. Check Sales Invoice fields
    results.append("1. CHECKING SALES INVOICE CUSTOM FIELDS:")
    results.append("-" * 50)

    try:
        si_meta = frappe.get_meta("Sales Invoice")
        coverage_fields = [f for f in si_meta.get_fieldnames() if "coverage" in f.lower()]

        if coverage_fields:
            results.append(f"Found coverage fields: {coverage_fields}")
            for field in coverage_fields:
                field_obj = si_meta.get_field(field)
                results.append(f"  - {field}: {field_obj.fieldtype} ({field_obj.label})")
        else:
            results.append("❌ No coverage fields found in Sales Invoice!")

        # Check if custom fields exist
        custom_coverage_start = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
        custom_coverage_end = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

        results.append(f"custom_coverage_start_date exists: {custom_coverage_start}")
        results.append(f"custom_coverage_end_date exists: {custom_coverage_end}")

    except Exception as e:
        results.append(f"Error checking Sales Invoice fields: {e}")

    results.append("\n" + "=" * 60)

    # 2. Check sample Members
    results.append("2. CHECKING SAMPLE MEMBER DATA:")
    results.append("-" * 50)

    try:
        sample_members = frappe.db.sql(
            """
            SELECT
                m.name, m.full_name, m.status, m.customer,
                mb.name as membership_name, mb.start_date, mb.cancellation_date, mb.status as membership_status
            FROM `tabMember` m
            LEFT JOIN `tabMembership` mb ON mb.member = m.name AND mb.docstatus = 1
            WHERE m.status = 'Active'
            LIMIT 5
        """,
            as_dict=True,
        )

        if sample_members:
            results.append(f"Found {len(sample_members)} sample members:")
            for member in sample_members:
                results.append(f"  - {member.name} ({member.full_name})")
                results.append(f"    Customer: {member.customer}")
                results.append(
                    f"    Membership: {member.current_membership_type} ({member.membership_status})"
                )
                results.append(
                    f"    Period: {member.current_membership_start} to {member.current_membership_end or 'Active'}"
                )
                results.append("")
        else:
            results.append("❌ No active members found!")

    except Exception as e:
        results.append(f"Error checking member data: {e}")

    results.append("=" * 60)

    # 3. Check Membership Dues Schedule data
    results.append("3. CHECKING MEMBERSHIP DUES SCHEDULE DATA:")
    results.append("-" * 50)

    try:
        dues_schedules = frappe.db.sql(
            """
            SELECT
                mds.name, mds.member, mds.billing_frequency, mds.dues_rate,
                mds.status, mds.last_invoice_date, mds.next_invoice_date
            FROM `tabMembership Dues Schedule` mds
            WHERE mds.status = 'Active'
            LIMIT 5
        """,
            as_dict=True,
        )

        if dues_schedules:
            results.append(f"Found {len(dues_schedules)} active dues schedules:")
            for schedule in dues_schedules:
                results.append(f"  - {schedule.name} (Member: {schedule.member})")
                results.append(f"    Frequency: {schedule.billing_frequency}, Rate: €{schedule.dues_rate}")
                results.append(
                    f"    Last Invoice: {schedule.last_invoice_date}, Next: {schedule.next_invoice_date}"
                )
                results.append("")
        else:
            results.append("❌ No active dues schedules found!")

    except Exception as e:
        results.append(f"Error checking dues schedule data: {e}")

    results.append("=" * 60)

    # 4. Check sample Sales Invoices
    results.append("4. CHECKING SAMPLE SALES INVOICE DATA:")
    results.append("-" * 50)

    try:
        # First check if any invoices exist
        invoice_count = frappe.db.count("Sales Invoice", {"docstatus": 1})
        results.append(f"Total submitted Sales Invoices: {invoice_count}")

        if invoice_count > 0:
            # Check for invoices with coverage dates
            if frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date"):
                coverage_invoices = frappe.db.sql(
                    """
                    SELECT
                        name, customer, posting_date, grand_total,
                        custom_coverage_start_date, custom_coverage_end_date
                    FROM `tabSales Invoice`
                    WHERE docstatus = 1
                    AND custom_coverage_start_date IS NOT NULL
                    LIMIT 5
                """,
                    as_dict=True,
                )

                results.append(f"Invoices with coverage dates: {len(coverage_invoices)}")

                if coverage_invoices:
                    for invoice in coverage_invoices:
                        results.append(f"  - {invoice.name} ({invoice.customer})")
                        results.append(
                            f"    Coverage: {invoice.custom_coverage_start_date} to {invoice.custom_coverage_end_date}"
                        )
                        results.append(f"    Amount: €{invoice.grand_total}")
                        results.append("")
                else:
                    results.append("❌ No invoices found with coverage dates!")
            else:
                results.append("❌ Custom coverage fields don't exist in Sales Invoice table!")

            # Check some sample invoices without coverage
            sample_invoices = frappe.db.sql(
                """
                SELECT name, customer, posting_date, grand_total
                FROM `tabSales Invoice`
                WHERE docstatus = 1
                LIMIT 3
            """,
                as_dict=True,
            )

            if sample_invoices:
                results.append("Sample invoices (checking for customer links):")
                for invoice in sample_invoices:
                    results.append(f"  - {invoice.name} ({invoice.customer}) - €{invoice.grand_total}")

    except Exception as e:
        results.append(f"Error checking invoice data: {e}")

    results.append("\n" + "=" * 60)

    # 5. Test key functions with a specific member
    results.append("5. TESTING KEY FUNCTIONS:")
    results.append("-" * 50)

    try:
        # Get one sample member
        sample_member = frappe.db.get_value("Member", {"status": "Active"}, "name")

        if sample_member:
            results.append(f"Testing with member: {sample_member}")

            # Test get_membership_periods directly
            from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                get_membership_periods,
            )

            periods = get_membership_periods(sample_member)
            results.append(f"Membership periods found: {len(periods)}")

            for i, (start, end) in enumerate(periods):
                results.append(f"  Period {i + 1}: {start} to {end}")

            if periods:
                # Test get_member_invoices_with_coverage
                from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                    get_member_invoices_with_coverage,
                )

                member_doc = frappe.get_doc("Member", sample_member)
                if member_doc.customer:
                    invoices = get_member_invoices_with_coverage(member_doc.customer)
                    results.append(f"Invoices with coverage found: {len(invoices)}")

                    for invoice in invoices[:3]:  # Show first 3
                        results.append(
                            f"  - {invoice.invoice}: {invoice.coverage_start} to {invoice.coverage_end}"
                        )
                else:
                    results.append("❌ Member has no customer record!")

                # Test calculate_coverage_timeline
                from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                    calculate_coverage_timeline,
                )

                coverage_analysis = calculate_coverage_timeline(sample_member)
                stats = coverage_analysis["stats"]
                results.append("\nCoverage Analysis Results:")
                results.append(f"  - Total Active Days: {stats['total_active_days']}")
                results.append(f"  - Covered Days: {stats['covered_days']}")
                results.append(f"  - Gap Days: {stats['gap_days']}")
                results.append(f"  - Coverage %: {stats['coverage_percentage']:.1f}%")

            else:
                results.append("❌ No membership periods found!")

        else:
            results.append("❌ No active members found for testing!")

    except Exception as e:
        results.append(f"Error testing functions: {e}")
        import traceback

        results.append(traceback.format_exc())

    # Return all results
    return "\n".join(results)


if __name__ == "__main__":
    print(debug_coverage_analysis())
