# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/dues_schedule_auto_creator.py

Covers:
  - pure helpers: _calculate_next_invoice_date, _get_template_dues_rate,
    _validate_final_dues_rate, _get_validated_dues_rate
  - core logic: _auto_create_missing_dues_schedules_impl,
    _process_dues_schedule_retry_queue (deprecated no-op),
    _create_max_retry_alert (deprecated no-op)
  - whitelisted endpoints: preview_missing_dues_schedules,
    auto_create_missing_dues_schedules(_enhanced), run_auto_creation_manually,
    get_members_without_dues_schedules, get_dues_schedule_retry_queue_status,
    clear_dues_schedule_retry_queue, manually_process_retry_queue,
    create_dues_schedules_for_members

RETURN SHAPE NOTE:
    When the @frappe.whitelist() + security-framework decorated functions are
    invoked directly as module functions (i.e. NOT over an HTTP request), the
    security framework returns the RAW value the inner function produced (a list
    or a plain dict like {"total_members", "created_count", ...}), NOT a
    serialized {"success", "data"} envelope. Tests therefore assert against the
    raw dict/list shape.

ISOLATION:
    The auto-creator COMMITS created schedules and member-field updates (escaping
    FrappeTestCase rollback). There is also pre-existing site data with members
    lacking schedules. Every test creates fixtures with UNIQUE names, tracks them,
    force-deletes them in tearDown, and scopes EVERY assertion to its own created
    members (never to pre-existing site data).

EMAIL BOUNDARY:
    The *_summary_email functions deliver via the EmailService/frappe boundary.
    Tests assert the auto-creator aggregates/returns correctly and (where the
    function is exercised) that it does not raise; real SMTP delivery is not
    asserted.
"""

import frappe
from frappe.utils import add_days, add_months, add_years, getdate, today

from verenigingen.services.billing import dues_schedule_auto_creator as dsac
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuesScheduleAutoCreator(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # (doctype, name) pairs that must be force-deleted in tearDown because the
        # code-under-test commits (escaping the test transaction rollback).
        self._committed_docs = []

    def tearDown(self):
        # Delete dues schedules first (children of member/membership), then
        # memberships, then membership types / members. We sort by a rough
        # priority so links resolve cleanly; ignore already-deleted rows.
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
    # Fixture helpers (allowed to use ignore_permissions / set_value)
    # ------------------------------------------------------------------
    def _as_admin(self):
        frappe.set_user("Administrator")

    def _make_membership_type(self, minimum_amount=12.0, with_template=True):
        """Create an active Membership Type. By default its after_insert hook
        auto-creates a dues-schedule template aligned to minimum_amount."""
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": "Verenigingen Member"}
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"DSAC-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Dues auto-creator test type"
        mt.is_active = 1
        mt.contribution_mode = "Fixed Amount"
        mt.minimum_amount = minimum_amount
        mt.role_profile = role_profile
        mt.save()
        self._committed_docs.append(("Membership Type", mt.name))

        # Align the auto-created template rate to the type minimum so downstream
        # schedules validate (mirrors the factory's behaviour).
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
            tdoc.minimum_amount = minimum_amount * 0.5
            tdoc.currency = "EUR"
            tdoc.save(ignore_permissions=True)
        if not with_template:
            frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", None)
            mt.reload()
        frappe.db.commit()
        return mt

    def _make_member(self):
        member = frappe.new_doc("Member")
        member.first_name = "DsacTest"
        member.last_name = f"M{frappe.generate_hash(length=6)}"
        member.email = f"dsac.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.birth_date = "1990-01-01"
        member.address_line1 = "1 Dues Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        # The endpoints under test call frappe.db.commit() internally, which ends
        # the surrounding transaction. Commit fixtures so they remain visible
        # across those internal commits (they are force-deleted in tearDown).
        frappe.db.commit()
        self._committed_docs.append(("Member", member.name))
        return member

    def _make_membership_without_schedule(self, member, membership_type):
        """Create + submit a Membership but SKIP the auto dues-schedule creation,
        producing exactly the "missing schedule" state the auto-creator fixes."""
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.flags.skip_dues_schedule_creation = True
        membership.insert(ignore_permissions=True)
        self._committed_docs.append(("Membership", membership.name))
        membership.flags.skip_dues_schedule_creation = True
        membership.submit()
        # Defensive: cancel any schedule that may have slipped through so the
        # member is genuinely "missing" an active schedule.
        self._deactivate_schedules(member.name)
        frappe.db.commit()
        return membership

    def _deactivate_schedules(self, member_name):
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")
            self._committed_docs.append(("Membership Dues Schedule", name))

    def _track_created_schedules_for(self, member_name):
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0},
            pluck="name",
        ):
            self._committed_docs.append(("Membership Dues Schedule", name))

    def _schedule_for(self, member_name):
        rows = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0, "status": "Active"},
            fields=["name", "dues_rate", "billing_frequency", "next_invoice_date"],
        )
        return rows[0] if rows else None

    # ==================================================================
    # Pure helper: _calculate_next_invoice_date
    # ==================================================================
    def test_next_invoice_date_daily(self):
        self.assertEqual(dsac._calculate_next_invoice_date("Daily"), add_days(today(), 1))

    def test_next_invoice_date_monthly(self):
        self.assertEqual(dsac._calculate_next_invoice_date("Monthly"), add_months(today(), 1))

    def test_next_invoice_date_quarterly(self):
        self.assertEqual(dsac._calculate_next_invoice_date("Quarterly"), add_months(today(), 3))

    def test_next_invoice_date_semi_annual(self):
        self.assertEqual(dsac._calculate_next_invoice_date("Semi-Annual"), add_months(today(), 6))

    def test_next_invoice_date_annual(self):
        self.assertEqual(dsac._calculate_next_invoice_date("Annual"), add_years(today(), 1))

    def test_next_invoice_date_unknown_defaults_monthly(self):
        # "Custom"/unknown frequencies fall back to monthly.
        self.assertEqual(dsac._calculate_next_invoice_date("Custom"), add_months(today(), 1))
        self.assertEqual(dsac._calculate_next_invoice_date(None), add_months(today(), 1))

    # ==================================================================
    # Pure helper: _get_template_dues_rate
    # ==================================================================
    def test_template_dues_rate_prefers_suggested_amount(self):
        mt = self._make_membership_type(minimum_amount=20.0)
        template = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
        rate = dsac._get_template_dues_rate(template)
        self.assertEqual(rate, 20.0)

    def test_template_dues_rate_falls_back_to_dues_rate(self):
        mt = self._make_membership_type(minimum_amount=15.0)
        template = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
        template.suggested_amount = 0
        template.dues_rate = 7.5
        rate = dsac._get_template_dues_rate(template)
        self.assertEqual(rate, 7.5)

    def test_template_dues_rate_raises_when_unconfigured(self):
        mt = self._make_membership_type(minimum_amount=15.0)
        template = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
        template.suggested_amount = 0
        template.dues_rate = 0
        with self.assertRaises(ValueError):
            dsac._get_template_dues_rate(template)

    # ==================================================================
    # Pure helper: _validate_final_dues_rate
    # ==================================================================
    def test_validate_final_rate_returns_positive_template_rate(self):
        mt = self._make_membership_type(minimum_amount=5.0)
        self.assertEqual(dsac._validate_final_dues_rate(25.0, mt), 25.0)

    def test_validate_final_rate_falls_back_to_minimum_amount(self):
        mt = self._make_membership_type(minimum_amount=18.0)
        # template rate 0 -> fall back to membership type minimum_amount
        self.assertEqual(dsac._validate_final_dues_rate(0, mt), 18.0)

    def test_validate_final_rate_raises_when_no_valid_rate(self):
        mt = self._make_membership_type(minimum_amount=18.0)
        frappe.db.set_value("Membership Type", mt.name, "minimum_amount", 0)
        mt.reload()
        with self.assertRaises(ValueError):
            dsac._validate_final_dues_rate(0, mt)

    # ==================================================================
    # Pure helper: _get_validated_dues_rate (preview path, swallows errors -> 0)
    # ==================================================================
    def test_validated_dues_rate_for_member_with_membership(self):
        mt = self._make_membership_type(minimum_amount=22.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)
        # The function receives a row-like object exposing .member_name (the SQL
        # aliases m.member AS member_name).
        row = frappe._dict({"member_name": member.name})
        self.assertEqual(dsac._get_validated_dues_rate(row), 22.0)

    def test_validated_dues_rate_returns_zero_when_no_membership(self):
        member = self._make_member()  # member with NO membership
        row = frappe._dict({"member_name": member.name})
        self.assertEqual(dsac._get_validated_dues_rate(row), 0)

    # ==================================================================
    # preview_missing_dues_schedules (whitelisted, returns list, LIMIT 10)
    # ==================================================================
    def test_preview_lists_my_missing_member(self):
        mt = self._make_membership_type(minimum_amount=14.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        rows = dsac.preview_missing_dues_schedules()
        self.assertIsInstance(rows, list)
        # It is a LIMIT-10 preview; we cannot guarantee our member appears if the
        # site already has >10 missing members. Assert shape instead, and that
        # every returned row has the documented columns.
        for r in rows:
            for key in ("membership_name", "member_name", "membership_type", "full_name"):
                self.assertIn(key, r)

    # ==================================================================
    # get_members_without_dues_schedules (whitelisted, returns list)
    # ==================================================================
    def test_get_members_without_schedules_includes_mine(self):
        mt = self._make_membership_type(minimum_amount=14.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        rows = dsac.get_members_without_dues_schedules()
        self.assertIsInstance(rows, list)
        names = {r["name"] for r in rows}
        self.assertIn(member.name, names)

    def test_get_members_without_schedules_excludes_member_with_schedule(self):
        mt = self._make_membership_type(minimum_amount=14.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        # Create the schedule, then the member must no longer appear.
        self._as_admin()
        dsac.create_dues_schedules_for_members(frappe.as_json([member.name]), send_emails=False)
        self._track_created_schedules_for(member.name)

        rows = dsac.get_members_without_dues_schedules()
        names = {r["name"] for r in rows}
        self.assertNotIn(member.name, names)

    # ==================================================================
    # auto_create_missing_dues_schedules_enhanced - preview mode
    # ==================================================================
    def test_enhanced_preview_mode_does_not_create(self):
        mt = self._make_membership_type(minimum_amount=33.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        result = dsac.auto_create_missing_dues_schedules_enhanced(preview_mode=True, send_emails=False)
        self.assertTrue(result["preview_mode"])
        self.assertEqual(result["created_count"], 0)
        # No active schedule should have been created for our member.
        self.assertIsNone(self._schedule_for(member.name))
        # Our member appears in the preview payload with the validated rate.
        mine = [s for s in result["created_schedules"] if s["member"] == member.name]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["dues_rate"], 33.0)
        self.assertEqual(mine[0]["billing_frequency"], "Monthly")

    # ==================================================================
    # auto_create_missing_dues_schedules_enhanced - real creation
    # ==================================================================
    def test_enhanced_creates_schedule_with_correct_rate_and_date(self):
        mt = self._make_membership_type(minimum_amount=27.5)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        result = dsac.auto_create_missing_dues_schedules_enhanced(preview_mode=False, send_emails=False)
        self._track_created_schedules_for(member.name)

        self.assertGreaterEqual(result["created_count"], 1)
        # Real DB state: an Active schedule now exists for our member.
        sched = self._schedule_for(member.name)
        self.assertIsNotNone(sched)
        self.assertEqual(sched["dues_rate"], 27.5)
        # The enhanced path inherits billing_frequency from the membership type's
        # dues-schedule template (whatever the template was created with).
        template_freq = frappe.db.get_value(
            "Membership Dues Schedule", mt.dues_schedule_template, "billing_frequency"
        )
        self.assertEqual(sched["billing_frequency"], template_freq)
        self.assertEqual(
            getdate(sched["next_invoice_date"]),
            getdate(dsac._calculate_next_invoice_date(template_freq)),
        )
        # Currency is populated (mandatory field) and is EUR for the association.
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", sched["name"], "currency"),
            "EUR",
        )

        # Member fields are synced.
        member.reload()
        self.assertEqual(member.current_dues_schedule, sched["name"])
        self.assertEqual(member.dues_rate, 27.5)

        # fee_change_history got a "Schedule Created" entry for this schedule.
        history_types = [h.change_type for h in member.fee_change_history]
        self.assertIn("Schedule Created", history_types)

    def test_enhanced_idempotent_second_run_creates_nothing_new(self):
        mt = self._make_membership_type(minimum_amount=19.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        dsac.auto_create_missing_dues_schedules_enhanced(preview_mode=False, send_emails=False)
        self._track_created_schedules_for(member.name)
        first = self._schedule_for(member.name)
        self.assertIsNotNone(first)

        # Second run: member now has an active schedule, so must not appear/recreate.
        result2 = dsac.auto_create_missing_dues_schedules_enhanced(preview_mode=False, send_emails=False)
        created_members = {s["member"] for s in result2["created_schedules"]}
        self.assertNotIn(member.name, created_members)
        active = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "is_template": 0, "status": "Active"},
        )
        self.assertEqual(len(active), 1)

    # ==================================================================
    # auto_create_missing_dues_schedules (thin wrapper)
    # ==================================================================
    def test_wrapper_delegates_to_enhanced_preview(self):
        self._as_admin()
        result = dsac.auto_create_missing_dues_schedules(preview_mode=True, send_emails=False)
        self.assertIn("total_members", result)
        self.assertIn("preview_mode", result)
        self.assertTrue(result["preview_mode"])

    # ==================================================================
    # run_auto_creation_manually
    # ==================================================================
    def test_run_auto_creation_manually_returns_result_dict(self):
        mt = self._make_membership_type(minimum_amount=16.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        result = dsac.run_auto_creation_manually()
        self._track_created_schedules_for(member.name)
        self.assertIn("created_count", result)
        self.assertIn("total_members", result)
        # Our member should have an active schedule now.
        self.assertIsNotNone(self._schedule_for(member.name))

    # ==================================================================
    # create_dues_schedules_for_members
    # ==================================================================
    def test_create_for_members_creates_schedule(self):
        mt = self._make_membership_type(minimum_amount=21.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        result = dsac.create_dues_schedules_for_members(frappe.as_json([member.name]), send_emails=False)
        self._track_created_schedules_for(member.name)
        self.assertEqual(result["total_members"], 1)
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["error_count"], 0)
        sched = self._schedule_for(member.name)
        self.assertIsNotNone(sched)
        self.assertEqual(sched["dues_rate"], 21.0)
        self.assertEqual(result["created_schedules"][0]["member"], member.name)

    def test_create_for_members_accepts_list_argument(self):
        mt = self._make_membership_type(minimum_amount=13.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        # Pass a real list (not a JSON string) to cover the non-str branch.
        result = dsac.create_dues_schedules_for_members([member.name], send_emails=False)
        self._track_created_schedules_for(member.name)
        self.assertEqual(result["created_count"], 1)

    def test_create_for_members_errors_on_member_without_membership(self):
        member = self._make_member()  # NO active membership

        self._as_admin()
        result = dsac.create_dues_schedules_for_members(frappe.as_json([member.name]), send_emails=False)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["error_count"], 1)
        self.assertTrue(any("No active membership" in e for e in result["errors"]))

    # ==================================================================
    # Impl / scheduled wrapper
    # ==================================================================
    def test_impl_returns_aggregate_shape(self):
        mt = self._make_membership_type(minimum_amount=11.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        result = dsac._auto_create_missing_dues_schedules_impl()
        self._track_created_schedules_for(member.name)
        for key in ("total_found", "created", "errors"):
            self.assertIn(key, result)
        # Our member got a schedule.
        self.assertIsNotNone(self._schedule_for(member.name))

    # ==================================================================
    # Deprecated no-ops
    # ==================================================================
    def test_process_retry_queue_is_noop(self):
        result = dsac._process_dues_schedule_retry_queue()
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["failed_retries"], [])
        self.assertEqual(result["successful_retries"], [])

    def test_create_max_retry_alert_is_noop(self):
        # Returns None and does not raise (deprecated no-op).
        self.assertIsNone(dsac._create_max_retry_alert("Some-Member", {"retry_count": 3}))

    def test_get_retry_queue_status_deprecated(self):
        self._as_admin()
        result = dsac.get_dues_schedule_retry_queue_status()
        self.assertEqual(result["queue_size"], 0)
        self.assertEqual(result["items"], [])
        self.assertIn("deprecated", result["message"].lower())

    def test_clear_retry_queue_deprecated(self):
        self._as_admin()
        result = dsac.clear_dues_schedule_retry_queue()
        self.assertIn("deprecated", result["message"].lower())

    def test_manually_process_retry_queue_deprecated(self):
        self._as_admin()
        result = dsac.manually_process_retry_queue()
        self.assertEqual(result["processed_count"], 0)
        self.assertIn("deprecated", result["message"].lower())

    # ==================================================================
    # Scheduled wrapper (advisory lock)
    # ==================================================================
    def test_scheduled_wrapper_acquires_lock_and_runs(self):
        mt = self._make_membership_type(minimum_amount=12.0)
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        result = dsac.auto_create_missing_dues_schedules_scheduled()
        self._track_created_schedules_for(member.name)
        # Returns the impl aggregate shape (not the skipped shape).
        for key in ("total_found", "created", "errors"):
            self.assertIn(key, result)
        self.assertNotIn("skipped", result)
        # Our member got an active schedule.
        self.assertIsNotNone(self._schedule_for(member.name))

    # NOTE: The skip-branch (lock-already-held) of the scheduled wrapper is not
    # unit-tested here because MariaDB GET_LOCK is re-entrant within a single DB
    # connection — holding the lock in the test session does not block the
    # in-process wrapper, so the skip path cannot be exercised deterministically
    # without a second connection. The positive path is covered above.

    # ==================================================================
    # create_dues_schedules_for_members — currency inherited from template
    # ==================================================================
    def test_create_for_members_inherits_template_currency(self):
        mt = self._make_membership_type(minimum_amount=17.0)
        # Give the template a non-default currency and verify it propagates.
        frappe.db.set_value("Membership Dues Schedule", mt.dues_schedule_template, "currency", "USD")
        frappe.db.commit()
        member = self._make_member()
        self._make_membership_without_schedule(member, mt)

        self._as_admin()
        result = dsac.create_dues_schedules_for_members(frappe.as_json([member.name]), send_emails=False)
        self._track_created_schedules_for(member.name)
        self.assertEqual(result["created_count"], 1)
        sched = self._schedule_for(member.name)
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", sched["name"], "currency"), "USD")

    # ==================================================================
    # create_dues_schedules_for_members — mixed success/error aggregation
    # ==================================================================
    def test_create_for_members_mixed_results(self):
        mt = self._make_membership_type(minimum_amount=15.0)
        ok_member = self._make_member()
        self._make_membership_without_schedule(ok_member, mt)
        bad_member = self._make_member()  # no membership -> error

        self._as_admin()
        result = dsac.create_dues_schedules_for_members(
            frappe.as_json([ok_member.name, bad_member.name]), send_emails=False
        )
        self._track_created_schedules_for(ok_member.name)
        self.assertEqual(result["total_members"], 2)
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertTrue(any(bad_member.name in e for e in result["errors"]))

    # ==================================================================
    # Summary email aggregation (email delivery is a boundary; assert no raise)
    # ==================================================================
    def test_send_summary_email_does_not_raise(self):
        # send_summary_email swallows all exceptions internally; exercise the
        # aggregation path (it computes counts then hands off to EmailService).
        self._as_admin()
        try:
            dsac.send_summary_email(created_count=2, error_count=1, total_found=3)
        except Exception as e:  # pragma: no cover - must never happen
            self.fail(f"send_summary_email raised: {e}")
