"""
Real-DB coverage for thin/uncovered branches of the Member controller
(``verenigingen/verenigingen/doctype/member/member.py``).

Member is almost entirely a delegation surface (mixins + extracted services);
the heavy logic lives in tested services. This file covers the controller-local
logic that isn't reached elsewhere:

- ``has_query_permission`` (admin / VBCM / default branches)
- ``should_have_member_id`` (non-application vs application member)
- ``on_change`` (clears the stuck in_print flag)
- ``_get_volunteer_id`` (found / none)
- ``_get_status_color`` delegation
- module-level shims: ``_load_member_for_shim`` guards, ``ensure_member_id``
  dict-normalisation, ``is_chapter_management_enabled``, ``get_board_memberships``

Real Member/Volunteer/User records via the factory; run as Administrator. No
business logic is mocked.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member import member as member_module
from verenigingen.verenigingen.doctype.member.member import Member


class TestMemberControllerCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="MemberCtrl",
            last_name="Cov",
            email=f"memberctrl.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    # ------------------------------------------------------------ has_query_permission

    def test_has_query_permission_admin_true(self):
        # Administrator holds an admin role -> always True.
        self.assertTrue(Member.has_query_permission("Administrator"))

    def test_has_query_permission_vbcm_true(self):
        user = self.create_test_user(
            email=f"vbcm.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Chapter Board Member"],
        )
        self.assertTrue(Member.has_query_permission(user.name))

    def test_has_query_permission_plain_user_default(self):
        user = self.create_test_user(
            email=f"plain.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        # Neither admin nor VBCM -> default Frappe behaviour (None).
        self.assertIsNone(Member.has_query_permission(user.name))

    # ------------------------------------------------------------ should_have_member_id

    def test_should_have_member_id_non_application_true(self):
        # A directly-created (non-application) member should always have an id.
        doc = frappe.get_doc("Member", self.member.name)
        self.assertTrue(doc.should_have_member_id())

    # ------------------------------------------------------------ on_change

    def test_on_change_clears_in_print_flag(self):
        doc = frappe.get_doc("Member", self.member.name)
        doc.flags.in_print = True
        doc.flags.print_settings = {"x": 1}
        doc.on_change()
        self.assertFalse(doc.flags.in_print)
        self.assertIsNone(doc.flags.get("print_settings"))

    # ------------------------------------------------------------ _get_volunteer_id

    def test_get_volunteer_id_none_when_no_volunteer(self):
        doc = frappe.get_doc("Member", self.member.name)
        self.assertIsNone(doc._get_volunteer_id())

    def test_get_volunteer_id_resolves(self):
        volunteer = self.create_test_volunteer(member=self.member.name)
        doc = frappe.get_doc("Member", self.member.name)
        self.assertEqual(doc._get_volunteer_id(), volunteer.name)

    # ------------------------------------------------------------ _get_status_color

    def test_get_status_color_returns_value(self):
        doc = frappe.get_doc("Member", self.member.name)
        color = doc._get_status_color("Active")
        self.assertTrue(color)

    # ------------------------------------------------------------ _load_member_for_shim guards

    def test_shim_requires_doc(self):
        with self.assertRaises(frappe.ValidationError):
            member_module._load_member_for_shim(None, "read")

    def test_shim_requires_name(self):
        with self.assertRaises(frappe.ValidationError):
            member_module._load_member_for_shim({"first_name": "x"}, "read")

    def test_shim_loads_from_dict(self):
        loaded = member_module._load_member_for_shim({"name": self.member.name}, "read")
        self.assertEqual(loaded.name, self.member.name)

    def test_shim_loads_from_json_string(self):
        loaded = member_module._load_member_for_shim(frappe.as_json({"name": self.member.name}), "read")
        self.assertEqual(loaded.name, self.member.name)

    # ------------------------------------------------------------ ensure_member_id shim

    def test_ensure_member_id_shim_returns_dict(self):
        # The shim must normalise an OperationResult to a plain dict via to_dict().
        # Assert it is actually a dict — a bare OperationResult (or a frappe._dict
        # whose .to_dict resolves to None) is the exact to_dict trap from prior
        # sessions this guards. isinstance(dict) also accepts frappe._dict.
        result = member_module.ensure_member_id({"name": self.member.name})
        self.assertIsInstance(result, dict)

    # ------------------------------------------------------------ module-level helpers

    def test_is_chapter_management_enabled_module_fn(self):
        self.assertIsInstance(member_module.is_chapter_management_enabled(), bool)

    def test_get_board_memberships_module_fn(self):
        # No board seats -> empty/structured result, no raise.
        result = member_module.get_board_memberships(self.member.name)
        self.assertIsNotNone(result)

    def test_get_volunteer_details_html_for_member(self):
        # Returns a string (possibly empty) for a member without a volunteer.
        html = member_module.get_volunteer_details_html_for_member(self.member.name)
        self.assertIsInstance(html, str)
