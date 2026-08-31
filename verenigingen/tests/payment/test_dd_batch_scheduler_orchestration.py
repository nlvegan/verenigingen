"""
Orchestration-layer tests for the SEPA Direct Debit Batch Scheduler.

verenigingen/verenigingen_payments/api/dd_batch_scheduler.py has two layers:

1. Pure date / config / validation helpers (is_bank_holiday, _weekday_number,
   should_skip_batch_creation, get_next_business_day, validate_batch_creation_days,
   get_scheduler_config, get_batch_creation_schedule). Those are already covered by
   verenigingen/tests/sepa/test_dd_batch_scheduler.py and are NOT duplicated here.

2. The ORCHESTRATION layer (covered here): daily_batch_optimization() and its
   advisory-lock wrapper, run_batch_creation_now(), get_batch_optimization_stats(),
   and the notification builders (send_batch_creation_notification /
   create_system_notification).

Tests run as Administrator (the test default), which satisfies the
@critical_api / @require_sepa_permission gates.

Mocking policy (Tier-2 integration): only true external boundaries are patched -
the advisory lock (get_lock / release_lock), background enqueue/email/notification
side-channels, and the lazily-imported sepa_batch_notifications senders. The
branch selectors is_batch_creation_day / should_skip_batch_creation are flipped
to drive the orchestration branches deterministically, but on the SUCCESS path
the real create_optimal_batches runs against real eligible invoices so an actual
Direct Debit Batch is created. No business logic is mocked.

Two tests pin recently-fixed bugs:
    - run_batch_creation_now used add_days(..., hours=-1) (add_days has no hours
      kwarg) -> now add_to_date(..., hours=-1). With eligible data it must succeed
      and not raise a "hours" TypeError.
    - get_batch_optimization_stats computed success_rate from a non-existent
      b.workflow_state field (always 0) -> now reads b.status. Processed batches
      must drive success_rate > 0.
"""

from unittest.mock import patch

import frappe
from frappe.utils import getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.api import dd_batch_scheduler as sched

NOTIF_MODULE = "verenigingen.verenigingen_payments.api.sepa_batch_notifications"


class _SchedulerOrchestrationBase(EnhancedTestCase):
    """Shared eligible-data builder, mirroring the optimizer integration suite."""

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)

    def _make_eligible_member_invoice(self, prefix, amount=25.0):
        """Create a member + linked customer + active mandate + submitted unpaid EUR invoice."""
        member = self.sepa.create_test_member(first_name=prefix)
        customer_name = member.customer
        if not customer_name:
            customer_name = self.sepa.create_test_customer(
                customer_name=f"Customer {member.full_name}"
            ).name
            member.db_set("customer", customer_name)
        frappe.db.set_value("Customer", customer_name, "member", member.name)
        membership = self.sepa.create_test_membership(member=member.name)
        # Link the invoice to its dues schedule. Since #616 the eligibility SQL
        # reaches Membership through `si.membership_dues_schedule_display ->
        # mds.membership` instead of "any Active membership of this member", so an
        # invoice with no schedule is not a dues invoice and is not batched.
        # `Membership.on_submit` already created the schedule; reuse it.
        schedule = self.sepa.create_test_membership_dues_schedule(
            member=member.name, payment_terms_template="SEPA Direct Debit"
        )
        # The helper above is a get-or-create; only its reuse branch returns the
        # schedule `Membership.on_submit` built, and only that one carries
        # `membership`. Assert it, or a factory change surfaces here as the far
        # more confusing "this invoice is not eligible".
        self.assertTrue(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "membership"),
            "fixture precondition: the dues schedule must name its membership",
        )
        mandate = self.sepa.create_test_sepa_mandate(member=member.name)
        frappe.db.set_value(
            "Member",
            member.name,
            {"payment_method": "SEPA Direct Debit", "iban": mandate.iban},
        )
        invoice = self.sepa.create_test_sales_invoice(
            customer=customer_name,
            member=member.name,
            membership_dues_schedule_display=schedule.name,
            grand_total=amount,
            status="Unpaid",
            submit=True,
        )
        self._track_test_document("Sales Invoice", invoice.name)
        self._track_test_document("Member", member.name)
        self._track_test_document("Customer", customer_name)
        self._track_test_document("Membership", membership.name)
        self._track_test_document("Membership Dues Schedule", schedule.name)
        self._track_test_document("SEPA Mandate", mandate.name)
        return member, invoice

    def _enable_auto_creation(self):
        settings = sched.get_payments_settings()
        settings.enable_auto_batch_creation = 1
        settings.batch_creation_days = "1"
        settings.save()
        return settings


class TestDailyBatchOptimization(_SchedulerOrchestrationBase):
    """daily_batch_optimization() branch coverage + advisory-lock wrapper."""

    def test_skips_when_not_batch_creation_day(self):
        self._enable_auto_creation()
        with patch.object(sched, "is_batch_creation_day", return_value=False) as is_day, patch.object(
            sched, "create_optimal_batches"
        ) as create_batches:
            result = sched._daily_batch_optimization_impl()
        # Skip-day branch returns None and never reaches batch creation.
        self.assertIsNone(result)
        is_day.assert_called_once()
        create_batches.assert_not_called()

    def test_skips_when_disabled(self):
        settings = sched.get_payments_settings()
        settings.enable_auto_batch_creation = 0
        settings.save()
        with patch.object(sched, "is_batch_creation_day") as is_day, patch.object(
            sched, "create_optimal_batches"
        ) as create_batches:
            result = sched._daily_batch_optimization_impl()
        self.assertIsNone(result)
        # Disabled short-circuits before the day check.
        is_day.assert_not_called()
        create_batches.assert_not_called()

    def test_skips_on_weekend_or_holiday(self):
        self._enable_auto_creation()
        with patch.object(sched, "is_batch_creation_day", return_value=True), patch.object(
            sched, "should_skip_batch_creation", return_value=True
        ), patch.object(sched, "create_optimal_batches") as create_batches:
            result = sched._daily_batch_optimization_impl()
        self.assertIsNone(result)
        create_batches.assert_not_called()

    def test_success_path_creates_real_batch(self):
        self._enable_auto_creation()
        for i in range(4):
            self._make_eligible_member_invoice(f"DailyOpt{i}", amount=30.0)

        # Run with a min batch size of 1 so the eligible invoices form a batch.
        with patch.object(sched, "is_batch_creation_day", return_value=True), patch.object(
            sched, "should_skip_batch_creation", return_value=False
        ), patch.object(sched, "get_scheduler_config", return_value={"min_invoices_per_batch": 1}), patch(
            f"{NOTIF_MODULE}.handle_automated_batch_validation",
            return_value={"action": "processed"},
        ) as handle_validation, patch(
            f"{NOTIF_MODULE}.send_daily_batch_summary"
        ) as send_summary:
            sched._daily_batch_optimization_impl()

        # Notification boundary was driven from the success path.
        self.assertTrue(handle_validation.called)
        send_summary.assert_called_once()

        # A real auto-optimized Direct Debit Batch must now exist.
        created = frappe.get_all(
            "Direct Debit Batch",
            filters={"batch_description": ["like", "%Auto-optimized%"]},
            pluck="name",
        )
        self.assertTrue(created, "success path must create at least one real batch")
        for name in created:
            self._track_test_document("Direct Debit Batch", name)

    def test_advisory_lock_skips_when_lock_held(self):
        # get_lock returning False means another run holds the lock -> skip without
        # touching the impl. get_lock / release_lock are imported inside the wrapper.
        with patch("verenigingen.utils.db_advisory_lock.get_lock", return_value=False) as get_lock, patch(
            "verenigingen.utils.db_advisory_lock.release_lock"
        ) as release_lock, patch.object(sched, "_daily_batch_optimization_impl") as impl:
            result = sched.daily_batch_optimization()
        self.assertIsNone(result)
        get_lock.assert_called_once()
        impl.assert_not_called()
        # Lock was never acquired, so it must not be released.
        release_lock.assert_not_called()

    def test_advisory_lock_runs_and_releases_when_acquired(self):
        with patch("verenigingen.utils.db_advisory_lock.get_lock", return_value=True) as get_lock, patch(
            "verenigingen.utils.db_advisory_lock.release_lock"
        ) as release_lock, patch.object(
            sched, "_daily_batch_optimization_impl", return_value="ran"
        ) as impl:
            result = sched.daily_batch_optimization()
        self.assertEqual(result, "ran")
        get_lock.assert_called_once()
        impl.assert_called_once()
        # Lock must always be released in the finally block.
        release_lock.assert_called_once()


class TestRunBatchCreationNow(_SchedulerOrchestrationBase):
    """run_batch_creation_now() - the manual trigger endpoint."""

    def test_creates_batch_with_eligible_data(self):
        """Regression: the rate-limit check used add_days(now_datetime(), hours=-1).

        add_days() has no `hours` kwarg, so the call raised a TypeError that the
        outer try/except turned into {"success": False, ...}. It now uses
        add_to_date(..., hours=-1). With eligible data the endpoint must succeed
        and create a real batch - and crucially must NOT surface a "hours" error.
        """
        self._enable_auto_creation()
        for i in range(4):
            self._make_eligible_member_invoice(f"RunNow{i}", amount=35.0)

        with patch.object(sched, "should_skip_batch_creation", return_value=False), patch.object(
            sched, "is_bank_holiday", return_value=False
        ), patch.object(
            sched, "get_scheduler_config", return_value={"min_invoices_per_batch": 1}
        ), patch.object(sched, "send_batch_creation_notification") as notify:
            result = sched.run_batch_creation_now()

        self.assertTrue(result["success"], msg=result)
        self.assertGreaterEqual(result["result"]["batches_created"], 1)
        # The fixed add_to_date call must not have produced a "hours" TypeError.
        self.assertNotIn("hours", str(result).lower())
        notify.assert_called_once()

        for name in result["result"].get("batch_names", []):
            self._track_test_document("Direct Debit Batch", name)

    def test_skips_when_conditions_not_met(self):
        # should_skip_batch_creation True -> early structured failure, no crash.
        with patch.object(sched, "should_skip_batch_creation", return_value=True):
            result = sched.run_batch_creation_now()
        self.assertFalse(result["success"])
        self.assertIn("error", result)


class TestBatchOptimizationStats(_SchedulerOrchestrationBase):
    """get_batch_optimization_stats() totals + success_rate."""

    def _create_auto_optimized_batches(self, count, amount=40.0):
        for i in range(count * 2):
            self._make_eligible_member_invoice(f"Stats{i}", amount=amount)
        result = sched.create_optimal_batches(
            target_date=getdate(), config={"min_invoices_per_batch": 1}
        )
        self.assertTrue(result["success"], msg=result)
        names = result.get("batch_names", [])
        self.assertTrue(names, msg=result)
        for name in names:
            self._track_test_document("Direct Debit Batch", name)
        return names

    def test_stats_empty_when_no_auto_batches(self):
        result = sched.get_batch_optimization_stats()
        self.assertTrue(result["success"])
        stats = result["stats"]
        self.assertEqual(stats["total_batches"], 0)
        self.assertEqual(stats["success_rate"], 0)

    def test_stats_totals_reflect_created_batches(self):
        names = self._create_auto_optimized_batches(count=2)
        result = sched.get_batch_optimization_stats()
        self.assertTrue(result["success"])
        stats = result["stats"]
        self.assertGreaterEqual(stats["total_batches"], len(names))
        self.assertGreater(stats["total_amount"], 0)
        self.assertGreater(stats["total_invoices"], 0)
        self.assertGreater(stats["average_batch_size"], 0)

    def test_success_rate_reads_status_not_workflow_state(self):
        """Regression: success_rate was computed from a non-existent b.workflow_state
        field, so it was always 0. It now reads b.status; batches at "Processed"
        must drive success_rate > 0.
        """
        names = self._create_auto_optimized_batches(count=2)
        # Mark every auto-optimized batch as Processed (a valid status option).
        for name in names:
            frappe.db.set_value("Direct Debit Batch", name, "status", "Processed")

        result = sched.get_batch_optimization_stats()
        self.assertTrue(result["success"])
        self.assertGreater(
            result["stats"]["success_rate"],
            0,
            "success_rate must read b.status (Processed) - the workflow_state bug returned 0",
        )

    def test_success_rate_zero_when_all_draft(self):
        # Freshly created batches default to Draft -> not counted as processed.
        names = self._create_auto_optimized_batches(count=2)
        for name in names:
            self.assertEqual(frappe.db.get_value("Direct Debit Batch", name, "status"), "Draft")
        result = sched.get_batch_optimization_stats()
        self.assertEqual(result["stats"]["success_rate"], 0)


class TestSchedulerNotificationBuilders(_SchedulerOrchestrationBase):
    """send_batch_creation_notification / create_system_notification.

    These are best-effort side-channels wrapped in try/except - they must not
    raise even with a minimal result payload, and the email path is mocked at the
    boundary so no real mail is sent.
    """

    def _minimal_result(self):
        return {
            "batches_created": 1,
            "total_invoices": 3,
            "batch_names": ["DD-BATCH-TEST-0001"],
            "optimization_report": {
                "summary": {
                    "total_amount_processed": 90.0,
                    "average_batch_size": 3,
                    "efficiency_score": 80,
                },
                "batch_details": [
                    {"name": "DD-BATCH-TEST-0001", "invoice_count": 3, "total_amount": 90.0, "risk_level": "Low"}
                ],
            },
        }

    # Both builders notify the "Verenigingen Financial Manager" role. These tests
    # pin the empty-audience branch (no such users -> no mail / no Notification
    # Log), which is robust without seeding the role. (They previously asserted a
    # tautology / nothing at all.)
    FINANCE_ROLE = "Verenigingen Financial Manager"

    def test_send_batch_creation_notification_skips_when_no_audience(self):
        # With no finance-manager users, the builder must return before touching
        # the email service -- never construct a body or mail an empty recipient
        # list. (Previously this asserted `assertTrue(x or not x)`, a tautology.)
        frappe.db.delete("Has Role", {"role": self.FINANCE_ROLE})
        with patch.object(sched, "get_email_service") as get_email:
            sched.send_batch_creation_notification(self._minimal_result())
        get_email.assert_not_called()

    def test_create_system_notification_no_audience_creates_no_log(self):
        # With no finance-manager users, create_system_notification must not
        # create any Notification Log row. (Previously this asserted nothing.)
        frappe.db.delete("Has Role", {"role": self.FINANCE_ROLE})
        before = frappe.db.count("Notification Log", {"subject": "Auto-created 1 DD batches"})
        sched.create_system_notification(self._minimal_result())
        after = frappe.db.count("Notification Log", {"subject": "Auto-created 1 DD batches"})
        self.assertEqual(after, before)
