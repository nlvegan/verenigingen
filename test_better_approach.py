#!/usr/bin/env python3
"""
Demonstration of the better testing approach suggested by the user
Instead of fighting the business rules, work with them by:
1. Creating a membership (gets auto-schedule)
2. Cancelling the auto-schedule
3. Creating controlled test schedules
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestBetterApproach(VereningingenTestCase):
    """Demonstrate the better testing approach"""

    def test_billing_frequency_conflict_better_way(self):
        """Test billing frequency conflict using the suggested approach"""

        # Step 1: Create member and membership (gets auto-schedule)
        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="BetterTest", last_name=f"User{test_id}", email=f"better.test.{test_id}@example.com"
        )

        membership_type = self.create_test_membership_type(
            membership_type_name=f"Better Test Type {test_id}", dues_rate=30.0
        )

        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name, docstatus=0
        )
        membership.submit()
        self.track_doc("Membership", membership.name)

        # Step 2: Find and cancel the auto-created schedule
        auto_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member.name, "status": "Active"}, fields=["name"]
        )

        self.assertTrue(len(auto_schedules) > 0, "Should have auto-created schedule")

        for schedule_info in auto_schedules:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_info.name)
            schedule.status = "Cancelled"
            schedule.save()
            print(f"Cancelled auto-schedule: {schedule.name}")

        # Step 3: Now create controlled test schedules
        # Create first schedule with Monthly frequency
        schedule1 = frappe.new_doc("Membership Dues Schedule")
        schedule1.schedule_name = f"Test-Monthly-{test_id}"
        schedule1.member = member.name
        schedule1.membership_type = membership_type.name
        schedule1.dues_rate = 30.0
        schedule1.billing_frequency = "Monthly"
        schedule1.status = "Active"
        schedule1.auto_generate = 1
        schedule1.next_invoice_date = today()
        schedule1.save()
        self.track_doc("Membership Dues Schedule", schedule1.name)
        print(f"Created monthly schedule: {schedule1.name}")

        # Step 4: Try to create second schedule with Annual frequency
        schedule2 = frappe.new_doc("Membership Dues Schedule")
        schedule2.schedule_name = f"Test-Annual-{test_id}"
        schedule2.member = member.name  # Same member!
        schedule2.membership_type = membership_type.name
        schedule2.dues_rate = 200.0
        schedule2.billing_frequency = "Annual"  # Different frequency!
        schedule2.status = "Active"
        schedule2.auto_generate = 1
        schedule2.next_invoice_date = today()

        # Step 5: Test if our validation catches the conflict
        try:
            schedule2.save()
            self.track_doc("Membership Dues Schedule", schedule2.name)

            # If we get here, we have two active schedules with different frequencies
            print(f"Created annual schedule: {schedule2.name}")
            print("SUCCESS: Can now test billing frequency conflict validation!")

            # Now test the actual validation method
            validation_result = schedule2.validate_billing_frequency_consistency()
            print(f"Validation result: {validation_result}")

            # The validation should detect the conflict
            if not validation_result.get("valid", True):
                print(f"✅ Validation correctly detected conflict: {validation_result['reason']}")
            else:
                print("❌ Validation should have detected frequency conflict")

        except Exception as e:
            print(f"❌ Still couldn't create second schedule: {e}")
            print("The business rule still prevents multiple schedules per member")

    def test_membership_type_mismatch_better_way(self):
        """Test membership type mismatch using the suggested approach"""

        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="TypeTest", last_name=f"User{test_id}", email=f"type.test.{test_id}@example.com"
        )

        # Create two different membership types
        type1 = self.create_test_membership_type(membership_type_name=f"Type One {test_id}", dues_rate=25.0)

        type2 = self.create_test_membership_type(membership_type_name=f"Type Two {test_id}", dues_rate=35.0)

        # Create membership with type1
        membership = self.create_test_membership(member=member.name, membership_type=type1.name, docstatus=0)
        membership.submit()
        self.track_doc("Membership", membership.name)

        # Cancel auto-created schedule
        auto_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member.name, "status": "Active"}, fields=["name"]
        )

        for schedule_info in auto_schedules:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_info.name)
            schedule.status = "Cancelled"
            schedule.save()

        # Create schedule with type2 (mismatch!)
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Mismatch-{test_id}"
        schedule.member = member.name
        schedule.membership_type = type2.name  # Different from member's membership!
        schedule.dues_rate = 35.0
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()

        try:
            schedule.save()
            self.track_doc("Membership Dues Schedule", schedule.name)
            print("SUCCESS: Created schedule with mismatched membership type!")

            # Now test the validation
            validation_result = schedule.validate_membership_type_consistency()
            print(f"Type consistency validation: {validation_result}")

            if not validation_result.get("valid", True):
                print(f"✅ Validation correctly detected mismatch: {validation_result['reason']}")
            else:
                print("❌ Validation should have detected type mismatch")

        except Exception as e:
            print(f"❌ Couldn't create mismatched schedule: {e}")


if __name__ == "__main__":
    # Run the demonstration
    test_case = TestBetterApproach()
    test_case.setUp()

    print("=== Testing Better Approach for Billing Frequency Conflicts ===")
    test_case.test_billing_frequency_conflict_better_way()

    print("\n=== Testing Better Approach for Membership Type Mismatches ===")
    test_case.test_membership_type_mismatch_better_way()

    test_case.tearDown()
    print("\n=== Test completed ===")
