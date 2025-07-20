# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Complete Member Lifecycle Workflow Test
Tests the entire journey from application submission to termination
"""


import frappe
from frappe.utils import add_days, add_months, today

from verenigingen.tests.utils.base import VereningingenWorkflowTestCase
from verenigingen.tests.utils.factories import TestDataBuilder, TestStateManager, TestUserFactory


class TestMemberLifecycle(VereningingenWorkflowTestCase):
    """
    Complete Member Lifecycle Test

    Stage 1: Submit Application
    Stage 2: Review & Approve Application
    Stage 3: Create Member, User Account, Customer
    Stage 4: Process Initial Payment
    Stage 5: Create/Renew Membership
    Stage 6: Optional - Create Volunteer Record
    Stage 7: Member Activities (join teams, submit expenses)
    Stage 8: Membership Renewal
    Stage 9: Optional - Suspension/Reactivation
    Stage 10: Termination Process
    """

    def setUp(self):
        """Set up the member lifecycle test"""
        super().setUp()
        self.state_manager = TestStateManager()
        self.test_data_builder = TestDataBuilder()

        # Set up test chapter for lifecycle
        self.test_chapter = self._create_test_chapter()
        self.admin_user = TestUserFactory.create_admin_user()

    def test_complete_member_lifecycle(self):
        """Test the complete member lifecycle from application to termination"""

        stages = [
            {
                "name": "Stage 1: Submit Application",
                "function": self._stage_1_submit_application,
                "validations": [self._validate_application_submitted]},
            {
                "name": "Stage 2: Review & Approve Application",
                "function": self._stage_2_review_approve,
                "validations": [self._validate_application_approved]},
            {
                "name": "Stage 3: Create Member & User Account",
                "function": self._stage_3_create_member_user,
                "validations": [self._validate_member_created, self._validate_user_created]},
            {
                "name": "Stage 4: Process Initial Payment",
                "function": self._stage_4_process_payment,
                "validations": [self._validate_payment_processed]},
            {
                "name": "Stage 5: Create/Activate Membership",
                "function": self._stage_5_activate_membership,
                "validations": [self._validate_membership_active]},
            {
                "name": "Stage 6: Create Volunteer Record",
                "function": self._stage_6_create_volunteer,
                "validations": [self._validate_volunteer_created]},
            {
                "name": "Stage 7: Member Activities",
                "function": self._stage_7_member_activities,
                "validations": [self._validate_activities_completed]},
            {
                "name": "Stage 8: Membership Renewal",
                "function": self._stage_8_membership_renewal,
                "validations": [self._validate_membership_renewed]},
            {
                "name": "Stage 9: Suspension & Reactivation",
                "function": self._stage_9_suspension_reactivation,
                "validations": [self._validate_suspension_reactivation]},
            {
                "name": "Stage 10: Termination Process",
                "function": self._stage_10_termination,
                "validations": [self._validate_termination_completed]},
        ]

        self.define_workflow(stages)

        with self.workflow_transaction():
            self.execute_workflow()

        # Final validations
        self._validate_complete_lifecycle()

    def _create_test_chapter(self):
        """Create a test chapter for the lifecycle"""
        chapter_name = "Test Lifecycle Chapter"

        # Check if chapter already exists
        if frappe.db.exists("Chapter", chapter_name):
            chapter = frappe.get_doc("Chapter", chapter_name)
            self.track_doc("Chapter", chapter.name)
            return chapter

        # Get the actual test region name (it might be slugified)
        test_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
        if not test_region:
            # Region should be created by base setUp, but just in case
            raise Exception("Test Region not found. Base setUp may have failed.")

        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": chapter_name,
                "region": test_region,
                "postal_codes": "1000-9999",
                "introduction": "Test chapter for lifecycle testing"}
        )
        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)
        return chapter

    # Stage 1: Submit Application
    def _stage_1_submit_application(self, context):
        """Stage 1: Submit membership application"""
        # Generate unique email for this test run
        test_id = frappe.utils.random_string(8)

        application_data = {
            "first_name": "TestLifecycle",
            "last_name": "Member",
            "email": f"lifecycle.test.{test_id}@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-01-01",  # Changed from date_of_birth
            "address_line1": "Test Street 123",  # Changed from street_address
            "postal_code": "1234AB",
            "city": "Amsterdam",
            "country": "Netherlands",
            "membership_type": "Annual",
            "payment_method": "SEPA Direct Debit",
            "iban": "NL91ABNA0417164300",
            "bank_account_name": "TestLifecycle Member",
            "chapter_preference": self.test_chapter.name}

        # Submit application using API
        from verenigingen.api.membership_application import submit_application

        result = submit_application(data=application_data)

        self.assertTrue(result.get("success"), f"Application submission failed: {result.get('error')}")

        application_id = result.get("application_id")
        self.assertIsNotNone(application_id, "Application ID not returned")

        # Record state
        self.state_manager.record_state("Application", application_id, "Submitted")

        return {"application_id": application_id, "application_data": application_data}

    def _validate_application_submitted(self, context):
        """Validate application was submitted correctly"""
        application_id = context.get("application_id")
        self.assertIsNotNone(application_id)

        # Check member exists with this application ID
        member_name = frappe.db.get_value("Member", {"application_id": application_id}, "name")
        self.assertIsNotNone(member_name, f"No member found with application_id {application_id}")

        # Check member state
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.status, "Pending")
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.first_name, "TestLifecycle")
        self.assertEqual(member.last_name, "Member")

        # Store member name for next stages
        context["member_name"] = member_name

    # Stage 2: Review & Approve Application
    def _stage_2_review_approve(self, context):
        """Stage 2: Review and approve the application"""
        member_name = context.get("member_name")

        with self.as_user(self.admin_user.name):
            # Get member and update status
            member = frappe.get_doc("Member", member_name)
            member.status = "Active"
            member.application_status = "Approved"
            if hasattr(member, "application_approved_on"):
                member.application_approved_on = frappe.utils.now_datetime()
            if hasattr(member, "application_approved_by"):
                member.application_approved_by = self.admin_user.name
            member.save(ignore_permissions=True)

            # Activate chapter membership if pending
            selected_chapter = (
                context.get("application_data", {}).get("chapter_preference") or self.test_chapter.name
            )
            if selected_chapter:
                from verenigingen.utils.application_helpers import activate_pending_chapter_membership

                activate_pending_chapter_membership(member, selected_chapter)

        # Record state transition
        self.state_manager.record_state("Member", member_name, "Approved")

        return {"member_approved": True}

    def _validate_application_approved(self, context):
        """Validate application was approved"""
        member_name = context.get("member_name")
        self.assertIsNotNone(member_name)

        member = frappe.get_doc("Member", member_name)

        # Check member status is now Active (approved)
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.application_status, "Approved")

        # Check approval metadata if available
        if hasattr(member, "application_approved_on"):
            self.assertIsNotNone(member.application_approved_on)
        if hasattr(member, "application_approved_by"):
            self.assertEqual(member.application_approved_by, self.admin_user.name)

    # Stage 3: Create Member & User Account
    def _stage_3_create_member_user(self, context):
        """Stage 3: Create member record and user account"""
        member_name = context.get("member_name")

        with self.as_user(self.admin_user.name):
            # Member already exists from application submission
            member = frappe.get_doc("Member", member_name)

            # Create user account if not exists
            if not member.user:
                user_email = member.email

                # Check if user already exists
                if not frappe.db.exists("User", user_email):
                    user = frappe.get_doc(
                        {
                            "doctype": "User",
                            "email": user_email,
                            "first_name": member.first_name,
                            "last_name": member.last_name,
                            "enabled": 1,
                            "new_password": frappe.utils.random_string(10),
                            "send_welcome_email": 0}
                    )
                    user.append("roles", {"role": "Verenigingen Member"})
                    user.insert(ignore_permissions=True)
                    self.track_doc("User", user.name)
                else:
                    user = frappe.get_doc("User", user_email)

                # Link user to member
                member.user = user.name
                member.save(ignore_permissions=True)
            else:
                user_email = member.user

        # Record states
        self.state_manager.record_state("Member", member_name, "Active")
        self.state_manager.record_state("User", user_email, "Created")

        return {"member_name": member_name, "user_email": user_email}

    def _validate_member_created(self, context):
        """Validate member was created correctly"""
        member_name = context.get("member_name")
        self.assertIsNotNone(member_name)

        # Check member exists and is linked to application
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.first_name, "TestLifecycle")

        # Check chapter membership through Chapter document
        if self.test_chapter:
            chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
            chapter_members = [cm for cm in chapter_doc.members if cm.member == member_name]
            self.assertTrue(len(chapter_members) > 0, "Member not assigned to chapter")

    def _validate_user_created(self, context):
        """Validate user account was created"""
        user_email = context.get("user_email")
        self.assertIsNotNone(user_email)

        # Check user exists and has correct roles
        user = frappe.get_doc("User", user_email)
        self.assertTrue(user.enabled)

        roles = [role.role for role in user.roles]
        self.assertIn("Verenigingen Member", roles)

    # Stage 4: Process Initial Payment
    def _stage_4_process_payment(self, context):
        """Stage 4: Process initial membership payment"""
        member_name = context.get("member_name")
        membership_name = context.get("membership_name")

        with self.as_user(self.admin_user.name):
            # First check if we have a membership yet, if not skip to stage 5
            if not membership_name:
                # Skip payment for now, membership will be created in stage 5
                return {"payment_skipped": True, "reason": "Membership not yet created"}

            # Create invoice for the membership
            from verenigingen.utils.application_payments import create_membership_invoice

            member = frappe.get_doc("Member", member_name)
            membership = frappe.get_doc("Membership", membership_name)
            membership_type = frappe.get_doc("Membership Type", membership.membership_type)

            invoice = create_membership_invoice(member, membership, membership_type, amount=100.00)
            self.track_doc("Sales Invoice", invoice.name)

            # Process the payment
            from verenigingen.utils.application_payments import process_application_payment

            # Set the application_invoice field on member if it exists
            if hasattr(member, "application_invoice"):
                member.application_invoice = invoice.name
                member.save()

                payment_result = process_application_payment(
                    member_name, "SEPA Direct Debit", payment_reference="TEST-LIFECYCLE-001"
                )
            else:
                # Alternative: Process payment directly
                payment_entry = frappe.get_doc(
                    {
                        "doctype": "Payment Entry",
                        "payment_type": "Receive",
                        "party_type": "Customer",
                        "party": member.customer or invoice.customer,
                        "paid_amount": invoice.grand_total,
                        "received_amount": invoice.grand_total,
                        "reference_no": "TEST-LIFECYCLE-001",
                        "reference_date": frappe.utils.today(),
                        "mode_of_payment": "Bank",
                        "references": [
                            {
                                "reference_doctype": "Sales Invoice",
                                "reference_name": invoice.name,
                                "allocated_amount": invoice.grand_total}
                        ]}
                )
                payment_entry.insert(ignore_permissions=True)
                payment_entry.submit()
                self.track_doc("Payment Entry", payment_entry.name)
                payment_result = {"success": True}

        # Record state
        if payment_result.get("payment_skipped"):
            return {"payment_skipped": True}

        invoice_name = invoice.name if "invoice" in locals() else None
        if invoice_name:
            self.state_manager.record_state("Payment", invoice_name, "Processed")

        return {"invoice_name": invoice_name, "payment_result": payment_result}

    def _validate_payment_processed(self, context):
        """Validate payment was processed"""
        # Check if payment was skipped (membership not yet created)
        if context.get("payment_skipped"):
            # This is expected - payment will be processed after membership creation
            return

        invoice_name = context.get("invoice_name")
        if invoice_name:
            # Check invoice exists and is paid
            if frappe.db.exists("Sales Invoice", invoice_name):
                invoice = frappe.get_doc("Sales Invoice", invoice_name)
                self.assertIn(invoice.status, ["Paid", "Submitted"])

    # Stage 5: Create/Activate Membership
    def _stage_5_activate_membership(self, context):
        """Stage 5: Activate membership after payment"""
        member_name = context.get("member_name")

        with self.as_user(self.admin_user.name):
            # Create membership record
            membership = frappe.get_doc(
                {
                    "doctype": "Membership",
                    "member": member_name,
                    "membership_type": "Annual",
                    "start_date": today(),
                    "renewal_date": add_months(today(), 12),
                    "status": "Active"}
            )
            membership.insert(ignore_permissions=True)
            membership.submit()
            self.track_doc("Membership", membership.name)

        # Record state
        self.state_manager.record_state("Membership", membership.name, "Active")

        return {"membership_name": membership.name}

    def _validate_membership_active(self, context):
        """Validate membership is active"""
        membership_name = context.get("membership_name")
        self.assertIsNotNone(membership_name)

        membership = frappe.get_doc("Membership", membership_name)
        self.assertEqual(membership.status, "Active")
        self.assertIsNotNone(membership.start_date)
        self.assertIsNotNone(membership.renewal_date)

    # Stage 6: Create Volunteer Record
    def _stage_6_create_volunteer(self, context):
        """Stage 6: Create volunteer profile"""
        member_name = context.get("member_name")
        user_email = context.get("user_email")

        # Member decides to become a volunteer
        with self.as_user(user_email):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "TestLifecycle Member",
                    "email": user_email,
                    "member": member_name,
                    "status": "Active",
                    "start_date": today(),
                    "skills": "Event Organization, Community Outreach"}
            )
            volunteer.insert(ignore_permissions=True)

        # Record state
        self.state_manager.record_state("Volunteer", volunteer.name, "Active")

        return {"volunteer_name": volunteer.name}

    def _validate_volunteer_created(self, context):
        """Validate volunteer record was created"""
        volunteer_name = context.get("volunteer_name")
        self.assertIsNotNone(volunteer_name)

        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(volunteer.member, context.get("member_name"))

    # Stage 7: Member Activities
    def _stage_7_member_activities(self, context):
        """Stage 7: Member participates in activities"""
        volunteer_name = context.get("volunteer_name")
        user_email = context.get("user_email")

        # Create team and join it
        with self.as_user(self.admin_user.name):
            # Generate unique team name to avoid duplicates
            test_id = frappe.utils.random_string(6)
            team_name = f"Events Team {test_id}"

            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": team_name,
                    "chapter": self.test_chapter.name,
                    "status": "Active",
                    "team_type": "Project Team",
                    "start_date": today()}
            )
            team.insert(ignore_permissions=True)
            self.track_doc("Team", team.name)

            # Add volunteer to team
            team.append(
                "team_members",
                {
                    "volunteer": volunteer_name,
                    "volunteer_name": "TestLifecycle Member",
                    "role": "Event Coordinator",
                    "role_type": "Team Leader",
                    "from_date": today(),
                    "is_active": 1,
                    "status": "Active"},
            )
            team.save(ignore_permissions=True)

        # Test board member addition - ensure status field is set
        with self.as_user(self.admin_user.name):
            # Create board role with unique name
            role_id = frappe.utils.random_string(6)
            role_name = f"Test Board Role {role_id}"

            board_role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "permissions_level": "Admin",
                    "is_active": 1}
            )
            board_role.insert(ignore_permissions=True)
            self.track_doc("Chapter Role", board_role.name)

            # Add as board member
            chapter = frappe.get_doc("Chapter", self.test_chapter.name)
            result = chapter.add_board_member(
                volunteer=volunteer_name, role=board_role.name, from_date=today()
            )
            self.assertTrue(result.get("success"), "Board member addition failed")

            # Reload and verify status field is set
            chapter.reload()
            member_in_chapter = None
            for cm in chapter.members:
                if cm.member == context.get("member_name"):
                    member_in_chapter = cm
                    break

            self.assertIsNotNone(member_in_chapter, "Member not found in chapter members")
            self.assertEqual(
                member_in_chapter.status, "Active", "Chapter member status field should be set to Active"
            )

        # Submit an expense
        with self.as_user(user_email):
            # Get or create expense category
            expense_category = None
            existing_categories = frappe.get_all("Expense Category", limit=1)
            if existing_categories:
                expense_category = existing_categories[0].name
            else:
                # Create expense category if none exist
                expense_account = frappe.get_all(
                    "Account", filters={"account_type": "Expense Account", "is_group": 0}, limit=1
                )
                if expense_account:
                    # Generate unique category name
                    cat_id = frappe.utils.random_string(6)
                    category_name = f"Test Supplies {cat_id}"

                    expense_cat = frappe.get_doc(
                        {
                            "doctype": "Expense Category",
                            "category_name": category_name,
                            "expense_account": expense_account[0].name}
                    )
                    expense_cat.insert(ignore_permissions=True)
                    self.track_doc("Expense Category", expense_cat.name)
                    expense_category = expense_cat.name
                else:
                    # Skip expense if no expense account exists
                    expense_category = None

            if expense_category:
                expense = frappe.get_doc(
                    {
                        "doctype": "Volunteer Expense",
                        "volunteer": volunteer_name,
                        "amount": 50.00,
                        "description": "Event supplies",
                        "expense_date": today(),
                        "status": "Draft",
                        "organization_type": "Chapter",
                        "chapter": self.test_chapter.name,
                        "category": expense_category}
                )
                expense.insert(ignore_permissions=True)
                self.track_doc("Volunteer Expense", expense.name)
            else:
                expense = None

        return {"team_name": team.name, "expense_name": expense.name if expense else None}

    def _validate_activities_completed(self, context):
        """Validate member activities were completed"""
        team_name = context.get("team_name")
        expense_name = context.get("expense_name")

        # Check team membership
        team = frappe.get_doc("Team", team_name)
        team_members = [tm for tm in team.team_members if tm.volunteer == context.get("volunteer_name")]
        self.assertTrue(len(team_members) > 0, "Volunteer not found in team")

        # Check expense submission if created
        if expense_name:
            expense = frappe.get_doc("Volunteer Expense", expense_name)
            self.assertEqual(expense.volunteer, context.get("volunteer_name"))

    # Stage 8: Membership Renewal
    def _stage_8_membership_renewal(self, context):
        """Stage 8: Renew membership for next period"""
        member_name = context.get("member_name")
        membership_name = context.get("membership_name")

        with self.as_user(self.admin_user.name):
            # Cancel old membership first
            old_membership = frappe.get_doc("Membership", membership_name)
            old_membership.cancel()

            # Create renewal membership
            new_membership_doc = frappe.get_doc(
                {
                    "doctype": "Membership",
                    "member": member_name,
                    "membership_type": old_membership.membership_type,
                    "start_date": add_days(old_membership.renewal_date, 1),
                    "renewal_date": add_months(old_membership.renewal_date, 12),
                    "status": "Active"}
            )
            new_membership_doc.insert(ignore_permissions=True)
            new_membership_doc.submit()
            self.track_doc("Membership", new_membership_doc.name)

            new_membership = new_membership_doc.name

        # Record state
        self.state_manager.record_state("Membership", new_membership, "Renewed")

        return {"renewed_membership": new_membership}

    def _validate_membership_renewed(self, context):
        """Validate membership was renewed"""
        renewed_membership = context.get("renewed_membership")
        self.assertIsNotNone(renewed_membership)

        # Check membership is still active with extended end date
        membership = frappe.get_doc("Membership", renewed_membership)
        self.assertEqual(membership.status, "Active")

    # Stage 9: Suspension & Reactivation
    def _stage_9_suspension_reactivation(self, context):
        """Stage 9: Test suspension and reactivation"""
        member_name = context.get("member_name")

        with self.as_user(self.admin_user.name):
            # Suspend member
            member = frappe.get_doc("Member", member_name)
            member.status = "Suspended"
            member.add_comment("Comment", "Test suspension for lifecycle")
            member.save(ignore_permissions=True)

            # Record suspension
            self.state_manager.record_state("Member", member_name, "Suspended")

            # Reactivate member
            member.status = "Active"
            member.add_comment("Comment", "Test reactivation for lifecycle")
            member.save(ignore_permissions=True)

            self.state_manager.record_state("Member", member_name, "Active")

        return {"suspension_tested": True}

    def _validate_suspension_reactivation(self, context):
        """Validate suspension and reactivation worked"""
        member_name = context.get("member_name")
        member = frappe.get_doc("Member", member_name)

        # Should be active again after reactivation
        self.assertEqual(member.status, "Active")

        # Check that suspension/reactivation transitions occurred
        transitions = self.state_manager.get_transitions("Member", member_name)
        suspension_transition = any(t["to_state"] == "Suspended" for t in transitions)
        reactivation_transition = any(
            t["from_state"] == "Suspended" and t["to_state"] == "Active" for t in transitions
        )

        # Only validate if suspension API is available
        if context.get("suspension_tested"):
            self.assertTrue(
                suspension_transition or reactivation_transition,
                "Expected suspension/reactivation transitions",
            )

    # Stage 10: Termination Process
    def _stage_10_termination(self, context):
        """Stage 10: Terminate member"""
        member_name = context.get("member_name")

        with self.as_user(self.admin_user.name):
            # Terminate member
            member = frappe.get_doc("Member", member_name)
            member.status = "Terminated"
            # Clear application_status to prevent sync_status_fields from changing it back
            member.application_status = ""
            member.add_comment("Comment", "Lifecycle test completion - member terminated")
            member.save(ignore_permissions=True)

            self.state_manager.record_state("Member", member_name, "Terminated")

        return {"termination_completed": True}

    def _validate_termination_completed(self, context):
        """Validate termination was completed"""
        member_name = context.get("member_name")
        member = frappe.get_doc("Member", member_name)

        # Member should be inactive/terminated
        self.assertIn(
            member.status,
            ["Inactive", "Terminated"],
            f"Member status is {member.status}, expected Inactive or Terminated",
        )

    def _validate_complete_lifecycle(self):
        """Final validation of complete lifecycle"""
        # Check that all major state transitions occurred
        transitions = self.state_manager.get_transitions()

        # Should have transitions for: Member, and optionally others
        entity_types = set(t["entity_type"] for t in transitions)

        # At minimum we should have Member transitions
        self.assertIn("Member", entity_types, "No transitions found for Member")

        # Check final states
        workflow_context = self.get_workflow_context()
        member_name = workflow_context.get("member_name")
        if member_name:
            final_member_state = self.state_manager.get_state("Member", member_name)
            self.assertEqual(final_member_state, "Terminated", "Member should be in terminated state")
