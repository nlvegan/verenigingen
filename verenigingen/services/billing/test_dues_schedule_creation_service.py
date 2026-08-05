# -*- coding: utf-8 -*-
"""
Integration tests for
verenigingen/services/billing/dues_schedule_creation_service.py

DuesScheduleCreationService.create_schedule_with_retry and its helpers:
  - Input validation rejections (empty member/membership/type, negative amount)
  - retry_count clamping
  - Idempotency (existing schedule -> ok with already_exists)
  - Real successful creation from a configured template
  - Circuit breaker: _record_failure / _should_circuit_break / _record_success
  - _categorize_error / _is_retryable_error classification
  - Non-retryable (validation) error path -> fail with max_retries metadata, no enqueue
  - retry_create_dues_schedule_job background entry point (delegates, returns dict)

Real DocTypes used for the creation path; no business logic mocked. The retry
ENQUEUE path (frappe.enqueue → RQ) is a true external boundary and is exercised
only via the non-retryable branch (which never enqueues) plus the
classification helpers that decide enqueue, so no jobs are actually queued.

The circuit breaker uses frappe.cache(); tests reset it in setUp/tearDown to
avoid cross-test/state leakage.
"""

import frappe
from frappe.utils import today

from verenigingen.services.billing.dues_schedule_creation_service import (
    DuesScheduleCreationService,
    retry_create_dues_schedule_job,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuesScheduleCreationService(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.svc = DuesScheduleCreationService()
        # Ensure a clean circuit-breaker state.
        frappe.cache().delete_value(self.svc.CIRCUIT_BREAKER_CACHE_KEY)
        self._committed_docs = []

    def tearDown(self):
        frappe.cache().delete_value(self.svc.CIRCUIT_BREAKER_CACHE_KEY)
        order = {
            "Membership Dues Schedule": 0,
            "Membership": 1,
            "Member": 2,
            "Membership Type": 3,
        }
        for doctype, name in sorted(self._committed_docs, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------
    def _make_membership_type(self, minimum_amount=12.0, with_template=True):
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": "Verenigingen Member"}
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"DSCS-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Creation service test type"
        mt.is_active = 1
        mt.contribution_mode = "Fixed Amount"
        mt.minimum_amount = minimum_amount
        mt.role_profile = role_profile
        mt.save()
        self._committed_docs.append(("Membership Type", mt.name))
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": mt.name},
            "name",
        )
        if template:
            self._committed_docs.append(("Membership Dues Schedule", template))
            tdoc = frappe.get_doc("Membership Dues Schedule", template)
            tdoc.suggested_amount = minimum_amount
            tdoc.dues_rate = minimum_amount
            tdoc.minimum_amount = minimum_amount
            tdoc.billing_frequency = "Monthly"
            tdoc.currency = "EUR"
            tdoc.save(ignore_permissions=True)
        if not with_template:
            frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", None)
        frappe.db.commit()
        return mt

    def _make_member_with_membership(self, mt):
        member = frappe.new_doc("Member")
        member.first_name = "Creation"
        member.last_name = f"M{frappe.generate_hash(length=6)}"
        member.email = f"dscs.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.birth_date = "1990-01-01"
        member.save()
        frappe.db.commit()
        self._committed_docs.append(("Member", member.name))

        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = mt.name
        membership.start_date = today()
        membership.status = "Active"
        membership.flags.skip_dues_schedule_creation = True
        membership.insert(ignore_permissions=True)
        self._committed_docs.append(("Membership", membership.name))
        membership.flags.skip_dues_schedule_creation = True
        membership.submit()
        for nm in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "is_template": 0},
            pluck="name",
        ):
            self._committed_docs.append(("Membership Dues Schedule", nm))
            frappe.delete_doc("Membership Dues Schedule", nm, force=True, ignore_permissions=True)
        frappe.db.commit()
        return member, membership

    def _track_schedule(self, member_name):
        for nm in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0},
            pluck="name",
        ):
            self._committed_docs.append(("Membership Dues Schedule", nm))

    # ==================================================================
    # Input validation
    # ==================================================================
    def test_empty_member_name_rejected(self):
        result = self.svc.create_schedule_with_retry("", "MEM-1", "Type-1")
        self.assertFalse(result.success)
        self.assertIn("member_name", result.error_message)
        self.assertEqual(result.metadata["error_category"], "validation")

    def test_empty_membership_name_rejected(self):
        result = self.svc.create_schedule_with_retry("MBR-1", "  ", "Type-1")
        self.assertFalse(result.success)
        self.assertIn("membership_name", result.error_message)

    def test_empty_membership_type_rejected(self):
        result = self.svc.create_schedule_with_retry("MBR-1", "MEM-1", "")
        self.assertFalse(result.success)
        self.assertIn("membership_type", result.error_message)

    def test_negative_custom_amount_rejected(self):
        result = self.svc.create_schedule_with_retry("MBR-1", "MEM-1", "Type-1", custom_amount=-5.0)
        self.assertFalse(result.success)
        self.assertIn("custom_amount", result.error_message)
        self.assertEqual(result.metadata["error_category"], "validation")

    # ==================================================================
    # Successful creation (real)
    # ==================================================================
    def test_successful_creation_returns_schedule_name(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, membership = self._make_member_with_membership(mt)
        result = self.svc.create_schedule_with_retry(
            member_name=member.name,
            membership_name=membership.name,
            membership_type=mt.name,
        )
        self._track_schedule(member.name)
        self.assertTrue(result.success, msg=getattr(result, "error_message", None))
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", result.data))
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", result.data, "member"), member.name)
        # Success resets the circuit breaker counter.
        self.assertFalse(frappe.cache().get_value(self.svc.CIRCUIT_BREAKER_CACHE_KEY))

    def test_idempotent_returns_existing_schedule(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, membership = self._make_member_with_membership(mt)
        first = self.svc.create_schedule_with_retry(
            member_name=member.name,
            membership_name=membership.name,
            membership_type=mt.name,
        )
        self._track_schedule(member.name)
        self.assertTrue(first.success)
        # Second call: schedule already exists -> ok with already_exists metadata.
        second = self.svc.create_schedule_with_retry(
            member_name=member.name,
            membership_name=membership.name,
            membership_type=mt.name,
        )
        self.assertTrue(second.success)
        self.assertEqual(second.data, first.data)
        self.assertTrue(second.metadata.get("already_exists"))

    # ==================================================================
    # Non-retryable error path (no enqueue) — membership type has no template
    # ==================================================================
    def test_non_retryable_config_or_validation_failure(self):
        # A membership type WITHOUT a template raises a "no dues schedule template"
        # error inside create_from_template. That message contains "template" so it
        # is categorized "config" (retryable) — but to exercise the NON-retryable
        # max-retries branch deterministically, drive retry_count at MAX_RETRIES so
        # the else-branch (alert + fail, no enqueue) is taken regardless of category.
        mt = self._make_membership_type(minimum_amount=10.0, with_template=False)
        member, membership = self._make_member_with_membership(mt)
        result = self.svc.create_schedule_with_retry(
            member_name=member.name,
            membership_name=membership.name,
            membership_type=mt.name,
            retry_count=self.svc.MAX_RETRIES,
        )
        self.assertFalse(result.success)
        self.assertTrue(result.metadata.get("max_retries_reached"))
        # No schedule was created.
        self.assertFalse(
            frappe.db.exists("Membership Dues Schedule", {"member": member.name, "is_template": 0})
        )

    # ==================================================================
    # Retryable error path — the retry must carry the agreed amount
    # ==================================================================
    def test_retryable_failure_enqueues_a_retry_carrying_the_custom_amount(self):
        """A retryable failure must enqueue a retry that still knows the agreed rate.

        REGRESSION GUARD for a financial bug. A previous revision replaced this
        enqueue with "let the daily auto_create_missing_dues_schedules task pick it
        up". That task creates the schedule at the membership type's TEMPLATE rate,
        not the member's agreed amount -- and Membership.create_or_update_dues_schedule
        clears csv_import_custom_fee (membership.py:157) BEFORE the create it is
        retrying, so the agreed amount is gone by the time we get here. A member
        imported at EUR 5 would silently have been billed the EUR 25 template rate.

        The only thing that carries the agreed rate forward is `custom_amount` in the
        enqueued kwargs, so that is what this asserts. Nothing else in the suite
        exercises the enqueue branch at all.
        """
        mt = self._make_membership_type(minimum_amount=10.0, with_template=False)
        member, membership = self._make_member_with_membership(mt)

        captured = {}
        original = frappe.enqueue
        frappe.enqueue = lambda *a, **k: captured.update(k)
        try:
            result = self.svc.create_schedule_with_retry(
                member_name=member.name,
                membership_name=membership.name,
                membership_type=mt.name,
                custom_amount=5.0,
                custom_amount_reason="Imported from CSV",
                custom_amount_approved=1,
                retry_count=0,
            )
        finally:
            frappe.enqueue = original

        self.assertFalse(result.success)
        self.assertTrue(captured, "a retryable failure must enqueue a retry")
        self.assertEqual(captured.get("custom_amount"), 5.0)
        self.assertEqual(captured.get("custom_amount_approved"), 1)
        self.assertEqual(captured.get("member_name"), member.name)
        # And the caller gets a token back, which is what keeps membership.py's
        # "will be retried automatically" branch and the admin alerting reachable.
        self.assertTrue(result.metadata.get("retry_job_id"))
        self.assertTrue(result.metadata.get("will_retry"))

    # ==================================================================
    # Error categorization
    # ==================================================================
    def test_categorize_error_duplicate(self):
        self.assertEqual(self.svc._categorize_error("Member already has a dues schedule"), "duplicate")
        self.assertEqual(self.svc._categorize_error("Schedule already exists"), "duplicate")

    def test_categorize_error_config(self):
        self.assertEqual(self.svc._categorize_error("Template not found"), "config")
        self.assertEqual(self.svc._categorize_error("missing suggested_amount"), "config")

    def test_categorize_error_validation(self):
        self.assertEqual(self.svc._categorize_error("validation failed"), "validation")
        self.assertEqual(self.svc._categorize_error("invalid field"), "validation")

    def test_categorize_error_system(self):
        self.assertEqual(self.svc._categorize_error("database connection lost"), "system")

    # ==================================================================
    # Retryability
    # ==================================================================
    def test_is_retryable(self):
        self.assertTrue(self.svc._is_retryable_error("config"))
        self.assertTrue(self.svc._is_retryable_error("system"))
        self.assertFalse(self.svc._is_retryable_error("validation"))
        self.assertFalse(self.svc._is_retryable_error("duplicate"))

    # ==================================================================
    # Circuit breaker
    # ==================================================================
    def test_circuit_breaker_opens_after_threshold(self):
        self.assertFalse(self.svc._should_circuit_break())
        for _ in range(self.svc.CIRCUIT_BREAKER_THRESHOLD):
            self.svc._record_failure()
        self.assertTrue(self.svc._should_circuit_break())
        # Count persisted at threshold.
        self.assertEqual(
            frappe.cache().get_value(self.svc.CIRCUIT_BREAKER_CACHE_KEY),
            self.svc.CIRCUIT_BREAKER_THRESHOLD,
        )

    def test_circuit_breaker_below_threshold_stays_closed(self):
        for _ in range(self.svc.CIRCUIT_BREAKER_THRESHOLD - 1):
            self.svc._record_failure()
        self.assertFalse(self.svc._should_circuit_break())

    def test_record_success_resets_breaker(self):
        for _ in range(self.svc.CIRCUIT_BREAKER_THRESHOLD):
            self.svc._record_failure()
        self.assertTrue(self.svc._should_circuit_break())
        self.svc._record_success()
        self.assertFalse(self.svc._should_circuit_break())
        self.assertIsNone(frappe.cache().get_value(self.svc.CIRCUIT_BREAKER_CACHE_KEY))

    def test_open_circuit_breaker_blocks_creation(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, membership = self._make_member_with_membership(mt)
        # Force circuit open.
        for _ in range(self.svc.CIRCUIT_BREAKER_THRESHOLD):
            self.svc._record_failure()
        result = self.svc.create_schedule_with_retry(
            member_name=member.name,
            membership_name=membership.name,
            membership_type=mt.name,
        )
        self.assertFalse(result.success)
        self.assertTrue(result.metadata.get("circuit_breaker_open"))
        self.assertEqual(result.metadata["error_category"], "system")
        # No schedule created while circuit is open.
        self.assertFalse(
            frappe.db.exists("Membership Dues Schedule", {"member": member.name, "is_template": 0})
        )

    # ==================================================================
    # Background job entry point
    # ==================================================================
    def test_retry_job_success_returns_dict(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, membership = self._make_member_with_membership(mt)
        out = retry_create_dues_schedule_job(
            member_name=member.name,
            membership_name=membership.name,
            membership_type=mt.name,
            retry_count=0,
        )
        self._track_schedule(member.name)
        self.assertIsInstance(out, dict)
        self.assertTrue(out["success"])
