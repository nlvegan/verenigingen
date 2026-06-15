# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Tests for verenigingen.utils.security.api_classifier.

The APIClassifier scans the real verenigingen/api/ source tree, parses each file
with AST, and classifies @frappe.whitelist endpoints by security level / operation
type / risk. These tests drive the classifier on real source and assert the
classification logic and report structure, plus the whitelisted API wrappers.
"""

import ast

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.api_classifier import (
    APIClassifier,
    APIEndpoint,
    ClassificationConfidence,
    classify_all_api_endpoints,
    generate_migration_report,
    get_api_classifier,
    get_implementation_code,
    setup_api_classifier,
)
from verenigingen.utils.security.types import OperationType, SecurityLevel


def _func_node(source: str) -> ast.FunctionDef:
    """Parse a snippet and return its first FunctionDef node."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            return node
    raise ValueError("no function in snippet")


class TestClassifierPureLogic(EnhancedTestCase):
    """Direct tests of the classifier's pure analysis helpers (no DB needed)."""

    def setUp(self):
        super().setUp()
        self.clf = APIClassifier()

    # ---- decorator detection -------------------------------------------------
    def test_detects_plain_frappe_whitelist(self):
        node = _func_node("@frappe.whitelist()\ndef f():\n    pass\n")
        self.assertTrue(self.clf._has_frappe_whitelist(node))

    def test_detects_bare_frappe_whitelist_attribute(self):
        node = _func_node("@frappe.whitelist\ndef f():\n    pass\n")
        self.assertTrue(self.clf._has_frappe_whitelist(node))

    def test_no_whitelist_when_undecorated(self):
        node = _func_node("def f():\n    pass\n")
        self.assertFalse(self.clf._has_frappe_whitelist(node))

    def test_allow_guest_true_detected(self):
        node = _func_node("@frappe.whitelist(allow_guest=True)\ndef f():\n    pass\n")
        self.assertTrue(self.clf._get_allow_guest(node))

    def test_allow_guest_false_when_absent(self):
        node = _func_node("@frappe.whitelist()\ndef f():\n    pass\n")
        self.assertFalse(self.clf._get_allow_guest(node))

    def test_security_decorators_detected(self):
        node = _func_node(
            "@frappe.whitelist()\n@rate_limit()\ndef f():\n    pass\n"
        )
        self.assertTrue(self.clf._has_security_decorators(node))

    def test_no_security_decorators_on_plain_endpoint(self):
        node = _func_node("@frappe.whitelist()\ndef f():\n    pass\n")
        self.assertFalse(self.clf._has_security_decorators(node))

    def test_get_existing_decorators_lists_names(self):
        node = _func_node(
            "@frappe.whitelist()\n@require_roles('x')\ndef f():\n    pass\n"
        )
        decs = self.clf._get_existing_decorators(node)
        self.assertIn("frappe.whitelist", decs)
        self.assertIn("require_roles", decs)

    def test_get_parameters(self):
        node = _func_node("def f(member, amount, year):\n    pass\n")
        self.assertEqual(self.clf._get_parameters(node), ["member", "amount", "year"])

    # ---- operation-type classification --------------------------------------
    def test_classify_financial_operation(self):
        op = self.clf._classify_operation_type("process_payment", "sepa invoice debit amount")
        self.assertEqual(op, OperationType.FINANCIAL)

    def test_classify_member_data_operation(self):
        op = self.clf._classify_operation_type("get_member_profile", "member contact profile")
        self.assertEqual(op, OperationType.MEMBER_DATA)

    def test_classify_admin_operation(self):
        op = self.clf._classify_operation_type("manage_system_config", "admin setting permission")
        self.assertEqual(op, OperationType.ADMIN)

    def test_classify_defaults_to_some_type_on_empty(self):
        # No keyword hits -> max() over zero-scores still returns a valid enum
        op = self.clf._classify_operation_type("zzz", "qqq")
        self.assertIsInstance(op, OperationType)

    # ---- security-level classification --------------------------------------
    def test_security_level_critical_for_delete(self):
        # 'delete' is a CRITICAL pattern; base for utility op is LOW -> upgraded
        level = self.clf._classify_security_level(
            "delete_record", "frappe.delete_doc", OperationType.UTILITY
        )
        self.assertEqual(level, SecurityLevel.CRITICAL)

    def test_security_level_high_for_create_on_low_base(self):
        level = self.clf._classify_security_level(
            "create_thing", "x.insert()", OperationType.UTILITY
        )
        # 'create' is a HIGH pattern, base LOW -> upgraded to HIGH
        self.assertEqual(level, SecurityLevel.HIGH)

    def test_financial_base_is_critical(self):
        level = self.clf._classify_security_level(
            "get_balance", "amount", OperationType.FINANCIAL
        )
        self.assertEqual(level, SecurityLevel.CRITICAL)

    # ---- risk / db / external analysis --------------------------------------
    def test_risk_factor_sql_injection(self):
        risks = self.clf._analyze_risk_factors("result = frappe.db.sql('select 1')")
        self.assertIn("sql_injection", risks)

    def test_risk_factor_permission_bypass(self):
        risks = self.clf._analyze_risk_factors("doc.insert(ignore_permissions=True)")
        self.assertIn("permission_bypass", risks)

    def test_risk_factor_data_export(self):
        risks = self.clf._analyze_risk_factors("return export_to_csv(rows)")
        self.assertIn("data_export", risks)

    def test_risk_factors_deduplicated(self):
        risks = self.clf._analyze_risk_factors("export csv export download")
        self.assertEqual(len(risks), len(set(risks)))

    def test_database_operations_detected(self):
        ops = self.clf._analyze_database_operations(
            "d = frappe.get_doc('X'); d.save(); frappe.delete_doc('X', n)"
        )
        self.assertIn("READ", ops)
        self.assertIn("INSERT", ops)
        self.assertIn("UPDATE", ops)
        self.assertIn("DELETE", ops)

    def test_external_calls_detected(self):
        calls = self.clf._analyze_external_calls("requests.get(url)\nrequests.post(url)")
        self.assertIn("requests.get", calls)
        self.assertIn("requests.post", calls)

    def test_no_external_calls_in_plain_source(self):
        self.assertEqual(self.clf._analyze_external_calls("return 1 + 1"), [])

    # ---- confidence / priority / sensitivity --------------------------------
    def _make_endpoint(self, **overrides) -> APIEndpoint:
        base = dict(
            module_path="verenigingen.api.x",
            function_name="get_member_list",
            file_path="/tmp/x.py",
            line_number=1,
            docstring="A docstring",
            current_security_level=None,
            recommended_security_level=SecurityLevel.MEDIUM,
            operation_type=OperationType.MEMBER_DATA,
            classification_confidence=ClassificationConfidence.MEDIUM,
            has_frappe_whitelist=True,
            has_security_decorators=False,
            existing_decorators=[],
            allow_guest=False,
            parameters=["member"],
            return_type=None,
            database_operations=["READ"],
            external_calls=[],
            risk_factors=[],
            security_recommendations=[],
            migration_priority=3,
            business_function=None,
            data_sensitivity="medium",
            user_roles_involved=[],
        )
        base.update(overrides)
        return APIEndpoint(**base)

    def test_confidence_high_when_rich_signals(self):
        ep = self._make_endpoint()
        conf = self.clf._calculate_confidence(ep)
        # docstring(20) + non-utility op(20) + db ops(15) + name pattern(25) + params(10) = 90
        self.assertEqual(conf, ClassificationConfidence.HIGH)

    def test_confidence_manual_when_no_signals(self):
        ep = self._make_endpoint(
            function_name="zzz",
            docstring=None,
            operation_type=OperationType.UTILITY,
            database_operations=[],
            parameters=[],
            risk_factors=[],
        )
        self.assertEqual(self.clf._calculate_confidence(ep), ClassificationConfidence.MANUAL)

    def test_migration_priority_critical_is_one(self):
        ep = self._make_endpoint(recommended_security_level=SecurityLevel.CRITICAL)
        self.assertEqual(self.clf._calculate_migration_priority(ep), 1)

    def test_migration_priority_delete_op_capped_at_two(self):
        ep = self._make_endpoint(
            recommended_security_level=SecurityLevel.MEDIUM,
            database_operations=["DELETE"],
        )
        self.assertLessEqual(self.clf._calculate_migration_priority(ep), 2)

    def test_data_sensitivity_financial_is_critical(self):
        ep = self._make_endpoint(operation_type=OperationType.FINANCIAL)
        self.assertEqual(self.clf._assess_data_sensitivity(ep), "critical")

    def test_data_sensitivity_utility_is_low(self):
        ep = self._make_endpoint(operation_type=OperationType.UTILITY)
        self.assertEqual(self.clf._assess_data_sensitivity(ep), "low")

    def test_recommendations_include_framework_for_unsecured(self):
        ep = self._make_endpoint(has_security_decorators=False)
        recs = self.clf._generate_recommendations(ep)
        self.assertTrue(any("api_security_framework" in r for r in recs))

    def test_recommendations_financial_mentions_csrf(self):
        ep = self._make_endpoint(operation_type=OperationType.FINANCIAL)
        recs = self.clf._generate_recommendations(ep)
        self.assertTrue(any("CSRF" in r for r in recs))

    # ---- function source extraction & analyze_function ----------------------
    def test_get_function_source_extracts_body(self):
        content = "@frappe.whitelist()\ndef target():\n    return 42\n\ndef other():\n    pass\n"
        node = _func_node(content)  # first func is target
        src = self.clf._get_function_source(node, content)
        self.assertIn("def target", src)
        self.assertIn("return 42", src)
        self.assertNotIn("def other", src)

    def test_analyze_function_returns_endpoint_for_whitelisted(self):
        content = (
            "@frappe.whitelist()\n"
            "def get_member_data(member):\n"
            '    """Return member info."""\n'
            "    return frappe.get_doc('Member', member)\n"
        )
        node = _func_node(content)
        ep = self.clf._analyze_function(node, "/tmp/fake_api.py", content)
        self.assertIsNotNone(ep)
        self.assertEqual(ep.function_name, "get_member_data")
        self.assertTrue(ep.has_frappe_whitelist)
        self.assertEqual(ep.operation_type, OperationType.MEMBER_DATA)
        self.assertIn("READ", ep.database_operations)
        self.assertIn("member", ep.parameters)

    def test_analyze_function_returns_none_for_undecorated(self):
        content = "def plain():\n    return 1\n"
        node = _func_node(content)
        self.assertIsNone(self.clf._analyze_function(node, "/tmp/f.py", content))

    # ---- implementation code generation -------------------------------------
    def test_generate_implementation_code_financial(self):
        ep = self._make_endpoint(
            operation_type=OperationType.FINANCIAL,
            recommended_security_level=SecurityLevel.CRITICAL,
            function_name="charge_member",
            parameters=["member", "amount"],
        )
        code = self.clf.generate_implementation_code(ep)
        self.assertIn("SecurityLevel.CRITICAL", code)
        self.assertIn("OperationType.FINANCIAL", code)
        self.assertIn('audit_level="detailed"', code)
        self.assertIn("def charge_member(member, amount)", code)
        self.assertIn("validate_with_schema('payment_data')", code)

    def test_generate_implementation_code_member_data_schema(self):
        ep = self._make_endpoint(operation_type=OperationType.MEMBER_DATA)
        code = self.clf.generate_implementation_code(ep)
        self.assertIn("validate_with_schema('member_data')", code)

    def test_generate_implementation_code_utility_no_schema(self):
        ep = self._make_endpoint(operation_type=OperationType.UTILITY)
        code = self.clf.generate_implementation_code(ep)
        self.assertNotIn("validate_with_schema", code)


class TestClassifierFullScan(EnhancedTestCase):
    """Run the classifier against the real verenigingen/api source tree."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._clf = APIClassifier()
        cls._endpoints = cls._clf.classify_all_endpoints()

    def test_scan_finds_many_endpoints(self):
        # The api/ tree has hundreds of whitelisted endpoints.
        self.assertGreater(len(self._endpoints), 50)

    def test_every_endpoint_has_whitelist_flag(self):
        self.assertTrue(all(e.has_frappe_whitelist for e in self._endpoints))

    def test_every_endpoint_has_valid_classification(self):
        for e in self._endpoints:
            self.assertIsInstance(e.recommended_security_level, SecurityLevel)
            self.assertIsInstance(e.operation_type, OperationType)
            self.assertIsInstance(e.classification_confidence, ClassificationConfidence)
            self.assertIn(e.migration_priority, range(1, 6))
            self.assertIn(e.data_sensitivity, {"low", "medium", "high", "critical"})

    def test_module_paths_are_verenigingen_api(self):
        for e in self._endpoints[:25]:
            self.assertTrue(e.module_path.startswith("verenigingen."))
            self.assertIn("api", e.module_path)

    def test_generate_migration_report_structure(self):
        report = self._clf.generate_migration_report()
        self.assertIn("summary", report)
        self.assertIn("priority_breakdown", report)
        self.assertIn("security_level_breakdown", report)
        self.assertIn("risk_analysis", report)
        self.assertIn("high_priority_endpoints", report)
        self.assertIn("manual_review_required", report)

        summary = report["summary"]
        self.assertEqual(
            summary["total_endpoints"],
            summary["secured_endpoints"] + summary["unsecured_endpoints"],
        )
        self.assertGreaterEqual(summary["security_coverage"], 0)
        self.assertLessEqual(summary["security_coverage"], 100)

    def test_priority_breakdown_sums_to_total(self):
        report = self._clf.generate_migration_report()
        total = report["summary"]["total_endpoints"]
        self.assertEqual(sum(report["priority_breakdown"].values()), total)

    def test_security_level_breakdown_sums_to_total(self):
        report = self._clf.generate_migration_report()
        total = report["summary"]["total_endpoints"]
        self.assertEqual(sum(report["security_level_breakdown"].values()), total)


class TestClassifierWhitelistedAPIs(EnhancedTestCase):
    """The whitelisted wrapper endpoints (require System Manager).

    EnhancedTestCase.setUp grants the test user System Manager, so the role
    gate passes here.
    """

    def setUp(self):
        super().setUp()
        # Reset the global classifier so each test starts clean.
        import verenigingen.utils.security.api_classifier as mod

        mod._api_classifier = None

    def test_classify_all_api_endpoints_success(self):
        result = classify_all_api_endpoints()
        self.assertTrue(result["success"])
        self.assertGreater(result["total_endpoints"], 0)
        self.assertEqual(len(result["endpoints"]), result["total_endpoints"])
        # Endpoints are serialised dataclasses
        sample = result["endpoints"][0]
        self.assertIn("function_name", sample)
        self.assertIn("recommended_security_level", sample)

    def test_generate_migration_report_success(self):
        result = generate_migration_report()
        self.assertTrue(result["success"])
        self.assertIn("summary", result["report"])

    def test_get_implementation_code_for_real_endpoint(self):
        # First classify to find a real endpoint, then request its code.
        clf = get_api_classifier()
        endpoints = clf.classify_all_endpoints()
        target = endpoints[0]
        result = get_implementation_code(target.module_path, target.function_name)
        self.assertTrue(result["success"])
        self.assertIn("implementation_code", result)
        self.assertIn("api_security_framework", result["implementation_code"])

    def test_get_implementation_code_unknown_endpoint(self):
        result = get_implementation_code("verenigingen.api.nope", "no_such_function_xyz")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Endpoint not found")

    def test_classify_requires_system_manager(self):
        # Drop privileged roles and confirm the gate throws.
        self._strip_admin_roles()
        with self.assertRaises(frappe.PermissionError):
            classify_all_api_endpoints()

    def _strip_admin_roles(self):
        # Helper (allowed to manipulate roles/user): run as a plain user.
        frappe.set_user("Guest")
        self.addCleanup(lambda: frappe.set_user("Administrator"))


class TestClassifierSetupAndSingleton(EnhancedTestCase):
    def test_get_api_classifier_is_singleton(self):
        import verenigingen.utils.security.api_classifier as mod

        mod._api_classifier = None
        a = get_api_classifier()
        b = get_api_classifier()
        self.assertIs(a, b)

    def test_setup_api_classifier_initialises_global(self):
        import verenigingen.utils.security.api_classifier as mod

        mod._api_classifier = None
        setup_api_classifier()
        self.assertIsNotNone(mod._api_classifier)
        self.assertIsInstance(mod._api_classifier, APIClassifier)
