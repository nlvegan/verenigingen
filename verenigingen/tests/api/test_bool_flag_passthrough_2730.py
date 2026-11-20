"""
#2730: a whitelisted bool flag that is PASSED THROUGH to a helper/service (follow-up to #2448).

Frappe coerces a flag only where the whitelisted function itself is annotated ``bool``. A callee's own
annotation is not applied to an internal call, so an unannotated entry point hands the raw "false" /
"0" string (truthy in Python) on. The class guard for this lives in
``test_bool_flags_over_http_2448`` (``unguarded_bool_flags(..., passthrough=True)``).

* ``TestDrivenEndpoints2730`` calls the real endpoints in-process. The welcome-mail pair was also
  measured through the WSGI app on develop: both already honoured "false"/"0" because the service
  converts with ``cbool`` (the issue's premise was not borne out); these tests pin that.
  ``auto_create_missing_dues_schedules`` and ``update_existing_imports`` stub the callee and assert it
  receives a real bool; they are red on develop.
* ``TestPassedThroughFlagsAreCoerced2730`` applies Frappe's own coercion
  (``transform_parameter_types``, what the whitelist wrapper runs) to the real endpoint objects whose
  callee tests the flag raw. Those are red on develop.

Usage:
    bench --site test_site_2 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_bool_flag_passthrough_2730
"""

import importlib
from unittest.mock import patch

import frappe
from frappe.utils.typing_validations import transform_parameter_types

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
    "verenigingen.templates.pages.mollie_payments_debug:list_subscriptions": ["active_only"],
    "verenigingen.templates.pages.mollie_payments_debug:check_balance_transaction_status": [
        "include_mollie_data"
    ],
    "verenigingen.templates.pages.mollie_payments_debug:check_all_customers_for_new_payments": [
        "all_history"
    ],
    "verenigingen.utils.orphaned_child_table_cleanup:cleanup_orphaned_child_tables": ["skip_index_check"],
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
        self.assertEqual(checked, 14 * 4)  # guards a silently shrunk table

    def test_an_unrecognised_string_is_refused(self):
        for target, params in PASSED_THROUGH.items():
            with self.assertRaises(frappe.exceptions.FrappeTypeError, msg=target):
                self._coerced(target, params[0], "maybe")


class TestDrivenEndpoints2730(VereningingenTestCase):
    """Calls the REAL whitelisted endpoints in-process.

    ``frappe.in_test`` is True under run-tests, so the whitelist wrapper coerces exactly as it does for a
    request. No commit and no second DB connection: an earlier WSGI version of the welcome-mail tests
    had to commit members for the child process and then failed 1 run in 3 in teardown with a 1205 lock
    wait on Contact. Nothing here needs the WSGI app: the endpoints are plain function calls.
    """

    FLAGS = (("false", 0), ("0", 0), ("true", 1), ("1", 1))

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _welcome_flag(self, email):
        return frappe.db.get_value("User", email, "send_welcome_email")

    def test_member_account_honours_string_flags(self):
        from verenigingen.api.member.general_api import create_member_user_account

        for raw, expected in self.FLAGS:
            member = self.create_test_member(first_name="Passthrough", last_name=f"Mail{frappe.generate_hash()[:6]}")
            with patch(SEND_MAIL):
                response = create_member_user_account(member.name, send_welcome_email=raw)
            self.assertTrue(response["success"], (raw, response))
            self.assertEqual(self._welcome_flag(member.email), expected, raw)

    def test_organization_user_honours_string_flags(self):
        from verenigingen.verenigingen.doctype.member.member import create_organization_user

        for raw, expected in self.FLAGS:
            member = self.create_test_member(first_name="Passthrough", last_name=f"Org{frappe.generate_hash()[:6]}")
            email = f"org-{frappe.generate_hash()[:8]}@test.invalid"
            with patch(SEND_MAIL):
                response = create_organization_user(member.name, email, "Org", send_welcome_email=raw)
            self.assertTrue(response["success"], (raw, response))
            self.assertEqual(self._welcome_flag(email), expected, raw)

    def test_auto_create_hands_the_callee_real_booleans(self):
        from verenigingen.services.billing import dues_schedule_auto_creator as module

        for raw, expected in (("false", False), ("0", False), ("true", True), ("1", True)):
            with patch.object(module, "auto_create_missing_dues_schedules_enhanced", return_value={}) as callee:
                module.auto_create_missing_dues_schedules(preview_mode=raw, send_emails=raw)
            callee.assert_called_once_with(preview_mode=expected, send_emails=expected)

    def test_auto_create_refuses_an_unusable_flag_without_calling_the_callee(self):
        from verenigingen.services.billing import dues_schedule_auto_creator as module

        for raw in ("maybe", "", None):
            for param in ("preview_mode", "send_emails"):
                with patch.object(module, "auto_create_missing_dues_schedules_enhanced") as callee:
                    with self.assertRaises(frappe.exceptions.FrappeTypeError, msg=(param, raw)):
                        module.auto_create_missing_dues_schedules(**{param: raw})
                callee.assert_not_called()

    def test_update_existing_imports_hands_the_manager_a_real_boolean(self):
        from verenigingen.e_boekhouden.utils import import_manager as module

        target = module.EBoekhoudenImportManager
        for raw, expected in (("false", False), ("0", False), ("true", True), ("1", True)):
            with patch.object(target, "update_existing_imports", return_value={}) as callee:
                module.update_existing_imports(force_update=raw)
            self.assertEqual(callee.call_args.args[2], expected, raw)  # "0"/"1" arrive as int 0/1

    def test_update_existing_imports_refuses_an_unusable_flag_without_calling_the_manager(self):
        from verenigingen.e_boekhouden.utils import import_manager as module

        for raw in ("maybe", "", None):
            with patch.object(module.EBoekhoudenImportManager, "update_existing_imports") as callee:
                with self.assertRaises(frappe.exceptions.FrappeTypeError, msg=raw):
                    module.update_existing_imports(force_update=raw)
            callee.assert_not_called()


class TestHandParsedFlagsAreCoerced2952(VereningingenTestCase):
    """#2952: four flags used ``isinstance(x, str)`` + ``.lower() in ("true", "1", "yes")``, which read
    "on" (and a typo such as "ture") as False. Only the parameter coercion is exercised: no gateway call
    is made, the callee is stubbed at the module boundary (``# Mock justified:`` below)."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # check_all_customers_for_new_payments takes a 60 s Redis cooldown that no rollback undoes.
        self._clear_discovery_cooldown()
        self.addCleanup(self._clear_discovery_cooldown)

    def _clear_discovery_cooldown(self):
        frappe.cache().delete(f"bulk_payment_discovery_limit:{frappe.session.user}")

    def test_on_reaches_the_gateway_helpers_as_true(self):
        from verenigingen.templates.pages import mollie_payments_debug as page

        # Mock justified: the Mollie debug service / bulk checker / status helper would call the Mollie
        # API; this test only asserts which value the endpoint hands them after parameter coercion.
        with patch.object(page, "MollieDebugService") as service:
            service.return_value.list_subscriptions.return_value = {}
            page.list_subscriptions("cst_x", active_only="on")
            self.assertEqual(service.return_value.list_subscriptions.call_args.args[2], True)
        with patch(
            "verenigingen.verenigingen_payments.api.balance_transaction_processing.check_transaction_status",
            return_value={},
        ) as status:
            page.check_balance_transaction_status("baltr_x", include_mollie_data="on")
            self.assertEqual(status.call_args.kwargs["include_mollie_data"], True)
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker.BulkPaymentChecker"
        ) as checker:
            checker.return_value.check_all_customers_for_new_payments.return_value = {}
            page.check_all_customers_for_new_payments(all_history="on")
            kwargs = checker.return_value.check_all_customers_for_new_payments.call_args.kwargs
            self.assertEqual(kwargs["all_history"], True)

    def test_an_unusable_value_is_refused_and_active_only_keeps_its_default(self):
        import inspect

        from verenigingen.templates.pages import mollie_payments_debug as page

        self.assertIs(inspect.signature(page.list_subscriptions).parameters["active_only"].default, True)
        for raw in ("maybe", "ture", ""):
            with self.assertRaises(frappe.exceptions.FrappeTypeError, msg=raw):
                page.list_subscriptions("cst_x", active_only=raw)

    def test_on_is_coerced_to_true_for_the_orphan_cleanup(self):
        from verenigingen.utils import orphaned_child_table_cleanup as module

        _args, kwargs = transform_parameter_types(
            module.cleanup_orphaned_child_tables, (), {"skip_index_check": "on"}
        )
        self.assertEqual(kwargs["skip_index_check"], True)
        with self.assertRaises(frappe.exceptions.FrappeTypeError):
            transform_parameter_types(module.cleanup_orphaned_child_tables, (), {"skip_index_check": "maybe"})
