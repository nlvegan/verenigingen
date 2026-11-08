# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
#1924: the Ponto client wrappers must not discard the HTTP status.

``PontoClient._handle_error_response`` raises ``PontoAPIError(status_code=N)``,
``PontoAuthenticationError`` (401) or ``PontoRateLimitError`` (429). The wrapper methods of
``PontoPaymentClient`` / ``PontoBetaalverzoekClient`` used to catch ``Exception`` and re-raise
a fresh ``PontoAPIError`` with NO ``status_code``, so a 404 and a 503 were indistinguishable
to any caller reading ``exc.status_code`` / ``exc.response.status_code``.

Only the transport is stubbed (``requests.Session.get/post/delete``, the token manager and
``time.sleep``): the real wrapper, the real ``PontoClient``, ``with_retry`` and
``_handle_error_response`` all run. The exception asserted is the one that SURFACES from the
wrapper method, not one reached through ``__context__``.

Fixture shortcut, stated: Ponto Settings (mTLS flag, one enabled account mapping) is written
with ``settings.save()`` so the Betaalverzoek client's ``_verify_pis_enabled`` passes.

Usage:
    bench --site test_site_8 run-tests --app verenigingen \\
        --module verenigingen.tests.sepa.test_ponto_client_wrapper_status
"""

from contextlib import ExitStack
from unittest.mock import patch

import frappe
import requests

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
from verenigingen.tests.sepa.test_ponto_status_poll import _response
from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoAPIError,
    PontoAuthenticationError,
    PontoRateLimitError,
)

CLIENT_MODULE = "verenigingen.verenigingen_payments.ponto.core.ponto_client"


def _root_causes(exc):
    seen = []
    while exc is not None and exc not in seen:
        seen.append(exc)
        exc = exc.__cause__ or exc.__context__
    return seen


# name -> (what the transport does, expected type, expected status_code or None)
HTTP_CASES = {
    "404": (lambda: _response(404, headers={"Retry-After": "3"}), PontoAPIError, 404),
    "400": (lambda: _response(400, headers={"Retry-After": "3"}), PontoAPIError, 400),
    "500": (lambda: _response(500, headers={"Retry-After": "3"}), PontoAPIError, 500),
    "503": (lambda: _response(503, headers={"Retry-After": "3"}), PontoAPIError, 503),
    "401": (lambda: _response(401, headers={"Retry-After": "3"}), PontoAuthenticationError, None),
    "429": (lambda: _response(429, headers={"Retry-After": "3"}), PontoRateLimitError, None),
}


class TestPontoClientWrapperStatus(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        settings = frappe.get_single("Ponto Settings")
        settings.use_ibanity_mtls = 1  # _verify_pis_enabled needs it; no certificate is configured, the transport is stubbed
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "wrap-id"
        settings.sandbox_client_secret = "wrap-secret"
        settings.ibanity_client_id = "wrap-ibanity"
        settings.ibanity_client_secret = "wrap-ibanity-secret"
        settings.set("bank_account_mappings", [])
        settings.append("bank_account_mappings", {"ponto_account_id": "wrap-account", "enabled": 1})
        settings.flags.ignore_validate = True
        settings.flags.ignore_links = True
        settings.flags.ignore_mandatory = True
        settings.save()

    def _stubbed_transport(self, behaviour):
        def fake(session, url, **kwargs):
            if isinstance(behaviour, Exception):
                raise behaviour
            return behaviour()

        stack = ExitStack()
        token = stack.enter_context(patch(f"{CLIENT_MODULE}.PontoTokenManager"))
        token.return_value.get_valid_token.return_value = "token"
        for verb in ("get", "post", "delete"):
            stack.enter_context(patch.object(requests.Session, verb, fake))
        stack.enter_context(patch("time.sleep"))
        return stack

    def _calls(self):
        """Every wrapper method that talks to Ponto: (label, callable(client))."""
        from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
            PontoBetaalverzoekClient,
        )
        from verenigingen.verenigingen_payments.ponto.clients.payment_client import PontoPaymentClient

        pay_kwargs = dict(creditor_name="x", creditor_iban=TestIBAN.ABN_AMRO_1, remittance_info="r")
        return [
            (PontoPaymentClient, "payment.create", lambda c: c.create_payment(
                account_id="acc", amount=10, currency="EUR", **pay_kwargs)),
            (PontoPaymentClient, "payment.get", lambda c: c.get_payment("acc", "p1")),
            (PontoPaymentClient, "payment.list", lambda c: c.list_payments("acc")),
            (PontoPaymentClient, "payment.delete", lambda c: c.delete_payment("acc", "p1")),
            (PontoBetaalverzoekClient, "request.create", lambda c: c.create_payment_request(
                amount=10, **pay_kwargs)),
            (PontoBetaalverzoekClient, "request.get", lambda c: c.get_payment_request("r1")),
            (PontoBetaalverzoekClient, "request.list", lambda c: c.list_payment_requests()),
            (PontoBetaalverzoekClient, "request.delete", lambda c: c.delete_payment_request("r1")),
        ]

    def _surfaced(self, client_class, call, behaviour):
        with self._stubbed_transport(behaviour):
            client = client_class()
            try:
                call(client)
            except Exception as e:
                return e
        self.fail("the wrapper did not raise")

    def test_every_wrapper_method_surfaces_the_http_status_and_type(self):
        for name, (behaviour, expected_type, expected_status) in HTTP_CASES.items():
            for client_class, label, call in self._calls():
                with self.subTest(http=name, method=label):
                    exc = self._surfaced(client_class, call, behaviour)
                    self.assertIsInstance(exc, expected_type)
                    self.assertEqual(getattr(exc, "status_code", None), expected_status)

    def test_a_transport_error_surfaces_as_status_less_api_error_with_the_request_exception_beneath(self):
        for client_class, label, call in self._calls():
            with self.subTest(method=label):
                exc = self._surfaced(client_class, call, requests.ConnectionError("refused"))
                self.assertIsInstance(exc, PontoAPIError)
                self.assertIsNone(exc.status_code)  # no HTTP response exists, so none is invented
                self.assertTrue(
                    any(isinstance(e, requests.ConnectionError) for e in _root_causes(exc)),
                    "the request exception must stay reachable",
                )

    def test_a_non_ponto_failure_is_still_wrapped_as_a_status_less_api_error_from_its_cause(self):
        """Control: the wrapping contract for anything that is not a Ponto error is unchanged."""
        for client_class, label, call in self._calls():
            with self.subTest(method=label):
                with patch(f"{CLIENT_MODULE}.PontoClient.get", side_effect=RuntimeError("boom")), patch(
                    f"{CLIENT_MODULE}.PontoClient.post", side_effect=RuntimeError("boom")
                ), patch(f"{CLIENT_MODULE}.PontoClient.delete", side_effect=RuntimeError("boom")), patch(
                    f"{CLIENT_MODULE}.PontoClient.get_paginated", side_effect=RuntimeError("boom")
                ):
                    client = client_class()
                    with self.assertRaises(PontoAPIError) as ctx:
                        call(client)
                self.assertIsNone(ctx.exception.status_code)
                self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
