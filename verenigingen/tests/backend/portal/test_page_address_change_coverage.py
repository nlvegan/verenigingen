"""
Coverage-extension tests for the address-change portal page
(verenigingen.templates.pages.address_change).

The portal cluster test already covers get_context (no-member / with-member),
get_current_address (none) and update_member_address (create / missing-required
/ invalid-email). This module fills the REMAINING uncovered branches:

- update_member_address: invalid postal code, invalid phone, valid optional
  fields accepted, the UPDATE-existing-address path (create then update), and
  the JSON-string input form (the endpoint json.loads() a str arg).
- get_current_address: returns a populated address after one is created,
  and the no-member-record throw.
- get_context: a member WITH an address exposes the populated address_data.
- update_member_address no-member-record throw.

OUT OF SCOPE: the secure_document_operation failure branches (result.success
False) cannot be reached with a legitimately-owned address and a valid member
session — they require an operation-level permission failure we cannot induce
without mocking the security framework (forbidden by the HARD RULES). The
secure_operations success path IS exercised through the create/update tests.
"""

import json

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageAddressChangeCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.email = f"addrcov-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Addr",
            last_name="Cover",
            email=self.email,
            birth_date="1990-01-01",
        )
        self.email = self.member.email
        self.user = self._ensure_user(self.email)
        self.member.db_set("user", self.user)

    def _ensure_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Addr",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    def _create_address(self, **overrides):
        from verenigingen.templates.pages.address_change import update_member_address

        payload = {
            "address_line1": "Hoofdstraat 1",
            "city": "Amsterdam",
            "country": "Netherlands",
            "pincode": "1011 AB",
        }
        payload.update(overrides)
        with self.as_user(self.user):
            with self.assertNoErrorLog():
                result = update_member_address(payload)
        self.member.reload()
        return result

    # ----- update_member_address validation throws ---------------------

    def test_update_rejects_invalid_postal_code(self):
        from verenigingen.templates.pages.address_change import update_member_address

        with self.as_user(self.user):
            with self.assertRaises(frappe.ValidationError):
                update_member_address(
                    {
                        "address_line1": "Straat 1",
                        "city": "Utrecht",
                        "country": "Netherlands",
                        "pincode": "!!",  # too short / invalid chars
                    }
                )

    def test_update_rejects_invalid_phone(self):
        from verenigingen.templates.pages.address_change import update_member_address

        with self.as_user(self.user):
            with self.assertRaises(frappe.ValidationError):
                update_member_address(
                    {
                        "address_line1": "Straat 1",
                        "city": "Utrecht",
                        "country": "Netherlands",
                        "phone": "abc",
                    }
                )

    def _make_user_without_member(self):
        """Create a Verenigingen Member User that has no linked Member record."""
        nomember = f"addrcov-nomember-{frappe.generate_hash()[:8]}@test.invalid"
        if not frappe.db.exists("User", nomember):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": nomember,
                    "first_name": "NoMember",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return nomember

    def test_update_no_member_record_throws(self):
        from verenigingen.templates.pages.address_change import update_member_address

        nomember = self._make_user_without_member()

        # The @self_service_api decorator resolves the caller's member for
        # ownership enforcement and rejects a user with no member record with a
        # PermissionError, before the body's own DoesNotExistError throw runs.
        with self.as_user(nomember):
            with self.assertRaises(frappe.PermissionError):
                update_member_address({"address_line1": "x", "city": "y", "country": "Netherlands"})

    # ----- update_member_address happy paths ---------------------------

    def test_update_accepts_valid_optional_fields(self):
        result = self._create_address(phone="+31 20 1234567", email_id="addr-valid@example.com")
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "created")

        addr = frappe.get_doc("Address", result["address_name"])
        self.assertEqual(addr.phone, "+31 20 1234567")
        self.assertEqual(addr.email_id, "addr-valid@example.com")

    def test_update_existing_address_path(self):
        # First create, then update -> hits the "address_doc exists" UPDATE branch.
        created = self._create_address()
        self.assertEqual(created["action"], "created")

        from verenigingen.templates.pages.address_change import update_member_address

        with self.as_user(self.user):
            with self.assertNoErrorLog():
                updated = update_member_address(
                    {
                        "address_line1": "Nieuwekade 99",
                        "city": "Utrecht",
                        "country": "Netherlands",
                        "pincode": "3511 BB",
                    }
                )
        self.assertTrue(updated["success"])
        self.assertEqual(updated["action"], "updated")
        # Same underlying address record was reused.
        self.assertEqual(updated["address_name"], created["address_name"])

        addr = frappe.get_doc("Address", updated["address_name"])
        self.assertEqual(addr.city, "Utrecht")
        self.assertEqual(addr.address_line1, "Nieuwekade 99")

    def test_update_accepts_json_string_argument(self):
        from verenigingen.templates.pages.address_change import update_member_address

        payload = json.dumps(
            {
                "address_line1": "Kanaalstraat 3",
                "city": "Rotterdam",
                "country": "Netherlands",
            }
        )
        with self.as_user(self.user):
            with self.assertNoErrorLog():
                result = update_member_address(payload)
        self.assertTrue(result["success"])
        addr = frappe.get_doc("Address", result["address_name"])
        self.assertEqual(addr.city, "Rotterdam")

    # ----- get_current_address -----------------------------------------

    def test_get_current_address_returns_created_address(self):
        from verenigingen.templates.pages.address_change import get_current_address

        created = self._create_address(pincode="1011 AB")
        with self.as_user(self.user):
            with self.assertNoErrorLog():
                result = get_current_address()
        self.assertIsNotNone(result["address"])
        self.assertEqual(result["address"]["name"], created["address_name"])
        self.assertEqual(result["address"]["city"], "Amsterdam")
        self.assertEqual(result["address"]["pincode"], "1011 AB")

    def test_get_current_address_no_member_record_throws(self):
        from verenigingen.templates.pages.address_change import get_current_address

        nomember = self._make_user_without_member()

        # @self_service_api rejects a member-less caller with PermissionError
        # before the body's DoesNotExistError throw.
        with self.as_user(nomember):
            with self.assertRaises(frappe.PermissionError):
                get_current_address()

    # ----- get_context with an existing address ------------------------

    def test_context_exposes_populated_address(self):
        from verenigingen.templates.pages.address_change import get_context

        self._create_address(pincode="1011 AB")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNotNone(ctx.current_address)
        self.assertEqual(ctx.address_data["city"], "Amsterdam")
        self.assertEqual(ctx.address_data["address_line1"], "Hoofdstraat 1")
        self.assertEqual(ctx.page_title, "Update Address")
