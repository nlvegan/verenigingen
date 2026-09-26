"""Regression test for #1466.

``EnhancedTestDataFactory.create_volunteer()`` passed ``"Volunteer"`` as the
``doctype`` argument to ``force_unique_name()``, so the collision-resolution
branch ran ``frappe.db.exists("Volunteer", <generated candidate>)``.

``Volunteer.autoname`` is ``format:Assoc-Vol-{YYYY}-{MM}-{###}``
(verenigingen/verenigingen/doctype/volunteer/volunteer.json) -- an
auto-generated series with no relationship to ``volunteer_name``, an
ordinary ``Data`` field with no ``unique`` flag. So the candidate string
``force_unique_name`` builds (e.g. ``"TEST John Doe 001_483920"``) can never
equal a real ``tabVolunteer.name`` (always ``"Assoc-Vol-2026-01-042"``-shaped)
-- the exists() check is structurally dead. It is also the wrong check for
the doctype's real uniqueness constraint: ``Volunteer.validate_unique_member_link``
enforces at most one Volunteer per ``member``, not per ``volunteer_name``, and
that constraint is unrelated to what ``force_unique_name`` was asked to
protect here. Passing a doctype for this caller therefore bought nothing but
a wasted query on every call; the fix drops it.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCreateVolunteerDoesNotProbeDeadCollisionCheck(EnhancedTestCase):
    def test_create_volunteer_does_not_query_volunteer_by_generated_name(self):
        original_exists = frappe.db.exists
        wasted_calls = []

        def spy_exists(dt, dn=None, *args, **kwargs):
            if dt == "Volunteer" and isinstance(dn, str) and dn.startswith("TEST "):
                wasted_calls.append(dn)
            return original_exists(dt, dn, *args, **kwargs)

        with patch.object(frappe.db, "exists", side_effect=spy_exists):
            volunteer = self.factory.create_volunteer(
                volunteer_name="Force Unique Name 1466 Dead Check"
            )

        self.factory.track_document("Volunteer", volunteer.name)

        self.assertEqual(
            wasted_calls,
            [],
            "create_volunteer's uniqueness pass for volunteer_name ran a "
            f"frappe.db.exists('Volunteer', <candidate>) probe ({wasted_calls!r}); "
            "Volunteer autonames on a series unrelated to volunteer_name, so "
            "that candidate can never match a real row -- the check is dead "
            "and should not be run at all",
        )
