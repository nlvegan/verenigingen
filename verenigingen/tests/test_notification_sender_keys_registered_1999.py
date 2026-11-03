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

Limits (a key passed in a shape below is NOT seen, and nothing here can prove there are none): a
positional key argument, a map under a name that does not contain ``notification_key`` (other than
the one named ``key_mapping`` in email_service.py), a subscript ``MAP[t]`` or conditional
expression feeding ``notification_key=``. ``_unresolved`` closes the keyword half of that gap: it
FAILS on any ``notification_key=<non-constant>`` that is not a parameter pass-through, a local
assigned from a map the walker reads, ``x["notification_key"]`` or ``x.get("notification_key", d)``.
Today it finds none, so there is no allow-list. A map or positional passing that never reaches a
``notification_key=`` keyword is outside the scan.

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


def _tree_keys(tree, relpath):
    """[(key, lineno)] for every constant sender key in one parsed module."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "notification_key":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found.append((node.value.value, node.value.lineno))
        elif isinstance(node, ast.Assign):
            names = " ".join(ast.unparse(t) for t in node.targets)
            if "notification_key" in names or (
                names == "key_mapping" and relpath == "services/communication/email_service.py"
            ):
                found.extend((c.value, c.lineno) for c in _map_values(node.value))
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "notification_key":
                    found.extend((c.value, c.lineno) for c in _str_values(v))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "notification_key"
        ):
            found.extend((c.value, c.lineno) for c in _map_values(node))
    return found


def _is_resolved(value, func):
    """True if a non-constant ``notification_key=<value>`` is one the walker already follows."""
    if isinstance(value, ast.Subscript):
        return ast.unparse(value.slice) in ("'notification_key'", '"notification_key"')
    if isinstance(value, ast.Call):
        return (
            isinstance(value.func, ast.Attribute)
            and value.func.attr == "get"
            and bool(value.args)
            and isinstance(value.args[0], ast.Constant)
            and value.args[0].value == "notification_key"
        )
    if isinstance(value, ast.Name) and func is not None:
        params = {a.arg for a in func.args.args + func.args.kwonlyargs}
        if value.id in params:
            return True  # pass-through: the callers' own arguments are scanned
        for node in ast.walk(func):  # a local assigned from a map the walker reads
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == value.id for t in node.targets
            ):
                return "notification_key" in value.id and isinstance(node.value, (ast.Dict, ast.Call))
    return False


def _unresolved(tree):
    """[lineno] of ``notification_key=<non-constant>`` whose possible values the walker cannot follow."""
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "notification_key":
            if isinstance(node.value, ast.Constant):
                continue
            func = node
            while func is not None and not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = parents.get(func)
            if not _is_resolved(node.value, func):
                bad.append(node.value.lineno)
    return bad


def _unregistered(found, registry, unreachable=()):
    """The part of ``{key: [sites]}`` that a sender passes but ``registry`` lacks."""
    return {k: v for k, v in found.items() if k not in registry and k not in unreachable}


def _parsed_sources():
    for path in _source_files():
        try:
            yield os.path.relpath(path, APP_ROOT), ast.parse(open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError):
            continue


def sender_keys():
    """{key: ["relative/path.py:line", ...]} for every key a sender can pass."""
    found = {}
    for relpath, tree in _parsed_sources():
        for key, lineno in _tree_keys(tree, relpath):
            found.setdefault(key, []).append(f"{relpath}:{lineno}")
    return found


class TestSenderKeysAreRegistered(FrappeTestCase):
    def test_every_key_a_sender_passes_is_registered(self):
        unregistered = _unregistered(sender_keys(), NOTIFICATION_KEYS, UNREACHABLE)
        self.assertEqual(
            unregistered,
            {},
            "These notification keys are passed to a sender but are not in notification_registry.py, "
            "so EmailService skips the mail as 'disabled' (key -> senders): " + repr(unregistered),
        )

    def test_the_checker_flags_an_unregistered_key_independently_of_the_real_tree(self):
        # control for the test above: it must be able to fail even if the registry were wrong
        found = {"fake_unregistered_key_1999": ["x.py:1"], "member_activated": ["y.py:2"]}
        self.assertEqual(_unregistered(found, NOTIFICATION_KEYS), {"fake_unregistered_key_1999": ["x.py:1"]})
        self.assertEqual(_unregistered(found, NOTIFICATION_KEYS, unreachable={"fake_unregistered_key_1999"}), {})
        planted = ast.parse(
            "def f(t):\n    notification_key_map = {'a': 'planted_fake_key_1999'}\n"
            "    notification_key = notification_key_map.get(t, 'planted_default_1999')\n"
            "    send(notification_key=notification_key)\n"
        )
        keys = {k for k, _ in _tree_keys(planted, "planted.py")}
        self.assertEqual(keys, {"planted_fake_key_1999", "planted_default_1999"})
        self.assertEqual(_unregistered({k: ["p"] for k in keys}, NOTIFICATION_KEYS).keys(), keys)

    def test_unresolvable_keyword_values_are_flagged_and_followed_ones_are_not(self):
        def flagged(source):
            return _unresolved(ast.parse(source))

        self.assertEqual(flagged("send(notification_key='member_activated')"), [])
        self.assertEqual(flagged("def f(notification_key):\n    send(notification_key=notification_key)"), [])
        self.assertEqual(flagged("send(notification_key=cfg['notification_key'])"), [])
        self.assertEqual(flagged("send(notification_key=ctx.get('notification_key', 'x'))"), [])
        self.assertEqual(
            flagged("def f(t):\n    notification_key = {'a': 'b'}.get(t)\n    send(notification_key=notification_key)"),
            [],
        )
        # the shapes the walker cannot follow
        self.assertEqual(flagged("send(notification_key='a' if c else 'b')"), [1])
        self.assertEqual(flagged("send(notification_key=f'x_{t}')"), [1])
        self.assertEqual(flagged("send(notification_key=MAP[t])"), [1])
        self.assertEqual(flagged("def f():\n    k = pick()\n    send(notification_key=k)"), [3])
        self.assertEqual(flagged("send(notification_key=obj.key)"), [1])

    def test_no_sender_passes_a_notification_key_the_walker_cannot_resolve(self):
        unresolved = [f"{rel}:{n}" for rel, tree in _parsed_sources() for n in _unresolved(tree)]
        self.assertEqual(unresolved, [], "extend sender_keys() to follow this shape, or allow-list it")

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

    def _seed_fresh_install_rows(self):
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

    @staticmethod
    def _cleanup_queue_rows(recipients):
        names = frappe.get_all(
            "Email Queue Recipient", filters={"recipient": ["in", recipients]}, pluck="parent"
        )
        if names:
            frappe.db.delete("Email Queue Recipient", {"parent": ["in", names]})
            frappe.db.delete("Email Queue", {"name": ["in", names]})
        frappe.db.commit()  # the rows were committed by singleton_backup; so must their removal be

    def _unique_recipient(self, label):
        # the per-recipient cooldown lives in Redis and survives a rollback: never reuse an address
        return f"{label}-{uuid.uuid4().hex[:8]}@example.com"

    def test_payment_failure_first_is_queued_on_a_seeded_site(self):
        control, target = self._unique_recipient("control"), self._unique_recipient("failure-first")
        # the harness replaces frappe.sendmail process-wide, so no Email Queue row could appear
        disable_test_email_mocking()
        self.addCleanup(enable_test_email_mocking)
        # singleton_backup commits on exit, which makes the queued rows durable, so a rollback
        # cannot remove them: delete them by recipient (registered before the send; LIFO).
        self.addCleanup(self._cleanup_queue_rows, [control, target])
        with singleton_backup(DOCTYPE):
            self._seed_fresh_install_rows()
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
            self._seed_fresh_install_rows()
            rows = {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}
            for key in newly:
                self.assertIn(key, rows, key)
                self.assertEqual(cint(rows[key].enabled), 1, key)
