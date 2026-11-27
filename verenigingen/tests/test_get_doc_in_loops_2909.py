"""
#2909: per-row ``frappe.get_doc`` inside ``get_all`` loops.

Each test drives the REAL function with N > 1 real rows and does two things:
  * asserts the RETURNED DATA (the rewrite must not change a result), and
  * counts the SQL statements issued while the function runs.

Cache warming: the table-column list (`table_columns::tab<DocType>`, Redis-backed) and the
DocType meta are warmed BEFORE the measured window, otherwise a cold cache adds queries
inside it and the count depends on what ran earlier in the shard.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _count_sql_2909(fn):
    """Run ``fn`` and return ``(its result, [every SQL string executed])``."""
    queries = []
    cls = frappe.db.__class__
    original = cls.sql

    def counting_sql(self, query, *args, **kwargs):
        queries.append(str(query))
        return original(self, query, *args, **kwargs)

    cls.sql = counting_sql
    try:
        result = fn()
    finally:
        cls.sql = original
    return result, queries


def _warm_2909(*doctypes):
    for dt in doctypes:
        frappe.get_meta(dt)
        frappe.db.get_table_columns(dt)


class TestGetDocInLoops2909(EnhancedTestCase):
    SEATS = 4

    def setUp(self):
        super().setUp()
        _warm_2909(
            "Chapter", "Chapter Role", "Chapter Board Member", "Chapter Member", "Volunteer", "User",
            "Member", "Email Group",
        )

    def _role(self, level):
        name = f"G2909{level}{frappe.generate_hash(length=6)}"
        return self.factory.ensure_chapter_role(name, {"permissions_level": level}).name

    def _seat(self, chapter_name, volunteer_name, role):
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append(
            "board_members",
            {"volunteer": volunteer_name, "chapter_role": role, "from_date": frappe.utils.today(), "is_active": 1},
        )
        chapter.save()

    def _volunteer(self, tag, with_user=True, enabled=1, with_email=True):
        member = self.create_test_member(first_name="G2909", last_name=tag, birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        user = None
        if with_user:
            user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
            if not enabled:
                frappe.db.set_value("User", user.name, "enabled", 0)
        if with_email and user:
            frappe.db.set_value("Volunteer", volunteer.name, "email", user.email, update_modified=False)
        return volunteer, user

    # ------------------------------------------------ expense_approver_service
    def _approver(self, volunteer_name):
        from verenigingen.services.volunteer.expense_approver_service import VolunteerExpenseApproverService

        return VolunteerExpenseApproverService(volunteer_name)

    def _approver_board(self):
        """SEATS seats at the same Financial role; the first SEATS-1 resolve to no usable
        approver (disabled user / no email / email without a User), the last to an enabled one."""
        chapter = self.ensure_test_chapter(f"G2909A{frappe.generate_hash(length=4)}")
        role = self._role("Financial")
        subject, _ = self._volunteer("subj", with_user=False)
        disabled, _ = self._volunteer("dis", enabled=0)
        no_email, _ = self._volunteer("noem", with_user=False)
        stray, _ = self._volunteer("stray", with_user=False)
        frappe.db.set_value("Volunteer", stray.name, "email", f"nobody-{frappe.generate_hash(length=6)}@example.com")
        good, good_user = self._volunteer("good")
        # The winning volunteer is reachable ONLY through personal_email: a rewrite that
        # drops the get_doc but forgets that field in its bulk read returns None here.
        frappe.db.set_value(
            "Volunteer", good.name, {"email": "", "personal_email": good_user.email}, update_modified=False
        )
        for vol in (disabled, no_email, stray, good):
            self._seat(chapter.name, vol.name, role)
        return chapter, subject, good_user

    def test_board_financial_approver_skips_unusable_seats_and_is_constant_query(self):
        chapter, subject, good_user = self._approver_board()
        service = self._approver(subject.name)

        result, queries = _count_sql_2909(lambda: service.get_board_financial_approver(chapter.name))

        self.assertEqual(result, good_user.email)
        per_seat = [q for q in queries if "`tabVolunteer`" in q or "`tabUser`" in q]
        # roles + seats + ONE volunteer read + ONE user read (+ the role top-up inside the
        # approver). Develop issues 2-3 per seat, i.e. 8+ for four seats.
        self.assertLessEqual(len(per_seat), 4, msg="\n\n".join(queries))

    def test_board_financial_approver_returns_none_when_nobody_usable(self):
        chapter = self.ensure_test_chapter(f"G2909N{frappe.generate_hash(length=4)}")
        subject, _ = self._volunteer("nsubj", with_user=False)
        role = self._role("Financial")
        disabled, _ = self._volunteer("ndis", enabled=0)
        no_email, _ = self._volunteer("nnoem", with_user=False)
        for vol in (disabled, no_email):
            self._seat(chapter.name, vol.name, role)
        self.assertIsNone(self._approver(subject.name).get_board_financial_approver(chapter.name))

    # -------------------------------------------- can_view_members_without_chapter
    def _board_member_user(self, levels):
        """A non-staff user whose volunteer holds one active seat per entry of ``levels``."""
        from verenigingen.api import member_management  # noqa: F401  (import warms the module)

        member = self.create_test_member(first_name="G2909V", last_name=frappe.generate_hash(length=5), birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        user = self.factory.create_user_with_roles(roles=["Verenigingen Member"])
        frappe.db.set_value("Member", member.name, "user", user.name, update_modified=False)
        for index, level in enumerate(levels):
            chapter = self.ensure_test_chapter(f"G2909V{index}{frappe.generate_hash(length=4)}")
            self._seat(chapter.name, volunteer.name, self._role(level))
        return user

    def _can_view_as(self, user):
        from verenigingen.api import member_management

        previous_user = frappe.session.user
        frappe.set_user(user.name)
        try:
            return _count_sql_2909(member_management.can_view_members_without_chapter)
        finally:
            frappe.set_user(previous_user)

    def test_can_view_false_with_many_non_admin_seats_and_constant_queries(self):
        user = self._board_member_user(["Basic"] * self.SEATS)
        result, queries = self._can_view_as(user)
        self.assertFalse(result)
        chapter_role_reads = [q for q in queries if "`tabChapter Role`" in q]
        self.assertLessEqual(len(chapter_role_reads), 1, msg="\n\n".join(queries))

    def test_can_view_true_when_any_seat_is_admin_level(self):
        user = self._board_member_user(["Basic", "Basic", "Admin", "Basic"])
        result, queries = self._can_view_as(user)
        self.assertTrue(result)

    def test_can_view_true_when_only_the_last_of_many_seats_is_admin(self):
        user = self._board_member_user(["Basic"] * (self.SEATS - 1) + ["Admin"])
        result, queries = self._can_view_as(user)
        self.assertTrue(result)
        self.assertLessEqual(len([q for q in queries if "`tabChapter Role`" in q]), 1)

    # ---------------------------------------------------------- email_group_sync
    def test_sync_member_on_change_does_not_load_chapter_docs(self):
        from verenigingen.email.email_group_sync import sync_member_on_change

        member = self.create_test_member(
            first_name="G2909E",
            last_name=frappe.generate_hash(length=5),
            email=f"g2909-{frappe.generate_hash(length=6)}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value("Member", member.name, "accepts_optional_communications", 1)
        member.reload()
        groups = []
        for index in range(self.SEATS):
            chapter = self.ensure_test_chapter(f"G2909E{index}{frappe.generate_hash(length=4)}")
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            chapter_doc.append("members", {"member": member.name, "enabled": 1, "chapter_join_date": frappe.utils.today()})
            chapter_doc.save()
            title = f"{chapter.name} - All Members"
            group = frappe.get_doc({"doctype": "Email Group", "title": title}).insert(ignore_permissions=True)
            groups.append(group.name)
        _warm_2909("Email Group Member", "Email Group")

        result, queries = _count_sql_2909(lambda: sync_member_on_change(member))

        self.assertTrue(result["success"], result)
        subscribed = frappe.get_all(
            "Email Group Member", filters={"email_group": ["in", groups], "email": member.email}, pluck="email_group"
        )
        self.assertEqual(sorted(subscribed), sorted(groups))
        chapter_doc_reads = [
            q for q in queries if "from `tabChapter` " in q.lower() or "from `tabchapter board member`" in q.lower()
        ]
        self.assertEqual(chapter_doc_reads, [], msg="\n\n".join(chapter_doc_reads))
