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

import itertools
from urllib.parse import urlparse

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.webhook_rate_limiter import reset_rate_limiter


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


_REMOTE_ADDRS = itertools.count()


class _GuestDispatchMixin:
    """Posts a Mollie-shaped form body through Frappe's real dispatch gate as Guest."""

    def setUp(self):
        super().setUp()
        # The webhook limiter is a per-PROCESS singleton keyed on client IP. Requests get a
        # unique REMOTE_ADDR (see _unique_remote_addr), which removes the shared "unknown"
        # bucket; the reset is defence in depth, so one class's posts cannot throttle the
        # next class in the shard (429 ``rate_limited``, nothing booked) and a fresh limiter
        # is left behind for whichever module runs next.
        reset_rate_limiter()
        self.addCleanup(reset_rate_limiter)

    @staticmethod
    def _unique_remote_addr() -> str:
        """A fresh TEST-NET-2 address per request, so no two posts share a limiter bucket."""
        return f"198.51.100.{next(_REMOTE_ADDRS) % 254 + 1}"

    def _post_as_guest(self, dotted: str, payment_id: str):
        from frappe.handler import execute_cmd

        environ = EnvironBuilder(
            method="POST",
            path="/",
            data={"id": payment_id},
            content_type="application/x-www-form-urlencoded",
            environ_overrides={"REMOTE_ADDR": self._unique_remote_addr()},
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

    def _unpaid_dues_invoice(self, coverage=("2025-04-01", "2025-04-30")):
        """A submitted open dues invoice. Real dues invoices always carry the coverage
        dates of the running period they discharge (the matcher keys on them); pass
        ``coverage=None`` for one that does not."""
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
        if coverage:
            invoice.custom_coverage_start_date, invoice.custom_coverage_end_date = coverage
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

    def _age_the_invoice_out_of_reach(self):
        """Move the open invoice's coverage to a period years before the payment, outside
        the matcher's window, so the payment matches NO open invoice (#1803).

        Probe shortcut: coverage dates are written directly (the matcher's own input)."""
        frappe.db.set_value(
            "Sales Invoice",
            self.invoice_name,
            {"custom_coverage_start_date": "2023-01-01", "custom_coverage_end_date": "2023-01-31"},
            update_modified=False,
        )

    def test_a_second_identical_delivery_leaves_state_unchanged(self):
        """#1780, for a payment that matches NO open invoice (it stays a Bank Transaction
        only; #1803 allocates the matched case, tested below).
        Probe shortcut: none -- both deliveries are the real Guest dispatch."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self._age_the_invoice_out_of_reach()
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))

        first = self._post_mollie_notification(payment)
        after_first = self._state_of(payment_id)
        self.assertEqual(len(after_first["bank_transactions"]), 1, f"fixture: no BT booked: {first}")
        self.assertEqual(after_first["payment_entries"], [], "fixture: BT mode books no Payment Entry")

        second = self._post_mollie_notification(payment)

        self.assertEqual(self._state_of(payment_id), after_first, f"a retry changed state: {second}")
        self.assertEqual(after_first["bank_transactions"][0]["status"], "Unreconciled")

    def test_a_retry_resubmits_a_bank_transaction_left_in_draft_and_allocates_the_matched_invoice(self):
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
        # The first delivery also must not book a Payment Entry against a draft BT.
        with patch.object(secure_operations, "secure_document_operation", side_effect=refuse_submit):
            self._post_mollie_notification(payment)
        rows = frappe.get_all("Bank Transaction", filters={"reference_number": payment_id}, fields=["docstatus"])
        self.assertEqual([r.docstatus for r in rows], [0], "fixture: the first delivery must leave a draft")
        self.assertEqual(self._state_of(payment_id)["payment_entries"], [], "a PE was booked against a draft BT")

        self._post_mollie_notification(payment)

        after = self._state_of(payment_id)
        self.assertEqual([b["docstatus"] for b in after["bank_transactions"]], [1], "draft BT not resubmitted")
        self.assertEqual(len(after["payment_entries"]), 1, "the retry must book ONE allocated Payment Entry")
        self.assertEqual(after["outstanding"], 0.0)
        self.assertEqual(after["bank_transactions"][0]["status"], "Reconciled")

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

    # ---- #1803: a confirmed dues payment is booked ALLOCATED to its open invoice ----

    def _allocation_state(self, payment_id):
        """The books for one payment: its Payment Entries (any docstatus), what each
        allocates, the Bank Transaction link rows and the invoice outstanding."""
        pes = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": payment_id, "payment_type": "Receive"},
            fields=["name", "docstatus", "paid_amount"],
        )
        refs = frappe.get_all(
            "Payment Entry Reference",
            filters={"parent": ["in", [p.name for p in pes] or [""]], "reference_doctype": "Sales Invoice"},
            fields=["parent", "reference_name", "allocated_amount"],
        )
        bts = frappe.get_all(
            "Bank Transaction",
            filters={"reference_number": payment_id},
            fields=["name", "docstatus", "status", "deposit", "allocated_amount", "unallocated_amount"],
        )
        links = frappe.get_all(
            "Bank Transaction Payments",
            filters={"parent": ["in", [b.name for b in bts] or [""]]},
            fields=["parent", "payment_document", "payment_entry", "allocated_amount"],
        )
        return {"pes": pes, "refs": refs, "bts": bts, "links": links, "outstanding": self._invoice_outstanding()}

    def test_a_paid_dues_notification_books_a_payment_entry_allocated_to_the_matched_invoice(self):
        """#1803, through the real Guest dispatch; only Mollie's HTTP boundary is stubbed."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        total = float(self.invoice_total)

        result = self._post_mollie_notification(self._paid_dues_payment(payment_id, total))

        state = self._allocation_state(payment_id)
        self.assertLess(self._http_status(), 400, result)
        self.assertEqual([p.docstatus for p in state["pes"]], [1], f"expected one submitted PE: {result}")
        pe = state["pes"][0]
        self.assertEqual(
            [(r.parent, r.reference_name, float(r.allocated_amount)) for r in state["refs"]],
            [(pe.name, self.invoice_name, total)],
            "the Payment Entry is not allocated to the matched invoice",
        )
        self.assertEqual(state["outstanding"], 0.0)
        self.assertEqual(frappe.db.get_value("Sales Invoice", self.invoice_name, "status"), "Paid")
        # The Bank Transaction and the PE are ONE movement of cash, linked, not two.
        self.assertEqual(len(state["bts"]), 1)
        bt = state["bts"][0]
        self.assertEqual(bt.docstatus, 1)
        self.assertEqual(float(bt.deposit), total)
        self.assertEqual(
            [(k.payment_document, k.payment_entry, float(k.allocated_amount)) for k in state["links"]],
            [("Payment Entry", pe.name, total)],
        )
        self.assertEqual(float(bt.allocated_amount), total)
        self.assertEqual(float(bt.unallocated_amount), 0.0)
        self.assertEqual(bt.status, "Reconciled")

    def test_an_overpayment_allocates_the_invoice_and_keeps_the_excess_unallocated(self):
        """One open invoice, paid a little more: the invoice is settled, the excess stays
        an unallocated credit on the customer, and the Bank Transaction is still fully
        linked (the PE records the whole cash)."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        total = float(self.invoice_total)
        paid = round(total + 1.37, 2)

        self._post_mollie_notification(self._paid_dues_payment(payment_id, paid))

        books = self._allocation_state(payment_id)
        self.assertEqual([p.docstatus for p in books["pes"]], [1])
        self.assertEqual(float(books["pes"][0].paid_amount), paid)
        self.assertEqual([float(r.allocated_amount) for r in books["refs"]], [total])
        self.assertEqual(books["outstanding"], 0.0)
        self.assertEqual(float(books["bts"][0].unallocated_amount), 0.0)

    def test_the_batch_path_with_create_payment_entry_links_the_allocated_entry_once(self):
        """Second path to the same outcome: ``batch_process_customer_payments`` links a
        Payment Entry to the BT itself when ``create_payment_entry`` is set. When the
        processor has already booked and linked the allocated one, a second link row
        would double-count the cash. Only the SDK listing is stubbed."""
        from types import SimpleNamespace

        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        customers = SimpleNamespace(
            get=lambda _cid: SimpleNamespace(payments=SimpleNamespace(list=lambda **_kw: [payment]))
        )
        processor = DuesPaymentProcessor()
        processor.mollie_client = SimpleNamespace(sdk_client=SimpleNamespace(customers=customers))

        result = processor.batch_process_customer_payments(self.mollie_customer_id, create_payment_entry=True)

        self.assertEqual(result["errors"], 0, result)
        books = self._allocation_state(payment_id)
        self.assertEqual([p.docstatus for p in books["pes"]], [1])
        self.assertEqual(len(books["links"]), 1, f"the Payment Entry was linked to the BT twice: {books['links']}")
        self.assertEqual(float(books["bts"][0].allocated_amount), float(self.invoice_total))
        self.assertEqual(books["outstanding"], 0.0)

    def test_a_second_delivery_of_an_allocated_dues_payment_changes_nothing(self):
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        self._post_mollie_notification(payment)
        before, books = self._state_of(payment_id), self._allocation_state(payment_id)
        self.assertEqual(len(books["pes"]), 1, "fixture: the first delivery must have allocated")

        again = self._post_mollie_notification(payment)

        self.assertLess(self._http_status(), 400, again)
        self.assertEqual(self._state_of(payment_id), before)
        self.assertEqual(self._allocation_state(payment_id), books)

    def test_a_redelivery_allocates_a_dues_bank_transaction_booked_before_it_could_match(self):
        """A BT-only row (what every dues payment produced before #1803, or one whose
        invoice did not exist yet) is completed by the next delivery: ONE allocated PE,
        linked to the EXISTING BT, no second BT.

        Probe shortcut: the first delivery is the real dispatch against an invoice with no
        coverage dates (the matcher keys on them), which the fixture then gains."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        frappe.db.set_value(
            "Sales Invoice",
            self.invoice_name,
            {"custom_coverage_start_date": None, "custom_coverage_end_date": None},
            update_modified=False,
        )
        self._post_mollie_notification(payment)
        first = self._allocation_state(payment_id)
        self.assertEqual((len(first["bts"]), first["pes"], first["outstanding"]), (1, [], float(self.invoice_total)))
        frappe.db.set_value(
            "Sales Invoice",
            self.invoice_name,
            {"custom_coverage_start_date": "2025-04-01", "custom_coverage_end_date": "2025-04-30"},
            update_modified=False,
        )

        result = self._post_mollie_notification(payment)

        books = self._allocation_state(payment_id)
        self.assertLess(self._http_status(), 400, result)
        self.assertEqual([b.name for b in books["bts"]], [b.name for b in first["bts"]], "a second BT was booked")
        self.assertEqual([p.docstatus for p in books["pes"]], [1])
        self.assertEqual(books["outstanding"], 0.0)
        self.assertEqual([k.payment_entry for k in books["links"]], [books["pes"][0].name])

    def test_a_redelivery_after_staff_cancelled_the_payment_entry_is_acknowledged_and_not_rebooked(self):
        """#2406 ruling through the real Guest dispatch: staff cancelled the allocated PE the
        webhook booked, Mollie re-delivers. The matched invoice is open again, so the #1803 path
        tries to book once more and the writer REFUSES; the webhook must still acknowledge
        (a 5xx starts a retry storm for a payment staff decided about), book nothing new, and
        alert staff once. Probe shortcut: none; the cancel is the real document cancel."""
        from verenigingen.tests.support import forward_refusal as refusal

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        test_user = frappe.session.user

        def book():
            self._post_mollie_notification(payment)
            # The dispatch leaves the webhook user on the session; staff act as the test's own user.
            frappe.set_user(test_user)
            return frappe.get_all(
                "Payment Entry", filters={"reference_no": payment_id, "docstatus": 1}, pluck="name"
            )[0]

        first = refusal.book_then_staff_cancel(self, payment_id, book)
        self.assertEqual(self._invoice_outstanding(), float(self.invoice_total), "fixture: invoice must be open")

        for _ in range(2):  # the second redelivery must not alert staff again
            result = self._post_mollie_notification(payment)

            self.assertLess(self._http_status(), 400, f"a refused redelivery must be acknowledged: {result}")
            refusal.assert_not_rebooked(self, payment_id, first)
            refusal.assert_refused_once(self, payment_id, f"{float(self.invoice_total):.2f}")
            self.assertEqual(self._invoice_outstanding(), float(self.invoice_total))

    def _error_log_rows(self, title, payment_id):
        """Error Log rows (MyISAM, so they survive rollback) naming this payment."""
        return frappe.get_all(
            "Error Log",
            filters={"method": title, "error": ["like", f"%{payment_id}%"]},
            fields=["name", "error"],
        )

    def _force_the_bank_transaction_link_to_fail(self):
        """Make ERPNext's ``add_payment_entries`` raise, the step the reviewer forced on #1803."""
        from unittest.mock import patch

        from erpnext.accounts.doctype.bank_transaction.bank_transaction import BankTransaction

        return patch.object(BankTransaction, "add_payment_entries", side_effect=RuntimeError("link boom"))

    LINK_FAILURE_TITLE = "Mollie dues: Bank Transaction not linked to Payment Entry"

    def test_a_failed_bank_transaction_link_is_written_to_the_error_log(self):
        """#1803 review F1: the PE is booked, the BT stays Unreconciled and the failure must
        be VISIBLE (frappe.logger() writes nothing anyone reads). Probe shortcut: the failure is
        forced by making ``add_payment_entries`` raise."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        self.addCleanup(frappe.db.delete, "Error Log", {"method": self.LINK_FAILURE_TITLE, "error": ["like", f"%{payment_id}%"]})
        self.expectErrorLog(self.LINK_FAILURE_TITLE)

        with self._force_the_bank_transaction_link_to_fail():
            self._post_mollie_notification(payment)

        books = self._allocation_state(payment_id)
        self.assertEqual([p.docstatus for p in books["pes"]], [1], "fixture: the PE must be booked")
        self.assertEqual(books["links"], [], "fixture: the link must have failed")
        rows = self._error_log_rows(self.LINK_FAILURE_TITLE, payment_id)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn(books["pes"][0].name, rows[0].error)
        self.assertIn(books["bts"][0].name, rows[0].error)
        self.assertIn("link boom", rows[0].error)

    def test_a_redelivery_links_the_bank_transaction_a_failed_link_left_behind(self):
        """#1803 review F1: without this the booked cash sits in the reconciliation pool and
        staff book it a second time. The redelivery links BT to the EXISTING PE: no second PE,
        no second BT, one link row. A further redelivery changes nothing."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        self.addCleanup(frappe.db.delete, "Error Log", {"method": self.LINK_FAILURE_TITLE, "error": ["like", f"%{payment_id}%"]})
        self.expectErrorLog(self.LINK_FAILURE_TITLE)
        with self._force_the_bank_transaction_link_to_fail():
            self._post_mollie_notification(payment)
        failed = self._allocation_state(payment_id)
        self.assertEqual(len(failed["pes"]), 1, "fixture: the PE must be booked")
        self.assertEqual(failed["links"], [], "fixture: the link must have failed")

        result = self._post_mollie_notification(payment)

        books = self._allocation_state(payment_id)
        self.assertLess(self._http_status(), 400, result)
        self.assertEqual([p.name for p in books["pes"]], [p.name for p in failed["pes"]], "a second PE was booked")
        self.assertEqual([b.name for b in books["bts"]], [b.name for b in failed["bts"]])
        self.assertEqual([k.payment_entry for k in books["links"]], [books["pes"][0].name])
        self.assertEqual(books["bts"][0].status, "Reconciled")
        self.assertEqual(books["bts"][0].allocated_amount, books["bts"][0].deposit)
        settled = self._allocation_state(payment_id)

        self._post_mollie_notification(payment)

        self.assertEqual(self._allocation_state(payment_id), settled)

    def test_a_redelivery_after_staff_cancelled_both_the_entry_and_the_bank_transaction_books_nothing(self):
        """#1803 review F4: staff cancel the PE AND the BT, Mollie redelivers. Pins what happens:
        nothing is booked, the webhook acknowledges (200), and the Error Log names the cancelled
        Bank Transaction that holds the unique reference instead of claiming a lost "race condition". Probe shortcut: none; both cancels are real document cancels."""
        from verenigingen.tests.support import forward_refusal as refusal

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        test_user = frappe.session.user

        def book():
            self._post_mollie_notification(payment)
            frappe.set_user(test_user)
            return frappe.get_all(
                "Payment Entry", filters={"reference_no": payment_id, "docstatus": 1}, pluck="name"
            )[0]

        first = refusal.book_then_staff_cancel(self, payment_id, book)
        bt_name = frappe.get_all("Bank Transaction", filters={"reference_number": payment_id}, pluck="name")[0]
        bt = frappe.get_doc("Bank Transaction", bt_name)
        if bt.docstatus == 1:
            bt.cancel()
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt_name, "docstatus"), 2, "fixture")
        held = "Bank Transaction Reference Held By Cancelled Row"
        self.addCleanup(frappe.db.delete, "Error Log", {"method": held, "error": ["like", f"%{payment_id}%"]})
        self.expectErrorLog(held)
        self.expectErrorLog("Secure Operation Failed")

        result = self._post_mollie_notification(payment)

        self.assertLess(self._http_status(), 400, result)
        refusal.assert_not_rebooked(self, payment_id, first)
        live_bts = frappe.get_all(
            "Bank Transaction", filters={"reference_number": payment_id, "docstatus": ["!=", 2]}, pluck="name"
        )
        self.assertEqual(live_bts, [], "a Bank Transaction was booked again")
        self.assertEqual(self._invoice_outstanding(), float(self.invoice_total))
        rows = self._error_log_rows(held, payment_id)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn(bt_name, rows[0].error)
        self.assertEqual(
            self._error_log_rows("Bank Transaction Race Condition Error", payment_id),
            [],
            "a cancelled Bank Transaction was reported as a lost race",
        )

    def test_a_genuine_failure_to_book_the_allocated_entry_still_answers_5xx(self):
        """Control for the #2406 acknowledgement: it is for the staff-cancel refusal ONLY. Same
        shape (a BT exists, the invoice matches, the writer books nothing) but nobody cancelled
        anything, so Mollie must keep retrying. Probe shortcut: the failure is made by stubbing
        the writer to return nothing, and the BT-only row by aging the invoice out of reach for
        the first delivery."""
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._paid_dues_payment(payment_id, float(self.invoice_total))
        self._age_the_invoice_out_of_reach()
        self._post_mollie_notification(payment)
        frappe.db.set_value(
            "Sales Invoice",
            self.invoice_name,
            {"custom_coverage_start_date": "2025-04-01", "custom_coverage_end_date": "2025-04-30"},
            update_modified=False,
        )
        self.assertEqual(len(self._allocation_state(payment_id)["bts"]), 1, "fixture: BT-only row expected")

        with patch.object(DuesPaymentProcessor, "_create_payment_entry_for_dues", return_value=None):
            self._post_mollie_notification(payment)

        self.assertEqual(self._http_status(), 500)
        self.assertEqual(self._allocation_state(payment_id)["pes"], [])

    def test_two_open_invoices_the_payment_could_be_for_are_not_guessed_between(self):
        """Control: with TWO equally good candidates the payment stays a Bank Transaction,
        both invoices stay open, nothing is allocated, and the refusal is in the Error Log.
        Both candidates are real, open, same-amount invoices of the member."""
        second_invoice, _ = self._unpaid_dues_invoice(coverage=("2025-04-01", "2025-04-30"))
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self.expectErrorLog("Invoice Match Ambiguous")

        result = self._post_mollie_notification(self._paid_dues_payment(payment_id, float(self.invoice_total)))

        books = self._allocation_state(payment_id)
        self.assertLess(self._http_status(), 400, result)
        self.assertEqual(books["pes"], [], "a payment was allocated by guessing between two invoices")
        self.assertEqual(len(books["bts"]), 1, "the payment must still be booked as a Bank Transaction")
        self.assertEqual(books["outstanding"], float(self.invoice_total))
        self.assertEqual(
            float(frappe.db.get_value("Sales Invoice", second_invoice, "outstanding_amount")),
            float(self.invoice_total),
        )

    def test_a_refund_of_an_allocated_dues_payment_is_booked(self):
        """The #1803 consequence: with the forward Payment Entry the webhook itself booked
        (no hand-made one), a refund announced by a re-delivery is bookable and moves the
        invoice back to open by exactly the refunded amount, once."""
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        total = float(self.invoice_total)
        self._post_mollie_notification(self._paid_dues_payment(payment_id, total))
        self.assertEqual(self._invoice_outstanding(), 0.0, "fixture: the delivery must allocate")
        refund = self._refund_of(round(total / 5, 2))
        refunded = float(refund["amount"]["value"])
        payment = self._paid_dues_payment(
            payment_id,
            total,
            amountRefunded={"value": f"{refunded:.2f}", "currency": self.currency},
        )
        client = _FakeMollie(refunds=[refund])

        first = self._post_mollie_notification(payment, client)
        again = self._post_mollie_notification(payment, client)

        self.assertLess(self._http_status(), 400, first)
        self.assertLess(self._http_status(), 400, again)
        key = f"{payment_id}_refund_{refund['id']}"
        self.assertEqual(len(frappe.get_all("Journal Entry", filters={"cheque_no": key, "docstatus": 1})), 1)
        self.assertEqual(self._invoice_outstanding(), refunded)

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
            "status": "refunded",
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
        # A payment matching no open invoice stays a Bank Transaction only (#1803).
        self._age_the_invoice_out_of_reach()
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
