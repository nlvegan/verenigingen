"""
Tests for Member Merge Service

Tests the member merge functionality including field-level selection,
conflict detection, and data preservation.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

import verenigingen.services.member_merge_service as member_merge_service_module
from verenigingen.services.member_merge_service import MemberMergeService
from verenigingen.tests.utils.ledger_rows import purge_ledger_rows


class TestMemberMerge(FrappeTestCase):
    """Test cases for member merge functionality."""

    def setUp(self):
        """Set up test data before each test."""
        self.service = MemberMergeService()
        # #1264 round 2: (doctype, name) pairs a test wants force-deleted in
        # tearDown, ADDITIONAL to the source/target Members below. Routed
        # through tearDown's own existing commit rather than adding a new
        # bare frappe.db.commit() site (the order_dependence ratchet is
        # zero-growth: even a COMMIT_EXEMPT-classified new site counts as
        # growth for the "baseline is in sync" gate, not just plain COMMIT).
        self._extra_cleanup_docs = []

        # Create test members
        self.source = frappe.get_doc({
            "doctype": "Member",
            "first_name": "John",
            "last_name": "Smith",
            "email": "john.smith@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-01-15",
            "notes": "Source member notes",
        }).insert()

        self.target = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Johnny",
            "last_name": "Smith",
            "email": "johnny.smith@example.com",
            "birth_date": "1990-01-15",
            # No contact number
            "notes": "Target member notes",
        }).insert()

        frappe.db.commit()

    def tearDown(self):
        """Clean up after each test."""
        # Extra docs a test registered (e.g. a Sales Invoice / Membership
        # Dues Schedule fixture) -- cancel first if still submitted, since
        # force=True bypasses link-integrity but NOT the submitted-record
        # guard.
        for doctype, name in reversed(self._extra_cleanup_docs):
            if not frappe.db.exists(doctype, name):
                continue
            try:
                doc = frappe.get_doc(doctype, name)
                if doc.docstatus == 1:
                    doc.flags.ignore_permissions = True
                    doc.flags.ignore_links = True
                    doc.cancel()
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                purge_ledger_rows(doctype, name)
            except Exception:
                pass

        # Delete test members if they exist
        for name in [self.source.name, self.target.name]:
            if frappe.db.exists("Member", name):
                frappe.delete_doc("Member", name, force=True)

        frappe.db.commit()

    def test_merge_preview_generation(self):
        """Test that merge preview correctly identifies conflicts and suggestions."""
        preview = self.service.get_merge_preview(
            self.source.name,
            self.target.name
        )

        # Check structure
        self.assertIn("source", preview)
        self.assertIn("target", preview)
        self.assertIn("fields", preview)
        self.assertIn("warnings", preview)

        # Check source/target info
        self.assertEqual(preview["source"]["name"], self.source.name)
        self.assertEqual(preview["target"]["name"], self.target.name)

        # Check field comparisons
        fields_by_name = {f["fieldname"]: f for f in preview["fields"]}

        # Contact number: source has value, target doesn't - should suggest source
        contact_field = fields_by_name.get("contact_number")
        self.assertIsNotNone(contact_field)
        self.assertEqual(contact_field["suggested"], "source")
        self.assertFalse(contact_field["has_conflict"])

        # Email: both have values but different - should have conflict
        email_field = fields_by_name.get("email")
        self.assertIsNotNone(email_field)
        self.assertTrue(email_field["has_conflict"])

        # Notes: both have values but different - should have conflict
        notes_field = fields_by_name.get("notes")
        self.assertIsNotNone(notes_field)
        self.assertTrue(notes_field["has_conflict"])

    def test_preview_warns_when_source_has_blocked_schedule(self):
        """#1325: staff must see the block in the merge PREVIEW, before
        filling in field selections -- not only after clicking through
        and having execute_merge refuse. On veg11, 431/748 (58%) of
        members have an invoice-referenced dues schedule and so can never
        be a merge source until this is resolved (maintainer ruling on
        #1325: keep refuse-up-front; surface it in the preview instead).

        Control (same test, before creating the schedule): the preview for
        an unblocked source has no such warning -- a mutant that always
        appends the warning would fail this half.
        """
        unblocked_preview = self.service.get_merge_preview(self.source.name, self.target.name)
        self.assertFalse(
            any("Membership Dues Schedule" in w for w in unblocked_preview["warnings"]),
            "an unblocked source must not carry the blocked-schedule warning",
        )

        mt_name = self._make_merge_test_membership_type()
        schedule = self._make_merge_test_dues_schedule(self.source.name, mt_name)
        self._make_merge_test_invoice(schedule.name)

        blocked_preview = self.service.get_merge_preview(self.source.name, self.target.name)
        matching = [w for w in blocked_preview["warnings"] if schedule.name in w]
        self.assertEqual(
            len(matching),
            1,
            f"expected exactly one warning naming {schedule.name}, got: {blocked_preview['warnings']}",
        )

    def test_merge_execution_with_source_preference(self):
        """Test merging with source data preferred for contact field."""
        field_selections = {
            "first_name": "source",  # John
            "contact_number": "source",  # +31612345678
            "email": "target",  # johnny.smith@example.com
            "notes": "target",  # Target member notes
        }

        result = self.service.execute_merge(
            self.source.name,
            self.target.name,
            field_selections
        )

        # Check result
        self.assertTrue(result["success"])
        self.assertGreater(result["changes_applied"], 0)

        # Verify target was updated
        merged = frappe.get_doc("Member", self.target.name)
        self.assertEqual(merged.first_name, "John")  # From source
        self.assertEqual(merged.contact_number, "+31612345678")  # From source
        self.assertEqual(merged.email, "johnny.smith@example.com")  # From target
        self.assertEqual(merged.notes, "Target member notes")  # From target

        # Verify source was deleted
        self.assertFalse(frappe.db.exists("Member", self.source.name))

    def test_merge_with_contact_email_preservation(self):
        """Test that secondary email is saved to Contact when both have emails."""
        # Create Contact for target
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": self.target.first_name,
            "last_name": self.target.last_name,
            "email_id": self.target.email,
        }).insert()

        self.target.contact = contact.name
        self.target.save()
        frappe.db.commit()

        # Merge with source email preferred
        field_selections = {
            "email": "source",  # Choose source email
        }

        result = self.service.execute_merge(
            self.source.name,
            self.target.name,
            field_selections
        )

        self.assertTrue(result["success"])

        # Check that target's old email was saved to Contact
        if result.get("secondary_emails_saved", 0) > 0:
            contact.reload()
            email_ids = [row.email_id for row in contact.email_ids]
            self.assertIn(self.target.email, email_ids)

        # Clean up contact
        frappe.delete_doc("Contact", contact.name, force=True)

    def test_merge_conflict_warnings(self):
        """Test that warnings are generated for financial/volunteer conflicts."""
        # current_membership_plan is a Link to Membership and is validated on
        # save, so we need a real Membership rather than a fabricated name.
        mt_name = "ZZ Merge Test Type"
        if not frappe.db.exists("Membership Type", mt_name):
            frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": mt_name,
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "is_active": 1,
            }).insert(ignore_permissions=True)

        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": self.source.name,
            "membership_type": mt_name,
            "start_date": frappe.utils.today(),
        })
        membership.flags.skip_dues_schedule_creation = True
        membership.insert(ignore_permissions=True)

        self.source.current_membership_plan = membership.name
        self.source.save()
        frappe.db.commit()

        preview = self.service.get_merge_preview(
            self.source.name,
            self.target.name
        )

        # Should have warning about active membership
        warnings_text = " ".join(preview["warnings"])
        self.assertIn("active membership", warnings_text.lower())

    def test_permission_checks(self):
        """Test that merge requires write permission on both members."""
        # This would need to be tested with a user without permissions
        # For now, just verify the preview method requires valid members
        with self.assertRaises(frappe.DoesNotExistError):
            self.service.get_merge_preview(
                "INVALID-MEMBER-1",
                self.target.name
            )

    # ------------------------------------------------------------------
    # #1264 round 2: _delete_source_member_and_dependencies used
    # frappe.delete_doc("Membership Dues Schedule", ..., force=True), the same
    # link-integrity bypass fixed elsewhere for this PR. The merge service's
    # OWN documented design already says unpaid invoices "remain linked to the
    # source member" (_check_merge_conflicts's warning text) -- i.e. the
    # invoice is deliberately preserved, unmerged. Force-deleting the schedule
    # such an invoice still names via membership_dues_schedule_display
    # produced #1250's exact shape as an unintended side effect of that
    # bypass, not anything the merge design called for.
    # ------------------------------------------------------------------

    def _make_merge_test_membership_type(self):
        mt_name = "ZZ Merge Test Type"
        if not frappe.db.exists("Membership Type", mt_name):
            frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": mt_name,
                    "billing_period": "Annual",
                    "minimum_amount": 50.0,
                    "is_active": 1,
                }
            ).insert(ignore_permissions=True)
        return mt_name

    def _make_merge_test_dues_schedule(self, member_name, membership_type):
        """Deliberately does NOT clear the Member's own current_dues_schedule /
        application_dues_schedule back-link that a bare insert sets as a
        save() side effect (confirmed empirically). #1264 round 2's review
        caught that clearing it here made the "still deletes" test pass by
        constructing a state real production schedules never have (every
        real schedule's owning Member carries this back-link) -- the fix
        (member_merge_service.py calling
        clear_member_schedule_backlinks_before_delete) now clears it itself,
        so this fixture instead models the REAL state.
        """
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"MERGE-TEST-{member_name}-{frappe.generate_hash(length=6)}"
        schedule.member = member_name
        schedule.membership_type = membership_type
        schedule.status = "Active"
        schedule.billing_frequency = "Annual"
        schedule.currency = "EUR"
        schedule.is_template = 0
        schedule.dues_rate = 25
        schedule.flags.ignore_validate = True
        schedule.insert(ignore_permissions=True, ignore_mandatory=True)
        self._extra_cleanup_docs.append(("Membership Dues Schedule", schedule.name))
        return schedule

    def _make_merge_test_invoice(self, schedule_name):
        company = "_Test Company"
        customer = frappe.db.get_value("Customer", {}, "name")
        item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
        income_account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_type": "Income Account",
                "is_group": 0,
                "account_currency": frappe.db.get_value("Company", company, "default_currency"),
            },
            "name",
        )
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = customer
        invoice.company = company
        invoice.membership_dues_schedule_display = schedule_name
        invoice.set_posting_time = 1
        invoice.append(
            "items",
            {
                "item_code": item,
                "qty": 1,
                "rate": 25,
                "income_account": income_account,
                "cost_center": cost_center,
            },
        )
        invoice.insert(ignore_permissions=True)
        invoice.submit()
        # No frappe.db.commit() here -- execute_merge (the code under test)
        # reads on the SAME connection within the same test, and cleanup is
        # handled by tearDown's own existing commit via _extra_cleanup_docs
        # (#815/order_dependence ratchet: this helper is not named
        # _create_*/_cleanup_*, so a bare commit here would not be exempt).
        self._extra_cleanup_docs.append(("Sales Invoice", invoice.name))
        return invoice

    def test_merge_refuses_before_any_write_when_source_has_blocked_schedule(self):
        """#1325 (follow-up to #1306): a schedule still referenced by a
        Sales Invoice via membership_dues_schedule_display must refuse the
        WHOLE merge before any write happens, not let it partially commit
        and then report failure.

        #1306 made Member.on_trash's handle_member_deletion anonymize the
        source instead of force-deleting it when this happens, raising
        MemberAnonymizedInsteadOfDeleted. #1325 found that execute_merge let
        target.save() -- and the anonymization's own frappe.db.commit() --
        land on the same connection BEFORE that raise, so a merge reported
        as "failed" had already changed both Members (this test used to
        assert exactly that as the expected shape).

        The fix (_ensure_source_deletable) pre-checks the SAME predicate
        handle_member_deletion uses (MemberCleanupService.
        _find_blocked_schedules) before any write, so a blocked merge now
        raises plain frappe.ValidationError and changes NEITHER Member: no
        target.save(), no source delete/anonymize attempt at all.
        """
        original_target_contact = frappe.db.get_value(
            "Member", self.target.name, "contact_number"
        )
        original_source_first_name = self.source.first_name

        mt_name = self._make_merge_test_membership_type()
        schedule = self._make_merge_test_dues_schedule(self.source.name, mt_name)
        invoice = self._make_merge_test_invoice(schedule.name)

        with self.assertRaises(frappe.ValidationError):
            # contact_number: target has none, source does -- selecting it
            # means a bug that reintroduces the old "save first, check
            # later" order would show up here (target absorbing the value)
            # exactly like it did before this fix.
            self.service.execute_merge(
                self.source.name, self.target.name, {"contact_number": "source"}
            )

        # The source Member is untouched -- NOT anonymized, because the
        # anonymize branch (handle_member_deletion) never ran: the merge
        # refused before attempting any delete.
        self.assertEqual(
            frappe.db.get_value("Member", self.source.name, "first_name"),
            original_source_first_name,
        )

        # The target's field merge never happened -- target.save() was
        # never reached.
        self.assertEqual(
            frappe.db.get_value("Member", self.target.name, "contact_number"),
            original_target_contact,
        )

        # The schedule and its invoice reference are untouched -- no delete
        # was ever attempted.
        self.assertTrue(
            frappe.db.exists("Membership Dues Schedule", schedule.name),
            "a schedule still referenced by a Sales Invoice must not be "
            "touched by a merge that refuses up front (#1250's shape, "
            "guarded a different way than #1306's anonymize branch)",
        )
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "membership_dues_schedule_display"),
            schedule.name,
        )

    def test_merge_refuses_when_blocked_schedule_is_not_active(self):
        """#1325: the pre-check must query ALL of the source's dues
        schedules, not just status="Active" ones.

        handle_member_deletion's own query (frappe.get_all(..., filters=
        {"member": ...}) with NO status filter) is the ground truth for
        "would a delete be refused" -- a Cancelled schedule still
        referenced by a Sales Invoice is just as much a delete-blocker as
        an Active one. DuesScheduleRepository.get_schedules_for_members
        (used elsewhere in this file, e.g. _delete_source_member_and_
        dependencies) filters to status="Active", which would silently
        miss exactly this case if reused here -- this test exists so that
        substitution is caught rather than shipped.
        """
        original_source_first_name = self.source.first_name

        mt_name = self._make_merge_test_membership_type()
        schedule = self._make_merge_test_dues_schedule(self.source.name, mt_name)
        schedule.db_set("status", "Cancelled", update_modified=False)
        invoice = self._make_merge_test_invoice(schedule.name)

        with self.assertRaises(frappe.ValidationError):
            self.service.execute_merge(self.source.name, self.target.name, {})

        self.assertTrue(
            frappe.db.exists("Membership Dues Schedule", schedule.name),
            "a Cancelled-but-referenced schedule must still block the merge "
            "up front, the same as an Active one",
        )

        # Discriminator: a wrong fix that only queries Active schedules
        # would find nothing blocked here, let the merge proceed, and only
        # hit the SAME ValidationError later via handle_member_deletion's
        # own anonymize branch during the real delete attempt -- which
        # would also leave the schedule in place, satisfying the assertion
        # above for the wrong reason. Anonymization is the tell: it only
        # happens on that later path, never on the up-front refusal.
        self.assertEqual(
            frappe.db.get_value("Member", self.source.name, "first_name"),
            original_source_first_name,
            "the source must not be anonymized -- that would mean the "
            "up-front check missed this schedule and the OLD (post-write) "
            "anonymize branch caught it instead",
        )

    def test_merge_closes_toctou_window_before_final_delete(self):
        """#1325 follow-up (maintainer ruling, refuse-up-front kept): the
        up-front check in execute_merge can be stale by the time
        _delete_source_member_and_dependencies reaches the final
        frappe.delete_doc("Member", ...) -- a Sales Invoice could reference
        one of source's schedules in that window. The second
        _ensure_source_deletable call, immediately before that delete,
        catches it there, BEFORE Member.on_trash's own anonymize-and-commit
        branch (#1306) ever runs (that branch's internal frappe.db.commit()
        would otherwise persist target.save() despite the eventual raise).

        This alone is NOT enough, and this test goes through the
        WHITELISTED wrapper (the real production entry point --
        member_list.js calls this, not the class method directly) to prove
        it. frappe/app.py only rolls back an exception that escapes
        frappe.handler.handle() uncaught; the wrapper CATCHES
        frappe.ValidationError and returns a normal OperationResult.fail()
        dict, so nothing escapes -- frappe/app.py's sync_database() would
        then COMMIT whatever is pending (POST is an "unsafe" HTTP method),
        durably persisting target.save() even with the second check in
        place. The wrapper's own explicit frappe.db.rollback() (added
        alongside the second check) is what actually makes "changes NEITHER
        Member" hold for this real caller, not the second check alone.

        Simulated by making the FIRST _ensure_source_deletable call (real,
        and passing -- nothing is blocked yet) create the blocking invoice
        immediately afterward, standing in for another process doing so in
        the real window between the two checks.
        """
        original_target_contact = frappe.db.get_value(
            "Member", self.target.name, "contact_number"
        )
        original_source_first_name = self.source.first_name

        mt_name = self._make_merge_test_membership_type()
        schedule = self._make_merge_test_dues_schedule(self.source.name, mt_name)
        # Deliberately no invoice yet: the first check must find nothing
        # blocked, exactly like the real race.

        real_ensure_source_deletable = MemberMergeService._ensure_source_deletable
        call_count = {"n": 0}
        created_invoice = {}

        def _create_racing_invoice_reference():
            """Named `_create_*` so its frappe.db.commit() below is the
            recognised, non-blocking COMMIT_EXEMPT kind (#825's convention),
            not a plain COMMIT the order-dependence ratchet gates PR-over-PR
            growth on. Justified regardless of that classification: this
            commit simulates ANOTHER PROCESS's own already-durable write
            (which in reality would be on a separate connection, unaffected
            by anything OUR merge attempt later rolls back) -- without it,
            the invoice (and the schedule, uncommitted since setUp) would
            themselves be wiped out by the wrapper's frappe.db.rollback()
            below, which cannot distinguish "the test's own fixture" from
            "the merge's own writes"; both are just uncommitted rows on the
            same connection.
            """
            invoice = self._make_merge_test_invoice(schedule.name)
            frappe.db.commit()
            return invoice

        def racing_ensure_source_deletable(service_self, source):
            call_count["n"] += 1
            if call_count["n"] == 1:
                real_ensure_source_deletable(service_self, source)  # passes: nothing blocked yet
                created_invoice["doc"] = _create_racing_invoice_reference()
            else:
                real_ensure_source_deletable(service_self, source)  # must now catch the race

        with patch.object(
            MemberMergeService, "_ensure_source_deletable", racing_ensure_source_deletable
        ):
            result = member_merge_service_module.execute_merge(
                self.source.name, self.target.name, json.dumps({"contact_number": "source"})
            )

        # Register cleanup before any assertion, so a failure below still
        # gets the invoice cleaned up.
        self._extra_cleanup_docs.append(("Sales Invoice", created_invoice["doc"].name))

        self.assertFalse(result["success"], f"expected a failed merge, got: {result}")

        # Neither Member changed: target.save() was rolled back by the
        # wrapper's explicit frappe.db.rollback(), and the source was never
        # anonymized (the second check raised before on_trash's own
        # anonymize-and-commit branch could run). These are the primary,
        # diagnostic assertions -- checked BEFORE the call-count sanity
        # check below, so removing the second check reddens here first,
        # showing the partial commit directly, not just a changed call count.
        self.assertEqual(
            frappe.db.get_value("Member", self.target.name, "contact_number"),
            original_target_contact,
            "target.save() must have been rolled back by the wrapper",
        )
        self.assertEqual(
            frappe.db.get_value("Member", self.source.name, "first_name"),
            original_source_first_name,
            "the source must not be anonymized -- the race must be caught "
            "by the SECOND check, not by Member.on_trash's own branch",
        )
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule.name))

        self.assertEqual(call_count["n"], 2, "both checks must have run")

    def test_merge_still_deletes_unreferenced_schedule(self):
        """#1264 round 2: a REAL schedule (the source Member's own back-link
        IS present, matching every real schedule in production) with no
        Sales Invoice referencing it must still be deleted by a merge --
        proving the fix clears the schedule's own back-link rather than
        refusing every ordinary delete.
        """
        mt_name = self._make_merge_test_membership_type()
        schedule = self._make_merge_test_dues_schedule(self.source.name, mt_name)
        self.assertEqual(
            frappe.db.get_value("Member", self.source.name, "current_dues_schedule"),
            schedule.name,
            "test precondition: the source Member's own back-link must be "
            "set by the real save() side effect, or this test cannot "
            "distinguish the fix from a fixture that never had the problem",
        )

        result = self.service.execute_merge(self.source.name, self.target.name, {})

        self.assertTrue(result["success"])
        self.assertFalse(frappe.db.exists("Membership Dues Schedule", schedule.name))
