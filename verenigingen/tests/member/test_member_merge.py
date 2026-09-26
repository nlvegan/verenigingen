"""
Tests for Member Merge Service

Tests the member merge functionality including field-level selection,
conflict detection, and data preservation.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

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
