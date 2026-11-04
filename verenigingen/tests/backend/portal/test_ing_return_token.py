"""ING Checkout return page: a Guest payer is authorised by a signed return token (#2038).

Maintainer ruling 2026-11-03: the token is minted into the ING return URL at order creation
(``guest_return_tokens``, as Mollie and Ponto do). ``/payment_success`` shows the order status
only for a valid token; a missing or invalid one is refused IDENTICALLY to an unknown orderId.

Only the Pay.nl HTTP client (``get_client``) is stubbed. The WSGI test drives a real Guest GET.
"""

import json
import os
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import frappe
from frappe.utils import get_bench_path

from verenigingen.templates.pages import payment_success
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.ing_return import ing_return_token, stub_paynl_order_status
from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token

_SETTINGS_PATH = (
    "verenigingen.verenigingen_payments.doctype.ing_checkout_settings."
    "ing_checkout_settings.get_ing_checkout_settings"
)


class TestIngReturnUrlMintsToken(EnhancedTestCase):
    def _create_order(self, settings_return_url=None, explicit_return_url=None):
        from verenigingen.verenigingen_payments.ing_checkout.api import payment

        client = MagicMock()
        client.create_order.return_value = {
            "id": f"EX-{frappe.generate_hash(length=4)}-5678-9012",
            "links": {"redirect": "https://connect.pay.nl/checkout/abc"},
        }
        settings = SimpleNamespace(default_return_url=settings_return_url, service_id="SL-1234-5678")
        doc = frappe.get_doc({"doctype": "ToDo", "description": "ing token probe"}).insert(
            ignore_permissions=True
        )
        self.track_doc("ToDo", doc.name)
        with patch(_SETTINGS_PATH, return_value=settings), patch.object(payment, "get_client", return_value=client):
            payment.create_ideal_order("ToDo", doc.name, 10.0, "probe", explicit_return_url)
        txn = frappe.db.get_value(
            "ING Checkout Transaction",
            {"transaction_id": client.create_order.return_value["id"]},
            "name",
        )
        self.track_doc("ING Checkout Transaction", txn)
        return doc.name, client.create_order.call_args[0][0]["returnUrl"]

    def test_default_return_url_carries_a_token_bound_to_the_reference(self):
        name, url = self._create_order()
        parts = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.assertEqual(parts.path, "/payment_success")
        self.assertEqual(list(query), ["token"], "Pay.nl appends orderId; only our token may be present")
        from verenigingen.verenigingen_payments.ing_checkout.api.payment import ING_RETURN_TOKEN_PURPOSE

        self.assertTrue(verify_guest_return_token(ING_RETURN_TOKEN_PURPOSE, f"ToDo:{name}", query["token"]))
        # Control: not a token for some other reference, nor Mollie's purpose.
        self.assertFalse(verify_guest_return_token(ING_RETURN_TOKEN_PURPOSE, "ToDo:OTHER", query["token"]))
        self.assertFalse(verify_guest_return_token("payment_success", f"ToDo:{name}", query["token"]))

    def test_stored_override_and_explicit_return_url_are_left_unchanged(self):
        """A page we do not render gets no proof: it would only leak it."""
        self.assertEqual(self._create_order("https://example.org/ing-back")[1], "https://example.org/ing-back")
        self.assertEqual(
            self._create_order(None, "https://example.org/explicit")[1], "https://example.org/explicit"
        )


class TestIngReturnPage(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        frappe.set_user(self._original_user)
        super().tearDown()

    def _order(self, order_id=None):
        donation = self.create_test_donation()
        self.track_doc("Donation", donation.name)
        order_id = order_id or f"EX-{frappe.generate_hash(length=8)}"
        txn = frappe.get_doc(
            {
                "doctype": "ING Checkout Transaction",
                "transaction_id": order_id,
                "status": "Pending",
                "amount": 10.0,
                "currency": "EUR",
                "reference_doctype": "Donation",
                "reference_name": donation.name,
            }
        ).insert()
        self.track_doc("ING Checkout Transaction", txn.name)
        return order_id, donation.name

    def _return(self, order_id, token):
        frappe.local.form_dict = frappe._dict({"orderId": order_id})
        if token is not None:
            frappe.local.form_dict["token"] = token
        context = frappe._dict()
        with stub_paynl_order_status(100) as client:
            payment_success.get_context(context)
        return context, client

    def test_valid_token_shows_the_status_as_a_guest(self):
        order_id, donation = self._order()
        frappe.set_user("Guest")
        with self.assertNoErrorLog():
            context, client = self._return(order_id, ing_return_token("Donation", donation))
        self.assertEqual(context.payment_status, "completed")
        self.assertEqual(context.document_info["docname"], donation)
        client.get_order.assert_called_once_with(order_id)

    def test_refusals_look_the_same_and_never_reach_pay_nl(self):
        """Unknown orderId, known + bad token, known + no token, known + a token for ANOTHER reference."""
        order_id, _donation = self._order()
        _other_order, other_donation = self._order()
        cases = {
            "unknown": ("EX-does-not-exist", ing_return_token("Donation", "whatever")),
            "bad": (order_id, "0" * 64),
            "none": (order_id, None),
            "wrong_reference": (order_id, ing_return_token("Donation", other_donation)),
        }
        frappe.set_user("Guest")
        results = {}
        for label, (oid, token) in cases.items():
            with self.subTest(case=label), self.assertNoErrorLog():
                context, client = self._return(oid, token)
                results[label] = (context.payment_status, context.payment_message, dict(context.document_info), list(context.next_steps))
                client.get_order.assert_not_called()
        self.assertEqual(results["unknown"][0], "error")
        self.assertEqual(results["unknown"][2], {})
        self.assertEqual(len({json.dumps(v, default=str) for v in results.values()}), 1, results)


class TestIngReturnOverWsgi(EnhancedTestCase):
    """A Guest GET through the real WSGI app, and every channel compared across the refusals."""

    def test_guest_get_shows_status_only_for_a_valid_token(self):
        script = textwrap.dedent(
            f"""
            import json, uuid
            from unittest.mock import MagicMock, patch
            import frappe

            SITE = {frappe.local.site!r}
            frappe.init(site=SITE)
            frappe.connect()
            donor = donation = txn = None
            order_id = "EX-" + uuid.uuid4().hex[:8]
            created = {{}}
            try:
                donor = frappe.get_doc({{"doctype": "Donor", "donor_name": "Ing Return Probe", "donor_type": "Individual",
                    "donor_email": "ing." + uuid.uuid4().hex[:8] + "@example.com", "currency": "EUR"}})
                # Donor.insert would otherwise create a committed Customer and Contact this script never deletes.
                donor.flags.ignore_customer_sync = True
                donor.insert()
                donation = frappe.get_doc({{"doctype": "Donation", "donor": donor.name, "donation_date": frappe.utils.today(),
                    "amount": 10.0, "mode_of_payment": "Mollie", "status": "One-time", "donation_purpose_type": "General", "paid": 0}}).insert()
                txn = frappe.get_doc({{"doctype": "ING Checkout Transaction", "transaction_id": order_id, "status": "Pending",
                    "amount": 10.0, "currency": "EUR", "reference_doctype": "Donation", "reference_name": donation.name}}).insert()
                from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token
                from verenigingen.verenigingen_payments.ing_checkout.api.payment import ING_RETURN_TOKEN_PURPOSE
                good = generate_guest_return_token(ING_RETURN_TOKEN_PURPOSE, "Donation:" + donation.name)
                created = {{"donor": donor.name, "donation": donation.name, "txn": txn.name}}
                frappe.db.commit()
                frappe.destroy()

                import frappe.app
                from frappe.database.database import Database
                from werkzeug.test import Client
                client = Client(frappe.app.application, use_cookies=False)
                headers = {{"X-Frappe-Site-Name": SITE}}

                def error_logs():
                    frappe.init(site=SITE); frappe.connect()
                    n = frappe.db.count("Error Log"); frappe.destroy(); return n

                paynl = MagicMock()
                paynl.get_order.return_value = {{"status": {{"code": 100, "action": "PAID"}}, "payments": []}}
                real_sql = Database.sql
                counter = {{"n": 0}}
                def counting_sql(self, *a, **kw):
                    counter["n"] += 1
                    return real_sql(self, *a, **kw)

                cases = (
                    ("good", "/payment_success?orderId=" + order_id + "&token=" + good),
                    ("unknown", "/payment_success?orderId=EX-nope-" + uuid.uuid4().hex[:6] + "&token=" + good),
                    ("bad", "/payment_success?orderId=" + order_id + "&token=" + "0" * 64),
                    ("none", "/payment_success?orderId=" + order_id),
                )
                out = {{}}
                for key, target in cases:
                    before_logs = error_logs()
                    paynl.get_order.reset_mock()
                    counter["n"] = 0
                    with patch("verenigingen.verenigingen_payments.ing_checkout.api.payment.get_client", return_value=paynl), \\
                         patch.object(Database, "sql", counting_sql):
                        r = client.get(target, headers=headers)
                    out[key] = {{
                        "status": r.status_code,
                        "body": r.get_data(as_text=True),
                        "server_messages": "_server_messages" in r.get_data(as_text=True) or r.headers.get("X-Frappe-Message-Log"),
                        "error_logs": error_logs() - before_logs,
                        "pay_nl_calls": paynl.get_order.call_count,
                        "queries": counter["n"],
                    }}
                print("RESULT" + json.dumps(out))
            finally:
                frappe.init(site=SITE)
                frappe.connect()
                for dt, key in (("ING Checkout Transaction", "txn"), ("Donation", "donation"), ("Donor", "donor")):
                    if created.get(key):
                        frappe.delete_doc(dt, created[key], force=True)
                frappe.db.commit()
                left = [(dt, frappe.db.exists(dt, created[key])) for dt, key in
                        (("ING Checkout Transaction", "txn"), ("Donation", "donation"), ("Donor", "donor")) if created.get(key)]
                left += [("Customer", frappe.db.count("Customer", {{"customer_name": ["like", "Ing Return Probe%"]}}))]
                print("LEFTOVER" + json.dumps([x for x in left if x[1]]))
                frappe.destroy()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        out = json.loads(next(x for x in lines if x.startswith("RESULT"))[len("RESULT") :])
        leftover = next(x for x in lines if x.startswith("LEFTOVER"))
        # The subprocess commits its fixtures: nothing it created (Donor, Donation, Transaction, Customer) may remain.
        self.assertEqual(leftover, "LEFTOVER[]")

        # Valid token: the Guest sees the real status, fetched once from the (stubbed) Pay.nl client.
        self.assertEqual(out["good"]["status"], 200)
        self.assertIn("Payment completed successfully", out["good"]["body"])
        self.assertEqual(out["good"]["pay_nl_calls"], 1)
        self.assertEqual(out["good"]["error_logs"], 0)

        # Every refusal: same status and body, no Pay.nl call, no Error Log row, same query count.
        refused = [out[k] for k in ("unknown", "bad", "none")]
        for label, case in zip(("unknown", "bad", "none"), refused):
            with self.subTest(case=label):
                self.assertEqual(case["status"], 200)
                self.assertIn("Invalid payment reference or document not found", case["body"])
                self.assertNotIn("Payment completed successfully", case["body"])
                self.assertEqual(case["pay_nl_calls"], 0)
                self.assertEqual(case["error_logs"], 0)
                self.assertFalse(case["server_messages"])
        self.assertEqual(len({c["status"] for c in refused}), 1)
        self.assertEqual(len({c["queries"] for c in refused}), 1, [c["queries"] for c in refused])
        # The only per-request byte is the brand-css cache-buster timestamp.
        import re

        bodies = {re.sub(r"\?v=[0-9: .-]+", "?v=X", c["body"]) for c in refused}
        self.assertEqual(len(bodies), 1, "refused bodies differ")
