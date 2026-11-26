"""
Part of #1891: ``d.get(k, "").strip()`` raises when the key is PRESENT with value None.

Each test drives the real entry point with the None value a caller can actually send
(a JSON ``null``, a short CSV row that ``csv.DictReader`` pads with ``None``, or a Pay.nl
response carrying ``"status": null``) and asserts the request is handled instead of dying
on ``'NoneType' object has no attribute ...``.

Only the outbound boundaries are stubbed (Mollie service, Pay.nl HTTP session).
"""

import json
from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_bulk_payment_creation as bulk_page
from verenigingen.templates.pages import mollie_subscription_recreation as recreation_page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg

NONETYPE = "NoneType"


def _insert_fixture_row(doc):
    """Persist a fixture row; the bypass lives here, as in test_ing_doctype_coverage."""
    doc.insert(ignore_permissions=True)
    return doc


class _FakeMollieService:
    """Mollie API boundary: never reached for the rows under test."""

    def __init__(self, *args, **kwargs):
        pass

    def debug_customer(self, customer_id):
        return {
            "subscriptions": [
                {
                    "id": "sub_1891",
                    "status": "active",
                    "amount": "25.00 EUR",
                    "interval": "1 month",
                    "description": "Dues",
                    "next_payment_date": "2030-01-01",
                    "mandate_id": "mdt_1891",
                }
            ]
        }


class TestVolunteerExpenseNullDescription(EnhancedTestCase):
    def test_json_null_description_is_a_validation_error_not_a_crash(self):
        from verenigingen.services.volunteer.expense_submission_service import (
            get_expense_submission_service,
        )

        # submit_multiple_expenses (the whitelisted page endpoint) json.loads the payload,
        # so a JSON null arrives here as None.
        expenses = json.loads(
            '[{"description": null, "amount": 10, "expense_date": null,'
            ' "organization_type": "National", "category": "x"}]'
        )
        result = get_expense_submission_service().submit_multiple_expenses_grouped(expenses)

        self.assertFalse(result.success)
        self.assertIn("description", [e["field"] for e in result.errors])


class TestSEPAGatewayNullIban(EnhancedTestCase):
    def test_json_null_iban_is_refused_as_missing(self):
        donation = self.create_test_donation(amount=15.0, mode_of_payment="SEPA Direct Debit", paid=0)

        result = pg.process_donation_payment(
            donation_id=donation.name,
            payment_method="SEPA Direct Debit",
            form_data={"donor_iban": None},
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["payment_result"]["status"], "error")
        self.assertIn("IBAN is required", result["payment_result"]["message"])


class TestMollieCsvShortRow(EnhancedTestCase):
    """csv.DictReader gives None for a column a short row does not reach."""

    # customer_id is the LAST column, so the one-field row "foo" has customer_id None.
    CSV = "note,customer_id\nfoo\nbar,cst_1891_valid\n"

    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()

    def tearDown(self):
        frappe.set_user(self._original_user)
        super().tearDown()

    def test_bulk_payment_validation_skips_row_without_customer_id(self):
        with self.as_role("Verenigingen Administrator"):
            with patch.object(bulk_page, "MollieDebugService", _FakeMollieService):
                result = bulk_page.validate_csv_members(self.CSV)

        self.assertNotIn(NONETYPE, str(result.get("error")), result)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual([r["customer_id"] for r in result["results"]], ["cst_1891_valid"])

    def test_subscription_export_skips_row_without_customer_id(self):
        with self.as_role("Verenigingen Administrator"):
            with patch.object(recreation_page, "MollieDebugService", _FakeMollieService):
                result = recreation_page.export_subscriptions_from_customers(self.CSV)

        self.assertNotIn(NONETYPE, str(result.get("error")), result)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["subscription_count"], 1)
        self.assertIn("cst_1891_valid", result["csv_content"])


class _FakeResponse:
    status_code = 200
    text = '{"status": null}'

    def json(self):
        return json.loads(self.text)


class _FakeSession:
    def request(self, **kwargs):
        return _FakeResponse()


class TestINGMandateSyncNullStatus(EnhancedTestCase):
    def test_pay_nl_null_status_is_a_no_change_not_a_crash(self):
        from verenigingen.verenigingen_payments.ing_checkout.api.mandate import sync_mandate_status
        from verenigingen.verenigingen_payments.ing_checkout.client import PayNLClient

        mandate = frappe.new_doc("ING Checkout Mandate")
        mandate.mandate_id = f"MANDATE-{frappe.generate_hash(length=8)}"
        mandate.mandate_type = "flexible"
        mandate.status = "Active"
        mandate.debtor_name = "Jan de Vries"
        mandate.debtor_iban = "NL91ABNA0417164300"
        _insert_fixture_row(mandate)

        client = PayNLClient(settings=object())
        client._session = _FakeSession()  # HTTP boundary: Pay.nl answers {"status": null}
        with patch(
            "verenigingen.verenigingen_payments.ing_checkout.client.get_client", return_value=client
        ):
            result = sync_mandate_status(mandate.name)

        self.assertTrue(result["success"], result)
        self.assertFalse(result["changed"])
        self.assertEqual(result["status"], "Active")
