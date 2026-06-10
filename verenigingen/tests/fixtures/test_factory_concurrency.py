# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Regression: ensure_membership_type_exists tolerates the get-or-create race.

Under ``run-parallel-tests`` the worker processes share one site database, so
two tests can both pass the ``frappe.db.exists`` pre-check and both reach the
``insert()`` for the same stable-named shared Membership Type. Because
``membership_type_name`` is the autoname/primary key, only one insert can win;
the loser collides and raises ``DuplicateEntryError``. The helper must absorb
that and return the existing name rather than crash the caller's ``setUp`` —
otherwise a single unlucky interleaving fails an unrelated (often SEPA) test.

This test forces that branch deterministically: it creates the type, then
patches ``frappe.db.exists`` so the helper's pre-check reports the row absent —
exactly the window a losing parallel worker sees — and asserts the re-attempted
insert is swallowed, the call still returns the name, and no duplicate row is
left behind.
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists


class TestEnsureMembershipTypeRace(EnhancedTestCase):
    def test_duplicate_insert_is_absorbed(self):
        name = f"Race Member {self.uid[:8]}"

        # First call creates the shared master the normal way.
        self.assertEqual(ensure_membership_type_exists(name), name)
        self.assertTrue(frappe.db.exists("Membership Type", name))

        real_exists = frappe.db.exists
        forced_misses = []

        def force_miss(*args, **kwargs):
            # Report ONLY the helper's pre-check for this exact name as "absent",
            # reproducing the window before a parallel worker sees the winner's
            # committed row. Every other lookup uses the real implementation.
            if args[:2] == ("Membership Type", name):
                forced_misses.append(args)
                return None
            return real_exists(*args, **kwargs)

        with patch.object(frappe.db, "exists", side_effect=force_miss):
            # Skips the early return and re-attempts the insert against the
            # existing primary key -> DuplicateEntryError -> absorbed.
            result = ensure_membership_type_exists(name)

        # Non-vacuous guard: the pre-check must actually have been forced to miss,
        # otherwise the helper short-circuits on the early return and never
        # exercises the duplicate-insert branch this test is asserting on.
        self.assertTrue(forced_misses, "pre-check was not intercepted; test is vacuous")
        self.assertEqual(result, name)
        # The failed insert rolled back to its savepoint: still exactly one row.
        self.assertEqual(frappe.db.count("Membership Type", {"membership_type_name": name}), 1)


if __name__ == "__main__":
    unittest.main()
