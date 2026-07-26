"""Tests for v2_2.clear_stale_membership_payment_history_links.

The patch repairs `Member Payment History` rows that point at a nonexistent
Membership, which makes the parent Member unsavable (see MR-SYNC-2026-00087).

Two deliberate choices here:

1. The stale rows are inserted with raw SQL, because `doc.save()` rejects them —
   that is exactly why the corruption stays invisible until the next save.
2. Every test calls `clear_stale_links(parent=...)`, never the unscoped
   `execute()`. `execute()` runs a site-wide UPDATE and commits, so calling it
   from a test permanently repairs rows belonging to other fixtures on a shared
   test site (observed: a run cleaned 17 unrelated rows on test_site_1). The
   scoped helper is the same code path with a `ph.parent` restriction.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.clear_stale_membership_payment_history_links import clear_stale_links


class TestClearStaleMembershipPaymentHistoryLinks(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.other_members = []

    def tearDown(self):
        for name in [self.member.name, *self.other_members]:
            frappe.db.delete("Member Payment History", {"parent": name})
            frappe.delete_doc("Member", name, force=True, ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    def _create_member(self, first_name="Patch", last_name="LinkTarget"):
        member = frappe.new_doc("Member")
        member.first_name = first_name
        member.last_name = last_name
        member.email = f"patch.link.{frappe.generate_hash(length=8)}@example.com"
        member.status = "Active"
        member.flags.ignore_workflow = True
        member._system_update = True
        member.insert(ignore_permissions=True)
        frappe.db.commit()
        return member

    def _insert_history_row(self, member_name, reference_doctype, reference_name):
        row_name = frappe.generate_hash(length=10)
        frappe.db.sql(
            """
            INSERT INTO `tabMember Payment History`
                (name, parent, parenttype, parentfield, idx, docstatus,
                 transaction_type, reference_doctype, reference_name)
            VALUES (%s, %s, 'Member', 'payment_history', 1, 0,
                    'Membership Invoice', %s, %s)
            """,
            (row_name, member_name, reference_doctype, reference_name),
        )
        frappe.db.commit()
        return row_name

    def _read_row(self, row_name):
        return frappe.db.get_value(
            "Member Payment History", row_name, ["reference_doctype", "reference_name"], as_dict=True
        )

    def test_clears_unresolvable_membership_link(self):
        row_name = self._insert_history_row(
            self.member.name, "Membership", "Schedule-Not-A-Membership-001"
        )

        rows, members = clear_stale_links(parent=self.member.name)

        self.assertEqual((rows, members), (1, 1))
        row = self._read_row(row_name)
        self.assertIsNone(row.reference_doctype)
        self.assertIsNone(row.reference_name)

    def test_preserves_a_resolvable_membership_reference(self):
        """The safety claim: a reference that DOES resolve must survive.

        This is the test that fails if anyone drops the `LEFT JOIN` /
        `m.name IS NULL` condition — without it, the UPDATE would null every
        membership reference on the site rather than only the broken ones.
        Asserting that an already-NULL row stays NULL cannot catch that, because
        the UPDATE only ever writes NULL.
        """
        real_membership = frappe.db.get_value("Membership", {}, "name")
        if not real_membership:
            self.skipTest("no Membership on this site to point a live reference at")

        stale_row = self._insert_history_row(
            self.member.name, "Membership", "Schedule-Not-A-Membership-002"
        )
        live_row = self._insert_history_row(self.member.name, "Membership", real_membership)

        rows, _members = clear_stale_links(parent=self.member.name)

        self.assertEqual(rows, 1, "only the unresolvable row should have been cleared")

        self.assertIsNone(self._read_row(stale_row).reference_doctype)

        preserved = self._read_row(live_row)
        self.assertEqual(preserved.reference_doctype, "Membership")
        self.assertEqual(preserved.reference_name, real_membership)

    def test_does_not_touch_rows_belonging_to_other_members(self):
        """Scoping guard — proves the parent restriction actually restricts."""
        other = self._create_member(first_name="Patch", last_name="Bystander")
        self.other_members.append(other.name)

        mine = self._insert_history_row(self.member.name, "Membership", "Schedule-Not-A-Membership-003")
        theirs = self._insert_history_row(other.name, "Membership", "Schedule-Not-A-Membership-004")

        rows, members = clear_stale_links(parent=self.member.name)

        self.assertEqual((rows, members), (1, 1))
        self.assertIsNone(self._read_row(mine).reference_doctype)
        self.assertEqual(self._read_row(theirs).reference_doctype, "Membership")

    def test_repaired_member_becomes_savable_again(self):
        """The point of the patch: the parent Member can be saved once more."""
        self._insert_history_row(self.member.name, "Membership", "Schedule-Not-A-Membership-005")

        blocked = frappe.get_doc("Member", self.member.name)
        blocked._system_update = True
        with self.assertRaises(frappe.LinkValidationError):
            blocked.save()
        frappe.db.rollback()

        clear_stale_links(parent=self.member.name)

        repaired = frappe.get_doc("Member", self.member.name)
        repaired._system_update = True
        repaired.save()  # must not raise
        frappe.db.commit()

    def test_is_idempotent(self):
        self._insert_history_row(self.member.name, "Membership", "Schedule-Not-A-Membership-006")

        first = clear_stale_links(parent=self.member.name)
        second = clear_stale_links(parent=self.member.name)

        self.assertEqual(first, (1, 1))
        self.assertEqual(second, (0, 0), "second run must find nothing left to clear")
