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
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_callback_guest_status
"""

import itertools
from unittest.mock import MagicMock, patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
from verenigingen.utils.security.guest_return_tokens import (
    generate_guest_return_token,
    verify_guest_return_token,
)
from verenigingen.verenigingen_payments.ponto.api import betaalverzoek_callback, payment_callback

REQ_CMD = "verenigingen.verenigingen_payments.ponto.api.payment_callback.payment_callback"
LINK_CMD = "verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_link_callback"
PAYMENT_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
LINK_CLIENT = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)
MARKER = "ATTACKER-CHOSEN-1815"
UNKNOWN_LINK = "PONTO-LINK-NOPE-1815"
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
        self._configure_webhook_user()
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
                "session_user": frappe.session.user,
                "response_type": frappe.local.response.get("type"),
                "location": frappe.local.response.get("location"),
                "message_log": list(frappe.local.message_log or []),
            }
            frappe.set_user(original_user)
        return seen

    def _configure_webhook_user(self):
        frappe.db.set_value("User", self.webhook_user, "enabled", 1)
        frappe.db.set_single_value("Verenigingen Payments Settings", "webhook_user", self.webhook_user)
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")

    def _unset_webhook_user(self):
        """No usable webhook_user. #1834: the guest callbacks must not fall back to
        Administrator, so nothing here may expect (or tolerate) an Error Log row."""
        self._configure_webhook_user()
        frappe.db.set_single_value("Verenigingen Payments Settings", "webhook_user", None)
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")

    def _disable_webhook_user(self):
        """A configured but DISABLED webhook_user: get_service_user would also fall back."""
        self._configure_webhook_user()
        frappe.db.set_value("User", self.webhook_user, "enabled", 0)

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

    # ---- #1834: the guest callbacks do not call Ponto and adopt nothing ---------------

    def _each_identity(self):
        """The three identities a callback can end up with: the configured minimal webhook
        user, no webhook_user, and a disabled one. Administrator is never among them."""
        return {
            "webhook_user": self._configure_webhook_user,
            "unset": self._unset_webhook_user,
            "disabled": self._disable_webhook_user,
        }

    def test_callbacks_never_call_ponto_and_adopt_nothing_it_reports(self):
        """Ponto says signed/authorized; the callback must neither ask nor adopt. Replaces
        test_error_callback_still_adopts_what_ponto_reports, which pinned the #1815 refresh
        under the Administrator fallback. Control: fails if refresh_status (or any Ponto
        client call) comes back, or if the Administrator fallback makes it authorised."""
        for label, prepare in self._each_identity().items():
            with self.subTest(identity=label):
                prepare()
                doc = self._make_ppr("Pending")
                link = self._make_ppl("Pending Authorization")
                req_client, link_client = _client_reporting("signed"), _client_reporting("authorized")
                with patch(PAYMENT_CLIENT, return_value=req_client) as req_factory, patch(
                    LINK_CLIENT, return_value=link_client
                ) as link_factory:
                    self._guest_get(REQ_CMD, payment_request=doc.name, error="access_denied")
                    self._guest_get(LINK_CMD, payment_link=link.name, error="access_denied")
                    self._guest_get(REQ_CMD, payment_request=doc.name)
                    self._guest_get(LINK_CMD, payment_link=link.name)
                self.assertEqual(req_factory.call_count, 0, "payment_callback reached for the Ponto client")
                self.assertEqual(link_factory.call_count, 0, "payment_link_callback reached for the Ponto client")
                self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Pending")
                self.assertEqual(
                    frappe.db.get_value("Ponto Payment Link", link.name, "status"), "Pending Authorization"
                )

    def test_callbacks_do_not_call_refresh_status(self):
        """Second channel for the same control: refresh_status itself is never invoked."""
        doc = self._make_ppr("Pending")
        link = self._make_ppl("Pending Authorization")
        with patch(
            "verenigingen.verenigingen_payments.doctype.ponto_payment_request."
            "ponto_payment_request.PontoPaymentRequest.refresh_status"
        ) as req_refresh, patch(
            "verenigingen.verenigingen_payments.doctype.ponto_payment_link."
            "ponto_payment_link.PontoPaymentLink.refresh_status"
        ) as link_refresh:
            self._guest_get(REQ_CMD, payment_request=doc.name)
            self._guest_get(LINK_CMD, payment_link=link.name)
        self.assertEqual(req_refresh.call_count, 0)
        self.assertEqual(link_refresh.call_count, 0)

    def test_the_dead_refresh_helpers_are_gone(self):
        self.assertFalse(hasattr(payment_callback, "_refresh_from_ponto"))
        self.assertFalse(hasattr(betaalverzoek_callback, "_refresh_link_from_ponto"))

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

    def test_known_and_unknown_request_leak_no_message_for_any_identity(self):
        """Replaces the #1815 test that needed a real refresh-driven status change (and the
        Administrator fallback to get one). With no refresh there is no change and no message;
        message_log must still match an unknown name under every identity."""
        for label, prepare in self._each_identity().items():
            with self.subTest(identity=label):
                prepare()
                doc = self._make_ppr("Pending")
                with patch(PAYMENT_CLIENT, return_value=_client_reporting("signed")):
                    known_seen = self._guest_get(REQ_CMD, payment_request=doc.name)
                    unknown_seen = self._guest_get(REQ_CMD, payment_request="PONTO-PAY-NOPE-1815")
                self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Pending")
                self.assertEqual(known_seen["message_log"], unknown_seen["message_log"])
                self.assertEqual(known_seen["response_type"], unknown_seen["response_type"])

    def test_known_and_unknown_request_leave_the_same_error_log_trail(self):
        doc = self._make_ppr("Pending")
        with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
            c0 = frappe.db.count("Error Log")
            self._guest_get(REQ_CMD, payment_request=doc.name, error="server_error")
            c1 = frappe.db.count("Error Log")
            self._guest_get(REQ_CMD, payment_request="PONTO-PAY-NOPE-1815", error="server_error")
            c2 = frappe.db.count("Error Log")
        self.assertEqual(c1 - c0, c2 - c1)

    # ---- #1834: the service-user fallback is gone ------------------------------------

    def test_no_webhook_user_means_no_write_no_error_log_and_no_elevation(self):
        """With webhook_user unset (or disabled) the callbacks change nothing: no status
        write, no Error Log row (get_service_user used to write a constant 'Using
        Administrator Fallback' row per anonymous GET), and the request never runs as
        anything but Guest. Replaces test_guest_error_callback_changes_nothing_when_
        webhook_user_unset, which expected that Error Log row."""
        for label in ("unset", "disabled"):
            with self.subTest(identity=label):
                self._each_identity()[label]()
                doc = self._make_ppr("Pending")
                link = self._make_ppl("Pending Authorization")
                req_before = self._modified_by("Ponto Payment Request", doc.name)
                link_before = self._modified_by("Ponto Payment Link", link.name)
                errors_before = frappe.db.count("Error Log")
                seen = [
                    self._guest_get(REQ_CMD, payment_request=doc.name, error="access_denied"),
                    self._guest_get(LINK_CMD, payment_link=link.name, error="access_denied"),
                ]
                self.assertEqual(frappe.db.count("Error Log"), errors_before)
                self.assertEqual(self._modified_by("Ponto Payment Request", doc.name), req_before)
                self.assertEqual(self._modified_by("Ponto Payment Link", link.name), link_before)
                for one in seen:
                    self.assertEqual(one["session_user"], "Guest")

    def test_a_configured_webhook_user_is_the_identity_the_callback_runs_as(self):
        """Control for the test above: with a real webhook_user the identity IS switched, so
        the 'stays Guest' assertion there can fail."""
        doc = self._make_ppr("Pending")
        seen = self._guest_get(REQ_CMD, payment_request=doc.name)
        self.assertEqual(seen["session_user"], self.webhook_user)

    def test_known_name_answers_the_same_whether_or_not_webhook_user_is_configured(self):
        """No guest-visible difference between a configured and an unconfigured site."""
        doc = self._make_ppr("Pending")
        link = self._make_ppl("Pending Authorization")
        answers = {}
        for label in ("webhook_user", "unset"):
            self._each_identity()[label]()
            answers[label] = [
                self._guest_get(REQ_CMD, payment_request=doc.name, error="access_denied"),
                self._guest_get(LINK_CMD, payment_link=link.name, error="access_denied"),
            ]
        for configured, unset in zip(answers["webhook_user"], answers["unset"]):
            for channel in ("response_type", "location", "message_log"):
                self.assertEqual(configured[channel], unset[channel], channel)

    # ---- ruled exception: a token-proved access_denied cancels a pre-signing row ------

    def _req_token(self, doc, purpose=None):
        return generate_guest_return_token(purpose or payment_callback.CANCEL_TOKEN_PURPOSE, doc.name)

    def _link_token(self, doc, purpose=None):
        return generate_guest_return_token(purpose or betaalverzoek_callback.CANCEL_TOKEN_PURPOSE, doc.name)

    def test_valid_token_access_denied_cancels_a_pending_request_as_the_webhook_user(self):
        doc = self._make_ppr("Pending")
        with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
            seen = self._guest_get(
                REQ_CMD, payment_request=doc.name, error="access_denied", cancel_token=self._req_token(doc)
            )
        row = self._modified_by("Ponto Payment Request", doc.name)
        self.assertEqual(row.status, "Cancelled")
        self.assertEqual(row.modified_by, self.webhook_user)
        self.assertEqual(seen["session_user"], self.webhook_user)

    def test_valid_token_access_denied_cancels_a_pending_link_as_the_webhook_user(self):
        doc = self._make_ppl("Pending Authorization")
        with patch(LINK_CLIENT, return_value=_client_reporting("pending")):
            self._guest_get(
                LINK_CMD, payment_link=doc.name, error="access_denied", cancel_token=self._link_token(doc)
            )
        row = self._modified_by("Ponto Payment Link", doc.name)
        self.assertEqual(row.status, "Cancelled")
        self.assertEqual(row.modified_by, self.webhook_user)

    def test_valid_token_cancel_fails_closed_without_a_webhook_user(self):
        """#1834 + #1815: the token-proved cancel needs the minimal webhook user. Unset or
        disabled, it writes nothing, adds no Error Log row, and answers exactly like a
        callback that carried no token. Fails if the Administrator fallback returns (the
        cancel would then succeed)."""
        for label in ("unset", "disabled"):
            with self.subTest(identity=label):
                self._each_identity()[label]()
                doc = self._make_ppr("Pending")
                link = self._make_ppl("Pending Authorization")
                errors_before = frappe.db.count("Error Log")
                proved = [
                    self._guest_get(
                        REQ_CMD, payment_request=doc.name, error="access_denied",
                        cancel_token=self._req_token(doc),
                    ),
                    self._guest_get(
                        LINK_CMD, payment_link=link.name, error="access_denied",
                        cancel_token=self._link_token(link),
                    ),
                ]
                bare = [
                    self._guest_get(REQ_CMD, payment_request=doc.name, error="access_denied"),
                    self._guest_get(LINK_CMD, payment_link=link.name, error="access_denied"),
                ]
                self.assertEqual(frappe.db.count("Error Log"), errors_before)
                self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Pending")
                self.assertEqual(
                    frappe.db.get_value("Ponto Payment Link", link.name, "status"), "Pending Authorization"
                )
                for p, b in zip(proved, bare):
                    for channel in ("response_type", "location", "message_log", "session_user"):
                        self.assertEqual(p[channel], b[channel], channel)

    def test_valid_token_cannot_cancel_past_the_pre_signing_state(self):
        """Control rows are REAL rows in each later state; Ponto reports the same state."""
        for initial, ponto in (("Signed", "signed"), ("Executed", "executed")):
            with self.subTest(kind="request", initial=initial):
                doc = self._make_ppr(initial)
                before = self._modified_by("Ponto Payment Request", doc.name)
                with patch(PAYMENT_CLIENT, return_value=_client_reporting(ponto)):
                    self._guest_get(
                        REQ_CMD, payment_request=doc.name, error="access_denied",
                        cancel_token=self._req_token(doc),
                    )
                self.assertEqual(self._modified_by("Ponto Payment Request", doc.name), before)
        for initial, ponto in (("Authorized", "authorized"), ("Executed", "executed")):
            with self.subTest(kind="link", initial=initial):
                doc = self._make_ppl(initial)
                before = self._modified_by("Ponto Payment Link", doc.name)
                with patch(LINK_CLIENT, return_value=_client_reporting(ponto)):
                    self._guest_get(
                        LINK_CMD, payment_link=doc.name, error="access_denied",
                        cancel_token=self._link_token(doc),
                    )
                self.assertEqual(self._modified_by("Ponto Payment Link", doc.name), before)

    def test_valid_token_with_any_other_error_writes_nothing(self):
        doc = self._make_ppr("Pending")
        link = self._make_ppl("Pending Authorization")
        for error in ("server_error", "temporarily_unavailable", MARKER, ""):
            with self.subTest(error=error):
                with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
                    self._guest_get(
                        REQ_CMD, payment_request=doc.name, error=error, cancel_token=self._req_token(doc)
                    )
                with patch(LINK_CLIENT, return_value=_client_reporting("pending")):
                    self._guest_get(
                        LINK_CMD, payment_link=link.name, error=error, cancel_token=self._link_token(link)
                    )
                self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Pending")
                self.assertEqual(
                    frappe.db.get_value("Ponto Payment Link", link.name, "status"), "Pending Authorization"
                )

    def test_a_token_for_another_name_or_purpose_does_not_cancel(self):
        doc, other = self._make_ppr("Pending"), self._make_ppr("Pending")
        link, other_link = self._make_ppl("Pending Authorization"), self._make_ppl("Pending Authorization")
        from verenigingen.templates.pages.payment_success import PONTO_RETURN_TOKEN_PURPOSE

        bad_req_tokens = {
            "other_name": self._req_token(other),
            "link_cancel_purpose": self._req_token(doc, betaalverzoek_callback.CANCEL_TOKEN_PURPOSE),
            "payment_success_purpose": self._req_token(doc, PONTO_RETURN_TOKEN_PURPOSE),
            "garbage": "not-a-token",
            "non_ascii": "h\u00e9llo",
        }
        bad_link_tokens = {
            "other_name": self._link_token(other_link),
            "request_cancel_purpose": self._link_token(link, payment_callback.CANCEL_TOKEN_PURPOSE),
            # the #1055 payment-success proof, which payment_link_callback itself hands to any guest
            "payment_success_purpose": self._link_token(link, PONTO_RETURN_TOKEN_PURPOSE),
            "garbage": "not-a-token",
        }
        for label, token in bad_req_tokens.items():
            with self.subTest(kind="request", token=label):
                with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
                    self._guest_get(
                        REQ_CMD, payment_request=doc.name, error="access_denied", cancel_token=token
                    )
                self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Pending")
        for label, token in bad_link_tokens.items():
            with self.subTest(kind="link", token=label):
                with patch(LINK_CLIENT, return_value=_client_reporting("pending")):
                    self._guest_get(
                        LINK_CMD, payment_link=link.name, error="access_denied", cancel_token=token
                    )
                self.assertEqual(
                    frappe.db.get_value("Ponto Payment Link", link.name, "status"), "Pending Authorization"
                )

    def test_cancel_tokens_do_not_verify_as_payment_success_tokens(self):
        """The reverse direction: a cancel token must not unlock the #1055 disclosure page."""
        from verenigingen.templates.pages.payment_success import PONTO_RETURN_TOKEN_PURPOSE

        link = self._make_ppl("Pending Authorization")
        self.assertFalse(verify_guest_return_token(PONTO_RETURN_TOKEN_PURPOSE, link.name, self._link_token(link)))
        self.assertTrue(
            verify_guest_return_token(
                betaalverzoek_callback.CANCEL_TOKEN_PURPOSE, link.name, self._link_token(link)
            )
        )

    def test_bad_token_on_a_known_name_answers_like_an_unknown_name(self):
        """Missing / wrong-name / wrong-purpose token: redirect, message_log and Error Log
        rows identical to an unknown name. Query count NOT compared (the known name reads
        the row, the unknown one does not, by construction)."""
        from verenigingen.templates.pages.payment_success import PONTO_RETURN_TOKEN_PURPOSE

        doc, other = self._make_ppr("Pending"), self._make_ppr("Pending")
        tokens = {
            "missing": None,
            "other_name": self._req_token(other),
            "wrong_purpose": self._req_token(doc, PONTO_RETURN_TOKEN_PURPOSE),
        }
        unknown = "PONTO-PAY-NOPE-1815"
        for label, token in tokens.items():
            with self.subTest(token=label):
                args = {"error": "access_denied"}
                if token:
                    args["cancel_token"] = token
                with patch(PAYMENT_CLIENT, return_value=_client_reporting("pending")):
                    c0 = frappe.db.count("Error Log")
                    known_seen = self._guest_get(REQ_CMD, payment_request=doc.name, **args)
                    c1 = frappe.db.count("Error Log")
                    unknown_seen = self._guest_get(REQ_CMD, payment_request=unknown, **args)
                    c2 = frappe.db.count("Error Log")
                self.assertEqual(
                    known_seen["location"].replace(doc.name, "<N>"),
                    unknown_seen["location"].replace(unknown, "<N>"),
                )
                self.assertEqual(known_seen["message_log"], unknown_seen["message_log"])
                self.assertEqual(c1 - c0, c2 - c1)
                self.assertEqual(frappe.db.get_value("Ponto Payment Request", doc.name, "status"), "Pending")

    def test_link_known_and_unknown_leak_no_message_for_any_identity(self):
        """Link twin of the request test (replaces the refresh-driven message-leak test)."""
        for label, prepare in self._each_identity().items():
            with self.subTest(identity=label):
                prepare()
                doc = self._make_ppl("Pending Authorization")
                with patch(LINK_CLIENT, return_value=_client_reporting("authorized")):
                    known_seen = self._guest_get(LINK_CMD, payment_link=doc.name)
                    unknown_seen = self._guest_get(LINK_CMD, payment_link=UNKNOWN_LINK)
                self.assertEqual(
                    frappe.db.get_value("Ponto Payment Link", doc.name, "status"), "Pending Authorization"
                )
                self.assertEqual(known_seen["message_log"], unknown_seen["message_log"])

    # ---- signing start embeds the token ----------------------------------------------

    def test_signing_start_embeds_a_verifying_cancel_token(self):
        from urllib.parse import parse_qs, urlparse

        doc = self._make_ppr("Draft")
        doc.ponto_payment_id = None
        client = MagicMock()
        client.create_payment.return_value = MagicMock(id="pid-1815", redirect_link="https://ponto/sign")
        with patch(PAYMENT_CLIENT, return_value=client):
            doc.create_ponto_payment()
        sent = client.create_payment.call_args.kwargs["redirect_uri"]
        query = parse_qs(urlparse(sent).query)
        self.assertEqual(query["payment_request"], [doc.name])
        self.assertTrue(
            verify_guest_return_token(payment_callback.CANCEL_TOKEN_PURPOSE, doc.name, query["cancel_token"][0])
        )

        link = self._make_ppl("Draft")
        link_client = MagicMock()
        link_client.create_payment_request.return_value = MagicMock(id="rid-1815", redirect_link="https://p/s")
        with patch(LINK_CLIENT, return_value=link_client):
            link.create_ponto_payment_request()
        sent = link_client.create_payment_request.call_args.kwargs["redirect_uri"]
        query = parse_qs(urlparse(sent).query)
        self.assertEqual(query["payment_link"], [link.name])
        self.assertTrue(
            verify_guest_return_token(
                betaalverzoek_callback.CANCEL_TOKEN_PURPOSE, link.name, query["cancel_token"][0]
            )
        )
