"""
Email and Newsletter Integration Boundary Testing
================================================

Comprehensive testing of email and newsletter service integration boundaries
for the Verenigingen association management system.

Critical business processes tested:
- Newsletter subscription management
- Bulk email campaign delivery
- Email bounce and unsubscribe handling
- Template rendering and personalization
- Email delivery tracking and analytics

@author Verenigingen Development Team
@version 1.0.0
"""

import frappe
from frappe.utils import today, add_months, flt, nowdate, now_datetime
from decimal import Decimal
import json
import requests_mock
from unittest.mock import patch, MagicMock, call
import uuid

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestNewsletterSubscriptionManagement(EnhancedTestCase):
    """
    Test newsletter subscription lifecycle and management

    Priority 1: Member communication and engagement
    """

    def setUp(self):
        """Set up newsletter integration test environment"""
        super().setUp()

        # Create test newsletter settings
        self.newsletter_settings = self.create_test_newsletter_settings()

    def create_test_newsletter_settings(self):
        """Create test newsletter service settings"""
        settings = frappe.new_doc("Newsletter Settings")
        settings.update({
            "service_provider": "Mailchimp",
            "api_key": "test_mailchimp_api_key",
            "list_id": "test_list_12345",
            "enabled": 1,
            "auto_subscribe_new_members": 1,
            "double_opt_in": 1
        })
        settings.insert()
        return settings

    def test_automatic_newsletter_subscription_on_member_creation(self):
        """
        Test automatic newsletter subscription when new member opts in

        Core workflow: Member Creation → Newsletter Subscription → Confirmation
        """
        with requests_mock.Mocker() as m:
            # Mock newsletter service subscription API
            m.post("https://us1.api.mailchimp.com/3.0/lists/test_list_12345/members",
                   json={
                       "id": "subscriber_12345",
                       "email_address": "newsletter.test@verenigingen.nl",
                       "status": "pending",  # Double opt-in enabled
                       "merge_fields": {
                           "FNAME": "Newsletter",
                           "LNAME": "Test Member"
                       }
                   })

            # Create member with newsletter opt-in
            member = self.create_test_member(
                first_name="Newsletter",
                last_name="Test Member",
                email="newsletter.test@verenigingen.nl",
                newsletter_subscription=1
            )

            # Verify newsletter subscription API called
            self.assertEqual(len(m.request_history), 1)
            request = m.request_history[0]
            request_data = json.loads(request.text)

            self.assertEqual(request_data["email_address"], "newsletter.test@verenigingen.nl")
            self.assertEqual(request_data["status"], "pending")
            self.assertEqual(request_data["merge_fields"]["FNAME"], "Newsletter")
            self.assertEqual(request_data["merge_fields"]["LNAME"], "Test Member")

            # Verify member record updated with subscription info
            member.reload()
            self.assertEqual(member.newsletter_subscriber_id, "subscriber_12345")
            self.assertEqual(member.newsletter_status, "Pending")

    def test_newsletter_subscription_confirmation_webhook(self):
        """
        Test newsletter subscription confirmation via webhook

        Handles double opt-in confirmation from newsletter service
        """
        # Create member with pending newsletter subscription
        member = self.create_test_member(
            email="confirm.test@verenigingen.nl",
            newsletter_subscription=1,
            newsletter_status="Pending",
            newsletter_subscriber_id="pending_subscriber_123"
        )

        # Simulate newsletter service confirmation webhook
        webhook_payload = {
            "type": "subscribe",
            "fired_at": "2024-11-01T15:30:00+00:00",
            "data": {
                "id": "pending_subscriber_123",
                "email": "confirm.test@verenigingen.nl",
                "status": "subscribed",
                "timestamp_opt": "2024-11-01T15:30:00+00:00"
            }
        }

        # Process newsletter webhook
        from verenigingen.utils.newsletter_integration import process_newsletter_webhook
        result = process_newsletter_webhook(webhook_payload)

        # Verify webhook processing success
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "confirmed_subscription")

        # Verify member newsletter status updated
        member.reload()
        self.assertEqual(member.newsletter_status, "Subscribed")
        self.assertIsNotNone(member.newsletter_confirmed_date)

    def test_newsletter_unsubscribe_handling(self):
        """
        Test newsletter unsubscribe via webhook and member preference

        Critical for GDPR compliance and member preference management
        """
        # Create subscribed member
        member = self.create_test_member(
            email="unsubscribe.test@verenigingen.nl",
            newsletter_subscription=1,
            newsletter_status="Subscribed",
            newsletter_subscriber_id="subscribed_member_456"
        )

        # Simulate unsubscribe webhook from newsletter service
        webhook_payload = {
            "type": "unsubscribe",
            "fired_at": "2024-11-01T16:00:00+00:00",
            "data": {
                "id": "subscribed_member_456",
                "email": "unsubscribe.test@verenigingen.nl",
                "reason": "manual"
            }
        }

        # Process unsubscribe webhook
        from verenigingen.utils.newsletter_integration import process_newsletter_webhook
        result = process_newsletter_webhook(webhook_payload)

        # Verify unsubscribe processing
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "unsubscribed")

        # Verify member preferences updated
        member.reload()
        self.assertFalse(member.newsletter_subscription)
        self.assertEqual(member.newsletter_status, "Unsubscribed")
        self.assertIsNotNone(member.newsletter_unsubscribed_date)

    def test_newsletter_subscription_sync_bulk_update(self):
        """
        Test bulk synchronization of newsletter subscription status

        Ensures data consistency between systems
        """
        # Create multiple members with various newsletter states
        members = []
        for i, status in enumerate(["Subscribed", "Pending", "Unsubscribed"]):
            member = self.create_test_member(
                email=f"bulk.sync{i}@verenigingen.nl",
                newsletter_subscription=(status != "Unsubscribed"),
                newsletter_status=status,
                newsletter_subscriber_id=f"bulk_member_{i}"
            )
            members.append(member)

        with requests_mock.Mocker() as m:
            # Mock newsletter service bulk status check
            m.get("https://us1.api.mailchimp.com/3.0/lists/test_list_12345/members",
                  json={
                      "members": [
                          {"id": "bulk_member_0", "status": "subscribed"},
                          {"id": "bulk_member_1", "status": "subscribed"},  # Status changed
                          {"id": "bulk_member_2", "status": "unsubscribed"}
                      ]
                  })

            # Run bulk sync
            from verenigingen.utils.newsletter_integration import sync_newsletter_subscriptions
            result = sync_newsletter_subscriptions()

            # Verify sync results
            self.assertEqual(result["total_processed"], 3)
            self.assertEqual(result["status_changes"], 1)  # Member 1 changed from pending to subscribed

            # Verify member status updated
            members[1].reload()
            self.assertEqual(members[1].newsletter_status, "Subscribed")


class TestEmailCampaignManagement(EnhancedTestCase):
    """
    Test email campaign creation, delivery, and tracking

    Priority 1: Member communication workflows
    """

    def setUp(self):
        """Set up email campaign test environment"""
        super().setUp()

        # Create test members for campaign targeting
        self.campaign_members = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Campaign{i}",
                last_name="Test Member",
                email=f"campaign.test{i}@verenigingen.nl",
                newsletter_subscription=1,
                newsletter_status="Subscribed"
            )
            self.campaign_members.append(member)

    def test_email_campaign_creation_and_delivery(self):
        """
        Test email campaign creation with member targeting

        Core workflow: Campaign Creation → Recipient Selection → Delivery
        """
        with requests_mock.Mocker() as m:
            # Mock email service campaign creation
            m.post("https://us1.api.mailchimp.com/3.0/campaigns",
                   json={
                       "id": "campaign_12345",
                       "status": "save",
                       "recipients": {"list_id": "test_list_12345"},
                       "settings": {
                           "subject_line": "Important Verenigingen Update",
                           "from_name": "Verenigingen Team"
                       }
                   })

            # Mock campaign send
            m.post("https://us1.api.mailchimp.com/3.0/campaigns/campaign_12345/actions/send",
                   json={"complete": True})

            # Create and send campaign
            from verenigingen.utils.email_campaign import EmailCampaignManager
            campaign_manager = EmailCampaignManager()

            campaign_data = {
                "subject": "Important Verenigingen Update",
                "content": "<h1>Hello {{first_name}}!</h1><p>This is an important update for our members.</p>",
                "target_audience": "newsletter_subscribers",
                "send_immediately": True
            }

            result = campaign_manager.create_and_send_campaign(campaign_data)

            # Verify campaign creation success
            self.assertTrue(result["success"])
            self.assertEqual(result["campaign_id"], "campaign_12345")
            self.assertEqual(result["recipients_count"], 5)
            self.assertTrue(result["sent"])

            # Verify campaign record created in database
            campaign_records = frappe.get_all(
                "Email Campaign",
                filters={"external_campaign_id": "campaign_12345"},
                fields=["name", "subject", "status", "recipients_count"]
            )
            self.assertEqual(len(campaign_records), 1)
            campaign = campaign_records[0]
            self.assertEqual(campaign.subject, "Important Verenigingen Update")
            self.assertEqual(campaign.status, "Sent")

    def test_email_template_personalization(self):
        """
        Test email template personalization with member data

        Ensures dynamic content renders correctly
        """
        # Create test member with rich profile data
        member = self.create_test_member(
            first_name="Personalization",
            last_name="Test Member",
            email="personalization.test@verenigingen.nl"
        )

        # Create membership for template context
        membership = self.create_test_membership(
            member.name,
            membership_type_name="Regular Adult"
        )

        # Test template with personalization
        template_content = """
        <h1>Hello {{first_name}} {{last_name}}!</h1>
        <p>Your membership type: {{membership_type}}</p>
        <p>Your member ID: {{member_id}}</p>
        <p>Next payment date: {{next_payment_date}}</p>
        """

        from verenigingen.utils.email_template_processor import EmailTemplateProcessor
        processor = EmailTemplateProcessor()

        rendered_content = processor.render_template(template_content, member)

        # Verify personalization
        self.assertIn("Hello Personalization Test Member!", rendered_content)
        self.assertIn("Your membership type: Regular Adult", rendered_content)
        self.assertIn(f"Your member ID: {member.member_id}", rendered_content)

    def test_email_campaign_segmentation(self):
        """
        Test email campaign targeting based on member segments

        Critical for targeted communication
        """
        # Create members with different characteristics for segmentation
        student_member = self.create_test_member(
            email="student@verenigingen.nl",
            current_membership_type="Student",
            newsletter_subscription=1
        )

        senior_member = self.create_test_member(
            email="senior@verenigingen.nl",
            current_membership_type="Senior (65+)",
            newsletter_subscription=1
        )

        family_member = self.create_test_member(
            email="family@verenigingen.nl",
            current_membership_type="Family",
            newsletter_subscription=1
        )

        # Test student-specific campaign
        from verenigingen.utils.email_campaign import EmailCampaignManager
        campaign_manager = EmailCampaignManager()

        # Get student segment
        student_segment = campaign_manager.get_segment_recipients({
            "membership_type": "Student",
            "newsletter_subscription": 1
        })

        self.assertEqual(len(student_segment), 1)
        self.assertEqual(student_segment[0]["email"], "student@verenigingen.nl")

        # Test family segment
        family_segment = campaign_manager.get_segment_recipients({
            "membership_type": "Family",
            "newsletter_subscription": 1
        })

        self.assertEqual(len(family_segment), 1)
        self.assertEqual(family_segment[0]["email"], "family@verenigingen.nl")


class TestEmailBounceAndDeliveryTracking(EnhancedTestCase):
    """
    Test email bounce handling and delivery tracking

    Priority 2: Email deliverability and list hygiene
    """

    def test_email_bounce_webhook_processing(self):
        """
        Test email bounce webhook processing and member status updates

        Critical for maintaining email deliverability
        """
        # Create member with email delivery issues
        member = self.create_test_member(
            email="bounce.test@invalid-domain.nl",
            newsletter_subscription=1,
            newsletter_status="Subscribed"
        )

        # Simulate email bounce webhook
        bounce_webhook = {
            "type": "bounce",
            "fired_at": "2024-11-01T17:00:00+00:00",
            "data": {
                "email": "bounce.test@invalid-domain.nl",
                "campaign_id": "campaign_bounce_test",
                "bounce_type": "hard",
                "reason": "mailbox_does_not_exist"
            }
        }

        # Process bounce webhook
        from verenigingen.utils.email_bounce_handler import process_bounce_webhook
        result = process_bounce_webhook(bounce_webhook)

        # Verify bounce processing
        self.assertTrue(result["success"])
        self.assertEqual(result["bounce_type"], "hard")

        # Verify member email status updated
        member.reload()
        self.assertEqual(member.email_status, "Bounced")
        self.assertFalse(member.newsletter_subscription)  # Auto-unsubscribed on hard bounce
        self.assertEqual(member.newsletter_status, "Bounced")

        # Verify bounce record created
        bounce_records = frappe.get_all(
            "Email Bounce Record",
            filters={"member": member.name},
            fields=["bounce_type", "reason", "email_address"]
        )
        self.assertEqual(len(bounce_records), 1)
        self.assertEqual(bounce_records[0].bounce_type, "Hard")
        self.assertEqual(bounce_records[0].reason, "mailbox_does_not_exist")

    def test_soft_bounce_retry_logic(self):
        """
        Test soft bounce handling with retry logic

        Temporary delivery issues should not immediately unsubscribe
        """
        member = self.create_test_member(
            email="soft.bounce@verenigingen.nl",
            newsletter_subscription=1
        )

        # Simulate soft bounce (temporary issue)
        soft_bounce_webhook = {
            "type": "bounce",
            "data": {
                "email": "soft.bounce@verenigingen.nl",
                "bounce_type": "soft",
                "reason": "mailbox_full"
            }
        }

        # Process soft bounce
        from verenigingen.utils.email_bounce_handler import process_bounce_webhook
        result = process_bounce_webhook(soft_bounce_webhook)

        # Verify soft bounce handling
        self.assertTrue(result["success"])
        self.assertEqual(result["bounce_type"], "soft")

        # Member should remain subscribed after single soft bounce
        member.reload()
        self.assertEqual(member.email_status, "Soft Bounce")
        self.assertTrue(member.newsletter_subscription)  # Still subscribed
        self.assertEqual(member.email_bounce_count, 1)

    def test_email_delivery_tracking_and_analytics(self):
        """
        Test email delivery tracking and campaign analytics

        Provides insights into campaign performance
        """
        # Create campaign delivery tracking data
        campaign_id = "analytics_test_campaign"

        # Create test members with various engagement levels
        members_data = [
            {"email": "opened@verenigingen.nl", "action": "open"},
            {"email": "clicked@verenigingen.nl", "action": "click"},
            {"email": "unopened@verenigingen.nl", "action": "sent"}
        ]

        tracking_events = []
        for member_data in members_data:
            member = self.create_test_member(email=member_data["email"])

            # Simulate tracking webhook
            if member_data["action"] in ["open", "click"]:
                tracking_webhook = {
                    "type": member_data["action"],
                    "fired_at": "2024-11-01T18:00:00+00:00",
                    "data": {
                        "email": member_data["email"],
                        "campaign_id": campaign_id,
                        "url": "https://verenigingen.nl" if member_data["action"] == "click" else None
                    }
                }
                tracking_events.append(tracking_webhook)

        # Process tracking events
        from verenigingen.utils.email_tracking import process_tracking_webhook
        for event in tracking_events:
            result = process_tracking_webhook(event)
            self.assertTrue(result["success"])

        # Generate campaign analytics
        from verenigingen.utils.email_analytics import generate_campaign_analytics
        analytics = generate_campaign_analytics(campaign_id)

        # Verify analytics data
        self.assertEqual(analytics["total_sent"], 3)
        self.assertEqual(analytics["total_opened"], 1)
        self.assertEqual(analytics["total_clicked"], 1)
        self.assertEqual(analytics["open_rate"], 33.33)  # 1/3 * 100
        self.assertEqual(analytics["click_rate"], 33.33)  # 1/3 * 100

    # Helper methods for email integration tests
    def create_test_email_campaign(self, subject="Test Campaign", **kwargs):
        """Create test email campaign record"""
        campaign = frappe.new_doc("Email Campaign")
        campaign.update({
            "subject": subject,
            "content": kwargs.get("content", "<p>Test campaign content</p>"),
            "status": kwargs.get("status", "Draft"),
            "target_audience": kwargs.get("target_audience", "all_subscribers"),
            "external_campaign_id": kwargs.get("external_campaign_id", f"test_campaign_{frappe.utils.random_string(8)}"),
            **kwargs
        })
        campaign.insert()
        return campaign

    def create_test_membership(self, member_name, membership_type_name="Regular Adult"):
        """Create test membership for template context"""
        membership = frappe.new_doc("Membership")
        membership.update({
            "member": member_name,
            "membership_type": membership_type_name,
            "from_date": today(),
            "to_date": add_months(today(), 12)
        })
        membership.insert()
        return membership