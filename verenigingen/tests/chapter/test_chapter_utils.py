"""
Chapter Access/Permission Utilities Test Suite
==============================================

Real-DB integration tests for ``verenigingen.services.chapter.chapter_utils``.

Builds a real Member -> Volunteer -> Chapter Board Member -> Chapter chain
(backed by real User accounts) and derives expected access from the data,
exercising the permission-resolution branches:

- admin role -> full access (None)
- no member record / no volunteer record / no board positions -> []
- permission-level filtering (Financial/Admin vs Basic)
- single-chapter check (has_chapter_access_permission)
- board-position enrichment (get_user_board_positions)
- is_chapter_board_member with/without required levels
- get_chapters_with_permission
- get_member_primary_chapter (active chapter resolution)
- the dues-split wrappers + whitelisted get_chapter_split_info

These functions commit indirectly via factory inserts; the chapter/role/board
fixtures are made unique per test class run to avoid DuplicateEntry collisions.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _ensure_test_region():
    """Idempotently ensure a "Test Region" exists; return its slug docname."""
    slug = "test-region"
    if not frappe.db.exists("Region", slug):
        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": "Test Region",
                "region_code": "TR",
                "country": "Netherlands",
                "is_active": 1,
            }
        )
        region.insert(ignore_permissions=True)
    return slug


class TestChapterUtilsAccess(EnhancedTestCase):
    """Cover the access-resolution functions of chapter_utils."""

    def setUp(self):
        super().setUp()

        import time

        token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        self.token = token

        region = _ensure_test_region()
        self.chapter_fin = self.create_chapter(chapter_name=f"CU Fin {token}", region=region)
        self.chapter_basic = self.create_chapter(chapter_name=f"CU Basic {token}", region=region)

        # Financial board member: User -> Member -> Volunteer -> board (Financial role)
        self.fin_user = self.create_test_user(email=f"cu-fin-{token}@test.com", roles=["Verenigingen Member"])
        self.fin_member = self.create_test_member(
            first_name="Fin", last_name="Boardmember", email=self.fin_user.name, user=self.fin_user.name
        )
        self.fin_volunteer = self.create_test_volunteer(self.fin_member.name)

        # Basic board member (no Financial/Admin level)
        self.basic_user = self.create_test_user(
            email=f"cu-basic-{token}@test.com", roles=["Verenigingen Member"]
        )
        self.basic_member = self.create_test_member(
            first_name="Basic",
            last_name="Boardmember",
            email=self.basic_user.name,
            user=self.basic_user.name,
        )
        self.basic_volunteer = self.create_test_volunteer(self.basic_member.name)

        # A member with NO volunteer record
        self.no_vol_user = self.create_test_user(
            email=f"cu-novol-{token}@test.com", roles=["Verenigingen Member"]
        )
        self.no_vol_member = self.create_test_member(
            first_name="NoVol",
            last_name="Member",
            email=self.no_vol_user.name,
            user=self.no_vol_user.name,
        )

        # A user with NO member record at all
        self.orphan_user = self.create_test_user(
            email=f"cu-orphan-{token}@test.com", roles=["Verenigingen Member"]
        )

        # Chapter roles
        self.financial_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"CU Treasurer {token}",
                "permissions_level": "Financial",
                "is_unique": 1,
                "is_active": 1,
            }
        )
        self.financial_role.save()

        self.basic_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"CU Secretary {token}",
                "permissions_level": "Basic",
                "is_unique": 1,
                "is_active": 1,
            }
        )
        self.basic_role.save()

        # Board positions
        self._add_board_position(self.chapter_fin.name, self.fin_volunteer.name, self.financial_role.name)
        self._add_board_position(self.chapter_basic.name, self.basic_volunteer.name, self.basic_role.name)

        frappe.db.commit()

    def _add_board_position(self, chapter, volunteer, role, is_active=1):
        bp = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": chapter,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": volunteer,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": is_active,
            }
        )
        bp.insert()
        return bp

    # ---- get_user_accessible_chapters --------------------------------------

    def test_admin_role_sees_all_chapters(self):
        """Admin roles -> None (no filter / sees everything)."""
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        admin_user = self.create_test_user(
            email=f"cu-admin-{self.token}@test.com", roles=["Verenigingen Administrator"]
        )
        self.assertIsNone(get_user_accessible_chapters(admin_user.name))

    def test_empty_user_returns_empty_list(self):
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        self.assertEqual(get_user_accessible_chapters(""), [])

    def test_user_without_member_record_has_no_access(self):
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        self.assertEqual(get_user_accessible_chapters(self.orphan_user.name), [])

    def test_member_without_volunteer_has_no_access(self):
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        self.assertEqual(get_user_accessible_chapters(self.no_vol_user.name), [])

    def test_financial_board_member_sees_own_chapter(self):
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        result = get_user_accessible_chapters(self.fin_user.name)
        self.assertIsInstance(result, list)
        self.assertIn(self.chapter_fin.name, result)
        # Must NOT see the other chapter where they hold no board position
        self.assertNotIn(self.chapter_basic.name, result)

    def test_basic_board_member_excluded_by_default_levels(self):
        """Default required levels are [Admin, Financial]; a Basic role is filtered out."""
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        result = get_user_accessible_chapters(self.basic_user.name)
        self.assertEqual(result, [])

    def test_basic_board_member_visible_when_basic_required(self):
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        result = get_user_accessible_chapters(self.basic_user.name, required_permission_levels=["Basic"])
        self.assertIn(self.chapter_basic.name, result)

    def test_inactive_board_position_excluded(self):
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        # Add an inactive Financial position in chapter_basic for the fin volunteer
        self._add_board_position(
            self.chapter_basic.name, self.fin_volunteer.name, self.financial_role.name, is_active=0
        )
        frappe.db.commit()
        result = get_user_accessible_chapters(self.fin_user.name)
        # Inactive position does not grant access to chapter_basic
        self.assertNotIn(self.chapter_basic.name, result)
        self.assertIn(self.chapter_fin.name, result)

    def test_dangling_chapter_role_is_skipped(self):
        """A board position pointing at a missing Chapter Role is skipped, not fatal."""
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        # Insert a position then delete its role to simulate a dangling reference.
        ephemeral_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"CU Ephemeral {self.token}",
                "permissions_level": "Financial",
                "is_active": 1,
            }
        )
        ephemeral_role.save()
        new_chapter = self.create_chapter(
            chapter_name=f"CU Dangle {self.token}", region=_ensure_test_region()
        )
        self._add_board_position(new_chapter.name, self.fin_volunteer.name, ephemeral_role.name)
        frappe.db.commit()

        # Remove the cached doc reference by force-deleting the role row directly.
        frappe.db.delete("Chapter Role", {"name": ephemeral_role.name})
        frappe.db.commit()
        frappe.clear_cache()

        # Should not raise; the dangling-role position is skipped while the valid
        # Financial position in chapter_fin is still resolved.
        result = get_user_accessible_chapters(self.fin_user.name)
        self.assertIn(self.chapter_fin.name, result)
        self.assertNotIn(new_chapter.name, result)

    # ---- national chapter access -------------------------------------------

    def test_national_board_member_gets_national_chapter_access(self):
        """A board member of the configured national chapter (with a sufficient
        permission level) gains access to the national chapter.

        This exercises the "Check national chapter access" branch of
        get_user_accessible_chapters, which previously crashed-and-swallowed because
        it called a non-existent frappe.get_cached_single() (AttributeError) and read
        a phantom `national_chapter` field instead of the real `national_board_chapter`.
        The fix repoints it to frappe.db.get_single_value(..., "national_board_chapter").

        NOTE on regression strength: this asserts the documented behaviour (a national
        board member sees the national chapter) but is a CHARACTERIZATION test, not a
        strict fail-before/pass-after guard. The earlier main board-positions loop
        already admits ANY chapter where the volunteer holds a qualifying active seat
        -- including the national chapter -- so the national branch is behaviourally
        redundant and the result is identical with the bug present. The strict
        regression anchors for THIS branch are the negative/level tests below plus the
        loop tests; this case documents the intended national-access semantics.
        """
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        # A dedicated national chapter, distinct from the member's own chapter(s).
        national_chapter = self.create_chapter(
            chapter_name=f"CU National {self.token}", region=_ensure_test_region()
        )
        # Give the financial volunteer an ACTIVE Financial board seat in it.
        self._add_board_position(national_chapter.name, self.fin_volunteer.name, self.financial_role.name)
        frappe.db.commit()

        # Configure the national chapter in settings WITHOUT committing: production
        # reads it via frappe.db.get_single_value in the same transaction, and this
        # rolls back at test end (never corrupting the shared Single for parallel shards).
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", national_chapter.name)

        result = get_user_accessible_chapters(self.fin_user.name)
        self.assertIn(national_chapter.name, result)
        # Own chapter is still resolved alongside the national one.
        self.assertIn(self.chapter_fin.name, result)

    def test_non_national_board_member_does_not_get_national_access(self):
        """A user with no seat in the national chapter does NOT receive it, even
        when a national chapter is configured."""
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        national_chapter = self.create_chapter(
            chapter_name=f"CU National Neg {self.token}", region=_ensure_test_region()
        )
        # fin_volunteer has NO board position in national_chapter.
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", national_chapter.name)

        result = get_user_accessible_chapters(self.fin_user.name)
        self.assertNotIn(national_chapter.name, result)
        # Their own chapter is unaffected.
        self.assertIn(self.chapter_fin.name, result)

    def test_national_board_member_below_required_level_excluded(self):
        """A national-chapter board seat whose permission level does not meet the
        requirement does not grant national access (Basic seat vs default
        [Admin, Financial] requirement)."""
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        national_chapter = self.create_chapter(
            chapter_name=f"CU National Basic {self.token}", region=_ensure_test_region()
        )
        # Basic-level seat for the financial volunteer in the national chapter.
        self._add_board_position(national_chapter.name, self.fin_volunteer.name, self.basic_role.name)
        frappe.db.commit()
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", national_chapter.name)

        result = get_user_accessible_chapters(self.fin_user.name)
        # Basic seat does not satisfy default [Admin, Financial] requirement.
        self.assertNotIn(national_chapter.name, result)
        self.assertIn(self.chapter_fin.name, result)

    def test_database_error_propagates_instead_of_denying_access(self):
        """An outage must not read as "this board member has no chapters".

        `[]` is the access-control answer here: permissions.py builds the Expense
        Claim query conditions from it, and every chapter-scoped report filters on
        it. Swallowing a database error and returning `[]` therefore denies a real
        board member silently - the caller gets a well-formed empty report, not an
        error, so nothing anywhere says the answer was never computed.

        Patch the board-position query specifically, AFTER the identity lookups have
        succeeded, so this pins THIS function's handler rather than the already-fixed
        one in get_member_name_for_user.
        """
        from unittest.mock import patch

        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        # Sanity: this user really does have access, so an [] below would be a lie
        # rather than a coincidentally correct answer.
        self.assertIn(self.chapter_fin.name, get_user_accessible_chapters(self.fin_user.name))

        outage = frappe.db.OperationalError("simulated database outage")
        with patch.object(frappe, "get_all", side_effect=outage):
            with self.assertRaises(frappe.db.OperationalError):
                get_user_accessible_chapters(self.fin_user.name)

    def test_board_positions_database_error_propagates(self):
        """Same contract for get_user_board_positions.

        is_chapter_board_member() is built on this function, so a swallowed error
        here reads as "not a board member". This function has already produced that
        failure once for a different reason - it selected phantom start_date/end_date
        columns and the broad except turned the resulting error into [] for every
        real board member.
        """
        from unittest.mock import patch

        from verenigingen.services.chapter.chapter_utils import get_user_board_positions

        self.assertTrue(get_user_board_positions(self.fin_user.name))

        outage = frappe.db.OperationalError("simulated database outage")
        with patch.object(frappe, "get_all", side_effect=outage):
            with self.assertRaises(frappe.db.OperationalError):
                get_user_board_positions(self.fin_user.name)

    def test_missing_chapter_role_skips_only_that_seat(self):
        """The NARROW excepts inside must survive the broad one being removed.

        A single unresolvable Chapter Role must not deny access that the user's other
        board seats already grant - that inner handler is the reason the function can
        afford to propagate real faults from the outer one.

        The failing seat carries a FINANCIAL role in a third chapter, so it would
        otherwise be granted. That is what makes the skip observable: with a Basic
        role the chapter is excluded by the permission-level filter anyway, and the
        test passes whether the lookup raised or not - pinning nothing.
        """
        from unittest.mock import patch

        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        # A SECOND Financial role, distinct from self.financial_role. The seats are
        # resolved in `order_by="parent"` order, so keying the failure on call count
        # would target whichever chapter name happens to sort first; keying it on a
        # role used by exactly one seat is order-independent.
        broken_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"CU Broken Treasurer {self.token}",
                "permissions_level": "Financial",
                "is_unique": 1,
                "is_active": 1,
            }
        )
        broken_role.save()
        third_chapter = self.create_chapter(
            chapter_name=f"CU Broken Role {self.token}", region=_ensure_test_region()
        )
        self._add_board_position(third_chapter.name, self.fin_volunteer.name, broken_role.name)
        frappe.db.commit()

        # Baseline: the seat really does grant access when its role resolves, so the
        # assertion below distinguishes "skipped" from "never granted in the first
        # place".
        self.assertIn(third_chapter.name, get_user_accessible_chapters(self.fin_user.name))

        real_get_cached_doc = frappe.get_cached_doc

        def fail_for_that_seat(doctype, *args, **kwargs):
            if doctype == "Chapter Role" and args and args[0] == broken_role.name:
                raise frappe.DoesNotExistError("Chapter Role vanished")
            return real_get_cached_doc(doctype, *args, **kwargs)

        with patch.object(frappe, "get_cached_doc", side_effect=fail_for_that_seat):
            result = get_user_accessible_chapters(self.fin_user.name)

        # The seat whose role failed is skipped...
        self.assertNotIn(third_chapter.name, result)
        # ...and the one that resolved is still granted. Both halves are needed: the
        # first alone would pass if the function denied everything, the second alone
        # if it ignored the failure entirely.
        self.assertIn(self.chapter_fin.name, result)

    # ---- has_chapter_access_permission -------------------------------------

    def test_has_chapter_access_permission_true_false(self):
        from verenigingen.services.chapter.chapter_utils import has_chapter_access_permission

        self.assertTrue(has_chapter_access_permission(self.chapter_fin.name, self.fin_user.name))
        self.assertFalse(has_chapter_access_permission(self.chapter_basic.name, self.fin_user.name))

    def test_has_chapter_access_permission_empty_chapter(self):
        from verenigingen.services.chapter.chapter_utils import has_chapter_access_permission

        self.assertFalse(has_chapter_access_permission("", self.fin_user.name))

    def test_has_chapter_access_permission_admin_true(self):
        from verenigingen.services.chapter.chapter_utils import has_chapter_access_permission

        admin_user = self.create_test_user(
            email=f"cu-admin2-{self.token}@test.com", roles=["Verenigingen Administrator"]
        )
        # Admin -> accessible_chapters is None -> always True
        self.assertTrue(has_chapter_access_permission(self.chapter_basic.name, admin_user.name))

    # ---- get_user_board_positions ------------------------------------------

    def test_get_user_board_positions_enriched(self):
        from verenigingen.services.chapter.chapter_utils import get_user_board_positions

        positions = get_user_board_positions(self.fin_user.name)
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos["chapter"], self.chapter_fin.name)
        self.assertEqual(pos["chapter_role"], self.financial_role.name)
        self.assertEqual(pos["permissions_level"], "Financial")
        # Pin the documented output keys (from_date/to_date are aliased to
        # start_date/end_date); this fails if the alias is dropped/renamed.
        self.assertIn("start_date", pos)
        self.assertEqual(str(pos["start_date"]), frappe.utils.today())
        self.assertIn("end_date", pos)

    def test_get_user_board_positions_chapter_filter(self):
        from verenigingen.services.chapter.chapter_utils import get_user_board_positions

        # Filter to a chapter the user has no position in -> empty
        positions = get_user_board_positions(self.fin_user.name, chapter_name=self.chapter_basic.name)
        self.assertEqual(positions, [])

    def test_get_user_board_positions_no_member(self):
        from verenigingen.services.chapter.chapter_utils import get_user_board_positions

        self.assertEqual(get_user_board_positions(self.orphan_user.name), [])

    def test_get_user_board_positions_no_volunteer(self):
        from verenigingen.services.chapter.chapter_utils import get_user_board_positions

        self.assertEqual(get_user_board_positions(self.no_vol_user.name), [])

    def test_get_user_board_positions_empty_user(self):
        from verenigingen.services.chapter.chapter_utils import get_user_board_positions

        self.assertEqual(get_user_board_positions(""), [])

    def test_get_user_board_positions_includes_inactive_when_requested(self):
        from verenigingen.services.chapter.chapter_utils import get_user_board_positions

        self._add_board_position(
            self.chapter_basic.name, self.fin_volunteer.name, self.financial_role.name, is_active=0
        )
        frappe.db.commit()
        active = get_user_board_positions(self.fin_user.name, active_only=True)
        allpos = get_user_board_positions(self.fin_user.name, active_only=False)
        self.assertEqual(len(active), 1)
        self.assertEqual(len(allpos), 2)

    # ---- is_chapter_board_member -------------------------------------------

    def test_is_chapter_board_member_any_position(self):
        from verenigingen.services.chapter.chapter_utils import is_chapter_board_member

        self.assertTrue(is_chapter_board_member(self.chapter_fin.name, self.fin_user.name))
        self.assertFalse(is_chapter_board_member(self.chapter_basic.name, self.fin_user.name))

    def test_is_chapter_board_member_empty_chapter(self):
        from verenigingen.services.chapter.chapter_utils import is_chapter_board_member

        self.assertFalse(is_chapter_board_member("", self.fin_user.name))

    def test_is_chapter_board_member_with_required_level(self):
        from verenigingen.services.chapter.chapter_utils import is_chapter_board_member

        # Financial board member matches "Financial" requirement...
        self.assertTrue(
            is_chapter_board_member(
                self.chapter_fin.name, self.fin_user.name, required_permission_levels=["Financial"]
            )
        )
        # ...but not an "Admin" requirement.
        self.assertFalse(
            is_chapter_board_member(
                self.chapter_fin.name, self.fin_user.name, required_permission_levels=["Admin"]
            )
        )

    # ---- get_chapters_with_permission --------------------------------------

    def test_get_chapters_with_permission(self):
        from verenigingen.services.chapter.chapter_utils import get_chapters_with_permission

        fin_chapters = get_chapters_with_permission("Financial", self.fin_user.name)
        self.assertIn(self.chapter_fin.name, fin_chapters)

        basic_chapters = get_chapters_with_permission("Basic", self.basic_user.name)
        self.assertIn(self.chapter_basic.name, basic_chapters)

    def test_get_chapters_with_permission_admin_returns_empty_list(self):
        """Admin gets None from get_user_accessible_chapters; wrapper coerces to []."""
        from verenigingen.services.chapter.chapter_utils import get_chapters_with_permission

        admin_user = self.create_test_user(
            email=f"cu-admin3-{self.token}@test.com", roles=["Verenigingen Administrator"]
        )
        self.assertEqual(get_chapters_with_permission("Financial", admin_user.name), [])


class TestChapterUtilsPrimaryChapter(EnhancedTestCase):
    """Cover get_member_primary_chapter (active chapter resolution)."""

    def setUp(self):
        super().setUp()
        import time

        token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        self.token = token
        self.chapter = self.create_chapter(chapter_name=f"PC Chapter {token}", region=_ensure_test_region())
        self.member = self.create_test_member(
            first_name="Primary", last_name="Member", email=f"pc-{token}@test.com"
        )

    def _add_chapter_member(self, chapter, member, status="Active", enabled=1, join_date=None):
        cm = frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter,
                "parenttype": "Chapter",
                "parentfield": "members",
                "member": member,
                "status": status,
                "enabled": enabled,
                "chapter_join_date": join_date or frappe.utils.today(),
            }
        )
        cm.insert()
        return cm

    def test_primary_chapter_empty_member(self):
        from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter

        self.assertIsNone(get_member_primary_chapter(""))

    def test_primary_chapter_none_when_no_membership(self):
        from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter

        self.assertIsNone(get_member_primary_chapter(self.member.name))

    def test_primary_chapter_active(self):
        from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter

        self._add_chapter_member(self.chapter.name, self.member.name)
        frappe.db.commit()
        self.assertEqual(get_member_primary_chapter(self.member.name), self.chapter.name)

    def test_primary_chapter_ignores_disabled_membership(self):
        from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter

        self._add_chapter_member(self.chapter.name, self.member.name, enabled=0)
        frappe.db.commit()
        self.assertIsNone(get_member_primary_chapter(self.member.name))

    def test_primary_chapter_ignores_inactive_status(self):
        from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter

        self._add_chapter_member(self.chapter.name, self.member.name, status="Inactive")
        frappe.db.commit()
        self.assertIsNone(get_member_primary_chapter(self.member.name))

    def test_primary_chapter_picks_most_recent_join(self):
        from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter

        older_chapter = self.create_chapter(
            chapter_name=f"PC Older {self.token}", region=_ensure_test_region()
        )
        self._add_chapter_member(
            older_chapter.name, self.member.name, join_date=frappe.utils.add_days(frappe.utils.today(), -30)
        )
        self._add_chapter_member(self.chapter.name, self.member.name, join_date=frappe.utils.today())
        frappe.db.commit()
        # ORDER BY chapter_join_date DESC LIMIT 1 -> most recently joined chapter
        self.assertEqual(get_member_primary_chapter(self.member.name), self.chapter.name)


class TestChapterUtilsDuesSplit(EnhancedTestCase):
    """Cover the dues-split wrapper functions and whitelisted info endpoint."""

    def setUp(self):
        super().setUp()
        import time

        token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        self.token = token
        self.chapter = self.create_chapter(chapter_name=f"DS Chapter {token}", region=_ensure_test_region())

    def test_get_chapter_split_percentage_default(self):
        from verenigingen.services.chapter.chapter_utils import get_chapter_split_percentage

        # With no per-chapter override (None or 0 both mean "use the default" per
        # SplitPercentage.from_chapter) the wrapper returns the configured default.
        # Derive the expected value from settings (site-independent) rather than
        # hardcoding it.
        override = frappe.db.get_value("Chapter", self.chapter.name, "chapter_split_percentage")
        self.assertIn(override, (None, 0, 0.0), f"Fresh chapter should have no override, got {override}")
        # Mirror SplitPercentage.from_chapter exactly (domain/chapter_dues.py): a
        # configured default is used as-is INCLUDING 0.0; only an UNSET (None) default
        # falls back to 60.0. `or 60.0` is wrong because 0.0 is falsy -> would expect
        # 60.0 on a site that configures 0, while production returns 0.
        settings_default = frappe.db.get_single_value(
            "Verenigingen Settings", "default_chapter_split_percentage"
        )
        expected_default = float(settings_default) if settings_default is not None else 60.0
        pct = get_chapter_split_percentage(self.chapter.name)
        self.assertIsInstance(pct, float)
        self.assertEqual(pct, expected_default)

    def test_get_chapter_split_percentage_custom(self):
        from verenigingen.services.chapter.chapter_utils import get_chapter_split_percentage

        frappe.db.set_value("Chapter", self.chapter.name, "chapter_split_percentage", 75)
        frappe.db.commit()
        self.assertEqual(get_chapter_split_percentage(self.chapter.name), 75.0)

    def test_calculate_dues_split_sums_to_total(self):
        from verenigingen.services.chapter.chapter_utils import calculate_dues_split

        result = calculate_dues_split(100.0, self.chapter.name)
        self.assertIn("chapter_amount", result)
        self.assertIn("national_amount", result)
        self.assertAlmostEqual(result["chapter_amount"] + result["national_amount"], 100.0, places=2)
        self.assertAlmostEqual(result["chapter_percentage"] + result["national_percentage"], 100.0, places=2)

    def test_calculate_dues_split_respects_custom_percentage(self):
        from verenigingen.services.chapter.chapter_utils import calculate_dues_split

        frappe.db.set_value("Chapter", self.chapter.name, "chapter_split_percentage", 40)
        frappe.db.commit()
        result = calculate_dues_split(200.0, self.chapter.name)
        self.assertAlmostEqual(result["chapter_amount"], 80.0, places=2)
        self.assertAlmostEqual(result["national_amount"], 120.0, places=2)

    def test_get_chapter_split_info_default(self):
        from verenigingen.services.chapter.chapter_utils import get_chapter_split_info

        info = get_chapter_split_info(self.chapter.name)
        self.assertEqual(info["chapter_name"], self.chapter.name)
        self.assertAlmostEqual(info["chapter_percentage"] + info["national_percentage"], 100.0, places=2)
        self.assertTrue(info["uses_default"])

    def test_get_chapter_split_info_custom_not_default(self):
        from verenigingen.services.chapter.chapter_utils import get_chapter_split_info

        frappe.db.set_value("Chapter", self.chapter.name, "chapter_split_percentage", 55)
        frappe.db.commit()
        info = get_chapter_split_info(self.chapter.name)
        self.assertEqual(info["chapter_percentage"], 55.0)
        self.assertEqual(info["national_percentage"], 45.0)
        self.assertFalse(info["uses_default"])


class TestChapterUtilsCacheInvalidation(EnhancedTestCase):
    """Cover invalidate_chapter_access_cache (no-raise behavior)."""

    def test_invalidate_for_explicit_user(self):
        from verenigingen.services.chapter.chapter_utils import invalidate_chapter_access_cache

        # Should not raise even if keys are absent.
        invalidate_chapter_access_cache("nobody@example.com")

    def test_invalidate_for_current_user(self):
        from verenigingen.services.chapter.chapter_utils import invalidate_chapter_access_cache

        invalidate_chapter_access_cache()


if __name__ == "__main__":
    unittest.main()
