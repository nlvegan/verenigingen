"""#2478: an unsaved ``require_webhook_signature`` must mean "signature required".

The field's JSON default is 1, but Frappe applies a Single's defaults only when the doctype has NO
``tabSingles`` rows at all. A site that saved Ponto Settings before the field existed has rows for
every other field and none for this one, so the Document reads it as 0 and the webhook accepted
unsigned events once ``enable_webhooks`` was turned on.

Everything goes through Frappe's real dispatch (``execute_cmd``) as Guest, via the helper the
sibling #1804 tests use. Probe shortcut, stated per the brief: the row state is built with raw
``tabSingles`` writes (that IS the defect's state; a save writes every field) and the whole row
set is restored on cleanup. Only the JWKS fetch is stubbed, and it is never reached for an
unsigned request.

An unsigned delivery that is PROCESSED answers 400 ("Unknown event format", the payload carries no
event type); a refused one answers 401, so the status discriminates the two.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.payment import test_ing_ponto_webhook_response_minimal as sibling

DT = "Ponto Settings"
FIELD = "require_webhook_signature"
PONTO = sibling.PONTO
PROCESSED, REFUSED = 400, 401


class TestPontoWebhookSignatureDefault(sibling._GuestWebhookCase):
    def setUp(self):
        super().setUp()
        rows = frappe.db.sql("select field, value from tabSingles where doctype=%s", DT)
        self.addCleanup(self._restore_rows, rows)
        self._seed_row("enable_webhooks", "1")
        frappe.cache.delete_keys("webhook_error_log_once:*")

    def _restore_rows(self, rows):
        frappe.db.sql("delete from tabSingles where doctype=%s", DT)
        for field, value in rows:
            frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (DT, field, value))
        frappe.clear_document_cache(DT, DT)

    def _seed_row(self, field, value):
        frappe.db.sql("delete from tabSingles where doctype=%s and field=%s", (DT, field))
        if value is not None:
            frappe.db.sql(
                "insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (DT, field, value)
            )
        frappe.clear_document_cache(DT, DT)

    def _post_unsigned(self):
        with patch(f"{PONTO}.verify_ponto_webhook", side_effect=AssertionError("unsigned: no JWKS")):  # Mock justified: JWKS fetch
            body, status, _ = self._post(
                f"{PONTO}.handle_ponto_webhook", {"data": {"id": "evt-unsigned"}}, ip="203.0.113.77"
            )
        return status

    def test_a_missing_row_among_saved_rows_requires_the_signature(self):
        self._seed_row(FIELD, None)
        # control: the premise is real, the Document does read the missing row as 0
        self.assertEqual(frappe.get_single(DT).get(FIELD), 0)
        self.assertEqual(self._post_unsigned(), REFUSED)

    def test_an_explicit_zero_still_lets_unsigned_events_through(self):
        """Control: the operator's explicit opt-out (a real row of 0) is honoured, so the
        refusal above comes from the missing row and not from refusing everything."""
        self._seed_row(FIELD, "0")
        self.assertEqual(self._post_unsigned(), PROCESSED)

    def test_an_explicit_one_requires_the_signature(self):
        self._seed_row(FIELD, "1")
        self.assertEqual(self._post_unsigned(), REFUSED)

    def test_a_site_with_no_rows_at_all_gets_the_declared_default(self):
        frappe.db.sql("delete from tabSingles where doctype=%s", DT)
        frappe.clear_document_cache(DT, DT)
        # webhooks are off on such a site; the field itself must still read as required
        from verenigingen.verenigingen_payments.ponto.api.webhook import is_signature_required

        self.assertTrue(is_signature_required(frappe.get_single(DT)))

    def test_an_unreadable_setting_requires_the_signature(self):
        """The check itself failing must not mean "not required". Probe shortcut: the failure is
        forced by patching the one query."""
        from verenigingen.verenigingen_payments.ponto.api.webhook import is_signature_required

        self._seed_row(FIELD, "0")
        self.expectErrorLog("Ponto webhook: signature setting unreadable")
        settings = frappe.get_single(DT)
        real_sql = frappe.db.sql

        def fail_only_the_signature_query(query, *args, **kwargs):
            if "FROM tabSingles" in query and "COALESCE" in query:
                raise RuntimeError("db gone")
            return real_sql(query, *args, **kwargs)

        with patch.object(frappe.db, "sql", side_effect=fail_only_the_signature_query):  # Mock justified: forced DB failure
            self.assertTrue(is_signature_required(settings))
