"""
Manual Testing Script for Balance Transaction Processing

This script provides easy-to-use commands for testing the balance transaction processing
workflow. Unlike settlement processing (90-day limit), this provides unlimited historical access.

Usage:
    bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_recent_transactions --args "[30]"
    bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_date_range --args "['2024-01-01', '2024-12-31']"
    bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_historical_migration --args "[12]"
    bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.check_transaction_status --args "['baltr_QM24bwP3Ur']"
    bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_balance_info
    bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_statistics --args "[30]"
    bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_configuration
"""

import json
from datetime import datetime, timedelta
from typing import Optional

import frappe
from frappe.utils import cstr

from verenigingen.verenigingen_payments.services.balance_transaction_processor import (
    BalanceTransactionProcessor,
)


def test_recent_transactions(days: int = 30, limit: int = 250):
    """
    Test processing balance transactions from recent days.

    Args:
        days: Number of days to look back (default: 30)
        limit: Maximum transactions to process (default: 250)

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_recent_transactions --args "[30]"
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_recent_transactions --args "[90, 500]"
    """
    print("\n" + "=" * 80)
    print(f"Testing Balance Transaction Processing (last {days} days, limit: {limit})")
    print("=" * 80 + "\n")

    try:
        processor = BalanceTransactionProcessor()
        balance_id = processor.get_primary_balance_id()

        print(f"Primary Balance ID: {balance_id}")

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        print(f"Date Range: {start_date.date()} to {end_date.date()}")
        print()

        result = processor.process_balance_transactions(
            balance_id=balance_id,
            from_date=start_date,
            until_date=end_date,
            limit=limit,
        )

        print("Processing Summary:")
        print(f"Total Transactions Found: {result.get('total_transactions')}")
        print(f"✅ Successfully Processed: {result.get('processed')}")
        print(f"⚠️  Already Processed: {result.get('already_processed')}")
        print(f"❌ Errors: {result.get('errors')}")

        if result.get("results"):
            print(f"\nDetailed Results ({len(result['results'])} items):")
            for idx, item in enumerate(result.get("results", []), 1):
                status_icon = (
                    "✅"
                    if item.get("status") == "success"
                    else "⚠️" if item.get("status") == "already_processed" else "❌"
                )
                print(
                    f"\n{idx}. {status_icon} Transaction: {item.get('transaction_id')} - {item.get('status')}"
                )
                if item.get("bank_transaction"):
                    print(f"   Bank Transaction: {item.get('bank_transaction')}")
                if item.get("amount"):
                    print(f"   Amount: {item.get('amount')}")
                if item.get("transaction_type"):
                    print(f"   Type: {item.get('transaction_type')}")
                if item.get("payment_id"):
                    print(f"   Payment: {item.get('payment_id')}")
                if item.get("settlement_id"):
                    print(f"   Settlement: {item.get('settlement_id')}")
                if item.get("error"):
                    print(f"   Error: {item.get('error')}")

        print("\n✅ Test completed!")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        import traceback

        traceback.print_exc()
        frappe.log_error(f"Test error: {str(e)}", "Balance Transaction Testing Error")


def test_date_range(from_date: str, until_date: str, limit: int = 250):
    """
    Test processing balance transactions for a specific date range.

    Args:
        from_date: Start date (YYYY-MM-DD)
        until_date: End date (YYYY-MM-DD)
        limit: Maximum transactions to process (default: 250)

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_date_range --args "['2024-01-01', '2024-12-31']"
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_date_range --args "['2023-01-01', '2023-12-31', 500]"
    """
    print("\n" + "=" * 80)
    print(f"Testing Balance Transaction Processing for Date Range")
    print(f"From: {from_date} To: {until_date} (Limit: {limit})")
    print("=" * 80 + "\n")

    try:
        processor = BalanceTransactionProcessor()
        balance_id = processor.get_primary_balance_id()

        print(f"Primary Balance ID: {balance_id}")
        print()

        # Parse dates
        from_date_obj = datetime.fromisoformat(from_date)
        until_date_obj = datetime.fromisoformat(until_date)

        result = processor.process_balance_transactions(
            balance_id=balance_id,
            from_date=from_date_obj,
            until_date=until_date_obj,
            limit=limit,
        )

        print("Processing Summary:")
        print(f"Total Transactions Found: {result.get('total_transactions')}")
        print(f"✅ Successfully Processed: {result.get('processed')}")
        print(f"⚠️  Already Processed: {result.get('already_processed')}")
        print(f"❌ Errors: {result.get('errors')}")

        if result.get("results"):
            print(f"\nShowing first 10 results (out of {len(result['results'])} total):")
            for idx, item in enumerate(result.get("results", [])[:10], 1):
                status_icon = (
                    "✅"
                    if item.get("status") == "success"
                    else "⚠️" if item.get("status") == "already_processed" else "❌"
                )
                print(
                    f"{idx}. {status_icon} {item.get('transaction_id')} - {item.get('transaction_type')} - {item.get('amount')}"
                )

        print("\n✅ Test completed!")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        import traceback

        traceback.print_exc()
        frappe.log_error(f"Test error: {str(e)}", "Balance Transaction Testing Error")


def test_historical_migration(months_back: int = 12, batch_size: int = 250):
    """
    Test historical data migration in batches.

    This processes balance transactions going back multiple months,
    useful for initial data migration or catching up on old data.

    Args:
        months_back: Number of months to look back (default: 12)
        batch_size: Transactions per batch (default: 250)

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_historical_migration --args "[12]"
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_historical_migration --args "[24, 500]"
    """
    print("\n" + "=" * 80)
    print(f"Testing Historical Balance Transaction Migration")
    print(f"Processing last {months_back} months in batches of {batch_size}")
    print("=" * 80 + "\n")

    try:
        processor = BalanceTransactionProcessor()

        result = processor.process_historical_data(
            months_back=months_back, batch_size=batch_size
        )

        print("Overall Migration Summary:")
        print(f"Total Batches Processed: {len(result.get('batches', []))}")
        print(f"✅ Total Successfully Processed: {result.get('total_processed')}")
        print(f"⚠️  Total Already Processed: {result.get('total_already_processed')}")
        print(f"❌ Total Errors: {result.get('total_errors')}")

        if result.get("batches"):
            print(f"\nBatch Details:")
            for batch in result.get("batches", []):
                batch_num = batch.get("batch_number")
                batch_result = batch.get("result", {})
                print(f"\nBatch {batch_num}:")
                print(f"  Period: {batch.get('from_date')} to {batch.get('to_date')}")
                print(f"  Transactions: {batch_result.get('total_transactions')}")
                print(f"  Processed: {batch_result.get('processed')}")
                print(f"  Already Processed: {batch_result.get('already_processed')}")
                print(f"  Errors: {batch_result.get('errors')}")

        if result.get("error"):
            print(f"\n❌ Migration Error: {result.get('error')}")
        else:
            print("\n✅ Historical migration completed!")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        import traceback

        traceback.print_exc()
        frappe.log_error(f"Test error: {str(e)}", "Historical Migration Testing Error")


def check_transaction_status(transaction_id: str):
    """
    Check if a balance transaction has already been processed.

    Args:
        transaction_id: Mollie balance transaction ID

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.check_transaction_status --args "['baltr_QM24bwP3Ur']"
    """
    print("\n" + "=" * 80)
    print(f"Checking Balance Transaction Status: {transaction_id}")
    print("=" * 80 + "\n")

    try:
        # Check in ERPNext database
        existing_bt = frappe.db.get_value(
            "Bank Transaction",
            {"reference_number": transaction_id},
            ["name", "date", "deposit", "withdrawal", "status", "description"],
            as_dict=True,
        )

        if existing_bt:
            print("✅ Balance Transaction Already Processed")
            print(f"Bank Transaction: {existing_bt.name}")
            print(f"Date: {existing_bt.date}")
            print(f"Deposit: {existing_bt.deposit}")
            print(f"Withdrawal: {existing_bt.withdrawal}")
            print(f"Status: {existing_bt.status}")
            print(f"Description: {existing_bt.description}")
        else:
            print("⚠️  Balance Transaction NOT Processed Yet")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Transaction Status Check Error")


def show_balance_info():
    """
    Display information about the primary Mollie balance.

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_balance_info
    """
    print("\n" + "=" * 80)
    print("Primary Mollie Balance Information")
    print("=" * 80 + "\n")

    try:
        processor = BalanceTransactionProcessor()
        primary_balance = processor.balances_client.get_primary_balance()

        print(f"Balance ID: {primary_balance.id}")
        print(f"Currency: {primary_balance.currency}")
        print(f"Status: {primary_balance.status}")

        if primary_balance.available_amount:
            print(
                f"Available Amount: {primary_balance.currency} {primary_balance.available_amount.decimal_value}"
            )

        if primary_balance.pending_amount:
            print(
                f"Pending Amount: {primary_balance.currency} {primary_balance.pending_amount.decimal_value}"
            )

        print(f"Created At: {primary_balance.created_at}")

        print("\n✅ Balance info retrieved successfully!")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Balance Info Error")


def show_statistics(days: int = 30):
    """
    Display processing statistics for balance transactions.

    Args:
        days: Number of days to look back (default: 30)

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_statistics --args "[30]"
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_statistics --args "[90]"
    """
    from frappe.utils import getdate, now_datetime

    print("\n" + "=" * 80)
    print(f"Balance Transaction Processing Statistics (last {days} days)")
    print("=" * 80 + "\n")

    try:
        # Calculate date range
        end_date = now_datetime()
        start_date = end_date - timedelta(days=days)

        print(f"Period: {start_date.date()} to {end_date.date()}\n")

        # Count Bank Transactions from balance transactions
        # Balance transaction IDs start with 'baltr_'
        total_processed = frappe.db.count(
            "Bank Transaction",
            filters={
                "reference_number": ["like", "baltr_%"],
                "date": ["between", [getdate(start_date), getdate(end_date)]],
            },
        )

        reconciled = frappe.db.count(
            "Bank Transaction",
            filters={
                "reference_number": ["like", "baltr_%"],
                "date": ["between", [getdate(start_date), getdate(end_date)]],
                "status": "Reconciled",
            },
        )

        unreconciled = frappe.db.count(
            "Bank Transaction",
            filters={
                "reference_number": ["like", "baltr_%"],
                "date": ["between", [getdate(start_date), getdate(end_date)]],
                "status": "Unreconciled",
            },
        )

        # Get amounts
        amounts = frappe.db.sql(
            """
            SELECT
                SUM(deposit) as total_deposits,
                SUM(withdrawal) as total_withdrawals
            FROM `tabBank Transaction`
            WHERE reference_number LIKE 'baltr_%'
                AND date BETWEEN %s AND %s
        """,
            (getdate(start_date), getdate(end_date)),
            as_dict=True,
        )

        amount_data = amounts[0] if amounts else {}

        print("Transaction Counts:")
        print(f"  Total Processed: {total_processed}")
        print(f"  Reconciled: {reconciled}")
        print(f"  Unreconciled: {unreconciled}")

        if total_processed > 0:
            print(
                f"  Reconciliation Rate: {round(reconciled / total_processed * 100, 2)}%"
            )

        print("\nAmounts:")
        print(f"  Total Deposits: EUR {amount_data.get('total_deposits') or 0:.2f}")
        print(
            f"  Total Withdrawals: EUR {amount_data.get('total_withdrawals') or 0:.2f}"
        )

        # Show recent transactions
        recent_transactions = frappe.db.get_all(
            "Bank Transaction",
            filters={
                "reference_number": ["like", "baltr_%"],
                "date": ["between", [getdate(start_date), getdate(end_date)]],
            },
            fields=["name", "date", "deposit", "withdrawal", "status", "description"],
            order_by="date desc",
            limit=10,
        )

        if recent_transactions:
            print(f"\nRecent Transactions (showing last 10):")
            for idx, tx in enumerate(recent_transactions, 1):
                amount = tx.deposit or tx.withdrawal
                direction = "↓" if tx.deposit else "↑"
                print(
                    f"{idx}. {direction} {tx.name} - {tx.date} - EUR {amount:.2f} - {tx.status}"
                )

        print("\n✅ Statistics retrieved successfully!")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Statistics Error")


def show_configuration():
    """
    Display current Mollie and ERPNext configuration for balance transaction processing.

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_configuration
    """
    print("\n" + "=" * 80)
    print("Balance Transaction Processing Configuration")
    print("=" * 80 + "\n")

    try:
        # Mollie Settings
        mollie_settings = frappe.get_single("Mollie Settings")

        print("Mollie Settings:")
        print(f"  Backend API Enabled: {mollie_settings.enable_backend_api}")
        print(f"  Organization ID: {mollie_settings.organization_id or '(auto-discover)'}")
        print(
            f"  Organization Access Token: {'*' * 20 if mollie_settings.organization_access_token else '(not set)'}"
        )
        print(f"  Mollie Bank Account: {mollie_settings.mollie_bank_account or '(not set)'}")
        print()

        # Verenigingen Settings
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        company = verenigingen_settings.donation_company or frappe.defaults.get_global_default(
            "company"
        )

        print("Verenigingen Settings:")
        print(f"  Donation Company: {company}")
        print()

        # Validation
        print("Configuration Validation:")

        if not mollie_settings.enable_backend_api:
            print("  ⚠️  Backend API is DISABLED - enable it in Mollie Settings")
        else:
            print("  ✅ Backend API is enabled")

        if not mollie_settings.organization_access_token:
            print(
                "  ⚠️  Organization Access Token not set - required for balance API access"
            )
        else:
            print("  ✅ Organization Access Token is configured")

        if not mollie_settings.mollie_bank_account:
            print(
                "  ⚠️  Mollie Bank Account not configured - where should transactions be recorded?"
            )
        else:
            # Check if Bank Account exists
            bank_account = frappe.db.get_value(
                "Bank Account", {"account": mollie_settings.mollie_bank_account}, "name"
            )
            if bank_account:
                print(f"  ✅ Mollie Bank Account configured: {bank_account}")
            else:
                print(
                    f"  ⚠️  No Bank Account found linked to GL Account '{mollie_settings.mollie_bank_account}'"
                )

        if not company:
            print("  ⚠️  No company configured for transaction processing")
        else:
            print(f"  ✅ Company configured: {company}")

        # Get balance info
        print("\nBalance Information:")
        try:
            processor = BalanceTransactionProcessor()
            balance_id = processor.get_primary_balance_id()
            print(f"  ✅ Primary Balance ID: {balance_id}")
        except Exception as e:
            print(f"  ⚠️  Could not retrieve primary balance: {str(e)}")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Configuration Display Error")


def show_usage():
    """
    Display usage instructions for all available test commands.

    Example:
        bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_usage
    """
    print("\n" + "=" * 80)
    print("Balance Transaction Processing Manual Testing Commands")
    print("=" * 80 + "\n")

    commands = [
        {
            "name": "Show Configuration",
            "command": "bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_configuration",
            "description": "Display current Mollie and ERPNext configuration",
        },
        {
            "name": "Show Balance Info",
            "command": "bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_balance_info",
            "description": "Display primary Mollie balance information",
        },
        {
            "name": "Show Statistics",
            "command": 'bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.show_statistics --args "[30]"',
            "description": "Show processing statistics for last 30 days",
        },
        {
            "name": "Check Transaction Status",
            "command": "bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.check_transaction_status --args \"['baltr_QM24bwP3Ur']\"",
            "description": "Check if a specific transaction has been processed",
        },
        {
            "name": "Process Recent Transactions",
            "command": 'bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_recent_transactions --args "[30]"',
            "description": "Process transactions from last 30 days (change number for different period)",
        },
        {
            "name": "Process Specific Date Range",
            "command": "bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_date_range --args \"['2024-01-01', '2024-12-31']\"",
            "description": "Process transactions for a specific date range (NO TIME LIMIT!)",
        },
        {
            "name": "Historical Data Migration",
            "command": 'bench --site dev.veganisme.net execute scripts.test_balance_transaction_processing.test_historical_migration --args "[12]"',
            "description": "Process historical data in batches (12 months back in this example)",
        },
    ]

    for idx, cmd in enumerate(commands, 1):
        print(f"{idx}. {cmd['name']}")
        print(f"   Description: {cmd['description']}")
        print(f"   Command: {cmd['command']}")
        print()

    print("=" * 80)
    print("TIP: Always start with 'show_configuration' to verify your setup!")
    print("=" * 80)
    print("\nKEY ADVANTAGE: Balance transactions have NO 90-day limit like settlements!")
    print("You can process transactions from ANY date in the past.")
    print("=" * 80 + "\n")
