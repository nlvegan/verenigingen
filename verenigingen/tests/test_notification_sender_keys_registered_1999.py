"""Every notification key a sender can pass is in the registry (#1999).

A key that is not in ``notification_registry.NOTIFICATION_KEYS`` is never seeded into
Verenigingen Email Configuration (#1959/#1998), so ``is_notification_enabled`` is False and
``EmailService._send_internal`` returns ``skipped`` - the mail is dropped silently. The keys that
slipped through arrive through variables and dict maps, which a grep for ``notification_key="..."``
(and ``discover_notification_keys``) cannot see, so this walks the AST of every non-test module.

What counts as a sender key:
  * a literal ``notification_key=`` keyword;
  * a literal VALUE of a dict (or a ``.get`` default) assigned to a name containing
    ``notification_key`` (the map keys are template/type names, not keys), plus the deprecated
    ``key_mapping`` in email_service.py (the name alone is too generic: utils/email_addresses.py
    has a ``key_mapping`` of test e-mail addresses);
  * a literal ``"notification_key": "<k>"`` dict entry or ``.get("notification_key", "<k>")`` default.

Two keys sit only in the deprecated ``EmailService.send_notification`` map and no caller passes
their notification types, so they are unreachable and deliberately not registered
(``UNREACHABLE``); ``test_the_unreachable_keys_really_are_unreachable`` keeps that honest.
"""

import ast
import os
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.hooks.lifecycle import after_install
from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.services.communication.email_service import EmailService
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.utils.test_config import disable_test_email_mocking, enable_test_email_mocking

DOCTYPE = "Verenigingen Email Configuration"
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# deprecated send_notification map entries whose notification_type no caller passes
UNREACHABLE = {"sepa_mandate_created": "sepa_mandate_created", "board_member_added": "board_member_added"}


def _source_files():
    for root, dirs, files in os.walk(APP_ROOT):
        dirs[:] = [d for d in dirs if d not in ("tests", "patches", "__pycache__", "node_modules")]
        for name in files:
            if name.endswith(".py") and not name.startswith("test_"):
                yield os.path.join(root, name)


def _str_values(node):
    return [n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _map_values(node):
    """Constant string values of a dict literal, or the default of ``x.get(k, "default")``."""
    if isinstance(node, ast.Dict):
        return [c for v in node.values for c in _str_values(v)]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return [c for a in node.args[1:] for c in _str_values(a)]
    return []


def sender_keys():
    """{key: ["relative/path.py:line", ...]} for every key a sender can pass."""
    found = {}

    def add(const, path):
        found.setdefault(const.value, []).append(f"{os.path.relpath(path, APP_ROOT)}:{const.lineno}")

    for path in _source_files():
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "notification_key":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    add(node.value, path)
            elif isinstance(node, ast.Assign):
                names = " ".join(ast.unparse(t) for t in node.targets)
                relpath = os.path.relpath(path, APP_ROOT)
                if "notification_key" in names or (
                    names == "key_mapping" and relpath == "services/communication/email_service.py"
                ):
                    for const in _map_values(node.value):
                        add(const, path)
            elif isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "notification_key":
                        for const in _str_values(v):
                            add(const, path)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "notification_key"
            ):
                for const in _map_values(node):
                    add(const, path)
    return found


class TestSenderKeysAreRegistered(FrappeTestCase):
    def test_every_key_a_sender_passes_is_registered(self):
        found = sender_keys()
        unregistered = {
            k: v for k, v in found.items() if k not in NOTIFICATION_KEYS and k not in UNREACHABLE
        }
        self.assertEqual(
            unregistered,
            {},
            "These notification keys are passed to a sender but are not in notification_registry.py, "
            "so EmailService skips the mail as 'disabled' (key -> senders): " + repr(unregistered),
        )

    def test_the_census_sees_literals_variables_and_dict_map_values(self):
        # control: a scan that finds nothing would pass the test above vacuously
        found = sender_keys()
        self.assertIn("member_activated", found, "literal keyword value")
        self.assertIn("payment_failure_first", found, "dict-map value (payment_webhook)")
        self.assertIn("subscription_suspended", found, "dict-map value (mollie sync)")
        self.assertIn("payment_reminder_friendly", found, ".get default / map value (payment_processing)")
        self.assertIn("chapter_membership_approved", found, "deprecated key_mapping value")
        self.assertIn("sepa_member_pre_notification", found, ".get('notification_key', default)")
        self.assertNotIn("Friendly Reminder", found, "map KEYS are not notification keys")
        self.assertGreater(len(found), 60)

    def test_the_unreachable_keys_really_are_unreachable(self):
        # They are only values of EmailService.send_notification's key_mapping; they stay
        # unregistered only while no caller passes those notification types.
        self.assertTrue(set(UNREACHABLE) <= set(sender_keys()), "control: the census still sees them")
        offenders = []
        for path in _source_files():
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "notification_type":
                    if isinstance(node.value, ast.Constant) and node.value.value in UNREACHABLE:
                        offenders.append(f"{os.path.relpath(path, APP_ROOT)}:{node.value.lineno}")
        self.assertEqual(offenders, [], "a caller now reaches an unregistered key: register it")


class TestUnregisteredKeyWarningIsTruthful(FrappeTestCase):
    def test_warning_does_not_promise_the_mail_is_sent(self):
        warnings = []

        class _RecordingLogger:
            def warning(self, message, *args, **kwargs):
                warnings.append(message)

        service = EmailService()
        service.logger = _RecordingLogger()  # records only; the code under test is unchanged
        self.assertFalse(service._validate_notification_key("not_a_registered_key_1999"))
        self.assertEqual(len(warnings), 1, "control: an unregistered key is warned about")
        self.assertNotIn("will still be sent", warnings[0])
        self.assertIn("skipped", warnings[0])


class TestNewlyRegisteredKeysAreSent(FrappeTestCase):
    """Behaviour: on a site seeded the way #1998 seeds it, the mail is queued, not skipped."""

    def _seed(self):
        handler = next(h for h in after_install if h.endswith("ensure_notification_registry_rows"))
        config = frappe.get_single(DOCTYPE)
        config.notification_types = []
        config.save()  # the fresh-install state: no rows (probe shortcut, as in the #1959 test)
        frappe.get_attr(handler)()

    def _send(self, key, recipient):
        return EmailService()._send_email_internal(
            recipients=[recipient], subject="s", content="c", notification_key=key
        )

    def _queued(self, recipient):
        return frappe.db.count("Email Queue Recipient", {"recipient": recipient})

    def _unique_recipient(self, label):
        # the per-recipient cooldown lives in Redis and survives a rollback: never reuse an address
        return f"{label}-{uuid.uuid4().hex[:8]}@example.com"

    def test_payment_failure_first_is_queued_on_a_seeded_site(self):
        control, target = self._unique_recipient("control"), self._unique_recipient("failure-first")
        # the harness replaces frappe.sendmail process-wide, so no Email Queue row could appear
        disable_test_email_mocking()
        self.addCleanup(enable_test_email_mocking)
        with singleton_backup(DOCTYPE):
            self._seed()
            control_result = self._send("member_activated", control)
            self.assertFalse((control_result.data or {}).get("skipped"), control_result)
            self.assertEqual(self._queued(control), 1, "control: a registered key is queued")

            result = self._send("payment_failure_first", target)
            self.assertFalse((result.data or {}).get("skipped"), result)
            self.assertEqual(self._queued(target), 1)

    def test_every_newly_registered_key_is_seeded_enabled(self):
        newly = (
            "payment_failure_first payment_failure_second payment_failure payment_reminder_friendly "
            "subscription_cancelled subscription_suspended chapter_membership_approved"
        ).split()
        with singleton_backup(DOCTYPE):
            self._seed()
            rows = {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}
            for key in newly:
                self.assertIn(key, rows, key)
                self.assertEqual(cint(rows[key].enabled), 1, key)
