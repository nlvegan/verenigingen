"""
Real-integration / pure-logic tests for
verenigingen/verenigingen_payments/utils/sepa_conflict_detector.py
(previously ~0% coverage).

The SEPAConflictDetector inspects a ``batch_data`` dict (``invoice_list``,
``batch_date``, ``batch_type``) and emits a list of ``ConflictResult`` objects
covering: empty batches, in-batch duplicate invoices, cross-batch invoice
assignments, membership-dues schedule timing, batch-date validity (weekend /
past / far-future / same-date), SEPA business rules (size / amount / zero /
B2B), SEPA mandate state (missing / inactive / expired / high-usage) and
amount reconciliation against the live Sales Invoice outstanding amount.

Most rules are pure-dict logic and are tested with hand-built invoice lists.
The DB-backed rules (cross-batch, schedule, same-date, mandate, amount) build
REAL Member / Customer / SEPA Mandate / Sales Invoice / Direct Debit Batch /
Membership Dues Schedule documents via SEPATestDataFactory. No business logic
is mocked. Date-sensitive assertions are made deterministic by computing batch
dates relative to ``today()`` rather than asserting ambient site state.

Tests run as Administrator, which satisfies the @critical_api /
@high_security_api gates on the module's API endpoints.
"""

import unittest

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.utils.sepa_conflict_detector import (
    ConflictResult,
    ConflictSeverity,
    SEPAConflictDetector,
    _generate_next_steps,
    _generate_recommendations,
    detect_batch_conflicts,
    validate_batch_with_conflicts,
)


def _next_weekday(reference, min_offset=1):
    """Return the first weekday (Mon-Fri) at least ``min_offset`` days ahead."""
    d = add_days(getdate(reference), min_offset)
    while getdate(d).weekday() >= 5:
        d = add_days(d, 1)
    return d


def _types(conflicts):
    return {c.conflict_type for c in conflicts}


def _by_type(conflicts, ctype):
    return [c for c in conflicts if c.conflict_type == ctype]


# ---------------------------------------------------------------------------
# Pure-logic tests (no DB fixtures needed)
# ---------------------------------------------------------------------------


class TestConflictDetectorPureLogic(unittest.TestCase):
    """Rules driven entirely by the in-memory batch_data dict."""

    def setUp(self):
        self.detector = SEPAConflictDetector()
        # A near-future weekday avoids weekend/past/far-future noise.
        self.good_date = _next_weekday(today(), 2)

    # --- empty batch / orchestrator short-circuit ---

    def test_empty_batch_returns_single_critical(self):
        conflicts = self.detector.detect_batch_creation_conflicts(
            {"invoice_list": [], "batch_date": self.good_date}
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].conflict_type, "empty_batch")
        self.assertEqual(conflicts[0].severity, ConflictSeverity.CRITICAL)

    def test_missing_invoice_list_key_treated_as_empty(self):
        conflicts = self.detector.detect_batch_creation_conflicts({})
        self.assertEqual([c.conflict_type for c in conflicts], ["empty_batch"])

    # --- in-batch duplicate detection ---

    def test_duplicate_invoice_within_batch(self):
        conflicts = self.detector._detect_invoice_duplicates(
            [{"invoice": "SI-1"}, {"invoice": "SI-2"}, {"invoice": "SI-1"}]
        )
        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c.conflict_type, "duplicate_invoice")
        self.assertEqual(c.severity, ConflictSeverity.CRITICAL)
        self.assertEqual(c.details["position"], 2)
        self.assertIn("SI-1", c.affected_resources)

    def test_no_duplicates_and_missing_ids_skipped(self):
        conflicts = self.detector._detect_invoice_duplicates(
            [{"invoice": "SI-1"}, {"invoice": None}, {}, {"invoice": "SI-2"}]
        )
        self.assertEqual(conflicts, [])

    # --- date conflicts ---

    def test_missing_batch_date_is_critical(self):
        conflicts = self.detector._detect_date_conflicts(None, "CORE")
        self.assertEqual([c.conflict_type for c in conflicts], ["missing_date"])
        self.assertEqual(conflicts[0].severity, ConflictSeverity.CRITICAL)

    def test_weekend_collection_warning(self):
        # Find next Saturday.
        d = add_days(today(), 1)
        while getdate(d).weekday() != 5:
            d = add_days(d, 1)
        conflicts = self.detector._detect_date_conflicts(d, "CORE")
        self.assertIn("weekend_collection", _types(conflicts))

    def test_past_date_is_critical(self):
        conflicts = self.detector._detect_date_conflicts(add_days(today(), -5), "CORE")
        types = _types(conflicts)
        self.assertIn("past_date", types)
        past = _by_type(conflicts, "past_date")[0]
        self.assertEqual(past.severity, ConflictSeverity.CRITICAL)
        self.assertEqual(past.details["days_ago"], 5)

    def test_far_future_date_warning(self):
        # 40 days ahead, forced onto a weekday so the only signal is far_future.
        d = _next_weekday(add_days(today(), 40), 0)
        conflicts = self.detector._detect_date_conflicts(d, "CORE")
        self.assertIn("far_future_date", _types(conflicts))

    def test_clean_near_future_weekday_has_no_date_signal(self):
        conflicts = self.detector._detect_date_conflicts(self.good_date, "CORE")
        # Only DB-backed same-date checks could fire; none of the date-validity ones.
        self.assertNotIn("weekend_collection", _types(conflicts))
        self.assertNotIn("past_date", _types(conflicts))
        self.assertNotIn("far_future_date", _types(conflicts))

    # --- business rules ---

    def test_batch_size_limit(self):
        big = [{"invoice": f"SI-{i}", "amount": 1} for i in range(10001)]
        conflicts = self.detector._detect_business_rule_conflicts({"invoice_list": big})
        size = _by_type(conflicts, "batch_size_limit")
        self.assertTrue(size)
        self.assertEqual(size[0].severity, ConflictSeverity.CRITICAL)
        self.assertEqual(size[0].details["limit"], 10000)

    def test_amount_limit(self):
        conflicts = self.detector._detect_business_rule_conflicts(
            {"invoice_list": [{"invoice": "SI-1", "amount": 1_000_000_000.0}]}
        )
        self.assertIn("amount_limit", _types(conflicts))

    def test_zero_amount_invoices_flagged(self):
        conflicts = self.detector._detect_business_rule_conflicts(
            {"invoice_list": [{"invoice": "SI-1", "amount": 0}, {"invoice": "SI-2", "amount": 10}]}
        )
        zero = _by_type(conflicts, "zero_amount")
        self.assertTrue(zero)
        self.assertEqual(zero[0].affected_resources, ["SI-1"])
        self.assertEqual(zero[0].severity, ConflictSeverity.WARNING)

    def test_negative_amount_counts_as_zero_amount(self):
        conflicts = self.detector._detect_business_rule_conflicts(
            {"invoice_list": [{"invoice": "SI-1", "amount": -5}]}
        )
        self.assertIn("zero_amount", _types(conflicts))

    def test_b2b_info_conflict(self):
        conflicts = self.detector._detect_business_rule_conflicts(
            {"invoice_list": [{"invoice": "SI-1", "amount": 10}], "batch_type": "B2B"}
        )
        b2b = _by_type(conflicts, "b2b_requirements")
        self.assertTrue(b2b)
        self.assertEqual(b2b[0].severity, ConflictSeverity.INFO)

    def test_core_batch_no_b2b_conflict(self):
        conflicts = self.detector._detect_business_rule_conflicts(
            {"invoice_list": [{"invoice": "SI-1", "amount": 10}], "batch_type": "CORE"}
        )
        self.assertNotIn("b2b_requirements", _types(conflicts))

    # --- mandate grouping with no mandate refs ---

    def test_mandate_conflicts_no_refs_returns_empty(self):
        conflicts = self.detector._detect_mandate_conflicts(
            [{"invoice": "SI-1"}, {"invoice": "SI-2"}]
        )
        self.assertEqual(conflicts, [])

    def test_mandate_not_found_when_ref_absent_from_db(self):
        # A mandate reference that does not exist in the DB -> mandate_not_found.
        ref = f"NONEXIST-{frappe.generate_hash(length=8)}"
        conflicts = self.detector._detect_mandate_conflicts(
            [{"invoice": "SI-1", "mandate_reference": ref}]
        )
        nf = _by_type(conflicts, "mandate_not_found")
        self.assertTrue(nf)
        self.assertEqual(nf[0].severity, ConflictSeverity.CRITICAL)
        self.assertEqual(nf[0].details["mandate_reference"], ref)

    # --- amount conflicts with no invoice names ---

    def test_amount_conflicts_no_invoices_returns_empty(self):
        self.assertEqual(self.detector._detect_amount_conflicts([{}, {"invoice": None}]), [])

    def test_amount_invoice_not_found(self):
        bogus = f"SI-MISSING-{frappe.generate_hash(length=8)}"
        conflicts = self.detector._detect_amount_conflicts([{"invoice": bogus, "amount": 10}])
        self.assertIn("invoice_not_found", _types(conflicts))

    # --- severity priority + report shaping ---

    def test_severity_priority_ordering(self):
        gsp = self.detector._get_severity_priority
        self.assertGreater(gsp(ConflictSeverity.CRITICAL), gsp(ConflictSeverity.WARNING))
        self.assertGreater(gsp(ConflictSeverity.WARNING), gsp(ConflictSeverity.INFO))

    def test_report_no_conflicts(self):
        report = self.detector.generate_conflict_report([])
        self.assertFalse(report["has_conflicts"])
        self.assertTrue(report["can_proceed"])
        self.assertEqual(report["conflicts"], [])

    def test_report_with_mixed_conflicts(self):
        conflicts = [
            ConflictResult(ConflictSeverity.CRITICAL, "duplicate_invoice", "m", ["a"], "fix", {}),
            ConflictResult(ConflictSeverity.WARNING, "weekend_collection", "m", [], "fix", {}),
            ConflictResult(ConflictSeverity.INFO, "b2b_requirements", "m", [], "fix", {}),
        ]
        report = self.detector.generate_conflict_report(conflicts)
        self.assertTrue(report["has_conflicts"])
        self.assertFalse(report["can_proceed"])  # has a critical
        self.assertEqual(report["critical_count"], 1)
        self.assertEqual(report["warning_count"], 1)
        self.assertEqual(report["info_count"], 1)
        self.assertEqual(len(report["conflicts"]), 3)
        # Serialized severities are the enum .value strings.
        self.assertEqual(report["conflicts"][0]["severity"], "critical")

    def test_report_warning_only_can_proceed(self):
        conflicts = [
            ConflictResult(ConflictSeverity.WARNING, "weekend_collection", "m", [], "fix", {})
        ]
        report = self.detector.generate_conflict_report(conflicts)
        self.assertTrue(report["can_proceed"])
        self.assertEqual(report["warning_count"], 1)

    # --- recommendation / next-step generators ---

    def test_recommendations_for_each_critical_type(self):
        conflicts = [
            ConflictResult(ConflictSeverity.CRITICAL, "duplicate_invoice", "m", [], "", {}),
            ConflictResult(ConflictSeverity.CRITICAL, "cross_batch_conflict", "m", [], "", {}),
            ConflictResult(ConflictSeverity.CRITICAL, "amount_mismatch", "m", [], "", {}),
            ConflictResult(ConflictSeverity.CRITICAL, "expired_mandate", "m", [], "", {}),
        ]
        recs = _generate_recommendations(conflicts)
        joined = " ".join(recs)
        self.assertIn("Resolve all critical conflicts", joined)
        self.assertIn("duplicate", joined)
        self.assertIn("other batches", joined)
        self.assertIn("Refresh invoice data", joined)
        self.assertIn("SEPA mandates", joined)

    def test_recommendations_empty_when_no_critical(self):
        conflicts = [ConflictResult(ConflictSeverity.WARNING, "weekend_collection", "m", [], "", {})]
        self.assertEqual(_generate_recommendations(conflicts), [])

    def test_next_steps_critical(self):
        conflicts = [ConflictResult(ConflictSeverity.CRITICAL, "duplicate_invoice", "m", [], "", {})]
        steps = _generate_next_steps(conflicts)
        self.assertTrue(any("Address all critical" in s for s in steps))

    def test_next_steps_warning_only(self):
        conflicts = [ConflictResult(ConflictSeverity.WARNING, "weekend_collection", "m", [], "", {})]
        steps = _generate_next_steps(conflicts)
        self.assertTrue(any("Review warnings" in s for s in steps))

    def test_next_steps_clean(self):
        steps = _generate_next_steps([])
        self.assertTrue(any("No critical conflicts detected" in s for s in steps))


# ---------------------------------------------------------------------------
# DB-backed tests (real fixtures)
# ---------------------------------------------------------------------------


class TestConflictDetectorWithFixtures(EnhancedTestCase):
    """Rules that query the database for real SEPA documents."""

    def setUp(self):
        super().setUp()
        self.factory = SEPATestDataFactory(seed=12345, use_faker=True)
        self.detector = SEPAConflictDetector()
        self.good_date = _next_weekday(today(), 2)

    # --- helpers ---

    def _make_member_with_mandate(self, status="Active", expiry_date=None):
        member = self.factory.create_test_member()
        # create_test_member already auto-creates and links a Customer
        # (Customer.member is UNIQUE). Reuse it rather than creating a second
        # customer, which would violate the unique back-link.
        customer_name = member.customer
        if not customer_name:
            customer_name = self.factory.create_test_customer(
                customer_name=f"Cust {member.full_name}"
            ).name
            member.db_set("customer", customer_name)
        frappe.db.set_value("Customer", customer_name, "member", member.name)
        customer = frappe.get_doc("Customer", customer_name)
        mandate = self.factory.create_test_sepa_mandate(
            member=member.name, status=status, expiry_date=expiry_date
        )
        return member, customer, mandate

    def _make_submitted_invoice(self, customer, member, amount=25.0, status="Unpaid"):
        return self.factory.create_test_sales_invoice(
            customer=customer.name, member=member, grand_total=amount, status=status, submit=True
        )

    # --- mandate conflicts (real SEPA Mandate) ---

    def test_active_mandate_no_conflict(self):
        _, _, mandate = self._make_member_with_mandate(status="Active")
        conflicts = self.detector._detect_mandate_conflicts(
            [{"invoice": "SI-X", "mandate_reference": mandate.mandate_id}]
        )
        self.assertEqual(
            {c.conflict_type for c in conflicts} & {"mandate_not_found", "inactive_mandate", "expired_mandate"},
            set(),
        )

    def test_inactive_mandate_conflict(self):
        _, _, mandate = self._make_member_with_mandate(status="Suspended")
        conflicts = self.detector._detect_mandate_conflicts(
            [{"invoice": "SI-X", "mandate_reference": mandate.mandate_id}]
        )
        inactive = _by_type(conflicts, "inactive_mandate")
        self.assertTrue(inactive)
        self.assertEqual(inactive[0].severity, ConflictSeverity.CRITICAL)
        self.assertEqual(inactive[0].details["status"], "Suspended")

    def test_expired_mandate_conflict(self):
        # Active but past expiry_date -> expired_mandate fires (independent of status).
        _, _, mandate = self._make_member_with_mandate(
            status="Active", expiry_date=add_days(today(), -1)
        )
        conflicts = self.detector._detect_mandate_conflicts(
            [{"invoice": "SI-X", "mandate_reference": mandate.mandate_id}]
        )
        self.assertIn("expired_mandate", _types(conflicts))

    def test_high_mandate_usage_warning(self):
        _, _, mandate = self._make_member_with_mandate(status="Active")
        invoices = [
            {"invoice": f"SI-{i}", "mandate_reference": mandate.mandate_id} for i in range(51)
        ]
        conflicts = self.detector._detect_mandate_conflicts(invoices)
        usage = _by_type(conflicts, "high_mandate_usage")
        self.assertTrue(usage)
        self.assertEqual(usage[0].details["usage_count"], 51)
        self.assertEqual(usage[0].severity, ConflictSeverity.WARNING)

    # --- amount conflicts (real Sales Invoice) ---

    def test_amount_match_no_conflict(self):
        _, customer, _ = self._make_member_with_mandate()
        member = frappe.get_doc("Customer", customer.name).member
        inv = self._make_submitted_invoice(customer, member, amount=25.0, status="Unpaid")
        conflicts = self.detector._detect_amount_conflicts(
            [{"invoice": inv.name, "amount": 25.0}]
        )
        self.assertNotIn("amount_mismatch", _types(conflicts))
        self.assertNotIn("invalid_status", _types(conflicts))

    def test_amount_mismatch_conflict(self):
        _, customer, _ = self._make_member_with_mandate()
        member = frappe.get_doc("Customer", customer.name).member
        inv = self._make_submitted_invoice(customer, member, amount=25.0, status="Unpaid")
        conflicts = self.detector._detect_amount_conflicts(
            [{"invoice": inv.name, "amount": 99.0}]
        )
        mismatch = _by_type(conflicts, "amount_mismatch")
        self.assertTrue(mismatch)
        self.assertEqual(mismatch[0].severity, ConflictSeverity.CRITICAL)
        self.assertAlmostEqual(mismatch[0].details["requested_amount"], 99.0)

    def test_invalid_status_conflict(self):
        # A submitted, fully-paid invoice (status Paid) -> invalid_status.
        _, customer, _ = self._make_member_with_mandate()
        member = frappe.get_doc("Customer", customer.name).member
        inv = self.factory.create_test_sales_invoice(
            customer=customer.name, member=member, grand_total=25.0, status="Unpaid", submit=True
        )
        # Force-set to a non-collectable status directly on the submitted doc.
        frappe.db.set_value("Sales Invoice", inv.name, "status", "Paid")
        frappe.db.set_value("Sales Invoice", inv.name, "outstanding_amount", 0)
        conflicts = self.detector._detect_amount_conflicts(
            [{"invoice": inv.name, "amount": 0}]
        )
        self.assertIn("invalid_status", _types(conflicts))

    # --- cross-batch conflicts (real Direct Debit Batch) ---

    def test_cross_batch_draft_is_critical(self):
        batch = self.factory.create_test_direct_debit_batch(
            batch_date=self.good_date, invoice_count=1, status="Draft"
        )
        invoice_name = batch.invoices[0].invoice
        conflicts = self.detector._detect_cross_batch_conflicts([{"invoice": invoice_name}])
        cross = _by_type(conflicts, "cross_batch_conflict")
        self.assertTrue(cross)
        self.assertEqual(cross[0].severity, ConflictSeverity.CRITICAL)
        self.assertEqual(cross[0].details["conflicting_batch"], batch.name)

    def test_cross_batch_clean_invoice_no_conflict(self):
        # An invoice not in any batch -> no cross-batch conflict.
        conflicts = self.detector._detect_cross_batch_conflicts(
            [{"invoice": f"SI-UNBATCHED-{frappe.generate_hash(length=8)}"}]
        )
        self.assertEqual(_by_type(conflicts, "cross_batch_conflict"), [])

    # --- same-date batch (real Direct Debit Batch) ---

    def test_same_date_batch_warning(self):
        batch = self.factory.create_test_direct_debit_batch(
            batch_date=self.good_date, invoice_count=1, status="Draft"
        )
        conflicts = self.detector._detect_date_conflicts(self.good_date, "CORE")
        same = _by_type(conflicts, "same_date_batch")
        self.assertTrue(same)
        self.assertEqual(same[0].details["existing_batch"], batch.name)

    # --- schedule overlap (real Sales Invoice + Membership Dues Schedule) ---

    def test_schedule_early_collection_warning(self):
        _, customer, _ = self._make_member_with_mandate()
        member = frappe.get_doc("Customer", customer.name).member
        self.factory.create_test_membership(member=member)
        # Schedule next due far in the future; collect now -> >30 days early.
        # The factory may reuse the membership's auto-created Active schedule, so
        # force the next_invoice_date directly to make the timing deterministic.
        schedule = self.factory.create_test_membership_dues_schedule(
            member=member, payment_terms_template=None
        )
        frappe.db.set_value(
            "Membership Dues Schedule", schedule.name, "next_invoice_date", add_days(today(), 60)
        )
        inv = self.factory.create_test_sales_invoice(
            customer=customer.name,
            member=member,
            grand_total=25.0,
            status="Unpaid",
            submit=True,
            membership_dues_schedule_display=schedule.name,
        )
        conflicts = self.detector._detect_schedule_overlaps([{"invoice": inv.name}], today())
        self.assertIn("early_collection", _types(conflicts))

    def test_schedule_late_collection_warning(self):
        _, customer, _ = self._make_member_with_mandate()
        member = frappe.get_doc("Customer", customer.name).member
        self.factory.create_test_membership(member=member)
        schedule = self.factory.create_test_membership_dues_schedule(
            member=member, payment_terms_template=None
        )
        frappe.db.set_value(
            "Membership Dues Schedule", schedule.name, "next_invoice_date", add_days(today(), -120)
        )
        inv = self.factory.create_test_sales_invoice(
            customer=customer.name,
            member=member,
            grand_total=25.0,
            status="Unpaid",
            submit=True,
            membership_dues_schedule_display=schedule.name,
        )
        conflicts = self.detector._detect_schedule_overlaps([{"invoice": inv.name}], today())
        self.assertIn("late_collection", _types(conflicts))

    def test_schedule_no_batch_date_returns_empty(self):
        self.assertEqual(self.detector._detect_schedule_overlaps([{"invoice": "SI-1"}], None), [])

    # --- full orchestrator integration + report + API endpoints ---

    def test_full_orchestrator_clean_batch(self):
        _, customer, mandate = self._make_member_with_mandate()
        member = frappe.get_doc("Customer", customer.name).member
        inv = self._make_submitted_invoice(customer, member, amount=25.0, status="Unpaid")
        batch_data = {
            "invoice_list": [
                {"invoice": inv.name, "amount": 25.0, "mandate_reference": mandate.mandate_id}
            ],
            "batch_date": self.good_date,
            "batch_type": "CORE",
        }
        conflicts = self.detector.detect_batch_creation_conflicts(batch_data)
        # No CRITICAL conflicts for a fully consistent batch.
        criticals = [c for c in conflicts if c.severity == ConflictSeverity.CRITICAL]
        self.assertEqual(criticals, [], msg=[c.conflict_type for c in criticals])
        report = self.detector.generate_conflict_report(conflicts)
        self.assertTrue(report["can_proceed"])

    def test_full_orchestrator_sorted_by_severity(self):
        # Past date (critical) + zero amount (warning) -> critical sorts first.
        batch_data = {
            "invoice_list": [{"invoice": "SI-1", "amount": 0}],
            "batch_date": add_days(today(), -3),
            "batch_type": "CORE",
        }
        conflicts = self.detector.detect_batch_creation_conflicts(batch_data)
        self.assertTrue(conflicts)
        self.assertEqual(conflicts[0].severity, ConflictSeverity.CRITICAL)

    def test_detect_batch_conflicts_api_empty(self):
        # Empty invoice_list -> the API reports the empty_batch critical conflict.
        report = detect_batch_conflicts(invoice_list=[], batch_date=self.good_date)
        self.assertTrue(report["has_conflicts"])
        self.assertFalse(report["can_proceed"])
        self.assertEqual(report["conflicts"][0]["type"], "empty_batch")

    def test_detect_batch_conflicts_api_clean(self):
        _, customer, mandate = self._make_member_with_mandate()
        member = frappe.get_doc("Customer", customer.name).member
        inv = self._make_submitted_invoice(customer, member, amount=25.0, status="Unpaid")
        report = detect_batch_conflicts(
            invoice_list=[
                {"invoice": inv.name, "amount": 25.0, "mandate_reference": mandate.mandate_id}
            ],
            batch_date=self.good_date,
            batch_type="CORE",
        )
        self.assertTrue(report["can_proceed"])

    def test_validate_batch_with_conflicts_api(self):
        result = validate_batch_with_conflicts(
            invoice_list=[{"invoice": "SI-1"}, {"invoice": "SI-1"}],
            batch_date=self.good_date,
        )
        self.assertFalse(result["validation_passed"])  # duplicate is critical
        self.assertIn("conflict_report", result)
        self.assertIn("recommendations", result)
        self.assertIn("next_steps", result)


if __name__ == "__main__":
    unittest.main()
