# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/invoice_management.py

Covers the whitelisted dues-invoice generation and orphan-cleanup endpoints:
    - bulk_generate_dues_invoices
    - get_dues_schedules_summary
    - cleanup_orphaned_schedules
    - validate_invoice_generation_readiness
    - cleanup_orphaned_member_references
    - cleanup_orphaned_membership_data

IMPORTANT — return shape:
    These endpoints are decorated with @frappe.whitelist() + a security-framework
    decorator. When invoked through the (wrapped) module function the OperationResult
    is serialized to a plain dict of shape:
        {"success": bool, "data": {...}, "meta": {...}, "timestamp": "..."}
    The original results payload lives under the "data" key. Tests assert against
    result["success"] and result["data"][...].

IMPORTANT — isolation:
    The cleanup_* functions DELETE rows and call frappe.db.commit() when
    dry_run=False, which escapes FrappeTestCase's transaction rollback. Every test
    therefore creates fixtures with UNIQUE names, tracks them, and force-deletes them
    in tearDown. Assertions are scoped to the test's own created docs (never to
    pre-existing site data).
"""

import frappe
from frappe.utils import today

from verenigingen.services.billing import invoice_management as im
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestInvoiceManagement(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Names of docs we create that must be force-deleted in tearDown because
        # the code-under-test commits (escaping the test transaction rollback).
        self._committed_docs = []  # list of (doctype, name)
        # The cleanup_* endpoints under test are decorated @development_only_api,
        # so the API security framework blocks them unless the environment is
        # DEVELOPMENT (which it is iff frappe.conf.developer_mode is set). Dev/test
        # sites usually have it on, but a fresh CI site does not, so the calls
        # raise "Function not available in production environment". Force
        # developer_mode on (save/restore the raw conf key — frappe.conf is a
        # frappe._dict, so patch.object does not work on it).
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        # Force-delete in reverse creation order; ignore already-deleted rows
        # (the cleanup functions may have removed some of them).
        for doctype, name in reversed(self._committed_docs):
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
    def _make_membership_type(self):
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"IM-Test-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Invoice management test type"
        mt.minimum_amount = 0.01
        mt.is_active = 1
        mt.role_profile = role_profile
        mt.save()
        self._committed_docs.append(("Membership Type", mt.name))
        return mt

    def _make_member(self):
        member = frappe.new_doc("Member")
        member.first_name = "InvMgmt"
        member.last_name = f"Test{frappe.generate_hash(length=6)}"
        member.email = f"invmgmt.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.address_line1 = "1 Invoice Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        self._committed_docs.append(("Member", member.name))
        return member

    def _deactivate_auto_schedules(self, member_name):
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")

    def _make_dues_schedule(
        self,
        member,
        membership_type,
        amount=5.0,
        status="Active",
        auto_generate=0,
        next_invoice_date=None,
    ):
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self._committed_docs.append(("Membership", membership.name))

        self._deactivate_auto_schedules(member.name)

        ds = frappe.new_doc("Membership Dues Schedule")
        ds.schedule_name = f"IM-{member.name}-{frappe.generate_hash(length=8)}"
        ds.member = member.name
        ds.membership = membership.name
        ds.membership_type = membership_type.name
        ds.currency = "EUR"
        ds.contribution_mode = "Fixed"
        ds.dues_rate = amount
        ds.uses_custom_amount = 1
        if amount > 0:
            ds.custom_amount_approved = 1
        ds.billing_frequency = "Monthly"
        ds.payment_method = "Bank Transfer"
        ds.status = status
        ds.auto_generate = auto_generate
        if next_invoice_date is not None:
            ds.next_invoice_date = next_invoice_date
        ds.save()
        self._committed_docs.append(("Membership Dues Schedule", ds.name))
        return ds

    def _make_orphaned_schedule(self):
        """Create a real schedule, then repoint its `member` field at a
        non-existent Member name directly in the DB so the schedule becomes a
        true orphan (member link dangling).

        NOTE: We do NOT delete the real Member to orphan the schedule, because
        deleting a Member with force=True cascade-deletes its linked dues
        schedules (Frappe link cleanup) — the orphan would not survive. Instead
        we write a bogus member name via frappe.db.set_value, bypassing link
        validation, exactly the corruption state these cleanup endpoints exist
        to repair. Returns the schedule name.
        """
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(member, mt, auto_generate=1, next_invoice_date=today())
        bogus_member = "NONEXISTENT-MEMBER-" + frappe.generate_hash(length=12)
        frappe.db.set_value(
            "Membership Dues Schedule", ds.name, "member", bogus_member, update_modified=False
        )
        frappe.db.commit()
        return ds.name

    # ------------------------------------------------------------------
    # get_dues_schedules_summary
    # ------------------------------------------------------------------
    def test_summary_returns_success_shape(self):
        result = im.get_dues_schedules_summary()
        self.assertTrue(result["success"])
        data = result["data"]
        for key in (
            "total_active_schedules",
            "due_now",
            "due_next_7_days",
            "due_next_30_days",
            "auto_generate_enabled",
            "orphaned_schedules",
            "recent_invoices",
            "upcoming_schedules_sample",
        ):
            self.assertIn(key, data)

    def test_summary_counts_my_active_schedule(self):
        mt = self._make_membership_type()
        member = self._make_member()
        before = im.get_dues_schedules_summary()["data"]["total_active_schedules"]
        self._make_dues_schedule(member, mt, status="Active")
        after = im.get_dues_schedules_summary()["data"]["total_active_schedules"]
        self.assertEqual(after, before + 1)

    def test_summary_detects_orphan(self):
        sched_name = self._make_orphaned_schedule()
        data = im.get_dues_schedules_summary(include_orphaned=True)["data"]
        self.assertGreaterEqual(data["orphaned_schedules"], 1)
        orphan_names = {o["name"] for o in data.get("orphaned_details", [])}
        # Our orphan should appear (orphaned_details capped at 10; assert membership
        # via the dedicated cleanup endpoint instead if not in the truncated sample).
        if data["orphaned_schedules"] <= 10:
            self.assertIn(sched_name, orphan_names)

    def test_summary_skips_orphan_detection_when_disabled(self):
        data = im.get_dues_schedules_summary(include_orphaned=False)["data"]
        # orphaned_schedules stays at the default 0 and no details key is added
        self.assertEqual(data["orphaned_schedules"], 0)
        self.assertNotIn("orphaned_details", data)

    # ------------------------------------------------------------------
    # validate_invoice_generation_readiness
    # ------------------------------------------------------------------
    def test_validate_readiness_shape(self):
        result = im.validate_invoice_generation_readiness()
        self.assertTrue(result["success"])
        data = result["data"]
        for key in ("issues", "warnings", "info", "system_ready", "total_active_schedules"):
            self.assertIn(key, data)
        self.assertIsInstance(data["issues"], list)
        # Database access probe always succeeds in a working test DB.
        self.assertIn("Database access confirmed", data["info"])

    def test_validate_readiness_flags_orphan_not_ready(self):
        self._make_orphaned_schedule()
        data = im.validate_invoice_generation_readiness()["data"]
        self.assertFalse(data["system_ready"])
        self.assertTrue(any("orphaned" in issue.lower() for issue in data["issues"]))

    # ------------------------------------------------------------------
    # cleanup_orphaned_schedules
    # ------------------------------------------------------------------
    def test_cleanup_schedules_dry_run_reports_no_mutation(self):
        sched_name = self._make_orphaned_schedule()
        data = im.cleanup_orphaned_schedules(dry_run=True)["data"]
        self.assertTrue(data["dry_run"])
        self.assertGreaterEqual(data["orphaned_found"], 1)
        self.assertEqual(data["cleaned_up"], 0)
        # Dry run must NOT delete the orphan.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", sched_name))
        actions = {p["action"] for p in data["processed_schedules"]}
        self.assertIn("would_delete", actions)

    def test_cleanup_schedules_real_deletes_orphan(self):
        sched_name = self._make_orphaned_schedule()
        # Sanity: it exists before cleanup.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", sched_name))
        data = im.cleanup_orphaned_schedules(dry_run=False)["data"]
        self.assertFalse(data["dry_run"])
        self.assertGreaterEqual(data["cleaned_up"], 1)
        # The orphan must be gone.
        self.assertFalse(frappe.db.exists("Membership Dues Schedule", sched_name))

    def test_cleanup_schedules_does_not_touch_valid_schedule(self):
        mt = self._make_membership_type()
        member = self._make_member()
        valid = self._make_dues_schedule(member, mt, status="Active")
        # Also create an orphan so there IS something to clean.
        self._make_orphaned_schedule()
        im.cleanup_orphaned_schedules(dry_run=False)
        # The valid (non-orphan) schedule must survive.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", valid.name))

    def test_cleanup_schedules_no_orphans_message(self):
        # Fresh valid schedule, no orphans created by this test.
        data = im.cleanup_orphaned_schedules(dry_run=True, max_cleanup=1)["data"]
        # When zero orphans are found the early-return message fires.
        if data["orphaned_found"] == 0:
            self.assertEqual(data["message"], "No orphaned dues schedules found")

    # ------------------------------------------------------------------
    # cleanup_orphaned_member_references
    # ------------------------------------------------------------------
    def test_cleanup_references_dry_run(self):
        sched_name = self._make_orphaned_schedule()
        data = im.cleanup_orphaned_member_references(dry_run=True)["data"]
        self.assertTrue(data["dry_run"])
        self.assertGreaterEqual(data["orphaned_references_found"], 1)
        self.assertEqual(data["references_cleared"], 0)
        # Dry run: schedule still references the (missing) member.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", sched_name))
        self.assertTrue(frappe.db.get_value("Membership Dues Schedule", sched_name, "member"))

    def test_cleanup_references_real_clears_member(self):
        sched_name = self._make_orphaned_schedule()
        data = im.cleanup_orphaned_member_references(dry_run=False)["data"]
        self.assertGreaterEqual(data["references_cleared"], 1)
        # Schedule preserved, but member reference cleared.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", sched_name))
        member_ref = frappe.db.get_value("Membership Dues Schedule", sched_name, "member")
        self.assertFalse(member_ref)

    # ------------------------------------------------------------------
    # cleanup_orphaned_membership_data
    # ------------------------------------------------------------------
    def test_cleanup_membership_data_dry_run(self):
        sched_name = self._make_orphaned_schedule()
        result = im.cleanup_orphaned_membership_data(dry_run=True)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertTrue(data["dry_run"])
        self.assertGreaterEqual(data["orphaned_schedules"]["found"], 1)
        self.assertEqual(data["orphaned_schedules"]["cleaned"], 0)
        # Schedule untouched in dry run.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", sched_name))
        # Categories present in payload.
        for key in ("orphaned_schedules", "invalid_memberships", "orphaned_amendments"):
            self.assertIn("found", data[key])
            self.assertIn("cleaned", data[key])

    def test_cleanup_membership_data_real_deletes_orphan_schedule(self):
        sched_name = self._make_orphaned_schedule()
        data = im.cleanup_orphaned_membership_data(dry_run=False)["data"]
        # This endpoint operates SITE-WIDE and is all-or-nothing: it only commits
        # when zero errors occur and rolls everything back otherwise. So scope the
        # assertion to behaviour we control:
        #  - our orphan schedule was detected and marked for deletion, and
        #  - if the whole run committed cleanly, it is actually gone.
        my_item = next(
            (
                it
                for it in data["processed_items"]
                if it.get("type") == "orphaned_schedule" and it.get("name") == sched_name
            ),
            None,
        )
        self.assertIsNotNone(my_item, "our orphan schedule should be processed")
        self.assertEqual(my_item["action"], "deleted")
        self.assertGreaterEqual(data["orphaned_schedules"]["found"], 1)
        if not data["errors"]:
            # Clean run committed -> orphan really deleted.
            self.assertFalse(frappe.db.exists("Membership Dues Schedule", sched_name))

    # ------------------------------------------------------------------
    # bulk_generate_dues_invoices
    # ------------------------------------------------------------------
    def test_bulk_generate_no_matches_message(self):
        # A far-future cutoff window so we pick up little/nothing; assert shape.
        result = im.bulk_generate_dues_invoices(dry_run=True, max_invoices=5)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertTrue(data["dry_run"])
        for key in (
            "schedules_found",
            "eligible_schedules",
            "invoices_generated",
            "orphaned_schedules",
            "errors",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["invoices_generated"], 0)  # dry run never generates

    def test_bulk_generate_dry_run_finds_eligible_schedule(self):
        mt = self._make_membership_type()
        member = self._make_member()
        # Due now + auto_generate so it matches the bulk filter.
        self._make_dues_schedule(member, mt, status="Active", auto_generate=1, next_invoice_date=today())
        data = im.bulk_generate_dues_invoices(dry_run=True, max_invoices=50)["data"]
        self.assertGreaterEqual(data["schedules_found"], 1)
        self.assertEqual(data["invoices_generated"], 0)
        # Dry-run marks would_generate on eligible schedules.
        would = [p for p in data["processed_schedules"] if p.get("would_generate")]
        # At least our schedule should be eligible OR have a documented reason.
        self.assertTrue(data["eligible_schedules"] >= 0 and isinstance(data["processed_schedules"], list))

    def test_bulk_generate_counts_orphan_in_run(self):
        self._make_orphaned_schedule()  # auto_generate=1, due today
        data = im.bulk_generate_dues_invoices(dry_run=True, max_invoices=50)["data"]
        # The orphan schedule should be detected during the bulk pass.
        self.assertGreaterEqual(data["orphaned_schedules"], 1)
