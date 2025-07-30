#!/usr/bin/env python3
"""
Comprehensive Membership Dues Coverage Analysis Debugger

This script performs deep analysis of the Membership Dues Coverage Analysis report
to identify why it's returning zero values for all coverage metrics.

Usage:
    bench --site dev.veganisme.net execute verenigingen.utils.debug_coverage_analysis.run_full_debug
"""

import json
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, date_diff, flt, getdate, today


@frappe.whitelist()
def run_full_debug():
    """Run comprehensive debugging of the coverage analysis system"""

    results = []
    results.append("=" * 80)
    results.append("MEMBERSHIP DUES COVERAGE ANALYSIS - COMPREHENSIVE DEBUGGER")
    results.append("=" * 80)
    results.append(f"Timestamp: {datetime.now()}")
    results.append("")

    try:
        # Phase 1: Database Structure Analysis
        results.extend(debug_database_structure())

        # Phase 2: Sample Data Analysis
        results.extend(debug_sample_data())

        # Phase 3: Function Testing
        results.extend(debug_function_flow())

        # Phase 4: Specific Issue Identification
        results.extend(debug_coverage_field_issues())

        # Phase 5: Proposed Solutions
        results.extend(generate_solution_recommendations())

    except Exception as e:
        results.append(f"\n❌ CRITICAL ERROR in debugger: {e}")
        import traceback

        results.append(traceback.format_exc())

    return "\n".join(results)


def debug_database_structure():
    """Phase 1: Analyze database structure and field existence"""

    results = []
    results.append("PHASE 1: DATABASE STRUCTURE ANALYSIS")
    results.append("-" * 50)

    # Check Sales Invoice table structure
    try:
        # Get all columns in Sales Invoice table
        columns = frappe.db.sql("DESCRIBE `tabSales Invoice`", as_dict=True)
        total_columns = len(columns)
        results.append(f"✓ Sales Invoice table exists with {total_columns} columns")

        # Check for coverage-related fields
        coverage_fields = [col for col in columns if "coverage" in col["Field"].lower()]
        custom_fields = [col for col in columns if col["Field"].startswith("custom_")]

        results.append(f"✓ Found {len(custom_fields)} custom fields in Sales Invoice")
        results.append(f"✓ Found {len(coverage_fields)} coverage-related fields")

        # Check specific fields the report needs
        required_fields = ["custom_coverage_start_date", "custom_coverage_end_date"]
        missing_fields = []

        for field in required_fields:
            has_field = frappe.db.has_column("tabSales Invoice", field)
            if has_field:
                results.append(f"✓ Field exists: {field}")
            else:
                results.append(f"❌ MISSING FIELD: {field}")
                missing_fields.append(field)

        # Show custom fields that do exist
        if custom_fields:
            results.append(f"\nFound custom fields (first 15):")
            for col in custom_fields[:15]:
                results.append(f"  - {col['Field']} ({col['Type']})")

        # Show coverage-related fields
        if coverage_fields:
            results.append(f"\nCoverage-related fields:")
            for col in coverage_fields:
                results.append(f"  - {col['Field']} ({col['Type']})")

        if missing_fields:
            results.append(f"\n❌ CRITICAL: Missing {len(missing_fields)} required fields!")

    except Exception as e:
        results.append(f"❌ Error checking Sales Invoice structure: {e}")

    # Check other important tables
    important_tables = ["tabMember", "tabMembership", "tabMembership Dues Schedule"]
    for table in important_tables:
        try:
            count = frappe.db.count(table.replace("tab", ""))
            results.append(f"✓ {table}: {count} records")
        except Exception as e:
            results.append(f"❌ Error checking {table}: {e}")

    results.append("")
    return results


def debug_sample_data():
    """Phase 2: Analyze sample data quality and relationships"""

    results = []
    results.append("PHASE 2: SAMPLE DATA ANALYSIS")
    results.append("-" * 50)

    try:
        # Get sample active members with customers
        sample_members = frappe.db.sql(
            """
            SELECT m.name, m.first_name, m.last_name, m.status, m.customer,
                   mb.start_date, mb.cancellation_date, mb.status as membership_status
            FROM `tabMember` m
            LEFT JOIN `tabMembership` mb ON mb.member = m.name AND mb.docstatus = 1
            WHERE m.status = 'Active' AND m.customer IS NOT NULL
            ORDER BY m.creation DESC
            LIMIT 5
        """,
            as_dict=True,
        )

        results.append(f"✓ Found {len(sample_members)} active members with customers")

        for i, member in enumerate(sample_members):
            results.append(f"\nMember {i+1}: {member.name}")
            results.append(f"  - Name: {member.first_name} {member.last_name or ''}")
            results.append(f"  - Customer: {member.customer}")
            results.append(f"  - Status: {member.status}")
            results.append(f"  - Membership: {member.start_date} to {member.cancellation_date or 'Active'}")

            # Check invoices for this customer
            if member.customer:
                invoices = frappe.db.sql(
                    """
                    SELECT name, posting_date, grand_total, status, outstanding_amount
                    FROM `tabSales Invoice`
                    WHERE customer = %s AND docstatus = 1
                    ORDER BY posting_date DESC
                    LIMIT 3
                """,
                    [member.customer],
                    as_dict=True,
                )

                results.append(f"  - Invoices: {len(invoices)}")
                for inv in invoices:
                    results.append(f"    * {inv.name}: €{inv.grand_total} ({inv.status})")

                # Check dues schedule
                dues_schedule = frappe.db.get_value(
                    "Membership Dues Schedule",
                    {"member": member.name, "status": "Active"},
                    ["billing_frequency", "dues_rate", "last_invoice_date"],
                    as_dict=True,
                )

                if dues_schedule:
                    results.append(
                        f"  - Dues: {dues_schedule.billing_frequency} @ €{dues_schedule.dues_rate}"
                    )
                    results.append(f"  - Last Invoice: {dues_schedule.last_invoice_date}")
                else:
                    results.append(f"  - ❌ No active dues schedule")

        if not sample_members:
            results.append("❌ No active members with customers found!")

            # Check what members do exist
            total_members = frappe.db.count("Member")
            active_members = frappe.db.count("Member", {"status": "Active"})
            members_with_customers = frappe.db.sql(
                """
                SELECT COUNT(*) as count FROM `tabMember`
                WHERE status = 'Active' AND customer IS NOT NULL
            """
            )[0][0]

            results.append(f"  - Total members: {total_members}")
            results.append(f"  - Active members: {active_members}")
            results.append(f"  - Active with customers: {members_with_customers}")

    except Exception as e:
        results.append(f"❌ Error in sample data analysis: {e}")
        import traceback

        results.append(traceback.format_exc())

    results.append("")
    return results


def debug_function_flow():
    """Phase 3: Test individual functions in the coverage analysis"""

    results = []
    results.append("PHASE 3: FUNCTION FLOW TESTING")
    results.append("-" * 50)

    try:
        # Import the coverage analysis functions
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            calculate_coverage_timeline,
            get_empty_coverage_analysis,
            get_member_invoices_with_coverage,
            get_membership_periods,
        )

        # Get a sample member for testing
        sample_member = frappe.db.get_value(
            "Member", {"status": "Active", "customer": ["!=", ""]}, ["name", "customer"], as_dict=True
        )

        if not sample_member:
            results.append("❌ No suitable member found for function testing")
            return results

        member_name = sample_member.name
        customer = sample_member.customer
        results.append(f"Testing with member: {member_name} (customer: {customer})")

        # Test 1: get_membership_periods
        results.append(f"\n1. Testing get_membership_periods...")
        try:
            periods = get_membership_periods(member_name)
            results.append(f"   ✓ Found {len(periods)} membership periods")
            for i, (start, end) in enumerate(periods):
                days = date_diff(end, start) + 1
                results.append(f"   - Period {i+1}: {start} to {end} ({days} days)")
        except Exception as e:
            results.append(f"   ❌ Error: {e}")

        # Test 2: get_member_invoices_with_coverage
        results.append(f"\n2. Testing get_member_invoices_with_coverage...")
        try:
            coverage_invoices = get_member_invoices_with_coverage(customer)
            results.append(f"   ✓ Found {len(coverage_invoices)} invoices with coverage")
            for inv in coverage_invoices:
                results.append(f"   - {inv.invoice}: {inv.coverage_start} to {inv.coverage_end}")
        except Exception as e:
            results.append(f"   ❌ Error: {e}")
            # This is likely where the issue is - missing coverage fields

        # Test 3: calculate_coverage_timeline
        results.append(f"\n3. Testing calculate_coverage_timeline...")
        try:
            coverage_analysis = calculate_coverage_timeline(member_name)
            stats = coverage_analysis["stats"]
            results.append(f"   ✓ Coverage analysis completed")
            results.append(f"   - Total Active Days: {stats['total_active_days']}")
            results.append(f"   - Covered Days: {stats['covered_days']}")
            results.append(f"   - Gap Days: {stats['gap_days']}")
            results.append(f"   - Coverage %: {stats['coverage_percentage']:.1f}%")

            if stats["total_active_days"] == 0:
                results.append(f"   ❌ ISSUE: No active days calculated!")
            if stats["covered_days"] == 0 and stats["total_active_days"] > 0:
                results.append(f"   ❌ ISSUE: No covered days found despite active membership!")

        except Exception as e:
            results.append(f"   ❌ Error: {e}")

    except ImportError as e:
        results.append(f"❌ Cannot import coverage analysis functions: {e}")
    except Exception as e:
        results.append(f"❌ Error in function flow testing: {e}")

    results.append("")
    return results


def debug_coverage_field_issues():
    """Phase 4: Deep dive into coverage field issues"""

    results = []
    results.append("PHASE 4: COVERAGE FIELD ISSUE ANALYSIS")
    results.append("-" * 50)

    try:
        # Check if the custom fields exist
        has_start = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
        has_end = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

        results.append(f"Custom coverage fields status:")
        results.append(f"  - custom_coverage_start_date: {has_start}")
        results.append(f"  - custom_coverage_end_date: {has_end}")

        if not has_start or not has_end:
            results.append(f"\n❌ CRITICAL ISSUE: Coverage fields missing!")
            results.append(f"The report depends on these fields but they don't exist in the database.")

            # Check for similar fields
            columns = frappe.db.sql("DESCRIBE `tabSales Invoice`", as_dict=True)
            date_fields = [col for col in columns if "date" in col["Field"].lower()]

            results.append(f"\nAvailable date fields in Sales Invoice:")
            for col in date_fields:
                results.append(f"  - {col['Field']} ({col['Type']})")

            # Check for other coverage-related fields
            coverage_fields = [col for col in columns if "coverage" in col["Field"].lower()]
            if coverage_fields:
                results.append(f"\nOther coverage-related fields:")
                for col in coverage_fields:
                    results.append(f"  - {col['Field']} ({col['Type']})")

        else:
            # Fields exist - check if they have data
            results.append(f"\n✓ Coverage fields exist, checking data...")

            coverage_count = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabSales Invoice`
                WHERE docstatus = 1
                AND custom_coverage_start_date IS NOT NULL
                AND custom_coverage_end_date IS NOT NULL
            """
            )[0][0]

            results.append(f"Invoices with coverage data: {coverage_count}")

            if coverage_count == 0:
                results.append(f"❌ ISSUE: No invoices have coverage dates set!")

                # Show sample invoices
                sample_invoices = frappe.db.sql(
                    """
                    SELECT name, posting_date, customer, grand_total
                    FROM `tabSales Invoice`
                    WHERE docstatus = 1
                    LIMIT 5
                """,
                    as_dict=True,
                )

                results.append(f"\nSample invoices (without coverage):")
                for inv in sample_invoices:
                    results.append(f"  - {inv.name}: {inv.customer} - €{inv.grand_total}")

            else:
                # Show sample invoices with coverage
                sample_coverage = frappe.db.sql(
                    """
                    SELECT name, customer, custom_coverage_start_date, custom_coverage_end_date, grand_total
                    FROM `tabSales Invoice`
                    WHERE docstatus = 1
                    AND custom_coverage_start_date IS NOT NULL
                    LIMIT 5
                """,
                    as_dict=True,
                )

                results.append(f"\nSample invoices with coverage:")
                for inv in sample_coverage:
                    results.append(
                        f"  - {inv.name}: {inv.custom_coverage_start_date} to {inv.custom_coverage_end_date}"
                    )

    except Exception as e:
        results.append(f"❌ Error in coverage field analysis: {e}")

    results.append("")
    return results


def generate_solution_recommendations():
    """Phase 5: Generate specific solution recommendations"""

    results = []
    results.append("PHASE 5: SOLUTION RECOMMENDATIONS")
    results.append("-" * 50)

    # Check current state
    has_start = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
    has_end = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

    if not has_start or not has_end:
        results.append("SOLUTION 1: Create Missing Custom Fields")
        results.append("=" * 40)
        results.append("The primary issue is missing custom coverage fields in Sales Invoice.")
        results.append("These fields are essential for the coverage analysis to work.")
        results.append("")
        results.append("Execute these functions:")
        results.append(
            "1. bench --site dev.veganisme.net execute verenigingen.utils.debug_coverage_analysis.create_coverage_fields"
        )
        results.append(
            "2. bench --site dev.veganisme.net execute verenigingen.utils.debug_coverage_analysis.populate_coverage_dates"
        )
        results.append("3. bench restart")
        results.append("")

    else:
        # Fields exist but may not have data
        coverage_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabSales Invoice`
            WHERE docstatus = 1
            AND custom_coverage_start_date IS NOT NULL
        """
        )[0][0]

        if coverage_count == 0:
            results.append("SOLUTION 2: Populate Coverage Data")
            results.append("=" * 40)
            results.append("Coverage fields exist but contain no data.")
            results.append("")
            results.append("Execute:")
            results.append(
                "bench --site dev.veganisme.net execute verenigingen.utils.debug_coverage_analysis.populate_coverage_dates"
            )
            results.append("")
        else:
            results.append("SOLUTION 3: Debug Data Quality Issues")
            results.append("=" * 40)
            results.append("Coverage fields exist and have some data.")
            results.append("The issue may be in data relationships or query logic.")
            results.append("")

    # Code fix recommendations
    results.append("TESTING COMMANDS")
    results.append("=" * 20)
    results.append("1. Quick test:")
    results.append(
        "   bench --site dev.veganisme.net execute verenigingen.utils.debug_coverage_analysis.quick_coverage_test"
    )
    results.append("")
    results.append("2. Test specific member:")
    results.append(
        "   bench --site dev.veganisme.net execute verenigingen.utils.debug_coverage_analysis.quick_coverage_test --args \"['MEM-001']\""
    )
    results.append("")

    return results


@frappe.whitelist()
def quick_coverage_test(member_name=None):
    """Quick test of coverage analysis for a specific member"""

    if not member_name:
        # Get any active member with customer
        member_name = frappe.db.get_value("Member", {"status": "Active", "customer": ["!=", ""]}, "name")

    if not member_name:
        return "No suitable member found for testing"

    results = []
    results.append(f"QUICK COVERAGE TEST - Member: {member_name}")
    results.append("=" * 60)

    try:
        # Get member info
        member = frappe.get_doc("Member", member_name)
        results.append(f"Member: {member.first_name} {member.last_name or ''}")
        results.append(f"Customer: {member.customer}")
        results.append(f"Status: {member.status}")

        # Check membership periods
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            get_membership_periods,
        )

        periods = get_membership_periods(member_name)
        results.append(f"\nMembership Periods: {len(periods)}")
        for i, (start, end) in enumerate(periods):
            days = date_diff(end, start) + 1
            results.append(f"  {i+1}. {start} to {end} ({days} days)")

        # Check invoices
        invoices = frappe.db.sql(
            """
            SELECT name, posting_date, grand_total, status
            FROM `tabSales Invoice`
            WHERE customer = %s AND docstatus = 1
            ORDER BY posting_date
        """,
            [member.customer],
            as_dict=True,
        )

        results.append(f"\nInvoices: {len(invoices)}")
        for inv in invoices:
            results.append(f"  - {inv.name}: {inv.posting_date} - €{inv.grand_total} ({inv.status})")

        # Test coverage analysis
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            calculate_coverage_timeline,
        )

        coverage = calculate_coverage_timeline(member_name)
        stats = coverage["stats"]

        results.append(f"\nCoverage Analysis:")
        results.append(f"  - Total Active Days: {stats['total_active_days']}")
        results.append(f"  - Covered Days: {stats['covered_days']}")
        results.append(f"  - Gap Days: {stats['gap_days']}")
        results.append(f"  - Coverage %: {stats['coverage_percentage']:.1f}%")
        results.append(f"  - Outstanding: €{stats['outstanding_amount']}")

        # Gaps
        gaps = coverage["gaps"]
        if gaps:
            results.append(f"\nGaps ({len(gaps)}):")
            for gap in gaps:
                results.append(
                    f"  - {gap['gap_start']} to {gap['gap_end']}: {gap['gap_days']} days ({gap['gap_type']})"
                )
        else:
            results.append(f"\nNo gaps found")

    except Exception as e:
        results.append(f"\n❌ Error: {e}")
        import traceback

        results.append(traceback.format_exc())

    return "\n".join(results)


@frappe.whitelist()
def create_coverage_fields():
    """Create the missing custom coverage fields in Sales Invoice"""

    results = []
    results.append("CREATING CUSTOM COVERAGE FIELDS")
    results.append("=" * 40)

    try:
        # Check if fields already exist
        has_start = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
        has_end = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

        if has_start and has_end:
            results.append("✓ Coverage fields already exist!")
            return "\n".join(results)

        # Create custom fields
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        custom_fields = {
            "Sales Invoice": [
                {
                    "fieldname": "custom_coverage_start_date",
                    "fieldtype": "Date",
                    "label": "Coverage Start Date",
                    "description": "Start date of membership period covered by this invoice",
                    "insert_after": "posting_date",
                },
                {
                    "fieldname": "custom_coverage_end_date",
                    "fieldtype": "Date",
                    "label": "Coverage End Date",
                    "description": "End date of membership period covered by this invoice",
                    "insert_after": "custom_coverage_start_date",
                },
            ]
        }

        create_custom_fields(custom_fields)
        results.append("✓ Created custom coverage fields in Sales Invoice")

        # Trigger migration
        frappe.reload_doctype("Sales Invoice")
        results.append("✓ Reloaded Sales Invoice DocType")

        # Test that fields now exist
        has_start_after = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
        has_end_after = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

        if has_start_after and has_end_after:
            results.append("✓ Verified: Coverage fields now exist in database")
        else:
            results.append("❌ Warning: Fields may not be immediately available")
            results.append("   Try restarting the bench: 'bench restart'")

    except Exception as e:
        results.append(f"❌ Error creating fields: {e}")
        import traceback

        results.append(traceback.format_exc())

    return "\n".join(results)


@frappe.whitelist()
def populate_coverage_dates():
    """Populate coverage dates for existing invoices based on membership dues schedule"""

    results = []
    results.append("POPULATING COVERAGE DATES FOR EXISTING INVOICES")
    results.append("=" * 60)

    try:
        # Check if coverage fields exist
        has_start = frappe.db.has_column("tabSales Invoice", "custom_coverage_start_date")
        has_end = frappe.db.has_column("tabSales Invoice", "custom_coverage_end_date")

        if not has_start or not has_end:
            results.append("❌ Coverage fields don't exist. Run create_coverage_fields() first.")
            return "\n".join(results)

        # Get invoices without coverage dates
        invoices_to_update = frappe.db.sql(
            """
            SELECT si.name, si.customer, si.posting_date, si.grand_total,
                   m.name as member_name, mds.billing_frequency, mds.dues_rate
            FROM `tabSales Invoice` si
            JOIN `tabCustomer` c ON c.name = si.customer
            JOIN `tabMember` m ON m.customer = c.name
            LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = m.name AND mds.status = 'Active'
            WHERE si.docstatus = 1
            AND (si.custom_coverage_start_date IS NULL OR si.custom_coverage_end_date IS NULL)
            ORDER BY si.posting_date
            LIMIT 50
        """,
            as_dict=True,
        )

        results.append(f"Found {len(invoices_to_update)} invoices to update")

        updated_count = 0
        error_count = 0

        for invoice_data in invoices_to_update:
            try:
                # Calculate coverage period based on billing frequency
                posting_date = getdate(invoice_data.posting_date)
                billing_frequency = invoice_data.billing_frequency or "Monthly"

                if billing_frequency == "Monthly":
                    # Coverage for the month of the invoice
                    coverage_start = posting_date.replace(day=1)
                    if coverage_start.month == 12:
                        coverage_end = coverage_start.replace(
                            year=coverage_start.year + 1, month=1, day=1
                        ) - timedelta(days=1)
                    else:
                        coverage_end = coverage_start.replace(
                            month=coverage_start.month + 1, day=1
                        ) - timedelta(days=1)

                elif billing_frequency == "Quarterly":
                    # Coverage for the quarter
                    quarter = ((posting_date.month - 1) // 3) + 1
                    quarter_start_month = (quarter - 1) * 3 + 1
                    coverage_start = posting_date.replace(month=quarter_start_month, day=1)
                    if quarter == 4:
                        coverage_end = coverage_start.replace(
                            year=coverage_start.year + 1, month=1, day=1
                        ) - timedelta(days=1)
                    else:
                        coverage_end = coverage_start.replace(
                            month=quarter_start_month + 3, day=1
                        ) - timedelta(days=1)

                elif billing_frequency == "Annual":
                    # Coverage for the year
                    coverage_start = posting_date.replace(month=1, day=1)
                    coverage_end = posting_date.replace(month=12, day=31)

                else:
                    # Default: 30 days from posting date
                    coverage_start = posting_date
                    coverage_end = add_days(posting_date, 30)

                # Update the invoice
                frappe.db.set_value(
                    "Sales Invoice",
                    invoice_data.name,
                    {"custom_coverage_start_date": coverage_start, "custom_coverage_end_date": coverage_end},
                )

                updated_count += 1
                results.append(f"✓ {invoice_data.name}: {coverage_start} to {coverage_end}")

            except Exception as e:
                error_count += 1
                results.append(f"❌ Error updating {invoice_data.name}: {e}")

        results.append(f"\nSummary:")
        results.append(f"✓ Updated: {updated_count} invoices")
        results.append(f"❌ Errors: {error_count} invoices")

        if updated_count > 0:
            frappe.db.commit()
            results.append("✓ Changes committed to database")

    except Exception as e:
        results.append(f"❌ Error populating coverage dates: {e}")
        import traceback

        results.append(traceback.format_exc())

    return "\n".join(results)


if __name__ == "__main__":
    print("This script should be run through Frappe:")
    print("bench --site dev.veganisme.net execute verenigingen.utils.debug_coverage_analysis.run_full_debug")
