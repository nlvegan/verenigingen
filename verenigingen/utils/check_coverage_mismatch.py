#!/usr/bin/env python3
"""Check for mismatches between next_invoice_date and actual invoice coverage"""

import frappe
from frappe.utils import getdate


def check_coverage_scheduling_mismatches():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("Checking for mismatches between next_invoice_date and actual coverage...\n")

    # Get all active schedules
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "auto_generate": 1},
        fields=["name", "member", "next_invoice_date", "billing_frequency"],
    )

    print(f"Checking {len(schedules)} active schedules...\n")

    mismatches = []

    for sched in schedules:
        if not sched.member:
            continue

        # Get member's customer
        try:
            member = frappe.get_doc("Member", sched.member)
        except:
            continue

        if not member.customer:
            continue

        # Get their latest invoice coverage
        latest_invoice = frappe.db.sql(
            """
            SELECT name, posting_date,
                   custom_coverage_start_date, custom_coverage_end_date
            FROM `tabSales Invoice`
            WHERE customer = %(customer)s
            AND docstatus = 1
            AND custom_coverage_end_date IS NOT NULL
            ORDER BY custom_coverage_end_date DESC
            LIMIT 1
        """,
            {"customer": member.customer},
            as_dict=True,
        )

        if not latest_invoice:
            continue

        latest_coverage_end = getdate(latest_invoice[0].custom_coverage_end_date)
        next_invoice_date = getdate(sched.next_invoice_date) if sched.next_invoice_date else None

        if not next_invoice_date:
            continue

        # Check for mismatch: coverage should end just before next_invoice_date
        # Allow some tolerance for different billing frequencies
        tolerance_days = 5
        expected_gap = (next_invoice_date - latest_coverage_end).days

        # Gap should be close to 0 or 1 (coverage ends, next invoice starts next day)
        if expected_gap < -tolerance_days or expected_gap > tolerance_days:
            mismatches.append(
                {
                    "schedule": sched.name,
                    "member": sched.member,
                    "member_name": f"{member.first_name} {member.last_name}",
                    "billing_frequency": sched.billing_frequency,
                    "latest_invoice": latest_invoice[0].name,
                    "coverage_end": latest_coverage_end,
                    "next_invoice_date": next_invoice_date,
                    "gap_days": expected_gap,
                    "invoice_posted": latest_invoice[0].posting_date,
                }
            )

    print(f"Found {len(mismatches)} schedules with coverage/scheduling mismatches\n")

    if mismatches:
        print("=" * 80)
        print("COVERAGE vs SCHEDULING MISMATCHES")
        print("=" * 80)

        for i, m in enumerate(mismatches[:20], 1):
            print(f"\n{i}. {m['member_name']} ({m['schedule']})")
            print(f"   Frequency: {m['billing_frequency']}")
            print(f"   Latest Invoice: {m['latest_invoice']} (posted {m['invoice_posted']})")
            print(f"   Coverage ends: {m['coverage_end']}")
            print(f"   Next invoice scheduled: {m['next_invoice_date']}")
            print(f"   ⚠️ GAP: {m['gap_days']} days")

            if m["gap_days"] < 0:
                print(f"   → Coverage EXTENDS PAST next invoice date!")
            else:
                print(f"   → Coverage ENDS TOO EARLY before next invoice!")

        if len(mismatches) > 20:
            print(f"\n... and {len(mismatches) - 20} more mismatches")
    else:
        print("✓ All schedules have consistent coverage and scheduling!")

    frappe.db.commit()
    frappe.destroy()


if __name__ == "__main__":
    check_coverage_scheduling_mismatches()
