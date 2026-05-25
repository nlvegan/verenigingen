"""Regression contract for the module-level shims in
verenigingen.verenigingen.doctype.member.member.

These shims exist so that callers using the dotted-path form
(``frappe.call("verenigingen.verenigingen.doctype.member.member.<name>", doc=...)``)
can invoke whitelisted Member instance methods. JS uses
``frm.call('<name>')``, which goes through Frappe's ``run_doc_method``
resolver and never hits these shims. The shims back tests, server
scripts, and any ``/api/method/<dotted.path>`` consumers.

Pin three things per shim:

1. It is a module-level attribute (``frappe.get_attr`` resolves it).
2. It is registered in ``frappe.whitelisted`` (HTTP-callable).
3. The shared loader raises a recognizable error when ``doc`` is missing
   the ``name`` field, and ``check_permission`` is enforced.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member import member as member_module

SHIM_NAMES = [
    "create_customer",
    "create_user",
    "update_membership_duration",
    "get_address_members_html",
    "get_current_membership_fee",
    "get_display_membership_fee",
    "ensure_member_id",
]


class TestMemberApiShims(VereningingenTestCase):
    def test_all_shims_resolve_as_module_attributes(self):
        for name in SHIM_NAMES:
            fn = getattr(member_module, name, None)
            self.assertIsNotNone(
                fn,
                f"{name} must be a module-level attribute (frappe.get_attr "
                f"resolves dotted paths via module attribute lookup)",
            )

    def test_all_shims_are_whitelisted(self):
        for name in SHIM_NAMES:
            fn = getattr(member_module, name)
            self.assertIn(
                fn,
                frappe.whitelisted,
                f"{name} must be in frappe.whitelisted to be HTTP-callable",
            )

    def test_loader_rejects_missing_doc(self):
        with self.assertRaises(frappe.ValidationError):
            member_module._load_member_for_shim(None, "read")

    def test_loader_rejects_doc_without_name(self):
        with self.assertRaises(frappe.ValidationError):
            member_module._load_member_for_shim({"doctype": "Member"}, "read")

    def test_loader_parses_json_string(self):
        member = self.create_test_member(first_name="Shim", last_name="Loader")
        loaded = member_module._load_member_for_shim(
            frappe.as_json({"name": member.name}), "read"
        )
        self.assertEqual(loaded.name, member.name)

    def test_shim_round_trip_via_frappe_call(self):
        member = self.create_test_member(first_name="Shim", last_name="RoundTrip")
        # The exact failure mode T3 F8 is fixing: dotted-path frappe.call()
        # used to raise AttributeError because the instance method was not a
        # module-level attribute. The shim restores that path.
        html = frappe.call(
            "verenigingen.verenigingen.doctype.member.member.get_address_members_html",
            doc=member.as_dict(),
        )
        self.assertIsInstance(html, str)

    def _create_member_role_user(self):
        """Create a test User with only the Verenigingen Member role.

        Bypasses User-create DocPerm because the test acts on the user as
        a target subject, not as the action under test.
        """
        user_email = f"shim.perm.{frappe.utils.random_string(8)}@test.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": "Shim",
                "last_name": "Perm",
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user_email

    def test_shim_enforces_permission_check(self):
        member = self.create_test_member(first_name="Shim", last_name="Perm")
        user_email = self._create_member_role_user()

        with self.as_user(user_email):
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.verenigingen.doctype.member.member.create_customer",
                    doc=member.as_dict(),
                )
