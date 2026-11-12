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

from verenigingen.setup import patch_fragments
from verenigingen.verenigingen_payments.ponto.services.configuration_service import PontoConfigurationService
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import PontoOAuth2Service
from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
    MollieConfigurationService,
)

PATCH = "verenigingen.patches.v2_2.seed_gateway_sandbox_mode_defaults_2509"
PONTO = ("Ponto Settings", "sandbox_mode")
MOLLIE = ("Mollie Settings", "test_mode")


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
