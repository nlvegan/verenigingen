"""
#1891: ``d.get("k", "")`` only defaults an ABSENT key. A JSON ``null`` (or a
present-but-None form value) yields None, and the following ``.strip()``
raised AttributeError -> a 500 instead of the endpoint's own validation.

Both portal endpoints take a caller-controlled payload (a JSON body), so a
key present with value null is reachable. Optional fields must behave like
blank; required fields must be refused with the endpoint's own message.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _PortalMemberCase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1
        self.member = self.create_test_member(
            first_name="Nullval", last_name="Vandenbergnull", birth_date="1990-01-01"
        )
        self.user = self.member.email
        if not frappe.db.exists("User", self.user):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self.user,
                    "first_name": "Nullval",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        self.member.db_set("user", self.user)

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()


class TestAddressChangeNullValues1891(_PortalMemberCase):
    def _call(self, payload):
        from verenigingen.templates.pages.address_change import update_member_address

        with self.as_user(self.user):
            return update_member_address(payload)

    def test_null_required_field_is_refused_with_the_required_message(self):
        for field in ("address_line1", "city", "country"):
            payload = {"address_line1": "Straat 1", "city": "Amsterdam", "country": "Netherlands"}
            payload[field] = None
            with self.assertRaises(frappe.ValidationError) as ctx:
                self._call(payload)
            self.assertIn("is required", str(ctx.exception), field)

    def test_null_optional_fields_are_treated_as_blank(self):
        result = self._call(
            {
                "address_line1": "Straat 1",
                "address_line2": None,
                "city": "Amsterdam",
                "state": None,
                "country": "Netherlands",
                "pincode": None,
                "phone": None,
                "email_id": None,
            }
        )
        self.assertTrue(result.get("success"), result)
        address = frappe.get_doc("Address", frappe.db.get_value("Member", self.member.name, "primary_address"))
        self.track_doc("Address", address.name)
        self.assertEqual(address.address_line1, "Straat 1")
        self.assertFalse(address.pincode)
        self.assertFalse(address.address_line2)

    def test_null_optional_fields_on_update_of_existing_address(self):
        base = {"address_line1": "Straat 1", "city": "Amsterdam", "country": "Netherlands"}
        first = self._call(dict(base))
        self.assertTrue(first.get("success"), first)
        self.track_doc("Address", frappe.db.get_value("Member", self.member.name, "primary_address"))
        second = self._call(dict(base, address_line2=None, state=None, pincode=None, phone=None, email_id=None))
        self.assertTrue(second.get("success"), second)


class TestPersonalDetailsNullValues1891(_PortalMemberCase):
    def _call(self, **fields):
        from verenigingen.templates.pages.personal_details import update_personal_details

        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(fields)
            try:
                return update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

    def test_null_required_names_are_refused_with_the_required_message(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._call(first_name=None, last_name="Vandenberg")
        self.assertIn("First name is required", str(ctx.exception))
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._call(first_name="Jan", last_name=None)
        self.assertIn("Last name is required", str(ctx.exception))

    def test_null_optional_fields_are_treated_as_blank(self):
        # Reaches the validation of every optional field; must not raise
        # AttributeError. "No changes" / success are both acceptable endings.
        try:
            self._call(
                first_name="Jan",
                last_name="Vandenberg",
                middle_name=None,
                tussenvoegsel=None,
                contact_number=None,
                birth_date=None,
                pronouns=None,
                custom_pronouns=None,
            )
        except AttributeError as e:
            self.fail(f"null optional value raised AttributeError: {e}")
        except frappe.ValidationError as e:
            self.fail(f"null optional value was refused: {e}")
