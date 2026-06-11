"""
Member-portal self-service access — batch 1.

These tests verify that a plain "Verenigingen Member" (SecurityLevel.LOW — the
only role profile real members carry) can invoke the member-portal endpoints
that operate on their OWN data. Each endpoint was previously decorated
@standard_api (MEDIUM), which a LOW member cannot pass, so the portal action
threw PermissionError and silently failed. The fix swaps those to
@self_service_api(MEMBER_DATA, implicit_allowed=True) — LOW tier with ownership
enforced by SelfServiceAccessController, matching the donation/fee portal.

Endpoints exercised (inventory: docs/plans/2026-06-09-member-portal-self-service-lockout-inventory.md):
- templates/pages/address_change.py:        get_current_address, update_member_address
- templates/pages/my_dues_schedule.py:      export_schedule, get_payment_details
- templates/pages/membership_adjustment.py: get_fee_calculation_info, get_available_membership_types
- templates/pages/contact_request.py:       submit_contact_request
- api/member/sepa_api.py:                    setup_sepa_direct_debit (payment dashboard)
- api/mollie_payment.py (batch 4):           get_subscription_details,
                                             cancel_specific_subscription,
                                             update_mollie_bank_account (payment dashboard)

The decorator's security check runs on direct in-process calls (the wrapper is
applied at import time), so calling the endpoint as a logged-in member is a
faithful reproduction of the portal HTTP path's auth gate.
"""

import frappe

from verenigingen.api import chapter_join, mollie_payment, payment_plan_management
from verenigingen.api.member import sepa_api
from verenigingen.templates.pages import (
    address_change,
    contact_request,
    membership_adjustment,
    my_dues_schedule,
    personal_details,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestMemberPortalSelfService(PortalSelfServiceTestMixin, EnhancedTestCase):
    """A plain member can invoke their own portal self-service endpoints.

    Uses PortalSelfServiceTestMixin's canonical _link_member_to_user (sets both
    Member.user and Member.email, assigns the LOW-tier Verenigingen Member role
    profile real members carry).
    """

    def _member_with_membership(self):
        """Member + submitted Active membership (auto-creates an active dues
        schedule via after_insert) linked to a plain-member user."""
        member = self.create_test_member(birth_date="1990-01-01")
        self.create_test_membership(member_name=member.name)
        user = self._link_member_to_user(member)
        return member, user

    # --- address_change.py ---------------------------------------------------

    def test_member_can_read_own_address(self):
        """get_current_address returns the member's address state (None when unset)."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            result = address_change.get_current_address()

        self.assertIn("address", result)
        self.assertIsNone(result["address"])  # no address created yet

    def test_member_can_update_own_address(self):
        """update_member_address creates/links an address for the calling member."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        address_data = {
            "address_line1": "Teststraat 1",
            "city": "Amsterdam",
            "country": "Netherlands",
            "pincode": "1011AB",
        }

        with self._as_user(user.name):
            result = address_change.update_member_address(address_data)

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "created")
        # The new address is now the member's primary address.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "primary_address"),
            result["address_name"],
        )

    # --- my_dues_schedule.py -------------------------------------------------

    def test_member_can_export_own_schedule(self):
        """export_schedule streams a CSV download for the calling member."""
        member, user = self._member_with_membership()

        with self._as_user(user.name):
            my_dues_schedule.export_schedule()
            self.assertEqual(frappe.response.get("type"), "download")
            self.assertIn(member.name, frappe.response.get("filename", ""))
            self.assertIn("Date", frappe.response.get("filecontent", ""))  # CSV header

    def test_member_can_query_own_payment_details(self):
        """get_payment_details reaches its business logic (no tier lockout).

        With no invoices the date lookup raises DoesNotExistError — crucially NOT
        the PermissionError a LOW member previously hit at the security gate.
        """
        _, user = self._member_with_membership()

        with self._as_user(user.name):
            with self.assertRaises(frappe.DoesNotExistError):
                my_dues_schedule.get_payment_details("2099-01-01")

    # --- api/member/sepa_api.py (payment dashboard) --------------------------

    def test_member_can_set_up_own_sepa_direct_debit(self):
        """setup_sepa_direct_debit (member payment dashboard) writes the calling
        member's bank details and creates an active SEPA mandate.

        Exercises the financial second-layer fix: the Member record write is
        if_owner-gated (members don't own their record), so a plain member.save()
        is denied and secure_document_operation can't help (it escalates to a
        system user a member may not request) — the write uses
        member.save(ignore_permissions=True) after ownership is verified. The
        SEPA Mandate create runs under the member's own (non-if_owner) perms.
        """
        member, user = self._member_with_membership()
        iban = generate_test_iban("TEST")

        with self._as_user(user.name):
            result = sepa_api.setup_sepa_direct_debit(iban=iban, account_holder_name="Test Holder")

        self.assertTrue(result.get("success"), msg=result)
        # An active mandate exists for this member (IBAN is persisted space-formatted,
        # so compare on the normalized value rather than filtering on the raw input).
        mandate = frappe.db.get_value(
            "SEPA Mandate",
            {"member": member.name, "status": "Active", "is_active": 1},
            ["name", "iban"],
            as_dict=True,
        )
        self.assertIsNotNone(mandate)
        self.assertEqual(mandate.iban.replace(" ", ""), iban)
        member.reload()
        self.assertEqual(member.iban.replace(" ", ""), iban)
        self.assertEqual(member.payment_method, "SEPA Direct Debit")

    def test_member_cannot_access_other_members_sepa_mandate(self):
        """A member must not see or read another member's SEPA mandate (IBANs are
        sensitive PII). The SEPA Mandate DocPerm grants members read/write with no
        per-member scoping by default, so a permission_query + has_permission hook
        is required to confine members to their own mandates.
        """
        owner, owner_user = self._member_with_membership()
        with self._as_user(owner_user.name):
            sepa_api.setup_sepa_direct_debit(
                iban=generate_test_iban("TEST"), account_holder_name="Owner"
            )
        mandate = frappe.db.get_value(
            "SEPA Mandate", {"member": owner.name, "status": "Active"}, "name"
        )
        self.assertIsNotNone(mandate)

        intruder = self.create_test_member(birth_date="1992-03-03")
        intruder_user = self._link_member_to_user(intruder)
        with self._as_user(intruder_user.name):
            # Not present in the intruder's permission-filtered list.
            visible = frappe.get_list("SEPA Mandate", pluck="name", limit_page_length=0)
            self.assertNotIn(mandate, visible)
            # And a direct permission check on the owner's mandate is denied.
            self.assertFalse(frappe.has_permission("SEPA Mandate", "read", mandate))

    def test_member_sepa_iban_change_replaces_old_mandate(self):
        """Changing IBAN cancels the previous mandate and leaves exactly one active.

        Guards the deactivate-then-create branch: a member setting up a new IBAN
        must not accumulate multiple active mandates.
        """
        member, user = self._member_with_membership()
        first_iban = generate_test_iban("TEST")
        second_iban = generate_test_iban("MOCK")
        self.assertNotEqual(first_iban, second_iban)

        with self._as_user(user.name):
            sepa_api.setup_sepa_direct_debit(iban=first_iban, account_holder_name="Test Holder")
            result = sepa_api.setup_sepa_direct_debit(iban=second_iban, account_holder_name="Test Holder")

        self.assertTrue(result.get("success"), msg=result)

        active = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member.name, "status": "Active", "is_active": 1},
            fields=["name", "iban"],
        )
        self.assertEqual(len(active), 1, msg=active)
        self.assertEqual(active[0].iban.replace(" ", ""), second_iban)
        # The first mandate was cancelled, not left dangling.
        self.assertTrue(frappe.db.exists("SEPA Mandate", {"member": member.name, "status": "Cancelled"}))

    # --- SelfServiceAccessController member resolution ------------------------

    def test_self_service_resolves_caller_by_user_link_not_only_email(self):
        """A member linked via Member.user (login) but whose Member.email differs
        is still recognized as the owner by the @self_service_api framework gate.

        The endpoint bodies resolve the caller user-first (get_current_user_member_name),
        but SelfServiceAccessController used to resolve email-only — so a member
        whose Member.user != Member.email (legacy data; the Member controller now
        auto-syncs user=email, but old records can still diverge) was wrongly locked
        out of the implicit (no-arg) self-service endpoints. This pins the aligned
        resolution.

        The divergent state is written directly (the Member save hook would
        re-sync user=email), which faithfully reproduces the resolver's input.
        """
        member = self.create_test_member(birth_date="1990-01-01")
        user = self.factory.create_user_with_roles(
            email=f"login-{member.name}-{self.uid}@example.com",
            roles=["Verenigingen Member"],
        )
        user.reload()
        user.set("role_profiles", [{"role_profile": "Verenigingen Member"}])
        user.save(ignore_permissions=True)
        # user-linked but email-divergent (bypass the user=email sync hook).
        frappe.db.set_value(
            "Member",
            member.name,
            {"user": user.name, "email": f"different-{self.uid}@example.org"},
            update_modified=False,
        )

        with self._as_user(user.name):
            # get_current_address takes no member arg → framework implicit branch,
            # which calls get_user_member to confirm the caller has a member.
            result = address_change.get_current_address()
        self.assertIn("address", result)

    # --- templates/pages/personal_details.py ---------------------------------

    def test_member_can_update_own_personal_details(self):
        """update_personal_details persists the calling member's name change.

        The Member record write is if_owner-gated (members don't own their
        record), so the endpoint must persist via an ownership-verified path that
        works for a plain member — same financial/data second-layer as SEPA.
        """
        member, user = self._member_with_membership()

        with self._as_user(user.name):
            frappe.local.form_dict = frappe._dict(
                {
                    "first_name": "Renamed",
                    "last_name": "Tester",
                }
            )
            try:
                personal_details.update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

        member.reload()
        self.assertEqual(member.first_name, "Renamed")
        self.assertEqual(member.last_name, "Tester")

    # --- api/payment_plan_management.py (payment plans portal) ---------------

    def test_member_can_request_own_payment_plan(self):
        """request_payment_plan creates a Draft plan for the calling member.

        The portal (payment_plans.html) passes member=null, so the endpoint must
        resolve the member from the session — exercises both the tier swap and the
        session-derivation that the live frontend depends on.
        """
        member, user = self._member_with_membership()
        with self._as_user(user.name):
            result = payment_plan_management.request_payment_plan(
                member=None, total_amount=300, preferred_installments=3, preferred_frequency="Monthly"
            )
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(frappe.db.exists("Payment Plan", {"member": member.name, "status": "Draft"}))

    def test_member_can_list_own_payment_plans(self):
        """get_member_payment_plans returns the calling member's plans."""
        _, user = self._member_with_membership()
        with self._as_user(user.name):
            payment_plan_management.request_payment_plan(
                member=None, total_amount=300, preferred_installments=3, preferred_frequency="Monthly"
            )
            result = payment_plan_management.get_member_payment_plans()
        self.assertTrue(result["success"], msg=result)
        self.assertGreaterEqual(len(result["data"]["payment_plans"]), 1)

    def test_member_can_preview_payment_plan(self):
        """calculate_payment_plan_preview is reachable by a plain member."""
        _, user = self._member_with_membership()
        with self._as_user(user.name):
            result = payment_plan_management.calculate_payment_plan_preview(
                total_amount=300, installments=3, frequency="Monthly"
            )
        self.assertTrue(result["success"], msg=result)

    # --- api/chapter_join.py (chapter join page) -----------------------------

    def test_member_can_join_chapter(self):
        """join_chapter files a Chapter Join Request for the calling member."""
        member, user = self._member_with_membership()
        chapter = self.create_test_chapter()
        with self._as_user(user.name):
            result = chapter_join.join_chapter(
                chapter_name=chapter.name, introduction="Hello, I would like to join."
            )
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(
            frappe.db.exists("Chapter Join Request", {"member": member.name, "chapter": chapter.name})
        )

    def test_member_can_read_chapter_join_context(self):
        """get_chapter_join_context returns the member's join status for a chapter."""
        member, user = self._member_with_membership()
        chapter = self.create_test_chapter()
        with self._as_user(user.name):
            result = chapter_join.get_chapter_join_context(chapter_name=chapter.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"]["member"], member.name)
        self.assertFalse(result["data"]["already_member"])

    # --- cross-tenant scoping (ownership invariant) --------------------------

    def test_payment_plan_endpoints_reject_other_members(self):
        """A member cannot read or request payment plans for ANOTHER member by
        passing an explicit member id — @self_service_api enforces ownership of
        the `member` argument (these endpoints, unlike the address ones, accept
        a caller-supplied member, so this is the key ownership invariant).
        """
        owner = self.create_test_member(birth_date="1990-01-01")
        self.create_test_membership(member_name=owner.name)
        intruder = self.create_test_member(birth_date="1991-02-02")
        intruder_user = self._link_member_to_user(intruder)

        with self._as_user(intruder_user.name):
            with self.assertRaises(frappe.PermissionError):
                payment_plan_management.get_member_payment_plans(member=owner.name)
            with self.assertRaises(frappe.PermissionError):
                payment_plan_management.request_payment_plan(
                    member=owner.name, total_amount=300, preferred_installments=3
                )

    def test_address_endpoints_are_scoped_to_session_member(self):
        """A member only ever reaches their OWN address.

        These endpoints take no member argument — the member is derived from the
        session — so there is no parameter-tampering vector to another member's
        data. This test pins that invariant: member B never sees member A's
        address, and each member reads back only their own.
        """
        member_a = self.create_test_member(birth_date="1990-01-01")
        user_a = self._link_member_to_user(member_a)
        with self._as_user(user_a.name):
            address_change.update_member_address(
                {"address_line1": "A-straat 1", "city": "Amsterdam", "country": "Netherlands"}
            )

        member_b = self.create_test_member(birth_date="1991-02-02")
        user_b = self._link_member_to_user(member_b)

        # B has no address of their own and must NOT inherit A's.
        with self._as_user(user_b.name):
            result_b = address_change.get_current_address()
        self.assertIsNone(result_b["address"])

        # A still sees only their own address.
        with self._as_user(user_a.name):
            result_a = address_change.get_current_address()
        self.assertEqual(result_a["address"]["address_line1"], "A-straat 1")

    # --- membership_adjustment.py -------------------------------------------

    def test_member_can_read_own_fee_calculation_info(self):
        """get_fee_calculation_info returns the member's fee figures."""
        _, user = self._member_with_membership()

        with self._as_user(user.name):
            result = membership_adjustment.get_fee_calculation_info()

        self.assertIn("standard_fee", result)
        self.assertIn("minimum_fee", result)
        self.assertIn("current_fee", result)

    def test_member_can_list_available_membership_types(self):
        """get_available_membership_types lists switch options for the member."""
        _, user = self._member_with_membership()

        with self._as_user(user.name):
            result = membership_adjustment.get_available_membership_types()

        self.assertIn("membership_types", result)
        self.assertIn("current_type", result)
        self.assertIsInstance(result["membership_types"], list)

    # --- contact_request.py --------------------------------------------------

    def test_member_can_submit_contact_request(self):
        """submit_contact_request files a request for the calling member.

        The Member Contact Request controller requires an Active member
        (membership_status == "Active"), so set up a submitted membership.
        """
        member, user = self._member_with_membership()

        with self._as_user(user.name):
            frappe.form_dict = frappe._dict(
                {
                    "subject": "Test inquiry",
                    "message": "Please contact me about my membership.",
                    "request_type": "General Inquiry",
                }
            )
            try:
                contact_request.submit_contact_request()
                response = frappe.response.get("message")
            finally:
                frappe.form_dict = frappe._dict()

        self.assertIsNotNone(response)
        self.assertTrue(response["success"])
        # The request is recorded against this member.
        self.assertTrue(
            frappe.db.exists("Member Contact Request", {"member": member.name})
        )

    # --- api/mollie_payment.py (batch 4) -------------------------------------
    #
    # These three endpoints back the Mollie panel of the member payment
    # dashboard (templates/pages/payment_dashboard.html). They were gated at
    # @high_security_api / @critical_api, locking the plain Verenigingen Member
    # out of viewing/cancelling their own subscription and changing their own
    # bank account. The swap to @self_service_api(implicit_allowed=True) matches
    # the rest of the portal: each function already resolves the member from the
    # session (get_current_user_member_name_required + validate_member_ownership)
    # and writes via db_set, so no second-layer permission fix is needed.
    #
    # Each function reaches the live Mollie API only AFTER an early-return guard
    # (no customer id / unauthorized customer id / no subscription). These tests
    # drive those guarded paths, so the assertion that a plain member reaches the
    # body at all — rather than being rejected by the tier gate — is a faithful
    # check of the decorator swap without depending on a Mollie sandbox.

    def test_member_can_query_own_subscription_details(self):
        """get_subscription_details passes the self-service gate for a plain
        member. With no Mollie customer id on the record it returns the
        'no_subscription' early result (before any Mollie API call) — proving
        the member cleared the auth tier rather than hitting PermissionError.
        """
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            result = mollie_payment.get_subscription_details()

        self.assertEqual(result["status"], "no_subscription")

    def test_member_cancel_subscription_enforces_customer_ownership(self):
        """cancel_specific_subscription passes the gate, then refuses to cancel a
        customer id the member does not own (in-body ownership check, before any
        Mollie call). The member owns cst_aaaaaaaaaa and asks to cancel a
        different customer's subscription → 'not authorized' error, not a tier
        PermissionError.
        """
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)
        frappe.db.set_value("Member", member.name, "mollie_customer_id", "cst_aaaaaaaaaa")

        with self._as_user(user.name):
            result = mollie_payment.cancel_specific_subscription(
                customer_id="cst_bbbbbbbbbb", subscription_id="sub_test01"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("not authorized", result["message"].lower())

    def test_member_update_bank_account_passes_gate(self):
        """update_mollie_bank_account passes the self-service gate for a plain
        member. With no active Mollie subscription on the record it returns the
        'no active subscription' guard result (before any Mollie API call) —
        again proving the member cleared the tier gate.
        """
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban=generate_test_iban(), account_holder_name="Test Member"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("no active mollie subscription", result["message"].lower())
