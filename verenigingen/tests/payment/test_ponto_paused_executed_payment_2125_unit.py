"""
#2125 / #1288 / #1848: Ponto reports a payment EXECUTED for a request whose Ponto account
mapping is Paused (or staff-disabled). The Payment Entry would book against a shared or
wrong-currency GL, so it is refused. The money has moved, so staff must get ONE loud,
specific alert naming the row and the amount, and the request must not be marked Executed
or Paid.

Driven through the real paths: refresh_status (UI button), the hourly poll's
``_refresh_one``, ``update_status_from_webhook`` and the webhook entrypoint
``handle_payment_request_closed``. Only the Ponto HTTP boundary is stubbed
(``get_payment_client``). Named ``*_unit.py`` for that boundary stub.
"""

import json
import os
import subprocess
import sys
import textwrap
import time
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import PaymentStatus, PontoTestDataFactory
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    PAY_CLIENT_PATH,
    _mock_ponto_get_payment_client,
    _PontoPaymentRequestFixtures,
)
from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
    PontoConfigurationService,
)

MARKER = "PONTO-EXECUTED-UNBOOKABLE"


class TestExecutedPaymentOnPausedAccount(_PontoPaymentRequestFixtures, EnhancedTestCase):
    AMOUNT = 123.45

    def tearDown(self):
        PontoConfigurationService.clear_cache()
        super().tearDown()

    def _paused_request(self, hint, disabled_only=False):
        req = self._create_ponto_request(self._create_supplier(hint), status="Signed", amount=self.AMOUNT)
        if disabled_only:
            frappe.db.set_value(
                "Ponto Bank Account Mapping",
                {"parent": "Ponto Settings", "ponto_account_id": self.TEST_PONTO_ACCOUNT_ID},
                "enabled",
                0,
            )
            PontoConfigurationService.clear_cache()
        else:
            PontoConfigurationService.pause_mapping(self.TEST_PONTO_ACCOUNT_ID, "shared bank account X")
        return req

    def _alerts(self, req):
        return frappe.get_all(
            "Notification Log",
            filters={"document_type": req.doctype, "document_name": req.name, "subject": ["like", f"{MARKER}%"]},
            fields=["subject", "email_content", "for_user"],
        )

    def _assert_unbooked_and_alerted(self, req):
        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Signed", "must not be marked Executed (or Paid)")
        self.assertFalse(row.payment_entry)
        self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": req.name}))
        alerts = self._alerts(req)
        # one Notification Log per recipient, none duplicated: a single alert, not one per attempt
        self.assertTrue(alerts)
        self.assertEqual(len({a.for_user for a in alerts}), len(alerts), alerts)
        text = alerts[0].subject + (alerts[0].email_content or "")
        self.assertIn(req.name, text)
        self.assertIn("123.45", text)
        self.assertIn("shared bank account X", text)

    def test_refresh_status_alerts_once_and_leaves_the_row_signed(self):
        req = self._paused_request("RefreshPaused")
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        counts = []
        for _ in range(2):  # a repeat (hourly poll) must not alert again
            with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
                req.reload()
                result = req.refresh_status()
            self.assertEqual(result["status"], "Signed")
            counts.append(len(self._alerts(req)))
        self.assertGreater(counts[0], 0)
        self.assertEqual(counts[0], counts[1], "the repeat must not send a second alert")
        self._assert_unbooked_and_alerted(req)

    def test_poll_path_alerts_and_leaves_the_row_signed(self):
        from verenigingen.verenigingen_payments.ponto.services.status_poll_service import _refresh_one

        req = self._paused_request("PollPaused")
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            outcome = _refresh_one("Ponto Payment Request", req.name)
        self.assertEqual(outcome, "ok")
        self._assert_unbooked_and_alerted(req)

    def test_webhook_entrypoint_alerts_and_leaves_the_row_signed(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_request_closed,
        )

        req = self._paused_request("WebhookPaused")
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id=req.ponto_payment_id, status=PaymentStatus.EXECUTED
            )
        )
        result = handle_payment_request_closed(payload)
        self.assertNotIn(req.name, result.get("updated_requests") or [])
        self.assertFalse(result.get("failed_requests"))
        self._assert_unbooked_and_alerted(req)

    def test_staff_disabled_mapping_is_refused_the_same_way(self):
        req = self._paused_request("DisabledOnly", disabled_only=True)
        self.expectErrorLog(MARKER, "Ponto payment executed but cannot be booked")
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.refresh_status()
        row = frappe.db.get_value("Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True)
        self.assertEqual((row.status, row.payment_entry), ("Signed", None))
        self.assertTrue(self._alerts(req))

    def test_usable_mapping_still_books_and_sends_no_alert(self):
        """Control: an enabled, OK mapping takes the normal path (no alert)."""
        req = self._create_ponto_request(
            self._create_supplier("Usable"), status="Signed", amount=self.AMOUNT, track_priority=6
        )
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.refresh_status()
        self.assertEqual(self._alerts(req), [])
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Executed")


ALERT_TITLE = "Ponto payment executed but cannot be booked"
UNDELIVERED_TITLE = "Ponto executed-unbookable alert was NOT DELIVERED to anyone"


class TestUnbookableAlertDelivery(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """N1: the alert reuses the #1848 machinery: once per row, locked, loud if undelivered."""

    def tearDown(self):
        PontoConfigurationService.clear_cache()
        super().tearDown()

    def _error_logs(self, title):
        return frappe.db.count("Error Log", {"method": title, "error": ["like", f"{MARKER}: %"]})

    def test_undelivered_alert_writes_one_loud_row_across_many_refreshes(self):
        """Key unseeded (counts as disabled): nobody can be notified. The poll retries hourly,
        but Error Log must get ONE row of each kind, not one per retry."""
        self.expectErrorLog(MARKER, ALERT_TITLE, UNDELIVERED_TITLE)
        req = self._create_ponto_request(self._create_supplier("Undelivered"), status="Signed", amount=77.0)
        PontoConfigurationService.pause_mapping(self.TEST_PONTO_ACCOUNT_ID, "shared bank account X")
        before = (self._error_logs(ALERT_TITLE), self._error_logs(UNDELIVERED_TITLE))
        # Disable the key's row in place and restore that one value in `finally`. Emptying the whole
        # singleton under singleton_backup leaked: the harness drain commits the open transaction.
        child = frappe.get_meta("Verenigingen Email Configuration").get_field("notification_types").options
        row_filters = {"parent": "Verenigingen Email Configuration", "notification_key": "ponto_executed_unbookable"}
        self.assertTrue(frappe.db.exists(child, row_filters), "control: the key is seeded")
        self._set_key_enabled(child, row_filters, 0)
        try:
            for _ in range(4):
                with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
                    req.reload()
                    req.refresh_status()
        finally:
            self._set_key_enabled(child, row_filters, 1)
        after = (self._error_logs(ALERT_TITLE), self._error_logs(UNDELIVERED_TITLE))
        self.assertEqual(after[0] - before[0], 1, "one Error Log row for the alert, not one per refresh")
        self.assertEqual(after[1] - before[1], 1, "one 'nobody was notified' row, not one per refresh")
        self.assertEqual(self._notification_logs(req), 0, "control: nothing was delivered")

    def _set_key_enabled(self, child, row_filters, value):
        frappe.db.set_value(child, row_filters, "enabled", value)
        frappe.clear_document_cache("Verenigingen Email Configuration", "Verenigingen Email Configuration")

    def _notification_logs(self, req):
        return frappe.db.count(
            "Notification Log",
            {"document_type": req.doctype, "document_name": req.name, "subject": ["like", f"{MARKER}%"]},
        )

    def _create_committed_request(self):
        """Commit a request so SEPARATE processes see it. The commit is load-bearing (see
        test_core_client_permission_oracle._create_test_login_password): the subprocesses open
        their own connections and would not see this test's open transaction."""
        req = self._create_ponto_request(self._create_supplier("Concurrent"), status="Signed", amount=88.0)
        frappe.db.commit()
        self.addCleanup(self._cleanup_alert_rows, req.name)
        return req

    def _cleanup_alert_rows(self, name):
        frappe.db.delete("Notification Log", {"document_type": "Ponto Payment Request", "document_name": name})
        frappe.db.delete("Comment", {"reference_doctype": "Ponto Payment Request", "reference_name": name})
        frappe.db.commit()

    def _make_alerter_process(self, name, hold_seconds):
        """A separate process (own DB connection) that raises the alert. ``hold_seconds`` delays
        the delivery INSIDE the alert, so the first process holds its transaction open and the
        second arrives while it is still running."""
        from frappe.utils import get_bench_path

        sites_dir = os.path.join(get_bench_path(), "sites")
        script = textwrap.dedent(
            f"""
            import time
            import frappe
            frappe.init(site={frappe.local.site!r})
            frappe.connect()
            frappe.set_user("Administrator")
            import verenigingen.utils.notification_helpers as nh
            real = nh.notify_administrators
            def slow(*a, **kw):
                time.sleep({hold_seconds})
                return real(*a, **kw)
            nh.notify_administrators = slow
            from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
                alert_executed_unbookable,
            )
            doc = frappe.get_doc("Ponto Payment Request", {name!r})
            alert_executed_unbookable(doc, "shared bank account X")
            frappe.db.commit()
            frappe.destroy()
            """
        )
        return subprocess.Popen(
            [sys.executable, "-c", script], cwd=sites_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

    def test_two_concurrent_alerters_produce_one_alert(self):
        self.expectErrorLog(MARKER, ALERT_TITLE, UNDELIVERED_TITLE)
        req = self._create_committed_request()
        first = self._make_alerter_process(req.name, hold_seconds=4)
        time.sleep(1.5)  # the first is now inside the alert, holding its row lock
        second = self._make_alerter_process(req.name, hold_seconds=0)
        outputs = [p.communicate(timeout=120) for p in (first, second)]
        self.assertEqual((first.returncode, second.returncode), (0, 0), outputs)
        frappe.db.rollback()  # leave the transaction's snapshot: see what the processes committed
        logs = frappe.get_all(
            "Notification Log",
            filters={"document_type": req.doctype, "document_name": req.name, "subject": ["like", f"{MARKER}%"]},
            pluck="for_user",
        )
        self.assertTrue(logs, "control: the alert was delivered")
        self.assertEqual(len(set(logs)), len(logs), f"the alert reached a recipient twice: {logs}")


class TestExecutedPaymentIsNeverBookedTwice(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """N2: the alert tells staff to resolve the pause. Once resolved, the next refresh must not
    book a second Payment Entry for money already booked by hand."""

    def tearDown(self):
        PontoConfigurationService.clear_cache()
        super().tearDown()

    def _set_mapping(self, **values):
        frappe.db.set_value(
            "Ponto Bank Account Mapping",
            {"parent": "Ponto Settings", "ponto_account_id": self.TEST_PONTO_ACCOUNT_ID},
            values,
        )
        PontoConfigurationService.clear_cache()

    def _hand_booked(self, hint):
        """A request whose money is already booked: a real submitted Payment Entry carrying the
        request name as Reference No, but NOT linked to the request.

        Probe shortcut, stated: the PE is made by running the real booking once on a usable
        mapping, then the request is set back to Signed / unlinked with db.set_value, standing
        in for 'staff booked it by hand and the request never learned of it'."""
        req = self._create_ponto_request(
            self._create_supplier(hint), status="Signed", amount=55.0, track_priority=6
        )
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.refresh_status()
        req.reload()
        pe = req.payment_entry
        self.assertTrue(pe, "control: the real booking made a Payment Entry")
        self.factory.track_document("Payment Entry", pe, priority=6)
        frappe.db.set_value(req.doctype, req.name, {"status": "Signed", "payment_entry": None})
        req.reload()
        return req, pe

    def _entries(self, req):
        return frappe.get_all("Payment Entry", filters={"reference_no": req.name, "docstatus": 1}, pluck="name")

    def test_unpausing_links_the_hand_booked_entry_instead_of_booking_again(self):
        self.expectErrorLog(MARKER, ALERT_TITLE)
        req, pe = self._hand_booked("HandBooked")
        self._set_mapping(enabled=0, sync_status="Paused", last_sync_error="shared bank account X")
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.refresh_status()
        self.assertEqual(self._entries(req), [pe], "control: paused refresh booked nothing")
        self._set_mapping(enabled=1, sync_status="OK", last_sync_error=None)
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.reload()
            req.refresh_status()
        self.assertEqual(self._entries(req), [pe], "a second Payment Entry was booked for the same payment")
        row = frappe.db.get_value("Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True)
        self.assertEqual((row.status, row.payment_entry), ("Executed", pe))

    def test_the_booking_backstop_refuses_a_conflicting_entry_if_a_race_reaches_it(self):
        """The refresh path alerts before the status moves (TestPaymentEntryConflictAlert). This calls
        ``create_payment_entry`` directly, as a race past that check would: it must still refuse to
        link or to book beside a same-Reference entry that differs.

        Probe shortcut, stated: the amount is rewritten with db.set_value on the hand-booked entry."""
        req, pe = self._hand_booked("Conflicting")
        frappe.db.set_value("Payment Entry", pe, "paid_amount", 54.0)
        with self.assertRaises(frappe.ValidationError):
            req.create_payment_entry()
        self.assertEqual(self._entries(req), [pe])
        self.assertFalse(frappe.db.get_value("Ponto Payment Request", req.name, "payment_entry"))

    def test_alert_text_says_resolve_the_pause_and_not_to_book_by_hand(self):
        self.expectErrorLog(MARKER, ALERT_TITLE)
        req = self._create_ponto_request(self._create_supplier("Text"), status="Signed", amount=12.0)
        PontoConfigurationService.pause_mapping(self.TEST_PONTO_ACCOUNT_ID, "shared bank account X")
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.refresh_status()
        text = frappe.get_all(
            "Notification Log",
            filters={"document_name": req.name, "subject": ["like", f"{MARKER}%"]},
            pluck="email_content",
        )[0]
        self.assertIn("next", text)
        self.assertIn("do not also book", text.lower())
        self.assertIn("Reference No", text)

    def test_the_row_gets_a_comment_naming_the_block(self):
        self.expectErrorLog(MARKER, ALERT_TITLE)
        req = self._create_ponto_request(self._create_supplier("Comment"), status="Signed", amount=13.0)
        PontoConfigurationService.pause_mapping(self.TEST_PONTO_ACCOUNT_ID, "shared bank account X")
        for _ in range(2):
            with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
                req.reload()
                req.refresh_status()
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": req.doctype, "reference_name": req.name, "comment_type": "Info",
                     "content": ["like", "%Ponto reports EXECUTED; blocked:%"]},
            pluck="content",
        )
        self.assertEqual(len(comments), 1, comments)
        self.assertIn("shared bank account X", comments[0])


CONFLICT_MARKER = "PONTO-PAYMENT-ENTRY-CONFLICT"
CONFLICT_TITLE = "Ponto payment executed but a Payment Entry conflicts"


class TestPaymentEntryConflictAlert(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """F2/F3 (#2125, #1848, #1931): a same-Reference Payment Entry that is not exactly the one
    this payment needs is ambiguous. Nothing is booked, the row stays as it is, and staff get ONE
    loud alert -- not two Error Log rows every hourly poll. Driven through the real
    ``refresh_status`` path; Payment Entries are real inserts/submits unless a test says otherwise."""

    AMOUNT = 66.0

    def tearDown(self):
        PontoConfigurationService.clear_cache()
        super().tearDown()

    def _make_request(self, hint, amount=None):
        return self._create_ponto_request(
            self._create_supplier(hint), status="Signed", amount=amount or self.AMOUNT, track_priority=6
        )

    def _make_payment_entry(self, req, party=None, amount=None, submit=True):
        """A real Payment Entry carrying ``req.name`` as Reference No (what staff would book by hand)."""
        from erpnext.accounts.party import get_party_account

        _, company, paid_from, party_type, req_party = req._validate_payment_entry_prerequisites()
        party = party or req_party
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.company = company
        pe.party_type = party_type
        pe.party = party
        pe.paid_from = paid_from
        pe.paid_to = get_party_account(party_type, party, company)
        pe.mode_of_payment = "Bank Transfer"
        pe.paid_from_account_currency = req.currency
        pe.paid_to_account_currency = req.currency
        pe.paid_amount = amount or req.amount
        pe.received_amount = amount or req.amount
        pe.reference_no = req.name
        pe.reference_date = frappe.utils.today()
        pe.insert()
        if submit:
            pe.submit()
        self.factory.track_document("Payment Entry", pe.name, priority=6)
        return pe

    def _poll(self, req):
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.reload()
            return req.refresh_status()

    def _row(self, req):
        return frappe.db.get_value("Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True)

    def _conflict_alerts(self, req):
        return frappe.get_all(
            "Notification Log",
            filters={
                "document_type": req.doctype,
                "document_name": req.name,
                "subject": ["like", f"{CONFLICT_MARKER}%"],
            },
            fields=["subject", "email_content", "for_user"],
        )

    def _error_logs(self):
        return frappe.db.count("Error Log", {"method": CONFLICT_TITLE, "error": ["like", f"{CONFLICT_MARKER}%"]})

    def _assert_one_alert_and_untouched(self, req, entry_names):
        self.expectErrorLog(CONFLICT_MARKER, CONFLICT_TITLE, "Payment Entry Conflict")
        errors_before = self._error_logs()
        counts = []
        for _ in range(3):
            result = self._poll(req)
            self.assertEqual(result["status"], "Signed")
            counts.append(len(self._conflict_alerts(req)))
        self.assertGreater(counts[0], 0, "staff must be alerted")
        self.assertEqual(counts, [counts[0]] * 3, "3 polls must give exactly one alert")
        self.assertLessEqual(self._error_logs() - errors_before, 1)
        self.assertEqual(self._row(req), {"status": "Signed", "payment_entry": None})
        alerts = self._conflict_alerts(req)
        self.assertEqual(len({a.for_user for a in alerts}), len(alerts), "one per recipient")
        text = alerts[0].subject + (alerts[0].email_content or "")
        self.assertIn(req.name, text)
        self.assertIn("66.00", text)
        for name in entry_names:
            self.assertIn(name, text)
        self.assertIn("Action required", text)
        self.assertEqual(
            sorted(frappe.get_all("Payment Entry", filters={"reference_no": req.name, "docstatus": ["<", 2]}, pluck="name")),
            sorted(entry_names),
            "nothing was booked beside the existing entries",
        )

    def test_a_differing_amount_alerts_once_across_three_polls(self):
        req = self._make_request("ConflictAmount")
        pe = self._make_payment_entry(req, amount=self.AMOUNT - 1)
        self._assert_one_alert_and_untouched(req, [pe.name])

    def test_a_different_party_with_the_same_amount_is_a_conflict(self):
        """F4 mutant: party check dropped -> this entry would be linked as if it were ours."""
        req = self._make_request("PartyA")
        other = self._create_supplier("PartyB")
        pe = self._make_payment_entry(req, party=other.name)
        self._assert_one_alert_and_untouched(req, [pe.name])

    def test_the_poll_entry_point_alerts_the_same_way(self):
        from verenigingen.verenigingen_payments.ponto.services.status_poll_service import _refresh_one

        req = self._make_request("ConflictPoll")
        pe = self._make_payment_entry(req, amount=self.AMOUNT - 1)
        self.expectErrorLog(CONFLICT_MARKER, CONFLICT_TITLE)
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            self.assertEqual(_refresh_one("Ponto Payment Request", req.name), "ok")
        self.assertTrue(self._conflict_alerts(req))
        self.assertIn(pe.name, self._conflict_alerts(req)[0].email_content)
        self.assertEqual(self._row(req), {"status": "Signed", "payment_entry": None})

    def test_a_draft_entry_is_a_conflict_not_a_second_booking(self):
        req = self._make_request("ConflictDraft")
        draft = self._make_payment_entry(req, submit=False)
        self.assertEqual(frappe.db.get_value("Payment Entry", draft.name, "docstatus"), 0)
        self._assert_one_alert_and_untouched(req, [draft.name])

    def test_two_submitted_entries_are_a_conflict_never_pick_first(self):
        req = self._make_request("ConflictTwo")
        first = self._make_payment_entry(req)
        second = self._make_payment_entry(req)
        self._assert_one_alert_and_untouched(req, [first.name, second.name])

    def test_a_cancelled_entry_is_ignored_and_a_new_one_is_booked(self):
        """F3 control + F4 mutant (docstatus filter dropped: the cancelled entry would be linked
        or counted as a conflict)."""
        req = self._make_request("ConflictCancelled")
        old = self._make_payment_entry(req)
        old.cancel()
        result = self._poll(req)
        self.assertEqual(result["status"], "Executed")
        row = self._row(req)
        self.assertEqual(row.status, "Executed")
        self.assertTrue(row.payment_entry)
        self.assertNotEqual(row.payment_entry, old.name)
        self.assertEqual(frappe.db.get_value("Payment Entry", row.payment_entry, "docstatus"), 1)
        self.assertEqual(self._conflict_alerts(req), [])

    def _assert_shortcut_field_is_a_conflict(self, hint, field, value):
        """Probe shortcut, stated: the submitted entry is made by the real flow and ONE field is then
        rewritten with db.set_value (a real Payment Entry of another type/company is not buildable
        on the shared test company), so the claim is about the filter, not about reachability."""
        req = self._make_request(hint)
        pe = self._make_payment_entry(req)
        frappe.db.set_value("Payment Entry", pe.name, field, value)
        self._assert_one_alert_and_untouched(req, [pe.name])

    def test_a_receive_entry_is_a_conflict(self):
        self._assert_shortcut_field_is_a_conflict("ConflictType", "payment_type", "Receive")

    def test_another_company_is_a_conflict(self):
        self._assert_shortcut_field_is_a_conflict("ConflictCompany", "company", "_Other Co")

    def test_another_paid_from_currency_is_a_conflict(self):
        self._assert_shortcut_field_is_a_conflict("ConflictCurrency", "paid_from_account_currency", "USD")

    def test_an_exact_match_is_still_linked_with_no_alert(self):
        """Control: the tightened filter must not refuse the legitimate hand-booked entry."""
        req = self._make_request("ConflictControl")
        pe = self._make_payment_entry(req)
        result = self._poll(req)
        self.assertEqual(result["status"], "Executed")
        self.assertEqual(self._row(req), {"status": "Executed", "payment_entry": pe.name})
        self.assertEqual(self._conflict_alerts(req), [])


class TestDeliveredMarkerSurvivesNotificationPruning(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """F4: the DELIVERED comment is what keeps an alert from being re-sent once its Notification
    Log rows are pruned."""

    def tearDown(self):
        PontoConfigurationService.clear_cache()
        super().tearDown()

    def test_no_redelivery_after_the_notification_logs_are_deleted(self):
        req = self._create_ponto_request(self._create_supplier("Pruned"), status="Signed", amount=31.0)
        PontoConfigurationService.pause_mapping(self.TEST_PONTO_ACCOUNT_ID, "shared bank account X")
        filters = {"document_type": req.doctype, "document_name": req.name, "subject": ["like", f"{MARKER}%"]}
        with self.assertErrorLog(ALERT_TITLE), patch(
            PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")
        ):
            req.refresh_status()
        self.assertTrue(frappe.db.count("Notification Log", filters), "control: it was delivered")
        frappe.db.delete("Notification Log", filters)
        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            req.reload()
            req.refresh_status()
        self.assertEqual(frappe.db.count("Notification Log", filters), 0, "the alert was delivered again")
