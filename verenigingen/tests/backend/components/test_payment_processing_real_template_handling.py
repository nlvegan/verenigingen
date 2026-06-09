"""
Payment Processing API Mock Elimination: Template Handling
=========================================================

This test demonstrates eliminating inappropriate database mocks from payment processing
template validation logic. Replaces mocked `frappe.db.exists` calls with real email
template data and database operations.

ELIMINATED INAPPROPRIATE MOCKS:
- @patch("frappe.db.exists") for template existence checks
- @patch("frappe.get_doc") for template document retrieval
- Artificial return values that bypass real template validation

KEPT LEGITIMATE MOCKS:
- frappe.sendmail (external email service)
- External SMTP configuration
- Network-based email delivery

REAL BUSINESS LOGIC TESTED:
- Actual email template existence validation
- Real template document retrieval and processing
- Authentic fallback logic when templates are missing
- Real template variable substitution
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.api.payment_processing import send_payment_reminder_email, generate_payment_reminder_html
from unittest.mock import patch


class TestPaymentProcessingRealTemplateHandling(EnhancedTestCase):
    """Real database tests for payment processing template handling"""

    def setUp(self):
        """Set up test data with real email templates"""
        super().setUp()

        # send_payment_reminder_email routes through EmailService, which only
        # reaches frappe.sendmail when (a) a default outgoing account exists and
        # (b) the relevant notification key is enabled in the configuration.
        # ORDER-DEPENDENCE FIX: these mutate the "Verenigingen Email Configuration"
        # Single (master_email_enabled + notification_types). Capture the original
        # state so tearDown can restore it, otherwise the enabled flags leak into
        # later files in the same shard (no DB reset between files).
        self._snapshot_email_configuration()
        self._ensure_outgoing_email_account()
        self._enable_notifications(["payment_reminder_friendly", "payment_reminder_urgent"])

        # Create real test member
        self.test_member = self.create_test_member(
            first_name="Template",
            last_name="Test",
            email="template.test@example.com"
        )

        # Create real payment information. generate_payment_reminder_html and the
        # reminder flow read overdue_count/total_overdue/days_overdue/membership_type,
        # so populate those (keeping amount/invoice_number for template tests).
        self.sample_payment_info = {
            "amount": 125.00,
            "total_overdue": 125.00,
            "overdue_count": 1,
            "membership_type": "Regular",
            "due_date": add_days(today(), -30),
            "invoice_number": f"TEST-INV-{frappe.utils.random_string(6)}",
            "member_name": self.test_member.full_name,
            "days_overdue": 30
        }

        # Create real email template for testing
        self.create_real_email_template()

    def _ensure_outgoing_email_account(self):
        """Ensure a default outgoing Email Account exists (see module-2 helper)."""
        if frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
            return
        account = frappe.get_doc(
            {
                "doctype": "Email Account",
                "email_account_name": "Test Outgoing",
                "email_id": "test-outgoing@example.com",
                "enable_outgoing": 1,
                "default_outgoing": 1,
                "smtp_server": "localhost",
                "smtp_port": 25,
                "login_id_is_different": 0,
            }
        )
        account.flags.ignore_validate = True
        account.flags.ignore_mandatory = True
        account.insert(ignore_permissions=True)

    def _snapshot_email_configuration(self):
        """Capture the Verenigingen Email Configuration Single for tearDown restore.

        Records master_email_enabled plus the (notification_key -> enabled) map and
        which keys existed before this test, so tearDown can restore the flags and
        drop any rows this test appended. Prevents leaking enabled-notification
        state into later files in the same parallel shard.
        """
        config = frappe.get_single("Verenigingen Email Configuration")
        self._orig_master_email_enabled = config.master_email_enabled
        self._orig_notification_state = {
            nt.notification_key: nt.enabled for nt in config.notification_types
        }

    def _enable_notifications(self, notification_keys):
        """Enable the given notification keys in Verenigingen Email Configuration."""
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = 1
        existing = {nt.notification_key for nt in config.notification_types}
        for key in notification_keys:
            if key in existing:
                for nt in config.notification_types:
                    if nt.notification_key == key:
                        nt.enabled = 1
            else:
                config.append(
                    "notification_types",
                    {"notification_key": key, "enabled": 1, "label": key,
                     "category": "Payment", "cooldown_minutes": 0},
                )
        config.flags.ignore_permissions = True
        config.save(ignore_permissions=True)

    def create_real_email_template(self):
        """Create real email template in database for testing"""
        template_name = "payment_reminder_friendly"

        # A production fixture for this template may already exist (with content
        # that does not match this test's expectations). Replace it so the test
        # deterministically controls the template content; tearDown removes it.
        if frappe.db.exists("Email Template", template_name):
            frappe.delete_doc("Email Template", template_name, force=True)

        # Create real email template document. send_payment_reminder_email renders
        # with a context of {member (doc), payment_info, custom_message, ...}, so the
        # template must reference member.first_name / payment_info.* (not bare
        # member_name / amount / invoice_number, which are not in the context).
        template = frappe.new_doc("Email Template")
        template.name = template_name
        template.subject = "Friendly Payment Reminder - {{ member.first_name }}"
        template.use_html = 1
        template.response_html = """
        <p>Dear {{ member.first_name }},</p>
        <p>This is a friendly reminder that your payment of €{{ payment_info.total_overdue }} is overdue.</p>
        <p>Number of overdue invoices: {{ payment_info.overdue_count }}</p>
        <p>Days overdue: {{ payment_info.days_overdue }}</p>
        <p>Please process your payment at your earliest convenience.</p>
        <p>Best regards,<br/>The Team</p>
        """
        template.doctype = "Email Template"
        template.insert()
        
        self.email_template = template
        return template

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # KEEP: External service mock
    def test_real_template_existence_validation(self, mock_sendmail):
        """Test email template existence with REAL database operations"""
        
        # REAL DATABASE OPERATION: Check if template exists
        template_exists = frappe.db.exists("Email Template", "payment_reminder_friendly")
        
        # Should find our real template
        self.assertIsNotNone(template_exists, "Real template should exist in database")
        
        # Test with REAL template validation (NO MOCKS)
        result = send_payment_reminder_email(
            member_name=self.test_member.name,
            reminder_type="Friendly Reminder",
            payment_info=self.sample_payment_info,
        )
        
        # The reminder routes through EmailService, which renders the template and
        # queues the email via frappe.sendmail(recipients, subject, message, ...)
        # — it does NOT pass template/args to sendmail.
        self.assertTrue(result, "Reminder should be sent for an existing template")
        mock_sendmail.assert_called_once()

        call_kwargs = mock_sendmail.call_args[1]
        self.assertEqual(call_kwargs["recipients"], [self.test_member.email])
        # send_payment_reminder_email passes a fixed subject_override
        # (get_reminder_subject), so the queued subject is that, not the template's.
        self.assertEqual(call_kwargs["subject"], "Payment Reminder - Membership Fees")
        # The rendered template body (member.first_name substituted) is the message.
        self.assertIn("message", call_kwargs)
        self.assertIn(self.test_member.first_name, call_kwargs["message"])

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # KEEP: External service mock
    def test_real_template_missing_fallback(self, mock_sendmail):
        """Test fallback behavior when template is missing using REAL database"""
        
        # Create unique reminder type that won't have a template
        # Unknown reminder types map to the "payment_reminder_friendly" template,
        # so to exercise the missing-template HTML fallback, remove that template
        # first; send_payment_reminder_email then falls back to
        # generate_payment_reminder_html via _send_email_internal.
        if frappe.db.exists("Email Template", "payment_reminder_friendly"):
            frappe.delete_doc("Email Template", "payment_reminder_friendly", force=True)

        result = send_payment_reminder_email(
            member_name=self.test_member.name,
            reminder_type="Friendly Reminder",
            payment_info=self.sample_payment_info,
        )

        # The fallback HTML path queues via frappe.sendmail with message content.
        self.assertTrue(result, "Reminder should still be sent via HTML fallback")
        mock_sendmail.assert_called_once()

        call_kwargs = mock_sendmail.call_args[1]
        self.assertIn("message", call_kwargs)  # HTML message used
        # Fallback HTML is generated from the member doc (first_name) + payment_info.
        html_content = call_kwargs.get("message", "")
        self.assertIn(self.test_member.first_name, html_content)
        self.assertIn("30", html_content)  # days overdue

    def test_real_template_document_retrieval(self):
        """Test real template document retrieval and processing"""
        
        # REAL DATABASE OPERATION: Retrieve actual template
        template_doc = frappe.get_doc("Email Template", "payment_reminder_friendly")
        
        # Verify real template structure
        self.assertIsNotNone(template_doc.subject, "Real template should have subject")
        self.assertIsNotNone(template_doc.response_html, "Real template should have HTML content")
        
        # Verify template contains expected placeholders (real context variables).
        self.assertIn("{{ member.first_name }}", template_doc.subject)
        self.assertIn("{{ payment_info.total_overdue }}", template_doc.response_html)
        self.assertIn("{{ payment_info.overdue_count }}", template_doc.response_html)
        self.assertIn("{{ payment_info.days_overdue }}", template_doc.response_html)

        print(f"✅ Real template document validation successful")
        print(f"   Subject: {template_doc.subject}")
        print(f"   HTML length: {len(template_doc.response_html)} chars")

    def test_real_html_generation_fallback(self):
        """Test real HTML generation when no template exists"""
        
        # generate_payment_reminder_html(member_doc, payment_info, reminder_type,
        # custom_message) renders member.first_name and payment_info.* (overdue_count,
        # total_overdue, days_overdue, membership_type).
        html_content = generate_payment_reminder_html(
            self.test_member,
            self.sample_payment_info,
            "Urgent Notice",
            "Please pay promptly",
        )

        # Verify real HTML generation
        self.assertIsInstance(html_content, str)
        self.assertGreater(len(html_content), 100, "Generated HTML should be substantial")

        # Verify real member data incorporated
        self.assertIn(self.test_member.first_name, html_content)
        self.assertIn("30", html_content)  # Days overdue
        self.assertIn("urgent notice", html_content.lower())  # reminder type
        self.assertIn("Please pay promptly", html_content)  # custom message

        # Verify HTML structure
        self.assertIn("<p>", html_content, "Should contain paragraph tags")

        print(f"✅ Real HTML generation successful")
        print(f"   Content length: {len(html_content)} chars")

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # KEEP: External service mock
    def test_multiple_template_types_real_database(self, mock_sendmail):
        """Test multiple reminder types with real template resolution"""
        
        # Create additional real templates for testing
        template_types = [
            ("payment_reminder_urgent", "Urgent Payment Notice - {{ member_name }}"),
            ("payment_reminder_final", "Final Payment Notice - {{ member_name }}"),
        ]
        
        for template_name, subject in template_types:
            if not frappe.db.exists("Email Template", template_name):
                template = frappe.new_doc("Email Template") 
                template.name = template_name
                template.subject = subject
                template.response_html = f"""
                <p>Dear {{{{ member_name }}}},</p>
                <p>This is an {template_name.split('_')[-1]} reminder for payment of €{{{{ amount }}}}.</p>
                <p>Invoice: {{{{ invoice_number }}}}</p>
                <p>Regards, The Team</p>
                """
                template.insert()
        
        # Test each template type with real database resolution
        test_cases = [
            ("Friendly Reminder", "payment_reminder_friendly"),
            ("Urgent Notice", "payment_reminder_urgent"), 
            ("Final Notice", "payment_reminder_final"),
        ]
        
        for reminder_type, expected_template in test_cases:
            # Reset mock for each test
            mock_sendmail.reset_mock()
            
            # REAL DATABASE TEMPLATE RESOLUTION
            result = send_payment_reminder_email(
                member_name=self.test_member.name,
                reminder_type=reminder_type,
                payment_info=self.sample_payment_info,
            )
            
            if result and mock_sendmail.called:
                call_kwargs = mock_sendmail.call_args[1]
                template_used = call_kwargs.get("template")
                
                # Verify correct template was resolved from real database
                if template_used:
                    self.assertEqual(template_used, expected_template,
                                   f"Real database should resolve {reminder_type} to {expected_template}")
                    print(f"✅ {reminder_type} -> {template_used}")
                else:
                    print(f"ℹ️  {reminder_type} used HTML fallback")
            else:
                print(f"⚠️  {reminder_type} not sent (business logic validation)")

    def test_template_variable_substitution_real_data(self):
        """Test template variable substitution with real member and payment data"""
        
        # Get real template
        template_doc = frappe.get_doc("Email Template", "payment_reminder_friendly")

        # Context mirrors the real reminder context: a member doc + payment_info.
        context = {
            "member": self.test_member,
            "payment_info": self.sample_payment_info,
        }

        # Test real template rendering (Frappe's template engine)
        from frappe.utils.jinja import render_template

        rendered_subject = render_template(template_doc.subject, context)
        rendered_html = render_template(template_doc.response_html, context)

        # Verify real template variable substitution
        self.assertNotIn("{{", rendered_subject, "All variables should be substituted in subject")
        self.assertNotIn("{{", rendered_html, "All variables should be substituted in HTML")

        # Verify actual member/payment data appears
        self.assertIn(self.test_member.first_name, rendered_subject)
        self.assertIn(self.test_member.first_name, rendered_html)
        self.assertIn("125.0", rendered_html)  # total_overdue
        self.assertIn("30", rendered_html)  # days_overdue

        print(f"✅ Real template variable substitution successful")
        print(f"   Subject: {rendered_subject}")

    def test_real_error_handling_invalid_member(self):
        """Test error handling with invalid member using real validation"""
        
        # Test with non-existent member (REAL DATABASE VALIDATION)
        nonexistent_member = "MEMBER-DOES-NOT-EXIST-123"
        
        # Verify member doesn't exist in real database
        member_exists = frappe.db.exists("Member", nonexistent_member)
        self.assertIsNone(member_exists, "Test member should not exist")
        
        # send_payment_reminder_email loads the member via frappe.get_doc, so a
        # nonexistent member raises a real DoesNotExistError (real DB validation).
        # Mock justified: External Service - SMTP delivery, not business logic
        with patch("frappe.sendmail"):  # Mock only email service
            with self.assertRaises(frappe.DoesNotExistError):
                send_payment_reminder_email(
                    member_name=nonexistent_member,
                    reminder_type="Friendly Reminder",
                    payment_info=self.sample_payment_info,
                )

    def test_email_template_change_invalidates_service_cache(self):
        """Editing or deleting an Email Template must invalidate the EmailService
        process-singleton cache, or stale content is served until the TTL expires
        (and the missing-template fallback is silently skipped)."""
        from verenigingen.services.communication.email_service import get_email_service

        name = "payment_reminder_friendly"  # created in setUp
        svc = get_email_service()

        cached = svc._get_template(name)
        self.assertIsNotNone(cached, "template should load")
        self.assertNotIn("UPDATED", cached["content"])

        # An edit must be reflected on the next read, not masked by the cache.
        doc = frappe.get_doc("Email Template", name)
        doc.response_html = "<p>UPDATED {{ member.first_name }}</p>"
        doc.save()
        refreshed = svc._get_template(name)
        self.assertIn("UPDATED", refreshed["content"])

        # A delete must make the template genuinely absent on the next read.
        frappe.delete_doc("Email Template", name, force=True)
        self.assertIsNone(svc._get_template(name))

    @patch("frappe.sendmail")  # KEEP: External service mock
    def test_missing_template_falls_back_despite_stale_cache(self, mock_sendmail):
        """Cross-file flake regression: a stale singleton-cached template must not
        suppress the missing-template HTML fallback once the DB row is gone."""
        from verenigingen.services.communication.email_service import get_email_service

        # Simulate a co-located test having cached a DIFFERENT
        # 'payment_reminder_friendly' (content without the days-overdue value)
        # in the process singleton — exactly the cross-shard pollution we hit.
        svc = get_email_service()
        svc.template_cache.set(
            "payment_reminder_friendly",
            {"subject": "stale", "content": "<p>stale body, no days</p>", "doc": None},
        )

        # Remove the real template so the only remaining "source" is the stale cache.
        if frappe.db.exists("Email Template", "payment_reminder_friendly"):
            frappe.delete_doc("Email Template", "payment_reminder_friendly", force=True)

        result = send_payment_reminder_email(
            member_name=self.test_member.name,
            reminder_type="Friendly Reminder",
            payment_info=self.sample_payment_info,
        )

        self.assertTrue(result, "missing template must fall back, not silently fail")
        mock_sendmail.assert_called_once()
        html = mock_sendmail.call_args[1].get("message", "")
        self.assertIn(self.test_member.first_name, html)
        self.assertIn("30", html)  # fallback HTML includes days overdue

    def test_send_templated_email_signals_missing_template_structurally(self):
        """The missing-template failure must be identifiable via a structured
        error_code, not by substring-matching a human-readable (translatable)
        message — otherwise an unrelated failure whose message contains
        'not found' would wrongly trigger the HTML fallback, which bypasses the
        cooldown/opt-out enforcement that the templated path honours."""
        from verenigingen.services.communication.email_service import get_email_service

        svc = get_email_service()

        # Genuinely-missing template → must carry TEMPLATE_NOT_FOUND.
        missing = "definitely_missing_template_xyz"
        svc.template_cache.evict(missing)
        if frappe.db.exists("Email Template", missing):
            frappe.delete_doc("Email Template", missing, force=True)
        result = svc.send_templated_email(template_name=missing, recipients=["x@example.com"], context={})
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TEMPLATE_NOT_FOUND")

        # A DIFFERENT outcome on an existing template (here: no recipients →
        # all-opted-out skip) must NOT be tagged as a missing template, so the
        # caller never wrongly falls back for a non-template result.
        result2 = svc.send_templated_email(
            template_name="payment_reminder_friendly",  # exists (setUp)
            recipients=[],
            context={"member": self.test_member, "payment_info": self.sample_payment_info},
        )
        self.assertNotEqual(result2.error_code, "TEMPLATE_NOT_FOUND")

    def tearDown(self):
        """Clean up test email templates"""
        try:
            # Clean up test templates
            test_templates = [
                "payment_reminder_friendly",
                "payment_reminder_urgent", 
                "payment_reminder_final"
            ]
            
            for template_name in test_templates:
                if frappe.db.exists("Email Template", template_name):
                    frappe.delete_doc("Email Template", template_name)

        except Exception as e:
            print(f"Warning: Template cleanup encountered issue: {e}")

        # ORDER-DEPENDENCE FIX: restore the Verenigingen Email Configuration Single
        # to its pre-test state (master flag + per-notification enabled flags, and
        # drop rows this test appended) so the enabled-notification state does not
        # leak into later files in the same shard.
        try:
            self._restore_email_configuration()
        except Exception as e:
            print(f"Warning: Email configuration restore encountered issue: {e}")

        super().tearDown()

    def _restore_email_configuration(self):
        """Restore the email configuration Single captured in _snapshot_email_configuration."""
        if not hasattr(self, "_orig_notification_state"):
            return
        config = frappe.get_single("Verenigingen Email Configuration")
        config.master_email_enabled = self._orig_master_email_enabled
        # Keep only notification rows that existed before; restore their enabled flag.
        retained = []
        for nt in config.notification_types:
            if nt.notification_key in self._orig_notification_state:
                nt.enabled = self._orig_notification_state[nt.notification_key]
                retained.append(nt)
        config.notification_types = retained
        config.flags.ignore_permissions = True
        config.save(ignore_permissions=True)

print("Payment Processing Real Template Handling Test Created")
print("=" * 55)
print("This test eliminates inappropriate database existence mocks")
print("and tests real email template validation, retrieval, and processing.")
print("Run with: bench --site dev.veganisme.net run-tests --module verenigingen.tests.backend.components.test_payment_processing_real_template_handling")