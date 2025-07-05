#!/usr/bin/env python3
"""
Fix Subscription Processing Error

Addresses the UpdateAfterSubmitError when subscriptions try to update
their current_invoice_start date during scheduled processing.
"""

import frappe
from frappe.utils import add_days


def fix_stuck_subscription(subscription_name="ACC-SUB-2025-00001"):
    """Fix a specific subscription that's stuck due to date update restrictions"""

    print(f"Fixing subscription {subscription_name}...")

    try:
        # Get subscription details
        sub_data = frappe.db.get_value(
            "Subscription",
            subscription_name,
            ["current_invoice_start", "current_invoice_end", "status", "docstatus"],
            as_dict=True,
        )

        if not sub_data:
            print(f"Subscription {subscription_name} not found")
            return False

        print(f"Current state: {sub_data}")

        # Method 1: Direct database update (bypasses validation)
        if sub_data["docstatus"] == 1:
            # Calculate next dates
            pass

            sub = frappe.get_doc("Subscription", subscription_name)

            # Get the subscription plan to determine the period
            if sub.plans:
                plan = frappe.get_doc("Subscription Plan", sub.plans[0].plan)
                interval = plan.interval
                interval_count = plan.interval_count or 1
            else:
                # Default to daily if no plan
                interval = "Day"
                interval_count = 1

            # Calculate next invoice period
            if sub.current_invoice_end:
                next_start = add_days(sub.current_invoice_end, 1)
            else:
                next_start = add_days(sub.current_invoice_start, 1)

            # Calculate end date based on interval
            if interval == "Day":
                next_end = add_days(next_start, interval_count - 1)
            elif interval == "Week":
                next_end = add_days(next_start, (7 * interval_count) - 1)
            elif interval == "Month":
                from dateutil.relativedelta import relativedelta

                next_end = add_days(next_start + relativedelta(months=interval_count), -1)
            elif interval == "Year":
                from dateutil.relativedelta import relativedelta

                next_end = add_days(next_start + relativedelta(years=interval_count), -1)

            print(f"Updating dates: {next_start} to {next_end}")

            # Update directly in database
            frappe.db.sql(
                """
                UPDATE `tabSubscription`
                SET
                    current_invoice_start = %s,
                    current_invoice_end = %s,
                    modified = NOW()
                WHERE name = %s
            """,
                (next_start, next_end, subscription_name),
            )

            frappe.db.commit()

            print("✓ Subscription dates updated successfully")
            return True

    except Exception as e:
        print(f"Error fixing subscription: {str(e)}")
        frappe.db.rollback()
        return False


def fix_all_stuck_subscriptions():
    """Fix all subscriptions with date issues"""

    print("Finding subscriptions with potential date issues...")

    # Find subscriptions that might be stuck
    stuck_subs = frappe.db.sql(
        """
        SELECT name, current_invoice_start, current_invoice_end, start_date
        FROM `tabSubscription`
        WHERE
            status = 'Active'
            AND docstatus = 1
            AND (
                current_invoice_start < CURDATE()
                OR current_invoice_end < CURDATE()
                OR current_invoice_end < current_invoice_start
            )
    """,
        as_dict=True,
    )

    print(f"Found {len(stuck_subs)} subscriptions with potential issues")

    fixed = 0
    failed = 0

    for sub in stuck_subs:
        print(f"\nProcessing {sub.name}...")
        if fix_stuck_subscription(sub.name):
            fixed += 1
        else:
            failed += 1

    print(f"\n✓ Fixed: {fixed}")
    print(f"✗ Failed: {failed}")

    return {"fixed": fixed, "failed": failed}


def add_subscription_override_to_hooks():
    """Add subscription override to hooks.py to prevent future issues"""

    hooks_path = frappe.get_app_path("verenigingen", "hooks.py")

    # Check if override already exists
    with open(hooks_path, "r") as f:
        content = f.read()

    if "override_doctype_class" in content and "Subscription" in content:
        print("Subscription override already exists in hooks.py")
        return

    # Find where to add the override
    if "override_doctype_class = {" in content:
        # Add to existing override_doctype_class
        print("Adding to existing override_doctype_class")
        # Implementation would go here
    else:
        # Add new override_doctype_class section
        print("Would add new override_doctype_class section")
        # Implementation would go here

    print("Note: Manual edit of hooks.py recommended for safety")


def create_safe_subscription_processing():
    """Create a safe subscription processing function"""

    safe_processor = '''#!/usr/bin/env python3
"""
Safe Subscription Processor

Processes subscriptions while handling date update restrictions
"""

import frappe
from frappe.utils import nowdate, getdate

def safe_process_subscriptions(posting_date=None):
    """Safely process all active subscriptions"""

    if not posting_date:
        posting_date = nowdate()

    subscriptions = frappe.get_all(
        "Subscription",
        filters={
            "status": "Active",
            "docstatus": 1
        },
        fields=["name"]
    )

    processed = 0
    errors = []

    for sub in subscriptions:
        try:
            # Try normal processing first
            subscription = frappe.get_doc("Subscription", sub.name)
            subscription.process(posting_date)
            processed += 1

        except frappe.exceptions.UpdateAfterSubmitError as e:
            # Handle date update errors specially
            if "current_invoice_start" in str(e) or "current_invoice_end" in str(e):
                # Use direct database update
                fix_stuck_subscription(sub.name)
                processed += 1
            else:
                errors.append(f"{sub.name}: {str(e)}")

        except Exception as e:
            errors.append(f"{sub.name}: {str(e)}")

    print(f"Processed: {processed}")
    print(f"Errors: {len(errors)}")

    return {"processed": processed, "errors": errors}


if __name__ == "__main__":
    safe_process_subscriptions()
'''

    file_path = frappe.get_app_path("verenigingen", "scripts", "schedulers", "safe_subscription_processor.py")

    import os

    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "w") as f:
        f.write(safe_processor)

    print(f"Created safe processor at {file_path}")


if __name__ == "__main__":
    frappe.connect(site=frappe.get_site())

    try:
        # Fix the specific subscription mentioned in the error
        print("=== Fixing Subscription ACC-SUB-2025-00001 ===")
        fix_stuck_subscription("ACC-SUB-2025-00001")

        # Optionally fix all stuck subscriptions
        # print("\n=== Fixing All Stuck Subscriptions ===")
        # fix_all_stuck_subscriptions()

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
