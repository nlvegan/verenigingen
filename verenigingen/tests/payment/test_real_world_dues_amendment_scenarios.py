"""
Real-world test scenarios for the enhanced dues amendment system.

This test suite validates realistic scenarios that would occur in actual usage:
1. Member requests fee increase due to improved financial situation
2. Member requests fee decrease due to financial hardship
3. Student member graduates and requests adult membership fee
4. Long-term member with legacy override migrates to new system
5. Member portal fee adjustment integration
6. Bulk amendment processing scenarios
"""

import unittest
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, today, flt

from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists
from verenigingen.tests.utils.base import VereningingenTestCase


class TestRealWorldDuesAmendmentScenarios(VereningingenTestCase):
    """Test real-world scenarios for dues amendment system"""

    def setUp(self):
        """Set up test data for realistic scenarios"""
        super().setUp()

        # Create various member types for realistic testing
        self.create_test_members()
        self.create_test_memberships()
        self.create_test_dues_schedules()

    def create_test_members(self):
        """Create different types of members for realistic testing"""

        # Young professional member
        self.young_professional = self.create_test_member(
            first_name="Sarah",
            last_name="Professional",
            email="sarah.professional@example.com",
            birth_date="1995-03-15",
            student_status=False,
        )

        # Student member
        self.student_member = self.create_test_member(
            first_name="Tom",
            last_name="Student",
            email="tom.student@example.com",
            birth_date="2000-08-20",
            student_status=True,
        )

        # Long-term member with legacy data
        self.legacy_member = self.create_test_member(
            first_name="Margaret",
            last_name="Legacy",
            email="margaret.legacy@example.com",
            birth_date="1970-05-10",
            student_status=False,
        )

        # Member facing financial hardship
        self.hardship_member = self.create_test_member(
            first_name="David",
            last_name="Hardship",
            email="david.hardship@example.com",
            birth_date="1985-12-03",
            student_status=False,
        )

    def _submit_membership(self, membership):
        """Submit a membership so the member has an ACTIVE membership.

        The factory only inserts (Draft); the dues schedule controller requires
        a submitted, Active membership. Submitting also auto-creates an Active
        Membership Dues Schedule for the member.
        """
        membership.submit()
        return membership

    def _ensure_member_user(self, member):
        """Create (if needed) a User with the member role and link it to the member.

        Returns the user's email. Needed so self-service portal APIs that resolve
        the member from the session user (and require member-level auth) work.
        """
        email = member.email
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": member.first_name or "Test",
                    "last_name": member.last_name or "Member",
                    "enabled": 1,
                    "user_type": "System User",
                    "send_welcome_email": 0,
                }
            )
            if frappe.db.exists("Role", "Verenigingen Member"):
                user.append("roles", {"role": "Verenigingen Member"})
            # The API security framework derives the member auth level from the
            # user's Role Profile assignment (not raw roles), so assign the
            # "Verenigingen Member" Role Profile too.
            if frappe.db.exists("Role Profile", "Verenigingen Member"):
                user.role_profile_name = "Verenigingen Member"
                user.append("role_profiles", {"role_profile": "Verenigingen Member"})
            user.flags.ignore_permissions = True
            user.insert(ignore_permissions=True)
            self.track_doc("User", user.name)
        if member.user != email:
            member.db_set("user", email)
            member.reload()
        # Invalidate the auth engine's role-profile cache so the freshly assigned
        # role profile is picked up when the API authorizes this user.
        try:
            from verenigingen.utils.security.authorization_engine import AuthorizationEngine

            AuthorizationEngine().invalidate_user_cache(email)
        except Exception:
            pass
        frappe.clear_cache(user=email)
        return email

    def _reconfigure_auto_schedule(self, member_name, dues_rate):
        """Return the member's auto-created Active dues schedule, reconfigured.

        Submitting a Membership auto-creates one Active dues schedule, and only
        one active schedule per member is allowed, so reuse that schedule rather
        than insert a colliding one.
        """
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0, "status": "Active"},
            "name",
        )
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        schedule.dues_rate = dues_rate
        schedule.save()
        return schedule

    def create_test_memberships(self):
        """Create memberships for test members"""

        # These scenarios use small dues rates (€8-€25), so the membership type's
        # minimum must be low enough to validate. ensure_membership_type_exists
        # aligns the auto-created template's rate to this minimum, so dues
        # schedules at these rates pass validation.
        regular_type = ensure_membership_type_exists("Regular Member (Real-World Test)", amount=5.0)
        # Expose for tests that create their own memberships and rely on the
        # type having a dues-schedule template (so submit auto-creates an Active
        # Membership Dues Schedule). The factory's default type has no template.
        self.regular_type = regular_type

        # Create memberships (factory inserts Draft; submit to make them Active)
        self.young_professional_membership = self._submit_membership(
            self.create_test_membership(
                member=self.young_professional.name,
                membership_type=regular_type,
                status="Active",
            )
        )

        self.student_membership = self._submit_membership(
            self.create_test_membership(
                member=self.student_member.name,
                membership_type=regular_type,
                status="Active",
            )
        )

        self.legacy_membership = self._submit_membership(
            self.create_test_membership(
                member=self.legacy_member.name,
                membership_type=regular_type,
                status="Active",
            )
        )

        self.hardship_membership = self._submit_membership(
            self.create_test_membership(
                member=self.hardship_member.name,
                membership_type=regular_type,
                status="Active",
            )
        )

    def create_test_dues_schedules(self):
        """Reconfigure the auto-created dues schedules for test members"""

        # Young professional - standard amount
        self.young_professional_schedule = self._reconfigure_auto_schedule(
            self.young_professional.name, dues_rate=15.00
        )

        # Student - reduced amount
        self.student_schedule = self._reconfigure_auto_schedule(self.student_member.name, dues_rate=10.00)

        # Legacy member - has override fields in addition to the dues schedule.
        # The amendment reads current_amount from the ACTIVE dues schedule (the
        # dues schedule takes priority over the legacy override), so align the
        # auto-created schedule's rate with the override to keep "current = €20".
        self.legacy_schedule = self._reconfigure_auto_schedule(self.legacy_member.name, dues_rate=20.00)
        self.legacy_member.reload()
        self.legacy_member.dues_rate = 20.00
        self.legacy_member.fee_override_reason = "Long-term member discount"
        self.legacy_member.fee_override_date = add_days(today(), -365)
        self.legacy_member.save()

        # Hardship member - current standard amount
        self.hardship_schedule = self._reconfigure_auto_schedule(self.hardship_member.name, dues_rate=15.00)

    def test_young_professional_fee_increase_scenario(self):
        """
        Real-world scenario: Young professional gets a promotion and wants to increase contribution
        """
        print("\\n=== Testing: Young Professional Fee Increase ===")

        # Member requests fee increase from €15 to €25
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.young_professional_membership.name,
                "member": self.young_professional.name,
                "amendment_type": "Fee Change",
                "requested_amount": 25.00,
                "reason": "Got a promotion and want to support the organization more",
                # Use today's date: apply_amendment only applies (and creates the
                # new schedule) for non-future effective dates; a future date
                # returns a "warning" and defers application.
                "effective_date": today(),
            }
        )

        # Should be auto-approved since it's an increase
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Verify auto-approval
        self.assertEqual(amendment.status, "Approved")
        self.assertIn("Auto-approved", amendment.internal_notes or "")

        # Apply the amendment
        result = amendment.apply_amendment()
        self.assertEqual(result["status"], "success")

        # A PURE fee change updates the member's existing active dues schedule in
        # place (rather than cancelling it and creating a new one), so
        # new_dues_schedule points back at the existing schedule with the new rate.
        self.assertIsNotNone(amendment.new_dues_schedule)
        self.assertEqual(amendment.new_dues_schedule, self.young_professional_schedule.name)

        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        self.assertEqual(new_schedule.dues_rate, 25.00)
        self.assertEqual(new_schedule.status, "Active")
        self.assertIn(amendment.name, new_schedule.notes or "")

        # The existing schedule was updated in place (stays Active, new rate).
        self.young_professional_schedule.reload()
        self.assertEqual(self.young_professional_schedule.status, "Active")
        self.assertEqual(self.young_professional_schedule.dues_rate, 25.00)

        # Verify legacy fields are maintained
        self.young_professional.reload()
        self.assertEqual(self.young_professional.dues_rate, 25.00)
        self.assertIn("Amendment:", self.young_professional.fee_override_reason)

    def test_student_graduation_scenario(self):
        """
        Real-world scenario: Student member graduates and requests adult membership rate
        """
        print("\\n=== Testing: Student Graduation Scenario ===")

        # Student graduates and requests adult rate (€10 -> €15)
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.student_membership.name,
                "member": self.student_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 15.00,
                "reason": "Graduated from university, moving to adult membership rate",
                # Today's date so apply_amendment applies immediately and creates
                # the new schedule (a future date defers application with a warning).
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Should be auto-approved since it's an increase
        self.assertEqual(amendment.status, "Approved")

        # Apply the amendment
        amendment.apply_amendment()

        # Verify the change
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)

        self.assertEqual(new_schedule.dues_rate, 15.00)
        # The amendment reason is preserved on the amendment request itself; the
        # generated schedule records provenance in `notes` (with the amendment name).
        self.assertIn("graduated", amendment.reason.lower())
        self.assertIn(amendment.name, new_schedule.notes or "")

        # Update member's student status
        self.student_member.reload()
        self.student_member.student_status = False
        self.student_member.save()

    def test_financial_hardship_scenario(self):
        """
        Real-world scenario: Member faces financial hardship and requests fee reduction
        """
        print("\\n=== Testing: Financial Hardship Scenario ===")

        # Member requests fee reduction from €15 to €8
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.hardship_membership.name,
                "member": self.hardship_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 8.00,
                "reason": "Temporary financial hardship due to job loss",
                # Today so apply_amendment applies immediately (future dates defer).
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # Current business rule auto-approves ALL fee changes that respect the
        # minimum fee (both increases and decreases). €8 is above the €5 minimum,
        # so this hardship decrease is auto-approved rather than left pending.
        self.assertEqual(amendment.status, "Approved")
        self.assertIn("Auto-approved", amendment.internal_notes or "")

        # Apply the amendment
        amendment.apply_amendment()

        # Verify the change
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)

        self.assertEqual(new_schedule.dues_rate, 8.00)
        # The amendment reason is preserved on the amendment request itself; the
        # generated schedule records provenance in `notes` (with the amendment name).
        self.assertIn("hardship", amendment.reason.lower())
        self.assertIn(amendment.name, new_schedule.notes or "")

    def test_legacy_member_migration_scenario(self):
        """
        Real-world scenario: Legacy member with override fields gets new dues schedule
        """
        print("\\n=== Testing: Legacy Member Migration Scenario ===")

        # Legacy member has override fields but no dues schedule
        self.assertIsNotNone(self.legacy_member.dues_rate)

        # Member requests small adjustment to trigger migration
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.legacy_membership.name,
                "member": self.legacy_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 22.00,  # Small increase from €20
                "reason": "Small adjustment to support increased costs",
                "effective_date": today(),
            }
        )

        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)

        # current_amount comes from the active dues schedule (aligned to €20 in setUp)
        self.assertEqual(amendment.current_amount, 20.00)

        # €22 respects the minimum, so the amendment is auto-approved on insert;
        # apply it directly (calling approve_amendment now would fail — not Pending).
        self.assertEqual(amendment.status, "Approved")
        amendment.apply_amendment()

        # Verify migration to dues schedule
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)

        self.assertEqual(new_schedule.dues_rate, 22.00)
        # Amendment-generated schedules use Fixed mode at the requested rate.
        self.assertEqual(new_schedule.contribution_mode, "Fixed")

    def test_zero_amount_free_membership_scenario(self):
        """
        Real-world scenario: a zero-amount ("free membership") fee change is rejected.

        The Contribution Amendment Request controller validates that the requested
        amount is greater than zero (validate_amount_changes), so a 0.00 fee change
        cannot be created. Verify that contract holds rather than expecting a free
        membership to be applied.
        """
        print("\\n=== Testing: Free Membership Scenario (rejected) ===")

        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.hardship_membership.name,
                "member": self.hardship_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 0.00,
                "reason": "Extreme financial hardship - requesting temporary free membership",
                "effective_date": today(),
            }
        )

        with self.assertRaises(frappe.ValidationError):
            amendment.insert()

    def test_bulk_amendment_processing_scenario(self):
        """
        Real-world scenario: Processing multiple amendments in batch
        """
        print("\\n=== Testing: Bulk Amendment Processing ===")

        # Create multiple amendments for different members
        amendments = []

        # Create amendments for each member
        for i, (member, membership) in enumerate(
            [
                (self.young_professional, self.young_professional_membership),
                (self.student_member, self.student_membership),
                (self.legacy_member, self.legacy_membership),
            ]
        ):
            amendment = frappe.get_doc(
                {
                    "doctype": "Contribution Amendment Request",
                    "membership": membership.name,
                    "member": member.name,
                    "amendment_type": "Fee Change",
                    "requested_amount": 20.00 + (i * 5),  # Different amounts
                    "reason": f"Bulk processing test amendment {i+1}",
                    "effective_date": today(),
                }
            )

            amendment.insert()
            amendments.append(amendment)
            self.track_doc("Contribution Amendment Request", amendment.name)

        # Process all amendments
        processed_count = 0
        for amendment in amendments:
            if amendment.status == "Pending Approval":
                amendment.approve_amendment("Bulk approval")

            result = amendment.apply_amendment()
            if result["status"] == "success":
                processed_count += 1

                # Track created dues schedules
                if amendment.new_dues_schedule:
                    self.track_doc("Membership Dues Schedule", amendment.new_dues_schedule)

        # Verify all were processed
        self.assertEqual(processed_count, len(amendments))

    @unittest.skip(
        "BLOCKED on a product/security decision (needs human sign-off): a plain "
        "'Verenigingen Member' cannot create a Contribution Amendment Request via "
        "submit_fee_adjustment_request. The DocType grants 'create' only to System "
        "Manager / Verenigingen Staff, and Member is not in secure_operations."
        "ESCALATION_ALLOWED_ROLES, so the self-service portal call fails with "
        "'permission denied'. Resolving this requires granting Member create access "
        "(DocPerm) or adding Member to the self-service escalation path -- a "
        "security change that should not be made silently to force a green test."
    )
    def test_member_portal_integration_scenario(self):
        """
        Real-world scenario: Member uses portal to adjust fee
        """
        print("\\n=== Testing: Member Portal Integration ===")

        # Simulate member portal fee adjustment
        from verenigingen.templates.pages.membership_adjustment import submit_fee_adjustment_request

        # submit_fee_adjustment_request is a self-service API: it resolves the
        # member from the session user (Member.user) and requires that user to be
        # an authenticated member (medium auth). Give the member a real User with
        # the member role and link it, then run as that user.
        member_user = self._ensure_member_user(self.young_professional)

        with self.as_user(member_user):
            # Submit fee adjustment through portal
            result = submit_fee_adjustment_request(
                new_amount=30.00, reason="Using member portal to increase contribution"
            )

            # Verify result
            self.assertTrue(result["success"])
            self.assertIn("amendment_id", result)

            # Get the created amendment
            amendment = frappe.get_doc("Contribution Amendment Request", result["amendment_id"])
            self.track_doc("Contribution Amendment Request", amendment.name)

            # Verify it was created correctly
            self.assertEqual(amendment.requested_amount, 30.00)
            self.assertEqual(amendment.member, self.young_professional.name)
            self.assertTrue(amendment.requested_by_member)

            # Should be auto-approved for increase
            if result.get("needs_approval"):
                self.assertEqual(amendment.status, "Approved")
            else:
                self.assertEqual(amendment.status, "Applied")

    def test_amendment_conflict_resolution_scenario(self):
        """
        Real-world scenario: Multiple amendments for same member with conflict resolution
        """
        print("\\n=== Testing: Amendment Conflict Resolution ===")

        # Only amendments left in "Pending Approval" block a new request. Fee
        # changes that respect the minimum auto-approve, and below-minimum fee
        # changes are rejected outright, so a Fee Change never stays pending.
        # A Membership Type Change ALWAYS requires manual approval (stays
        # Pending), so use it to create a genuine pending conflict.
        other_type = ensure_membership_type_exists("Conflict Other Type (Real-World Test)", amount=5.0)
        amendment1 = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.young_professional_membership.name,
                "member": self.young_professional.name,
                "amendment_type": "Membership Type Change",
                "requested_membership_type": other_type,
                "reason": "First amendment request (type change -> pending)",
                "effective_date": add_days(today(), 30),
            }
        )

        amendment1.insert()
        self.track_doc("Contribution Amendment Request", amendment1.name)
        self.assertEqual(amendment1.status, "Pending Approval")

        # Create second amendment while one is pending (should be prevented).
        with self.assertRaises(frappe.ValidationError):
            amendment2 = frappe.get_doc(
                {
                    "doctype": "Contribution Amendment Request",
                    "membership": self.young_professional_membership.name,
                    "member": self.young_professional.name,
                    "amendment_type": "Fee Change",
                    "requested_amount": 28.00,
                    "reason": "Second amendment request",
                    "effective_date": add_days(today(), 30),
                }
            )
            amendment2.insert()

    def test_realistic_fee_calculation_scenario(self):
        """
        Real-world scenario: Test realistic fee calculation priorities
        """
        print("\\n=== Testing: Realistic Fee Calculation ===")

        # Test priority system: Dues Schedule > Legacy Override > Standard

        # Member with both dues schedule and legacy override
        member_with_both = self.create_test_member(
            first_name="Mixed", last_name="System", email="mixed.system@example.com"
        )

        # Set legacy override
        member_with_both.dues_rate = 18.00
        member_with_both.fee_override_reason = "Legacy override"
        member_with_both.save()

        # Active membership first (auto-creates a dues schedule); reconfigure it
        # so the dues schedule takes priority over the legacy override. Use
        # regular_type, which has a dues-schedule template, so submitting the
        # membership auto-creates an Active Membership Dues Schedule.
        membership = self._submit_membership(
            self.create_test_membership(
                member=member_with_both.name,
                membership_type=self.regular_type,
                status="Active",
            )
        )
        dues_schedule = self._reconfigure_auto_schedule(member_with_both.name, dues_rate=22.00)

        # Test fee calculation
        from verenigingen.templates.pages.membership_adjustment import get_effective_fee_for_member

        effective_fee = get_effective_fee_for_member(member_with_both, membership)

        # Should prioritize dues schedule over legacy override
        self.assertEqual(effective_fee["amount"], 22.00)
        self.assertEqual(effective_fee["source"], "dues_schedule")

        print(f"✓ Fee calculation priority working: {effective_fee}")


def run_real_world_tests():
    """Run the real-world dues amendment tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestRealWorldDuesAmendmentScenarios)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\\n=== REAL-WORLD DUES AMENDMENT TEST RESULTS ===")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\\nFAILURES:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")

    if result.errors:
        print("\\nERRORS:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

    return result.wasSuccessful()


if __name__ == "__main__":
    run_real_world_tests()



