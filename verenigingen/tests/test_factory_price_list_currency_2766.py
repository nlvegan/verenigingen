"""#2766: a test invoice in company currency must not need an exchange rate.

`_ensure_selling_price_list(currency)` returned "Standard Selling" whatever ITS
currency was (INR on a fresh erpnext site). erpnext's `set_price_list_currency`
then overwrote the invoice's `price_list_currency` with INR and called
`get_exchange_rate(INR, EUR)`. With no stored rate that is a live provider fetch,
which erpnext refuses unless the session user is a System User -- so a EUR
invoice built by the factory passed or errored depending on which session user
an EARLIER module in the shard left behind (13 SEPA XML errors on CI shard 3).
"""

from unittest import mock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


def _refuse_exchange_rate(*args, **kwargs):
    raise AssertionError(f"get_exchange_rate called for a company-currency invoice: {args}")


class TestFactoryPriceListCurrency2766(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.company = get_eur_test_company()
        self.company_currency = frappe.db.get_value("Company", self.company, "default_currency")
        # Precondition: the defect needs a selling list named "Standard Selling" in a
        # currency OTHER than the company's (true on a fresh erpnext site: INR). Fail
        # loudly rather than pass vacuously where it does not hold.
        self.assertNotEqual(
            frappe.db.get_value("Price List", "Standard Selling", "currency"),
            self.company_currency,
            "precondition: 'Standard Selling' must be in a foreign currency for this test to mean anything",
        )
        # Decoy (#2772): the NEWEST enabled selling list is in a foreign currency. Without
        # it, a wrong helper returning "any enabled selling list" passes on a site that
        # already holds a "Test Selling EUR" (get_value orders by creation DESC).
        foreign = "USD" if self.company_currency != "USD" else "INR"
        self.decoy = frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": f"ZZ Decoy Selling {foreign} {frappe.generate_hash(length=6)}",
                "selling": 1,
                "currency": foreign,
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(
            frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name"),
            self.decoy.name,
            "control: the decoy must be what 'any enabled selling list' returns",
        )

    def test_factory_invoice_needs_no_exchange_rate(self):
        member = self.create_test_member(first_name="PlcCurrency", last_name="Probe2766")
        with mock.patch(
            "erpnext.controllers.accounts_controller.get_exchange_rate",
            side_effect=_refuse_exchange_rate,
        ):
            invoice = self.create_test_sales_invoice(customer=member.name, grand_total=10.0, company=self.company)

        self.assertEqual(invoice.price_list_currency, self.company_currency)
        self.assertEqual(
            frappe.db.get_value("Price List", invoice.selling_price_list, "currency"),
            self.company_currency,
        )
        self.assertEqual(invoice.plc_conversion_rate, 1.0)

    def test_core_factory_price_list_matches_currency(self):
        """The CoreTestDataFactory copy of the helper (same clone family) honours currency too."""
        from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory

        factory = CoreTestDataFactory.__new__(CoreTestDataFactory)
        name = factory._ensure_selling_price_list(self.company_currency)
        self.assertEqual(frappe.db.get_value("Price List", name, "currency"), self.company_currency)
        self.assertEqual(frappe.db.get_value("Price List", name, "selling"), 1)


class TestSepaFactoryPriceListCurrency2766(EnhancedTestCase):
    """The SEPA factory's own `create_test_sales_invoice` set no price list at all, so
    it fell through to the site default ("Standard Selling", INR on a fresh site)."""

    def setUp(self):
        super().setUp()
        self.company = get_eur_test_company()
        self.company_currency = frappe.db.get_value("Company", self.company, "default_currency")
        self.assertNotEqual(
            frappe.db.get_value("Price List", "Standard Selling", "currency"),
            self.company_currency,
            "precondition: 'Standard Selling' must be in a foreign currency for this test to mean anything",
        )

    def test_sepa_factory_invoice_needs_no_exchange_rate(self):
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        factory = SEPATestDataFactory(seed=2766, use_faker=False)
        customer = factory.create_test_customer().name
        with mock.patch(
            "erpnext.controllers.accounts_controller.get_exchange_rate",
            side_effect=_refuse_exchange_rate,
        ):
            invoice = factory.create_test_sales_invoice(
                customer=customer, grand_total=10.0, company=self.company
            )

        self.assertEqual(invoice.price_list_currency, self.company_currency)
        self.assertEqual(
            frappe.db.get_value("Price List", invoice.selling_price_list, "currency"),
            self.company_currency,
        )
