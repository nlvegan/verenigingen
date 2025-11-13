"""Quick wrapper to run subscription audit from command line."""

import json

from verenigingen.utils.admin_utilities.subscription_audit import SubscriptionAudit


def run():
    """Execute the audit and print results."""
    print("\n" + "=" * 80)
    print("MOLLIE SUBSCRIPTION AUDIT")
    print("=" * 80 + "\n")

    auditor = SubscriptionAudit()
    report = auditor.run_full_audit(auto_cancel_orphans=False)

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total Mollie Subscriptions: {report['summary']['total_mollie_subscriptions']}")
    print(f"Active Mollie Subscriptions: {report['summary']['active_mollie_subscriptions']}")
    print(f"\n*** ORPHANED SUBSCRIPTIONS: {report['summary']['orphaned_subscriptions']} ***")
    print(f"*** DELETED MEMBER SUBSCRIPTIONS: {report['summary']['deleted_member_subscriptions']} ***")
    print(f"Status Mismatches: {report['summary']['status_mismatches']}")
    print(f"Missing Mollie Data: {report['summary']['missing_mollie_data']}")
    print(f"\nTest Mode: {report['test_mode']}")

    # Print orphaned details
    if report["details"]["orphaned_subscriptions"]:
        print("\n" + "-" * 80)
        print("ORPHANED SUBSCRIPTION DETAILS:")
        print("-" * 80)
        for orphan in report["details"]["orphaned_subscriptions"]:
            print(f"\nID: {orphan['subscription_id']}")
            print(f"  Customer: {orphan['customer_id']}")
            print(f"  Status: {orphan['status']}")
            print(f"  Amount: {orphan['amount']}")
            print(f"  Interval: {orphan['interval']}")
            print(f"  Description: {orphan['description']}")
            print(f"  Next Payment: {orphan['next_payment_date']}")

    # Print deleted member details
    if report["details"]["deleted_member_subscriptions"]:
        print("\n" + "-" * 80)
        print("DELETED MEMBER SUBSCRIPTION DETAILS:")
        print("-" * 80)
        for deleted in report["details"]["deleted_member_subscriptions"]:
            print(f"\nID: {deleted['subscription_id']}")
            print(f"  Deleted Member: {deleted['deleted_member']}")
            print(f"  Status: {deleted['status']}")
            print(f"  Amount: {deleted['amount']}")

    # Print status mismatches
    if report["details"]["status_mismatches"]:
        print("\n" + "-" * 80)
        print("STATUS MISMATCH DETAILS:")
        print("-" * 80)
        for mismatch in report["details"]["status_mismatches"]:
            print(f"\nMember: {mismatch.get('member_name', 'N/A')} ({mismatch.get('member_id', 'N/A')})")
            if mismatch.get("issue") == "customer_id_mismatch":
                print(f"  Issue: Customer ID mismatch")
                print(f"  Mollie: {mismatch['mollie_customer_id']}")
                print(f"  Member: {mismatch['member_customer_id']}")
            else:
                print(f"  Mollie Status: {mismatch.get('mollie_status')}")
                print(f"  Member Status: {mismatch.get('member_status')}")

    # Save full report
    report_path = "/tmp/subscription_audit_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n\nFull JSON report saved to: {report_path}")
    print("=" * 80 + "\n")

    return report
