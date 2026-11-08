"""
#857: a permission-check helper that ERRORS must not look like a plain denial.

Three helpers in verenigingen/utils/secure_operations.py returned False both for
"denied" and for "the check itself raised", logging only via frappe.logger()
(a rotating file nobody reads). They stay FAIL-CLOSED; what changed is that an
errored check is now recorded in the Error Log, and validate_permissions()
raises PermissionCheckError so secure_document_operation() does not mistake it
for a denial and fall into the system-user escalation branch.

Failures are injected at the layer that really raises:
* validate_permissions: ``frappe.has_permission`` raises DoesNotExistError for an
  unknown DocType when the caller is not Administrator (measured on test_site_9).
* can_*: ``frappe.get_roles`` raises when handed a user that is not a string
  (a list is unhashable in its cache lookup).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

BOGUS_DOCTYPE = "NoSuchDoctypeXYZ857"
CHECK_TITLE_PREFIX = "Permission check errored:"


class TestPermissionCheckErrors857(EnhancedTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _make_user_857(self, role):
        return self.factory.create_user_with_roles(roles=[role])

    def _call_as_857(self, user_name, fn, *args, **kwargs):
        """Run fn as user_name; privilege switches live in helpers (enforcer allowlist)."""
        frappe.set_user(user_name)
        try:
            return fn(*args, **kwargs)
        finally:
            frappe.set_user("Administrator")

    def _error_titles(self, since):
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", since], "method": ["like", f"{CHECK_TITLE_PREFIX}%"]},
            pluck="method",
        )

    def _broken_user(self):
        # Not a str: frappe.get_roles() raises on it, on the real code path.
        return ["not", "a", "user"]

    # ---- can_request_system_escalation / can_use_bypass_validations ----
    def test_errored_escalation_check_is_denied_and_recorded(self):
        from verenigingen.utils.secure_operations import can_request_system_escalation

        since = frappe.utils.now_datetime()
        self.assertFalse(can_request_system_escalation(self._broken_user()))
        self.assertEqual(
            self._error_titles(since), [f"{CHECK_TITLE_PREFIX} can_request_system_escalation"]
        )

    def test_errored_bypass_check_is_denied_and_recorded(self):
        from verenigingen.utils.secure_operations import can_use_bypass_validations

        since = frappe.utils.now_datetime()
        self.assertFalse(can_use_bypass_validations(self._broken_user()))
        self.assertEqual(self._error_titles(since), [f"{CHECK_TITLE_PREFIX} can_use_bypass_validations"])

    def test_clean_denial_and_allow_record_nothing(self):
        from verenigingen.utils.secure_operations import (
            can_request_system_escalation,
            can_use_bypass_validations,
        )

        member = self._make_user_857("Verenigingen Member")
        admin = self._make_user_857("System Manager")
        since = frappe.utils.now_datetime()
        self.assertFalse(can_request_system_escalation(member.name))
        self.assertFalse(can_use_bypass_validations(member.name))
        self.assertTrue(can_request_system_escalation(admin.name))
        self.assertTrue(can_use_bypass_validations(admin.name))
        self.assertEqual(self._error_titles(since), [])

    # ---- validate_permissions ----
    def test_errored_validate_permissions_raises_not_returns_false(self):
        from verenigingen.utils.secure_operations import PermissionCheckError, validate_permissions

        member = self._make_user_857("Verenigingen Member")
        doc = frappe._dict(doctype=BOGUS_DOCTYPE, name="x")
        with self.assertRaises(PermissionCheckError):
            self._call_as_857(member.name, validate_permissions, doc, "create")

    def test_validate_permissions_denial_still_returns_false_and_allow_true(self):
        from verenigingen.utils.secure_operations import validate_permissions

        member = self._make_user_857("Verenigingen Member")
        doc = frappe.new_doc("ToDo")
        doc.description = "perm check 857"
        self.assertTrue(validate_permissions(doc, "create"))  # Administrator
        denied = self._call_as_857(member.name, validate_permissions, frappe.new_doc("Chapter"), "delete")
        self.assertFalse(denied)

    # ---- secure_document_operation: an errored check never escalates ----
    def test_errored_check_does_not_escalate_an_escalation_capable_user(self):
        """The harm: before, error -> False -> 'lacks permission' -> escalation."""
        from verenigingen.utils.secure_operations import (
            can_request_system_escalation,
            secure_document_operation,
        )

        user = self._make_user_857("Verenigingen Administrator")
        self.assertTrue(can_request_system_escalation(user.name))  # would be allowed to escalate
        doc = frappe._dict(doctype=BOGUS_DOCTYPE, name="x", docstatus=0)
        result = self._call_as_857(
            user.name,
            secure_document_operation,
            operation="save",
            doc=doc,
            justification="exercise the broken-check path for #857",
        )
        self.assertFalse(result.success)
        joined = " ".join(result.errors)
        self.assertIn("could not be completed", joined)
        self.assertNotIn("Even system user", joined)
        self.assertNotIn("Insufficient permissions", joined)
