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
def _driver_error_on_2996(fragment, code):
    """Raise ``OperationalError(code)`` at the cursor for queries containing ``fragment``.

    A fresh exception per raise. ``state["hits"]`` proves the injected query really ran, so a
    test cannot pass because the code never reached the query."""
    cursor = frappe.db._cursor
    real_execute = cursor.execute
    state = {"hits": 0}

    def execute(query, *args, **kwargs):
        if fragment in str(query).lower():
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

    def test_lock_timeout_on_the_volunteer_lookup_escapes_the_helper(self):
        volunteer = self._volunteer_2996()
        with _driver_error_on_2996(VOLUNTEER_SELECT, LOCK_TIMEOUT) as state:
            with self.assertRaises(frappe.QueryTimeoutError):
                self._send_volunteer_2996(volunteer)
        self.assertGreaterEqual(state["hits"], 1)

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
        self.assertFalse(result["success"])

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
