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

The decorator's security check runs on direct in-process calls (the wrapper is
applied at import time), so calling the endpoint as a logged-in member is a
faithful reproduction of the portal HTTP path's auth gate.
"""

import frappe

from verenigingen.api.member import sepa_api
from verenigingen.templates.pages import (
    address_change,
    contact_request,
    membership_adjustment,
    my_dues_schedule,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestMemberPortalSelfService(EnhancedTestCase):
    """A plain member can invoke their own portal self-service endpoints."""

    def _link_member_to_user(self, member, roles=("Verenigingen Member",)):
        """Create a User carrying ONLY the Verenigingen Member role profile and
        link it to the member.

        Sets BOTH Member.user and Member.email, as production account creation
        does. Member.user is required by paths that resolve ownership strictly via
        the user link (e.g. the dues-schedule member-self-edit policy in
        DuesSchedulePermissionService.can_user_edit_schedule), not just the
        email fallback used by get_member_name_for_user.

        The role_profiles child table is the v16 canonical store and gives the
        user the exact LOW-tier profile real members carry — so these tests fail
        if an endpoint demands more than LOW.
        """
        user = self.factory.create_user_with_roles(
            email=f"selfsvc-{member.name}-{self.uid}@example.com",
            roles=list(roles),
        )
        user.reload()
        user.set("role_profiles", [{"role_profile": "Verenigingen Member"}])
        user.save(ignore_permissions=True)

        # reload: after_insert (customer) / membership creation may have bumped
        # the member's modified timestamp since the caller fetched it.
        member.reload()
        member.user = user.name
        member.email = user.name
        member.save(ignore_permissions=True)
        return user

    def _as_user(self, user_name):
        class _Switcher:
            def __enter__(self):
                self.original = frappe.session.user
                frappe.set_user(user_name)
                return self

            def __exit__(self, *_):
                frappe.set_user(self.original)

        return _Switcher()

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

    # --- cross-tenant scoping (ownership invariant) --------------------------

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
