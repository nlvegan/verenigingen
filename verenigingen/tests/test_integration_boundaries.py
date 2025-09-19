"""
Integration Boundary Testing - Priority 2 System Integration
=============================================================

Comprehensive testing of external system integrations that form critical
business boundaries for the Verenigingen association management system.

These tests validate the integration points between Verenigingen and external
services, ensuring data consistency, error handling, and business continuity
across system boundaries.

Test Categories:
1. E-Boekhouden Accounting Integration
2. Mollie Payment Gateway Integration
3. Email/Newsletter Service Integration
4. Bank Import/Export Integration
5. Webhook Security and Validation

@author Verenigingen Development Team
@version 1.0.0
"""

import frappe
from frappe.utils import today, add_months, flt, nowdate, now_datetime
from decimal import Decimal
import json
import requests_mock
from unittest.mock import patch, MagicMock

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestEBoekhoudenIntegration(EnhancedTestCase):
    """
    Test E-Boekhouden accounting system integration boundaries

    Critical for financial data synchronization and compliance.
    """

    def setUp(self):
        """Set up E-Boekhouden integration test environment"""
        super().setUp()

        # Create test E-Boekhouden settings
        self.eboekhouden_settings = self.create_test_eboekhouden_settings()

    def create_test_eboekhouden_settings(self):
        """Create test E-Boekhouden settings"""
        settings = frappe.new_doc("E Boekhouden Settings")
        settings.update({
            "username": "test_user",
            "security_code": "test_security_code",
            "enabled": 1,
            "sync_customers": 1,
            "sync_invoices": 1,
            "sync_payments": 1,
            "test_mode": 1
        })
        settings.insert()
        return settings

    def test_customer_sync_to_eboekhouden_on_member_creation(self):
        """
        Test that new members are automatically synced to E-Boekhouden as customers
        """
        with requests_mock.Mocker() as m:
            # Mock E-Boekhouden API response
            m.post("https://secure.e-boekhouden.nl/verhuur/api_xml.asp",
                   text='<?xml version="1.0"?><result><customers><customer><id>12345</id></customer></customers></result>')

            # Create member (should trigger E-Boekhouden sync)
            member = self.create_test_member(
                first_name="Integration",
                last_name="Test Customer",
                email="integration.test@example.nl"
            )

            # Verify E-Boekhouden customer fields are populated
            self.assertIsNotNone(member.custom_eboekhouden_customer_id)
            self.assertEqual(member.custom_eboekhouden_customer_id, "12345")
            self.assertTrue(member.custom_eboekhouden_synced)

    def test_invoice_sync_to_eboekhouden_with_payment_terms(self):
        """
        Test invoice synchronization with proper payment terms mapping
        """
        # Create member with customer
        member = self.create_test_member()

        # Create sales invoice
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            grand_total=125.00
        )

        with requests_mock.Mocker() as m:
            # Mock E-Boekhouden invoice creation
            m.post("https://secure.e-boekhouden.nl/verhuur/api_xml.asp",
                   text='<?xml version="1.0"?><result><invoices><invoice><id>INV-2024-001</id></invoice></invoices></result>')

            # Trigger E-Boekhouden sync
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRestClient
            client = EBoekhoudenRestClient()
            result = client.sync_invoice(invoice)

            # Verify sync result
            self.assertTrue(result["success"])
            self.assertEqual(result["eboekhouden_id"], "INV-2024-001")

            # Verify invoice custom fields updated
            invoice.reload()
            self.assertEqual(invoice.custom_eboekhouden_invoice_id, "INV-2024-001")
            self.assertTrue(invoice.custom_eboekhouden_synced)

    def test_payment_reconciliation_from_eboekhouden_import(self):
        """
        Test payment import from E-Boekhouden and automatic reconciliation
        """
        # Create unreconciled invoice
        member = self.create_test_member()
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            grand_total=50.00,
            submit=True
        )

        # Mock E-Boekhouden payment data
        payment_data = {
            "payments": [
                {
                    "id": "PAY-001",
                    "invoice_id": "INV-001",
                    "amount": 50.00,
                    "date": today(),
                    "reference": invoice.name,
                    "payment_method": "Bank Transfer"
                }
            ]
        }

        with requests_mock.Mocker() as m:
            m.get("https://secure.e-boekhouden.nl/verhuur/api_xml.asp",
                  text=f'<?xml version="1.0"?><result>{json.dumps(payment_data)}</result>')

            # Process payment import
            from verenigingen.e_boekhouden.utils.eboekhouden_payment_import import import_payments
            result = import_payments()

            # Verify payment entry created and invoice reconciled
            payment_entries = frappe.get_all("Payment Entry",
                                           filters={"custom_eboekhouden_payment_id": "PAY-001"})
            self.assertEqual(len(payment_entries), 1)

            # Verify invoice is paid
            invoice.reload()
            self.assertEqual(invoice.status, "Paid")
            self.assertEqual(invoice.outstanding_amount, 0)

    def test_chart_of_accounts_synchronization(self):
        """
        Test Chart of Accounts import and mapping from E-Boekhouden
        """
        coa_data = {
            "accounts": [
                {"code": "1000", "name": "Bank Account", "type": "Asset"},
                {"code": "4000", "name": "Membership Income", "type": "Income"},
                {"code": "8000", "name": "Office Expenses", "type": "Expense"}
            ]
        }

        with requests_mock.Mocker() as m:
            m.get("https://secure.e-boekhouden.nl/verhuur/api_xml.asp",
                  text=f'<?xml version="1.0"?><result>{json.dumps(coa_data)}</result>')

            # Import chart of accounts
            from verenigingen.e_boekhouden.utils.eboekhouden_coa_import import import_chart_of_accounts
            result = import_chart_of_accounts()

            # Verify accounts created with proper mapping
            bank_account = frappe.get_doc("Account", {"account_number": "1000"})
            self.assertEqual(bank_account.account_name, "Bank Account")
            self.assertEqual(bank_account.account_type, "Bank")

            income_account = frappe.get_doc("Account", {"account_number": "4000"})
            self.assertEqual(income_account.account_name, "Membership Income")
            self.assertEqual(income_account.root_type, "Income")


class TestMolliePaymentIntegration(EnhancedTestCase):
    """
    Test Mollie payment gateway integration boundaries

    Critical for secure payment processing and subscription management.
    """

    def setUp(self):
        """Set up Mollie integration test environment"""
        super().setUp()

        # Create test Mollie settings
        self.mollie_settings = self.create_test_mollie_settings()

    def create_test_mollie_settings(self):
        """Create test Mollie settings"""
        settings = frappe.new_doc("Mollie Settings")
        settings.update({
            "api_key": "test_mollie_api_key",
            "webhook_url": "https://dev.veganisme.net/api/method/verenigingen.utils.payment_gateways.mollie_subscription_webhook",
            "enabled": 1,
            "test_mode": 1
        })
        settings.insert()
        return settings

    def test_subscription_creation_for_recurring_membership_dues(self):
        """
        Test Mollie subscription creation for recurring membership payments
        """
        # Create member with SEPA mandate
        member = self.create_test_member()
        sepa_mandate = self.create_test_sepa_mandate(member.name)

        with requests_mock.Mocker() as m:
            # Mock Mollie customer creation
            m.post("https://api.mollie.com/v2/customers",
                   json={"id": "cst_test_customer", "name": member.full_name})

            # Mock Mollie subscription creation
            m.post("https://api.mollie.com/v2/customers/cst_test_customer/subscriptions",
                   json={
                       "id": "sub_test_subscription",
                       "status": "active",
                       "amount": {"value": "25.00", "currency": "EUR"},
                       "interval": "1 month",
                       "nextPaymentDate": "2024-12-01"
                   })

            # Create subscription
            from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService
            service = MolliePaymentService()
            result = service.create_subscription(member, 25.00, "1 month")

            # Verify subscription created
            self.assertTrue(result["success"])
            self.assertEqual(result["subscription_id"], "sub_test_subscription")

            # Verify member fields updated
            member.reload()
            self.assertEqual(member.mollie_customer_id, "cst_test_customer")
            self.assertEqual(member.mollie_subscription_id, "sub_test_subscription")
            self.assertEqual(member.subscription_status, "Active")

    def test_webhook_payment_processing_and_invoice_reconciliation(self):
        """
        Test Mollie webhook processing for successful payments
        """
        # Create member with subscription
        member = self.create_test_member()
        member.mollie_subscription_id = "sub_test_subscription"
        member.save()

        # Create unpaid invoice
        invoice = self.create_test_sales_invoice(
            customer=member.customer,
            grand_total=25.00,
            submit=True
        )

        # Simulate Mollie webhook payload
        webhook_payload = {
            "id": "tr_test_payment",
            "status": "paid",
            "amount": {"value": "25.00", "currency": "EUR"},
            "subscriptionId": "sub_test_subscription",
            "paidAt": now_datetime().isoformat(),
            "metadata": {"invoice_id": invoice.name}
        }

        with requests_mock.Mocker() as m:
            # Mock Mollie payment verification
            m.get(f"https://api.mollie.com/v2/payments/tr_test_payment",
                  json=webhook_payload)

            # Process webhook
            from verenigingen.utils.payment_gateways import mollie_subscription_webhook
            result = mollie_subscription_webhook(webhook_payload)

            # Verify payment entry created
            payment_entries = frappe.get_all("Payment Entry",
                                           filters={"custom_mollie_payment_id": "tr_test_payment"})
            self.assertEqual(len(payment_entries), 1)

            # Verify invoice reconciled
            invoice.reload()
            self.assertEqual(invoice.status, "Paid")
            self.assertEqual(invoice.outstanding_amount, 0)

    def test_failed_payment_handling_and_retry_logic(self):
        """
        Test handling of failed Mollie payments and retry mechanisms
        """
        member = self.create_test_member()

        # Simulate failed payment webhook
        webhook_payload = {
            "id": "tr_failed_payment",
            "status": "failed",
            "subscriptionId": "sub_test_subscription",
            "failureReason": "insufficient_funds"
        }

        with requests_mock.Mocker() as m:
            m.get(f"https://api.mollie.com/v2/payments/tr_failed_payment",
                  json=webhook_payload)

            # Process failed payment webhook
            from verenigingen.utils.payment_gateways import mollie_subscription_webhook
            result = mollie_subscription_webhook(webhook_payload)

            # Verify member notified and retry scheduled
            self.assertTrue(result["retry_scheduled"])

            # Verify member payment history updated
            payment_history = frappe.get_all("Member Payment History",
                                           filters={"member": member.name, "status": "Failed"})
            self.assertEqual(len(payment_history), 1)


class TestEmailNewsletterIntegration(EnhancedTestCase):
    """
    Test email and newsletter service integration boundaries

    Critical for member communication and engagement.
    """

    def test_member_newsletter_subscription_sync(self):
        """
        Test automatic newsletter subscription when member opts in
        """
        with patch('verenigingen.utils.newsletter_integration.subscribe_to_newsletter') as mock_subscribe:
            mock_subscribe.return_value = {"success": True, "subscriber_id": "sub_12345"}

            # Create member with newsletter opt-in
            member = self.create_test_member(
                email="newsletter.test@example.nl",
                newsletter_subscription=1
            )

            # Verify newsletter subscription called
            mock_subscribe.assert_called_once()
            call_args = mock_subscribe.call_args[0]
            self.assertEqual(call_args[0], "newsletter.test@example.nl")
            self.assertIn("first_name", call_args[1])

    def test_bulk_email_campaign_delivery_tracking(self):
        """
        Test bulk email campaign creation and delivery tracking
        """
        # Create test members
        members = []
        for i in range(5):
            member = self.create_test_member(
                email=f"campaign.test{i}@example.nl",
                newsletter_subscription=1
            )
            members.append(member)

        with patch('verenigingen.utils.email_campaign.send_bulk_email') as mock_send:
            mock_send.return_value = {
                "success": True,
                "campaign_id": "camp_12345",
                "recipients": 5,
                "delivery_status": "scheduled"
            }

            # Create and send campaign
            from verenigingen.utils.email_campaign import create_campaign
            campaign = create_campaign(
                subject="Test Campaign",
                content="<p>Test content</p>",
                recipient_filter={"newsletter_subscription": 1}
            )

            # Verify campaign tracking
            self.assertEqual(campaign.recipients_count, 5)
            self.assertEqual(campaign.status, "Scheduled")
            self.assertIsNotNone(campaign.external_campaign_id)

    def test_email_bounce_and_unsubscribe_handling(self):
        """
        Test handling of email bounces and unsubscribe requests
        """
        member = self.create_test_member(email="bounce.test@example.nl")

        # Simulate bounce webhook
        bounce_payload = {
            "type": "bounce",
            "email": "bounce.test@example.nl",
            "reason": "mailbox_full",
            "timestamp": now_datetime().isoformat()
        }

        # Process bounce
        from verenigingen.utils.email_bounce_handler import handle_bounce
        result = handle_bounce(bounce_payload)

        # Verify member email status updated
        member.reload()
        self.assertEqual(member.email_status, "Bounced")
        self.assertFalse(member.newsletter_subscription)


class TestBankImportExportIntegration(EnhancedTestCase):
    """
    Test bank import/export integration boundaries

    Critical for financial reconciliation and payment processing.
    """

    def test_bank_statement_import_and_payment_matching(self):
        """
        Test bank statement import with automatic payment matching
        """
        # Create unpaid invoices
        member1 = self.create_test_member()
        member2 = self.create_test_member()

        invoice1 = self.create_test_sales_invoice(
            customer=member1.customer,
            grand_total=25.00,
            submit=True
        )
        invoice2 = self.create_test_sales_invoice(
            customer=member2.customer,
            grand_total=50.00,
            submit=True
        )

        # Mock bank statement data
        bank_data = {
            "transactions": [
                {
                    "date": today(),
                    "amount": 25.00,
                    "description": f"Payment {invoice1.name}",
                    "reference": invoice1.name,
                    "counterparty": member1.full_name
                },
                {
                    "date": today(),
                    "amount": 50.00,
                    "description": f"Payment {invoice2.name}",
                    "reference": invoice2.name,
                    "counterparty": member2.full_name
                }
            ]
        }

        # Process bank import
        from verenigingen.utils.bank_import import process_bank_statement
        result = process_bank_statement(bank_data)

        # Verify automatic matching
        self.assertEqual(result["matched_payments"], 2)
        self.assertEqual(result["unmatched_payments"], 0)

        # Verify invoices reconciled
        invoice1.reload()
        invoice2.reload()
        self.assertEqual(invoice1.status, "Paid")
        self.assertEqual(invoice2.status, "Paid")

    def test_sepa_direct_debit_file_export(self):
        """
        Test SEPA direct debit file generation and export
        """
        # Create members with SEPA mandates
        members_with_mandates = []
        for i in range(3):
            member = self.create_test_member()
            mandate = self.create_test_sepa_mandate(member.name)
            members_with_mandates.append((member, mandate))

        # Create direct debit batch
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
        sepa_factory = SEPATestDataFactory()
        batch = sepa_factory.create_test_direct_debit_batch(invoice_count=3)

        # Generate SEPA file
        from verenigingen.utils.sepa_export import generate_sepa_file
        sepa_file = generate_sepa_file(batch)

        # Verify SEPA file structure
        self.assertIn("<?xml version", sepa_file)
        self.assertIn("<CstmrDrctDbtInitn>", sepa_file)
        self.assertIn("<NbOfTxs>3</NbOfTxs>", sepa_file)

        # Verify each mandate included
        for member, mandate in members_with_mandates:
            self.assertIn(mandate.iban.replace(" ", ""), sepa_file)
            self.assertIn(mandate.mandate_id, sepa_file)


class TestWebhookSecurityAndValidation(EnhancedTestCase):
    """
    Test webhook security and validation across all integrations

    Critical for preventing security vulnerabilities and data corruption.
    """

    def test_mollie_webhook_signature_validation(self):
        """
        Test Mollie webhook signature verification
        """
        payload = {"id": "tr_test", "status": "paid"}

        # Test with valid signature
        with patch('verenigingen.utils.webhook_security.verify_mollie_signature') as mock_verify:
            mock_verify.return_value = True

            from verenigingen.utils.payment_gateways import mollie_subscription_webhook
            result = mollie_subscription_webhook(payload)

            self.assertTrue(result["signature_valid"])

    def test_eboekhouden_api_rate_limiting(self):
        """
        Test E-Boekhouden API rate limiting and retry logic
        """
        with requests_mock.Mocker() as m:
            # Mock rate limit response
            m.post("https://secure.e-boekhouden.nl/verhuur/api_xml.asp",
                   status_code=429,
                   headers={"Retry-After": "60"})

            from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRestClient
            client = EBoekhoudenRestClient()

            # Verify rate limiting handled gracefully
            result = client.sync_customer({"name": "Test"})
            self.assertFalse(result["success"])
            self.assertIn("rate_limited", result["error"])

    def test_webhook_payload_validation_and_sanitization(self):
        """
        Test webhook payload validation prevents injection attacks
        """
        malicious_payload = {
            "id": "'; DROP TABLE members; --",
            "status": "<script>alert('xss')</script>",
            "amount": {"value": "not_a_number"}
        }

        from verenigingen.utils.webhook_security import validate_webhook_payload
        result = validate_webhook_payload(malicious_payload, "mollie_payment")

        # Verify malicious content rejected
        self.assertFalse(result["valid"])
        self.assertIn("Invalid characters detected", result["errors"])

    # Helper methods for integration tests
    def create_test_sepa_mandate(self, member_name, iban=None, **kwargs):
        """Create test SEPA mandate for integration tests"""
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.update({
            "member": member_name,
            "iban": iban or "NL91ABNA0417164300",
            "mandate_id": f"TST{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}",
            "status": "Active",
            "sign_date": frappe.utils.today(),
            "account_holder_name": kwargs.get("account_holder_name", "Test Account Holder"),
            **kwargs
        })
        mandate.insert()
        return mandate