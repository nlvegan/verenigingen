"""No test arms ``own_notification_keys`` before ``ensure_outgoing_email_account`` (#2673).

``ensure_outgoing_email_account`` creates a default outgoing account on a site with none (CI's fresh
site) and registers a cleanup that deletes it and COMMITS. ``own_notification_keys`` registers a
cleanup that fails the test if any commit ran while it was armed. Cleanups are LIFO, so the account
helper called SECOND runs its commit while the check is still armed, and the test fails with
"frappe.db.commit() ran while own_notification_keys was active". Called FIRST, its commit lands
after the restore and makes the restore permanent.

It only bites when the test's tearDown did not roll back (``_rollback_once_before_draining`` rolls
back only when a tracked row exists, and a rollback drops the commit hook), and only on a site with
no outgoing account, so a warm bench site never shows it. Measured on test_site_1 with every Email
Account disabled: ``test_mail_body_escaping_2307`` with the two calls swapped went 6 red of 12.

This is a static check of the order, per test method (its ``setUp`` calls, then its own). A later
``ensure_outgoing_email_account`` after an earlier one is a no-op (the account exists), so only the
FIRST ensure call matters.

Coverage limits. The scan does NOT follow: helper methods called from a test body; ``setUpClass``;
a second base class, or a base class defined in another file; aliased imports; or private ensure
helpers outside ``ENSURE`` (``_ensure_outgoing_account``, ``_own_default_outgoing_account``; a file
that uses only those is also skipped by the source prefilter). The review of #2673 found no live
instance of any of these today; the files it checked that use such helpers are
``tests/payment/test_payment_reminder_outcomes.py`` and
``tests/payment/test_shipped_template_context_2018_2020.py``.
"""

import ast
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

OWN = "own_notification_keys"
ENSURE = ("ensure_outgoing_email_account", "_ensure_outgoing_email_account")
PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # the verenigingen package directory


def _calls_in_order(function):
    found = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == OWN or name in ENSURE:
            found.append((node.lineno, node.col_offset, "own" if name == OWN else "ensure"))
    return [kind for _, _, kind in sorted(found)]


def _methods_with_inherited_setup(tree):
    """Yield (class, test method, kinds in the order the test runs them)."""
    classes = {c.name: c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}

    def setup_kinds(cls):
        for base in cls.bases:
            parent = classes.get(getattr(base, "id", None))
            inherited = setup_kinds(parent) if parent else []
            break
        else:
            inherited = []
        own = [f for f in cls.body if isinstance(f, ast.FunctionDef) and f.name == "setUp"]
        # a setUp that calls super().setUp() keeps the inherited calls first
        return inherited + _calls_in_order(own[0]) if own else inherited

    for cls in classes.values():
        prefix = setup_kinds(cls)
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test"):
                yield cls.name, fn.name, prefix + _calls_in_order(fn)


def wrong_order_tests(source):
    """Tests in ``source`` whose FIRST ensure_outgoing_email_account comes after own_notification_keys."""
    bad = []
    for class_name, method, kinds in _methods_with_inherited_setup(ast.parse(source)):
        if "own" in kinds and "ensure" in kinds:
            if kinds.index("own") < kinds.index("ensure"):
                bad.append(f"{class_name}.{method}")
    return bad


class TestNotificationKeysOrder2673(FrappeTestCase):
    def test_every_test_module_calls_the_account_helper_first(self):
        offenders = {}
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            source = path.read_text()
            if OWN not in source or "ensure_outgoing_email_account" not in source:
                continue
            bad = wrong_order_tests(source)
            if bad:
                offenders[str(path.relative_to(PACKAGE_ROOT))] = bad
        self.assertEqual(
            offenders,
            {},
            "own_notification_keys is armed before ensure_outgoing_email_account: on a site with no "
            "outgoing account the account cleanup's commit runs while the check is armed (#2673). "
            "Call ensure_outgoing_email_account first.",
        )

    def test_control_the_scan_sees_the_wrong_order_and_the_right_one(self):
        wrong = (
            "class T:\n"
            "    def setUp(self):\n        own_notification_keys(self, 'k')\n"
            "        ensure_outgoing_email_account(self)\n"
            "    def test_a(self): pass\n"
        )
        right = wrong.replace("own_notification_keys(self, 'k')", "XX").replace(
            "ensure_outgoing_email_account(self)", "own_notification_keys(self, 'k')"
        ).replace("XX", "ensure_outgoing_email_account(self)")
        inherited = (
            "class B:\n    def setUp(self):\n        own_notification_keys(self, 'k')\n"
            "class T(B):\n    def test_a(self):\n        ensure_outgoing_email_account(self)\n"
        )
        ensured_earlier = (
            "class T:\n    def setUp(self):\n        ensure_outgoing_email_account(self)\n"
            "    def test_a(self):\n        own_notification_keys(self, 'k')\n"
            "        ensure_outgoing_email_account(self)\n"
        )
        self.assertEqual(wrong_order_tests(wrong), ["T.test_a"])
        self.assertEqual(wrong_order_tests(right), [])
        self.assertEqual(wrong_order_tests(inherited), ["T.test_a"])
        self.assertEqual(wrong_order_tests(ensured_earlier), [])
