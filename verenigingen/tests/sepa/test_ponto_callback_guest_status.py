"""
#1815: the Ponto redirect callbacks are allow_guest GETs that switch to the webhook
service user. They used to write a status taken straight from the query string
(?error=access_denied -> Cancelled, any other error -> Rejected), so an anonymous GET
could cancel or reject any Ponto Payment Request / Link, and a known name redirected
somewhere different from an unknown one.

These tests dispatch AS GUEST through frappe.handler.execute_cmd with a real werkzeug
Request, so the whitelist, the @public_api decorator and the REAL get_service_user path
(no patching of the service user) all run. Only the outbound Ponto HTTP client is
replaced, because Ponto is the authority the callback must defer to.

Probe shortcut: the fixtures write ``status`` directly at insert time to stand in for a
request that reached that state through Ponto; the reachability of Signed/Executed is
the real flow's (refresh_status / webhook), not asserted here.

Usage:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_callback_guest_status
"""

import itertools
from unittest.mock import MagicMock, patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN

REQ_CMD = "verenigingen.verenigingen_payments.ponto.api.payment_callback.payment_callback"
LINK_CMD = "verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_link_callback"
PAYMENT_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
LINK_CLIENT = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)
MARKER = "ATTACKER-CHOSEN-1815"
_ip = itertools.count(1)


def _client_reporting(status):
    """Stand-in for the Ponto client; reports ``status`` as the authoritative state."""
    client = MagicMock()
    client.get_payment.return_value = MagicMock(status=status)
    client.get_payment_request.return_value = MagicMock(status=status)
    return client


class TestPontoCallbackGuestStatus(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.webhook_user = self._make_webhook_user()
        frappe.db.set_single_value("Verenigingen Payments Settings", "webhook_user", self.webhook_user)
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")
        self.addCleanup(frappe.set_user, "Administrator")

    def _make_webhook_user(self):
        email = "ponto-cb-1815@example.com"
        if not frappe.db.exists("User", email):
            user = frappe.new_doc("User")
            user.email = email
            user.first_name = "PontoCb"
            user.send_welcome_email = 0
            user.append("roles", {"role": "Verenigingen Webhook User"})
            user.insert(ignore_permissions=True)
        return email

    def _make_ppr(self, status="Pending"):
        doc = frappe.new_doc("Ponto Payment Request")
        doc.ponto_account = "cb-acc"
        doc.amount = 20.00
        doc.currency = "EUR"
        doc.creditor_name = "Org"
        doc.creditor_iban = TestIBAN.ABN_AMRO_1
        doc.remittance_info = "ref"
        doc.status = status
        doc.ponto_payment_id = "ponto-id-1815"
        doc.insert()
        self.track_doc("Ponto Payment Request", doc.name)
        return doc

    def _make_ppl(self, status="Pending Authorization"):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.payment_type = "One-Time"
        doc.amount = 25.00
        doc.currency = "EUR"
        doc.description = "Membership dues"
        doc.creditor_name = "Org"
        doc.creditor_iban = TestIBAN.ABN_AMRO_1
        doc.status = status
        doc.ponto_request_id = "ponto-req-1815"
        doc.redirect_link = "https://myponto.com/sign/req-1815"
        doc.insert()
        self.track_doc("Ponto Payment Link", doc.name)
        return doc

    def _guest_get(self, cmd, **args):
        """Dispatch ``cmd`` as Guest the way the web server would. Returns a dict of
        every guest-visible channel plus the message_log."""
        env = EnvironBuilder(
            path=f"/api/method/{cmd}",
            query_string=args,
            method="GET",
            environ_overrides={"REMOTE_ADDR": f"10.18.{next(_ip) % 250}.{(next(_ip) % 250) + 1}"},
        ).get_environ()
        original_user = frappe.session.user
        frappe.set_user("Guest")
        frappe.local.request = Request(env)
        frappe.local.form_dict = frappe._dict(args)
        frappe.local.response = frappe._dict()
        frappe.local.message_log = []
        try:
            frappe.handler.execute_cmd(cmd)
        finally:
            seen = {
                "response_type": frappe.local.response.get("type"),
                "location": frappe.local.response.get("location"),
                "message_log": list(frappe.local.message_log or []),
            }
            frappe.set_user(original_user)
        return seen

    def _unset_webhook_user(self):
        """get_service_user then falls back to Administrator (its fallback_user default),
        the only identity under which refresh_status() is authorised for the callback:
        it is @high_security_api(FINANCIAL), which the Webhook User role does not meet."""
        self.expectErrorLog("Using Administrator Fallback")
        frappe.db.set_single_value("Verenigingen Payments Settings", "webhook_user", None)
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")

    def _modified_by(self, doctype, name):
        return frappe.db.get_value(doctype, name, ["status", "modified_by", "modified"], as_dict=True)

    # ---- the harm: no status from the query string ----------------------------

    def test_error_in_query_string_does_not_change_request_status(self):
        for initial in ("Pending", "Signed", "Executed"):
            for error in ("access_denied", "server_error"):
                with self.subTest(initial=initial, error=error):
                    doc = self._make_ppr(initial)
                    before = self._modified_by("Ponto Payment Request", doc.name)
                    with patch(PAYMENT_CLIENT, return_value=_client_reporting(initial.lower())):
                        self._guest_get(
                            REQ_CMD,
                            payment_request=doc.name,
                            error=error,
                            error_description=MARKER,
                        )
                    self.assertEqual(self._modified_by("Ponto Payment Request", doc.name), before)

    def test_error_in_query_string_does_not_change_link_status(self):
        for initial in ("Pending Authorization", "Authorized", "Executed"):
            for error in ("access_denied", "server_error"):
                with self.subTest(initial=initial, error=error):
                    doc = self._make_ppl(initial)
                    before = self._modified_by("Ponto Payment Link", doc.name)
                    ponto_says = {"Pending Authorization": "pending", "Authorized": "authorized"}.get(
                        initial, "executed"
                    )
                    with patch(LINK_CLIENT, return_value=_client_reporting(ponto_says)):
                        self._guest_get(LINK_CMD, payment_link=doc.name, error=error)
                    self.assertEqual(self._modified_by("Ponto Payment Link", doc.name), before)

    # ---- control: Ponto, not the caller, is the authority ---------------------

    def test_error_callback_still_adopts_what_ponto_reports(self):
        """Control: the status moves when PONTO says so, with an error param present
        (Ponto says signed; the query string says access_denied). Run under the
        Administrator fallback, the one identity the callback's refresh is authorised
        for. Fails under a 'write nothing' variant and under one that trusts the
        query string."""
        self._unset_webhook_user()
        doc = self._make_ppr("Pending")
        with patch(PAYMENT_CLIENT, return_value=_client_reporting("signed")):
            self._guest_get(REQ_CMD, payment_request=doc.name, error="access_denied")
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Signed")

        link = self._make_ppl("Pending Authorization")
        with patch(LINK_CLIENT, return_value=_client_reporting("authorized")):
            self._guest_get(LINK_CMD, payment_link=link.name, error="access_denied")
        self.assertEqual(frappe.db.get_value("Ponto Payment Link", link.name, "status"), "Authorized")

    # ---- attacker-controlled text is not persisted ----------------------------

    def test_attacker_text_is_not_written_to_error_log(self):
        doc = self._make_ppr("Pending")
        before = frappe.db.count("Error Log")
        with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
            self._guest_get(
                REQ_CMD, payment_request=doc.name, error=MARKER, error_description=MARKER
            )
        link = self._make_ppl()
        with patch(LINK_CLIENT, return_value=_client_reporting("pending")):
            self._guest_get(LINK_CMD, payment_link=link.name, error=MARKER, error_description=MARKER)
        self.assertEqual(frappe.db.count("Error Log"), before)
        self.assertFalse(frappe.db.exists("Error Log", {"error": ["like", f"%{MARKER}%"]}))

    # ---- existence oracle -----------------------------------------------------

    def test_known_and_unknown_request_names_answer_identically(self):
        doc = self._make_ppr("Pending")
        unknown = "PONTO-PAY-NOPE-1815"
        for error in (None, "access_denied", "server_error"):
            with self.subTest(error=error):
                args = {"error": error} if error else {}
                with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
                    known_seen = self._guest_get(REQ_CMD, payment_request=doc.name, **args)
                    unknown_seen = self._guest_get(REQ_CMD, payment_request=unknown, **args)
                self.assertEqual(
                    known_seen["location"].replace(doc.name, "<N>"),
                    unknown_seen["location"].replace(unknown, "<N>"),
                )
                self.assertEqual(known_seen["response_type"], unknown_seen["response_type"])
                self.assertEqual(known_seen["message_log"], unknown_seen["message_log"])

    def test_a_real_status_change_does_not_leak_a_message_to_the_caller(self):
        """refresh_status() msgprints "Status updated to Signed" only for a KNOWN name; the
        guest must not see that. Needs a status that actually changes, so it runs under the
        Administrator fallback (see _unset_webhook_user)."""
        self._unset_webhook_user()
        doc = self._make_ppr("Pending")
        with patch(PAYMENT_CLIENT, return_value=_client_reporting("signed")):
            known_seen = self._guest_get(REQ_CMD, payment_request=doc.name)
            unknown_seen = self._guest_get(REQ_CMD, payment_request="PONTO-PAY-NOPE-1815")
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Signed")
        self.assertEqual(known_seen["message_log"], unknown_seen["message_log"])

    def test_known_and_unknown_request_leave_the_same_error_log_trail(self):
        doc = self._make_ppr("Pending")
        with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
            c0 = frappe.db.count("Error Log")
            self._guest_get(REQ_CMD, payment_request=doc.name, error="server_error")
            c1 = frappe.db.count("Error Log")
            self._guest_get(REQ_CMD, payment_request="PONTO-PAY-NOPE-1815", error="server_error")
            c2 = frappe.db.count("Error Log")
        self.assertEqual(c1 - c0, c2 - c1)

    # ---- the service-user fallback -------------------------------------------

    def test_guest_error_callback_changes_nothing_when_webhook_user_unset(self):
        """get_service_user falls back to Administrator when webhook_user is unset
        (fallback_user default). The harm must not depend on which identity ran."""
        self._unset_webhook_user()
        doc = self._make_ppr("Pending")
        before = self._modified_by("Ponto Payment Request", doc.name)
        with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
            self._guest_get(REQ_CMD, payment_request=doc.name, error="access_denied")
        self.assertEqual(self._modified_by("Ponto Payment Request", doc.name), before)
