"""#3029: e-Boekhouden party creation must not turn a 1213/1205 into a False / None / log line.

A 1213 makes the server roll the WHOLE transaction back. A broad ``except Exception`` that
logs and returns lets the migration carry on and count the party as skipped or created while
the row is gone (#3008 class). Each test injects a real-shape lock error at the DRIVER
(``Cursor.execute``), below every swallowing layer, and asserts it reaches the caller.

Probe shortcut, stated: the deadlock is injected, not provoked, and (as in #3008's tests) no
server ROLLBACK is issued -- the question under test is only who sees the error.
"""

import itertools
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.services.relation_migration_service import RelationMigrationService
from verenigingen.e_boekhouden.utils import invoice_helpers
from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _get_or_create_company_party,
    _get_or_create_customer,
    _get_or_create_supplier,
)
from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor
from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver
from verenigingen.e_boekhouden.utils.transaction_utils import create_customer_impl, create_supplier_impl
from verenigingen.tests.e_boekhouden.test_transaction_utils import _TxUtilsBase


def _lock_error_at_driver_3029(fragment, startswith, code=1213):
    """Patch ``Cursor.execute``: the first statement starting with one of *startswith* and
    containing *fragment* raises OperationalError(code); frappe's dispatch turns that into
    QueryDeadlockError / QueryTimeoutError. Returns (patcher, hits)."""
    hits = []
    cursor_cls = frappe.db._cursor.__class__
    real_execute = cursor_cls.execute

    def execute(cursor, query, *args, **kwargs):
        if isinstance(query, str) and query.lstrip().upper().startswith(startswith) and fragment in query:
            hits.append(query)
            if len(hits) == 1:
                raise frappe.db.OperationalError(code, "injected at the driver")
        return real_execute(cursor, query, *args, **kwargs)

    # Mock justified: fault injection at the driver; calls through for every other statement
    return patch.object(cursor_cls, "execute", execute), hits


class TestPartyCreationLockErrors3029(_TxUtilsBase):
    _seq_3029 = itertools.count()

    def _reaches_caller_3029(self, fragment, startswith, call):
        """Both non-resumable classes must reach the caller: 1213 (whole transaction rolled
        back) and 1205 (unit of work half-applied)."""
        for code, error in ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError)):
            with self.subTest(code=code):
                inject, hits = _lock_error_at_driver_3029(fragment, startswith, code)
                with inject, self.assertRaises(error):
                    call()
                self.assertTrue(hits, "the injection must have fired")

    def _existing_party_3029(self, doctype="Customer", provisional=False):
        name = f"{'E-Boekhouden ' if provisional else ''}Probe 3029 {self.uid} {doctype}"
        doc = frappe.new_doc(doctype)
        setattr(doc, f"{doctype.lower()}_name", name)
        if doctype == "Customer":
            doc.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
            doc.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
        else:
            doc.supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
        doc.insert()
        return doc

    # --- relation_migration_service ------------------------------------------------------
    def test_create_customer_does_not_report_a_rolled_back_party_as_skipped(self):
        self.expectErrorLog("Failed to create")
        data = {"companyName": f"Probe 3029 Customer {self.uid} BV"}
        self._reaches_caller_3029(
            "`tabCustomer`", ("INSERT",), lambda: RelationMigrationService().create_customer(data)
        )

    def test_create_supplier_does_not_report_a_rolled_back_party_as_skipped(self):
        self.expectErrorLog("Failed to create")
        data = {"companyName": f"Probe 3029 Supplier {self.uid} BV"}
        self._reaches_caller_3029(
            "`tabSupplier`", ("INSERT",), lambda: RelationMigrationService().create_supplier(data)
        )

    def test_create_customer_still_reports_an_ordinary_failure_as_false(self):
        """Control: a non-lock error keeps the old contract (False), so the re-raise is narrow."""
        self.expectErrorLog("Error in customer creation")
        with patch.object(RelationMigrationService, "_determine_party_type", side_effect=ValueError("x")):
            self.assertFalse(RelationMigrationService().create_customer({"companyName": "Ctl BV"}))

    # --- transaction_utils ---------------------------------------------------------------
    def test_create_customer_impl_does_not_return_success_false_after_a_deadlock(self):
        data = {"Bedrijf": f"Probe 3029 Impl {self.uid} BV", "ID": "3029"}
        self._reaches_caller_3029(
            "`tabCustomer`", ("INSERT",), lambda: create_customer_impl(self.migration_doc, data)
        )

    def test_create_supplier_impl_does_not_return_success_false_after_a_deadlock(self):
        data = {"Bedrijf": f"Probe 3029 Impl {self.uid} BV", "ID": "3029"}
        self._reaches_caller_3029(
            "`tabSupplier`", ("INSERT",), lambda: create_supplier_impl(self.migration_doc, data)
        )

    def test_create_customer_impl_still_returns_failure_for_an_ordinary_error(self):
        """Control: a non-lock error stays a {'success': False} result."""
        with patch(
            "verenigingen.e_boekhouden.utils.transaction_utils.resolve_non_group_customer_group",
            side_effect=ValueError("ordinary"),
        ):
            result = create_customer_impl(self.migration_doc, {"Bedrijf": f"Ctl 3029 {self.uid} BV"})
        self.assertEqual(result, {"success": False, "error": "ordinary"})

    # --- eboekhouden_rest_full_migration -------------------------------------------------
    def test_get_or_create_customer_does_not_return_none_after_a_deadlock(self):
        debug = []
        self._reaches_caller_3029(
            "`tabCustomer`", ("INSERT",), lambda: _get_or_create_customer(f"3029{self.uid}", debug)
        )

    def test_get_or_create_supplier_does_not_return_none_after_a_deadlock(self):
        self._reaches_caller_3029(
            "`tabSupplier`", ("INSERT",), lambda: _get_or_create_supplier(f"3029{self.uid}", "d", [])
        )

    def test_get_or_create_company_party_does_not_return_none_after_a_deadlock(self):
        self._reaches_caller_3029(
            "`tabCustomer`",
            ("INSERT",),
            lambda: _get_or_create_company_party("Customer", f"Probe3029 {self.uid}", []),
        )

    def test_get_or_create_customer_still_returns_none_for_an_ordinary_error(self):
        """Control: a non-lock error keeps the old contract."""
        debug = []
        with patch.object(EBoekhoudenPartyResolver, "resolve_customer", side_effect=ValueError("o")):
            self.assertIsNone(_get_or_create_customer("1", debug))
        self.assertTrue(any("Error resolving customer" in d for d in debug))

    # --- party_extractor -----------------------------------------------------------------
    def test_resolve_party_by_name_does_not_return_none_after_a_deadlock(self):
        self.expectErrorLog("EBoekhoudenPartyExtractor")
        self._reaches_caller_3029(
            "`tabCustomer`",
            ("INSERT",),
            lambda: EBoekhoudenPartyExtractor(self.company)._resolve_party_by_name(
                f"Probe 3029 {self.uid} BV", "Customer"
            ),
        )

    def test_resolve_party_by_relation_id_does_not_return_none_after_a_deadlock(self):
        """SELECT-injected: the lookup read. The resolver behind it is reached since #3063
        (see test_party_extractor_resolver_call_3063)."""
        self.expectErrorLog("EBoekhoudenPartyExtractor")
        self._reaches_caller_3029(
            "`tabCustomer`",
            ("SELECT",),
            lambda: EBoekhoudenPartyExtractor(self.company)._resolve_party_by_relation_id(
                f"3029{self.uid}", "Customer"
            ),
        )

    def test_resolve_party_for_journal_entry_does_not_return_none_after_a_deadlock(self):
        self.expectErrorLog("EBoekhoudenPartyExtractor")
        self._reaches_caller_3029(
            "`tabCustomer`",
            ("INSERT",),
            lambda: EBoekhoudenPartyExtractor(self.company).resolve_party_for_journal_entry(
                {"party_name": f"Probe 3029 {self.uid} JE BV", "party_type": "Customer"},
                frappe.db.get_value(
                    "Account", {"company": self.company, "account_type": "Receivable", "is_group": 0}
                ),
            ),
        )

    def test_party_extractor_still_returns_none_for_an_ordinary_error(self):
        """Control: the handler keeps degrading on a non-lock error."""
        self.expectErrorLog("EBoekhoudenPartyExtractor")
        with patch.object(EBoekhoudenPartyExtractor, "_resolve_party_by_name", side_effect=ValueError("o")):
            self.assertIsNone(
                EBoekhoudenPartyExtractor(self.company).resolve_party_for_journal_entry(
                    {"party_name": "x", "party_type": "Customer"}, "Debtors - X"
                )
            )

    # --- party_resolver ------------------------------------------------------------------
    def test_update_party_with_fresh_data_does_not_return_false_after_a_deadlock(self):
        party = self._existing_party_3029(provisional=True)
        self._reaches_caller_3029(
            "`tabCustomer`",
            ("UPDATE",),
            lambda: EBoekhoudenPartyResolver()._update_party_with_fresh_data(
                "Customer", party.name, {"bedrijfsnaam": "Better BV"}, []
            ),
        )

    def test_create_contact_lets_a_deadlock_reach_the_caller(self):
        party = self._existing_party_3029()
        self._reaches_caller_3029(
            "`tabContact`",
            ("INSERT",),
            lambda: EBoekhoudenPartyResolver().create_contact(party, {"email": "p3029@example.com"}, []),
        )

    def test_add_party_address_lets_a_deadlock_reach_the_caller(self):
        self.expectErrorLog("failed to create address")
        party = self._existing_party_3029()
        self._reaches_caller_3029(
            "`tabAddress`",
            ("INSERT",),
            lambda: EBoekhoudenPartyResolver()._add_party_address(party, {"adres": "Probeweg 1", "plaats": "Utrecht"}, []),
        )

    def test_create_contact_still_swallows_an_ordinary_failure(self):
        """Control: a non-lock failure (a party object with no title) is still recorded and swallowed."""
        debug = []
        EBoekhoudenPartyResolver().create_contact(SimpleNamespace(name="P-3029", doctype="Customer"), {"email": "p@example.com"}, debug)
        self.assertTrue(any("Failed to create contact" in d for d in debug), debug)

    # --- invoice_helpers -----------------------------------------------------------------
    def test_create_customer_from_relation_does_not_pass_over_a_deadlock_on_the_field_update(self):
        name = f"Probe 3029 Relation {self.uid} BV"
        self._reaches_caller_3029(
            "`tabCustomer`",
            ("UPDATE",),
            lambda: invoice_helpers.create_customer_from_relation(
                {"id": f"3029{self.uid}", "name": f"{name} {next(self._seq_3029)}", "email": "p@example.com"},
                [],
            ),
        )

    def test_create_customer_from_relation_does_not_turn_a_deadlock_on_the_party_insert_into_a_validation_error(
        self,
    ):
        self._reaches_caller_3029(
            "`tabCustomer`",
            ("INSERT",),
            lambda: invoice_helpers.create_customer_from_relation(
                {"id": f"3029{self.uid}", "name": f"Probe 3029 Rel Ins {self.uid} BV"}, []
            ),
        )
