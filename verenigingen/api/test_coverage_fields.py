"""
Test coverage field functionality for member portal
"""

import frappe
from frappe.utils import formatdate


@frappe.whitelist()
def test_coverage_fields():
    """Test if coverage fields exist and have data"""
    frappe.only_for("System Manager")

    results = []

    # Check if coverage fields exist in Sales Invoice
    try:
        # Get Sales Invoice meta to check fields
        meta = frappe.get_meta("Sales Invoice")
        field_names = [field.fieldname for field in meta.fields]

        coverage_fields = ["custom_coverage_start_date", "custom_coverage_end_date"]

        results.append("🔍 Checking coverage fields in Sales Invoice...")
        for field in coverage_fields:
            if field in field_names:
                results.append(f"✅ {field} exists")
            else:
                results.append(f"❌ {field} missing")

        # Check if any Sales Invoices have coverage data
        invoices_with_coverage = frappe.db.sql(
            """
            SELECT name, custom_coverage_start_date, custom_coverage_end_date, customer, due_date
            FROM `tabSales Invoice`
            WHERE custom_coverage_start_date IS NOT NULL
            AND custom_coverage_end_date IS NOT NULL
            AND docstatus = 1
            LIMIT 5
        """,
            as_dict=True,
        )

        if invoices_with_coverage:
            results.append(f"\n📊 Found {len(invoices_with_coverage)} invoices with coverage data:")
            for inv in invoices_with_coverage:
                results.append(
                    f"  - {inv.name}: {formatdate(inv.custom_coverage_start_date)} to {formatdate(inv.custom_coverage_end_date)}"
                )
        else:
            results.append("\n⚠️ No Sales Invoices found with coverage date data")

            # Show some sample invoices without coverage data
            sample_invoices = frappe.db.sql(
                """
                SELECT name, customer, due_date, grand_total, outstanding_amount
                FROM `tabSales Invoice`
                WHERE docstatus = 1
                AND outstanding_amount > 0
                LIMIT 3
            """,
                as_dict=True,
            )

            if sample_invoices:
                results.append("📋 Sample outstanding invoices (no coverage data):")
                for inv in sample_invoices:
                    results.append(
                        f"  - {inv.name}: Due {formatdate(inv.due_date) if inv.due_date else 'No due date'}, Amount: {inv.grand_total}"
                    )

    except Exception as e:
        results.append(f"❌ Error checking coverage fields: {e}")

    # Test the member portal utility functions
    try:
        from verenigingen.utils.member_portal_utils import (
            enhance_outstanding_invoices_with_coverage,
            format_coverage_period,
        )

        results.append("\n🧪 Testing coverage utility functions...")

        # Test format_coverage_period function
        test_period = format_coverage_period("2025-01-01", "2025-01-31", "Monthly")
        results.append(f"✅ format_coverage_period test: {test_period}")

        # Test with sample invoice data
        sample_invoices = [{"name": "TEST-INV-001", "due_date": "2025-08-22"}]
        enhanced = enhance_outstanding_invoices_with_coverage(sample_invoices, "Monthly")
        results.append(
            f"✅ enhance_outstanding_invoices_with_coverage test: {len(enhanced)} invoices processed"
        )

        if enhanced:
            results.append(f"   Coverage period result: {enhanced[0].get('coverage_period', 'Not found')}")

    except Exception as e:
        results.append(f"❌ Error testing utility functions: {e}")

    return {"success": True, "results": results}


@frappe.whitelist()
def populate_sample_coverage_data():
    """Populate some sample coverage data for testing"""
    frappe.only_for("System Manager")

    results = []

    try:
        # Get a few outstanding Sales Invoices
        invoices = frappe.db.sql(
            """
            SELECT name, due_date
            FROM `tabSales Invoice`
            WHERE docstatus = 1
            AND outstanding_amount > 0
            AND (custom_coverage_start_date IS NULL OR custom_coverage_end_date IS NULL)
            LIMIT 3
        """,
            as_dict=True,
        )

        if not invoices:
            results.append("ℹ️ No invoices found that need coverage data")
            return {"success": True, "results": results}

        from datetime import datetime, timedelta

        from frappe.utils import add_days, add_months, getdate

        for invoice in invoices:
            try:
                # Use due date as end of coverage period
                if invoice.due_date:
                    end_date = getdate(invoice.due_date)
                    # Assume monthly billing - start date is one month before
                    start_date = add_months(end_date, -1)
                    start_date = add_days(start_date, 1)  # Start day after previous period
                else:
                    # Use current month as fallback
                    end_date = getdate()
                    start_date = getdate().replace(day=1)

                # Update the invoice with coverage dates
                frappe.db.set_value(
                    "Sales Invoice",
                    invoice.name,
                    {"custom_coverage_start_date": start_date, "custom_coverage_end_date": end_date},
                )

                results.append(f"✅ Updated {invoice.name}: {start_date} to {end_date}")

            except Exception as e:
                results.append(f"❌ Error updating {invoice.name}: {e}")

        frappe.db.commit()
        results.append(f"\n🎉 Successfully updated {len(invoices)} invoices with sample coverage data")

    except Exception as e:
        results.append(f"❌ Error populating sample data: {e}")

    return {"success": True, "results": results}
