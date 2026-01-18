"""
SEPA Mandate Mixin for Member DocType.

This mixin provides SEPA mandate-related functionality for the Member DocType.
Most methods delegate to SEPAMandateManager service for actual implementation.

Phase 2 SEPA Service Extraction:
    - All core logic moved to SEPAMandateManager
    - Mixin provides backward-compatible member.method() patterns
    - Deprecation warnings guide migration to service layer

Architecture:
    Member.sepa_method() → SEPAMandateManager.method()
    - Thin delegation layer
    - Backward compatibility for existing code
    - Deprecation path to direct service usage
"""

from typing import Any, Dict

import frappe
from frappe.utils import today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class SEPAMandateMixin:
    """Mixin for SEPA mandate-related functionality.

    .. note::
        All methods delegate to SEPAMandateManager. This mixin provides backward
        compatibility for code that relies on member.method() patterns.
    """

    def get_active_sepa_mandates(self):
        """
        Get all active SEPA mandates for this member.

        .. deprecated:: 2025-10-14
            Use SEPAMandateManager.get_active_mandates() instead.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "get_active_sepa_mandates() is deprecated. Use SEPAMandateManager.get_active_mandates() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        manager = get_sepa_mandate_manager()
        mandates = manager.get_active_mandates(self.name)
        return [
            frappe._dict(
                name=m.name,
                mandate_id=m.mandate_id,
                status=m.status,
                expiry_date=m.expiry_date,
                used_for_memberships=m.used_for_memberships,
                used_for_donations=m.used_for_donations,
            )
            for m in mandates
        ]

    def get_default_sepa_mandate(self):
        """
        Get the default SEPA mandate for this member.

        .. deprecated:: 2025-10-14
            Use SEPAMandateManager.get_default_mandate() instead.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "get_default_sepa_mandate() is deprecated. Use SEPAMandateManager.get_default_mandate() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        manager = get_sepa_mandate_manager()
        mandate_info = manager.get_default_mandate(self.name)
        if mandate_info:
            return frappe.get_doc("SEPA Mandate", mandate_info.name)
        return None

    def has_active_sepa_mandate(self, purpose="memberships"):
        """
        Check if member has an active SEPA mandate for a specific purpose.

        .. deprecated:: 2025-10-14
            Use SEPAMandateManager.has_active_mandate() instead.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "has_active_sepa_mandate() is deprecated. Use SEPAMandateManager.has_active_mandate() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        manager = get_sepa_mandate_manager()
        return manager.has_active_mandate(self.name, purpose)

    def refresh_sepa_mandates_table(self):
        """
        Refresh the SEPA mandates child table by syncing with actual SEPA Mandate records.

        EXTRACTED: Delegates to SEPAMandateManager.sync_member_mandates()
        for service layer separation (Phase 2 SEPA Service Extraction).
        """
        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        manager = get_sepa_mandate_manager()
        result = manager.sync_member_mandates(self.name)

        # Convert ValidationResult to dict for backward compatibility
        if result.valid:
            return {
                "success": True,
                "message": result.message,
                "mandates_count": result.data.get("mandates_count", 0),
            }
        else:
            return {"success": False, "error": result.message}

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def create_sepa_mandate(self):
        """
        Create a new SEPA mandate for this member with enhanced prefilling.

        .. deprecated:: 2025-10-14
            Use SEPAMandateManager.create_mandate() instead.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "create_sepa_mandate() is deprecated. Use SEPAMandateManager.create_mandate() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        manager = get_sepa_mandate_manager()
        iban = getattr(self, "iban", None) or ""
        bic = getattr(self, "bic", None)
        account_holder = getattr(self, "bank_account_name", None) or self.full_name

        result = manager.create_mandate(
            member=self.name,
            iban=iban,
            bic=bic,
            account_holder_name=account_holder,
            notes=f"Created from Member {self.name} on {today()}",
        )

        if result.valid:
            return result.data.get("mandate_name")
        else:
            frappe.throw(result.message)

    def _generate_mandate_reference(self):
        """
        Generate a suggested mandate reference for a member.

        .. deprecated:: 2025-10-14
            Use SEPAMandateManager.generate_mandate_reference() instead.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "_generate_mandate_reference() is deprecated. Use SEPAMandateManager.generate_mandate_reference() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        manager = get_sepa_mandate_manager()
        mandate_ref = manager.generate_mandate_reference(self.name, self.member_id)
        return {"mandate_reference": mandate_ref}

    def create_sepa_mandate_via_service(self, iban: str, bic: str = None) -> Dict[str, Any]:
        """
        Service layer integration method for SEPA mandate creation.

        .. deprecated:: 2025-10-14
            Use SEPAMandateManager.create_mandate() instead.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "create_sepa_mandate_via_service() is deprecated. Use SEPAMandateManager.create_mandate() instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        manager = get_sepa_mandate_manager()
        account_holder = getattr(self, "bank_account_name", None) or self.full_name

        result = manager.create_mandate(
            member=self.name,
            iban=iban,
            bic=bic,
            account_holder_name=account_holder,
            notes=f"Created via service layer from Member {self.name} on {today()}",
        )

        if result.valid:
            return {
                "success": True,
                "mandate": frappe.get_doc("SEPA Mandate", result.data.get("mandate_name")),
                "message": result.message,
            }
        else:
            return {
                "success": False,
                "message": result.message,
                "errors": result.errors,
            }


# ========== Module-Level API Functions ==========
# These delegate to SEPAMandateManager for actual implementation


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def check_sepa_mandate_discrepancies():
    """
    Scheduled task to check for SEPA mandate discrepancies and automatically fix them.

    EXTRACTED: Delegates to SEPAMandateManager.check_discrepancies()
    for service layer separation (Phase 2 SEPA Service Extraction).

    This replaces the real-time checking that was triggered by form field changes.
    """
    from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

    manager = get_sepa_mandate_manager()
    return manager.check_discrepancies()
