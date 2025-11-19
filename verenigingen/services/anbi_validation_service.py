"""
ANBI Validation Service

Unified validation logic for ANBI (Algemeen Nut Beogende Instelling) periodic donation
tax benefits according to Dutch tax law.

Dutch Tax Law Context
---------------------
ANBI (Algemeen Nut Beogende Instelling) status allows donors to deduct 100% of periodic
donations from taxable income without annual limits. This requires:

- Organization registered as ANBI with Belastingdienst (Dutch Tax Authority)
- Minimum 5-year or lifetime commitment from donor
- Formal documentation (notarial deed or private written agreement)
- Donor tax identifier (BSN for individuals, RSIN for organizations)
- Explicit donor consent for tax reporting

This service consolidates ~250 lines of validation logic previously duplicated across
Donation and Periodic Donation Agreement controllers.

Usage Examples
--------------
Basic validation::

    from verenigingen.services.anbi_validation_service import ANBIValidationService

    validator = ANBIValidationService()
    is_valid, errors = validator.validate_full_anbi_eligibility(
        donor_name="DONOR-001",
        duration_years=5,
        agreement_type="Notarial"
    )

    if not is_valid:
        frappe.throw(errors[0])  # Show first error

Individual validation checks::

    # Check if ANBI enabled
    is_valid, error = validator.validate_system_anbi_enabled()

    # Check donor consent
    donor = frappe.get_doc("Donor", donor_name)
    is_valid, error = validator.validate_donor_consent(donor)

    # Check if amount should be reported
    should_report = validator.should_mark_reportable(amount=750.00)

Integration in DocType controllers::

    class PeriodicDonationAgreement(Document):
        def validate(self):
            if self.anbi_eligible:
                validator = ANBIValidationService()
                is_valid, errors = validator.validate_full_anbi_eligibility(
                    donor_name=self.donor,
                    duration_years=self.get_agreement_duration(),
                    agreement_type=self.agreement_type
                )
                if not is_valid:
                    frappe.throw(errors[0])

References
----------
- Dutch Tax Law: https://wetten.overheid.nl/BWBR0002320/2023-01-01
- ANBI Requirements: https://www.belastingdienst.nl/wps/wcm/connect/nl/aftrek-en-kortingen/content/anbi

See Also
--------
- :class:`verenigingen.verenigingen.doctype.periodic_donation_agreement.periodic_donation_agreement.PeriodicDonationAgreement`
- :class:`verenigingen.verenigingen.doctype.donation.donation.Donation`
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _


class ANBIValidationService:
    """Service for ANBI eligibility validation"""

    def _load_settings(self) -> Dict[str, Any]:
        """
        Load ANBI-related settings from Verenigingen Settings.

        Note: No caching - settings are loaded fresh each time to ensure
        current ANBI registration status is always checked. Frappe's internal
        singles cache provides sufficient performance.

        Note: We use 'enable_anbi_functionality' for both system enable check
        and organization ANBI status. If the feature is enabled, it implies
        the organization has valid ANBI registration.
        """
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")

        return {
            "anbi_enabled": anbi_enabled,
            "org_has_anbi": anbi_enabled,  # Same field - feature enabled implies org has ANBI status
            "min_reportable_amount": frappe.db.get_single_value(
                "Verenigingen Settings", "anbi_minimum_reportable_amount"
            )
            or 500,
        }

    @property
    def settings(self) -> Dict[str, Any]:
        """Get current ANBI settings"""
        return self._load_settings()

    def validate_system_anbi_enabled(self) -> Tuple[bool, Optional[str]]:
        """
        Validate that ANBI functionality is enabled in system settings.

        Returns:
            (is_valid, error_message) tuple
        """
        anbi_enabled = self.settings.get("anbi_enabled")

        if anbi_enabled is None:
            return (
                False,
                "ANBI functionality is not configured in system settings. Please contact administrator to configure ANBI settings.",
            )

        if not anbi_enabled:
            return (False, "ANBI functionality is disabled in system settings. Please contact administrator.")

        return (True, None)

    def validate_organization_anbi_status(self) -> Tuple[bool, Optional[str]]:
        """
        Validate that organization has valid ANBI registration.

        Returns:
            (is_valid, error_message) tuple
        """
        org_anbi_status = self.settings.get("org_has_anbi")

        if org_anbi_status is None:
            return (
                False,
                "Organization ANBI status is not configured in system settings. Please contact administrator to configure ANBI registration status.",
            )

        if not org_anbi_status:
            return (
                False,
                "Organization does not have valid ANBI registration. ANBI tax benefits cannot be offered.",
            )

        return (True, None)

    def validate_donor_consent(self, donor_doc: Any, strict: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Validate that donor has provided ANBI consent.

        Args:
            donor_doc: Donor document to validate
            strict: If False (default), returns warning instead of error

        Returns:
            (is_valid, error_message) tuple
        """
        if not getattr(donor_doc, "anbi_consent", False):
            if strict:
                return (
                    False,
                    "Donor must provide ANBI consent before creating ANBI-eligible agreement. Please update donor record first.",
                )
            # Return True but with informational message
            return (
                True,
                None,  # Don't block - consent can be obtained later
            )

        return (True, None)

    def validate_donor_tax_identifier(self, donor_doc: Any) -> Tuple[bool, Optional[str]]:
        """
        Validate that donor has required tax identifier (BSN or RSIN).

        Args:
            donor_doc: Donor document to validate

        Returns:
            (is_valid, error_message) tuple
        """
        donor_type = getattr(donor_doc, "donor_type", None)

        if donor_type == "Individual":
            if not getattr(donor_doc, "bsn_citizen_service_number", None):
                return (
                    False,
                    "Individual donors require valid BSN (Citizen Service Number) for ANBI agreements",
                )
        elif donor_type == "Organization":
            if not getattr(donor_doc, "rsin_organization_tax_number", None):
                return (
                    False,
                    "Organization donors require valid RSIN (Organization Tax Number) for ANBI agreements",
                )
        else:
            return (False, "Donor type must be 'Individual' or 'Organization' for ANBI agreements")

        return (True, None)

    def validate_agreement_duration(self, duration_years: float) -> Tuple[bool, Optional[str]]:
        """
        Validate that agreement duration meets ANBI minimum (5 years or lifetime).

        Args:
            duration_years: Duration in years (-1 for lifetime)

        Returns:
            (is_valid, error_message) tuple
        """
        if duration_years != -1 and duration_years < 5:
            return (
                False,
                "ANBI periodic donation agreements require minimum 5-year commitment or lifetime agreement",
            )

        return (True, None)

    def validate_agreement_type(self, agreement_type: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        Validate that agreement type supports ANBI (requires formal documentation).

        Args:
            agreement_type: Type of agreement

        Returns:
            (is_valid, error_message) tuple
        """
        if agreement_type and agreement_type not in ["Notarial", "Private Written"]:
            return (False, "ANBI agreements require formal documentation (Notarial or Private Written)")

        return (True, None)

    def check_duplicate_agreements(
        self, donor_name: str, current_agreement_name: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check for duplicate active ANBI agreements for a donor.

        Args:
            donor_name: Donor to check
            current_agreement_name: Name of current agreement to exclude from check

        Returns:
            (is_valid, error_message) tuple
        """
        filters = {
            "donor": donor_name,
            "anbi_eligible": 1,
            "status": ["in", ["Active", "Draft"]],
        }

        if current_agreement_name:
            filters["name"] = ["!=", current_agreement_name]

        existing_agreements = frappe.get_all(
            "Periodic Donation Agreement", filters=filters, fields=["name", "status"]
        )

        if existing_agreements:
            active_agreements = [ag.name for ag in existing_agreements if ag.status == "Active"]
            if active_agreements:
                return (
                    False,
                    f"Donor already has active ANBI agreement: {', '.join(active_agreements)}. Only one active ANBI agreement per donor is allowed.",
                )

        return (True, None)

    def validate_full_anbi_eligibility(
        self,
        donor_name: str,
        duration_years: float,
        agreement_type: Optional[str] = None,
        current_agreement_name: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Perform complete ANBI eligibility validation.

        This is the main validation method that runs all checks in sequence.

        Args:
            donor_name: Donor making the agreement
            duration_years: Agreement duration in years (-1 for lifetime)
            agreement_type: Type of agreement (optional)
            current_agreement_name: Name of current agreement (for updates)

        Returns:
            (is_valid, list_of_errors) tuple
        """
        errors = []

        # 1. Check system ANBI enabled
        is_valid, error = self.validate_system_anbi_enabled()
        if not is_valid:
            errors.append(error)
            return (False, errors)  # Fatal error, stop validation

        # 2. Check organization ANBI status
        is_valid, error = self.validate_organization_anbi_status()
        if not is_valid:
            errors.append(error)
            return (False, errors)  # Fatal error, stop validation

        # 3. Validate donor exists
        if not donor_name or not frappe.db.exists("Donor", donor_name):
            errors.append("Donor is required for ANBI agreements")
            return (False, errors)

        try:
            donor_doc = frappe.get_doc("Donor", donor_name)
        except frappe.DoesNotExistError:
            errors.append(
                f"Donor record '{donor_name}' not found. Please ensure donor exists before creating agreement."
            )
            return (False, errors)

        # 4. Validate donor consent
        is_valid, error = self.validate_donor_consent(donor_doc)
        if not is_valid:
            errors.append(error)

        # 5. Validate tax identifier
        is_valid, error = self.validate_donor_tax_identifier(donor_doc)
        if not is_valid:
            errors.append(error)

        # 6. Validate duration
        is_valid, error = self.validate_agreement_duration(duration_years)
        if not is_valid:
            errors.append(error)

        # 7. Validate agreement type
        is_valid, error = self.validate_agreement_type(agreement_type)
        if not is_valid:
            errors.append(error)

        # 8. Check for duplicates
        is_valid, error = self.check_duplicate_agreements(donor_name, current_agreement_name)
        if not is_valid:
            errors.append(error)

        return (len(errors) == 0, errors)

    def should_mark_reportable(self, amount: float) -> bool:
        """
        Determine if donation should be marked as reportable to Belastingdienst.

        Args:
            amount: Donation amount

        Returns:
            True if should be marked reportable
        """
        min_amount = self.settings.get("min_reportable_amount", 500)
        return amount >= min_amount

    def get_validation_status_dict(
        self, donor_name: str, duration_years: float, agreement_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive validation status as dictionary (for UI/diagnostics).

        Args:
            donor_name: Donor to validate
            duration_years: Agreement duration
            agreement_type: Type of agreement

        Returns:
            Dictionary with validation status and detailed errors/warnings
        """
        is_valid, errors = self.validate_full_anbi_eligibility(donor_name, duration_years, agreement_type)

        return {
            "valid": is_valid,
            "errors": errors,
            "warnings": [],
            "message": "ANBI validation passed" if is_valid else f"{len(errors)} validation errors found",
        }
