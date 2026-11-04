"""The URL Mollie and ING Checkout are GIVEN as the payer's return page (#1996).

Maintainer ruling 2026-11-03: until frappe/payments#192 (#1878) Mollie and ING Checkout
returns point at THIS app's ``/payment_success`` (underscore), not the payments app's
``/payment-success`` (hyphen). The hyphen page says "successfully accepted" for any outcome
and never consults our token or status checks; for ING it is a 500.

Gateway HTTP clients are stubbed at the client boundary (``client.payments.create``,
``get_client``), so these tests behave the same with and without gateway credentials.
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
from frappe.utils import get_bench_path, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.gateway_stub import stub_redirect_gateway
from verenigingen.tests.support.ing_return import create_ing_order
from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token
from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import get_mollie_settings
from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

_GATEWAY_FACTORY_PATH = (
    "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway"
)


class ReturnUrlCase(EnhancedTestCase):
    def _settings_with_redirect_override(self, redirect_url=None):
        """The real Mollie Settings doc, with the override set in memory only (never saved)."""
        settings = get_mollie_settings()
        settings.redirect_url = redirect_url
        return settings

    def _url_parts(self, url):
        parts = urlsplit(url)
        return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}


class TestMollieReturnUrl(ReturnUrlCase):
    def test_default_return_url_is_the_underscore_page_with_a_valid_token(self):
        settings = self._settings_with_redirect_override()
        path, query = self._url_parts(settings.get_redirect_url("Sales Invoice", "SINV-X-1"))
        self.assertEqual(path, "/payment_success")
        self.assertEqual((query["doctype"], query["docname"]), ("Sales Invoice", "SINV-X-1"))
        self.assertTrue(
            verify_guest_return_token("payment_success", "Sales Invoice:SINV-X-1", query["token"])
        )

    def test_a_stored_redirect_url_override_still_wins(self):
        settings = self._settings_with_redirect_override("https://example.org/custom-return")
        self.assertEqual(
            settings.get_redirect_url("Sales Invoice", "SINV-X-1"), "https://example.org/custom-return"
        )

    def test_the_url_the_gateway_hands_mollie_is_the_underscore_page(self):
        """MollieGateway.process_payment is the producer for PaymentHook, payment plans and checkout."""
        gateway = MollieGateway.__new__(MollieGateway)
        gateway.settings = self._settings_with_redirect_override()
        gateway.client = MagicMock()
        gateway.client.payments.create.return_value = SimpleNamespace(
            id="tr_stub",
            checkout_url="https://pay.mollie.test/x",
            status="open",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        doc = SimpleNamespace(
            doctype="Sales Invoice", name="SINV-X-2", amount=12.5, currency="EUR", contact_email=""
        )
        with self.assertNoErrorLog():
            result = gateway.process_payment(doc, {})

        self.assertEqual(result["status"], "redirect_required")
        sent = gateway.client.payments.create.call_args[0][0]["redirectUrl"]
        path, query = self._url_parts(sent)
        self.assertEqual(path, "/payment_success")
        self.assertEqual(query["docname"], "SINV-X-2")


class TestIngReturnUrl(ReturnUrlCase):
    def test_default_return_url_is_the_underscore_page(self):
        path, _query = self._url_parts(create_ing_order(self)[1])
        self.assertEqual(path, "/payment_success")

    def test_a_stored_default_return_url_override_still_wins(self):
        _name, url = create_ing_order(self, "https://example.org/ing-back")
        self.assertEqual(url, "https://example.org/ing-back")


class TestCheckoutScriptReturnUrl(ReturnUrlCase):
    # The checkout script's own redirect is covered behaviourally by
    # tests/unit/mollie-checkout-return-url.test.js (jest), which runs the real script.

    def _make_unpaid_mollie_donation(self, donor_email):
        donor = self.create_test_donor(donor_email=donor_email)
        return frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": today(),
                "amount": 20.0,
                "mode_of_payment": "Mollie",
                "status": "One-time",
                "donation_purpose_type": "General",
                "paid": 0,
            }
        ).insert(ignore_permissions=True)

    def _checkout_payload_json(self, payer_email):
        return json.dumps(
            {"amount": 20.0, "title": "D", "description": "D", "payer_name": "S", "payer_email": payer_email,
             "order_id": "ORD-1", "currency": "EUR"}
        )

    def test_make_payment_returns_a_token_the_underscore_page_accepts(self):
        """A Sales Invoice carries no payment_id field, so payment_id alone is always refused there."""
        from verenigingen.verenigingen_payments.templates.pages.mollie_checkout import make_payment

        donor_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_unpaid_mollie_donation(donor_email)
        with self.as_user("Guest"), patch(_GATEWAY_FACTORY_PATH, return_value=stub_redirect_gateway()):
            result = make_payment(
                data=self._checkout_payload_json(donor_email),
                reference_doctype="Donation",
                reference_docname=donation.name,
            )

        self.assertEqual(result["status"], "Open")
        self.assertTrue(
            verify_guest_return_token("payment_success", f"Donation:{donation.name}", result.get("returnToken"))
        )

    def test_make_payment_mints_no_token_for_a_wrong_email_on_a_real_document(self):
        """Control: the document exists, only the payer's email is wrong, so there must be no token."""
        from verenigingen.verenigingen_payments.templates.pages.mollie_checkout import make_payment

        self.expectErrorLog("Mollie Payment Error")
        owner_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_unpaid_mollie_donation(owner_email)
        data = self._checkout_payload_json(f"stranger-{frappe.generate_hash()[:8]}@example.com")
        with self.as_user("Guest"), patch(_GATEWAY_FACTORY_PATH, return_value=stub_redirect_gateway()):
            result = make_payment(data=data, reference_doctype="Donation", reference_docname=donation.name)

        self.assertEqual(result["status"], "Error")
        self.assertNotIn("returnToken", result)

    def test_the_token_is_minted_for_the_verified_document_name(self):
        """A case-variant docname resolves to the real document; the token must name the real one."""
        from verenigingen.verenigingen_payments.templates.pages.mollie_checkout import make_payment

        owner_email = f"owner-{frappe.generate_hash()[:8]}@example.com"
        donation = self._make_unpaid_mollie_donation(owner_email)
        with self.as_user("Guest"), patch(_GATEWAY_FACTORY_PATH, return_value=stub_redirect_gateway()):
            result = make_payment(
                data=self._checkout_payload_json(owner_email),
                reference_doctype="Donation",
                reference_docname=donation.name.lower(),
            )
        self.assertFalse(
            verify_guest_return_token(
                "payment_success", f"Donation:{donation.name.lower()}", result.get("returnToken")
            )
        )
        self.assertTrue(
            verify_guest_return_token("payment_success", f"Donation:{donation.name}", result.get("returnToken"))
        )



class TestReturnUrlOverWsgi(ReturnUrlCase):
    """The URL the gateway is given, followed by a Guest through the real WSGI app."""

    def test_guest_following_the_mollie_return_url_reaches_our_page(self):
        script = textwrap.dedent(
            f"""
            import json, uuid
            import frappe
            from urllib.parse import urlsplit

            SITE = {frappe.local.site!r}
            frappe.init(site=SITE)
            frappe.connect()
            donor = donation = None
            try:
                customers_before = frappe.db.count("Customer", {{"customer_name": ["like", "Return Probe%"]}})
                donor = frappe.get_doc({{"doctype": "Donor", "donor_name": "Return Probe", "donor_type": "Individual",
                    "donor_email": "ret." + uuid.uuid4().hex[:8] + "@example.com", "currency": "EUR"}})
                # Donor.insert would otherwise create a committed Customer and Contact this script never deletes.
                donor.flags.ignore_customer_sync = True
                donor.insert()
                donation = frappe.get_doc({{"doctype": "Donation", "donor": donor.name, "donation_date": frappe.utils.today(),
                    "amount": 10.0, "mode_of_payment": "Mollie", "status": "One-time", "donation_purpose_type": "General", "paid": 0}}).insert()
                from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import get_mollie_settings
                settings = get_mollie_settings()
                settings.redirect_url = None
                given = settings.get_redirect_url("Donation", donation.name)
                parts = urlsplit(given)
                good = parts.path + "?" + parts.query
                bad = parts.path + "?doctype=Donation&docname=" + donation.name + "&token=" + "0" * 64
                frappe.db.commit()
                frappe.destroy()

                import frappe.app
                from werkzeug.test import Client
                client = Client(frappe.app.application, use_cookies=False)
                headers = {{"X-Frappe-Site-Name": SITE}}
                out = {{"given_path": parts.path}}
                for key, target in (("good", good), ("bad", bad)):
                    r = client.get(target, headers=headers)
                    out[key] = {{"status": r.status_code, "body": r.get_data(as_text=True)}}
                print("RESULT" + json.dumps(out))
            finally:
                frappe.init(site=SITE)
                frappe.connect()
                if donation:
                    frappe.delete_doc("Donation", donation.name, force=True)
                if donor:
                    frappe.delete_doc("Donor", donor.name, force=True)
                frappe.db.commit()
                print("LEFTOVER" + str(frappe.db.count("Customer", {{"customer_name": ["like", "Return Probe%"]}}) - customers_before))
                frappe.destroy()
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        out = json.loads(next(x for x in result.stdout.splitlines() if x.startswith("RESULT"))[len("RESULT"):])
        leftover = next(x for x in result.stdout.splitlines() if x.startswith("LEFTOVER"))
        # The subprocess commits its fixtures, so nothing the test drain can claim may remain.
        self.assertEqual(leftover, "LEFTOVER0")

        self.assertEqual(out["given_path"], "/payment_success")
        # Not the payments app's unconditional banner, and a real status for the proven return.
        self.assertEqual(out["good"]["status"], 200)
        self.assertNotIn("successfully accepted", out["good"]["body"])
        self.assertIn("Payment Processing", out["good"]["body"])
        # Control: a bad token must be REFUSED by our page (the hyphen page would accept it).
        self.assertEqual(out["bad"]["status"], 200)
        self.assertIn("Invalid payment reference", out["bad"]["body"])
        self.assertNotIn("successfully accepted", out["bad"]["body"])
