"""
Communication System Integration Tests
Complete validation of email templates, notification triggers, communication preferences,
and multi-language content delivery workflows
"""

import frappe
from frappe.utils import today, add_days, now_datetime, get_datetime
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import json
from unittest.mock import patch, MagicMock
import unittest


class TestCommunicationSystemIntegration(EnhancedTestCase):
    """Comprehensive communication system integration testing"""

    def setUp(self):
        """Set up test data for communication system tests"""
        super().setUp()

        # Ensure the custom roles referenced below exist. before_tests (which
        # normally creates these via fixtures) is skipped on single-module runs.
        for role_name in ("Verenigingen Chapter Manager", "Volunteer Coordinator"):
            if not frappe.db.exists("Role", role_name):
                role_doc = frappe.get_doc({"doctype": "Role", "role_name": role_name})
                role_doc.insert(ignore_permissions=True)
                self._track_test_document("Role", role_doc.name)

        # Create test roles for notification testing
        self.admin_user = self._create_test_user("admin@test.com", ["System Manager"])
        self.chapter_manager = self._create_test_user("manager@test.com", ["Verenigingen Chapter Manager"])
        self.volunteer_coordinator = self._create_test_user("coordinator@test.com", ["Volunteer Coordinator"])

        # Create test chapter with communication settings.
        # NOTE: email_notifications_enabled / primary_contact are not real Chapter
        # fields, so they are not passed to the factory (field validation rejects them).
        self.test_chapter = self.factory.create_test_chapter()

        # Create test membership types.
        # NOTE: send_welcome_email / send_renewal_reminders are not real
        # Membership Type fields, so they are intentionally omitted.
        self.regular_membership = self.factory.create_test_membership_type(
            membership_type_name="Regular Communication Test",
            minimum_amount=25.00,
        )

        # Create communication templates
        self._setup_email_templates()

    def _create_test_user(self, email, roles=None):
        """Create test user with specified roles"""
        if frappe.db.exists("User", email):
            return frappe.get_doc("User", email)

        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Test"
        user.last_name = "User"
        user.enabled = 1
        # Suppress welcome email: Frappe v16's send_welcome_mail_to_user
        # raises AttributeError ('bool' has no attribute 'message') when the
        # mailer returns a bool in the no-email test context.
        user.send_welcome_email = 0

        if roles:
            for role in roles:
                user.append("roles", {"role": role})

        user.save()  # EnhancedTestCase handles permissions
        self._track_test_document("User", user.name)
        return user

    def _setup_email_templates(self):
        """Set up email templates for testing"""
        templates = [
            {
                "name": "Welcome New Member",
                "subject": "Welcome to {{organization_name}}!",
                "message": "Dear {{member_name}},\n\nWelcome to our organization!",
                "use_html": 0
            },
            {
                "name": "Membership Renewal Reminder",
                "subject": "Time to Renew Your Membership",
                "message": "Dear {{member_name}},\n\nYour membership expires on {{expiry_date}}.",
                "use_html": 0
            },
            {
                "name": "Payment Confirmation",
                "subject": "Payment Received - {{amount}}",
                "message": "Thank you for your payment of {{amount}} on {{payment_date}}.",
                "use_html": 0
            },
            {
                "name": "Volunteer Assignment",
                "subject": "New Volunteer Assignment: {{team_name}}",
                "message": "You have been assigned to {{team_name}} starting {{start_date}}.",
                "use_html": 0
            }
        ]

        for template_data in templates:
            # Frappe's Email Template stores the body in 'response', not 'message'.
            existing = frappe.db.exists("Email Template", template_data["name"])
            template = (
                frappe.get_doc("Email Template", template_data["name"])
                if existing
                else frappe.new_doc("Email Template")
            )
            for key, value in template_data.items():
                setattr(template, "response" if key == "message" else key, value)
            template.save()
            if not existing:
                self._track_test_document("Email Template", template.name)

    def test_email_template_rendering_validation(self):
        """Test email template rendering with various member data scenarios"""
        # Create test member with complete data
        member = self.factory.create_test_member(
            first_name="Template",
            last_name="Test",
            email=f"template.test.{self.factory.test_run_id}@example.com",
        )

        membership = self.factory.create_test_membership(
            member=member.name,
            membership_type=self.regular_membership.name,
        )

        # Test Welcome Template Rendering
        welcome_template = frappe.get_doc("Email Template", "Welcome New Member")

        context = {
            "member_name": f"{member.first_name} {member.last_name}",
            "organization_name": "Test Organization",
            "membership_type": membership.membership_type,
            "start_date": membership.start_date
        }

        # Render subject and message
        rendered_subject = frappe.render_template(welcome_template.subject, context)
        rendered_message = frappe.render_template(welcome_template.response, context)

        # Verify template rendering
        self.assertEqual(rendered_subject, "Welcome to Test Organization!")
        self.assertIn("Template Test", rendered_message)
        self.assertIn("Welcome to our organization", rendered_message)

        # Test Renewal Reminder Template
        renewal_template = frappe.get_doc("Email Template", "Membership Renewal Reminder")

        renewal_context = {
            "member_name": f"{member.first_name} {member.last_name}",
            "expiry_date": membership.get("renewal_date") or add_days(today(), 30)
        }

        rendered_renewal_subject = frappe.render_template(renewal_template.subject, renewal_context)
        rendered_renewal_message = frappe.render_template(renewal_template.response, renewal_context)

        self.assertEqual(rendered_renewal_subject, "Time to Renew Your Membership")
        self.assertIn("Template Test", rendered_renewal_message)
        self.assertIn(str(renewal_context["expiry_date"]), rendered_renewal_message)

        # Test with missing context variables. Frappe's Jinja environment uses
        # the default (lenient) Undefined, so an unknown variable renders to an
        # empty string rather than raising. Assert that graceful behaviour.
        incomplete_context = {"member_name": "Test User"}
        rendered_incomplete = frappe.render_template(
            "Hello {{missing_variable}}", incomplete_context
        )
        # Rendering must not raise; the missing variable is handled leniently.
        self.assertIsInstance(rendered_incomplete, str)
        self.assertIn("Hello", rendered_incomplete)

    def test_notification_triggers_across_user_roles(self):
        """Test notification triggers for different user roles and events"""
        # Mock email sending to capture notifications
        sent_emails = []

        def mock_send_email(recipients, subject, message, **kwargs):
            sent_emails.append({
                "recipients": recipients,
                "subject": subject,
                "message": message,
                "kwargs": kwargs
            })
            return True

        # Mock justified: External Service - SMTP delivery, not business logic
        with patch('frappe.sendmail', side_effect=mock_send_email):
            # Test 1: New Member Creation Notification
            member = self.factory.create_test_member(
                first_name="Notification",
                last_name="Test",
                email=f"notification.test.{self.factory.test_run_id}@example.com",
                chapter=self.test_chapter.name
            )

            # Create membership for the member
            membership = self.factory.create_test_membership(
                member=member.name,
                membership_type=self.regular_membership.name
            )

            # Trigger notification (simulate new member workflow)
            self._trigger_new_member_notification(member, membership)

            # Test 2: Membership Expiry Notification
            member = self.factory.create_test_member(
                first_name="Expiry",
                last_name="Test",
                email=f"expiry.test.{self.factory.test_run_id}@example.com"
            )

            membership = self.factory.create_test_membership(
                member=member.name,
                membership_type=self.regular_membership.name,
                renewal_date=add_days(today(), 7),  # Expires in 7 days
            )

            # Trigger expiry notification
            self._trigger_expiry_notification(membership)

            # Test 3: Payment Failure Notification
            # NOTE: "Member Payment History" is a child table (istable=1), so it
            # cannot be created/saved standalone. The notification trigger below
            # only reads member/amount/failure_reason, so a lightweight stand-in
            # carrying those attributes is sufficient to exercise the workflow.
            payment_history = frappe._dict(
                member=member.name,
                payment_date=today(),
                amount=25.00,
                status="Failed",
                failure_reason="Insufficient funds",
            )

            # Trigger payment failure notification
            self._trigger_payment_failure_notification(payment_history)

            # Test 4: Volunteer Assignment Notification
            volunteer = self.factory.create_test_volunteer(
                member=member.name,
                email=f"volunteer.{self.factory.test_run_id}@example.com"
            )

            # Create volunteer assignment.
            # NOTE: "Volunteer Assignment" is a child table (istable=1) and has no
            # volunteer/team/assigned_by fields, so it cannot be created standalone.
            # The notification trigger only reads volunteer/team/start_date, so a
            # lightweight stand-in carrying those attributes is sufficient.
            assignment = frappe._dict(
                volunteer=volunteer.name,
                team="Communications Team",
                start_date=today(),
                assigned_by=self.volunteer_coordinator.name,
            )

            # Trigger volunteer assignment notification
            self._trigger_volunteer_assignment_notification(assignment)

        # Verify notifications were sent
        self.assertGreater(len(sent_emails), 0, "At least one notification should be sent")

        # Verify role-based notification targeting
        admin_notifications = [email for email in sent_emails
                              if self.admin_user.email in email.get("recipients", [])]
        manager_notifications = [email for email in sent_emails
                               if self.chapter_manager.email in email.get("recipients", [])]

        # Verify different roles receive appropriate notifications
        self.assertGreater(len(admin_notifications) + len(manager_notifications), 0,
                          "Role-based notifications should be sent")

    def _trigger_new_member_notification(self, member, membership):
        """Simulate new member notification trigger"""
        # In real system, this would be triggered by workflow
        frappe.sendmail(
            recipients=[self.chapter_manager.email, self.admin_user.email],
            subject=f"New Member Added: {member.first_name} {member.last_name}",
            message=f"A new member has been added: {member.first_name} {member.last_name} with membership {membership.name}"
        )

    def _trigger_expiry_notification(self, membership):
        """Simulate membership expiry notification"""
        member = frappe.get_doc("Member", membership.member)
        frappe.sendmail(
            recipients=[member.email],
            subject="Membership Renewal Reminder",
            message=f"Your membership expires on {membership.get('renewal_date')}"
        )

    def _trigger_payment_failure_notification(self, payment_history):
        """Simulate payment failure notification"""
        member = frappe.get_doc("Member", payment_history.member)
        frappe.sendmail(
            recipients=[member.email, self.chapter_manager.email],
            subject="Payment Failed",
            message=f"Payment of {payment_history.amount} failed due to: {payment_history.failure_reason}"
        )

    def _trigger_volunteer_assignment_notification(self, assignment):
        """Simulate volunteer assignment notification"""
        volunteer = frappe.get_doc("Volunteer", assignment.volunteer)
        frappe.sendmail(
            recipients=[volunteer.email],
            subject=f"New Assignment: {assignment.team}",
            message=f"You have been assigned to {assignment.team} starting {assignment.start_date}"
        )

    @unittest.skip(
        "Depends on 'Communication Preferences' and 'Communication Unsubscribe' "
        "doctypes which do not exist in this app (never implemented). FLAG: needs "
        "either the doctypes built or the test rewritten against real comms model."
    )
    def test_communication_preferences_workflow(self):
        """Test member communication preferences and opt-out workflows"""
        # Create member with specific communication preferences
        member = self.factory.create_test_member(
            first_name="Preference",
            last_name="Test",
            email=f"preference.test.{self.factory.test_run_id}@example.com",
            preferred_language="English",
            email_notifications=1,
            sms_notifications=0
        )

        # Create communication preferences record
        preferences = frappe.new_doc("Communication Preferences")
        preferences.member = member.name
        preferences.email_newsletters = 1
        preferences.email_reminders = 1
        preferences.email_marketing = 0  # Opted out
        preferences.sms_reminders = 0
        preferences.postal_mail = 1
        preferences.save()
        self._track_test_document("Communication Preferences", preferences.name)

        # Test preference validation
        self.assertTrue(preferences.email_newsletters)
        self.assertTrue(preferences.email_reminders)
        self.assertFalse(preferences.email_marketing)

        # Test communication filtering based on preferences
        communication_scenarios = [
            {
                "type": "newsletter",
                "allowed": preferences.email_newsletters,
                "message": "Monthly Newsletter"
            },
            {
                "type": "reminder",
                "allowed": preferences.email_reminders,
                "message": "Payment Reminder"
            },
            {
                "type": "marketing",
                "allowed": preferences.email_marketing,
                "message": "Special Offer"
            }
        ]

        for scenario in communication_scenarios:
            should_send = self._check_communication_permission(
                member.name, scenario["type"], preferences
            )
            self.assertEqual(should_send, scenario["allowed"],
                           f"Communication permission incorrect for {scenario['type']}")

        # Test opt-out workflow
        # Simulate member clicking unsubscribe link
        unsubscribe_token = frappe.generate_hash(length=32)

        # Create unsubscribe record
        unsubscribe = frappe.new_doc("Communication Unsubscribe")
        unsubscribe.member = member.name
        unsubscribe.email = member.email
        unsubscribe.unsubscribe_token = unsubscribe_token
        unsubscribe.communication_type = "All Marketing"
        unsubscribe.unsubscribe_date = now_datetime()
        unsubscribe.save()
        self._track_test_document("Communication Unsubscribe", unsubscribe.name)

        # Update preferences based on unsubscribe
        preferences.email_marketing = 0
        preferences.email_newsletters = 0  # Unsubscribed from all marketing
        preferences.save()

        # Verify updated preferences
        self.assertFalse(preferences.email_marketing)
        self.assertFalse(preferences.email_newsletters)
        self.assertTrue(preferences.email_reminders)  # Should still receive reminders

    def _check_communication_permission(self, member_name, communication_type, preferences):
        """Check if member should receive specific communication type"""
        type_mapping = {
            "newsletter": preferences.email_newsletters,
            "reminder": preferences.email_reminders,
            "marketing": preferences.email_marketing
        }
        return type_mapping.get(communication_type, False)

    def test_multi_language_content_delivery(self):
        """Test multi-language content delivery and template selection"""
        # Create members with different language preferences
        members_languages = [
            ("Dutch", "nl"),
            ("English", "en"),
            ("German", "de"),
            ("French", "fr")
        ]

        created_members = []
        for language, lang_code in members_languages:
            member = self.factory.create_test_member(
                first_name=f"{language}",
                last_name="Speaker",
                email=f"{lang_code}.speaker.{self.factory.test_run_id}@example.com",
            )
            created_members.append((member, language, lang_code))

        # Create multi-language email templates
        template_translations = {
            "Welcome New Member": {
                "en": {
                    "subject": "Welcome to {{organization_name}}!",
                    "message": "Dear {{member_name}},\n\nWelcome to our organization!"
                },
                "nl": {
                    "subject": "Welkom bij {{organization_name}}!",
                    "message": "Beste {{member_name}},\n\nWelkom bij onze organisatie!"
                },
                "de": {
                    "subject": "Willkommen bei {{organization_name}}!",
                    "message": "Liebe/r {{member_name}},\n\nWillkommen in unserer Organisation!"
                },
                "fr": {
                    "subject": "Bienvenue chez {{organization_name}}!",
                    "message": "Cher/Chère {{member_name}},\n\nBienvenue dans notre organisation!"
                }
            }
        }

        # Create language-specific templates
        for template_name, translations in template_translations.items():
            for lang_code, content in translations.items():
                template_lang_name = f"{template_name} - {lang_code.upper()}"

                lang_existing = frappe.db.exists("Email Template", template_lang_name)
                template = (
                    frappe.get_doc("Email Template", template_lang_name)
                    if lang_existing
                    else frappe.new_doc("Email Template")
                )
                template.name = template_lang_name
                template.subject = content["subject"]
                # Email Template stores the body in 'response', not 'message'.
                template.response = content["message"]
                template.save()
                if not lang_existing:
                    self._track_test_document("Email Template", template.name)

        # Test language-specific template selection
        for member, language, lang_code in created_members:
            # Get appropriate template for member's language
            template_name = self._get_template_for_language("Welcome New Member", lang_code)

            if template_name:
                template = frappe.get_doc("Email Template", template_name)

                context = {
                    "member_name": f"{member.first_name} {member.last_name}",
                    "organization_name": "Test Organization"
                }

                rendered_subject = frappe.render_template(template.subject, context)
                rendered_message = frappe.render_template(template.response, context)

                # Verify language-appropriate content
                if lang_code == "nl":
                    self.assertIn("Welkom", rendered_subject)
                    self.assertIn("Beste", rendered_message)
                elif lang_code == "de":
                    self.assertIn("Willkommen", rendered_subject)
                    self.assertIn("Liebe", rendered_message)
                elif lang_code == "fr":
                    self.assertIn("Bienvenue", rendered_subject)
                    self.assertIn("Cher", rendered_message)
                else:  # English default
                    self.assertIn("Welcome", rendered_subject)
                    self.assertIn("Dear", rendered_message)

                # Verify member name is correctly inserted
                self.assertIn(f"{member.first_name} {member.last_name}", rendered_message)

    def _get_template_for_language(self, base_template_name, lang_code):
        """Get language-specific template name"""
        lang_template_name = f"{base_template_name} - {lang_code.upper()}"

        if frappe.db.exists("Email Template", lang_template_name):
            return lang_template_name

        # Fallback to English
        english_template_name = f"{base_template_name} - EN"
        if frappe.db.exists("Email Template", english_template_name):
            return english_template_name

        # Final fallback to base template
        if frappe.db.exists("Email Template", base_template_name):
            return base_template_name

        return None

    def test_email_delivery_validation(self):
        """Test email delivery tracking and failure handling"""
        # Create test member for context
        self.factory.create_test_member(
            first_name="Delivery",
            last_name="Test",
            email=f"delivery.test.{self.factory.test_run_id}@example.com"
        )

        # Test email delivery scenarios
        delivery_scenarios = [
            {
                "email": "valid@example.com",
                "expected_status": "Sent",
                "should_succeed": True
            },
            {
                "email": "invalid-email-format",
                "expected_status": "Failed",
                "should_succeed": False
            },
            {
                # The synchronous send succeeds; the bounce is an asynchronous
                # event handled separately (see mock + bounced_communications check),
                # so the send call itself must be treated as a success.
                "email": "bounced@example.com",
                "expected_status": "Bounced",
                "should_succeed": True
            }
        ]

        sent_communications = []

        # Mock email sending with different outcomes
        def mock_send_email_with_outcomes(recipients, subject, message, **kwargs):
            recipient_email = recipients[0] if isinstance(recipients, list) else recipients

            # Simulate different delivery outcomes
            if "invalid-email-format" in recipient_email:
                raise frappe.ValidationError("Invalid email format")
            elif "bounced@example.com" in recipient_email:
                # Simulate successful send but later bounce
                communication_log = {
                    "recipient": recipient_email,
                    "subject": subject,
                    "status": "Sent",
                    "sent_at": now_datetime()
                }
                sent_communications.append(communication_log)
                # Simulate bounce handling
                frappe.get_hooks("email_bounced", [lambda: self._handle_email_bounce(recipient_email)])
                return True
            else:
                # Successful delivery
                communication_log = {
                    "recipient": recipient_email,
                    "subject": subject,
                    "status": "Sent",
                    "sent_at": now_datetime()
                }
                sent_communications.append(communication_log)
                return True

        # Mock justified: External Service - SMTP delivery, not business logic
        with patch('frappe.sendmail', side_effect=mock_send_email_with_outcomes):
            for scenario in delivery_scenarios:
                try:
                    # Attempt to send email
                    frappe.sendmail(
                        recipients=[scenario["email"]],
                        subject="Test Email Delivery",
                        message="This is a test email for delivery validation."
                    )

                    if not scenario["should_succeed"]:
                        self.fail(f"Expected failure for {scenario['email']} but succeeded")

                except frappe.ValidationError:
                    if scenario["should_succeed"]:
                        self.fail(f"Expected success for {scenario['email']} but failed")

        # Verify communication logs
        successful_sends = [comm for comm in sent_communications
                           if comm["status"] == "Sent"]

        self.assertGreater(len(successful_sends), 0, "At least one email should be sent successfully")

        # Test bounce handling
        bounced_communications = [comm for comm in sent_communications
                                if "bounced@example.com" in comm["recipient"]]

        if bounced_communications:
            self.assertEqual(len(bounced_communications), 1)

    def _handle_email_bounce(self, email):
        """Handle email bounce notification"""
        # In real system, this would update member communication preferences
        # and possibly create a bounce log entry
        bounce_log = {
            "email": email,
            "bounce_date": now_datetime(),
            "bounce_type": "Hard Bounce",
            "action_taken": "Disabled email notifications"
        }
        # Would save to database in real implementation
        return bounce_log


def run_communication_system_tests():
    """Run communication system integration tests"""
    print("📧 Running Communication System Integration Tests...")

    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCommunicationSystemIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All communication system tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_communication_system_tests()
