# Copyright (c) 2026, Verenigingen
# License: MIT

"""A member's Sales Invoice paid through Mollie checkout (#2244).

Two halves, tested separately because the harness company's currency is site-dependent (INR on
some test sites) while Mollie refuses INR:

* ``TestSalesInvoiceCheckoutIdempotency2244``: ``mollie_checkout.make_payment``. The invoice is
  pinned to EUR (``db_set``) so a missing refusal would reach ``payments.create``. Only Mollie's
  HTTP client is stubbed (``_Si2244MollieHttp``).
* ``TestSalesInvoiceWebhookBooking2244``: the anonymous Mollie notification, through Frappe's
  real Guest dispatch (so rate limit, webhook authentication and the webhook-user switch run).
  Only ``fetch_payment`` and the SDK client the refund discovery lists from are stubbed. The
  payment is in the company's own currency, the Bank Transaction's account requiring that.

Probe shortcuts (stated): ``outstanding_amount`` is set with ``db_set`` where a test needs a
changed amount, and the invoice's ``payment_id`` is written with ``db_set`` in the webhook half
(the checkout half writes it through the real ``make_payment``).
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_mollie_gateway_sales_invoice_amount import (
    _GET_CLIENT,
    _GET_WEBHOOK_URL,
)
from verenigingen.tests.payment.test_provider_webhook_urls_guest_reachable import (
    _dotted_method,
    _GuestDispatchMixin,
)

UNBOOKABLE_KEY = "mollie_invoice_payment_unbookable"
UNBOOKABLE_TITLE = "Mollie Invoice Payment Not Booked"


class _Si2244MollieHttp:
    """Mollie's HTTP boundary: remembers what was created and deleted, answers ``get``."""

    def __init__(self):
        self.payments = self
        self.created = []
        self.deleted = []
        self.state = "open"
        self.delete_raises = False

    def create(self, data):
        payment_id = f"tr_si2244_{len(self.created) + 1}_{frappe.generate_hash(length=6)}"
        self.created.append((payment_id, data))
        return SimpleNamespace(
            id=payment_id,
            status="open",
            expires_at=datetime.now() + timedelta(days=1),
            checkout_url=f"https://pay.mollie.test/checkout/{payment_id}",
        )

    def get(self, payment_id):
        data = dict(self.created)[payment_id]
        state = self.state
        return SimpleNamespace(
            id=payment_id,
            amount=data["amount"],
            checkout_url=f"https://pay.mollie.test/checkout/{payment_id}",
            is_paid=lambda: state == "paid",
            is_pending=lambda: state == "pending",
            is_open=lambda: state == "open",
        )

    def delete(self, payment_id):
        if self.delete_raises:
            raise RuntimeError("mollie refuses to cancel")
        self.deleted.append(payment_id)


def _si2244_member_invoice(case, *, with_member=True, currency=None, grand_total=40.0):
    member = case.create_test_member(first_name="Si2244", last_name=f"M{frappe.generate_hash()[:6]}")
    invoice = case.create_test_sales_invoice(customer=member.name, grand_total=grand_total)
    email = f"si2244-{frappe.generate_hash()[:8]}@example.com"
    invoice.db_set("contact_email", email)
    # The factory may or may not link the member; set it explicitly either way.
    invoice.db_set("member", member.name if with_member else None)
    if currency:
        invoice.db_set("currency", currency)
    invoice.reload()
    return member, invoice, email


class TestSalesInvoiceCheckoutIdempotency2244(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_user = frappe.session.user
        self.mollie = _Si2244MollieHttp()

    def tearDown(self):
        frappe.set_user(self._original_user)
        super().tearDown()

    def _checkout(self, invoice, email):
        from verenigingen.verenigingen_payments.templates.pages.mollie_checkout import make_payment

        data = json.dumps(
            {
                "amount": 1.23,
                "title": "Invoice",
                "description": "Invoice",
                "payer_name": "Someone",
                "payer_email": email,
                "order_id": "ORD-2244",
                "currency": "EUR",
            }
        )
        with self.as_user("Administrator"), patch(_GET_CLIENT, return_value=self.mollie), patch(
            _GET_WEBHOOK_URL, return_value="https://example.test/webhook"
        ):
            return make_payment(
                data=data,
                reference_doctype="Sales Invoice",
                reference_docname=invoice.name,
                gateway_name="Default",
            )

    def _stored_payment_id(self, invoice):
        return frappe.db.get_value("Sales Invoice", invoice.name, "payment_id")

    def test_the_second_checkout_reuses_the_open_payment(self):
        _m, invoice, email = _si2244_member_invoice(self, currency="EUR")

        first = self._checkout(invoice, email)
        second = self._checkout(invoice, email)

        self.assertEqual(len(self.mollie.created), 1, "a second live Mollie payment was created")
        self.assertEqual(first["status"], "Open", first)
        self.assertEqual(second["status"], "Open", second)
        self.assertEqual(second["paymentUrl"], first["paymentUrl"])
        self.assertEqual(self._stored_payment_id(invoice), self.mollie.created[0][0])
        self.assertEqual(self.mollie.deleted, [], "an up-to-date open payment must not be cancelled")

    def test_an_open_payment_for_an_amount_no_longer_owed_is_cancelled_and_replaced(self):
        _m, invoice, email = _si2244_member_invoice(self, currency="EUR", grand_total=40.0)
        self._checkout(invoice, email)
        old_id, old_data = self.mollie.created[0]
        # Probe shortcut: a part-payment is stood in for by setting the outstanding directly.
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 15.0)

        second = self._checkout(invoice, email)

        self.assertEqual(second["status"], "Open", second)
        self.assertEqual(self.mollie.deleted, [old_id])
        self.assertEqual(len(self.mollie.created), 2)
        new_id, new_data = self.mollie.created[1]
        self.assertEqual(new_data["amount"]["value"], "15.00")
        self.assertNotEqual(new_data["amount"], old_data["amount"], "fixture: the amounts must differ")
        self.assertEqual(self._stored_payment_id(invoice), new_id)

    def test_a_failed_cancel_of_the_stale_payment_keeps_the_old_payment_instead_of_a_second_live_one(self):
        """If Mollie will not cancel the stale payment it is still payable, so creating a second
        live one would open a double-charge window: the payer is sent to the old one."""
        self.expectErrorLog("Mollie Stale Payment Cancel Failed")
        _m, invoice, email = _si2244_member_invoice(self, currency="EUR", grand_total=40.0)
        first = self._checkout(invoice, email)
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 15.0)
        self.mollie.delete_raises = True

        second = self._checkout(invoice, email)

        self.assertEqual(second["status"], "Open", second)
        self.assertEqual(second["paymentUrl"], first["paymentUrl"])
        self.assertEqual(len(self.mollie.created), 1, "a second live payment was created")
        self.assertEqual(self._stored_payment_id(invoice), self.mollie.created[0][0])

    def test_a_cancelled_payment_is_replaced_without_a_cancel_call(self):
        _m, invoice, email = _si2244_member_invoice(self, currency="EUR")
        self._checkout(invoice, email)
        self.mollie.state = "cancelled"

        second = self._checkout(invoice, email)

        self.assertEqual(second["status"], "Open", second)
        self.assertEqual(len(self.mollie.created), 2)
        self.assertEqual(self.mollie.deleted, [])

    def test_a_paid_payment_is_not_replaced(self):
        _m, invoice, email = _si2244_member_invoice(self, currency="EUR")
        self._checkout(invoice, email)
        self.mollie.state = "paid"

        second = self._checkout(invoice, email)

        self.assertEqual(second["status"], "Completed", second)
        self.assertEqual(len(self.mollie.created), 1)

    def test_an_invoice_without_a_member_is_refused_before_mollie(self):
        _m, invoice, email = _si2244_member_invoice(self, with_member=False, currency="EUR")

        result = self._checkout(invoice, email)

        self.assertEqual(self.mollie.created, [])
        self.assertEqual(result["status"], "Error", result)
        self.assertEqual(result["message"], "This invoice cannot be paid through this page.")
        self.assertFalse(self._stored_payment_id(invoice))

    def test_a_settled_invoice_creates_no_payment(self):
        _m, invoice, email = _si2244_member_invoice(self, currency="EUR")
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0.0)

        result = self._checkout(invoice, email)

        self.assertEqual(self.mollie.created, [])
        self.assertEqual(result["status"], "Error", result)

    def test_the_stored_id_is_read_under_a_row_lock(self):
        """Mechanism check only: two concurrent checkouts are serialised by the row lock, which a
        single-connection test cannot exercise, so this asserts the locking read is issued."""
        _m, invoice, email = _si2244_member_invoice(self, currency="EUR")
        real = frappe.db.get_value
        seen = []

        def spy(*args, **kwargs):
            if args and args[0] == "Sales Invoice" and "payment_id" in args:
                seen.append(kwargs.get("for_update"))
            return real(*args, **kwargs)

        # Mock justified: call-through spy; every read still runs for real, the spy only records the flag
        with patch.object(frappe.db, "get_value", side_effect=spy):
            self._checkout(invoice, email)

        self.assertIn(True, seen)

    def test_a_copied_invoice_does_not_inherit_the_payment_id(self):
        self.assertEqual(frappe.get_meta("Sales Invoice").get_field("payment_id").no_copy, 1)


class TestSalesInvoiceWebhookBooking2244(_GuestDispatchMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        from verenigingen.tests.fixtures.mollie_account_fixtures import (
            ensure_bank_account_record,
            provisioned_mollie_settings,
        )

        self.company = self._get_test_company()
        ctx = provisioned_mollie_settings(company=self.company)
        accounts = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.clearing_account = accounts["clearing_account"]
        ensure_bank_account_record(self.company, accounts["clearing_account"])
        self.currency = frappe.get_value("Company", self.company, "default_currency")
        self.member, self.invoice, _email = _si2244_member_invoice(self)
        self.total = float(self.invoice.grand_total)
        self.webhook_url = frappe.get_single("Mollie Settings").get_subscription_webhook_url()
        self.payment_id = f"tr_{frappe.generate_hash(length=10)}"
        self.invoice.db_set("payment_id", self.payment_id)
        self.addCleanup(self._purge_alert_rows, self.payment_id)

    @staticmethod
    def _purge_alert_rows(payment_id):
        for event in frappe.get_all("Staff Alert Event", filters={"reference_name": payment_id}, pluck="name"):
            frappe.delete_doc("Staff Alert Event", event, force=True)
        frappe.db.delete("Error Log", {"method": UNBOOKABLE_TITLE, "error": ["like", f"%{payment_id}%"]})

    def _paid_invoice_payment(self, amount=None, status="paid", payment_id=None, invoice_name=None, **extra):
        """What Mollie returns for a payment ``make_payment`` created: the metadata and the default
        ``Donation <name>`` description are exactly what the gateway sends, and no customer id."""
        invoice_name = invoice_name or self.invoice.name
        return SimpleNamespace(
            id=payment_id or self.payment_id,
            status=status,
            amount={"value": f"{(self.total if amount is None else amount):.2f}", "currency": self.currency},
            description=f"Donation {invoice_name}",
            metadata={
                "donation_id": invoice_name,
                "reference_doctype": "Sales Invoice",
                "reference_docname": invoice_name,
            },
            subscription_id=None,
            customer_id=None,
            paid_at="2025-04-10T09:00:00+00:00",
            **extra,
        )

    def _deliver_si2244(self, payment, mollie_client=None):
        """One anonymous notification through the real Guest dispatch (rate limit, webhook
        authentication, webhook user). Only ``fetch_payment`` and the SDK client are stubbed."""
        from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
        from verenigingen.verenigingen_payments.mollie.services.payment_type_router import (
            PaymentTypeRouter,
        )

        class _Listing:
            def __init__(self, refunds):
                self._refunds = refunds
                self.payments = self

            def get(self, _id):
                return self

            @property
            def refunds(self):
                return SimpleNamespace(list=lambda: {"_embedded": {"refunds": self._refunds}})

            @property
            def chargebacks(self):
                return SimpleNamespace(list=lambda: [])

        client = mollie_client or _Listing([])
        frappe.local.response.pop("http_status_code", None)
        test_user = frappe.session.user
        with patch.object(PaymentTypeRouter, "fetch_payment", return_value=payment), patch.object(
            MollieClient, "_get_mollie_client", return_value=client
        ), patch.dict(frappe.conf, {"allow_mollie_test_mode": 1}):
            result = self._post_as_guest(_dotted_method(self.webhook_url), payment.id)
        frappe.set_user(test_user)
        return result

    def _books(self, payment_id=None):
        payment_id = payment_id or self.payment_id
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
        return {
            "pes": [dict(p) for p in pes],
            "refs": [dict(r) for r in refs],
            "bts": frappe.get_all("Bank Transaction", filters={"reference_number": payment_id}, pluck="name"),
            "journal_entries": frappe.get_all(
                "Journal Entry", filters={"cheque_no": ["like", f"{payment_id}%"], "docstatus": 1}, pluck="name"
            ),
            "outstanding": flt(
                frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")
            ),
        }

    @staticmethod
    def _si2244_http_status():
        return int(frappe.local.response.get("http_status_code") or 200)

    def _alert_rows(self, payment_id=None):
        payment_id = payment_id or self.payment_id
        return {
            "logs": frappe.get_all(
                "Error Log", filters={"method": UNBOOKABLE_TITLE, "error": ["like", f"%{payment_id}%"]}, pluck="error"
            ),
            "events": frappe.get_all(
                "Staff Alert Event",
                filters={"notification_key": UNBOOKABLE_KEY, "reference_name": payment_id},
                fields=["name", "attempts", "recipient_count"],
            ),
        }

    def _a_reachable_staff_recipient(self):
        from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows

        ensure_notification_registry_rows()
        frappe.get_doc(
            {
                "doctype": "User",
                "email": f"staff2244-{frappe.generate_hash(length=6)}@example.com",
                "first_name": "Staff2244",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()

    # ---- booking ----

    def test_a_paid_invoice_payment_books_a_payment_entry_allocated_to_the_invoice(self):
        result = self._deliver_si2244(self._paid_invoice_payment())

        books = self._books()
        self.assertLess(self._si2244_http_status(), 400, result)
        self.assertEqual([p["docstatus"] for p in books["pes"]], [1], result)
        self.assertEqual(
            [(r["parent"], r["reference_name"], flt(r["allocated_amount"])) for r in books["refs"]],
            [(books["pes"][0]["name"], self.invoice.name, self.total)],
        )
        self.assertEqual(books["outstanding"], 0.0)
        self.assertEqual(frappe.db.get_value("Sales Invoice", self.invoice.name, "status"), "Paid")
        self.assertEqual(len(books["bts"]), 1)

    def test_an_overpayment_settles_the_invoice_and_keeps_the_excess_unallocated(self):
        paid = round(self.total + 1.37, 2)

        self._deliver_si2244(self._paid_invoice_payment(amount=paid))

        books = self._books()
        self.assertEqual([flt(p["paid_amount"]) for p in books["pes"]], [paid])
        self.assertEqual([flt(r["allocated_amount"]) for r in books["refs"]], [self.total])
        self.assertEqual(books["outstanding"], 0.0)

    def test_a_redelivery_changes_nothing(self):
        payment = self._paid_invoice_payment()
        self._deliver_si2244(payment)
        before = self._books()
        self.assertEqual(len(before["pes"]), 1, "fixture: the first delivery must book")

        again = self._deliver_si2244(payment)

        self.assertLess(self._si2244_http_status(), 400, again)
        self.assertEqual(self._books(), before)

    def test_a_payment_that_is_not_paid_books_nothing(self):
        before = self._books()

        result = self._deliver_si2244(self._paid_invoice_payment(status="open"))

        self.assertLess(self._si2244_http_status(), 400, result)
        self.assertEqual(self._books(), before)
        self.assertEqual(before["pes"], [])

    def test_a_refund_announced_for_an_invoice_payment_reaches_the_reversal_booking(self):
        """Routing seam with real code, no booked Payment Entry. Refund discovery commits, so with a
        forward Payment Entry booked first the harness drain could not delete it (TEST-LEAK); the
        reversal booking itself is covered for dues in ``test_provider_webhook_urls_guest_reachable``.
        Here the invoice has no Member, so the forward payment is refused (nothing booked) and the
        refund the delivery announces is still discovered and handed to the reversal booking, which
        refuses it because the original payment was never booked: a 5xx naming that. Control: the
        same delivery with no refund announced answers 2xx (``test_a_payment_for_an_invoice_without_a_member_...``)."""
        self.invoice.db_set("member", None)
        self.expectErrorLog(UNBOOKABLE_TITLE, "Mollie Webhook Processing Error")
        refunded = round(self.total / 5, 2)
        refund = {
            "id": f"re_{frappe.generate_hash(length=8)}",
            "amount": {"value": f"{refunded:.2f}", "currency": self.currency},
            "status": "refunded",
            "createdAt": "2025-04-11T09:00:00+00:00",
        }
        payment = self._paid_invoice_payment(
            amountRefunded={"value": f"{refunded:.2f}", "currency": self.currency}
        )

        class _Refunds:
            def __init__(s):
                s.payments = s

            def get(s, _id):
                return s

            @property
            def refunds(s):
                return SimpleNamespace(list=lambda: {"_embedded": {"refunds": [refund]}})

            @property
            def chargebacks(s):
                return SimpleNamespace(list=lambda: [])

        self._deliver_si2244(payment, _Refunds())

        self.assertGreaterEqual(self._si2244_http_status(), 400, "the refund never reached the reversal booking")
        books = self._books()
        self.assertEqual((books["pes"], books["journal_entries"]), ([], []))
        logged = frappe.get_all(
            "Error Log",
            filters={"method": "Mollie Webhook Processing Error", "error": ["like", f"%{self.payment_id}%"]},
            pluck="error",
        )
        self.assertTrue(
            any("reversal(s) of" in row and "not booked" in row for row in logged),
            "the reversal booking was not asked for this payment's refund",
        )
        self.addCleanup(
            frappe.db.delete, "Error Log", {"method": "Mollie Webhook Processing Error", "error": ["like", f"%{self.payment_id}%"]}
        )

    def test_a_redelivery_after_staff_cancelled_the_entry_is_not_booked_again(self):
        """#2406 applies: the dues writer refuses, alerts staff on its own key and still acknowledges."""
        from verenigingen.tests.support import forward_refusal as refusal

        payment = self._paid_invoice_payment()
        self._deliver_si2244(payment)
        first = self._books()["pes"][0]["name"]
        frappe.get_doc("Payment Entry", first).cancel()
        refusal.prepare_refusal_fixture(self, self.payment_id)

        result = self._deliver_si2244(payment)

        self.assertLess(self._si2244_http_status(), 400, result)
        refusal.assert_not_rebooked(self, self.payment_id, first)
        self.assertEqual(len(refusal.alert_events(self.payment_id)), 1)

    def test_a_payment_that_is_not_paid_raises_no_alert_even_when_it_is_not_the_invoices_current_one(self):
        """Control for the status guard: an open or cancelled payment of a replaced id is ordinary
        (the payer abandoned it), so it must not be reported as an unbookable PAID payment."""
        self.invoice.db_set("payment_id", f"tr_newer{frappe.generate_hash(length=6)}")
        for status in ("open", "canceled", "expired"):
            payment = self._paid_invoice_payment(status=status)

            result = self._deliver_si2244(payment)

            self.assertLess(self._si2244_http_status(), 400, result)
            rows = self._alert_rows()
            self.assertEqual((rows["logs"], rows["events"]), ([], []), status)

    def test_the_dues_processor_refuses_a_member_who_does_not_own_the_invoice(self):
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        other = self.create_test_member(first_name="Other2244", last_name=f"O{frappe.generate_hash()[:6]}")

        result = DuesPaymentProcessor().process_dues_payment(
            self.payment_id,
            payment=self._paid_invoice_payment(),
            invoice_name=self.invoice.name,
            member_name=other.name,
        )

        self.assertEqual(result["status"], "error", result)
        self.assertEqual(self._books()["pes"], [])
        self.assertEqual(self._books()["outstanding"], self.total)

    # ---- unbookable: staff are told once, Mollie is acknowledged ----

    def test_a_payment_for_an_invoice_without_a_member_is_refused_and_staff_are_told(self):
        self.invoice.db_set("member", None)
        self._a_reachable_staff_recipient()
        self.expectErrorLog(UNBOOKABLE_TITLE)
        payment = self._paid_invoice_payment()

        result = self._deliver_si2244(payment)
        self._deliver_si2244(payment)

        books = self._books()
        self.assertLess(self._si2244_http_status(), 400, result)
        self.assertEqual((books["pes"], books["bts"]), ([], []))
        self.assertEqual(books["outstanding"], self.total)
        rows = self._alert_rows()
        self.assertIn("not linked to a Member", rows["logs"][0])
        self.assertEqual(len(rows["events"]), 1, "staff must be told once per payment")
        self.assertGreaterEqual(rows["events"][0].recipient_count, 1, "the alert reached nobody")

    def test_a_paid_payment_that_is_not_the_invoices_current_one_is_refused(self):
        """A stale payment (replaced at checkout, cancel failed, then paid anyway)."""
        self.invoice.db_set("payment_id", f"tr_newer{frappe.generate_hash(length=6)}")
        self._a_reachable_staff_recipient()
        self.expectErrorLog(UNBOOKABLE_TITLE)

        result = self._deliver_si2244(self._paid_invoice_payment())

        books = self._books()
        self.assertLess(self._si2244_http_status(), 400, result)
        self.assertEqual((books["pes"], books["bts"]), ([], []))
        self.assertEqual(books["outstanding"], self.total)
        rows = self._alert_rows()
        self.assertIn("not the invoice's current payment", rows["logs"][0])
        self.assertEqual(len(rows["events"]), 1)

    def test_a_payment_for_an_unknown_invoice_is_refused_and_staff_are_told(self):
        self._a_reachable_staff_recipient()
        self.expectErrorLog(UNBOOKABLE_TITLE)

        result = self._deliver_si2244(self._paid_invoice_payment(invoice_name="ACC-SINV-NOPE-2244"))

        self.assertLess(self._si2244_http_status(), 400, result)
        self.assertIn("does not exist", self._alert_rows()["logs"][0])

    def test_a_normal_booking_raises_no_alert(self):
        """Control: the refusal rows above are not produced by a payment that books."""
        self._deliver_si2244(self._paid_invoice_payment())

        rows = self._alert_rows()
        self.assertEqual((rows["logs"], rows["events"]), ([], []))
