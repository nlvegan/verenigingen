"""
Regression test for #374: update_member_address()'s outer `except Exception`
swallows the body's OWN deliberate `frappe.throw(..., frappe.PermissionError)`
("Access denied: Address does not belong to your member record") and replaces
it with a generic "An error occurred while updating your address." message,
raised as a plain ValidationError instead of PermissionError.

The scenario: a member's `primary_address` points at an Address that is not
Dynamically Linked to that member (a data-integrity edge case reachable
without insert-time validation -- e.g. a stale/incorrectly migrated
reference). The endpoint's own ownership check is designed to catch this and
raise a PermissionError with an explicit reason; the surrounding broad
`except Exception` currently intercepts that raise and re-throws a generic,
untyped message instead.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAddressChangeSwallowedThrow374(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # update_member_address is a @self_service_api (HIGH security) endpoint
        # gated to the DEVELOPMENT environment via frappe.conf.developer_mode.
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.member = self.create_test_member(
            first_name="Swallow",
            last_name="Address374",
            birth_date="1990-01-01",
        )
        self.user = self.member.email
        if not frappe.db.exists("User", self.user):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self.user,
                    "first_name": "Swallow",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        self.member.db_set("user", self.user)

        # An Address that exists but is NOT Dynamically Linked to this member.
        other_member = self.create_test_member(first_name="Other", last_name="Owner374")
        self.foreign_address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": other_member.full_name,
                "address_type": "Personal",
                "address_line1": "Elsewhere 1",
                "city": "Utrecht",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": other_member.name}],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Address", self.foreign_address.name)

        # Point OUR member's primary_address at that foreign address without
        # a Dynamic Link of its own -- this is the data condition the
        # ownership check exists to catch.
        self.member.db_set("primary_address", self.foreign_address.name)

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def test_access_denied_reaches_caller_as_permission_error_with_its_own_message(self):
        from verenigingen.templates.pages.address_change import update_member_address

        with self.as_user(self.user):
            with self.assertRaises(frappe.PermissionError) as ctx:
                update_member_address(
                    {
                        "address_line1": "New Street 1",
                        "city": "Amsterdam",
                        "country": "Netherlands",
                    }
                )

        # The endpoint's own deliberate refusal message must reach the caller
        # verbatim -- not the generic "An error occurred..." replacement the
        # surrounding `except Exception` currently substitutes.
        self.assertIn("does not belong to your member record", str(ctx.exception))
