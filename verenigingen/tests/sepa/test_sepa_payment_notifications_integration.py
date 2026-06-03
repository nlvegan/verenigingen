"""
SEPA and Payment Notification Integration Tests
==============================================

Tests the complete SEPA payment notification system with realistic data
generation and end-to-end flows. Focuses on Dutch banking scenarios,
SEPA mandate lifecycle, and payment processing notifications.

Covers:
- SEPA mandate creation, modification, and cancellation notifications
- Payment success and failure notifications
- Retry mechanism notifications
- Bulk notification processing
- Dutch banking validation and formatting
- Real-world payment scenarios
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import frappe
from frappe.utils import add_days, getdate, today, flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager
import unittest


class TestSEPANotificationIntegration(EnhancedTestCase):
    """Integration tests for SEPA notification system"""

    def setUp(self):
        """Set up test environment with SEPA-related data"""
        super().setUp()

        # Create test members with Dutch characteristics
        self.dutch_member = self.create_test_member(
            first_name="Johannes",
            last_name="van der Meer",
            email="j.vandermeer@test.invalid",
            birth_date="1982-04-12"
        )

        self.regular_member = self.create_test_member(
            first_name="Anna",
            last_name="de Vries",
            email="anna.devries@test.invalid",
            birth_date="1990-08-25"
        )

        # Initialize notification manager
        self.notification_manager = SEPAMandateNotificationManager()

        # Create test SEPA mandate data
        self.test_mandates = self._create_test_mandates()

    def _create_test_mandates(self):
        """Create test SEPA mandate objects"""
        mandates = []

        # Dutch bank mandates with realistic IBANs
        dutch_banks = [
            {"iban": "NL91RABO0300065264", "bank": "Rabobank"},
            {"iban": "NL69INGB0123456789", "bank": "ING"},
            {"iban": "NL02ABNA0123456789", "bank": "ABN AMRO"},
            {"iban": "NL44BUNQ2025123456", "bank": "Bunq"},
        ]

        for i, bank_data in enumerate(dutch_banks):
            mandate = MagicMock()
            mandate.name = f"SEPA-MANDATE-{i+1:03d}"
            mandate.mandate_id = f"MAND-{datetime.now().year}-{i+1:04d}"
            mandate.member = self.dutch_member.name if i % 2 == 0 else self.regular_member.name
            mandate.iban = bank_data["iban"]
            mandate.sign_date = add_days(today(), -30)
            mandate.expiry_date = add_days(today(), 365)
            mandate.status = "Active"
            mandate.mandate_type = "RCUR"  # Recurring
            mandates.append(mandate)

        return mandates

    def test_sepa_mandate_created_notification_flow(self):
        """Test complete SEPA mandate creation notification flow.

        The notification methods route through the unified EmailService via
        send_sepa_email() (not frappe.sendmail directly), so we mock that boundary
        and assert on the recipients/subject/context handed to it.
        """
        mandate = self.test_mandates[0]  # Rabobank mandate

        with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
            # Test individual notification
            self.notification_manager.send_mandate_created_notification(mandate)

            # Verify email was sent
            mock_send.assert_called_once()
            call_args = mock_send.call_args[1]

            # Verify email metadata
            self.assertIn("SEPA", call_args["subject"])
            self.assertIn("Activated", call_args["subject"])
            self.assertIn(self.dutch_member.email, call_args["recipients"])

            # Verify IBAN masking in the rendered context
            context = call_args["context"]
            self.assertEqual(context["iban"], "NL91****5264")  # Should be masked
            self.assertNotIn("0300065264", context["iban"])  # Full IBAN should not appear

    def test_sepa_mandate_cancelled_notification_flow(self):
        """Test SEPA mandate cancellation notification flow"""
        mandate = self.test_mandates[1]  # ING mandate
        cancellation_reason = "Member requested cancellation due to bank change"

        with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
            self.notification_manager.send_mandate_cancelled_notification(mandate, cancellation_reason)

            mock_send.assert_called_once()
            call_args = mock_send.call_args[1]

            # Verify cancellation-specific content
            self.assertIn("Cancelled", call_args["subject"])
            context = call_args["context"]
            self.assertEqual(context["cancellation_reason"], cancellation_reason)
            self.assertEqual(context["iban"], "NL69****6789")  # Masked ING IBAN

    def test_sepa_mandate_expiring_notification_flow(self):
        """Test SEPA mandate expiring notification flow"""
        mandate = self.test_mandates[2]  # ABN AMRO mandate
        days_until_expiry = 30

        with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
            self.notification_manager.send_mandate_expiring_notification(mandate, days_until_expiry)

            mock_send.assert_called_once()
            call_args = mock_send.call_args[1]

            # Verify expiration-specific content
            self.assertIn("Expiring", call_args["subject"])
            context = call_args["context"]
            self.assertEqual(context["days_until_expiry"], 30)  # Days until expiry
            self.assertEqual(context["iban"], "NL02****6789")  # Masked ABN AMRO IBAN

    def test_sepa_bulk_notification_processing(self):
        """Test bulk SEPA notification processing"""
        # Prepare bulk notification data
        bulk_notifications = []

        for i, mandate in enumerate(self.test_mandates[:3]):
            notification_type = ["created", "cancelled", "expiring"][i]
            extra_data = {}

            if notification_type == "cancelled":
                extra_data["reason"] = "Bulk processing test cancellation"
            elif notification_type == "expiring":
                extra_data["days_until_expiry"] = 15

            bulk_notifications.append({
                "mandate": mandate,
                "notification_type": notification_type,
                "extra_data": extra_data
            })

        # send_mandate_notifications_batch builds an email batch and hands it to
        # _send_email_batch (which persists Communications and enqueues delivery).
        # Mock that boundary and assert the batch was assembled correctly.
        with patch.object(self.notification_manager, '_send_email_batch') as mock_batch:
            self.notification_manager.send_mandate_notifications_batch(bulk_notifications)

            # Should have assembled one batch containing all three notifications
            mock_batch.assert_called_once()
            email_batch = mock_batch.call_args[0][0]
            self.assertEqual(len(email_batch), 3)

            # Verify each notification type was handled
            subjects = [email["subject"] for email in email_batch]
            self.assertTrue(any("Activated" in subject for subject in subjects))
            self.assertTrue(any("Cancelled" in subject for subject in subjects))
            self.assertTrue(any("Expiring" in subject for subject in subjects))

    def test_dutch_bank_identification(self):
        """Test Dutch bank identification from IBAN"""
        test_cases = [
            ("NL91RABO0300065264", "Rabobank"),
            ("NL69INGB0123456789", "ING"),
            ("NL02ABNA0123456789", "ABN AMRO"),
            ("NL44BUNQ2025123456", "Bunq"),
            ("DE89370400440532013000", "Unknown Bank"),  # German bank
            ("INVALID_IBAN", "Unknown Bank"),
        ]

        for iban, expected_bank in test_cases:
            with self.subTest(iban=iban):
                bank_name = self.notification_manager._get_bank_name(iban)
                if expected_bank != "Unknown Bank":
                    self.assertEqual(bank_name, expected_bank)
                else:
                    # For unknown banks, just verify it returns a string
                    self.assertIsInstance(bank_name, str)

    def test_iban_masking_dutch_formats(self):
        """Test IBAN masking for various Dutch formats"""
        test_cases = [
            ("NL91RABO0300065264", "NL91****5264"),
            ("NL69INGB0123456789", "NL69****6789"),
            # Spaced format: _mask_iban() normalizes (strips spaces, uppercases)
            # before masking, so the result is the compact masked form.
            ("NL 02 ABNA 0123 4567 89", "NL02****6789"),  # Spaced format
            ("SHORT", "SHORT"),  # Too short
            ("", ""),  # Empty
            (None, None),  # None
        ]

        for iban, expected in test_cases:
            with self.subTest(iban=iban):
                masked = self.notification_manager._mask_iban(iban)
                self.assertEqual(masked, expected)

    def test_member_data_bulk_loading_performance(self):
        """Test bulk member data loading for performance"""
        member_names = [self.dutch_member.name, self.regular_member.name]

        # Test bulk loading
        member_data = self.notification_manager._load_member_data_bulk(member_names)

        # Verify data structure
        self.assertIsInstance(member_data, dict)
        self.assertEqual(len(member_data), 2)

        # Verify member data content
        if self.dutch_member.name in member_data:
            dutch_data = member_data[self.dutch_member.name]
            self.assertEqual(dutch_data["name"], self.dutch_member.name)
            self.assertEqual(dutch_data["email"], self.dutch_member.email)
            self.assertIn("van der Meer", dutch_data["full_name"])

    def test_notification_context_preparation_edge_cases(self):
        """Test notification context preparation with edge cases"""
        mandate = self.test_mandates[0]
        member_data = {
            "name": self.dutch_member.name,
            "full_name": "Johannes van der Meer",  # Dutch name with tussenvoegsels
            "email": self.dutch_member.email
        }

        mock_settings = MagicMock()
        mock_settings.company_name = "Vereniging Test Nederland"
        mock_settings.support_email = "support@testvereniging.nl"

        # Test created context with Dutch data
        context = self.notification_manager._prepare_created_context(mandate, member_data, mock_settings)

        # Verify Dutch-specific formatting
        self.assertIn("Johannes van der Meer", context["member_name"])
        self.assertIn("Vereniging Test Nederland", context["company_name"])
        self.assertIn("NL91****5264", context["iban"])

        # Test context with missing data
        incomplete_member_data = {"name": "test", "full_name": "", "email": ""}
        context = self.notification_manager._prepare_created_context(mandate, incomplete_member_data, mock_settings)

        # Should handle missing data gracefully
        self.assertIn("member_name", context)
        self.assertIn("mandate_id", context)

    def test_payment_notification_scenarios(self):
        """Test various payment notification scenarios"""
        # Mock payment entry
        payment_entry = MagicMock()
        payment_entry.name = "PE-2024-001"
        payment_entry.party_type = "Customer"
        payment_entry.party = self.dutch_member.name  # Link to customer
        payment_entry.paid_amount = 25.00
        payment_entry.paid_to_account_currency = "EUR"
        payment_entry.posting_date = today()
        payment_entry.mode_of_payment = "SEPA Direct Debit"

        # Mock customer lookup
        with patch('frappe.db.get_value', return_value=self.dutch_member.name):
            with patch('frappe.get_doc', return_value=self.dutch_member):
                with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
                    self.notification_manager.send_payment_success_notification(payment_entry)

                    # Verify success notification was sent
                    mock_send.assert_called_once()
                    call_args = mock_send.call_args[1]
                    self.assertIn("Payment Received", call_args["subject"])
                    self.assertEqual(call_args["context"]["payment_reference"], "PE-2024-001")

    def test_payment_retry_notification_scenarios(self):
        """Test payment retry notification scenarios"""
        # Mock retry record
        retry_record = MagicMock()
        retry_record.invoice = "SI-2024-001"
        retry_record.member = self.dutch_member.name
        retry_record.original_amount = 25.00
        retry_record.next_retry_date = add_days(today(), 3)
        retry_record.retry_count = 1
        retry_record.last_failure_reason = "Insufficient funds"
        retry_record.status = "Scheduled"

        # Mock invoice and member lookup
        mock_invoice = MagicMock()
        mock_invoice.name = "SI-2024-001"

        with patch('frappe.get_doc') as mock_get_doc:
            mock_get_doc.side_effect = lambda doctype, name: {
                "Sales Invoice": mock_invoice,
                "Member": self.dutch_member
            }.get(doctype)

            with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
                self.notification_manager.send_payment_retry_notification(retry_record)

                mock_send.assert_called_once()
                call_args = mock_send.call_args[1]
                self.assertIn("Retry Scheduled", call_args["subject"])
                self.assertEqual(call_args["context"]["failure_reason"], "Insufficient funds")

    def test_sepa_notification_error_handling(self):
        """Test SEPA notification error handling scenarios"""
        mandate = self.test_mandates[0]

        # Test with member that has no email. The factory enforces a valid email,
        # so create the member normally then clear the email at the DB level — the
        # notification methods read the email via a direct SQL lookup.
        member_without_email = self.create_test_member(
            first_name="NoEmail",
            last_name="Member",
            birth_date="1990-01-01"
        )
        frappe.db.set_value("Member", member_without_email.name, "email", "")

        mandate.member = member_without_email.name

        # Should handle gracefully without sending email
        with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
            self.notification_manager.send_mandate_created_notification(mandate)
            mock_send.assert_not_called()

    def test_sepa_expiry_check_scheduler_integration(self):
        """Test SEPA expiry check scheduler integration"""
        # Create mock expiring mandate in database query result
        expiring_mandate_data = {
            "name": "SEPA-MANDATE-EXPIRING",
            "member": self.dutch_member.name,
            "expiry_date": add_days(today(), 15),  # Expiring in 15 days
            "mandate_id": "MAND-2024-EXPIRING",
            "iban": "NL91RABO0300065264"
        }

        # Mock database queries
        with patch('frappe.get_all') as mock_get_all:
            mock_get_all.return_value = [type('MockMandate', (), expiring_mandate_data)]

            with patch('frappe.db.get_value', return_value=None):  # No recent notifications
                with patch('frappe.get_doc') as mock_get_doc:
                    mock_mandate = MagicMock()
                    mock_mandate.name = expiring_mandate_data["name"]
                    mock_mandate.member = expiring_mandate_data["member"]
                    mock_mandate.expiry_date = expiring_mandate_data["expiry_date"]
                    mock_mandate.mandate_id = expiring_mandate_data["mandate_id"]
                    mock_mandate.iban = expiring_mandate_data["iban"]
                    mock_get_doc.return_value = mock_mandate

                    with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
                        # Call the scheduler function
                        self.notification_manager.check_and_send_expiry_notifications()

                        # Should have sent expiry notification
                        mock_send.assert_called_once()
                        call_args = mock_send.call_args[1]
                        self.assertIn("Expiring", call_args["subject"])

    def test_realistic_dutch_member_notification_flow(self):
        """Test complete notification flow with realistic Dutch member data"""
        # Create member with typical Dutch characteristics
        dutch_member = self.create_test_member(
            first_name="Pieter-Jan",
            last_name="van den Berg-de Wit",  # Complex Dutch surname
            email="pj.vandenberg@email.nl",
            birth_date="1975-11-30"
        )

        # Create realistic SEPA mandate
        mandate = MagicMock()
        mandate.name = "SEPA-MANDATE-DUTCH"
        mandate.mandate_id = f"MAND-{datetime.now().year}-NL-001"
        mandate.member = dutch_member.name
        mandate.iban = "NL20INGB0001234567"  # ING bank IBAN
        mandate.sign_date = getdate()
        mandate.expiry_date = add_days(getdate(), 1095)  # 3 years
        mandate.status = "Active"
        mandate.mandate_type = "RCUR"

        # Test with realistic Dutch settings
        mock_settings = MagicMock()
        mock_settings.company_name = "Nederlandse Vereniging voor Duurzaamheid"
        mock_settings.support_email = "info@duurzaamheidsvereniging.nl"

        with patch.object(self.notification_manager, '_get_settings', return_value=mock_settings):
            with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
                self.notification_manager.send_mandate_created_notification(mandate)

                mock_send.assert_called_once()
                call_args = mock_send.call_args[1]

                # Verify Dutch content handling in the rendered context
                context = call_args["context"]
                self.assertIn("Pieter-Jan van den Berg-de Wit", context["member_name"])
                self.assertIn("Nederlandse Vereniging", context["company_name"])
                self.assertEqual(context["iban"], "NL20****4567")  # Masked IBAN
                self.assertIn("ING", context["bank_name"])  # Bank name should be identified

    def test_sepa_notification_performance_optimization(self):
        """Test SEPA notification performance optimizations"""
        # Test bulk member data loading vs individual queries
        member_names = [member.name for member in [self.dutch_member, self.regular_member]]

        # Measure bulk loading
        import time
        start_time = time.time()
        bulk_data = self.notification_manager._load_member_data_bulk(member_names)
        bulk_time = time.time() - start_time

        # Verify bulk loading returns correct data
        self.assertEqual(len(bulk_data), 2)
        self.assertIn(self.dutch_member.name, bulk_data)
        self.assertIn(self.regular_member.name, bulk_data)

        # Verify performance is reasonable (should be very fast)
        self.assertLess(bulk_time, 1.0)  # Should complete in under 1 second

    def test_sepa_notification_compliance_features(self):
        """Test SEPA notification compliance features"""
        mandate = self.test_mandates[0]

        # Test notification includes required SEPA information
        with patch('verenigingen.services.communication.compatibility.send_sepa_email') as mock_send:
            self.notification_manager.send_mandate_created_notification(mandate)

            mock_send.assert_called_once()
            context = mock_send.call_args[1]["context"]

            # Verify required SEPA compliance elements
            self.assertEqual(context["mandate_id"], mandate.mandate_id)  # Mandate reference
            self.assertEqual(context["iban"], "NL91****5264")  # Masked bank account

            # Should include unsubscribe/preference link for compliance
            context_used = self.notification_manager._prepare_context({})
            self.assertIn("unsubscribe_link", context_used)
            self.assertIn("website_url", context_used)


if __name__ == '__main__':
    import unittest
    unittest.main()