# Copyright (c) 2026, Verenigingen
"""PontoPaymentRequest status transitions mark a status only after the Payment
Entry it triggers actually succeeds -- #1323, the #1288 class.

Before this fix, both ``refresh_status()`` and ``update_status_from_webhook()``
saved the new status (e.g. "Executed") BEFORE calling ``create_payment_entry()``,
and ``create_payment_entry()`` wrapped its whole body in a bare try/except that
only logged and returned on failure. Any PE failure therefore left the request
permanently stuck at "Executed" with no Payment Entry and no automatic retry --
the only trace was an Error Log row.

Most of this file forces a PE failure by patching ``create_payment_entry()``
itself, to isolate the ORDERING/atomicity half of the fix from PE-creation
correctness (covered separately by test_ponto_payment_entry_creation.py and
test_ponto_doctype_coverage.py). That patch replaces the whole method, so it
cannot discriminate the SECOND half of the fix -- that ``create_payment_entry()``
itself no longer swallows its own exceptions.
TestCreatePaymentEntryPropagatesFailure below forces a REAL failure inside the
unmocked method body instead, specifically to red/green that half.

Usage:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import PaymentStatus, PontoTestDataFactory
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
    PontoPaymentRequest,
)

PAY_CLIENT_PATH = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
_PE_FAILURE_MESSAGE = "Simulated Payment Entry failure (#1323 test)"


def _mock_ponto_get_payment_client(status="executed"):
    """A get_payment_client() stand-in whose get_payment() reports `status`."""
    client = MagicMock()
    payment = MagicMock()
    payment.status = status
    client.get_payment.return_value = payment
    return client


class _PontoPaymentRequestFixtures:
    """Shared fixture helpers: a real EUR company/bank account (owned, shared
    master data -- see get_eur_test_company()'s own docstring) plus a Ponto
    Settings mapping and Supplier/request builders private to this module.
    """

    TEST_PONTO_ACCOUNT_ID = "ppr-1323-test-account"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.bank_account = get_eur_bank_account(cls.company)
        cls._settings_backup = SingletonBackup("Ponto Settings")
        cls._settings_backup.backup()
        cls._create_ponto_settings_mapping()

    @classmethod
    def tearDownClass(cls):
        cls._settings_backup.restore()
        super().tearDownClass()

    @classmethod
    def _create_ponto_settings_mapping(cls):
        """Shared, class-scoped fixture: a Ponto Settings bank-account mapping.

        Named `_create_*` so scan_order_dependence.py's COMMIT_EXEMPT applies --
        the commit below is load-bearing, not a leak: this runs once in
        setUpClass, and EnhancedTestCase's per-test rollback would otherwise
        undo it after the FIRST test method in the class, leaving every later
        method without the mapping.
        """
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_client_id = "test_client_id"
        settings.sandbox_client_secret = "test_client_secret"
        settings.sandbox_mode = 1
        settings.set("bank_account_mappings", [])
        settings.append(
            "bank_account_mappings",
            {
                "ponto_account_id": cls.TEST_PONTO_ACCOUNT_ID,
                "bank_account": cls.bank_account,
                "enabled": 1,
            },
        )
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        settings.flags.ignore_validate = False
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_supplier(self, name_hint):
        supplier = frappe.get_doc(
            {
                "doctype": "Supplier",
                "supplier_name": f"_Test PPR Supplier {name_hint} {frappe.generate_hash(length=6)}",
                "supplier_group": "All Supplier Groups",
                "supplier_type": "Company",
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Supplier", supplier.name)
        return supplier

    def _create_ponto_request(self, supplier, status="Signed", amount=42.0):
        """A Ponto Payment Request already past signing -- inserted directly at
        the target status/ponto_payment_id rather than driven through submit(),
        matching the existing TestPontoPaymentRequest coverage suite's own
        pattern (test_ponto_doctype_coverage.py), since before_submit() would
        otherwise hit the real Ponto API to create the payment.
        """
        req = frappe.new_doc("Ponto Payment Request")
        req.ponto_account = self.TEST_PONTO_ACCOUNT_ID
        req.amount = amount
        req.currency = "EUR"
        req.creditor_name = supplier.supplier_name
        req.creditor_iban = "NL91ABNA0417164300"
        req.remittance_info = "Test payment #1323"
        req.reference_doctype = "Supplier"
        req.reference_name = supplier.name
        req.status = status
        req.ponto_payment_id = f"ponto_pay_{frappe.generate_hash(length=10)}"
        req.insert(ignore_permissions=True)
        self.track_doc("Ponto Payment Request", req.name)
        return req


class TestRefreshStatusAtomicity(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """refresh_status(): a PE failure must not leave the status stuck "Executed"."""

    def test_pe_failure_leaves_status_unchanged_and_raises(self):
        req = self._create_ponto_request(self._create_supplier("Refresh"), status="Signed")
        self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            with patch.object(
                PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
            ):
                with self.assertRaises(frappe.ValidationError):
                    req.refresh_status()

        reloaded = frappe.get_doc("Ponto Payment Request", req.name)
        self.assertEqual(
            reloaded.status, "Signed", "status must NOT be stuck at Executed when the PE fails"
        )
        self.assertFalse(reloaded.payment_entry)
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": req.name}),
            "no Payment Entry may be left behind for a refused attempt",
        )

    def test_pe_success_updates_status_and_msgprint(self):
        """Control: the happy path still works exactly as before."""
        req = self._create_ponto_request(self._create_supplier("RefreshOK"), status="Signed")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("signed")):
            result = req.refresh_status()

        self.assertEqual(result["status"], "Signed")


class TestCreatePaymentEntryPropagatesFailure(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """create_payment_entry() itself: a real failure must propagate, not be
    logged and swallowed -- the second half of the #1323 fix, which a
    patched-out create_payment_entry() (as used above) cannot discriminate."""

    def test_missing_party_account_propagates_instead_of_being_swallowed(self):
        req = self._create_ponto_request(self._create_supplier("RealFail"), status="Signed")

        # get_party_account() returning None (no configured Payable account
        # anywhere in the resolution chain) is a REAL, unmocked failure mode
        # of create_payment_entry() itself: `pe.paid_to` stays unset and
        # Payment Entry.insert() raises for the missing mandatory field. Only
        # the account-resolution dependency is patched -- create_payment_entry()
        # runs for real.
        with patch("erpnext.accounts.party.get_party_account", return_value=None):
            with self.assertNoErrorLog():
                with self.assertRaises(frappe.MandatoryError):
                    req.create_payment_entry()

        self.assertFalse(
            frappe.db.get_value("Ponto Payment Request", req.name, "payment_entry"),
            "a failed attempt must not be recorded as having created a Payment Entry",
        )
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": req.name}),
            "no Payment Entry may be left behind for a refused attempt",
        )


class TestUpdateStatusFromWebhookAtomicity(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """update_status_from_webhook() has the identical shape as refresh_status()."""

    def test_pe_failure_leaves_status_unchanged_and_raises(self):
        req = self._create_ponto_request(self._create_supplier("Webhook"), status="Signed")

        with patch.object(
            PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
        ):
            with self.assertRaises(RuntimeError):
                req.update_status_from_webhook("Executed")

        reloaded = frappe.get_doc("Ponto Payment Request", req.name)
        self.assertEqual(reloaded.status, "Signed")
        self.assertFalse(reloaded.payment_entry)

    def test_webhook_entrypoint_reports_failure_and_leaves_request_retryable(self):
        """The real webhook entrypoint: handle_payment_request_closed() already
        wraps each row in its own savepoint and rolls back on ANY exception --
        this is what that isolation is FOR once create_payment_entry() stops
        swallowing its own exception. Before this fix the swallow meant that
        savepoint never saw a failure at all: the status save always "succeeded".
        """
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_request_closed,
        )

        req = self._create_ponto_request(self._create_supplier("WebhookEntry"), status="Signed")
        self.expectErrorLog(f"Payment webhook status update failed: {req.name}")

        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id=req.ponto_payment_id,
                status=PaymentStatus.EXECUTED,
            )
        )

        with patch.object(
            PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
        ):
            result = handle_payment_request_closed(payload)

        self.assertIn(req.name, result.get("failed_requests") or [])
        self.assertNotIn(req.name, result.get("updated_requests") or [])

        reloaded_status = frappe.db.get_value("Ponto Payment Request", req.name, "status")
        self.assertEqual(
            reloaded_status, "Signed", "a redelivered webhook must be able to retry this request"
        )
        self.assertFalse(frappe.db.get_value("Ponto Payment Request", req.name, "payment_entry"))


class TestRetryCreatesExactlyOnePaymentEntry(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """A retry after a transient PE failure, once the cause is gone, must
    create exactly one real Payment Entry -- not a second one alongside a
    stray first attempt from before the fix."""

    def test_retry_after_pe_failure_creates_exactly_one_payment_entry(self):
        req = self._create_ponto_request(self._create_supplier("Retry"), status="Signed")
        self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            with patch.object(
                PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
            ):
                with self.assertRaises(frappe.ValidationError):
                    req.refresh_status()

            # No PE from the failed attempt, and the status must still be
            # retryable ("Signed" != "Executed" is what re-drives the PE
            # attempt on the next refresh).
            self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": req.name}))
            self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Signed")

            # Real retry: create_payment_entry() runs for real this time,
            # against the same EUR test company/bank account/Supplier this
            # module owns.
            req.reload()
            result = req.refresh_status()

        self.assertEqual(result["status"], "Executed")
        req.reload()
        self.assertEqual(req.status, "Executed")
        self.assertTrue(req.payment_entry, "a successful retry must latch payment_entry")

        pe = frappe.get_doc("Payment Entry", req.payment_entry)
        self.assertEqual(pe.docstatus, 1)

        entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": req.name, "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(len(entries), 1, f"the payment was posted more than once: {entries}")
