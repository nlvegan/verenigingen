#!/usr/bin/env python3

import sys

import frappe
from frappe.utils import add_days, getdate, today


def debug_member_sinv():
    """Debug why Assoc-Member-2025-07-0025 hasn't gotten SINV today"""

    try:
        member_name = "Assoc-Member-2025-07-0025"
        print(f"=== DEBUGGING MEMBER: {member_name} ===")
        print(f"Today's date: {today()}")

        # Check if member exists
        if not frappe.db.exists("Member", member_name):
            print(f"ERROR: Member {member_name} does not exist!")
            return

        member = frappe.get_doc("Member", member_name)
        print(f"\n=== MEMBER DETAILS ===")
        print(f"Name: {member.name}")
        print(f"Status: {member.status}")
        print(f"Member Type: {member.member_type}")
        print(f"Email: {member.email_address}")
        print(f"Created: {member.creation}")
        print(f"Modified: {member.modified}")

        # Check memberships
        print(f"\n=== MEMBERSHIPS ===")
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member.name},
            fields=["name", "membership_type", "from_date", "to_date", "status", "creation", "modified"],
            order_by="creation desc",
        )

        if not memberships:
            print("ERROR: No memberships found for this member!")
            return

        for membership in memberships:
            print(f"Membership: {membership.name}")
            print(f"  Type: {membership.membership_type}")
            print(f"  Period: {membership.from_date} to {membership.to_date}")
            print(f"  Status: {membership.status}")
            print(f"  Created: {membership.creation}")
            print(f"  Modified: {membership.modified}")

            # Check if this membership should generate SINV today
            from_date = getdate(membership.from_date)
            to_date = getdate(membership.to_date)
            today_date = getdate(today())

            print(f"  Today in period: {from_date <= today_date <= to_date}")

        # Check existing Sales Invoices
        print(f"\n=== EXISTING SALES INVOICES ===")
        sinvs = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.name, "posting_date": today()},
            fields=["name", "status", "grand_total", "posting_date", "creation"],
        )

        if sinvs:
            print("Sales Invoices found for today:")
            for sinv in sinvs:
                print(f"  {sinv.name} - {sinv.status} - {sinv.grand_total} - {sinv.posting_date}")
        else:
            print("No Sales Invoices found for today")

        # Check all recent Sales Invoices
        recent_sinvs = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.name},
            fields=["name", "status", "grand_total", "posting_date", "creation"],
            order_by="creation desc",
            limit=10,
        )

        if recent_sinvs:
            print("\nRecent Sales Invoices:")
            for sinv in recent_sinvs:
                print(f"  {sinv.name} - {sinv.status} - {sinv.grand_total} - {sinv.posting_date}")

        # Check dues schedules
        print(f"\n=== DUES SCHEDULES ===")
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name},
            fields=["name", "due_date", "amount", "status", "invoice", "creation"],
            order_by="due_date desc",
        )

        if dues_schedules:
            today_date = getdate(today())
            for dues in dues_schedules:
                due_date = getdate(dues.due_date)
                is_due_today = due_date == today_date
                print(f"Schedule: {dues.name}")
                print(f"  Due Date: {dues.due_date} {'(TODAY!)' if is_due_today else ''}")
                print(f"  Amount: {dues.amount}")
                print(f"  Status: {dues.status}")
                print(f"  Invoice: {dues.invoice}")
                print(f"  Created: {dues.creation}")
        else:
            print("No dues schedules found")

        # Check subscription overrides
        print(f"\n=== SUBSCRIPTION OVERRIDES ===")
        overrides = frappe.get_all(
            "Subscription Override",
            filters={"member": member.name},
            fields=["name", "subscription_type", "override_amount", "start_date", "end_date", "status"],
            order_by="creation desc",
        )

        if overrides:
            for override in overrides:
                print(f"Override: {override.name}")
                print(f"  Type: {override.subscription_type}")
                print(f"  Amount: {override.override_amount}")
                print(f"  Period: {override.start_date} to {override.end_date}")
                print(f"  Status: {override.status}")
        else:
            print("No subscription overrides found")

        # Check SEPA mandates
        print(f"\n=== SEPA MANDATES ===")
        mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member.name},
            fields=["name", "status", "iban", "creation"],
            order_by="creation desc",
        )

        if mandates:
            for mandate in mandates:
                print(f"Mandate: {mandate.name}")
                print(f"  Status: {mandate.status}")
                print(f"  IBAN: {mandate.iban}")
                print(f"  Created: {mandate.creation}")
        else:
            print("No SEPA mandates found")

    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_member_sinv()
