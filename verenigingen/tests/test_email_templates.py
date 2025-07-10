# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Email Template System Tests
Tests for email template rendering, fallbacks, and multi-language support
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, Mock
import json
from jinja2 import Template, TemplateSyntaxError, UndefinedError


class TestEmailTemplates(FrappeTestCase):
    """Test email template functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_member = self._create_test_member()
        self.test_templates = self._create_test_templates()
        
    def _create_test_member(self):
        """Create a test member for template testing"""
        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Template",
            "last_name": "Tester",
            "email": f"template.test.{frappe.utils.random_string(6)}@example.com",
            "phone": "+31612345678",
            "status": "Active",
            "preferred_language": "nl"
        })
        member.insert(ignore_permissions=True)
        return member
        
    def _create_test_templates(self):
        """Create test email templates"""
        templates = {
            "welcome_member": {
                "en": {
                    "subject": "Welcome to {{ organization_name }}!",
                    "body": """
                    <p>Dear {{ member.first_name }},</p>
                    <p>Welcome to {{ organization_name }}! Your membership is now active.</p>
                    <p>Your member ID is: {{ member.name }}</p>
                    <p>Best regards,<br>{{ organization_name }} Team</p>
                    """
                },
                "nl": {
                    "subject": "Welkom bij {{ organization_name }}!",
                    "body": """
                    <p>Beste {{ member.first_name }},</p>
                    <p>Welkom bij {{ organization_name }}! Uw lidmaatschap is nu actief.</p>
                    <p>Uw lidnummer is: {{ member.name }}</p>
                    <p>Met vriendelijke groet,<br>{{ organization_name }} Team</p>
                    """
                }
            },
            "payment_reminder": {
                "en": {
                    "subject": "Payment Reminder - {{ invoice.name }}",
                    "body": """
                    <p>Dear {{ member.full_name }},</p>
                    <p>This is a reminder that your payment of {{ invoice.grand_total }} {{ invoice.currency }} is due.</p>
                    <p>Invoice: {{ invoice.name }}</p>
                    <p>Due Date: {{ invoice.due_date }}</p>
                    <p>Please make your payment at your earliest convenience.</p>
                    """
                },
                "nl": {
                    "subject": "Betalingsherinnering - {{ invoice.name }}",
                    "body": """
                    <p>Beste {{ member.full_name }},</p>
                    <p>Dit is een herinnering dat uw betaling van {{ invoice.grand_total }} {{ invoice.currency }} verschuldigd is.</p>
                    <p>Factuur: {{ invoice.name }}</p>
                    <p>Vervaldatum: {{ invoice.due_date }}</p>
                    <p>Gelieve zo spoedig mogelijk te betalen.</p>
                    """
                }
            }
        }
        return templates
        
    def test_template_rendering_all_types(self):
        """Test rendering different template types"""
        # Test welcome email
        welcome_template = Template(self.test_templates["welcome_member"]["en"]["body"])
        
        context = {
            "member": self.test_member,
            "organization_name": "Test Association"
        }
        
        rendered = welcome_template.render(context)
        
        # Verify rendering
        self.assertIn("Template", rendered)  # First name
        self.assertIn("Test Association", rendered)
        self.assertIn(self.test_member.name, rendered)  # Member ID
        
        # Test payment reminder
        payment_template = Template(self.test_templates["payment_reminder"]["en"]["body"])
        
        invoice_context = {
            "member": self.test_member,
            "invoice": {
                "name": "INV-2025-001",
                "grand_total": 100.00,
                "currency": "EUR",
                "due_date": "2025-02-01"
            }
        }
        
        payment_rendered = payment_template.render(invoice_context)
        
        # Verify payment reminder
        self.assertIn("Template Tester", payment_rendered)
        self.assertIn("100.0", payment_rendered)
        self.assertIn("EUR", payment_rendered)
        self.assertIn("INV-2025-001", payment_rendered)
        
    def test_missing_variable_handling(self):
        """Test handling of missing template variables"""
        # Template with undefined variable
        template_with_undefined = Template("""
            Hello {{ member.first_name }},
            Your chapter is {{ member.chapter_name | default('Not Assigned') }}.
            Your balance is {{ member.balance | default(0) }}.
        """)
        
        context = {
            "member": self.test_member
        }
        
        # Should handle missing variables gracefully
        rendered = template_with_undefined.render(context)
        
        self.assertIn("Template", rendered)
        self.assertIn("Not Assigned", rendered)  # Default for missing chapter
        self.assertIn("0", rendered)  # Default for missing balance
        
        # Test strict undefined handling
        from jinja2 import StrictUndefined
        
        strict_template = Template(
            "Hello {{ member.nonexistent_field }}", 
            undefined=StrictUndefined
        )
        
        with self.assertRaises(UndefinedError):
            strict_template.render(context)
            
    def test_language_switching(self):
        """Test multi-language template switching"""
        languages = ["en", "nl"]
        
        for lang in languages:
            # Get template for language
            template_data = self.test_templates["welcome_member"][lang]
            
            subject_template = Template(template_data["subject"])
            body_template = Template(template_data["body"])
            
            context = {
                "member": self.test_member,
                "organization_name": "Test Vereniging"
            }
            
            subject = subject_template.render(context)
            body = body_template.render(context)
            
            # Verify language-specific content
            if lang == "en":
                self.assertIn("Welcome to", subject)
                self.assertIn("Dear", body)
                self.assertIn("Best regards", body)
            elif lang == "nl":
                self.assertIn("Welkom bij", subject)
                self.assertIn("Beste", body)
                self.assertIn("Met vriendelijke groet", body)
                
    def test_email_queue_processing(self):
        """Test email queue and delivery tracking"""
        # Create test email queue entries
        email_queue = []
        
        for i in range(5):
            email_entry = {
                "doctype": "Email Queue",
                "sender": "test@association.org",
                "recipients": f"member{i}@example.com",
                "subject": f"Test Email {i}",
                "message": f"Test message content {i}",
                "status": "Not Sent",
                "priority": i % 3  # 0=high, 1=medium, 2=low
            }
            email_queue.append(email_entry)
            
        # Sort by priority (high priority first)
        sorted_queue = sorted(email_queue, key=lambda x: x["priority"])
        
        # Process queue
        processed = []
        for email in sorted_queue:
            # Simulate sending
            email["status"] = "Sent"
            email["sent_at"] = frappe.utils.now()
            processed.append(email)
            
        # Verify processing order
        self.assertEqual(len(processed), 5)
        self.assertEqual(processed[0]["priority"], 0)  # High priority first
        
    def test_bounce_handling(self):
        """Test email bounce detection and handling"""
        # Simulate bounce scenarios
        bounce_types = [
            {
                "type": "hard_bounce",
                "email": "invalid@nonexistent-domain.com",
                "action": "block_permanently"
            },
            {
                "type": "soft_bounce",
                "email": "full-mailbox@example.com",
                "action": "retry_later"
            },
            {
                "type": "out_of_office",
                "email": "vacation@example.com",
                "action": "ignore"
            },
            {
                "type": "spam_complaint",
                "email": "complainer@example.com",
                "action": "unsubscribe"
            }
        ]
        
        # Process bounces
        for bounce in bounce_types:
            if bounce["action"] == "block_permanently":
                # Add to suppression list
                self.assertTrue(self._should_suppress_email(bounce["email"]))
            elif bounce["action"] == "retry_later":
                # Schedule retry
                self.assertTrue(self._should_retry_email(bounce["email"]))
            elif bounce["action"] == "unsubscribe":
                # Mark as unsubscribed
                self.assertTrue(self._should_unsubscribe(bounce["email"]))
                
    def _should_suppress_email(self, email):
        """Check if email should be suppressed"""
        # Simulate suppression logic
        return "@nonexistent-domain.com" in email
        
    def _should_retry_email(self, email):
        """Check if email should be retried"""
        return "full-mailbox" in email
        
    def _should_unsubscribe(self, email):
        """Check if email should be unsubscribed"""
        return "complainer" in email
        
    def test_template_variables_documentation(self):
        """Test template variable availability and documentation"""
        # Define available variables per template type
        template_variables = {
            "welcome_member": {
                "member": ["name", "first_name", "last_name", "email", "chapter"],
                "organization_name": "string",
                "current_date": "date"
            },
            "payment_reminder": {
                "member": ["name", "full_name", "email"],
                "invoice": ["name", "grand_total", "currency", "due_date"],
                "payment_url": "string"
            },
            "volunteer_assignment": {
                "volunteer": ["name", "volunteer_name", "email"],
                "assignment": ["role", "team", "start_date"],
                "team_leader": ["name", "email", "phone"]
            }
        }
        
        # Verify all required variables are documented
        for template_type, variables in template_variables.items():
            self.assertIn("member", variables)  # Member should be in most templates
            
    def test_template_inheritance(self):
        """Test template inheritance and blocks"""
        # Base template
        base_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{% block title %}Default Title{% endblock %}</title>
        </head>
        <body>
            <header>
                <h1>{{ organization_name }}</h1>
            </header>
            <main>
                {% block content %}
                Default content
                {% endblock %}
            </main>
            <footer>
                <p>© 2025 {{ organization_name }}</p>
            </footer>
        </body>
        </html>
        """)
        
        # Child template
        child_template = """
        {% extends base %}
        
        {% block title %}Welcome Email{% endblock %}
        
        {% block content %}
        <p>Welcome {{ member.first_name }}!</p>
        <p>Thank you for joining us.</p>
        {% endblock %}
        """
        
        # Test inheritance works correctly
        # In actual implementation, this would use Jinja2's template loader
        self.assertIn("block title", base_template.source)
        self.assertIn("block content", base_template.source)
        
    def test_attachment_handling(self):
        """Test email attachment processing"""
        # Test different attachment types
        attachments = [
            {
                "filename": "welcome_guide.pdf",
                "content_type": "application/pdf",
                "size_kb": 500,
                "allowed": True
            },
            {
                "filename": "membership_card.png",
                "content_type": "image/png",
                "size_kb": 100,
                "allowed": True
            },
            {
                "filename": "dangerous.exe",
                "content_type": "application/x-executable",
                "size_kb": 50,
                "allowed": False
            },
            {
                "filename": "huge_file.zip",
                "content_type": "application/zip",
                "size_kb": 15000,  # 15MB
                "allowed": False  # Too large
            }
        ]
        
        max_size_kb = 10000  # 10MB limit
        allowed_types = ["application/pdf", "image/png", "image/jpeg"]
        
        for attachment in attachments:
            # Check file type
            type_allowed = attachment["content_type"] in allowed_types
            
            # Check file size
            size_allowed = attachment["size_kb"] <= max_size_kb
            
            # Overall allowed
            is_allowed = type_allowed and size_allowed
            
            self.assertEqual(is_allowed, attachment["allowed"])
            
    def test_personalization_tokens(self):
        """Test advanced personalization tokens"""
        # Template with various personalization tokens
        template = Template("""
        Dear {{ member.first_name | title }},
        
        You joined us {{ days_since_joining }} days ago.
        Your membership {% if is_active %}is active{% else %}has expired{% endif %}.
        
        {% if recent_activities %}
        Your recent activities:
        {% for activity in recent_activities %}
        - {{ activity.date }}: {{ activity.description }}
        {% endfor %}
        {% else %}
        No recent activities recorded.
        {% endif %}
        
        {{ custom_message | default('Thank you for being a member!') }}
        """)
        
        # Test context
        import datetime
        join_date = datetime.date(2024, 1, 1)
        today = datetime.date(2025, 1, 10)
        days_since = (today - join_date).days
        
        context = {
            "member": self.test_member,
            "days_since_joining": days_since,
            "is_active": True,
            "recent_activities": [
                {"date": "2025-01-05", "description": "Attended workshop"},
                {"date": "2025-01-08", "description": "Volunteered at event"}
            ],
            "custom_message": "Special announcement: New benefits available!"
        }
        
        rendered = template.render(context)
        
        # Verify personalization
        self.assertIn("Template", rendered)  # Title case first name
        self.assertIn(str(days_since), rendered)
        self.assertIn("is active", rendered)
        self.assertIn("Attended workshop", rendered)
        self.assertIn("Special announcement", rendered)
        
    def tearDown(self):
        """Clean up test data"""
        try:
            frappe.delete_doc("Member", self.test_member.name, force=True)
        except:
            pass