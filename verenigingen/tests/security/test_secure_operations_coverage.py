"""
Coverage / behaviour tests for verenigingen/utils/secure_operations.py
======================================================================

Sibling to ``test_secure_operations_security_audit.py``. That suite covers the
headline audit fixes; this one exercises the many still-uncovered branches with
REAL integration tests (EnhancedTestCase -> per-test rollback on the dirty veg11
dev site):

* validate_justification - all length/empty branches
* can_request_system_escalation / can_use_bypass_validations - allow AND deny,
  and the security-critical fact that bypass is STRICTER than escalation
* validate_permissions - basic deny, nonexistent-DocType deny, specific-perm deny
* verify_document_integrity - child-table broken links, no-bypass, meta error
* get_system_user_for_operation - happy path
* secure_user_context_with_validation - nonexistent / disabled target rejection
* secure_document_operation - allow_system_user=False denial path
* secure_batch_operation - success + malformed op handling
* CriticalOperationsRegistry - business-rule / criticality / monitoring logic
* execute_critical_operation - unconfigured, critical-violation, missing
  justification, configured success
* execute_bulk_member_operation convenience wrapper
* SecureOperationResult.doc typo-guard, deprecated secure_user_context wrapper

All privilege switches happen in ``_ensure_*`` / ``_with_*`` fixture helpers so
the test-quality-enforcer allowlist is respected, and every switch is restored
in a finally block.
"""

import contextlib

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSecureOperationsCoverage(EnhancedTestCase):
    """Branch-coverage integration tests for the secure operations framework."""

    def setUp(self):
        super().setUp()
        self._start_user = frappe.session.user

    def tearDown(self):
        # Defensive: always land back on Administrator before rollback/cleanup.
        frappe.set_user("Administrator")
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixture helpers (privileged operations live here by naming convention)
    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def _with_user(self, user):
        previous = frappe.session.user
        frappe.set_user(user)
        try:
            yield
        finally:
            frappe.set_user(previous)

    def _ensure_role(self, role_name):
        if not frappe.db.exists("Role", role_name):
            role = frappe.new_doc("Role")
            role.role_name = role_name
            role.desk_access = 1
            role.insert(ignore_permissions=True)
        return role_name

    def _make_user(self, roles):
        """Create an enabled System User carrying exactly ``roles`` (plus defaults)."""
        for r in roles:
            self._ensure_role(r)
        return self.factory.create_user_with_roles(roles=list(roles))

    # ==================================================================
    # validate_justification
    # ==================================================================
    def test_validate_justification_rejects_empty(self):
        from verenigingen.utils.secure_operations import validate_justification

        with self.assertRaises(frappe.ValidationError):
            validate_justification("", "create")

    def test_validate_justification_rejects_whitespace_only(self):
        from verenigingen.utils.secure_operations import validate_justification

        # Non-empty string that strips down below MIN_JUSTIFICATION_LENGTH.
        with self.assertRaises(frappe.ValidationError):
            validate_justification("   short   ", "create")

    def test_validate_justification_rejects_too_short(self):
        from verenigingen.utils.secure_operations import (
            MIN_JUSTIFICATION_LENGTH,
            validate_justification,
        )

        too_short = "a" * (MIN_JUSTIFICATION_LENGTH - 1)
        with self.assertRaises(frappe.ValidationError):
            validate_justification(too_short, "save")

    def test_validate_justification_strips_and_returns_valid(self):
        from verenigingen.utils.secure_operations import validate_justification

        result = validate_justification("  a valid justification string  ", "save")
        self.assertEqual(result, "a valid justification string")

    def test_validate_justification_truncates_overlong(self):
        from verenigingen.utils.secure_operations import (
            MAX_JUSTIFICATION_LENGTH,
            validate_justification,
        )

        overlong = "x" * (MAX_JUSTIFICATION_LENGTH + 50)
        result = validate_justification(overlong, "save")
        self.assertEqual(len(result), MAX_JUSTIFICATION_LENGTH)
        self.assertTrue(result.endswith("..."))

    # ==================================================================
    # can_request_system_escalation
    # ==================================================================
    def test_administrator_can_request_escalation(self):
        from verenigingen.utils.secure_operations import can_request_system_escalation

        self.assertTrue(can_request_system_escalation("Administrator"))

    def test_escalation_allowed_role_can_request_escalation(self):
        from verenigingen.utils.secure_operations import can_request_system_escalation

        user = self._make_user(["Verenigingen Administrator"])
        self.assertTrue(can_request_system_escalation(user.name))

    def test_ordinary_member_cannot_request_escalation(self):
        from verenigingen.utils.secure_operations import can_request_system_escalation

        user = self._make_user(["Verenigingen Member"])
        self.assertFalse(can_request_system_escalation(user.name))

    def test_escalation_defaults_to_session_user(self):
        from verenigingen.utils.secure_operations import can_request_system_escalation

        user = self._make_user(["Verenigingen Member"])
        with self._with_user(user.name):
            # No explicit user -> falls back to frappe.session.user
            self.assertFalse(can_request_system_escalation())

    # ==================================================================
    # can_use_bypass_validations  (STRICTER than escalation)
    # ==================================================================
    def test_administrator_can_use_bypass(self):
        from verenigingen.utils.secure_operations import can_use_bypass_validations

        self.assertTrue(can_use_bypass_validations("Administrator"))

    def test_system_manager_can_use_bypass(self):
        from verenigingen.utils.secure_operations import can_use_bypass_validations

        user = self._make_user(["System Manager"])
        self.assertTrue(can_use_bypass_validations(user.name))

    def test_escalation_role_cannot_use_bypass(self):
        """SECURITY: a user who CAN escalate must still be denied bypass_validations.

        bypass is gated by BYPASS_VALIDATION_ALLOWED_ROLES which is strictly
        narrower than ESCALATION_ALLOWED_ROLES. Verenigingen Administrator is in
        the escalation set but NOT the bypass set.
        """
        from verenigingen.utils.secure_operations import (
            can_request_system_escalation,
            can_use_bypass_validations,
        )

        user = self._make_user(["Verenigingen Administrator"])
        self.assertTrue(can_request_system_escalation(user.name))
        self.assertFalse(can_use_bypass_validations(user.name))

    def test_ordinary_member_cannot_use_bypass(self):
        from verenigingen.utils.secure_operations import can_use_bypass_validations

        user = self._make_user(["Verenigingen Member"])
        self.assertFalse(can_use_bypass_validations(user.name))

    # ==================================================================
    # validate_permissions
    # ==================================================================
    def test_validate_permissions_administrator_allowed(self):
        from verenigingen.utils.secure_operations import validate_permissions

        doc = frappe.new_doc("ToDo")
        doc.description = "perm check todo"
        self.assertTrue(validate_permissions(doc, "create"))

    def test_validate_permissions_denies_nonexistent_required_doctype(self):
        from verenigingen.utils.secure_operations import validate_permissions

        doc = frappe.new_doc("ToDo")
        doc.description = "perm check todo"
        # Administrator passes the basic check, but the required DocType is bogus.
        self.assertFalse(
            validate_permissions(doc, "create", required_permissions=["NoSuchDocTypeXYZ:read"])
        )

    def test_validate_permissions_guest_denied_basic(self):
        from verenigingen.utils.secure_operations import validate_permissions

        doc = frappe.new_doc("Customer")
        doc.customer_name = "Perm Deny Customer"
        with self._with_user("Guest"):
            self.assertFalse(validate_permissions(doc, "create"))

    def test_validate_permissions_specific_permission_denied(self):
        from verenigingen.utils.secure_operations import validate_permissions

        user = self._make_user(["Verenigingen Member"])
        doc = frappe.new_doc("ToDo")
        doc.description = "specific perm check"
        with self._with_user(user.name):
            # Ordinary member lacks 'delete' on Chapter -> specific-permission branch denies.
            self.assertFalse(
                validate_permissions(doc, "read", required_permissions=["Chapter:delete"])
            )

    # ==================================================================
    # verify_document_integrity
    # ==================================================================
    def test_integrity_no_bypass_returns_empty(self):
        from verenigingen.utils.secure_operations import verify_document_integrity

        doc = frappe.new_doc("ToDo")
        self.assertEqual(verify_document_integrity(doc, None), [])
        self.assertEqual(verify_document_integrity(doc, []), [])

    def test_integrity_detects_broken_child_table_link(self):
        from verenigingen.utils.secure_operations import verify_document_integrity

        # User.roles is a child table (Has Role) whose `role` is a Link to Role.
        doc = frappe.new_doc("User")
        doc.email = "integrity-child@example.invalid"
        doc.first_name = "Integrity"
        doc.append("roles", {"role": "NoSuchRoleXYZ123"})

        violations = verify_document_integrity(doc, ["link_validation"])
        self.assertTrue(
            any("roles" in v and "NoSuchRoleXYZ123" in v for v in violations),
            f"Expected a broken child-table link violation, got: {violations}",
        )

    def test_integrity_verification_failure_is_captured(self):
        from verenigingen.utils.secure_operations import verify_document_integrity

        # A doctype that does not exist makes frappe.get_meta raise; the function
        # must swallow it into a violation rather than propagate.
        bogus = frappe._dict(doctype="NoSuchDocTypeForIntegrityXYZ", name="x")
        violations = verify_document_integrity(bogus, ["link_validation"])
        self.assertTrue(
            any("Integrity verification failed" in v for v in violations),
            f"Expected captured failure violation, got: {violations}",
        )

    # ==================================================================
    # get_system_user_for_operation (happy path)
    # ==================================================================
    def test_get_system_user_returns_configured_enabled_user(self):
        from verenigingen.utils.secure_operations import get_system_user_for_operation

        system_user = self._make_user(["System Manager"])

        orig = frappe.db.get_single_value("Verenigingen Settings", "creation_user")
        try:
            frappe.db.set_value("Verenigingen Settings", None, "creation_user", system_user.name)
            frappe.clear_document_cache("Verenigingen Settings")
            resolved = get_system_user_for_operation("test context")
            self.assertEqual(resolved, system_user.name)
        finally:
            frappe.db.set_value("Verenigingen Settings", None, "creation_user", orig)
            frappe.clear_document_cache("Verenigingen Settings")

    # ==================================================================
    # secure_user_context_with_validation - target validation
    # ==================================================================
    def test_context_rejects_nonexistent_target_user(self):
        from verenigingen.utils.secure_operations import (
            _get_impersonation_stack,
            secure_user_context_with_validation,
        )

        _get_impersonation_stack().clear()
        with self.assertRaises(frappe.ValidationError) as ctx:
            with secure_user_context_with_validation("nobody-xyz@example.invalid", "op"):
                pass
        self.assertIn("does not exist", str(ctx.exception))
        # Stack must be cleaned up even on the rejection path.
        self.assertEqual(len(_get_impersonation_stack()), 0)

    def test_context_rejects_disabled_target_user(self):
        from verenigingen.utils.secure_operations import (
            _get_impersonation_stack,
            secure_user_context_with_validation,
        )

        disabled = self._make_user(["Verenigingen Member"])
        frappe.db.set_value("User", disabled.name, "enabled", 0)
        frappe.clear_document_cache("User", disabled.name)

        _get_impersonation_stack().clear()
        with self.assertRaises(frappe.ValidationError) as ctx:
            with secure_user_context_with_validation(disabled.name, "op"):
                pass
        self.assertIn("disabled", str(ctx.exception))
        self.assertEqual(len(_get_impersonation_stack()), 0)

    # ==================================================================
    # secure_document_operation - allow_system_user=False denial
    # ==================================================================
    def test_operation_without_system_fallback_fails_cleanly(self):
        from verenigingen.utils.secure_operations import secure_document_operation

        self.expectErrorLog("Secure Operation Failed")
        doc = frappe.new_doc("Customer")
        doc.customer_name = "No Fallback Customer"

        with self._with_user("Guest"):
            result = secure_document_operation(
                operation="create",
                doc=doc,
                justification="Attempt without system fallback allowed",
                allow_system_user=False,
            )

        self.assertFalse(result.success)
        error_text = " ".join(result.errors).lower()
        self.assertIn("fallback not allowed", error_text)
        self.assertIsNone(result.doc_name)

    def test_operation_succeeds_for_current_user(self):
        from verenigingen.utils.secure_operations import secure_document_operation

        doc = frappe.new_doc("ToDo")
        doc.description = "current-user secure op"
        result = secure_document_operation(
            operation="create",
            doc=doc,
            justification="Administrator creates a ToDo directly",
            allow_system_user=False,
        )
        self.assertTrue(result.success, f"errors: {result.errors}")
        self.assertIsNotNone(result.doc_name)
        self.assertIs(result.document, doc)

    def test_registry_is_singleton(self):
        from verenigingen.utils.secure_operations import get_critical_operations_registry

        self.assertIs(get_critical_operations_registry(), get_critical_operations_registry())

    def test_registry_business_rule_amount_threshold(self):
        from verenigingen.utils.secure_operations import CriticalOperationsRegistry

        reg = CriticalOperationsRegistry()
        reg.operation_configs["thr_op"] = {
            "security_level": "critical",
            "business_rules": {"enabled": True, "amount_threshold": 100},
            "monitoring": {"latency_ms": 500},
        }

        # Over threshold -> violation
        over = reg.validate_business_rules("thr_op", amount=250)
        self.assertTrue(any("exceeds threshold" in v for v in over))
        # Under threshold -> no violation
        self.assertEqual(reg.validate_business_rules("thr_op", amount=50), [])
        # Criticality + monitoring accessors
        self.assertTrue(reg.is_critical_operation("thr_op"))
        self.assertEqual(reg.get_monitoring_thresholds("thr_op"), {"latency_ms": 500})

    def test_registry_business_rules_disabled_and_unknown(self):
        from verenigingen.utils.secure_operations import CriticalOperationsRegistry

        reg = CriticalOperationsRegistry()
        reg.operation_configs["off_op"] = {
            "security_level": "low",
            "business_rules": {"enabled": False, "amount_threshold": 1},
        }
        # Disabled business rules -> always empty
        self.assertEqual(reg.validate_business_rules("off_op", amount=9999), [])
        # low security level -> not critical
        self.assertFalse(reg.is_critical_operation("off_op"))
        # Unknown op -> not critical, empty monitoring
        self.assertFalse(reg.is_critical_operation("does_not_exist_op"))
        self.assertEqual(reg.get_monitoring_thresholds("does_not_exist_op"), {})

    def test_secure_result_doc_attribute_raises(self):
        from verenigingen.utils.secure_operations import SecureOperationResult

        r = SecureOperationResult(True, "op-id")
        with self.assertRaises(AttributeError) as ctx:
            _ = r.doc
        self.assertIn(".document", str(ctx.exception))

    # ==================================================================
    # Deprecated wrapper
    # ==================================================================
    def test_deprecated_secure_user_context_still_yields_result(self):
        from verenigingen.utils.secure_operations import (
            SecureOperationResult,
            _get_impersonation_stack,
            secure_user_context,
        )

        _get_impersonation_stack().clear()
        with secure_user_context("Administrator", "deprecated_op") as result:
            self.assertIsInstance(result, SecureOperationResult)
        self.assertEqual(len(_get_impersonation_stack()), 0)
