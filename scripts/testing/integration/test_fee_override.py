#!/usr/bin/env python3
"""
Test fee override change functionality
"""
import frappe
from frappe.utils import now, today


def test_fee_override():
    """Test fee override change functionality"""

    # Get the member
    member = frappe.get_doc("Member", "Assoc-Member-2025-05-0009")
    print(f"Member: {member.full_name}")
    print(f"Current override: {member.membership_fee_override}")
    print(f"Override reason: {member.fee_override_reason}")

    # Store original values
    original_amount = member.membership_fee_override
    original_reason = member.fee_override_reason

    # Test the handle_fee_override_changes method
    member.membership_fee_override = 99.99
    member.fee_override_reason = "Test fee change flow"

    print(f"\nTesting fee change: {original_amount} -> {member.membership_fee_override}")

    try:
        # Test the handle_fee_override_changes method directly
        member.handle_fee_override_changes()
        print("handle_fee_override_changes() completed successfully")
        print(f"Has pending amendment: {hasattr(member, '_pending_amendment')}")

        if hasattr(member, "_pending_amendment"):
            print(f"Pending amendment data: {member._pending_amendment}")

        # Test save process
        print("\nTesting save process...")
        member.save()
        print("Save completed successfully")

        # Check for amendments
        amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={"member": member.name},
            fields=["name", "status", "amendment_type", "requested_amount", "creation"],
        )
        print(f"\nAmendments created: {len(amendments)}")
        for amend in amendments:
            print(
                f"  {amend.name}: {amend.status} - {amend.amendment_type} - {amend.requested_amount} - {amend.creation}"
            )

        # Check fee change history
        member.reload()
        print(f"\nFee change history entries: {len(member.fee_change_history)}")
        for history in member.fee_change_history:
            print(f"  {history.change_date}: {history.old_amount} -> {history.new_amount} - {history.reason}")

    except Exception as e:
        print(f"Error during testing: {str(e)}")
        import traceback

        traceback.print_exc()

    finally:
        # Restore original values
        try:
            member.membership_fee_override = original_amount
            member.fee_override_reason = original_reason
            member.save()
            print(f"\nRestored original values: {original_amount}, {original_reason}")
        except Exception as e:
            print(f"Error restoring values: {str(e)}")


if __name__ == "__main__":
    test_fee_override()
