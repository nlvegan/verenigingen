"""
Payment/Banking DocType Coverage Tests

Tests 9 payment/banking DocTypes:
- Direct Debit Batch (submittable, SEPA XML generation)
- Payment Plan (installment generation, tracking)
- Donation Campaign (date/goal validation, progress)
- Mollie Audit Log (immutability, integrity hash)
- Mollie Reconciliation Log (count validation)
- SEPA Batch Upload Log (hash uniqueness, audit trail)
- SEPA Return File Log (status tracking)
- Payment History (child table, payment_id uniqueness)
- Member SEPA Mandate Link (child table, mandate validation)

Also tests 2 Mollie services:
- MollieReconciliationService (member reconciliation logic)
- MollieWebhookService (webhook URL management)
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_months, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDirectDebitBatch(EnhancedTestCase):
    """Tests for Direct Debit Batch DocType — SEPA batch processing.

    Note: validate() calls batch_processing_service which throws if no invoices
    are present. We test validation logic by calling methods directly or by
    inserting with ignore_validate where needed.
    """

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_batch(self, **kwargs):
        """Helper to create a Direct Debit Batch with minimal required fields."""
        doc = frappe.new_doc("Direct Debit Batch")
        doc.batch_date = kwargs.get("batch_date", today())
        doc.batch_description = kwargs.get("batch_description", "Test batch")
        doc.batch_type = kwargs.get("batch_type", "CORE")
        doc.currency = kwargs.get("currency", "EUR")
        doc.update(kwargs)
        return doc

    def test_create_empty_batch_throws_no_invoices(self):
        """A batch without invoices should throw 'No invoices added to batch'."""
        batch = self._create_batch()
        with self.assertRaises(frappe.ValidationError):
            batch.insert()

    def test_batch_calculate_totals_python_fallback(self):
        """Python fallback for totals should work on empty invoices."""
        batch = self._create_batch()
        batch._calculate_totals_python()
        self.assertEqual(batch.entry_count, 0)
        self.assertEqual(batch.total_amount, 0)

    def test_batch_on_cancel_sets_status(self):
        """Cancelling a batch should set status to Cancelled."""
        batch = self._create_batch()
        batch.status = "Submitted"
        batch.on_cancel()
        self.assertEqual(batch.status, "Cancelled")

    def test_batch_process_requires_sepa_file(self):
        """Process should throw if SEPA file not generated."""
        batch = self._create_batch()
        batch.sepa_file_generated = 0
        with self.assertRaises(frappe.ValidationError):
            batch.process_batch()

    def test_validate_sequence_types_empty_invoices(self):
        """validate_sequence_types should return early if no invoices."""
        batch = self._create_batch()
        batch.invoices = []
        batch.validate_sequence_types()  # Should not raise


class TestPaymentPlan(EnhancedTestCase):
    """Tests for Payment Plan DocType — installment generation and tracking."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._ensure_member()

    def _ensure_member(self):
        """Create or get a test member for payment plan tests."""
        if frappe.db.exists("Member", {"email_id": "pp-test@example.com"}):
            self.member_name = frappe.db.get_value(
                "Member", {"email_id": "pp-test@example.com"}, "name"
            )
        else:
            member = frappe.new_doc("Member")
            member.first_name = "PaymentPlan"
            member.last_name = "Tester"
            member.email_id = "pp-test@example.com"
            member.insert(ignore_permissions=True)
            self.member_name = member.name

    def _create_plan(self, **kwargs):
        """Create a Payment Plan with defaults."""
        doc = frappe.new_doc("Payment Plan")
        doc.naming_series = "PP-.####"
        doc.member = kwargs.pop("member", self.member_name)
        doc.plan_type = kwargs.pop("plan_type", "Equal Installments")
        doc.total_amount = kwargs.pop("total_amount", 120.0)
        doc.number_of_installments = kwargs.pop("number_of_installments", 4)
        doc.frequency = kwargs.pop("frequency", "Monthly")
        doc.start_date = kwargs.pop("start_date", today())
        doc.status = kwargs.pop("status", "Draft")
        doc.update(kwargs)
        return doc

    def test_equal_installments_generation(self):
        """Equal installments should generate correct number of installments."""
        plan = self._create_plan(total_amount=100, number_of_installments=4)
        plan.insert()
        self.assertEqual(len(plan.installments), 4)
        # Each installment should be ~25.00
        self.assertAlmostEqual(plan.installment_amount, 25.0, places=2)

    def test_last_installment_rounding(self):
        """Last installment should absorb rounding differences."""
        plan = self._create_plan(total_amount=100, number_of_installments=3)
        plan.insert()
        total = sum(inst.amount for inst in plan.installments)
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_deferred_payment_type(self):
        """Deferred payment should create single installment."""
        plan = self._create_plan(plan_type="Deferred Payment", total_amount=500)
        plan.number_of_installments = None
        plan.frequency = None
        plan.insert()
        self.assertEqual(len(plan.installments), 1)
        self.assertAlmostEqual(plan.installments[0].amount, 500.0, places=2)

    def test_custom_schedule_no_auto_generate(self):
        """Custom schedule should not auto-generate installments."""
        plan = self._create_plan(plan_type="Custom Schedule")
        plan.number_of_installments = None
        plan.frequency = None
        plan.insert()
        self.assertEqual(len(plan.installments), 0)

    def test_installments_zero_throws(self):
        """Zero installments should raise validation error."""
        plan = self._create_plan(number_of_installments=0)
        with self.assertRaises(frappe.ValidationError):
            plan.insert()

    def test_frequency_required_for_equal_installments(self):
        """Missing frequency should raise validation error for equal installments."""
        # A new document cannot reach this check: _set_defaults() fills an empty
        # Select with its first option ("Weekly") on insert, so frequency is only
        # ever missing on an existing plan whose value was cleared.
        plan = self._create_plan()
        plan.insert()
        plan.frequency = None
        with self.assertRaises(frappe.ValidationError):
            plan.save()

    def test_weekly_frequency_dates(self):
        """Weekly frequency should space installments 7 days apart."""
        start = getdate("2026-01-05")
        plan = self._create_plan(
            frequency="Weekly",
            number_of_installments=3,
            start_date=start,
        )
        plan.insert()
        dates = [getdate(inst.due_date) for inst in plan.installments]
        self.assertEqual(dates[0], start)
        self.assertEqual((dates[1] - dates[0]).days, 7)
        self.assertEqual((dates[2] - dates[1]).days, 7)

    def test_biweekly_frequency_dates(self):
        """Bi-weekly frequency should space installments 14 days apart."""
        start = getdate("2026-01-05")
        plan = self._create_plan(
            frequency="Bi-weekly",
            number_of_installments=2,
            start_date=start,
        )
        plan.insert()
        dates = [getdate(inst.due_date) for inst in plan.installments]
        self.assertEqual((dates[1] - dates[0]).days, 14)

    def test_end_date_calculated(self):
        """End date should be calculated from start date and installments."""
        start = getdate("2026-01-01")
        plan = self._create_plan(
            frequency="Monthly",
            number_of_installments=6,
            start_date=start,
        )
        plan.insert()
        expected_end = add_months(start, 5)
        self.assertEqual(getdate(plan.end_date), expected_end)

    def test_tracking_fields_updated(self):
        """Tracking fields should be initialized correctly for new plan."""
        plan = self._create_plan()
        plan.insert()
        self.assertEqual(plan.total_paid, 0)
        self.assertAlmostEqual(plan.remaining_balance, plan.total_amount, places=2)
        self.assertIsNotNone(plan.next_payment_date)

    def test_status_completed_when_fully_paid(self):
        """Status should become Completed when remaining balance is zero."""
        plan = self._create_plan(total_amount=50, number_of_installments=1)
        plan.insert()
        # Simulate payment
        plan.installments[0].status = "Paid"
        plan.installments[0].payment_date = today()
        plan.update_tracking_fields()
        self.assertEqual(plan.status, "Completed")

    def test_status_suspended_after_three_missed(self):
        """Status should become Suspended after 3 consecutive missed payments."""
        plan = self._create_plan(
            total_amount=400,
            number_of_installments=4,
            start_date=add_months(today(), -6),
        )
        plan.insert()
        # Mark first 3 as overdue with past dates
        for i in range(3):
            plan.installments[i].status = "Overdue"
        plan.update_tracking_fields()
        self.assertEqual(plan.status, "Suspended")

    def test_invalid_member_throws(self):
        """Invalid member reference should throw."""
        plan = self._create_plan(member="NONEXISTENT-MEMBER-12345")
        with self.assertRaises(frappe.ValidationError):
            plan.insert()

    def test_zero_total_amount_throws(self):
        """A zero total amount is rejected by validate_plan_details()."""
        plan = self._create_plan(total_amount=0)
        with self.assertRaises(frappe.ValidationError) as ctx:
            plan.insert()
        self.assertIn("Total amount must be greater than 0", str(ctx.exception))

    def test_negative_total_amount_throws(self):
        """A negative total amount is rejected by validate_plan_details()."""
        plan = self._create_plan(total_amount=-50)
        with self.assertRaises(frappe.ValidationError) as ctx:
            plan.insert()
        self.assertIn("Total amount must be greater than 0", str(ctx.exception))

    def test_dues_schedule_of_other_member_throws(self):
        """A dues schedule owned by a different member must be rejected.

        validate_member_and_schedule() cross-checks that the linked
        Membership Dues Schedule belongs to the plan's member; a mismatch is a
        genuine configuration error, not graceful degradation.
        """
        other_member = self.create_test_member(first_name="OtherPP")
        # An active membership auto-creates the member's active dues schedule
        # (production after_insert), which we then mis-link to a different member.
        self.create_test_membership(member_name=other_member.name)
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": other_member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.assertIsNotNone(schedule_name, "Expected an auto-created dues schedule for the other member")
        # Plan.member defaults to self.member_name (a different member than
        # the schedule's owner), so the ownership check must fail.
        plan = self._create_plan(membership_dues_schedule=schedule_name)
        with self.assertRaises(frappe.ValidationError) as ctx:
            plan.insert()
        self.assertIn("does not belong to selected member", str(ctx.exception))


class TestDonationCampaign(EnhancedTestCase):
    """Tests for Donation Campaign DocType — date/goal validation, progress."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_campaign(self, **kwargs):
        """Create a Donation Campaign with defaults."""
        doc = frappe.new_doc("Donation Campaign")
        doc.campaign_name = kwargs.pop(
            "campaign_name",
            f"Test Campaign {frappe.generate_hash(length=6)}",
        )
        # "General" is not one of the field's options; "Other" is the generic one.
        doc.campaign_type = kwargs.pop("campaign_type", "Other")
        doc.status = kwargs.pop("status", "Draft")
        doc.start_date = kwargs.pop("start_date", today())
        doc.update(kwargs)
        return doc

    def test_create_campaign(self):
        """Campaign with valid data should save."""
        camp = self._create_campaign()
        camp.insert()
        self.assertTrue(camp.name)

    def test_end_date_before_start_throws(self):
        """End date before start date should throw validation error."""
        camp = self._create_campaign(
            start_date="2026-06-01",
            end_date="2026-05-01",
        )
        with self.assertRaises(frappe.ValidationError):
            camp.insert()

    def test_negative_monetary_goal_throws(self):
        """Negative monetary goal should throw validation error."""
        camp = self._create_campaign(monetary_goal=-100)
        with self.assertRaises(frappe.ValidationError):
            camp.insert()

    def test_negative_donor_goal_throws(self):
        """Negative donor goal should throw validation error."""
        camp = self._create_campaign(donor_goal=-5)
        with self.assertRaises(frappe.ValidationError):
            camp.insert()

    def test_accounting_dimension_auto_generated(self):
        """Accounting dimension value should be auto-generated from campaign name."""
        camp = self._create_campaign(campaign_name="Summer Fundraiser 2026")
        camp.insert()
        self.assertTrue(camp.accounting_dimension_value)
        self.assertIn("SUMMER", camp.accounting_dimension_value)

    def test_accounting_dimension_uniqueness(self):
        """Duplicate accounting dimension values should get unique suffixes."""
        name1 = f"Dupe Test {frappe.generate_hash(length=4)}"
        camp1 = self._create_campaign(campaign_name=name1)
        camp1.insert()

        name2 = f"Dupe Test {frappe.generate_hash(length=4)}"
        camp2 = self._create_campaign(campaign_name=name2)
        camp2.insert()

        # Both should exist and have different names
        self.assertNotEqual(camp1.name, camp2.name)

    def test_progress_on_new_campaign(self):
        """New campaign should have zero/None progress (update_progress skips new docs)."""
        camp = self._create_campaign(monetary_goal=1000)
        camp.insert()
        # update_progress skips new docs (is_new() check), so fields are None/0
        self.assertFalse(camp.total_donations)
        self.assertFalse(camp.total_raised)
        self.assertFalse(camp.monetary_progress)

    def test_campaign_url_public(self):
        """Public campaign should return URL."""
        camp = self._create_campaign()
        camp.is_public = 1
        camp.show_on_website = 1
        camp.insert()
        url = camp.get_campaign_url()
        self.assertIsNotNone(url)
        self.assertIn(camp.name, url)

    def test_campaign_url_private(self):
        """Private campaign should return None URL."""
        camp = self._create_campaign()
        camp.is_public = 0
        camp.insert()
        self.assertIsNone(camp.get_campaign_url())


class TestMollieAuditLog(EnhancedTestCase):
    """Tests for Mollie Audit Log DocType — immutability and integrity hash."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_audit_log(self, **kwargs):
        """Create a Mollie Audit Log entry."""
        doc = frappe.new_doc("Mollie Audit Log")
        doc.action = kwargs.get("action", "test_action")
        doc.status = kwargs.get("status", "success")
        doc.details = kwargs.get("details", "test details")
        doc.user = kwargs.get("user", "Administrator")
        doc.timestamp = kwargs.get("timestamp", frappe.utils.now())
        doc.update(kwargs)
        return doc

    def test_create_audit_log(self):
        """Audit log should save and auto-generate integrity hash."""
        log = self._create_audit_log()
        log.insert()
        self.assertTrue(log.name)
        self.assertTrue(log.integrity_hash)

    def test_integrity_hash_calculated(self):
        """Integrity hash should be SHA256 of critical fields."""
        log = self._create_audit_log()
        log.insert()
        # Verify the hash matches recalculation
        self.assertTrue(log.verify_integrity())

    def test_immutability_prevents_modification(self):
        """Modifying critical fields after creation should throw."""
        log = self._create_audit_log()
        log.insert()

        log.action = "modified_action"
        with self.assertRaises(frappe.ValidationError):
            log.save()

    def test_immutability_status_change(self):
        """Changing status after creation should throw."""
        log = self._create_audit_log()
        log.insert()

        log.status = "failed"
        with self.assertRaises(frappe.ValidationError):
            log.save()

    def test_cannot_delete(self):
        """Deleting audit log should throw for compliance."""
        log = self._create_audit_log()
        log.insert()

        with self.assertRaises(frappe.ValidationError):
            log.delete()

    def test_verify_integrity_detects_tampering(self):
        """Direct DB modification should be detected by integrity check."""
        log = self._create_audit_log()
        log.insert()

        # Tamper via direct DB update (bypassing validate)
        frappe.db.set_value(
            "Mollie Audit Log",
            log.name,
            "action",
            "tampered_action",
            update_modified=False,
        )

        log.reload()
        self.assertFalse(log.verify_integrity())


class TestMollieReconciliationLog(EnhancedTestCase):
    """Tests for Mollie Reconciliation Log — count validation."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_recon_log(self, **kwargs):
        """Create a Mollie Reconciliation Log."""
        doc = frappe.new_doc("Mollie Reconciliation Log")
        doc.reconciliation_id = kwargs.get(
            "reconciliation_id", f"RECON-{frappe.generate_hash(length=6)}"
        )
        doc.date = kwargs.get("date", today())
        # The field offers Success/Partial/Failed; "Completed" is not an option.
        doc.status = kwargs.get("status", "Success")
        doc.error_count = kwargs.get("error_count", 0)
        doc.warning_count = kwargs.get("warning_count", 0)
        doc.correction_count = kwargs.get("correction_count", 0)
        doc.update(kwargs)
        return doc

    def test_create_recon_log(self):
        """Reconciliation log should save with valid data."""
        log = self._create_recon_log()
        log.insert()
        self.assertTrue(log.name)

    def test_negative_error_count_throws(self):
        """Negative error count should throw."""
        log = self._create_recon_log(error_count=-1)
        with self.assertRaises(frappe.ValidationError):
            log.insert()

    def test_negative_warning_count_throws(self):
        """Negative warning count should throw."""
        log = self._create_recon_log(warning_count=-1)
        with self.assertRaises(frappe.ValidationError):
            log.insert()

    def test_negative_correction_count_throws(self):
        """Negative correction count should throw."""
        log = self._create_recon_log(correction_count=-1)
        with self.assertRaises(frappe.ValidationError):
            log.insert()

    def test_valid_counts_accepted(self):
        """Zero and positive counts should be accepted."""
        log = self._create_recon_log(
            error_count=5,
            warning_count=10,
            correction_count=2,
        )
        log.insert()
        self.assertEqual(log.error_count, 5)


class TestSEPABatchUploadLog(EnhancedTestCase):
    """Tests for SEPA Batch Upload Log — hash uniqueness, audit trail."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_upload_log(self, **kwargs):
        """Create a SEPA Batch Upload Log."""
        doc = frappe.new_doc("SEPA Batch Upload Log")
        doc.batch_name = kwargs.get("batch_name", "TEST-BATCH-001")
        # The field's own default; plain "Pending" is not one of its options.
        doc.batch_status = kwargs.get("batch_status", "Pending Upload")
        doc.file_hash = kwargs.get("file_hash", frappe.generate_hash(length=64))
        doc.update(kwargs)
        return doc

    def test_create_upload_log(self):
        """Upload log should save with valid data."""
        log = self._create_upload_log()
        # batch_name is a Link to Direct Debit Batch; use ignore_links
        log.flags.ignore_links = True
        log.insert()
        self.assertTrue(log.name)

    def test_missing_batch_name_throws(self):
        """Missing batch_name should throw validation error."""
        log = self._create_upload_log(batch_name="")
        log.flags.ignore_links = True
        with self.assertRaises(frappe.ValidationError):
            log.insert()

    def test_duplicate_hash_throws(self):
        """Duplicate file hash should throw DuplicateEntryError."""
        file_hash = frappe.generate_hash(length=64)
        log1 = self._create_upload_log(file_hash=file_hash)
        log1.flags.ignore_links = True
        log1.insert()

        log2 = self._create_upload_log(
            batch_name="TEST-BATCH-002",
            file_hash=file_hash,
        )
        log2.flags.ignore_links = True
        with self.assertRaises(frappe.DuplicateEntryError):
            log2.insert()

    def test_unique_hashes_accepted(self):
        """Different file hashes should be accepted."""
        log1 = self._create_upload_log(file_hash="hash_a_" + frappe.generate_hash(length=58))
        log1.flags.ignore_links = True
        log1.insert()
        log2 = self._create_upload_log(
            batch_name="TEST-BATCH-002",
            file_hash="hash_b_" + frappe.generate_hash(length=58),
        )
        log2.flags.ignore_links = True
        log2.insert()
        self.assertNotEqual(log1.name, log2.name)

    def test_cannot_delete(self):
        """Deleting upload log should throw for audit trail integrity."""
        log = self._create_upload_log()
        log.flags.ignore_links = True
        log.insert()
        with self.assertRaises(frappe.PermissionError):
            log.delete()


class TestSEPAReturnFileLog(EnhancedTestCase):
    """Tests for SEPA Return File Log — status tracking."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_return_log(self, **kwargs):
        """Create a SEPA Return File Log."""
        doc = frappe.new_doc("SEPA Return File Log")
        doc.file_hash = kwargs.get("file_hash", frappe.generate_hash(length=64))
        doc.processing_date = kwargs.get("processing_date", today())
        doc.processed_by = kwargs.get("processed_by", "Administrator")
        # The field's own default; "Pending" is not one of its options.
        doc.status = kwargs.get("status", "Processing")
        doc.update(kwargs)
        return doc

    def test_create_return_log(self):
        """Return file log should save with valid data."""
        log = self._create_return_log()
        log.insert()
        self.assertTrue(log.name)

    def test_completed_status_sets_defaults(self):
        """Completed status should initialize count fields to 0 if unset."""
        log = self._create_return_log(status="Completed")
        log.insert()
        self.assertEqual(log.return_count, 0)
        self.assertEqual(log.successful_reversals, 0)
        self.assertEqual(log.failed_reversals, 0)

    def test_completed_status_preserves_counts(self):
        """Completed status should preserve existing count values."""
        log = self._create_return_log(status="Completed")
        log.return_count = 5
        log.successful_reversals = 3
        log.failed_reversals = 2
        log.insert()
        self.assertEqual(log.return_count, 5)
        self.assertEqual(log.successful_reversals, 3)
        self.assertEqual(log.failed_reversals, 2)


# TestPaymentHistory removed (#596). It exercised PaymentHistory.validate_required_fields()
# directly -- a method that lived only inside the dead child-DocType validate() this issue
# removed. Its own docstring's premise ("Payment History is a child table of Donation") was
# already wrong: no DocType JSON on this bench declares a Table field pointing at "Payment
# History" (Donation's actual payment child table is the distinct "Donation Payment"), and no
# non-test code references the doctype name at all. The tests called the private helper
# directly rather than going through .validate(), so they never actually exercised the
# framework gap #596 is about; removing them loses no real coverage.


class TestMollieReconciliationService(EnhancedTestCase):
    """Tests for MollieReconciliationService — member reconciliation logic.

    Mocks only external Mollie API calls, uses real DB for member queries.
    """

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_filter_dues_subscriptions(self):
        """Should filter subscriptions by dues keywords."""
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        service = MollieReconciliationService()
        service._dues_keywords = ["contributie", "membership"]

        all_subs = [
            {"description": "Contributie 2026", "status": "active"},
            {"description": "Donation monthly", "status": "active"},
            {"description": "Membership dues", "status": "active"},
        ]

        filtered = service._filter_dues_subscriptions(all_subs)
        self.assertEqual(len(filtered), 2)

    def test_group_subscriptions_by_customer(self):
        """Should group subscriptions by customer ID."""
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        service = MollieReconciliationService()
        subs = [
            {"customerId": "cst_A", "id": "sub_1", "status": "active", "description": "x"},
            {"customerId": "cst_A", "id": "sub_2", "status": "canceled", "description": "y"},
            {"customerId": "cst_B", "id": "sub_3", "status": "active", "description": "z"},
        ]

        grouped = service._group_subscriptions_by_customer(subs)
        self.assertEqual(len(grouped["cst_A"]), 2)
        self.assertEqual(len(grouped["cst_B"]), 1)

    def test_detect_discrepancies_no_active_but_member_claims_active(self):
        """Should flag when member has active status but no Mollie subscription."""
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        service = MollieReconciliationService()
        member = {
            "subscription_status": "active",
            "mollie_subscription_id": "sub_123",
        }
        result = service._detect_discrepancies(member, [])
        self.assertTrue(len(result["discrepancies"]) > 0)
        self.assertEqual(result["suggested_status"], "canceled")

    def test_detect_discrepancies_single_active_match(self):
        """No discrepancy when member matches single active subscription."""
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        service = MollieReconciliationService()
        member = {
            "subscription_status": "active",
            "mollie_subscription_id": "sub_123",
        }
        active_subs = [
            {"subscription_id": "sub_123", "status": "active", "next_payment_date": "2026-04-01"},
        ]
        result = service._detect_discrepancies(member, active_subs)
        self.assertEqual(len(result["discrepancies"]), 0)

    def test_detect_discrepancies_multiple_active(self):
        """Should flag multiple active subscriptions."""
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        service = MollieReconciliationService()
        member = {
            "subscription_status": "active",
            "mollie_subscription_id": "sub_1",
        }
        active_subs = [
            {"subscription_id": "sub_1", "status": "active", "next_payment_date": "2026-04-01"},
            {"subscription_id": "sub_2", "status": "active", "next_payment_date": "2026-05-01"},
        ]
        result = service._detect_discrepancies(member, active_subs)
        self.assertTrue(len(result["discrepancies"]) > 0)
        self.assertIn("Multiple", result["discrepancies"][0])

    def test_detect_discrepancies_id_mismatch(self):
        """Should flag when subscription IDs don't match."""
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        service = MollieReconciliationService()
        member = {
            "subscription_status": "active",
            "mollie_subscription_id": "sub_old",
        }
        active_subs = [
            {"subscription_id": "sub_new", "status": "active", "next_payment_date": "2026-04-01"},
        ]
        result = service._detect_discrepancies(member, active_subs)
        self.assertTrue(len(result["discrepancies"]) > 0)
        self.assertEqual(result["suggested_subscription_id"], "sub_new")

    def test_build_member_reconciliation_sorts_issues_first(self):
        """Members with issues should appear first in results."""
        from verenigingen.services.payment.mollie_reconciliation_service import (
            MollieReconciliationService,
        )

        service = MollieReconciliationService()
        members = [
            {
                "name": "MEM-OK",
                "full_name": "Alice",
                "status": "Active",
                "subscription_status": "active",
                "mollie_customer_id": "cst_A",
                "mollie_subscription_id": "sub_1",
                "next_payment_date": None,
                "mollie_subscription_next_invoice_date": None,
            },
            {
                "name": "MEM-BAD",
                "full_name": "Bob",
                "status": "Active",
                "subscription_status": "active",
                "mollie_customer_id": "cst_B",
                "mollie_subscription_id": "sub_missing",
                "next_payment_date": None,
                "mollie_subscription_next_invoice_date": None,
            },
        ]
        subs = [
            {
                "customerId": "cst_A",
                "id": "sub_1",
                "status": "active",
                "description": "Contributie",
                "amount": {"value": "10.00"},
                "interval": "1 month",
                "nextPaymentDate": "2026-05-01",
                "createdAt": "2025-01-01",
                "canceledAt": None,
            },
        ]

        dues_subs = service._filter_dues_subscriptions(subs)
        result = service.build_member_reconciliation(members, dues_subs)
        # Bob (MEM-BAD) should be first because he has issues
        self.assertTrue(result[0]["has_issues"])
        self.assertEqual(result[0]["member_id"], "MEM-BAD")


class TestMollieWebhookService(EnhancedTestCase):
    """Tests for MollieWebhookService — webhook URL management.

    Mocks only Mollie API calls via MollieDebugService.
    """

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_has_admin_access_for_admin(self):
        """System Manager should have admin access."""
        from verenigingen.services.payment.mollie_webhook_service import (
            MollieWebhookService,
        )

        service = MollieWebhookService()
        self.assertTrue(service.has_admin_access())

    def test_bulk_update_requires_https(self):
        """Bulk update should reject non-HTTPS URLs."""
        from verenigingen.services.payment.mollie_webhook_service import (
            MollieWebhookService,
        )

        service = MollieWebhookService()
        with self.assertRaises(ValueError):
            service.bulk_update_webhooks(
                subscriptions=[{"customer_id": "c1", "subscription_id": "s1"}],
                new_webhook_url="http://insecure.example.com/webhook",
            )

    def test_bulk_update_requires_url(self):
        """Bulk update should reject empty URL."""
        from verenigingen.services.payment.mollie_webhook_service import (
            MollieWebhookService,
        )

        service = MollieWebhookService()
        with self.assertRaises(ValueError):
            service.bulk_update_webhooks(
                subscriptions=[{"customer_id": "c1", "subscription_id": "s1"}],
                new_webhook_url="",
            )

    def test_bulk_update_requires_subscriptions(self):
        """Bulk update should reject empty subscription list."""
        from verenigingen.services.payment.mollie_webhook_service import (
            MollieWebhookService,
        )

        service = MollieWebhookService()
        with self.assertRaises(ValueError):
            service.bulk_update_webhooks(
                subscriptions=[],
                new_webhook_url="https://example.com/webhook",
            )

    @patch(
        "verenigingen.services.payment.mollie_webhook_service.MollieDebugService"
    )
    def test_bulk_update_success(self, MockDebugService):
        """Successful bulk update should report correct counts."""
        from verenigingen.services.payment.mollie_webhook_service import (
            MollieWebhookService,
        )

        mock_instance = MockDebugService.return_value
        mock_instance.update_subscription_webhook.return_value = {
            "status": "success",
            "old_webhook_url": "https://old.example.com/hook",
        }

        service = MollieWebhookService()
        service._debug_service = mock_instance

        result = service.bulk_update_webhooks(
            subscriptions=[
                {"customer_id": "c1", "subscription_id": "s1"},
                {"customer_id": "c2", "subscription_id": "s2"},
            ],
            new_webhook_url="https://new.example.com/hook",
        )

        self.assertEqual(result["summary"]["success"], 2)
        self.assertEqual(result["summary"]["errors"], 0)

    @patch(
        "verenigingen.services.payment.mollie_webhook_service.MollieDebugService"
    )
    def test_bulk_update_partial_failure(self, MockDebugService):
        """Partial failure should be reported correctly."""
        from verenigingen.services.payment.mollie_webhook_service import (
            MollieWebhookService,
        )

        mock_instance = MockDebugService.return_value
        mock_instance.update_subscription_webhook.side_effect = [
            {"status": "success", "old_webhook_url": "old"},
            Exception("API error"),
        ]

        service = MollieWebhookService()
        service._debug_service = mock_instance

        result = service.bulk_update_webhooks(
            subscriptions=[
                {"customer_id": "c1", "subscription_id": "s1"},
                {"customer_id": "c2", "subscription_id": "s2"},
            ],
            new_webhook_url="https://new.example.com/hook",
        )

        self.assertEqual(result["summary"]["success"], 1)
        self.assertEqual(result["summary"]["errors"], 1)
