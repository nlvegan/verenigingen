"""`@standard_api(operation_type=ADMIN)` was a label, not a gate (#2753).

`standard_api` hardcodes SecurityLevel.MEDIUM; `operation_type` only picks the rate-limit class. So
every endpoint below, labelled ADMIN, ran for any MEDIUM-tier caller (a Volunteer profile is enough).
They now use `critical_api(operation_type=ADMIN)`, which requires the CRITICAL tier.

Every case dispatches through frappe.handler.execute_cmd with a real werkzeug POST and
``frappe.flags.in_test = False`` (the test-mode short-circuit in the framework is off), the way the web
server does. The attacker holds the Volunteer role profile, which clears the MEDIUM tier, so the tier
check under test is the only thing that can refuse. The refusal must be the framework's own message:
a Frappe doctype-permission refusal would be a refusal for the wrong reason.

The admin holds the Verenigingen Administrator profile (CRITICAL) plus System Manager (some bodies
carry their own System Manager / System Settings check on top); both are assigned through the real
User.role_profiles save path. Probe shortcut: the attacker is linked to the test Member with a direct
``Member.user`` write (so run_doc_method's Member read check is not what refuses).
"""

import ast
import pathlib

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import verenigingen
from verenigingen.tests.utils.base import VereningingenTestCase

REFUSAL = "Access denied. You do not have permission for this operation."

MODULE_UTILS = "verenigingen.verenigingen.doctype.member.member_utils"

# (command, kwargs the admin call passes; chosen so the body is cheap and side-effect free)
FUNCTION_ENDPOINTS = [
    (
        "verenigingen.services.member.donor.donor_customer_sync.bulk_sync_donors_to_customers",
        {"filters": {"name": "NO-SUCH-DONOR-2753"}},
    ),
    ("verenigingen.services.volunteer.expense_history_batch_processor.process_pending_expense_history_updates", {}),
    ("verenigingen.services.volunteer.expense_history_batch_processor.validate_expense_history_integrity", {}),
    ("verenigingen.services.volunteer.expense_history_batch_processor.cleanup_orphaned_expense_history", {}),
    ("verenigingen.verenigingen_payments.mollie.api.sync.bulk_sync_recent_payments", {"hours": 1}),
    (f"{MODULE_UTILS}.get_next_member_id_preview", {}),
    ("verenigingen.utils.bulk_queue_config.clear_stuck_jobs", {}),
    ("verenigingen.utils.auth_monitoring.get_auth_health_status", {}),
    ("verenigingen.utils.database_query_analyzer.analyze_database_performance", {"hours": 1}),
    ("verenigingen.utils.database_query_analyzer.get_index_recommendations", {"table_name": "not-a-table"}),
]

# Member controller methods, dispatched through run_doc_method.
DOC_METHODS = ["force_update_membership_duration", "force_update_chapter_display"]

# Endpoints that stay `standard_api(ADMIN)` because a lower role legitimately reaches them (class b in the
# #2753 report). Each is a ruling, not an oversight; a new entry here needs the same evidence.
STILL_LABELLED_ADMIN = {
    ("services/member/donor/donor_customer_sync.py", "get_sync_status_summary"),
    ("email/email_group_sync.py", "create_initial_email_groups"),
    ("email/email_group_sync.py", "sync_email_groups_manually"),
    ("email/email_group_sync.py", "get_email_group_stats"),
}


def _standard_api_admin_sites():
    """(relative path, function) for every def under the app decorated standard_api(... ADMIN ...)."""
    root = pathlib.Path(verenigingen.__file__).parent
    found = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("tests/") or "/tests/" in rel:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and getattr(dec.func, "id", getattr(dec.func, "attr", None)) == "standard_api"
                    and any("ADMIN" in ast.dump(a) for a in [*dec.args, *[k.value for k in dec.keywords]])
                ):
                    found.add((rel, node.name))
    return found


class TestAdminLabelIsAGate2753(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        suffix = frappe.generate_hash(length=6)
        self.attacker = self._setup_profiled_user_2753(f"vol-2753-{suffix}@example.org", "Verenigingen Volunteer")
        # HIGH tier, no CRITICAL: the issue measured a plain Staff user running the expense rewrite, and
        # it is what a high_security_api (wrong tier) fix would still let through.
        self.staff = self._setup_profiled_user_2753(f"stf-2753-{suffix}@example.org", "Verenigingen Staff")
        self.admin = self._setup_profiled_user_2753(
            f"adm-2753-{suffix}@example.org", "Verenigingen Administrator", ["System Manager"]
        )
        self.member = self.create_test_member()
        # The attacker is the member's own user, so Member read (run_doc_method) is not what refuses.
        frappe.db.set_value("Member", self.member.name, "user", self.attacker, update_modified=False)

    def _setup_profiled_user_2753(self, email, profile, extra_roles=()):
        user = self.create_test_user(email, roles=list(extra_roles))
        user.append("role_profiles", {"role_profile": profile})
        user.save(ignore_permissions=True)
        return email

    def _dispatch_2753(self, user, cmd, args):
        """Real dispatch. Returns (outcome, message_log_delta, error_log_delta, http_status)."""
        env = EnvironBuilder(path=f"/api/method/{cmd}", data=args, method="POST").get_environ()
        original, in_test = frappe.session.user, frappe.flags.in_test
        frappe.set_user(user)
        frappe.flags.in_test = False
        # Mock justified: Infrastructure - the request context the web server sets before execute_cmd;
        # dispatch itself, the security wrapper and the endpoint bodies are all real.
        frappe.local.request = Request(env)
        frappe.local.form_dict = frappe._dict(args)
        frappe.local.response = frappe._dict()
        # Mock justified: Infrastructure - empty request-local log so the delta below is this call's
        frappe.local.message_log = []
        errors_before = frappe.db.count("Error Log")
        try:
            try:
                frappe.handler.execute_cmd(cmd)
                outcome = ("ok", "")
            except Exception as exc:
                outcome = (type(exc).__name__, str(exc))
            return (
                outcome,
                list(frappe.local.message_log),
                frappe.db.count("Error Log") - errors_before,
                frappe.local.response.get("http_status_code"),
            )
        finally:
            # Mock justified: Infrastructure - restore the test-mode flag turned off for dispatch
            frappe.flags.in_test = in_test
            frappe.set_user(original)

    def _doc_call_2753(self, method):
        return "run_doc_method", {"dt": "Member", "dn": self.member.name, "method": method}

    def _assert_tier_refused_2753(self, result, label):
        (kind, message), _log, _errors, _status = result
        self.assertEqual(kind, "PermissionError", f"{label}: expected PermissionError, got {result}")
        self.assertEqual(message, REFUSAL, f"{label}: refused by something other than the tier gate")

    def _assert_tier_allowed_2753(self, result, label):
        (kind, message), *_ = result
        self.assertNotEqual(message, REFUSAL, f"{label}: the admin was refused by the tier gate: {result}")
        self.assertNotEqual(kind, "PermissionError", f"{label}: the admin was refused: {result}")

    def test_plain_volunteer_is_refused_and_admin_is_allowed_on_every_function_endpoint(self):
        for cmd, args in FUNCTION_ENDPOINTS:
            with self.subTest(cmd=cmd):
                self._assert_tier_refused_2753(self._dispatch_2753(self.attacker, cmd, args), f"{cmd} (volunteer)")
                self._assert_tier_refused_2753(self._dispatch_2753(self.staff, cmd, args), f"{cmd} (staff)")
                self._assert_tier_allowed_2753(self._dispatch_2753(self.admin, cmd, args), f"{cmd} (admin)")

    def test_plain_volunteer_is_refused_and_admin_is_allowed_on_every_member_method(self):
        for method in DOC_METHODS:
            with self.subTest(method=method):
                cmd, args = self._doc_call_2753(method)
                self._assert_tier_refused_2753(self._dispatch_2753(self.attacker, cmd, args), f"{method} (volunteer)")
                self._assert_tier_allowed_2753(self._dispatch_2753(self.admin, cmd, args), f"{method} (admin)")

    def test_refusal_is_identical_with_valid_and_unknown_arguments(self):
        """The refusal carries nothing that tells a probe whether its arguments were right.

        Compared on every channel: exception type and text, message_log, Error Log rows and HTTP status.
        (Frappe validates a typed argument such as ``hours: int`` BEFORE the security wrapper runs, so a
        wrongly TYPED value is rejected by Frappe itself, for every whitelisted function alike; that
        is outside this change and is why the probe argument here is an unknown name, not a bad type.)
        """
        for cmd, args in FUNCTION_ENDPOINTS:
            with self.subTest(cmd=cmd):
                valid = self._dispatch_2753(self.attacker, cmd, args)
                unknown = self._dispatch_2753(self.attacker, cmd, {"no_such_argument_2753": "x"})
                self._assert_tier_refused_2753(valid, cmd)
                self.assertEqual(valid, unknown, f"{cmd}: refusal differs by argument shape")

    def test_scheduler_context_still_reaches_the_scheduled_endpoints(self):
        """The three expense jobs run from hooks.scheduler_events as Administrator, not over HTTP."""
        from verenigingen.services.volunteer import expense_history_batch_processor as mod

        for name in (
            "process_pending_expense_history_updates",
            "validate_expense_history_integrity",
            "cleanup_orphaned_expense_history",
        ):
            with self.subTest(job=name):
                getattr(mod, name)()  # raises PermissionError if the new tier refused the scheduler

    def test_no_new_standard_api_admin_label_appears(self):
        """The label cannot mislead again: only the ruled (class b) sites may keep it."""
        found = _standard_api_admin_sites()
        self.assertEqual(found, STILL_LABELLED_ADMIN)
        # control: the scan really sees a decorated site (it is not vacuously empty)
        self.assertTrue(STILL_LABELLED_ADMIN <= found)
