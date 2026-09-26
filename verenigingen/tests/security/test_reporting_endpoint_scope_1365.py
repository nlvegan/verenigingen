"""Caller-scoping tests for four @standard_api(REPORTING) listings found by the
#1365 census (the #1329 shape: no caller-supplied identifier, an unfiltered
listing, gated only by the generic MEDIUM tier).

MEDIUM is cleared by role profiles that hold none of Roles.ADMIN_ROLES --
"Verenigingen Chapter Board Member", "Verenigingen Volunteer", "Verenigingen
Auditor" (authorization_policy.ROLE_PROFILE_SECURITY_MAPPING) -- so each
endpoint's own query is the only thing that can scope what those callers see.

Fixed here, by reading through the doctype's OWN permission model instead of
bypassing it (frappe.get_all / raw SQL -> frappe.get_list), so no new scope
definition is written:

- get_auto_creation_dashboard (api/donor_auto_creation_management.py) and
  get_auto_creation_stats (services/member/donor/donor_auto_creation.py) listed
  the ten most recent auto-created Donors -- name and creation_trigger_amount --
  org-wide. Donor's permission query (permissions._make_member_linked_permission)
  already scopes a Chapter Board Member to donors of members in the chapters
  they hold an ACTIVE seat on, via _get_board_chapters_for_member() -- the
  helper #1329's get_mandate_issues fix reuses -- and a plain member to their
  own donor record. Admin/staff: unrestricted.
- get_donor_sync_dashboard (api/donor_customer_management.py) listed up to 30
  Donor rows across three queries (recent syncs, needs-sync, no-customer),
  including donor_email in the no-customer listing -- the same Donor permission
  query as above now scopes all three.
- get_mt940_import_status (verenigingen_payments/utils/mt940_import.py) listed
  the 20 most recent Bank Transactions -- amounts and bank descriptions, which
  carry counterparty names and IBANs. Bank Transaction's DocPerm grants read
  to Accounts User/Manager and System Manager only; the Volunteer and Auditor
  profiles hold none of those, the Chapter Board Member profile holds Accounts
  User. So Volunteer/Auditor are refused and a board member keeps what the
  Bank Transaction list view already shows them.

The org-wide COUNT/SUM figures these endpoints also return are aggregates and
are deliberately unchanged.
"""

import frappe
from frappe.utils import today

from verenigingen.api.donor_auto_creation_management import get_auto_creation_dashboard
from verenigingen.api.donor_customer_management import get_donor_sync_dashboard
from verenigingen.services.member.donor.donor_auto_creation import get_auto_creation_stats
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.verenigingen_payments.utils.mt940_import import get_mt940_import_status


def _dashboard_recent_names():
    result = get_auto_creation_dashboard()
    # The @standard_api wrapper serialises the OperationResult to a plain dict.
    data = result["data"] if isinstance(result, dict) else result.data
    return {row["name"] for row in data["recent_creations"]}


def _stats_recent_names():
    result = get_auto_creation_stats()
    return {row["name"] for row in result["recent_creations"]}


class TestAutoCreatedDonorListingScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    """A board member of chapter A sees chapter A's members' auto-created donors
    and not chapter B's; Volunteer/Auditor see neither; staff sees both plus a
    donor with no member link at all."""

    def setUp(self):
        super().setUp()
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        self.board = self.create_test_board_member(chapter_a.name)

        member_a = self.create_test_member(first_name="AutoDonorScopeA")
        self.add_member_to_test_chapter(member_a.name, chapter_a.name)
        member_b = self.create_test_member(first_name="AutoDonorScopeB")
        self.add_member_to_test_chapter(member_b.name, chapter_b.name)

        self.donor_a = self._auto_created_donor("Auto Scope Donor A", member=member_a.name)
        self.donor_b = self._auto_created_donor("Auto Scope Donor B", member=member_b.name)
        # Auto-created donors are usually built from a bare Customer, with no member.
        self.donor_unlinked = self._auto_created_donor("Auto Scope Donor Unlinked")

    def _auto_created_donor(self, donor_name, **kwargs):
        donor = self.create_test_donor(donor_name=donor_name, **kwargs)
        frappe.db.set_value(
            "Donor",
            donor.name,
            {"customer_sync_status": "Auto-Created", "creation_trigger_amount": 55.0},
            update_modified=False,
        )
        return donor.name

    def _assert_board_scoped(self, recent_names):
        with self.set_user(self.board.user):
            names = recent_names()
        self.assertIn(self.donor_a, names)
        self.assertNotIn(self.donor_b, names)
        self.assertNotIn(self.donor_unlinked, names)

    def _assert_profile_sees_neither(self, recent_names, role_profile):
        user_email, _member = self._user_linked_to_own_member(
            f"AutoDonor{role_profile.split()[-1]}", "Verenigingen Member", role_profile
        )
        with self.set_user(user_email):
            names = recent_names()
        self.assertNotIn(self.donor_a, names)
        self.assertNotIn(self.donor_b, names)
        self.assertNotIn(self.donor_unlinked, names)

    def _assert_staff_sees_all(self, recent_names):
        staff_user = self._staff_user("AutoDonorStaff", role="Verenigingen Staff")
        with self.set_user(staff_user):
            names = recent_names()
        self.assertTrue({self.donor_a, self.donor_b, self.donor_unlinked} <= names)

    def test_dashboard_board_member_sees_only_own_chapter(self):
        self._assert_board_scoped(_dashboard_recent_names)

    def test_dashboard_volunteer_sees_none(self):
        self._assert_profile_sees_neither(_dashboard_recent_names, "Verenigingen Volunteer")

    def test_dashboard_auditor_sees_none(self):
        self._assert_profile_sees_neither(_dashboard_recent_names, "Verenigingen Auditor")

    def test_dashboard_staff_sees_all(self):
        self._assert_staff_sees_all(_dashboard_recent_names)

    def test_stats_board_member_sees_only_own_chapter(self):
        self._assert_board_scoped(_stats_recent_names)

    def test_stats_volunteer_sees_none(self):
        self._assert_profile_sees_neither(_stats_recent_names, "Verenigingen Volunteer")

    def test_stats_auditor_sees_none(self):
        self._assert_profile_sees_neither(_stats_recent_names, "Verenigingen Auditor")

    def test_stats_staff_sees_all(self):
        self._assert_staff_sees_all(_stats_recent_names)


class TestMt940ImportStatusScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    """Bank Transaction rows reach only callers whose roles can read Bank
    Transaction: board member (Accounts User via the profile) and staff yes,
    Volunteer and Auditor no."""

    def setUp(self):
        super().setUp()
        company = get_eur_test_company()
        txn = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": today(),
                "bank_account": get_eur_bank_account(company),
                "company": company,
                "deposit": 42.0,
                "withdrawal": 0.0,
                "currency": "EUR",
                "reference_number": f"MT940SCOPE-{frappe.generate_hash(length=8)}",
                "description": "MT940 scope probe NL91ABNA0417164300 J Doe",
                "status": "Unreconciled",
                "unallocated_amount": 42.0,
                "allocated_amount": 0.0,
            }
        ).insert(ignore_permissions=True)
        self.txn = txn.name

    def _names_for(self, user):
        with self.set_user(user):
            result = get_mt940_import_status()
        return result, {row["name"] for row in result.get("recent_transactions", [])}

    def _assert_mt940_refused(self, role_profile):
        user_email, _member = self._user_linked_to_own_member(
            f"Mt940{role_profile.split()[-1]}", "Verenigingen Member", role_profile
        )
        result, names = self._names_for(user_email)
        self.assertNotIn(self.txn, names)
        self.assertFalse(result["success"])
        self.assertIn("Bank Transaction", result["message"])

    def test_volunteer_refused(self):
        self._assert_mt940_refused("Verenigingen Volunteer")

    def test_auditor_refused(self):
        self._assert_mt940_refused("Verenigingen Auditor")

    def test_board_member_with_accounts_user_still_sees_transactions(self):
        """Opposite-harm control: the Chapter Board Member profile carries Accounts
        User, which reads Bank Transaction in the list view already; an admin-only
        refusal here would remove access the doctype grants."""
        chapter = self.create_test_chapter()
        board = self.create_test_board_member(chapter.name)
        result, names = self._names_for(board.user)
        self.assertTrue(result["success"])
        self.assertIn(self.txn, names)

    def test_staff_sees_transactions(self):
        staff_user = self._staff_user("Mt940Staff", role="Verenigingen Staff")
        result, names = self._names_for(staff_user)
        self.assertTrue(result["success"])
        self.assertIn(self.txn, names)


class TestDonorSyncDashboardScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    """get_donor_sync_dashboard's "no_customers" listing (name, donor_name,
    donor_email) is the most sensitive of its three Donor queries -- it is the
    one carrying donor_email. A board member of chapter A sees chapter A's
    members' donors and not chapter B's; Volunteer/Auditor see neither; staff
    sees both plus a donor with no member link at all."""

    def setUp(self):
        super().setUp()
        chapter_a = self.create_test_chapter()
        chapter_b = self.create_test_chapter()
        self.board = self.create_test_board_member(chapter_a.name)

        member_a = self.create_test_member(first_name="DonorSyncScopeA")
        self.add_member_to_test_chapter(member_a.name, chapter_a.name)
        member_b = self.create_test_member(first_name="DonorSyncScopeB")
        self.add_member_to_test_chapter(member_b.name, chapter_b.name)

        self.donor_a = self.create_test_donor(donor_name="Sync Scope Donor A", member=member_a.name).name
        self.donor_b = self.create_test_donor(donor_name="Sync Scope Donor B", member=member_b.name).name
        # No-customer donors are commonly created with no member link at all.
        self.donor_unlinked = self.create_test_donor(donor_name="Sync Scope Donor Unlinked").name

    def _no_customer_names(self):
        result = get_donor_sync_dashboard()
        data = result["data"] if isinstance(result, dict) else result.data
        return {row["name"] for row in data["no_customers"]}

    def test_board_member_sees_only_own_chapter(self):
        with self.set_user(self.board.user):
            names = self._no_customer_names()
        self.assertIn(self.donor_a, names)
        self.assertNotIn(self.donor_b, names)
        self.assertNotIn(self.donor_unlinked, names)

    def _assert_no_customer_profile_excluded(self, role_profile):
        user_email, _member = self._user_linked_to_own_member(
            f"DonorSync{role_profile.split()[-1]}", "Verenigingen Member", role_profile
        )
        with self.set_user(user_email):
            names = self._no_customer_names()
        self.assertNotIn(self.donor_a, names)
        self.assertNotIn(self.donor_b, names)
        self.assertNotIn(self.donor_unlinked, names)

    def test_volunteer_sees_none(self):
        self._assert_no_customer_profile_excluded("Verenigingen Volunteer")

    def test_auditor_sees_none(self):
        self._assert_no_customer_profile_excluded("Verenigingen Auditor")

    def test_staff_sees_all(self):
        staff_user = self._staff_user("DonorSyncStaff", role="Verenigingen Staff")
        with self.set_user(staff_user):
            names = self._no_customer_names()
        self.assertTrue({self.donor_a, self.donor_b, self.donor_unlinked} <= names)
