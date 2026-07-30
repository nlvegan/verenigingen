"""Harness fidelity: EnhancedTestCase must not suppress production document behavior.

These tests assert framework-level guarantees rather than any app behavior. They exist
because ``EnhancedTestCase.setUp`` set ``frappe.flags.in_import = True`` purely to bypass
``throttle_user_creation()`` (``frappe/core/doctype/user/user.py``), and that flag
incidentally disabled four things Frappe does on every real save:

- ``_set_defaults()``       defined ``frappe/model/document.py:998``, called from ``:435,543``
- ``_validate_selects()``   defined ``frappe/model/base_document.py:1094``, called from
  ``frappe/model/document.py:790``
- ``_validate_constants()`` defined ``frappe/model/base_document.py:1170``
- autoname regeneration     ``frappe/model/naming.py:158``

Every test on the harness therefore ran against a document model production never sees.
These tests pin the restored behavior so it cannot silently regress if someone reintroduces
a blanket ``in_import`` in the harness.

ToDo is the subject for the framework assertions: a core DocType with two defaulted Select
fields and a single required field, so it exercises the behavior without dragging in app
hooks that might supply the same values by another route and mask a regression.

Design: docs/superpowers/specs/2026-07-30-in-import-harness-phase1-design.md
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestHarnessProductionFidelity(EnhancedTestCase):
    """The harness must leave Frappe's document behavior intact."""

    def test_document_defaults_are_applied_on_insert(self):
        """DocType field defaults must reach the inserted document.

        ToDo.priority defaults to "Medium" and ToDo.status to "Open" in todo.json.
        Under frappe.flags.in_import, Document._set_defaults() early-returns and both
        arrive unset. This is the same mechanism that made test Users land disabled:
        User.enabled defaults to "1", so suppressing defaults creates a disabled user.
        """
        todo = frappe.get_doc({"doctype": "ToDo", "description": "harness fidelity probe"})
        todo.insert()

        self.assertEqual(todo.priority, "Medium", "ToDo.priority default was not applied")
        self.assertEqual(todo.status, "Open", "ToDo.status default was not applied")

    def test_user_without_explicit_enabled_is_enabled(self):
        """A User created without an explicit `enabled` must come out enabled.

        This is the concrete bug: User.enabled has default "1" in user.json, so a factory
        or service that omits the field relies on _set_defaults() to supply it. With
        defaults suppressed the user is created disabled, which then fails any test that
        needs an authorized session for it. The failure was masked for years because
        ERPNext force-syncs Employee.status to User.enabled, so seating the user as an
        Active Employee quietly re-enabled it.

        Note the assertion deliberately does NOT go through create_test_user() or
        create_user_with_roles() — both pass enabled=1 explicitly, so they would pass
        regardless and prove nothing about defaults.
        """
        email = f"harness-fidelity-{frappe.generate_hash(length=8)}@example.invalid"

        # No permission bypass: EnhancedTestCase.setUp already grants the test user
        # System Manager, which may create Users. Running as the real test user rather
        # than Administrator also keeps this closer to how production creates accounts.
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Harness",
                "last_name": "Fidelity",
                # `enabled` intentionally omitted — that is the point of the test.
                "send_welcome_email": 0,
            }
        )
        user.insert()

        self.assertEqual(user.enabled, 1, "User.enabled default was not applied")

    def test_user_creation_throttle_is_bypassed(self):
        """The bypass the harness actually needs must survive.

        This is the one thing frappe.flags.in_import was set for. Removing it in favour of
        a raised throttle_user_limit is only correct if the bypass still holds, and nothing
        else in this file would notice if it stopped: suites create users well under the
        default 60/hour and would stay green until a bulk suite tripped "Throttled".

        get_creation_count is stubbed high rather than inserting 60+ real users — the
        subject under test is throttle_user_creation()'s limit comparison, not Frappe's
        row counting.

        The second assertion is not redundant with the first, and this is the trap it
        avoids: sites/test_site_1/site_config.json already carries
        "throttle_user_limit": 100000, so on that site the no-throw assertion passes even
        with the setUp override deleted. It would only fail on a fresh CI site that lacks
        the key — i.e. exactly the "green locally, red on CI" asymmetry this suite has been
        bitten by before. Asserting the harness raised the limit *itself*, above whatever
        the site configured, makes the test site-independent.
        """
        from unittest.mock import patch

        from frappe.core.doctype.user.user import throttle_user_creation

        with patch.object(frappe.db, "get_creation_count", return_value=10_000):
            # Must not raise. 10_000 exceeds the stock limit of 60.
            throttle_user_creation()

        self.assertGreaterEqual(
            frappe.local.conf.get("throttle_user_limit") or 0,
            1000000,
            "EnhancedTestCase.setUp no longer raises throttle_user_limit; user creation in "
            "tests is relying on site config and will throttle on a fresh CI site",
        )

    def test_invalid_select_value_is_rejected(self):
        """Select fields must be validated against their options.

        ToDo.priority allows only High/Medium/Low. Under frappe.flags.in_import,
        _validate_selects() early-returns and a junk value is accepted, so tests could
        write states production rejects outright.
        """
        todo = frappe.get_doc(
            {
                "doctype": "ToDo",
                "description": "harness fidelity select probe",
                "priority": "Wobbly",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            todo.insert()
