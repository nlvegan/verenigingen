"""
Coverage tests for verenigingen.utils.security.enhanced_validation

These exercise the PURE validation engine (ValidationRule, ValidationSchema,
SchemaRegistry, EnhancedValidator) with real inputs - no mocking. The focus is
on which rule fires, with what severity and message, plus type coercion,
format/range/length/enum/pattern/custom rules, the schema aggregation logic,
business-rule validation and the secure error-response shaping.

Companion file: test_input_environment_validators_coverage.py
"""

import json

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.enhanced_validation import (
    EnhancedValidator,
    SchemaRegistry,
    ValidationRule,
    ValidationSchema,
    ValidationSeverity,
    ValidationType,
    get_enhanced_validator,
    get_schema_registry,
)


class TestValidationRuleRequired(VereningingenTestCase):
    """ValidationType.REQUIRED rule"""

    def test_none_value_fails_required(self):
        rule = ValidationRule(ValidationType.REQUIRED)
        result = rule.validate(None, "first_name")
        self.assertFalse(result["valid"])
        self.assertEqual(result["severity"], "error")
        self.assertEqual(result["rule_type"], "required")
        self.assertIn("first_name", result["message"])

    def test_empty_string_fails_required(self):
        rule = ValidationRule(ValidationType.REQUIRED)
        self.assertFalse(rule.validate("", "x")["valid"])

    def test_whitespace_only_fails_required(self):
        rule = ValidationRule(ValidationType.REQUIRED)
        # The .strip() branch: a non-empty but blank string must fail.
        self.assertFalse(rule.validate("   ", "x")["valid"])

    def test_zero_passes_required(self):
        # 0 is not None/"" so it should pass required (an important edge case
        # for numeric fields).
        rule = ValidationRule(ValidationType.REQUIRED)
        self.assertTrue(rule.validate(0, "amount")["valid"])

    def test_present_value_passes(self):
        rule = ValidationRule(ValidationType.REQUIRED)
        self.assertTrue(rule.validate("John", "first_name")["valid"])

    def test_custom_message_used(self):
        rule = ValidationRule(ValidationType.REQUIRED, message="Naam verplicht")
        result = rule.validate("", "first_name")
        self.assertEqual(result["message"], "Naam verplicht")

    def test_no_field_name_uses_field_default(self):
        rule = ValidationRule(ValidationType.REQUIRED)
        result = rule.validate(None, None)
        self.assertIn("Field", result["message"])


class TestValidationRuleType(VereningingenTestCase):
    """ValidationType.TYPE rule"""

    def test_no_expected_type_passes(self):
        rule = ValidationRule(ValidationType.TYPE)
        self.assertTrue(rule.validate("anything", "f")["valid"])

    def test_none_value_passes_type(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="integer")
        self.assertTrue(rule.validate(None, "f")["valid"])

    def test_integer_valid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="integer")
        self.assertTrue(rule.validate("42", "qty")["valid"])

    def test_integer_invalid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="integer")
        result = rule.validate("abc", "qty")
        self.assertFalse(result["valid"])
        self.assertIn("integer", result["message"])

    def test_float_valid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="float")
        self.assertTrue(rule.validate("3.14", "amount")["valid"])

    def test_float_invalid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="float")
        result = rule.validate("not-a-number", "amount")
        self.assertFalse(result["valid"])
        self.assertIn("number", result["message"])

    def test_float_nan_rejected(self):
        """Audit #8: float("nan") parses successfully but must be rejected."""
        rule = ValidationRule(ValidationType.TYPE, expected_type="float")
        result = rule.validate("nan", "amount")
        self.assertFalse(result["valid"])
        self.assertIn("finite", result["message"])

    def test_float_infinity_rejected(self):
        """Audit #8: float("inf") must be rejected by the float type rule."""
        rule = ValidationRule(ValidationType.TYPE, expected_type="float")
        self.assertFalse(rule.validate("inf", "amount")["valid"])

    def test_boolean_valid_accepts_string_flags(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="boolean")
        for v in ["true", "false", "0", "1", True, False]:
            self.assertTrue(rule.validate(v, "flag")["valid"], f"{v!r} should be boolean-ok")

    def test_boolean_invalid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="boolean")
        result = rule.validate("maybe", "flag")
        self.assertFalse(result["valid"])
        self.assertIn("boolean", result["message"])

    def test_date_valid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="date")
        self.assertTrue(rule.validate("2024-01-15", "birth_date")["valid"])

    def test_date_invalid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="date")
        result = rule.validate("not-a-date", "birth_date")
        self.assertFalse(result["valid"])
        self.assertIn("date", result["message"])

    def test_datetime_valid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="datetime")
        self.assertTrue(rule.validate("2024-01-15 10:30:00", "ts")["valid"])

    def test_datetime_invalid(self):
        rule = ValidationRule(ValidationType.TYPE, expected_type="datetime")
        result = rule.validate("xx", "ts")
        self.assertFalse(result["valid"])
        self.assertIn("datetime", result["message"])

    def test_string_type_always_passes(self):
        # string branch only coerces; never rejects
        rule = ValidationRule(ValidationType.TYPE, expected_type="string")
        self.assertTrue(rule.validate(12345, "f")["valid"])


class TestValidationRuleFormat(VereningingenTestCase):
    """ValidationType.FORMAT rule (email/phone/iban/postal_code)"""

    def test_empty_value_skips_format(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="email")
        self.assertTrue(rule.validate("", "email")["valid"])
        self.assertTrue(rule.validate(None, "email")["valid"])

    def test_valid_email(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="email")
        self.assertTrue(rule.validate("a@b.com", "email")["valid"])

    def test_invalid_email(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="email")
        result = rule.validate("not-an-email", "email")
        self.assertFalse(result["valid"])
        self.assertEqual(result["rule_type"], "format")

    def test_valid_phone(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="phone")
        self.assertTrue(rule.validate("+31612345678", "phone")["valid"])

    def test_invalid_phone(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="phone")
        self.assertFalse(rule.validate("abc", "phone")["valid"])

    def test_valid_iban(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="iban")
        # Valid Dutch test IBAN
        self.assertTrue(rule.validate("NL91ABNA0417164300", "iban")["valid"])

    def test_invalid_iban(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="iban")
        result = rule.validate("NL00BANK0123456789", "iban")
        self.assertFalse(result["valid"])

    def test_valid_postal_code(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="postal_code", country="NL")
        self.assertTrue(rule.validate("1234AB", "postal_code")["valid"])

    def test_invalid_postal_code(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="postal_code", country="NL")
        result = rule.validate("99999", "postal_code")
        self.assertFalse(result["valid"])

    def test_format_warning_severity_preserved(self):
        rule = ValidationRule(
            ValidationType.FORMAT,
            severity=ValidationSeverity.WARNING,
            format_type="phone",
        )
        result = rule.validate("abc", "phone")
        self.assertFalse(result["valid"])
        self.assertEqual(result["severity"], "warning")

    def test_unknown_format_type_passes(self):
        rule = ValidationRule(ValidationType.FORMAT, format_type="bogus")
        self.assertTrue(rule.validate("whatever", "f")["valid"])


class TestValidationRuleRange(VereningingenTestCase):
    """ValidationType.RANGE rule"""

    def test_none_passes(self):
        rule = ValidationRule(ValidationType.RANGE, min=1, max=10)
        self.assertTrue(rule.validate(None, "f")["valid"])

    def test_within_range(self):
        rule = ValidationRule(ValidationType.RANGE, min=1, max=10)
        self.assertTrue(rule.validate(5, "f")["valid"])

    def test_below_min(self):
        rule = ValidationRule(ValidationType.RANGE, min=1, max=10)
        result = rule.validate(0, "amount")
        self.assertFalse(result["valid"])
        self.assertIn("at least", result["message"])

    def test_above_max(self):
        rule = ValidationRule(ValidationType.RANGE, min=1, max=10)
        result = rule.validate(11, "amount")
        self.assertFalse(result["valid"])
        self.assertIn("exceed", result["message"])

    def test_boundary_min_inclusive(self):
        rule = ValidationRule(ValidationType.RANGE, min=1, max=10)
        self.assertTrue(rule.validate(1, "f")["valid"])

    def test_boundary_max_inclusive(self):
        rule = ValidationRule(ValidationType.RANGE, min=1, max=10)
        self.assertTrue(rule.validate(10, "f")["valid"])

    def test_non_numeric_value(self):
        rule = ValidationRule(ValidationType.RANGE, min=1, max=10)
        result = rule.validate("abc", "amount")
        self.assertFalse(result["valid"])
        self.assertIn("numeric", result["message"])

    def test_only_min(self):
        rule = ValidationRule(ValidationType.RANGE, min=5)
        self.assertTrue(rule.validate(100, "f")["valid"])
        self.assertFalse(rule.validate(4, "f")["valid"])

    def test_nan_rejected(self):
        """Audit #8: nan must be rejected. Comparisons against nan are always
        false, so an unchecked nan satisfies both min and max bounds."""
        rule = ValidationRule(ValidationType.RANGE, min=0.01, max=10000)
        result = rule.validate("nan", "amount")
        self.assertFalse(result["valid"])
        self.assertIn("finite", result["message"])

    def test_infinity_rejected(self):
        """Audit #8: inf must be rejected by RANGE bounds."""
        rule = ValidationRule(ValidationType.RANGE, min=0.01, max=10000)
        self.assertFalse(rule.validate("inf", "amount")["valid"])
        self.assertFalse(rule.validate("-inf", "amount")["valid"])


class TestValidationRuleLength(VereningingenTestCase):
    """ValidationType.LENGTH rule"""

    def test_none_passes(self):
        rule = ValidationRule(ValidationType.LENGTH, min=3, max=10)
        self.assertTrue(rule.validate(None, "f")["valid"])

    def test_within_length(self):
        rule = ValidationRule(ValidationType.LENGTH, min=3, max=10)
        self.assertTrue(rule.validate("hello", "f")["valid"])

    def test_too_short(self):
        rule = ValidationRule(ValidationType.LENGTH, min=3, max=10)
        result = rule.validate("ab", "name")
        self.assertFalse(result["valid"])
        self.assertIn("at least", result["message"])

    def test_too_long(self):
        rule = ValidationRule(ValidationType.LENGTH, min=3, max=10)
        result = rule.validate("a" * 11, "name")
        self.assertFalse(result["valid"])
        self.assertIn("exceed", result["message"])

    def test_boundary_min_inclusive(self):
        rule = ValidationRule(ValidationType.LENGTH, min=3, max=10)
        self.assertTrue(rule.validate("abc", "f")["valid"])

    def test_boundary_max_inclusive(self):
        rule = ValidationRule(ValidationType.LENGTH, min=3, max=10)
        self.assertTrue(rule.validate("a" * 10, "f")["valid"])

    def test_list_length(self):
        rule = ValidationRule(ValidationType.LENGTH, max=2)
        self.assertTrue(rule.validate([1, 2], "items")["valid"])
        self.assertFalse(rule.validate([1, 2, 3], "items")["valid"])

    def test_object_without_len_counts_zero(self):
        # objects without __len__ are treated as length 0; with min=1 that fails
        rule = ValidationRule(ValidationType.LENGTH, min=1)
        result = rule.validate(12345, "f")
        self.assertFalse(result["valid"])


class TestValidationRulePattern(VereningingenTestCase):
    """ValidationType.PATTERN rule"""

    def test_empty_value_skips(self):
        rule = ValidationRule(ValidationType.PATTERN, pattern=r"^\d+$")
        self.assertTrue(rule.validate("", "f")["valid"])

    def test_no_pattern_passes(self):
        rule = ValidationRule(ValidationType.PATTERN)
        self.assertTrue(rule.validate("anything", "f")["valid"])

    def test_pattern_match(self):
        rule = ValidationRule(ValidationType.PATTERN, pattern=r"^\d+$")
        self.assertTrue(rule.validate("12345", "f")["valid"])

    def test_pattern_no_match(self):
        rule = ValidationRule(ValidationType.PATTERN, pattern=r"^\d+$")
        result = rule.validate("12a45", "code")
        self.assertFalse(result["valid"])
        self.assertIn("invalid", result["message"].lower())

    def test_invalid_pattern_configuration(self):
        # Unbalanced bracket -> re.error -> caught branch
        rule = ValidationRule(ValidationType.PATTERN, pattern=r"[invalid")
        result = rule.validate("x", "f")
        self.assertFalse(result["valid"])
        self.assertIn("pattern", result["message"].lower())

    def test_pattern_uses_fullmatch_not_prefix_match(self):
        """Audit #8: a non-anchored pattern must not accept trailing junk.

        re.match anchors only at the start, so r"[A-Z]{2}\\d+" would accept
        "AB12<script>". fullmatch requires the whole value to conform.
        """
        rule = ValidationRule(ValidationType.PATTERN, pattern=r"[A-Z]{2}\d+")
        self.assertTrue(rule.validate("AB12", "code")["valid"])
        self.assertFalse(rule.validate("AB12<script>", "code")["valid"])
        self.assertFalse(rule.validate("AB12 extra", "code")["valid"])


class TestValidationRuleEnum(VereningingenTestCase):
    """ValidationType.ENUM rule"""

    def test_none_passes(self):
        rule = ValidationRule(ValidationType.ENUM, allowed_values=["EUR", "USD"])
        self.assertTrue(rule.validate(None, "currency")["valid"])

    def test_allowed_value(self):
        rule = ValidationRule(ValidationType.ENUM, allowed_values=["EUR", "USD"])
        self.assertTrue(rule.validate("EUR", "currency")["valid"])

    def test_disallowed_value(self):
        rule = ValidationRule(ValidationType.ENUM, allowed_values=["EUR", "USD"])
        result = rule.validate("GBP", "currency")
        self.assertFalse(result["valid"])
        self.assertIn("EUR", result["message"])
        self.assertIn("USD", result["message"])


class TestValidationRuleCustom(VereningingenTestCase):
    """ValidationType.CUSTOM rule"""

    def test_no_validator_passes(self):
        rule = ValidationRule(ValidationType.CUSTOM)
        self.assertTrue(rule.validate("x", "f")["valid"])

    def test_custom_returns_true(self):
        rule = ValidationRule(ValidationType.CUSTOM, validator=lambda v, fn, **p: True)
        result = rule.validate("x", "f")
        self.assertTrue(result["valid"])
        # passing custom maps severity to INFO
        self.assertEqual(result["severity"], "info")

    def test_custom_returns_false(self):
        rule = ValidationRule(
            ValidationType.CUSTOM,
            message="bad",
            validator=lambda v, fn, **p: False,
        )
        result = rule.validate("x", "f")
        self.assertFalse(result["valid"])
        self.assertEqual(result["severity"], "error")
        self.assertEqual(result["message"], "bad")

    def test_custom_returns_dict(self):
        rule = ValidationRule(
            ValidationType.CUSTOM,
            validator=lambda v, fn, **p: {"valid": False, "severity": "warning", "message": "m"},
        )
        result = rule.validate("x", "f")
        self.assertEqual(result["severity"], "warning")
        self.assertEqual(result["message"], "m")

    def test_custom_returns_other_type_passes(self):
        rule = ValidationRule(ValidationType.CUSTOM, validator=lambda v, fn, **p: "weird")
        self.assertTrue(rule.validate("x", "f")["valid"])

    def test_custom_raises_is_caught(self):
        def boom(v, fn, **p):
            raise RuntimeError("kaboom")

        rule = ValidationRule(ValidationType.CUSTOM, validator=boom)
        result = rule.validate("x", "f")
        self.assertFalse(result["valid"])
        self.assertIn("kaboom", result["message"])


class TestValidationRuleDispatchFallback(VereningingenTestCase):
    """The validate() dispatcher's else branch + business_rule type"""

    def test_business_rule_type_returns_valid_by_default(self):
        # BUSINESS_RULE has no handler -> falls through to the else: {"valid": True}
        rule = ValidationRule(ValidationType.BUSINESS_RULE)
        self.assertTrue(rule.validate("anything", "f")["valid"])


class TestValidationSchema(VereningingenTestCase):
    """ValidationSchema.validate aggregation logic"""

    def _member_like_schema(self):
        schema = ValidationSchema("test_member", "desc")
        schema.add_field_rule("first_name", ValidationRule(ValidationType.REQUIRED))
        schema.add_field_rule("first_name", ValidationRule(ValidationType.LENGTH, max=5))
        schema.add_field_rule("email", ValidationRule(ValidationType.FORMAT, format_type="email"))
        schema.add_field_rule(
            "phone",
            ValidationRule(ValidationType.FORMAT, severity=ValidationSeverity.WARNING, format_type="phone"),
        )
        return schema

    def test_valid_data_passes(self):
        schema = self._member_like_schema()
        result = schema.validate({"first_name": "Jan", "email": "a@b.com"})
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["schema_name"], "test_member")

    def test_error_severity_marks_invalid(self):
        schema = self._member_like_schema()
        result = schema.validate({"first_name": "", "email": "bad"})
        self.assertFalse(result["valid"])
        # required + email format -> 2 errors
        self.assertEqual(len(result["errors"]), 2)

    def test_warning_does_not_mark_invalid(self):
        schema = self._member_like_schema()
        # bad phone is a WARNING; rest valid
        result = schema.validate({"first_name": "Jan", "phone": "xx"})
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(len(result["errors"]), 0)

    def test_field_not_in_schema_is_string_sanitized(self):
        schema = self._member_like_schema()
        result = schema.validate({"first_name": "Jan", "notes": "<script>alert(1)</script>"})
        # unknown string field sanitized via APIValidator.sanitize_text -> escaped
        self.assertNotIn("<script>", result["sanitized_data"]["notes"])
        self.assertIn("&lt;script&gt;", result["sanitized_data"]["notes"])

    def test_field_not_in_schema_nonstring_passthrough(self):
        schema = self._member_like_schema()
        result = schema.validate({"first_name": "Jan", "count": 42})
        self.assertEqual(result["sanitized_data"]["count"], 42)

    def test_length_max_exceeded_in_schema(self):
        schema = self._member_like_schema()
        result = schema.validate({"first_name": "TooLongName"})
        self.assertFalse(result["valid"])
        self.assertTrue(any(e["rule_type"] == "length" for e in result["errors"]))

    def test_info_severity_collected(self):
        schema = ValidationSchema("info_schema")
        schema.add_field_rule(
            "x",
            ValidationRule(
                ValidationType.CUSTOM,
                severity=ValidationSeverity.INFO,
                validator=lambda v, fn, **p: {
                    "valid": False,
                    "severity": "info",
                    "message": "note",
                },
            ),
        )
        result = schema.validate({"x": "value"})
        self.assertTrue(result["valid"])  # info doesn't invalidate
        self.assertEqual(len(result["info"]), 1)

    def test_global_rule_error(self):
        schema = ValidationSchema("global_schema")

        def dataset_rule(data, field_name, **p):
            return {"valid": False, "severity": "error", "message": "dataset bad"}

        schema.add_global_rule(ValidationRule(ValidationType.CUSTOM, validator=dataset_rule))
        result = schema.validate({"a": 1})
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["field"], "global")

    def test_global_rule_warning(self):
        schema = ValidationSchema("global_warn")

        def dataset_rule(data, field_name, **p):
            return {"valid": False, "severity": "warning", "message": "dataset warn"}

        schema.add_global_rule(ValidationRule(ValidationType.CUSTOM, validator=dataset_rule))
        result = schema.validate({"a": 1})
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["warnings"]), 1)

    def test_global_rule_info(self):
        schema = ValidationSchema("global_info")

        def dataset_rule(data, field_name, **p):
            return {"valid": False, "severity": "info", "message": "dataset info"}

        schema.add_global_rule(ValidationRule(ValidationType.CUSTOM, validator=dataset_rule))
        result = schema.validate({"a": 1})
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["info"]), 1)

    def test_format_field_string_value_is_sanitized(self):
        # The _validate_field FORMAT-sanitization branch
        schema = ValidationSchema("san")
        schema.add_field_rule("email", ValidationRule(ValidationType.FORMAT, format_type="email"))
        result = schema.validate({"email": "a@b.com"})
        # sanitize_text escapes/strips; valid email round-trips unchanged
        self.assertEqual(result["sanitized_data"]["email"], "a@b.com")


class TestSchemaRegistry(VereningingenTestCase):
    """SchemaRegistry default schemas + register/get"""

    def test_default_schemas_registered(self):
        registry = SchemaRegistry()
        for name in ["member_data", "payment_data", "sepa_batch", "volunteer_data"]:
            self.assertIsNotNone(registry.get_schema(name), f"{name} should be registered")

    def test_get_unknown_returns_none(self):
        registry = SchemaRegistry()
        self.assertIsNone(registry.get_schema("does_not_exist"))

    def test_register_custom_schema(self):
        registry = SchemaRegistry()
        custom = ValidationSchema("custom_x")
        registry.register_schema(custom)
        self.assertIs(registry.get_schema("custom_x"), custom)

    def test_get_schema_registry_singleton(self):
        a = get_schema_registry()
        b = get_schema_registry()
        self.assertIs(a, b)

    def test_payment_schema_amount_range(self):
        registry = SchemaRegistry()
        schema = registry.get_schema("payment_data")
        # amount above max (10000) should error
        result = schema.validate({"amount": 99999, "currency": "EUR"})
        self.assertFalse(result["valid"])

    def test_payment_schema_currency_enum(self):
        registry = SchemaRegistry()
        schema = registry.get_schema("payment_data")
        result = schema.validate({"amount": 10, "currency": "GBP"})
        self.assertFalse(result["valid"])


class TestEnhancedValidatorEngine(VereningingenTestCase):
    """EnhancedValidator.validate_with_schema / business_rules / error response"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.validator = get_enhanced_validator()

    def test_get_enhanced_validator_singleton(self):
        self.assertIs(get_enhanced_validator(), get_enhanced_validator())

    def test_validate_with_schema_unknown_raises(self):
        from verenigingen.utils.error_handling import ValidationError as VValidationError

        with self.assertRaises(VValidationError):
            self.validator.validate_with_schema({}, "no_such_schema")

    def test_validate_with_schema_valid(self):
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email_id": "john@example.com",
        }
        result = self.validator.validate_with_schema(data, "member_data")
        self.assertTrue(result["valid"])

    def test_validate_with_schema_errors_logged_path(self):
        # invalid -> exercises the audit "errors" logging branch
        data = {"first_name": "", "last_name": "Doe", "email_id": "bad"}
        result = self.validator.validate_with_schema(data, "member_data")
        self.assertFalse(result["valid"])

    def test_validate_with_schema_warnings_only_path(self):
        # only a warning (bad phone) -> exercises the warnings logging branch.
        # Regression: this branch logged audit event type "validation_warnings",
        # which was not a valid API Audit Log option, so the audit write was
        # rejected and silently dropped (Error Log only). assertNoErrorLog pins
        # that the warnings audit event now persists cleanly.
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email_id": "john@example.com",
            "phone": "not-a-phone",
        }
        before = frappe.db.count("API Audit Log", {"event_type": "validation_warnings"})
        with self.assertNoErrorLog():
            result = self.validator.validate_with_schema(data, "member_data")
        self.assertTrue(result["valid"])
        self.assertGreaterEqual(len(result["warnings"]), 1)
        after = frappe.db.count("API Audit Log", {"event_type": "validation_warnings"})
        self.assertEqual(after, before + 1, "warnings-only validation must persist an audit event")

    def test_business_rules_valid(self):
        def rule(data):
            return {"valid": True}

        result = self.validator.validate_business_rules({"a": 1}, [rule])
        self.assertTrue(result["valid"])

    def test_business_rules_error(self):
        def rule(data):
            return {"valid": False, "severity": "error", "message": "nope"}

        result = self.validator.validate_business_rules({"a": 1}, [rule])
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["rule"], "rule")
        self.assertEqual(result["errors"][0]["message"], "nope")

    def test_business_rules_warning(self):
        def rule(data):
            return {"valid": False, "severity": "warning", "message": "careful"}

        result = self.validator.validate_business_rules({"a": 1}, [rule])
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["warnings"]), 1)

    def test_business_rules_non_dict_return_ignored(self):
        def rule(data):
            return True  # not a dict -> ignored, stays valid

        result = self.validator.validate_business_rules({"a": 1}, [rule])
        self.assertTrue(result["valid"])

    def test_business_rules_exception_captured(self):
        def rule(data):
            raise ValueError("explode")

        result = self.validator.validate_business_rules({"a": 1}, [rule])
        self.assertFalse(result["valid"])
        self.assertIn("explode", result["errors"][0]["message"])
        self.assertEqual(result["errors"][0]["rule"], "rule")

    def test_secure_error_response_valid(self):
        validation_result = {
            "valid": True,
            "sanitized_data": {"a": 1},
            "warnings": [{"message": "w"}],
        }
        # without expose_details -> warnings hidden
        resp = self.validator.create_secure_error_response(validation_result, expose_details=False)
        self.assertTrue(resp["success"])
        self.assertEqual(resp["warnings"], [])

    def test_secure_error_response_valid_expose(self):
        validation_result = {
            "valid": True,
            "sanitized_data": {"a": 1},
            "warnings": [{"message": "w"}],
        }
        resp = self.validator.create_secure_error_response(validation_result, expose_details=True)
        self.assertEqual(len(resp["warnings"]), 1)

    def test_secure_error_response_invalid_generic(self):
        validation_result = {
            "valid": False,
            "errors": [{"field": "email", "message": "Invalid email format"}],
            "schema_name": "member_data",
        }
        resp = self.validator.create_secure_error_response(validation_result, expose_details=False)
        self.assertFalse(resp["success"])
        self.assertEqual(resp["error_count"], 1)
        # generic error must NOT leak the field-level detail
        self.assertEqual(resp["errors"][0]["code"], "VALIDATION_ERROR")
        self.assertNotIn("email", json.dumps(resp["errors"]))

    def test_secure_error_response_invalid_expose(self):
        validation_result = {
            "valid": False,
            "errors": [{"field": "email", "message": "Invalid email format"}],
            "warnings": [],
            "schema_name": "member_data",
        }
        resp = self.validator.create_secure_error_response(validation_result, expose_details=True)
        self.assertFalse(resp["success"])
        self.assertEqual(resp["errors"][0]["field"], "email")
        self.assertEqual(resp["schema"], "member_data")

    def test_direct_instantiation(self):
        # EnhancedValidator() should construct with audit logger + registry
        v = EnhancedValidator()
        self.assertIsNotNone(v.schema_registry)
        self.assertIsNotNone(v.audit_logger)
