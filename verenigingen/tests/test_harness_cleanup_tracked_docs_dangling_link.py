"""`VereningingenTestCase._cleanup_tracked_docs` can orphan a submitted invoice.

`tearDownClass` walks `cls._track_created_docs` in reverse (child-first) order and
force-deletes each row (`base.py::_cleanup_tracked_docs`). Unlike its sibling drain
in `EnhancedTestCase._remove_drained_record`, it never cancels a submitted document
before trying to delete it. `frappe.delete_doc(..., force=True)` does NOT bypass the
submitted-record guard (`check_permission_and_not_submitted` runs before the
`if not force` check in `frappe/model/delete_doc.py`), so deleting a still-submitted
Sales Invoice raises `ValidationError` -- which this loop's `except` clause silently
swallows and print()s.

The loop then keeps going: the next (earlier-created, so processed later in the
reversed walk) tracked record is the Membership Dues Schedule the invoice's
`membership_dues_schedule_display` still names. That record is NOT submittable, so
`force=True` deletes it outright, bypassing the ordinary link-integrity check
(`check_if_doc_is_linked`) that would otherwise refuse -- confirmed empirically:
without `force`, deleting a Membership Dues Schedule while a Sales Invoice still
names it via `membership_dues_schedule_display` raises `LinkExistsError` citing that
Sales Invoice.

Net effect: the invoice survives (still submitted, unpaid), but the schedule it
names no longer exists -- a dangling `membership_dues_schedule_display`. That is the
exact shape measured on veg11 in #1250 (134 unpaid Sales Invoices whose dues
schedule had been deleted out from under them), and this file reproduces the
mechanism directly rather than only asserting the production symptom.

`track_class_doc` is currently used by exactly one test file
(`test_harness_setup_fatal` style `Error Log` cleanup is elsewhere; the only real
caller today is unrelated to billing), so this is not necessarily how the #1250 rows
were produced -- but it is a live, reachable defect in the same class of code, and
the fix (cancel a submittable, still-submitted row before deleting it, mirroring
`_cancel_if_submitted` / `EnhancedTestCase._remove_drained_record`) closes it.
"""

import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TrackedDocCleanupDoesNotOrphanInvoiceLinksTest(unittest.TestCase):
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
            {"company": self.company, "account_type": "Income Account", "is_group": 0},
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
        VereningingenTestCase._track_created_docs = self._saved_tracked
        for doctype, name in reversed(self._leftover):
            try:
                if frappe.db.exists(doctype, name):
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
            except Exception as e:
                print(f"test cleanup could not remove {doctype} {name}: {e}")
        frappe.db.commit()

    def _make_member(self, tag):
        member = frappe.new_doc("Member")
        member.first_name = f"Probe1250{tag}"
        member.last_name = frappe.generate_hash(length=6)
        member.flags.ignore_validate = True
        member.insert(ignore_permissions=True, ignore_mandatory=True)
        self._leftover.append(("Member", member.name))
        return member

    def _make_schedule(self, tag, member_name):
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

    def _make_submitted_invoice(self, schedule_name):
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

    def test_cleanup_does_not_orphan_a_submitted_invoice_link(self):
        member = self._make_member("A")
        mds = self._make_schedule("A", member.name)
        si = self._make_submitted_invoice(mds.name)

        # Isolate the scenario: strip every OTHER reference to the schedule so
        # the Sales Invoice's `membership_dues_schedule_display` is the only
        # thing standing between it and an unguarded delete -- exactly #1250.
        frappe.db.set_value("Member", member.name, "current_dues_schedule", None, update_modified=False)
        frappe.db.set_value(
            "Member", member.name, "application_dues_schedule", None, update_modified=False
        )
        frappe.db.sql("DELETE FROM `tabMember Fee Change History` WHERE dues_schedule=%s", mds.name)
        frappe.db.commit()

        # Exercise the real harness method, in the real order it is populated in:
        # setUpClass creates docs and tracks them in creation order; tearDownClass
        # walks them in reverse.
        VereningingenTestCase._track_created_docs = [
            {"doctype": "Member", "name": member.name},
            {"doctype": "Membership Dues Schedule", "name": mds.name},
            {"doctype": "Sales Invoice", "name": si.name},
        ]
        VereningingenTestCase._cleanup_tracked_docs()
        frappe.db.commit()

        invoice_still_exists = bool(frappe.db.exists("Sales Invoice", si.name))
        if invoice_still_exists:
            linked_schedule = frappe.db.get_value(
                "Sales Invoice", si.name, "membership_dues_schedule_display"
            )
            if linked_schedule:
                self.assertTrue(
                    frappe.db.exists("Membership Dues Schedule", linked_schedule),
                    "_cleanup_tracked_docs deleted the Membership Dues Schedule "
                    f"{linked_schedule!r} while leaving Sales Invoice {si.name!r} "
                    "still pointing at it -- the dangling-link defect measured "
                    "in #1250.",
                )
        else:
            # Fully removed is also an acceptable outcome: nothing dangles.
            pass
