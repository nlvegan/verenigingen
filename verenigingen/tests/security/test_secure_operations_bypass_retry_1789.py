# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
#1789: secure_document_operation's ``link_validation`` bypass retry.

1. Under ``update_child_table`` the retry did not tolerate a dead Chapter reference in
   ``Chapter Membership History`` even for a System Manager. Cause (traced): Frappe's
   ``get_invalid_links`` does ``setattr(row, "chapter_name", values.name)`` BEFORE it reports
   the link, and ``values.name`` is None for a dead link, so the first (failing) save has
   already blanked the Link field on the in-memory row. The retry then saved a row with an
   empty Mandatory ``chapter_name``. (A Dynamic Link with no doctype raises BEFORE the setattr, so
   that shape was never blanked - measured: its control test below is green on develop.)
2. Under ``operation="save"`` the bypass is never acted on, yet two invoice-handler sites
   requested it for every System Manager, recording a bypass in the audit trail and the
   ``bypass_used`` metric that never happened.

Probe shortcut (stated, not hidden): the dead-link child rows are inserted with ``db_insert``
(a normal save refuses them) to stand in for how legacy data came to exist. Whether any real
Member carries such a row has not been queried.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.secure_operations import _get_metrics, secure_document_operation


class TestBypassRetryRestoresDeadLinks(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Bypass1789", last_name="Chap", birth_date="1975-09-09")
        self.ghost = f"GHOST-CHAPTER-{frappe.generate_hash(length=6)}"
        row = frappe.get_doc(
            {
                "doctype": "Chapter Membership History",
                "parent": self.member.name,
                "parenttype": "Member",
                "parentfield": "chapter_membership_history",
                "idx": 90,
                "chapter_name": self.ghost,
                "assignment_type": "Member",
                "start_date": today(),
                "status": "Active",
            }
        )
        row.db_insert()
        self.row_name = row.name
        self.addCleanup(frappe.db.delete, "Chapter Membership History", {"name": row.name})

    def _history_chapter(self):
        return frappe.db.get_value("Chapter Membership History", self.row_name, "chapter_name")

    def _update(self, bypass):
        member = frappe.get_doc("Member", self.member.name)
        return secure_document_operation(
            operation="update_child_table",
            doc=member,
            justification="1789 dead chapter reference probe",
            required_permissions=["Member:write"],
            bypass_validations=bypass,
        )

    def test_system_manager_bypass_tolerates_dead_chapter_row_and_keeps_the_reference(self):
        admin = self.ensure_test_admin_user().name
        previous = frappe.session.user
        frappe.set_user(admin)
        try:
            result = self._update(["link_validation"])
        finally:
            frappe.set_user(previous)
        self.assertTrue(result.success, result.errors)
        self.assertEqual(self._history_chapter(), self.ghost, "the dead reference must be kept, not blanked")

    def test_dynamic_link_row_keeps_its_reference_too(self):
        """CONTROL (green on develop too): the shape the retry already tolerated (Payment History,
        reference_name without reference_doctype) must still keep its reference."""
        ref = f"GHOST-REF-{frappe.generate_hash(length=6)}"
        row = frappe.get_doc(
            {
                "doctype": "Member Payment History",
                "parent": self.member.name,
                "parenttype": "Member",
                "parentfield": "payment_history",
                "idx": 99,
                "reference_name": ref,
            }
        )
        row.db_insert()
        self.addCleanup(frappe.db.delete, "Member Payment History", {"name": row.name})
        admin = self.ensure_test_admin_user().name
        previous = frappe.session.user
        frappe.set_user(admin)
        try:
            result = self._update(["link_validation"])
        finally:
            frappe.set_user(previous)
        self.assertTrue(result.success, result.errors)
        self.assertEqual(frappe.db.get_value("Member Payment History", row.name, "reference_name"), ref)

    def test_without_the_bypass_the_dead_chapter_row_still_refuses(self):
        """Control: the write is refused when no bypass is requested, and the row is untouched."""
        self.expectErrorLog()
        result = self._update(None)
        self.assertFalse(result.success)
        self.assertIn("Could not find", "; ".join(result.errors))
        self.assertEqual(self._history_chapter(), self.ghost)


class TestInvoiceHandlerDoesNotRequestInertBypass(EnhancedTestCase):
    """operation="save" cannot act on bypass_validations, so a System Manager's retry-tracking
    write must not record one."""

    def test_system_manager_retry_tracking_records_no_bypass(self):
        from verenigingen.services.billing.invoice_error_handler_service import (
            get_invoice_error_handler_service,
        )

        member = self.create_test_member(first_name="Bypass1789", last_name="Inv", birth_date="1975-09-09")
        self.create_test_membership(member_name=member.name, membership_type_name="Regular Member")
        name = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member.name, "status": "Active"}, limit=1
        )[0].name
        frappe.db.set_value("Membership Dues Schedule", name, "next_invoice_date", add_days(today(), -1))
        schedule = frappe.get_doc("Membership Dues Schedule", name)
        admin = self.ensure_test_admin_user().name
        counters = _get_metrics()
        before = counters["bypass_used"]
        previous = frappe.session.user
        frappe.set_user(admin)
        try:
            outcome = get_invoice_error_handler_service().handle_invoice_generation_failure(
                schedule, "invalid coverage window"
            )
        finally:
            frappe.set_user(previous)
        self.assertEqual(outcome["action_taken"], "retry_tracked")
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", name, "custom_invoice_retry_count"), 1
        )
        self.assertEqual(counters["bypass_used"], before, "a bypass was recorded for a save that cannot bypass")
