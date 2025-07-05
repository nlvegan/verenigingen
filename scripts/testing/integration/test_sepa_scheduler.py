#!/usr/bin/env python3
"""
Test script for SEPA mandate discrepancy checking scheduled task
"""

import os
import sys

# Add the app directory to Python path
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")

import frappe

from verenigingen.verenigingen.doctype.member.mixins.sepa_mixin import check_sepa_mandate_discrepancies


def main():
    """Test the SEPA mandate discrepancy checking function"""

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("Testing SEPA mandate discrepancy checking...")

    try:
        # Call the scheduled function
        results = check_sepa_mandate_discrepancies()

        if results and not results.get("error"):
            print(f"\n✅ Test completed successfully!")
            print(f"📊 Results:")
            print(f"   - Total members checked: {results['total_checked']}")
            print(f"   - Missing mandates: {len(results['missing_mandates'])}")
            print(f"   - IBAN mismatches: {len(results['iban_mismatches'])}")
            print(f"   - Name mismatches: {len(results['name_mismatches'])}")
            print(f"   - Auto-fixed issues: {len(results['auto_fixed'])}")
            print(f"   - Processing errors: {len(results['errors'])}")

            # Show some details if there are issues
            if results["missing_mandates"]:
                print(f"\n⚠️  Members missing SEPA mandates:")
                for item in results["missing_mandates"][:5]:  # Show first 5
                    print(f"   - {item['member_name']} ({item['member']})")
                if len(results["missing_mandates"]) > 5:
                    print(f"   ... and {len(results['missing_mandates']) - 5} more")

            if results["auto_fixed"]:
                print(f"\n🔧 Auto-fixed issues:")
                for item in results["auto_fixed"][:5]:  # Show first 5
                    print(f"   - {item['member_name']}: {item['action']} ({item['reason']})")
                if len(results["auto_fixed"]) > 5:
                    print(f"   ... and {len(results['auto_fixed']) - 5} more")

        else:
            print(f"❌ Test failed with error: {results.get('error', 'Unknown error')}")

    except Exception as e:
        print(f"❌ Test failed with exception: {str(e)}")
        import traceback

        traceback.print_exc()

    finally:
        frappe.db.close()


if __name__ == "__main__":
    main()
