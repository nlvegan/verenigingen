# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""Tests for the factory's caller-supplied-email uniquification (#1254).

``EnhancedTestDataFactory.create_member`` appends a run-unique suffix to a
caller-supplied ``email``. The trigger used to be a heuristic -- "the local
part's last five characters contain no digit" -- standing in for "the caller
did not make this unique themselves".

That heuristic misfires on the exact shape callers use FOR uniqueness.
``frappe.generate_hash()`` returns lowercase hex, so the last five characters
of a hash-suffixed local part are digit-free with probability (6/16)**5, i.e.
**1 run in ~135**. When it fired, ``Member.email`` silently diverged from the
string the caller went on to build the ``User`` from, so
``get_member_name_for_user()`` resolved neither by ``user`` (blank) nor by
``email`` (rewritten) -- and the test failed for a reason unrelated to its
subject. That is the mechanism behind #1254.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import get_member_name_for_user


class TestFactoryEmailUniquification(EnhancedTestCase):
    def _digit_free_tail_email(self, prefix):
        """An address that is globally unique AND whose local part's last five
        characters carry no digit -- the 1-in-135 draw, made deterministic.

        The hash supplies the uniqueness; the trailing alphabetic run supplies
        the property under test. Derived from the fixture rather than hardcoded,
        so a re-run cannot collide with its own earlier row.
        """
        return f"{prefix}-{frappe.generate_hash(length=8)}-abcdef@example.com"

    def test_a_unique_caller_supplied_email_reaches_the_member_unchanged(self):
        """An address nobody holds must survive to Member.email verbatim.

        This is what every caller that separately creates a ``User`` from the
        same string depends on, and what broke 1 run in ~135.
        """
        email = self._digit_free_tail_email("fixture1254-unchanged")
        self.assertFalse(
            any(c.isdigit() for c in email.split("@")[0][-5:]),
            "fixture must exhibit the digit-free tail it is testing",
        )

        member = self.create_test_member(email=email)
        self.track_doc("Member", member.name)

        self.assertEqual(member.email, email)

    def test_an_email_already_held_by_another_member_is_still_uniquified(self):
        """CONTROL: the anti-collision intent must survive the fix.

        A static literal replayed against a persistent DB still finds the
        earlier run's row, and must still be moved aside. Without this, the fix
        is indistinguishable from deleting the uniquifier outright.
        """
        email = self._digit_free_tail_email("fixture1254-taken")

        first = self.create_test_member(email=email)
        self.track_doc("Member", first.name)
        self.assertEqual(first.email, email)

        second = self.create_test_member(email=email)
        self.track_doc("Member", second.name)

        self.assertNotEqual(second.email, email)
        self.assertTrue(second.email.endswith("@example.com"))
        # The incumbent keeps the address; only the newcomer moves.
        self.assertEqual(frappe.db.get_value("Member", first.name, "email"), email)

    def test_a_user_built_from_the_same_string_resolves_back_to_the_member(self):
        """The end-to-end shape #1254 actually failed on.

        ~16 test files build a ``User`` from the same local variable they hand
        to ``create_test_member``. That only works while the factory leaves the
        address alone, because ``Member.user`` is blank (the Member is created
        first) so resolution depends entirely on the email fallback.
        """
        email = self._digit_free_tail_email("fixture1254-resolves")

        member = self.create_test_member(email=email)
        self.track_doc("Member", member.name)

        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Fixture1254",
                    "send_welcome_email": 0,
                    "enabled": 1,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert()
            self.track_doc("User", user.name)

        self.assertEqual(get_member_name_for_user(email), member.name)
