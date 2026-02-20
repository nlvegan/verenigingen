"""
Migration Orchestrator for E-Boekhouden

This module handles the main migration coordination and progress tracking.
"""

import frappe


class MigrationOrchestrator:
    """Coordinates the overall migration process"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.company = migration_doc.company

    def start_migration(self):
        """Start the migration process - moved from main file"""
        try:
            self.migration_doc.db_set(
                {
                    "migration_status": "In Progress",
                    "start_time": frappe.utils.now_datetime(),
                    "current_operation": "Initializing migration...",
                    "progress_percentage": 0,
                }
            )
            frappe.db.commit()

            # Get settings
            settings = frappe.get_single("E-Boekhouden Settings")
            if not settings.api_token:
                frappe.throw("E-Boekhouden Settings not configured. Please configure API token first.")

            # Initialize counters
            self.migration_doc.total_records = 0
            self.migration_doc.imported_records = 0
            self.migration_doc.failed_records = 0

            migration_log = []
            self.migration_doc.failed_record_details = []

            # Execute migration phases
            self._execute_migration_phases(settings, migration_log)

            # Complete migration
            self._complete_migration(migration_log)

        except Exception as e:
            self._handle_migration_error(str(e))

    def _execute_migration_phases(self, settings, migration_log):
        """Execute the migration phases"""

        # Phase 1: Chart of Accounts
        if getattr(self.migration_doc, "migrate_accounts", 0):
            self._execute_accounts_phase(settings, migration_log)

        # Phase 2: Cost Centers
        if getattr(self.migration_doc, "migrate_cost_centers", 0):
            self._execute_cost_centers_phase(settings, migration_log)

        # Phase 3: Customers
        if getattr(self.migration_doc, "migrate_customers", 0):
            self._execute_customers_phase(settings, migration_log)

        # Phase 4: Suppliers
        if getattr(self.migration_doc, "migrate_suppliers", 0):
            self._execute_suppliers_phase(settings, migration_log)

        # Phase 5: Transactions
        if getattr(self.migration_doc, "migrate_transactions", 0):
            self._execute_transactions_phase(settings, migration_log)

        # Phase 6: Stock Transactions
        if getattr(self.migration_doc, "migrate_stock_transactions", 0):
            self._execute_stock_phase(settings, migration_log)

    def _execute_accounts_phase(self, settings, migration_log):
        """Execute chart of accounts migration"""
        self.migration_doc.db_set(
            {"current_operation": "Migrating Chart of Accounts...", "progress_percentage": 10}
        )
        frappe.db.commit()

        # Use existing method
        result = self.migration_doc.migrate_chart_of_accounts(settings)
        migration_log.append(f"Chart of Accounts: {result}")

    def _execute_cost_centers_phase(self, settings, migration_log):
        """Execute cost centers migration"""
        self.migration_doc.db_set(
            {"current_operation": "Migrating Cost Centers...", "progress_percentage": 20}
        )
        frappe.db.commit()

        result = self.migration_doc.do_migrate_cost_centers(settings)
        migration_log.append(f"Cost Centers: {result}")

    def _execute_customers_phase(self, settings, migration_log):
        """Execute customers migration"""
        self.migration_doc.db_set({"current_operation": "Migrating Customers...", "progress_percentage": 40})
        frappe.db.commit()

        result = self.migration_doc.migrate_customers_data(settings)
        migration_log.append(f"Customers: {result}")

    def _execute_suppliers_phase(self, settings, migration_log):
        """Execute suppliers migration"""
        self.migration_doc.db_set({"current_operation": "Migrating Suppliers...", "progress_percentage": 50})
        frappe.db.commit()

        result = self.migration_doc.migrate_suppliers_data(settings)
        migration_log.append(f"Suppliers: {result}")

    def _execute_transactions_phase(self, settings, migration_log):
        """Execute transactions migration"""
        self.migration_doc.db_set(
            {"current_operation": "Migrating Transactions...", "progress_percentage": 60}
        )
        frappe.db.commit()

        result = self.migration_doc.migrate_transactions_data(settings)
        migration_log.append(f"Transactions: {result}")

    def _execute_stock_phase(self, settings, migration_log):
        """Execute stock transactions migration"""
        self.migration_doc.db_set(
            {"current_operation": "Migrating Stock Transactions...", "progress_percentage": 90}
        )
        frappe.db.commit()

        result = self.migration_doc.migrate_stock_transactions_data(settings)
        migration_log.append(f"Stock Transactions: {result}")

    def _complete_migration(self, migration_log):
        """Complete the migration process"""
        self.migration_doc.db_set(
            {
                "migration_status": "Completed",
                "end_time": frappe.utils.now_datetime(),
                "current_operation": "Migration completed successfully",
                "progress_percentage": 100,
                "migration_log": "\n".join(migration_log),
            }
        )
        frappe.db.commit()

    def _handle_migration_error(self, error_message):
        """Handle migration errors"""
        self.migration_doc.db_set(
            {
                "migration_status": "Failed",
                "end_time": frappe.utils.now_datetime(),
                "current_operation": f"Migration failed: {error_message}",
                "progress_percentage": 0,
            }
        )
        frappe.db.commit()
        frappe.throw(error_message)
