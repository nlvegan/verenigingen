"""Structural + behavioural gate for SEPA Mandate's Connections tab (#1261).

Why this needs a test at all:
    `sepa_mandate_dashboard.py` named a doctype that has never existed
    (`"Direct Debit Invoice"` in `non_standard_fieldnames`) -- dead, but harmless on
    its own since nothing ever looks that key up (Frappe indexes
    `non_standard_fieldnames` by the *item doctype*, and `"Direct Debit Invoice"` was
    never one of the `transactions` items).

    Separately, and with real impact: `"Direct Debit Batch"` **is** a live
    transaction item, has no override in `non_standard_fieldnames`, and falls back
    to the dashboard's default `fieldname`, `"sepa_mandate"`. Neither
    `Direct Debit Batch` nor its child table `Direct Debit Batch Invoice` has a
    field by that name. Measured on test_site_1 (2026-09-23), calling the exact
    server method the Desk UI calls when a SEPA Mandate form's Connections tab
    loads (`frappe.desk.notifications.get_open_count`) against a real, freshly
    inserted SEPA Mandate raised:

        MySQLdb.OperationalError: (1054, "Unknown column 'sepa_mandate' in 'WHERE'")

    -- an uncaught 500, not a graceful zero. The same measurement showed two more
    of the four `transactions` items are equally broken for the same reason
    (`SEPA Payment Retry` and `Sales Invoice` also have no `sepa_mandate` field, nor
    any other mandate-referencing field at all) -- so 3 of 4 items crash the tab,
    not just the one #1261 named. `get_external_links` is called unguarded (no
    try/except) for any item without an `internal_links` entry, so the first
    crashing item aborts the whole `get_open_count` call.

    Even if `"Direct Debit Batch"` were mapped to its child table's
    `mandate_reference` field (Frappe's filter builder *can* join a parent doctype
    to a Table field's child doctype -- see `frappe.utils.data.get_filter`), that
    field stores the mandate's `mandate_id` (its human reference, e.g.
    "TST0095C0447"), never its docname -- confirmed by
    `direct_debit_batch.py::validate_sequence_types`, which looks up
    `frappe.db.get_value("SEPA Mandate", {"mandate_id": invoice.mandate_reference}, "name")`.
    Frappe's dashboard mechanism always filters by `frm.doc.name` (the docname), so
    that mapping would never match anything -- a permanent, silent zero, not a real
    connection. There is no field anywhere in this data model that holds a SEPA
    Mandate's docname on `Direct Debit Batch`, `SEPA Payment Retry`, or
    `Sales Invoice`, so all three are dropped rather than "fixed" with a mapping
    that can never be correct.

    `Payment Entry` (`non_standard_fieldnames["Payment Entry"] = "remarks"`) is
    untouched by this fix: `remarks` is a real field on Payment Entry, so the query
    does not crash, and this test's positive control confirms the fix did not
    collaterally remove or break it.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.doctype.sepa_mandate.sepa_mandate_dashboard import get_data


def _referenced_doctypes(data):
    """Every doctype named by non_standard_fieldnames keys or transactions items."""
    referenced = set(data.get("non_standard_fieldnames", {}).keys())
    for group in data.get("transactions", []):
        referenced.update(group.get("items", []))
    return referenced


class TestSepaMandateDashboard(EnhancedTestCase):
    def test_no_dead_doctype_references(self):
        """#1261: every doctype the dashboard names (as a non_standard_fieldnames
        key or a transactions item) must actually exist."""
        data = get_data()
        referenced = _referenced_doctypes(data)

        # Positive control: a doctype this file legitimately still names must not
        # be flagged, or the assertion below would be vacuously satisfied by an
        # empty `referenced` set (e.g. a typo'd dict key on get_data()).
        self.assertIn("Payment Entry", referenced)

        missing = sorted(d for d in referenced if not frappe.db.exists("DocType", d))
        self.assertEqual(
            missing,
            [],
            f"sepa_mandate_dashboard.py references doctypes with no DocType record: {missing}",
        )

    def _create_test_sepa_mandate(self):
        """Minimal, real SEPA Mandate -- inserted with ignore_permissions because
        this test runs as whatever user the harness leaves active, not because the
        mandate's own permission boundary is under test here (that boundary has its
        own tests elsewhere)."""
        return frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"TEST-DASH-{frappe.generate_hash(length=8)}",
                "account_holder_name": "Dashboard Test Holder",
                "iban": "NL91ABNA0417164300",
                "sign_date": frappe.utils.today(),
            }
        ).insert(ignore_permissions=True)

    def test_get_open_count_does_not_crash_for_a_real_mandate(self):
        """#1261: the real Desk code path (frappe.desk.notifications.get_open_count)
        must not raise for a real SEPA Mandate, and the surviving Payment Entry
        connection must still be queried (positive control)."""
        mandate = self._create_test_sepa_mandate()

        from frappe.desk.notifications import get_open_count

        result = get_open_count("SEPA Mandate", mandate.name)
        found_doctypes = {d["doctype"] for d in result["count"]["external_links_found"]}

        # Positive control: Payment Entry's mapping is untouched by this fix and
        # must still be present -- proves the fix did not also remove it.
        self.assertIn("Payment Entry", found_doctypes)

        # #1261's fix: these three had no field that could ever hold this
        # mandate's docname, so they are no longer offered as connections at all.
        self.assertNotIn("Direct Debit Batch", found_doctypes)
        self.assertNotIn("SEPA Payment Retry", found_doctypes)
        self.assertNotIn("Sales Invoice", found_doctypes)
