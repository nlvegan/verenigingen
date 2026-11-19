# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
#1844: the ``update_child_table`` link_validation retry decided WHETHER to tolerate a dead link by
matching the error TEXT (``Chapter:`` and ``Could not find Row``). The scope it tolerates is unchanged
here (a dead Chapter in a Chapter Membership History row, plus a Dynamic Link with no doctype); only the
decision is now made from the data, so it holds in any user language and in any order of the message.

Probe shortcut (stated, not hidden): dead-link rows and the dead ``previous_chapter`` are written with
``db_insert`` / ``db.set_value`` to stand in for legacy data; whether a real Member carries them has not
been queried.
"""

import frappe
from frappe.utils import add_to_date, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.secure_operations import secure_document_operation


class TestLinkValidationRetryScope1844(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Bypass1844", last_name="Scope", birth_date="1975-09-09")
        self.admin = self.ensure_test_admin_user().name

    def _dead_chapter_row(self):
        ghost = f"GHOST-CH-{frappe.generate_hash(length=6)}"
        row = frappe.get_doc(
            {
                "doctype": "Chapter Membership History",
                "parent": self.member.name,
                "parenttype": "Member",
                "parentfield": "chapter_membership_history",
                "idx": 90,
                "chapter_name": ghost,
                "assignment_type": "Member",
                "start_date": today(),
                "status": "Active",
            }
        )
        row.db_insert()
        self.addCleanup(frappe.db.delete, "Chapter Membership History", {"name": row.name})
        return row.name, ghost

    def _dead_payment_history_row(self):
        """A dead link OUTSIDE the tolerated scope: doctype set, document gone."""
        ghost = f"GHOST-INV-{frappe.generate_hash(length=6)}"
        row = frappe.get_doc(
            {
                "doctype": "Member Payment History",
                "parent": self.member.name,
                "parenttype": "Member",
                "parentfield": "payment_history",
                "idx": 99,
                "reference_doctype": "Sales Invoice",
                "reference_name": ghost,
            }
        )
        row.db_insert()
        self.addCleanup(frappe.db.delete, "Member Payment History", {"name": row.name})
        return row.name, ghost

    def _dead_previous_chapter(self):
        ghost = f"GHOST-PREV-{frappe.generate_hash(length=6)}"
        frappe.db.set_value("Member", self.member.name, "previous_chapter", ghost, update_modified=False)
        return ghost

    def _update(self, lang=None):
        previous_user, previous_lang = frappe.session.user, frappe.local.lang
        frappe.set_user(self.admin)
        if lang:
            frappe.local.lang = lang  # Mock justified: execution-context language switch, not a stub
        try:
            return secure_document_operation(
                operation="update_child_table",
                doc=frappe.get_doc("Member", self.member.name),
                justification="1844 scope probe",
                required_permissions=["Member:write"],
                bypass_validations=["link_validation"],
            )
        finally:
            frappe.local.lang = previous_lang  # Mock justified: restores the execution-context language
            frappe.set_user(previous_user)

    def test_tolerated_dead_chapter_row_is_kept(self):
        """CONTROL (green on develop): the shape the retry exists for."""
        row_name, ghost = self._dead_chapter_row()
        result = self._update()
        self.assertTrue(result.success, result.errors)
        self.assertEqual(frappe.db.get_value("Chapter Membership History", row_name, "chapter_name"), ghost)

    def test_tolerated_dead_chapter_row_is_kept_for_a_dutch_user(self):
        """Frappe translates the message ("Kon Rij #90: Hoofdstuk: X niet vinden"), so a text match on
        'Chapter:' / 'Could not find Row' refused the in-scope case for every Dutch-language user."""
        self.assertNotEqual(
            frappe.get_attr("frappe.translate.get_all_translations")("nl").get("Could not find {0}"),
            "Could not find {0}",
            "the nl translation must exist or this test is vacuous",
        )
        row_name, ghost = self._dead_chapter_row()
        result = self._update(lang="nl")
        self.assertTrue(result.success, result.errors)
        self.assertEqual(frappe.db.get_value("Chapter Membership History", row_name, "chapter_name"), ghost)

    def _dynamic_link_row_without_doctype(self):
        """The tolerated 'Reference DocType must be set first' shape (reference_name, no doctype)."""
        row = frappe.get_doc(
            {
                "doctype": "Member Payment History",
                "parent": self.member.name,
                "parenttype": "Member",
                "parentfield": "payment_history",
                "idx": 98,
                "reference_name": f"GHOST-REF-{frappe.generate_hash(length=6)}",
            }
        )
        row.db_insert()
        self.addCleanup(frappe.db.delete, "Member Payment History", {"name": row.name})
        return row.name

    def test_dynamic_link_row_without_doctype_is_still_tolerated(self):
        """CONTROL: the second tolerated shape keeps working (also in Dutch)."""
        for lang in (None, "nl"):
            row_name = self._dynamic_link_row_without_doctype()
            result = self._update(lang=lang)
            self.assertTrue(result.success, (lang, result.errors))
            self.assertTrue(frappe.db.get_value("Member Payment History", row_name, "reference_name"))

    def test_timestamp_conflict_is_not_retried_over_a_tolerated_dynamic_link_row(self):
        """The retry resets doc.modified to the DB value, so retrying a TimestampMismatchError (raised
        BEFORE link validation) would be a lost update. Only a link error may be retried."""
        self._dynamic_link_row_without_doctype()
        member = frappe.get_doc("Member", self.member.name)
        frappe.db.set_value("Member", self.member.name, "modified", add_to_date(member.modified, seconds=5))
        previous_user = frappe.session.user
        frappe.set_user(self.admin)
        self.expectErrorLog()
        try:
            result = secure_document_operation(
                operation="update_child_table",
                doc=member,
                justification="1844 timestamp probe",
                required_permissions=["Member:write"],
                bypass_validations=["link_validation"],
            )
        finally:
            frappe.set_user(previous_user)
        self.assertFalse(result.success, "a stale save was retried and overwrote a newer one")
        self.assertIn("modified", "; ".join(result.errors).lower())

    def test_no_dead_link_found_refuses_the_retry(self):
        """Fails closed: a link-validation error with nothing dead in the snapshot is not retried."""
        from verenigingen.utils.secure_operations import _link_error_is_within_bypass_scope

        self.assertFalse(_link_error_is_within_bypass_scope(frappe.LinkValidationError("x"), []))

    def test_dead_own_link_alone_is_refused(self):
        """CONTROL: the parent's own dead Link is outside the scope (green on develop too)."""
        ghost = self._dead_previous_chapter()
        self.expectErrorLog()
        result = self._update()
        self.assertFalse(result.success)
        self.assertIn(ghost, "; ".join(result.errors))
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "previous_chapter"), ghost)

    def test_dead_own_link_with_a_tolerated_row_is_refused(self):
        """Mixed: the tolerated row must not carry the untolerated parent link through."""
        row_name, row_ghost = self._dead_chapter_row()
        ghost = self._dead_previous_chapter()
        self.expectErrorLog()
        result = self._update()
        self.assertFalse(result.success)
        self.assertIn(ghost, "; ".join(result.errors))
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "previous_chapter"), ghost)

    def test_untolerated_dead_row_link_with_a_tolerated_row_is_refused(self):
        """Mixed, both in child rows: on develop the message contains 'Chapter:' and 'Could not find
        Row', so the retry fired and PERSISTED the dead Sales Invoice reference as well."""
        self._dead_chapter_row()
        self._dead_payment_history_row()
        self.expectErrorLog()
        result = self._update()
        self.assertFalse(result.success, "the dead Payment History reference must not be tolerated")
        self.assertIn("Could not find", "; ".join(result.errors))

    def test_untolerated_dead_row_link_alone_is_refused(self):
        """CONTROL (green on develop too)."""
        self._dead_payment_history_row()
        self.expectErrorLog()
        result = self._update()
        self.assertFalse(result.success)
