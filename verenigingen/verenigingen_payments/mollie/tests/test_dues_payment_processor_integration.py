"""
Integration tests (Tier-2) for the member-matching / classification logic in
DuesPaymentProcessor, against REAL Member records and the real PaymentClassifier
strategy chain. No mocks of the logic under test.

Targets (verenigingen/verenigingen_payments/mollie/services/dues_payment_processor.py):
    - DuesPaymentProcessor.identify_payment_type()   -> PaymentClassifier (DB lookups)
    - DuesPaymentProcessor.find_member_for_payment()  -> MemberPaymentMatcher (DB lookups)
    - DuesPaymentProcessor._resolve_chapter_cost_center() -> company fallback
    - DuesPaymentProcessor._get_membership_type_cached()  -> settings default + caching

Credential-free in CI:
    DuesPaymentProcessor.__init__ constructs a MollieClient, which reads a key
    from Mollie Settings. The methods under test do NOT call Mollie's HTTP API —
    they only query the DB. To exercise them in CI WITHOUT credentials we sidestep
    the constructor (the only Mollie boundary) the same way the sibling suite
    test_mollie_payment_db_integration.py does: obtain a processor instance via
    object.__new__() (bypassing __init__, so no MollieClient is built) and attach
    only the collaborators the methods actually use — here the credential-free
    PaymentClassifier. find_member_for_payment() and _resolve_chapter_cost_center()
    use no instance state at all, and _get_membership_type_cached() lazily
    initialises its own cache, so a bare bypassed instance is sufficient.

    Net effect: all four DB-only methods run in CI. There is no live-MollieClient
    path in this suite, so nothing is gated on credentials.

Mollie payments are stood in with SimpleNamespace stubs (the SDK boundary); only
the attributes the matcher/classifier read are set.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import PaymentClassifier
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor


def _make_processor():
    """Build a DuesPaymentProcessor without invoking __init__.

    __init__ constructs a MollieClient (needs Mollie Settings credentials). The
    methods under test never touch the Mollie HTTP client, so we bypass the
    constructor via object.__new__() and attach only the collaborator they use:
    the credential-free PaymentClassifier (identify_payment_type reads
    self.classifier). The remaining methods use no instance state beyond a cache
    they initialise themselves on first call.
    """
    processor = object.__new__(DuesPaymentProcessor)
    processor.classifier = PaymentClassifier()
    return processor


class TestDuesPaymentProcessorMatching(EnhancedTestCase):
    """Member matching + payment-type classification via the real services."""

    def setUp(self):
        super().setUp()
        self.processor = _make_processor()

    def _payment(self, **kwargs):
        defaults = dict(
            id="tr_dpp_test",
            status="paid",
            amount={"value": "25.00", "currency": "EUR"},
            description="Membership dues",
            customer_id=None,
            subscription_id=None,
            metadata={},
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_find_member_by_customer_id(self):
        token = frappe.generate_hash()[:8]
        cid = f"cst_dpp_{token}"
        member = self.create_test_member(
            first_name="DPP", last_name=f"Cust{token}", email=f"dpp.cust.{token}@example.com"
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", cid)

        payment = self._payment(customer_id=cid)
        found = self.processor.find_member_for_payment(payment)
        self.assertEqual(found, member.name)

    def test_find_member_returns_none_for_unknown_customer(self):
        payment = self._payment(customer_id=f"cst_nobody_{frappe.generate_hash()[:8]}")
        self.assertIsNone(self.processor.find_member_for_payment(payment))

    def test_identify_payment_type_dues_via_customer_match(self):
        token = frappe.generate_hash()[:8]
        cid = f"cst_dppt_{token}"
        member = self.create_test_member(
            first_name="DPP", last_name=f"Type{token}", email=f"dpp.type.{token}@example.com"
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", cid)

        payment = self._payment(customer_id=cid, description="recurring payment")
        # A Member match on customer_id classifies the payment as dues.
        self.assertEqual(self.processor.identify_payment_type(payment), "dues")

    def test_resolve_chapter_cost_center_falls_back_to_company(self):
        # Member with no chapter -> falls back to the company's default cost center
        # (or None if the company has none configured). Either way it must not raise.
        member = self.create_test_member(
            first_name="DPP",
            last_name=f"CC{frappe.generate_hash()[:8]}",
            email=f"dpp.cc.{frappe.generate_hash()[:6]}@example.com",
        )
        member_doc = frappe.get_doc("Member", member.name)
        company = frappe.db.get_single_value(
            "Verenigingen Settings", "company"
        ) or frappe.defaults.get_global_default("company")

        result = self.processor._resolve_chapter_cost_center(member_doc, company)

        company_cc = frappe.db.get_value("Company", company, "cost_center")
        if company_cc and frappe.db.exists("Cost Center", company_cc):
            self.assertEqual(result, company_cc)
        else:
            self.assertIsNone(result)

    def test_get_membership_type_cached_uses_settings_default(self):
        # Member with no current_membership_plan -> falls through to the settings default.
        member = self.create_test_member(
            first_name="DPP",
            last_name=f"MT{frappe.generate_hash()[:8]}",
            email=f"dpp.mt.{frappe.generate_hash()[:6]}@example.com",
        )
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.current_membership_plan = None

        # The method reads the default off the loaded Single doc; an unset Link
        # field surfaces as None there (vs "" via get_single_value), so normalise.
        expected = frappe.get_single("Verenigingen Settings").default_membership_type or None
        result = self.processor._get_membership_type_cached(member_doc)
        self.assertEqual(result, expected)

        # Second call must hit the cache and return the same value (caching path).
        self.assertEqual(self.processor._get_membership_type_cached(member_doc), expected)
        self.assertEqual(self.processor._default_membership_type, expected)
