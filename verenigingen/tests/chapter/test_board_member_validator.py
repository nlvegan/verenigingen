"""
Real-DB tests for the chapter ``BoardMemberValidator``
(``verenigingen/verenigingen/doctype/chapter/validators/board_member_validator.py``).

The validator takes board members as plain dicts (already normalised by
ChapterValidator) and checks required fields, date ranges, volunteer/role
existence, unique-role assignment, board size and required roles. Volunteer and
Chapter Role existence are real DB lookups, so those branches use real factory
documents rather than mocks.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.chapter.validators.board_member_validator import (
    BoardMemberValidator,
)


class TestBoardMemberValidator(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = BoardMemberValidator()

    def _make_role(self, is_unique=0, is_active=1):
        role_name = f"BMVRole{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_unique": is_unique,
                "is_active": is_active,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def _make_volunteer(self):
        member = self.create_test_member(
            first_name="BMV",
            last_name="Tester",
            email=f"bmv.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        return self.create_test_volunteer(member=member.name)

    # ---------------------------------------------- validate_single_board_member

    def test_missing_required_fields_errors(self):
        result = self.v.validate_single_board_member({}, index=0)
        self.assertFalse(result.is_valid)
        # volunteer, chapter_role and from_date are all required
        self.assertTrue(any("volunteer" in e for e in result.errors))
        self.assertTrue(any("chapter_role" in e for e in result.errors))
        self.assertTrue(any("from_date" in e for e in result.errors))

    def test_nonexistent_volunteer_errors(self):
        result = self.v.validate_single_board_member(
            {"volunteer": "NO-SUCH-VOL-XYZ", "chapter_role": "x", "from_date": today()}
        )
        self.assertTrue(any("does not exist" in e for e in result.errors))

    def test_nonexistent_role_errors(self):
        vol = self._make_volunteer()
        result = self.v.validate_single_board_member(
            {"volunteer": vol.name, "chapter_role": "NO-SUCH-ROLE-XYZ", "from_date": today()}
        )
        self.assertTrue(any("Chapter Role" in e and "does not exist" in e for e in result.errors))

    def test_valid_member_passes(self):
        vol = self._make_volunteer()
        role = self._make_role()
        result = self.v.validate_single_board_member(
            {"volunteer": vol.name, "chapter_role": role, "from_date": today(), "is_active": 1}
        )
        self.assertTrue(result.is_valid, result.errors)

    def test_from_date_after_to_date_errors(self):
        vol = self._make_volunteer()
        role = self._make_role()
        result = self.v.validate_single_board_member(
            {
                "volunteer": vol.name,
                "chapter_role": role,
                "from_date": today(),
                "to_date": add_days(today(), -10),
            }
        )
        self.assertTrue(any("cannot be after" in e for e in result.errors))

    def test_active_member_with_past_end_date_warns_but_does_not_block(self):
        # Deliberately a WARNING, not an error. #596 wired this per-row check into
        # Chapter.validate(); as a blocking error it made a Chapter carrying the stale
        # "is_active=1 with an expired to_date" combination unsaveable, which the
        # board_members_only segment query treats as ordinary data it filters out
        # rather than as an impossible state. See board_member_validator.py.
        vol = self._make_volunteer()
        role = self._make_role()
        result = self.v.validate_single_board_member(
            {
                "volunteer": vol.name,
                "chapter_role": role,
                "from_date": add_days(today(), -30),
                "to_date": add_days(today(), -5),
                "is_active": 1,
                "volunteer_name": "Past Person",
            }
        )
        self.assertTrue(any("end date in the past" in w for w in result.warnings))
        self.assertFalse(any("end date in the past" in e for e in result.errors))
        self.assertTrue(result.is_valid)

    def test_invalid_email_errors(self):
        vol = self._make_volunteer()
        role = self._make_role()
        result = self.v.validate_single_board_member(
            {
                "volunteer": vol.name,
                "chapter_role": role,
                "from_date": today(),
                "email": "not-an-email",
            }
        )
        self.assertTrue(any("email" in e.lower() for e in result.errors))

    # ------------------------------------------------- validate_board_constraints

    def test_unique_role_assigned_twice_errors(self):
        role = self._make_role(is_unique=1)
        members = [
            {"volunteer": "V1", "chapter_role": role, "is_active": 1, "volunteer_name": "A"},
            {"volunteer": "V2", "chapter_role": role, "is_active": 1, "volunteer_name": "B"},
        ]
        result = self.v.validate_board_constraints(members)
        self.assertTrue(any("assigned to multiple" in e for e in result.errors))

    def test_unique_role_single_holder_ok(self):
        role = self._make_role(is_unique=1)
        members = [
            {"volunteer": "V1", "chapter_role": role, "is_active": 1, "volunteer_name": "A"},
        ]
        result = self.v.validate_board_constraints(members)
        self.assertFalse(any("multiple" in e for e in result.errors))

    def test_non_unique_role_assigned_twice_ok(self):
        role = self._make_role(is_unique=0)
        members = [
            {"volunteer": "V1", "chapter_role": role, "is_active": 1},
            {"volunteer": "V2", "chapter_role": role, "is_active": 1},
        ]
        result = self.v.validate_board_constraints(members)
        self.assertFalse(any("multiple" in e for e in result.errors))

    def test_small_board_warns(self):
        # default minimum_board_size is 3; one active member -> warning
        members = [{"volunteer": "V1", "chapter_role": "r", "is_active": 1}]
        result = self.v.validate_board_constraints(members)
        self.assertTrue(any("Recommended minimum" in w for w in result.warnings))

    def test_required_roles_missing_warns(self):
        # default required roles include Chair/Secretary/Treasurer
        members = [{"volunteer": "V1", "chapter_role": "Custodian", "is_active": 1}]
        result = self.v.validate_board_constraints(members)
        self.assertTrue(any("Required role" in w for w in result.warnings))

    # ------------------------------------------------- validate_role_uniqueness

    def test_role_uniqueness_conflict(self):
        role = self._make_role(is_unique=1)
        active = [{"chapter_role": role, "is_active": 1, "name": "BM-OTHER", "volunteer_name": "Held"}]
        result = self.v.validate_role_uniqueness(role, current_member_id="BM-SELF", active_members=active)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("already assigned" in e for e in result.errors))

    def test_role_uniqueness_same_member_no_conflict(self):
        role = self._make_role(is_unique=1)
        active = [{"chapter_role": role, "is_active": 1, "name": "BM-SELF"}]
        result = self.v.validate_role_uniqueness(role, current_member_id="BM-SELF", active_members=active)
        self.assertTrue(result.is_valid)

    def test_role_uniqueness_non_unique_role_skipped(self):
        role = self._make_role(is_unique=0)
        active = [{"chapter_role": role, "is_active": 1, "name": "BM-OTHER"}]
        result = self.v.validate_role_uniqueness(role, current_member_id="BM-SELF", active_members=active)
        self.assertTrue(result.is_valid)

    # ----------------------------------------- validate_board_member_changes

    def test_deactivation_without_end_date_warns(self):
        old = [{"name": "BM1", "is_active": 1, "chapter_role": "r", "volunteer_name": "X"}]
        new = [{"name": "BM1", "is_active": 0, "chapter_role": "r", "volunteer_name": "X"}]
        result = self.v.validate_board_member_changes(old, new)
        self.assertTrue(any("no end date is set" in w for w in result.warnings))

    def test_unchanged_member_no_warning(self):
        old = [{"name": "BM1", "is_active": 1, "chapter_role": "r", "to_date": None}]
        new = [{"name": "BM1", "is_active": 1, "chapter_role": "r", "to_date": None}]
        result = self.v.validate_board_member_changes(old, new)
        self.assertEqual(result.warnings, [])

    # --------------------------------------------------- get_validation_summary

    def test_validation_summary_shape(self):
        vol = self._make_volunteer()
        role = self._make_role()
        members = [
            {"volunteer": vol.name, "chapter_role": role, "from_date": today(), "is_active": 1}
        ]
        summary = self.v.get_validation_summary(members)
        self.assertIn("is_valid", summary)
        self.assertEqual(summary["active_members_count"], 1)
        self.assertEqual(summary["error_count"], len(summary["errors"]))


if __name__ == "__main__":
    import unittest

    unittest.main()
