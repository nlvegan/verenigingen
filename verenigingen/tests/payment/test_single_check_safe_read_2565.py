"""#2565: a Single's safety Check must read as its SAFE default when its row is unset.

Frappe applies a Single's JSON defaults only while the doctype has no ``tabSingles`` rows at all.
``frappe.db.set_single_value`` on a row-less Single creates rows for only ``modified``,
``modified_by`` and the field it was given, so every other Check then reads 0, which for
``Mollie Settings.test_mode`` / ``Ponto Settings.sandbox_mode`` means LIVE and for
``Ponto Settings.require_webhook_signature`` means "unsigned webhooks accepted". This module
reproduces that exact mechanism (not a hand-built row) and asks the real consumers.

Probe shortcuts, stated per the brief: blank/NULL rows are hand-written (a save never produces
them); live credentials are written to ``__Auth`` / ``tabSingles`` directly. Everything touched is
restored on cleanup. No gateway HTTP client is involved.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password

from verenigingen.verenigingen_payments.ponto.api.webhook import is_signature_required
from verenigingen.verenigingen_payments.ponto.services.configuration_service import PontoConfigurationService
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import PontoOAuth2Service
from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
    MollieConfigurationService,
)

PONTO, MOLLIE, ING = "Ponto Settings", "Mollie Settings", "ING Checkout Settings"
LIVE_PASSWORD = {PONTO: "production_client_secret", MOLLIE: "live_secret_key"}


class TestSingleCheckSafeRead(FrappeTestCase):
    def setUp(self):
        for doctype in (PONTO, MOLLIE):
            rows = frappe.db.sql("select field, value from tabSingles where doctype=%s", doctype)
            self.addCleanup(self._restore_rows_2565, doctype, rows)
            frappe.db.sql("delete from tabSingles where doctype=%s", doctype)
        auth = frappe.db.sql(
            "select doctype, name, fieldname, password, encrypted from __Auth where doctype in %s "
            "and fieldname in %s",
            ((PONTO, MOLLIE), tuple(LIVE_PASSWORD.values())),
        )
        self.addCleanup(self._restore_auth_2565, auth)
        frappe.db.sql(
            "delete from __Auth where doctype in %s and fieldname in %s",
            ((PONTO, MOLLIE), tuple(LIVE_PASSWORD.values())),
        )
        self._clear_2565()

    def _restore_rows_2565(self, doctype, rows):
        frappe.db.sql("delete from tabSingles where doctype=%s", doctype)
        for field, value in rows:
            frappe.db.sql(
                "insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (doctype, field, value)
            )
        self._clear_2565()

    def _restore_auth_2565(self, auth):
        frappe.db.sql(
            "delete from __Auth where doctype in %s and fieldname in %s",
            ((PONTO, MOLLIE), tuple(LIVE_PASSWORD.values())),
        )
        for row in auth:
            frappe.db.sql(
                "insert into __Auth (doctype, name, fieldname, password, encrypted) values (%s,%s,%s,%s,%s)",
                row,
            )

    def _clear_2565(self):
        for doctype in (PONTO, MOLLIE):
            frappe.clear_document_cache(doctype, doctype)
        PontoConfigurationService.clear_cache()
        MollieConfigurationService.clear_cache()
        frappe.clear_document_cache(ING, ING)

    def _partial_rows(self, doctype, field="profile_id", value="x"):
        """The defect's real mechanism: set_single_value on a row-less Single."""
        frappe.db.set_single_value(doctype, field, value)
        self._clear_2565()
        stored = {r[0] for r in frappe.db.sql("select field from tabSingles where doctype=%s", doctype)}
        self.assertEqual(stored, {"modified", "modified_by", field}, "control: only those rows exist")

    def _set_row_2565(self, doctype, field, value):
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (doctype, field))
        frappe.db.sql(
            "insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (doctype, field, value)
        )
        self._clear_2565()

    def _live_credentials(self, doctype):
        set_encrypted_password(doctype, doctype, "live-test-value", LIVE_PASSWORD[doctype])
        self._clear_2565()

    # --- Mollie Settings.test_mode: unset means TEST ---

    def test_mollie_unset_test_mode_reads_test_through_the_document_and_the_service(self):
        self._partial_rows(MOLLIE)
        self.assertEqual(frappe.get_single(MOLLIE).test_mode, 1)
        self.assertTrue(MollieConfigurationService.is_test_mode())

    def test_mollie_blank_or_null_test_mode_reads_test(self):
        for value in ("", None):
            self._partial_rows_then_blank(MOLLIE, "test_mode", value)
            self.assertEqual(frappe.get_single(MOLLIE).test_mode, 1, repr(value))

    def test_mollie_explicit_zero_is_honoured(self):
        self._partial_rows(MOLLIE)
        self._set_row_2565(MOLLIE, "test_mode", "0")
        self.assertEqual(frappe.get_single(MOLLIE).test_mode, 0)
        self.assertFalse(MollieConfigurationService.is_test_mode())

    def test_mollie_unset_test_mode_with_live_credentials_stays_live(self):
        """Maintainer ruling on #2509: a live site is not flipped to test mode silently."""
        self._partial_rows(MOLLIE)
        self._live_credentials(MOLLIE)
        self.assertEqual(frappe.get_single(MOLLIE).test_mode, 0)

    def test_mollie_with_no_rows_at_all_keeps_the_declared_default(self):
        self.assertEqual(frappe.get_single(MOLLIE).test_mode, 1)

    def _partial_rows_then_blank(self, doctype, field, value):
        self._partial_rows(doctype) if not frappe.db.sql(
            "select 1 from tabSingles where doctype=%s", doctype
        ) else None
        self._set_row_2565(doctype, field, "x")
        frappe.db.sql(
            "update tabSingles set value=%s where doctype=%s and field=%s", (value, doctype, field)
        )
        self._clear_2565()

    # --- Ponto Settings.sandbox_mode: unset means SANDBOX ---

    def test_ponto_unset_sandbox_mode_reads_sandbox_through_the_document_and_consumers(self):
        self._partial_rows(PONTO)
        self.assertEqual(frappe.get_single(PONTO).sandbox_mode, 1)
        self.assertTrue(PontoConfigurationService.is_sandbox_mode())
        self.assertEqual(
            PontoOAuth2Service()._get_authorization_base_url(), PontoOAuth2Service.SANDBOX_AUTHORIZATION_URL
        )

    def test_ponto_blank_or_null_sandbox_mode_reads_sandbox(self):
        for value in ("", None):
            self._partial_rows_then_blank(PONTO, "sandbox_mode", value)
            self.assertEqual(frappe.get_single(PONTO).sandbox_mode, 1, repr(value))

    def test_ponto_explicit_zero_is_honoured(self):
        self._partial_rows(PONTO)
        self._set_row_2565(PONTO, "sandbox_mode", "0")
        self.assertEqual(frappe.get_single(PONTO).sandbox_mode, 0)
        self.assertFalse(PontoConfigurationService.is_sandbox_mode())

    def test_ponto_unset_sandbox_mode_with_live_credentials_stays_production(self):
        self._partial_rows(PONTO)
        self._live_credentials(PONTO)
        self.assertEqual(frappe.get_single(PONTO).sandbox_mode, 0)

    def test_ponto_unset_sandbox_mode_with_production_client_id_only_stays_production(self):
        self._partial_rows(PONTO)
        self._set_row_2565(PONTO, "production_client_id", "live-id")
        self.assertEqual(frappe.get_single(PONTO).sandbox_mode, 0)

    # --- ING Checkout Settings.sandbox_mode: unset means SANDBOX ---

    def _ing_snapshot(self):
        rows = frappe.db.sql("select field, value from tabSingles where doctype=%s", ING)
        auth = frappe.db.sql(
            "select doctype, name, fieldname, password, encrypted from __Auth where doctype=%s", ING
        )
        self.addCleanup(self._restore_ing, rows, auth)
        frappe.db.sql("delete from tabSingles where doctype=%s", ING)
        frappe.db.sql("delete from __Auth where doctype=%s", ING)
        frappe.clear_document_cache(ING, ING)

    def _restore_ing(self, rows, auth):
        frappe.db.sql("delete from tabSingles where doctype=%s", ING)
        frappe.db.sql("delete from __Auth where doctype=%s", ING)
        for field, value in rows:
            frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s,%s,%s)", (ING, field, value))
        for row in auth:
            frappe.db.sql(
                "insert into __Auth (doctype, name, fieldname, password, encrypted) values (%s,%s,%s,%s,%s)", row
            )
        frappe.clear_document_cache(ING, ING)

    def test_ing_unset_sandbox_mode_reads_sandbox_and_blank_too(self):
        self._ing_snapshot()
        self._partial_rows(ING, "service_id", "SL-1-2")
        settings = frappe.get_single(ING)
        self.assertEqual(settings.sandbox_mode, 1)
        for value in ("", None):
            self._set_row_2565(ING, "sandbox_mode", "x")
            frappe.db.sql("update tabSingles set value=%s where doctype=%s and field='sandbox_mode'", (value, ING))
            frappe.clear_document_cache(ING, ING)
            self.assertEqual(frappe.get_single(ING).sandbox_mode, 1, repr(value))

    def test_ing_explicit_zero_is_honoured(self):
        self._ing_snapshot()
        self._partial_rows(ING, "service_id", "SL-1-2")
        self._set_row_2565(ING, "sandbox_mode", "0")
        self.assertEqual(frappe.get_single(ING).sandbox_mode, 0)

    def test_ing_unset_sandbox_mode_on_an_operating_integration_stays_production(self):
        self._ing_snapshot()
        self._partial_rows(ING, "service_id", "SL-1-2")
        self._set_row_2565(ING, "enabled", "1")
        set_encrypted_password(ING, ING, "tok", "api_token")
        frappe.clear_document_cache(ING, ING)
        self.assertEqual(frappe.get_single(ING).sandbox_mode, 0)

    # --- Ponto Settings.require_webhook_signature: unset means REQUIRED ---

    def test_ponto_unset_signature_flag_requires_the_signature(self):
        self._partial_rows(PONTO, "enable_webhooks", "1")
        settings = frappe.get_single(PONTO)
        self.assertEqual(settings.require_webhook_signature, 1)
        self.assertTrue(is_signature_required(settings))

    def test_ponto_explicit_zero_signature_flag_is_the_operators_opt_out(self):
        self._partial_rows(PONTO, "enable_webhooks", "1")
        self._set_row_2565(PONTO, "require_webhook_signature", "0")
        settings = frappe.get_single(PONTO)
        self.assertEqual(settings.require_webhook_signature, 0)
        self.assertFalse(is_signature_required(settings))
