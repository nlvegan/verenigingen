"""Regression contract for the module-level shims in
verenigingen.verenigingen.doctype.member.member.

These shims exist so that callers using the dotted-path form
(``frappe.call("verenigingen.verenigingen.doctype.member.member.<name>", doc=...)``)
can invoke whitelisted Member instance methods. JS uses
``frm.call('<name>')``, which goes through Frappe's ``run_doc_method``
resolver and never hits these shims. The shims back tests, server
scripts, and any ``/api/method/<dotted.path>`` consumers.

Pin four things per shim:

1. It is a module-level attribute (``frappe.get_attr`` resolves it).
2. It is registered in ``frappe.whitelisted`` (HTTP-callable).
3. The shared loader raises a recognizable error when ``doc`` is missing
   the ``name`` field, and ``check_permission`` is enforced.
4. The return value is JSON-serialisable by ``frappe.as_json`` (orjson),
   which is the same encoder Frappe's HTTP response handler uses. This
   catches regressions like the pre-fix ``ensure_member_id`` shim that
   returned a raw ``OperationResult`` dataclass — in-process
   ``frappe.call(...)`` tests passed because the Python object was
   truthy, but real HTTP callers would have hit a 500 from orjson.
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

    def _assert_shim_result_serialisable(self, shim_name, doc):
        """Pin the end-to-end serialisability contract for each shim.

        Round-trips the shim's return value through ``frappe.as_json``
        (stdlib ``json.dumps`` + Frappe's ``json_handler``). Adjacent
        tools — logging, debug helpers, server scripts that re-serialise
        responses, and any caller using ``frappe.as_json`` directly —
        all use this stdlib path. The canonical Frappe convention for
        whitelisted methods is to return primitives/dicts/lists, not raw
        dataclasses.

        Note: the actual HTTP response builder uses *orjson*, which DOES
        natively serialise dataclasses. So a return that fails here will
        not necessarily 500 over HTTP. But it pins the broader contract:
        if the framework decorator that auto-converts ``OperationResult``
        is ever removed from an instance method without compensation in
        the shim, this test fires.

        Catches a wide net of exception types because stdlib ``json``
        raises ``AttributeError``/``TypeError``/``ValueError`` for
        different unserialisable inputs.
        """
        result = frappe.call(
            f"verenigingen.verenigingen.doctype.member.member.{shim_name}",
            doc=doc,
        )
        try:
            frappe.as_json(result)
        except Exception as exc:  # noqa: BLE001 — pin contract, not a specific failure mode
            self.fail(
                f"{shim_name} returned a value that frappe.as_json cannot "
                f"serialise: {type(exc).__name__}: {exc}; result={result!r}"
            )

    def test_all_shim_results_are_http_serialisable(self):
        # One member covers the read-only and idempotent shims (the writes here
        # only ever set computed fields or assign a member_id, never fail
        # because the member already has the relation).
        base = self.create_test_member(
            first_name="ShimJson",
            last_name="Base",
            email=f"shim.json.base.{frappe.utils.random_string(8)}@test.com",
        )
        for shim in (
            "get_address_members_html",
            "get_current_membership_fee",
            "get_display_membership_fee",
            "update_membership_duration",
            "ensure_member_id",
        ):
            self._assert_shim_result_serialisable(shim, base.as_dict())

        # create_customer needs a member with no customer link
        cust_member = self.create_test_member(
            first_name="ShimJson",
            last_name="Cust",
            email=f"shim.json.cust.{frappe.utils.random_string(8)}@test.com",
        )
        if cust_member.customer:
            frappe.db.set_value("Member", cust_member.name, "customer", None)
            cust_member.reload()
        self._assert_shim_result_serialisable("create_customer", cust_member.as_dict())

        # create_user needs a member with no user link
        user_member = self.create_test_member(
            first_name="ShimJson",
            last_name="User",
            email=f"shim.json.user.{frappe.utils.random_string(8)}@test.com",
        )
        if user_member.user:
            frappe.db.set_value("Member", user_member.name, "user", None)
            user_member.reload()
        self._assert_shim_result_serialisable("create_user", user_member.as_dict())
