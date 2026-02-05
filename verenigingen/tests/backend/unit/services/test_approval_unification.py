"""
Tests for approval orchestration unification.

PURPOSE:
    These tests verify the state of the approval orchestration code after the
    unification refactoring that consolidated three competing approval orchestrators
    into one canonical path through MembershipCreationService.

ARCHITECTURE AFTER REFACTORING:
    The canonical approval flow is:
        approve_membership_application() in api/membership_application_review.py
            → member.create_membership_on_approval()
                → MembershipCreationService.create_membership_on_approval()

    Background approval uses the same canonical path:
        approve_membership_application_background() in api/background_approval_api.py
            → member.create_membership_on_approval(approval_fields=...)

DELETED (no longer exist):
    - member_approval_service.validate_member_fields
    - member_approval_service.create_membership_and_invoice
    - member_approval_service.finalize_member_approval
    - member_approval_service.process_member_approval
    - membership_application_review.create_membership_and_invoice (local copy)

PRESERVED (must remain importable):
    - member_approval_service.resolve_membership_type
    - member_approval_service.create_member_iban_history
    - member_approval_service.validate_approval_prerequisites
    - membership_creation_service.MembershipCreationService

NOTE:
    These tests do NOT create any documents or test business logic. They are pure
    import/existence checks that run without database interaction.
"""

import importlib
import inspect

from frappe.tests.utils import FrappeTestCase


class TestApprovalOrchestrationUnified(FrappeTestCase):
    """
    Post-refactoring tests verifying the approval orchestration unification.

    These tests confirm that:
    1. Deleted functions are no longer importable
    2. Preserved functions remain importable
    3. The canonical approval path exists and is wired correctly
    4. The background API uses the canonical path (not deleted functions)
    """

    # -------------------------------------------------------------------------
    # Tests verifying deleted functions are GONE
    # -------------------------------------------------------------------------

    def test_validate_member_fields_removed(self):
        """validate_member_fields was deleted — must not exist."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.member_approval_service"
        )
        self.assertIsNone(
            getattr(module, "validate_member_fields", None),
            "validate_member_fields should have been deleted from member_approval_service",
        )

    def test_approval_service_create_membership_and_invoice_removed(self):
        """Approval service's create_membership_and_invoice was deleted — must not exist."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.member_approval_service"
        )
        self.assertIsNone(
            getattr(module, "create_membership_and_invoice", None),
            "create_membership_and_invoice should have been deleted from member_approval_service",
        )

    def test_finalize_member_approval_removed(self):
        """finalize_member_approval was deleted — must not exist."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.member_approval_service"
        )
        self.assertIsNone(
            getattr(module, "finalize_member_approval", None),
            "finalize_member_approval should have been deleted from member_approval_service",
        )

    def test_process_member_approval_removed(self):
        """process_member_approval was deleted — must not exist."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.member_approval_service"
        )
        self.assertIsNone(
            getattr(module, "process_member_approval", None),
            "process_member_approval should have been deleted from member_approval_service",
        )

    def test_review_api_create_membership_and_invoice_removed(self):
        """Review API's local create_membership_and_invoice was deleted — must not exist."""
        module = importlib.import_module(
            "verenigingen.api.membership_application_review"
        )
        self.assertIsNone(
            getattr(module, "create_membership_and_invoice", None),
            "create_membership_and_invoice should have been deleted from review API",
        )

    # -------------------------------------------------------------------------
    # Tests verifying preserved functions still exist
    # -------------------------------------------------------------------------

    def test_resolve_membership_type_preserved(self):
        """resolve_membership_type must remain importable."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.member_approval_service"
        )
        func = getattr(module, "resolve_membership_type", None)
        self.assertIsNotNone(
            func,
            "resolve_membership_type must exist in member_approval_service",
        )
        self.assertTrue(callable(func))

    def test_create_member_iban_history_preserved(self):
        """create_member_iban_history must remain importable."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.member_approval_service"
        )
        func = getattr(module, "create_member_iban_history", None)
        self.assertIsNotNone(
            func,
            "create_member_iban_history must exist in member_approval_service",
        )
        self.assertTrue(callable(func))

    def test_validate_approval_prerequisites_preserved(self):
        """validate_approval_prerequisites must remain importable."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.member_approval_service"
        )
        func = getattr(module, "validate_approval_prerequisites", None)
        self.assertIsNotNone(
            func,
            "validate_approval_prerequisites must exist in member_approval_service",
        )
        self.assertTrue(callable(func))

    def test_membership_creation_service_class_preserved(self):
        """MembershipCreationService class must remain importable."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.membership_creation_service"
        )
        cls = getattr(module, "MembershipCreationService", None)
        self.assertIsNotNone(
            cls,
            "MembershipCreationService must exist in membership_creation_service",
        )
        self.assertTrue(inspect.isclass(cls))

    # -------------------------------------------------------------------------
    # Tests verifying the canonical approval path
    # -------------------------------------------------------------------------

    def test_canonical_approval_endpoint_exists(self):
        """approve_membership_application must exist as the canonical API endpoint."""
        module = importlib.import_module(
            "verenigingen.api.membership_application_review"
        )
        func = getattr(module, "approve_membership_application", None)
        self.assertIsNotNone(func)
        self.assertTrue(callable(func))

    def test_membership_creation_service_has_create_membership_on_approval(self):
        """MembershipCreationService must have create_membership_on_approval method."""
        module = importlib.import_module(
            "verenigingen.services.member.approval.membership_creation_service"
        )
        cls = getattr(module, "MembershipCreationService", None)
        self.assertIsNotNone(cls)
        self.assertTrue(hasattr(cls, "create_membership_on_approval"))
        self.assertTrue(callable(getattr(cls, "create_membership_on_approval")))

    def test_member_doctype_has_create_membership_on_approval(self):
        """Member DocType must have create_membership_on_approval method (delegates to service)."""
        module = importlib.import_module(
            "verenigingen.verenigingen.doctype.member.member"
        )
        member_cls = getattr(module, "Member", None)
        self.assertIsNotNone(member_cls)
        self.assertTrue(hasattr(member_cls, "create_membership_on_approval"))
        self.assertTrue(callable(getattr(member_cls, "create_membership_on_approval")))

    def test_member_doctype_has_approve_application(self):
        """Member DocType must still have approve_application (deprecated but not removed)."""
        module = importlib.import_module(
            "verenigingen.verenigingen.doctype.member.member"
        )
        member_cls = getattr(module, "Member", None)
        self.assertIsNotNone(member_cls)
        self.assertTrue(hasattr(member_cls, "approve_application"))

    def test_lifecycle_service_approve_application_exists(self):
        """MemberLifecycleService.approve_application must still exist (deprecated)."""
        module = importlib.import_module(
            "verenigingen.services.member.core.member_lifecycle_service"
        )
        cls = getattr(module, "MemberLifecycleService", None)
        self.assertIsNotNone(cls)
        self.assertTrue(hasattr(cls, "approve_application"))
        self.assertTrue(callable(getattr(cls, "approve_application")))

    # -------------------------------------------------------------------------
    # Tests verifying cross-module import relationships
    # -------------------------------------------------------------------------

    def test_background_api_does_not_import_create_membership_and_invoice(self):
        """Background API must NOT import create_membership_and_invoice from review API.

        After refactoring, the background API uses member.create_membership_on_approval()
        instead of the deleted create_membership_and_invoice function.
        """
        import ast

        module = importlib.import_module(
            "verenigingen.api.background_approval_api"
        )
        source_code = inspect.getsource(module)
        tree = ast.parse(source_code)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "membership_application_review" in node.module:
                    imported_names = [alias.name for alias in node.names]
                    self.assertNotIn(
                        "create_membership_and_invoice",
                        imported_names,
                        "background API must not import create_membership_and_invoice from review API",
                    )

    def test_background_api_uses_canonical_approval_path(self):
        """Background API must use member.create_membership_on_approval().

        Verify the source code contains the canonical call pattern.
        """
        module = importlib.import_module(
            "verenigingen.api.background_approval_api"
        )
        source_code = inspect.getsource(module)

        self.assertIn(
            "create_membership_on_approval",
            source_code,
            "background API must use member.create_membership_on_approval()",
        )

    def test_review_api_imports_resolve_membership_type_from_approval_service(self):
        """Review API must re-export resolve_membership_type from approval service."""
        module = importlib.import_module(
            "verenigingen.api.membership_application_review"
        )
        func = getattr(module, "resolve_membership_type", None)
        self.assertIsNotNone(
            func,
            "resolve_membership_type should be importable from membership_application_review",
        )
        self.assertTrue(callable(func))
