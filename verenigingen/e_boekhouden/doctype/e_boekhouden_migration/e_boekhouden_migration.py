# Copyright (c) 2025, R.S.P. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from verenigingen.e_boekhouden.utils.security_helper import (
    migration_context,
    validate_and_insert,
    validate_and_save,
)


class EBoekhoudenMigration(Document):
    def validate(self):
        """Validate migration settings"""
        # Debug logging
        frappe.logger().debug(f"Validating migration: {self.migration_name}, Status: {self.migration_status}")

        # Allow empty dates for "import all transactions" - empty dates mean import everything
        if (
            getattr(self, "migrate_transactions", 0)
            and (self.date_from or self.date_to)
            and not (self.date_from and self.date_to)
        ):
            frappe.throw("If specifying a date range, both Date From and Date To are required")

        if self.date_from and self.date_to and getdate(self.date_from) > getdate(self.date_to):
            frappe.throw("Date From cannot be after Date To")

    def on_submit(self):
        """Start migration process when document is submitted"""
        frappe.logger().debug(f"Migration submitted: {self.migration_name}, Status: {self.migration_status}")
        if self.migration_status == "Draft":
            # Run migration in background to avoid timeouts
            self.start_migration_background()

    def start_migration_background(self):
        """Start migration process in background to avoid timeouts"""
        try:
            # Set initial status
            self.db_set(
                {
                    "migration_status": "In Progress",
                    "start_time": frappe.utils.now_datetime(),
                    "current_operation": "Queuing migration for background processing...",
                    "progress_percentage": 0,
                }
            )
            frappe.db.commit()

            # Run migration in background with appropriate timeout
            frappe.enqueue(
                "verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.run_migration_background",
                migration_name=self.name,
                queue="long",
                timeout=7200,  # 2 hours timeout
            )

        except Exception as e:
            self.db_set(
                {
                    "migration_status": "Failed",
                    "error_message": str(e),
                    "end_time": frappe.utils.now_datetime(),
                }
            )
            frappe.db.commit()
            raise

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

            # Phase 3: Transactions
            if getattr(self, "migrate_transactions", 0):
                self.db_set({"current_operation": "Migrating Transactions...", "progress_percentage": 80})
                frappe.db.commit()

                # Use getattr to avoid field/method name conflict
                migrate_method = getattr(self.__class__, "migrate_transactions_data")
                result = migrate_method(self, settings)
                migration_log.append(f"Transactions: {result}")

            # Phase 4: Stock Transactions
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

            from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

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
            from verenigingen.e_boekhouden.utils.eboekhouden_account_group_fix import (
                analyze_account_hierarchy,
            )

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
            from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

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
            from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

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

                    # Try multiple creation methods with proper permissions
                    try:
                        validate_and_save(
                            account, skip_validation=True
                        )  # Root accounts need special handling
                        created.append(f"{acc['account_name']} ({acc['root_type']})")
                        frappe.logger().info(f"Created root account: {account.name}")
                    except Exception:
                        # If save fails, try insert
                        try:
                            validate_and_insert(
                                account, skip_validation=True
                            )  # Root accounts need special handling
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
            from verenigingen.e_boekhouden.utils.eboekhouden_cost_center_fix import (
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
                    from verenigingen.e_boekhouden.utils.eboekhouden_cost_center_fix import (
                        fix_cost_center_groups,
                    )

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
            # from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI
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

    def migrate_transactions_data(self, settings):
        """Migrate Transactions from e-Boekhouden using REST API

        DEPRECATED: SOAP API usage has been removed. This method now always uses REST API.
        The SOAP API was limited to 500 transactions and is considered deprecated.
        """
        try:
            # Always use enhanced migration - single unified approach
            from verenigingen.e_boekhouden.utils.eboekhouden_enhanced_migration import (
                execute_enhanced_migration,
            )

            result = execute_enhanced_migration(self.name)

            # Extract stats from enhanced migration result
            if result.get("success", False):
                # Enhanced migration returns stats from start_full_rest_import
                if "stats" in result:
                    # Direct stats from start_full_rest_import
                    stats = result["stats"].copy()
                else:
                    # Fallback structure (backwards compatibility)
                    stats = {
                        "success": True,
                        "total_mutations": result.get("total_processed", 0),
                        "invoices_created": result.get("created", 0),
                        "payments_processed": 0,
                        "journal_entries_created": 0,
                        "errors": result.get("errors", []),
                    }

                # If we have audit summary, extract more detailed stats to override
                if "audit_summary" in result:
                    audit = result["audit_summary"]
                    if "overall_statistics" in audit:
                        overall = audit["overall_statistics"]
                        stats["invoices_created"] = overall.get("records_created", {}).get(
                            "Sales Invoice", 0
                        ) + overall.get("records_created", {}).get("Purchase Invoice", 0)
                        stats["payments_processed"] = overall.get("records_created", {}).get(
                            "Payment Entry", 0
                        )
                        stats["journal_entries_created"] = overall.get("records_created", {}).get(
                            "Journal Entry", 0
                        )

                result = {"success": True, "stats": stats}
            else:
                result = {"success": False, "error": result.get("error", "Migration failed")}

            # Process result regardless of which method was used
            if result.get("success"):
                if "stats" in result:
                    stats = result["stats"]
                    # Try to extract meaningful counts
                    imported = (
                        stats.get("invoices_created", 0)
                        + stats.get("payments_processed", 0)
                        + stats.get("journal_entries_created", 0)
                    )
                    failed = stats.get("errors", []) if isinstance(stats.get("errors"), list) else []
                    total = stats.get("total_mutations", imported)

                    self.imported_records += imported
                    self.failed_records += len(failed)
                    self.total_records += total

                    return f"Successfully imported {imported} transactions from {total} mutations"
                else:
                    # Fallback for other result formats
                    return "Transaction import completed successfully"
            else:
                return f"Error: {result.get('error', 'Unknown error')}"
        except Exception as e:
            return f"Error migrating Transactions: {str(e)}"

    def migrate_stock_transactions_data(self, settings):
        """Migrate Stock Transactions from e-Boekhouden"""
        try:
            # Use the fixed stock migration that properly handles E-Boekhouden limitations
            from verenigingen.utils.migration.stock_migration_fixed import migrate_stock_transactions_safe

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
                    from verenigingen.e_boekhouden.utils.eboekhouden_migration_enhancements import (
                        EnhancedAccountMigration,
                    )

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

            validate_and_insert(account)
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
        Enhanced Bank Account creation for Chart of Accounts bank account
        """
        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_coa_import import (
                create_bank_account_record,
                extract_bank_info_from_account_name,
                get_or_create_bank,
                is_potential_bank_account,
            )

            # First check if this looks like a bank account
            account_code = getattr(account_doc, "account_number", None)
            if not is_potential_bank_account(account_name, account_code):
                frappe.logger().debug(f"Account {account_name} does not appear to be a bank account")
                return None

            # Extract bank information from account name
            bank_info = extract_bank_info_from_account_name(account_name)

            # Enhanced validation - accept accounts even without perfect number match
            if bank_info.get("account_number") or bank_info.get("bank_name") != "Unknown Bank":
                # Check if Bank Account already exists
                existing_bank_account = None
                if bank_info.get("iban"):
                    existing_bank_account = frappe.db.exists("Bank Account", {"iban": bank_info["iban"]})

                if not existing_bank_account and bank_info.get("account_number"):
                    existing_bank_account = frappe.db.exists(
                        "Bank Account", {"bank_account_no": bank_info["account_number"]}
                    )

                # Also check by account mapping to avoid duplicates
                if not existing_bank_account:
                    existing_bank_account = frappe.db.exists("Bank Account", {"account": account_doc.name})

                if not existing_bank_account:
                    # Create or get Bank record
                    bank_name = get_or_create_bank(bank_info)

                    # Create Bank Account record with enhanced validation
                    bank_account = create_bank_account_record(
                        account=account_doc,
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
                        frappe.logger().warning(f"Failed to create Bank Account for {account_doc.name}")
                else:
                    frappe.logger().info(f"Bank Account already exists for account: {account_name}")
            else:
                frappe.logger().debug(f"Insufficient bank info extracted from {account_name}: {bank_info}")

            return None

        except Exception as e:
            frappe.logger().error(f"Error creating bank account for {account_doc.name}: {str(e)}")
            frappe.log_error(
                f"Bank account creation error for {account_doc.name}: {str(e)}", "Bank Account Creation"
            )
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

            validate_and_insert(group_account)
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
                from verenigingen.e_boekhouden.utils.eboekhouden_cost_center_fix import (
                    ensure_root_cost_center,
                )

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

            validate_and_insert(cost_center)
            frappe.logger().info(f"Created cost center: {description}")
            return True

        except Exception as e:
            self.log_error(f"Failed to create cost center {description}: {str(e)}")
            return False

    def create_customer(self, customer_data):
        """Create Customer in ERPNext with SOAP/REST API compatibility"""
        try:
            # Handle both SOAP and REST API data formats
            # SOAP format: {ID, Bedrijf, Contactpersoon, Email, BP, Geslacht, ...}
            # REST format: {id, name, companyName, contactName, email, ...}

            # Extract fields from either API format
            customer_id = customer_data.get("ID") or customer_data.get("id", "")
            company_name = (
                customer_data.get("Bedrijf", "").strip() or customer_data.get("companyName", "").strip()
            )
            contact_name = (
                customer_data.get("Contactpersoon", "").strip()
                or customer_data.get("contactName", "").strip()
            )
            email = customer_data.get("Email", "").strip() or customer_data.get("email", "").strip()
            name = customer_data.get("name", "").strip()

            # SOAP-specific fields for better classification
            bp_type = customer_data.get("BP", "")  # P=Person, B=Business

            # Determine display name and customer type
            display_name = company_name or contact_name or name

            # Determine if this is a company or individual
            is_company = False
            if bp_type == "B":  # Business type in SOAP
                is_company = True
            elif bp_type == "P":  # Person type in SOAP
                is_company = False
            elif company_name and not contact_name:  # REST API: only company name
                is_company = True
            elif contact_name and not company_name:  # REST API: only contact name
                is_company = False

            # If we have meaningful display name, create the customer
            if display_name:
                return self._create_customer_with_type(
                    customer_data, display_name, is_company, customer_id, email, contact_name
                )

            # If we only have ID (common case with REST API), skip creation during Chart of Accounts import
            if customer_id and not display_name:
                frappe.logger().info(
                    f"Skipping customer {customer_id} during Chart of Accounts import - no meaningful name data. Will be created during transaction import."
                )
                return False

            # If we have no usable data at all, log and skip
            frappe.logger().warning(f"Customer data has no usable information: {customer_data}")
            return False

        except Exception as e:
            frappe.logger().warning(f"Error in customer creation: {str(e)}")
            return False

    def _create_customer_with_type(
        self, customer_data, display_name, is_company, customer_id, email, contact_name
    ):
        """Create customer with proper company/individual classification"""
        try:
            # Check if customer already exists
            if frappe.db.exists("Customer", {"customer_name": display_name}):
                frappe.logger().info(f"Customer '{display_name}' already exists, skipping")
                return False

            # Get default settings
            settings = frappe.get_single("E-Boekhouden Settings")

            # Get proper territory
            territory = self.get_proper_territory_for_customer(customer_data)

            # Create new customer with proper type classification
            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": display_name,
                    "customer_type": "Company" if is_company else "Individual",
                    "customer_group": "All Customer Groups",
                    "territory": territory,
                    "default_currency": self._get_migration_currency(settings),
                    "disabled": 0,
                }
            )

            # Save relation ID for future updates (both SOAP and REST formats)
            if customer_id:
                try:
                    customer.eboekhouden_relation_code = str(customer_id)
                except Exception as rel_e:
                    frappe.logger().warning(f"Could not save relation ID {customer_id}: {str(rel_e)}")

            validate_and_insert(customer)

            # Create contact if contact details are available
            if contact_name or email:
                self.create_contact_for_customer(customer.name, customer_data)

            # Create address if address details are available (SOAP format)
            address_fields = ["Adres", "Plaats", "Postcode", "address", "city", "postalCode"]
            if any(customer_data.get(field) for field in address_fields):
                self.create_address_for_customer(customer.name, customer_data)

            customer_type_str = "Company" if is_company else "Individual"
            frappe.logger().info(f"Created {customer_type_str} customer: {display_name} (ID: {customer_id})")
            return True

        except Exception as e:
            self.log_error(f"Failed to create customer {display_name}: {str(e)}")
            return False

    def _create_customer_fallback(self, customer_data):
        """Fallback customer creation method"""
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
                    # Use relation ID for placeholder but mark for future update
                    display_name = f"eBoekhouden Relation {customer_id}"
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
                    "default_currency": self._get_migration_currency(settings),
                    "disabled": 0,
                }
            )

            # Save relation ID for future updates
            if customer_id:
                try:
                    customer.eboekhouden_relation_code = str(customer_id)
                except Exception as rel_e:
                    frappe.logger().warning(f"Could not save relation ID {customer_id}: {str(rel_e)}")

            validate_and_insert(customer)

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
        """Create Supplier in ERPNext with SOAP/REST API compatibility"""
        try:
            # Handle both SOAP and REST API data formats
            # SOAP format: {ID, Bedrijf, Contactpersoon, Email, BP, Geslacht, BTWNummer, ...}
            # REST format: {id, name, companyName, contactName, email, vatNumber, ...}

            # Extract fields from either API format
            supplier_id = supplier_data.get("ID") or supplier_data.get("id", "")
            company_name = (
                supplier_data.get("Bedrijf", "").strip() or supplier_data.get("companyName", "").strip()
            )
            contact_name = (
                supplier_data.get("Contactpersoon", "").strip()
                or supplier_data.get("contactName", "").strip()
            )
            email = supplier_data.get("Email", "").strip() or supplier_data.get("email", "").strip()
            name = supplier_data.get("name", "").strip()

            # SOAP-specific fields for better classification
            bp_type = supplier_data.get("BP", "")  # P=Person, B=Business
            vat_number = (
                supplier_data.get("BTWNummer", "").strip() or supplier_data.get("vatNumber", "").strip()
            )

            # Determine display name and supplier type
            display_name = company_name or contact_name or name

            # Determine if this is a company or individual
            is_company = False
            if bp_type == "B":  # Business type in SOAP
                is_company = True
            elif bp_type == "P":  # Person type in SOAP
                is_company = False
            elif company_name and not contact_name:  # REST API: only company name
                is_company = True
            elif contact_name and not company_name:  # REST API: only contact name
                is_company = False
            elif vat_number:  # Has VAT number, likely a business
                is_company = True

            # If we have meaningful display name, create the supplier
            if display_name:
                return self._create_supplier_with_type(
                    supplier_data, display_name, is_company, supplier_id, email, contact_name, vat_number
                )

            # If we only have ID (common case with REST API), skip creation during Chart of Accounts import
            if supplier_id and not display_name:
                frappe.logger().info(
                    f"Skipping supplier {supplier_id} during Chart of Accounts import - no meaningful name data. Will be created during transaction import."
                )
                return False

            # If we have no usable data at all, log and skip
            frappe.logger().warning(f"Supplier data has no usable information: {supplier_data}")
            return False

        except Exception as e:
            frappe.logger().warning(f"Error in supplier creation: {str(e)}")
            return False

    def _create_supplier_with_type(
        self, supplier_data, display_name, is_company, supplier_id, email, contact_name, vat_number
    ):
        """Create supplier with proper company/individual classification"""
        try:
            # Check if supplier already exists
            if frappe.db.exists("Supplier", {"supplier_name": display_name}):
                frappe.logger().info(f"Supplier '{display_name}' already exists, skipping")
                return False

            # Get default settings
            settings = frappe.get_single("E-Boekhouden Settings")

            # Create new supplier with proper type classification
            supplier = frappe.get_doc(
                {
                    "doctype": "Supplier",
                    "supplier_name": display_name,
                    "supplier_type": "Company" if is_company else "Individual",
                    "supplier_group": "All Supplier Groups",
                    "default_currency": self._get_migration_currency(settings),
                    "disabled": 0,
                }
            )

            # Save relation ID for future updates (both SOAP and REST formats)
            if supplier_id:
                try:
                    supplier.eboekhouden_relation_code = str(supplier_id)
                except Exception as rel_e:
                    frappe.logger().warning(f"Could not save relation ID {supplier_id}: {str(rel_e)}")

            # Add VAT number if available (both SOAP and REST formats)
            if vat_number:
                supplier.tax_id = vat_number

            validate_and_insert(supplier)

            # Create contact if contact details are available
            if contact_name or email:
                self.create_contact_for_supplier(supplier.name, supplier_data)

            # Create address if address details are available (SOAP format)
            address_fields = ["Adres", "Plaats", "Postcode", "address", "city", "postalCode"]
            if any(supplier_data.get(field) for field in address_fields):
                self.create_address_for_supplier(supplier.name, supplier_data)

            supplier_type_str = "Company" if is_company else "Individual"
            frappe.logger().info(f"Created {supplier_type_str} supplier: {display_name} (ID: {supplier_id})")
            return True

        except Exception as e:
            self.log_error(f"Failed to create supplier {display_name}: {str(e)}")
            return False

    def _create_supplier_fallback(self, supplier_data):
        """Fallback supplier creation method"""
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
                    # Use relation ID for placeholder but mark for future update
                    display_name = f"eBoekhouden Relation {supplier_id}"
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
                    "default_currency": self._get_migration_currency(settings),
                    "disabled": 0,
                }
            )

            # Save relation ID for future updates
            if supplier_id:
                try:
                    supplier.eboekhouden_relation_code = str(supplier_id)
                except Exception as rel_e:
                    frappe.logger().warning(f"Could not save relation ID {supplier_id}: {str(rel_e)}")

            # Add VAT number if available
            vat_number = supplier_data.get("vatNumber", "").strip()
            if vat_number:
                supplier.tax_id = vat_number

            validate_and_insert(supplier)

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

            validate_and_insert(journal_entry)
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

            validate_and_insert(contact)
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

            validate_and_insert(contact)
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

            validate_and_insert(address)
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

            validate_and_insert(address)
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

                from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

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

    def check_data_quality(self):
        """Check data quality of imported records"""
        quality_report = {
            "timestamp": frappe.utils.now(),
            "company": self.company,
            "issues": [],
            "statistics": {},
            "recommendations": [],
        }

        # Check unmapped GL accounts
        self._check_unmapped_accounts(quality_report)

        # Check missing party mappings
        self._check_missing_parties(quality_report)

        # Check transactions without categorization
        self._check_uncategorized_transactions(quality_report)

        # Check invoices missing tax information
        self._check_missing_tax_info(quality_report)

        # Check payment reconciliation status
        self._check_unreconciled_payments(quality_report)

        # Generate recommendations
        self._generate_quality_recommendations(quality_report)

        return quality_report

    def _check_unmapped_accounts(self, report):
        """Check for GL accounts used in transactions but not mapped"""
        unmapped = frappe.db.sql(
            """
            SELECT DISTINCT
                jea.account,
                COUNT(*) as usage_count,
                SUM(jea.debit_in_account_currency) as total_debit,
                SUM(jea.credit_in_account_currency) as total_credit
            FROM `tabJournal Entry Account` jea
            JOIN `tabJournal Entry` je ON je.name = jea.parent
            WHERE je.company = %s
            AND je.eboekhouden_mutation_nr IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM `tabE-Boekhouden Ledger Mapping` elm
                WHERE elm.erpnext_account = jea.account
            )
            GROUP BY jea.account
            ORDER BY usage_count DESC
        """,
            self.company,
            as_dict=True,
        )

        if unmapped:
            report["issues"].append(
                {
                    "type": "unmapped_accounts",
                    "severity": "medium",
                    "count": len(unmapped),
                    "details": unmapped[:10],  # Top 10
                }
            )

        report["statistics"]["unmapped_accounts"] = len(unmapped)
        return unmapped

    def _check_missing_parties(self, report):
        """Check for transactions with provisional parties"""
        missing_customers = frappe.db.count(
            "Customer", {"customer_name": ["like", "Provisional Customer%"], "disabled": 0}
        )

        missing_suppliers = frappe.db.count(
            "Supplier", {"supplier_name": ["like", "Provisional Supplier%"], "disabled": 0}
        )

        total_missing = missing_customers + missing_suppliers

        if total_missing > 0:
            report["issues"].append(
                {
                    "type": "provisional_parties",
                    "severity": "high",
                    "count": total_missing,
                    "details": {"customers": missing_customers, "suppliers": missing_suppliers},
                }
            )

        report["statistics"]["provisional_parties"] = total_missing
        return total_missing

    def _check_uncategorized_transactions(self, report):
        """Check for transactions without proper categorization"""
        # Check invoices with generic items
        generic_items = frappe.db.sql(
            """
            SELECT
                COUNT(DISTINCT parent) as invoice_count,
                COUNT(*) as line_count
            FROM (
                SELECT sii.parent, sii.item_code
                FROM `tabSales Invoice Item` sii
                JOIN `tabSales Invoice` si ON si.name = sii.parent
                WHERE si.company = %s
                AND si.eboekhouden_invoice_number IS NOT NULL
                AND sii.item_code IN ('Service Item', 'Generic Service', 'Generic Product')

                UNION ALL

                SELECT pii.parent, pii.item_code
                FROM `tabPurchase Invoice Item` pii
                JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
                WHERE pi.company = %s
                AND pi.eboekhouden_invoice_number IS NOT NULL
                AND pii.item_code IN ('Service Item', 'Generic Service', 'Generic Product')
            ) as generic_usage
        """,
            (self.company, self.company),
            as_dict=True,
        )

        if generic_items and generic_items[0].get("invoice_count", 0) > 0:
            report["issues"].append(
                {
                    "type": "generic_items",
                    "severity": "low",
                    "count": generic_items[0].get("invoice_count", 0),
                    "details": {
                        "invoices_affected": generic_items[0].get("invoice_count", 0),
                        "line_items": generic_items[0].get("line_count", 0),
                    },
                }
            )

        report["statistics"]["uncategorized_transactions"] = (
            generic_items[0].get("invoice_count", 0) if generic_items else 0
        )
        return generic_items

    def _check_missing_tax_info(self, report):
        """Check for invoices missing tax information"""
        missing_tax = frappe.db.sql(
            """
            SELECT
                'Sales' as invoice_type,
                COUNT(*) as count
            FROM `tabSales Invoice` si
            WHERE si.company = %s
            AND si.eboekhouden_invoice_number IS NOT NULL
            AND si.docstatus = 1
            AND NOT EXISTS (
                SELECT 1 FROM `tabSales Taxes and Charges` stc
                WHERE stc.parent = si.name
            )

            UNION ALL

            SELECT
                'Purchase' as invoice_type,
                COUNT(*) as count
            FROM `tabPurchase Invoice` pi
            WHERE pi.company = %s
            AND pi.eboekhouden_invoice_number IS NOT NULL
            AND pi.docstatus = 1
            AND NOT EXISTS (
                SELECT 1 FROM `tabPurchase Taxes and Charges` ptc
                WHERE ptc.parent = pi.name
            )
        """,
            (self.company, self.company),
            as_dict=True,
        )

        total_missing = sum(row.get("count", 0) for row in missing_tax)

        if total_missing > 0:
            report["issues"].append(
                {
                    "type": "missing_tax_info",
                    "severity": "high",
                    "count": total_missing,
                    "details": missing_tax,
                }
            )

        report["statistics"]["missing_tax_info"] = total_missing
        return missing_tax

    def _check_unreconciled_payments(self, report):
        """Check payment reconciliation status"""
        unreconciled = frappe.db.sql(
            """
            SELECT
                pe.payment_type,
                COUNT(*) as count,
                SUM(CASE WHEN pe.payment_type = 'Receive'
                    THEN pe.received_amount
                    ELSE pe.paid_amount END) as total_amount
            FROM `tabPayment Entry` pe
            WHERE pe.company = %s
            AND pe.eboekhouden_mutation_nr IS NOT NULL
            AND pe.docstatus = 1
            AND pe.unallocated_amount > 0
            GROUP BY pe.payment_type
        """,
            self.company,
            as_dict=True,
        )

        total_unreconciled = sum(row.get("count", 0) for row in unreconciled)

        if total_unreconciled > 0:
            report["issues"].append(
                {
                    "type": "unreconciled_payments",
                    "severity": "medium",
                    "count": total_unreconciled,
                    "details": unreconciled,
                }
            )

        report["statistics"]["unreconciled_payments"] = total_unreconciled
        return unreconciled

    def _generate_quality_recommendations(self, report):
        """Generate recommendations based on quality issues"""
        recommendations = []

        if report["statistics"].get("unmapped_accounts", 0) > 0:
            recommendations.append(
                {
                    "priority": "high",
                    "action": "Map GL Accounts",
                    "description": f"Map {report['statistics']['unmapped_accounts']} GL accounts to E-Boekhouden ledgers",
                    "impact": "Improves reporting accuracy and automation",
                }
            )

        if report["statistics"].get("provisional_parties", 0) > 0:
            recommendations.append(
                {
                    "priority": "high",
                    "action": "Update Party Information",
                    "description": f"Replace {report['statistics']['provisional_parties']} provisional parties with actual customer/supplier data",
                    "impact": "Enables proper communication and relationship management",
                }
            )

        if report["statistics"].get("missing_tax_info", 0) > 0:
            recommendations.append(
                {
                    "priority": "high",
                    "action": "Add Tax Information",
                    "description": f"Add tax details to {report['statistics']['missing_tax_info']} invoices",
                    "impact": "Ensures tax compliance and accurate financial reporting",
                }
            )

        if report["statistics"].get("unreconciled_payments", 0) > 0:
            recommendations.append(
                {
                    "priority": "medium",
                    "action": "Reconcile Payments",
                    "description": f"Reconcile {report['statistics']['unreconciled_payments']} payments with their invoices",
                    "impact": "Improves cash flow visibility and reduces outstanding balances",
                }
            )

        if report["statistics"].get("uncategorized_transactions", 0) > 0:
            recommendations.append(
                {
                    "priority": "low",
                    "action": "Categorize Items",
                    "description": f"Replace generic items in {report['statistics']['uncategorized_transactions']} invoices with specific categories",
                    "impact": "Better inventory management and cost analysis",
                }
            )

        report["recommendations"] = recommendations


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
            method="verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.run_migration_background",
            queue="long",
            timeout=3600,
            migration_name=migration_name,
            setup_only=setup_only,
        )

        return {"success": True, "message": "Migration started in background"}

    except Exception as e:
        frappe.log_error(f"Error starting migration: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def cleanup_chart_of_accounts(company, delete_all_accounts=False):
    """Delegated to cleanup_utils for better organization"""
    from verenigingen.e_boekhouden.utils.cleanup_utils import cleanup_chart_of_accounts as cleanup_impl

    return cleanup_impl(company, delete_all_accounts)


@frappe.whitelist()
def import_single_mutation(migration_name, mutation_id, overwrite_existing=True):
    """Import a single mutation by ID for testing purposes"""
    try:
        # Get migration record
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Check if mutation already exists
        existing_je = frappe.db.get_value(
            "Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)}, "name"
        )
        existing_si = frappe.db.get_value(
            "Sales Invoice", {"eboekhouden_mutation_nr": str(mutation_id)}, "name"
        )
        existing_pi = frappe.db.get_value(
            "Purchase Invoice", {"eboekhouden_mutation_nr": str(mutation_id)}, "name"
        )
        existing_pe = frappe.db.get_value(
            "Payment Entry", {"eboekhouden_mutation_nr": str(mutation_id)}, "name"
        )

        existing_doc = existing_je or existing_si or existing_pi or existing_pe

        if existing_doc and not overwrite_existing:
            return {
                "success": False,
                "error": f"Mutation {mutation_id} already exists as {existing_doc}. Enable 'Overwrite if exists' to replace it.",
            }

        # Delete existing document if overwrite is enabled
        if existing_doc and overwrite_existing:
            docs_to_delete = [
                ("Journal Entry", existing_je),
                ("Sales Invoice", existing_si),
                ("Purchase Invoice", existing_pi),
                ("Payment Entry", existing_pe),
            ]

            for doctype, docname in docs_to_delete:
                if docname:
                    try:
                        # Get the document to check its status
                        doc = frappe.get_doc(doctype, docname)

                        # If document is submitted, cancel it first
                        if doc.docstatus == 1:  # Submitted
                            # For Sales/Purchase Invoices, check for linked Payment Entries that need to be cancelled first
                            if doctype in ["Sales Invoice", "Purchase Invoice"]:
                                linked_payments = frappe.get_all(
                                    "Payment Entry",
                                    filters={
                                        "reference_doctype": doctype,
                                        "reference_name": docname,
                                        "docstatus": 1,
                                    },
                                    fields=["name"],
                                )

                                for payment in linked_payments:
                                    payment_doc = frappe.get_doc("Payment Entry", payment.name)
                                    payment_doc.cancel()
                                    frappe.logger().info(
                                        f"Cancelled linked Payment Entry {payment.name} before deleting {doctype} {docname}"
                                    )

                            doc.cancel()
                            frappe.logger().info(f"Cancelled {doctype} {docname} before deletion")

                        # Now delete the document
                        frappe.delete_doc(doctype, docname, force=True)
                        frappe.logger().info(
                            f"Deleted {doctype} {docname} for mutation {mutation_id} overwrite"
                        )

                    except Exception as e:
                        # Log the error but continue with the import
                        frappe.log_error(
                            title=f"Failed to delete {doctype} {docname}",
                            message=f"Error during overwrite deletion: {str(e)}",
                        )
                        return {
                            "success": False,
                            "error": f"Failed to delete existing {doctype} {docname}: {str(e)}. Please cancel it manually first.",
                        }

        # Fetch mutation from eBoekhouden API
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        try:
            settings = frappe.get_single("E-Boekhouden Settings")
            api = EBoekhoudenAPI(settings)
        except ValueError as e:
            return {
                "success": False,
                "error": f"E-Boekhouden API configuration error: {str(e)}. Please check the E-Boekhouden Settings.",
            }

        result = api.make_request(f"v1/mutation/{mutation_id}")

        if not result or not result.get("success") or result.get("status_code") != 200:
            return {
                "success": False,
                "error": f"Failed to fetch mutation {mutation_id} from eBoekhouden API: {result.get('error', 'Unknown error')}",
            }

        # Parse mutation data
        import json

        mutation_data = json.loads(result.get("data", "{}"))

        # Import the mutation
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _process_single_mutation

        debug_info = []

        # Get cost center for the company
        company = migration.company
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        if not cost_center:
            return {"success": False, "error": f"No cost center found for company {company}"}

        # Process the mutation
        created_doc = _process_single_mutation(
            mutation=mutation_data, company=company, cost_center=cost_center, debug_info=debug_info
        )

        if created_doc:
            # Get document type and name from the document object
            doc_type = created_doc.doctype
            doc_name = created_doc.name

            frappe.db.commit()

            return {
                "success": True,
                "mutation_id": mutation_id,
                "document_type": doc_type,
                "document_name": doc_name,
                "debug_info": debug_info,
                "message": f"Successfully imported mutation {mutation_id} as {doc_type} {doc_name}",
            }
        else:
            return {
                "success": False,
                "error": f"Failed to create document for mutation {mutation_id}. Check debug info for details.",
                "debug_info": debug_info,
            }

    except Exception as e:
        frappe.log_error(f"Error importing single mutation {mutation_id}: {str(e)}")
        return {
            "success": False,
            "error": f"Unexpected error importing mutation {mutation_id}: {str(e)}",
        }


@frappe.whitelist()
def start_transaction_import(migration_name, import_type="recent"):
    """Start importing transactions using REST API only

    DEPRECATED: The 'recent' option previously used SOAP API which was limited to 500 transactions.
    Now both 'recent' and 'all' use REST API with different date ranges.

    Args:
        migration_name: Name of the migration document
        import_type: 'recent' for last 90 days, 'all' for full history via REST
    """
    try:
        # Debug: Log the migration name we're looking for
        frappe.logger().info(f"Looking for migration document: {migration_name}")

        # Check if document exists first
        if not frappe.db.exists("E-Boekhouden Migration", migration_name):
            # Get recent migrations for debugging
            recent_migrations = frappe.get_all(
                "E-Boekhouden Migration",
                fields=["name", "migration_name", "creation"],
                order_by="creation desc",
                limit=5,
            )
            frappe.logger().error(
                f"Migration document '{migration_name}' not found. Recent migrations: {recent_migrations}"
            )
            return {
                "success": False,
                "error": f"Migration document '{migration_name}' not found. Please ensure the document is saved before starting import.",
                "debug_info": {"recent_migrations": recent_migrations},
            }

        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        if migration.migration_status != "Draft":
            return {"success": False, "error": "Migration must be in Draft status to start"}

        # Check if REST API is configured
        settings = frappe.get_single("E-Boekhouden Settings")
        api_token = settings.get_password("api_token") or settings.get_password("rest_api_token")
        if not api_token:
            return {
                "success": False,
                "error": "REST API token not configured. Please configure in E-Boekhouden Settings.",
            }

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

        # Set date range based on import type
        if import_type == "recent":
            # Import last 90 days of transactions
            from frappe.utils import add_days, today

            migration.db_set({"date_from": add_days(today(), -90), "date_to": today()})
            message = "Recent transactions import started (last 90 days) via REST API"
        else:
            # Full import - dates should already be set or will use full range
            message = "Full transaction import started via REST API"

        frappe.db.commit()

        # Always use REST API import
        frappe.enqueue(
            "verenigingen.e_boekhouden.utils_rest_full_migration.start_full_rest_import",
            migration_name=migration_name,
            queue="long",
            timeout=7200 if import_type == "all" else 3600,  # 2 hours for full, 1 hour for recent
        )

        return {"success": True, "message": message}

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
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

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
def check_migration_data_quality(migration_name):
    """Check data quality for a migration"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        quality_report = migration.check_data_quality()

        # Store the quality report in the migration document
        # Using migration_summary field as data_quality_report field doesn't exist
        migration.db_set("migration_summary", json.dumps(quality_report))

        return {"success": True, "report": quality_report}
    except Exception as e:
        frappe.log_error(f"Data quality check failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def import_opening_balances_only(migration_name):
    """Import only opening balances using the new ERPNext approach"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Import opening balances using the new implementation
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _import_opening_balances

        # Get company details
        company = migration.company
        cost_center = frappe.db.get_value("Company", company, "cost_center")

        debug_info = []

        # Check if this is a dry run
        is_dry_run = migration.get("dry_run", False)

        # Call the new opening balance import function
        frappe.logger().info(f"Starting opening balance import for company: {company}, dry_run: {is_dry_run}")
        result = _import_opening_balances(company, cost_center, debug_info, dry_run=is_dry_run)
        frappe.logger().info(f"Opening balance import result: {result}")

        # Update migration record with results
        if result.get("success"):
            imported_count = 1 if result.get("journal_entry") else 0
            # Use the actual number of opening balance mutations processed
            accounts_processed = result.get("accounts_processed", 0)
            total_mutations = accounts_processed if accounts_processed > 0 else imported_count

            migration.db_set(
                {
                    "migration_status": "Completed",
                    "imported_records": imported_count,
                    "total_records": total_mutations,  # Show actual number of mutations processed
                    "migration_summary": f"Opening balances imported. Journal Entry: {result.get('journal_entry', 'None')}. Processed {accounts_processed} opening balance accounts.",
                }
            )
        else:
            migration.db_set(
                {
                    "migration_status": "Failed",
                    "error_log": result.get("error", "Unknown error"),
                }
            )

        frappe.db.commit()

        return {
            "success": result.get("success", False),
            "result": {
                "imported": 1 if result.get("journal_entry") else 0,
                "journal_entry": result.get("journal_entry"),
                "message": result.get("message", ""),
                "errors": [result.get("error")] if result.get("error") else [],
                "debug_info": debug_info,
            },
        }

    except Exception as e:
        frappe.log_error(f"Opening balance import failed: {str(e)}")

        # Only try to update migration record if the document exists
        if frappe.db.exists("E-Boekhouden Migration", migration_name):
            try:
                migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
                migration.db_set({"migration_status": "Failed", "error_log": str(e)})
                frappe.db.commit()
            except Exception as update_error:
                frappe.log_error(f"Could not update migration status: {str(update_error)}")

        return {"success": False, "error": str(e)}


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
        validate_and_save(account)

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Updated account type for {account.account_name} to {new_account_type}",
        }

    except Exception as e:
        frappe.log_error(f"Error updating account type: {str(e)}")
        return {"success": False, "error": str(e)}

    def _get_migration_currency(self, settings):
        """Get currency for migration with explicit validation"""
        # Check settings default currency
        if hasattr(settings, "default_currency") and settings.default_currency:
            return settings.default_currency

        # Get company default currency
        if hasattr(self, "company") and self.company:
            company_currency = frappe.db.get_value("Company", self.company, "default_currency")
            if company_currency:
                return company_currency

        # Final fallback with logging
        frappe.log_error(
            f"No currency configured in E-Boekhouden Settings or Company settings for migration '{self.name}', using 'EUR' fallback",
            "E-Boekhouden Migration Currency Configuration",
        )
        return "EUR"


@frappe.whitelist()
def run_migration_background(migration_name):
    """Background function to run migration without timeout issues"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.start_migration()
        return {"success": True}
    except Exception as e:
        frappe.log_error(f"Error in background migration: {str(e)}")
        # Update migration status
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.db_set(
            {
                "migration_status": "Failed",
                "error_message": str(e),
                "end_time": frappe.utils.now_datetime(),
            }
        )
        frappe.db.commit()
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
                    a.name as account, a.account_name, a.eboekhouden_grootboek_nummer as account_code,
                    a.account_type as current_type, a.is_group, a.parent_account, a.root_type,
                    p.eboekhouden_grootboek_nummer as parent_group_number
                FROM `tabAccount` a
                LEFT JOIN `tabAccount` p ON a.parent_account = p.name
                WHERE a.company = %s
                AND a.eboekhouden_grootboek_nummer IS NOT NULL
                AND a.eboekhouden_grootboek_nummer != ''
                ORDER BY a.eboekhouden_grootboek_nummer
            """,
                company,
                as_dict=True,
            )
        else:
            # Get only accounts without proper types set
            accounts = frappe.db.sql(
                """
                SELECT
                    a.name as account, a.account_name, a.eboekhouden_grootboek_nummer as account_code,
                    a.account_type as current_type, a.is_group, a.parent_account, a.root_type,
                    p.eboekhouden_grootboek_nummer as parent_group_number
                FROM `tabAccount` a
                LEFT JOIN `tabAccount` p ON a.parent_account = p.name
                WHERE a.company = %s
                AND a.eboekhouden_grootboek_nummer IS NOT NULL
                AND a.eboekhouden_grootboek_nummer != ''
                AND (a.account_type IS NULL OR a.account_type = '' OR a.account_type = 'Not Set')
                ORDER BY a.eboekhouden_grootboek_nummer
            """,
                company,
                as_dict=True,
            )

        # Add recommended types for each account
        recommendations = []
        for account in accounts:
            if not account.account_code:
                continue

            recommended_type = get_recommended_account_type(account.account_code, account.account_name)

            recommendations.append(
                {
                    "account": account.account,
                    "account_code": account.account_code,
                    "account_name": account.account_name,
                    "current_type": account.current_type or "Not Set",
                    "recommended_type": recommended_type,
                    "is_group": account.is_group,
                    "parent_account": account.parent_account,
                    "root_type": account.root_type,
                }
            )

        return {"success": True, "recommendations": recommendations}

    except Exception as e:
        frappe.log_error(f"Error getting account type recommendations: {str(e)}")
        return {"success": False, "error": str(e)}


def get_recommended_account_type(account_code, account_name):
    """Get recommended account type based on E-Boekhouden account code patterns"""
    try:
        code = str(account_code).strip()
        name = account_name.lower() if account_name else ""

        # Dutch account code patterns based on RGS (Reference Code System)
        if code.startswith("1"):
            # Balance sheet - Assets
            if code.startswith("10"):
                return "Fixed Asset"
            elif code.startswith("11") or code.startswith("12"):
                return "Current Asset"
            elif code.startswith("13"):
                if "bank" in name or "kas" in name or "giro" in name:
                    return "Bank"
                elif "debiteuren" in name or "vorderingen" in name:
                    return "Receivable"
                else:
                    return "Current Asset"
            elif code.startswith("14"):
                return "Stock"
            elif code.startswith("15"):
                if "btw" in name or "belasting" in name:
                    return "Tax"
                else:
                    return "Current Liability"
            elif code.startswith("16") or code.startswith("17"):
                return "Current Liability"
            elif code.startswith("18") or code.startswith("19"):
                return "Current Liability"
            else:
                return "Current Asset"

        elif code.startswith("2"):
            # Balance sheet - Liabilities & Equity
            if code.startswith("20") or code.startswith("21"):
                return "Payable"
            elif code.startswith("22") or code.startswith("23"):
                return "Current Liability"
            elif code.startswith("24") or code.startswith("25"):
                return "Equity"
            elif code.startswith("26") or code.startswith("27"):
                return "Equity"
            else:
                return "Current Liability"

        elif code.startswith("3"):
            # Profit & Loss - Revenue
            return "Income"

        elif code.startswith("4"):
            # Profit & Loss - Cost of Sales
            return "Cost of Goods Sold"

        elif code.startswith("5"):
            # Profit & Loss - Personnel costs
            return "Expense"

        elif code.startswith("6"):
            # Profit & Loss - Depreciation & other costs
            return "Expense"

        elif code.startswith("7"):
            # Profit & Loss - Financial income/costs
            if "rente" in name and ("ontvangen" in name or "baten" in name):
                return "Income"
            else:
                return "Expense"

        elif code.startswith("8"):
            # Profit & Loss - Extraordinary income/costs
            if any(word in name for word in ["opbrengst", "baten", "winst", "ontvangen"]):
                return "Income"
            else:
                return "Expense"
        else:
            return "Not Sure"

    except Exception as e:
        frappe.log_error(f"Error determining account type for {account_code}: {str(e)}")
        return "Not Sure"
