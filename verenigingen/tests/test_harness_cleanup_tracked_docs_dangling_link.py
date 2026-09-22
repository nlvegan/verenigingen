"""`VereningingenTestCase._cleanup_tracked_docs` can orphan a submitted invoice --
or, if fixed carelessly, strand its ledger rows instead. Both properties are tested
here.

`tearDownClass` walks `cls._track_created_docs` in reverse (child-first) order and
force-deletes each row (`base.py::_cleanup_tracked_docs`). Before the fix this file
tests for, it never cancelled a submitted document before trying to delete it.
`frappe.delete_doc(..., force=True)` does NOT bypass the submitted-record guard
(`check_permission_and_not_submitted` runs before the `if not force` check in
`frappe/model/delete_doc.py`), so deleting a still-submitted Sales Invoice raised
`ValidationError` -- which this loop's `except` clause silently swallowed and
print()ed. The loop then kept going: the next (earlier-created, so processed later
in the reversed walk) tracked record was the Membership Dues Schedule the invoice's
`membership_dues_schedule_display` still names. That record is NOT submittable, so
`force=True` deleted it outright, bypassing the ordinary link-integrity check
(`check_if_doc_is_linked`) that would otherwise refuse -- confirmed empirically:
without `force`, deleting a Membership Dues Schedule while a Sales Invoice still
names it via `membership_dues_schedule_display` raises `LinkExistsError` citing that
Sales Invoice. Net effect: the invoice survived (still submitted, unpaid), but the
schedule it named no longer existed -- a dangling `membership_dues_schedule_display`,
the exact shape measured on veg11 in #1250 (134 unpaid Sales Invoices whose dues
schedule had been deleted out from under them).

The cancel-before-delete fix for that is the SAME mechanism `_cancel_if_submitted`
(this same file) already carries -- `_cleanup_document_with_retry` merely CALLS it,
so there is one cancel-before-delete rule in the file, not two -- and that mechanism
comes with a ledger carve-out that is NOT optional: cancelling a ledger-bearing
voucher does not remove its GL Entry / Payment Ledger Entry rows, it WRITES MORE
(reversals), and `delete_doc` never takes them with the parent. A cancel-before-
delete fix that skips that carve-out trades the dangling-link defect for a WORSE
one -- orphaned ledger rows pointing at a voucher_no the naming series then reissues
to the next document (#328's mechanism, the one #482 / PR #518 already fixed for
the sibling drain). A first version of this fix did exactly that; the review that
caught it is why this file now has two tests instead of one:

- `test_cleanup_does_not_orphan_a_non_ledger_submittable_doc` -- the case the fix
  CAN fully close: a submittable, non-ledger-bearing tracked document is cancelled
  and removed cleanly, and nothing it referenced is left dangling.
- `test_cleanup_does_not_strand_ledger_rows_for_a_leaked_invoice` -- the case it
  cannot: an ordinary Sales Invoice posts real GL/Payment Ledger Entry rows on
  submit, so the ledger guard means it is deliberately left as a leak (still
  submitted, not deleted) rather than risk stranding those rows. That is the
  SAME trade-off `_cancel_if_submitted` already makes and documents.

**Residual scope, stated plainly**: for a genuinely ledger-bearing invoice, this fix
does NOT stop the schedule/member it references from being force-deleted by a later
loop iteration -- the invoice is left behind, submitted, with a dangling
`membership_dues_schedule_display`, exactly as before this PR. Preventing that too
would require the drain to know that a still-standing tracked document depends on
what it is about to delete, which is a materially bigger change than "reuse the
existing ledger guard" and is out of scope here; tracked as a residual risk in
#1264. What this fix DOES guarantee is that the drain never converts that leak into
silent ledger corruption, and that a non-ledger-bearing chain (the only real caller
of `track_class_doc` today, `Error Log` cleanup, is one) is cleaned up completely.

`track_class_doc` is currently used by exactly one test file (`Error Log` cleanup,
unrelated to billing), so none of this is necessarily how the #1250 rows were
produced -- but it is live, reachable, general-purpose harness infrastructure.
"""

import unittest

import frappe

from verenigingen.tests.utils import ledger_rows
from verenigingen.tests.utils.base import VereningingenTestCase


class TrackedDocCleanupLedgerAndDanglingLinkSafetyTest(unittest.TestCase):
    """Plain unittest.TestCase, not VereningingenTestCase: this drives
    `_cleanup_tracked_docs` directly and manages its own fixtures/cleanup so it
    does not pay for -- or depend on -- the full class-level setup this base
    normally performs in `setUpClass`.
    """

    def setUp(self):
        self.company = "_Test Company"
        self.customer = frappe.db.get_value("Customer", {}, "name")
        self.item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
        self.income_account = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_type": "Income Account",
                "is_group": 0,
                "account_currency": frappe.db.get_value("Company", self.company, "default_currency"),
            },
            "name",
        )
        self.cost_center = frappe.db.get_value(
            "Cost Center", {"company": self.company, "is_group": 0}, "name"
        )
        self.membership_type = frappe.db.get_value("Membership Type", {}, "name")
        self._leftover = []
        # Never let this test's tracked-doc list leak into a real test class's
        # teardown, and never inherit one left behind by an earlier test.
        self._saved_tracked = getattr(VereningingenTestCase, "_track_created_docs", None)

    def tearDown(self):
        # This is the TEST's own scratch cleanup, not the code under test --
        # `test_cleanup_does_not_strand_ledger_rows_for_a_leaked_invoice`
        # deliberately leaves a ledger-bearing Sales Invoice submitted behind,
        # so unlike `_cleanup_tracked_docs` itself, this teardown is free to
        # sweep the ledger rows once the parent is gone (mirroring
        # `EnhancedTestCase._remove_drained_record` / `purge_ledger_rows`) so
        # the site is left clean rather than accumulating test debris.
        VereningingenTestCase._track_created_docs = self._saved_tracked
        for doctype, name in reversed(self._leftover):
            try:
                if frappe.db.exists(doctype, name):
                    had_ledger_rows = ledger_rows.has_ledger_rows(doctype, name)
                    if (
                        frappe.get_meta(doctype).is_submittable
                        and frappe.db.get_value(doctype, name, "docstatus") == 1
                    ):
                        doc = frappe.get_doc(doctype, name)
                        doc.flags.ignore_permissions = True
                        doc.flags.ignore_links = True
                        try:
                            doc.cancel()
                        except Exception:
                            frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                    if had_ledger_rows:
                        ledger_rows.purge_ledger_rows(doctype, name)
            except Exception as e:
                print(f"test cleanup could not remove {doctype} {name}: {e}")
        frappe.db.commit()

    def _ledger_row_counts(self, doctype, name):
        """(GL Entry, Payment Ledger Entry) rows currently posted for this voucher."""
        return (
            frappe.db.count("GL Entry", {"voucher_type": doctype, "voucher_no": name}),
            frappe.db.count("Payment Ledger Entry", {"voucher_type": doctype, "voucher_no": name}),
        )

    def _probe_make_member(self, tag):
        member = frappe.new_doc("Member")
        member.first_name = f"Probe1250{tag}"
        member.last_name = frappe.generate_hash(length=6)
        member.flags.ignore_validate = True
        member.insert(ignore_permissions=True, ignore_mandatory=True)
        self._leftover.append(("Member", member.name))
        return member

    def _create_membership(self, member_name):
        """A submittable document that posts NO ledger rows (unlike Sales Invoice),
        so the ledger guard never blocks cancelling it -- the case the fix can
        close completely. Deliberately does not link any Membership Dues Schedule
        to it, so Membership.on_trash's own MDS cleanup (membership.py) has
        nothing to act on and cannot confound this test with a second delete path.
        """
        membership = frappe.new_doc("Membership")
        membership.member = member_name
        membership.membership_type = self.membership_type
        membership.flags.ignore_validate = True
        membership.insert(ignore_permissions=True, ignore_mandatory=True)
        membership.flags.ignore_validate = True
        membership.submit()
        self._leftover.append(("Membership", membership.name))
        frappe.db.commit()
        return membership

    def _probe_make_schedule(self, tag, member_name):
        mds = frappe.new_doc("Membership Dues Schedule")
        mds.schedule_name = f"PROBE-1250{tag}-Schedule-{frappe.generate_hash(length=6)}"
        mds.membership_type = self.membership_type
        mds.member = member_name
        mds.status = "Active"
        mds.billing_frequency = "Annual"
        mds.currency = "EUR"
        mds.is_template = 0
        mds.dues_rate = 25
        mds.flags.ignore_validate = True
        mds.insert(ignore_permissions=True, ignore_mandatory=True)
        self._leftover.append(("Membership Dues Schedule", mds.name))
        return mds

    def _create_submitted_invoice(self, schedule_name):
        si = frappe.new_doc("Sales Invoice")
        si.customer = self.customer
        si.company = self.company
        si.membership_dues_schedule_display = schedule_name
        si.set_posting_time = 1
        si.append(
            "items",
            {
                "item_code": self.item,
                "qty": 1,
                "rate": 25,
                "income_account": self.income_account,
                "cost_center": self.cost_center,
            },
        )
        si.insert(ignore_permissions=True)
        si.submit()
        self._leftover.append(("Sales Invoice", si.name))
        frappe.db.commit()
        return si

    def test_cleanup_does_not_orphan_a_non_ledger_submittable_doc(self):
        """The case this fix CAN close completely: a submittable, non-ledger-
        bearing tracked document (Membership) is cancelled and removed cleanly,
        and the Member it depends on is untouched by anything left dangling.
        """
        member = self._probe_make_member("A")
        membership = self._create_membership(member.name)

        # Real creation order (Member then Membership); tearDownClass drains in
        # reverse, so Membership -- the submitted, newer record -- is handled
        # first, exactly as it would be for a real class-level fixture chain.
        VereningingenTestCase._track_created_docs = [
            {"doctype": "Member", "name": member.name},
            {"doctype": "Membership", "name": membership.name},
        ]
        VereningingenTestCase._cleanup_tracked_docs()

        self.assertFalse(
            frappe.db.exists("Membership", membership.name),
            "a non-ledger-bearing submitted Membership should be cancelled and "
            "fully removed by the fix, not left behind as a leak",
        )
        self.assertFalse(
            frappe.db.exists("Member", member.name),
            "with the Membership gone, the Member it referenced should also "
            "have been removed -- nothing should have blocked this drain",
        )

    def test_cleanup_does_not_strand_ledger_rows_for_a_leaked_invoice(self):
        """The case this fix does NOT close (and must not pretend to): an
        ordinary Sales Invoice posts real GL Entry / Payment Ledger Entry rows
        on submit, so `has_ledger_rows` makes the guard skip cancelling it.
        The invoice is deliberately left as an honest, still-submitted leak --
        the same trade-off `_cancel_if_submitted` already makes -- rather than
        risk the #328/#482 mechanism: cancelling a ledger-bearing voucher WRITES
        reversal rows, and `delete_doc` does not take any of them with the
        parent, so cancel-then-delete here would strand them instead.

        This is the regression the first version of this fix introduced and a
        reviewer caught: reproduced independently on test_site_4 as
        GL 6->8, PLE 3->4, parent gone. This test asserts that specific
        before/after invariant rather than only the end state, so a future
        change that "fixes" the leak by cancelling anyway reddens here even if
        it happens to leave the row counts looking plausible individually.
        """
        member = self._probe_make_member("B")
        mds = self._probe_make_schedule("B", member.name)
        si = self._create_submitted_invoice(mds.name)

        gl_before, ple_before = self._ledger_row_counts("Sales Invoice", si.name)
        self.assertGreater(gl_before, 0, "test setup did not post any GL Entry rows -- fix the fixture")

        VereningingenTestCase._track_created_docs = [
            {"doctype": "Member", "name": member.name},
            {"doctype": "Membership Dues Schedule", "name": mds.name},
            {"doctype": "Sales Invoice", "name": si.name},
        ]
        VereningingenTestCase._cleanup_tracked_docs()

        self.assertTrue(
            frappe.db.exists("Sales Invoice", si.name),
            "the invoice should survive as an honest leak, not be silently "
            "deleted while carrying ledger rows",
        )
        self.assertEqual(
            1,
            frappe.db.get_value("Sales Invoice", si.name, "docstatus"),
            "a leaked ledger-bearing invoice must stay fully submitted, not "
            "half-cancelled",
        )
        gl_after, ple_after = self._ledger_row_counts("Sales Invoice", si.name)
        self.assertEqual(
            (gl_before, ple_before),
            (gl_after, ple_after),
            "GL Entry / Payment Ledger Entry row counts for this invoice "
            "changed -- the drain cancelled a ledger-bearing voucher (or "
            "otherwise touched its ledger rows) instead of leaving it alone, "
            "which either writes reversals or strands rows (#328/#482).",
        )
