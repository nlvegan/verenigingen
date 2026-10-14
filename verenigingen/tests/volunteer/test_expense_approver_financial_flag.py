"""
#1650: the automatic expense approver keys on ``Chapter Role.permissions_level``.

Rulings (maintainer, 2026-10-12 / 2026-10-14):
  * only the ``Financial`` permissions level makes a chapter seat a financial seat;
    a role NAME ("Treasurer", "Board Chair", ...) means nothing, and chapter ``Admin``
    does NOT imply financial rights;
  * a chapter treasurer does not approve their own claim: it goes to the national
    treasurer.

Fixtures are real documents built through the factory. The only direct write is
``Verenigingen Settings.national_board_chapter`` via ``set_single_value`` (a config
INPUT, restored in a cleanup); no state under test is set by a shortcut.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseApproverFinancialFlag(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="FlagSubj", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    def tearDown(self):
        if hasattr(frappe.local, "_volunteer_assignment_cache"):
            delattr(frappe.local, "_volunteer_assignment_cache")
        super().tearDown()

    # ------------------------------------------------------------------ helpers
    def _approver_service(self, volunteer_name=None):
        from verenigingen.services.volunteer.expense_approver_service import (
            VolunteerExpenseApproverService,
        )

        return VolunteerExpenseApproverService(volunteer_name or self.volunteer.name)

    def _role(self, level, name=None):
        """A fresh Chapter Role at ``level`` (unique name unless one is given)."""
        name = name or f"Flag{level}{frappe.generate_hash(length=6)}"
        role = self.factory.ensure_chapter_role(name, {"permissions_level": level})
        if role.permissions_level != level:
            # A shared, pre-existing role of this name: pin its level for this test only.
            previous = role.permissions_level
            frappe.db.set_value("Chapter Role", role.name, "permissions_level", level)
            self.addCleanup(frappe.db.set_value, "Chapter Role", role.name, "permissions_level", previous)
        return role.name

    def _flag_user(self, prefix):
        return self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])

    def _volunteer_with_user(self, prefix):
        user = self._flag_user(prefix)
        member = self.create_test_member(first_name="Flag", last_name=prefix, birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        frappe.db.set_value("Volunteer", volunteer.name, "email", user.email, update_modified=False)
        return volunteer, user

    def _flag_chapter(self, hint):
        return self.ensure_test_chapter(f"Flag{hint}{frappe.generate_hash(length=4)}")

    def _flag_seat(self, chapter_name, volunteer_name, role):
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter.save()

    def _stagger_seat_creation(self, chapter_name, first_is_older):
        """Give the seats distinct `creation` stamps (child rows inherit the parent's, so a
        creation-ordered query would tie). PROBE SHORTCUT: written straight to the DB so that
        idx order and creation order demonstrably disagree; an idx-ordered query is
        unaffected, any creation-ordered one picks the wrong seat in one of the two cases."""
        rows = frappe.get_all(
            "Chapter Board Member", filters={"parent": chapter_name}, pluck="name", order_by="idx asc"
        )
        stamps = ["2020-01-01 00:00:00", "2021-01-01 00:00:00"]
        if not first_is_older:
            stamps.reverse()
        for row, stamp in zip(rows, stamps):
            frappe.db.set_value("Chapter Board Member", row, "creation", stamp, update_modified=False)

    def _flag_join(self, chapter_name, member_name):
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append("members", {"member": member_name, "enabled": 1})
        chapter.save()

    def _make_national(self, chapter_name):
        previous = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", chapter_name)
        self.addCleanup(
            frappe.db.set_single_value, "Verenigingen Settings", "national_board_chapter", previous
        )

    # ------------------------------------------------------------ flag, not name
    def test_financial_seat_with_a_non_listed_name_is_the_approver(self):
        """veg11's real treasurer role is 'Penningmeester': a name no list contains."""
        chapter = self._flag_chapter("Pen")
        vol, user = self._volunteer_with_user("pen")
        self._flag_seat(chapter.name, vol.name, self._role("Financial", f"Penningmeester{frappe.generate_hash(length=4)}"))

        self.assertEqual(self._approver_service().get_board_financial_approver(chapter.name), user.email)

    def test_admin_level_seat_named_treasurer_is_not_an_approver(self):
        """veg11's 'Treasurer' role is level Admin. Admin does not imply financial."""
        chapter = self._flag_chapter("AdmTr")
        vol, _user = self._volunteer_with_user("admtr")
        self._flag_seat(chapter.name, vol.name, self._role("Admin", "Treasurer"))

        self.assertIsNone(self._approver_service().get_board_financial_approver(chapter.name))

    def test_admin_level_seat_with_any_name_is_not_an_approver(self):
        chapter = self._flag_chapter("Adm")
        vol, _user = self._volunteer_with_user("adm")
        self._flag_seat(chapter.name, vol.name, self._role("Admin"))

        self.assertIsNone(self._approver_service().get_board_financial_approver(chapter.name))

    def test_basic_level_seat_named_board_chair_is_not_an_approver(self):
        chapter = self._flag_chapter("Chair")
        vol, _user = self._volunteer_with_user("chair")
        self._flag_seat(chapter.name, vol.name, self._role("Basic", "Board Chair"))

        self.assertIsNone(self._approver_service().get_board_financial_approver(chapter.name))

    def test_financial_seat_is_picked_over_admin_seat_on_the_same_board(self):
        chapter = self._flag_chapter("Mix")
        admin_vol, _admin_user = self._volunteer_with_user("mixadm")
        fin_vol, fin_user = self._volunteer_with_user("mixfin")
        self._flag_seat(chapter.name, admin_vol.name, self._role("Admin", "Treasurer"))
        self._flag_seat(chapter.name, fin_vol.name, self._role("Financial"))

        self.assertEqual(self._approver_service().get_board_financial_approver(chapter.name), fin_user.email)

    # ------------------------------------------------- no self-approval (ruling)
    def test_chapter_treasurer_gets_the_national_treasurer_not_themselves(self):
        chapter = self._flag_chapter("Self")
        self._flag_join(chapter.name, self.member.name)
        self._flag_seat(chapter.name, self.volunteer.name, self._role("Financial"))
        frappe.db.set_value("Volunteer", self.volunteer.name, "email", self._flag_user("selfuser").email)

        national = self._flag_chapter("Natl")
        natl_vol, natl_user = self._volunteer_with_user("natl")
        self._flag_seat(national.name, natl_vol.name, self._role("Financial"))
        self._make_national(national.name)
        # The generic fallback picks the newest enabled user; a newer one than the national
        # treasurer makes sure this test cannot pass by that fallback happening to land there.
        self._flag_user("decoy")

        self.assertEqual(self._approver_service().get_expense_approver(), natl_user.email)

    def test_chapter_treasurer_is_never_their_own_approver_without_a_national_board(self):
        chapter = self._flag_chapter("SelfNo")
        self._flag_join(chapter.name, self.member.name)
        own_user = self._flag_user("selfonly")
        frappe.db.set_value("Volunteer", self.volunteer.name, "email", own_user.email)
        self._flag_seat(chapter.name, self.volunteer.name, self._role("Financial"))
        self._make_national(None)

        self.assertNotEqual(self._approver_service().get_expense_approver(), own_user.email)

    def test_chapter_member_still_gets_their_chapter_treasurer(self):
        """Control: the exclusion must not redirect an ordinary member's claim."""
        chapter = self._flag_chapter("Ctl")
        self._flag_join(chapter.name, self.member.name)
        treas_vol, treas_user = self._volunteer_with_user("ctltreas")
        self._flag_seat(chapter.name, treas_vol.name, self._role("Financial"))

        national = self._flag_chapter("CtlNatl")
        natl_vol, natl_user = self._volunteer_with_user("ctlnatl")
        self._flag_seat(national.name, natl_vol.name, self._role("Financial"))
        self._make_national(national.name)

        approver = self._approver_service().get_expense_approver()
        self.assertEqual(approver, treas_user.email)
        self.assertNotEqual(approver, natl_user.email)

    def test_team_path_excludes_a_treasurer_approving_their_own_claim(self):
        chapter = self._flag_chapter("TeamSelf")
        own_user = self._flag_user("teamself")
        frappe.db.set_value("Volunteer", self.volunteer.name, "email", own_user.email)
        self._flag_seat(chapter.name, self.volunteer.name, self._role("Financial"))
        team = self.create_test_team(team_name="FlagTeam")
        frappe.db.set_value("Team", team.name, "chapter", chapter.name, update_modified=False)
        self.create_test_team_member(team.name, self.volunteer.name)

        self.assertIsNone(self._approver_service()._get_team_member_approver())

    # ------------------------------------------------- the other name-list copies
    def test_department_approvers_follow_the_flag(self):
        from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

        chapter = self._flag_chapter("Dept")
        adm_vol, _adm_user = self._volunteer_with_user("deptadm")
        self._flag_seat(chapter.name, adm_vol.name, self._role("Admin", "Treasurer"))
        self.assertEqual(DepartmentHierarchyManager()._get_financial_approvers(chapter.name), [])

        fin_vol, fin_user = self._volunteer_with_user("deptfin")
        self._flag_seat(chapter.name, fin_vol.name, self._role("Financial"))
        self.assertEqual(DepartmentHierarchyManager()._get_financial_approvers(chapter.name), [fin_user.email])

    def test_department_sync_hook_recognises_financial_roles_by_flag(self):
        from verenigingen.services.volunteer.department_approver_sync import get_financial_roles

        fin = self._role("Financial")
        admin = self._role("Admin", "Treasurer")
        roles = get_financial_roles()
        self.assertIn(fin, roles)
        self.assertNotIn(admin, roles)

    # ------------------------------------------- nobody to approve: left unassigned
    def _expense_approver_role_count(self):
        return frappe.db.count("Has Role", {"role": "Expense Approver", "parenttype": "User"})

    def test_no_financial_seat_anywhere_leaves_the_claim_unassigned(self):
        """Ruling (2026-10-14): no chapter/team/national Financial seat -> no approver, and
        nobody is auto-granted Expense Approver. A chapter with only a Basic seat and an
        enabled newer user (what the old generic fallback would have picked) is the row a
        wrong 'fall back to some user' fix would find."""
        chapter = self._flag_chapter("Unassigned")
        self._flag_join(chapter.name, self.member.name)
        basic_vol, _basic_user = self._volunteer_with_user("unasbasic")
        self._flag_seat(chapter.name, basic_vol.name, self._role("Basic"))
        self._make_national(None)
        self._flag_user("unasnewest")
        before = self._expense_approver_role_count()

        self.assertIsNone(self._approver_service().get_expense_approver())
        self.assertEqual(self._expense_approver_role_count(), before)

    def test_unknown_volunteer_is_an_error_not_an_unassigned_claim(self):
        with self.assertRaises(frappe.DoesNotExistError):
            self._approver_service("VOL-DOES-NOT-EXIST-1650").get_expense_approver()

    def test_sole_national_treasurer_is_not_routed_to_themselves(self):
        """Their own claim: the national step excludes them, and nothing else is left."""
        national = self._flag_chapter("NatSole")
        frappe.db.set_value("Volunteer", self.volunteer.name, "email", self._flag_user("natsole").email)
        self._flag_seat(national.name, self.volunteer.name, self._role("Financial"))
        self._make_national(national.name)
        self._flag_user("natdecoy")

        self.assertIsNone(self._approver_service().get_expense_approver())

    # ------------------------------------------------ which Financial seat wins
    def test_first_financial_seat_in_board_order_wins(self):
        """Child rows inherit the parent's creation timestamp, so the seat order the user
        sees (idx) decides, not creation."""
        role = self._role("Financial")
        first_vol, first_user = self._volunteer_with_user("seatfirst")
        second_vol, second_user = self._volunteer_with_user("seatsecond")
        # Which volunteer sits first alternates, and the seats' creation stamps are staggered
        # both ways (see _stagger_seat_creation), so creation asc and creation desc each fail.
        service = self._approver_service()
        for index in range(6):
            seats = [(first_vol, first_user), (second_vol, second_user)]
            if index % 2:
                seats.reverse()
            chapter = self._flag_chapter(f"Order{index}")
            for volunteer, _user in seats:
                self._flag_seat(chapter.name, volunteer.name, role)
            self._stagger_seat_creation(chapter.name, first_is_older=index % 4 < 2)
            self.assertEqual(service.get_board_financial_approver(chapter.name), seats[0][1].email)

    def test_department_approver_follows_board_order(self):
        from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

        role = self._role("Financial")
        first_vol, first_user = self._volunteer_with_user("deptfirst")
        second_vol, second_user = self._volunteer_with_user("deptsecond")
        manager = DepartmentHierarchyManager()
        # Several chapters with alternating seat order: tie order other than idx is arbitrary
        # per chapter, so a wrong order cannot pass by a single coin flip.
        for index in range(6):
            seats = [(first_vol, first_user), (second_vol, second_user)]
            if index % 2:
                seats.reverse()
            chapter = self._flag_chapter(f"DeptOrder{index}")
            for volunteer, _user in seats:
                self._flag_seat(chapter.name, volunteer.name, role)
            self._stagger_seat_creation(chapter.name, first_is_older=index % 4 < 2)
            self.assertEqual(manager._get_financial_approvers(chapter.name), [seats[0][1].email])

    def test_inactive_financial_role_is_not_financial(self):
        chapter = self._flag_chapter("InactiveRole")
        vol, _user = self._volunteer_with_user("inactiverole")
        role = self._role("Financial")
        self._flag_seat(chapter.name, vol.name, role)
        frappe.db.set_value("Chapter Role", role, "is_active", 0)

        self.assertIsNone(self._approver_service().get_board_financial_approver(chapter.name))
