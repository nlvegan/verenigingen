"""#2509: a Ponto/Mollie settings Single saved before ``sandbox_mode`` / ``test_mode`` existed reads
the flag as 0, which selects the PRODUCTION Ponto authorization URL / client and LIVE Mollie mode.
The patch writes the missing row as 1 (the declared default) and never touches an existing row.

Probe shortcut: the row state is built with raw ``tabSingles`` writes (that is the defect's state; a
save writes every field) and ``execute`` is called directly, not through the patch runner. The
whole row set of each doctype is restored on cleanup. No gateway HTTP client is involved: the
consumers asked are the pure mode decisions.
"""

import importlib

import frappe
from frappe.modules import patch_handler
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password

from verenigingen.setup import patch_fragments
from verenigingen.verenigingen_payments.ponto.services.configuration_service import PontoConfigurationService
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import PontoOAuth2Service
from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
    MollieConfigurationService,
)

PATCH = "verenigingen.patches.v2_2.seed_gateway_sandbox_mode_defaults_2509"
PONTO = ("Ponto Settings", "sandbox_mode")
MOLLIE = ("Mollie Settings", "test_mode")
LIVE_PASSWORDS = {
    "Ponto Settings": ("production_client_secret",),
    "Mollie Settings": ("live_secret_key",),
}
ERROR_TITLE = "%.% has no stored value but live credentials are configured%"


def _stored_value_2509(doctype, field):
    r = frappe.db.sql("select value from tabSingles where doctype=%s and field=%s", (doctype, field))
    return r[0][0] if r else None


class TestSeedGatewaySandboxModeDefaults(FrappeTestCase):
    def setUp(self):
        for doctype, _field in (PONTO, MOLLIE):
            rows = frappe.db.sql("select field, value from tabSingles where doctype=%s", doctype)
            self.addCleanup(self._restore_rows_2509, doctype, rows)
            # a saved Single: a row for another field exists, so Frappe will not apply defaults
            frappe.db.sql("delete from tabSingles where doctype=%s and field='profile_id'", doctype)
            frappe.db.sql(
                "insert into tabSingles (doctype, field, value) values (%s, 'profile_id', 'x')", doctype
            )
        self.addCleanup(self._clear_caches_2509)
        # this bench carries live gateway credentials and CI does not: start from "none" explicitly
        auth = frappe.db.sql(
            "select doctype, name, fieldname, password, encrypted from __Auth where doctype in %s",
            (("Ponto Settings", "Mollie Settings"),),
        )
        self.addCleanup(self._restore_auth_2509, auth)
        frappe.db.sql(
            "delete from __Auth where doctype in %s and fieldname in %s",
            (("Ponto Settings", "Mollie Settings"), tuple(f for fs in LIVE_PASSWORDS.values() for f in fs)),
        )
        frappe.db.sql("delete from tabSingles where doctype='Ponto Settings' and field='production_client_id'")
        self.addCleanup(self._purge_error_logs_2509)

    def _restore_auth_2509(self, auth):
        frappe.db.sql(
            "delete from __Auth where doctype in %s and fieldname in %s",
            (("Ponto Settings", "Mollie Settings"), tuple(f for fs in LIVE_PASSWORDS.values() for f in fs)),
        )
        for row in auth:
            if row[2] in tuple(f for fs in LIVE_PASSWORDS.values() for f in fs):
                frappe.db.sql(
                    "insert into __Auth (doctype, name, fieldname, password, encrypted) values (%s,%s,%s,%s,%s)",
                    row,
                )

    @staticmethod
    def _purge_error_logs_2509():
        # Error Log is MyISAM: a rollback would not remove what the patch wrote
        frappe.db.sql("delete from `tabError Log` where method like %s", ERROR_TITLE)

    @staticmethod
    def _error_logs_2509(field):
        return frappe.db.sql(
            "select name from `tabError Log` where method like %s", f"%.{field} has no stored value%"
        )

    @staticmethod
    def _set_live_credentials_2509(doctype):
        for field in LIVE_PASSWORDS[doctype]:
            set_encrypted_password(doctype, doctype, "live-test-value", field)
        if doctype == "Ponto Settings":
            frappe.db.sql(
                "insert into tabSingles (doctype, field, value) values (%s, 'production_client_id', 'live-id')",
                doctype,
            )

    def _restore_rows_2509(self, doctype, rows):
        frappe.db.sql("delete from tabSingles where doctype=%s", doctype)
        for field, value in rows:
            frappe.db.sql(
                "insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (doctype, field, value)
            )
        frappe.clear_document_cache(doctype, doctype)

    @staticmethod
    def _clear_caches_2509():
        PontoConfigurationService.clear_cache()
        MollieConfigurationService.clear_cache()

    def _drop_row_2509(self, target):
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", target)
        frappe.clear_document_cache(target[0], target[0])
        self._clear_caches_2509()

    def _run_patch_2509(self):
        importlib.import_module(PATCH).execute()
        self._clear_caches_2509()

    def test_a_missing_ponto_row_selects_the_sandbox_after_the_patch(self):
        self._drop_row_2509(PONTO)
        self.assertEqual(
            PontoOAuth2Service()._get_authorization_base_url(),
            PontoOAuth2Service.LIVE_AUTHORIZATION_URL,
            "control: without the patch the missing row selects the PRODUCTION authorization URL",
        )
        self._run_patch_2509()
        self.assertEqual(_stored_value_2509(*PONTO), "1")
        self.assertEqual(
            PontoOAuth2Service()._get_authorization_base_url(), PontoOAuth2Service.SANDBOX_AUTHORIZATION_URL
        )
        self.assertTrue(PontoConfigurationService.is_sandbox_mode())

    def test_a_missing_mollie_row_selects_test_mode_after_the_patch(self):
        self._drop_row_2509(MOLLIE)
        self.assertFalse(
            MollieConfigurationService.is_test_mode(), "control: without the patch the site reads LIVE"
        )
        self._clear_caches_2509()
        self._run_patch_2509()
        self.assertEqual(_stored_value_2509(*MOLLIE), "1")
        self.assertTrue(MollieConfigurationService.is_test_mode())
        self.assertEqual(frappe.get_single("Mollie Settings").test_mode, 1)

    def test_an_explicit_zero_is_never_touched(self):
        for target in (PONTO, MOLLIE):
            self._drop_row_2509(target)
            frappe.db.sql(
                "insert into tabSingles (doctype, field, value) values (%s, %s, '0')", target
            )
        self._run_patch_2509()
        for target in (PONTO, MOLLIE):
            self.assertEqual(_stored_value_2509(*target), "0")
        self.assertFalse(PontoConfigurationService.is_sandbox_mode())
        self.assertFalse(MollieConfigurationService.is_test_mode())

    def test_a_site_with_no_rows_is_left_to_the_declared_default(self):
        for doctype, field in (PONTO, MOLLIE):
            frappe.db.sql("delete from tabSingles where doctype=%s", doctype)
            frappe.clear_document_cache(doctype, doctype)
        self._run_patch_2509()
        for target in (PONTO, MOLLIE):
            self.assertIsNone(_stored_value_2509(*target))
            self.assertEqual(frappe.get_single(target[0]).get(target[1]), 1)

    def test_it_is_idempotent(self):
        for target in (PONTO, MOLLIE):
            self._drop_row_2509(target)
        self._run_patch_2509()
        self._run_patch_2509()
        for target in (PONTO, MOLLIE):
            count = frappe.db.sql(
                "select count(*) from tabSingles where doctype=%s and field=%s", target
            )[0][0]
            self.assertEqual(count, 1)

    def test_the_patch_is_registered_as_a_fragment(self):
        patch_fragments.install()
        self.assertIn(PATCH, patch_handler.get_patches_from_app("verenigingen"))

    def test_a_missing_row_with_live_credentials_is_left_and_one_error_log_is_written(self):
        for target in (PONTO, MOLLIE):
            self._drop_row_2509(target)
            self._set_live_credentials_2509(target[0])
        self._run_patch_2509()
        for target in (PONTO, MOLLIE):
            self.assertIsNone(_stored_value_2509(*target), "the live site is not flipped to test mode")
            self.assertEqual(len(self._error_logs_2509(target[1])), 1, target)
        self.assertFalse(MollieConfigurationService.is_test_mode(), "still reads live, as before")
        self._run_patch_2509()
        # a second run alerts again by design (a patch runs once); the first run wrote exactly one each
        self.assertEqual(len(self._error_logs_2509("test_mode")), 2)

    def test_an_error_log_names_the_doctype_and_field(self):
        self._drop_row_2509(MOLLIE)
        self._set_live_credentials_2509(MOLLIE[0])
        self._run_patch_2509()
        message = frappe.db.sql(
            "select error from `tabError Log` where method like %s", "%.test_mode has no stored value%"
        )[0][0]
        self.assertIn("Mollie Settings.test_mode", message)

    def test_a_present_row_with_live_credentials_is_untouched(self):
        for target in (PONTO, MOLLIE):
            self._drop_row_2509(target)
            frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s, %s, '0')", target)
            self._set_live_credentials_2509(target[0])
        self._run_patch_2509()
        for target in (PONTO, MOLLIE):
            self.assertEqual(_stored_value_2509(*target), "0")
            self.assertEqual(self._error_logs_2509(target[1]), ())

    def test_live_credentials_of_one_gateway_do_not_block_the_other(self):
        for target in (PONTO, MOLLIE):
            self._drop_row_2509(target)
        self._set_live_credentials_2509(MOLLIE[0])
        self._run_patch_2509()
        self.assertEqual(_stored_value_2509(*PONTO), "1")
        self.assertIsNone(_stored_value_2509(*MOLLIE))

    def test_a_blank_or_null_row_is_seeded_without_live_credentials(self):
        for blank in ("", None):
            for target in (PONTO, MOLLIE):
                self._drop_row_2509(target)
                frappe.db.sql(
                    "insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (*target, blank)
                )
            self._run_patch_2509()
            for target in (PONTO, MOLLIE):
                self.assertEqual(_stored_value_2509(*target), "1", (target, blank))

    def test_a_blank_row_with_live_credentials_is_left_and_alerted(self):
        self._drop_row_2509(MOLLIE)
        frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s, %s, '')", MOLLIE)
        self._set_live_credentials_2509(MOLLIE[0])
        self._run_patch_2509()
        self.assertEqual(_stored_value_2509(*MOLLIE), "")
        self.assertEqual(len(self._error_logs_2509("test_mode")), 1)

    def _assert_ponto_row_left_and_alerted_2509(self):
        self._run_patch_2509()
        self.assertIsNone(_stored_value_2509(*PONTO), "one live credential half is enough to leave the row")
        self.assertEqual(len(self._error_logs_2509(PONTO[1])), 1)

    def test_a_ponto_production_client_id_alone_counts_as_a_live_credential(self):
        self._drop_row_2509(PONTO)
        frappe.db.sql(
            "insert into tabSingles (doctype, field, value) values (%s, 'production_client_id', 'live-id')",
            PONTO[0],
        )
        self._assert_ponto_row_left_and_alerted_2509()

    def test_a_ponto_production_client_secret_alone_counts_as_a_live_credential(self):
        self._drop_row_2509(PONTO)
        set_encrypted_password(PONTO[0], PONTO[0], "live-test-value", "production_client_secret")
        self._assert_ponto_row_left_and_alerted_2509()
