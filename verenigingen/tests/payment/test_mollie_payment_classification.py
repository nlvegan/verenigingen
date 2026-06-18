"""
Tests for Mollie payment classification.

Covers ``verenigingen_payments/mollie/domain/payment_classification.py``:
- PaymentPatterns.extract_invoice_number (regex parsing)
- Individual classification rules (Order / Subscription / Customer / Keyword)
- PaymentClassifier chain-of-responsibility ordering and fallback
- classify_batch (batched DB lookups) parity with single classify

The only external boundary is the Mollie payment object, which is a plain data
container here (SimpleNamespace). All Member/Donor lookups run for real against
the test database via created fixtures.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_payment_classification
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
    ConfidenceLevel,
    CustomerBasedClassification,
    DescriptionKeywordClassification,
    OrderBasedClassification,
    PaymentClassifier,
    PaymentPatterns,
    PaymentType,
    SubscriptionBasedClassification,
)


def _payment(**kwargs):
    """Build a minimal Mollie-like payment object."""
    kwargs.setdefault("id", "tr_TEST")
    kwargs.setdefault("description", "")
    kwargs.setdefault("subscription_id", None)
    kwargs.setdefault("customer_id", None)
    return SimpleNamespace(**kwargs)


class TestPaymentPatterns(EnhancedTestCase):
    def test_extract_invoice_number_with_year(self):
        self.assertEqual(
            PaymentPatterns.extract_invoice_number("Bestelling 2025-55986"), "2025-55986"
        )

    def test_extract_invoice_number_plain(self):
        self.assertEqual(PaymentPatterns.extract_invoice_number("Bestelling 12345"), "12345")

    def test_extract_invoice_number_case_insensitive(self):
        self.assertEqual(PaymentPatterns.extract_invoice_number("bestelling 999"), "999")

    def test_extract_invoice_number_none_for_no_match(self):
        self.assertIsNone(PaymentPatterns.extract_invoice_number("Random payment"))

    def test_extract_invoice_number_empty_string(self):
        self.assertIsNone(PaymentPatterns.extract_invoice_number(""))

    def test_extract_invoice_number_none_input(self):
        self.assertIsNone(PaymentPatterns.extract_invoice_number(None))


class TestOrderBasedClassification(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.rule = OrderBasedClassification()

    def test_classifies_bestelling_as_order(self):
        result = self.rule.classify(_payment(description="Bestelling 2025-100"))
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.ORDER)
        self.assertEqual(result.confidence, ConfidenceLevel.HIGH)
        self.assertEqual(result.matched_by, "order_keyword_bestelling")

    def test_no_match_for_plain_description(self):
        self.assertIsNone(self.rule.classify(_payment(description="Membership contributie")))

    def test_no_match_for_non_string_description(self):
        self.assertIsNone(self.rule.classify(_payment(description=12345)))

    def test_no_match_for_empty_description(self):
        self.assertIsNone(self.rule.classify(_payment(description="")))


class TestDescriptionKeywordClassification(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.rule = DescriptionKeywordClassification()

    def test_dues_keyword(self):
        # 'contributie' is a default dues keyword. Avoid 'bestelling' which is
        # handled by OrderBasedClassification at a higher priority.
        result = self.rule.classify(_payment(description="Jaarlijkse contributie 2025"))
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.DUES)
        self.assertEqual(result.confidence, ConfidenceLevel.LOW)

    def test_donation_keyword(self):
        result = self.rule.classify(_payment(description="Een donatie voor het goede doel"))
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.DONATION)

    def test_no_keyword_match(self):
        self.assertIsNone(self.rule.classify(_payment(description="onbekende betaling")))

    def test_non_string_description(self):
        self.assertIsNone(self.rule.classify(_payment(description=None)))


class TestDatabaseLookupClassification(EnhancedTestCase):
    """Subscription/Customer rules that hit the DB via real Member/Donor records."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Classif", last_name="Member", email=f"classif.m.{frappe.generate_hash(length=6)}@example.com"
        )
        self.donor = self.create_test_donor(
            donor_name="Classif Donor",
            donor_email=f"classif.d.{frappe.generate_hash(length=6)}@example.com",
        )

    def _set_mollie_field(self, doctype, name, field, value):
        frappe.db.set_value(doctype, name, field, value, update_modified=False)

    def test_subscription_match_member_high_confidence(self):
        sub_id = f"sub_{frappe.generate_hash(length=8)}"
        self._set_mollie_field("Member", self.member.name, "mollie_subscription_id", sub_id)
        rule = SubscriptionBasedClassification()
        result = rule.classify(_payment(subscription_id=sub_id))
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.DUES)
        self.assertEqual(result.confidence, ConfidenceLevel.HIGH)
        self.assertEqual(result.member_id, self.member.name)

    def test_subscription_match_donor(self):
        sub_id = f"sub_{frappe.generate_hash(length=8)}"
        self._set_mollie_field("Donor", self.donor.name, "mollie_subscription_id", sub_id)
        rule = SubscriptionBasedClassification()
        result = rule.classify(_payment(subscription_id=sub_id))
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.donor_id, self.donor.name)

    def test_subscription_no_id(self):
        self.assertIsNone(SubscriptionBasedClassification().classify(_payment()))

    def test_subscription_id_but_no_match(self):
        # subscription_id present but matches nobody -> None (and logs a warning)
        self.assertIsNone(
            SubscriptionBasedClassification().classify(_payment(subscription_id="sub_nomatch_xyz"))
        )

    def test_customer_match_member_medium_confidence(self):
        cust_id = f"cst_{frappe.generate_hash(length=8)}"
        self._set_mollie_field("Member", self.member.name, "mollie_customer_id", cust_id)
        result = CustomerBasedClassification().classify(_payment(customer_id=cust_id))
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.DUES)
        self.assertEqual(result.confidence, ConfidenceLevel.MEDIUM)
        self.assertEqual(result.member_id, self.member.name)

    def test_customer_match_donor(self):
        cust_id = f"cst_{frappe.generate_hash(length=8)}"
        self._set_mollie_field("Donor", self.donor.name, "mollie_customer_id", cust_id)
        result = CustomerBasedClassification().classify(_payment(customer_id=cust_id))
        self.assertIsNotNone(result)
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.donor_id, self.donor.name)

    def test_customer_no_id(self):
        self.assertIsNone(CustomerBasedClassification().classify(_payment()))


class TestPaymentClassifierOrchestration(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Orch", last_name="Member", email=f"orch.{frappe.generate_hash(length=6)}@example.com"
        )

    def test_unknown_when_no_rule_matches(self):
        classifier = PaymentClassifier()
        result = classifier.classify(_payment(description="nothing here"))
        self.assertEqual(result.payment_type, PaymentType.UNKNOWN)
        self.assertEqual(result.confidence, ConfidenceLevel.NONE)
        self.assertEqual(result.matched_by, "no_rule_matched")

    def test_order_takes_priority_over_subscription(self):
        # Order rule sits ahead of subscription rule in the default chain.
        sub_id = f"sub_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member", self.member.name, "mollie_subscription_id", sub_id, update_modified=False
        )
        classifier = PaymentClassifier()
        result = classifier.classify(
            _payment(description="Bestelling 2025-77", subscription_id=sub_id)
        )
        self.assertEqual(result.payment_type, PaymentType.ORDER)

    def test_subscription_beats_keyword(self):
        sub_id = f"sub_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member", self.member.name, "mollie_subscription_id", sub_id, update_modified=False
        )
        classifier = PaymentClassifier()
        # description contains 'donatie' keyword, but subscription should win as DUES
        result = classifier.classify(
            _payment(description="donatie", subscription_id=sub_id)
        )
        self.assertEqual(result.payment_type, PaymentType.DUES)
        self.assertEqual(result.confidence, ConfidenceLevel.HIGH)

    def test_custom_rules_override_default(self):
        classifier = PaymentClassifier(rules=[OrderBasedClassification()])
        # No order keyword -> unknown, because only the order rule is present
        self.assertEqual(
            classifier.classify(_payment(description="contributie")).payment_type,
            PaymentType.UNKNOWN,
        )


class TestClassifyBatch(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Batch", last_name="Member", email=f"batch.{frappe.generate_hash(length=6)}@example.com"
        )
        self.donor = self.create_test_donor(
            donor_name="Batch Donor",
            donor_email=f"batch.d.{frappe.generate_hash(length=6)}@example.com",
        )

    def test_batch_empty(self):
        self.assertEqual(PaymentClassifier().classify_batch([]), [])

    def test_batch_matches_member_by_customer_and_falls_back_for_order(self):
        cust_id = f"cst_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member", self.member.name, "mollie_customer_id", cust_id, update_modified=False
        )
        payments = [
            _payment(id="tr_1", customer_id=cust_id),  # member dues by customer
            _payment(id="tr_2", description="Bestelling 2025-9"),  # order via fallback
            _payment(id="tr_3", description="totally unknown"),  # unknown via fallback
        ]
        results = PaymentClassifier().classify_batch(payments)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].payment_type, PaymentType.DUES)
        self.assertEqual(results[0].member_id, self.member.name)
        self.assertEqual(results[1].payment_type, PaymentType.ORDER)
        self.assertEqual(results[2].payment_type, PaymentType.UNKNOWN)

    def test_batch_subscription_donor_match(self):
        sub_id = f"sub_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Donor", self.donor.name, "mollie_subscription_id", sub_id, update_modified=False
        )
        results = PaymentClassifier().classify_batch([_payment(id="tr_x", subscription_id=sub_id)])
        self.assertEqual(results[0].payment_type, PaymentType.DONATION)
        self.assertEqual(results[0].confidence, ConfidenceLevel.HIGH)
        self.assertEqual(results[0].donor_id, self.donor.name)
