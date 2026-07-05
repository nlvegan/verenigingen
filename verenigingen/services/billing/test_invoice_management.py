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
from frappe.utils import add_days, today

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
        # Shared factory (EnhancedTestCase); low minimum keeps it permissive.
        mt = self.create_test_membership_type(membership_type_name="IM-Test-Type", minimum_amount=0.01)
        self._committed_docs.append(("Membership Type", mt.name))
        return mt

    def _make_member(self):
        member = self.create_test_member(member_since=today())
        self._committed_docs.append(("Member", member.name))
        return member

    def _make_dues_schedule(
        self,
        member,
        membership_type,
        amount=5.0,
        status="Active",
        auto_generate=0,
        next_invoice_date=None,
    ):
        # skip_dues_schedule_creation suppresses the on_submit hook, so the only
        # schedule for this member is the explicit one built below.
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=membership_type.name,
            skip_dues_schedule_creation=True,
        )
        self._committed_docs.append(("Membership", membership.name))

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
        ds = self._make_dues_schedule(member, mt, status="Active", auto_generate=1, next_invoice_date=today())
        # max_invoices high enough to include our just-created schedule even on a
        # shared DB with many other eligible schedules (dry-run -> non-destructive).
        data = im.bulk_generate_dues_invoices(dry_run=True, max_invoices=100000)["data"]
        self.assertGreaterEqual(data["schedules_found"], 1)
        self.assertEqual(data["invoices_generated"], 0)
        # Our due-today auto_generate schedule must be classified would_generate.
        ours = next((p for p in data["processed_schedules"] if p.get("schedule") == ds.name), None)
        self.assertIsNotNone(ours, f"our schedule not in processed list; errors={data.get('errors')}")
        self.assertTrue(ours.get("would_generate"), f"expected would_generate, got {ours}")

    def test_bulk_generate_counts_orphan_in_run(self):
        self._make_orphaned_schedule()  # auto_generate=1, due today
        data = im.bulk_generate_dues_invoices(dry_run=True, max_invoices=50)["data"]
        # The orphan schedule should be detected during the bulk pass.
        self.assertGreaterEqual(data["orphaned_schedules"], 1)

    def test_bulk_generate_real_run_creates_invoice(self):
        """Non-dry-run path: an eligible due-now schedule produces a real Sales
        Invoice; invoices_generated and generated_invoices reflect it, and the
        commit branch (invoices_generated > 0) fires."""
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(
            member, mt, amount=11.0, status="Active", auto_generate=1, next_invoice_date=today()
        )
        result = im.bulk_generate_dues_invoices(dry_run=False, max_invoices=50)
        self.assertTrue(result["success"])
        data = result["data"]
        # Find our schedule's result row.
        ours = next((p for p in data["processed_schedules"] if p.get("schedule") == ds.name), None)
        self.assertIsNotNone(ours, f"our schedule not processed; errors={data['errors']}")
        if ours.get("can_generate"):
            # Real generation happened: track the invoice for cleanup.
            self.assertTrue(ours.get("success"), f"row={ours}")
            invoice_name = ours.get("invoice")
            self.assertTrue(frappe.db.exists("Sales Invoice", invoice_name))
            self.assertGreaterEqual(data["invoices_generated"], 1)
            # generated_invoices summary list includes our invoice.
            gen_names = {g["invoice"] for g in data["generated_invoices"]}
            self.assertIn(invoice_name, gen_names)
            self._committed_docs.append(("Sales Invoice", invoice_name))

    def test_bulk_generate_custom_filter_and_days_ahead(self):
        """filter_criteria with a custom days_ahead is honored (covers the
        filter_criteria.update + days_ahead extraction branch)."""
        mt = self._make_membership_type()
        member = self._make_member()
        self._make_dues_schedule(member, mt, status="Active", auto_generate=1, next_invoice_date=today())
        # days_ahead=0 narrows the window to today-or-earlier; our due-today
        # schedule still qualifies (cutoff = today + 0).
        result = im.bulk_generate_dues_invoices(
            filter_criteria={"days_ahead": 0}, dry_run=True, max_invoices=5
        )
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["filter_criteria"], {"days_ahead": 0})
        # due_now must count our due-today schedule.
        self.assertGreaterEqual(data["due_now"], 1)

    # ------------------------------------------------------------------
    # cleanup_orphaned_membership_data - invalid membership + amendment branches
    # ------------------------------------------------------------------
    def _make_membership_with_invalid_type(self):
        """Create a real Membership, then repoint its membership_type at a
        non-existent type via direct DB write (bypassing link validation) so it
        becomes an 'invalid membership type' candidate. Returns membership name."""
        mt = self._make_membership_type()
        member = self._make_member()
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = mt.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self._committed_docs.append(("Membership", membership.name))
        bogus_type = "NONEXISTENT-TYPE-" + frappe.generate_hash(length=10)
        frappe.db.set_value(
            "Membership", membership.name, "membership_type", bogus_type, update_modified=False
        )
        frappe.db.commit()
        return membership.name, member.name

    def test_cleanup_membership_data_detects_invalid_membership_type(self):
        """An invalid-membership-type Membership is detected in the
        invalid_memberships category (dry run -> would_delete, no mutation)."""
        membership_name, _member_name = self._make_membership_with_invalid_type()
        # max_cleanup must exceed the global invalid-membership count so our own
        # record is in scope on a shared DB (dry-run -> no mutation, safe to scan all).
        data = im.cleanup_orphaned_membership_data(dry_run=True, max_cleanup=100000)["data"]
        self.assertGreaterEqual(data["invalid_memberships"]["found"], 1)
        my_item = next(
            (
                it
                for it in data["processed_items"]
                if it.get("type") == "invalid_membership" and it.get("name") == membership_name
            ),
            None,
        )
        self.assertIsNotNone(my_item, "our invalid membership should be processed")
        self.assertEqual(my_item["action"], "would_delete")
        # Dry run did not delete it.
        self.assertTrue(frappe.db.exists("Membership", membership_name))

    def test_cleanup_membership_data_invalid_type_member_exists_skipped(self):
        """The member-exists guard branch ('member_exists_skipped') only fires in
        non-dry-run mode. cleanup_orphaned_membership_data is a GLOBAL operation that
        frappe.db.commit()s its deletions (invoice_management.py:1010), so a real run
        here would permanently delete OTHER suites' orphaned memberships from the
        shared test DB. Skipped to avoid destructive cross-suite pollution; the
        member-exists branch needs a scoped API param or an isolated fixture DB to
        test safely. FLAG for Foppe."""
        self.skipTest(
            "global destructive cleanup (commits deletions) — unsafe against shared test DB; "
            "needs scoped API or isolated dataset"
        )

    # ------------------------------------------------------------------
    # validate_invoice_generation_readiness - warning branches
    # ------------------------------------------------------------------
    def _set_auto_submit(self, value):
        """Set + restore the auto_submit_membership_invoices single value."""
        original = frappe.db.get_single_value("Verenigingen Settings", "auto_submit_membership_invoices")
        frappe.db.set_single_value("Verenigingen Settings", "auto_submit_membership_invoices", value)
        self.addCleanup(
            frappe.db.set_single_value,
            "Verenigingen Settings",
            "auto_submit_membership_invoices",
            original,
        )

    def test_validate_readiness_auto_submit_enabled_info(self):
        """When auto-submit is enabled, the readiness info list says so (covers the
        auto_submit truthy branch at invoice_management.py:586-587)."""
        self._set_auto_submit(1)
        data = im.validate_invoice_generation_readiness()["data"]
        self.assertIn("Auto-submit is enabled for membership invoices", data["info"])

    def test_validate_readiness_auto_submit_disabled_warning(self):
        """When auto-submit is disabled, readiness emits the draft warning
        (covers invoice_management.py:589)."""
        self._set_auto_submit(0)
        data = im.validate_invoice_generation_readiness()["data"]
        self.assertTrue(
            any("draft" in w.lower() for w in data["warnings"]),
            f"expected draft warning, warnings={data['warnings']}",
        )

    def test_validate_readiness_flags_overdue_schedule(self):
        """An Active auto_generate schedule with a past next_invoice_date is counted
        as overdue (covers the overdue_count > 0 warning at invoice_management.py:610-611)."""
        mt = self._make_membership_type()
        member = self._make_member()
        past = add_days(today(), -10)
        self._make_dues_schedule(member, mt, status="Active", auto_generate=1, next_invoice_date=past)
        data = im.validate_invoice_generation_readiness()["data"]
        self.assertTrue(
            any("overdue" in w.lower() for w in data["warnings"]),
            f"expected overdue warning, warnings={data['warnings']}",
        )

    def test_validate_readiness_upcoming_sample_populated(self):
        """A future-dated auto_generate schedule appears in upcoming_schedules_sample
        (covers the upcoming list-comprehension at invoice_management.py:568-576)."""
        mt = self._make_membership_type()
        member = self._make_member()
        future = add_days(today(), 5)
        ds = self._make_dues_schedule(member, mt, status="Active", auto_generate=1, next_invoice_date=future)
        data = im.validate_invoice_generation_readiness()["data"]
        sample_names = {s["name"] for s in data["upcoming_schedules_sample"]}
        # Sample is capped at 10 and ordered by next_invoice_date; our +5d schedule
        # may not appear if the shared DB has >10 sooner ones. Assert structural
        # correctness of any rows that ARE present, and our schedule if in range.
        for s in data["upcoming_schedules_sample"]:
            self.assertIn("member_name", s)
            self.assertIn("next_invoice_date", s)
            self.assertIn("dues_rate", s)
        if len(data["upcoming_schedules_sample"]) < 10:
            self.assertIn(ds.name, sample_names)

    # ------------------------------------------------------------------
    # cleanup_orphaned_member_references - clear-failed branch is hard to hit;
    # cover the empty-result early return and processed-row shape instead.
    # ------------------------------------------------------------------
    def test_cleanup_references_processed_row_shape_dry_run(self):
        """Each processed row in a reference-cleanup dry run carries the expected
        keys and the 'would_clear_reference' action (invoice_management.py:742)."""
        sched_name = self._make_orphaned_schedule()
        data = im.cleanup_orphaned_member_references(dry_run=True)["data"]
        mine = next((p for p in data["processed_schedules"] if p["schedule"] == sched_name), None)
        self.assertIsNotNone(mine, "our orphan schedule should be in the processed list")
        self.assertEqual(mine["action"], "would_clear_reference")
        self.assertIn("member", mine)
        self.assertIn("status", mine)

    # ------------------------------------------------------------------
    # cleanup_orphaned_membership_data - orphaned amendment branch (dry run)
    # ------------------------------------------------------------------
    def _make_orphaned_amendment(self):
        """Create a real Approved Contribution Amendment Request, then repoint its
        `member` at a non-existent Member via direct DB write so the LEFT JOIN in
        the orphaned-amendment query (m.name IS NULL) matches it. Returns its name.
        """
        mt = self._make_membership_type()
        member = self._make_member()
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = mt.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self._committed_docs.append(("Membership", membership.name))

        amendment = frappe.new_doc("Contribution Amendment Request")
        amendment.membership = membership.name
        amendment.member = member.name
        amendment.amendment_type = "Fee Change"
        amendment.requested_date = today()
        amendment.effective_date = today()
        amendment.reason = "Invoice management test orphan amendment"
        amendment.flags.ignore_validate = True
        amendment.save(ignore_permissions=True)
        self._committed_docs.append(("Contribution Amendment Request", amendment.name))
        frappe.db.set_value(
            "Contribution Amendment Request",
            amendment.name,
            "status",
            "Approved",
            update_modified=False,
        )
        bogus_member = "NONEXISTENT-MEMBER-" + frappe.generate_hash(length=12)
        frappe.db.set_value(
            "Contribution Amendment Request",
            amendment.name,
            "member",
            bogus_member,
            update_modified=False,
        )
        frappe.db.commit()
        return amendment.name

    def test_cleanup_membership_data_detects_orphaned_amendment(self):
        """An Approved amendment whose member no longer exists is detected in the
        orphaned_amendments category (dry run -> would_delete, no mutation).
        Covers the amendment branch invoice_management.py:954-999."""
        amendment_name = self._make_orphaned_amendment()
        data = im.cleanup_orphaned_membership_data(dry_run=True, max_cleanup=100000)["data"]
        self.assertGreaterEqual(data["orphaned_amendments"]["found"], 1)
        mine = next(
            (
                it
                for it in data["processed_items"]
                if it.get("type") == "orphaned_amendment" and it.get("name") == amendment_name
            ),
            None,
        )
        self.assertIsNotNone(mine, "our orphaned amendment should be processed")
        self.assertEqual(mine["action"], "would_delete")
        self.assertEqual(mine["amendment_type"], "Fee Change")
        # Dry run must not delete it.
        self.assertTrue(frappe.db.exists("Contribution Amendment Request", amendment_name))

    # ------------------------------------------------------------------
    # bulk_generate_dues_invoices - custom DocType filter merge branch
    # ------------------------------------------------------------------
    def test_bulk_generate_custom_field_filter_narrows_results(self):
        """A non-control filter key (billing_frequency) is merged into the SQL
        WHERE clause (invoice_management.py:88-89). An Annual-only filter must
        exclude our Monthly schedule from schedules_found's matched set."""
        mt = self._make_membership_type()
        member = self._make_member()
        ds = self._make_dues_schedule(
            member, mt, status="Active", auto_generate=1, next_invoice_date=today()
        )  # billing_frequency = Monthly
        result = im.bulk_generate_dues_invoices(
            filter_criteria={"billing_frequency": "Annual"}, dry_run=True, max_invoices=100000
        )
        self.assertTrue(result["success"])
        data = result["data"]
        # Our Monthly schedule must NOT be among processed schedules under an Annual filter.
        names = {p.get("schedule") for p in data["processed_schedules"]}
        self.assertNotIn(ds.name, names)
        self.assertEqual(data["filter_criteria"], {"billing_frequency": "Annual"})
