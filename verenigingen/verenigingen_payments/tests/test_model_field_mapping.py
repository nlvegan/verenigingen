#!/usr/bin/env python3
"""
Comprehensive tests for Mollie API model field mapping

Tests that all models correctly parse real Mollie API responses with proper
camelCase to snake_case conversion and nested object handling.
"""

import unittest
from datetime import datetime
from decimal import Decimal

from verenigingen.verenigingen_payments.core.models.balance import Balance, BalanceReport, BalanceTransaction
from verenigingen.verenigingen_payments.core.models.chargeback import Chargeback
from verenigingen.verenigingen_payments.core.models.invoice import Invoice, InvoiceLine
from verenigingen.verenigingen_payments.core.models.organization import Organization, OrganizationAddress
from verenigingen.verenigingen_payments.core.models.settlement import Settlement, SettlementPeriod


class TestMollieModelFieldMapping(unittest.TestCase):
    """Test suite for Mollie API model field mapping"""

    def test_balance_model_parsing(self):
        """Test Balance model parses real API response correctly"""
        # Real Mollie Balance API response structure
        api_response = {
            "resource": "balance",
            "id": "bal_gVMhHKqSSRYJyPsuoPNFH",
            "mode": "live",
            "createdAt": "2024-01-15T10:00:00+00:00",
            "currency": "EUR",
            "status": "active",
            "transferFrequency": "daily",
            "transferThreshold": {"value": "100.00", "currency": "EUR"},
            "transferDestination": {
                "type": "bank-account",
                "beneficiaryName": "Test Account",
                "bankAccount": "NL53INGB0000000000",
            },
            "availableAmount": {"value": "905.25", "currency": "EUR"},
            "pendingAmount": {"value": "55.44", "currency": "EUR"},
            "_links": {
                "self": {
                    "href": "https://api.mollie.com/v2/balances/bal_gVMhHKqSSRYJyPsuoPNFH",
                    "type": "application/hal+json",
                }
            },
        }

        # Parse with model
        balance = Balance(api_response)

        # Test basic fields
        self.assertEqual(balance.resource, "balance")
        self.assertEqual(balance.id, "bal_gVMhHKqSSRYJyPsuoPNFH")
        self.assertEqual(balance.mode, "live")
        self.assertEqual(balance.created_at, "2024-01-15T10:00:00+00:00")
        self.assertEqual(balance.currency, "EUR")
        self.assertEqual(balance.status, "active")
        self.assertEqual(balance.transfer_frequency, "daily")  # camelCase -> snake_case

        # Test nested Amount objects
        self.assertIsNotNone(balance.available_amount)  # camelCase -> snake_case
        self.assertEqual(balance.available_amount.value, "905.25")
        self.assertEqual(balance.available_amount.currency, "EUR")
        self.assertEqual(balance.available_amount.decimal_value, Decimal("905.25"))

        self.assertIsNotNone(balance.pending_amount)  # camelCase -> snake_case
        self.assertEqual(balance.pending_amount.value, "55.44")
        self.assertEqual(balance.pending_amount.currency, "EUR")

        self.assertIsNotNone(balance.transfer_threshold)  # camelCase -> snake_case
        self.assertEqual(balance.transfer_threshold.value, "100.00")

        # Test transfer_destination (nested dict but not Amount)
        self.assertIsNotNone(balance.transfer_destination)  # camelCase -> snake_case
        self.assertEqual(balance.transfer_destination["type"], "bank-account")

        # Test utility methods
        self.assertTrue(balance.is_active())
        self.assertEqual(balance.get_total_balance(), Decimal("960.69"))  # 905.25 + 55.44

    def test_chargeback_model_parsing(self):
        """Test Chargeback model parses real API response correctly"""
        api_response = {
            "resource": "chargeback",
            "id": "chb_n9z0tp",
            "amount": {"value": "100.00", "currency": "EUR"},
            "settlementAmount": {"value": "-105.00", "currency": "EUR"},
            "createdAt": "2024-01-15T10:00:00+00:00",
            "reversedAt": None,
            "paymentId": "tr_WDqYK6vllg",
            "settlementId": "stl_jDk30akdN",
            "reason": {"code": "fraudulent", "description": "The customer claims the payment was fraudulent"},
            "_links": {
                "self": {
                    "href": "https://api.mollie.com/v2/payments/tr_WDqYK6vllg/chargebacks/chb_n9z0tp",
                    "type": "application/hal+json",
                },
                "payment": {
                    "href": "https://api.mollie.com/v2/payments/tr_WDqYK6vllg",
                    "type": "application/hal+json",
                },
            },
        }

        chargeback = Chargeback(api_response)

        # Test basic fields with camelCase conversion
        self.assertEqual(chargeback.id, "chb_n9z0tp")
        self.assertEqual(chargeback.created_at, "2024-01-15T10:00:00+00:00")  # camelCase -> snake_case
        self.assertEqual(chargeback.reversed_at, None)  # camelCase -> snake_case
        self.assertEqual(chargeback.payment_id, "tr_WDqYK6vllg")  # camelCase -> snake_case
        self.assertEqual(chargeback.settlement_id, "stl_jDk30akdN")  # camelCase -> snake_case

        # Test nested Amount objects
        self.assertEqual(chargeback.amount.decimal_value, Decimal("100.00"))
        self.assertEqual(
            chargeback.settlement_amount.decimal_value, Decimal("-105.00")
        )  # camelCase -> snake_case

        # Test reason nested object
        self.assertEqual(chargeback.get_reason_code(), "fraudulent")
        self.assertEqual(
            chargeback.get_reason_description(), "The customer claims the payment was fraudulent"
        )

        # Test utility methods
        self.assertFalse(chargeback.is_reversed())
        self.assertEqual(chargeback.get_financial_impact(), Decimal("205.00"))  # 100 + abs(-105)

    def test_invoice_model_parsing(self):
        """Test Invoice model parses real API response correctly"""
        api_response = {
            "resource": "invoice",
            "id": "inv_FrvewDA3Pr",
            "reference": "2022.0001",
            "vatNumber": "NL123456789B01",
            "status": "open",
            "issuedAt": "2024-01-01",
            "paidAt": None,
            "dueAt": "2024-01-31",
            "netAmount": {"value": "100.00", "currency": "EUR"},
            "vatAmount": {"value": "21.00", "currency": "EUR"},
            "grossAmount": {"value": "121.00", "currency": "EUR"},
            "lines": [
                {
                    "period": "2024-01",
                    "description": "iDEAL transaction costs",
                    "count": 100,
                    "vatPercentage": 21.0,
                    "amount": {"value": "1.00", "currency": "EUR"},
                }
            ],
            "settlements": ["stl_jDk30akdN", "stl_BkEjN2eAT"],
            "_links": {
                "self": {
                    "href": "https://api.mollie.com/v2/invoices/inv_FrvewDA3Pr",
                    "type": "application/hal+json",
                }
            },
        }

        invoice = Invoice(api_response)

        # Test basic fields with camelCase conversion
        self.assertEqual(invoice.id, "inv_FrvewDA3Pr")
        self.assertEqual(invoice.vat_number, "NL123456789B01")  # camelCase -> snake_case
        self.assertEqual(invoice.issued_at, "2024-01-01")  # camelCase -> snake_case
        self.assertEqual(invoice.paid_at, None)  # camelCase -> snake_case
        self.assertEqual(invoice.due_at, "2024-01-31")  # camelCase -> snake_case

        # Test nested Amount objects
        self.assertEqual(invoice.net_amount.decimal_value, Decimal("100.00"))  # camelCase -> snake_case
        self.assertEqual(invoice.vat_amount.decimal_value, Decimal("21.00"))  # camelCase -> snake_case
        self.assertEqual(invoice.gross_amount.decimal_value, Decimal("121.00"))  # camelCase -> snake_case

        # Test invoice lines parsing
        self.assertEqual(len(invoice.lines), 1)
        line = invoice.lines[0]
        self.assertIsInstance(line, InvoiceLine)
        self.assertEqual(line.description, "iDEAL transaction costs")
        self.assertEqual(line.count, 100)
        self.assertEqual(line.vat_percentage, 21.0)  # camelCase -> snake_case (vatPercentage)
        self.assertEqual(line.amount.decimal_value, Decimal("1.00"))

        # Test utility methods
        self.assertFalse(invoice.is_paid())
        self.assertFalse(invoice.is_overdue())
        self.assertEqual(invoice.calculate_total_lines(), Decimal("100.00"))  # 1.00 * 100
        self.assertEqual(invoice.get_vat_rate(), 21.0)

    def test_organization_model_parsing(self):
        """Test Organization model parses real API response correctly"""
        api_response = {
            "resource": "organization",
            "id": "org_12345678",
            "name": "Mollie B.V.",
            "email": "info@mollie.com",
            "locale": "nl_NL",
            "address": {
                "streetAndNumber": "Keizersgracht 126",
                "postalCode": "1015 CW",
                "city": "Amsterdam",
                "country": "NL",
            },
            "registrationNumber": "30204462",
            "vatNumber": "NL814958520B01",
            "vatRegulation": "dutch",
            "_links": {
                "self": {
                    "href": "https://api.mollie.com/v2/organizations/org_12345678",
                    "type": "application/hal+json",
                }
            },
        }

        organization = Organization(api_response)

        # Test basic fields
        self.assertEqual(organization.id, "org_12345678")
        self.assertEqual(organization.name, "Mollie B.V.")
        self.assertEqual(organization.email, "info@mollie.com")
        self.assertEqual(organization.locale, "nl_NL")

        # Test fields with camelCase conversion
        self.assertEqual(organization.registration_number, "30204462")  # camelCase -> snake_case
        self.assertEqual(organization.vat_number, "NL814958520B01")  # camelCase -> snake_case
        self.assertEqual(organization.vat_regulation, "dutch")  # camelCase -> snake_case

        # Test nested address object
        self.assertIsInstance(organization.address, OrganizationAddress)
        self.assertEqual(
            organization.address.street_and_number, "Keizersgracht 126"
        )  # camelCase -> snake_case
        self.assertEqual(organization.address.postal_code, "1015 CW")  # camelCase -> snake_case
        self.assertEqual(organization.address.city, "Amsterdam")
        self.assertEqual(organization.address.country, "NL")

        # Test utility methods
        self.assertTrue(organization.has_vat_number())
        self.assertEqual(organization.get_display_name(), "Mollie B.V. (org_12345678)")

        # Test address formatting
        expected_address = "Keizersgracht 126, 1015 CW Amsterdam, NL"
        self.assertEqual(organization.address.get_full_address(), expected_address)

    def test_settlement_model_parsing(self):
        """Test Settlement model parses real API response correctly"""
        api_response = {
            "resource": "settlement",
            "id": "stl_jDk30akdN",
            "reference": "1234567.1511.03",
            "createdAt": "2024-01-15T10:00:00+00:00",
            "settledAt": "2024-01-16T10:00:00+00:00",
            "status": "paidout",
            "amount": {"value": "1000.00", "currency": "EUR"},
            "periods": {
                "2024-01": {
                    "revenue": [
                        {
                            "description": "iDEAL",
                            "method": "ideal",
                            "count": 6,
                            "amountNet": {"value": "1000.00", "currency": "EUR"},
                            "amountVat": {"value": "210.00", "currency": "EUR"},
                            "amountGross": {"value": "1210.00", "currency": "EUR"},
                        }
                    ],
                    "costs": [
                        {
                            "description": "iDEAL transaction costs",
                            "method": "ideal",
                            "count": 6,
                            "amountNet": {"value": "-3.54", "currency": "EUR"},
                        }
                    ],
                    "invoiceId": "inv_FrvewDA3Pr",
                }
            },
            "invoiceId": "inv_FrvewDA3Pr",
            "_links": {
                "self": {
                    "href": "https://api.mollie.com/v2/settlements/stl_jDk30akdN",
                    "type": "application/hal+json",
                }
            },
        }

        settlement = Settlement(api_response)

        # Test basic fields with camelCase conversion
        self.assertEqual(settlement.id, "stl_jDk30akdN")
        self.assertEqual(settlement.reference, "1234567.1511.03")
        self.assertEqual(settlement.created_at, "2024-01-15T10:00:00+00:00")  # camelCase -> snake_case
        self.assertEqual(settlement.settled_at, "2024-01-16T10:00:00+00:00")  # camelCase -> snake_case
        self.assertEqual(settlement.status, "paidout")
        self.assertEqual(settlement.invoice_id, "inv_FrvewDA3Pr")  # camelCase -> snake_case

        # Test nested Amount object
        self.assertEqual(settlement.amount.decimal_value, Decimal("1000.00"))

        # Test periods parsing
        self.assertIsNotNone(settlement.periods)
        self.assertIn("2024-01", settlement.periods)
        period = settlement.periods["2024-01"]
        self.assertIsInstance(period, SettlementPeriod)

        # Test period data
        self.assertEqual(period.invoice_id, "inv_FrvewDA3Pr")  # camelCase -> snake_case
        self.assertIsNotNone(period.revenue)
        self.assertIsNotNone(period.costs)

        # Test utility methods
        self.assertTrue(settlement.is_settled())
        self.assertFalse(settlement.is_failed())

        # Test calculations
        total_revenue = settlement.get_total_revenue()
        total_costs = settlement.get_total_costs()
        self.assertEqual(total_revenue, Decimal("1000.00"))
        self.assertEqual(total_costs, Decimal("-3.54"))

    def test_balance_transaction_parsing(self):
        """Test BalanceTransaction model parses correctly"""
        api_response = {
            "resource": "balance_transaction",
            "id": "baltr_QM24QwzUWR4ev4Xfgyt29A",
            "type": "payment",
            "resultAmount": {"value": "96.46", "currency": "EUR"},
            "initialAmount": {"value": "100.00", "currency": "EUR"},
            "deductions": [
                {"type": "fee", "amount": {"value": "3.54", "currency": "EUR"}, "description": "Payment fee"}
            ],
            "createdAt": "2024-01-15T10:00:00+00:00",
            "context": {"paymentId": "tr_WDqYK6vllg"},
        }

        transaction = BalanceTransaction(api_response)

        # Test basic fields
        self.assertEqual(transaction.id, "baltr_QM24QwzUWR4ev4Xfgyt29A")
        self.assertEqual(transaction.type, "payment")
        self.assertEqual(transaction.created_at, "2024-01-15T10:00:00+00:00")  # camelCase -> snake_case

        # Test nested Amount objects
        self.assertEqual(transaction.result_amount.decimal_value, Decimal("96.46"))  # camelCase -> snake_case
        self.assertEqual(
            transaction.initial_amount.decimal_value, Decimal("100.00")
        )  # camelCase -> snake_case

        # Test deductions array
        self.assertIsNotNone(transaction.deductions)
        self.assertEqual(len(transaction.deductions), 1)

        # Test context object
        self.assertIsNotNone(transaction.context)
        self.assertEqual(transaction.context["paymentId"], "tr_WDqYK6vllg")

        # Test utility method
        self.assertEqual(transaction.get_total_deductions(), Decimal("3.54"))

    def test_field_normalization_edge_cases(self):
        """Test edge cases in field name normalization"""
        from verenigingen.verenigingen_payments.core.models.base import BaseModel

        base = BaseModel()

        # Test various camelCase patterns
        test_cases = [
            ("id", "id"),  # already snake_case
            ("paymentId", "payment_id"),  # simple camelCase
            ("createdAt", "created_at"),  # simple camelCase
            ("vatNumber", "vat_number"),  # acronym
            ("XMLParser", "xml_parser"),  # caps acronym
            ("HTTPResponseCode", "http_response_code"),  # multiple caps
            ("streetAndNumber", "street_and_number"),  # multiple words
            ("availableAmount", "available_amount"),  # available + Amount
            ("_links", "_links"),  # underscore prefix
            ("__meta", "__meta"),  # double underscore
        ]

        for input_name, expected in test_cases:
            result = base._normalize_attribute_name(input_name)
            self.assertEqual(result, expected, f"Failed for {input_name}: got {result}, expected {expected}")

    def test_model_validation_methods(self):
        """Test that model validation methods work correctly"""
        # Test valid amount
        valid_amount_data = {"value": "100.00", "currency": "EUR"}
        from verenigingen.verenigingen_payments.core.models.base import Amount

        amount = Amount(valid_amount_data)
        self.assertTrue(amount.validate())

        # Test invalid amount
        invalid_amount_data = {"value": "", "currency": "EUR"}
        invalid_amount = Amount(invalid_amount_data)
        self.assertFalse(invalid_amount.validate())


if __name__ == "__main__":
    unittest.main()
