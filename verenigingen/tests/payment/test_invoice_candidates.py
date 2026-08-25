"""The rule that resolves ONE Sales Invoice out of a party's candidate set (#567).

`verenigingen_payments/utils/invoice_candidates.unambiguous_invoice` is the shared
form of the fix #559 made in one place. Four other call sites were taking the first
row of a party's invoices and moving money against it; they now all route through
this rule, so it is tested directly rather than only through each of them -- a
branch-level `assertIsNone` at a call site is equally satisfied by that branch
breaking outright.

Real Members / Customers / Sales Invoices / Payment Entries throughout. Nothing
about the rule is mocked.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.invoice_payments import member_with_customer, receive_against_invoice
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.verenigingen_payments.utils.invoice_candidates import unambiguous_invoice


class InvoiceCandidatesBase(EnhancedTestCase):
    """A member with a customer in the EUR test company, plus invoice builders."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Provision the company's bank account (committed) ONCE, before any
        # per-test transaction opens -- `receive_against_invoice` reads it and
        # fails loudly if it is absent. Same shape and the same reason as
        # `ReconBase.setUpClass` (test_sepa_reconciliation.py:95): provisioning
        # from a test body would commit that test's in-flight fixtures.
        # Without this, whether the read succeeds depends on whether an EARLIER
        # module in the shard happened to stamp `Company.default_bank_account` --
        # which is what reddened shard 11/12 of #575.
        get_eur_bank_account(get_eur_test_company())

    def setUp(self):
        super().setUp()
        # Own the company by name rather than scanning for one: a company another
        # suite partially drained can never be repaired (#390), and which one a
        # scan wins depends on what else ran first in the shard.
        self.company = get_eur_test_company()

    def _unpaid(self, member, grand_total):
        """A submitted, Unpaid invoice -- outstanding == grand_total."""
        return self.create_test_sales_invoice(
            customer=member.name, grand_total=grand_total, company=self.company
        )

    def _partly_paid(self, member, grand_total, paid):
        """A submitted invoice whose outstanding and grand_total genuinely differ.

        Without that, a test cannot tell which column the rule compared on, and
        the reversal call site depends on the answer.
        """
        invoice = self._unpaid(member, grand_total)
        part_paid, _payment_entry = receive_against_invoice(self, invoice.name, paid)
        return part_paid

    def _ask(self, member, amount, **kwargs):
        return unambiguous_invoice(
            filters={
                "customer": member.customer,
                "docstatus": 1,
                "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
            },
            amount=amount,
            **kwargs,
        )


class TestTheRule(InvoiceCandidatesBase):
    def test_no_candidates_is_not_ambiguous(self):
        """Nothing to match and a choice I must not make are different outcomes.

        Every call site reports them differently, so the count has to come back.
        """
        member = member_with_customer(self, "CandNone")
        choice = self._ask(member, 10.0)
        self.assertIsNone(choice.invoice)
        self.assertEqual(choice.candidates, 0)
        self.assertFalse(choice.is_ambiguous)

    def test_one_candidate_wins_whatever_the_amount(self):
        """Rule 1. A smaller payment against one open invoice is a partial payment.

        This is the behaviour the tempting version of this fix ("require the amount
        to match") removes. It is pinned deliberately.
        """
        member = member_with_customer(self, "CandOne")
        invoice = self._unpaid(member, 25.0)
        choice = self._ask(member, 7.5)
        self.assertIsNotNone(choice.invoice)
        self.assertEqual(choice.invoice["name"], invoice.name)
        self.assertEqual(choice.candidates, 1)

    def test_the_candidate_matching_the_amount_is_chosen(self):
        """Rule 2. The discriminator was available all along at every call site."""
        member = member_with_customer(self, "CandTwo")
        wanted = self._unpaid(member, 25.0)
        other = self._unpaid(member, 90.0)
        self.assertNotEqual(wanted.name, other.name)
        choice = self._ask(member, 25.0)
        self.assertIsNotNone(choice.invoice)
        self.assertEqual(choice.invoice["name"], wanted.name)
        self.assertEqual(choice.candidates, 2)

    def test_two_candidates_and_nothing_to_choose_on_is_refused(self):
        """Rule 3. An amount matching neither leaves nothing but creation order."""
        member = member_with_customer(self, "CandAmbig")
        first = self._unpaid(member, 25.0)
        second = self._unpaid(member, 90.0)
        choice = self._ask(member, 17.5)
        self.assertIsNone(
            choice.invoice,
            f"must not resolve to either of {first.name} / {second.name} on order alone",
        )
        self.assertEqual(choice.candidates, 2)
        self.assertTrue(choice.is_ambiguous)

    def test_two_candidates_of_the_same_amount_are_still_refused(self):
        """The amount filter has to actually discriminate.

        Two invoices both equal to the payment narrow nothing: picking either is
        the same arbitrary choice, reached through a filter instead of through
        creation order. Two open dues invoices of one amount is ordinary.
        """
        member = member_with_customer(self, "CandTwins")
        self._unpaid(member, 30.0)
        self._unpaid(member, 30.0)
        choice = self._ask(member, 30.0)
        self.assertIsNone(choice.invoice)
        self.assertEqual(choice.candidates, 2)
        self.assertTrue(choice.is_ambiguous)

    def test_a_sub_cent_difference_is_still_the_amount_match(self):
        """Compared at the field's own precision, as the payment-entry path does."""
        member = member_with_customer(self, "CandPrec")
        wanted = self._unpaid(member, 30.0)
        self._unpaid(member, 90.0)
        choice = self._ask(member, 30.001)
        self.assertIsNotNone(choice.invoice)
        self.assertEqual(choice.invoice["name"], wanted.name)

    def test_amount_field_selects_which_column_discriminates(self):
        """`grand_total` and `outstanding_amount` give DIFFERENT answers here.

        The reversal call site (`process_individual_return`) matches a settled
        invoice, whose outstanding carries no information -- it compares on
        `grand_total`. This fixture makes the two columns disagree, so a rule that
        ignored `amount_field` and always read `outstanding_amount` fails it.
        """
        member = member_with_customer(self, "CandField")
        plain = self._unpaid(member, 30.0)
        partly = self._partly_paid(member, 45.0, 15.0)  # outstanding 30, grand_total 45
        self.assertAlmostEqual(float(partly.outstanding_amount), 30.0, places=2)

        on_grand_total = self._ask(member, 45.0, amount_field="grand_total")
        self.assertIsNotNone(on_grand_total.invoice)
        self.assertEqual(on_grand_total.invoice["name"], partly.name)

        # Same question against the default column: both invoices have outstanding
        # 30, so 45 matches neither and the rule refuses.
        on_outstanding = self._ask(member, 45.0)
        self.assertIsNone(on_outstanding.invoice)
        self.assertTrue(on_outstanding.is_ambiguous)

        # And 30 is ambiguous on outstanding while grand_total resolves it.
        self.assertIsNone(self._ask(member, 30.0).invoice)
        resolved = self._ask(member, 30.0, amount_field="grand_total")
        self.assertIsNotNone(resolved.invoice)
        self.assertEqual(resolved.invoice["name"], plain.name)

    def test_requested_fields_come_back_with_the_amount_column(self):
        """Call sites need the row, not just the name, and must not re-query for it."""
        member = member_with_customer(self, "CandFields")
        invoice = self._unpaid(member, 25.0)
        choice = unambiguous_invoice(
            filters={"customer": member.customer, "docstatus": 1},
            amount=25.0,
            fields=["name", "grand_total", "company", "currency"],
        )
        self.assertIsNotNone(choice.invoice)
        self.assertEqual(choice.invoice["name"], invoice.name)
        self.assertEqual(choice.invoice["company"], self.company)
        # appended because it is the discriminator, even though it was not requested
        self.assertIn("outstanding_amount", choice.invoice)


if __name__ == "__main__":
    unittest.main()
