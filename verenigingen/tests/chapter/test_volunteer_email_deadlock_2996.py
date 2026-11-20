"""#2996: a deadlock (1213) must not be turned into a failure result by the volunteer email path.

``send_volunteer_email`` and every ``except Exception`` on ``EmailService``'s send path returned
a failure result for a 1213. The only callers of ``send_volunteer_email`` are the
``ChapterBoardMember`` ``after_insert`` / ``on_trash`` hooks, which discard the result, so the
request carried on and could commit a partial unit of work after the server had rolled it back.

Every error here is injected at the DRIVER: ``frappe.db._cursor.execute`` raises
``OperationalError(1213|1205, ...)`` for a query the code under test really runs, and Frappe's
own dispatch wraps it into ``QueryDeadlockError`` / ``QueryTimeoutError`` exactly as in
production. Nothing above the cursor is patched, so every swallowing layer on the path is live
(dispatch rule 17: #1703's test patched one layer above the real swallow and proved nothing).

Policy asserted for ``EmailService``: a 1213 propagates, a 1205 does NOT (it undoes only the
failed statement, the transaction is intact, and the many best-effort callers already handle a
failure result). ``send_volunteer_email`` propagates both, as #2700 prescribes.

One stub, stated plainly: ``EmailService._has_active_email_account`` is forced True in the tests
that must reach the Email Queue INSERT, so they do not depend on which Email Account the site
has. The layer is exercised for real in its own test.
"""

from contextlib import contextmanager
from unittest import mock

import frappe

from verenigingen.services.communication.email_service import EmailService
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.notification_helpers import send_volunteer_email

DEADLOCK = 1213
LOCK_TIMEOUT = 1205
ORDINARY = 1064  # a syntax error: resumable, must keep today's failure-result behaviour


@contextmanager
def _driver_error_on_2996(fragment, code, skip=0):
    """Raise ``OperationalError(code)`` at the cursor for queries (or their bound values)
    containing ``fragment``. ``skip`` lets that many matches through first, to fail MID-loop.

    A fresh exception per raise. ``state["hits"]`` proves the injected query really ran, so a
    test cannot pass because the code never reached the query."""
    cursor = frappe.db._cursor
    real_execute = cursor.execute
    state = {"hits": 0, "seen": 0}

    def execute(query, *args, **kwargs):
        if fragment in (str(query) + " " + str(args)).lower():
            state["seen"] += 1
            if state["seen"] <= skip:
                return real_execute(query, *args, **kwargs)
            state["hits"] += 1
            raise frappe.db.OperationalError(code, f"injected {code}")
        return real_execute(query, *args, **kwargs)

    with mock.patch.object(cursor, "execute", execute):
        yield state


QUEUE_INSERT = "into `tabemail queue`"
TEMPLATE_SELECT = "from `tabemail template`"
ACCOUNT_SELECT = "from `tabemail account`"
VOLUNTEER_SELECT = "from `tabvolunteer`"
SINGLES_SELECT = "from `tabsingles`"
TODO_SELECT = "from `tabtodo`"
CONFIG_READ = "verenigingen email configuration"
SETTINGS_READ = "verenigingen settings"


def _succeeded_2996(result):
    """send_volunteer_email returns a dict on develop and an OperationResult after #2984/#2995."""
    return result["success"] if isinstance(result, dict) else result.success


class TestVolunteerEmailDeadlock2996(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.template = f"t2996-{frappe.generate_hash(length=8)}"
        frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": self.template,
                "subject": "s {{ organization_name }}",
                "response": "hello",
            }
        ).insert()
        self.track_doc("Email Template", self.template)
        self.service = EmailService()  # fresh: the singleton's template cache would hide a lookup
        self.recipient = f"t2996.{frappe.generate_hash(length=8)}@test.invalid"
        account = mock.patch.object(EmailService, "_has_active_email_account", return_value=True)
        self.addCleanup(account.stop)
        self._account_stub = account

    def _assert_deadlock_2996(self, call, fragment):
        with _driver_error_on_2996(fragment, DEADLOCK) as state:
            with self.assertRaises(frappe.QueryDeadlockError) as caught:
                call()
        self.assertGreaterEqual(state["hits"], 1, "the injected query never ran")
        cause = caught.exception.__cause__
        self.assertEqual(cause.args[0], DEADLOCK, "the driver error is what reached the caller")

    def _assert_failure_result_2996(self, call, fragment, code):
        with _driver_error_on_2996(fragment, code) as state:
            result = call()
        self.assertGreaterEqual(state["hits"], 1, "the injected query never ran")
        return result

    def _send_2996(self, **options):
        return self.service.send_templated_email(
            self.template, [self.recipient], {}, bypass_cooldown=True, **options
        )

    # ------------------------------------------------------------ EmailService layers

    def test_deadlock_on_the_email_queue_insert_escapes_send_templated_email(self):
        self._account_stub.start()
        self._assert_deadlock_2996(self._send_2996, QUEUE_INSERT)

    def test_deadlock_on_the_email_queue_insert_escapes_send_simple_email(self):
        self._account_stub.start()
        self._assert_deadlock_2996(
            lambda: self.service.send_simple_email(self.recipient, "subject", "body"), QUEUE_INSERT
        )

    def test_deadlock_on_the_template_lookup_escapes_send_templated_email(self):
        self._assert_deadlock_2996(self._send_2996, TEMPLATE_SELECT)

    def test_deadlock_on_the_template_lookup_escapes_send_notification(self):
        self._assert_deadlock_2996(
            lambda: self.service.send_notification("member_approval", [self.recipient], {}),
            TEMPLATE_SELECT,
        )

    def test_deadlock_on_the_template_lookup_escapes_send_bulk_emails(self):
        batch = [{"template_name": self.template, "recipients": [self.recipient]}]
        self._assert_deadlock_2996(
            lambda: self.service.send_bulk_emails(batch, delay_between_batches=0), TEMPLATE_SELECT
        )

    def test_deadlock_on_the_email_account_check_escapes_send_templated_email(self):
        # real _has_active_email_account: the stub is not started
        self._assert_deadlock_2996(self._send_2996, ACCOUNT_SELECT)

    def test_deadlock_on_the_notification_delegation_escapes(self):
        self._assert_deadlock_2996(
            lambda: self.service._delegate_to_frappe_notification("n2996", "ToDo", "x"), TODO_SELECT
        )

    def test_deadlock_on_the_default_context_read_escapes(self):
        self._assert_deadlock_2996(self.service._get_default_context, SINGLES_SELECT)

    # ---------------------------------------------- EmailService controls (must stay failures)

    def test_an_ordinary_driver_error_on_the_queue_insert_is_still_a_failure_result(self):
        self._account_stub.start()
        result = self._assert_failure_result_2996(self._send_2996, QUEUE_INSERT, ORDINARY)
        self.assertFalse(result.success)
        self.assertIn("Failed to queue email", result.error_message)

    def test_an_ordinary_driver_error_on_the_template_lookup_is_still_a_failure_result(self):
        result = self._assert_failure_result_2996(self._send_2996, TEMPLATE_SELECT, ORDINARY)
        self.assertFalse(result.success)

    def test_a_lock_timeout_on_the_queue_insert_stays_a_failure_result(self):
        """1205 undoes only the failed statement; a best-effort send must not abort its caller.
        Pinned so that widening the EmailService clause to the whole tuple is a decision."""
        self._account_stub.start()
        result = self._assert_failure_result_2996(self._send_2996, QUEUE_INSERT, LOCK_TIMEOUT)
        self.assertFalse(result.success)

    # ------------------------------------------------------------ send_volunteer_email

    def _volunteer_2996(self):
        email = f"t2996.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(first_name="Vol", last_name="Dead", email=email, status="Active")
        volunteer = self.create_test_volunteer(member=member.name)
        return volunteer.name

    def _send_volunteer_2996(self, volunteer):
        return send_volunteer_email(
            volunteer=volunteer,
            template_name=self.template,
            notification_key="chapter_board_added",
            subject="x",
        )

    def test_deadlock_on_the_volunteer_lookup_escapes_the_helper(self):
        volunteer = self._volunteer_2996()
        self._assert_deadlock_2996(lambda: self._send_volunteer_2996(volunteer), VOLUNTEER_SELECT)

    def test_lock_timeout_on_the_volunteer_lookup_stays_a_failure_result_in_the_helper(self):
        """1205 leaves the transaction intact; not worth aborting a Chapter Board Member insert."""
        volunteer = self._volunteer_2996()
        self.expectErrorLog("Volunteer Email Error")
        result = self._assert_failure_result_2996(
            lambda: self._send_volunteer_2996(volunteer), VOLUNTEER_SELECT, LOCK_TIMEOUT
        )
        self.assertFalse(_succeeded_2996(result))

    def test_deadlock_inside_the_email_service_escapes_the_helper(self):
        """Through the real stack: helper -> get_email_service -> send path -> queue INSERT."""
        self._account_stub.start()
        volunteer = self._volunteer_2996()
        self._assert_deadlock_2996(lambda: self._send_volunteer_2996(volunteer), QUEUE_INSERT)

    def test_an_ordinary_error_on_the_volunteer_lookup_is_still_a_failure_dict(self):
        volunteer = self._volunteer_2996()
        self.expectErrorLog("Volunteer Email Error")
        result = self._assert_failure_result_2996(
            lambda: self._send_volunteer_2996(volunteer), VOLUNTEER_SELECT, ORDINARY
        )
        self.assertFalse(_succeeded_2996(result))

    # ---------------------------------------- the ChapterBoardMember hooks, real doc insert

    def _board_row_2996(self, chapter, volunteer):
        role = f"Sec2996 {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", role)
        return {
            "parent": chapter.name,
            "parenttype": "Chapter",
            "parentfield": "board_members",
            "volunteer": volunteer,
            "chapter_role": role,
            "from_date": frappe.utils.today(),
            "is_active": 1,
        }

    def _create_row_2996(self, row):
        import frappe.api.v2

        frappe.form_dict.update(row)
        try:
            return frappe.api.v2.create_doc("Chapter Board Member")
        finally:
            frappe.form_dict.clear()

    def _chapter_2996(self):
        return self.create_test_chapter(
            chapter_name=f"Row2996 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )

    def test_a_deadlock_in_the_board_added_mail_refuses_the_insert(self):
        self._account_stub.start()
        row = self._board_row_2996(self._chapter_2996(), self._volunteer_2996())
        with _driver_error_on_2996(QUEUE_INSERT, DEADLOCK) as state:
            with self.assertRaises(frappe.QueryDeadlockError):
                self._create_row_2996(row)
        self.assertGreaterEqual(state["hits"], 1, "the hook never reached the mail send")

    def test_an_ordinary_mail_failure_does_not_refuse_the_insert(self):
        """Control: best-effort mail. The hook still carries on, as before."""
        self._account_stub.start()
        row = self._board_row_2996(self._chapter_2996(), self._volunteer_2996())
        with _driver_error_on_2996(QUEUE_INSERT, ORDINARY) as state:
            created = self._create_row_2996(row)
        self.assertGreaterEqual(state["hits"], 1)
        self.assertTrue(frappe.db.exists("Chapter Board Member", created["name"] if isinstance(created, dict) else created.name))

    def test_a_deadlock_in_the_board_removed_mail_refuses_the_delete(self):
        self._account_stub.start()
        row = self._board_row_2996(self._chapter_2996(), self._volunteer_2996())
        created = self._create_row_2996(row)
        name = created["name"] if isinstance(created, dict) else created.name
        with _driver_error_on_2996(QUEUE_INSERT, DEADLOCK) as state:
            with self.assertRaises(frappe.QueryDeadlockError):
                frappe.delete_doc("Chapter Board Member", name, force=True)
        self.assertGreaterEqual(state["hits"], 1)

    # ------------------------------------------------ config reads on the send path (round 2)

    def test_deadlock_on_a_config_read_escapes_instead_of_reporting_queued(self):
        """Before: _get_config swallowed it into None, which reads as 'enabled', so the send
        returned success/queued although the transaction was gone."""
        self._account_stub.start()
        self._assert_deadlock_2996(
            lambda: self.service.send_simple_email(self.recipient, "subject", "body"), CONFIG_READ
        )

    def test_deadlock_on_the_cooldown_config_read_escapes_record_cooldown(self):
        self._assert_deadlock_2996(
            lambda: self.service._record_cooldown("chapter_board_added", [self.recipient]), CONFIG_READ
        )

    def test_deadlock_on_the_settings_read_escapes_the_constructor(self):
        self._assert_deadlock_2996(EmailService, SETTINGS_READ)

    def test_deadlock_on_the_communication_insert_escapes(self):
        self._as_administrator_2996()  # the insert goes through a permission-checked wrapper
        self._assert_deadlock_2996(
            lambda: self.service._create_communication_record([self.recipient], "s", "c"),
            "tabcommunication",
        )

    def test_an_ordinary_config_read_error_still_degrades(self):
        """Control: an ordinary error on the config read keeps the fail-open behaviour."""
        self._account_stub.start()
        with _driver_error_on_2996(CONFIG_READ, ORDINARY) as state:
            result = self.service.send_simple_email(self.recipient, "subject", "body")
        self.assertGreaterEqual(state["hits"], 1)
        self.assertTrue(result.success)

    # ---------------------------------------------- callers with their own outer handler

    def _as_administrator_2996(self):
        """The batch API's security decorators and the permission-checked Communication insert
        need a privileged session; restored on cleanup."""
        self.addCleanup(frappe.set_user, frappe.session.user)
        frappe.set_user("Administrator")

    def _fake_team_2996(self, count=3):
        members = []
        for i in range(count):
            member = self.create_test_member(
                first_name=f"Tm{i}", last_name="Dead", email=f"t2996.{frappe.generate_hash(length=8)}@test.invalid"
            )
            members.append(
                frappe._dict(is_active=1, volunteer=self.create_test_volunteer(member=member.name).name)
            )
        # Probe shortcut: a plain object, not a saved Team; the sends below are real.
        return frappe._dict(name="T-2996", team_members=members, team_lead=None)

    def test_a_mid_loop_deadlock_escapes_the_team_leadership_notification(self):
        from verenigingen.events.subscribers import team_subscribers as ts

        self._account_stub.start()
        team = self._fake_team_2996()
        with _driver_error_on_2996(QUEUE_INSERT, DEADLOCK, skip=1) as state:
            with self.assertRaises(frappe.QueryDeadlockError):
                ts._send_leadership_change_notification(team, None, None)
        self.assertGreaterEqual(state["hits"], 1, "the loop never reached a second send")

    def test_a_mid_loop_deadlock_escapes_the_team_leadership_event_handler(self):
        from verenigingen.events.subscribers import team_subscribers as ts

        self._account_stub.start()
        team = self._fake_team_2996()
        with mock.patch.object(ts, "get_doc_if_exists", return_value=team):
            with _driver_error_on_2996(QUEUE_INSERT, DEADLOCK, skip=1) as state:
                with self.assertRaises(frappe.QueryDeadlockError):
                    ts.handle_leadership_notifications("e", {"team": "T-2996"})
        self.assertGreaterEqual(state["hits"], 1)

    def test_an_ordinary_mid_loop_error_is_still_swallowed_by_the_team_notification(self):
        from verenigingen.events.subscribers import team_subscribers as ts

        self._account_stub.start()
        team = self._fake_team_2996()
        with _driver_error_on_2996(QUEUE_INSERT, ORDINARY, skip=1) as state:
            ts._send_leadership_change_notification(team, None, None)  # must not raise
        self.assertGreaterEqual(state["hits"], 1)

    def _batch_result_2996(self):
        return {
            "batches_created": 1,
            "total_invoices": 1,
            "optimization_report": {
                "summary": {},
                "batch_details": [
                    {
                        "name": f"B-{frappe.generate_hash(length=6)}",
                        "invoice_count": 1,
                        "total_amount": 1,
                        "risk_level": "Low",
                    }
                ],
            },
        }

    def _three_finance_emails_2996(self):
        return [f"f2996.{frappe.generate_hash(length=8)}@test.invalid" for _ in range(3)]

    def test_a_mid_loop_deadlock_escapes_the_batch_creation_notification(self):
        from verenigingen.verenigingen_payments.api import dd_batch_scheduler as dd

        self._account_stub.start()
        with mock.patch.object(dd, "get_financial_admin_emails", return_value=self._three_finance_emails_2996()):
            with _driver_error_on_2996(QUEUE_INSERT, DEADLOCK, skip=1) as state:
                with self.assertRaises(frappe.QueryDeadlockError):
                    dd.send_batch_creation_notification(self._batch_result_2996())
        self.assertGreaterEqual(state["hits"], 1, "the loop never reached a second send")

    def test_a_deadlock_escapes_the_whitelisted_run_batch_creation_now(self):
        """Upstream stubs, stated: batch creation and the day/holiday gates are replaced so the
        request reaches the notification; the notification and the mail send are real."""
        from verenigingen.verenigingen_payments.api import dd_batch_scheduler as dd

        self._account_stub.start()
        self._as_administrator_2996()
        with mock.patch.object(dd, "should_skip_batch_creation", return_value=False), mock.patch.object(
            dd, "is_bank_holiday", return_value=False
        ), mock.patch.object(
            dd, "create_optimal_batches", return_value={"success": True, **self._batch_result_2996()}
        ), mock.patch.object(
            dd, "get_financial_admin_emails", return_value=self._three_finance_emails_2996()
        ):
            with _driver_error_on_2996(QUEUE_INSERT, DEADLOCK, skip=1) as state:
                with self.assertRaises(frappe.QueryDeadlockError):
                    dd.run_batch_creation_now()
        self.assertGreaterEqual(state["hits"], 1)

    # ------------------------------------------------ round 3 (#2996): sibling swallowers

    def test_a_deadlock_on_the_recipient_lookup_escapes_the_batch_notification(self):
        """get_financial_admin_emails is REAL here (the tests above patch it). Before: its generic
        handler turned a 1213 into [], send_batch_creation_notification then returned None quietly
        and run_batch_creation_now reported success over a rolled-back transaction."""
        from verenigingen.verenigingen_payments.api import dd_batch_scheduler as dd

        with _driver_error_on_2996("from `tabhas role`", DEADLOCK) as state:
            with self.assertRaises(frappe.QueryDeadlockError):
                dd.send_batch_creation_notification(self._batch_result_2996())
        self.assertGreaterEqual(state["hits"], 1, "the recipient lookup never ran its role read")

    def test_an_ordinary_error_on_the_recipient_lookup_still_degrades_to_no_recipients(self):
        """Control: the generic handler is intact for every other error."""
        from verenigingen.verenigingen_payments.api import sepa_batch_notifications as sbn

        self.expectErrorLog("sepa_batch_scheduler_alert")
        with _driver_error_on_2996("from `tabhas role`", ORDINARY) as state:
            self.assertEqual(sbn.get_financial_admin_emails("sepa_batch_scheduler_alert"), [])
        self.assertGreaterEqual(state["hits"], 1)

    def _delegating_config_service_2996(self):
        from verenigingen.services.communication.email_configuration_service import (
            EmailConfigurationService,
        )

        service = EmailConfigurationService()
        # Probe shortcut: the two in-memory config reads are stubbed so the Notification read runs;
        # that read itself is real.
        service._get_config = lambda: frappe._dict(use_frappe_notifications=1)
        service.get_notification_config = lambda key: {"frappe_notification": "N2996-missing"}
        return service

    def test_a_deadlock_on_the_linked_notification_read_escapes(self):
        service = self._delegating_config_service_2996()
        self._assert_deadlock_2996(lambda: service.get_frappe_notification_for("k"), "from `tabnotification`")

    def test_an_ordinary_error_on_the_linked_notification_read_means_send_directly(self):
        service = self._delegating_config_service_2996()
        result = self._assert_failure_result_2996(
            lambda: service.get_frappe_notification_for("k"), "from `tabnotification`", ORDINARY
        )
        self.assertIsNone(result)

    def test_a_deadlock_on_the_leadership_user_read_escapes(self):
        from verenigingen.events.subscribers import team_subscribers as ts

        self._account_stub.start()
        team = self._fake_team_2996(count=1)
        old_lead = "t2996-old@test.invalid"
        self._assert_deadlock_2996(
            lambda: ts._send_leadership_change_notification(team, old_lead, None), old_lead
        )

    def test_a_deadlock_on_the_new_leadership_user_read_escapes(self):
        """The new lead's User read has its own re-raise; pin it separately from the old lead's."""
        from verenigingen.events.subscribers import team_subscribers as ts

        self._account_stub.start()
        team = self._fake_team_2996(count=1)
        new_lead = "t2996-new@test.invalid"
        self._assert_deadlock_2996(
            lambda: ts._send_leadership_change_notification(team, None, new_lead), new_lead
        )

    def test_a_missing_leadership_user_is_still_tolerated(self):
        """Control: the user does not exist (DoesNotExistError), the notification still goes out."""
        from verenigingen.events.subscribers import team_subscribers as ts

        self._account_stub.start()
        team = self._fake_team_2996(count=1)
        ts._send_leadership_change_notification(team, "t2996-old@test.invalid", "t2996-new@test.invalid")
