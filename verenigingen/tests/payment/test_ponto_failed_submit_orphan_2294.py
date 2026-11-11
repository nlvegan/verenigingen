# Copyright (c) 2026, Verenigingen
"""A submit that fails AFTER Ponto created the payment must not orphan it -- #2294.

``before_submit`` calls Ponto first and Frappe writes the row afterwards, so a failure of
that write left a real, unsigned payment at Ponto with no local row pointing at it. The
maintainer ruling (2026-11-11): best-effort delete it with the on_cancel helpers, re-raise
the original error, and when the delete fails too write an Error Log row and raise the
registered staff alert naming the Ponto id. No commit inside the hook.

The failure is injected BELOW the real submit: the stubbed Ponto client answers with an id
longer than the ``Data`` column, so Frappe's own length validation raises
CharacterLengthExceededError after ``before_submit`` returned (the shape #2279 hit with a
230-character link). The second trigger is a real ``on_submit`` raising, after the write.
Only the Ponto HTTP client is stubbed. Control: a good submit calls no delete.

Usage:
    bench --site test_site_11 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_failed_submit_orphan_2294
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.hooks.lifecycle import after_install
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    PAY_CLIENT_PATH,
    _PontoPaymentRequestFixtures,
)
from verenigingen.verenigingen_payments.doctype.ponto_payment_link.ponto_payment_link import PontoPaymentLink
from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
    PontoPaymentRequest,
)
from verenigingen.verenigingen_payments.ponto.core.submitted_rows import ORPHAN_TITLE

LINK_CLIENT_PATH = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)
CONFIG = "Verenigingen Email Configuration"
OVERLONG_ID = "ponto-orphan-" + "x" * 200  # Data columns are varchar(140)


def _stub_orphan_client(ponto_id, delete_error=None):
    """The Ponto HTTP boundary: creates with ``ponto_id`` and records every delete."""
    created = SimpleNamespace(id=ponto_id, redirect_link=f"https://ponto.example/sign/{ponto_id[:20]}")
    return SimpleNamespace(
        create_payment=lambda **kw: created,
        create_payment_request=lambda **kw: created,
        delete_payment=MagicMock(side_effect=delete_error),
        delete_payment_request=MagicMock(side_effect=delete_error),
    )


class _OrphanChecks:
    def setUp(self):
        super().setUp()
        # A key with no row counts as disabled; a fresh CI site seeds rows in after_install.
        backup = SingletonBackup(CONFIG)
        backup.backup()
        self.addCleanup(backup.restore)
        frappe.get_attr(next(h for h in after_install if h.endswith("ensure_notification_registry_rows")))()

    def _orphan_alerts(self, name):
        notes = frappe.get_all(
            "Notification Log",
            filters={"document_name": name, "subject": ["like", f"{ORPHAN_TITLE}%"]},
            fields=["subject", "email_content"],
        )
        logs = frappe.get_all(
            "Error Log", filters={"method": ORPHAN_TITLE, "error": ["like", f"%{name}%"]}, fields=["error"]
        )
        return notes, logs

    def _assert_one_alert_naming(self, name, ponto_id):
        notes, logs = self._orphan_alerts(name)
        self.assertTrue(notes, "the staff alert must reach somebody")
        self.assertTrue(all(ponto_id in n.subject + n.email_content for n in notes))
        self.assertEqual(len(logs), 1)
        self.assertIn(ponto_id, logs[0].error)

    def _assert_no_alert(self, name):
        self.assertEqual(self._orphan_alerts(name), ([], []))

    def _on_submit_raising(self, doctype_class):
        return patch.object(doctype_class, "on_submit", create=True, side_effect=RuntimeError("late hook"))


class TestPontoPaymentRequestFailedSubmit(_OrphanChecks, _PontoPaymentRequestFixtures, EnhancedTestCase):
    def _make_draft_request_2294(self):
        supplier = self._create_supplier("Orphan2294")
        req = frappe.new_doc("Ponto Payment Request")
        req.ponto_account = self.TEST_PONTO_ACCOUNT_ID
        req.amount = 42.0
        req.currency = "EUR"
        req.creditor_name = supplier.supplier_name
        req.creditor_iban = "NL91ABNA0417164300"
        req.remittance_info = "Orphan #2294"
        req.reference_doctype = "Supplier"
        req.reference_name = supplier.name
        req.insert(ignore_permissions=True)
        self.factory.track_document("Ponto Payment Request", req.name, priority=6)
        return req

    def test_a_failure_after_the_create_deletes_the_payment_and_reraises(self):
        req = self._make_draft_request_2294()
        client = _stub_orphan_client(OVERLONG_ID)
        with patch(PAY_CLIENT_PATH, return_value=client):
            with self.assertRaises(frappe.CharacterLengthExceededError):
                req.submit()
        client.delete_payment.assert_called_once_with(
            account_id=self.TEST_PONTO_ACCOUNT_ID, payment_id=OVERLONG_ID
        )
        row = frappe.db.get_value("Ponto Payment Request", req.name, ["docstatus", "ponto_payment_id"])
        self.assertEqual(tuple(row), (0, None), "no submitted row may point at the deleted payment")
        self._assert_no_alert(req.name)

    def test_a_late_on_submit_failure_deletes_the_payment_and_reraises(self):
        req = self._make_draft_request_2294()
        client = _stub_orphan_client("ponto-pay-2294-late")
        with patch(PAY_CLIENT_PATH, return_value=client), self._on_submit_raising(PontoPaymentRequest):
            with self.assertRaises(RuntimeError):
                req.submit()
        client.delete_payment.assert_called_once_with(
            account_id=self.TEST_PONTO_ACCOUNT_ID, payment_id="ponto-pay-2294-late"
        )

    def test_a_failed_delete_writes_an_error_log_row_and_alerts_staff_with_the_id(self):
        req = self._make_draft_request_2294()
        client = _stub_orphan_client(OVERLONG_ID, delete_error=ConnectionError("ponto down"))
        self.expectErrorLog(ORPHAN_TITLE)
        with patch(PAY_CLIENT_PATH, return_value=client):
            with self.assertErrorLog(ORPHAN_TITLE):
                with self.assertRaises(frappe.CharacterLengthExceededError):
                    req.submit()
        client.delete_payment.assert_called_once()
        self._assert_one_alert_naming(req.name, OVERLONG_ID)

    def test_a_good_submit_deletes_nothing_and_alerts_nobody(self):
        req = self._make_draft_request_2294()
        client = _stub_orphan_client("ponto-pay-2294-ok")
        with patch(PAY_CLIENT_PATH, return_value=client):
            req.submit()
        client.delete_payment.assert_not_called()
        self.assertEqual(
            tuple(frappe.db.get_value("Ponto Payment Request", req.name, ["docstatus", "status"])),
            (1, "Pending"),
        )
        self._assert_no_alert(req.name)


class TestPontoPaymentLinkFailedSubmit(_OrphanChecks, EnhancedTestCase):
    def _make_draft_link_2294(self):
        link = frappe.new_doc("Ponto Payment Link")
        link.payment_type = "One-Time"
        link.amount = 30.0
        link.currency = "EUR"
        link.description = "Contributie 2294"
        link.creditor_name = "Vereniging Test"
        link.creditor_iban = "NL91ABNA0417164300"
        link.insert(ignore_permissions=True)
        self.track_doc("Ponto Payment Link", link.name)
        return link

    def test_a_failure_after_the_create_deletes_the_request_and_reraises(self):
        link = self._make_draft_link_2294()
        client = _stub_orphan_client(OVERLONG_ID)
        with patch(LINK_CLIENT_PATH, return_value=client):
            with self.assertRaises(frappe.CharacterLengthExceededError):
                link.submit()
        client.delete_payment_request.assert_called_once_with(OVERLONG_ID)
        row = frappe.db.get_value("Ponto Payment Link", link.name, ["docstatus", "ponto_request_id"])
        self.assertEqual(tuple(row), (0, None), "no submitted row may point at the deleted request")
        self._assert_no_alert(link.name)

    def test_a_late_on_submit_failure_deletes_the_request_and_reraises(self):
        link = self._make_draft_link_2294()
        client = _stub_orphan_client("ponto-req-2294-late")
        with patch(LINK_CLIENT_PATH, return_value=client), self._on_submit_raising(PontoPaymentLink):
            with self.assertRaises(RuntimeError):
                link.submit()
        client.delete_payment_request.assert_called_once_with("ponto-req-2294-late")

    def test_a_failed_delete_writes_an_error_log_row_and_alerts_staff_with_the_id(self):
        link = self._make_draft_link_2294()
        client = _stub_orphan_client(OVERLONG_ID, delete_error=ConnectionError("ponto down"))
        self.expectErrorLog(ORPHAN_TITLE)
        with patch(LINK_CLIENT_PATH, return_value=client):
            with self.assertErrorLog(ORPHAN_TITLE):
                with self.assertRaises(frappe.CharacterLengthExceededError):
                    link.submit()
        client.delete_payment_request.assert_called_once()
        self._assert_one_alert_naming(link.name, OVERLONG_ID)

    def test_a_good_submit_deletes_nothing_and_alerts_nobody(self):
        link = self._make_draft_link_2294()
        client = _stub_orphan_client("ponto-req-2294-ok")
        with patch(LINK_CLIENT_PATH, return_value=client):
            link.submit()
        client.delete_payment_request.assert_not_called()
        self.assertEqual(
            tuple(frappe.db.get_value("Ponto Payment Link", link.name, ["docstatus", "status"])),
            (1, "Pending Authorization"),
        )
        self._assert_no_alert(link.name)
