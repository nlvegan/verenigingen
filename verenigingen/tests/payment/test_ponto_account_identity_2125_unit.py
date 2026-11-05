"""
#2125: a Ponto account maps to an ERPNext Bank Account only on an exact,
unambiguous identity; otherwise a dedicated account is created, or the mapping
is PAUSED with a reason staff can read.

Real flows: ``fetch_ponto_accounts`` runs for real (real Bank / GL Account /
Bank Account creation); the only stubs are the Ponto HTTP boundary (the
accounts client, the transactions client's ``list_transactions``) and the token
check. Named ``*_unit.py``-style boundary patching only.

Probe shortcut, stated per the brief: the "already merged" state in
``test_existing_merged_state_*`` is built by a FAITHFUL INSERT (several mapping
rows pointing at one Bank Account, ``enabled=1``, ``sync_status`` default), not
by running the pre-fix code. It is the shape veg11 holds per the issue.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoAccount, PontoTransaction

ACCOUNTS_CLIENT = "verenigingen.verenigingen_payments.ponto.clients.accounts_client.PontoAccountsClient"
TOKEN_MANAGER = "verenigingen.verenigingen_payments.ponto.utils.token_manager.PontoTokenManager"
LIST_TXNS = (
    "verenigingen.verenigingen_payments.ponto.clients.transactions_client."
    "PontoTransactionsClient.list_transactions"
)


def _ponto_acct(account_id, iban="", currency="EUR", description="Acct"):
    return PontoAccount(
        id=account_id,
        reference=iban,
        reference_type="IBAN" if iban else "",
        currency=currency,
        current_balance=Decimal("0"),
        available_balance=Decimal("0"),
        description=description,
        holder_name="Holder",
    )


def _tx(tx_id, account_id, currency="EUR", amount="10.00"):
    return PontoTransaction(
        id=tx_id,
        amount=Decimal(amount),
        currency=currency,
        value_date=date(2026, 1, 5),
        execution_date=date(2026, 1, 5),
        description=f"tx {tx_id}",
        account_id=account_id,
    )


class PontoIdentityBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._orig_in_test = frappe.flags.in_test
        frappe.flags.in_test = True
        self.company = get_eur_test_company()
        frappe.db.set_single_value("Verenigingen Settings", "company", self.company)
        self.sfx = frappe.generate_hash(length=6)

    def tearDown(self):
        frappe.flags.in_test = self._orig_in_test
        frappe.db.rollback()
        super().tearDown()

    def _prepare(self, mappings=()):
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-id"
        settings.sandbox_client_secret = "sandbox-secret"
        settings.bank_account_mappings = []
        for m in mappings:
            settings.append("bank_account_mappings", m)
        settings.save()
        return frappe.get_single("Ponto Settings")

    def _fetch(self, accounts):
        settings = frappe.get_single("Ponto Settings")
        client = MagicMock()
        client.list_accounts.return_value = accounts
        with patch(TOKEN_MANAGER, return_value=MagicMock()), patch(ACCOUNTS_CLIENT, return_value=client):
            result = settings.fetch_ponto_accounts()
        return result

    def _rows(self):
        return {r.ponto_account_id: r for r in frappe.get_single("Ponto Settings").bank_account_mappings}

    def _ba_gl_currency(self, bank_account):
        gl = frappe.db.get_value("Bank Account", bank_account, "account")
        return frappe.db.get_value("Account", gl, "account_currency")

    def _make_manual_bank_account(self, iban, currency="EUR", company=None):
        """A pre-existing manual Bank Account (not created by Ponto code)."""
        company = company or self.company
        parent = frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "account_type": "Bank"}, "name"
        )
        gl = frappe.new_doc("Account")
        gl.account_name = f"Manual Bank {frappe.generate_hash(length=6)}"
        gl.company = company
        gl.parent_account = parent
        gl.account_type = "Bank"
        gl.account_currency = currency
        gl.insert(ignore_permissions=True)
        bank = frappe.db.get_value("Bank", {}, "name")
        if not bank:
            b = frappe.new_doc("Bank")
            b.bank_name = f"Manual Inst {self.sfx}"
            b.insert(ignore_permissions=True)
            bank = b.name
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Manual BA {frappe.generate_hash(length=6)}"
        ba.bank = bank
        ba.account = gl.name
        ba.company = company
        ba.is_company_account = 1
        ba.iban = iban
        ba.insert(ignore_permissions=True)
        return ba.name


class TestFetchIdentity(PontoIdentityBase):
    def test_a_two_ibanless_accounts_of_different_currencies_get_distinct_accounts(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            self._fetch([_ponto_acct("acc-a-eur", "", "EUR", "Alpha"), _ponto_acct("acc-a-gbp", "", "GBP", "Beta")])
            rows = self._rows()
            eur, gbp = rows["acc-a-eur"], rows["acc-a-gbp"]
            self.assertTrue(eur.bank_account and gbp.bank_account)
            self.assertNotEqual(eur.bank_account, gbp.bank_account)
            self.assertEqual(self._ba_gl_currency(eur.bank_account), "EUR")
            self.assertEqual(self._ba_gl_currency(gbp.bank_account), "GBP")
            self.assertEqual((eur.enabled, gbp.enabled), (1, 1))

    def test_a_two_ibanless_accounts_with_the_same_description_stay_distinct(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            self._fetch([_ponto_acct("acc-s-1", "", "EUR", "Same"), _ponto_acct("acc-s-2", "", "EUR", "Same")])
            rows = self._rows()
            self.assertNotEqual(rows["acc-s-1"].bank_account, rows["acc-s-2"].bank_account)
            self.assertNotEqual(
                frappe.db.get_value("Bank Account", rows["acc-s-1"].bank_account, "account"),
                frappe.db.get_value("Bank Account", rows["acc-s-2"].bank_account, "account"),
            )

    def test_b_shared_iban_different_currencies_never_share_an_account(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            iban = TestIBAN.ABN_AMRO_1
            self._fetch([_ponto_acct("acc-b-gbp", iban, "GBP", "Magni"), _ponto_acct("acc-b-eur", iban, "EUR", "Id")])
            rows = self._rows()
            self.assertNotEqual(rows["acc-b-gbp"].bank_account, rows["acc-b-eur"].bank_account)
            self.assertEqual(self._ba_gl_currency(rows["acc-b-gbp"].bank_account), "GBP")
            self.assertEqual(self._ba_gl_currency(rows["acc-b-eur"].bank_account), "EUR")

    def test_b_shared_iban_is_never_adopted_even_when_a_matching_manual_account_exists(self):
        """Control with a real candidate: the manual EUR account matches one Ponto
        account's IBAN and currency, but the IBAN is shared, so it is not exact."""
        with singleton_backup("Ponto Settings"):
            self._prepare()
            iban = TestIBAN.ING_1
            manual = self._make_manual_bank_account(iban, "EUR")
            self._fetch([_ponto_acct("acc-b2-eur", iban, "EUR"), _ponto_acct("acc-b2-gbp", iban, "GBP")])
            rows = self._rows()
            self.assertNotIn(manual, (rows["acc-b2-eur"].bank_account, rows["acc-b2-gbp"].bank_account))
            self.assertNotEqual(rows["acc-b2-eur"].bank_account, rows["acc-b2-gbp"].bank_account)
            self.assertEqual(self._ba_gl_currency(rows["acc-b2-gbp"].bank_account), "GBP")

    def test_c_unambiguous_manual_bank_account_is_adopted(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            iban = TestIBAN.ING_1
            manual = self._make_manual_bank_account(iban, "EUR")
            self._fetch([_ponto_acct("acc-c", iban, "EUR")])
            row = self._rows()["acc-c"]
            self.assertEqual(row.bank_account, manual)
            self.assertEqual(row.enabled, 1)
            self.assertEqual(frappe.db.count("Bank Account", {"iban": iban}), 1)

    def test_d_manual_bank_account_with_currency_mismatch_is_paused_and_gl_untouched(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            iban = TestIBAN.ING_1
            manual = self._make_manual_bank_account(iban, "EUR")
            gl = frappe.db.get_value("Bank Account", manual, "account")
            self._fetch([_ponto_acct("acc-d", iban, "GBP")])
            row = self._rows()["acc-d"]
            self.assertEqual(row.enabled, 0)
            self.assertEqual(row.sync_status, "Paused")
            self.assertIn("GBP", row.last_sync_error)
            self.assertFalse(row.bank_account)
            self.assertEqual(frappe.db.get_value("Account", gl, "account_currency"), "EUR")
            self.assertEqual(frappe.db.count("Bank Account", {"iban": iban}), 1)

    def test_manual_account_claimed_by_another_mapping_is_not_adopted(self):
        """R1 holds Bank Account B (IBAN X). A DIFFERENT Ponto account with IBAN X must not
        adopt B: this reaches _adopt_or_pause, unlike an IBAN-less account."""
        with singleton_backup("Ponto Settings"):
            iban = TestIBAN.ING_1
            manual = self._make_manual_bank_account(iban, "EUR")
            self._prepare(
                [{"ponto_account_id": "r1", "ponto_iban": "", "ponto_currency": "EUR",
                  "bank_account": manual, "enabled": 1}]
            )
            self._fetch([_ponto_acct("r2", iban, "EUR", "Second")])
            rows = self._rows()
            self.assertEqual(rows["r1"].bank_account, manual)
            self.assertEqual((rows["r2"].enabled, rows["r2"].sync_status), (0, "Paused"))
            self.assertFalse(rows["r2"].bank_account)
            self.assertIn("already linked", rows["r2"].last_sync_error)

    def test_manual_account_in_another_company_is_not_adopted(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            iban = TestIBAN.ING_1
            other = "_Test Company"
            self.assertNotEqual(other, self.company)
            manual = self._make_manual_bank_account(iban, "EUR", company=other)
            self._fetch([_ponto_acct("acc-co", iban, "EUR")])
            row = self._rows()["acc-co"]
            self.assertEqual((row.enabled, row.sync_status), (0, "Paused"))
            self.assertIn("another company", row.last_sync_error)
            self.assertNotEqual(row.bank_account, manual)

    def test_two_manual_accounts_with_the_same_iban_pause_and_adopt_neither(self):
        """ERPNext enforces no IBAN uniqueness on Bank Account (the second insert below
        succeeds), so the duplicate-candidate branch is reachable."""
        with singleton_backup("Ponto Settings"):
            self._prepare()
            iban = TestIBAN.ING_1
            first = self._make_manual_bank_account(iban, "EUR")
            second = self._make_manual_bank_account(iban, "EUR")
            self.assertEqual(frappe.db.count("Bank Account", {"iban": iban}), 2)
            self._fetch([_ponto_acct("acc-dup", iban, "EUR")])
            row = self._rows()["acc-dup"]
            self.assertEqual((row.enabled, row.sync_status), (0, "Paused"))
            self.assertFalse(row.bank_account)
            self.assertIn("2 Bank Accounts carry IBAN", row.last_sync_error)
            self.assertNotIn(row.bank_account, (first, second))

    def test_refetch_is_idempotent(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            accounts = [_ponto_acct("acc-i1", "", "EUR", "One"), _ponto_acct("acc-i2", "", "GBP", "Two")]
            self._fetch(accounts)
            before = {k: v.bank_account for k, v in self._rows().items()}
            n_ba = frappe.db.count("Bank Account")
            self._fetch(accounts)
            self.assertEqual({k: v.bank_account for k, v in self._rows().items()}, before)
            self.assertEqual(frappe.db.count("Bank Account"), n_ba)

    def test_creation_failure_pauses_the_account_with_reason(self):
        self.expectErrorLog("Ponto bank account creation failed")
        with singleton_backup("Ponto Settings"):
            self._prepare()
            with patch(
                "verenigingen.verenigingen_payments.ponto.utils.bank_account_creator.get_parent_bank_account_group",
                return_value=None,
            ):
                self._fetch([_ponto_acct("acc-fail", "", "EUR", "Nope")])
            row = self._rows()["acc-fail"]
            self.assertEqual((row.enabled, row.sync_status), (0, "Paused"))
            self.assertFalse(row.bank_account)
            self.assertTrue(row.last_sync_error)

    def test_cleanup_keeps_ibanless_rows_and_dedupes_by_account_id(self):
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.bank_account_mappings = []
            for acc_id in ("x1", "x2", "x2"):
                settings.append("bank_account_mappings", {"ponto_account_id": acc_id, "ponto_iban": ""})
            removed = settings.cleanup_duplicate_mappings()
            self.assertEqual(removed, 1)
            self.assertEqual([r.ponto_account_id for r in settings.bank_account_mappings], ["x1", "x2"])


class TestExistingMergedState(PontoIdentityBase):
    """g: veg11-shaped state (faithful insert, see module docstring)."""

    def _merged(self):
        shared = self._make_manual_bank_account("", "EUR")
        self._prepare(
            [
                {"ponto_account_id": f"m-{c}-{i}", "ponto_iban": "", "ponto_currency": c,
                 "bank_account": shared, "enabled": 1}
                for i, c in enumerate(("EUR", "GBP", "USD"))
            ]
        )
        return shared

    def test_g_refetch_pauses_every_sharing_mapping_and_does_not_rewrite_gl(self):
        with singleton_backup("Ponto Settings"):
            shared = self._merged()
            gl = frappe.db.get_value("Bank Account", shared, "account")
            accounts = [_ponto_acct(f"m-{c}-{i}", "", c) for i, c in enumerate(("EUR", "GBP", "USD"))]
            self._fetch(accounts)
            self._fetch(accounts)  # second retrieve must not make it worse
            for row in self._rows().values():
                self.assertEqual((row.enabled, row.sync_status), (0, "Paused"), row.ponto_account_id)
                self.assertIn("shared", row.last_sync_error)
            self.assertEqual(frappe.db.get_value("Account", gl, "account_currency"), "EUR")

    def test_g_clearing_the_link_recovers_with_a_dedicated_account(self):
        with singleton_backup("Ponto Settings"):
            shared = self._merged()
            accounts = [_ponto_acct(f"m-{c}-{i}", "", c) for i, c in enumerate(("EUR", "GBP", "USD"))]
            self._fetch(accounts)
            settings = frappe.get_single("Ponto Settings")
            for row in settings.bank_account_mappings:
                if row.ponto_currency == "GBP":
                    row.bank_account = None
            settings.save()
            self._fetch(accounts)
            rows = self._rows()
            gbp = rows["m-GBP-1"]
            self.assertEqual((gbp.enabled, gbp.sync_status), (1, "OK"))
            self.assertNotEqual(gbp.bank_account, shared)
            self.assertEqual(self._ba_gl_currency(gbp.bank_account), "GBP")
            # the other two now share nothing with GBP but still share with each other
            self.assertEqual(rows["m-EUR-0"].sync_status, "Paused")

    def test_mismatched_single_mapping_is_paused_not_rewritten(self):
        with singleton_backup("Ponto Settings"):
            ba = self._make_manual_bank_account("", "EUR")
            gl = frappe.db.get_value("Bank Account", ba, "account")
            self._prepare(
                [{"ponto_account_id": "mm", "ponto_iban": "", "ponto_currency": "EUR",
                  "bank_account": ba, "enabled": 1}]
            )
            self._fetch([_ponto_acct("mm", "", "USD")])
            row = self._rows()["mm"]
            self.assertEqual((row.enabled, row.sync_status), (0, "Paused"))
            self.assertIn("USD", row.last_sync_error)
            self.assertEqual(frappe.db.get_value("Account", gl, "account_currency"), "EUR")


class TestImportGuards(PontoIdentityBase):
    def _mapped(self, currency="EUR", **mapping):
        ba = self._make_manual_bank_account("", currency)
        self._prepare(
            [dict({"ponto_account_id": "imp-1", "ponto_account_name": "Imp", "ponto_iban": "",
                   "ponto_currency": currency, "bank_account": ba, "enabled": 1}, **mapping)]
        )
        return ba

    def _bt_count(self, account_id="imp-1"):
        return frappe.db.count("Bank Transaction", {"custom_ponto_account_id": account_id})

    def test_e_paused_mapping_imports_nothing_and_reports_once(self):
        with singleton_backup("Ponto Settings"):
            self._mapped(enabled=1, sync_status="Paused", last_sync_error="shared bank account X")
            calls = []
            with patch(LIST_TXNS, side_effect=lambda **kw: calls.append(kw) or [_tx("t1", "imp-1")]):
                from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
                    import_new_transactions,
                )

                out = import_new_transactions("imp-1")
            self.assertEqual(calls, [])
            self.assertEqual(self._bt_count(), 0)
            self.assertEqual(out.get("reason"), "account_paused")
            self.assertIn("shared bank account X", " ".join(out["errors"]))

    def test_e_manual_sync_with_a_paused_mapping_gives_one_summary(self):
        with singleton_backup("Ponto Settings"):
            ba = self._make_manual_bank_account("", "EUR")
            self._prepare(
                [
                    {"ponto_account_id": "p-ok", "ponto_account_name": "Ok", "ponto_currency": "EUR",
                     "bank_account": ba, "enabled": 1},
                    {"ponto_account_id": "p-paused", "ponto_account_name": "Paused one",
                     "ponto_currency": "GBP", "bank_account": ba, "enabled": 0,
                     "sync_status": "Paused", "last_sync_error": "shared bank account"},
                ]
            )
            settings = frappe.get_single("Ponto Settings")
            seen = []

            def fake_list(**kw):
                seen.append(kw["account_id"])
                return []

            before = len(frappe.local.message_log)
            with patch(LIST_TXNS, side_effect=fake_list):
                result = settings.trigger_manual_sync()
            self.assertEqual(seen, ["p-ok"])
            new = frappe.local.message_log[before:]
            texts = [m.get("message", "") if isinstance(m, dict) else str(m) for m in new]
            self.assertEqual(len([t for t in texts if "Paused one" in t]), 1, texts)
            self.assertEqual(len(new), 1, texts)
            self.assertEqual(self._bt_count("p-paused"), 0)
            self.assertTrue(result["success"])

    def test_f_currency_mismatch_inserts_nothing_pauses_and_reports_once(self):
        with singleton_backup("Ponto Settings"):
            ba = self._mapped("EUR")
            txs = [_tx("f1", "imp-1", "EUR"), _tx("f2", "imp-1", "GBP"), _tx("f3", "imp-1", "GBP")]
            settings = frappe.get_single("Ponto Settings")
            before = len(frappe.local.message_log)
            errlog = frappe.db.count("Error Log", {"method": ["like", "Secure Operation Failed%"]})
            with patch(LIST_TXNS, return_value=txs):
                result = settings.trigger_manual_sync()
            self.assertEqual(self._bt_count(), 0)
            self.assertEqual(result["imported"], 0)
            row = self._rows()["imp-1"]
            self.assertEqual((row.enabled, row.sync_status), (0, "Paused"))
            self.assertIn("GBP", row.last_sync_error)
            self.assertEqual(self._ba_gl_currency(ba), "EUR")
            new = frappe.local.message_log[before:]
            self.assertEqual(len(new), 1, new)
            self.assertEqual(
                frappe.db.count("Error Log", {"method": ["like", "Secure Operation Failed%"]}), errlog
            )

    def test_f_matching_currency_still_imports(self):
        """Control: the guard must not refuse legitimate same-currency rows."""
        with singleton_backup("Ponto Settings"):
            self._mapped("EUR")
            with patch(LIST_TXNS, return_value=[_tx("ok1", "imp-1", "EUR")]):
                result = frappe.get_single("Ponto Settings").trigger_manual_sync()
            self.assertEqual(result["imported"], 1)
            self.assertEqual(self._bt_count(), 1)
            self.assertEqual(self._rows()["imp-1"].sync_status, "OK")

    def test_no_enabled_mappings_throws_without_error_log_row(self):
        with singleton_backup("Ponto Settings"):
            self._prepare()
            before = frappe.db.count("Error Log", {"method": ["like", "Ponto manual sync failed%"]})
            with self.assertRaises(frappe.ValidationError) as ctx:
                frappe.get_single("Ponto Settings").trigger_manual_sync()
            self.assertNotIn("Sync failed", str(ctx.exception))
            self.assertEqual(
                frappe.db.count("Error Log", {"method": ["like", "Ponto manual sync failed%"]}), before
            )

    def test_webhook_sync_ok_does_not_clear_a_pause(self):
        with singleton_backup("Ponto Settings"):
            self._mapped(enabled=0, sync_status="Paused", last_sync_error="why")
            from verenigingen.verenigingen_payments.ponto.api.webhook import _update_account_sync_status

            _update_account_sync_status("imp-1", status="OK")
            row = self._rows()["imp-1"]
            self.assertEqual((row.sync_status, row.last_sync_error), ("Paused", "why"))


class TestPausedMappingsOnMoneyPaths(PontoIdentityBase):
    """B2: a paused mapping is refused by every reader, including after staff re-tick
    `enabled` on a Paused row (enabled=1, sync_status=Paused)."""

    STATES = ({"enabled": 0, "sync_status": "Paused"}, {"enabled": 1, "sync_status": "Paused"})

    def _paused(self, **state):
        ba = self._make_manual_bank_account("", "EUR")
        self._prepare(
            [dict({"ponto_account_id": "pm-1", "ponto_account_name": "Paused acct", "ponto_iban": "",
                   "ponto_currency": "EUR", "bank_account": ba, "last_sync_error": "shared bank account X"},
                  **state)]
        )
        return ba

    def test_create_sepa_payment_refuses_a_paused_account(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        for state in self.STATES:
            with self.subTest(state=state), singleton_backup("Ponto Settings"):
                self._paused(**state)
                before = frappe.db.count("Ponto Payment Request", {"ponto_account": "pm-1"})
                with self.assertRaises(PontoIntegrationError) as ctx:
                    create_sepa_payment("pm-1", 10.0, "Cred", TestIBAN.ABN_AMRO_1, "ref", auto_submit=False)
                self.assertIn("shared bank account X", str(ctx.exception))
                self.assertEqual(frappe.db.count("Ponto Payment Request", {"ponto_account": "pm-1"}), before)

    def test_create_sepa_payment_refuses_an_unmapped_account_as_before(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_sepa_payment,
        )

        with singleton_backup("Ponto Settings"):
            self._prepare()
            with self.assertRaises(PontoIntegrationError):
                create_sepa_payment("nope", 10.0, "Cred", TestIBAN.ABN_AMRO_1, "ref", auto_submit=False)

    def _make_supplier_with_iban(self):
        sup = frappe.new_doc("Supplier")
        sup.supplier_name = f"Ponto Sup {frappe.generate_hash(length=6)}"
        sup.insert(ignore_permissions=True)
        sup_ba = frappe.new_doc("Bank Account")
        sup_ba.account_name = f"Sup BA {frappe.generate_hash(length=6)}"
        sup_ba.bank = frappe.db.get_value("Bank", {}, "name")
        sup_ba.party_type, sup_ba.party = "Supplier", sup.name
        sup_ba.iban = TestIBAN.ABN_AMRO_2
        sup_ba.insert(ignore_permissions=True)
        return sup.name

    def test_default_account_for_supplier_payment_skips_a_paused_row(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError
        from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
            create_payment_for_supplier,
        )

        for state in self.STATES:
            with self.subTest(state=state), singleton_backup("Ponto Settings"):
                self._paused(**state)
                supplier = [self._make_supplier_with_iban()]
                with self.assertRaises(PontoIntegrationError) as ctx:
                    create_payment_for_supplier(supplier[0], 5.0, "ref", auto_submit=False)
                self.assertIn("No enabled Ponto accounts", str(ctx.exception))

    def test_payment_entry_prerequisites_refuse_a_paused_account_with_the_reason(self):
        for state in self.STATES:
            with self.subTest(state=state), singleton_backup("Ponto Settings"):
                self._paused(**state)
                doc = frappe.new_doc("Ponto Payment Request")
                doc.ponto_account = "pm-1"
                with self.assertRaises(frappe.ValidationError) as ctx:
                    doc._validate_payment_entry_prerequisites()
                self.assertIn("shared bank account X", str(ctx.exception))

    def test_getters_use_the_same_rule(self):
        from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
            PontoConfigurationService as Config,
        )

        for state in self.STATES:
            with self.subTest(state=state), singleton_backup("Ponto Settings"):
                self._paused(**state)
                Config.clear_cache()
                self.assertEqual(Config.get_enabled_account_mappings(), [])
                self.assertIsNone(Config.get_bank_account_for_ponto_account("pm-1"))
                self.assertIsNone(Config.get_first_enabled_bank_account())
                settings = frappe.get_single("Ponto Settings")
                self.assertEqual(settings.get_enabled_account_mappings(), [])
                self.assertIsNone(settings.get_bank_account_for_ponto_account("pm-1"))

    def test_usable_mapping_still_passes_every_reader(self):
        """Control: an enabled, OK, linked mapping is NOT refused."""
        from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
            PontoConfigurationService as Config,
        )

        with singleton_backup("Ponto Settings"):
            ba = self._paused(enabled=1, sync_status="OK")
            Config.clear_cache()
            self.assertEqual(Config.get_bank_account_for_ponto_account("pm-1"), ba)
            doc = frappe.new_doc("Ponto Payment Request")
            doc.ponto_account = "pm-1"
            try:
                doc._validate_payment_entry_prerequisites()
            except frappe.ValidationError as e:
                self.assertNotIn("paused", str(e).lower())


class TestStalePausesAreNotOverwritten(PontoIdentityBase):
    """S1: a stale in-memory copy must not un-pause a mapping paused meanwhile."""

    def _paused_after_load(self):
        ba = self._make_manual_bank_account("", "EUR")
        self._prepare(
            [{"ponto_account_id": "st-1", "ponto_iban": "", "ponto_currency": "EUR",
              "bank_account": ba, "enabled": 1}]
        )
        stale = frappe.get_single("Ponto Settings")
        from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
            PontoConfigurationService,
        )

        self.assertTrue(PontoConfigurationService.pause_mapping("st-1", "Import refused: test reason"))
        return stale

    def test_refresh_user_info_does_not_unpause(self):
        with singleton_backup("Ponto Settings"):
            stale = self._paused_after_load()
            client = MagicMock()
            client.get.return_value = {"name": "Org", "sub": "org-1", "onboardingComplete": True}
            with patch("verenigingen.verenigingen_payments.ponto.core.ponto_client.PontoClient", return_value=client):
                stale.refresh_user_info()
            row = self._rows()["st-1"]
            self.assertEqual((row.enabled, row.sync_status), (0, "Paused"))
            self.assertEqual(frappe.db.get_single_value("Ponto Settings", "organization_name"), "Org")

    def test_fetch_cleanup_does_not_unpause(self):
        with singleton_backup("Ponto Settings"):
            ba = self._make_manual_bank_account("", "EUR")
            self._prepare(
                [
                    {"ponto_account_id": "st-1", "ponto_iban": "", "ponto_currency": "EUR",
                     "bank_account": ba, "enabled": 1},
                ]
            )
            stale = frappe.get_single("Ponto Settings")
            stale.append("bank_account_mappings", {"ponto_account_id": "st-1"})  # duplicate to clean
            from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
                PontoConfigurationService,
            )

            PontoConfigurationService.pause_mapping("st-1", "Import refused: test reason")
            client = MagicMock()
            client.list_accounts.return_value = [_ponto_acct("st-1", "", "EUR")]
            with patch(TOKEN_MANAGER, return_value=MagicMock()), patch(ACCOUNTS_CLIENT, return_value=client):
                stale.fetch_ponto_accounts()
            row = self._rows()["st-1"]
            self.assertEqual((row.enabled, row.sync_status), (0, "Paused"))

    def test_fetch_does_not_overwrite_a_pause_set_while_it_runs(self):
        """A pause landing during account creation (after the fetch loaded the mappings)."""
        from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
            PontoConfigurationService,
        )
        from verenigingen.verenigingen_payments.ponto.utils import bank_account_creator as creator

        with singleton_backup("Ponto Settings"):
            ba = self._make_manual_bank_account("", "EUR")
            self._prepare(
                [{"ponto_account_id": "st-1", "ponto_iban": "", "ponto_currency": "EUR",
                  "bank_account": ba, "enabled": 1}]
            )
            real_create = creator.create_ponto_bank_account

            def create_and_pause(*args, **kwargs):
                PontoConfigurationService.pause_mapping("st-1", "Import refused: concurrent")
                return real_create(*args, **kwargs)

            client = MagicMock()
            client.list_accounts.return_value = [_ponto_acct("st-1", "", "EUR"), _ponto_acct("st-2", "", "EUR", "New")]
            settings = frappe.get_single("Ponto Settings")
            with patch(TOKEN_MANAGER, return_value=MagicMock()), patch(
                ACCOUNTS_CLIENT, return_value=client
            ), patch.object(creator, "create_ponto_bank_account", side_effect=create_and_pause):
                settings.fetch_ponto_accounts()
            rows = self._rows()
            self.assertEqual((rows["st-1"].enabled, rows["st-1"].sync_status), (0, "Paused"))
            self.assertEqual(rows["st-2"].sync_status, "OK")

    def test_audit_pause_resumes_but_an_import_refusal_does_not(self):
        with singleton_backup("Ponto Settings"):
            ba1 = self._make_manual_bank_account("", "EUR")
            ba2 = self._make_manual_bank_account("", "EUR")
            self._prepare(
                [
                    {"ponto_account_id": "au-1", "ponto_iban": "", "ponto_currency": "EUR", "bank_account": ba1,
                     "enabled": 0, "sync_status": "Paused", "last_sync_error": "Bank Account x is shared by 2"},
                    {"ponto_account_id": "au-2", "ponto_iban": "", "ponto_currency": "EUR", "bank_account": ba2,
                     "enabled": 0, "sync_status": "Paused", "last_sync_error": "Import refused: GBP rows"},
                ]
            )
            self._fetch([_ponto_acct("au-1", "", "EUR"), _ponto_acct("au-2", "", "EUR")])
            rows = self._rows()
            self.assertEqual((rows["au-1"].enabled, rows["au-1"].sync_status), (1, "OK"))
            self.assertEqual((rows["au-2"].enabled, rows["au-2"].sync_status), (0, "Paused"))

    def test_webhook_failure_on_a_paused_account_keeps_pause_and_reason(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook import _update_account_sync_status

        with singleton_backup("Ponto Settings"):
            ba = self._make_manual_bank_account("", "EUR")
            self._prepare(
                [{"ponto_account_id": "wf-1", "ponto_iban": "", "ponto_currency": "EUR", "bank_account": ba,
                  "enabled": 0, "sync_status": "Paused", "last_sync_error": "the pause reason"}]
            )
            _update_account_sync_status("wf-1", status="Failed", error="ibanity 500")
            row = self._rows()["wf-1"]
            self.assertEqual((row.sync_status, row.last_sync_error), ("Paused", "the pause reason"))
            self.assertIsNotNone(row.last_sync_failure_time)
