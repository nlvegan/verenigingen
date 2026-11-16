"""
#2448: whitelisted functions that test a boolean parameter bare (``if flag:``).

Follow-up to #2385. Over HTTP a flag arrives as a string and ``"0"`` / ``"false"`` are truthy in
Python. The mechanism used here is Frappe's own: a parameter annotated ``bool`` is coerced by the
``frappe.whitelist`` wrapper before the body runs ("0"/"false"/"no"/"off" -> falsy, "1"/"true" ->
truthy, anything else is refused with a type error), so the body never sees the raw string.

* ``TestAnnotationCoercesOverHttp`` drives the real WSGI app for one endpoint that echoes its flag.
* ``TestEveryUnsafeFlagIsAnnotated`` pins the 18 parameters this issue fixed, by name, on the real
  function objects (most sit behind rate limits, role gates or side effects that cannot be driven over
  HTTP from a unit test).
* ``TestNoUnguardedBoolFlagLeft`` is the class guard: an AST census of every whitelisted function with
  a ``True``/``False``-default parameter that is tested bare and neither annotated ``bool`` nor
  converted first. It has a control: the same detector must flag a synthetic offender.

Usage:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_bool_flags_over_http_2448
"""

import ast
import importlib
import inspect
import json
import os

import frappe

import verenigingen
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    run_wsgi_cases,
)
from verenigingen.tests.utils.base import VereningingenTestCase

SAFE_CALLS = {"cbool", "cint", "is_dry_run", "is_confirmed", "int", "bool", "safe_int", "sbool"}

# "module:qualname" -> parameters fixed by #2448 (a bare ``if`` on a string flag). Parameters that were
# already annotated on develop are not listed (the census never flagged them: see the class guard).
FIXED = {
    "verenigingen.services.billing.dues_schedule_health_manager:sync_all_member_fields": ["continue_on_error"],
    "verenigingen.services.billing.dues_schedule_auto_creator:auto_create_missing_dues_schedules_enhanced": [
        "preview_mode",
        "send_emails",
    ],
    "verenigingen.services.billing.invoice_management:bulk_generate_dues_invoices": ["dry_run"],
    "verenigingen.services.billing.invoice_management:get_dues_schedules_summary": ["include_orphaned"],
    "verenigingen.services.billing.invoice_management:cleanup_orphaned_schedules": ["dry_run"],
    "verenigingen.services.billing.invoice_management:cleanup_orphaned_member_references": ["dry_run"],
    "verenigingen.services.billing.invoice_management:cleanup_orphaned_membership_data": ["dry_run"],
    "verenigingen.verenigingen_payments.api.sepa_mandate_management:create_missing_sepa_mandates": ["dry_run"],
    "verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import:process_import_background": [
        "test_mode"
    ],
    "verenigingen.verenigingen.doctype.procurios_membership_import.procurios_membership_import:process_import_background": [
        "test_mode"
    ],
    "verenigingen.verenigingen.doctype.member_import.member_import:process_import_background": ["test_mode"],
    "verenigingen.e_boekhouden.services.account_hierarchy_service:reorganize_account_hierarchy": ["dry_run"],
    "verenigingen.e_boekhouden.services.account_hierarchy_service:reclassify_accounts_by_group_mappings": [
        "dry_run"
    ],
    "verenigingen.e_boekhouden.utils.import_manager:EBoekhoudenImportManager.update_existing_imports": [
        "force_update"
    ],
    "verenigingen.verenigingen.page.membership_analytics.membership_analytics:get_dashboard_data": [
        "compare_previous"
    ],
    "verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry:generate_expulsion_governance_report": [
        "include_appeals"
    ],
    "verenigingen.verenigingen.doctype.periodic_donation_agreement.periodic_donation_agreement:PeriodicDonationAgreement.cancel_agreement": [
        "send_email"
    ],
}


def _resolve_whitelisted_target_2448(target):
    module_name, qualname = target.split(":")
    obj = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _tested_bare(fn, param):
    for node in ast.walk(fn):
        test = node.test if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)) else None
        if test is not None and any(isinstance(n, ast.Name) and n.id == param for n in ast.walk(test)):
            return True
    return False


def _converted_first(fn, param):
    for node in ast.walk(fn):
        # ``if isinstance(flag, str): flag = <parse>`` (hand-rolled, but it converts before use)
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Call)
            and getattr(node.test.func, "id", "") == "isinstance"
            and isinstance(node.test.args[0], ast.Name)
            and node.test.args[0].id == param
        ):
            return True
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == param for t in node.targets):
            for call in ast.walk(node.value):
                if isinstance(call, ast.Call) and getattr(call.func, "id", getattr(call.func, "attr", "")) in SAFE_CALLS:
                    return True
    return False


def unguarded_bool_flags(source):
    """[(function, param)] for whitelisted functions testing a bool-default param bare, unannotated."""
    found = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any("whitelist" in ast.unparse(d) for d in fn.decorator_list):
            continue
        args = fn.args
        positional = args.posonlyargs + args.args
        defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
        pairs = list(zip(positional, defaults)) + list(zip(args.kwonlyargs, args.kw_defaults))
        for arg, default in pairs:
            if not (isinstance(default, ast.Constant) and isinstance(default.value, bool)):
                continue
            annotated = arg.annotation is not None and ast.unparse(arg.annotation) == "bool"
            if not annotated and _tested_bare(fn, arg.arg) and not _converted_first(fn, arg.arg):
                found.append((fn.name, arg.arg))
    return found


class TestNoUnguardedBoolFlagLeft(VereningingenTestCase):
    def test_detector_flags_a_synthetic_offender(self):
        """Control: without this the tree scan below could be returning [] because it sees nothing."""
        source = (
            "@frappe.whitelist()\ndef bad(force=False):\n    if force:\n        pass\n\n"
            "@frappe.whitelist()\ndef annotated(force: bool = False):\n    if force:\n        pass\n\n"
            "@frappe.whitelist()\ndef converted(force=False):\n    force = cbool(force)\n    if force:\n        pass\n\n"
            "def not_whitelisted(force=False):\n    if force:\n        pass\n"
        )
        self.assertEqual(unguarded_bool_flags(source), [("bad", "force")])

    def test_no_whitelisted_function_tests_an_unannotated_bool_flag_bare(self):
        root = os.path.dirname(os.path.dirname(verenigingen.__file__))
        offenders = []
        for top in ("verenigingen", "scripts"):
            for dirpath, _dirs, files in os.walk(os.path.join(root, top)):
                if os.sep + "tests" in dirpath or "node_modules" in dirpath:
                    continue
                for name in files:
                    if not name.endswith(".py") or name.startswith("test_"):
                        continue
                    path = os.path.join(dirpath, name)
                    try:
                        with open(path, encoding="utf-8") as handle:
                            hits = unguarded_bool_flags(handle.read())
                    except (SyntaxError, UnicodeDecodeError):
                        continue
                    offenders += [f"{os.path.relpath(path, root)}:{fn}({param})" for fn, param in hits]
        self.assertEqual(offenders, [])


class TestEveryUnsafeFlagIsAnnotated(VereningingenTestCase):
    def test_each_fixed_parameter_is_annotated_bool(self):
        checked = 0
        for target, params in FIXED.items():
            func = inspect.unwrap(_resolve_whitelisted_target_2448(target))
            hints = inspect.signature(func).parameters
            for param in params:
                self.assertIn(param, hints, (target, param))
                self.assertIn(hints[param].annotation, (bool, "bool"), (target, param))
                checked += 1
        self.assertEqual(checked, 18)  # the 18 parameters the census listed; guards a silently shrunk table


class TestAnnotationCoercesOverHttp(CommittedLoginUsersMixin, VereningingenTestCase):
    """bulk_generate_dues_invoices echoes ``dry_run``; the filter matches no schedule, so a real run is harmless."""

    def setUp(self):
        super().setUp()
        self.user = self._create_login_users(admin="Verenigingen Administrator")["admin"]

    def _post(self, dry_run):
        case = {
            "name": "c",
            "endpoint": api_path("verenigingen.services.billing.invoice_management.bulk_generate_dues_invoices"),
            "login": {"usr": self.user, "pwd": self.password},
            "csrf": "valid",
            "json": {"filter_criteria": {"member": "zz-2448-no-such-member"}, "dry_run": dry_run},
        }
        return run_wsgi_cases(case)["c"]

    def test_string_flags_are_converted_before_the_body_runs(self):
        for flag, expected in (("0", False), ("false", False), ("true", True), ("1", True)):
            response = self._post(flag)
            self.assertEqual(response["status"], 200, (flag, response["body"][:300]))
            message = json.loads(response["body"])["message"]
            data = message.get("data", message)
            self.assertEqual(bool(data["dry_run"]), expected, (flag, data))

    def test_an_unrecognised_string_is_refused_not_treated_as_a_flag(self):
        response = self._post("maybe")
        self.assertNotEqual(response["status"], 200, response["body"][:300])
