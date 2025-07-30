#!/usr/bin/env python3

import frappe
from frappe.utils import getdate, today


@frappe.whitelist()
def debug_coverage_analysis():
    """Debug the coverage analysis by checking data structures and sample data"""

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
    """Debug the coverage analysis by checking data structures and sample data"""

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
                results.append(f"    Membership: {member.membership_name} ({member.membership_status})")
                results.append(f"    Period: {member.start_date} to {member.cancellation_date or 'Active'}")
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
                results.append(f"  Period {i+1}: {start} to {end}")

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
                results.append(f"\nCoverage Analysis Results:")
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
