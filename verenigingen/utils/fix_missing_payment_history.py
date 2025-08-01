#!/usr/bin/env python3

import frappe
from frappe.utils import add_days, today


@frappe.whitelist()
def fix_missing_payment_history():
    """Fix missing payment history entries for recently generated invoices"""

    try:
        # Get invoices from the last 2 days that might be missing from payment history
        cutoff_date = add_days(today(), -2)

        # Get all submitted invoices from the last 2 days
        recent_invoices = frappe.db.sql(
            """
            SELECT
                si.name as invoice_name,
                si.customer,
                si.posting_date,
                si.grand_total,
                si.outstanding_amount,
                si.status,
                si.creation,
                m.name as member_name,
                m.full_name as member_full_name
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMember` m ON si.customer = m.customer
            WHERE si.creation >= %s
            AND si.docstatus = 1
            AND m.name IS NOT NULL
            ORDER BY si.creation DESC
        """,
            (cutoff_date,),
            as_dict=True,
        )

        print(f"=== Payment History Sync for {len(recent_invoices)} recent invoices ===")

        # Check which invoices are missing from payment history
        missing_invoices = []
        for invoice_data in recent_invoices:
            # Check if this invoice exists in the member's payment history
            existing = frappe.db.get_value(
                "Member Payment History",
                {"parent": invoice_data.member_name, "invoice": invoice_data.invoice_name},
                "name",
            )

            if not existing:
                missing_invoices.append(invoice_data)
                print(
                    f"Missing: {invoice_data.invoice_name} for {invoice_data.member_full_name} (€{invoice_data.grand_total:.2f})"
                )

        print(f"\nFound {len(missing_invoices)} invoices missing from payment history")

        # Add missing invoices to payment history
        success_count = 0
        error_count = 0

        for invoice_data in missing_invoices:
            try:
                # Get the member document
                member_doc = frappe.get_doc("Member", invoice_data.member_name)

                # Use the atomic add method
                member_doc.add_invoice_to_payment_history(invoice_data.invoice_name)

                success_count += 1
                print(
                    f"✓ Added {invoice_data.invoice_name} to payment history for {invoice_data.member_full_name}"
                )

            except Exception as e:
                error_count += 1
                print(f"✗ Failed to add {invoice_data.invoice_name} for {invoice_data.member_full_name}: {e}")
                frappe.log_error(
                    f"Failed to add invoice {invoice_data.invoice_name} to payment history for member {invoice_data.member_name}: {str(e)}",
                    "Manual Payment History Fix",
                )

        # Summary
        print("\n=== Summary ===")
        print(f"Total recent invoices: {len(recent_invoices)}")
        print(f"Missing from payment history: {len(missing_invoices)}")
        print(f"Successfully added: {success_count}")
        print(f"Errors: {error_count}")

        # Commit the changes
        if success_count > 0:
            frappe.db.commit()
            print("Changes committed to database")

        return {
            "success": True,
            "total_invoices": len(recent_invoices),
            "missing_invoices": len(missing_invoices),
            "fixed": success_count,
            "errors": error_count,
        }

    except Exception as e:
        print(f"Error in payment history fix: {e}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}
