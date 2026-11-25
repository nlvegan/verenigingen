"""
#2675 (maintainer ruling 2026-11-25, option a): a comma-separated ``mollie_customer_id`` list is
supported. Payment attribution AND the shared-id refusal work per individual id.

Surfaces covered: the single classifier (Member and Donor), the batch classifier, the
MemberPaymentMatcher, and the admin CSV check (``validate_csv_members``).

Probe shortcut, stated: lists are put on rows with ``db.set_value`` (as the #1497/#2576 modules
do); no writer in the app is driven here.

Run with:
    PYTHONPATH=<worktree> scripts/testing/run_without_credentials.sh test_site_8 \\
        verenigingen.tests.payment.test_mollie_multi_id_customer_lists_2675
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.payment.test_mollie_classification_ambiguous_party_1497 import _purge
from verenigingen.tests.payment.test_mollie_shared_id_lookups_2576 import SharedIdBase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
    MEMBER_LOG_TITLE,
    PaymentClassifier,
    PaymentType,
)
from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
    MemberPaymentMatcher,
)
from verenigingen.verenigingen_payments.utils.mollie_customer_id_list import (
    split_mollie_customer_ids,
)


class TestSplitHelper(SharedIdBase):
    def test_whitespace_empties_and_duplicates_are_normalised(self):
        self.assertEqual(split_mollie_customer_ids(" cst_a ,, cst_b,cst_a , "), ["cst_a", "cst_b"])
        self.assertEqual(split_mollie_customer_ids(None), [])
        self.assertEqual(split_mollie_customer_ids(""), [])
        self.assertEqual(split_mollie_customer_ids("cst_12"), ["cst_12"])


class MultiIdBase(SharedIdBase):
    def setUp(self):
        super().setUp()
        h = frappe.generate_hash(length=8)
        self.id_a, self.id_b, self.id_c = f"cst_a{h}", f"cst_b{h}", f"cst_c{h}"

    def _list_on(self, row, *ids, doctype="Member", sep=", "):
        self._set(doctype, row.name, "mollie_customer_id", sep.join(ids))


class TestAttributionPerId(MultiIdBase):
    def test_second_id_of_a_list_attributes_to_the_member(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        for cid in (self.id_a, self.id_b):
            result = PaymentClassifier().classify(self.payment(customer_id=cid))
            self.assertEqual(result.payment_type, PaymentType.DUES, cid)
            self.assertEqual(result.member_id, self.members[0].name, cid)

    def test_batch_classifier_matches_each_id_of_a_list(self):
        self._list_on(self.members[0], self.id_a, self.id_b, sep=" , ")
        payments = [
            self.payment(id=f"{self.payment_id}a", customer_id=self.id_a),
            self.payment(id=f"{self.payment_id}b", customer_id=self.id_b),
        ]
        self.addCleanup(_purge, [p.id for p in payments])
        results = PaymentClassifier().classify_batch(payments)
        self.assertEqual([r.member_id for r in results], [self.members[0].name] * 2)

    def test_donor_list_attributes_a_donation(self):
        self._list_on(self.donors[0], self.id_a, self.id_b, doctype="Donor")
        result = PaymentClassifier().classify(self.payment(customer_id=self.id_b))
        self.assertEqual(result.payment_type, PaymentType.DONATION)
        self.assertEqual(result.donor_id, self.donors[0].name)

    def test_matcher_resolves_each_id_of_a_list(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        matcher = MemberPaymentMatcher()
        for cid in (self.id_a, self.id_b):
            found = matcher.find_member_for_payment(self.payment(customer_id=cid))
            self.assertEqual(found["name"], self.members[0].name, cid)
            self.assertTrue(matcher.is_customer_id_known(cid))

    def test_csv_check_resolves_each_id_of_a_list(self):
        self._list_on(self.members[0], self.id_a, self.id_b)
        self._act_as_admin()
        from verenigingen.templates.pages.mollie_bulk_payment_creation import validate_csv_members

        csv_content = f"customer_id,amount,charge_date\n{self.id_b},10.00,{add_days(today(), 5)}\n"
        (row,) = validate_csv_members(csv_content)["results"]
        self.assertEqual(row["member_id"], self.members[0].name)


class TestSharedIdRefusalPerId(MultiIdBase):
    """Member 0 lists (a, b); Member 1 lists (b, c): b is shared, a and c are unique."""

    def setUp(self):
        super().setUp()
        self._list_on(self.members[0], self.id_a, self.id_b)
        self._list_on(self.members[1], self.id_b, self.id_c)

    def test_classifier_refuses_the_shared_id_and_names_both_members(self):
        result = PaymentClassifier().classify(self.payment(customer_id=self.id_b))
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)
        self.assertIsNone(result.member_id)
        (row,) = self._error_rows(MEMBER_LOG_TITLE)
        for member in self.members:
            self.assertIn(member.name, row)

    def test_batch_classifier_refuses_the_shared_id(self):
        (result,) = PaymentClassifier().classify_batch([self.payment(customer_id=self.id_b)])
        self.assertEqual(result.payment_type, PaymentType.AMBIGUOUS)

    def test_unique_ids_of_the_same_lists_still_attribute(self):
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=self.id_a)).member_id,
            self.members[0].name,
        )
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=self.id_c)).member_id,
            self.members[1].name,
        )

    def test_matcher_refuses_the_shared_id_but_resolves_the_unique_ones(self):
        matcher = MemberPaymentMatcher()
        self.assertIsNone(matcher.find_member_for_payment(self.payment(customer_id=self.id_b)))
        self.assertTrue(matcher.is_customer_id_known(self.id_b))
        self.assertEqual(
            matcher.find_member_for_payment(self.payment(customer_id=self.id_c))["name"],
            self.members[1].name,
        )

    def test_csv_check_refuses_the_shared_id(self):
        self._act_as_admin()
        from verenigingen.templates.pages.mollie_bulk_payment_creation import validate_csv_members

        csv_content = f"customer_id,amount,charge_date\n{self.id_b},10.00,{add_days(today(), 5)}\n"
        (row,) = validate_csv_members(csv_content)["results"]
        self.assertEqual(row["status"], "error")
        self.assertIsNone(row["member_id"])


class TestControls(MultiIdBase):
    def test_a_single_id_still_works(self):
        self._set("Member", self.members[0].name, "mollie_customer_id", self.id_a)
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=self.id_a)).member_id,
            self.members[0].name,
        )
        self.assertEqual(
            MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=self.id_a))["name"],
            self.members[0].name,
        )

    def test_a_substring_id_does_not_match_a_longer_id(self):
        longer = f"{self.id_a}9"
        self._list_on(self.members[0], longer, self.id_b)
        for payment_id in (self.id_a,):
            result = PaymentClassifier().classify(self.payment(customer_id=payment_id))
            self.assertNotEqual(result.member_id, self.members[0].name, "prefix id matched a longer id")
            (batch,) = PaymentClassifier().classify_batch([self.payment(customer_id=payment_id)])
            self.assertNotEqual(batch.member_id, self.members[0].name)
            self.assertIsNone(
                MemberPaymentMatcher().find_member_for_payment(self.payment(customer_id=payment_id))
            )
        # control: the longer id itself does match, so the fixture holds a real candidate
        self.assertEqual(
            PaymentClassifier().classify(self.payment(customer_id=longer)).member_id, self.members[0].name
        )

    def test_a_substring_of_the_list_text_does_not_match(self):
        self._list_on(self.members[0], self.id_a, self.id_b, sep=",")
        glued = f"{self.id_a},{self.id_b}"
        self.assertNotEqual(
            PaymentClassifier().classify(self.payment(customer_id=f"{self.id_a},")).member_id,
            self.members[0].name,
        )
        self.assertIsNotNone(glued)
