"""
Create database indexes for refund query optimization.

This patch creates composite indexes to optimize refund-related queries.
"""

import frappe


def execute():
    """Create database indexes for refund processing optimization."""

    try:
        # Create composite index for refund queries
        frappe.db.sql(
            """
            CREATE INDEX IF NOT EXISTS idx_payment_refunds
            ON `tabPayment Entry` (
                payment_type,
                custom_original_payment_id,
                custom_reversal_type,
                docstatus,
                creation
            )
        """
        )

        # Create index for webhook processing log queries
        frappe.db.sql(
            """
            CREATE INDEX IF NOT EXISTS idx_webhook_processing
            ON `tabWebhook Processing Log` (
                webhook_id,
                status,
                processed_at
            )
        """
        )

        # Create index for donation payment lookups
        frappe.db.sql(
            """
            CREATE INDEX IF NOT EXISTS idx_donation_payment_id
            ON `tabDonation` (payment_id)
        """
        )

        frappe.db.commit()

        print("✅ Created refund processing database indexes")

    except Exception as e:
        frappe.log_error(f"Error creating refund indexes: {str(e)}", "Index Creation Error")
        print(f"❌ Failed to create indexes: {str(e)}")
