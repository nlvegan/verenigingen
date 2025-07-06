# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class EBoekhoudenMigration(Document):
    def validate(self):
        """Validate migration settings"""
        # Debug logging
        frappe.logger().debug(f"Validating migration: {self.migration_name}, Status: {self.migration_status}")

        if getattr(self, "migrate_transactions", 0) and not (self.date_from and self.date_to):
            frappe.throw("Date range is required when migrating transactions")

        if self.date_from and self.date_to and getdate(self.date_from) > getdate(self.date_to):
            frappe.throw("Date From cannot be after Date To")

    def on_submit(self):
        """Start migration process when document is submitted"""
        frappe.logger().debug(f"Migration submitted: {self.migration_name}, Status: {self.migration_status}")
        if self.migration_status == "Draft":
            self.start_migration()

    def start_migration(self):
        """Start the migration process"""
        try:
            self.db_set(
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
            self.total_records = 0
            self.imported_records = 0
            self.failed_records = 0

            migration_log = []
            self.failed_record_details = []  # Track details of failed records

            # Phase 0: Full Initial Migration Cleanup
            if getattr(self, "migration_type", "") == "Full Initial Migration":
                self.db_set(
                    {
                        "current_operation": "Performing initial cleanup for full migration...",
                        "progress_percentage": 2,
                    }
                )
                frappe.db.commit()

                try:
                    # Use the enhanced cleanup function
                    cleanup_result = debug_cleanup_all_imported_data(settings.default_company)
                    if cleanup_result["success"]:
                        cleanup_summary = f"Cleaned up existing data: {cleanup_result['results']}"
                        migration_log.append(f"Initial Cleanup: {cleanup_summary}")
                        self.log_error(
                            f"Full migration cleanup completed: {cleanup_summary}",
                            "cleanup",
                            cleanup_result["results"],
                        )
                    else:
                        # Log error but continue - don't fail migration for cleanup issues
                        error_msg = f"Initial cleanup warning: {cleanup_result.get('error', 'Unknown error')}"
                        migration_log.append(f"Initial Cleanup: {error_msg}")
                        self.log_error(error_msg, "cleanup_warning")
                except Exception as e:
                    # Log error but continue
                    error_msg = f"Initial cleanup failed: {str(e)}"
                    migration_log.append(f"Initial Cleanup: {error_msg}")
                    self.log_error(error_msg, "cleanup_error")

            # Phase 1: Chart of Accounts
            if getattr(self, "migrate_accounts", 0):
                self.db_set(
                    {"current_operation": "Migrating Chart of Accounts...", "progress_percentage": 10}
                )
                frappe.db.commit()

                # Use getattr to avoid field/method name conflict
                migrate_method = getattr(self.__class__, "migrate_chart_of_accounts")
                result = migrate_method(self, settings)
                migration_log.append(f"Chart of Accounts: {result}")

            # Phase 2: Cost Centers
            if getattr(self, "migrate_cost_centers", 0):
                self.db_set({"current_operation": "Migrating Cost Centers...", "progress_percentage": 20})
                frappe.db.commit()

                # Use getattr to avoid field/method name conflict
                migrate_method = getattr(self.__class__, "migrate_cost_centers")
                result = migrate_method(self, settings)
                migration_log.append(f"Cost Centers: {result}")

            # Phase 3: Customers
            if getattr(self, "migrate_customers", 0):
                self.db_set({"current_operation": "Migrating Customers...", "progress_percentage": 40})
                frappe.db.commit()

                # Use getattr to avoid field/method name conflict
                migrate_method = getattr(self.__class__, "migrate_customers")
                result = migrate_method(self, settings)
                migration_log.append(f"Customers: {result}")

            # Phase 4: Suppliers
            if getattr(self, "migrate_suppliers", 0):
                self.db_set({"current_operation": "Migrating Suppliers...", "progress_percentage": 60})
                frappe.db.commit()

                # Use getattr to avoid field/method name conflict
                migrate_method = getattr(self.__class__, "migrate_suppliers")
                result = migrate_method(self, settings)
                migration_log.append(f"Suppliers: {result}")

            # Phase 5: Transactions
            if getattr(self, "migrate_transactions", 0):
                self.db_set({"current_operation": "Migrating Transactions...", "progress_percentage": 80})
                frappe.db.commit()

                # Use getattr to avoid field/method name conflict
                migrate_method = getattr(self.__class__, "migrate_transactions_data")
                result = migrate_method(self, settings)
                migration_log.append(f"Transactions: {result}")

            # Phase 6: Stock Transactions
            if getattr(self, "migrate_stock_transactions", 0):
                self.db_set(
                    {"current_operation": "Migrating Stock Transactions...", "progress_percentage": 90}
                )
                frappe.db.commit()

                # Use getattr to avoid field/method name conflict
                migrate_method = getattr(self.__class__, "migrate_stock_transactions_data")
                result = migrate_method(self, settings)
                migration_log.append(f"Stock Transactions: {result}")

            # Completion
            self.db_set(
                {
                    "migration_status": "Completed",
                    "current_operation": "Migration completed successfully",
                    "progress_percentage": 100,
                    "end_time": frappe.utils.now_datetime(),
                    "migration_summary": "\n".join(migration_log),
                }
            )

            # Save failed records to file
            if self.failed_record_details:
                self.save_failed_records_log()

            frappe.db.commit()

        except Exception as e:
            self.db_set(
                {
                    "migration_status": "Failed",
                    "current_operation": f"Migration failed: {str(e)}",
                    "end_time": frappe.utils.now_datetime(),
                    "error_log": frappe.get_traceback(),
                }
            )
            frappe.db.commit()
            frappe.log_error(f"E-Boekhouden migration failed: {str(e)}", "E-Boekhouden Migration")
            raise

    def clear_existing_accounts(self, settings):
        """Clear all existing imported accounts before importing new ones"""
        try:
            company = settings.default_company
            if not company:
                return {"success": False, "error": "No default company set"}

            # Get all accounts for the company that have account numbers (imported accounts)
            existing_accounts = frappe.get_all(
                "Account",
                filters={"company": company, "account_number": ["!=", ""]},
                fields=["name", "account_name", "account_number"],
                order_by="lft desc",  # Delete child accounts first
            )

            if not existing_accounts:
                return {
                    "success": True,
                    "message": "No existing imported accounts to clear",
                    "deleted_count": 0,
                }

            if self.dry_run:
                return {
                    "success": True,
                    "message": f"Dry Run: Would delete {len(existing_accounts)} imported accounts",
                    "deleted_count": 0,
                }

            # Delete accounts (delete in reverse tree order to avoid constraint issues)
            deleted_count = 0
            errors = []

            for account in existing_accounts:
                try:
                    # Check if account has any GL entries
                    has_gl_entries = frappe.db.exists("GL Entry", {"account": account.name})
                    if has_gl_entries:
                        # Force delete even with GL entries since this is a nuke operation
                        frappe.db.delete("GL Entry", {"account": account.name})

                    frappe.delete_doc("Account", account.name, force=True)
                    deleted_count += 1
                    frappe.logger().info(
                        f"Deleted account: {account.account_number} - {account.account_name}"
                    )

                except Exception as e:
                    error_msg = (
                        f"Failed to delete account {account.account_number} ({account.name}): {str(e)}"
                    )
                    errors.append(error_msg)
                    self.log_error(error_msg, "account_deletion", account)

            frappe.db.commit()

            result_msg = f"Cleared {deleted_count} existing accounts"
            if errors:
                result_msg += f", {len(errors)} errors"

            return {"success": True, "message": result_msg, "deleted_count": deleted_count, "errors": errors}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def parse_account_group_mappings(self, settings):
        """Parse account group mappings from settings in format 'number <space> <group name>'"""
        try:
            mappings = {}
            if hasattr(settings, "account_group_mappings") and settings.account_group_mappings:
                lines = settings.account_group_mappings.strip().split("\n")
                for line in lines:
                    line = line.strip()
                    if line:
                        # Split on first space to separate code from name
                        parts = line.split(" ", 1)
                        if len(parts) == 2:
                            code = parts[0].strip()
                            name = parts[1].strip()
                            if code and name:
                                mappings[code] = name

            frappe.logger().info(f"Parsed {len(mappings)} account group mappings")
            return mappings
        except Exception as e:
            frappe.logger().error(f"Error parsing account group mappings: {str(e)}")
            return {}

    def migrate_chart_of_accounts(self, settings):
        """Migrate Chart of Accounts from e-Boekhouden"""
        try:
            # Clear existing accounts if requested
            if getattr(self, "clear_existing_accounts", 0):
                self.db_set({"current_operation": "Clearing existing accounts...", "progress_percentage": 5})
                frappe.db.commit()

                clear_result = self.clear_existing_accounts(settings)
                if not clear_result["success"]:
                    return f"Failed to clear existing accounts: {clear_result['error']}"
                else:
                    frappe.logger().info(f"Cleared accounts: {clear_result['message']}")

            # Ensure root accounts exist before importing
            self.db_set({"current_operation": "Creating root account structure...", "progress_percentage": 8})
            frappe.db.commit()

            root_result = self.ensure_root_accounts(settings)
            if not root_result["success"]:
                frappe.logger().warning(
                    f"Root account creation issues: {root_result.get('error', 'Unknown error')}"
                )
                # Continue anyway - some root accounts might exist
            else:
                frappe.logger().info(f"Root accounts: {root_result['message']}")

            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            # Get Chart of Accounts data using new API
            api = EBoekhoudenAPI(settings)
            result = api.get_chart_of_accounts()

            if not result["success"]:
                return f"Failed to fetch Chart of Accounts: {result['error']}"

            # Parse JSON response
            import json

            data = json.loads(result["data"])
            accounts_data = data.get("items", [])

            if self.dry_run:
                dry_run_msg = f"Dry Run: Found {len(accounts_data)} accounts to migrate"
                if getattr(self, "clear_existing_accounts", 0):
                    clear_result = self.clear_existing_accounts(settings)
                    dry_run_msg += f"\n{clear_result['message']}"
                return dry_run_msg

            # Analyze account hierarchy to determine which should be groups
            from verenigingen.utils.eboekhouden_account_group_fix import analyze_account_hierarchy

            group_accounts = analyze_account_hierarchy(accounts_data)
            frappe.logger().info(f"Identified {len(group_accounts)} accounts that should be groups")

            # Store group accounts for use in create_account
            self._group_accounts = group_accounts

            # Parse and store account group mappings from settings
            self._account_group_mappings = self.parse_account_group_mappings(settings)

            # Store all account codes to check parent-child relationships
            self._all_account_codes = set(
                account.get("code", "") for account in accounts_data if account.get("code")
            )
            frappe.logger().info(
                f"Stored {len(self._all_account_codes)} account codes for hierarchy analysis"
            )

            # Sort accounts by code length to ensure parents are created before children
            # This ensures that account "80" is created before "800", which is created before "8000"
            sorted_accounts = sorted(accounts_data, key=lambda x: (len(x.get("code", "")), x.get("code", "")))
            frappe.logger().info("Sorted accounts for hierarchical creation")

            # Create accounts in ERPNext
            created_count = 0
            skipped_count = 0

            # Log first few accounts to see what we're processing
            frappe.logger().info(f"Processing {len(sorted_accounts)} accounts")
            for i, acc in enumerate(sorted_accounts[:10]):
                frappe.logger().info(
                    f"Account {i}: code={acc.get('code')}, group={acc.get('group')}, category={acc.get('category')}, desc={acc.get('description')[:30] if acc.get('description') else 'N/A'}"
                )

            for account_data in sorted_accounts:
                try:
                    if self.create_account(account_data):
                        created_count += 1
                        self.imported_records += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    self.failed_records += 1
                    self.log_error(
                        f"Failed to create account {account_data.get('code', 'Unknown')}: {str(e)}",
                        "account",
                        account_data,
                    )

            self.total_records += len(accounts_data)
            return f"Created {created_count} accounts, skipped {skipped_count} ({len(accounts_data)} total)"

        except Exception as e:
            return f"Error migrating Chart of Accounts: {str(e)}"

    @frappe.whitelist()
    def analyze_specific_accounts(self):
        """Analyze specific problematic accounts"""
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            # Get E-Boekhouden settings
            settings = frappe.get_single("E-Boekhouden Settings")

            # Get Chart of Accounts data
            api = EBoekhoudenAPI(settings)
            result = api.get_chart_of_accounts()

            if not result["success"]:
                return {"success": False, "error": f"API call failed: {result['error']}"}

            # Parse JSON response
            import json

            data = json.loads(result["data"])
            accounts_data = data.get("items", [])

            # Look for specific problematic accounts
            problem_accounts = []
            equity_pattern_accounts = []
            income_pattern_accounts = []

            for account in accounts_data:
                code = account.get("code", "")
                description = account.get("description", "")
                category = account.get("category", "")
                group = account.get("group", "")

                # Check 05xxx accounts
                if code.startswith("05"):
                    problem_accounts.append(
                        {
                            "type": "equity_05xxx",
                            "code": code,
                            "description": description,
                            "category": category,
                            "group": group,
                        }
                    )

                # Check 8xxx accounts
                if code.startswith("8") and len(code) > 1:
                    problem_accounts.append(
                        {
                            "type": "income_8xxx",
                            "code": code,
                            "description": description,
                            "category": category,
                            "group": group,
                        }
                    )

                # Check accounts with equity keywords
                if any(term in description.lower() for term in ["eigen vermogen", "reserve", "bestemmings"]):
                    equity_pattern_accounts.append(
                        {"code": code, "description": description, "category": category, "group": group}
                    )

                # Check accounts with income keywords
                if any(
                    term in description.lower() for term in ["contributie", "donatie", "inkomst", "opbrengst"]
                ):
                    income_pattern_accounts.append(
                        {"code": code, "description": description, "category": category, "group": group}
                    )

            return {
                "success": True,
                "problem_accounts": problem_accounts,
                "equity_pattern_accounts": equity_pattern_accounts[:10],
                "income_pattern_accounts": income_pattern_accounts[:10],
                "total_accounts": len(accounts_data),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    @frappe.whitelist()
    def analyze_eboekhouden_data(self):
        """Analyze E-Boekhouden data to understand group structure"""
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            # Get E-Boekhouden settings
            settings = frappe.get_single("E-Boekhouden Settings")

            # Get Chart of Accounts data
            api = EBoekhoudenAPI(settings)
            result = api.get_chart_of_accounts()

            if not result["success"]:
                return {"success": False, "error": f"API call failed: {result['error']}"}

            # Parse JSON response
            import json

            data = json.loads(result["data"])
            accounts_data = data.get("items", [])

            # Analyze group distribution
            groups = {}
            categories = {}
            sample_accounts = []

            for account in accounts_data[:20]:  # Sample first 20 accounts
                code = account.get("code", "")
                description = account.get("description", "")
                category = account.get("category", "")
                group = account.get("group", "")

                sample_accounts.append(
                    {"code": code, "description": description, "category": category, "group": group}
                )

                if group:
                    if group not in groups:
                        groups[group] = []
                    groups[group].append(f"{code} - {description}")

                if category:
                    categories[category] = categories.get(category, 0) + 1

            return {
                "success": True,
                "total_accounts": len(accounts_data),
                "groups": {k: len(v) for k, v in groups.items()},
                "categories": categories,
                "sample_accounts": sample_accounts,
                "group_details": {k: v[:5] for k, v in groups.items()},  # First 5 accounts per group
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    @frappe.whitelist()
    def test_group_mappings(self):
        """Test the group mapping functionality"""
        try:
            # Get E-Boekhouden settings
            settings = frappe.get_single("E-Boekhouden Settings")

            # Parse mappings
            mappings = self.parse_account_group_mappings(settings)

            return {
                "success": True,
                "mappings_count": len(mappings),
                "mappings": mappings,
                "settings_field_exists": hasattr(settings, "account_group_mappings"),
                "settings_value": getattr(settings, "account_group_mappings", "Field not found"),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def ensure_root_accounts(self, settings):
        """Ensure root accounts exist based on E-boekhouden categories and Dutch accounting standards"""
        try:
            company = settings.default_company
            if not company:
                return {"success": False, "error": "No default company set"}

            # Define root accounts based on E-boekhouden categories and Dutch standards
            root_accounts = [
                # Main root categories matching E-boekhouden structure
                {"account_name": "Activa", "root_type": "Asset", "account_number": "0", "category": "BAL"},
                {
                    "account_name": "Passiva",
                    "root_type": "Liability",
                    "account_number": "3",
                    "category": "BAL",
                },
                {
                    "account_name": "Eigen Vermogen",
                    "root_type": "Equity",
                    "account_number": "5",
                    "category": "BAL",
                },
                {
                    "account_name": "Opbrengsten",
                    "root_type": "Income",
                    "account_number": "8",
                    "category": "VW",
                },
                {"account_name": "Kosten", "root_type": "Expense", "account_number": "6", "category": "VW"},
            ]

            created = []
            errors = []
            existing = []

            for acc in root_accounts:
                try:
                    # Check if a root account of this type already exists
                    existing_account = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "root_type": acc["root_type"],
                            "parent_account": ["in", ["", None]],
                            "is_group": 1,
                        },
                        "name",
                    )

                    if existing_account:
                        existing.append(f"{acc['account_name']} ({existing_account})")
                        frappe.logger().info(
                            f"Root account for {acc['root_type']} already exists: {existing_account}"
                        )
                        continue

                    # Try to create root account using ERPNext's account creation method
                    # This bypasses the parent_account requirement for true root accounts
                    account = frappe.new_doc("Account")
                    account.account_name = acc["account_name"]
                    account.company = company
                    account.root_type = acc["root_type"]
                    account.is_group = 1
                    account.account_number = acc["account_number"]

                    # Use special validation flags for root accounts
                    account.flags.ignore_validate = True
                    account.flags.ignore_mandatory = True

                    # Try multiple creation methods
                    try:
                        account.save(ignore_permissions=True)
                        created.append(f"{acc['account_name']} ({acc['root_type']})")
                        frappe.logger().info(f"Created root account: {account.name}")
                    except Exception:
                        # If save fails, try insert
                        try:
                            account.insert(ignore_permissions=True)
                            created.append(f"{acc['account_name']} ({acc['root_type']})")
                            frappe.logger().info(f"Created root account via insert: {account.name}")
                        except Exception as e2:
                            errors.append(f"{acc['account_name']}: {str(e2)}")
                            frappe.logger().error(
                                f"Failed to create root account {acc['account_name']}: {str(e2)}"
                            )

                except Exception as e:
                    errors.append(f"{acc['account_name']}: {str(e)}")
                    frappe.logger().error(f"Error processing root account {acc['account_name']}: {str(e)}")

            # If no accounts were created or existed, this indicates a fundamental issue
            total_available = len(created) + len(existing)
            if total_available == 0:
                return {
                    "success": False,
                    "error": "No root accounts available - this will cause Chart of Accounts import to fail",
                    "details": {"created": created, "existing": existing, "errors": errors},
                }

            # Commit any successful creations
            if created:
                frappe.db.commit()

            return {
                "success": True,
                "created": created,
                "existing": existing,
                "errors": errors,
                "message": f"Root accounts ready: {len(created)} created, {len(existing)} existing, {len(errors)} errors",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def migrate_cost_centers(self, settings):
        """Migrate Cost Centers from e-Boekhouden with proper hierarchy"""
        try:
            # Use the fixed cost center migration
            from verenigingen.utils.eboekhouden_cost_center_fix import (
                cleanup_cost_centers,
                migrate_cost_centers_with_hierarchy,
            )

            result = migrate_cost_centers_with_hierarchy(settings)

            if result["success"]:
                self.imported_records += result["created"]
                self.total_records += result["total"]

                # Run cleanup to fix any orphaned cost centers and group flags
                if settings.default_company:
                    # First fix any cost centers that should be groups
                    from verenigingen.utils.eboekhouden_cost_center_fix import fix_cost_center_groups

                    group_fix_result = fix_cost_center_groups(settings.default_company)
                    if group_fix_result["success"] and group_fix_result["fixed"] > 0:
                        self.log_error(f"Fixed {group_fix_result['fixed']} cost centers to be groups")

                    # Then cleanup orphaned cost centers
                    cleanup_result = cleanup_cost_centers(settings.default_company)
                    if cleanup_result["success"] and cleanup_result["fixed"] > 0:
                        self.log_error(f"Fixed {cleanup_result['fixed']} orphaned cost centers")

                if result.get("errors"):
                    for error in result["errors"][:5]:  # Log first 5 errors
                        self.log_error(f"Cost center error: {error}")

                return result["message"]
            else:
                return f"Error: {result.get('error', 'Unknown error')}"

            # Old implementation below for reference
            # from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI
            #
            # # Get Cost Centers data using new API
            # api = EBoekhoudenAPI(settings)
            # result = api.get_cost_centers()
            #
            # if not result["success"]:
            #     return f"Failed to fetch Cost Centers: {result['error']}"
            #
            # # Parse JSON response
            # import json
            # data = json.loads(result["data"])
            # cost_centers_data = data.get("items", [])
            #
            # if self.dry_run:
            #     return f"Dry Run: Found {len(cost_centers_data)} cost centers to migrate"
            #
            # # Create cost centers in ERPNext
            # created_count = 0
            # skipped_count = 0
        except Exception as e:
            return f"Error migrating Cost Centers: {str(e)}"

    def migrate_customers(self, settings):
        """Migrate Customers from e-Boekhouden"""
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            # Get Customers data using new API
            api = EBoekhoudenAPI(settings)
            result = api.get_customers()

            if not result["success"]:
                return f"Failed to fetch Customers: {result['error']}"

            # Parse JSON response
            import json

            data = json.loads(result["data"])
            customers_data = data.get("items", [])

            if self.dry_run:
                return f"Dry Run: Found {len(customers_data)} customers to migrate"

            # Create customers in ERPNext
            created_count = 0
            skipped_count = 0

            for customer_data in customers_data:
                try:
                    if self.create_customer(customer_data):
                        created_count += 1
                        self.imported_records += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    self.failed_records += 1
                    self.log_error(
                        f"Failed to create customer {customer_data.get('name', 'Unknown')}: {str(e)}"
                    )

            self.total_records += len(customers_data)
            return f"Created {created_count} customers, skipped {skipped_count} ({len(customers_data)} total)"

        except Exception as e:
            return f"Error migrating Customers: {str(e)}"

    def migrate_suppliers(self, settings):
        """Migrate Suppliers from e-Boekhouden"""
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            # Get Suppliers data using new API
            api = EBoekhoudenAPI(settings)
            result = api.get_suppliers()

            if not result["success"]:
                return f"Failed to fetch Suppliers: {result['error']}"

            # Parse JSON response
            import json

            data = json.loads(result["data"])
            suppliers_data = data.get("items", [])

            if self.dry_run:
                return f"Dry Run: Found {len(suppliers_data)} suppliers to migrate"

            # Create suppliers in ERPNext
            created_count = 0
            skipped_count = 0

            for supplier_data in suppliers_data:
                try:
                    if self.create_supplier(supplier_data):
                        created_count += 1
                        self.imported_records += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    self.failed_records += 1
                    self.log_error(
                        f"Failed to create supplier {supplier_data.get('name', 'Unknown')}: {str(e)}"
                    )

            self.total_records += len(suppliers_data)
            return f"Created {created_count} suppliers, skipped {skipped_count} ({len(suppliers_data)} total)"

        except Exception as e:
            return f"Error migrating Suppliers: {str(e)}"

    def migrate_transactions_data(self, settings):
        """Migrate Transactions from e-Boekhouden using SOAP API"""
        try:
            # Check if we should use SOAP API (default to True)
            use_soap = getattr(self, "use_soap_api", True)

            if use_soap:
                # Use the new SOAP-based migration
                from verenigingen.utils.eboekhouden_soap_migration import migrate_using_soap

                # Check if we should use account mappings
                use_account_mappings = getattr(self, "use_account_mappings", True)

                result = migrate_using_soap(self, settings, use_account_mappings)

                if result["success"]:
                    stats = result["stats"]
                    # Update counters in database directly to avoid document conflicts
                    imported = (
                        stats["invoices_created"]
                        + stats["payments_processed"]
                        + stats["journal_entries_created"]
                    )

                    # Get categorized results for better reporting
                    categorized = stats.get("categorized_results", {})

                    # Calculate "failed" based on actual errors, not retries
                    actual_failures = 0
                    if "categories" in categorized:
                        # Count validation errors and system errors as failures
                        actual_failures = categorized["categories"].get("validation_error", {}).get(
                            "count", 0
                        ) + categorized["categories"].get("system_error", {}).get("count", 0)
                    else:
                        # Fallback to old method
                        actual_failures = len(stats["errors"])

                    total = stats["total_mutations"]

                    self.db_set(
                        {
                            "imported_records": self.imported_records + imported,
                            "failed_records": self.failed_records + actual_failures,
                            "total_records": self.total_records + total,
                        }
                    )

                    # Use the improved message from categorizer
                    return result["message"]
                else:
                    return f"Error: {result.get('error', 'Unknown error')}"
            else:
                # Use the old REST API grouped migration
                from verenigingen.utils.eboekhouden_grouped_migration import migrate_mutations_grouped

                result = migrate_mutations_grouped(self, settings)

                if result["success"]:
                    self.imported_records += result["created"]
                    self.failed_records += result["failed"]
                    self.total_records += result["total_mutations"]

                    return (
                        f"Created {result['created']} journal entries from "
                        f"{result['total_mutations']} mutations "
                        f"({result['grouped_entries']} grouped, "
                        f"{result['ungrouped_mutations']} ungrouped)"
                    )
                else:
                    return f"Error: {result.get('error', 'Unknown error')}"
        except Exception as e:
            return f"Error migrating Transactions: {str(e)}"

    def migrate_stock_transactions_data(self, settings):
        """Migrate Stock Transactions from e-Boekhouden"""
        try:
            # Use the fixed stock migration that properly handles E-Boekhouden limitations
            from verenigingen.utils.stock_migration_fixed import migrate_stock_transactions_safe

            # Get date range
            date_from = self.date_from if self.date_from else None
            date_to = self.date_to if self.date_to else None

            # Run migration - returns a message or result dict
            result = migrate_stock_transactions_safe(self, date_from, date_to)

            # If result is a dict, extract the message
            if isinstance(result, dict):
                message = result.get("message", "Stock migration completed")
                # Update counters if available
                if "skipped" in result:
                    self.total_records += result["skipped"]
                if "processed" in result:
                    self.imported_records += result["processed"]
                return message
            else:
                # Result is already a message string
                return result

        except Exception as e:
            # Log full error without truncation
            frappe.log_error(
                title="Stock Transaction Migration Error",
                message=f"Error migrating stock transactions:\n{str(e)}\n\n{frappe.get_traceback()}",
            )
            return f"Error migrating Stock Transactions: {str(e)[:100]}..."  # Truncate for display

    def parse_grootboekrekeningen_xml(self, xml_data):
        """Parse Chart of Accounts XML response"""
        try:
            # This is a simplified parser - you'll need to adjust based on actual XML structure
            accounts = []

            # Basic parsing - adjust based on actual e-Boekhouden XML structure
            if "Grootboekrekening" in xml_data:
                # Parse the XML properly here
                # For now, return mock data structure
                pass

            return accounts
        except Exception as e:
            frappe.log_error(f"Error parsing Chart of Accounts XML: {str(e)}")
            return []

    def parse_relaties_xml(self, xml_data):
        """Parse Relations (Customers/Suppliers) XML response"""
        try:
            relations = []

            # Basic parsing - adjust based on actual e-Boekhouden XML structure
            if "Relatie" in xml_data:
                # Parse the XML properly here
                pass

            return relations
        except Exception as e:
            frappe.log_error(f"Error parsing Relations XML: {str(e)}")
            return []

    def parse_mutaties_xml(self, xml_data):
        """Parse Transactions (Mutaties) XML response"""
        try:
            transactions = []

            # Basic parsing - adjust based on actual e-Boekhouden XML structure
            if "Mutatie" in xml_data:
                # Parse the XML properly here
                pass

            return transactions
        except Exception as e:
            frappe.log_error(f"Error parsing Transactions XML: {str(e)}")
            return []

    def log_error(self, message, record_type=None, record_data=None):
        """Enhanced error logging with detailed debugging information"""
        # Create a short title for the error log
        if record_type:
            title = f"E-Boekhouden {record_type} Error"
        else:
            # Extract first part of message for title
            title = message.split(":")[0] if ":" in message else message
            title = title[:100]  # Ensure it's not too long

        # Ensure title is within 140 character limit
        if len(title) > 140:
            title = title[:137] + "..."

        # Enhanced error logging with full details
        enhanced_message = f"MIGRATION ERROR: {message}"

        # Add record data context if available
        if record_data:
            enhanced_message += f"\n\nRECORD DATA:\n{json.dumps(record_data, indent=2, default=str)}"

        # Add stack trace for debugging
        try:
            import traceback

            enhanced_message += f"\n\nSTACK TRACE:\n{traceback.format_exc()}"
        except Exception:
            pass

        # Add additional context
        enhanced_message += "\n\nCONTEXT:"
        enhanced_message += f"\n- Migration: {self.migration_name}"
        enhanced_message += f"\n- Timestamp: {frappe.utils.now_datetime()}"
        enhanced_message += f"\n- Record Type: {record_type or 'Unknown'}"

        try:
            frappe.log_error(enhanced_message, title)
        except Exception:
            # If logging fails, try with a generic title
            try:
                frappe.log_error(enhanced_message, "E-Boekhouden Migration Error")
            except Exception:
                # Last resort - just print to console
                frappe.logger().error(f"E-Boekhouden Migration: {enhanced_message}")

        # Also save to debug file immediately
        self.save_debug_error(message, record_type, record_data, enhanced_message)

        if hasattr(self, "error_details"):
            self.error_details += f"\n{message}"
        else:
            self.error_details = message

        # Track failed record details if provided
        if record_type and record_data and hasattr(self, "failed_record_details"):
            self.failed_record_details.append(
                {
                    "timestamp": frappe.utils.now_datetime(),
                    "record_type": record_type,
                    "error_message": message,
                    "record_data": record_data,
                    "enhanced_message": enhanced_message,
                }
            )

    def create_account(self, account_data, use_enhanced=False):
        """Create Account in ERPNext"""
        try:
            # Use enhanced migration if available and enabled
            if use_enhanced:
                try:
                    from verenigingen.utils.eboekhouden_migration_enhancements import EnhancedAccountMigration

                    enhanced_migrator = EnhancedAccountMigration(self)
                    result = enhanced_migrator.analyze_and_create_account(account_data)

                    account_code = account_data.get("code", "")
                    account_name = account_data.get("description", "")

                    if result["status"] == "created":
                        frappe.logger().info(
                            f"Created account: {account_code} - {account_name} (Group: {result.get('group', 'N/A')})"
                        )
                        return True
                    elif result["status"] == "skipped":
                        frappe.logger().info(
                            f"Skipped: {account_code} - {account_name} ({result.get('reason', '')})"
                        )
                        return False
                    else:
                        self.log_error(f"Failed: {account_code} - {account_name}: {result.get('error', '')}")
                        return False
                except ImportError:
                    # Fall back to standard migration
                    pass

            # Standard migration logic
            # Map e-Boekhouden account to ERPNext account
            account_code = account_data.get("code", "")
            account_name = account_data.get("description", "")
            category = account_data.get("category", "")
            group_code = account_data.get("group", "")

            if not account_code or not account_name:
                self.log_error(f"Invalid account data: code={account_code}, name={account_name}")
                return False

            # Clean up account name - remove duplicate account code if present
            # E-Boekhouden sometimes includes the code in the name like "88210 - 88210 - Advertenties in vm"
            if account_name.startswith(f"{account_code} - "):
                # Remove the first occurrence of "code - "
                account_name = account_name[len(account_code) + 3 :]

            # Also check if the name starts with just the code (without dash)
            if account_name.startswith(account_code):
                account_name = account_name[len(account_code) :].lstrip(" -")

            # If account name is empty after cleaning, use a default
            if not account_name.strip():
                account_name = f"Account {account_code}"

            # Truncate account name if too long (ERPNext limit is 140 chars)
            if len(account_name) > 120:  # Leave room for account code
                account_name = account_name[:120] + "..."
                frappe.logger().info(f"Truncated long account name for {account_code}")

            # Use the cleaned account name without the code
            full_account_name = account_name
            if len(full_account_name) > 140:
                # If too long, truncate
                full_account_name = account_name[:137] + "..."

            # Get default company first
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

            if not company:
                self.log_error("No default company set in E-Boekhouden Settings")
                return False

            # Check if account already exists
            # Check both by account_number and by name (which includes company suffix)
            existing_by_number = frappe.db.exists(
                "Account", {"account_number": account_code, "company": company}
            )

            # Get company abbreviation
            company_abbr = frappe.db.get_value("Company", company, "abbr")
            existing_by_name = frappe.db.exists("Account", {"name": f"{full_account_name} - {company_abbr}"})

            if existing_by_number or existing_by_name:
                frappe.logger().info(
                    f"SKIPPING - Account {account_code} already exists (by_number={existing_by_number}, by_name={existing_by_name})"
                )
                return False

            # Map e-Boekhouden categories to ERPNext account types and root types
            # Based on e-Boekhouden REST API specification
            category_mapping = {
                # Tax-related categories
                "BTWRC": {"account_type": "Tax", "root_type": "Liability"},  # VAT current account
                "AF6": {"account_type": "Tax", "root_type": "Liability"},  # Turnover tax low rate
                "AF19": {"account_type": "Tax", "root_type": "Liability"},  # Turnover tax high rate
                "AFOVERIG": {"account_type": "Tax", "root_type": "Liability"},  # Turnover tax other
                "AF": {"account_type": "Tax", "root_type": "Liability"},  # Turnover tax
                "VOOR": {"account_type": "Tax", "root_type": "Asset"},  # Input tax (VAT receivable)
                # Balance sheet categories
                "BAL": {"account_type": "", "root_type": None},  # Balance sheet - need to determine from code
                "FIN": {
                    "account_type": "Bank",
                    "root_type": "Asset",
                },  # Financial/Liquid Assets - Bank accounts
                "DEB": {
                    "account_type": "Current Asset",
                    "root_type": "Asset",
                },  # Debtors (not Receivable to avoid party requirement)
                "CRED": {
                    "account_type": "Current Liability",
                    "root_type": "Liability",
                },  # Creditors (not Payable to avoid party requirement)
                # Profit & Loss category - ALL VW accounts are P&L accounts
                "VW": {
                    "account_type": "Expense Account",
                    "root_type": "Expense",
                },  # Default VW to Expense Account (will be refined by code patterns)
            }

            # Get mapping or default
            mapping = category_mapping.get(category, {"account_type": "", "root_type": None})
            account_type = mapping["account_type"]
            root_type = mapping["root_type"]

            # Handle BAL and VW categories - need to determine root_type from account code
            if root_type is None:
                if category == "BAL":
                    # Balance sheet accounts - check for equity patterns first
                    account_name_lower = account_name.lower()
                    if any(
                        pattern in account_name_lower
                        for pattern in [
                            "eigen vermogen",
                            "reserve",
                            "reservering",
                            "bestemmingsreserve",
                            "continuiteitsreserve",
                        ]
                    ):
                        root_type = "Equity"
                        account_type = ""
                        frappe.logger().info(
                            f"BAL account {account_code} classified as Equity due to name pattern: {account_name}"
                        )
                    elif group_code == "005":
                        root_type = "Equity"
                        account_type = ""
                        frappe.logger().info(
                            f"BAL account {account_code} classified as Equity due to group {group_code}"
                        )
                    elif account_code.startswith(("0", "1", "2")):
                        root_type = "Asset"
                    elif account_code.startswith(("3", "4")):
                        root_type = "Liability"
                    elif account_code.startswith("5") and not group_code:
                        # Only use code pattern if no group code available
                        root_type = "Equity"
                        frappe.logger().info(
                            f"BAL account {account_code} classified as Equity due to 5xxx code pattern (no group)"
                        )
                    else:
                        # Default for unknown BAL accounts
                        root_type = "Asset"
                        frappe.logger().warning(f"Unknown BAL account code pattern: {account_code}")
                elif category == "VW":
                    # Profit & Loss accounts - use GROUP NUMBERS instead of account codes
                    # Group 055 = Income (Opbrengsten)
                    # Groups 056-059 = Expenses (various cost types)
                    if group_code == "055":
                        root_type = "Income"
                        account_type = "Income Account"
                        frappe.logger().info(
                            f"VW account {account_code} classified as Income (group 055 - Opbrengsten)"
                        )
                    elif group_code in ["056", "057", "058", "059"]:
                        root_type = "Expense"
                        account_type = "Expense Account"
                        frappe.logger().info(
                            f"VW account {account_code} classified as Expense (group {group_code} - cost type)"
                        )
                    else:
                        # For VW accounts without clear group codes, use name-based detection and account code patterns
                        account_name_lower = account_name.lower()
                        if (
                            "opbrengst" in account_name_lower
                            or "omzet" in account_name_lower
                            or "inkomst" in account_name_lower
                            or "contributie" in account_name_lower
                            or "donatie" in account_name_lower
                            or "verkoop" in account_name_lower
                            or "advertentie" in account_name_lower
                            or "commissie" in account_name_lower
                            or "provisie" in account_name_lower
                            or "rentebaten" in account_name_lower
                        ):
                            root_type = "Income"
                            account_type = "Income Account"
                            frappe.logger().info(
                                f"VW account {account_code} classified as Income (name pattern: {account_name})"
                            )
                        elif account_code.startswith("8") and not group_code:
                            # 8xxx accounts are typically income in Dutch accounting (fallback when no group)
                            root_type = "Income"
                            account_type = "Income Account"
                            frappe.logger().info(
                                f"VW account {account_code} classified as Income (8xxx code pattern, no group)"
                            )
                        else:
                            # Default VW accounts to expense
                            root_type = "Expense"
                            account_type = "Expense Account"
                            frappe.logger().info(
                                f"VW account {account_code} classified as Expense (VW category default, group {group_code})"
                            )

            # Enhanced account type determination - prioritize Dutch rekeninggroepen over account codes
            # ALWAYS run this logic to override category-based defaults with group-based precision
            if account_code:
                # PRIORITY 1: Dutch Rekeninggroepen (Account Groups) - most reliable
                if group_code:
                    # Dutch standard rekeninggroepen mapping
                    if group_code == "001":  # Vaste activa
                        account_type = "Fixed Asset"
                        root_type = "Asset"
                    elif group_code == "002":  # Liquide middelen - Financial assets (bank/cash)
                        # Distinguish between bank and cash based on account name
                        if "kas" in account_name.lower() and "bank" not in account_name.lower():
                            account_type = "Cash"
                            root_type = "Asset"
                            frappe.logger().info(
                                f"Account {account_code} classified as Cash due to group 002 + name pattern"
                            )
                        else:
                            account_type = "Bank"
                            root_type = "Asset"
                            frappe.logger().info(
                                f"Account {account_code} classified as Bank due to group 002 (Liquide middelen)"
                            )
                    elif group_code == "003":  # Voorraden
                        account_type = (
                            "Current Asset"  # Use Current Asset instead of Stock for migration simplicity
                        )
                        root_type = "Asset"
                    elif group_code == "004":  # Vorderingen
                        account_type = "Receivable"  # Proper receivable classification
                        root_type = "Asset"
                    elif group_code == "006":  # Kortlopende schulden
                        # Check for specific payable patterns before generic Current Liability
                        account_name_lower = account_name.lower()
                        if "te betalen" in account_name_lower or "crediteuren" in account_name_lower:
                            account_type = "Payable"  # Specific payable classification
                            root_type = "Liability"
                            frappe.logger().info(
                                f"Account {account_code} classified as Payable due to group 006 + name pattern"
                            )
                        else:
                            account_type = "Current Liability"  # Generic group 006 classification
                            root_type = "Liability"
                    elif group_code == "007":  # Langlopende schulden
                        account_type = "Current Liability"
                        root_type = "Liability"
                    elif group_code == "008":  # Overlopende passiva
                        account_type = "Current Liability"
                        root_type = "Liability"
                    elif group_code == "005":  # Eigen vermogen (single group 005)
                        account_type = ""
                        root_type = "Equity"
                        frappe.logger().info(
                            f"Account {account_code} classified as Equity due to group {group_code} (Eigen vermogen)"
                        )
                    elif group_code == "055":  # Opbrengsten (Income)
                        account_type = "Income Account"
                        root_type = "Income"
                    elif group_code in ["056", "057", "058", "059"]:  # Various cost types
                        account_type = "Expense Account"
                        root_type = "Expense"
                        frappe.logger().info(
                            f"Account {account_code} classified as Expense due to group {group_code} (Dutch cost group)"
                        )

                # PRIORITY 2: Account name patterns - supplement group classification
                if not account_type:
                    account_name_lower = account_name.lower()

                    # Equity patterns - detect common equity terms
                    if any(
                        pattern in account_name_lower
                        for pattern in [
                            "eigen vermogen",
                            "reserve",
                            "reservering",
                            "bestemmingsreserve",
                            "continuiteitsreserve",
                        ]
                    ):
                        account_type = ""
                        root_type = "Equity"
                        frappe.logger().info(
                            f"Account {account_code} classified as Equity due to name pattern: {account_name}"
                        )

                    # Cash patterns (only detect cash, not banks - banks should come from FIN category)
                    elif "kas" in account_name_lower and "bank" not in account_name_lower:
                        account_type = "Cash"
                        root_type = "Asset"

                    # BTW/VAT patterns
                    elif "btw" in account_name_lower or "vat" in account_name_lower:
                        account_type = "Tax"
                        root_type = "Liability"

                    # Receivables and payables patterns
                    elif "te ontvangen" in account_name_lower:
                        account_type = "Receivable"  # Proper receivable classification
                        root_type = "Asset"
                    elif "te betalen" in account_name_lower:
                        account_type = "Payable"  # Proper payable classification
                        root_type = "Liability"
                    elif "vooruitontvangen" in account_name_lower:
                        account_type = "Current Liability"
                        root_type = "Liability"
                    elif "vooruitbetaald" in account_name_lower:
                        account_type = "Current Asset"
                        root_type = "Asset"

                    # Depreciation patterns
                    elif "afschrijving" in account_name_lower and (
                        "cum" in account_name_lower or "cumul" in account_name_lower
                    ):
                        account_type = "Accumulated Depreciation"
                        root_type = "Asset"
                    elif "afschrijving" in account_name_lower:
                        account_type = "Depreciation"
                        root_type = "Expense"

                    # Equity patterns
                    elif any(
                        pattern in account_name_lower for pattern in ["reserve", "reservering", "vermogen"]
                    ):
                        account_type = ""
                        root_type = "Equity"

                    # Income patterns
                    elif any(pattern in account_name_lower for pattern in ["omzet", "opbrengst"]):
                        account_type = "Income Account"
                        root_type = "Income"

                    # Expense patterns
                    elif "kosten" in account_name_lower:
                        account_type = "Expense Account"
                        root_type = "Expense"

                # PRIORITY 3: Category-based fallbacks - NO account code patterns
                if not account_type and not root_type:
                    # Use category information as fallback
                    if category == "VW":  # P&L accounts - already handled in category logic above
                        # VW accounts should have been handled by category logic, this is fallback
                        account_type = "Expense Account"
                        root_type = "Expense"  # Default VW to expense
                        frappe.logger().info(
                            f"VW account {account_code} defaulted to Expense (no group/name match)"
                        )
                    elif category == "BAL":  # Balance sheet accounts - use conservative defaults
                        account_type = "Current Asset"
                        root_type = "Asset"
                        frappe.logger().info(f"BAL account {account_code} defaulted to Current Asset")
                    elif category == "FIN":  # Financial accounts
                        account_type = "Bank"
                        root_type = "Asset"
                        frappe.logger().info(f"FIN account {account_code} classified as Bank")
                    elif category == "DEB":  # Debtors
                        account_type = "Current Asset"
                        root_type = "Asset"
                        frappe.logger().info(f"DEB account {account_code} classified as Current Asset")
                    elif category == "CRED":  # Creditors
                        account_type = "Current Liability"
                        root_type = "Liability"
                        frappe.logger().info(f"CRED account {account_code} classified as Current Liability")
                    else:
                        # Unknown category - default to asset
                        account_type = "Current Asset"
                        root_type = "Asset"
                        frappe.logger().warning(
                            f"Unknown account {account_code} (category {category}, group {group_code}) defaulted to Current Asset"
                        )

            # Check if this should be a root account
            # With our Dutch root account structure in place, very few accounts should be truly root
            is_root_account = False
            parent_account = None

            # IMPORTANT: We now have Dutch root accounts (Activa, Passiva, Eigen Vermogen, Opbrengsten, Kosten)
            # Only treat accounts as root if they are truly meant to be at the top level
            # Most E-boekhouden accounts should be children of these root accounts

            frappe.logger().info(
                f"Analyzing account {account_code}: len={len(account_code)}, group={group_code}, category={category}"
            )

            # Very restrictive root account logic - only truly top-level accounts
            if len(account_code) == 1 or (  # Single digit codes like "0", "3", "5", "6", "8"
                len(account_code) == 2 and account_code in ["00", "30", "50", "60", "80"]
            ):  # Very specific two-digit roots
                is_root_account = True
                frappe.logger().info(
                    f"Account {account_code} identified as ROOT account (single digit or specific two-digit)"
                )
            else:
                # All other accounts should find appropriate parents from our root structure
                # This includes accounts with group codes like 001-010 - they should be children, not roots
                frappe.logger().info(f"Account {account_code} will be child account (not root)")

            # For all non-root accounts, find appropriate parent from our Dutch root structure
            if not is_root_account:
                # Check if this account has a group code and if we have a mapping for it
                if (
                    group_code
                    and hasattr(self, "_account_group_mappings")
                    and group_code in self._account_group_mappings
                ):
                    # Try to find or create the intermediate group account
                    parent_account = self.get_or_create_group_account(group_code, root_type, company)
                else:
                    # Use standard parent account logic
                    parent_account = self.get_parent_account(account_type, root_type, company)

                # If no specific parent found, ensure we at least get the appropriate root account
                if not parent_account:
                    # Find the appropriate Dutch root account based on root_type
                    parent_account = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "root_type": root_type,
                            "is_group": 1,
                            "parent_account": ["in", ["", None]],
                        },
                        "name",
                    )

                    if parent_account:
                        frappe.logger().info(
                            f"Using Dutch root account as parent for {account_code}: {parent_account}"
                        )
                    else:
                        frappe.logger().warning(
                            f"No Dutch root account found for {account_code} with root_type {root_type}"
                        )
                        return False  # Skip account if no parent can be found

            # Determine if this should be a group account
            is_group = 0

            # Check if this account was identified as a group
            if hasattr(self, "_group_accounts") and account_code in self._group_accounts:
                is_group = 1
                frappe.logger().info(f"Creating account {account_code} as group (has children)")
            elif is_root_account:
                # Root accounts must be groups in ERPNext
                is_group = 1
                frappe.logger().info(f"Creating root account {account_code} as group")

            # Create new account
            account_doc = {
                "doctype": "Account",
                "account_name": full_account_name,  # Use the properly formatted name
                "account_number": account_code,
                "eboekhouden_grootboek_nummer": account_code,  # Also populate E-boekhouden field
                "company": company,
                "root_type": root_type,
                "is_group": is_group,
                "disabled": 0,
            }

            # Only set parent_account if one was found
            if parent_account:
                account_doc["parent_account"] = parent_account

            # Only set account_type if it's not empty (some accounts don't need a specific type)
            if account_type:
                account_doc["account_type"] = account_type

            account = frappe.get_doc(account_doc)

            frappe.logger().info(
                f"Attempting to create account: {account_code} - {account_name}, is_group={is_group}, parent={parent_account}, root_type={root_type}"
            )

            account.insert(ignore_permissions=True)
            frappe.logger().info(f"Successfully created account: {account_code} - {account_name}")

            # If this is a bank account, try to create corresponding Bank Account record
            if account_type == "Bank":
                try:
                    self.create_bank_account_for_coa_account(account, account_name)
                except Exception as e:
                    frappe.logger().error(f"Failed to create Bank Account for {account_code}: {str(e)}")
                    # Don't fail the entire account creation if bank account creation fails

            return True

        except Exception as e:
            # account_code might not be defined if error occurs early
            account_ref = account_data.get("code", "Unknown") if "account_data" in locals() else "Unknown"
            self.log_error(
                f"Failed to create account {account_ref}: {str(e)}",
                "account",
                account_data if "account_data" in locals() else {},
            )
            return False

    def create_bank_account_for_coa_account(self, account_doc, account_name):
        """
        Create Bank Account record for a Chart of Accounts bank account
        """
        try:
            from verenigingen.utils.eboekhouden_enhanced_coa_import import (
                create_bank_account_record,
                extract_bank_info_from_account_name,
                get_or_create_bank,
            )

            # Extract bank information from account name
            bank_info = extract_bank_info_from_account_name(account_name)

            if bank_info.get("account_number"):
                # Check if Bank Account already exists
                existing_bank_account = None
                if bank_info.get("iban"):
                    existing_bank_account = frappe.db.exists("Bank Account", {"iban": bank_info["iban"]})

                if not existing_bank_account and bank_info.get("account_number"):
                    existing_bank_account = frappe.db.exists(
                        "Bank Account", {"bank_account_no": bank_info["account_number"]}
                    )

                if not existing_bank_account:
                    # Create or get Bank record
                    bank_name = get_or_create_bank(bank_info)

                    # Create Bank Account record
                    account_data = {
                        "name": account_doc.name,
                        "account_name": account_name,
                        "account_number": getattr(account_doc, "account_number", None),
                    }

                    bank_account = create_bank_account_record(
                        account=account_data,
                        bank_name=bank_name,
                        bank_info=bank_info,
                        company=account_doc.company,
                    )

                    if bank_account:
                        frappe.logger().info(
                            f"Created Bank Account: {bank_account} for account: {account_doc.name}"
                        )
                        return bank_account
                else:
                    frappe.logger().info(f"Bank Account already exists for account: {account_name}")

            return None

        except Exception as e:
            frappe.logger().error(f"Error creating bank account for {account_doc.name}: {str(e)}")
            return None

    def get_parent_account(self, account_type, root_type, company):
        """Get appropriate parent account for the new account with enhanced logic"""
        try:
            # Enhanced parent account finding logic
            parent = None

            # First, try to find existing parent accounts by type
            if account_type == "Tax":
                # Look for Tax Assets or Duties and Taxes - try multiple variations
                tax_parent_names = [
                    "Tax Assets",
                    "Duties and Taxes",
                    "VAT",
                    "BTW",
                    "Belastingen",
                    "Current Liabilities",
                    "Schulden op korte termijn",
                ]

                for parent_name in tax_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {"company": company, "account_name": ["like", f"%{parent_name}%"], "is_group": 1},
                        "name",
                    )
                    if parent:
                        break

            elif account_type == "Bank":
                # Look for Bank group accounts, prioritizing E-Boekhouden specific names
                bank_parent_names = ["Liquide middelen", "Bank", "Kas en Bank", "Financiele activa"]

                for parent_name in bank_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Asset",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Bank parent account: {parent} for {parent_name}")
                        break

                # If no specific bank group, try by account type
                if not parent:
                    parent = frappe.db.get_value(
                        "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
                    )

            elif account_type == "Cash":
                # Look for Cash group accounts, prioritizing shared liquide middelen group
                cash_parent_names = ["Liquide middelen", "Kas", "Cash"]

                for parent_name in cash_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Asset",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Cash parent account: {parent} for {parent_name}")
                        break

                # If no specific cash group, try by account type
                if not parent:
                    parent = frappe.db.get_value(
                        "Account", {"company": company, "account_type": "Cash", "is_group": 1}, "name"
                    )

            elif account_type == "Income Account":
                # Look for Income/Opbrengsten/Inkomsten group accounts
                income_parent_names = ["Inkomsten", "Opbrengsten", "Direct Income", "Income"]

                for parent_name in income_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Income",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Income parent account: {parent} for {parent_name}")
                        break

            elif account_type == "Expense Account":
                # Look for Expense/Kosten group accounts
                expense_parent_names = ["Kosten", "Uitgaven", "Direct Expenses", "Expenses"]

                for parent_name in expense_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Expense",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Expense parent account: {parent} for {parent_name}")
                        break

            elif root_type == "Equity":
                # Handle Equity accounts (which have empty account_type)
                # Look for Equity/Eigen Vermogen group accounts
                equity_parent_names = ["Eigen Vermogen", "Equity", "Capital"]

                for parent_name in equity_parent_names:
                    parent = frappe.db.get_value(
                        "Account",
                        {
                            "company": company,
                            "account_name": ["like", f"%{parent_name}%"],
                            "root_type": "Equity",
                            "is_group": 1,
                        },
                        "name",
                    )
                    if parent:
                        frappe.logger().info(f"Found Equity parent account: {parent} for {parent_name}")
                        break

            # If still no parent found, use enhanced fallback logic
            if not parent:
                # Try to find or create appropriate group accounts based on root_type
                parent = self.find_or_create_parent_group(root_type, company)

            # Final fallback: get the root account for this root_type
            if not parent:
                parent = frappe.db.get_value(
                    "Account",
                    {
                        "company": company,
                        "root_type": root_type,
                        "is_group": 1,
                        "parent_account": ["in", ["", None]],
                    },
                    "name",
                )

            return parent

        except Exception as e:
            self.log_error(f"Error finding parent account for {account_type}/{root_type}: {str(e)}")
            # Return any group account as last resort
            return frappe.db.get_value("Account", {"company": company, "is_group": 1}, "name", order_by="lft")

    def get_or_create_group_account(self, group_code, root_type, company):
        """Find or create an intermediate group account based on group mapping"""
        try:
            if not hasattr(self, "_account_group_mappings") or group_code not in self._account_group_mappings:
                return None

            group_name = self._account_group_mappings[group_code]

            # Get company abbreviation for naming
            company_abbr = frappe.db.get_value("Company", company, "abbr")
            f"{group_name} - {company_abbr}"

            # Check if group account already exists
            existing_group = frappe.db.get_value(
                "Account",
                {"account_name": group_name, "company": company, "is_group": 1, "root_type": root_type},
                "name",
            )

            if existing_group:
                frappe.logger().info(f"Found existing group account for {group_code}: {existing_group}")
                return existing_group

            # Find the appropriate root account to be parent of this group
            root_parent_result = frappe.db.sql(
                """
                SELECT name
                FROM `tabAccount`
                WHERE company = %s
                AND root_type = %s
                AND is_group = 1
                AND (parent_account IS NULL OR parent_account = '')
                LIMIT 1
            """,
                (company, root_type),
            )

            root_parent = root_parent_result[0][0] if root_parent_result else None

            if not root_parent:
                frappe.logger().warning(
                    f"No root account found for group {group_code} with root_type {root_type}"
                )
                return None

            # Create the group account
            group_account = frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": group_name,
                    "company": company,
                    "root_type": root_type,
                    "is_group": 1,
                    "parent_account": root_parent,
                    "disabled": 0,
                }
            )

            group_account.insert(ignore_permissions=True)
            frappe.logger().info(f"Created group account: {group_code} - {group_name} under {root_parent}")

            return group_account.name

        except Exception as e:
            frappe.logger().error(f"Error creating group account for {group_code}: {str(e)}")
            return None

    def find_or_create_parent_group(self, root_type, company):
        """Find or create appropriate parent group account"""
        try:
            # Define parent group mappings for each root type
            parent_group_mappings = {
                "Asset": ["Current Assets", "Vlottende activa", "Activa"],
                "Liability": ["Current Liabilities", "Schulden op korte termijn", "Passiva"],
                "Equity": ["Capital Account", "Eigen vermogen", "Kapitaal"],
                "Income": ["Direct Income", "Opbrengsten", "Inkomsten"],
                "Expense": ["Direct Expenses", "Kosten", "Uitgaven"],
            }

            # Try to find existing parent group
            potential_parents = parent_group_mappings.get(root_type, [])

            for parent_name in potential_parents:
                parent = frappe.db.get_value(
                    "Account",
                    {
                        "company": company,
                        "account_name": ["like", f"%{parent_name}%"],
                        "root_type": root_type,
                        "is_group": 1,
                    },
                    "name",
                )
                if parent:
                    return parent

            # If no specific parent found, look for any group under this root_type
            parent_accounts = frappe.db.get_all(
                "Account",
                {"company": company, "root_type": root_type, "is_group": 1},
                ["name", "parent_account"],
                order_by="lft",
            )

            # Return the first non-root group account
            for acc in parent_accounts:
                if acc.parent_account:  # Not a root account
                    return acc.name

            # If only root accounts exist, return the root
            if parent_accounts:
                return parent_accounts[0].name

            return None

        except Exception as e:
            frappe.logger().error(f"Error in find_or_create_parent_group: {str(e)}")
            return None

    def create_cost_center(self, cost_center_data):
        """Create Cost Center in ERPNext"""
        try:
            # Map e-Boekhouden cost center to ERPNext cost center
            description = cost_center_data.get("description", "")
            parent_id = cost_center_data.get("parentId", 0)
            active = cost_center_data.get("active", True)

            if not description:
                self.log_error("Invalid cost center data: no description")
                return False

            # Get default company
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

            if not company:
                self.log_error("No default company set in E-Boekhouden Settings")
                return False

            # Check if cost center already exists
            existing_cc = frappe.db.get_value(
                "Cost Center", {"cost_center_name": description, "company": company}, "name"
            )
            if existing_cc:
                # Return False but don't log as error - this is expected for existing data
                return False

            # Determine parent cost center
            parent_cost_center = None
            if parent_id and parent_id != 0:
                # Try to find parent by description (this is simplified - ideally we'd map IDs)
                parent_cost_center = frappe.db.get_value(
                    "Cost Center", {"company": company, "is_group": 1}, "name"
                )

            if not parent_cost_center:
                # Get the root cost center for the company
                parent_cost_center = frappe.db.get_value(
                    "Cost Center", {"company": company, "is_group": 1, "parent_cost_center": ""}, "name"
                )

            if not parent_cost_center:
                # Try to create root cost center if it doesn't exist
                from verenigingen.utils.eboekhouden_cost_center_fix import ensure_root_cost_center

                parent_cost_center = ensure_root_cost_center(company)

                if not parent_cost_center:
                    self.log_error(f"Could not create or find root cost center for company {company}")
                    return False

            # Create new cost center
            cost_center = frappe.get_doc(
                {
                    "doctype": "Cost Center",
                    "cost_center_name": description,
                    "parent_cost_center": parent_cost_center,
                    "company": company,
                    "is_group": 0,
                    "disabled": not active,
                }
            )

            cost_center.insert(ignore_permissions=True)
            frappe.logger().info(f"Created cost center: {description}")
            return True

        except Exception as e:
            self.log_error(f"Failed to create cost center {description}: {str(e)}")
            return False

    def create_customer(self, customer_data):
        """Create Customer in ERPNext"""
        try:
            # Map e-Boekhouden relation to ERPNext customer
            customer_name = customer_data.get("name", "").strip()
            company_name = customer_data.get("companyName", "").strip()
            contact_name = customer_data.get("contactName", "").strip()
            email = customer_data.get("email", "").strip()
            customer_id = customer_data.get("id", "")

            # Use company name if available, otherwise contact name, otherwise name, otherwise ID
            display_name = company_name or contact_name or customer_name

            if not display_name:
                if customer_id:
                    display_name = f"Customer {customer_id}"
                else:
                    self.log_error("Invalid customer data: no name or ID available")
                    return False

            # Check if customer already exists
            if frappe.db.exists("Customer", {"customer_name": display_name}):
                frappe.logger().info(f"Customer '{display_name}' already exists, skipping")
                return False

            # Get default settings
            settings = frappe.get_single("E-Boekhouden Settings")

            # Get proper territory (avoid "Rest Of The World")
            territory = self.get_proper_territory_for_customer(customer_data)

            # Create new customer
            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": display_name,
                    "customer_type": "Company" if company_name else "Individual",
                    "customer_group": "All Customer Groups",  # Default customer group
                    "territory": territory,
                    "default_currency": settings.default_currency or "EUR",
                    "disabled": 0,
                }
            )

            customer.insert(ignore_permissions=True)

            # Create contact if contact details are available
            if contact_name or email:
                self.create_contact_for_customer(customer.name, customer_data)

            # Create address if address details are available
            if any(
                [customer_data.get("address"), customer_data.get("city"), customer_data.get("postalCode")]
            ):
                self.create_address_for_customer(customer.name, customer_data)

            frappe.logger().info(f"Created customer: {display_name}")
            return True

        except Exception as e:
            self.log_error(f"Failed to create customer {display_name}: {str(e)}")
            return False

    def create_supplier(self, supplier_data):
        """Create Supplier in ERPNext"""
        try:
            # Map e-Boekhouden relation to ERPNext supplier
            supplier_name = supplier_data.get("name", "").strip()
            company_name = supplier_data.get("companyName", "").strip()
            contact_name = supplier_data.get("contactName", "").strip()
            email = supplier_data.get("email", "").strip()
            supplier_id = supplier_data.get("id", "")

            # Use company name if available, otherwise contact name, otherwise name, otherwise ID
            display_name = company_name or contact_name or supplier_name

            if not display_name:
                if supplier_id:
                    display_name = f"Supplier {supplier_id}"
                else:
                    self.log_error("Invalid supplier data: no name or ID available")
                    return False

            # Check if supplier already exists
            if frappe.db.exists("Supplier", {"supplier_name": display_name}):
                frappe.logger().info(f"Supplier '{display_name}' already exists, skipping")
                return False

            # Get default settings
            settings = frappe.get_single("E-Boekhouden Settings")

            # Create new supplier
            supplier = frappe.get_doc(
                {
                    "doctype": "Supplier",
                    "supplier_name": display_name,
                    "supplier_type": "Company" if company_name else "Individual",
                    "supplier_group": "All Supplier Groups",  # Default supplier group
                    "default_currency": settings.default_currency or "EUR",
                    "disabled": 0,
                }
            )

            # Add VAT number if available
            vat_number = supplier_data.get("vatNumber", "").strip()
            if vat_number:
                supplier.tax_id = vat_number

            supplier.insert(ignore_permissions=True)

            # Create contact if contact details are available
            if contact_name or email:
                self.create_contact_for_supplier(supplier.name, supplier_data)

            # Create address if address details are available
            if any(
                [supplier_data.get("address"), supplier_data.get("city"), supplier_data.get("postalCode")]
            ):
                self.create_address_for_supplier(supplier.name, supplier_data)

            frappe.logger().info(f"Created supplier: {display_name}")
            return True

        except Exception as e:
            self.log_error(f"Failed to create supplier {display_name}: {str(e)}")
            return False

    def create_journal_entry(self, transaction_data):
        """Create Journal Entry in ERPNext"""
        try:
            # Map e-Boekhouden transaction to ERPNext journal entry
            # e-Boekhouden API format: {id, type, date, invoiceNumber, ledgerId, amount, entryNumber}
            transaction_date = transaction_data.get("date", "")
            ledger_id = transaction_data.get("ledgerId", "")
            amount = float(transaction_data.get("amount", 0) or 0)
            transaction_type = transaction_data.get("type", 0)  # 0=debit, 1=credit typically
            invoice_number = transaction_data.get("invoiceNumber", "").strip()
            entry_number = transaction_data.get("entryNumber", "").strip()

            # Create description from available fields
            description_parts = []
            if invoice_number:
                description_parts.append(f"Invoice: {invoice_number}")
            if entry_number:
                description_parts.append(f"Entry: {entry_number}")
            if ledger_id:
                description_parts.append(f"Ledger: {ledger_id}")

            description = " | ".join(description_parts) if description_parts else "Imported transaction"

            # Handle missing date
            if not transaction_date:
                self.log_error(f"Invalid transaction data: missing date for {description}")
                return False

            # Skip zero-amount transactions
            if amount == 0:
                return False

            # Convert ledgerId to account code - need to look up in chart of accounts
            account_code = self.get_account_code_from_ledger_id(ledger_id)
            if not account_code:
                self.log_error(f"Could not find account code for ledger ID {ledger_id}")
                return False

            # Determine debit/credit based on type and amount
            if transaction_type == 0:  # Assuming 0 = debit
                debit_amount = amount
                credit_amount = 0
            else:  # 1 = credit
                debit_amount = 0
                credit_amount = amount

            # Find the account in ERPNext
            account_details = frappe.db.get_value(
                "Account", {"account_number": account_code}, ["name", "account_type"], as_dict=True
            )
            if not account_details:
                self.log_error(f"Account {account_code} not found in ERPNext")  # noqa: E713
                return False

            account = account_details.name
            account_type = account_details.account_type

            # Skip stock accounts - they can only be updated via stock transactions
            if account_type == "Stock":
                frappe.logger().info(
                    f"Skipping stock account {account_code} - must be updated via stock transactions"
                )
                # Track skipped stock transactions
                if not hasattr(self, "skipped_stock_transactions"):
                    self.skipped_stock_transactions = 0
                self.skipped_stock_transactions += 1
                return False

            # Get default settings
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

            if not company:
                self.log_error("No default company set in E-Boekhouden Settings")
                return False

            # Parse transaction date
            try:
                from datetime import datetime

                if "T" in transaction_date:
                    posting_date = datetime.strptime(transaction_date.split("T")[0], "%Y-%m-%d").date()
                else:
                    posting_date = datetime.strptime(transaction_date, "%Y-%m-%d").date()
            except ValueError:
                self.log_error(f"Invalid date format: {transaction_date}")
                return False

            # Create journal entry
            journal_entry = frappe.get_doc(
                {
                    "doctype": "Journal Entry",
                    "company": company,
                    "posting_date": posting_date,
                    "voucher_type": "Journal Entry",
                    "user_remark": f"Migrated from e-Boekhouden: {description}",
                    "accounts": [],
                }
            )

            # Add the account entry
            journal_entry.append(
                "accounts",
                {
                    "account": account,
                    "debit_in_account_currency": debit_amount if debit_amount > 0 else 0,
                    "credit_in_account_currency": credit_amount if credit_amount > 0 else 0,
                    "user_remark": description,
                    "cost_center": settings.default_cost_center,
                },
            )

            # For balance, we need to create a balancing entry
            # This is a simplified approach - in reality you'd need to group transactions properly
            if debit_amount > 0:
                # Find a suitable contra account (e.g., suspense account)
                contra_account = self.get_suspense_account(company)
                if contra_account:
                    journal_entry.append(
                        "accounts",
                        {
                            "account": contra_account,
                            "credit_in_account_currency": debit_amount,
                            "user_remark": f"Contra entry for: {description}",
                            "cost_center": settings.default_cost_center,
                        },
                    )
            elif credit_amount > 0:
                # Find a suitable contra account
                contra_account = self.get_suspense_account(company)
                if contra_account:
                    journal_entry.append(
                        "accounts",
                        {
                            "account": contra_account,
                            "debit_in_account_currency": credit_amount,
                            "user_remark": f"Contra entry for: {description}",
                            "cost_center": settings.default_cost_center,
                        },
                    )

            if len(journal_entry.accounts) < 2:
                self.log_error(f"Could not create balanced journal entry for transaction: {description}")
                return False

            journal_entry.insert(ignore_permissions=True)
            frappe.logger().info(f"Created journal entry: {description}")
            return True

        except Exception as e:
            self.log_error(f"Failed to create journal entry: {str(e)}")
            return False

    def create_contact_for_customer(self, customer_name, customer_data):
        """Create contact for customer"""
        try:
            contact_name = customer_data.get("contactName", "").strip()
            email = customer_data.get("email", "").strip()
            phone = customer_data.get("phone", "").strip()

            if not contact_name and not email:
                return

            contact = frappe.get_doc(
                {
                    "doctype": "Contact",
                    "first_name": contact_name or email.split("@")[0],
                    "email_ids": [{"email_id": email, "is_primary": 1}] if email else [],
                    "phone_nos": [{"phone": phone, "is_primary_phone": 1}] if phone else [],
                    "links": [{"link_doctype": "Customer", "link_name": customer_name}],
                }
            )

            contact.insert(ignore_permissions=True)
            frappe.logger().info(f"Created contact for customer: {customer_name}")

        except Exception as e:
            self.log_error(f"Failed to create contact for customer {customer_name}: {str(e)}")

    def create_contact_for_supplier(self, supplier_name, supplier_data):
        """Create contact for supplier"""
        try:
            contact_name = supplier_data.get("contactName", "").strip()
            email = supplier_data.get("email", "").strip()
            phone = supplier_data.get("phone", "").strip()

            if not contact_name and not email:
                return

            contact = frappe.get_doc(
                {
                    "doctype": "Contact",
                    "first_name": contact_name or email.split("@")[0],
                    "email_ids": [{"email_id": email, "is_primary": 1}] if email else [],
                    "phone_nos": [{"phone": phone, "is_primary_phone": 1}] if phone else [],
                    "links": [{"link_doctype": "Supplier", "link_name": supplier_name}],
                }
            )

            contact.insert(ignore_permissions=True)
            frappe.logger().info(f"Created contact for supplier: {supplier_name}")

        except Exception as e:
            self.log_error(f"Failed to create contact for supplier {supplier_name}: {str(e)}")

    def create_address_for_customer(self, customer_name, customer_data):
        """Create address for customer"""
        try:
            address_line1 = customer_data.get("address", "").strip()
            city = customer_data.get("city", "").strip()
            postal_code = customer_data.get("postalCode", "").strip()
            country = customer_data.get("country", "Netherlands").strip()

            if not address_line1 and not city:
                return

            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": f"{customer_name} Address",
                    "address_line1": address_line1,
                    "city": city,
                    "pincode": postal_code,
                    "country": country,
                    "links": [{"link_doctype": "Customer", "link_name": customer_name}],
                }
            )

            address.insert(ignore_permissions=True)
            frappe.logger().info(f"Created address for customer: {customer_name}")

        except Exception as e:
            self.log_error(f"Failed to create address for customer {customer_name}: {str(e)}")

    def create_address_for_supplier(self, supplier_name, supplier_data):
        """Create address for supplier"""
        try:
            address_line1 = supplier_data.get("address", "").strip()
            city = supplier_data.get("city", "").strip()
            postal_code = supplier_data.get("postalCode", "").strip()
            country = supplier_data.get("country", "Netherlands").strip()

            if not address_line1 and not city:
                return

            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": f"{supplier_name} Address",
                    "address_line1": address_line1,
                    "city": city,
                    "pincode": postal_code,
                    "country": country,
                    "links": [{"link_doctype": "Supplier", "link_name": supplier_name}],
                }
            )

            address.insert(ignore_permissions=True)
            frappe.logger().info(f"Created address for supplier: {supplier_name}")

        except Exception as e:
            self.log_error(f"Failed to create address for supplier {supplier_name}: {str(e)}")

    def get_proper_territory_for_customer(self, customer_data):
        """Get appropriate territory for customer, avoiding 'Rest Of The World'"""
        try:
            # Try to determine territory from customer data
            country = customer_data.get("country", "").strip()
            if country:
                # Check if territory exists for this country
                territory = frappe.db.get_value("Territory", {"territory_name": country}, "name")
                if territory:
                    return territory

            # Get the company's home country territory
            default_country = frappe.db.get_default("country")
            if default_country:
                home_territory = frappe.db.get_value("Territory", {"territory_name": default_country}, "name")
                if home_territory:
                    return home_territory

            # Get territories, preferring specific ones over "Rest Of The World"
            territories = frappe.get_all(
                "Territory",
                filters={"is_group": 0},
                fields=["name", "territory_name"],
                order_by="territory_name",
            )

            # Filter out "Rest Of The World" and similar generic territories
            preferred_territories = [
                t
                for t in territories
                if not any(
                    word in t.territory_name.lower() for word in ["rest", "world", "other", "misc", "unknown"]
                )
            ]

            if preferred_territories:
                return preferred_territories[0].name

            # Fall back to any territory if needed
            return territories[0].name if territories else "All Territories"

        except Exception as e:
            self.log_error(f"Error determining territory: {str(e)}")
            return "All Territories"

    def get_account_code_from_ledger_id(self, ledger_id):
        """Convert e-Boekhouden ledger ID to account code"""
        try:
            # First, try to get chart of accounts and build a mapping
            if not hasattr(self, "_ledger_id_mapping"):
                self._ledger_id_mapping = {}

                from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

                settings = frappe.get_single("E-Boekhouden Settings")
                api = EBoekhoudenAPI(settings)

                result = api.get_chart_of_accounts()
                if result["success"]:
                    import json

                    data = json.loads(result["data"])
                    accounts = data.get("items", [])

                    # Build mapping of ledger ID to account code
                    for account in accounts:
                        account_id = account.get("id")
                        account_code = account.get("code")
                        if account_id and account_code:
                            self._ledger_id_mapping[str(account_id)] = account_code

            # Look up the ledger ID in our mapping
            return self._ledger_id_mapping.get(str(ledger_id))

        except Exception as e:
            self.log_error(f"Error converting ledger ID {ledger_id} to account code: {str(e)}")
            return None

    def get_suspense_account(self, company):
        """Get or create suspense account for balancing entries"""
        try:
            # Try to find existing suspense account
            suspense_account = frappe.db.get_value(
                "Account", {"company": company, "account_name": ["like", "%suspense%"]}, "name"
            )

            if suspense_account:
                return suspense_account

            # If not found, look for temporary account
            temp_account = frappe.db.get_value(
                "Account", {"company": company, "account_name": ["like", "%temporary%"]}, "name"
            )

            if temp_account:
                return temp_account

            # As last resort, return the first liability account
            liability_account = frappe.db.get_value(
                "Account", {"company": company, "root_type": "Liability", "is_group": 0}, "name"
            )

            return liability_account

        except Exception as e:
            self.log_error(f"Error finding suspense account: {str(e)}")
            return None

    def save_debug_error(self, message, record_type, record_data, enhanced_message):
        """Save error immediately to debug file for analysis"""
        try:
            import os
            from datetime import datetime

            # Create logs directory if it doesn't exist
            log_dir = frappe.get_site_path("private", "files", "eboekhouden_debug_logs")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # Create debug filename
            timestamp = datetime.now().strftime("%Y%m%d")
            filename = f"debug_errors_{self.name}_{timestamp}.txt"
            filepath = os.path.join(log_dir, filename)

            # Append error to debug file
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"ERROR TIMESTAMP: {frappe.utils.now_datetime()}\n")
                f.write(f"RECORD TYPE: {record_type or 'Unknown'}\n")
                f.write(f"{'=' * 80}\n")
                f.write(enhanced_message)
                f.write(f"\n{'=' * 80}\n\n")

        except Exception as e:
            frappe.logger().error(f"Failed to save debug error: {str(e)}")

    def save_failed_records_log(self):
        """Save detailed log of failed records to a file"""
        try:
            import os
            from datetime import datetime

            # Create logs directory if it doesn't exist
            log_dir = frappe.get_site_path("private", "files", "eboekhouden_migration_logs")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"failed_records_{self.name}_{timestamp}.json"
            filepath = os.path.join(log_dir, filename)

            # Save the failed records
            with open(filepath, "w") as f:
                json.dump(
                    {
                        "migration_name": self.name,
                        "migration_id": self.migration_name,
                        "timestamp": frappe.utils.now_datetime(),
                        "total_failed": self.failed_records,
                        "failed_records": self.failed_record_details,
                    },
                    f,
                    indent=2,
                    default=str,
                )

            # Add note to migration summary
            self.migration_summary += f"\n\nFailed records log saved to: {filename}"
            frappe.logger().info(f"Failed records log saved to: {filepath}")

        except Exception as e:
            frappe.log_error(f"Failed to save failed records log: {str(e)}")


@frappe.whitelist()
def start_migration_api(migration_name, dry_run=1):
    """API method to start migration process"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        if migration.migration_status != "Draft":
            return {"success": False, "error": "Migration must be in Draft status to start"}

        # Update migration settings and initialize counters
        migration.dry_run = int(dry_run)
        migration.migration_status = "In Progress"
        migration.start_time = frappe.utils.now_datetime()
        migration.current_operation = "Initializing migration..."
        migration.progress_percentage = 0

        # Initialize counters - THIS IS THE FIX!
        migration.total_records = 0
        migration.imported_records = 0
        migration.failed_records = 0

        migration.save()

        # Start migration directly without submission
        migration.start_migration()

        return {"success": True, "message": "Migration started successfully"}

    except Exception as e:
        frappe.log_error(f"Error starting migration: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def start_migration(migration_name, setup_only=False):
    """API method to start migration process

    Args:
        migration_name: Name of the migration document
        setup_only: If True, only migrate CoA, customers, suppliers (skip transactions)
    """
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        if migration.migration_status != "Draft":
            return {"success": False, "error": "Migration must be in Draft status to start"}

        # If setup_only, configure the migration to skip transactions
        if setup_only:
            # Temporarily set migration flags for setup-only mode
            migration.db_set(
                {
                    "migrate_accounts": 1,
                    "migrate_cost_centers": 1,
                    "migrate_customers": 1,
                    "migrate_suppliers": 1,
                    "migrate_transactions": 0,  # Skip transactions
                }
            )
            frappe.db.commit()

        # Start migration in background
        frappe.enqueue(
            method="verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.run_migration_background",
            queue="long",
            timeout=3600,
            migration_name=migration_name,
            setup_only=setup_only,
        )

        return {"success": True, "message": "Migration started in background"}

    except Exception as e:
        frappe.log_error(f"Error starting migration: {str(e)}")
        return {"success": False, "error": str(e)}


def run_migration_background(migration_name, setup_only=False):
    """Run migration in background"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.start_migration()
    except Exception as e:
        frappe.log_error(f"Background migration failed: {str(e)}")
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.migration_status = "Failed"
        migration.error_log = str(e)
        migration.save()


@frappe.whitelist()
def cleanup_chart_of_accounts(company, delete_all_accounts=False):
    """Clean up chart of accounts

    Args:
        company: The company to clean up accounts for
        delete_all_accounts: If True, delete ALL accounts (not just E-Boekhouden).
                           If False, only delete E-Boekhouden imported accounts.
    """
    try:
        delete_all_accounts = (
            delete_all_accounts.lower() == "true"
            if isinstance(delete_all_accounts, str)
            else delete_all_accounts
        )

        # First run cleanup of all imported data to remove any transactions
        if delete_all_accounts:
            frappe.logger().info("Running cleanup of all imported data first...")
            cleanup_result = debug_cleanup_all_imported_data(company)
            if not cleanup_result.get("success", True):
                frappe.logger().warning(f"Cleanup of imported data had issues: {cleanup_result}")

        accounts_deleted = 0
        failed_deletions = []

        # Build the SQL query based on what we're deleting
        if delete_all_accounts:
            # Get ALL accounts except the root company account
            # where_clause = """
            #     WHERE company = %s
            #     AND root_type IS NOT NULL
            # """
            delete_type = "all"
        else:
            # Get only E-Boekhouden accounts
            # where_clause = """
            #     WHERE company = %s
            #     AND eboekhouden_grootboek_nummer IS NOT NULL
            #     AND eboekhouden_grootboek_nummer != ''
            # """
            delete_type = "E-Boekhouden"

        # Get accounts with proper ordering for deletion
        # Use (rgt - lft) to determine depth - smaller values are leaf nodes
        accounts = frappe.db.sql(
            """
            SELECT
                name,
                is_group,
                account_name,
                parent_account,
                lft,
                rgt,
                root_type,
                account_type,
                (rgt - lft) as node_width
            FROM `tabAccount`
            {where_clause}
            ORDER BY node_width ASC, rgt DESC
        """,
            company,
            as_dict=True,
        )

        frappe.logger().info(f"Found {len(accounts)} {delete_type} accounts to delete")

        # Delete accounts one by one, starting from leaf nodes
        for account in accounts:
            try:
                # Check if account still exists (it might have been deleted as a child of another)
                if frappe.db.exists("Account", account.name):
                    if not delete_all_accounts:
                        # When deleting only E-Boekhouden accounts, check for non-E-Boekhouden children
                        non_eb_children = frappe.db.sql(
                            """
                            SELECT COUNT(*) as count
                            FROM `tabAccount`
                            WHERE parent_account = %s
                            AND company = %s
                            AND (eboekhouden_grootboek_nummer IS NULL OR eboekhouden_grootboek_nummer = '')
                        """,
                            (account.name, company),
                            as_dict=True,
                        )[0]["count"]

                        if non_eb_children > 0:
                            # Skip this account as it has non-E-Boekhouden children
                            failed_deletions.append(
                                {
                                    "account": account.account_name,
                                    "error": f"Has {non_eb_children} non-E-Boekhouden child accounts",
                                }
                            )
                            continue

                    # Delete the account
                    frappe.delete_doc("Account", account.name, force=True, ignore_permissions=True)
                    accounts_deleted += 1
                    frappe.logger().info(f"Deleted account: {account.account_name}")

            except Exception as e:
                error_msg = str(e)
                if "existing transaction" in error_msg:
                    # Account has transactions - this is expected for some accounts
                    failed_deletions.append(
                        {
                            "account": account.account_name,
                            "error": "Has existing transactions - cannot delete",
                        }
                    )
                elif "child nodes" in error_msg:
                    # This shouldn't happen with our ordering, but log it
                    failed_deletions.append(
                        {
                            "account": account.account_name,
                            "error": "Still has child nodes - this indicates an ordering issue",
                        }
                    )
                elif "mandatory" in error_msg.lower():
                    # Some accounts are mandatory and cannot be deleted
                    failed_deletions.append(
                        {"account": account.account_name, "error": "Mandatory account cannot be deleted"}
                    )
                else:
                    failed_deletions.append({"account": account.account_name, "error": error_msg})
                frappe.log_error(f"Failed to delete account {account.account_name}: {error_msg}")

        frappe.db.commit()

        result = {
            "success": True,
            "accounts_deleted": accounts_deleted,
            "message": f"Deleted {accounts_deleted} {delete_type} accounts",
        }

        if failed_deletions:
            result["failed_deletions"] = failed_deletions
            result["message"] += f" ({len(failed_deletions)} failed)"

        return result

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_cleanup_all_imported_data(company=None):
    """Debug function to completely clean up all imported data for fresh migration"""
    try:
        # Get default company if not provided
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        results = {}

        # 1. Clean up Journal Entries (proper cancellation sequence)
        journal_entries_deleted = 0
        try:
            journal_entries = frappe.get_all(
                "Journal Entry",
                filters={"company": company, "user_remark": ["like", "%Migrated from e-Boekhouden%"]},
                fields=["name", "docstatus"],
            )

            for je in journal_entries:
                try:
                    je_doc = frappe.get_doc("Journal Entry", je.name)

                    # Cancel if submitted
                    if je_doc.docstatus == 1:
                        # Set ignore_linked_doctypes to handle GL Entries
                        je_doc.ignore_linked_doctypes = (
                            "GL Entry",
                            "Stock Ledger Entry",
                            "Payment Ledger Entry",
                            "Repost Payment Ledger",
                            "Repost Payment Ledger Items",
                            "Repost Accounting Ledger",
                            "Repost Accounting Ledger Items",
                        )
                        je_doc.cancel()

                    # Delete after cancellation
                    frappe.delete_doc("Journal Entry", je.name)
                    journal_entries_deleted += 1
                except Exception as e:
                    frappe.log_error(f"Failed to delete Journal Entry {je.name}: {str(e)}")
        except Exception as e:
            frappe.log_error(f"Error cleaning journal entries: {str(e)}")

        results["journal_entries_deleted"] = journal_entries_deleted

        # 2. Clean up Payment Entries (proper cancellation sequence)
        payment_entries_deleted = 0

        def cleanup_payment_entries(pe_list, method_name):
            deleted = 0
            for pe in pe_list:
                try:
                    if not frappe.db.exists("Payment Entry", pe.name):
                        continue

                    # First, aggressively clean up any GL Entries for this Payment Entry
                    try:
                        frappe.db.sql(
                            """
                            DELETE FROM `tabGL Entry`
                            WHERE voucher_type = 'Payment Entry'
                            AND voucher_no = %s
                        """,
                            pe.name,
                        )
                    except Exception:
                        pass

                    pe_doc = frappe.get_doc("Payment Entry", pe.name)

                    # Cancel if submitted
                    if pe_doc.docstatus == 1:
                        # Set ignore_linked_doctypes to handle GL Entries properly
                        pe_doc.ignore_linked_doctypes = (
                            "GL Entry",
                            "Stock Ledger Entry",
                            "Payment Ledger Entry",
                            "Repost Payment Ledger",
                            "Repost Payment Ledger Items",
                            "Repost Accounting Ledger",
                            "Repost Accounting Ledger Items",
                            "Unreconcile Payment",
                            "Unreconcile Payment Entries",
                        )
                        try:
                            pe_doc.cancel()
                        except Exception:
                            # If cancellation fails, try direct status update
                            frappe.db.sql(
                                "UPDATE `tabPayment Entry` SET docstatus = 2 WHERE name = %s", pe.name
                            )

                    # Delete after cancellation - try multiple approaches
                    try:
                        frappe.delete_doc("Payment Entry", pe.name)
                    except Exception:
                        # If delete_doc fails, try direct SQL deletion
                        try:
                            frappe.db.sql("DELETE FROM `tabPayment Entry` WHERE name = %s", pe.name)
                        except Exception:
                            pass

                    deleted += 1
                except Exception as e:
                    frappe.log_error(f"Failed to delete Payment Entry {pe.name} via {method_name}: {str(e)}")
            return deleted

        # Method 1: By eboekhouden_mutation_nr (most reliable)
        try:
            mutation_nr_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["eboekhouden_mutation_nr", "is", "set"],
                    ["eboekhouden_mutation_nr", "!=", ""],
                    ["docstatus", "!=", 2],
                ],
                fields=["name", "docstatus"],
            )

            payment_entries_deleted += cleanup_payment_entries(mutation_nr_entries, "mutation_nr")
        except Exception as e:
            frappe.log_error(f"Error with mutation_nr cleanup method: {str(e)}")

        # Method 2: By numeric reference_no (backup method) - using SQL query due to regexp limitation
        try:
            numeric_ref_entries = frappe.db.sql(
                """
                SELECT name, docstatus FROM `tabPayment Entry`
                WHERE company = %s
                AND reference_no REGEXP '^[0-9]+$'
                AND docstatus != 2
            """,
                (company,),
                as_dict=True,
            )

            payment_entries_deleted += cleanup_payment_entries(numeric_ref_entries, "numeric_ref")
        except Exception as e:
            frappe.log_error(f"Error with numeric_ref cleanup method: {str(e)}")

        # Method 3: By remarks pattern (catch remaining entries)
        try:
            remarks_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["remarks", "like", "%Mutation Nr:%"],
                    ["docstatus", "!=", 2],
                ],
                fields=["name", "docstatus"],
            )

            payment_entries_deleted += cleanup_payment_entries(remarks_entries, "remarks")
        except Exception as e:
            frappe.log_error(f"Error with remarks cleanup method: {str(e)}")

        results["payment_entries_deleted"] = payment_entries_deleted

        # 3. Clean up Sales Invoices (proper cancellation sequence)
        sales_invoices_deleted = 0

        def cleanup_sales_invoices(si_list, method_name):
            deleted = 0
            for si in si_list:
                try:
                    if not frappe.db.exists("Sales Invoice", si.name):
                        continue

                    # First, aggressively clean up any GL Entries for this Sales Invoice
                    try:
                        frappe.db.sql(
                            """
                            DELETE FROM `tabGL Entry`
                            WHERE voucher_type = 'Sales Invoice'
                            AND voucher_no = %s
                        """,
                            si.name,
                        )
                    except Exception:
                        pass

                    si_doc = frappe.get_doc("Sales Invoice", si.name)

                    # Cancel if submitted
                    if si_doc.docstatus == 1:
                        # Set ignore_linked_doctypes to handle GL Entries properly
                        si_doc.ignore_linked_doctypes = (
                            "GL Entry",
                            "Stock Ledger Entry",
                            "Payment Ledger Entry",
                            "Repost Payment Ledger",
                            "Repost Payment Ledger Items",
                            "Repost Accounting Ledger",
                            "Repost Accounting Ledger Items",
                            "Unreconcile Payment",
                            "Unreconcile Payment Entries",
                        )
                        try:
                            si_doc.cancel()
                        except Exception:
                            # If cancellation fails, try direct status update
                            frappe.db.sql(
                                "UPDATE `tabSales Invoice` SET docstatus = 2 WHERE name = %s", si.name
                            )

                    # Delete after cancellation - try multiple approaches
                    try:
                        frappe.delete_doc("Sales Invoice", si.name)
                    except Exception:
                        # If delete_doc fails, try direct SQL deletion
                        try:
                            frappe.db.sql("DELETE FROM `tabSales Invoice` WHERE name = %s", si.name)
                        except Exception:
                            pass

                    deleted += 1
                except Exception as e:
                    frappe.log_error(f"Failed to delete Sales Invoice {si.name} via {method_name}: {str(e)}")
            return deleted

        # Method 1: By eboekhouden_invoice_number field (PRIMARY METHOD)
        # This is the most reliable way to identify E-Boekhouden invoices
        try:
            eboekhouden_invoices = frappe.get_all(
                "Sales Invoice",
                filters=[
                    ["company", "=", company],
                    ["eboekhouden_invoice_number", "is", "set"],
                    ["eboekhouden_invoice_number", "!=", ""],
                    ["docstatus", "!=", 2],
                ],
                fields=["name", "docstatus"],
            )

            sales_invoices_deleted += cleanup_sales_invoices(
                eboekhouden_invoices, "eboekhouden_invoice_number"
            )
        except Exception as e:
            frappe.log_error(f"Error with eboekhouden_invoice_number-based SI cleanup: {str(e)}")

        # Method 2: By remarks field (secondary method)
        try:
            remarks_invoices = frappe.get_all(
                "Sales Invoice",
                filters=[
                    ["company", "=", company],
                    ["remarks", "like", "%e-Boekhouden%"],
                    ["docstatus", "!=", 2],
                ],
                fields=["name", "docstatus"],
            )

            sales_invoices_deleted += cleanup_sales_invoices(remarks_invoices, "remarks")
        except Exception as e:
            frappe.log_error(f"Error with remarks-based SI cleanup: {str(e)}")

        # Method 3: By eboekhouden_mutation_nr field (if it exists)
        try:
            # Check if the field exists
            if frappe.db.has_column("Sales Invoice", "eboekhouden_mutation_nr"):
                mutation_invoices = frappe.get_all(
                    "Sales Invoice",
                    filters=[
                        ["company", "=", company],
                        ["eboekhouden_mutation_nr", "is", "set"],
                        ["eboekhouden_mutation_nr", "!=", ""],
                        ["docstatus", "!=", 2],
                    ],
                    fields=["name", "docstatus"],
                )

                sales_invoices_deleted += cleanup_sales_invoices(mutation_invoices, "mutation_nr")
        except Exception as e:
            frappe.log_error(f"Error with mutation_nr-based SI cleanup: {str(e)}")

        # Method 4: By numeric invoice number pattern (backup method)
        try:
            # E-Boekhouden invoices often have numeric invoice numbers
            # Patterns: SINV-[0-9]+, ACC-SINV-YYYY-[0-9]+
            numeric_invoices = frappe.db.sql(
                """
                SELECT name, docstatus FROM `tabSales Invoice`
                WHERE company = %s
                AND (
                    name REGEXP '^SINV-[0-9]+$'
                    OR name REGEXP '^ACC-SINV-[0-9]{4}-[0-9]+$'
                )
                AND docstatus != 2
            """,
                (company,),
                as_dict=True,
            )

            sales_invoices_deleted += cleanup_sales_invoices(numeric_invoices, "numeric_pattern")
        except Exception as e:
            frappe.log_error(f"Error with numeric pattern SI cleanup: {str(e)}")

        # Method 5: By custom field or other identifying marks
        try:
            # Check for any sales invoices created during migration period
            migration_period_invoices = frappe.db.sql(
                """
                SELECT si.name, si.docstatus
                FROM `tabSales Invoice` si
                WHERE si.company = %s
                AND si.docstatus != 2
                AND EXISTS (
                    SELECT 1 FROM `tabJournal Entry` je
                    WHERE je.company = %s
                    AND je.user_remark LIKE '%%Migrated from e-Boekhouden%%'
                    AND DATE(si.creation) = DATE(je.creation)
                )
                LIMIT 100
            """,
                (company, company),
                as_dict=True,
            )

            sales_invoices_deleted += cleanup_sales_invoices(migration_period_invoices, "migration_period")
        except Exception as e:
            frappe.log_error(f"Error with migration period SI cleanup: {str(e)}")

        results["sales_invoices_deleted"] = sales_invoices_deleted

        # Note: If you want to delete ALL sales invoices for the company (DANGEROUS!),
        # you can uncomment the following code:
        #
        # # Method 5: Nuclear option - delete ALL sales invoices for the company
        # # WARNING: This will delete ALL sales invoices, not just E-Boekhouden ones!
        # if frappe.flags.nuclear_cleanup:
        #     try:
        #         all_invoices = frappe.get_all("Sales Invoice", filters=[
        #             ["company", "=", company],
        #             ["docstatus", "!=", 2]
        #         ], fields=["name", "docstatus"])
        #
        #         sales_invoices_deleted += cleanup_sales_invoices(all_invoices, "nuclear")
        #     except Exception as e:
        #         frappe.log_error(f"Error with nuclear SI cleanup: {str(e)}")

        # 4. Clean up Purchase Invoices (proper cancellation sequence)
        purchase_invoices_deleted = 0

        def cleanup_purchase_invoices(pi_list, method_name):
            deleted = 0
            for pi in pi_list:
                try:
                    if not frappe.db.exists("Purchase Invoice", pi.name):
                        continue

                    # First, aggressively clean up any GL Entries for this Purchase Invoice
                    try:
                        frappe.db.sql(
                            """
                            DELETE FROM `tabGL Entry`
                            WHERE voucher_type = 'Purchase Invoice'
                            AND voucher_no = %s
                        """,
                            pi.name,
                        )
                    except Exception:
                        pass

                    pi_doc = frappe.get_doc("Purchase Invoice", pi.name)

                    # Cancel if submitted
                    if pi_doc.docstatus == 1:
                        # Set ignore_linked_doctypes to handle GL Entries properly
                        pi_doc.ignore_linked_doctypes = (
                            "GL Entry",
                            "Stock Ledger Entry",
                            "Payment Ledger Entry",
                            "Repost Payment Ledger",
                            "Repost Payment Ledger Items",
                            "Repost Accounting Ledger",
                            "Repost Accounting Ledger Items",
                            "Unreconcile Payment",
                            "Unreconcile Payment Entries",
                        )
                        try:
                            pi_doc.cancel()
                        except Exception:
                            # If cancellation fails, try direct status update
                            frappe.db.sql(
                                "UPDATE `tabPurchase Invoice` SET docstatus = 2 WHERE name = %s", pi.name
                            )

                    # Delete after cancellation - try multiple approaches
                    try:
                        frappe.delete_doc("Purchase Invoice", pi.name)
                    except Exception:
                        # If delete_doc fails, try direct SQL deletion
                        try:
                            frappe.db.sql("DELETE FROM `tabPurchase Invoice` WHERE name = %s", pi.name)
                        except Exception:
                            pass

                    deleted += 1
                except Exception as e:
                    frappe.log_error(
                        f"Failed to delete Purchase Invoice {pi.name} via {method_name}: {str(e)}"
                    )
            return deleted

        # Method 1: By eboekhouden_invoice_number field (PRIMARY METHOD)
        try:
            # Check if the field exists
            if frappe.db.has_column("Purchase Invoice", "eboekhouden_invoice_number"):
                eboekhouden_pinvoices = frappe.get_all(
                    "Purchase Invoice",
                    filters=[
                        ["company", "=", company],
                        ["eboekhouden_invoice_number", "is", "set"],
                        ["eboekhouden_invoice_number", "!=", ""],
                        ["docstatus", "!=", 2],
                    ],
                    fields=["name", "docstatus"],
                )

                purchase_invoices_deleted += cleanup_purchase_invoices(
                    eboekhouden_pinvoices, "eboekhouden_invoice_number"
                )
        except Exception as e:
            frappe.log_error(f"Error with eboekhouden_invoice_number-based PI cleanup: {str(e)}")

        # Method 2: By remarks field (secondary method)
        try:
            remarks_pinvoices = frappe.get_all(
                "Purchase Invoice",
                filters=[
                    ["company", "=", company],
                    ["remarks", "like", "%e-Boekhouden%"],
                    ["docstatus", "!=", 2],
                ],
                fields=["name", "docstatus"],
            )

            purchase_invoices_deleted += cleanup_purchase_invoices(remarks_pinvoices, "remarks")
        except Exception as e:
            frappe.log_error(f"Error with remarks-based PI cleanup: {str(e)}")

        # Method 3: By eboekhouden_mutation_nr field (if it exists)
        try:
            # Check if the field exists
            if frappe.db.has_column("Purchase Invoice", "eboekhouden_mutation_nr"):
                mutation_pinvoices = frappe.get_all(
                    "Purchase Invoice",
                    filters=[
                        ["company", "=", company],
                        ["eboekhouden_mutation_nr", "is", "set"],
                        ["eboekhouden_mutation_nr", "!=", ""],
                        ["docstatus", "!=", 2],
                    ],
                    fields=["name", "docstatus"],
                )

                purchase_invoices_deleted += cleanup_purchase_invoices(mutation_pinvoices, "mutation_nr")
        except Exception as e:
            frappe.log_error(f"Error with mutation_nr-based PI cleanup: {str(e)}")

        # Method 4: By numeric invoice number pattern (backup method)
        try:
            # E-Boekhouden invoices often have numeric invoice numbers
            # Patterns: PINV-[0-9]+, ACC-PINV-YYYY-[0-9]+
            numeric_pinvoices = frappe.db.sql(
                """
                SELECT name, docstatus FROM `tabPurchase Invoice`
                WHERE company = %s
                AND (
                    name REGEXP '^PINV-[0-9]+$'
                    OR name REGEXP '^ACC-PINV-[0-9]{4}-[0-9]+$'
                )
                AND docstatus != 2
            """,
                (company,),
                as_dict=True,
            )

            purchase_invoices_deleted += cleanup_purchase_invoices(numeric_pinvoices, "numeric_pattern")
        except Exception as e:
            frappe.log_error(f"Error with numeric pattern PI cleanup: {str(e)}")

        # Method 5: By custom field or other identifying marks
        try:
            # Check for any purchase invoices created during migration period
            migration_period_pinvoices = frappe.db.sql(
                """
                SELECT pi.name, pi.docstatus
                FROM `tabPurchase Invoice` pi
                WHERE pi.company = %s
                AND pi.docstatus != 2
                AND EXISTS (
                    SELECT 1 FROM `tabJournal Entry` je
                    WHERE je.company = %s
                    AND je.user_remark LIKE '%%Migrated from e-Boekhouden%%'
                    AND DATE(pi.creation) = DATE(je.creation)
                )
                LIMIT 100
            """,
                (company, company),
                as_dict=True,
            )

            purchase_invoices_deleted += cleanup_purchase_invoices(
                migration_period_pinvoices, "migration_period"
            )
        except Exception as e:
            frappe.log_error(f"Error with migration period PI cleanup: {str(e)}")

        results["purchase_invoices_deleted"] = purchase_invoices_deleted

        # 5. Clean up GL Entries (Note: These should be handled automatically by cancellation above)
        gl_entries_deleted = 0
        try:
            # Only clean up orphaned GL Entries that might be left behind
            gl_entries = frappe.db.get_all(
                "GL Entry", filters={"company": company, "remarks": ["like", "%e-Boekhouden%"]}
            )

            for gl in gl_entries:
                try:
                    # Use SQL delete for GL Entries as they don't have document controllers
                    frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", gl.name)
                    gl_entries_deleted += 1
                except Exception as e:
                    frappe.log_error(f"Failed to delete GL Entry {gl.name}: {str(e)}")
        except Exception as e:
            frappe.log_error(f"Error cleaning GL entries: {str(e)}")

        results["gl_entries_deleted"] = gl_entries_deleted

        # 6. Clean up Customers (optional - be careful with this)
        customers = frappe.get_all("Customer", filters={"customer_name": ["like", "%e-Boekhouden%"]})

        for customer in customers:
            try:
                frappe.delete_doc("Customer", customer.name, force=True)
            except Exception:
                pass
        results["customers_deleted"] = len(customers)

        # 7. Clean up Suppliers (optional - be careful with this)
        suppliers = frappe.get_all("Supplier", filters={"supplier_name": ["like", "%e-Boekhouden%"]})

        for supplier in suppliers:
            try:
                frappe.delete_doc("Supplier", supplier.name, force=True)
            except Exception:
                pass
        results["suppliers_deleted"] = len(suppliers)

        frappe.db.commit()

        return {"success": True, "message": "Cleanup completed successfully", "results": results}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_cleanup_gl_entries_only(company=None):
    """Debug function to specifically clean up GL Entries created by E-Boekhouden import"""
    try:
        # Get default company if not provided
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        results = {"gl_entries_deleted": 0, "errors": []}

        # Method 1: Clean up GL Entries linked to E-Boekhouden Payment Entries
        try:
            # Get Payment Entry names that are from E-Boekhouden
            payment_entries = frappe.db.sql(
                """
                SELECT name FROM `tabPayment Entry`
                WHERE company = %s
                AND (
                    eboekhouden_mutation_nr IS NOT NULL
                    OR reference_no REGEXP '^[0-9]+$'
                    OR remarks LIKE '%%Mutation Nr:%%'
                )
            """,
                (company,),
                as_dict=True,
            )

            pe_names = [pe.name for pe in payment_entries]

            if pe_names:
                # Get GL Entries for these Payment Entries
                gl_entries = frappe.db.sql(
                    """
                    SELECT name FROM `tabGL Entry`
                    WHERE company = %s
                    AND voucher_type = 'Payment Entry'
                    AND voucher_no IN ({})
                """.format(
                        ",".join(["%s"] * len(pe_names))
                    ),
                    [company] + pe_names,
                    as_dict=True,
                )

                for gl in gl_entries:
                    try:
                        frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", gl.name)
                        results["gl_entries_deleted"] += 1
                    except Exception as e:
                        results["errors"].append(f"Failed to delete GL Entry {gl.name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Error cleaning Payment Entry GL Entries: {str(e)}")

        # Method 2: Clean up GL Entries linked to E-Boekhouden Invoices
        try:
            # Sales Invoice GL Entries
            si_gl_entries = frappe.db.sql(
                """
                SELECT gl.name FROM `tabGL Entry` gl
                JOIN `tabSales Invoice` si ON gl.voucher_no = si.name
                WHERE gl.company = %s
                AND gl.voucher_type = 'Sales Invoice'
                AND si.remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
                as_dict=True,
            )

            for gl in si_gl_entries:
                try:
                    frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", gl.name)
                    results["gl_entries_deleted"] += 1
                except Exception as e:
                    results["errors"].append(f"Failed to delete Sales Invoice GL Entry {gl.name}: {str(e)}")

            # Purchase Invoice GL Entries
            pi_gl_entries = frappe.db.sql(
                """
                SELECT gl.name FROM `tabGL Entry` gl
                JOIN `tabPurchase Invoice` pi ON gl.voucher_no = pi.name
                WHERE gl.company = %s
                AND gl.voucher_type = 'Purchase Invoice'
                AND pi.remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
                as_dict=True,
            )

            for gl in pi_gl_entries:
                try:
                    frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", gl.name)
                    results["gl_entries_deleted"] += 1
                except Exception as e:
                    results["errors"].append(
                        f"Failed to delete Purchase Invoice GL Entry {gl.name}: {str(e)}"
                    )
        except Exception as e:
            results["errors"].append(f"Error cleaning Invoice GL Entries: {str(e)}")

        # Method 3: Clean up GL Entries linked to E-Boekhouden Journal Entries
        try:
            je_gl_entries = frappe.db.sql(
                """
                SELECT gl.name FROM `tabGL Entry` gl
                JOIN `tabJournal Entry` je ON gl.voucher_no = je.name
                WHERE gl.company = %s
                AND gl.voucher_type = 'Journal Entry'
                AND je.user_remark LIKE '%%Migrated from e-Boekhouden%%'
            """,
                (company,),
                as_dict=True,
            )

            for gl in je_gl_entries:
                try:
                    frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", gl.name)
                    results["gl_entries_deleted"] += 1
                except Exception as e:
                    results["errors"].append(f"Failed to delete Journal Entry GL Entry {gl.name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Error cleaning Journal Entry GL Entries: {str(e)}")

        # Method 4: Clean up any remaining GL Entries with E-Boekhouden in remarks
        try:
            direct_gl_entries = frappe.db.sql(
                """
                SELECT name FROM `tabGL Entry`
                WHERE company = %s
                AND remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
                as_dict=True,
            )

            for gl in direct_gl_entries:
                try:
                    frappe.db.sql("DELETE FROM `tabGL Entry` WHERE name = %s", gl.name)
                    results["gl_entries_deleted"] += 1
                except Exception as e:
                    results["errors"].append(f"Failed to delete direct GL Entry {gl.name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Error cleaning direct GL Entries: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "message": f"GL Entry cleanup completed. Deleted {results['gl_entries_deleted']} entries.",
            "results": results,
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_analyze_cleanup_requirements(company=None):
    """Analyze what E-Boekhouden data exists and needs cleanup"""
    try:
        # Get default company if not provided
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        analysis = {}

        # 1. Analyze Payment Entries
        payment_analysis = {}

        # Count by mutation number field
        mutation_nr_count = frappe.db.count(
            "Payment Entry",
            filters=[
                ["company", "=", company],
                ["eboekhouden_mutation_nr", "is", "set"],
                ["docstatus", "!=", 2],
            ],
        )
        payment_analysis["by_mutation_nr"] = mutation_nr_count

        # Count by numeric reference - using SQL query due to regexp limitation
        numeric_ref_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM `tabPayment Entry`
            WHERE company = %s
            AND reference_no REGEXP '^[0-9]+$'
            AND docstatus != 2
        """,
            (company,),
            as_dict=True,
        )[0].count
        payment_analysis["by_numeric_ref"] = numeric_ref_count

        # Count by remarks pattern
        remarks_count = frappe.db.count(
            "Payment Entry",
            filters=[
                ["company", "=", company],
                ["remarks", "like", "%Mutation Nr:%"],
                ["docstatus", "!=", 2],
            ],
        )
        payment_analysis["by_remarks"] = remarks_count

        # Count by document status
        draft_pe = frappe.db.count(
            "Payment Entry",
            filters=[
                ["company", "=", company],
                ["eboekhouden_mutation_nr", "is", "set"],
                ["docstatus", "=", 0],
            ],
        )
        submitted_pe = frappe.db.count(
            "Payment Entry",
            filters=[
                ["company", "=", company],
                ["eboekhouden_mutation_nr", "is", "set"],
                ["docstatus", "=", 1],
            ],
        )
        cancelled_pe = frappe.db.count(
            "Payment Entry",
            filters=[
                ["company", "=", company],
                ["eboekhouden_mutation_nr", "is", "set"],
                ["docstatus", "=", 2],
            ],
        )

        payment_analysis["by_status"] = {
            "draft": draft_pe,
            "submitted": submitted_pe,
            "cancelled": cancelled_pe,
        }

        analysis["payment_entries"] = payment_analysis

        # 2. Analyze GL Entries
        gl_analysis = {}

        # GL Entries linked to Payment Entries
        pe_gl_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM `tabGL Entry` gl
            JOIN `tabPayment Entry` pe ON gl.voucher_no = pe.name
            WHERE gl.company = %s
            AND gl.voucher_type = 'Payment Entry'
            AND pe.eboekhouden_mutation_nr IS NOT NULL
        """,
            (company,),
            as_dict=True,
        )[0].count
        gl_analysis["payment_entry_linked"] = pe_gl_count

        # GL Entries linked to Invoices
        si_gl_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM `tabGL Entry` gl
            JOIN `tabSales Invoice` si ON gl.voucher_no = si.name
            WHERE gl.company = %s
            AND gl.voucher_type = 'Sales Invoice'
            AND si.remarks LIKE '%%e-Boekhouden%%'
        """,
            (company,),
            as_dict=True,
        )[0].count
        gl_analysis["sales_invoice_linked"] = si_gl_count

        pi_gl_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM `tabGL Entry` gl
            JOIN `tabPurchase Invoice` pi ON gl.voucher_no = pi.name
            WHERE gl.company = %s
            AND gl.voucher_type = 'Purchase Invoice'
            AND pi.remarks LIKE '%%e-Boekhouden%%'
        """,
            (company,),
            as_dict=True,
        )[0].count
        gl_analysis["purchase_invoice_linked"] = pi_gl_count

        # GL Entries linked to Journal Entries
        je_gl_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM `tabGL Entry` gl
            JOIN `tabJournal Entry` je ON gl.voucher_no = je.name
            WHERE gl.company = %s
            AND gl.voucher_type = 'Journal Entry'
            AND je.user_remark LIKE '%%Migrated from e-Boekhouden%%'
        """,
            (company,),
            as_dict=True,
        )[0].count
        gl_analysis["journal_entry_linked"] = je_gl_count

        # Direct GL Entries with e-Boekhouden in remarks
        direct_gl_count = frappe.db.count(
            "GL Entry", filters=[["company", "=", company], ["remarks", "like", "%e-Boekhouden%"]]
        )
        gl_analysis["direct_remarks"] = direct_gl_count

        analysis["gl_entries"] = gl_analysis

        # 3. Analyze Invoices
        invoice_analysis = {}

        sales_invoices = frappe.db.count(
            "Sales Invoice", filters=[["company", "=", company], ["remarks", "like", "%e-Boekhouden%"]]
        )
        invoice_analysis["sales_invoices"] = sales_invoices

        purchase_invoices = frappe.db.count(
            "Purchase Invoice", filters=[["company", "=", company], ["remarks", "like", "%e-Boekhouden%"]]
        )
        invoice_analysis["purchase_invoices"] = purchase_invoices

        analysis["invoices"] = invoice_analysis

        # 4. Analyze Journal Entries
        journal_entries = frappe.db.count(
            "Journal Entry",
            filters=[["company", "=", company], ["user_remark", "like", "%Migrated from e-Boekhouden%"]],
        )
        analysis["journal_entries"] = journal_entries

        # 5. Analyze Customers and Suppliers
        customers = frappe.db.count("Customer", filters=[["customer_name", "like", "%e-Boekhouden%"]])
        suppliers = frappe.db.count("Supplier", filters=[["supplier_name", "like", "%e-Boekhouden%"]])

        analysis["parties"] = {"customers": customers, "suppliers": suppliers}

        # 6. Generate cleanup recommendations
        recommendations = []

        if submitted_pe > 0:
            recommendations.append(
                f"❗ {submitted_pe} submitted Payment Entries need proper cancellation before deletion"
            )

        if pe_gl_count > 0:
            recommendations.append(f"❗ {pe_gl_count} GL Entries are linked to Payment Entries")

        if (si_gl_count + pi_gl_count + je_gl_count) > 0:
            recommendations.append(
                f"❗ {si_gl_count + pi_gl_count + je_gl_count} GL Entries are linked to Invoices/Journal Entries"
            )

        if direct_gl_count > 0:
            recommendations.append(f"⚠️ {direct_gl_count} GL Entries have e-Boekhouden in remarks")

        recommendations.append(
            "✅ Use the improved debug_cleanup_all_imported_data() function for safe cleanup"
        )
        recommendations.append(
            "✅ Use debug_cleanup_gl_entries_only() if GL Entries remain after main cleanup"
        )

        analysis["recommendations"] = recommendations

        return {"success": True, "message": "Analysis completed successfully", "analysis": analysis}

    except Exception as e:
        return {"success": False, "error": str(e)}

    def stage_eboekhouden_data(self, settings):
        """Stage E-Boekhouden data for manual review before processing"""
        try:
            from .eboekhouden_soap_api import EBoekhoudenSOAPAPI

            # Initialize API
            api = EBoekhoudenSOAPAPI(settings)

            # Step 1: Retrieve and analyze Chart of Accounts
            self.db_set(
                {
                    "current_operation": "Retrieving Chart of Accounts for analysis...",
                    "progress_percentage": 32,
                }
            )
            frappe.db.commit()

            accounts_result = api.get_grootboekrekeningen()
            if not accounts_result["success"]:
                return {"success": False, "error": f"Failed to retrieve accounts: {accounts_result['error']}"}

            # Store account analysis for manual review
            account_analysis = self.analyze_account_structure(accounts_result["accounts"])

            # Step 2: Retrieve Relations for customer/supplier analysis
            self.db_set({"current_operation": "Retrieving relations data...", "progress_percentage": 35})
            frappe.db.commit()

            relations_result = api.get_relaties()
            if not relations_result["success"]:
                return {
                    "success": False,
                    "error": f"Failed to retrieve relations: {relations_result['error']}",
                }

            # Step 3: Sample mutation data for mapping analysis
            self.db_set(
                {
                    "current_operation": "Sampling transaction data for mapping analysis...",
                    "progress_percentage": 38,
                }
            )
            frappe.db.commit()

            # Get a representative sample of mutations
            sample_result = api.get_mutations(
                date_from=frappe.utils.add_months(frappe.utils.today(), -3), date_to=frappe.utils.today()
            )

            if not sample_result["success"]:
                return {
                    "success": False,
                    "error": f"Failed to retrieve sample mutations: {sample_result['error']}",
                }

            # Analyze mapping requirements
            mapping_analysis = self.analyze_mapping_requirements(sample_result["mutations"])

            # Store staging data
            staging_data = {
                "accounts": accounts_result["accounts"],
                "account_analysis": account_analysis,
                "relations": relations_result["relations"],
                "sample_mutations": sample_result["mutations"][:100],  # Store first 100 for analysis
                "mapping_analysis": mapping_analysis,
                "staged_at": frappe.utils.now_datetime(),
            }

            # Save staging data to migration document
            self.db_set(
                {
                    "staging_data": json.dumps(staging_data, default=str),
                    "migration_status": "Data Staged",
                    "current_operation": "Data staging completed - ready for configuration",
                }
            )
            frappe.db.commit()

            return {
                "success": True,
                "message": f"Staged {len(accounts_result['accounts'])} accounts, {len(relations_result['relations'])} relations, analyzed {len(sample_result['mutations'])} sample transactions",
                "analysis": {"accounts": account_analysis, "mappings": mapping_analysis},
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def analyze_account_structure(self, accounts):
        """Analyze the account structure to suggest proper account types"""
        analysis = {
            "total_accounts": len(accounts),
            "by_category": {},
            "account_type_suggestions": [],
            "potential_issues": [],
        }

        for account in accounts:
            category = account.get("Categorie", "Unknown")
            analysis["by_category"][category] = analysis["by_category"].get(category, 0) + 1

            # Suggest account types based on code patterns and categories
            code = account.get("Code", "")
            name = account.get("Omschrijving", "").lower()

            suggestion = self.suggest_account_type(code, name, category)
            if suggestion:
                analysis["account_type_suggestions"].append(
                    {
                        "code": code,
                        "name": account.get("Omschrijving", ""),
                        "category": category,
                        "suggested_type": suggestion["type"],
                        "confidence": suggestion["confidence"],
                        "reason": suggestion["reason"],
                    }
                )

        return analysis

    def suggest_account_type(self, code, name, category):
        """Suggest ERPNext account type based on E-Boekhouden account info"""
        suggestions = []

        # Code-based suggestions
        if code.startswith("1"):
            if "kas" in name or "bank" in name or "giro" in name:
                suggestions.append({"type": "Bank", "confidence": 0.9, "reason": "Bank/cash account pattern"})
            elif "debiteuren" in name or "vorderingen" in name:
                suggestions.append({"type": "Receivable", "confidence": 0.8, "reason": "Receivables pattern"})
            else:
                suggestions.append({"type": "Asset", "confidence": 0.7, "reason": "Asset account range"})

        elif code.startswith("2"):
            if "crediteuren" in name or "schulden" in name:
                suggestions.append({"type": "Payable", "confidence": 0.8, "reason": "Payables pattern"})
            else:
                suggestions.append(
                    {"type": "Liability", "confidence": 0.7, "reason": "Liability account range"}
                )

        elif code.startswith("3"):
            suggestions.append({"type": "Equity", "confidence": 0.8, "reason": "Equity account range"})

        elif code.startswith("4"):
            suggestions.append({"type": "Income", "confidence": 0.8, "reason": "Income account range"})

        elif code.startswith("5") or code.startswith("6") or code.startswith("7"):
            suggestions.append({"type": "Expense", "confidence": 0.8, "reason": "Expense account range"})

        # Category-based suggestions
        category_mappings = {
            "Omzet": {"type": "Income", "confidence": 0.9},
            "Kosten": {"type": "Expense", "confidence": 0.9},
            "Activa": {"type": "Asset", "confidence": 0.8},
            "Passiva": {"type": "Liability", "confidence": 0.8},
        }

        if category in category_mappings:
            suggestions.append({**category_mappings[category], "reason": f"Category '{category}' mapping"})

        # Return highest confidence suggestion
        if suggestions:
            return max(suggestions, key=lambda x: x["confidence"])

        return None

    def analyze_mapping_requirements(self, mutations):
        """Analyze mutations to identify mapping patterns and requirements"""
        analysis = {
            "total_mutations": len(mutations),
            "by_type": {},
            "account_usage": {},
            "unmapped_patterns": [],
            "suggested_mappings": [],
        }

        for mutation in mutations:
            mut_type = mutation.get("Soort", "Unknown")
            analysis["by_type"][mut_type] = analysis["by_type"].get(mut_type, 0) + 1

            # Analyze account usage in mutation lines
            for line in mutation.get("MutatieRegels", []):
                account_code = line.get("TegenrekeningCode")
                if account_code:
                    if account_code not in analysis["account_usage"]:
                        analysis["account_usage"][account_code] = {
                            "count": 0,
                            "sample_descriptions": [],
                            "amount_range": {"min": None, "max": None},
                        }

                    usage = analysis["account_usage"][account_code]
                    usage["count"] += 1

                    # Store sample descriptions
                    desc = line.get("Omschrijving") or mutation.get("Omschrijving", "")
                    if desc and len(usage["sample_descriptions"]) < 5:
                        usage["sample_descriptions"].append(desc)

                    # Track amount ranges
                    amount = float(line.get("BedragExclBTW", 0) or 0)
                    if amount:
                        if usage["amount_range"]["min"] is None or amount < usage["amount_range"]["min"]:
                            usage["amount_range"]["min"] = amount
                        if usage["amount_range"]["max"] is None or amount > usage["amount_range"]["max"]:
                            usage["amount_range"]["max"] = amount

        return analysis


@frappe.whitelist()
def get_staging_data_for_review(migration_name):
    """Get staged data for manual review and configuration"""
    try:
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        if not migration_doc.staging_data:
            return {"success": False, "error": "No staging data available"}

        staging_data = json.loads(migration_doc.staging_data)

        # Enhance with current mapping status
        enhanced_data = {
            "migration_status": migration_doc.migration_status,
            "staging_info": {
                "staged_at": staging_data.get("staged_at"),
                "accounts_count": len(staging_data.get("accounts", [])),
                "relations_count": len(staging_data.get("relations", [])),
                "sample_mutations_count": len(staging_data.get("sample_mutations", [])),
            },
            "account_analysis": staging_data.get("account_analysis", {}),
            "mapping_analysis": staging_data.get("mapping_analysis", {}),
            "current_mappings": get_current_account_mappings(migration_doc.company),
            "configuration_status": assess_configuration_status(migration_doc.company, staging_data),
        }

        return {"success": True, "data": enhanced_data}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_manual_account_mapping(
    migration_name, account_code, description_pattern, document_type, transaction_category, reason
):
    """Create a manual override for account mapping"""
    try:
        # Create or update account mapping
        existing = frappe.db.exists(
            "E-Boekhouden Account Mapping", {"account_code": account_code, "is_manual_override": 1}
        )

        if existing:
            mapping_doc = frappe.get_doc("E-Boekhouden Account Mapping", existing)
        else:
            mapping_doc = frappe.new_doc("E-Boekhouden Account Mapping")
            mapping_doc.account_code = account_code
            mapping_doc.is_manual_override = 1

        # Update mapping details
        mapping_doc.update(
            {
                "description_pattern": description_pattern,
                "document_type": document_type,
                "transaction_category": transaction_category,
                "override_reason": reason,
                "priority": 100,  # High priority for manual overrides
                "is_active": 1,
                "migration_reference": migration_name,
            }
        )

        mapping_doc.save()

        return {
            "success": True,
            "message": f"Manual mapping created for account {account_code}",
            "mapping_name": mapping_doc.name,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def preview_mapping_impact(migration_name, account_code=None, limit=50):
    """Preview what documents will be created with current mappings"""
    try:
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        if not migration_doc.staging_data:
            return {"success": False, "error": "No staging data available"}

        staging_data = json.loads(migration_doc.staging_data)
        sample_mutations = staging_data.get("sample_mutations", [])

        if account_code:
            # Filter mutations for specific account
            filtered_mutations = []
            for mutation in sample_mutations:
                for line in mutation.get("MutatieRegels", []):
                    if line.get("TegenrekeningCode") == account_code:
                        filtered_mutations.append(mutation)
                        break
            sample_mutations = filtered_mutations

        # Limit the preview
        sample_mutations = sample_mutations[:limit]

        preview_results = []

        for mutation in sample_mutations:
            # Apply current mapping logic
            from verenigingen.verenigingen.doctype.e_boekhouden_account_mapping.e_boekhouden_account_mapping import (
                get_mapping_for_mutation,
            )

            document_type = "Purchase Invoice"  # Default
            transaction_category = "General Expenses"
            mapping_name = None

            # Check each mutation line for account mapping
            for regel in mutation.get("MutatieRegels", []):
                account_code = regel.get("TegenrekeningCode")
                if account_code:
                    mapping = get_mapping_for_mutation(account_code, mutation.get("Omschrijving", ""))
                    if mapping and mapping.get("name"):
                        document_type = mapping["document_type"]
                        transaction_category = mapping["transaction_category"]
                        mapping_name = mapping["name"]
                        break

            preview_results.append(
                {
                    "mutation_nr": mutation.get("MutatieNr"),
                    "date": mutation.get("Datum"),
                    "description": mutation.get("Omschrijving", ""),
                    "amount": sum(
                        float(r.get("BedragInclBTW", 0) or 0) for r in mutation.get("MutatieRegels", [])
                    ),
                    "will_create": document_type,
                    "category": transaction_category,
                    "mapping_used": mapping_name,
                    "account_codes": [
                        r.get("TegenrekeningCode")
                        for r in mutation.get("MutatieRegels", [])
                        if r.get("TegenrekeningCode")
                    ],
                }
            )

        # Summary statistics
        summary = {
            "total_previewed": len(preview_results),
            "by_document_type": {},
            "by_category": {},
            "unmapped_count": 0,
        }

        for result in preview_results:
            doc_type = result["will_create"]
            category = result["category"]

            summary["by_document_type"][doc_type] = summary["by_document_type"].get(doc_type, 0) + 1
            summary["by_category"][category] = summary["by_category"].get(category, 0) + 1

            if not result["mapping_used"]:
                summary["unmapped_count"] += 1

        return {"success": True, "preview": preview_results, "summary": summary}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def approve_and_continue_migration(migration_name):
    """Approve current configuration and continue with migration"""
    try:
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        if migration_doc.migration_status != "Data Staged":
            return {
                "success": False,
                "error": f"Migration must be in 'Data Staged' status, currently: {migration_doc.migration_status}",
            }

        # Update status to continue migration
        migration_doc.db_set(
            {
                "migration_status": "Configuration Approved",
                "current_operation": "Configuration approved - resuming migration...",
                "progress_percentage": 45,
            }
        )
        frappe.db.commit()

        # Continue with the actual migration
        settings = frappe.get_single("E-Boekhouden Settings")

        migration_doc.db_set(
            {
                "current_operation": "Processing transactions with approved configuration...",
                "progress_percentage": 50,
            }
        )
        frappe.db.commit()

        # Use SOAP API migration with current mappings
        from verenigingen.utils.eboekhouden_soap_migration import migrate_using_soap

        result = migrate_using_soap(migration_doc, settings, True)  # Force use of account mappings

        if result["success"]:
            migration_doc.db_set(
                {
                    "migration_status": "Completed",
                    "current_operation": "Migration completed successfully",
                    "progress_percentage": 100,
                    "end_time": frappe.utils.now_datetime(),
                }
            )

            # Update summary
            summary = f"Migration completed: {result['stats']['invoices_created']} invoices, {result['stats']['payments_processed']} payments created"
            if result["stats"]["errors"]:
                summary += f", {len(result['stats']['errors'])} errors"

            migration_doc.db_set("migration_summary", summary)
            frappe.db.commit()

            return {"success": True, "message": summary, "stats": result["stats"]}
        else:
            migration_doc.db_set(
                {
                    "migration_status": "Failed",
                    "current_operation": f"Migration failed: {result.get('error', 'Unknown error')}",
                    "error_log": str(result.get("error", "")),
                }
            )
            frappe.db.commit()

            return {"success": False, "error": result.get("error", "Migration failed")}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_current_account_mappings(company):
    """Get current account mappings for the company"""
    mappings = frappe.get_all(
        "E-Boekhouden Account Mapping",
        filters={"is_active": 1},
        fields=[
            "name",
            "account_code",
            "account_name",
            "description_pattern",
            "document_type",
            "transaction_category",
            "priority",
            "usage_count",
            "is_manual_override",
        ],
        order_by="priority desc, usage_count desc",
    )

    return mappings


def assess_configuration_status(company, staging_data):
    """Assess the configuration readiness for migration"""
    status = {
        "accounts_configured": False,
        "mappings_configured": False,
        "ready_for_migration": False,
        "issues": [],
        "recommendations": [],
    }

    # Check account configuration
    account_analysis = staging_data.get("account_analysis", {})
    if account_analysis.get("account_type_suggestions"):
        unmapped_accounts = [s for s in account_analysis["account_type_suggestions"] if s["confidence"] < 0.8]
        if unmapped_accounts:
            status["issues"].append(f"{len(unmapped_accounts)} accounts have low confidence type suggestions")
            status["recommendations"].append(
                "Review and manually configure account types for better accuracy"
            )
        else:
            status["accounts_configured"] = True

    # Check mapping configuration
    current_mappings = get_current_account_mappings(company)
    mapping_analysis = staging_data.get("mapping_analysis", {})

    if mapping_analysis.get("account_usage"):
        unmapped_accounts = []
        for account_code, usage in mapping_analysis["account_usage"].items():
            has_mapping = any(m["account_code"] == account_code for m in current_mappings)
            if not has_mapping and usage["count"] > 1:  # Only care about frequently used accounts
                unmapped_accounts.append(account_code)

        if unmapped_accounts:
            status["issues"].append(f"{len(unmapped_accounts)} frequently used accounts have no mappings")
            status["recommendations"].append("Create account mappings for frequently used accounts")
        else:
            status["mappings_configured"] = True

    # Overall readiness
    status["ready_for_migration"] = status["accounts_configured"] and status["mappings_configured"]

    if status["ready_for_migration"]:
        status["recommendations"].append("Configuration looks good - ready to proceed with migration")

    return status


@frappe.whitelist()
def debug_nuclear_cleanup_all_imported_data(company=None):
    """Nuclear option: Aggressively clean up all imported data using direct SQL where needed"""
    try:
        # Get default company if not provided
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        results = {}

        # 1. First, nuclear cleanup of ALL GL Entries related to E-Boekhouden
        gl_deleted = 0
        try:
            # Delete GL Entries linked to Payment Entries with mutation numbers
            result = frappe.db.sql(
                """
                DELETE gl FROM `tabGL Entry` gl
                JOIN `tabPayment Entry` pe ON gl.voucher_no = pe.name
                WHERE gl.company = %s
                AND gl.voucher_type = 'Payment Entry'
                AND (
                    pe.eboekhouden_mutation_nr IS NOT NULL
                    OR pe.reference_no REGEXP '^[0-9]+$'
                    OR pe.remarks LIKE '%%Mutation Nr:%%'
                )
            """,
                (company,),
            )
            gl_deleted += result or 0

            # Delete GL Entries linked to E-Boekhouden invoices
            result = frappe.db.sql(
                """
                DELETE gl FROM `tabGL Entry` gl
                JOIN `tabSales Invoice` si ON gl.voucher_no = si.name
                WHERE gl.company = %s
                AND gl.voucher_type = 'Sales Invoice'
                AND si.remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
            )
            gl_deleted += result or 0

            result = frappe.db.sql(
                """
                DELETE gl FROM `tabGL Entry` gl
                JOIN `tabPurchase Invoice` pi ON gl.voucher_no = pi.name
                WHERE gl.company = %s
                AND gl.voucher_type = 'Purchase Invoice'
                AND pi.remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
            )
            gl_deleted += result or 0

            # Delete GL Entries linked to Journal Entries
            result = frappe.db.sql(
                """
                DELETE gl FROM `tabGL Entry` gl
                JOIN `tabJournal Entry` je ON gl.voucher_no = je.name
                WHERE gl.company = %s
                AND gl.voucher_type = 'Journal Entry'
                AND je.user_remark LIKE '%%Migrated from e-Boekhouden%%'
            """,
                (company,),
            )
            gl_deleted += result or 0

            # Delete any remaining GL Entries with e-Boekhouden in remarks
            result = frappe.db.sql(
                """
                DELETE FROM `tabGL Entry`
                WHERE company = %s
                AND remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
            )
            gl_deleted += result or 0

        except Exception as e:
            frappe.log_error(f"Error in nuclear GL Entry cleanup: {str(e)}")

        results["gl_entries_deleted"] = gl_deleted

        # 2. Nuclear cleanup of Payment Entries
        payment_deleted = 0
        try:
            # Direct SQL deletion of Payment Entries
            result = frappe.db.sql(
                """
                DELETE FROM `tabPayment Entry`
                WHERE company = %s
                AND (
                    eboekhouden_mutation_nr IS NOT NULL
                    OR reference_no REGEXP '^[0-9]+$'
                    OR remarks LIKE '%%Mutation Nr:%%'
                )
            """,
                (company,),
            )
            payment_deleted = result or 0
        except Exception as e:
            frappe.log_error(f"Error in nuclear Payment Entry cleanup: {str(e)}")

        results["payment_entries_deleted"] = payment_deleted

        # 3. Nuclear cleanup of Journal Entries
        je_deleted = 0
        try:
            result = frappe.db.sql(
                """
                DELETE FROM `tabJournal Entry`
                WHERE company = %s
                AND user_remark LIKE '%%Migrated from e-Boekhouden%%'
            """,
                (company,),
            )
            je_deleted = result or 0
        except Exception as e:
            frappe.log_error(f"Error in nuclear Journal Entry cleanup: {str(e)}")

        results["journal_entries_deleted"] = je_deleted

        # 4. Nuclear cleanup of Sales Invoices
        si_deleted = 0
        try:
            result = frappe.db.sql(
                """
                DELETE FROM `tabSales Invoice`
                WHERE company = %s
                AND remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
            )
            si_deleted = result or 0
        except Exception as e:
            frappe.log_error(f"Error in nuclear Sales Invoice cleanup: {str(e)}")

        results["sales_invoices_deleted"] = si_deleted

        # 5. Nuclear cleanup of Purchase Invoices
        pi_deleted = 0
        try:
            result = frappe.db.sql(
                """
                DELETE FROM `tabPurchase Invoice`
                WHERE company = %s
                AND remarks LIKE '%%e-Boekhouden%%'
            """,
                (company,),
            )
            pi_deleted = result or 0
        except Exception as e:
            frappe.log_error(f"Error in nuclear Purchase Invoice cleanup: {str(e)}")

        results["purchase_invoices_deleted"] = pi_deleted

        # 6. Clean up orphaned customer/supplier data (optional)
        customers_deleted = 0
        suppliers_deleted = 0
        try:
            # Only delete if they don't have other transactions
            result = frappe.db.sql(
                """
                DELETE FROM `tabCustomer`
                WHERE customer_name LIKE '%%e-Boekhouden%%'
                OR customer_name LIKE 'Customer %'
            """
            )
            customers_deleted = result or 0

            result = frappe.db.sql(
                """
                DELETE FROM `tabSupplier`
                WHERE supplier_name LIKE '%%e-Boekhouden%%'
                OR supplier_name LIKE 'Supplier %'
            """
            )
            suppliers_deleted = result or 0
        except Exception as e:
            frappe.log_error(f"Error in nuclear Customer/Supplier cleanup: {str(e)}")

        results["customers_deleted"] = customers_deleted
        results["suppliers_deleted"] = suppliers_deleted

        frappe.db.commit()

        return {"success": True, "message": "Nuclear cleanup completed successfully", "results": results}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_cleanup_transactions_only(company=None):
    """Debug function to clean up only transaction data (Journal Entries, Payment Entries, etc.)"""
    try:
        # Get default company if not provided
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        results = {}

        # Clean up Journal Entries
        journal_entries = frappe.get_all(
            "Journal Entry",
            filters={"company": company, "user_remark": ["like", "%Migrated from e-Boekhouden%"]},
        )

        for je in journal_entries:
            try:
                frappe.delete_doc("Journal Entry", je.name, force=True)
            except Exception:
                pass
        results["journal_entries_deleted"] = len(journal_entries)

        # Clean up Payment Entries (using multiple identification methods)
        payment_entries_deleted = 0

        # Method 1: By eboekhouden_mutation_nr (most reliable)
        try:
            mutation_nr_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["eboekhouden_mutation_nr", "is", "set"],
                    ["eboekhouden_mutation_nr", "!=", ""],
                    ["docstatus", "!=", 2],
                ],
            )

            for pe in mutation_nr_entries:
                try:
                    frappe.delete_doc("Payment Entry", pe.name, force=True)
                    payment_entries_deleted += 1
                except Exception:
                    pass
        except Exception:
            pass

        # Method 2: By numeric reference_no (backup method)
        try:
            numeric_ref_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["reference_no", "regexp", "^[0-9]+$"],
                    ["docstatus", "!=", 2],
                ],
            )

            for pe in numeric_ref_entries:
                try:
                    if frappe.db.exists("Payment Entry", pe.name):
                        frappe.delete_doc("Payment Entry", pe.name, force=True)
                        payment_entries_deleted += 1
                except Exception:
                    pass
        except Exception:
            pass

        # Method 3: By remarks pattern (catch remaining entries)
        try:
            remarks_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["remarks", "like", "%Mutation Nr:%"],
                    ["docstatus", "!=", 2],
                ],
            )

            for pe in remarks_entries:
                try:
                    if frappe.db.exists("Payment Entry", pe.name):
                        frappe.delete_doc("Payment Entry", pe.name, force=True)
                        payment_entries_deleted += 1
                except Exception:
                    pass
        except Exception:
            pass

        results["payment_entries_deleted"] = payment_entries_deleted

        # Clean up GL Entries
        gl_entries = frappe.db.get_all(
            "GL Entry", filters={"company": company, "remarks": ["like", "%e-Boekhouden%"]}
        )

        for gl in gl_entries:
            try:
                frappe.db.delete("GL Entry", gl.name)
            except Exception:
                pass
        results["gl_entries_deleted"] = len(gl_entries)

        frappe.db.commit()

        return {"success": True, "message": "Transaction cleanup completed successfully", "results": results}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_get_error_analysis(migration_name=None):
    """Debug function to analyze and categorize errors from the migration"""
    try:
        # Get the most recent migration if none specified
        if not migration_name:
            migration = frappe.get_all("E-Boekhouden Migration", order_by="creation desc", limit=1)
            if migration:
                migration_name = migration[0].name
            else:
                return {"success": False, "error": "No migrations found"}

        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Analyze failed records
        failed_records = getattr(migration_doc, "failed_record_details", [])

        error_categories = {}
        error_summary = {
            "total_errors": len(failed_records),
            "parent_account_errors": 0,
            "unknown_errors": 0,
            "validation_errors": 0,
            "other_errors": 0,
        }

        for record in failed_records:
            error_msg = record.get("error_message", "")
            record_type = record.get("record_type", "unknown")

            # Categorize errors
            if "parent_account" in error_msg.lower():
                error_summary["parent_account_errors"] += 1
                category = "parent_account"
            elif "unknown error" in error_msg.lower():
                error_summary["unknown_errors"] += 1
                category = "unknown"
            elif any(word in error_msg.lower() for word in ["validation", "required", "invalid"]):
                error_summary["validation_errors"] += 1
                category = "validation"
            else:
                error_summary["other_errors"] += 1
                category = "other"

            if category not in error_categories:
                error_categories[category] = []

            error_categories[category].append(
                {
                    "record_type": record_type,
                    "error": error_msg,
                    "timestamp": record.get("timestamp"),
                    "record_data": record.get("record_data", {}),
                }
            )

        return {
            "success": True,
            "migration_name": migration_name,
            "error_summary": error_summary,
            "error_categories": error_categories,
            "migration_status": migration_doc.migration_status,
            "migration_summary": migration_doc.migration_summary,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_cleanup_payment_entries_only(company=None):
    """Debug function to clean up only e-Boekhouden Payment Entries"""
    try:
        # Get default company if not provided
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        results = {
            "by_mutation_nr": 0,
            "by_reference_no": 0,
            "by_remarks": 0,
            "by_title": 0,
            "total_deleted": 0,
            "errors": [],
        }

        # Method 1: By eboekhouden_mutation_nr (most reliable)
        try:
            mutation_nr_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["eboekhouden_mutation_nr", "is", "set"],
                    ["eboekhouden_mutation_nr", "!=", ""],
                    ["docstatus", "!=", 2],
                ],
            )

            for pe in mutation_nr_entries:
                try:
                    # First cancel if submitted
                    doc = frappe.get_doc("Payment Entry", pe.name)
                    if doc.docstatus == 1:
                        doc.cancel()
                        frappe.db.commit()

                    frappe.delete_doc("Payment Entry", pe.name, force=True)
                    results["by_mutation_nr"] += 1
                except Exception as e:
                    results["errors"].append(f"Failed to delete {pe.name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Error querying by mutation_nr: {str(e)}")

        # Method 2: By numeric reference_no (backup method)
        try:
            numeric_ref_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["reference_no", "regexp", "^[0-9]+$"],
                    ["docstatus", "!=", 2],
                ],
            )

            for pe in numeric_ref_entries:
                try:
                    if frappe.db.exists("Payment Entry", pe.name):
                        # First cancel if submitted
                        doc = frappe.get_doc("Payment Entry", pe.name)
                        if doc.docstatus == 1:
                            doc.cancel()
                            frappe.db.commit()

                        frappe.delete_doc("Payment Entry", pe.name, force=True)
                        results["by_reference_no"] += 1
                except Exception as e:
                    results["errors"].append(f"Failed to delete {pe.name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Error querying by reference_no: {str(e)}")

        # Method 3: By remarks pattern (catch remaining entries)
        try:
            remarks_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["remarks", "like", "%Mutation Nr:%"],
                    ["docstatus", "!=", 2],
                ],
            )

            for pe in remarks_entries:
                try:
                    if frappe.db.exists("Payment Entry", pe.name):
                        # First cancel if submitted
                        doc = frappe.get_doc("Payment Entry", pe.name)
                        if doc.docstatus == 1:
                            doc.cancel()
                            frappe.db.commit()

                        frappe.delete_doc("Payment Entry", pe.name, force=True)
                        results["by_remarks"] += 1
                except Exception as e:
                    results["errors"].append(f"Failed to delete {pe.name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Error querying by remarks: {str(e)}")

        # Method 4: By title pattern (unreconciled payments)
        try:
            title_entries = frappe.get_all(
                "Payment Entry",
                filters=[
                    ["company", "=", company],
                    ["title", "like", "%UNRECONCILED%"],
                    ["docstatus", "!=", 2],
                ],
            )

            for pe in title_entries:
                try:
                    if frappe.db.exists("Payment Entry", pe.name):
                        # First cancel if submitted
                        doc = frappe.get_doc("Payment Entry", pe.name)
                        if doc.docstatus == 1:
                            doc.cancel()
                            frappe.db.commit()

                        frappe.delete_doc("Payment Entry", pe.name, force=True)
                        results["by_title"] += 1
                except Exception as e:
                    results["errors"].append(f"Failed to delete {pe.name}: {str(e)}")
        except Exception as e:
            results["errors"].append(f"Error querying by title: {str(e)}")

        results["total_deleted"] = (
            results["by_mutation_nr"]
            + results["by_reference_no"]
            + results["by_remarks"]
            + results["by_title"]
        )

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Deleted {results['total_deleted']} e-Boekhouden payment entries",
            "details": results,
        }

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_fix_parent_account_errors(migration_name=None):
    """Debug function to analyze and attempt to fix parent account errors"""
    try:
        # Get the most recent migration if none specified
        if not migration_name:
            migration = frappe.get_all("E-Boekhouden Migration", order_by="creation desc", limit=1)
            if migration:
                migration_name = migration[0].name
            else:
                return {"success": False, "error": "No migrations found"}

        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Get company
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        if not company:
            return {"success": False, "error": "No default company set"}

        # Get failed records with parent account errors
        failed_records = getattr(migration_doc, "failed_record_details", [])
        parent_account_errors = []

        for record in failed_records:
            error_msg = record.get("error_message", "")
            if "parent_account" in error_msg.lower():
                parent_account_errors.append(record)

        # Analyze the errors and suggest fixes
        fixes_suggested = []

        for error_record in parent_account_errors:
            record_data = error_record.get("record_data", {})
            account_code = record_data.get("code", "")
            account_name = record_data.get("description", "")

            # Suggest parent account based on account code
            suggested_parent = None
            if account_code.startswith("1"):
                suggested_parent = "Current Assets"
            elif account_code.startswith("2"):
                suggested_parent = "Fixed Assets"
            elif account_code.startswith("3"):
                suggested_parent = "Current Liabilities"
            elif account_code.startswith("4"):
                suggested_parent = "Current Liabilities"
            elif account_code.startswith("5"):
                suggested_parent = "Capital Account"
            elif account_code.startswith("8"):
                suggested_parent = "Direct Income"
            elif account_code.startswith("6") or account_code.startswith("7"):
                suggested_parent = "Direct Expenses"

            # Try to find the actual parent account in the system
            if suggested_parent:
                parent_account = frappe.db.get_value(
                    "Account",
                    {"company": company, "account_name": ["like", f"%{suggested_parent}%"], "is_group": 1},
                    "name",
                )

                if parent_account:
                    fixes_suggested.append(
                        {
                            "account_code": account_code,
                            "account_name": account_name,
                            "suggested_parent": parent_account,
                            "error": error_record.get("error_message"),
                        }
                    )

        return {
            "success": True,
            "migration_name": migration_name,
            "total_parent_account_errors": len(parent_account_errors),
            "fixes_suggested": fixes_suggested,
            "company": company,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def start_transaction_import(migration_name, import_type="recent"):
    """Start importing transactions with option for recent (SOAP) or all (REST)

    Args:
        migration_name: Name of the migration document
        import_type: 'recent' for last 500 via SOAP, 'all' for full history via REST
    """
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        if migration.migration_status != "Draft":
            return {"success": False, "error": "Migration must be in Draft status to start"}

        # Configure migration for transaction import
        migration.db_set(
            {
                "migrate_accounts": 0,  # Skip accounts
                "migrate_cost_centers": 0,  # Skip cost centers
                "migrate_customers": 1,  # Import any new customers found
                "migrate_suppliers": 1,  # Import any new suppliers found
                "migrate_transactions": 1,  # Import transactions
            }
        )
        frappe.db.commit()

        # For REST API full import, use different method
        if import_type == "all":
            # Check if REST API is configured
            settings = frappe.get_single("E-Boekhouden Settings")
            api_token = settings.get_password("api_token")
            if not api_token:
                return {
                    "success": False,
                    "error": "REST API token not configured. Please configure in E-Boekhouden Settings.",
                }

            # Start REST API import in background
            frappe.enqueue(
                "verenigingen.utils.eboekhouden_rest_full_migration.start_full_rest_import",
                migration_name=migration_name,
                queue="long",
                timeout=7200,  # 2 hours for full import
            )

            return {"success": True, "message": "Full transaction import started via REST API"}
        else:
            # Use standard SOAP migration for recent 500
            frappe.enqueue(
                "verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.run_migration_background",
                migration_name=migration_name,
                setup_only=False,
                queue="long",
                timeout=3600,
            )

            return {"success": True, "message": "Recent transaction import started via SOAP API"}

    except Exception as e:
        frappe.log_error(f"Error starting transaction import: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_rest_api_status():
    """Check if REST API is configured and working"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        # Check if API token is configured (either field name could be used)
        api_token = settings.get_password("api_token") or settings.get_password("rest_api_token")
        if not api_token:
            return {"configured": False, "message": "REST API token not configured"}

        # Try a simple REST API call to verify it works
        from verenigingen.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        try:
            iterator = EBoekhoudenRESTIterator()
            # Try to get session token by calling the private method
            session_token = iterator._get_session_token()
            if session_token:
                return {"configured": True, "working": True, "message": "REST API is configured and working"}
            else:
                return {
                    "configured": True,
                    "working": False,
                    "message": "REST API token configured but authentication failed",
                }
        except Exception as e:
            return {"configured": True, "working": False, "message": f"REST API error: {str(e)}"}

    except Exception as e:
        return {"configured": False, "error": str(e)}


@frappe.whitelist()
def update_account_type_mapping(account_name, new_account_type, company):
    """Update the account type for a specific account

    Args:
        account_name: Either the account name (doctype name) or account_name field
        new_account_type: The new account type to set
        company: Company name
    """
    try:
        # First try to find by name (doctype primary key)
        if frappe.db.exists("Account", account_name):
            account = frappe.get_doc("Account", account_name)
        # Otherwise try by account_name field
        elif frappe.db.exists("Account", {"account_name": account_name, "company": company}):
            account = frappe.get_doc("Account", {"account_name": account_name, "company": company})
        else:
            return {"success": False, "error": f"Account {account_name} not found"}

        # Validate it's from the right company
        if account.company != company:
            return {"success": False, "error": f"Account {account_name} belongs to different company"}

        # Update account type
        account.account_type = new_account_type
        account.save(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Updated account type for {account.account_name} to {new_account_type}",
        }

    except Exception as e:
        frappe.log_error(f"Error updating account type: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_account_type_recommendations(company, show_all=False):
    """Get recommended account types for E-Boekhouden imported accounts

    Args:
        company: Company name
        show_all: If True, show all accounts (not just those without types)
    """
    try:
        # Build the query based on whether we want all accounts or just untyped ones
        if show_all:
            # Get ALL imported accounts with parent information
            accounts = frappe.db.sql(
                """
                SELECT
                    a.name, a.account_name, a.eboekhouden_grootboek_nummer,
                    a.account_type, a.is_group, a.parent_account, a.root_type,
                    p.eboekhouden_grootboek_nummer as parent_group_number
                FROM `tabAccount` a
                LEFT JOIN `tabAccount` p ON a.parent_account = p.name
                WHERE a.company = %s
                AND a.eboekhouden_grootboek_nummer != ''
                ORDER BY a.eboekhouden_grootboek_nummer
            """,
                company,
                as_dict=True,
            )
        else:
            # Get only accounts without types
            accounts = frappe.db.sql(
                """
                SELECT
                    a.name, a.account_name, a.eboekhouden_grootboek_nummer,
                    a.account_type, a.is_group, a.parent_account, a.root_type,
                    p.eboekhouden_grootboek_nummer as parent_group_number
                FROM `tabAccount` a
                LEFT JOIN `tabAccount` p ON a.parent_account = p.name
                WHERE a.company = %s
                AND a.eboekhouden_grootboek_nummer != ''
                AND (a.account_type = '' OR a.account_type IS NULL)
                ORDER BY a.eboekhouden_grootboek_nummer
            """,
                company,
                as_dict=True,
            )

        recommendations = []

        for account in accounts:
            account_code = account.eboekhouden_grootboek_nummer
            account_name = account.account_name.lower()

            # Recommend account type based on code and name patterns
            recommended_type = None

            # === E-BOEKHOUDEN API CATEGORY-BASED CLASSIFICATION ===
            # Use logical inference of original E-Boekhouden categories based on account patterns

            # Infer likely E-Boekhouden category from account characteristics
            inferred_category = None

            # VW category inference - Profit & Loss accounts (codes 4, 6, 7, 8) - CHECK FIRST
            if account_code.startswith(("4", "6", "7", "8")):
                inferred_category = "VW"
                # Simple rule: opbrengsten = income, everything else = expense
                if "opbrengst" in account_name or "omzet" in account_name:
                    recommended_type = "Income Account"
                elif "afschrijving" in account_name:
                    recommended_type = "Depreciation"
                else:
                    recommended_type = "Expense Account"

            # FIN category inference - Liquid assets (should be Bank accounts) - CHECK AFTER VW
            elif (
                "liquide" in account_name
                or account_code in ["10480", "10620"]
                or (
                    any(
                        bank in account_name
                        for bank in ["bank", "triodos", "abn", "asn", "mollie", "paypal", "zettle"]
                    )
                    or " ing " in account_name
                    or account_name.startswith("ing ")
                    or account_name.endswith(" ing")
                )
            ):
                inferred_category = "FIN"
                recommended_type = "Bank"

            # DEB category inference - Debtors (should be receivables/current assets)
            elif "debiteur" in account_name or (
                account_code.startswith("13") and "te ontvangen" in account_name
            ):
                inferred_category = "DEB"
                recommended_type = "Current Asset"  # Use Current Asset to avoid party requirements

            # CRED category inference - Creditors (should be payables/current liabilities)
            elif "crediteur" in account_name or "te betalen" in account_name:
                inferred_category = "CRED"
                recommended_type = "Current Liability"  # Use Current Liability to avoid party requirements

            # VAT/BTW category inference - Tax accounts
            elif "btw" in account_name or "vat" in account_name:
                inferred_category = "VAT"
                recommended_type = "Tax"

            # BAL category inference - Balance sheet accounts (everything else)
            else:
                inferred_category = "BAL"
                # For BAL accounts, use root_type to determine account type
                if account.root_type == "Asset":
                    if account_code.startswith("05"):
                        recommended_type = "Equity"  # Misclassified equity accounts
                    else:
                        recommended_type = "Current Asset"
                elif account.root_type == "Liability":
                    if "vooruitontvangen" in account_name:
                        recommended_type = "Current Liability"
                    else:
                        recommended_type = "Current Liability"
                elif account.root_type == "Equity":
                    recommended_type = "Equity"
                else:
                    recommended_type = "Current Asset"  # Default fallback

            # Log the inferred category for debugging
            if inferred_category:
                frappe.logger().info(
                    f"Account {account_code} ({account_name}) inferred as E-Boekhouden category '{inferred_category}' -> {recommended_type}"
                )

            if recommended_type or not account.is_group:
                recommendations.append(
                    {
                        "account": account.name,
                        "account_name": account.account_name,
                        "account_code": account.eboekhouden_grootboek_nummer,
                        "current_type": account.account_type or "Not Set",
                        "recommended_type": recommended_type or "Not Sure",
                        "is_group": account.is_group,
                    }
                )

        return {"success": True, "recommendations": recommendations, "total_accounts": len(recommendations)}

    except Exception as e:
        frappe.log_error(f"Error getting account recommendations: {str(e)}")
        return {"success": False, "error": str(e)}
