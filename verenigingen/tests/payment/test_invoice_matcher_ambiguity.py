"""`find_matching_invoice` must refuse an arbitrary pick, not order its way out of one (#578).

Both of this module's targets belong to #567's class, and PR #575's sweep could not see
either: it was an AST walk for `frappe.get_all`/`get_list`/`get_value`, so the raw
`frappe.db.sql` in `_find_invoice_by_coverage_sql` was structurally invisible to it, and
`_find_invoice_by_calculated_coverage` was affirmatively cleared on the assumption that
`(customer, coverage_start, coverage_end)` is unique -- which this codebase contradicts by
shipping `coverage_overlap_detector.find_overlapping_invoices` and
`invoice_matcher._check_for_overlap_warning`.

Reachable in production, traced end to end: Mollie Bulk Run -> `mollie_bulk_run_service`
-> `MolliePaymentOrchestrator.process_payment` -> `_resolve_invoice_fresh` ->
`find_matching_invoice` -> here, and the result reaches
`dues_processor._create_payment_entry_for_dues(invoice_name=...)`. So money moves against
whatever these two functions return.

Real Members / Customers / Sales Invoices throughout. Nothing about the matcher is mocked.

Two amounts are load-bearing in the fixtures below and are worth stating once:

* The SQL strategy filters on `ABS(grand_total - amount) < 0.01`, so an invoice amount
  EQUAL to the payment is what makes an invoice a candidate at all. Giving two candidates
  the SAME amount is therefore not a contrivance -- it is the ordinary consequence of a
  flat recurring fee, and it is precisely the case in which the amount discriminator can
  narrow nothing.
* The calculated-coverage strategy applies NO amount filter (its own docstring says the
  amount is "used for logging, not matching", deliberately, so a price change still
  matches). To reach it the SQL strategy must find nothing, so those fixtures give the
  invoices an amount the payment does NOT match.
"""

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.services.billing.invoice_matcher import find_matching_invoice
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.error_log_assertions import assert_error_log
from verenigingen.tests.support.invoice_payments import member_with_customer
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class InvoiceMatcherBase(EnhancedTestCase):
    """A member with a customer in the EUR test company, plus a coverage-invoice builder."""

    def setUp(self):
        super().setUp()
        # Own the company by name rather than scanning for one: which company a scan
        # wins depends on what else ran first in the shard.
        self.company = get_eur_test_company()

    def _membership_invoice(self, member, grand_total, coverage_start, coverage_end):
        """A submitted membership invoice carrying a coverage period.

        `custom_coverage_start_date`/`custom_coverage_end_date` are written with
        `db_set` because `create_test_sales_invoice` does not forward them; the code
        under test reads them from the database in raw SQL, so a `db_set` is exactly as
        visible to it as a field set before insert.
        """
        invoice = self.create_test_sales_invoice(
            customer=member.name,
            grand_total=grand_total,
            company=self.company,
            is_membership_invoice=1,
        )
        invoice.db_set("custom_coverage_start_date", getdate(coverage_start))
        invoice.db_set("custom_coverage_end_date", getdate(coverage_end))
        invoice.reload()
        return invoice


class TestTheCoverageSqlStrategy(InvoiceMatcherBase):
    """Strategy 1 -- `_find_invoice_by_coverage_sql`, the raw-SQL `LIMIT 1` pick."""

    def test_one_candidate_in_the_buffer_window_is_still_matched(self):
        """The working case, pinned first.

        The tempting version of this fix refuses whenever the payment date falls
        outside every coverage window. That removes something that works: a single
        candidate within the 3-month buffer IS the invoice this payment is for, and
        `within_buffer` is a match type this code deliberately supports.
        """
        member = member_with_customer(self, "MatchOne")
        window_start = add_months(today(), -2)
        invoice = self._membership_invoice(member, 25.0, window_start, add_days(window_start, 27))

        result = find_matching_invoice(member.name, getdate(today()), 25.0)

        self.assertTrue(result.found, "a single candidate in the buffer window must match")
        self.assertEqual(result.invoice_name, invoice.name)
        self.assertEqual(result.match_type, "within_buffer")

    def test_two_equal_amount_invoices_in_the_buffer_window_are_refused(self):
        """The #578 defect. Two months in arrears on a flat fee, paid late.

        Both invoices are in the buffer window and neither contains the payment date, so
        both carry `match_priority = 1`; their amounts are equal, so the amount filter
        cannot separate them. `ORDER BY custom_coverage_start_date DESC LIMIT 1` then
        allocated the money to the NEWEST period and left the OLDEST open -- a choice,
        made silently, in the direction that leaves the older debt unpaid.
        """
        member = member_with_customer(self, "MatchTwo")
        older_start = add_months(today(), -2)
        newer_start = add_months(today(), -1)
        older = self._membership_invoice(member, 25.0, older_start, add_days(older_start, 27))
        newer = self._membership_invoice(member, 25.0, newer_start, add_days(newer_start, 27))

        result = find_matching_invoice(member.name, getdate(today()), 25.0)

        self.assertFalse(
            result.found,
            f"two equal-amount candidates is a CHOICE, not a match; got {result.invoice_name}",
        )
        self.assertEqual(result.ambiguous_candidates, 2)
        # `found` is False, so `invoice_name` is already None -- asserting it is neither
        # of the two names would be a tautology. What is worth pinning instead is that
        # the OLD answer, the newer coverage period, is not what came back.
        self.assertIsNone(result.invoice_name, f"the old code returned {newer.name}")
        self.assertTrue(frappe.db.get_value("Sales Invoice", older.name, "outstanding_amount"))

    def test_the_invoice_whose_coverage_contains_the_payment_date_wins(self):
        """`match_priority` stays a real discriminator, not a tie-break.

        "The payment date falls inside THIS invoice's coverage window" is evidence about
        which invoice the payment is for -- unlike creation order. So when exactly one
        candidate has it, that one is the match even though a second candidate shares its
        amount. Refusing here would be over-correcting.
        """
        member = member_with_customer(self, "MatchPri")
        inside_start = add_days(today(), -3)
        outside_start = add_months(today(), -2)
        inside = self._membership_invoice(member, 25.0, inside_start, add_days(inside_start, 27))
        self._membership_invoice(member, 25.0, outside_start, add_days(outside_start, 27))

        result = find_matching_invoice(member.name, getdate(today()), 25.0)

        self.assertTrue(result.found, "the invoice covering the payment date is a real match")
        self.assertEqual(result.invoice_name, inside.name)
        self.assertEqual(result.match_type, "exact_coverage")

    def test_the_refusal_reaches_the_error_log(self):
        """#567 asks that the refusal be VISIBLE, not logged into a void.

        `expectErrorLog` alone would not check this -- it is a suppression, so a test
        calling only that passes with the `log_error` deleted (PR #575 shipped six
        mis-titled rows through exactly that gap). The row is located by the customer
        name, which is unique to this test, because `tabError Log` is MyISAM and its rows
        outlive both the rollback and the run.
        """
        self.expectErrorLog("Invoice Match Ambiguous")
        member = member_with_customer(self, "MatchLog")
        customer = frappe.db.get_value("Member", member.name, "customer")
        older_start = add_months(today(), -2)
        newer_start = add_months(today(), -1)
        older = self._membership_invoice(member, 25.0, older_start, add_days(older_start, 27))
        newer = self._membership_invoice(member, 25.0, newer_start, add_days(newer_start, 27))

        result = find_matching_invoice(member.name, getdate(today()), 25.0)
        self.assertFalse(result.found)

        # NOT a bare "2" -- that is satisfied by "25.0", by the year, by an invoice
        # name. The count and the candidate NAMES are what an operator acts on, and the
        # names are the whole reason `InvoiceChoice` carries its rows.
        assert_error_log(
            self,
            "Invoice Match Ambiguous",
            customer,
            must_contain=(customer, "between 2 candidate", older.name, newer.name),
        )


class TestTheCalculatedCoverageStrategy(InvoiceMatcherBase):
    """Strategy 2 -- `_find_invoice_by_calculated_coverage`, the `get_value` pick.

    `frappe.db.get_value` with no `order_by` is `creation DESC`, so this silently
    returned the most recently created of however many invoices share the calculated
    window. There is no amount filter here at all.
    """

    def _calculated_window(self, member, payment_date):
        """The window the production calculator returns, asked rather than assumed.

        Hard-coding a window would make these tests pass or fail on whether this
        member's coverage sequence happens to be calendar-aligned, which is a property
        of the fixture, not of the code under test.
        """
        from verenigingen.services.billing.coverage_calculator import calculate_coverage_for_payment_date

        return calculate_coverage_for_payment_date(member.name, payment_date)

    def test_one_invoice_on_the_calculated_window_is_matched_whatever_the_amount(self):
        """The working case: a price change still matches on coverage alone.

        The payment (25.0) does not match the invoice (30.0), which is what keeps
        strategy 1 out of this test -- its SQL filter requires the amounts to agree
        within a cent.
        """
        member = member_with_customer(self, "CalcOne")
        payment_date = getdate(today())
        start, end = self._calculated_window(member, payment_date)
        invoice = self._membership_invoice(member, 30.0, start, end)

        result = find_matching_invoice(member.name, payment_date, 25.0)

        self.assertTrue(result.found, "one invoice on the calculated window is a match")
        self.assertEqual(result.invoice_name, invoice.name)
        self.assertEqual(result.match_type, "coverage_calculated")

    def test_two_invoices_sharing_the_calculated_window_are_refused(self):
        """The uniqueness assumption PR #575 cleared this site on, refuted by fixture.

        Two submitted, outstanding invoices on the same `(customer, coverage_start,
        coverage_end)`. The repo ships overlap detection because this state occurs; the
        pick was `creation DESC`.
        """
        member = member_with_customer(self, "CalcTwo")
        payment_date = getdate(today())
        start, end = self._calculated_window(member, payment_date)
        first = self._membership_invoice(member, 30.0, start, end)
        second = self._membership_invoice(member, 30.0, start, end)

        result = find_matching_invoice(member.name, payment_date, 25.0)

        self.assertFalse(
            result.found,
            f"two invoices share this coverage window; got {result.invoice_name}",
        )
        self.assertEqual(result.ambiguous_candidates, 2)
        self.assertIsNone(result.invoice_name, f"the old code returned {second.name}")


class TestARefusalDoesNotBecomeANewInvoice(InvoiceMatcherBase):
    """Recovery mode must not read a refusal as "nothing exists" (#578).

    `payment_processing_recovery.complete_partial_payments` calls
    `process_payment(create_missing_invoice=True)`, and `_resolve_invoice_fresh` fell
    straight from `not match_result.found` to `_create_invoice_if_safe`. A refusal is not
    "not found": with two equal-amount arrears invoices the calculated window is the NEXT
    period (measured here: 2026-08-22 to 2026-09-21), which overlaps neither, so the
    overlap guard permits the create and the member is billed a THIRD period for having
    paid, both arrears still open. Strictly worse than the arbitrary pick the refusal
    replaced, on the one path that is explicitly a money-mover.

    What is asserted is whether the CREATION PATH IS INVOKED, not whether a row appeared.
    Both gateway constructors on this path (`MolliePaymentOrchestrator.__init__` and
    `DuesPaymentProcessor.__init__`) build a `MollieClient`, which needs credentials this
    bench has and CI does not -- so a test that let the real creation run would take a
    different branch in CI than here, which is the parity trap CLAUDE.md documents. The
    recorder below stands in for exactly that credentialed boundary and nothing else:
    `find_matching_invoice`, `_resolve_invoice_fresh` and `_create_invoice_if_safe` are
    all real.
    """

    class _RecordingDuesProcessor:
        """Records the one call that would have created the third invoice."""

        def __init__(self):
            self.created_for = []

        def _get_or_create_historical_invoice(self, *args, **kwargs):
            self.created_for.append(kwargs or args)
            return "ACC-SINV-WOULD-HAVE-BEEN-CREATED"

    def _orchestrator(self, dues_processor):
        from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
            MolliePaymentOrchestrator,
        )

        class _NoClientOrchestrator(MolliePaymentOrchestrator):
            def __init__(self):
                # Deliberately not super().__init__(): that builds a MollieClient.
                self.dues_processor = dues_processor
                self._bank_config_cache = None

        return _NoClientOrchestrator()

    def test_recovery_mode_refuses_rather_than_creating_a_third_invoice(self):
        from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
            PaymentProcessingResult,
        )

        self.expectErrorLog("Invoice Match Ambiguous")
        member = member_with_customer(self, "NoCreate")
        older_start = add_months(today(), -2)
        newer_start = add_months(today(), -1)
        self._membership_invoice(member, 25.0, older_start, add_days(older_start, 27))
        self._membership_invoice(member, 25.0, newer_start, add_days(newer_start, 27))

        dues = self._RecordingDuesProcessor()
        result = PaymentProcessingResult(payment_id="tr_refusal_no_create")
        resolved = self._orchestrator(dues)._resolve_invoice_fresh(
            member_name=member.name,
            payment_date=getdate(today()),
            payment_amount=25.0,
            create_missing_invoice=True,
            result=result,
        )

        self.assertEqual(
            dues.created_for,
            [],
            "a refusal reached the invoice-CREATION path; that bills the member a third "
            "period for having paid, with both arrears still open",
        )
        self.assertIsNone(resolved, "a refusal must not resolve an invoice")
        self.assertTrue(
            any("Refused to choose between 2" in action for action in result.actions_taken),
            f"the refusal must be reported to the caller; got {result.actions_taken}",
        )
