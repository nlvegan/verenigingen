"""
Manual Testing Script for Settlement Bank Transaction Processing

This script provides easy-to-use commands for testing the settlement processing
workflow without needing to schedule automatic jobs.

Usage:
    bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_single_settlement --args "['stl_jDk30akdN']"
    bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_by_bank_reference --args "['1234.5678.90']"
    bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_batch_processing --args "[7]"
    bench --site dev.veganisme.net execute scripts.test_settlement_processing.check_settlement_status --args "['stl_jDk30akdN']"
    bench --site dev.veganisme.net execute scripts.test_settlement_processing.list_recent_settlements --args "[7]"
    bench --site dev.veganisme.net execute scripts.test_settlement_processing.show_configuration
"""

import json
from typing import Optional

import frappe
from frappe.utils import cstr

from verenigingen.verenigingen_payments.services.settlement_bank_transaction_processor import (
    SettlementBankTransactionProcessor,
)


def test_single_settlement(settlement_id: str):
    """
    Test processing a single settlement by Mollie settlement ID.

    Args:
        settlement_id: Mollie settlement ID (e.g., "stl_jDk30akdN")

    Example:
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_single_settlement --args "['stl_jDk30akdN']"
    """
    print("\n" + "=" * 80)
    print(f"Testing Settlement Processing by Settlement ID: {settlement_id}")
    print("=" * 80 + "\n")

    try:
        processor = SettlementBankTransactionProcessor()
        result = processor.process_settlement_deposit(settlement_id=settlement_id)

        print("Result:")
        print(json.dumps(result, indent=2, default=cstr))

        if result.get("status") == "success":
            print("\n✅ SUCCESS!")
            print(f"Created Bank Transaction: {result.get('bank_transaction')}")
            print(f"Settlement Reference: {result.get('settlement_reference')}")
            print(f"Amount: {result.get('currency')} {result.get('amount')}")
            print(f"Linked Payment Entries: {result.get('linked_payment_entries')}")
        elif result.get("status") == "already_processed":
            print("\n⚠️  ALREADY PROCESSED")
            print(f"Existing Bank Transaction: {result.get('bank_transaction')}")
        else:
            print("\n❌ ERROR")
            print(f"Error: {result.get('error')}")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Settlement Testing Error")


def test_by_bank_reference(bank_reference: str):
    """
    Test processing a settlement by bank reference from your bank statement.

    Args:
        bank_reference: Bank reference (e.g., "1234.5678.90")

    Example:
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_by_bank_reference --args "['1234.5678.90']"
    """
    print("\n" + "=" * 80)
    print(f"Testing Settlement Processing by Bank Reference: {bank_reference}")
    print("=" * 80 + "\n")

    try:
        processor = SettlementBankTransactionProcessor()
        result = processor.process_settlement_deposit(bank_reference=bank_reference)

        print("Result:")
        print(json.dumps(result, indent=2, default=cstr))

        if result.get("status") == "success":
            print("\n✅ SUCCESS!")
            print(f"Settlement ID: {result.get('settlement_id')}")
            print(f"Created Bank Transaction: {result.get('bank_transaction')}")
            print(f"Amount: {result.get('currency')} {result.get('amount')}")
            print(f"Linked Payment Entries: {result.get('linked_payment_entries')}")
        elif result.get("status") == "already_processed":
            print("\n⚠️  ALREADY PROCESSED")
            print(f"Settlement ID: {result.get('settlement_id')}")
            print(f"Existing Bank Transaction: {result.get('bank_transaction')}")
        else:
            print("\n❌ ERROR")
            print(f"Error: {result.get('error')}")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Settlement Testing Error")


def test_batch_processing(days: int = 7):
    """
    Test batch processing of recent settlements.

    Args:
        days: Number of days to look back (default: 7)

    Example:
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_batch_processing --args "[7]"
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_batch_processing --args "[30]"
    """
    print("\n" + "=" * 80)
    print(f"Testing Batch Settlement Processing (last {days} days)")
    print("=" * 80 + "\n")

    try:
        processor = SettlementBankTransactionProcessor()
        result = processor.batch_process_recent_settlements(days=days)

        print("Batch Processing Summary:")
        print(f"Total Settlements Found: {result.get('total_settlements')}")
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
                    f"\n{idx}. {status_icon} Settlement: {item.get('settlement_id')} - {item.get('status')}"
                )
                if item.get("bank_transaction"):
                    print(f"   Bank Transaction: {item.get('bank_transaction')}")
                if item.get("amount"):
                    print(f"   Amount: {item.get('currency')} {item.get('amount')}")
                if item.get("error"):
                    print(f"   Error: {item.get('error')}")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Settlement Batch Testing Error")


def check_settlement_status(settlement_id: str):
    """
    Check if a settlement has already been processed.

    Args:
        settlement_id: Mollie settlement ID

    Example:
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.check_settlement_status --args "['stl_jDk30akdN']"
    """
    print("\n" + "=" * 80)
    print(f"Checking Settlement Status: {settlement_id}")
    print("=" * 80 + "\n")

    try:
        # Check in ERPNext database
        existing_bt = frappe.db.get_value(
            "Bank Transaction",
            {"reference_number": settlement_id},
            ["name", "date", "deposit", "status"],
            as_dict=True,
        )

        if existing_bt:
            print("✅ Settlement Already Processed")
            print(f"Bank Transaction: {existing_bt.name}")
            print(f"Date: {existing_bt.date}")
            print(f"Amount: {existing_bt.deposit}")
            print(f"Status: {existing_bt.status}")
        else:
            print("⚠️  Settlement NOT Processed Yet")

        # Try to get info from Mollie API
        print("\nFetching settlement details from Mollie API...")
        processor = SettlementBankTransactionProcessor()
        settlement = processor.settlements_client.get_settlement(settlement_id)

        print(f"\nMollie Settlement Details:")
        print(f"Reference: {settlement.reference}")
        print(f"Status: {settlement.status}")
        print(
            f"Amount: {settlement.amount.currency} {settlement.amount.decimal_value if settlement.amount else 0.0}"
        )
        print(f"Settled At: {settlement.settled_at}")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Settlement Status Check Error")


def list_recent_settlements(days: int = 7):
    """
    List all recent settlements from Mollie API.

    Args:
        days: Number of days to look back (default: 7)

    Example:
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.list_recent_settlements --args "[7]"
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.list_recent_settlements --args "[30]"
    """
    from datetime import datetime, timedelta

    print("\n" + "=" * 80)
    print(f"Listing Recent Settlements (last {days} days)")
    print("=" * 80 + "\n")

    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        processor = SettlementBankTransactionProcessor()
        settlements = processor.settlements_client.list_settlements(
            from_date=start_date, until_date=end_date
        )

        print(f"Found {len(settlements)} settlements\n")

        for idx, settlement in enumerate(settlements, 1):
            # Check if already processed
            existing_bt = frappe.db.get_value(
                "Bank Transaction", {"reference_number": settlement.id}, "name"
            )

            status_icon = "✅" if existing_bt else "⚠️"
            processed_text = f"(Processed: {existing_bt})" if existing_bt else "(Not Processed)"

            print(f"{idx}. {status_icon} {settlement.id}")
            print(f"   Reference: {settlement.reference}")
            print(f"   Status: {settlement.status}")
            print(
                f"   Amount: {settlement.amount.currency} {settlement.amount.decimal_value if settlement.amount else 0.0}"
            )
            print(f"   Settled At: {settlement.settled_at}")
            print(f"   {processed_text}")
            print()

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Settlement Listing Error")


def show_configuration():
    """
    Display current Mollie and ERPNext configuration for settlement processing.

    Example:
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.show_configuration
    """
    print("\n" + "=" * 80)
    print("Settlement Processing Configuration")
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
        print(
            f"  Mollie Clearing Account: {mollie_settings.mollie_clearing_account or '(not set)'}"
        )
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
                "  ⚠️  Organization Access Token not set - required for settlement API access"
            )
        else:
            print("  ✅ Organization Access Token is configured")

        if not mollie_settings.mollie_bank_account:
            print(
                "  ⚠️  Mollie Bank Account not configured - where should settlement deposits be recorded?"
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
            print("  ⚠️  No company configured for settlement processing")
        else:
            print(f"  ✅ Company configured: {company}")

    except Exception as e:
        print(f"\n❌ EXCEPTION: {str(e)}")
        frappe.log_error(f"Test error: {str(e)}", "Configuration Display Error")


def show_usage():
    """
    Display usage instructions for all available test commands.

    Example:
        bench --site dev.veganisme.net execute scripts.test_settlement_processing.show_usage
    """
    print("\n" + "=" * 80)
    print("Settlement Processing Manual Testing Commands")
    print("=" * 80 + "\n")

    commands = [
        {
            "name": "Show Configuration",
            "command": "bench --site dev.veganisme.net execute scripts.test_settlement_processing.show_configuration",
            "description": "Display current Mollie and ERPNext configuration",
        },
        {
            "name": "List Recent Settlements",
            "command": "bench --site dev.veganisme.net execute scripts.test_settlement_processing.list_recent_settlements --args \"[7]\"",
            "description": "List all settlements from last 7 days (change number for different period)",
        },
        {
            "name": "Check Settlement Status",
            "command": "bench --site dev.veganisme.net execute scripts.test_settlement_processing.check_settlement_status --args \"['stl_jDk30akdN']\"",
            "description": "Check if a specific settlement has been processed",
        },
        {
            "name": "Process Single Settlement (by ID)",
            "command": "bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_single_settlement --args \"['stl_jDk30akdN']\"",
            "description": "Process one settlement using Mollie settlement ID",
        },
        {
            "name": "Process Single Settlement (by Bank Reference)",
            "command": "bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_by_bank_reference --args \"['1234.5678.90']\"",
            "description": "Process one settlement using bank reference from your statement",
        },
        {
            "name": "Batch Process Recent Settlements",
            "command": "bench --site dev.veganisme.net execute scripts.test_settlement_processing.test_batch_processing --args \"[7]\"",
            "description": "Process all settlements from last 7 days (change number for different period)",
        },
    ]

    for idx, cmd in enumerate(commands, 1):
        print(f"{idx}. {cmd['name']}")
        print(f"   Description: {cmd['description']}")
        print(f"   Command: {cmd['command']}")
        print()

    print("=" * 80)
    print("TIP: Always start with 'show_configuration' to verify your setup!")
    print("=" * 80 + "\n")
