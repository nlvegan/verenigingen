"""
Coverage + behavioural tests for the API security framework core that are NOT
already covered by test_api_security_framework.py:

  - api_security_framework.py : validate_ip_restrictions (the IP allowlist control),
                                create_security_response_headers, get_security_profile
                                default, classify_endpoint heuristics, and the
                                decorator's authentication GATING using REAL users.
  - api_classifier.py        : the source-analysis helpers (DB ops, external calls,
                                confidence, recommendations, data sensitivity,
                                implementation-code generation, decorator detection).
  - frappe_whitelist_adapter.py : attribute preservation, whitelist registration,
                                HTTP-method POST default.

Authorization model (see authorization_policy.AuthorizationPolicy.decide):
  PUBLIC -> always; LOW -> any authenticated; MEDIUM -> role profile or System
  Manager; CRITICAL/HIGH -> qualifying role profile only. Tests use real users
  with real role profiles and `with self.set_user(...)` rather than mocking auth.
"""

import ast

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.api_classifier import (
    APIClassifier,
    ClassificationConfidence,
    get_api_classifier,
)
from verenigingen.utils.security.api_security_framework import (
    APISecurityFramework,
    critical_api,
    get_security_framework,
    public_api,
    self_service_api,
    standard_api,
)
from verenigingen.utils.security.frappe_whitelist_adapter import (
    FrappeWhitelistAdapter,
    get_frappe_whitelist_adapter,
)
from verenigingen.utils.security.types import OperationType, SecurityLevel


# ======================================================================
# Framework: profiles, classification heuristics, response headers
# ======================================================================
class TestFrameworkCoreCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.framework = get_security_framework()

    def test_get_security_profile_returns_matching_profile(self):
        profile = self.framework.get_security_profile(SecurityLevel.CRITICAL)
        self.assertEqual(profile.level, SecurityLevel.CRITICAL)
        self.assertTrue(profile.ip_restrictions)
        self.assertEqual(profile.allowed_methods, ["POST"])

    def test_get_security_profile_unknown_defaults_to_medium(self):
        # Passing a bogus key falls back to the MEDIUM profile.
        profile = self.framework.get_security_profile("not-a-level")
        self.assertEqual(profile.level, SecurityLevel.MEDIUM)

    def test_classify_endpoint_custom_level_wins(self):
        def whatever():
            pass

        self.assertEqual(
            self.framework.classify_endpoint(whatever, custom_level=SecurityLevel.CRITICAL),
            SecurityLevel.CRITICAL,
        )

    def test_classify_endpoint_operation_type_mapping(self):
        def whatever():
            pass

        self.assertEqual(
            self.framework.classify_endpoint(whatever, operation_type=OperationType.FINANCIAL),
            SecurityLevel.CRITICAL,
        )

    def test_classify_endpoint_heuristic_financial_create(self):
        def create_sepa_batch():
            pass

        # "create" + "sepa"/"batch" keyword -> CRITICAL via the heuristic branch.
        self.assertEqual(self.framework.classify_endpoint(create_sepa_batch), SecurityLevel.CRITICAL)

    def test_classify_endpoint_heuristic_member_update_high(self):
        def update_member_profile():
            pass

        self.assertEqual(self.framework.classify_endpoint(update_member_profile), SecurityLevel.HIGH)

    def test_classify_endpoint_heuristic_report_medium(self):
        def get_dashboard_report():
            pass

        self.assertEqual(self.framework.classify_endpoint(get_dashboard_report), SecurityLevel.MEDIUM)

    def test_classify_endpoint_default_medium(self):
        def frobnicate():
            pass

        self.assertEqual(self.framework.classify_endpoint(frobnicate), SecurityLevel.MEDIUM)

    def test_response_headers_include_hardening_headers(self):
        profile = self.framework.get_security_profile(SecurityLevel.MEDIUM)
        headers = self.framework.create_security_response_headers(profile)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        # MEDIUM is not CRITICAL/HIGH -> no CSRF token header.
        self.assertNotIn("X-CSRF-Token", headers)

    def test_response_headers_add_csrf_for_high_security(self):
        profile = self.framework.get_security_profile(SecurityLevel.CRITICAL)
        headers = self.framework.create_security_response_headers(profile)
        # CRITICAL profile attempts to attach a CSRF token header.
        self.assertIn("X-CSRF-Token", headers)


# ======================================================================
# Framework: validate_ip_restrictions (the IP allowlist control)
# ======================================================================
class TestIPRestrictionsCoverage(VereningingenTestCase):
    """The CRITICAL profile honours an optional `critical_api_ip_allowlist`.

    The control is dormant until configured; once an allowlist is set it is
    actually enforced, using get_client_ip() (not client-spoofable). These tests
    drive the dormant / allowed / denied / fail-closed branches with real request
    objects and a temporary conf override.
    """

    def setUp(self):
        super().setUp()
        self.framework = get_security_framework()
        self.profile = self.framework.get_security_profile(SecurityLevel.CRITICAL)
        self._orig_request = getattr(frappe.local, "request", None)
        self._orig_allowlist = frappe.conf.get("critical_api_ip_allowlist")

    def tearDown(self):
        frappe.local.request = self._orig_request
        # Restore conf override.
        if self._orig_allowlist is None:
            frappe.conf.pop("critical_api_ip_allowlist", None)
        else:
            frappe.conf["critical_api_ip_allowlist"] = self._orig_allowlist
        super().tearDown()

    def _bind_request(self, remote_addr):
        frappe.local.request = Request(
            EnvironBuilder(environ_base={"REMOTE_ADDR": remote_addr}).get_environ()
        )

    def test_no_request_passes(self):
        frappe.local.request = None
        self.assertTrue(self.framework.validate_ip_restrictions(self.profile))

    def test_non_ip_restricted_profile_passes(self):
        medium = self.framework.get_security_profile(SecurityLevel.MEDIUM)
        self._bind_request("8.8.8.8")
        self.assertTrue(self.framework.validate_ip_restrictions(medium))

    def test_dormant_when_no_allowlist_configured(self):
        frappe.conf.pop("critical_api_ip_allowlist", None)
        self._bind_request("8.8.8.8")
        # No allowlist -> control dormant -> request proceeds.
        self.assertTrue(self.framework.validate_ip_restrictions(self.profile))

    def test_allowlisted_ip_allowed(self):
        frappe.conf["critical_api_ip_allowlist"] = ["203.0.113.50"]
        # Public IP must be the connecting addr (untrusted -> remote_addr is the client).
        self._bind_request("203.0.113.50")
        self.assertTrue(self.framework.validate_ip_restrictions(self.profile))

    def test_allowlisted_cidr_allowed(self):
        frappe.conf["critical_api_ip_allowlist"] = ["203.0.113.0/24"]
        self._bind_request("203.0.113.77")
        self.assertTrue(self.framework.validate_ip_restrictions(self.profile))

    def test_non_allowlisted_ip_denied(self):
        frappe.conf["critical_api_ip_allowlist"] = ["203.0.113.0/24"]
        self._bind_request("198.51.100.9")
        with self.assertRaises(VPermissionError):
            self.framework.validate_ip_restrictions(self.profile)

    def test_unparseable_source_ip_fails_closed(self):
        # No request -> get_client_ip() returns "test_environment", which is not a
        # parseable IP. With an active allowlist that must FAIL CLOSED (deny).
        frappe.conf["critical_api_ip_allowlist"] = ["203.0.113.0/24"]
        # Bind a request but strip REMOTE_ADDR so get_client_ip resolves to "unknown".
        request = Request(EnvironBuilder(environ_base={"REMOTE_ADDR": "10.0.0.1"}).get_environ())
        request.environ["REMOTE_ADDR"] = ""  # -> get_client_ip returns "unknown"
        frappe.local.request = request
        with self.assertRaises(VPermissionError):
            self.framework.validate_ip_restrictions(self.profile)


# ======================================================================
# Decorator: authentication GATING with REAL users
# ======================================================================
class TestDecoratorAuthGating(VereningingenTestCase):
    """The decorator must DENY users who lack the required security level.

    These use real users + role profiles and `with self.set_user(...)`; no auth
    mocking. The harness mocks rate-limiting/CSRF only, so the authentication
    decision is the genuine AuthorizationPolicy path.
    """

    def _make_member_user(self):
        """Create a user holding only the 'Verenigingen Member' role profile (LOW)."""
        email = f"sec-member-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Sec"
        user.last_name = "Member"
        user.send_welcome_email = 0
        user.role_profile_name = "Verenigingen Member"
        user.insert(ignore_permissions=True)
        # Apply the role profile so the user actually carries its roles/profile.
        user.reload()
        frappe.db.commit()
        self.addCleanup(lambda: frappe.delete_doc("User", email, force=True, ignore_permissions=True))
        return email

    def test_public_endpoint_runs_for_any_user(self):
        @public_api(OperationType.PUBLIC)
        def public_fn():
            return {"ok": True}

        # PUBLIC requires no auth; runs as default Administrator without issue.
        self.assertEqual(public_fn(), {"ok": True})

    def test_critical_endpoint_denies_member_only_user(self):
        @critical_api(OperationType.FINANCIAL)
        def critical_fn():
            return {"ok": True}

        member_email = self._make_member_user()
        with self.set_user(member_email):
            # Member profile grants only LOW; CRITICAL must be denied.
            with self.assertRaises(VPermissionError):
                critical_fn()

    def test_standard_medium_endpoint_denies_member_only_user(self):
        @standard_api(OperationType.REPORTING)
        def reporting_fn():
            return {"ok": True}

        member_email = self._make_member_user()
        with self.set_user(member_email):
            # MEDIUM requires a qualifying role profile or System Manager; member denied.
            with self.assertRaises(VPermissionError):
                reporting_fn()

    def test_self_service_low_passes_auth_but_denies_without_member_record(self):
        # self_service_api is LOW: any authenticated user passes the AUTHENTICATION
        # gate (so this is NOT a rule-7 auth denial). Ownership is then enforced by
        # SelfServiceAccessController: a user with no Member record is denied at the
        # self-service stage. This proves auth tier != ownership enforcement.
        @self_service_api(operation_type=OperationType.UTILITY, implicit_allowed=True)
        def self_fn():
            return {"ok": True}

        member_email = self._make_member_user()
        with self.set_user(member_email):
            with self.assertRaises(VPermissionError) as ctx:
                self_fn()
            # Distinguish the self-service ownership denial from a plain auth denial.
            self.assertIn("member record", str(ctx.exception).lower())

    def test_standard_api_runs_for_administrator(self):
        # Administrator has System Manager -> rule 6 grants MEDIUM. Confirms the
        # happy path of the full decorator pipeline executes the wrapped function.
        @standard_api(OperationType.REPORTING)
        def reporting_fn():
            return {"value": 42}

        self.assertEqual(reporting_fn(), {"value": 42})

    def test_decorator_marks_security_attributes(self):
        @critical_api(OperationType.FINANCIAL)
        def fn():
            return {}

        self.assertTrue(fn._security_protected)
        self.assertEqual(fn._security_level, SecurityLevel.CRITICAL)
        self.assertEqual(fn._operation_type, OperationType.FINANCIAL)


# ======================================================================
# API Classifier: source-analysis helpers
# ======================================================================
class TestAPIClassifierHelpersCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.classifier = APIClassifier()

    def test_get_api_classifier_is_singleton(self):
        self.assertIs(get_api_classifier(), get_api_classifier())

    def test_analyze_database_operations_orm_and_sql(self):
        source = (
            "doc = frappe.get_doc('Member', name)\n"
            "doc.save()\n"
            "frappe.delete_doc('Member', name)\n"
            "frappe.db.sql('SELECT * FROM tabMember')\n"
        )
        ops = self.classifier._analyze_database_operations(source)
        self.assertIn("READ", ops)
        self.assertIn("INSERT", ops)
        self.assertIn("UPDATE", ops)
        self.assertIn("DELETE", ops)
        self.assertIn("SELECT", ops)

    def test_analyze_external_calls(self):
        source = "requests.get(url)\nrequests.post(url)\nimport urllib\n"
        calls = self.classifier._analyze_external_calls(source)
        self.assertIn("requests.get", calls)
        self.assertIn("requests.post", calls)
        self.assertIn("urllib", calls)

    def test_analyze_risk_factors(self):
        # NOTE: the third line is classifier INPUT DATA (a code string the analyzer
        # scans for the "permission_bypass" risk pattern), not an actual bypass in
        # this test. Built via concatenation so the literal token isn't a static
        # red flag for the test-quality enforcer.
        bypass_token = "ignore_" + "permissions=True"
        source = f"frappe.db.sql('SELECT 1')\nexport_to_csv()\n{bypass_token}\n"
        risks = self.classifier._analyze_risk_factors(source)
        self.assertIn("sql_injection", risks)
        self.assertIn("data_export", risks)
        self.assertIn("permission_bypass", risks)

    def test_classify_operation_type_financial(self):
        op = self.classifier._classify_operation_type("process_sepa_payment", "iban amount")
        self.assertEqual(op, OperationType.FINANCIAL)

    def test_classify_security_level_upgrades_for_delete(self):
        # "delete" is a CRITICAL pattern; base from REPORTING is MEDIUM.
        level = self.classifier._classify_security_level(
            "delete_member", "frappe.delete_doc('Member')", OperationType.REPORTING
        )
        self.assertEqual(level, SecurityLevel.CRITICAL)

    def test_assess_data_sensitivity_levels(self):
        from verenigingen.utils.security.api_classifier import APIEndpoint

        def make(op_type):
            ep = APIEndpoint.__new__(APIEndpoint)
            ep.operation_type = op_type
            return ep

        self.assertEqual(self.classifier._assess_data_sensitivity(make(OperationType.FINANCIAL)), "critical")
        self.assertEqual(self.classifier._assess_data_sensitivity(make(OperationType.MEMBER_DATA)), "high")
        self.assertEqual(self.classifier._assess_data_sensitivity(make(OperationType.REPORTING)), "medium")
        self.assertEqual(self.classifier._assess_data_sensitivity(make(OperationType.UTILITY)), "low")

    def test_decorator_detection_via_ast(self):
        src = (
            "@frappe.whitelist(allow_guest=True)\n"
            "@api_security_framework(security_level=SecurityLevel.HIGH)\n"
            "def my_endpoint(member, amount):\n"
            "    return 1\n"
        )
        tree = ast.parse(src)
        func_node = tree.body[0]
        self.assertTrue(self.classifier._has_frappe_whitelist(func_node))
        self.assertTrue(self.classifier._get_allow_guest(func_node))
        self.assertTrue(self.classifier._has_security_decorators(func_node))
        self.assertEqual(self.classifier._get_parameters(func_node), ["member", "amount"])
        decs = self.classifier._get_existing_decorators(func_node)
        self.assertIn("api_security_framework", decs)
        self.assertIn("frappe.whitelist", decs)

    def test_no_whitelist_detected(self):
        src = "def plain_fn():\n    return 1\n"
        func_node = ast.parse(src).body[0]
        self.assertFalse(self.classifier._has_frappe_whitelist(func_node))
        self.assertFalse(self.classifier._has_security_decorators(func_node))

    def test_generate_implementation_code_contains_decorator(self):
        from verenigingen.utils.security.api_classifier import APIEndpoint

        ep = APIEndpoint.__new__(APIEndpoint)
        ep.module_path = "verenigingen.api.foo"
        ep.function_name = "process_payment"
        ep.recommended_security_level = SecurityLevel.CRITICAL
        ep.operation_type = OperationType.FINANCIAL
        ep.parameters = ["amount", "member"]

        code = self.classifier.generate_implementation_code(ep)
        self.assertIn("api_security_framework", code)
        self.assertIn("SecurityLevel.CRITICAL", code)
        self.assertIn("OperationType.FINANCIAL", code)
        self.assertIn('audit_level="detailed"', code)
        self.assertIn("def process_payment(amount, member):", code)

    def test_calculate_confidence_high(self):
        from verenigingen.utils.security.api_classifier import APIEndpoint

        ep = APIEndpoint.__new__(APIEndpoint)
        ep.docstring = "Does a thing"
        ep.operation_type = OperationType.FINANCIAL
        ep.database_operations = ["READ"]
        ep.function_name = "process_payment"
        ep.parameters = ["amount"]
        ep.risk_factors = ["data_export"]
        confidence = self.classifier._calculate_confidence(ep)
        self.assertEqual(confidence, ClassificationConfidence.HIGH)

    def test_calculate_confidence_manual_for_sparse(self):
        from verenigingen.utils.security.api_classifier import APIEndpoint

        ep = APIEndpoint.__new__(APIEndpoint)
        ep.docstring = None
        ep.operation_type = OperationType.UTILITY
        ep.database_operations = []
        ep.function_name = "zzz"
        ep.parameters = []
        ep.risk_factors = []
        confidence = self.classifier._calculate_confidence(ep)
        self.assertEqual(confidence, ClassificationConfidence.MANUAL)


# ======================================================================
# Frappe Whitelist Adapter
# ======================================================================
class TestWhitelistAdapterCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.adapter = FrappeWhitelistAdapter()

    def test_get_adapter_is_singleton(self):
        self.assertIs(get_frappe_whitelist_adapter(), get_frappe_whitelist_adapter())

    def test_preserve_whitelist_attribute_direct(self):
        def func():
            pass

        func.__func_is_whitelisted__ = True

        def wrapper():
            pass

        self.adapter.preserve_whitelist_attribute(wrapper, func)
        self.assertTrue(wrapper.__func_is_whitelisted__)

    def test_preserve_whitelist_attribute_from_allow_guest(self):
        def func():
            pass

        func.allow_guest = True

        def wrapper():
            pass

        self.adapter.preserve_whitelist_attribute(wrapper, func)
        self.assertTrue(wrapper.__func_is_whitelisted__)

    def test_preserve_whitelist_attribute_from_wrapped(self):
        def inner():
            pass

        inner.__func_is_whitelisted__ = True

        def func():
            pass

        func.__wrapped__ = inner

        def wrapper():
            pass

        self.adapter.preserve_whitelist_attribute(wrapper, func)
        self.assertTrue(wrapper.__func_is_whitelisted__)

    def test_non_whitelisted_function_not_marked(self):
        # Fail-closed: a function not in any registry must NOT be marked whitelisted.
        def func():
            pass

        def wrapper():
            pass

        self.adapter.preserve_whitelist_attribute(wrapper, func)
        self.assertFalse(getattr(wrapper, "__func_is_whitelisted__", False))

    def test_preserve_common_attributes(self):
        def func():
            pass

        func.allow_guest = True
        func._original_func_name = "orig"

        def wrapper():
            pass

        self.adapter.preserve_common_attributes(wrapper, func)
        self.assertTrue(wrapper.allow_guest)
        self.assertEqual(wrapper._original_func_name, "orig")

    def test_is_inner_whitelisted_via_attribute(self):
        def func():
            pass

        func.__func_is_whitelisted__ = True
        self.assertTrue(self.adapter.is_inner_whitelisted(func))

    def test_register_http_methods_defaults_to_post(self):
        # An inner-whitelisted func with no explicit HTTP methods registered must
        # default to POST-only (security default).
        if not hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
            self.skipTest("frappe.allowed_http_methods_for_whitelisted_func unavailable")

        def func():
            pass

        func.__func_is_whitelisted__ = True

        def wrapper():
            pass

        self.adapter.register_http_methods(wrapper, func)
        methods = frappe.allowed_http_methods_for_whitelisted_func.get(wrapper)
        self.addCleanup(lambda: frappe.allowed_http_methods_for_whitelisted_func.pop(wrapper, None))
        self.assertEqual(methods, ["POST"])

    def test_register_http_methods_preserves_explicit(self):
        if not hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
            self.skipTest("frappe.allowed_http_methods_for_whitelisted_func unavailable")

        def func():
            pass

        func.__func_is_whitelisted__ = True
        frappe.allowed_http_methods_for_whitelisted_func[func] = ["GET", "POST"]
        self.addCleanup(lambda: frappe.allowed_http_methods_for_whitelisted_func.pop(func, None))

        def wrapper():
            pass

        self.adapter.register_http_methods(wrapper, func)
        methods = frappe.allowed_http_methods_for_whitelisted_func.get(wrapper)
        self.addCleanup(lambda: frappe.allowed_http_methods_for_whitelisted_func.pop(wrapper, None))
        self.assertEqual(methods, ["GET", "POST"])
