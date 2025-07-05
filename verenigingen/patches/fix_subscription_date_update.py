"""
Fix for Subscription Update After Submit Error

This patch addresses the issue where subscriptions cannot update their
current_invoice_start date after submission.
"""

import frappe
from frappe.utils import getdate, nowdate


def fix_subscription_date_updates():
    """
    Fix subscriptions that are stuck due to date update restrictions
    """

    # Get all active subscriptions
    subscriptions = frappe.get_all(
        "Subscription",
        filters={"status": "Active", "docstatus": 1},
        fields=["name", "current_invoice_start", "current_invoice_end", "start_date"],
    )

    fixed_count = 0
    errors = []

    for sub in subscriptions:
        try:
            # Check if subscription needs fixing
            if needs_date_fix(sub):
                fix_subscription(sub.name)
                fixed_count += 1
                print(f"✓ Fixed subscription {sub.name}")
        except Exception as e:
            error_msg = f"Error fixing {sub.name}: {str(e)}"
            errors.append(error_msg)
            print(f"✗ {error_msg}")

    print(f"\nSummary: Fixed {fixed_count} subscriptions")
    if errors:
        print(f"Errors: {len(errors)}")
        for error in errors[:5]:
            print(f"  - {error}")

    return {"fixed": fixed_count, "errors": errors}


def needs_date_fix(subscription):
    """Check if subscription has date inconsistencies"""

    # If current_invoice_start is before today, it might need updating
    if subscription.current_invoice_start and getdate(subscription.current_invoice_start) < getdate(
        nowdate()
    ):
        return True

    # If current_invoice_end is before current_invoice_start
    if (
        subscription.current_invoice_start
        and subscription.current_invoice_end
        and getdate(subscription.current_invoice_end) < getdate(subscription.current_invoice_start)
    ):
        return True

    return False


def fix_subscription(subscription_name):
    """Fix a specific subscription by cancelling and recreating if needed"""

    # Get the full subscription document
    sub = frappe.get_doc("Subscription", subscription_name)

    # Option 1: Try to update using frappe.db.set_value (bypasses validation)
    try:
        # Calculate the next invoice period
        from erpnext.accounts.doctype.subscription.subscription import get_next_date

        next_invoice_start = get_next_date(sub.current_invoice_end, sub.number_of_days)
        next_invoice_end = get_next_date(next_invoice_start, sub.number_of_days)

        # Update directly in database
        frappe.db.set_value(
            "Subscription",
            subscription_name,
            {"current_invoice_start": next_invoice_start, "current_invoice_end": next_invoice_end},
            update_modified=False,
        )
        frappe.db.commit()

        return True

    except Exception as e:
        # Option 2: Cancel and recreate
        print(f"Direct update failed for {subscription_name}: {str(e)}")
        return cancel_and_recreate_subscription(sub)


def cancel_and_recreate_subscription(old_sub):
    """Cancel the problematic subscription and create a new one"""

    # Store original data
    original_data = {
        "party_type": old_sub.party_type,
        "party": old_sub.party,
        "company": old_sub.company,
        "start_date": old_sub.start_date,
        "generate_invoice_at": old_sub.generate_invoice_at,
        "submit_invoice": old_sub.submit_invoice,
        "days_until_due": old_sub.days_until_due,
        "plans": [],
    }

    # Copy subscription plans
    for plan in old_sub.plans:
        original_data["plans"].append({"plan": plan.plan, "qty": plan.qty})

    try:
        # Cancel old subscription
        old_sub.cancel()

        # Create new subscription
        new_sub = frappe.get_doc({"doctype": "Subscription", **original_data})

        new_sub.insert()
        new_sub.submit()

        print(f"Created new subscription {new_sub.name} to replace {old_sub.name}")
        return True

    except Exception as e:
        print(f"Failed to recreate subscription: {str(e)}")
        # Try to restore the old subscription
        old_sub.docstatus = 1
        old_sub.save()
        return False


def create_subscription_override():
    """
    Create an override for the Subscription doctype to allow date updates
    This is a more permanent solution
    """

    override_code = '''
# Override for Subscription to allow date updates after submit

import frappe
from erpnext.accounts.doctype.subscription.subscription import Subscription

class CustomSubscription(Subscription):
    def validate_update_after_submit(self):
        """Override to allow updating invoice dates after submit"""

        # Get the base implementation
        super().validate_update_after_submit()

        # Additionally allow these fields to be updated
        allowed_fields = [
            "current_invoice_start",
            "current_invoice_end",
            "next_invoice_date"
        ]

        # Remove these fields from the validation error
        for field in allowed_fields:
            if field in self.flags.get("ignore_validate_update_after_submit", []):
                continue
            self.flags.setdefault("ignore_validate_update_after_submit", []).append(field)
'''

    # Save this as a custom override
    file_path = frappe.get_app_path("verenigingen", "overrides", "subscription_override.py")

    import os

    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "w") as f:
        f.write(override_code)

    print(f"Created subscription override at {file_path}")
    print("Remember to update hooks.py to include this override")


if __name__ == "__main__":
    # Run the fix
    fix_subscription_date_updates()

    # Optionally create the override
    # create_subscription_override()
