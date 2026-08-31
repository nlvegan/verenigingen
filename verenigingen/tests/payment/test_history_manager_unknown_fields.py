"""`MemberFinancialHistoryManager` drops fields the child doctype does not have, loudly.

The standing guard for #465's class. Frappe drops an unknown key silently -- measured on
`test_site_2`:

    row = member.append("payment_history", {"invoice": "X", "mollie_payment_id": "tr_x"})
    row.get("mollie_payment_id")            -> 'tr_x'      (a plain Python attribute)
    "mollie_payment_id" in row.as_dict()    -> False
    row.get_valid_dict()                    -> {'invoice': 'X'}   only
    "mollie_payment_id" in columns          -> False
    CONTROL "invoice" in columns            -> True

So the write succeeds, reports success, and the data is gone.

Two properties, and the second is the one a naive guard gets wrong:

1. An unknown key is stripped and reported, and the REST OF THE ROW STILL LANDS.
   Refusing the whole write would convert "lose one field" into "lose the row" -- and
   on the Mollie donation path a False becomes HTTP 500 "Trigger Mollie retry"
   (`unified_payment_api.py:85`), so a schema typo would produce a 26-hour retry storm
   that can never succeed.
2. A history field that is not a table at all is a HARD failure. The first version of
   this guard treated an unresolvable table as "nothing to check against" and passed,
   which made it fail OPEN on the exact typo class it exists to catch.

SCOPE, narrowly: this covers writers that go through the manager. Eight production
sites `append()` directly and are invisible to it, three of them with #465's defect --
enumerated in #712. The guard is not a claim about them.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_financial_history_manager import (
    MemberFinancialHistoryManager,
    get_payment_history_manager,
)

ROW_ID = "I465-GUARD-ROW"


class TestHistoryManagerUnknownFields(EnhancedTestCase):
    """A known-good entry lands whole; a known-bad key is dropped, not silently lost."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # Dropping a field and refusing a bad table both write an Error Log, which is
        # the point of this module; the automatic tearDown guard would flag every one.
        self.expectErrorLog("Financial History Unknown Field")
        self.expectErrorLog("Financial History Unknown Table")
        self.member = self.create_test_member(first_name="HistoryGuard")
        self.manager = get_payment_history_manager(frappe.get_doc("Member", self.member.name))

    def rows(self):
        return frappe.get_doc("Member", self.member.name).payment_history

    @staticmethod
    def entry(**extra):
        base = {
            "invoice": ROW_ID,
            "invoice_doctype": None,
            "amount": 5.0,
            "status": "Completed",
        }
        base.update(extra)
        return base

    def add(self, entry):
        return self.manager.add_or_update_entry(ROW_ID, lambda: entry, "invoice")

    def unknown_field_logs(self):
        """Error Log rows written during THIS test, by title.

        Scoped to `self._test_start_time`: `tabError Log` is MyISAM, so rows from an
        earlier green run survive the rollback and an unscoped query would read them
        back and pass for the wrong reason.
        """
        return [
            r
            for r in self._error_logs_since(self._test_start_time, use_expected=False)
            if r.method == "Financial History Unknown Field"
        ]

    # -- the control comes first: a valid entry must go through untouched ----
    def test_an_entry_naming_only_real_fields_is_written(self):
        self.assertTrue(self.add(self.entry()))
        self.assertEqual([r.invoice for r in self.rows()], [ROW_ID])
        self.assertEqual(self.unknown_field_logs(), [], "a clean entry must not be reported")

    def test_an_unknown_key_is_dropped_and_the_rest_of_the_row_still_lands(self):
        """Strip and continue, not refuse. The `amount` is the assertion that matters:
        a guard that refused would leave the member with no donation row at all."""
        self.assertTrue(self.add(self.entry(mollie_payment_id="tr_guard")))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].invoice, ROW_ID)
        self.assertEqual(rows[0].amount, 5.0)
        self.assertEqual(rows[0].status, "Completed")

    def test_the_drop_names_the_offending_field_to_an_operator(self):
        """A guard nobody can see is a silent drop with extra steps."""
        self.add(self.entry(mollie_payment_id="tr_guard", payment_type="Donation"))
        logs = self.unknown_field_logs()
        self.assertTrue(logs, "no Error Log naming the dropped fields")
        self.assertIn("mollie_payment_id", logs[0].error)
        self.assertIn("payment_type", logs[0].error)
        self.assertIn("Member Payment History", logs[0].error)

    def test_an_entry_with_nothing_writable_left_is_refused(self):
        """Stripping everything would otherwise append an empty row."""
        self.assertFalse(self.add({"mollie_payment_id": "tr_guard", "payment_type": "x"}))
        self.assertEqual(self.rows(), [])
        self.assertTrue(self.unknown_field_logs())

    def test_update_entry_field_drops_an_unknown_field(self):
        """`update_entry_field` setattrs straight onto the row, so it has the same
        exposure as the builder path and needs the same treatment."""
        self.assertTrue(self.add(self.entry()))
        # Only an unknown field -> nothing left to update.
        self.assertFalse(self.manager.update_entry_field(ROW_ID, {"payment_type": "x"}, "invoice"))
        # A real field alongside an unknown one -> the real one still applies.
        self.assertTrue(
            self.manager.update_entry_field(
                ROW_ID, {"transaction_type": "Donation", "payment_type": "x"}, "invoice"
            )
        )
        self.assertEqual(self.rows()[0].transaction_type, "Donation")

    # -- fail CLOSED on a history field that is not a table ------------------
    def test_a_misspelt_history_field_is_a_hard_failure_not_a_free_pass(self):
        """The typo class the guard exists to catch, applied to the guard itself.

        Measured before the fix: with `history_field_name="payment_histroy"` the field
        check accepted an entry of pure nonsense, because an unresolvable table read as
        "nothing to check against".
        """
        broken = MemberFinancialHistoryManager(
            doc=frappe.get_doc("Member", self.member.name), history_field_name="payment_histroy"
        )
        self.assertIsNone(broken._resolve_child_doctype())
        self.assertFalse(broken.add_or_update_entry(ROW_ID, lambda: {"totally_bogus": 1}, "invoice"))
        self.assertFalse(broken.update_entry_field(ROW_ID, {"totally_bogus": 1}, "invoice"))
        # CONTROL: the correctly-spelt field resolves and behaves.
        self.assertEqual(self.manager._resolve_child_doctype(), "Member Payment History")

    def test_the_framework_row_columns_are_not_treated_as_unknown(self):
        """`as_dict()` supplies `doctype`/`creation`/`modified`/`parent`, and returning
        `row.as_dict()` is a live pattern in this app (`payment_history_service.py:551`).
        A hand-written allowlist accepted `parent` and refused `creation`; frappe's own
        `default_fields`/`child_table_fields`/`optional_fields` are used instead."""
        row_shaped = self.entry()
        row_shaped.update(
            {
                "doctype": "Member Payment History",
                "name": "abc123",
                "idx": 1,
                "owner": "Administrator",
                "creation": frappe.utils.now(),
                "modified": frappe.utils.now(),
                "modified_by": "Administrator",
                "docstatus": 0,
                "parent": self.member.name,
                "parentfield": "payment_history",
                "parenttype": "Member",
                "_user_tags": None,
            }
        )
        kept = self.manager._drop_unknown_fields("Member Payment History", row_shaped, ROW_ID)
        self.assertEqual(kept, row_shaped, "no framework row column may be reported as unknown")
        self.assertEqual(self.unknown_field_logs(), [])

    def test_the_guard_resolves_the_child_doctype_from_the_table_field(self):
        """Premise: the check is against `Member Payment History` and not against some
        wider set that would accept anything. `donation_amount` is a real field -- of a
        DIFFERENT history doctype."""
        self.assertEqual(
            self.manager._drop_unknown_fields(
                "Member Payment History", {"transaction_type": "x"}, ROW_ID
            ),
            {"transaction_type": "x"},
        )
        self.assertIsNone(
            self.manager._drop_unknown_fields(
                "Member Payment History", {"donation_amount": 1}, ROW_ID
            )
        )
