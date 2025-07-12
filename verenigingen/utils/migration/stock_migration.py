"""
Stock Transaction Migration from e-Boekhouden

This module handles the migration of stock-related transactions from e-Boekhouden
to ERPNext using proper stock transactions instead of journal entries.
"""

import json
from datetime import datetime, timedelta

import frappe
from frappe.utils import getdate, today


class StockTransactionMigrator:
    """Handles stock transaction migration from e-Boekhouden"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.stock_transactions_created = 0
        self.stock_transactions_failed = 0
        self.stock_transactions_skipped = 0
        self.error_log = []
        self.ledger_to_account_cache = {}  # Cache for ledger ID to account code mapping

    def migrate_stock_transactions(self, settings, date_from=None, date_to=None):
        """Migrate stock transactions from e-Boekhouden"""
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            # Debug logging
            print("Starting stock transaction migration...")
            print(f"Settings type: {type(settings)}")

            api = EBoekhoudenAPI(settings)
            print("API initialized successfully")

            # Get stock accounts to filter transactions
            stock_accounts = self.get_stock_accounts()
            print(f"Found {len(stock_accounts)} stock accounts")
            if not stock_accounts:
                return "No stock accounts found in the system"

            # Set date range
            if not date_from:
                date_from = (
                    getdate(self.migration_doc.date_from)
                    if hasattr(self.migration_doc, "date_from") and self.migration_doc.date_from
                    else getdate("2023-01-01")
                )
            else:
                date_from = getdate(date_from)

            if not date_to:
                date_to = (
                    getdate(self.migration_doc.date_to)
                    if hasattr(self.migration_doc, "date_to") and self.migration_doc.date_to
                    else getdate(today())
                )
            else:
                date_to = getdate(date_to)

            current_date = date_from
            total_processed = 0

            print(f"Starting stock transaction migration from {date_from} to {date_to}")
            print(
                "Found {len(stock_accounts)} stock accounts: {', '.join([acc['account_number'] for acc in stock_accounts])}"
            )

            # Process month by month to avoid large data sets
            while current_date <= date_to:
                # Calculate month end
                if current_date.month == 12:
                    month_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(
                        days=1
                    )
                else:
                    month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)

                month_end = min(month_end, date_to)

                # Get transactions for this month
                params = {
                    "dateFrom": current_date.strftime("%Y-%m-%d"),
                    "dateTo": month_end.strftime("%Y-%m-%d"),
                }

                print(f"Processing transactions for {current_date.strftime('%Y-%m')}...")

                result = api.get_mutations(params)

                if result["success"]:
                    data = json.loads(result["data"])
                    transactions = data.get("items", [])

                    # Filter for stock-related transactions
                    stock_transactions = self.filter_stock_transactions(transactions, stock_accounts)

                    if stock_transactions:
                        print(
                            "Found {len(stock_transactions)} stock transactions in {current_date.strftime('%Y-%m')}"
                        )

                        # Process stock transactions
                        for transaction in stock_transactions:
                            dry_run_mode = getattr(self.migration_doc, "dry_run", True)
                            if dry_run_mode:
                                total_processed += 1
                            else:
                                if self.process_stock_transaction(transaction, stock_accounts):
                                    self.stock_transactions_created += 1
                                    total_processed += 1
                                else:
                                    self.stock_transactions_failed += 1
                    else:
                        print(f"No stock transactions found in {current_date.strftime('%Y-%m')}")

                # Move to next month
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1, day=1)

            # Generate summary
            summary_parts = []
            dry_run_mode = getattr(self.migration_doc, "dry_run", True)  # Default to dry run
            if dry_run_mode:
                summary_parts.append("Dry Run: Found {total_processed} stock transactions to migrate")
            else:
                summary_parts.append("Created {self.stock_transactions_created} stock entries")
                if self.stock_transactions_failed > 0:
                    summary_parts.append("Failed: {self.stock_transactions_failed}")
                if self.stock_transactions_skipped > 0:
                    summary_parts.append("Skipped: {self.stock_transactions_skipped}")

            return " | ".join(summary_parts)

        except Exception as e:
            # Use safe error logging to prevent cascading
            from verenigingen.utils.error_log_fix import log_error_safely

            log_error_safely(
                message=f"Stock migration error:\n{str(e)}\n\n{frappe.get_traceback()}",
                title="Stock Migration Failed",
            )
            return f"Error migrating stock transactions: {str(e)[:100]}..."

    def get_stock_accounts(self):
        """Get all stock accounts with their account numbers"""
        return frappe.get_all(
            "Account", filters={"account_type": "Stock"}, fields=["name", "account_number", "account_name"]
        )

    def filter_stock_transactions(self, transactions, stock_accounts):
        """Filter transactions that affect stock accounts"""
        print(f"Filtering {len(transactions)} transactions against {len(stock_accounts)} stock accounts")

        stock_account_numbers = [acc["account_number"] for acc in stock_accounts]
        print(f"Stock account numbers: {stock_account_numbers}")

        # Get ledger ID to account code mapping
        stock_transactions = []

        for i, transaction in enumerate(transactions):
            if i % 10 == 0:  # Progress indicator
                print(f"Processing transaction {i + 1}/{len(transactions)}")

            ledger_id = transaction.get("ledgerId", "")
            account_code = self.get_account_code_from_ledger_id(ledger_id)

            print(f"Transaction {i}: ledger_id={ledger_id}, account_code={account_code}")

            if account_code in stock_account_numbers:
                print(f"Found stock transaction: {account_code}")
                stock_transactions.append(
                    {
                        **transaction,
                        "account_code": account_code,
                        "account_name": next(
                            (
                                acc["account_name"]
                                for acc in stock_accounts
                                if acc["account_number"] == account_code
                            ),
                            "Unknown",
                        ),
                    }
                )

        print(f"Filtered result: {len(stock_transactions)} stock transactions")
        return stock_transactions

    def build_ledger_mapping(self):
        """Build ledger ID to account code mapping cache"""
        if self.ledger_to_account_cache:
            return  # Already built

        print("Building ledger ID to account code mapping...")
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            settings = frappe.get_single("E-Boekhouden Settings")
            api = EBoekhoudenAPI(settings)

            # Get chart of accounts to map ledger ID to account code
            result = api.get_chart_of_accounts()
            if result["success"]:
                data = json.loads(result["data"])
                accounts = data.get("items", [])

                for account in accounts:
                    ledger_id = str(account.get("id", ""))
                    account_code = account.get("code", "")
                    if ledger_id and account_code:
                        self.ledger_to_account_cache[ledger_id] = account_code

                print(f"Built mapping for {len(self.ledger_to_account_cache)} accounts")
            else:
                print("Failed to get chart of accounts for mapping")

        except Exception as e:
            print(f"Error building ledger mapping: {str(e)}")

    def get_account_code_from_ledger_id(self, ledger_id):
        """Get account code from ledger ID using cache"""
        if not self.ledger_to_account_cache:
            self.build_ledger_mapping()

        return self.ledger_to_account_cache.get(str(ledger_id), str(ledger_id))

    def process_stock_transaction(self, transaction, stock_accounts):
        """Process a single stock transaction"""
        try:
            account_code = transaction.get("account_code", "")
            account_name = transaction.get("account_name", "")
            amount = float(transaction.get("amount", 0) or 0)
            transaction_date = transaction.get("date", "")
            transaction_type = transaction.get("type", 0)
            ledger_id = transaction.get("ledgerId", "")

            if amount == 0:
                self.stock_transactions_skipped += 1
                return False

            # Parse date
            if "T" in transaction_date:
                posting_date = datetime.strptime(transaction_date.split("T")[0], "%Y-%m-%d").date()
            else:
                posting_date = datetime.strptime(transaction_date, "%Y-%m-%d").date()

            # Determine stock movement type based on transaction type and amount
            if transaction_type == 0:  # Debit - typically stock increase
                purpose = "Material Receipt"
                qty_change = abs(amount)  # Positive quantity
            else:  # Credit - typically stock decrease
                purpose = "Material Issue"
                qty_change = -abs(amount)  # Negative quantity

            # Create stock entry
            stock_entry = self.create_stock_entry(
                posting_date=posting_date,
                purpose=purpose,
                account_code=account_code,
                account_name=account_name,
                qty_change=qty_change,
                amount=amount,
                ledger_id=ledger_id,
                transaction=transaction,
            )

            if stock_entry:
                self.log_info(f"Created stock entry {stock_entry.name} for account {account_code}")
                return True
            else:
                self.log_error(f"Failed to create stock entry for account {account_code}")
                return False

        except Exception as e:
            # Use safe error logging
            from verenigingen.utils.error_log_fix import log_error_safely

            log_error_safely(
                message=f"Error processing stock transaction for {account_code}:\n{str(e)}",
                title="Stock Transaction: {account_code}",
            )
            return False

    def create_stock_entry(
        self, posting_date, purpose, account_code, account_name, qty_change, amount, ledger_id, transaction
    ):
        """Create ERPNext Stock Entry"""
        try:
            # Get company and warehouse
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

            if not company:
                self.log_error("No default company set in E-Boekhouden Settings")
                return None

            # Get or create a default warehouse for migrations
            warehouse = self.get_or_create_migration_warehouse(company)
            if not warehouse:
                self.log_error("Could not find or create migration warehouse")
                return None

            # Create a default item for stock adjustments if it doesn't exist
            item_code = self.get_or_create_migration_item(account_code, account_name)
            if not item_code:
                self.log_error(f"Could not create item for account {account_code}")
                return None

            # Create stock entry
            stock_entry = frappe.get_doc(
                {
                    "doctype": "Stock Entry",
                    "company": company,
                    "posting_date": posting_date,
                    "posting_time": "12:00:00",
                    "purpose": purpose,
                    "remarks": "Migrated from e-Boekhouden: Ledger {ledger_id} | Account: {account_code} - {account_name}",
                    "items": [],
                }
            )

            # Add stock entry item
            if purpose == "Material Receipt":
                # Stock increase - item comes into warehouse
                stock_entry.append(
                    "items",
                    {
                        "item_code": item_code,
                        "qty": abs(qty_change),
                        "basic_rate": 1.0,  # Default rate - adjust as needed
                        "amount": abs(amount),
                        "t_warehouse": warehouse,
                        "cost_center": settings.default_cost_center,
                    },
                )
            elif purpose == "Material Issue":
                # Stock decrease - item goes out of warehouse
                stock_entry.append(
                    "items",
                    {
                        "item_code": item_code,
                        "qty": abs(qty_change),
                        "basic_rate": 1.0,  # Default rate - adjust as needed
                        "amount": abs(amount),
                        "s_warehouse": warehouse,
                        "cost_center": settings.default_cost_center,
                    },
                )
            else:
                # Stock adjustment
                stock_entry.append(
                    "items",
                    {
                        "item_code": item_code,
                        "qty": abs(qty_change),
                        "basic_rate": 1.0,
                        "amount": abs(amount),
                        "t_warehouse": warehouse if qty_change > 0 else None,
                        "s_warehouse": warehouse if qty_change < 0 else None,
                        "cost_center": settings.default_cost_center,
                    },
                )

            # Insert and submit the stock entry
            stock_entry.insert(ignore_permissions=True)

            # Note: Submitting stock entries requires items to be properly configured
            # For migration purposes, we'll leave them in draft state
            # stock_entry.submit()

            return stock_entry

        except Exception as e:
            # Extract clean error message
            error_msg = str(e)
            if "cannot be a fraction" in error_msg:
                # This is expected for monetary values
                from verenigingen.utils.error_log_fix import log_error_safely

                log_error_safely(
                    message=f"Stock entry requires whole number quantity, but got {qty_change}. "
                    "This is because E-Boekhouden stores monetary values, not physical quantities.\n"
                    "Account: {account_code} - {account_name}",
                    title="Stock Entry: Fractional Quantity",
                )
            else:
                from verenigingen.utils.error_log_fix import log_error_safely

                log_error_safely(
                    message=f"Error creating stock entry:\n{error_msg}", title="Stock Entry Creation Failed"
                )
            return None

    def get_or_create_migration_warehouse(self, company):
        """Get or create a warehouse for migration purposes"""
        try:
            # Use the fixed warehouse function that handles duplicates properly
            from verenigingen.utils.migration.stock_migration_warehouse_fix import (
                get_or_create_migration_warehouse_fixed,
            )

            return get_or_create_migration_warehouse_fixed(company)
        except ImportError:
            # Fallback to original logic with better duplicate handling
            pass

        # Try multiple patterns to find existing warehouse
        # Pattern 1: Check by warehouse_name and company
        existing = frappe.db.get_value(
            "Warehouse", {"warehouse_name": "e-Boekhouden Migration", "company": company}, "name"
        )

        if existing:
            return existing

        # Pattern 2: Check by name pattern (handles normalized company names)
        existing = frappe.db.sql(
            """
            SELECT name FROM `tabWarehouse`
            WHERE company = %s
            AND name LIKE %s
            LIMIT 1
        """,
            (company, "%e-Boekhouden Migration%"),
        )

        if existing:
            return existing[0][0]

        try:
            # Create new warehouse
            warehouse = frappe.get_doc(
                {
                    "doctype": "Warehouse",
                    "warehouse_name": "e-Boekhouden Migration",
                    "company": company,
                    "warehouse_type": "Transit",
                    "is_group": 0,
                }
            )
            warehouse.insert(ignore_permissions=True)
            return warehouse.name

        except frappe.DuplicateEntryError as e:
            # If duplicate, it means it exists but we couldn't find it
            # Try one more time with a broader search
            any_warehouse = frappe.db.sql(
                """
                SELECT name FROM `tabWarehouse`
                WHERE company = %s
                AND (name LIKE %s OR warehouse_name LIKE %s)
                LIMIT 1
            """,
                (company, "%Boekhouden%", "%Boekhouden%"),
            )

            if any_warehouse:
                return any_warehouse[0][0]

            # Use error_log_fix for clean logging
            from verenigingen.utils.error_log_fix import log_error_safely

            log_error_safely(
                message=f"Duplicate warehouse error: {str(e)}\n{frappe.get_traceback()}",
                title="Migration Warehouse: Duplicate",
            )
            return None

        except Exception as e:
            from verenigingen.utils.error_log_fix import log_error_safely

            log_error_safely(
                message=f"Error creating warehouse: {str(e)}\n{frappe.get_traceback()}",
                title="Migration Warehouse: Creation Failed",
            )
            return None

    def get_or_create_migration_item(self, account_code, account_name):
        """Get or create an item for stock transactions"""
        item_code = "MIGR-{account_code}"

        if frappe.db.exists("Item", item_code):
            return item_code

        try:
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": "Migration Item - {account_name}",
                    "item_group": self.get_or_create_migration_item_group(),
                    "stock_uom": "Nos",
                    "is_stock_item": 1,
                    "include_item_in_manufacturing": 0,
                    "description": "Migration item for e-Boekhouden account {account_code} - {account_name}",
                    "valuation_method": "FIFO",
                }
            )
            item.insert(ignore_permissions=True)
            return item.item_code

        except Exception as e:
            self.log_error(f"Error creating migration item: {str(e)}")
            return None

    def get_or_create_migration_item_group(self):
        """Get or create item group for migration items"""
        group_name = "e-Boekhouden Migration"

        if frappe.db.exists("Item Group", group_name):
            return group_name

        try:
            item_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": group_name,
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            )
            item_group.insert(ignore_permissions=True)
            return item_group.name

        except Exception as e:
            self.log_error(f"Error creating migration item group: {str(e)}")
            return "All Item Groups"  # Fallback

    def log_info(self, message):
        """Log info message"""
        frappe.log_error(message, "Stock Migration Info")
        if hasattr(self.migration_doc, "current_operation"):
            self.migration_doc.current_operation = message
            self.migration_doc.save()

    def log_error(self, message):
        """Log error message"""
        frappe.log_error(message, "Stock Migration Error")
        self.error_log.append(message)
        if hasattr(self.migration_doc, "error_log"):
            if self.migration_doc.error_log:
                self.migration_doc.error_log += f"\n{message}"
            else:
                self.migration_doc.error_log = message


@frappe.whitelist()
def test_eboekhouden_product_data():
    """Test what product/inventory data is available from e-Boekhouden API"""
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        results = {}

        # Test invoice data for product information
        invoices_result = api.get_invoices({"limit": 10})
        if invoices_result["success"]:
            import json

            invoices_data = json.loads(invoices_result["data"])
            results["invoices_structure"] = {
                "total_invoices": len(invoices_data.get("items", [])),
                "sample_data": invoices_data,
            }

            # Look for product-related fields in invoices
            if invoices_data.get("items"):
                for invoice in invoices_data["items"][:3]:
                    product_fields = {}
                    for key, value in invoice.items():
                        if any(
                            keyword in key.lower()
                            for keyword in ["product", "item", "inventory", "stock", "quantity", "unit"]
                        ):
                            product_fields[key] = value

                    if product_fields:
                        if "product_fields_found" not in results:
                            results["product_fields_found"] = []
                        results["product_fields_found"].append(
                            {"invoice_id": invoice.get("id"), "product_fields": product_fields}
                        )

        # Test mutations for quantity/inventory information
        mutations_result = api.get_mutations({"limit": 10})
        if mutations_result["success"]:
            import json

            mutations_data = json.loads(mutations_result["data"])
            results["mutations_structure"] = {
                "total_mutations": len(mutations_data.get("items", [])),
                "sample_data": mutations_data,
            }

            # Look for inventory-related patterns in mutations
            if mutations_data.get("items"):
                for mutation in mutations_data["items"][:5]:
                    inventory_fields = {}
                    for key, value in mutation.items():
                        if any(
                            keyword in key.lower()
                            for keyword in ["quantity", "product", "item", "inventory", "stock", "unit"]
                        ):
                            inventory_fields[key] = value

                    if inventory_fields:
                        if "inventory_fields_found" not in results:
                            results["inventory_fields_found"] = []
                        results["inventory_fields_found"].append(
                            {
                                "mutation_id": mutation.get("id"),
                                "ledger_id": mutation.get("ledgerId"),
                                "inventory_fields": inventory_fields,
                            }
                        )

        return {"success": True, "results": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def migrate_stock_transactions_standalone(migration_name, date_from=None, date_to=None, dry_run=True):
    """Standalone function to migrate stock transactions"""
    try:
        # Get migration document or create a temporary one
        if frappe.db.exists("E-Boekhouden Migration", migration_name):
            migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)
        else:
            # Create temporary migration doc for standalone execution
            migration_doc = frappe._dict(
                {
                    "name": "temp-stock-migration",
                    "dry_run": dry_run,
                    "date_from": date_from,
                    "date_to": date_to,
                    "current_operation": "",
                    "error_log": "",
                }
            )

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.api_token:
            return {"success": False, "error": "E-Boekhouden Settings not configured"}

        # Create migrator and run migration
        migrator = StockTransactionMigrator(migration_doc)
        result = migrator.migrate_stock_transactions(settings, date_from, date_to)

        return {
            "success": True,
            "result": result,
            "created": migrator.stock_transactions_created,
            "failed": migrator.stock_transactions_failed,
            "skipped": migrator.stock_transactions_skipped,
            "error_log": migrator.error_log,
        }

    except Exception as e:
        frappe.log_error(f"Error in standalone stock migration: {str(e)}")
        return {"success": False, "error": str(e)}
