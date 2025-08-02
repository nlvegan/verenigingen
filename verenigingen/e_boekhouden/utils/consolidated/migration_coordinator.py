"""
Consolidated Migration Coordinator for E-Boekhouden Integration

This module consolidates migration coordination and utilities from:
- migration_utils.py (212 lines)
- migration_api.py (281 lines)
- import_manager.py (330 lines)

Total consolidated: 823 lines → ~400 lines of focused functionality
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import frappe

from verenigingen.e_boekhouden.utils.consolidated.account_manager import EBoekhoudenAccountManager
from verenigingen.e_boekhouden.utils.consolidated.party_manager import EBoekhoudenPartyManager
from verenigingen.e_boekhouden.utils.security_helper import atomic_migration_operation, migration_transaction


class EBoekhoudenMigrationCoordinator:
    """
    Central coordinator for E-Boekhouden migration operations.

    Features:
    - Transaction coordination with proper rollback
    - Progress tracking and reporting
    - Prerequisites validation
    - Component integration (accounts, parties, transactions)
    - Error handling and recovery
    """

    def __init__(self, company: str, cost_center: str = None):
        self.company = company
        self.cost_center = cost_center or frappe.db.get_value("Company", company, "cost_center")

        # Initialize component managers
        self.party_manager = EBoekhoudenPartyManager()
        self.account_manager = EBoekhoudenAccountManager(company)

        # Migration state
        self.migration_log = []
        self.progress_tracker = {
            "phase": None,
            "total_operations": 0,
            "completed_operations": 0,
            "errors": [],
            "start_time": None,
            "current_operation": None,
        }

    def coordinate_full_migration(self, migration_config: Dict) -> Dict:
        """
        Coordinate complete E-Boekhouden migration with proper transaction management.

        Args:
            migration_config: Migration configuration dictionary

        Returns:
            Migration results with statistics and errors
        """
        self.progress_tracker["start_time"] = datetime.now()
        self.progress_tracker["phase"] = "initialization"

        results = {
            "success": False,
            "phases_completed": [],
            "total_duration": 0,
            "statistics": {},
            "errors": [],
        }

        try:
            # Phase 1: Prerequisites validation
            self._log("Starting prerequisites validation")
            self.progress_tracker["phase"] = "prerequisites"

            prereq_results = self.validate_prerequisites(migration_config)
            if not prereq_results["valid"]:
                results["errors"].extend(prereq_results["errors"])
                return results

            results["phases_completed"].append("prerequisites")

            # Phase 2: Chart of Accounts setup
            if migration_config.get("migrate_accounts", True):
                self._log("Starting Chart of Accounts migration")
                self.progress_tracker["phase"] = "accounts"

                with migration_transaction("account_creation", batch_size=50) as tx:
                    account_results = self._migrate_chart_of_accounts(migration_config, tx)
                    results["statistics"]["accounts"] = account_results

                results["phases_completed"].append("accounts")

            # Phase 3: Parties (Customers/Suppliers) setup
            if migration_config.get("migrate_parties", True):
                self._log("Starting parties migration")
                self.progress_tracker["phase"] = "parties"

                with migration_transaction("party_creation", batch_size=25) as tx:
                    party_results = self._migrate_parties(migration_config, tx)
                    results["statistics"]["parties"] = party_results

                results["phases_completed"].append("parties")

            # Phase 4: Historical transactions
            if migration_config.get("migrate_transactions", True):
                self._log("Starting transactions migration")
                self.progress_tracker["phase"] = "transactions"

                with migration_transaction("payment_processing", batch_size=20) as tx:
                    transaction_results = self._migrate_transactions(migration_config, tx)
                    results["statistics"]["transactions"] = transaction_results

                results["phases_completed"].append("transactions")

            # Phase 5: Post-migration validation and cleanup
            self._log("Starting post-migration validation")
            self.progress_tracker["phase"] = "validation"

            validation_results = self._post_migration_validation()
            results["statistics"]["validation"] = validation_results
            results["phases_completed"].append("validation")

            # Calculate final statistics
            end_time = datetime.now()
            results["total_duration"] = (end_time - self.progress_tracker["start_time"]).total_seconds()
            results["success"] = True

            self._log(f"Migration completed successfully in {results['total_duration']:.2f} seconds")

        except Exception as e:
            error_msg = f"Migration failed in phase {self.progress_tracker['phase']}: {str(e)}"
            self._log(f"ERROR: {error_msg}")
            results["errors"].append(error_msg)
            frappe.log_error(error_msg, "E-Boekhouden Migration Coordinator")

        finally:
            self.progress_tracker["phase"] = "completed"

        return results

    def validate_prerequisites(self, config: Dict) -> Dict:
        """Validate all prerequisites for migration."""
        results = {"valid": True, "checks": [], "errors": [], "warnings": []}

        checks = [
            ("E-Boekhouden Settings", self._check_eboekhouden_settings),
            ("Company Configuration", self._check_company_config),
            ("Custom Fields", self._check_custom_fields),
            ("API Connectivity", self._check_api_connectivity),
            ("Permissions", self._check_migration_permissions),
            ("Database Space", self._check_database_space),
        ]

        for check_name, check_function in checks:
            try:
                self.progress_tracker["current_operation"] = f"Checking {check_name}"
                check_result = check_function(config)

                results["checks"].append(
                    {
                        "name": check_name,
                        "passed": check_result["passed"],
                        "details": check_result.get("details", []),
                    }
                )

                if not check_result["passed"]:
                    results["valid"] = False
                    results["errors"].extend(check_result.get("errors", []))

                if check_result.get("warnings"):
                    results["warnings"].extend(check_result["warnings"])

            except Exception as e:
                results["valid"] = False
                results["errors"].append(f"{check_name} check failed: {str(e)}")

        return results

    def track_progress(self) -> Dict:
        """Get current migration progress."""
        progress = self.progress_tracker.copy()

        if progress["total_operations"] > 0:
            progress["completion_percentage"] = (
                progress["completed_operations"] / progress["total_operations"] * 100
            )
        else:
            progress["completion_percentage"] = 0

        if progress["start_time"]:
            progress["elapsed_time"] = (datetime.now() - progress["start_time"]).total_seconds()

        return progress

    def get_migration_summary(self) -> Dict:
        """Get comprehensive migration summary."""
        return {
            "progress": self.track_progress(),
            "migration_log": self.migration_log[-50:],  # Last 50 entries
            "component_logs": {
                "party_manager": self.party_manager.get_debug_log()[-20:],
                "account_manager": self.account_manager.get_debug_log()[-20:],
            },
        }

    # Private migration phase methods

    def _migrate_chart_of_accounts(self, config: Dict, tx) -> Dict:
        """Migrate chart of accounts with transaction tracking."""
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient

            client = EBoekhoudenRESTClient()
            accounts = client.get_accounts()

            results = {"created": 0, "updated": 0, "errors": []}

            for account_data in accounts:
                try:
                    account_name = self.account_manager.create_account(account_data)
                    if account_name:
                        results["created"] += 1
                        tx.track_operation("account_created", account_name, account_data)

                except Exception as e:
                    results["errors"].append(f"Account {account_data.get('code')}: {str(e)}")

            # Fix account groups and hierarchy
            group_results = self.account_manager.fix_account_groups()
            results.update(group_results)

            return results

        except Exception as e:
            raise Exception(f"Chart of accounts migration failed: {str(e)}")

    def _migrate_parties(self, config: Dict, tx) -> Dict:
        """Migrate customers and suppliers."""
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient

            client = EBoekhoudenRESTClient()
            results = {"customers": 0, "suppliers": 0, "errors": []}

            # Migrate customers
            if config.get("migrate_customers", True):
                try:
                    customers = client.get_relations("Customer")
                    for customer_data in customers:
                        customer_name = self.party_manager.resolve_customer(
                            customer_data.get("id"), self.migration_log
                        )
                        if customer_name:
                            results["customers"] += 1
                            tx.track_operation("customer_created", customer_name, customer_data)

                except Exception as e:
                    results["errors"].append(f"Customer migration failed: {str(e)}")

            # Migrate suppliers
            if config.get("migrate_suppliers", True):
                try:
                    suppliers = client.get_relations("Supplier")
                    for supplier_data in suppliers:
                        supplier_name = self.party_manager.resolve_supplier(
                            supplier_data.get("id"), supplier_data.get("name", ""), self.migration_log
                        )
                        if supplier_name:
                            results["suppliers"] += 1
                            tx.track_operation("supplier_created", supplier_name, supplier_data)

                except Exception as e:
                    results["errors"].append(f"Supplier migration failed: {str(e)}")

            # Process enrichment queue
            enrichment_results = self.party_manager.process_enrichment_queue()
            results["enriched"] = enrichment_results["processed"]
            results["errors"].extend(enrichment_results["errors"])

            return results

        except Exception as e:
            raise Exception(f"Party migration failed: {str(e)}")

    def _migrate_transactions(self, config: Dict, tx) -> Dict:
        """Migrate historical transactions."""
        try:
            from verenigingen.e_boekhouden.utils.processors.transaction_coordinator import (
                TransactionCoordinator,
            )

            coordinator = TransactionCoordinator(self.company, self.cost_center)

            # Use date range from config
            date_from = config.get("date_from")
            date_to = config.get("date_to")

            results = coordinator.process_date_range(date_from, date_to)

            # Track operations
            for operation_type, count in results.get("statistics", {}).items():
                if isinstance(count, int) and count > 0:
                    tx.track_operation(f"transaction_{operation_type}", f"{count}_transactions")

            return results

        except Exception as e:
            raise Exception(f"Transaction migration failed: {str(e)}")

    def _post_migration_validation(self) -> Dict:
        """Post-migration validation and cleanup."""
        results = {"validations": [], "cleanup_actions": [], "warnings": []}

        try:
            # Validate account hierarchy
            hierarchy_results = self.account_manager.validate_account_hierarchy()
            results["validations"].append(("Account Hierarchy", hierarchy_results))

            # Validate party data
            # Could add party validation here

            # Cleanup temporary data
            # Could add cleanup actions here

        except Exception as e:
            results["warnings"].append(f"Post-migration validation failed: {str(e)}")

        return results

    # Prerequisite check methods

    def _check_eboekhouden_settings(self, config: Dict) -> Dict:
        """Check E-Boekhouden settings configuration."""
        try:
            settings = frappe.get_single("E-Boekhouden Settings")

            checks = [
                ("API Token", bool(settings.api_token)),
                ("Default Company", bool(settings.default_company)),
                ("Username", bool(settings.username)),
            ]

            passed = all(result for _, result in checks)

            return {
                "passed": passed,
                "details": [f"{name}: {'✓' if result else '✗'}" for name, result in checks],
                "errors": [] if passed else ["E-Boekhouden settings incomplete"],
            }

        except Exception as e:
            return {"passed": False, "errors": [f"Settings check failed: {str(e)}"]}

    def _check_company_config(self, config: Dict) -> Dict:
        """Check company configuration."""
        try:
            company_doc = frappe.get_doc("Company", self.company)

            checks = [
                ("Company exists", True),
                ("Cost Center", bool(company_doc.cost_center)),
                ("Default Currency", bool(company_doc.default_currency)),
            ]

            passed = all(result for _, result in checks)

            return {
                "passed": passed,
                "details": [f"{name}: {'✓' if result else '✗'}" for name, result in checks],
            }

        except Exception as e:
            return {"passed": False, "errors": [f"Company check failed: {str(e)}"]}

    def _check_custom_fields(self, config: Dict) -> Dict:
        """Check required custom fields."""
        required_fields = [
            ("Customer", "eboekhouden_relation_code"),
            ("Supplier", "eboekhouden_relation_code"),
            ("Account", "eboekhouden_account_id"),
        ]

        missing_fields = []

        for doctype, fieldname in required_fields:
            if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}):
                missing_fields.append(f"{doctype}.{fieldname}")

        return {
            "passed": len(missing_fields) == 0,
            "details": [f"Missing fields: {', '.join(missing_fields)}"]
            if missing_fields
            else ["All custom fields present"],
            "warnings": [f"Missing custom fields: {', '.join(missing_fields)}"] if missing_fields else [],
        }

    def _check_api_connectivity(self, config: Dict) -> Dict:
        """Check E-Boekhouden API connectivity."""
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient

            client = EBoekhoudenRESTClient()
            # Simple connectivity test
            client.get_accounts(limit=1)

            return {"passed": True, "details": ["API connectivity verified"]}

        except Exception as e:
            return {"passed": False, "errors": [f"API connectivity failed: {str(e)}"]}

    def _check_migration_permissions(self, config: Dict) -> Dict:
        """Check migration permissions."""
        from verenigingen.e_boekhouden.utils.security_helper import has_migration_permission

        required_permissions = ["account_creation", "party_creation", "payment_processing", "journal_entries"]

        missing_permissions = []

        for permission in required_permissions:
            if not has_migration_permission(permission):
                missing_permissions.append(permission)

        return {
            "passed": len(missing_permissions) == 0,
            "details": [f"Missing permissions: {', '.join(missing_permissions)}"]
            if missing_permissions
            else ["All permissions available"],
            "errors": [f"Missing migration permissions: {', '.join(missing_permissions)}"]
            if missing_permissions
            else [],
        }

    def _check_database_space(self, config: Dict) -> Dict:
        """Check available database space."""
        # Basic check - could be enhanced with actual space monitoring
        return {
            "passed": True,
            "details": ["Database space check skipped"],
            "warnings": ["Database space not monitored"],
        }

    def _log(self, message: str):
        """Add message to migration log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp}: {message}"
        self.migration_log.append(log_entry)
        frappe.logger().info(f"Migration Coordinator: {message}")


# Convenience functions for backward compatibility
def coordinate_migration(company: str, config: Dict) -> Dict:
    """Backward compatibility wrapper for migration coordination."""
    coordinator = EBoekhoudenMigrationCoordinator(company)
    return coordinator.coordinate_full_migration(config)


def validate_migration_prerequisites(company: str, config: Dict) -> Dict:
    """Backward compatibility wrapper for prerequisite validation."""
    coordinator = EBoekhoudenMigrationCoordinator(company)
    return coordinator.validate_prerequisites(config)
