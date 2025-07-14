"""
Transaction Processing for E-Boekhouden Migration

This module handles all transaction-related operations including
invoices, payments, and journal entries.
"""

import frappe
from frappe.utils import now


class TransactionProcessor:
    """Handles transaction processing for E-Boekhouden migration"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.company = migration_doc.company

    def migrate_transactions_data(self, settings):
        """Migrate Transactions from e-Boekhouden using REST API"""
        try:
            # Always use REST API - SOAP is deprecated
            use_enhanced = getattr(self.migration_doc, "use_enhanced_migration", True)

            if use_enhanced:
                result = self._migrate_transactions_enhanced()
            else:
                result = self._migrate_transactions_rest()

            # Process result
            if result.get("success"):
                stats = result.get("stats", {})
                imported = self._calculate_imported_count(stats)
                failed = self._calculate_failed_count(stats)
                total = stats.get("total_mutations", imported)

                self.migration_doc.imported_records += imported
                self.migration_doc.failed_records += failed
                self.migration_doc.total_records += total

                return f"Successfully imported {imported} transactions from {total} mutations"
            else:
                return f"Error: {result.get('error', 'Unknown error')}"

        except Exception as e:
            return f"Error migrating Transactions: {str(e)}"

    def _migrate_transactions_enhanced(self):
        """Use enhanced migration with all improvements"""
        try:
            from verenigingen.utils.eboekhouden_enhanced_migration import execute_enhanced_migration

            result = execute_enhanced_migration(self.migration_doc.name)

            if result.get("success", False) or "total_processed" in result:
                stats = self._extract_enhanced_stats(result)
                return {"success": True, "stats": stats}
            else:
                return {"success": False, "error": result.get("error", "Migration failed")}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _migrate_transactions_rest(self):
        """Use REST API migration"""
        try:
            from verenigingen.utils.eboekhouden_rest_full_migration import start_full_rest_import

            result = start_full_rest_import(self.migration_doc.name)

            if isinstance(result, dict) and "success" in result:
                return result
            else:
                # Wrap in expected format
                return {"success": True, "stats": result if isinstance(result, dict) else {}}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _extract_enhanced_stats(self, result):
        """Extract statistics from enhanced migration result"""
        stats = {
            "success": True,
            "total_mutations": result.get("total_processed", 0),
            "invoices_created": result.get("created", 0),
            "payments_processed": 0,
            "journal_entries_created": 0,
            "errors": result.get("errors", []),
        }

        # Extract detailed stats if available
        if "audit_summary" in result:
            audit = result["audit_summary"]
            if "overall_statistics" in audit:
                overall = audit["overall_statistics"]
                records_created = overall.get("records_created", {})

                stats["invoices_created"] = records_created.get("Sales Invoice", 0) + records_created.get(
                    "Purchase Invoice", 0
                )
                stats["payments_processed"] = records_created.get("Payment Entry", 0)
                stats["journal_entries_created"] = records_created.get("Journal Entry", 0)

        return stats

    def _calculate_imported_count(self, stats):
        """Calculate total imported records"""
        return (
            stats.get("invoices_created", 0)
            + stats.get("payments_processed", 0)
            + stats.get("journal_entries_created", 0)
        )

    def _calculate_failed_count(self, stats):
        """Calculate total failed records"""
        errors = stats.get("errors", [])
        return len(errors) if isinstance(errors, list) else 0

    def migrate_stock_transactions_data(self, settings):
        """Migrate Stock Transactions from e-Boekhouden"""
        try:
            from verenigingen.utils.migration.stock_migration_fixed import migrate_stock_transactions_safe

            # Get date range
            date_from = self.migration_doc.date_from if self.migration_doc.date_from else None
            date_to = self.migration_doc.date_to if self.migration_doc.date_to else None

            # Run migration
            result = migrate_stock_transactions_safe(self.migration_doc, date_from, date_to)

            # Process result
            if isinstance(result, dict):
                message = result.get("message", "Stock migration completed")

                # Update counters if available
                if "skipped" in result:
                    self.migration_doc.total_records += result["skipped"]
                if "processed" in result:
                    self.migration_doc.imported_records += result["processed"]

                return message
            else:
                return result

        except Exception as e:
            frappe.log_error(
                title="Stock Transaction Migration Error",
                message=f"Error migrating stock transactions:\n{str(e)}\n\n{frappe.get_traceback()}",
            )
            return f"Error migrating Stock Transactions: {str(e)[:100]}..."

    def create_journal_entry(self, transaction_data):
        """Create a Journal Entry from transaction data"""
        try:
            je = frappe.new_doc("Journal Entry")
            je.company = self.company
            je.posting_date = transaction_data.get("posting_date", now())
            je.voucher_type = "Journal Entry"
            je.user_remark = transaction_data.get("description", "E-Boekhouden Import")

            # Add accounting entries
            total_debit = 0
            total_credit = 0

            for entry in transaction_data.get("accounts", []):
                je_account = je.append("accounts")
                je_account.account = entry["account"]
                je_account.debit_in_account_currency = entry.get("debit", 0)
                je_account.credit_in_account_currency = entry.get("credit", 0)

                total_debit += entry.get("debit", 0)
                total_credit += entry.get("credit", 0)

            # Validate balancing
            if abs(total_debit - total_credit) > 0.01:
                frappe.throw(f"Journal Entry is not balanced: Debit {total_debit}, Credit {total_credit}")

            je.insert()
            je.submit()

            return je.name

        except Exception as e:
            frappe.log_error(f"Error creating journal entry: {str(e)}")
            return None

    def create_sales_invoice(self, invoice_data):
        """Create a Sales Invoice from E-Boekhouden data"""
        try:
            # Use invoice helpers for creation
            from verenigingen.utils.eboekhouden.invoice_helpers import create_sales_invoice_from_mutation

            return create_sales_invoice_from_mutation(invoice_data, self.company)

        except Exception as e:
            frappe.log_error(f"Error creating sales invoice: {str(e)}")
            return None

    def create_purchase_invoice(self, invoice_data):
        """Create a Purchase Invoice from E-Boekhouden data"""
        try:
            # Use invoice helpers for creation
            from verenigingen.utils.eboekhouden.invoice_helpers import create_purchase_invoice_from_mutation

            return create_purchase_invoice_from_mutation(invoice_data, self.company)

        except Exception as e:
            frappe.log_error(f"Error creating purchase invoice: {str(e)}")
            return None

    def create_payment_entry(self, payment_data):
        """Create a Payment Entry from E-Boekhouden data"""
        try:
            # Use enhanced payment import if available
            from verenigingen.utils.eboekhouden.enhanced_payment_import import create_enhanced_payment_entry

            debug_info = []
            payment_name = create_enhanced_payment_entry(
                payment_data, self.company, None, debug_info  # cost_center
            )

            if debug_info:
                for info in debug_info:
                    self.migration_doc.log_error(f"Payment info: {info}")

            return payment_name

        except Exception as e:
            frappe.log_error(f"Error creating payment entry: {str(e)}")
            return None
