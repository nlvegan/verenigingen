"""
Fixed Stock Migration for E-Boekhouden

This version properly handles stock transactions without using monetary amounts as quantities
"""


import frappe


class StockMigrationFixed:
    """
    Fixed stock migration that properly handles E-Boekhouden stock data

    Key changes:
    1. Doesn't use monetary amounts as quantities
    2. Skips stock transactions if no proper quantity data
    3. Better error handling
    """

    def __init__(self, migration_doc=None):
        self.migration_doc = migration_doc
        self.processed_count = 0
        self.skipped_count = 0
        self.error_count = 0
        self.messages = []

    def migrate_stock_transactions(self, from_date=None, to_date=None):
        """
        Migrate stock transactions from E-Boekhouden

        Note: E-Boekhouden typically doesn't have proper inventory quantities,
        only monetary values. This migration will:
        1. Identify stock-related accounts
        2. Skip them with a proper message
        3. Suggest manual stock adjustment if needed
        """
        try:
            from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

            # Get stock accounts from E-Boekhouden
            api = EBoekhoudenAPI()

            # Get chart of accounts
            accounts_result = api.get_chart_of_accounts()
            if not accounts_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to fetch accounts",
                    "message": "Could not retrieve chart of accounts from E-Boekhouden",
                }

            import json

            accounts_data = json.loads(accounts_result["data"])
            accounts = accounts_data.get("items", [])

            # Identify stock accounts (typically 30xx in Dutch accounting)
            stock_accounts = []
            for account in accounts:
                code = account.get("code", "")
                name = account.get("description", "")

                # Stock accounts typically start with 30
                if code.startswith("30"):
                    stock_accounts.append({"code": code, "name": name, "id": account.get("id")})

            if not stock_accounts:
                return {
                    "success": True,
                    "message": "No stock accounts found in E-Boekhouden",
                    "processed": 0,
                    "skipped": 0,
                }

            # Get transactions for stock accounts
            if not from_date or not to_date:
                return {"success": False, "error": "Date range required for stock migration"}

            params = {"dateFrom": from_date, "dateTo": to_date}

            mutations_result = api.get_mutations(params)
            if not mutations_result["success"]:
                return {"success": False, "error": "Failed to fetch transactions"}

            mutations_data = json.loads(mutations_result["data"])
            all_mutations = mutations_data.get("items", [])

            # Filter for stock account transactions
            stock_mutations = []
            stock_account_ids = [str(acc["id"]) for acc in stock_accounts]

            for mutation in all_mutations:
                ledger_id = str(mutation.get("ledgerId", ""))
                if ledger_id in stock_account_ids:
                    stock_mutations.append(mutation)

            # Analyze stock mutations
            summary = self._analyze_stock_mutations(stock_mutations, stock_accounts)

            # Create summary message
            message_parts = [
                "Found {len(stock_mutations)} stock-related transactions in E-Boekhouden.",
                "",
                "Stock Account Summary:",
            ]

            for acc_summary in summary["account_summaries"]:
                message_parts.append(
                    "- {acc_summary['code']} {acc_summary['name']}: "
                    "€{acc_summary['total_amount']:.2f} ({acc_summary['transaction_count']} transactions)"
                )

            message_parts.extend(
                [
                    "",
                    "Note: E-Boekhouden transactions contain monetary values, not physical quantities.",
                    "Stock entries require actual quantities (pieces, kg, etc.).",
                    "",
                    "Recommendation:",
                    "1. Use Opening Stock tool in ERPNext to set initial stock levels",
                    "2. Or create manual Stock Reconciliation entries",
                    "3. Ensure proper Item master data with UOM settings",
                ]
            )

            return {
                "success": True,
                "message": "\n".join(message_parts),
                "processed": 0,
                "skipped": len(stock_mutations),
                "stock_accounts": stock_accounts,
                "summary": summary,
            }

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()

            # Log error properly without truncation
            frappe.log_error(
                title="Stock Migration Error", message=f"Error in stock migration:\n{error_details}"
            )

            return {
                "success": False,
                "error": str(e),
                "message": "Stock migration failed. Check error log for details.",
            }

    def _analyze_stock_mutations(self, mutations, stock_accounts):
        """Analyze stock mutations to provide summary"""
        account_summary = {}

        # Create lookup for account info
        account_lookup = {str(acc["id"]): acc for acc in stock_accounts}

        for mutation in mutations:
            ledger_id = str(mutation.get("ledgerId", ""))
            amount = float(mutation.get("amount", 0))

            if ledger_id not in account_summary:
                acc_info = account_lookup.get(ledger_id, {})
                account_summary[ledger_id] = {
                    "code": acc_info.get("code", ""),
                    "name": acc_info.get("name", ""),
                    "total_amount": 0,
                    "transaction_count": 0,
                    "debit_amount": 0,
                    "credit_amount": 0,
                }

            account_summary[ledger_id]["total_amount"] += amount
            account_summary[ledger_id]["transaction_count"] += 1

            if amount > 0:
                account_summary[ledger_id]["debit_amount"] += amount
            else:
                account_summary[ledger_id]["credit_amount"] += abs(amount)

        return {"total_mutations": len(mutations), "account_summaries": list(account_summary.values())}


def migrate_stock_transactions_safe(migration_doc, from_date=None, to_date=None):
    """
    Safe wrapper for stock migration that handles E-Boekhouden limitations
    """
    try:
        fixed_migration = StockMigrationFixed(migration_doc)
        result = fixed_migration.migrate_stock_transactions(from_date, to_date)

        # Update migration document with result
        if migration_doc:
            if result["success"]:
                message = result.get("message", "Stock migration completed")
                if result.get("skipped", 0) > 0:
                    message += (
                        f"\nSkipped {result['skipped']} stock transactions (no quantity data available)"
                    )
            else:
                message = f"Stock migration failed: {result.get('error', 'Unknown error')}"

            # Don't let the message get truncated
            if hasattr(migration_doc, "stock_migration_notes"):
                migration_doc.stock_migration_notes = message

            return message

        return result.get("message", "Stock migration completed")

    except Exception as e:
        error_msg = f"Error in stock migration: {str(e)}"
        frappe.log_error(title="Stock Migration Error", message=error_msg + "\n\n" + frappe.get_traceback())
        return error_msg
