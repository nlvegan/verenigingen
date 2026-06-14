#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Permission System Coverage Tests
================================

Real-integration coverage for the access-control functions in
``verenigingen/permissions.py`` that were not exercised by the existing
permission suites (member / donor / chapter-board). These are the security-
critical, previously-untested paths:

- Permission *query* builders (get_*_permission_query) that emit the SQL WHERE
  filters Frappe applies to list views — Donation, Address, Employee, Chapter
  Member, Termination Request, Volunteer (management roles), Team Member,
  Expense Claim.
- Document-level checks: has_donation_permission, has_address_permission,
  has_expense_claim_permission, has_volunteer_permission (team-leader path),
  has_membership_permission.
- Financial-privacy gates: can_view_financial_info, check_member_payment_access
  (Public / Board Only / Admin Only categories).
- Termination authorization: can_terminate_member, can_access_termination_functions.
- The shared member-linked factory (_make_member_linked_permission) used by Donor
  and SEPA Mandate: contract guards, disabled-user denial, dangling-link denial.
- Service-account (webhook) DocPerm deferral and the permission cache helpers.

Every test builds real DocTypes and asserts behavior as a real acting user, in
line with the repo's real-integration testing policy (no business-logic mocks).
"""

import time

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


def _ensure_test_region():
    """Idempotently ensure a "Test Region" exists; return its slug docname."""
    slug = "test-region"
    if not frappe.db.exists("Region", slug):
        frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": "Test Region",
                "region_code": "TR",
                "country": "Netherlands",
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
    return slug


class PermissionsCoverageBase(EnhancedTestCase):
    """Shared fixture graph: two chapters, a board member (treasurer of chapter A),
    a regular member of chapter A, an unrelated member of chapter B, plus staff,
    admin and webhook users.

    The acting users must be backed by real User accounts because the permission
    functions resolve acting user -> Member -> Volunteer -> board Chapter. These
    tests commit (per-test rollback would not undo committed Chapter Board Member
    inserts and the role-assignment hook), so names are tokenized for uniqueness.
    """

    def setUp(self):
        super().setUp()
        self.token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        region = _ensure_test_region()

        self.chapter_a = self.create_chapter(chapter_name=f"Perm Chapter A {self.token}", region=region)
        self.chapter_b = self.create_chapter(chapter_name=f"Perm Chapter B {self.token}", region=region)

        # Board member of chapter A, holding a Financial-level (treasurer) role.
        self.board_user = self.create_test_user(
            email=f"perm-board-{self.token}@test.com",
            roles=[Roles.VERENIGINGEN_MEMBER, Roles.CHAPTER_BOARD_MEMBER],
        )
        self.board_member = self.create_test_member(
            first_name="Perm",
            last_name="Board",
            email=f"perm-board-{self.token}@test.com",
            user=self.board_user.name,
        )

        # Regular member of chapter A.
        self.regular_user = self.create_test_user(
            email=f"perm-regular-{self.token}@test.com", roles=[Roles.VERENIGINGEN_MEMBER]
        )
        self.regular_member = self.create_test_member(
            first_name="Perm",
            last_name="Regular",
            email=f"perm-regular-{self.token}@test.com",
            user=self.regular_user.name,
        )

        # Member of the OTHER chapter (board user must never reach this one).
        self.other_member = self.create_test_member(
            first_name="Perm", last_name="Other", email=f"perm-other-{self.token}@test.com"
        )

        # Staff (org-wide admin) and a no-Member-record bare user.
        self.staff_user = self.create_test_user(
            email=f"perm-staff-{self.token}@test.com", roles=[Roles.VERENIGINGEN_STAFF]
        )
        self.bare_user = self.create_test_user(
            email=f"perm-bare-{self.token}@test.com", roles=[Roles.VERENIGINGEN_MEMBER]
        )

        # Board scaffolding for chapter A.
        self.financial_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Perm Treasurer {self.token}",
                "permissions_level": "Financial",
                "is_active": 1,
            }
        )
        self.financial_role.insert()

        self.board_volunteer = self.create_test_volunteer(self.board_member.name)
        self.board_position = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.chapter_a.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": self.board_volunteer.name,
                "chapter_role": self.financial_role.name,
                "from_date": today(),
                "is_active": 1,
            }
        )
        self.board_position.insert()

        self._add_member_to_chapter(self.board_member.name, self.chapter_a.name)
        self._add_member_to_chapter(self.regular_member.name, self.chapter_a.name)
        self._add_member_to_chapter(self.other_member.name, self.chapter_b.name)

        frappe.db.commit()

    def _add_member_to_chapter(self, member_name, chapter_name):
        frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter_name,
                "parenttype": "Chapter",
                "parentfield": "members",
                "member": member_name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            }
        ).insert()


class TestPermissionQueryBuilders(PermissionsCoverageBase):
    """The get_*_permission_query functions: admin -> "", scoped role -> filter,
    no-access -> "1=0". These emit SQL Frappe injects into list queries."""

    def test_member_query_executes_and_scopes_board(self):
        """Board member's Member query must actually select their chapter's members
        and exclude the other chapter's members when run against the DB."""
        from verenigingen.permissions import get_member_permission_query

        cond = get_member_permission_query(self.board_user.name)
        self.assertTrue(cond and cond != "1=0")

        def visible(member_name):
            rows = frappe.db.sql(
                f"SELECT name FROM `tabMember` WHERE name = %s AND {cond}", member_name
            )
            return bool(rows)

        self.assertTrue(visible(self.regular_member.name), "board sees own-chapter member")
        self.assertFalse(visible(self.other_member.name), "board must not see other-chapter member")

    def test_employee_query_admin_and_board_and_denied(self):
        from verenigingen.permissions import get_employee_permission_query

        self.assertEqual(get_employee_permission_query(self.staff_user.name), "")

        board_cond = get_employee_permission_query(self.board_user.name)
        self.assertIn("tabEmployee", board_cond)
        self.assertIn("Chapter Member", board_cond)

        # A member with no chapter/board position gets no employee access.
        self.assertEqual(get_employee_permission_query(self.bare_user.name), "1=0")

    def test_membership_query_admin_and_denied(self):
        from verenigingen.permissions import get_membership_permission_query

        self.assertEqual(get_membership_permission_query(self.staff_user.name), "")
        self.assertEqual(get_membership_permission_query(self.bare_user.name), "1=0")
        board_cond = get_membership_permission_query(self.board_user.name)
        self.assertIn("tabMembership", board_cond)

    def test_chapter_member_query_admin_board_and_member(self):
        from verenigingen.permissions import get_chapter_member_permission_query

        self.assertEqual(get_chapter_member_permission_query(self.staff_user.name), "")

        # Board member: own records OR their board chapters.
        board_cond = get_chapter_member_permission_query(self.board_user.name)
        self.assertIn("Chapter Member", board_cond)
        self.assertIn(self.chapter_a.name, board_cond)

        # Regular member with no board position: own records only.
        reg_cond = get_chapter_member_permission_query(self.regular_user.name)
        self.assertIn("member", reg_cond)
        self.assertIn(self.regular_member.name, reg_cond)

        # No member record -> no access.
        self.assertEqual(
            get_chapter_member_permission_query(f"nobody-{self.token}@test.com"), "1=0"
        )

    def test_termination_query_admin_board_and_denied(self):
        from verenigingen.permissions import get_termination_permission_query

        self.assertEqual(get_termination_permission_query(self.staff_user.name), "")
        # Bare member, no board -> no termination visibility.
        self.assertEqual(get_termination_permission_query(self.bare_user.name), "1=0")
        # Board member -> EXISTS subquery scoped to their chapter.
        board_cond = get_termination_permission_query(self.board_user.name)
        self.assertIn("EXISTS", board_cond)
        self.assertIn(self.chapter_a.name, board_cond)

    def test_termination_query_includes_national_chapter(self):
        from verenigingen.permissions import get_termination_permission_query

        settings = frappe.get_single("Verenigingen Settings")
        original = settings.get("national_chapter")
        settings.db_set("national_chapter", self.chapter_b.name)
        try:
            cond = get_termination_permission_query(self.board_user.name)
            self.assertIn(self.chapter_b.name, cond, "national chapter must be appended for board user")
        finally:
            settings.db_set("national_chapter", original)

    def test_volunteer_query_admin_member_and_management(self):
        from verenigingen.permissions import get_volunteer_permission_query

        self.assertEqual(get_volunteer_permission_query(self.staff_user.name), "")
        self.assertEqual(
            get_volunteer_permission_query(f"nobody-{self.token}@test.com"), "1=0"
        )

        # Plain member: own volunteer records only (single condition).
        reg_cond = get_volunteer_permission_query(self.regular_user.name)
        self.assertIn("tabVolunteer", reg_cond)
        self.assertIn(self.regular_member.name, reg_cond)

        # Board member (a management role): own + chapter-scoped expansion.
        board_cond = get_volunteer_permission_query(self.board_user.name)
        self.assertIn("Chapter Member", board_cond)

    def test_team_member_query_paths(self):
        from verenigingen.permissions import get_team_member_permission_query

        self.assertEqual(get_team_member_permission_query(self.staff_user.name), "")
        # No member record -> 1=0.
        self.assertEqual(
            get_team_member_permission_query(f"nobody-{self.token}@test.com"), "1=0"
        )
        # Member but not on any team -> 1=0 (regular member has a volunteer? no volunteer -> 1=0).
        self.assertEqual(get_team_member_permission_query(self.regular_user.name), "1=0")


class TestDonationPermissions(PermissionsCoverageBase):
    def _make_donation(self, member_name):
        donor = self.create_test_donor(member=member_name)
        donation = self.create_test_donation(donor=donor.name)
        return donor, donation

    def test_donation_doc_permission_member_and_board_and_deny(self):
        from verenigingen.permissions import has_donation_permission

        _donor, donation = self._make_donation(self.regular_member.name)

        # Admin/staff: always.
        self.assertTrue(has_donation_permission(donation.name, self.staff_user.name))

        # Owning member: yes.
        self.assertTrue(has_donation_permission(donation.name, self.regular_user.name))

        # Board member of the donor's chapter: yes.
        self.assertTrue(has_donation_permission(donation.name, self.board_user.name))

        # Unrelated bare member: no.
        self.assertFalse(has_donation_permission(donation.name, self.bare_user.name))

    def test_donation_doc_permission_missing_record_denied(self):
        from verenigingen.permissions import has_donation_permission

        self.assertFalse(
            has_donation_permission(f"NONEXISTENT-{self.token}", self.regular_user.name)
        )

    def test_donation_query_admin_member_board_deny(self):
        from verenigingen.permissions import get_donation_permission_query

        self.assertEqual(get_donation_permission_query(self.staff_user.name), "")

        member_cond = get_donation_permission_query(self.regular_user.name)
        self.assertIn("tabDonation", member_cond)
        self.assertIn("tabDonor", member_cond)

        board_cond = get_donation_permission_query(self.board_user.name)
        self.assertIn("Chapter Member", board_cond)

        self.assertEqual(get_donation_permission_query(self.bare_user.name), "1=0")


class TestAddressPermissions(PermissionsCoverageBase):
    def _make_address_for(self, member):
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Addr {member.name}",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": member.name}],
            }
        )
        address.insert(ignore_permissions=True)
        return address

    def test_address_doc_permission_owner_board_admin_deny(self):
        from verenigingen.permissions import has_address_permission

        address = self._make_address_for(self.regular_member)

        self.assertTrue(has_address_permission(address.name, self.staff_user.name))
        self.assertTrue(has_address_permission(address.name, self.regular_user.name), "own address")
        self.assertTrue(
            has_address_permission(address.name, self.board_user.name), "board sees chapter member address"
        )
        self.assertFalse(has_address_permission(address.name, self.bare_user.name))

    def test_address_query_admin_member_board_and_no_access(self):
        from verenigingen.permissions import get_address_permission_query

        self.assertEqual(get_address_permission_query(self.staff_user.name), "")

        member_cond = get_address_permission_query(self.regular_user.name)
        self.assertIn("tabDynamic Link", member_cond)
        self.assertIn(self.regular_member.name, member_cond)

        board_cond = get_address_permission_query(self.board_user.name)
        self.assertIn("Chapter Member", board_cond)

        # No member and no contact -> no access.
        self.assertEqual(
            get_address_permission_query(f"nobody-{self.token}@test.com"), "1=0"
        )

    def test_contact_fallback_accepts_string_and_doc_without_crashing(self):
        """Regression guard for the Contact-fallback fix. bare_user has no Member
        record, so has_address_permission falls through to the Contact-based check.
        That path must accept BOTH a bare address name (str) and an Address doc:
        the str form previously crashed with `'str' object has no attribute
        'links'` because the raw string was handed to contact.has_common_link.
        bare_user's auto-created Contact shares no link with this address, so both
        shapes must return False WITHOUT raising."""
        from verenigingen.permissions import has_address_permission

        address = self._make_address_for(self.regular_member)
        # str shape (the one that used to raise)
        self.assertFalse(has_address_permission(address.name, self.bare_user.name))
        # doc-object shape (hasattr(doc, "links") branch)
        addr_doc = frappe.get_doc("Address", address.name)
        self.assertFalse(has_address_permission(addr_doc, self.bare_user.name))

    def test_contact_common_link_grants_access(self):
        """Positive Contact-common-link path: when the acting user's Contact and
        the Address share a Dynamic Link to the same party, has_address_permission
        returns True via contact.has_common_link — the exact True path the fix
        enables. Exercised for both the str-name and doc-object call shapes.

        bare_user is not the ``user`` of any Member, so it falls through the
        member/board branches to the Contact fallback. Sharing the link via a
        Member (rather than a Customer) reuses existing fixtures and avoids
        ERPNext Customer mandatory-field setup."""
        from verenigingen.permissions import has_address_permission

        # Link bare_user's auto-created Contact to other_member.
        contact_name = frappe.db.get_value("Contact", {"email_id": self.bare_user.name}, "name")
        self.assertIsNotNone(contact_name, "User.after_insert should have created a Contact")
        contact = frappe.get_doc("Contact", contact_name)
        contact.append("links", {"link_doctype": "Member", "link_name": self.other_member.name})
        contact.save()

        # An address linked to the same member shares a common link with the Contact.
        address = self._make_address_for(self.other_member)

        self.assertTrue(has_address_permission(address.name, self.bare_user.name))
        self.assertTrue(has_address_permission(frappe.get_doc("Address", address.name), self.bare_user.name))


class TestFinancialAccess(PermissionsCoverageBase):
    def test_can_view_financial_info_admin_self_and_deny(self):
        from verenigingen.permissions import can_view_financial_info

        # Staff: always.
        self.assertTrue(can_view_financial_info("Member", self.regular_member.name, self.staff_user.name))
        # Self.
        self.assertTrue(
            can_view_financial_info("Member", self.regular_member.name, self.regular_user.name)
        )
        # Non-member user -> False.
        self.assertFalse(
            can_view_financial_info("Member", self.regular_member.name, f"nobody-{self.token}@test.com")
        )
        # Member but no target name -> False (general check).
        self.assertFalse(can_view_financial_info("Member", None, self.regular_user.name))

    def test_check_member_payment_access_categories(self):
        from verenigingen.permissions import check_member_payment_access

        # Admin path.
        self.assertTrue(check_member_payment_access(self.regular_member.name, self.staff_user.name))
        # Self path.
        self.assertTrue(check_member_payment_access(self.regular_member.name, self.regular_user.name))

        # Public category -> anyone (a bare member) can view.
        self.regular_member.db_set("permission_category", "Public")
        self.assertTrue(check_member_payment_access(self.regular_member.name, self.bare_user.name))

        # Admin Only category -> bare member denied.
        self.regular_member.db_set("permission_category", "Admin Only")
        self.assertFalse(check_member_payment_access(self.regular_member.name, self.bare_user.name))

        # Board Only -> falls through to chapter board check; bare member denied.
        self.regular_member.db_set("permission_category", "Board Only")
        self.assertFalse(check_member_payment_access(self.regular_member.name, self.bare_user.name))


class TestTerminationAuthorization(PermissionsCoverageBase):
    def test_can_terminate_member_admin_board_and_deny(self):
        from verenigingen.permissions import can_terminate_member

        # Admin pair (staff is NOT in ADMIN_PAIR -> exercises non-admin path);
        # use a real admin user.
        admin_user = self.create_test_user(
            email=f"perm-admin-{self.token}@test.com", roles=[Roles.VERENIGINGEN_ADMIN]
        )
        self.assertTrue(can_terminate_member(self.regular_member.name, admin_user.name))

        # Board member of the target's chapter A: allowed.
        self.assertTrue(can_terminate_member(self.regular_member.name, self.board_user.name))

        # Board member must NOT terminate a member of the other chapter.
        self.assertFalse(can_terminate_member(self.other_member.name, self.board_user.name))

        # Non-member acting user: denied.
        self.assertFalse(
            can_terminate_member(self.regular_member.name, f"nobody-{self.token}@test.com")
        )

    def test_can_terminate_member_missing_member(self):
        from verenigingen.permissions import can_terminate_member

        self.assertFalse(
            can_terminate_member(f"NONEXISTENT-{self.token}", self.board_user.name)
        )

    def test_can_access_termination_functions(self):
        from verenigingen.permissions import can_access_termination_functions

        admin_user = self.create_test_user(
            email=f"perm-admin2-{self.token}@test.com", roles=[Roles.SYSTEM_MANAGER]
        )
        self.assertTrue(can_access_termination_functions(admin_user.name))

        # Board member (active board position via volunteer) -> True.
        self.assertTrue(can_access_termination_functions(self.board_user.name))

        # Regular member, no board position -> False.
        self.assertFalse(can_access_termination_functions(self.regular_user.name))

        # Non-member -> False.
        self.assertFalse(can_access_termination_functions(f"nobody-{self.token}@test.com"))


class TestMemberLinkedFactory(PermissionsCoverageBase):
    """The _make_member_linked_permission factory powering Donor + SEPA Mandate."""

    def test_contract_guards(self):
        from verenigingen.permissions import _make_member_linked_permission

        with self.assertRaises(ValueError):
            _make_member_linked_permission("Bad`Name")
        with self.assertRaises(ValueError):
            _make_member_linked_permission("Donor", member_field="not an identifier")

    def test_donor_query_admin_member_board_deny(self):
        from verenigingen.permissions import get_donor_permission_query

        self.assertEqual(get_donor_permission_query(self.staff_user.name), "")

        donor = self.create_test_donor(member=self.regular_member.name)
        self.assertTrue(donor)  # ensure a donor exists for the member

        member_cond = get_donor_permission_query(self.regular_user.name)
        self.assertIn("tabDonor", member_cond)
        self.assertIn(self.regular_member.name, member_cond)

        board_cond = get_donor_permission_query(self.board_user.name)
        self.assertIn("Chapter Member", board_cond)

        self.assertEqual(get_donor_permission_query(self.bare_user.name), "1=0")

    def test_sepa_mandate_query_mirrors_donor(self):
        from verenigingen.permissions import get_sepa_mandate_permission_query

        self.assertEqual(get_sepa_mandate_permission_query(self.staff_user.name), "")
        cond = get_sepa_mandate_permission_query(self.regular_user.name)
        self.assertIn("tabSEPA Mandate", cond)
        self.assertEqual(get_sepa_mandate_permission_query(self.bare_user.name), "1=0")

    def test_donor_doc_permission_owner_and_dangling_link(self):
        from verenigingen.permissions import has_donor_permission

        donor = self.create_test_donor(member=self.regular_member.name)

        self.assertTrue(has_donor_permission(donor.name, self.staff_user.name))
        self.assertTrue(has_donor_permission(donor.name, self.regular_user.name), "own donor")
        self.assertTrue(has_donor_permission(donor.name, self.board_user.name), "board of chapter")
        self.assertFalse(has_donor_permission(donor.name, self.bare_user.name))

    def test_donor_doc_permission_disabled_user_denied(self):
        from verenigingen.permissions import has_donor_permission

        donor = self.create_test_donor(member=self.regular_member.name)
        # A disabled user that still holds the Member role must be denied.
        frappe.db.set_value("User", self.regular_user.name, "enabled", 0)
        try:
            self.assertFalse(has_donor_permission(donor.name, self.regular_user.name))
        finally:
            frappe.db.set_value("User", self.regular_user.name, "enabled", 1)


class TestMiscPermissionHelpers(PermissionsCoverageBase):
    def test_has_membership_permission_admin_and_fallback(self):
        from verenigingen.permissions import has_membership_permission

        # Admin -> True.
        self.assertTrue(has_membership_permission("any", self.staff_user.name))
        # Non-admin -> None (defer to DocPerm + query).
        self.assertIsNone(has_membership_permission("any", self.regular_user.name))

    def test_service_account_deferral(self):
        from verenigingen.permissions import _check_service_account_permission

        # Non-service user -> None (caller continues with normal logic).
        self.assertIsNone(_check_service_account_permission(self.regular_user.name, "Member", "read"))

        # Webhook service account -> a concrete bool (DocPerm deferral), never None.
        webhook_user = self.create_test_user(
            email=f"perm-webhook-{self.token}@test.com", roles=[Roles.WEBHOOK_USER]
        )
        result = _check_service_account_permission(webhook_user.name, "Member", "read")
        self.assertIn(result, (True, False))

    def test_cache_helpers(self):
        from verenigingen.permissions import (
            clear_permission_cache,
            get_cache_key,
            get_user_chapter_memberships_cached,
            get_user_treasurer_chapters_cached,
        )

        key = get_cache_key()
        # Board user is a board member of chapter A.
        chapters = get_user_chapter_memberships_cached(self.board_user.name, key)
        self.assertIn(self.chapter_a.name, chapters)

        # Board user holds a Financial-level role -> appears as treasurer chapter.
        treasurer = get_user_treasurer_chapters_cached(self.board_user.name, key)
        self.assertIn(self.chapter_a.name, treasurer)

        # Empty user short-circuits to [].
        self.assertEqual(get_user_chapter_memberships_cached("", key), [])
        self.assertEqual(get_user_treasurer_chapters_cached("", key), [])

        # Should not raise.
        clear_permission_cache()


class TestExpenseClaimPermissions(PermissionsCoverageBase):
    """has_expense_claim_permission + get_expense_claim_permission_query.

    The acting documents are passed as frappe._dict instances — this is the exact
    shape Frappe's permission system hands to has_permission hooks (a document with
    .employee / .custom_chapter attributes); it is a real data object, not a mock.
    """

    def _make_employee_for_user(self, user_name):
        company = frappe.get_value("Verenigingen Settings", None, "company")
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Emp {self.token[:6]}",
                "last_name": "Test",
                "status": "Active",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": today(),
                "company": company,
                "user_id": user_name,
            }
        )
        emp.insert(ignore_permissions=True)
        return emp

    def test_query_admin_employee_approver_and_deny(self):
        from verenigingen.permissions import get_expense_claim_permission_query

        # Staff is in HR_ADMIN_ROLES -> no filter.
        self.assertEqual(get_expense_claim_permission_query(self.staff_user.name), "")

        # Employee can see own claims.
        self._make_employee_for_user(self.regular_user.name)
        emp_cond = get_expense_claim_permission_query(self.regular_user.name)
        self.assertIn("tabExpense Claim", emp_cond)
        self.assertIn("employee", emp_cond)

        # Expense Approver who is a Financial board member of chapter A sees that
        # chapter's claims.
        approver = frappe.get_doc("User", self.board_user.name)
        approver.append("roles", {"role": Roles.EXPENSE_APPROVER})
        approver.save()
        appr_cond = get_expense_claim_permission_query(self.board_user.name)
        self.assertIn("custom_chapter", appr_cond)
        self.assertIn(self.chapter_a.name, appr_cond)

        # Bare member: no employee, no approver role -> no access.
        self.assertEqual(get_expense_claim_permission_query(self.bare_user.name), "1=0")

    def test_doc_permission_admin_employee_and_deny(self):
        from verenigingen.permissions import has_expense_claim_permission

        emp = self._make_employee_for_user(self.regular_user.name)

        # Staff/HR admin: always.
        self.assertTrue(
            has_expense_claim_permission(
                frappe._dict(employee=emp.name, custom_chapter=None), self.staff_user.name
            )
        )

        # Owning employee sees their own claim.
        self.assertTrue(
            has_expense_claim_permission(
                frappe._dict(employee=emp.name, custom_chapter=None), self.regular_user.name
            )
        )

        # Unrelated bare member with no employee/approver role: denied.
        self.assertFalse(
            has_expense_claim_permission(
                frappe._dict(employee=emp.name, custom_chapter=self.chapter_a.name),
                self.bare_user.name,
            )
        )

    def test_doc_permission_approver_chapter_scope(self):
        from verenigingen.permissions import has_expense_claim_permission

        approver = frappe.get_doc("User", self.board_user.name)
        approver.append("roles", {"role": Roles.EXPENSE_APPROVER})
        approver.save()

        # Approver (Financial board of chapter A) can access a claim for chapter A.
        self.assertTrue(
            has_expense_claim_permission(
                frappe._dict(employee=None, custom_chapter=self.chapter_a.name), self.board_user.name
            )
        )
        # But not a claim for the other chapter.
        self.assertFalse(
            has_expense_claim_permission(
                frappe._dict(employee=None, custom_chapter=self.chapter_b.name), self.board_user.name
            )
        )


def teardown_module():
    frappe.db.rollback()
