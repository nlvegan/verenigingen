"""
Coverage for the non-webhook endpoints of the unified Mollie payment API.

Target: verenigingen/verenigingen_payments/mollie/api/unified_payment_api.py

The webhook entry points (handle_payment_webhook / handle_refund_webhook /
handle_chargeback_webhook) are already covered by
verenigingen_payments/mollie/tests/test_unified_payment_api_webhook.py and
tests/payment/test_unified_webhook_error_scenarios.py. This suite covers the
remaining whitelisted operations:
  - create_donation_payment
  - create_subscription
  - cancel_subscription
  - get_payment_status
  - get_client_info
  - test_webhook_processing
  - initiate_refund

What is real vs. stubbed:
  - The endpoint orchestration (form-dict parsing, required-field validation,
    error->frappe.throw mapping, response shape) IS the logic under test and is
    NOT mocked. The endpoints run through their real @*_api security wrapper as
    Administrator.
  - The CompletePaymentService / MollieClient boundary calls Mollie's HTTP API
    and needs live credentials, so those are replaced with deterministic fakes.

Why form_dict is set inside the user context: entering the test framework's
`set_user` resets frappe.local, so the form_dict has to be populated *after*
the user is switched, otherwise the endpoint sees an empty form (and a
"missing field" test would pass for the wrong reason).
"""

import types
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import unified_payment_api
from verenigingen.verenigingen_payments.mollie.exceptions import (
    MolliePaymentError,
    MollieValidationError,
)
from verenigingen.verenigingen_payments.utils.payment_services.refund_utility import (
    validate_refund_permissions,
)

SERVICE_PATH = (
    "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.CompletePaymentService"
)
# initiate_refund imports MollieClient lazily inside the function body
# (`from ..core.client import MollieClient`), so patch it at its source module.
CLIENT_PATH = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient"


def _fake_service(**methods):
    """Build a callable returning a SimpleNamespace standing in for
    CompletePaymentService (its constructor takes no required args here)."""
    return lambda: types.SimpleNamespace(**methods)


class _MollieClientFake:
    def __init__(self, refund=None, raises=None):
        self._refund = refund
        self._raises = raises
        self.captured = {}

    def create_refund(self, payment_id, refund_data):
        self.captured["payment_id"] = payment_id
        self.captured["refund_data"] = refund_data
        if self._raises is not None:
            raise self._raises
        return self._refund


class _ApiTestBase(EnhancedTestCase):
    @contextmanager
    def _admin_with_form(self, **form):
        """Run as Administrator with frappe.form_dict populated AFTER the user
        switch (set_user resets frappe.local)."""
        with self.set_user("Administrator"):
            frappe.local.form_dict = frappe._dict(form)
            yield


class TestCreateDonationPayment(_ApiTestBase):
    def test_missing_donation_id_throws(self):
        with self._admin_with_form(amount="10.00", return_url="https://x.org/r"):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.create_donation_payment()

    def test_missing_amount_throws(self):
        with self._admin_with_form(donation_id="D-1", return_url="https://x.org/r"):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.create_donation_payment()

    def test_missing_return_url_throws(self):
        with self._admin_with_form(donation_id="D-1", amount="10.00"):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.create_donation_payment()

    def test_nonexistent_donation_throws_not_found(self):
        # All required fields present, but the donation does not exist ->
        # DoesNotExistError is caught and re-thrown as a ValidationError.
        with self._admin_with_form(
            donation_id="NO-SUCH-DONATION", amount="10.00", return_url="https://x.org/r"
        ):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.create_donation_payment()


class TestCreateSubscription(_ApiTestBase):
    def test_missing_email_throws(self):
        with self._admin_with_form(amount="10.00", interval="1 month"):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.create_subscription()

    def test_missing_interval_throws(self):
        with self._admin_with_form(customer_email="x@e.org", amount="10.00"):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.create_subscription()

    def test_success_passes_normalized_data_to_service(self):
        captured = {}

        def create_customer_subscription(customer_data, subscription_data):
            captured["customer"] = customer_data
            captured["subscription"] = subscription_data
            return {"status": "success", "subscription_id": "sub_1"}

        with self._admin_with_form(customer_email="x@e.org", amount="12.5", interval="1 month"):
            with patch(
                SERVICE_PATH,
                _fake_service(create_customer_subscription=create_customer_subscription),
            ):
                result = unified_payment_api.create_subscription()
        self.assertEqual(result["status"], "success")
        # Amount is formatted to 2 decimals as a string inside an amount dict.
        self.assertEqual(captured["subscription"]["amount"], {"currency": "EUR", "value": "12.50"})
        self.assertEqual(captured["subscription"]["interval"], "1 month")
        # customer name falls back to the email when no name supplied.
        self.assertEqual(captured["customer"]["name"], "x@e.org")

    def test_validation_error_mapped_to_throw(self):
        def boom(customer_data, subscription_data):
            raise MollieValidationError("bad data")

        with self._admin_with_form(customer_email="x@e.org", amount="10.00", interval="1 month"):
            with patch(SERVICE_PATH, _fake_service(create_customer_subscription=boom)):
                with self.assertRaises(frappe.ValidationError):
                    unified_payment_api.create_subscription()


class TestCancelSubscription(_ApiTestBase):
    def test_missing_customer_id_throws(self):
        with self._admin_with_form(subscription_id="sub_1"):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.cancel_subscription()

    def test_missing_subscription_id_throws(self):
        with self._admin_with_form(customer_id="cst_1"):
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.cancel_subscription()

    def test_success(self):
        captured = {}

        def cancel_subscription(customer_id, subscription_id, reason):
            captured.update(customer_id=customer_id, subscription_id=subscription_id, reason=reason)
            return {"status": "success"}

        with self._admin_with_form(customer_id="cst_1", subscription_id="sub_1"):
            with patch(SERVICE_PATH, _fake_service(cancel_subscription=cancel_subscription)):
                result = unified_payment_api.cancel_subscription()
        self.assertEqual(result["status"], "success")
        self.assertEqual(captured["reason"], "Customer request")  # default

    def test_payment_error_mapped_to_throw(self):
        def boom(customer_id, subscription_id, reason):
            raise MolliePaymentError("cannot cancel")

        with self._admin_with_form(customer_id="cst_1", subscription_id="sub_1"):
            with patch(SERVICE_PATH, _fake_service(cancel_subscription=boom)):
                with self.assertRaises(frappe.ValidationError):
                    unified_payment_api.cancel_subscription()


class TestGetPaymentStatusAndClientInfo(_ApiTestBase):
    def test_get_payment_status_missing_id_throws(self):
        with self._admin_with_form():
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.get_payment_status()

    def test_get_payment_status_success(self):
        with self._admin_with_form(payment_id="tr_1"):
            with patch(
                SERVICE_PATH,
                _fake_service(get_payment_status=lambda pid: {"status": "paid", "payment_id": pid}),
            ):
                result = unified_payment_api.get_payment_status()
        self.assertEqual(result["payment_id"], "tr_1")

    def test_get_payment_status_error_mapped_to_throw(self):
        def boom(pid):
            raise MolliePaymentError("upstream down")

        with self._admin_with_form(payment_id="tr_1"):
            with patch(SERVICE_PATH, _fake_service(get_payment_status=boom)):
                with self.assertRaises(frappe.ValidationError):
                    unified_payment_api.get_payment_status()

    def test_get_client_info_success(self):
        with self._admin_with_form():
            with patch(
                SERVICE_PATH,
                _fake_service(get_client_info=lambda: {"test_mode": True, "configured": True}),
            ):
                result = unified_payment_api.get_client_info()
        self.assertTrue(result["test_mode"])

    def test_get_client_info_error_mapped_to_throw(self):
        def boom():
            raise Exception("config error")

        with self._admin_with_form():
            with patch(SERVICE_PATH, _fake_service(get_client_info=boom)):
                with self.assertRaises(frappe.ValidationError):
                    unified_payment_api.get_client_info()


class TestTestWebhookProcessing(_ApiTestBase):
    def test_success_in_developer_mode(self):
        # developer_mode is on for the test bench; exercise the happy path.
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode disabled on this bench")
        with self._admin_with_form(payment_id="tr_1"):
            with patch(SERVICE_PATH, _fake_service(process_webhook=lambda pid: {"status": "ok"})):
                result = unified_payment_api.test_webhook_processing()
        self.assertEqual(result["status"], "test_success")
        self.assertEqual(result["payment_id"], "tr_1")

    def test_missing_payment_id_returns_test_error(self):
        # With developer_mode on, a missing payment_id throws inside the body;
        # the endpoint's own broad except catches it and returns a test_error
        # dict (it never re-raises).
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode disabled on this bench")
        with self._admin_with_form():
            result = unified_payment_api.test_webhook_processing()
        self.assertEqual(result["status"], "test_error")


class TestInitiateRefund(_ApiTestBase):
    def test_missing_payment_id_throws(self):
        with self._admin_with_form():
            with self.assertRaises(frappe.ValidationError):
                unified_payment_api.initiate_refund()

    def test_success_full_refund(self):
        refund = types.SimpleNamespace(id="re_1", amount={"value": "10.00", "currency": "EUR"})
        client = _MollieClientFake(refund=refund)
        with self._admin_with_form(payment_id="tr_1"):
            with patch(CLIENT_PATH, return_value=client):
                result = unified_payment_api.initiate_refund()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["refund_id"], "re_1")
        self.assertEqual(result["payment_id"], "tr_1")
        # No amount supplied -> refund_data carries only the description (full refund).
        self.assertNotIn("amount", client.captured["refund_data"])

    def test_partial_refund_passes_amount(self):
        refund = types.SimpleNamespace(id="re_2", amount={"value": "5.00", "currency": "EUR"})
        client = _MollieClientFake(refund=refund)
        with self._admin_with_form(payment_id="tr_1", amount="5"):
            with patch(CLIENT_PATH, return_value=client):
                result = unified_payment_api.initiate_refund()
        self.assertEqual(client.captured["refund_data"]["amount"], {"currency": "EUR", "value": "5.00"})
        self.assertEqual(result["refund_id"], "re_2")

    def test_payment_error_mapped_to_throw(self):
        client = _MollieClientFake(raises=MolliePaymentError("refund failed"))
        with self._admin_with_form(payment_id="tr_1"):
            with patch(CLIENT_PATH, return_value=client):
                with self.assertRaises(frappe.ValidationError):
                    unified_payment_api.initiate_refund()


class TestInitiateRefundEnforcesPermissionCheck(_ApiTestBase):
    """Regression test for #1017.

    initiate_refund() here is a *different, sibling* function from
    refund_utility.py's initiate_refund() (#968/#1021) -- same name, different
    module, no relation. It is gated only by @high_security_api
    (SecurityLevel.HIGH), which ROLE_PROFILE_SECURITY_MAPPING
    (authorization_policy.py) grants to "Verenigingen Chapter Board Member" and
    "Verenigingen Staff" -- populations wider than the CRITICAL-level Treasurer/
    National Board Member #968 was about -- and the function body itself had no
    domain-specific check at all: it read frappe.form_dict and called
    MollieClient.create_refund directly. This test provisions a real Chapter
    Board Member (the widest population @high_security_api admits) and proves
    that population reaches the live Mollie client call before the fix, and is
    refused after it.
    """

    UNAUTHORIZED_USER = "test-cbm-1017@example.com"

    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user

        frappe.set_user("Administrator")
        if frappe.db.exists("User", self.UNAUTHORIZED_USER):
            user = frappe.get_doc("User", self.UNAUTHORIZED_USER)
        else:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self.UNAUTHORIZED_USER,
                    "first_name": "Chapter",
                    "last_name": "Board1017",
                    "enabled": 1,
                    "send_welcome_email": 0,
                    "user_type": "System User",
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", user.name)

        # Provision the same way production actually does: a "role_profiles"
        # Table MultiSelect entry (this exercises the real
        # populate_role_profile_roles() sync), not the deprecated
        # role_profile_name field directly -- see the matching note in
        # test_refund_utility.py::TestRefundEndpointsEnforcePermissionCheck (#968).
        user.role_profiles = []
        user.append("role_profiles", {"role_profile": "Verenigingen Chapter Board Member"})
        user.save(ignore_permissions=True)

        # Confirm the test's own premise before relying on it: this user must
        # actually fail validate_refund_permissions(), or the test proves
        # nothing about the fix.
        self.assertFalse(
            validate_refund_permissions(self.UNAUTHORIZED_USER),
            "test setup invalid: Chapter Board Member must fail validate_refund_permissions()",
        )

    def tearDown(self):
        frappe.set_user(self.original_user)
        super().tearDown()

    def test_unauthorized_role_profile_cannot_initiate_refund(self):
        refund = types.SimpleNamespace(id="re_1017", amount={"value": "10.00", "currency": "EUR"})
        client = _MollieClientFake(refund=refund)

        with self.set_user(self.UNAUTHORIZED_USER):
            frappe.local.form_dict = frappe._dict(payment_id="tr_1017_abc")
            with patch(CLIENT_PATH, return_value=client):
                with self.assertRaises(frappe.PermissionError):
                    unified_payment_api.initiate_refund()

        self.assertNotIn("payment_id", client.captured, "create_refund must never be reached")


class TestInitiateRefundStillWorksForAuthorizedUser(_ApiTestBase):
    """Confirms the #1017 fix does not lock out a legitimate refunder.

    Provisions a real "Verenigingen Treasurer" the same way production does
    (role_profiles Table MultiSelect + save(), not the deprecated
    role_profile_name field) and confirms initiate_refund() still completes.
    Treasurer holds "Accounts Manager" per role_profile.json, so it must pass
    validate_refund_permissions() -- unlike Chapter Board Member/Staff/National
    Board Member, which #1017's class of test intentionally excludes.
    """

    AUTHORIZED_USER = "test-treasurer-1017@example.com"

    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user

        frappe.set_user("Administrator")
        if frappe.db.exists("User", self.AUTHORIZED_USER):
            user = frappe.get_doc("User", self.AUTHORIZED_USER)
        else:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self.AUTHORIZED_USER,
                    "first_name": "Treasurer",
                    "last_name": "User1017",
                    "enabled": 1,
                    "send_welcome_email": 0,
                    "user_type": "System User",
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", user.name)

        user.role_profiles = []
        user.append("role_profiles", {"role_profile": "Verenigingen Treasurer"})
        user.save(ignore_permissions=True)

        self.assertTrue(
            validate_refund_permissions(self.AUTHORIZED_USER),
            "test setup invalid: Treasurer must pass validate_refund_permissions()",
        )

    def tearDown(self):
        frappe.set_user(self.original_user)
        super().tearDown()

    def test_authorized_role_profile_can_initiate_refund(self):
        refund = types.SimpleNamespace(id="re_1017_ok", amount={"value": "10.00", "currency": "EUR"})
        client = _MollieClientFake(refund=refund)

        with self.set_user(self.AUTHORIZED_USER):
            frappe.local.form_dict = frappe._dict(payment_id="tr_1017_ok")
            with patch(CLIENT_PATH, return_value=client):
                result = unified_payment_api.initiate_refund()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["refund_id"], "re_1017_ok")
        self.assertEqual(client.captured["payment_id"], "tr_1017_ok")
