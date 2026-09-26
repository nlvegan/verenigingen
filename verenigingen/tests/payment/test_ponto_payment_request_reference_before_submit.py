# Copyright (c) 2026, Verenigingen
"""before_submit() must refuse a misconfigured Ponto Payment Request BEFORE the
real Ponto API call -- #1379, a follow-up to #1323/PR #1383.

#1323 made create_payment_entry()'s four misconfiguration guards (no mapped
bank account, no Company on the bank account, no linked GL Account, no
reference Supplier/Employee) RAISE instead of silently returning -- correct,
since a silent return released the caller's atomic-transition savepoint and
committed "Executed" with no Payment Entry and no trail.

But before_submit() already calls the real Ponto API (create_ponto_payment())
with NONE of those four things checked, and reference_doctype/reference_name
are not allow_on_submit -- so a request submitted with a missing prerequisite
gets a REAL SEPA payment sent, and then the create_payment_entry() guard
raises PERMANENTLY on every later status refresh/webhook delivery, with no
way to add the missing reference to the already-submitted document (amending
would re-fire a real payment).

This file red/greens the fix: the same four checks
(``PontoPaymentRequest._validate_payment_entry_prerequisites()``) now run
from ``before_submit()`` too, BEFORE ``create_ponto_payment()``, so a
misconfigured request never reaches the Ponto API at all.

Reuses ``_PontoPaymentRequestFixtures`` (company/bank-account/Ponto-Settings-
mapping/Supplier/misconfigured-bank-account builders) from
test_ponto_payment_request_paid_after_pe.py rather than re-declaring them --
the duplicate-helper validator (#1044) flags a second near-identical copy of
those bodies as exactly the "fix goes to die in the other copy" shape it
exists to catch. Only the request-builder here is genuinely new: the shared
mixin's own ``_create_ponto_request`` inserts directly at a target status
(bypassing submit()), which is the wrong shape for a test that must exercise
the REAL ``before_submit()`` hook.

Usage:
    bench --site test_site_6 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_payment_request_reference_before_submit
"""

from unittest.mock import MagicMock, patch as mock_patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    _PontoPaymentRequestFixtures,
)

PAY_CLIENT_PATH = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"


class TestPontoPaymentRequestPrerequisitesBeforeSubmit(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """Each of the four PE-creation prerequisites must be refused at submit
    time, before the mocked Ponto client is ever invoked."""

    def _build_draft_request(self, **kwargs):
        """An UNSUBMITTED Ponto Payment Request, built field-by-field (unlike
        the mixin's ``_create_ponto_request``, which inserts directly at a
        target status/ponto_payment_id and never calls submit()). Every test
        below calls ``.submit()`` on the result itself, to exercise the real
        ``before_submit()`` hook the #1379 fix lives in.
        """
        req = frappe.new_doc("Ponto Payment Request")
        req.ponto_account = kwargs.pop("ponto_account", self.TEST_PONTO_ACCOUNT_ID)
        req.amount = kwargs.pop("amount", 42.0)
        req.currency = "EUR"
        req.creditor_name = kwargs.pop("creditor_name", "Test Creditor")
        req.creditor_iban = kwargs.pop("creditor_iban", "NL91ABNA0417164300")
        req.remittance_info = kwargs.pop("remittance_info", "Test payment #1379")
        req.update(kwargs)
        req.insert(ignore_permissions=True)
        self.track_doc("Ponto Payment Request", req.name)
        return req

    # -- guard 4: no reference party -----------------------------------------

    def test_missing_reference_never_calls_api(self):
        """No reference Supplier/Employee -> refused before create_payment()."""
        req = self._build_draft_request()  # no reference_doctype/reference_name
        fake_client = MagicMock()

        with mock_patch(PAY_CLIENT_PATH, return_value=fake_client):
            with self.assertRaises(frappe.ValidationError) as cm:
                req.submit()

        self.assertIn("no reference Supplier or Employee", str(cm.exception))
        fake_client.create_payment.assert_not_called()
        req.reload()
        self.assertEqual(req.docstatus, 0, "a refused submit must leave the document a Draft")
        self.assertFalse(req.ponto_payment_id)

    # -- guard 1: no bank account mapped for this Ponto account --------------

    def test_unmapped_ponto_account_never_calls_api(self):
        """No Ponto Settings mapping for this account -> refused before the API call."""
        supplier = self._create_supplier("Unmapped")
        req = self._build_draft_request(
            ponto_account="ppr-1379-not-mapped-anywhere",
            reference_doctype="Supplier",
            reference_name=supplier.name,
        )
        fake_client = MagicMock()

        with mock_patch(PAY_CLIENT_PATH, return_value=fake_client):
            with self.assertRaises(frappe.ValidationError):
                req.submit()

        fake_client.create_payment.assert_not_called()
        req.reload()
        self.assertEqual(req.docstatus, 0)

    # -- guard 2: bank account has no Company ---------------------------------

    def test_bank_account_without_company_never_calls_api(self):
        supplier = self._create_supplier("NoCompany")
        bank_account = self._make_bank_account_without_company("A")
        ctx = self._make_ponto_mapping("ppr-1379-no-company", bank_account)
        try:
            req = self._build_draft_request(
                ponto_account="ppr-1379-no-company",
                reference_doctype="Supplier",
                reference_name=supplier.name,
            )
            fake_client = MagicMock()

            with mock_patch(PAY_CLIENT_PATH, return_value=fake_client):
                with self.assertRaises(frappe.ValidationError):
                    req.submit()

            fake_client.create_payment.assert_not_called()
            req.reload()
            self.assertEqual(req.docstatus, 0)
        finally:
            ctx.__exit__(None, None, None)

    # -- guard 3: bank account has no linked GL Account -----------------------

    def test_bank_account_without_gl_account_never_calls_api(self):
        supplier = self._create_supplier("NoGL")
        bank_account = self._make_bank_account_without_gl_account("A")
        ctx = self._make_ponto_mapping("ppr-1379-no-gl", bank_account)
        try:
            req = self._build_draft_request(
                ponto_account="ppr-1379-no-gl",
                reference_doctype="Supplier",
                reference_name=supplier.name,
            )
            fake_client = MagicMock()

            with mock_patch(PAY_CLIENT_PATH, return_value=fake_client):
                with self.assertRaises(frappe.ValidationError):
                    req.submit()

            fake_client.create_payment.assert_not_called()
            req.reload()
            self.assertEqual(req.docstatus, 0)
        finally:
            ctx.__exit__(None, None, None)

    # -- control: a fully-configured request still reaches the API -----------

    def test_fully_configured_request_still_calls_api(self):
        """Control for the four tests above: with every prerequisite satisfied,
        submit() must still reach create_ponto_payment() and call the client.
        Without this control, a guard bug that refuses EVERYTHING would pass
        every test above."""
        supplier = self._create_supplier("Control")
        req = self._build_draft_request(
            reference_doctype="Supplier",
            reference_name=supplier.name,
        )
        fake_client = MagicMock()
        fake_payment = MagicMock()
        fake_payment.id = "ponto-pay-1379-ok"
        fake_payment.redirect_link = "https://myponto.example/sign/1379"
        fake_client.create_payment.return_value = fake_payment

        with mock_patch(PAY_CLIENT_PATH, return_value=fake_client):
            req.submit()

        fake_client.create_payment.assert_called_once()
        req.reload()
        self.assertEqual(req.docstatus, 1)
        self.assertEqual(req.status, "Pending")
        self.assertEqual(req.ponto_payment_id, "ponto-pay-1379-ok")
