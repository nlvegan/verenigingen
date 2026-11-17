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

    `Payment Entry` (`non_standard_fieldnames["Payment Entry"] = "remarks"`) was left
    by #1261 because `remarks` is a real field, so the query does not crash. #1318
    found it equally dead: `remarks` is ERPNext's free-text narrative, never a
    mandate docname, so the count was always 0. Payment Entry carries no field that
    holds a SEPA Mandate (its only SEPA field is `custom_sepa_batch`, a link to
    Direct Debit Batch, which reaches a mandate only via the mandate_id on a child
    row -- see above), so #1318 drops it too.
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

        # Control: the collector must see names when there are some, or the
        # assertion below would be vacuous now that this dashboard names none.
        self.assertEqual(
            _referenced_doctypes(
                {"non_standard_fieldnames": {"Gone A": "x"}, "transactions": [{"items": ["Gone B"]}]}
            ),
            {"Gone A", "Gone B"},
        )

        missing = sorted(d for d in referenced if not frappe.db.exists("DocType", d))
        self.assertEqual(
            missing,
            [],
            f"sepa_mandate_dashboard.py references doctypes with no DocType record: {missing}",
        )

    def _insert_minimal_test_mandate(self):
        """A real SEPA Mandate with no `member` set (the field is optional --
        "Leave blank for non-member donors" -- and this test is about dashboard
        link mechanics, not member linkage). Inserted with ignore_permissions
        because this test runs as whatever user the harness leaves active, not
        because the mandate's own permission boundary is under test here (that
        boundary has its own tests elsewhere)."""
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
        """#1261/#1318: the real Desk code path (frappe.desk.notifications.get_open_count)
        must not raise for a real SEPA Mandate, and must offer no connection that
        can never match."""
        mandate = self._insert_minimal_test_mandate()

        from frappe.desk.notifications import get_open_count

        # get_open_count() calls frappe.db.set_execution_timeout(1) (SET SESSION
        # max_statement_time = 1) and never restores it -- a frappe core gap this
        # app cannot fix directly (apps/frappe/ is framework code). Left alone,
        # every later test sharing this process's DB connection inherits a
        # permanent 1s statement ceiling: any query that legitimately runs (or
        # blocks) for more than a second is killed with MariaDB error 1969
        # ("max_statement_time exceeded") instead of completing normally.
        # Measured: this is exactly what broke
        # test_base_history_manager_row_lock.TestBaseHistoryManagerLocksItsParentRow
        # .test_the_lock_is_taken_before_anything_is_read_or_written when this
        # test ran earlier in the same CI shard -- its deliberate 2-second
        # innodb_lock_wait_timeout wait never got the chance to fire because the
        # leaked 1s max_statement_time killed the query first, and that MariaDB
        # error is not one BaseHistoryManager treats as a lock conflict, so it
        # was swallowed into an ordinary failed result instead of raised (#1350).
        original_timeout = frappe.db.sql("SELECT @@session.max_statement_time")[0][0]
        self.addCleanup(frappe.db.sql, f"SET SESSION max_statement_time = {int(original_timeout)}")

        result = get_open_count("SEPA Mandate", mandate.name)
        found_doctypes = {d["doctype"] for d in result["count"]["external_links_found"]}

        # #1318: Payment Entry was mapped via free-text `remarks` (always 0).
        self.assertNotIn("Payment Entry", found_doctypes)
        self.assertEqual(found_doctypes, set())

        # #1261's fix: these three had no field that could ever hold this
        # mandate's docname, so they are no longer offered as connections at all.
        self.assertNotIn("Direct Debit Batch", found_doctypes)
        self.assertNotIn("SEPA Payment Retry", found_doctypes)
        self.assertNotIn("Sales Invoice", found_doctypes)

    def test_dashboard_has_no_free_text_field_mapping(self):
        """#1318: no `non_standard_fieldnames` entry may point at free text, and the
        mandate's Reports entry (the part of the tab that works) must survive."""
        data = get_data()
        for doctype, fieldname in data.get("non_standard_fieldnames", {}).items():
            field = frappe.get_meta(doctype).get_field(fieldname)
            self.assertIsNotNone(field, f"{doctype}.{fieldname} does not exist")
            self.assertNotIn(field.fieldtype, ("Small Text", "Text", "Long Text", "Text Editor", "Data"))
        self.assertTrue(data["reports"], "the Mandate Usage Report entry must remain")

    def test_payment_entry_still_has_no_field_that_can_hold_a_mandate(self):
        """Tripwire for #1318's premise. If Payment Entry ever gains a Link to SEPA
        Mandate, the item should be restored with that field mapped (and a test that
        counts a real linked Payment Entry), not left removed."""
        fields = frappe.get_meta("Payment Entry").fields
        # Control: the scan sees SEPA-related fields (custom_sepa_batch is one), so
        # an empty result below is not an artefact of the scan.
        self.assertIn("custom_sepa_batch", [f.fieldname for f in fields])
        holders = [
            f.fieldname
            for f in fields
            if (f.fieldtype in ("Link", "Dynamic Link") and f.options == "SEPA Mandate")
            or "mandate" in f.fieldname
        ]
        self.assertEqual(holders, [])
