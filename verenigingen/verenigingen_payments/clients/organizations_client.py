"""
Mollie Organizations API Client
Client for managing organization account information
"""

from typing import Dict, Optional

import frappe
from frappe import _

from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.models.organization import Organization
from ..core.mollie_base_client import MollieBaseClient


class OrganizationsClient(MollieBaseClient):
    """
    Client for Mollie Organizations API

    Provides:
    - Organization profile retrieval
    - Account information management
    - VAT details access
    """

    def get_current_organization(self) -> Organization:
        """
        Get the current organization details

        Returns:
            Organization object
        """
        self.audit_trail.log_event(
            AuditEventType.CONFIGURATION_CHANGED,
            AuditSeverity.INFO,
            "Retrieving current organization details",
        )

        response = self.get("organizations/me")
        return Organization(response)

    def get_organization(self, organization_id: str) -> Organization:
        """
        Get a specific organization

        Args:
            organization_id: Organization identifier

        Returns:
            Organization object
        """
        self.audit_trail.log_event(
            AuditEventType.CONFIGURATION_CHANGED,
            AuditSeverity.INFO,
            f"Retrieving organization: {organization_id}",
        )

        response = self.get(f"organizations/{organization_id}")
        return Organization(response)

    def get_organization_info(self) -> Dict:
        """
        Get comprehensive organization information

        Returns:
            Dict with organization details
        """
        org = self.get_current_organization()

        info = {
            "id": org.id,
            "name": org.name,
            "email": org.email,
            "locale": org.locale,
            "has_vat": org.has_vat_number(),
            "vat_number": org.vat_number,
            "vat_regulation": org.vat_regulation,
            "registration_number": org.registration_number,
            "display_name": org.get_display_name(),
        }

        # Add address if available
        if org.address:
            info["address"] = {
                "street": org.address.street_and_number,
                "postal_code": org.address.postal_code,
                "city": org.address.city,
                "country": org.address.country,
                "full": org.address.get_full_address(),
            }

        return info

    def verify_organization_status(self) -> Dict:
        """
        Verify organization account status and compliance

        Returns:
            Dict with verification results
        """
        org = self.get_current_organization()

        verification = {
            "organization_id": org.id,
            "name": org.name,
            "verified": True,
            "issues": [],
            "warnings": [],
        }

        # Check required fields
        if not org.email:
            verification["issues"].append("Email address missing")
            verification["verified"] = False

        if not org.address:
            verification["warnings"].append("Address information incomplete")

        # Check VAT configuration for businesses
        if org.vat_regulation and not org.has_vat_number():
            verification["warnings"].append("VAT number not configured")

        # Log verification
        severity = AuditSeverity.INFO if verification["verified"] else AuditSeverity.WARNING
        self.audit_trail.log_event(
            AuditEventType.CONFIGURATION_CHANGED,
            severity,
            f"Organization verification {'passed' if verification['verified'] else 'failed'}",
            details=verification,
        )

        return verification

    def sync_organization_to_frappe(self) -> Dict:
        """
        Sync organization details to Frappe system

        Returns:
            Dict with sync results
        """
        org = self.get_current_organization()

        sync_result = {"organization_id": org.id, "synced_fields": [], "status": "success"}

        try:
            # Update or create Company record
            company_name = org.name or "Default Company"

            if frappe.db.exists("Company", company_name):
                company = frappe.get_doc("Company", company_name)
            else:
                company = frappe.new_doc("Company")
                company.company_name = company_name

            # Update fields
            if org.email:
                company.email = org.email
                sync_result["synced_fields"].append("email")

            if org.vat_number:
                company.tax_id = org.vat_number
                sync_result["synced_fields"].append("vat_number")

            if org.address:
                if org.address.street_and_number:
                    company.address_line1 = org.address.street_and_number
                    sync_result["synced_fields"].append("street")

                if org.address.city:
                    company.city = org.address.city
                    sync_result["synced_fields"].append("city")

                if org.address.postal_code:
                    company.postal_code = org.address.postal_code
                    sync_result["synced_fields"].append("postal_code")

                if org.address.country:
                    company.country = org.address.country
                    sync_result["synced_fields"].append("country")

            company.save()
            frappe.db.commit()

            sync_result["company_name"] = company_name

            # Log successful sync
            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.INFO,
                f"Organization synced to Frappe: {company_name}",
                details=sync_result,
            )

        except Exception as e:
            sync_result["status"] = "failed"
            sync_result["error"] = str(e)

            # Log error
            self.audit_trail.log_event(
                AuditEventType.ERROR_OCCURRED,
                AuditSeverity.ERROR,
                f"Organization sync failed: {str(e)}",
                details=sync_result,
            )

            frappe.log_error(f"Organization sync error: {str(e)}", "Mollie Organization Sync")

        return sync_result
