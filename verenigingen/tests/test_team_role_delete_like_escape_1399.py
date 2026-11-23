"""#1399: Team Role deletion counted assignment history with an unescaped LIKE.

``Volunteer Assignment.role`` holds ``"<role_name>"`` or ``"<role_name> - <extra>"``
(team_service._get_role_description_for_history), so a CONTAINS match is intended.
A ``%`` or ``_`` typed into ``role_name`` must be literal, not a wildcard. The count
only feeds an informational msgprint; it never blocks the delete.
"""

import re

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestTeamRoleDeleteLikeEscape1399(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        frappe.flags.skip_volunteer_account_creation = True
        self.volunteer = self.create_test_volunteer()

    def _make_role_1399(self, role_name):
        doc = frappe.get_doc(
            {
                "doctype": "Team Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_team_leader": 0,
                "is_unique": 0,
                "is_active": 1,
            }
        ).insert()
        self.track_doc(doc.doctype, doc.name)
        return doc

    def _add_history_1399(self, role_text):
        volunteer = frappe.get_doc("Volunteer", self.volunteer.name)
        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Team",
                "role": role_text,
                "start_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        volunteer.save()

    def _delete_and_get_history_count_1399(self, role):
        """Delete through the real delete_doc; return the N of the history note, or None."""
        frappe.local.message_log = []
        frappe.delete_doc("Team Role", role.name, force=False)
        for entry in frappe.local.message_log:
            message = entry.get("message", "") if isinstance(entry, dict) else str(entry)
            found = re.search(r"referenced in (\d+) assignment history", message)
            if found:
                return int(found.group(1))
        return None

    def _check_wildcard_not_overmatching_1399(self, role_name, lookalike):
        role = self._make_role_1399(role_name)
        self._add_history_1399(lookalike)
        self.assertIsNone(
            self._delete_and_get_history_count_1399(role),
            f"{role_name!r} must not count {lookalike!r} as a reference",
        )

    def test_underscore_is_not_a_wildcard(self):
        suffix = frappe.generate_hash(length=6)
        self._check_wildcard_not_overmatching_1399(f"Wild_{suffix}", f"WildX{suffix}")

    def test_percent_is_not_a_wildcard(self):
        suffix = frappe.generate_hash(length=6)
        self._check_wildcard_not_overmatching_1399(f"Pct%{suffix}", f"PctZZZ{suffix}")

    def test_backslash_is_literal(self):
        """A backslash in role_name must be escaped too, or it eats the next character."""
        suffix = frappe.generate_hash(length=6)
        role = self._make_role_1399(f"Back\\{suffix}")
        self._add_history_1399(role.role_name)
        # An unescaped "\\" turns the pattern into an escape of the next char and loses this row.
        self._add_history_1399(f"BackX{suffix}")
        self.assertEqual(self._delete_and_get_history_count_1399(role), 1)

    def test_real_references_are_still_counted_exact_and_with_suffix(self):
        """Control: literal matches (exact, 'role - extra' and 'prefix role') are counted, a lookalike is not."""
        suffix = frappe.generate_hash(length=6)
        role = self._make_role_1399(f"Wild_{suffix}")
        self._add_history_1399(role.role_name)
        self._add_history_1399(f"{role.role_name} - Treasurer")
        self._add_history_1399(f"Lead {role.role_name}")
        self._add_history_1399(f"WildX{suffix}")
        self.assertEqual(self._delete_and_get_history_count_1399(role), 3)
        self.assertFalse(frappe.db.exists("Team Role", role.name))
