"""
#2739: a Ponto Settings form loaded BEFORE a token refresh or a sync must not roll
``access_token_expiry`` / ``last_sync_time`` back.

Both are written with ``db.set_value(update_modified=False)``, so ``modified`` does not move
and Frappe's stale-save check cannot refuse the stale Single save. ``access_token_expiry``
is read by ``PontoOAuth2Service.get_access_token`` to decide whether the stored access token
is still usable, so a rolled-back value makes a fresh token look expired and forces a refresh
(Ibanity invalidates a refresh token on use).

The writers are the REAL ones: ``PontoOAuth2Service._store_tokens`` and
``PontoConfigurationService.update_last_sync_time`` (both commit, so ``singleton_backup``
restores the Single in a ``finally``). Rows are put at a known value straight in tabSingles.
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import get_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import PontoTestDataFactory
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
    PontoConfigurationService,
)
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import PontoOAuth2Service

DOCTYPE = "Ponto Settings"
LONG_AGO = "2020-01-01 00:00:00"


class TestStalePontoSettingsSaveKeepsBackgroundFields(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._orig_in_test = frappe.flags.in_test
        frappe.flags.in_test = True

    def tearDown(self):
        frappe.flags.in_test = self._orig_in_test
        super().tearDown()

    def _raw_ponto_single_2739(self, field):
        row = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s", (DOCTYPE, field))
        return row[0][0] if row else None

    def _stale_doc_then_background_writers(self):
        """A form open in a tab, then a token refresh and a sync, then the staff save."""
        settings = frappe.get_single(DOCTYPE)
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "sandbox-id"
        settings.sandbox_client_secret = "sandbox-secret"
        settings.save()
        frappe.db.set_value(DOCTYPE, DOCTYPE, "access_token_expiry", LONG_AGO, update_modified=False)
        frappe.db.set_value(DOCTYPE, DOCTYPE, "last_sync_time", LONG_AGO, update_modified=False)
        frappe.clear_document_cache(DOCTYPE, DOCTYPE)
        stale = frappe.get_doc(DOCTYPE)
        self.assertEqual(str(stale.access_token_expiry), LONG_AGO)
        PontoOAuth2Service()._store_tokens(PontoTestDataFactory.create_token_response(expires_in=1800))
        PontoConfigurationService.update_last_sync_time()
        return stale

    def test_stale_save_does_not_roll_back_access_token_expiry(self):
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_then_background_writers()
            written = self._raw_ponto_single_2739("access_token_expiry")
            self.assertNotIn("2020-01-01", str(written))
            stale.save()
            self.assertEqual(self._raw_ponto_single_2739("access_token_expiry"), written)
            # the consequence: the stored token is still judged usable
            expiry = get_datetime(self._raw_ponto_single_2739("access_token_expiry"))
            self.assertGreater(expiry, datetime.now() + timedelta(minutes=10))

    def test_stale_save_does_not_roll_back_last_sync_time(self):
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_then_background_writers()
            written = self._raw_ponto_single_2739("last_sync_time")
            self.assertNotIn("2020-01-01", str(written))
            stale.save()
            self.assertEqual(self._raw_ponto_single_2739("last_sync_time"), written)

    def test_control_a_stale_save_still_writes_what_staff_edit(self):
        """Control: only the background-owned fields are re-read; a staff edit still lands."""
        with singleton_backup(DOCTYPE):
            stale = self._stale_doc_then_background_writers()
            stale.sync_interval_hours = 7
            stale.save()
            self.assertEqual(int(self._raw_ponto_single_2739("sync_interval_hours")), 7)

    def test_revoke_tokens_still_clears_the_expiry(self):
        """Control for the writer flag: revoke_tokens saves the doc and MUST clear the field."""
        with singleton_backup(DOCTYPE):
            settings = frappe.get_single(DOCTYPE)
            settings.sandbox_mode = 1
            settings.sandbox_client_id = "sandbox-id"
            settings.sandbox_client_secret = "sandbox-secret"
            settings.save()
            PontoOAuth2Service()._store_tokens(PontoTestDataFactory.create_token_response(expires_in=1800))
            self.assertTrue(self._raw_ponto_single_2739("access_token_expiry"))
            PontoOAuth2Service().revoke_tokens()
            self.assertFalse(self._raw_ponto_single_2739("access_token_expiry"))
