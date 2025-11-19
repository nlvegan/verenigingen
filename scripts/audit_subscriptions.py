#!/usr/bin/env python3
"""
Quick script to audit Mollie subscriptions for data integrity issues.

Usage:
    bench --site dev.veganisme.net execute scripts.audit_subscriptions.audit
    bench --site dev.veganisme.net execute scripts.audit_subscriptions.audit --kwargs "{'auto_cancel': True}"
"""

import json
from verenigingen.utils.admin_utilities.subscription_audit import SubscriptionAudit


def audit(auto_cancel=False):
    """
    Run subscription audit and print results.

    Args:
        auto_cancel: If True, automatically cancel orphaned subscriptions
    """
    print("\n" + "="*80)
    print("MOLLIE SUBSCRIPTION AUDIT")
    print("="*80 + "\n")

    auditor = SubscriptionAudit()
    report = auditor.run_full_audit(auto_cancel_orphans=auto_cancel)

    # Print detailed findings
    print("\n" + "-"*80)
    print("ORPHANED SUBSCRIPTIONS (no matching member)")
    print("-"*80)
    if report["details"]["orphaned_subscriptions"]:
        for orphan in report["details"]["orphaned_subscriptions"]:
            print(f"\nSubscription ID: {orphan['subscription_id']}")
            print(f"  Customer ID: {orphan['customer_id']}")
            print(f"  Status: {orphan['status']}")
            print(f"  Amount: {orphan['amount']}")
            print(f"  Interval: {orphan['interval']}")
            print(f"  Description: {orphan['description']}")
            print(f"  Next Payment: {orphan['next_payment_date']}")
            if orphan.get('cancelled'):
                print(f"  ✓ CANCELLED")
    else:
        print("None found ✓")

    print("\n" + "-"*80)
    print("DELETED MEMBER SUBSCRIPTIONS")
    print("-"*80)
    if report["details"]["deleted_member_subscriptions"]:
        for deleted in report["details"]["deleted_member_subscriptions"]:
            print(f"\nSubscription ID: {deleted['subscription_id']}")
            print(f"  Deleted Member: {deleted['deleted_member']}")
            print(f"  Status: {deleted['status']}")
            print(f"  Amount: {deleted['amount']}")
            print(f"  Next Payment: {deleted['next_payment_date']}")
    else:
        print("None found ✓")

    print("\n" + "-"*80)
    print("STATUS MISMATCHES")
    print("-"*80)
    if report["details"]["status_mismatches"]:
        for mismatch in report["details"]["status_mismatches"]:
            print(f"\nMember: {mismatch.get('member_name', 'N/A')} ({mismatch.get('member_id', 'N/A')})")
            if mismatch.get('issue') == 'customer_id_mismatch':
                print(f"  Issue: Customer ID mismatch")
                print(f"  Mollie: {mismatch['mollie_customer_id']}")
                print(f"  Member: {mismatch['member_customer_id']}")
            else:
                print(f"  Mollie Status: {mismatch.get('mollie_status')}")
                print(f"  Member Status: {mismatch.get('member_status')}")
    else:
        print("None found ✓")

    print("\n" + "-"*80)
    print("MISSING MOLLIE DATA")
    print("-"*80)
    if report["details"]["missing_mollie_data"]:
        for missing in report["details"]["missing_mollie_data"]:
            print(f"\nMember: {missing['member_name']} ({missing['member_id']})")
            print(f"  Issue: {missing['issue']}")
            print(f"  Member Subscription Status: {missing['subscription_status']}")
            if missing.get('error'):
                print(f"  Error: {missing['error']}")
    else:
        print("None found ✓")

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total Mollie Subscriptions: {report['summary']['total_mollie_subscriptions']}")
    print(f"Active Mollie Subscriptions: {report['summary']['active_mollie_subscriptions']}")
    print(f"Orphaned Subscriptions: {report['summary']['orphaned_subscriptions']}")
    print(f"Deleted Member Subscriptions: {report['summary']['deleted_member_subscriptions']}")
    print(f"Status Mismatches: {report['summary']['status_mismatches']}")
    print(f"Missing Mollie Data: {report['summary']['missing_mollie_data']}")
    print(f"\nTest Mode: {report['test_mode']}")
    print(f"Audit Timestamp: {report['audit_timestamp']}")

    # Save detailed JSON report
    import frappe
    report_path = frappe.get_site_path("private", "files", "subscription_audit_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nDetailed JSON report saved to: {report_path}")
    print("="*80 + "\n")

    return report


if __name__ == "__main__":
    audit()
