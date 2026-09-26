"""
Integration tests (Tier-2) for CompletePaymentService
(verenigingen/verenigingen_payments/mollie/services/complete_payment_service.py).

LIVE: CompletePaymentService is instantiated by unified_payment_api.py,
payment_gateways.py, and templates/pages/donate.py.

Credential-free pattern (matches test_dues_payment_processor_integration.py):
    __init__ builds a real MollieClient + a UnifiedWebhookWrapperService (both
    need Mollie Settings). The methods under test are validators (pure),
    metadata builders (DB read of Donation only), client-boundary calls
    (get_payment_status, cancel_subscription), the enable_subscriptions gate,
    the mandate-finder (pure over a mandate list), and owner-record writers
    (real Member/Donor DB writes via set_value). We bypass __init__ via
    object.__new__() and attach a SimpleNamespace fake client ONLY where a
    method talks to the SDK — the service logic itself is never mocked.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.exceptions import (
    MolliePaymentError,
    MollieValidationError,
)
from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
    CompletePaymentService,
)


def _bare_service():
    """CompletePaymentService without __init__ (no MollieClient built)."""
    return object.__new__(CompletePaymentService)


def _service_with_client(client):
    svc = _bare_service()
    svc.client = client
    return svc


class TestValidateDonationPaymentData(EnhancedTestCase):
    """_validate_donation_payment_data — required-field + amount validation."""

    def _form(self, **overrides):
        form = {
            "amount": "25.00",
            "currency": "EUR",
            "return_url": "https://example.com/return",
        }
        form.update(overrides)
        return form

    def test_valid_data_passes(self):
        svc = _bare_service()
        # Should not raise; donation_doc only needs to be truthy here.
        svc._validate_donation_payment_data(SimpleNamespace(name="DON-1"), self._form())

    def test_missing_donation_doc_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_donation_payment_data(None, self._form())

    def test_missing_amount_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_donation_payment_data(SimpleNamespace(name="D"), self._form(amount=None))

    def test_invalid_amount_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_donation_payment_data(SimpleNamespace(name="D"), self._form(amount="-5"))

    def test_missing_currency_raises(self):
        svc = _bare_service()
        form = self._form()
        form.pop("currency")
        with self.assertRaises(MollieValidationError):
            svc._validate_donation_payment_data(SimpleNamespace(name="D"), form)

    def test_missing_return_url_raises(self):
        svc = _bare_service()
        form = self._form()
        form.pop("return_url")
        with self.assertRaises(MollieValidationError):
            svc._validate_donation_payment_data(SimpleNamespace(name="D"), form)


class TestValidateSubscriptionData(EnhancedTestCase):
    """_validate_subscription_data + _is_valid_interval."""

    def _customer(self):
        return {"email": "sub@example.com"}

    def test_valid_dict_amount(self):
        svc = _bare_service()
        svc._validate_subscription_data(
            self._customer(), {"amount": {"value": "10.00", "currency": "EUR"}, "interval": "1 month"}
        )

    def test_valid_scalar_amount(self):
        svc = _bare_service()
        svc._validate_subscription_data(self._customer(), {"amount": "10.00", "interval": "3 months"})

    def test_missing_email_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_subscription_data({}, {"amount": "10", "interval": "1 month"})

    def test_missing_amount_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_subscription_data(self._customer(), {"interval": "1 month"})

    def test_amount_dict_without_value_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_subscription_data(
                self._customer(), {"amount": {"currency": "EUR"}, "interval": "1 month"}
            )

    def test_missing_interval_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_subscription_data(self._customer(), {"amount": "10"})

    def test_bad_interval_format_raises(self):
        svc = _bare_service()
        with self.assertRaises(MollieValidationError):
            svc._validate_subscription_data(self._customer(), {"amount": "10", "interval": "monthly"})

    def test_is_valid_interval_variants(self):
        svc = _bare_service()
        self.assertTrue(svc._is_valid_interval("1 month"))
        self.assertTrue(svc._is_valid_interval("3 months"))
        self.assertTrue(svc._is_valid_interval("14 days"))
        self.assertFalse(svc._is_valid_interval("month"))
        self.assertFalse(svc._is_valid_interval("1 year"))
        self.assertFalse(svc._is_valid_interval("x month"))


class TestPreparePaymentData(EnhancedTestCase):
    """_prepare_payment_data — builds the Mollie create-payment dict."""

    def test_builds_expected_payload(self):
        svc = _bare_service()
        # get_webhook_url is the only client touch in this method.
        svc.client = SimpleNamespace(get_webhook_url=lambda: "https://example.com/webhook")
        donation = SimpleNamespace(name="DON-77", donation_type="general")
        form = {
            "amount": "30.00",
            "currency": "EUR",
            "return_url": "https://example.com/return",
            "method": "ideal",
            "sequenceType": "first",
        }

        data = svc._prepare_payment_data(donation, form)

        self.assertEqual(data["amount"], {"value": "30.00", "currency": "EUR"})
        self.assertEqual(data["description"], "Donation DON-77")
        self.assertEqual(data["redirectUrl"], "https://example.com/return")
        self.assertEqual(data["webhookUrl"], "https://example.com/webhook")
        self.assertEqual(data["method"], "ideal")
        self.assertEqual(data["sequenceType"], "first")
        # Metadata carries the webhook-handler reference fields.
        self.assertEqual(data["metadata"]["reference_doctype"], "Donation")
        self.assertEqual(data["metadata"]["reference_docname"], "DON-77")
        self.assertEqual(data["metadata"]["donation_id"], "DON-77")

    def test_optional_fields_omitted(self):
        svc = _bare_service()
        svc.client = SimpleNamespace(get_webhook_url=lambda: "https://example.com/webhook")
        donation = SimpleNamespace(name="DON-78", donation_type="general")
        data = svc._prepare_payment_data(
            donation,
            {"amount": "5.00", "currency": "EUR", "return_url": "https://example.com/r"},
        )
        self.assertNotIn("method", data)
        self.assertNotIn("sequenceType", data)


class TestGetPaymentStatus(EnhancedTestCase):
    """get_payment_status — client boundary success + error wrapping."""

    def test_success(self):
        payment = SimpleNamespace(
            status="paid",
            amount={"value": "12.00", "currency": "EUR"},
            description="Donation X",
            created_at="2025-01-01T00:00:00+00:00",
            paid_at="2025-01-01T00:05:00+00:00",
        )
        svc = _service_with_client(SimpleNamespace(get_payment=lambda pid: payment))
        result = svc.get_payment_status("tr_x")
        self.assertEqual(result["payment_id"], "tr_x")
        self.assertEqual(result["status"], "paid")
        self.assertEqual(result["amount"], {"value": "12.00", "currency": "EUR"})
        self.assertEqual(result["paid_at"], "2025-01-01T00:05:00+00:00")

    def test_client_error_wrapped(self):
        def _raise(pid):
            raise RuntimeError("not found")

        svc = _service_with_client(SimpleNamespace(get_payment=_raise))
        with self.assertRaises(MolliePaymentError):
            svc.get_payment_status("tr_missing")


class TestCancelSubscription(EnhancedTestCase):
    """cancel_subscription — client cancel + owner status flip."""

    def _persist_member_subscription(self, sub_id):
        member = self.create_test_member(
            first_name="Cancel",
            last_name=f"Sub{frappe.generate_hash()[:8]}",
            email=f"cancel.sub.{frappe.generate_hash()[:6]}@example.com",
        )
        frappe.db.set_value("Member", member.name, "mollie_subscription_id", sub_id)
        return member

    def test_cancel_with_explicit_owner_updates_member(self):
        sub_id = f"sub_{frappe.generate_hash()[:10]}"
        member = self._persist_member_subscription(sub_id)
        cancelled = {}
        client = SimpleNamespace(
            cancel_subscription=lambda cid, sid: cancelled.update({"cid": cid, "sid": sid})
        )
        svc = _service_with_client(client)

        result = svc.cancel_subscription(
            "cst_1", sub_id, reason="test", owner_doctype="Member", owner_name=member.name
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], sub_id)
        self.assertEqual(cancelled["sid"], sub_id)
        self.assertEqual(frappe.db.get_value("Member", member.name, "subscription_status"), "canceled")

    def test_cancel_reverse_resolves_owner(self):
        # No explicit owner -> _update_subscription_status reverse-resolves the
        # Member by mollie_subscription_id and flips its status.
        sub_id = f"sub_{frappe.generate_hash()[:10]}"
        member = self._persist_member_subscription(sub_id)
        client = SimpleNamespace(cancel_subscription=lambda cid, sid: None)
        svc = _service_with_client(client)

        svc.cancel_subscription("cst_1", sub_id, reason="rev")
        self.assertEqual(frappe.db.get_value("Member", member.name, "subscription_status"), "canceled")

    def test_cancel_client_error_wrapped(self):
        def _raise(cid, sid):
            raise RuntimeError("mollie 500")

        svc = _service_with_client(SimpleNamespace(cancel_subscription=_raise))
        with self.assertRaises(MolliePaymentError):
            svc.cancel_subscription("cst", "sub_err")


class TestUpdateOwnerRecord(EnhancedTestCase):
    """_update_owner_record — only writes fields the DocType defines."""

    def test_skips_fields_absent_on_donor(self):
        # Donor has no subscription_status / next_payment_date fields; those
        # keys must be silently dropped while writing mollie_customer_id.
        donation = self.create_test_donation(
            donor_email=f"owner.{frappe.generate_hash()[:6]}@example.com", amount=10.0
        )
        donor = frappe.db.get_value("Donation", donation.name, "donor")
        cid = f"cst_owner_{frappe.generate_hash()[:8]}"

        svc = _bare_service()
        svc._update_owner_record(
            "Donor",
            donor,
            {
                "mollie_customer_id": cid,
                "subscription_status": "active",
                "next_payment_date": "2030-01-01",
            },
        )
        self.assertEqual(frappe.db.get_value("Donor", donor, "mollie_customer_id"), cid)


class TestResolveCustomerByEmailAmbiguous(EnhancedTestCase):
    """_resolve_customer_by_email — #1396: more than one Donor sharing the
    given e-mail is an unresolvable ambiguity. Reading OR writing an
    arbitrarily-picked one of them is a financially-relevant misattribution
    (a subsequent charge or an existing mollie_customer_id read off the
    wrong Donor) - the same rule #1356/#1384/#1389/#1392/#1406 established
    for every other Donor-by-email sibling. The payment must still succeed:
    on ambiguity this falls back to _create_mollie_customer_only, the same
    "no owner record" path already used when zero Donors match."""

    def _donor_with_mollie_customer_id(self, email, mollie_customer_id=None):
        """Not a copy of the app's various `_make_donor` test helpers (a
        clone-baselined family, #1396 self-review): this one additionally
        sets mollie_customer_id, which none of those do."""
        donor = self.create_test_donor(donor_email=email, donor_type="Individual")
        if mollie_customer_id:
            frappe.db.set_value("Donor", donor.name, "mollie_customer_id", mollie_customer_id)
        return donor

    def test_ambiguous_email_creates_customer_without_reading_or_writing_either_donor(self):
        email = f"ambig.mollie.{frappe.generate_hash()[:8]}@example.com"
        first = self._donor_with_mollie_customer_id(email, mollie_customer_id="cst_existing_first")
        second = self._donor_with_mollie_customer_id(email)

        get_customer_calls = []
        create_customer_calls = []

        def _get_customer(cid):
            # Recorded, never asserted-not-called via a raise: a raise here
            # would be swallowed by the (legitimate, for a real stale id)
            # inner try/except in the unfixed code and could mask the bug
            # instead of exposing it. The call-count assertion below is the
            # real check.
            get_customer_calls.append(cid)
            return SimpleNamespace(id=cid)

        def _create_customer(payload):
            create_customer_calls.append(payload)
            return SimpleNamespace(id="cst_new_from_ambiguous")

        svc = _service_with_client(
            SimpleNamespace(get_customer=_get_customer, create_customer=_create_customer)
        )

        self.expectErrorLog("DONOR_001")
        with self.assertErrorLog("DONOR_001"):
            result = svc._resolve_customer_by_email({"email": email, "name": "Ambiguous Payer"})

        self.assertEqual(result, {"status": "created", "customer_id": "cst_new_from_ambiguous"})
        self.assertEqual(get_customer_calls, [])
        self.assertEqual(len(create_customer_calls), 1)

        # Neither pre-existing ambiguous Donor was read from or written to.
        first.reload()
        second.reload()
        self.assertEqual(first.mollie_customer_id, "cst_existing_first")
        self.assertFalse(second.mollie_customer_id)

    def test_single_match_still_resolves(self):
        # Control for the test above: a single match is NOT ambiguous and
        # must still use the existing donor's stored customer id.
        email = f"single.mollie.{frappe.generate_hash()[:8]}@example.com"
        self._donor_with_mollie_customer_id(email, mollie_customer_id="cst_existing_only")

        svc = _service_with_client(
            SimpleNamespace(get_customer=lambda cid: SimpleNamespace(id=cid))
        )
        result = svc._resolve_customer_by_email({"email": email, "name": "Solo Payer"})
        self.assertEqual(result, {"status": "found", "customer_id": "cst_existing_only"})


class TestFindUsableDirectdebitMandate(EnhancedTestCase):
    """_find_usable_directdebit_mandate — pure selection over a mandate list."""

    def _mandate(self, status, iban, method="directdebit"):
        return SimpleNamespace(
            id=f"mdt_{frappe.generate_hash()[:6]}",
            method=method,
            status=status,
            details={"consumerAccount": iban},
        )

    def test_valid_mandate_preferred(self):
        iban = "NL91ABNA0417164300"
        mandates = [self._mandate("pending", iban), self._mandate("valid", iban)]
        svc = _service_with_client(SimpleNamespace(list_mandates=lambda cid: mandates))
        found = svc._find_usable_directdebit_mandate("cst_1", iban)
        self.assertEqual(found.status, "valid")

    def test_pending_returned_when_no_valid(self):
        iban = "NL91ABNA0417164300"
        mandates = [self._mandate("pending", iban)]
        svc = _service_with_client(SimpleNamespace(list_mandates=lambda cid: mandates))
        found = svc._find_usable_directdebit_mandate("cst_1", iban)
        self.assertEqual(found.status, "pending")

    def test_iban_comparison_ignores_spacing_and_case(self):
        mandates = [self._mandate("valid", "nl91 abna 0417 1643 00")]
        svc = _service_with_client(SimpleNamespace(list_mandates=lambda cid: mandates))
        found = svc._find_usable_directdebit_mandate("cst_1", "NL91ABNA0417164300")
        self.assertIsNotNone(found)

    def test_non_directdebit_and_other_iban_ignored(self):
        target = "NL91ABNA0417164300"
        mandates = [
            self._mandate("valid", target, method="creditcard"),
            self._mandate("valid", "NL00BANK0000000000"),
        ]
        svc = _service_with_client(SimpleNamespace(list_mandates=lambda cid: mandates))
        self.assertIsNone(svc._find_usable_directdebit_mandate("cst_1", target))

    def test_list_failure_fails_open_to_none(self):
        def _raise(cid):
            raise RuntimeError("api down")

        svc = _service_with_client(SimpleNamespace(list_mandates=_raise))
        self.assertIsNone(svc._find_usable_directdebit_mandate("cst_1", "NL91ABNA0417164300"))


class TestCreateCustomerSubscriptionGate(EnhancedTestCase):
    """create_customer_subscription — enable_subscriptions gate."""

    def test_disabled_subscriptions_raises_validation(self):
        # Force the gate closed for this test (rolled back per-method by
        # EnhancedTestCase). The validation error must propagate untouched.
        original = frappe.db.get_single_value("Mollie Settings", "enable_subscriptions")
        try:
            frappe.db.set_single_value("Mollie Settings", "enable_subscriptions", 0)
            svc = _bare_service()
            with self.assertRaises(MollieValidationError):
                svc.create_customer_subscription(
                    {"email": "x@example.com"},
                    {"amount": {"value": "10.00", "currency": "EUR"}, "interval": "1 month"},
                )
        finally:
            frappe.db.set_single_value("Mollie Settings", "enable_subscriptions", original)
