from typing import Any, Dict

import frappe
from frappe.utils import today

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.utils.settings_utils import get_payments_settings


class SEPAMandateMixin:
    """Mixin for SEPA mandate-related functionality.

    .. note::
        Most methods delegate to SEPAMandateManager. This mixin provides backward
        compatibility for code that relies on member.method() patterns.
    """

    def get_active_sepa_mandates(self):
        """
        Get all active SEPA mandates for this member.

        .. deprecated:: 2025-10-14
            Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.get_active_mandates` instead.
            This method will be removed in a future version.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "get_active_sepa_mandates() is deprecated. Use SEPAMandateManager.get_active_mandates() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to service - convert MandateInfo objects to dicts for backward compatibility
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
            Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.get_default_mandate` instead.
            This method will be removed in a future version.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "get_default_sepa_mandate() is deprecated. Use SEPAMandateManager.get_default_mandate() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to service - return full doc for backward compatibility
        manager = get_sepa_mandate_manager()
        mandate_info = manager.get_default_mandate(self.name)
        if mandate_info:
            return frappe.get_doc("SEPA Mandate", mandate_info.name)
        return None

    def has_active_sepa_mandate(self, purpose="memberships"):
        """
        Check if member has an active SEPA mandate for a specific purpose.

        .. deprecated:: 2025-10-14
            Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.has_active_mandate` instead.
            This method will be removed in a future version.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "has_active_sepa_mandate() is deprecated. Use SEPAMandateManager.has_active_mandate() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to service
        manager = get_sepa_mandate_manager()
        return manager.has_active_mandate(self.name, purpose)

    def refresh_sepa_mandates_table(self):
        """Refresh the SEPA mandates child table by syncing with actual SEPA Mandate records"""
        try:
            # Get all SEPA mandates for this member
            mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": self.name},
                fields=["name", "mandate_id", "status", "is_active", "sign_date", "expiry_date"],
                order_by="creation desc",
            )

            # Clear existing links
            self.sepa_mandates = []

            # Rebuild the child table from actual mandates
            for mandate in mandates:
                self.append(
                    "sepa_mandates",
                    {
                        "sepa_mandate": mandate.name,
                        "mandate_reference": mandate.mandate_id,
                        "status": mandate.status,
                        "is_current": 1 if mandate.status == "Active" and mandate.is_active else 0,
                        "valid_from": mandate.sign_date,
                        "valid_until": mandate.expiry_date,
                    },
                )

            # Save using native update_child_table to avoid timestamp conflicts
            self.update_child_table("sepa_mandates")
            frappe.db.commit()

            return {
                "success": True,
                "message": f"Refreshed {len(mandates)} SEPA mandate(s)",
                "mandates_count": len(mandates),
            }

        except Exception as e:
            frappe.log_error(f"Error refreshing SEPA mandates for member {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def create_sepa_mandate(self):
        """
        Create a new SEPA mandate for this member with enhanced prefilling.

        .. deprecated:: 2025-10-14
            Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.create_mandate` instead.
            This method will be removed in a future version.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "create_sepa_mandate() is deprecated. Use SEPAMandateManager.create_mandate() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to service
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
            Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.generate_mandate_reference` instead.
        """
        import warnings

        from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

        warnings.warn(
            "_generate_mandate_reference() is deprecated. Use SEPAMandateManager.generate_mandate_reference() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to service
        manager = get_sepa_mandate_manager()
        mandate_ref = manager.generate_mandate_reference(self.name, self.member_id)
        return {"mandate_reference": mandate_ref}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def check_sepa_mandate_discrepancies():
    """
    Scheduled task to check for SEPA mandate discrepancies and automatically fix them.
    This replaces the real-time checking that was triggered by form field changes.
    """
    import time

    start_time = time.time()

    frappe.logger().info("Starting scheduled SEPA mandate discrepancy check")

    try:
        # First check company SEPA settings
        company_settings_status = _check_company_sepa_settings()
        if company_settings_status:
            frappe.logger().warning(f"SEPA Settings Issue: {company_settings_status}")

        # Find members with SEPA Direct Debit or SEPA Direct Debit payment method
        members_with_direct_debit = frappe.get_all(
            "Member",
            filters={"payment_method": "SEPA Direct Debit", "docstatus": ["!=", 2]},  # Not cancelled
            fields=["name", "full_name", "iban", "bic", "bank_account_name"],
        )

        results = {
            "total_checked": len(members_with_direct_debit),
            "missing_mandates": [],
            "iban_mismatches": [],
            "name_mismatches": [],
            "auto_fixed": [],
            "manual_review_needed": [],
            "errors": [],
        }

        for member_data in members_with_direct_debit:
            try:
                member_name = member_data.name
                member_iban = member_data.iban
                member_account_name = member_data.bank_account_name

                # Skip if no IBAN set
                if not member_iban:
                    continue

                # Get active SEPA mandates for this member
                active_mandates = frappe.get_all(
                    "SEPA Mandate",
                    filters={"member": member_name, "status": "Active", "is_active": 1},
                    fields=["name", "mandate_id", "iban", "account_holder_name"],
                )

                if not active_mandates:
                    # No active mandate found
                    results["missing_mandates"].append(
                        {"member": member_name, "member_name": member_data.full_name, "iban": member_iban}
                    )
                    continue

                # Check for discrepancies with existing mandates
                for mandate in active_mandates:
                    mandate_iban = mandate.iban.replace(" ", "").upper() if mandate.iban else ""
                    current_iban = member_iban.replace(" ", "").upper() if member_iban else ""

                    # Check IBAN mismatch
                    if mandate_iban != current_iban:
                        discrepancy = {
                            "member": member_name,
                            "member_name": member_data.full_name,
                            "mandate_id": mandate.mandate_id,
                            "mandate_iban": mandate.iban,
                            "current_iban": member_iban,
                        }

                        # Auto-fix: Deactivate old mandate if IBAN changed
                        if _should_auto_fix_iban_change(member_name, mandate_iban, current_iban):
                            try:
                                _deactivate_mandate_for_iban_change(mandate.name, mandate_iban, current_iban)
                                results["auto_fixed"].append(
                                    {
                                        **discrepancy,
                                        "action": "deactivated_old_mandate",
                                        "reason": "IBAN changed",
                                    }
                                )
                            except Exception as e:
                                results["errors"].append(
                                    {**discrepancy, "error": str(e), "action": "failed_to_deactivate"}
                                )
                        else:
                            results["iban_mismatches"].append(discrepancy)

                    # Check account holder name mismatch
                    if member_account_name and mandate.account_holder_name:
                        if _names_significantly_different(member_account_name, mandate.account_holder_name):
                            discrepancy = {
                                "member": member_name,
                                "member_name": member_data.full_name,
                                "mandate_id": mandate.mandate_id,
                                "mandate_name": mandate.account_holder_name,
                                "current_name": member_account_name,
                            }

                            # Auto-fix: Update mandate name if it's a minor difference
                            if _should_auto_fix_name_change(mandate.account_holder_name, member_account_name):
                                try:
                                    _update_mandate_account_name(mandate.name, member_account_name)
                                    results["auto_fixed"].append(
                                        {
                                            **discrepancy,
                                            "action": "updated_account_name",
                                            "reason": "minor_name_difference",
                                        }
                                    )
                                except Exception as e:
                                    results["errors"].append(
                                        {**discrepancy, "error": str(e), "action": "failed_to_update_name"}
                                    )
                            else:
                                results["name_mismatches"].append(discrepancy)

            except Exception as e:
                results["errors"].append(
                    {"member": member_data.name, "error": str(e), "action": "member_processing_failed"}
                )

        # Log results
        end_time = time.time()
        processing_time = round(end_time - start_time, 2)

        frappe.logger().info(f"SEPA mandate discrepancy check completed in {processing_time}s")
        frappe.logger().info(
            f"Results: {results['total_checked']} checked, "
            f"{len(results['missing_mandates'])} missing mandates, "
            f"{len(results['iban_mismatches'])} IBAN mismatches, "
            f"{len(results['name_mismatches'])} name mismatches, "
            f"{len(results['auto_fixed'])} auto-fixed, "
            f"{len(results['errors'])} errors"
        )

        # Create a log entry for significant issues that need manual review
        _create_discrepancy_log(results)

        return results

    except Exception as e:
        frappe.log_error(f"Error in scheduled SEPA mandate discrepancy check: {str(e)}")
        return {"error": str(e)}


def _should_auto_fix_iban_change(member_name, old_iban, new_iban):
    """Determine if IBAN change should be auto-fixed"""
    # Only auto-fix if both IBANs are valid and different
    if not old_iban or not new_iban:
        return False

    # Don't auto-fix if IBANs are too similar (might be typo)
    if _strings_too_similar(old_iban, new_iban):
        return False

    return True


def _should_auto_fix_name_change(old_name, new_name):
    """Determine if account name change should be auto-fixed"""
    if not old_name or not new_name:
        return False

    # Auto-fix if names are very similar (minor differences)
    return _names_slightly_different(old_name, new_name)


def _names_significantly_different(name1, name2):
    """Check if two names are significantly different"""
    if not name1 or not name2:
        return True

    # Normalize names for comparison
    name1_norm = name1.lower().strip()
    name2_norm = name2.lower().strip()

    # If exact match, not different
    if name1_norm == name2_norm:
        return False

    # Check if one name contains the other
    if name1_norm in name2_norm or name2_norm in name1_norm:
        return False

    # Use simple word overlap check
    words1 = set(name1_norm.split())
    words2 = set(name2_norm.split())

    # If more than 50% word overlap, consider similar
    overlap = len(words1.intersection(words2))
    min_words = min(len(words1), len(words2))

    if min_words > 0 and (overlap / min_words) > 0.5:
        return False

    return True


def _names_slightly_different(name1, name2):
    """Check if two names are only slightly different (for auto-fix)"""
    if not name1 or not name2:
        return False

    # Normalize names
    name1_norm = name1.lower().strip()
    name2_norm = name2.lower().strip()

    # Check if difference is minimal (like punctuation, spacing, case)
    import re

    name1_clean = re.sub(r"[^\w\s]", "", name1_norm)
    name2_clean = re.sub(r"[^\w\s]", "", name2_norm)

    # Remove extra spaces
    name1_clean = " ".join(name1_clean.split())
    name2_clean = " ".join(name2_clean.split())

    return name1_clean == name2_clean


def _strings_too_similar(str1, str2):
    """Check if two strings are suspiciously similar (might indicate typo)"""
    if not str1 or not str2:
        return False

    # Simple character difference check
    if len(str1) == len(str2):
        differences = sum(c1 != c2 for c1, c2 in zip(str1, str2))
        return differences <= 2  # 2 or fewer character differences

    return False


def _deactivate_mandate_for_iban_change(mandate_name, old_iban, new_iban):
    """Deactivate a mandate due to IBAN change"""
    mandate = frappe.get_doc("SEPA Mandate", mandate_name)
    mandate.status = "Cancelled"
    mandate.is_active = 0
    mandate.cancelled_date = today()
    mandate.cancellation_reason = f"IBAN changed from {old_iban} to {new_iban} (auto-deactivated)"
    mandate.save()

    frappe.logger().info(f"Auto-deactivated SEPA mandate {mandate.mandate_id} due to IBAN change")


def _update_mandate_account_name(mandate_name, new_account_name):
    """Update mandate account holder name"""
    mandate = frappe.get_doc("SEPA Mandate", mandate_name)
    old_name = mandate.account_holder_name
    mandate.account_holder_name = new_account_name
    mandate.save()

    frappe.logger().info(
        f"Auto-updated SEPA mandate {mandate.mandate_id} account name from '{old_name}' to '{new_account_name}'"
    )


def _create_discrepancy_log(results):
    """Create a log entry for discrepancies that need manual review"""
    significant_issues = (
        len(results["missing_mandates"])
        + len(results["iban_mismatches"])
        + len(results["name_mismatches"])
        + len(results["errors"])
    )

    if significant_issues > 0:
        # Check for company IBAN/account settings
        company_settings_warning = _check_company_sepa_settings()

        # Create an Error Log entry for manual review
        log_message = f"""SEPA Mandate Discrepancy Check Results:

Total Members Checked: {results['total_checked']}
Auto-Fixed Issues: {len(results['auto_fixed'])}
{company_settings_warning}
MANUAL REVIEW NEEDED:
- Missing Mandates: {len(results['missing_mandates'])}
- IBAN Mismatches: {len(results['iban_mismatches'])}
- Name Mismatches: {len(results['name_mismatches'])}
- Processing Errors: {len(results['errors'])}

Missing Mandates:
{_format_issue_list(results['missing_mandates'], ['member', 'member_name', 'iban'])}

IBAN Mismatches:
{_format_issue_list(results['iban_mismatches'], ['member', 'member_name', 'mandate_id', 'mandate_iban', 'current_iban'])}

Name Mismatches:
{_format_issue_list(results['name_mismatches'], ['member', 'member_name', 'mandate_id', 'mandate_name', 'current_name'])}

Errors:
{_format_issue_list(results['errors'], ['member', 'error', 'action'])}
"""

        frappe.log_error(log_message, "SEPA Mandate Discrepancies - Manual Review Required")


def _check_company_sepa_settings():
    """Check if company SEPA settings are configured"""
    try:
        # SEPA settings are now in Verenigingen Payments Settings
        payments_settings = get_payments_settings()
        general_settings = frappe.get_single("Verenigingen Settings")
        missing_settings = []

        # Check required SEPA settings (from Payments Settings)
        if not getattr(payments_settings, "company_iban", None):
            missing_settings.append("Company IBAN")
        if not getattr(payments_settings, "company_account_holder", None):
            missing_settings.append("Bank Account Holder Name")
        if not getattr(payments_settings, "creditor_id", None):
            missing_settings.append("SEPA Creditor ID (Incassant ID)")
        if not getattr(general_settings, "company_name", None):
            missing_settings.append("Company Name")
        # BIC is optional as it can be derived from IBAN

        if missing_settings:
            settings_list = "\n".join(f"- {setting}" for setting in missing_settings)
            return f"""
⚠️ WARNING: Missing Company SEPA Settings!
The following settings are required for SEPA processing but are not configured:
{settings_list}

Please configure these in Verenigingen Payments Settings before processing SEPA mandates.
Without these settings, direct debit batches cannot be created.
Note: BIC/SWIFT is optional as it can be automatically derived from Dutch IBANs.
"""
        return ""
    except Exception as e:
        return f"\n⚠️ WARNING: Could not check company SEPA settings: {str(e)}\n"


def _format_issue_list(issues, fields):
    """Format a list of issues for logging"""
    if not issues:
        return "None"

    formatted = []
    for issue in issues[:10]:  # Limit to first 10 to avoid huge logs
        formatted.append(" | ".join([f"{field}: {issue.get(field, 'N/A')}" for field in fields]))

    if len(issues) > 10:
        formatted.append(f"... and {len(issues) - 10} more")

    return "\n".join(formatted)


# Service Layer Integration Methods - Phase 3.3
# These methods provide integration between existing mixins and the new service layer


def create_sepa_mandate_via_service(self, iban: str, bic: str = None) -> Dict[str, Any]:
    """
    Service layer integration method for SEPA mandate creation.

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.create_mandate` instead.

    Args:
        iban: International Bank Account Number
        bic: Bank Identifier Code (optional)

    Returns:
        Dict containing mandate creation result
    """
    import warnings

    from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager

    warnings.warn(
        "create_sepa_mandate_via_service() is deprecated. Use SEPAMandateManager.create_mandate() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Delegate to SEPAMandateManager service
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
        # Return legacy format for backward compatibility
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


# Add service layer integration to SEPAMandateMixin class
SEPAMandateMixin.create_sepa_mandate_via_service = create_sepa_mandate_via_service
