"""
Every webhook URL this app hands a payment provider must be reachable by the
provider, which calls without credentials, i.e. as Guest (#1771).

Frappe gates whitelisted methods only at DISPATCH (``frappe.handler.execute_cmd`` ->
``frappe.is_whitelisted``): an internal call never consults ``frappe.guest_methods``,
so a webhookUrl on a non-guest function looks fine in every unit test and is refused
for every real notification. That is exactly how ``get_subscription_webhook_url()``
pointed Mollie at ``payment_gateways.mollie_subscription_webhook`` (whitelisted,
not allow_guest) for every member-dues subscription.
"""

from urllib.parse import urlparse

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _dotted_method(url: str) -> str:
    path = urlparse(url).path
    assert "/api/method/" in path, f"not a method URL: {url}"
    return path.split("/api/method/", 1)[1]


def _inline(method: str) -> str:
    return frappe.utils.get_url(f"/api/method/{method}")


def _provider_urls() -> dict:
    """Every producer of a provider-facing webhook URL, by name.

    Census (grep ``webhookUrl|exchangeUrl|webhook_url|get_.*webhook_url``): Mollie
    Settings (4), MollieClient, PaymentService, the bulk-payment page, Ponto Settings,
    ING Checkout Settings and the ING mandate service (2 types). A new producer is not
    covered until it is added here.
    """
    from verenigingen.templates.pages.mollie_bulk_payment_creation import get_webhook_url as bulk_url
    from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import MandateService
    from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
    from verenigingen.verenigingen_payments.mollie.services.payment_service import PaymentService
    from verenigingen.verenigingen_payments.ponto.services.oauth2_service import PontoOAuth2Service

    mollie = frappe.get_single("Mollie Settings")
    ponto = frappe.new_doc("Ponto Settings")
    ponto.enable_webhooks = 1
    ponto.update_webhook_url()
    ing = frappe.new_doc("ING Checkout Settings")
    ing._generate_webhook_url()
    mandates = MandateService()
    return {
        "Mollie Settings.get_webhook_url": mollie.get_webhook_url(),
        "Mollie Settings.get_test_webhook_url": mollie.get_test_webhook_url(),
        "Mollie Settings.get_live_webhook_url": mollie.get_live_webhook_url(),
        "Mollie Settings.get_subscription_webhook_url": mollie.get_subscription_webhook_url(),
        "MollieClient.get_webhook_url": MollieClient().get_webhook_url(),
        "PaymentService._get_webhook_url": PaymentService()._get_webhook_url(),
        "mollie_bulk_payment_creation.get_webhook_url": bulk_url(),
        "Ponto Settings.webhook_url": ponto.webhook_url,
        "ING Checkout Settings.webhook_url": ing.webhook_url,
        "ING MandateService mandate": mandates._get_webhook_url("mandate"),
        "ING MandateService direct_debit": mandates._get_webhook_url("direct_debit"),
        # Inline producers (the URL is built inside a function, so these two are the
        # literal paths copied from ing_checkout/api/payment.py and
        # ponto/services/oauth2_service.py::_get_redirect_uri; the latter is the OAuth
        # redirect a browser lands on, not a server-to-server webhook).
        "ING payment.py inline webhook_url": _inline(
            "verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment"
        ),
        "Ponto oauth2 redirect": PontoOAuth2Service()._get_redirect_uri(),
    }


class TestProviderWebhookUrlsGuestReachable(EnhancedTestCase):
    def test_every_provider_webhook_url_resolves_to_a_guest_method(self):
        for name, url in _provider_urls().items():
            with self.subTest(producer=name):
                self.assertTrue(url, f"{name} produced no URL")
                dotted = _dotted_method(url)
                # get_attr imports the module, which runs the whitelist decorator,
                # so membership cannot depend on import order.
                method = frappe.get_attr(dotted)
                self.assertIn(method, frappe.whitelisted, f"{dotted} ({name}) is not whitelisted")
                self.assertIn(
                    method,
                    frappe.guest_methods,
                    f"{dotted} ({name}) is not allow_guest: the provider's anonymous call is refused",
                )

    def test_the_membership_check_distinguishes_a_non_guest_function(self):
        """Control: a whitelisted-but-not-guest function is whitelisted and NOT in guest_methods."""

        @frappe.whitelist()
        def _members_only_probe():
            return None

        self.addCleanup(frappe.whitelisted.remove, _members_only_probe)
        self.assertIn(_members_only_probe, frappe.whitelisted)
        self.assertNotIn(_members_only_probe, frappe.guest_methods)


class _GuestDispatchMixin:
    """Posts a Mollie-shaped form body through Frappe's real dispatch gate as Guest."""

    def _post_as_guest(self, dotted: str, payment_id: str):
        from frappe.handler import execute_cmd

        environ = EnvironBuilder(
            method="POST",
            path="/",
            data={"id": payment_id},
            content_type="application/x-www-form-urlencoded",
        ).get_environ()
        old = (getattr(frappe.local, "request", None), frappe.local.form_dict, frappe.session.user)
        self.addCleanup(self._restore_guest_dispatch_state, old)
        frappe.local.request = Request(environ)
        # frappe.app.make_form_dict reads the body first and werkzeug caches it; the
        # webhook authenticators then read it back via get_data(). Mirror that, or the
        # body is reported empty.
        frappe.local.request.get_data(as_text=True)
        # set_user() resets form_dict, so it must come first.
        frappe.set_user("Guest")
        frappe.local.form_dict = frappe._dict(id=payment_id)
        return execute_cmd(dotted)

    @staticmethod
    def _restore_guest_dispatch_state(old):
        frappe.local.request, frappe.local.form_dict = old[0], old[1]
        frappe.set_user(old[2])


class _MollieMustNotBeAsked:
    """A payment that reports no refund or chargeback needs no discovery call."""

    asked = False

    @property
    def payments(self):
        # Recorded as well as raised: discovery swallows exceptions into
        # "check failed", so the raise alone would not fail the delivery under test.
        type(self).asked = True
        raise AssertionError("refund/chargeback discovery ran for a payment that reports none")


class _FakeMollie:
    """The SDK surface the idempotency manager lists reversals from."""

    def __init__(self, refunds=(), chargebacks=(), fail=False):
        self._refunds, self._chargebacks, self._fail = list(refunds), list(chargebacks), fail
        self.payments = self

    def get(self, _payment_id):
        return self

    @property
    def refunds(self):
        return self._lister({"_embedded": {"refunds": self._refunds}})

    @property
    def chargebacks(self):
        return self._lister(self._chargebacks)

    def _lister(self, value):
        from types import SimpleNamespace

        def list_():
            if self._fail:
                raise ConnectionError("mollie down")
            return value

        return SimpleNamespace(list=list_)


class TestSubscriptionWebhookDispatch(_GuestDispatchMixin, EnhancedTestCase):
    """Behavioural: an anonymous Mollie-shaped POST must get past dispatch."""

    def test_anonymous_post_to_the_subscription_webhook_url_is_not_refused_at_dispatch(self):
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.utils import webhook_security

        # The unknown payment id / unconfigured test site makes the handler log its own
        # refusal; that is the handler answering, which is what is being proven.
        self.expectErrorLog("Mollie", "Webhook Processing Error", "Security")
        url = frappe.get_single("Mollie Settings").get_subscription_webhook_url()
        payment_id = f"tr_{frappe.generate_hash(length=10)}"

        # wraps= calls through: the spy only records that the handler Mollie reaches
        # authenticates the way the payment webhook does (it sets the webhook user).
        # Merely adding allow_guest to payment_gateways.mollie_subscription_webhook
        # would pass the dispatch gate but answer {"status": "ignored", "reason": "No
        # subscription ID in payload"} to a real ``id=tr_...`` body without ever
        # reaching this function, so being "not refused" alone is not enough.
        with patch.object(
            webhook_security, "authenticate_mollie_webhook", wraps=webhook_security.authenticate_mollie_webhook
        ) as authenticated:
            # The payment does not exist at Mollie (or there are no credentials): the
            # handler may answer with an error dict / 5xx, but it must be REACHED.
            # frappe.PermissionError is the dispatch refusal this test exists to catch.
            try:
                result = self._post_as_guest(_dotted_method(url), payment_id)
            except frappe.PermissionError as e:
                self.fail(f"Mollie's anonymous POST is refused at dispatch ({url}): {e}")

        authenticated.assert_called_once()
        self.assertIsInstance(result, dict)
        self.assertNotEqual(result.get("status"), "ignored", result)


class TestSubscriptionWebhookBooksTheDuesPayment(_GuestDispatchMixin, EnhancedTestCase):
    """The anonymous notification must actually BOOK the payment, not merely get past
    dispatch: a guest method that authenticates, swallows everything and answers ``ok``
    passes the dispatch test above and books nothing (reviewer's mutant on #1779).

    Only the Mollie fetch (``PaymentTypeRouter.fetch_payment``) is stubbed. Everything
    after it is real: classification by ``Member.mollie_subscription_id``,
    ``DuesPaymentProcessor`` and the Bank Transaction it writes.

    A SECOND delivery of the same ``tr_`` id is asserted too (#1780): Mollie re-posts the
    id on retries AND on a refund or chargeback of that payment, and the two must be told
    apart -- a retry changes nothing, a reversal reaches ``process_reversal_webhook``.
    """

    def setUp(self):
        super().setUp()
        from verenigingen.tests.fixtures.mollie_account_fixtures import (
            ensure_bank_account_record,
            provisioned_mollie_settings,
        )

        self.company = "_Test Company"
        ctx = provisioned_mollie_settings(company=self.company)
        accounts = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.clearing_account = accounts["clearing_account"]
        self.currency = frappe.get_value("Company", self.company, "default_currency")
        # The Bank Transaction is booked against the Bank Account of the clearing GL.
        ensure_bank_account_record(self.company, accounts["clearing_account"])

        self.member = self.create_test_member(
            first_name="SubHook",
            last_name="Member",
            email=f"subhook.{frappe.generate_hash(length=6)}@example.com",
        )
        self.member.reload()
        self.customer = self.member.customer
        self.assertTrue(self.customer)
        self.subscription_id = f"sub_{frappe.generate_hash(length=8)}"
        self.mollie_customer_id = f"cst_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member",
            self.member.name,
            {"mollie_subscription_id": self.subscription_id, "mollie_customer_id": self.mollie_customer_id},
            update_modified=False,
        )
        self.invoice_name, self.invoice_total = self._unpaid_dues_invoice()
        # Resolved before any delivery: a Guest dispatch leaves the request context on
        # a host the URL builder refuses, so a later call would raise.
        self.webhook_url = frappe.get_single("Mollie Settings").get_subscription_webhook_url()

    def _unpaid_dues_invoice(self):
        income = frappe.get_value("Company", self.company, "default_income_account")
        item_code = f"Sub Hook Dues {frappe.generate_hash(length=5)}"
        item = frappe.new_doc("Item")
        item.item_code = item.item_name = item_code
        item.item_group = (
            "Services"
            if frappe.db.exists("Item Group", "Services")
            else frappe.get_value("Item Group", {"is_group": 0}, "name")
        )
        item.stock_uom = "Unit" if frappe.db.exists("UOM", "Unit") else frappe.get_value("UOM", {}, "name")
        item.is_stock_item = 0
        item.insert()

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.customer
        invoice.company = self.company
        invoice.currency = frappe.get_value("Company", self.company, "default_currency")
        invoice.member = self.member.name
        invoice.is_membership_invoice = 1
        invoice.append("items", {"item_code": item_code, "qty": 1, "rate": 25, "income_account": income})
        invoice.insert()
        invoice.submit()
        return invoice.name, invoice.grand_total

    def test_anonymous_subscription_notification_books_a_bank_transaction_for_the_member(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.services.payment_type_router import (
            PaymentTypeRouter,
        )

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        # The paid amount deliberately differs from the invoice total, so a deposit
        # taken from the invoice (or a constant) cannot pass for one taken from Mollie.
        paid_amount = round(float(self.invoice_total) + 1.37, 2)
        payment = SimpleNamespace(
            id=payment_id,
            status="paid",
            # The company's own currency: the Bank Account's currency must match.
            amount={
                "value": f"{paid_amount:.2f}",
                "currency": frappe.get_value("Company", self.company, "default_currency"),
            },
            description="",
            subscription_id=self.subscription_id,
            customer_id=self.mollie_customer_id,
            paid_at="2025-04-10T09:00:00+00:00",
        )
        url = frappe.get_single("Mollie Settings").get_subscription_webhook_url()

        # allow_mollie_test_mode: the site's test_mode safety check refuses to authenticate
        # a test-mode webhook on a non-development site, before any booking.
        with patch.object(PaymentTypeRouter, "fetch_payment", return_value=payment), patch.dict(
            frappe.conf, {"allow_mollie_test_mode": 1}
        ):
            result = self._post_as_guest(_dotted_method(url), payment_id)

        rows = frappe.get_all(
            "Bank Transaction",
            filters={"reference_number": payment_id},
            fields=["name", "deposit", "party_type", "party", "custom_member"],
        )
        self.assertEqual(len(rows), 1, f"expected one Bank Transaction for {payment_id}; result: {result}")
        self.assertEqual(float(rows[0].deposit), paid_amount)
        self.assertEqual(rows[0].party_type, "Customer")
        self.assertEqual(rows[0].party, self.customer)
        self.assertEqual(rows[0].custom_member, self.member.name)

    # ---- #1780 / #370: one tr_ id, delivered more than once -----------------------

    def _paid_dues_payment(self, payment_id, paid_amount, **extra):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=payment_id,
            status="paid",
            amount={
                "value": f"{paid_amount:.2f}",
                "currency": frappe.get_value("Company", self.company, "default_currency"),
            },
            description="",
            subscription_id=self.subscription_id,
            customer_id=self.mollie_customer_id,
            paid_at="2025-04-10T09:00:00+00:00",
            **extra,
        )

    def _post_mollie_notification(self, payment, mollie_client=None):
        """One anonymous Mollie notification. Only Mollie's HTTP boundary is stubbed:
        ``fetch_payment`` and, where a test needs refund/chargeback discovery, the SDK
        client the idempotency manager lists them from."""
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
        from verenigingen.verenigingen_payments.mollie.services.payment_type_router import (
            PaymentTypeRouter,
        )

        url = self.webhook_url
        client = mollie_client or _MollieMustNotBeAsked()
        _MollieMustNotBeAsked.asked = False
        frappe.local.response.pop("http_status_code", None)
        with patch.object(PaymentTypeRouter, "fetch_payment", return_value=payment), patch.object(
            MollieClient, "_get_mollie_client", return_value=client
        ), patch.dict(frappe.conf, {"allow_mollie_test_mode": 1}):
            result = self._post_as_guest(_dotted_method(url), payment.id)
        if mollie_client is None:
            self.assertFalse(_MollieMustNotBeAsked.asked, "an ordinary delivery listed refunds at Mollie")
        return result

    def _state_of(self, payment_id):
        """Everything a retry could move, keyed on the payment."""
        bts = frappe.get_all(
            "Bank Transaction",
            filters={"reference_number": payment_id},
            fields=["name", "docstatus", "status", "deposit", "allocated_amount", "unallocated_amount"],
        )
        return {
            "bank_transactions": [dict(r) for r in bts],
            "bt_links": frappe.db.count(
                "Bank Transaction Payments", {"parent": ["in", [b.name for b in bts] or [""]]}
            ),
            "payment_entries": sorted(
                frappe.get_all(
                    "Payment Entry",
                    filters={"party": self.customer, "docstatus": ["!=", 2]},
                    pluck="name",
                )
            ),
            "journal_entries": sorted(
                frappe.get_all(
                    "Journal Entry",
                    filters={"cheque_no": ["like", f"{payment_id}%"], "docstatus": ["!=", 2]},
                    pluck="name",
                )
            ),
            "outstanding": float(frappe.db.get_value("Sales Invoice", self.invoice_name, "outstanding_amount")),
        }

    def test_a_second_identical_delivery_leaves_state_unchanged(self):
        """#1780. Probe shortcut: none -- both deliveries are the real Guest dispatch."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))

        first = self._post_mollie_notification(payment)
        after_first = self._state_of(payment_id)
        self.assertEqual(len(after_first["bank_transactions"]), 1, f"fixture: no BT booked: {first}")
        self.assertEqual(after_first["payment_entries"], [], "fixture: BT mode books no Payment Entry")

        second = self._post_mollie_notification(payment)

        self.assertEqual(self._state_of(payment_id), after_first, f"a retry changed state: {second}")
        self.assertEqual(after_first["bank_transactions"][0]["status"], "Unreconciled")

    def test_a_retry_resubmits_a_bank_transaction_left_in_draft_instead_of_booking_a_payment_entry(self):
        """The retry that IS owed work: the first delivery left a BT that never submitted.

        Probe shortcut: the draft is produced by making the SUBMIT step of
        ``secure_document_operation`` report failure (the permission boundary a webhook
        user without ``Bank Transaction:submit`` hits), not by editing docstatus.
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        from verenigingen.utils import secure_operations

        real = secure_operations.secure_document_operation

        def refuse_submit(*args, **kwargs):
            if kwargs.get("operation") == "submit":
                return SimpleNamespace(
                    success=False, errors=["no submit permission"], partial_write=False, document=None
                )
            return real(*args, **kwargs)

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        with patch.object(secure_operations, "secure_document_operation", side_effect=refuse_submit):
            self._post_mollie_notification(payment)
        rows = frappe.get_all("Bank Transaction", filters={"reference_number": payment_id}, fields=["docstatus"])
        self.assertEqual([r.docstatus for r in rows], [0], "fixture: the first delivery must leave a draft")

        self._post_mollie_notification(payment)

        after = self._state_of(payment_id)
        self.assertEqual([b["docstatus"] for b in after["bank_transactions"]], [1], "draft BT not resubmitted")
        self.assertEqual(after["payment_entries"], [], "the retry posted a Payment Entry")

    def test_a_delivery_that_raced_past_the_existence_check_still_books_nothing_new(self):
        """Concurrent double delivery. Two deliveries that BOTH read "no BT yet" book one
        row, because ``Bank Transaction`` carries a per-account unique key on the
        reference (#1267) and the loser recovers the winner's row.

        Probe shortcut: the interleaving is simulated by making the second delivery's
        existence check answer "not processed", not by running two connections.
        """
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            BankTransactionCreator,
        )

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        self._post_mollie_notification(payment)
        after_first = self._state_of(payment_id)

        blank = {"already_processed": False, "bank_transaction": None, "payment_entry": None}
        with patch.object(BankTransactionCreator, "check_already_processed", return_value=blank):
            self._post_mollie_notification(payment)

        self.assertEqual(self._state_of(payment_id), after_first)

    def _forward_dues_payment_entry(self, payment_id):
        """The forward artefact the reversal booking needs: a submitted Payment Entry
        carrying the Mollie id, allocated to the invoice -- what reconciling the dues BT
        produces, and what the older Payment Entry mode wrote."""
        from decimal import Decimal

        from frappe.utils import getdate

        from verenigingen.verenigingen_payments.services.payment import payment_entry_service

        self.ensure_mode_of_payment("Mollie", "Bank")
        pe = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=self.invoice_name,
            amount=Decimal(str(self.invoice_total)),
            posting_date=getdate(),
            reference_no=payment_id,
            reference_date=getdate(),
            mode_of_payment="Mollie",
            bank_account=self.clearing_account,
        )
        self.track_test_record("Payment Entry", pe.name)
        return pe.name

    def _refund_of(self, amount):
        return {
            "id": f"re_{frappe.generate_hash(length=8)}",
            "amount": {"value": f"{amount:.2f}", "currency": self.currency},
            "createdAt": "2025-04-11T09:00:00+00:00",
        }

    @staticmethod
    def _http_status():
        """The status Mollie sees. The body is not read: #1781 reduces it to ok|error."""
        return int(frappe.local.response.get("http_status_code") or 200)

    def _invoice_outstanding(self):
        return float(frappe.db.get_value("Sales Invoice", self.invoice_name, "outstanding_amount"))

    def test_a_redelivery_carrying_a_refund_reaches_the_reversal_booking_once(self):
        """#370 slice. The forward payment is reconciled (a Payment Entry exists); Mollie
        re-posts the id because the payment was partly refunded."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        forward = self._forward_dues_payment_entry(payment_id)
        self.assertEqual(self._invoice_outstanding(), 0.0, "fixture: the invoice should start settled")
        # Derived from the fixture, not hard-coded: a fraction of what was paid.
        refund = self._refund_of(round(float(self.invoice_total) / 5, 2))
        refunded = float(refund["amount"]["value"])
        payment = self._paid_dues_payment(
            payment_id,
            float(self.invoice_total),
            amountRefunded={"value": f"{refunded:.2f}", "currency": self.currency},
        )
        client = _FakeMollie(refunds=[refund])

        first = self._post_mollie_notification(payment, client)
        self.assertLess(self._http_status(), 400, first)

        key = f"{payment_id}_refund_{refund['id']}"
        jes = frappe.get_all("Journal Entry", filters={"cheque_no": key, "docstatus": 1}, pluck="name")
        self.assertEqual(len(jes), 1, f"the refund must book exactly one Journal Entry: {first}")
        self.assertEqual(self._invoice_outstanding(), refunded)
        before = self._state_of(payment_id)

        again = self._post_mollie_notification(payment, client)

        self.assertLess(self._http_status(), 400, again)
        self.assertEqual(self._state_of(payment_id), before, "a re-delivery of a booked refund moved state")
        self.assertEqual(self._invoice_outstanding(), refunded, "the refund was restored twice")
        self.assertIn(forward, before["payment_entries"])

    def test_a_redelivery_carrying_a_chargeback_reaches_the_reversal_booking(self):
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self._forward_dues_payment_entry(payment_id)
        amount = round(float(self.invoice_total) / 5, 2)
        chargeback = {
            "id": f"chb_{frappe.generate_hash(length=8)}",
            "amount": {"value": f"{amount:.2f}", "currency": self.currency},
            "reason": {"code": "AM04", "description": "Insufficient funds"},
        }
        payment = self._paid_dues_payment(
            payment_id,
            float(self.invoice_total),
            amountChargedBack={"value": f"{amount:.2f}", "currency": self.currency},
        )

        result = self._post_mollie_notification(payment, _FakeMollie(chargebacks=[chargeback]))

        self.assertLess(self._http_status(), 400, result)
        key = f"{payment_id}_chargeback_{chargeback['id']}"
        self.assertEqual(
            len(frappe.get_all("Journal Entry", filters={"cheque_no": key, "docstatus": 1})), 1, result
        )
        self.assertEqual(self._invoice_outstanding(), amount)

    def test_a_refund_of_an_unreconciled_bank_transaction_is_not_swallowed_and_posts_nothing(self):
        """BT-only forward booking: there is no Payment Entry for the reversal to mirror.
        The delivery must say so (non-success, so Mollie retries until the treasurer has
        reconciled) -- never answer 200 and lose the refund, and never post a stand-in."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        self._post_mollie_notification(payment)
        before = self._state_of(payment_id)
        refund = self._refund_of(1.0)
        refunded_payment = self._paid_dues_payment(
            payment_id,
            float(self.invoice_total),
            amountRefunded={"value": "1.00", "currency": self.currency},
        )

        result = self._post_mollie_notification(refunded_payment, _FakeMollie(refunds=[refund]))

        self.assertEqual(self._http_status(), 500, result)
        self.assertEqual(self._state_of(payment_id), before)

    def test_an_unavailable_mollie_defers_refund_discovery_rather_than_dropping_it(self):
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self._forward_dues_payment_entry(payment_id)
        payment = self._paid_dues_payment(
            payment_id,
            float(self.invoice_total),
            amountRefunded={"value": "1.00", "currency": self.currency},
        )

        result = self._post_mollie_notification(payment, _FakeMollie(fail=True))

        self.assertEqual(self._http_status(), 503, result)

    def test_a_payment_reporting_zero_refunded_is_not_listed_at_mollie(self):
        """Control for the discovery gate: Mollie may send ``amountRefunded`` as 0.00
        (a truthy dict / string), which is not a refund."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        zero = {"value": "0.00", "currency": self.currency}
        payment = self._paid_dues_payment(
            payment_id, float(self.invoice_total), amountRefunded=zero, amountChargedBack=zero
        )

        self._post_mollie_notification(payment)  # asserts Mollie was not asked

        self.assertLess(self._http_status(), 400)
        self.assertEqual(len(self._state_of(payment_id)["bank_transactions"]), 1)
