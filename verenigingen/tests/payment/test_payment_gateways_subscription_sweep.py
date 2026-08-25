"""
Subscription-activation coverage sweep for payment_gateways.py.

Targets the uncovered SUBSCRIPTION region of
verenigingen/verenigingen_payments/utils/payment_gateways.py that the existing
trio (test_payment_gateways.py / _unit.py / _coverage.py) does NOT reach:

    - _authenticate_and_parse_subscription_payload: webhook signature
      authentication (valid accepted / tampered + replayed-payload rejected /
      missing-signature unsigned-webhook design path / test-mode bypass), plus
      JSON, form-encoded, truncated/invalid-JSON, ping, no-subscription-id and
      already-processed (idempotency) parse branches.
    - mollie_subscription_webhook: full request-entry orchestration - auth
      failure short-circuit, ping, no-member ignored, and the success path that
      creates a real Payment Entry against a real Sales Invoice and updates the
      member subscription status.
    - retry_failed_subscription_activations: the per-payment loop body
      (already-active skip, non-first-sequence skip, successful activation, and
      failed-activation accounting) - the existing suite only covered the empty
      summary.

SECURITY: the authentication tests assert that a VALID signature is accepted
and a TAMPERED / wrong-payload signature is REJECTED. They are deliberately not
signature-agnostic - a build that accepted any signature would fail here.

Only the external boundaries are stubbed (the live Mollie SDK client/settings
and the HTTP request context); the authentication, parsing, Payment Entry
creation and retry-orchestration logic all run for real.

Named to live in tests/payment/ alongside the existing gateway suites; the
permission-bypass inserts live in _make_*-prefixed helpers / setUp so the
test-quality enforcer recognises them as setup patterns.
"""

import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_payment_gateways_unit import _StubAmount, _StubPayment
from verenigingen.tests.support.invoice_payments import member_with_customer, receive_against_invoice
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import MollieSettings
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    install_fake_request,
    sign_payload,
)
from verenigingen.verenigingen_payments.utils import payment_gateways as pg

WEBHOOK_SECRET = "whsec_subscription_sweep_secret_key"


@contextmanager
def _mollie_auth_config(*, test_mode, webhook_secret=WEBHOOK_SECRET):
    """Configure Mollie Settings for webhook authentication WITHOUT saving the doc.

    The shared mollie_settings_override fixture calls settings.save(), which on
    this environment re-validates Mollie Settings account-link fields (Mollie
    Bank Account / Payment Processing Fees Account) that may not exist here and
    raises LinkValidationError. We only need two values for the signature path:
      - test_mode (read as settings.test_mode) -> toggled via set_single_value,
        which writes tabSingles directly and bypasses doc-link validation;
      - the webhook secret (read via settings.get_webhook_secret()) -> patched at
        that retrieval seam (the config boundary), so the REAL HMAC verification
        in verify_mollie_webhook_signature still runs against it.
    """
    prev_test_mode = frappe.db.get_single_value("Mollie Settings", "test_mode")
    frappe.db.set_single_value("Mollie Settings", "test_mode", 1 if test_mode else 0)
    frappe.clear_document_cache("Mollie Settings", "Mollie Settings")
    # On a production-like CI site (no developer_mode), _validate_test_mode_safety()
    # rejects test_mode as a security risk BEFORE any signature logic and logs a
    # CRITICAL error -- that error path commits while test_mode=1, which survives the
    # per-test rollback and poisons every later Mollie test in the shard. The
    # production code offers an explicit staging override (allow_mollie_test_mode);
    # set it (like test_webhook_security_live.py) so the genuine auth path is reached
    # on every site and no error is committed. frappe.conf is process-global and not
    # transaction-scoped, so it is restored in the finally below.
    prev_allow_test_mode = frappe.conf.get("allow_mollie_test_mode")
    if test_mode:
        frappe.conf["allow_mollie_test_mode"] = True
    with patch.object(MollieSettings, "get_webhook_secret", return_value=webhook_secret):
        try:
            yield
        finally:
            frappe.db.set_single_value("Mollie Settings", "test_mode", prev_test_mode)
            frappe.clear_document_cache("Mollie Settings", "Mollie Settings")
            if prev_allow_test_mode is None:
                frappe.conf.pop("allow_mollie_test_mode", None)
            else:
                frappe.conf["allow_mollie_test_mode"] = prev_allow_test_mode


# ---------------------------------------------------------------------------
# Boundary stubs: minimal stand-ins for the Mollie SDK surface the gateway
# touches. These model the external HTTP/SDK boundary only - the gateway and
# helper functions they feed run for real.
# ---------------------------------------------------------------------------
class _StubPayments:
    def __init__(self, payment):
        self._payment = payment

    def get(self, payment_id):
        return self._payment


class _StubClient:
    def __init__(self, payment=None):
        self.payments = _StubPayments(payment)


class _StubSettings:
    """Stand-in for the Mollie Settings surface the gateway touches."""

    def __init__(self, subscription=None, enable_subscriptions=True):
        self._subscription = subscription
        self.enable_subscriptions = enable_subscriptions

    def get_subscription(self, customer_id, subscription_id):
        return self._subscription

    def get_subscription_webhook_url(self):
        return "https://app.test/sub-webhook"


def _make_gateway(payment=None, subscription=None):
    """Build a MollieGateway without __init__ (which needs live settings/API).

    Bypassing __init__ + injecting a stubbed client/settings is the SDK boundary.
    """
    gw = pg.MollieGateway.__new__(pg.MollieGateway)
    gw.gateway_name = "Default"
    gw.client = _StubClient(payment)
    gw.settings = _StubSettings(subscription)
    return gw


def _json_event(payment_id=None, subscription_id=None, event_type="payment.paid"):
    """Build a modern Mollie JSON webhook-event body."""
    body = {"resource": "event", "type": event_type}
    if payment_id:
        body["entityId"] = payment_id
        if subscription_id:
            body["_embedded"] = {"entity": {"subscriptionId": subscription_id}}
    elif subscription_id:
        body["entityId"] = subscription_id
        body["type"] = "subscription.updated"
    return json.dumps(body)


# ===========================================================================
# _authenticate_and_parse_subscription_payload - signature security + parsing
# ===========================================================================
class TestSubscriptionWebhookAuthentication(EnhancedTestCase):
    """SECURITY: signature accept/reject + payload parsing branches.

    Runs in LIVE mode (test_mode=0) with a configured webhook secret so a
    present signature is genuinely HMAC-verified (test mode would bypass it).
    """

    def _auth(self, body, *, signature, test_mode=False):
        with _mollie_auth_config(test_mode=test_mode):
            with install_fake_request(body, signature=signature):
                return pg._authenticate_and_parse_subscription_payload()

    def test_valid_signature_is_accepted(self):
        # A correctly-signed subscription event authenticates and parses.
        body = _json_event(payment_id="tr_validsig", subscription_id="sub_validsig")
        parsed, error = self._auth(body, signature=sign_payload(body, WEBHOOK_SECRET))
        self.assertIsNone(error, "valid signature must be accepted")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["subscription_id"], "sub_validsig")
        self.assertEqual(parsed["payment_id"], "tr_validsig")

    def test_tampered_signature_is_rejected(self):
        # SECURITY: a signature computed under the WRONG secret must be rejected.
        self.expectErrorLog("Webhook Security Alert")
        self.expectErrorLog("Mollie Security - CRITICAL")
        body = _json_event(payment_id="tr_tamper", subscription_id="sub_tamper")
        bad_signature = sign_payload(body, "attacker_guessed_secret")
        parsed, error = self._auth(body, signature=bad_signature)
        self.assertIsNone(parsed, "tampered signature must NOT yield a parsed payload")
        self.assertIsNotNone(error)
        self.assertEqual(error.get("status"), "error")

    def test_signature_for_different_payload_is_rejected(self):
        # SECURITY: a valid signature for a DIFFERENT body (replay/tamper of the
        # body after signing) must be rejected - proves verification is bound to
        # the exact payload bytes.
        self.expectErrorLog("Webhook Security Alert")
        self.expectErrorLog("Mollie Security - CRITICAL")
        signed_body = _json_event(payment_id="tr_orig", subscription_id="sub_orig")
        sent_body = _json_event(payment_id="tr_swapped", subscription_id="sub_swapped")
        signature = sign_payload(signed_body, WEBHOOK_SECRET)
        parsed, error = self._auth(sent_body, signature=signature)
        self.assertIsNone(parsed)
        self.assertIsNotNone(error)
        self.assertEqual(error.get("status"), "error")

    def test_missing_signature_accepted_as_unsigned_webhook(self):
        # DESIGN (not a bug): standard Mollie Payments-API webhooks are UNSIGNED;
        # authenticity is re-established by re-fetching state from Mollie by id.
        # An unsigned webhook in live mode is therefore accepted.
        body = _json_event(payment_id="tr_unsigned", subscription_id="sub_unsigned")
        parsed, error = self._auth(body, signature=None)
        self.assertIsNone(error)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["subscription_id"], "sub_unsigned")

    def test_test_mode_without_signature_accepted(self):
        # Mollie test-mode webhooks carry no signature; accepted under test_mode.
        body = _json_event(subscription_id="sub_testmode")
        parsed, error = self._auth(body, signature=None, test_mode=True)
        self.assertIsNone(error)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["subscription_id"], "sub_testmode")

    def test_ping_event_returns_success_without_processing(self):
        body = json.dumps({"resource": "event", "type": "hook.ping"})
        parsed, error = self._auth(body, signature=sign_payload(body, WEBHOOK_SECRET))
        self.assertIsNone(parsed)
        self.assertEqual(error["status"], "success")
        self.assertIn("ping", error["message"].lower())

    def test_form_encoded_payload_is_parsed(self):
        # Legacy form-encoded body (id=sub_xxx) - not JSON - is still parsed.
        body = "id=sub_formenc"
        parsed, error = self._auth(body, signature=sign_payload(body, WEBHOOK_SECRET))
        self.assertIsNone(error)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["subscription_id"], "sub_formenc")

    def test_invalid_json_payload_rejected(self):
        self.expectErrorLog("Mollie Subscription Webhook JSON Error")
        body = "this is neither json nor formencoded"
        parsed, error = self._auth(body, signature=sign_payload(body, WEBHOOK_SECRET))
        self.assertIsNone(parsed)
        self.assertIn("Invalid JSON", error["message"])

    def test_truncated_json_payload_rejected(self):
        self.expectErrorLog("Mollie Subscription Webhook JSON Error")
        body = '{"resource": "event", "type": "payment.paid", "entityId": "tr_'
        parsed, error = self._auth(body, signature=sign_payload(body, WEBHOOK_SECRET))
        self.assertIsNone(parsed)
        self.assertIn("Invalid JSON", error["message"])

    def test_no_subscription_id_is_ignored(self):
        # An unsupported id-prefix yields no subscription id -> ignored.
        body = json.dumps({"id": "xx_unknownprefix"})
        parsed, error = self._auth(body, signature=sign_payload(body, WEBHOOK_SECRET))
        self.assertIsNone(parsed)
        self.assertEqual(error["status"], "ignored")
        self.assertIn("subscription ID", error["reason"])

    def test_empty_payload_is_authentication_failure(self):
        # An empty body fails authentication ("Empty webhook payload").
        self.expectErrorLog("Webhook Security Alert")
        parsed, error = self._auth("", signature=None)
        self.assertIsNone(parsed)
        self.assertEqual(error.get("status"), "error")


# ===========================================================================
# mollie_subscription_webhook - full request-entry orchestration
# ===========================================================================
class TestSubscriptionWebhookEntry(EnhancedTestCase):
    """Drive the whitelisted entry point end-to-end against real documents.

    _process_subscription_payment owns a real begin()/commit() transaction, so
    the Payment Entry it creates survives FrappeTestCase rollback; we force-clean
    those committed PEs in tearDown to avoid order-dependence.
    """

    def setUp(self):
        super().setUp()
        self._committed_pes = []

    def tearDown(self):
        # Newest first: a later PE allocated against the same invoice must come
        # off before the earlier one.
        for pe_name in reversed(self._committed_pes):
            if frappe.db.exists("Payment Entry", pe_name):
                doc = frappe.get_doc("Payment Entry", pe_name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Payment Entry", pe_name, force=True, ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    def _make_member_with_customer(self, first_name, subscription_id=None, customer_id=None):
        member = self.create_test_member(first_name=first_name)
        member.reload()
        if not member.customer:
            member.create_customer()
            member.reload()
        tags = {}
        if subscription_id:
            tags["custom_mollie_subscription_id"] = subscription_id
        if customer_id:
            tags["custom_mollie_customer_id"] = customer_id
        if tags:
            frappe.db.set_value("Customer", member.customer, tags)
        return member

    def test_auth_failure_short_circuits(self):
        # A tampered signature makes the entry point return the auth-failure
        # error response without touching any member/payment processing.
        self.expectErrorLog("Webhook Security Alert")
        self.expectErrorLog("Mollie Security - CRITICAL")
        body = _json_event(payment_id="tr_authfail", subscription_id="sub_authfail")
        with _mollie_auth_config(test_mode=False):
            with install_fake_request(body, signature=sign_payload(body, "wrong_secret")):
                result = pg.mollie_subscription_webhook()
        self.assertEqual(result.get("status"), "error")

    def test_ping_event_acknowledged(self):
        body = json.dumps({"resource": "event", "type": "hook.ping"})
        with _mollie_auth_config(test_mode=False):
            with install_fake_request(body, signature=sign_payload(body, WEBHOOK_SECRET)):
                result = pg.mollie_subscription_webhook()
        self.assertEqual(result["status"], "success")

    def test_no_member_for_subscription_ignored(self):
        self.expectErrorLog("Mollie Subscription Webhook")  # "No customer found"
        body = _json_event(subscription_id="sub_no_member_anywhere")
        with _mollie_auth_config(test_mode=False):
            with install_fake_request(body, signature=sign_payload(body, WEBHOOK_SECRET)):
                result = pg.mollie_subscription_webhook()
        self.assertEqual(result["status"], "ignored")
        self.assertIn("No member found", result["reason"])

    def test_success_creates_payment_entry_and_updates_status(self):
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        # Submitting the PE fires a payment-notification hook that reads
        # frappe.request.host; the FakeWebhookRequest has no host, so the
        # notification swallows-and-logs. That is a test-harness artifact (no real
        # HTTP request in a unit test), unrelated to the payment processing under
        # test - mark it expected so the error-log audit stays green.
        self.expectErrorLog("Payment Notification Error")

        # _process_subscription_payment derives the Payment Entry company from the
        # user-default Company and looks up that company's receivable/bank
        # accounts. Pin both the invoice and that lookup to the EUR test company
        # (which has a complete, valid Chart of Accounts) so the PE and the
        # invoice's debit_to belong to the same, correctly-seeded company.
        company = get_eur_test_company()
        member = self._make_member_with_customer(
            "WebhookE2E", subscription_id="sub_e2e", customer_id="cst_e2e"
        )
        invoice = self.create_test_sales_invoice(customer=member.name, grand_total=10.0, company=company)
        # Flush setup writes before _process_subscription_payment calls begin().
        frappe.db.commit()

        ref_no = f"tr_e2e_{frappe.generate_hash(length=8)}"
        payment = _StubPayment(
            id=ref_no,
            paid=True,
            amount=_StubAmount(value=str(invoice.grand_total)),
            sequence_type="recurring",  # not "first" -> no activation branch
        )
        gw = _make_gateway(
            payment=payment,
            subscription={"id": "sub_e2e", "status": "active", "next_payment_date": "2026-09-01"},
        )

        body = _json_event(payment_id=ref_no, subscription_id="sub_e2e")

        # Pin the user-default Company that _process_subscription_payment reads to
        # the EUR test company (config seam, not the logic under test) so the PE
        # is created under the same company as the invoice.
        orig_get_user_default = frappe.defaults.get_user_default

        def _company_default(key):
            return company if key == "Company" else orig_get_user_default(key)

        # Mock justified: PaymentGatewayFactory builds a real MollieGateway that
        # needs live settings/API; replace only the gateway construction (the SDK
        # boundary). All webhook orchestration + PE creation runs for real.
        with _mollie_auth_config(test_mode=False):
            # Flush the test_mode write _mollie_auth_config just made: otherwise
            # the uncommitted single-value write makes _process_subscription_payment's
            # frappe.db.begin() trip the implicit-commit guard.
            frappe.db.commit()
            with install_fake_request(body, signature=sign_payload(body, WEBHOOK_SECRET)):
                with patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=gw):
                    with patch.object(frappe.defaults, "get_user_default", side_effect=_company_default):
                        result = pg.mollie_subscription_webhook()

        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["member"], member.name)
        self.assertIn("payment_processed", result["actions"])
        self.assertIn("status_updated", result["actions"])

        payment_result = result["payment_processed"]
        self.assertEqual(payment_result["status"], "success")
        pe_name = payment_result["payment_entry"]
        self._committed_pes.append(pe_name)
        self.assertTrue(frappe.db.exists("Payment Entry", pe_name))

        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.reference_no, ref_no)
        self.assertEqual(pe.party, member.customer)
        self.assertEqual(pe.references[0].reference_name, invoice.name)
        self.assertAlmostEqual(float(pe.paid_amount), float(invoice.grand_total), places=2)

        # _update_subscription_status wrote the live status onto the member.
        self.assertEqual(frappe.db.get_value("Member", member.name, "subscription_status"), "active")

        # Idempotency: a second webhook for the same payment id is recognised as
        # already-processed during auth/parse (the committed PE is found).
        with _mollie_auth_config(test_mode=False):
            with install_fake_request(body, signature=sign_payload(body, WEBHOOK_SECRET)):
                parsed, error = pg._authenticate_and_parse_subscription_payload()
        self.assertIsNone(parsed)
        self.assertEqual(error["status"], "already_processed")
        self.assertEqual(error["payment_id"], ref_no)


# ===========================================================================
# retry_failed_subscription_activations - per-payment loop body
# ===========================================================================
class TestRetryFailedActivationsLoop(EnhancedTestCase):
    """Exercise the retry loop body with seeded recent-payment rows.

    The Payment Entry query is replaced with deterministic rows (the established
    pattern in the existing coverage suite); every other step - member lookup,
    sequence/paid checks, activation - runs for real against real documents.
    """

    def _make_member_with_customer(self, first_name):
        member = self.create_test_member(first_name=first_name)
        member.reload()
        if not member.customer:
            member.create_customer()
            member.reload()
        return member

    def _run_retry(self, member_customer, payment, *, complete_payment_service=None):
        gw = _make_gateway(payment=payment)
        rows = [
            {
                "party": member_customer,
                "reference_no": "tr_retry_ref",
                "posting_date": frappe.utils.today(),
            }
        ]
        orig_get_all = frappe.get_all

        def fake_get_all(doctype, *a, **k):
            if doctype == "Payment Entry":
                return rows
            return orig_get_all(doctype, *a, **k)

        cm = patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=gw)
        with cm, patch.object(frappe, "get_all", side_effect=fake_get_all):
            if complete_payment_service is not None:
                with patch.object(pg, "CompletePaymentService") as svc:
                    svc.return_value.create_customer_subscription.return_value = complete_payment_service
                    return pg.retry_failed_subscription_activations()
            return pg.retry_failed_subscription_activations()

    def test_first_payment_activates_subscription_on_retry(self):
        member = self._make_member_with_customer("RetryOk")
        self.create_test_membership(member_name=member.name)
        self.create_test_dues_schedule(member.name, amount=15.0, frequency="monthly")

        payment = _StubPayment(id="tr_retry_ref", paid=True, sequence_type="first")
        fake_sub = {
            "customer_id": "cst_retry",
            "subscription_id": "sub_retry_ok",
            "subscription_status": "active",
            "next_payment_date": "2026-07-01",
        }
        result = self._run_retry(member.customer, payment, complete_payment_service=fake_sub)

        self.assertEqual(result["total_payments_checked"], 1)
        self.assertEqual(result["members_without_subscriptions"], 1)
        self.assertEqual(result["retry_attempts"], 1)
        self.assertEqual(result["successful_activations"], 1)
        self.assertEqual(result["failed_retries"], 0)
        self.assertEqual(result["details"][0]["result"], "success")
        self.assertEqual(result["details"][0]["subscription_id"], "sub_retry_ok")

    def test_non_first_sequence_is_skipped(self):
        member = self._make_member_with_customer("RetryRecurring")
        payment = _StubPayment(id="tr_retry_ref", paid=True, sequence_type="recurring")
        result = self._run_retry(member.customer, payment)

        self.assertEqual(result["members_without_subscriptions"], 1)
        self.assertEqual(result["retry_attempts"], 0)
        self.assertEqual(result["successful_activations"], 0)

    def test_already_active_member_is_skipped_before_retry(self):
        member = self._make_member_with_customer("RetryActive")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_subscription_id": "sub_existing", "subscription_status": "Active"},
        )
        payment = _StubPayment(id="tr_retry_ref", paid=True, sequence_type="first")
        result = self._run_retry(member.customer, payment)

        # Active members are skipped before the without-subscription counter.
        self.assertEqual(result["members_without_subscriptions"], 0)
        self.assertEqual(result["retry_attempts"], 0)

    def test_first_payment_without_dues_schedule_counts_as_failed(self):
        # First + paid -> a retry is attempted, but with no active dues schedule
        # the activation returns "skipped" and is accounted as a failed retry.
        member = self._make_member_with_customer("RetryNoSchedule")
        payment = _StubPayment(id="tr_retry_ref", paid=True, sequence_type="first")
        result = self._run_retry(member.customer, payment)

        self.assertEqual(result["retry_attempts"], 1)
        self.assertEqual(result["successful_activations"], 0)
        self.assertEqual(result["failed_retries"], 1)
        self.assertEqual(result["details"][0]["result"], "failed")

# ===========================================================================
# _process_subscription_payment - which invoice a subscription payment pays (#567)
# ===========================================================================
class TestSubscriptionPaymentInvoiceChoice(EnhancedTestCase):
    """A subscription payment must not be posted against an arbitrary invoice.

    This function took the member's unpaid invoices `order_by="posting_date desc",
    limit=1`, so a member with two open invoices got the more recent one whatever
    the payment was for. It then COMPUTED `abs(payment - invoice) > 0.01`, announced
    the mismatch through a bare `frappe.logger().warning` -- dropped on level and
    written only to a rotating file, so it reached no log anyone reads (CLAUDE.md
    records this as having caused three separate defects) -- and continued anyway.

    It is on the live Mollie subscription webhook path, so it runs unattended.

    `_process_subscription_payment` owns a real begin()/commit(), so any Payment
    Entry it creates survives FrappeTestCase rollback; committed PEs are force-
    cleaned in tearDown to keep this class out of the next one's way.
    """

    def setUp(self):
        super().setUp()
        self.company = get_eur_test_company()
        self._committed_pes = []

    def tearDown(self):
        # Newest first: a later PE allocated against the same invoice must come
        # off before the earlier one.
        for pe_name in reversed(self._committed_pes):
            if frappe.db.exists("Payment Entry", pe_name):
                doc = frappe.get_doc("Payment Entry", pe_name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Payment Entry", pe_name, force=True, ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    def _open_invoice(self, member, grand_total, **kwargs):
        return self.create_test_sales_invoice(
            customer=member.name, grand_total=grand_total, company=self.company, **kwargs
        )

    def _process_subscription(self, member, amount):
        """Drive the real function with only the Mollie SDK stubbed."""
        ref_no = f"tr_choice_{frappe.generate_hash(length=8)}"
        payment = _StubPayment(
            id=ref_no,
            paid=True,
            amount=_StubAmount(value=str(amount)),
            sequence_type="recurring",  # not "first" -> no activation branch
        )
        gateway = _make_gateway(payment=payment)
        # Flush setup writes: the function calls frappe.db.begin(), which trips the
        # implicit-commit guard if uncommitted work is pending.
        frappe.db.commit()
        result = pg._process_subscription_payment(
            gateway, member.name, member.customer, ref_no, "sub_invoice_choice"
        )
        pe_name = (result or {}).get("payment_entry")
        if pe_name:
            self._committed_pes.append(pe_name)
        return result, ref_no

    def _payment_entries_for(self, ref_no):
        return frappe.get_all("Payment Entry", filters={"reference_no": ref_no}, fields=["name"])

    def test_two_open_invoices_and_nothing_to_choose_on_is_refused(self):
        """Two open invoices is not a match, it is a choice -- and money moves here.

        Red against develop: a Payment Entry was created against the 90.00 invoice
        purely because it was posted later, for a payment of 17.50 that said nothing
        about which invoice it belonged to.
        """
        # The refusal is stated as an Error Log row on purpose -- that is the part
        # #567 asked for, since the old warning reached no log anyone reads.
        self.expectErrorLog("Mollie Subscription Payment Ambiguous")
        member = member_with_customer(self, "SubAmbig")
        first = self._open_invoice(member, 25.0)
        second = self._open_invoice(member, 90.0)
        self.assertNotEqual(first.name, second.name)

        result, ref_no = self._process_subscription(member, 17.50)

        self.assertNotEqual(
            (result or {}).get("status"), "success", msg=f"must not auto-post: {result}"
        )
        self.assertFalse(
            self._payment_entries_for(ref_no),
            "no Payment Entry may be created when the invoice is a choice, not a match",
        )
        # Both invoices must be untouched.
        for invoice in (first, second):
            invoice.reload()
            self.assertEqual(float(invoice.outstanding_amount), float(invoice.grand_total))

    def test_the_invoice_matching_the_payment_is_chosen(self):
        """The discriminator was available all along and this site ignored it.

        The matching invoice is deliberately given the EARLIER posting_date, so
        `posting_date desc limit 1` picks the other one *deterministically*. An
        earlier version of this test gave both invoices today's date, which leaves
        the tie-break unspecified -- it passed against develop by luck, and a test
        that can pass against the bug is not a test of the fix.
        """
        member = member_with_customer(self, "SubMatch")
        wanted = self._open_invoice(member, 25.0, posting_date=add_days(today(), -10))
        decoy = self._open_invoice(member, 90.0)
        self.assertGreater(getdate(decoy.posting_date), getdate(wanted.posting_date))

        result, ref_no = self._process_subscription(member, 25.0)

        self.assertEqual((result or {}).get("status"), "success", msg=result)
        self.assertEqual(result["invoice"], wanted.name)
        pe = frappe.get_doc("Payment Entry", result["payment_entry"])
        self.assertEqual(pe.references[0].reference_name, wanted.name)

    def test_a_single_open_invoice_still_takes_a_partial_payment(self):
        """Pins the behaviour the tempting version of this fix would remove.

        A payment smaller than the outstanding is a legitimate partial payment.
        Passes against develop too, deliberately.
        """
        member = member_with_customer(self, "SubPartial")
        invoice = self._open_invoice(member, 50.0)

        result, _ref_no = self._process_subscription(member, 20.0)

        self.assertEqual((result or {}).get("status"), "success", msg=result)
        self.assertEqual(result["invoice"], invoice.name)
        pe = frappe.get_doc("Payment Entry", result["payment_entry"])
        self.assertAlmostEqual(float(pe.references[0].allocated_amount), 20.0, places=2)

    def test_a_part_paid_invoice_is_not_over_allocated(self):
        """`Partly Paid` is in this query's status list, so grand_total is the wrong bound.

        Red against develop with an exception, not a wrong answer: the allocation was
        `min(payment, grand_total)` = min(40, 45) = 40 against an outstanding of 30,
        and ERPNext throws "Allocated Amount cannot be greater than outstanding
        amount" (payment_entry.py:377). The same wrong column was also the amount
        discriminator.
        """
        # 40 against an outstanding of 30 is an OVERpayment: the surplus stays
        # unallocated on the Payment Entry, which is surfaced for an operator.
        self.expectErrorLog("Mollie Subscription Payment Overpaid")
        member = member_with_customer(self, "SubPartPaid")
        invoice = self._open_invoice(member, 45.0)
        part_paid, part_payment = receive_against_invoice(self, invoice.name, 15.0)
        # _process_subscription_payment commits, which commits this PE with it.
        self._committed_pes.append(part_payment.name)
        self.assertAlmostEqual(float(part_paid.outstanding_amount), 30.0, places=2)

        result, _ref_no = self._process_subscription(member, 40.0)

        self.assertEqual((result or {}).get("status"), "success", msg=result)
        pe = frappe.get_doc("Payment Entry", result["payment_entry"])
        self.assertAlmostEqual(
            float(pe.references[0].allocated_amount),
            30.0,
            places=2,
            msg="allocation must be bounded by what is still outstanding",
        )


if __name__ == "__main__":
    unittest.main()
