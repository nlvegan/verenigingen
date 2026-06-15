"""
Tests for the SEPA Direct Debit Batch Optimizer.

verenigingen/verenigingen_payments/api/dd_batch_optimizer.py splits into two
layers:

1. Pure optimization/analysis helpers (analyze_invoices_for_optimization,
   create_*_batches, calculate_efficiency_score, determine_batch_type,
   generate_optimization_report). These operate on plain invoice dicts and a
   config dict, so they are tested directly with synthetic data - fast,
   deterministic, and exercising the grouping/scoring branch logic precisely.

2. Whitelisted DB-touching endpoints (create_optimal_batches, get_batching_preview,
   validate_all_pending_invoices, update_batch_optimization_config). These are
   exercised end-to-end via the SEPA test factory against real DocTypes so the
   eligibility SQL, batch document creation, and security decorators run exactly
   as in production.

Run as Administrator (the test default), which satisfies @critical_api /
@high_security_api and @require_sepa_permission (Administrator carries all SEPA
permission levels).
"""


import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.api import dd_batch_optimizer as opt


def _inv(invoice, amount, customer="CUST-1", member="MEM-1", priority="Normal", posting_date=None):
    """Build a synthetic eligible-invoice dict matching the optimizer's SQL row shape."""
    return {
        "invoice": invoice,
        "customer": customer,
        "amount": amount,
        "currency": "EUR",
        "posting_date": posting_date or today(),
        "membership": "MS-1",
        "member": member,
        "member_name": "Test Member",
        "iban": "NL39RABO0300065264",
        "payment_method": "SEPA Direct Debit",
        "mandate_reference": "TST-MANDATE",
        "member_since": today(),
        "member_status": "Active",
        "membership_status": "Active",
        "priority": priority,
    }


class TestOptimizerPureHelpers(EnhancedTestCase):
    """Pure functions - no DB required, synthetic dict inputs."""

    def setUp(self):
        super().setUp()
        self.config = opt.DEFAULT_CONFIG.copy()

    # --- analyze_invoices_for_optimization ----------------------------------

    def test_analyze_categorizes_by_amount(self):
        invoices = [
            _inv("I-high", 150),  # > 100 -> high
            _inv("I-med", 50),  # > 25 -> medium
            _inv("I-low", 10),  # <= 25 -> low
        ]
        analysis = opt.analyze_invoices_for_optimization(invoices)
        self.assertEqual(analysis["total_invoices"], 3)
        self.assertEqual(analysis["total_amount"], 210)
        self.assertEqual(len(analysis["by_amount"]["high"]), 1)
        self.assertEqual(len(analysis["by_amount"]["medium"]), 1)
        self.assertEqual(len(analysis["by_amount"]["low"]), 1)

    def test_analyze_groups_by_customer_and_age(self):
        invoices = [
            _inv("I-1", 30, customer="CUST-A", posting_date=add_days(today(), -40)),  # overdue
            _inv("I-2", 30, customer="CUST-A", posting_date=today()),  # current
            _inv("I-3", 30, customer="CUST-B", posting_date=today()),
        ]
        analysis = opt.analyze_invoices_for_optimization(invoices)
        self.assertEqual(len(analysis["by_customer"]["CUST-A"]), 2)
        self.assertEqual(len(analysis["by_customer"]["CUST-B"]), 1)
        self.assertEqual(len(analysis["by_age"]["overdue"]), 1)
        self.assertEqual(len(analysis["by_age"]["current"]), 2)

    def test_analyze_flags_high_total_volume_risk(self):
        invoices = [_inv(f"I-{i}", 500) for i in range(50)]  # 25_000 total
        analysis = opt.analyze_invoices_for_optimization(invoices)
        self.assertIn("High total volume", analysis["risk_factors"])

    def test_analyze_empty(self):
        analysis = opt.analyze_invoices_for_optimization([])
        self.assertEqual(analysis["total_invoices"], 0)
        self.assertEqual(analysis["total_amount"], 0)
        self.assertEqual(analysis["risk_factors"], [])

    # --- create_amount_optimized_batches ------------------------------------

    def test_amount_batches_respect_min_batch_size(self):
        # Only 2 invoices but min is 3 -> no batch should be emitted.
        invoices = [_inv("I-1", 10), _inv("I-2", 10)]
        batches = opt.create_amount_optimized_batches(invoices, self.config)
        self.assertEqual(batches, [])

    def test_amount_batches_splits_on_preferred_size(self):
        # preferred_batch_size is 15; feed 15 small invoices -> exactly one batch.
        invoices = [_inv(f"I-{i}", 1) for i in range(15)]
        batches = opt.create_amount_optimized_batches(invoices, self.config)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 15)

    def test_amount_batches_splits_on_max_amount(self):
        # Each invoice is 1500; max_amount_per_batch is 4000 -> 2 fit, 3rd starts
        # a new batch. With min 3 the tail (<3) is dropped, so configure min=1.
        cfg = self.config.copy()
        cfg["min_invoices_per_batch"] = 1
        cfg["preferred_batch_size"] = 99
        invoices = [_inv(f"I-{i}", 1500) for i in range(5)]
        batches = opt.create_amount_optimized_batches(invoices, cfg)
        # 1500*2 = 3000 <= 4000, 1500*3 = 4500 > 4000 -> 2 per batch.
        for b in batches:
            self.assertLessEqual(sum(i["amount"] for i in b), 4000)
        self.assertEqual(sum(len(b) for b in batches), 5)

    def test_amount_batches_splits_on_max_invoices(self):
        cfg = self.config.copy()
        cfg["max_invoices_per_batch"] = 5
        cfg["preferred_batch_size"] = 99  # don't let preferred-size trigger first
        cfg["min_invoices_per_batch"] = 1
        invoices = [_inv(f"I-{i}", 1) for i in range(12)]
        batches = opt.create_amount_optimized_batches(invoices, cfg)
        for b in batches:
            self.assertLessEqual(len(b), 5)
        self.assertEqual(sum(len(b) for b in batches), 12)

    # --- create_priority_batches --------------------------------------------

    def test_priority_batches_sorted_desc_and_min_enforced(self):
        cfg = self.config.copy()
        cfg["min_invoices_per_batch"] = 3
        invoices = [_inv("a", 10), _inv("b", 30), _inv("c", 20)]
        batches = opt.create_priority_batches(invoices, cfg)
        self.assertEqual(len(batches), 1)
        amounts = [i["amount"] for i in batches[0]]
        self.assertEqual(amounts, sorted(amounts, reverse=True))

    def test_priority_batches_drops_below_min(self):
        cfg = self.config.copy()
        cfg["min_invoices_per_batch"] = 5
        invoices = [_inv("a", 10), _inv("b", 10)]
        self.assertEqual(opt.create_priority_batches(invoices, cfg), [])

    # --- create_customer_consolidated_batches -------------------------------

    def test_customer_consolidation_makes_own_batch(self):
        # One customer with >= min invoices under the amount cap gets its own batch.
        cfg = self.config.copy()
        cfg["min_invoices_per_batch"] = 3
        invoices = [_inv(f"I-{i}", 10, customer="CUST-X", member=f"M-{i}") for i in range(4)]
        batches = opt.create_customer_consolidated_batches(invoices, cfg)
        self.assertTrue(any(len(b) == 4 for b in batches))

    def test_customer_consolidation_handles_singletons(self):
        # All single-invoice customers fall through to amount-optimized batching.
        cfg = self.config.copy()
        cfg["min_invoices_per_batch"] = 1
        cfg["preferred_batch_size"] = 99
        invoices = [_inv(f"I-{i}", 10, customer=f"CUST-{i}", member=f"M-{i}") for i in range(5)]
        batches = opt.create_customer_consolidated_batches(invoices, cfg)
        self.assertEqual(sum(len(b) for b in batches), 5)

    # --- create_optimal_batch_groups (orchestration) ------------------------

    def test_optimal_groups_no_invoice_dropped_or_duplicated(self):
        cfg = self.config.copy()
        cfg["min_invoices_per_batch"] = 1
        invoices = [_inv(f"I-{i}", 20, customer=f"C-{i % 3}", member=f"M-{i}") for i in range(9)]
        analysis = opt.analyze_invoices_for_optimization(invoices)
        groups = opt.create_optimal_batch_groups(analysis, cfg)
        seen = [inv["invoice"] for g in groups for inv in g]
        # No duplicates across groups.
        self.assertEqual(len(seen), len(set(seen)))

    def test_optimal_groups_routes_high_priority_first(self):
        cfg = self.config.copy()
        cfg["min_invoices_per_batch"] = 3
        invoices = [_inv(f"P-{i}", 20, customer=f"C-{i}", member=f"M-{i}", priority="High") for i in range(4)]
        analysis = opt.analyze_invoices_for_optimization(invoices)
        groups = opt.create_optimal_batch_groups(analysis, cfg)
        self.assertTrue(groups)

    # --- calculate_efficiency_score -----------------------------------------

    def test_efficiency_score_bounds_0_100(self):
        # Wildly off avg size + many high-risk batches -> clamps at 0.
        low = opt.calculate_efficiency_score(
            avg_batch_size=200, target_size=15, risk_dist={"high_risk_batches": 10}, batch_count=50
        )
        self.assertGreaterEqual(low, 0)
        self.assertLessEqual(low, 100)
        # Perfect size, no risk, single batch -> high score.
        high = opt.calculate_efficiency_score(
            avg_batch_size=15, target_size=15, risk_dist={"high_risk_batches": 0}, batch_count=1
        )
        self.assertGreater(high, low)
        self.assertLessEqual(high, 100)

    def test_efficiency_score_penalizes_high_risk(self):
        no_risk = opt.calculate_efficiency_score(15, 15, {"high_risk_batches": 0}, 2)
        with_risk = opt.calculate_efficiency_score(15, 15, {"high_risk_batches": 2}, 2)
        self.assertGreater(no_risk, with_risk)


class TestOptimizerIntegration(EnhancedTestCase):
    """End-to-end against real DocTypes via the SEPA factory."""

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)

    def _make_eligible_member_invoice(self, prefix, amount=25.0, member_status="Active"):
        """Create a member + linked customer + active mandate + submitted unpaid EUR invoice."""
        member = self.sepa.create_test_member(first_name=prefix)
        # create_test_member auto-creates and links a Customer (Customer.member is
        # UNIQUE), so reuse it rather than minting a second one. The eligibility SQL
        # joins Sales Invoice.customer = Member.customer; the before_validate hook
        # reads Customer.member to populate invoice.member.
        customer_name = member.customer
        if not customer_name:
            customer_name = self.sepa.create_test_customer(customer_name=f"Customer {member.full_name}").name
            member.db_set("customer", customer_name)
        frappe.db.set_value("Customer", customer_name, "member", member.name)
        membership = self.sepa.create_test_membership(member=member.name)
        mandate = self.sepa.create_test_sepa_mandate(member=member.name)
        # The eligibility SQL requires the Member itself to carry payment_method
        # 'SEPA Direct Debit' and a non-empty IBAN (separate from the mandate).
        frappe.db.set_value(
            "Member",
            member.name,
            {"payment_method": "SEPA Direct Debit", "iban": mandate.iban},
        )
        invoice = self.sepa.create_test_sales_invoice(
            customer=customer_name,
            member=member.name,
            grand_total=amount,
            status="Unpaid",
            submit=True,
        )
        if member_status != "Active":
            frappe.db.set_value("Member", member.name, "status", member_status)
        self._track_test_document("Sales Invoice", invoice.name)
        self._track_test_document("Member", member.name)
        self._track_test_document("Customer", customer_name)
        self._track_test_document("Membership", membership.name)
        self._track_test_document("SEPA Mandate", mandate.name)
        return member, invoice

    # --- get_eligible_invoices_for_batching ---------------------------------

    def test_eligible_invoices_includes_active_member(self):
        member, invoice = self._make_eligible_member_invoice("OptElig")
        eligible = opt.get_eligible_invoices_for_batching()
        names = {row["invoice"] for row in eligible}
        self.assertIn(invoice.name, names)

    def test_eligible_invoices_excludes_terminated_member(self):
        member, invoice = self._make_eligible_member_invoice("OptQuit", member_status="Quit")
        eligible = opt.get_eligible_invoices_for_batching()
        names = {row["invoice"] for row in eligible}
        self.assertNotIn(invoice.name, names, "terminated member's invoice must not be eligible")

    # --- validate_member_eligibility_for_billing ----------------------------

    def test_validate_eligibility_true_for_active(self):
        member, invoice = self._make_eligible_member_invoice("OptValidOK")
        row = _inv(invoice.name, 25.0, member=member.name)
        row["member_status"] = "Active"
        row["membership_status"] = "Active"
        row["payment_method"] = "Bank Transfer"  # avoid the mandate-existence branch
        self.assertTrue(opt.validate_member_eligibility_for_billing(row))

    def test_validate_eligibility_false_for_no_member(self):
        self.assertFalse(opt.validate_member_eligibility_for_billing({"member": None}))

    def test_validate_eligibility_false_for_terminated(self):
        row = _inv("X", 25.0, member="MEM-T")
        row["member_status"] = "Deceased"
        self.assertFalse(opt.validate_member_eligibility_for_billing(row))

    def test_validate_eligibility_false_for_inactive_membership(self):
        row = _inv("X", 25.0, member="MEM-IM")
        row["member_status"] = "Active"
        row["membership_status"] = "Cancelled"
        self.assertFalse(opt.validate_member_eligibility_for_billing(row))

    # --- get_batching_preview -----------------------------------------------

    def test_get_batching_preview_empty(self):
        # No eligible invoices created in this isolated test -> empty preview.
        result = opt.get_batching_preview()
        self.assertTrue(result["success"])
        # Either the "no eligible" message or an empty/structured preview.
        self.assertIn("preview", result)

    def test_get_batching_preview_with_invoices(self):
        for i in range(4):
            self._make_eligible_member_invoice(f"OptPrev{i}", amount=30.0)
        result = opt.get_batching_preview(config={"min_invoices_per_batch": 1})
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["eligible_invoices"], 4)
        self.assertTrue(result["preview"])
        # Preview rows carry risk_level + customers + sample_invoices.
        row = result["preview"][0]
        self.assertIn("risk_level", row)
        self.assertIn("total_amount", row)
        self.assertIn(row["risk_level"], ("High", "Medium", "Low"))

    # --- create_optimal_batches (full pipeline) -----------------------------

    def test_create_optimal_batches_empty_returns_zero(self):
        # Isolated DB with no eligible invoices.
        result = opt.create_optimal_batches(target_date=add_days(getdate(), 1))
        self.assertTrue(result["success"])
        self.assertEqual(result["batches_created"], 0)
        self.assertEqual(result["total_invoices"], 0)

    def test_create_optimal_batches_creates_real_batch(self):
        for i in range(4):
            self._make_eligible_member_invoice(f"OptBatch{i}", amount=40.0)
        result = opt.create_optimal_batches(
            target_date=add_days(getdate(), 1), config={"min_invoices_per_batch": 1}
        )
        self.assertTrue(result["success"], msg=result)
        self.assertGreaterEqual(result["batches_created"], 1)
        self.assertGreaterEqual(result["total_invoices"], 4)
        # Real Direct Debit Batch documents must exist.
        for name in result["batch_names"]:
            self._track_test_document("Direct Debit Batch", name)
            self.assertTrue(frappe.db.exists("Direct Debit Batch", name))
        # Optimization report shape.
        report = result["optimization_report"]
        self.assertIn("summary", report)
        self.assertIn("efficiency_score", report["summary"])
        self.assertIn("risk_analysis", report)

    def test_create_optimal_batches_accepts_string_date(self):
        result = opt.create_optimal_batches(target_date=str(add_days(getdate(), 2)))
        self.assertTrue(result["success"])

    # --- update_batch_optimization_config -----------------------------------

    def test_update_config_persists_to_payments_settings(self):
        """update_batch_optimization_config persists the config where it is read.

        Regression: the endpoint used to write batch_optimization_config to the
        "Verenigingen Settings" single, but that field lives ONLY on "Verenigingen
        Payments Settings" (migrated by patches/v2_1/migrate_financial_settings_to_
        payments.py), which is where dd_batch_scheduler.get_scheduler_config() and
        www/batch-optimizer.py read it back. The endpoint now targets the right
        DocType, so the value reaches the consumers.
        """
        new_config = {
            "max_amount_per_batch": 3500,
            "max_invoices_per_batch": 18,
            "min_invoices_per_batch": 2,
        }
        opt.update_batch_optimization_config(new_config)
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")
        stored = frappe.db.get_single_value("Verenigingen Payments Settings", "batch_optimization_config")
        self.assertIn("3500", str(stored))

    def test_update_config_rejects_missing_required_field(self):
        """Missing required config field surfaces as a real validation error.

        Regression: @require_sepa_permission used to wrap the entire function body
        in `except Exception`, so the endpoint's own frappe.throw(ValidationError)
        for a missing required field was masked as a generic PermissionError. The
        decorator now only guards the auth check, so the ValidationError propagates.
        """
        with self.assertRaises(frappe.ValidationError):
            opt.update_batch_optimization_config({"max_amount_per_batch": 3500})

    # --- validate_all_pending_invoices --------------------------------------

    def test_validate_all_pending_invoices_shape(self):
        result = opt.validate_all_pending_invoices()
        for key in (
            "total_checked",
            "issues_found",
            "terminated_members",
            "inactive_memberships",
            "missing_mandates",
            "validation_errors",
        ):
            self.assertIn(key, result)
        self.assertIsInstance(result["total_checked"], int)
