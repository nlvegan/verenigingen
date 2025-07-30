#!/usr/bin/env python3

import sys

import frappe
from frappe.utils import getdate, today


def debug_coverage_analysis():
    """Debug the coverage analysis by checking data structures and sample data"""

    print("=== MEMBERSHIP DUES COVERAGE ANALYSIS DEBUGGING ===\n")

    # 1. Check Sales Invoice fields
    print("1. CHECKING SALES INVOICE CUSTOM FIELDS:")
    print("-" * 50)

    try:
        si_meta = frappe.get_meta("Sales Invoice")
        coverage_fields = [f for f in si_meta.get_fieldnames() if "coverage" in f.lower()]

        if coverage_fields:
            print(f"Found coverage fields: {coverage_fields}")
            for field in coverage_fields:
                field_obj = si_meta.get_field(field)
                print(f"  - {field}: {field_obj.fieldtype} ({field_obj.label})")
        else:
            print("❌ No coverage fields found in Sales Invoice!")

        # Check if custom fields exist
        custom_coverage_start = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
        custom_coverage_end = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

        print(f"custom_coverage_start_date exists: {custom_coverage_start}")
        print(f"custom_coverage_end_date exists: {custom_coverage_end}")

    except Exception as e:
        print(f"Error checking Sales Invoice fields: {e}")

    print("\n" + "=" * 60)

    # 2. Check sample Members
    print("2. CHECKING SAMPLE MEMBER DATA:")
    print("-" * 50)

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
            print(f"Found {len(sample_members)} sample members:")
            for member in sample_members:
                print(f"  - {member.name} ({member.full_name})")
                print(f"    Customer: {member.customer}")
                print(f"    Membership: {member.membership_name} ({member.membership_status})")
                print(f"    Period: {member.start_date} to {member.cancellation_date or 'Active'}")
                print()
        else:
            print("❌ No active members found!")

    except Exception as e:
        print(f"Error checking member data: {e}")

    print("=" * 60)

    # 3. Check sample Sales Invoices
    print("3. CHECKING SAMPLE SALES INVOICE DATA:")
    print("-" * 50)

    try:
        # First check if any invoices exist
        invoice_count = frappe.db.count("Sales Invoice", {"docstatus": 1})
        print(f"Total submitted Sales Invoices: {invoice_count}")

        if invoice_count > 0:
            # Check for invoices with coverage dates
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

            print(f"Invoices with coverage dates: {len(coverage_invoices)}")

            if coverage_invoices:
                for invoice in coverage_invoices:
                    print(f"  - {invoice.name} ({invoice.customer})")
                    print(
                        f"    Coverage: {invoice.custom_coverage_start_date} to {invoice.custom_coverage_end_date}"
                    )
                    print(f"    Amount: €{invoice.grand_total}")
                    print()
            else:
                print("❌ No invoices found with coverage dates!")

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

                print("Sample invoices without coverage dates:")
                for invoice in sample_invoices:
                    print(f"  - {invoice.name} ({invoice.customer}) - €{invoice.grand_total}")

    except Exception as e:
        print(f"Error checking invoice data: {e}")

    print("\n" + "=" * 60)

    # 4. Test key functions
    print("4. TESTING KEY FUNCTIONS:")
    print("-" * 50)

    try:
        # Get one sample member
        sample_member = frappe.db.get_value("Member", {"status": "Active"}, "name")

        if sample_member:
            print(f"Testing with member: {sample_member}")

            # Test get_membership_periods
            from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                get_membership_periods,
            )

            periods = get_membership_periods(sample_member)
            print(f"Membership periods found: {len(periods)}")

            for i, (start, end) in enumerate(periods):
                print(f"  Period {i+1}: {start} to {end}")

            if periods:
                # Test get_member_invoices_with_coverage
                from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                    get_member_invoices_with_coverage,
                )

                member_doc = frappe.get_doc("Member", sample_member)
                if member_doc.customer:
                    invoices = get_member_invoices_with_coverage(member_doc.customer)
                    print(f"Invoices with coverage found: {len(invoices)}")

                    for invoice in invoices:
                        print(f"  - {invoice.invoice}: {invoice.coverage_start} to {invoice.coverage_end}")
                else:
                    print("❌ Member has no customer record!")
            else:
                print("❌ No membership periods found!")

        else:
            print("❌ No active members found for testing!")

    except Exception as e:
        print(f"Error testing functions: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_coverage_analysis()
