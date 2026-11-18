"""
#2730: a whitelisted bool flag that is PASSED THROUGH to a helper/service (follow-up to #2448).

Frappe coerces a flag only where the whitelisted function itself is annotated ``bool``. A callee's own
annotation is not applied to an internal call, so an unannotated entry point hands the raw "false" /
"0" string (truthy in Python) on. The class guard for this lives in
``test_bool_flags_over_http_2448`` (``unguarded_bool_flags(..., passthrough=True)``).

* ``TestWelcomeMailFlagOverHttp2730`` drives the two welcome-mail endpoints through the real WSGI app.
  Measured on develop: both already honoured "false"/"0" because the service converts with ``cbool``
  (the issue's premise was not borne out); the tests pin that so a refactor cannot lose it.
* ``TestPassedThroughFlagsAreCoerced2730`` applies Frappe's own coercion
  (``transform_parameter_types``, what the whitelist wrapper runs) to the real endpoint objects whose
  callee tests the flag raw. Those are red on develop.

Usage:
    bench --site test_site_2 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_bool_flag_passthrough_2730
"""

import importlib

import frappe
from frappe.utils.typing_validations import transform_parameter_types

from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    run_wsgi_cases,
)
from verenigingen.tests.utils.base import VereningingenTestCase

SEND_MAIL = "frappe.core.doctype.user.user.User.send_welcome_mail_to_user"

# "module:function" -> flag parameters that an unannotated entry point used to hand on as a raw string.
PASSED_THROUGH = {
    "verenigingen.api.member.general_api:create_member_user_account": ["send_welcome_email"],
    "verenigingen.verenigingen.doctype.member.member:create_organization_user": ["send_welcome_email"],
    "verenigingen.services.billing.dues_schedule_auto_creator:auto_create_missing_dues_schedules": [
        "preview_mode",
        "send_emails",
    ],
    "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings:reclassify_accounts_by_group_mappings": [
        "dry_run"
    ],
    "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings:reorganize_account_hierarchy": [
        "dry_run"
    ],
    "verenigingen.e_boekhouden.utils.import_manager:update_existing_imports": ["force_update"],
    "verenigingen.utils.api_endpoint_optimizer:run_api_optimization": ["dry_run"],
    "verenigingen.utils.admin_utilities.mandate_sync_utility:run_mandate_sync": ["dry_run"],
    "verenigingen.utils.migration.stock_migration:migrate_stock_transactions_standalone": ["dry_run"],
}


class TestPassedThroughFlagsAreCoerced2730(VereningingenTestCase):
    def _coerced(self, target, param, raw):
        module_name, name = target.split(":")
        endpoint = getattr(importlib.import_module(module_name), name)
        _args, kwargs = transform_parameter_types(endpoint, (), {param: raw})
        return kwargs[param]

    def test_string_flags_are_coerced_before_the_body_runs(self):
        checked = 0
        for target, params in PASSED_THROUGH.items():
            for param in params:
                for raw, expected in (("false", False), ("0", False), ("true", True), ("1", True)):
                    self.assertEqual(self._coerced(target, param, raw), expected, (target, param, raw))
                    checked += 1
        self.assertEqual(checked, 10 * 4)  # guards a silently shrunk table

    def test_an_unrecognised_string_is_refused(self):
        for target, params in PASSED_THROUGH.items():
            with self.assertRaises(frappe.exceptions.FrappeTypeError, msg=target):
                self._coerced(target, params[0], "maybe")


class TestWelcomeMailFlagOverHttp2730(CommittedLoginUsersMixin, VereningingenTestCase):
    """The observable is ``User.send_welcome_email``: User.after_insert mails only when it is set."""

    def setUp(self):
        super().setUp()
        self.admin = self._create_login_users(admin="Verenigingen Administrator")["admin"]

    def _new_member(self):
        member = self.create_test_member(first_name="Passthrough", last_name=f"Mail{frappe.generate_hash()[:6]}")
        frappe.db.commit()  # the WSGI child is another connection and sees only committed rows
        self.addCleanup(self._drop_user, member.email)
        return member

    def _drop_user(self, email):
        frappe.db.rollback()
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _post(self, dotted, payload):
        case = {
            "name": "c",
            "endpoint": api_path(dotted),
            "login": {"usr": self.admin, "pwd": self.password},
            "csrf": "valid",
            "json": payload,
        }
        response = run_wsgi_cases(case, patches=(SEND_MAIL,))["c"]
        self.assertEqual(response["status"], 200, response["body"][:300])
        frappe.db.rollback()  # drop this connection's snapshot so the child's commit is visible
        return response

    def _welcome_flag(self, email):
        return frappe.db.get_value("User", email, "send_welcome_email")

    def test_member_account_honours_string_flags(self):
        for raw, expected in (("false", 0), ("0", 0), ("true", 1), ("1", 1)):
            member = self._new_member()
            self._post(
                "verenigingen.api.member.general_api.create_member_user_account",
                {"member_name": member.name, "send_welcome_email": raw},
            )
            self.assertEqual(self._welcome_flag(member.email), expected, raw)

    def test_organization_user_honours_string_flags(self):
        for raw, expected in (("false", 0), ("0", 0), ("true", 1), ("1", 1)):
            member = self._new_member()
            email = f"org-{frappe.generate_hash()[:8]}@test.invalid"
            self.addCleanup(self._drop_user, email)
            self._post(
                "verenigingen.verenigingen.doctype.member.member.create_organization_user",
                {"member": member.name, "email": email, "first_name": "Org", "send_welcome_email": raw},
            )
            self.assertEqual(self._welcome_flag(email), expected, raw)
