"""
#2792: a Ponto Settings form loaded BEFORE a webhook / sync / pause must not roll the
``Ponto Bank Account Mapping`` rows' background-written fields back (child-table sibling
of #2739).

The writers write the rows with ``update_modified=False`` (or a raw UPDATE), so the parent's
``modified`` does not move, Frappe's stale-save check cannot refuse the stale form, and the
save rewrites every child row from the in-memory values. The writers here are the REAL ones
(``_update_account_sync_status`` of the webhook, ``PontoConfigurationService.update_last_sync_time``,
``increment_transactions_imported``, ``pause_mapping``). The initial rows are put at a known
value with ``db.set_value`` (probe shortcut for "the state the stale form was loaded with").
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.verenigingen_payments.ponto.api.webhook import _update_account_sync_status
from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
    PontoConfigurationService,
)

DOCTYPE = "Ponto Settings"
ROW = "Ponto Bank Account Mapping"
LONG_AGO = "2020-01-01 00:00:00"
ACCOUNT_A = "acct-2792-aaaa"
ACCOUNT_B = "acct-2792-bbbb"
BACKGROUND_FIELDS = (
    "sync_status",
    "last_sync_time",
    "last_sync_error",
    "last_sync_failure_time",
    "transactions_imported",
    "enabled",
)


class TestStaleMappingSaveKeepsRowState(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._orig_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._orig_in_test
        super().tearDown()

    def _mapping_row_2792(self, account_id):
        return frappe.db.get_value(
            ROW,
            {"parent": DOCTYPE, "ponto_account_id": account_id},
            ["name", *BACKGROUND_FIELDS, "bank_account"],
            as_dict=True,
        )

    def _stale_doc_2792(self):
        """Settings with two mapped accounts, rows at a known old state, form loaded."""
        settings = frappe.get_single(DOCTYPE)
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-id"
        settings.sandbox_client_secret = "sandbox-secret"
        settings.set("bank_account_mappings", [])
        for account_id in (ACCOUNT_A, ACCOUNT_B):
            settings.append("bank_account_mappings", {"enabled": 1, "ponto_account_id": account_id})
        settings.save()
        for account_id in (ACCOUNT_A, ACCOUNT_B):
            frappe.db.set_value(
                ROW,
                self._mapping_row_2792(account_id).name,
                {
                    "sync_status": "OK",
                    "last_sync_time": LONG_AGO,
                    "last_sync_error": None,
                    "last_sync_failure_time": None,
                    "transactions_imported": 1,
                },
                update_modified=False,
            )
        frappe.clear_document_cache(DOCTYPE, DOCTYPE)
        stale = frappe.get_doc(DOCTYPE)
        self.assertEqual(len(stale.bank_account_mappings), 2)
        return stale

    def test_stale_save_keeps_webhook_failure_status(self):
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_2792()
            self.assertTrue(_update_account_sync_status(ACCOUNT_A, status="Failed", error="boom 2792"))
            written = self._mapping_row_2792(ACCOUNT_A)
            self.assertEqual(written.sync_status, "Failed")
            stale.save()
            after = self._mapping_row_2792(ACCOUNT_A)
            for field in ("sync_status", "last_sync_error", "last_sync_failure_time"):
                self.assertEqual(after[field], written[field], field)
            self.assertEqual(after.last_sync_error, "boom 2792")

    def test_stale_save_keeps_webhook_success_stamp(self):
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_2792()
            self.assertTrue(_update_account_sync_status(ACCOUNT_A, status="OK"))
            written = self._mapping_row_2792(ACCOUNT_A)
            self.assertNotIn("2020-01-01", str(written.last_sync_time))
            stale.save()
            self.assertEqual(self._mapping_row_2792(ACCOUNT_A).last_sync_time, written.last_sync_time)

    def test_stale_save_keeps_update_last_sync_time_stamp(self):
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_2792()
            PontoConfigurationService.update_last_sync_time(ponto_account_id=ACCOUNT_A)
            written = self._mapping_row_2792(ACCOUNT_A)
            self.assertNotIn("2020-01-01", str(written.last_sync_time))
            stale.save()
            self.assertEqual(self._mapping_row_2792(ACCOUNT_A).last_sync_time, written.last_sync_time)

    def test_stale_save_keeps_transactions_imported(self):
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_2792()
            PontoConfigurationService.increment_transactions_imported(ACCOUNT_A, 5)
            self.assertEqual(self._mapping_row_2792(ACCOUNT_A).transactions_imported, 6)
            stale.save()
            self.assertEqual(self._mapping_row_2792(ACCOUNT_A).transactions_imported, 6)

    def test_stale_save_keeps_a_pause(self):
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_2792()
            self.assertTrue(PontoConfigurationService.pause_mapping(ACCOUNT_A, "currency mismatch 2792"))
            stale.save()
            after = self._mapping_row_2792(ACCOUNT_A)
            self.assertEqual(after.sync_status, "Paused")
            self.assertEqual(after.enabled, 0)
            self.assertEqual(after.last_sync_error, "currency mismatch 2792")

    def test_control_the_other_account_is_untouched(self):
        """Control: the row no writer touched keeps its own (old) values, not account A's."""
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_2792()
            _update_account_sync_status(ACCOUNT_A, status="Failed", error="boom")
            stale.save()
            other = self._mapping_row_2792(ACCOUNT_B)
            self.assertEqual(other.sync_status, "OK")
            self.assertEqual(str(other.last_sync_time), LONG_AGO)
            self.assertEqual(other.transactions_imported, 1)

    def test_control_a_stale_save_still_writes_what_staff_edit(self):
        """Control: bank_account (staff-owned) and a new row still land via a stale save."""
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_2792()
            _update_account_sync_status(ACCOUNT_A, status="Failed", error="boom")
            bank_account = frappe.db.get_value("Bank Account", {}, "name")
            if bank_account:
                stale.bank_account_mappings[1].bank_account = bank_account
            stale.append("bank_account_mappings", {"enabled": 1, "ponto_account_id": "acct-2792-new"})
            stale.save()
            new = self._mapping_row_2792("acct-2792-new")
            self.assertTrue(new)
            self.assertEqual(new.sync_status, "OK")
            if bank_account:
                self.assertEqual(self._mapping_row_2792(ACCOUNT_B).bank_account, bank_account)
            self.assertEqual(self._mapping_row_2792(ACCOUNT_A).sync_status, "Failed")
