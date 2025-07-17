import frappe
from frappe.utils import today


class SEPAMandateMixin:
    """Mixin for SEPA mandate-related functionality"""

    def get_active_sepa_mandates(self):
        """Get all active SEPA mandates for this member"""
        return frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.name, "status": "Active", "is_active": 1},
            fields=[
                "name",
                "mandate_id",
                "status",
                "expiry_date",
                "used_for_memberships",
                "used_for_donations",
            ],
        )

    def get_default_sepa_mandate(self):
        """Get the default SEPA mandate for this member"""
        for link in self.sepa_mandates:
            if link.is_current and link.sepa_mandate:
                try:
                    mandate = frappe.get_doc("SEPA Mandate", link.sepa_mandate)
                    if mandate.status == "Active" and mandate.is_active:
                        return mandate
                except frappe.DoesNotExistError:
                    continue

        active_mandates = self.get_active_sepa_mandates()
        if active_mandates:
            for link in self.sepa_mandates:
                if link.sepa_mandate == active_mandates[0].name:
                    link.is_current = 1
                    break

            return frappe.get_doc("SEPA Mandate", active_mandates[0].name)

        return None

    def has_active_sepa_mandate(self, purpose="memberships"):
        """Check if member has an active SEPA mandate for a specific purpose"""
        filters = {"member": self.name, "status": "Active", "is_active": 1}

        if purpose == "memberships":
            filters["used_for_memberships"] = 1
        elif purpose == "donations":
            filters["used_for_donations"] = 1

        return frappe.db.exists("SEPA Mandate", filters)

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

            # Save the updated member document
            self.save(ignore_permissions=True)

            return {
                "success": True,
                "message": f"Refreshed {len(mandates)} SEPA mandate(s)",
                "mandates_count": len(mandates),
            }

        except Exception as e:
            frappe.log_error(f"Error refreshing SEPA mandates for member {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}

    @frappe.whitelist()
    def create_sepa_mandate(self):
        """Create a new SEPA mandate for this member with enhanced prefilling"""
        mandate_ref_result = self._generate_mandate_reference()
        suggested_reference = mandate_ref_result.get(
            "mandate_reference", f"M-{self.member_id}-{today().replace('-', '')}"
        )

        mandate = frappe.new_doc("SEPA Mandate")
        mandate.member = self.name
        mandate.member_name = self.full_name
        mandate.mandate_id = suggested_reference
        mandate.account_holder_name = self.bank_account_name or self.full_name
        mandate.sign_date = today()

        if hasattr(self, "iban") and self.iban:
            mandate.iban = self.iban
        if hasattr(self, "bic") and self.bic:
            mandate.bic = self.bic

        mandate.used_for_memberships = 1
        mandate.used_for_donations = 0
        mandate.mandate_type = "RCUR"

        mandate.notes = f"Created from Member {self.name} on {today()}"

        mandate.insert()

        self.append(
            "sepa_mandates",
            {
                "sepa_mandate": mandate.name,
                "mandate_reference": mandate.mandate_id,
                "is_current": 0,
                "status": "Draft",
                "valid_from": mandate.sign_date,
            },
        )

        self.save()

        return mandate.name

    def _generate_mandate_reference(self):
        """Generate a suggested mandate reference for a member"""
        member_id = self.member_id or self.name.replace("Assoc-Member-", "").replace("-", "")

        from datetime import datetime

        now_dt = datetime.now()
        date_str = now_dt.strftime("%Y%m%d")

        existing_mandates_today = frappe.get_all(
            "SEPA Mandate",
            filters={
                "mandate_id": ["like", f"M-{member_id}-{date_str}-%"],
                "creation": [">=", now_dt.strftime("%Y-%m-%d 00:00:00")],
            },
            fields=["mandate_id"],
        )

        sequence = len(existing_mandates_today) + 1
        sequence_str = str(sequence).zfill(3)

        suggested_reference = f"M-{member_id}-{date_str}-{sequence_str}"

        return {"mandate_reference": suggested_reference}


@frappe.whitelist()
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
    mandate.cancellation_date = today()
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
        _check_company_sepa_settings()

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
        settings = frappe.get_single("Verenigingen Settings")
        missing_settings = []

        # Check required SEPA settings
        if not getattr(settings, "company_iban", None):
            missing_settings.append("Company IBAN")
        if not getattr(settings, "company_account_holder", None):
            missing_settings.append("Bank Account Holder Name")
        if not getattr(settings, "creditor_id", None):
            missing_settings.append("SEPA Creditor ID (Incassant ID)")
        if not getattr(settings, "company_name", None):
            missing_settings.append("Company Name")
        # BIC is optional as it can be derived from IBAN

        if missing_settings:
            # settings_list = "\n".join(f"- {setting}" for setting in missing_settings)
            return """
⚠️ WARNING: Missing Company SEPA Settings!
The following settings are required for SEPA processing but are not configured:
{settings_list}

Please configure these in Verenigingen Settings before processing SEPA mandates.
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
