"""
Coverage tests for:
- verenigingen.utils.security.input_validator (InputValidator)
- verenigingen.utils.security.environment_validator (EnvironmentValidator)

InputValidator is a pure module (no Frappe I/O): real inputs only, no mocking.
EnvironmentValidator reads frappe.conf - we exercise both pass and fail branches
by passing an explicit current_env (no mocking of frappe internals) and by
reading the real site environment.

Companion file: test_enhanced_validation_coverage.py
"""

import json

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import (
    PermissionError as VPermissionError,
    ValidationError as VValidationError,
)
from verenigingen.utils.security.environment_validator import (
    EnvironmentValidator,
    get_environment_validator,
)
from verenigingen.utils.security.input_validator import (
    InputValidator,
    get_input_validator,
)
from verenigingen.utils.security.types import (
    EnvironmentLevel,
    OperationType,
    SecurityLevel,
    SecurityProfile,
)


class TestInputValidatorMaxLength(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = InputValidator()

    def test_default_max_length(self):
        self.assertEqual(self.v.get_max_length(None), InputValidator.DEFAULT_MAX_LENGTH)

    def test_operation_specific_max_length(self):
        self.assertEqual(self.v.get_max_length(OperationType.FINANCIAL), 100000)
        self.assertEqual(self.v.get_max_length(OperationType.MEMBER_DATA), 5000)
        self.assertEqual(self.v.get_max_length(OperationType.REPORTING), 2000)
        self.assertEqual(self.v.get_max_length(OperationType.ADMIN), 50000)

    def test_unmapped_operation_falls_back_to_default(self):
        # UTILITY is not in MAX_LENGTHS -> default
        self.assertEqual(self.v.get_max_length(OperationType.UTILITY), InputValidator.DEFAULT_MAX_LENGTH)


class TestInputValidatorFileDetection(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = InputValidator()

    def test_known_file_key_case_insensitive(self):
        self.assertTrue(self.v.is_file_data("FileData", "<script>x</script>"))
        self.assertTrue(self.v.is_file_data("attachment_content", "anything"))

    def test_generic_key_not_treated_as_file(self):
        # SECURITY: "content"/"data" must NOT bypass sanitization
        self.assertFalse(self.v.is_file_data("content", "<script>x</script>"))
        self.assertFalse(self.v.is_file_data("data", "<b>hi</b>"))

    def test_data_uri_detected_as_binary(self):
        big = "data:image/png;base64," + ("A" * 2000)
        self.assertTrue(self.v.is_file_data("some_field", big))

    def test_short_value_not_binary(self):
        self.assertFalse(self.v._looks_like_binary_data("short"))

    def test_long_base64_detected(self):
        # >10000 alnum -> binary
        blob = "A" * 11000
        self.assertTrue(self.v._looks_like_binary_data(blob))

    def test_long_nonbase64_not_detected(self):
        # >1000 but contains spaces/punctuation -> not base64-like
        blob = "hello world! " * 1000
        self.assertFalse(self.v._looks_like_binary_data(blob))

    def test_empty_value_not_binary(self):
        self.assertFalse(self.v._looks_like_binary_data(""))


class TestInputValidatorJsonDetection(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = InputValidator()

    def test_valid_json_object(self):
        self.assertTrue(self.v.is_json_payload('{"a": 1}'))

    def test_valid_json_array(self):
        self.assertTrue(self.v.is_json_payload("[1, 2, 3]"))

    def test_non_json_text(self):
        self.assertFalse(self.v.is_json_payload("hello world"))

    def test_malformed_json_returns_false(self):
        # starts with { but is not valid JSON
        self.assertFalse(self.v.is_json_payload('{"a": '))


class TestInputValidatorValidateString(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = InputValidator()

    def test_file_data_passes_through_unchanged(self):
        raw = "<script>alert(1)</script>"
        # known file key -> returned verbatim (not sanitized)
        self.assertEqual(self.v.validate_string("filedata", raw), raw)

    def test_html_entities_decoded(self):
        # &quot; should be decoded to " before sanitization re-escapes
        result = self.v.validate_string("field", "say &quot;hi&quot;")
        # sanitize_text escapes the decoded quote back to &quot;
        self.assertIn("&quot;", result)

    def test_xss_is_escaped(self):
        result = self.v.validate_string("field", "<script>alert(1)</script>")
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_json_payload_returned_after_length_check(self):
        payload = json.dumps({"items": [1, 2, 3]})
        self.assertEqual(self.v.validate_string("field", payload), payload)

    def test_json_payload_too_long_raises(self):
        # JSON payload over 100000 chars -> raises
        big_list = json.dumps(list(range(40000)))  # well over 100000 chars
        self.assertGreater(len(big_list), 100000)
        with self.assertRaises(VValidationError):
            self.v.validate_string("field", big_list)

    def test_regular_text_length_enforced(self):
        with self.assertRaises(VValidationError):
            self.v.validate_string("field", "x" * 50, max_length=10)


class TestInputValidatorValidateContainers(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = InputValidator()

    def test_validate_dict_sanitizes_strings(self):
        result = self.v.validate_dict({"name": "<b>x</b>", "n": 5})
        self.assertNotIn("<b>", result["name"])
        self.assertEqual(result["n"], 5)

    def test_validate_dict_nested(self):
        result = self.v.validate_dict({"outer": {"inner": "<i>x</i>"}})
        self.assertNotIn("<i>", result["outer"]["inner"])

    def test_validate_dict_with_list(self):
        result = self.v.validate_dict({"items": ["<u>a</u>", 2]})
        self.assertNotIn("<u>", result["items"][0])
        self.assertEqual(result["items"][1], 2)

    def test_validate_list_recursive(self):
        result = self.v.validate_list(["<b>x</b>", {"k": "<i>y</i>"}, [3], 4])
        self.assertNotIn("<b>", result[0])
        self.assertNotIn("<i>", result[1]["k"])
        self.assertEqual(result[2], [3])
        self.assertEqual(result[3], 4)


class TestInputValidatorValidate(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = InputValidator()

    def test_none_value_passthrough(self):
        result = self.v.validate(OperationType.MEMBER_DATA, field=None)
        self.assertIsNone(result["field"])

    def test_string_sanitized(self):
        result = self.v.validate(OperationType.MEMBER_DATA, note="<script>x</script>")
        self.assertNotIn("<script>", result["note"])

    def test_dict_and_list_handled(self):
        result = self.v.validate(
            OperationType.ADMIN,
            d={"a": "<b>x</b>"},
            l=["<i>y</i>"],
            n=10,
        )
        self.assertNotIn("<b>", result["d"]["a"])
        self.assertNotIn("<i>", result["l"][0])
        self.assertEqual(result["n"], 10)

    def test_financial_allows_large_payload(self):
        # FINANCIAL max_length is 100000; a 6000-char plain string is fine
        # (would exceed default 1000 limit and raise otherwise)
        result = self.v.validate(OperationType.FINANCIAL, blob="a" * 6000)
        self.assertEqual(len(result["blob"]), 6000)

    def test_default_operation_limits_string(self):
        # No operation type -> 1000 char default -> 6000 chars raises
        with self.assertRaises(VValidationError):
            self.v.validate(None, blob="a" * 6000)

    def test_singleton(self):
        self.assertIs(get_input_validator(), get_input_validator())


class TestEnvironmentValidator(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.v = EnvironmentValidator()

    def _profile(self, allowed):
        return SecurityProfile(level=SecurityLevel.LOW, allowed_environments=allowed)

    def test_get_current_environment_returns_enum(self):
        env = self.v.get_current_environment()
        self.assertIsInstance(env, EnvironmentLevel)

    def test_validate_access_allowed_explicit_env(self):
        profile = self._profile([EnvironmentLevel.DEVELOPMENT, EnvironmentLevel.STAGING])
        self.assertTrue(self.v.validate_access(profile, current_env=EnvironmentLevel.DEVELOPMENT))

    def test_validate_access_denied_explicit_env(self):
        profile = self._profile([EnvironmentLevel.DEVELOPMENT])
        with self.assertRaises(VPermissionError):
            self.v.validate_access(profile, current_env=EnvironmentLevel.PRODUCTION)

    def test_validate_access_denied_message_lists_allowed(self):
        profile = self._profile([EnvironmentLevel.STAGING])
        try:
            self.v.validate_access(profile, current_env=EnvironmentLevel.PRODUCTION)
            self.fail("expected VPermissionError")
        except VPermissionError as e:
            msg = str(e)
            self.assertIn("production", msg)
            self.assertIn("staging", msg)

    def test_validate_access_detects_env_when_none(self):
        # current_env defaults via get_current_environment(); allow every env so
        # the call passes regardless of detected site environment.
        profile = self._profile(
            [
                EnvironmentLevel.DEVELOPMENT,
                EnvironmentLevel.STAGING,
                EnvironmentLevel.PRODUCTION,
            ]
        )
        self.assertTrue(self.v.validate_access(profile))

    def test_default_profile_allows_all_environments(self):
        # SecurityProfile.__post_init__ sets all 3 environments by default
        profile = SecurityProfile(level=SecurityLevel.LOW)
        for env in EnvironmentLevel:
            self.assertTrue(self.v.validate_access(profile, current_env=env))

    def test_singleton(self):
        self.assertIs(get_environment_validator(), get_environment_validator())


class TestEnvironmentDetectionBranches(VereningingenTestCase):
    """Exercise get_current_environment config-driven branches.

    We mutate frappe.conf directly (real config dict, no mocking of frappe APIs)
    and restore it in tearDown, so each detection branch is covered against the
    actual implementation.
    """

    def setUp(self):
        super().setUp()
        import frappe

        self.v = EnvironmentValidator()
        self._saved = {
            k: frappe.conf.get(k) for k in ("developer_mode", "deployment_environment", "environment")
        }

    def tearDown(self):
        import frappe

        for k, val in self._saved.items():
            if val is None:
                frappe.conf.pop(k, None)
            else:
                frappe.conf[k] = val
        super().tearDown()

    def _clear(self):
        import frappe

        for k in ("developer_mode", "deployment_environment", "environment"):
            frappe.conf.pop(k, None)

    def test_developer_mode_means_development(self):
        import frappe

        self._clear()
        frappe.conf["developer_mode"] = 1
        self.assertEqual(self.v.get_current_environment(), EnvironmentLevel.DEVELOPMENT)

    def test_deployment_environment_config(self):
        import frappe

        self._clear()
        frappe.conf["deployment_environment"] = "staging"
        self.assertEqual(self.v.get_current_environment(), EnvironmentLevel.STAGING)

    def test_invalid_deployment_environment_falls_through(self):
        import frappe

        self._clear()
        frappe.conf["deployment_environment"] = "bogus"
        # invalid -> falls through to default PRODUCTION
        self.assertEqual(self.v.get_current_environment(), EnvironmentLevel.PRODUCTION)

    def test_environment_config_used(self):
        import frappe

        self._clear()
        frappe.conf["environment"] = "staging"
        self.assertEqual(self.v.get_current_environment(), EnvironmentLevel.STAGING)

    def test_invalid_environment_config_falls_through(self):
        import frappe

        self._clear()
        frappe.conf["environment"] = "nonsense"
        self.assertEqual(self.v.get_current_environment(), EnvironmentLevel.PRODUCTION)

    def test_default_production_when_nothing_set(self):
        self._clear()
        self.assertEqual(self.v.get_current_environment(), EnvironmentLevel.PRODUCTION)
