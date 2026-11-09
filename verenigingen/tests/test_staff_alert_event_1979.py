"""Staff Alert Event: record + write-ahead for ``notify_administrators`` staff alerts (#1979 phase 1).

Real flow: every test drives ``notify_administrators(staff_alert=True, ...)`` against real Verenigingen
Email Configuration rows, real Users and real Notification Logs. The UNSEEDED state is built the way
the #1959 tests build it (``singleton_backup`` + an emptied ``notification_types``), because
"unregistered" and "unseeded" are different outcomes.

``recipient_count`` is always compared with a count taken from the Notification Log rows, never a
literal. The event table is MyISAM, so its rows survive rollback: every test removes its own rows in
``tearDown`` instead of relying on rollback (ruling 5).

Two documented shortcuts, both inserting a Notification Log row directly because the real flow cannot
create it: ``test_a_log_row_for_administrator_does_not_count_as_reached`` (``create_system_notification``
drops Administrator, so the row can only be inserted directly) and
``test_a_disabled_users_log_row_is_not_counted`` (it never creates one for a disabled user).
"""

import ast
import pathlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint, now_datetime

from verenigingen.notification_registry import NOTIFICATION_KEYS, REQUIRES_ACTION_KEYS
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.utils import staff_alert_events
from verenigingen.utils.notification_helpers import notify_administrators

EVENT = "Staff Alert Event"
CONFIG = "Verenigingen Email Configuration"
SEEDED_KEY = "ponto_executed_on_cancelled_row"  # registered, requires_action
INFO_KEY = "chapter_board_removed"  # registered, informational
NEVER_REGISTERED = "zz_unregistered_1979"
NO_REFERENCE_KEY = "zz_noref_1979"
APP_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _config_row(key, policy="Fixed", fixed="", roles="", enabled=1):
    return {
        "notification_key": key,
        "label": key,
        "category": "Admin",
        "recipient_policy": policy,
        "fixed_recipients": fixed,
        "recipient_roles": roles,
        "enabled": enabled,
    }


def _set_config_rows(rows):
    config = frappe.get_single(CONFIG)
    config.notification_types = []
    for row in rows:
        config.append("notification_types", row)
    config.save()


def _events_for(reference_name):
    return frappe.get_all(
        EVENT,
        filters={"reference_name": reference_name},
        fields=["name", "outcome", "attempts", "recipient_count", "delivered_at", "requires_action"],
    )


def _log_users(event):
    return frappe.get_all(
        "Notification Log", filters={"source_doctype": EVENT, "source_name": event}, pluck="for_user"
    )


class TestStaffAlertEvent(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._notes = []
        self._users = []
        # Entered here and left LAST in tearDown: its restore commits, which is what makes the deletions
        # below stick (a bare commit is gated). Without it each test leaks its Note and User.
        self._config_backup = singleton_backup(CONFIG)
        self._config_backup.__enter__()

    def tearDown(self):
        for note in self._notes:
            for event in frappe.get_all(EVENT, filters={"reference_name": note}, pluck="name"):
                frappe.db.delete("Notification Log", {"source_doctype": EVENT, "source_name": event})
                frappe.delete_doc(EVENT, event, force=True)
            frappe.delete_doc("Note", note, force=True)
        for event in frappe.get_all(EVENT, filters={"notification_key": NO_REFERENCE_KEY}, pluck="name"):
            frappe.delete_doc(EVENT, event, force=True)
        for user in self._users:
            frappe.db.delete("Notification Log", {"for_user": user})
            frappe.delete_doc("User", user, force=True)
        frappe.db.delete("Error Log", {"method": ["like", "Staff Alert Event could not be recorded%"]})
        self._config_backup.__exit__(None, None, None)
        super().tearDown()

    # ---- fixtures -------------------------------------------------------------------------------
    def _note(self):
        note = frappe.get_doc(
            {"doctype": "Note", "title": f"T1979 {frappe.generate_hash(length=8)}", "public": 0}
        ).insert()
        self._notes.append(note.name)
        return note.name

    def _make_alert_recipient(self, enabled=1):
        email = f"staff1979-{frappe.generate_hash(length=6)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Staff1979",
                "enabled": enabled,
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()
        self._users.append(user.name)
        return user.name

    def _alert(self, key, note, **kwargs):
        kwargs.setdefault("staff_alert", True)
        return notify_administrators(
            subject=f"alert {note}",
            message="<p>m</p>",
            notification_key=key,
            document_type="Note",
            document_name=note,
            **kwargs,
        )

    def _only_event(self, note):
        events = _events_for(note)
        self.assertEqual(len(events), 1, events)
        return frappe._dict(events[0])

    # ---- outcomes -------------------------------------------------------------------------------
    def test_unseeded_key_is_recorded_as_not_seeded(self):
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            before = frappe.db.count("Notification Log")
            result = self._alert(SEEDED_KEY, note)
            self.assertTrue(result.get("skipped"), "control: an unseeded key is dropped")
            self.assertEqual(frappe.db.count("Notification Log"), before)
        event = self._only_event(note)
        self.assertEqual(event.outcome, "Skipped - key not seeded")
        self.assertEqual(event.recipient_count, 0)
        self.assertIsNone(event.delivered_at)
        self.assertEqual(cint(event.requires_action), 1)

    def test_a_key_missing_from_the_registry_is_a_different_outcome_from_unseeded(self):
        self.assertNotIn(NEVER_REGISTERED, NOTIFICATION_KEYS)
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            self._alert(NEVER_REGISTERED, note)
        self.assertEqual(self._only_event(note).outcome, "Skipped - key not in registry")

    def test_a_disabled_key_is_recorded_as_disabled(self):
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=self._make_alert_recipient(), enabled=0)])
            self._alert(SEEDED_KEY, note)
        self.assertEqual(self._only_event(note).outcome, "Skipped - key disabled")

    def test_email_switched_off_globally_is_recorded(self):
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=self._make_alert_recipient())])
            config = frappe.get_single(CONFIG)
            config.master_email_enabled = 0
            config.save()
            self._alert(SEEDED_KEY, note)
        self.assertEqual(self._only_event(note).outcome, "Skipped - email off")

    def test_delivery_is_recorded_and_the_count_comes_from_the_notification_log(self):
        note = self._note()
        user = self._make_alert_recipient()
        bystander = self._make_alert_recipient()
        # An unrelated Notification Log for ANOTHER enabled user on the same document, no source: a join
        # on the document instead of on source_name would count it as reached.
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": "unrelated",
                "for_user": bystander,
                "type": "Alert",
                "document_type": "Note",
                "document_name": note,
            }
        ).insert()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            result = self._alert(SEEDED_KEY, note)
        event = self._only_event(note)
        logged = _log_users(event.name)
        self.assertEqual(logged, [user], "control: the log row exists and joins on source_name")
        self.assertEqual(result["notifications_created"], len(logged))
        self.assertEqual(event.outcome, "Delivered")
        self.assertEqual(event.recipient_count, len(set(logged)))
        self.assertIsNotNone(event.delivered_at)

    def test_no_recipient_left_is_recorded(self):
        note = self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            self._alert(SEEDED_KEY, note, exclude_users=[user])
        event = self._only_event(note)
        self.assertEqual(event.outcome, "No recipient")
        self.assertEqual(frappe.db.count("Notification Log", {"source_name": event.name}), 0)

    def test_a_log_row_for_administrator_does_not_count_as_reached(self):
        """Probe shortcut: the row is inserted directly, because ``create_system_notification`` cannot
        create one for Administrator (it drops that user, #1958), so the "row exists" case needs a
        direct insert; the next test is the real flow."""
        note = self._note()
        event = staff_alert_events.begin_event(SEEDED_KEY, "s", "direct", "Note", note)
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": "s",
                "for_user": "Administrator",
                "type": "Alert",
                "source_doctype": EVENT,
                "source_name": event,
            }
        ).insert()
        self.assertEqual(_log_users(event), ["Administrator"], "control: the row exists and joins")
        staff_alert_events.finish_event(event, {"success": True, "notifications_created": 1})
        row = self._only_event(note)
        self.assertEqual((row.outcome, row.recipient_count), ("No counted recipient", 0))
        self.assertIsNone(row.delivered_at)

    def test_an_alert_addressed_only_to_administrator_is_recorded_as_not_delivered(self):
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed="Administrator")])
            result = self._alert(SEEDED_KEY, note)
        # Since #1958 + the Administrator ruling the helper drops Administrator: no row, no error.
        self.assertFalse(result.get("notifications_created"), "control: nothing was created")
        event = self._only_event(note)
        self.assertEqual(_log_users(event.name), [], "control: no log joins the event")
        self.assertEqual((event.outcome, event.recipient_count), ("No recipient", 0))

    def test_a_user_configured_as_not_counting_is_not_reached_and_the_same_user_otherwise_is(self):
        note_a, note_b = self._note(), self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            self._alert(SEEDED_KEY, note_a)
            config = frappe.get_single(CONFIG)
            config.staff_alert_uncounted_users = f"someone@example.org, {user.upper()}"
            config.save()
            self._alert(SEEDED_KEY, note_b)
        self.assertEqual(self._only_event(note_a).outcome, "Delivered")
        configured = self._only_event(note_b)
        self.assertEqual(_log_users(configured.name), [user], "control: the log row exists")
        self.assertEqual((configured.outcome, configured.recipient_count), ("No counted recipient", 0))

    def test_a_disabled_users_log_row_is_not_counted(self):
        """Probe shortcut: the Notification Log row is inserted directly (see module docstring)."""
        note = self._note()
        user = self._make_alert_recipient(enabled=0)
        event = staff_alert_events.begin_event(SEEDED_KEY, "s", "direct", "Note", note)
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": "s",
                "for_user": user,
                "type": "Alert",
                "source_doctype": EVENT,
                "source_name": event,
            }
        ).insert()
        self.assertEqual(len(_log_users(event)), 1, "control: the row exists")
        self.assertEqual(staff_alert_events.count_reached(event), 0)

    # ---- dedupe ---------------------------------------------------------------------------------
    def test_the_same_problem_twice_is_one_event_and_a_late_seed_turns_it_delivered(self):
        note = self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            self._alert(SEEDED_KEY, note)
            first = self._only_event(note)
            self.assertEqual((first.outcome, first.attempts), ("Skipped - key not seeded", 1))
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            self._alert(SEEDED_KEY, note)
        event = self._only_event(note)
        self.assertEqual(event.name, first.name)
        self.assertEqual(event.attempts, 2)
        self.assertEqual(event.outcome, "Delivered")
        self.assertEqual(event.recipient_count, len(set(_log_users(event.name))))
        self.assertIsNotNone(event.delivered_at)

    def test_a_different_reference_is_a_different_event(self):
        note_a, note_b = self._note(), self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            self._alert(SEEDED_KEY, note_a)
            self._alert(SEEDED_KEY, note_b)
        self.assertNotEqual(self._only_event(note_a).name, self._only_event(note_b).name)

    def test_alerts_without_a_reference_are_always_new_events(self):
        with singleton_backup(CONFIG):
            _set_config_rows([])
            for _ in range(2):
                notify_administrators(
                    subject="s", message="m", notification_key=NO_REFERENCE_KEY, staff_alert=True
                )
        self.assertEqual(frappe.db.count(EVENT, {"notification_key": NO_REFERENCE_KEY}), 2)

    def test_a_problem_marked_done_that_comes_back_is_open_again(self):
        """Probe shortcut: ``action_status`` is set to Done with ``db.set_value``, because no UI or flow
        sets it yet (the manual field and the Ponto resolver come in a later phase)."""
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            self._alert(SEEDED_KEY, note)
            event = self._only_event(note)
            frappe.db.set_value(
                EVENT,
                event.name,
                {"action_status": "Done", "action_done_by": "Administrator", "action_done_at": now_datetime()},
                update_modified=False,
            )
            self._alert(SEEDED_KEY, note)
        row = frappe.db.get_value(
            EVENT, event.name, ["action_status", "action_done_by", "action_done_at"], as_dict=True
        )
        self.assertEqual(row.action_status, "Open")
        self.assertIsNone(row.action_done_by, "a reopened problem is not 'done by' anyone")
        self.assertIsNone(row.action_done_at)

    def test_a_problem_marked_not_needed_stays_not_needed_when_it_comes_back(self):
        """Probe shortcut as above. Control for the reopen rule: only Done is reopened."""
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            self._alert(SEEDED_KEY, note)
            event = self._only_event(note)
            frappe.db.set_value(EVENT, event.name, "action_status", "Not needed", update_modified=False)
            self._alert(SEEDED_KEY, note)
        self.assertEqual(frappe.db.get_value(EVENT, event.name, "action_status"), "Not needed")
        self.assertEqual(frappe.db.get_value(EVENT, event.name, "attempts"), 2, "control: it did recur")

    # ---- the outcome is the LATEST attempt's (F1) ------------------------------------------------
    def test_a_recurrence_that_reaches_nobody_is_not_reported_delivered(self):
        note = self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            self._alert(SEEDED_KEY, note)
            first = self._only_event(note)
            self.assertEqual(first.outcome, "Delivered", "control: attempt 1 delivered")
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user, enabled=0)])
            self._alert(SEEDED_KEY, note)
        event = self._only_event(note)
        detail = frappe.db.get_value(EVENT, event.name, "detail")
        self.assertEqual(event.attempts, 2)
        self.assertEqual(event.outcome, "Skipped - key disabled")
        self.assertEqual(event.recipient_count, 0, "recipients reached by the LATEST attempt")
        self.assertIn("disabled", detail)
        self.assertEqual(event.delivered_at, first.delivered_at, "the history of the first delivery is kept")
        self.assertEqual(len(_log_users(event.name)), 1, "control: the first attempt's log row still exists")

    def test_a_recurrence_that_delivers_again_is_delivered(self):
        note = self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            self._alert(SEEDED_KEY, note)
            self._alert(SEEDED_KEY, note)
        event = self._only_event(note)
        self.assertEqual((event.outcome, event.attempts, event.recipient_count), ("Delivered", 2, 1))
        self.assertEqual(len(_log_users(event.name)), 2, "control: two log rows, one per attempt")

    def test_when_the_exclusion_list_cannot_be_read_the_event_is_not_reported_delivered(self):
        """Fail closed: an error reading ``staff_alert_uncounted_users`` leaves the event Pending."""
        note = self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            # Mock justified: failure injection for the config read.
            with patch.object(frappe.db, "get_single_value", side_effect=OSError("boom-config")):
                self._alert(SEEDED_KEY, note)
        event = self._only_event(note)
        self.assertEqual(len(_log_users(event.name)), 1, "control: the alert itself was delivered")
        self.assertEqual(event.outcome, "Pending")
        self.assertTrue(
            frappe.get_all(
                "Error Log", filters={"method": "Staff Alert Event could not be recorded (finish)"}, limit=1
            )
        )

    # ---- classification flags -------------------------------------------------------------------
    def test_an_informational_key_is_recorded_without_requiring_action_and_the_call_can_override(self):
        note_a, note_b = self._note(), self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            self._alert(INFO_KEY, note_a)
            self._alert(INFO_KEY, note_b, requires_action=True)
        a, b = self._only_event(note_a), self._only_event(note_b)
        self.assertEqual((cint(a.requires_action), cint(b.requires_action)), (0, 1))
        self.assertEqual(
            frappe.db.get_value(EVENT, a.name, "action_status") or "", "", "informational: no action status"
        )

    def test_a_call_that_is_not_marked_as_a_staff_alert_records_nothing(self):
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([])
            result = self._alert(SEEDED_KEY, note, staff_alert=False)
        self.assertTrue(result.get("skipped"), "control: the alert still ran and was dropped")
        self.assertEqual(_events_for(note), [])

    def test_registry_requires_action_set_names_only_registered_keys(self):
        self.assertFalse(REQUIRES_ACTION_KEYS - set(NOTIFICATION_KEYS))
        never_sent = {
            "security_alert",
            "member_application_overdue",
            "payment_history_critical_error",
            "payment_history_failure_alert",
        }
        self.assertFalse(REQUIRES_ACTION_KEYS & never_sent)
        self.assertIn("payment_plan_request", REQUIRES_ACTION_KEYS)
        self.assertNotIn("sepa_batch_warning", REQUIRES_ACTION_KEYS)

    def test_the_notify_administrators_keys_are_marked_staff_alert_at_the_call_site(self):
        marked = {}
        for path in APP_ROOT.rglob("*.py"):
            if "tests" in path.parts or "node_modules" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "notify_administrators"):
                    continue
                kwargs = {k.arg: k.value for k in node.keywords if k.arg}
                key = kwargs.get("notification_key")
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    flag = kwargs.get("staff_alert")
                    marked.setdefault(key.value, []).append(isinstance(flag, ast.Constant) and flag.value is True)
        # The control lists every key the census must find; dues_schedule_creation_failed (#2107) and
        # mijnrood_disabled_default_type (#2094) are literal-key call sites, and the loop below still demands it is marked staff_alert=True.
        self.assertEqual(
            set(marked),
            {
                SEEDED_KEY,
                "termination_overdue",
                INFO_KEY,
                "dues_schedule_creation_failed",
                "mijnrood_disabled_default_type",
                "mijnrood_chapter_move_failed",
            },
            "control: every literal-key call site was found",
        )
        for key, flags in marked.items():
            self.assertTrue(all(flags), f"{key}: a call site is not marked staff_alert=True ({flags})")

    # ---- write-ahead and rollback ---------------------------------------------------------------
    def test_the_event_survives_a_rollback_and_the_notification_log_does_not(self):
        note = self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            frappe.db.savepoint("t1979_alert")  # the Note, User and config are before it: only the alert is undone
            self._alert(SEEDED_KEY, note)
            event = self._only_event(note)
            self.assertEqual(len(_log_users(event.name)), 1, "control: delivered before the rollback")
            frappe.db.rollback(save_point="t1979_alert")
        self.assertEqual(
            _log_users(event.name), [], "control: the InnoDB Notification Log row is gone after rollback"
        )
        survivor = frappe.db.get_value(EVENT, event.name, ["outcome", "recipient_count"], as_dict=True)
        self.assertIsNotNone(survivor, "the MyISAM event survives the caller's rollback")
        self.assertEqual(survivor.outcome, "Delivered", "documented false 'Delivered': see the design, 4c")

    def test_the_event_table_is_myisam(self):
        engine = frappe.db.sql(
            "SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            ("tab" + EVENT,),
        )
        self.assertEqual(engine[0][0], "MyISAM")

    def test_a_send_that_raises_still_leaves_a_failed_event(self):
        """A send whose recipient lookup raises still leaves a Failed event (write-ahead).

        This used a Role-Based row with NULL ``recipient_roles`` (``None.split``) to make the lookup
        raise; #1997 (PR #2031) fixed that crash, so the failure is now injected at the same boundary.
        """
        note = self._note()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, policy="Role-Based", roles="x")])
            frappe.db.savepoint("t1979_raise")
            # Mock justified: failure injection at the recipient-lookup boundary the real crash came from.
            with patch(
                "verenigingen.services.communication.email_configuration_service."
                "EmailConfigurationService.get_recipients_for_notification",
                side_effect=AttributeError("injected lookup failure"),
            ):
                with self.assertRaises(AttributeError):
                    self._alert(SEEDED_KEY, note)
            frappe.db.rollback(save_point="t1979_raise")
        event = frappe.db.get_value(EVENT, {"reference_name": note}, ["outcome", "detail"], as_dict=True)
        self.assertIsNotNone(event, "the write-ahead row is there although the send raised and rolled back")
        self.assertEqual(event.outcome, "Failed")
        self.assertIn("AttributeError", event.detail)

    # ---- recording must never change the alert --------------------------------------------------
    def test_a_recorder_failure_changes_nothing_about_the_alert(self):
        note_a, note_b = self._note(), self._note()
        user = self._make_alert_recipient()
        with singleton_backup(CONFIG):
            _set_config_rows([_config_row(SEEDED_KEY, fixed=user)])
            plain = self._alert(SEEDED_KEY, note_a, staff_alert=False)
            # Mock justified: failure injection at the recorder boundary (both halves of it).
            with patch.object(staff_alert_events, "_dedupe_key", side_effect=OSError("boom-begin")):
                begin_failed = self._alert(SEEDED_KEY, note_b)
            self.assertEqual(begin_failed, plain)
            self.assertEqual(_events_for(note_b), [])
            with patch.object(staff_alert_events, "count_reached", side_effect=OSError("boom-finish")):
                finish_failed = self._alert(SEEDED_KEY, note_b)
            self.assertEqual(finish_failed, plain)
        self.assertEqual(self._only_event(note_b).outcome, "Pending", "a finish that fails leaves Pending")
        titles = frappe.get_all(
            "Error Log", filters={"method": ["like", "Staff Alert Event could not be recorded%"]}, pluck="method"
        )
        self.assertEqual(sorted(titles), [
            "Staff Alert Event could not be recorded (begin)",
            "Staff Alert Event could not be recorded (finish)",
        ])
