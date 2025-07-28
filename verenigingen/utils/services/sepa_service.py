"""
SEPA Service Layer
Phase 3.3: Evolutionary Architecture Improvements

Provides centralized SEPA operations that work alongside existing Member mixins.
This service layer gradually replaces complex mixin methods while maintaining
backward compatibility.
"""

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import frappe


class SEPAService:
    """
    Service layer for SEPA operations - works alongside existing mixins

    This service provides enhanced SEPA functionality while maintaining
    compatibility with existing Member mixin patterns.
    """

    @staticmethod
    def create_mandate_enhanced(
        member_name: str, iban: str, bic: str = None, validate_member: bool = True
    ) -> Dict[str, Any]:
        """
        Enhanced SEPA mandate creation with better error handling

        Args:
            member_name: Name of the member document
            iban: International Bank Account Number
            bic: Bank Identifier Code (optional, auto-derived for Dutch banks)
            validate_member: Whether to validate member exists and is active

        Returns:
            Dict containing mandate information and creation status
        """
        try:
            # Enhanced input validation
            if not SEPAService.validate_inputs(member_name, iban):
                raise ValueError("Invalid input parameters")

            # Validate IBAN format and country
            if not SEPAService.validate_iban(iban):
                raise ValueError(f"Invalid IBAN format: {iban}")

            # Auto-derive BIC for Dutch IBANs if not provided
            if not bic and iban.startswith("NL"):
                bic = SEPAService.derive_bic_from_iban(iban)

            # Validate member if requested
            if validate_member:
                member_doc = frappe.get_doc("Member", member_name)
                if member_doc.status != "Active":
                    raise ValueError(f"Member {member_name} is not active")
            else:
                member_doc = frappe.get_doc("Member", member_name)

            # Check for existing active mandate with same IBAN
            existing_mandate = SEPAService.get_active_mandate_by_iban(member_name, iban)
            if existing_mandate:
                return {
                    "success": False,
                    "message": f"Active mandate already exists for IBAN {iban}",
                    "existing_mandate": existing_mandate,
                    "action": "skipped",
                }

            # Use existing mixin method but add service layer benefits
            mandate_result = member_doc.create_sepa_mandate_via_service(iban, bic)

            # Enhanced logging and audit trail
            frappe.log_action(
                "SEPA Mandate Created",
                {
                    "member": member_name,
                    "iban": iban[-4:],  # Log only last 4 digits for privacy
                    "bic": bic,
                    "service_layer": True,
                    "timestamp": datetime.now().isoformat(),
                },
            )

            return {
                "success": True,
                "mandate": mandate_result,
                "message": f"SEPA mandate created successfully for {member_name}",
                "action": "created",
            }

        except Exception as e:
            # Enhanced error logging
            frappe.log_error(
                title="SEPA Mandate Creation Failed",
                message=f"Member: {member_name}, IBAN: {iban[-4:] if iban else 'N/A'}, Error: {str(e)}",
            )

            return {
                "success": False,
                "message": f"SEPA mandate creation failed: {str(e)}",
                "action": "failed",
            }

    @staticmethod
    def validate_inputs(member_name: str, iban: str) -> bool:
        """Validate input parameters for security and format"""
        if not isinstance(member_name, str) or len(member_name) == 0:
            return False

        if not isinstance(iban, str) or len(iban) < 15:
            return False

        # Check for potential injection patterns
        if any(char in member_name for char in ["<", ">", '"', "'", ";"]):
            return False

        return True

    @staticmethod
    def validate_iban(iban: str) -> bool:
        """
        Enhanced IBAN validation using MOD-97 algorithm

        Supports real IBANs and mock bank IBANs for testing.
        """
        if not iban or len(iban) < 15:
            return False

        # Remove spaces and convert to uppercase
        iban = iban.replace(" ", "").upper()

        # Check basic format (2 letters + 2 digits + up to 30 alphanumeric)
        if not re.match(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$", iban):
            return False

        # For Dutch IBANs, validate length (18 characters)
        if iban.startswith("NL") and len(iban) != 18:
            return False

        # Check for mock banks (TEST, MOCK, DEMO) - valid for testing
        if any(bank in iban for bank in ["TEST", "MOCK", "DEMO"]):
            return SEPAService._validate_mock_iban(iban)

        # MOD-97 validation for real IBANs
        return SEPAService._validate_iban_mod97(iban)

    @staticmethod
    def _validate_mock_iban(iban: str) -> bool:
        """Validate mock bank IBANs for testing"""
        # Mock banks: NLXXTEST0123456789, NLXXMOCK0123456789, NLXXDEMO0123456789
        if len(iban) != 18 or not iban.startswith("NL"):
            return False

        # Extract bank code and account number
        bank_code = iban[4:8]
        if bank_code not in ["TEST", "MOCK", "DEMO"]:
            return False

        # Check account number format (10 digits)
        account_number = iban[8:]
        if not account_number.isdigit() or len(account_number) != 10:
            return False

        return True

    @staticmethod
    def _validate_iban_mod97(iban: str) -> bool:
        """Validate IBAN using MOD-97 algorithm"""
        try:
            # Move first 4 characters to end
            rearranged = iban[4:] + iban[:4]

            # Replace letters with numbers (A=10, B=11, ..., Z=35)
            numeric = ""
            for char in rearranged:
                if char.isalpha():
                    numeric += str(ord(char) - ord("A") + 10)
                else:
                    numeric += char

            # Check MOD 97
            return int(numeric) % 97 == 1
        except (ValueError, OverflowError):
            return False

    @staticmethod
    def derive_bic_from_iban(iban: str) -> str:
        """
        Derive BIC from Dutch IBAN

        For real banks, this would use a lookup table.
        For mock banks, generate appropriate test BICs.
        """
        if not iban or len(iban) < 8:
            return ""

        # Extract bank code (positions 4-7)
        bank_code = iban[4:8]

        # Mock bank BIC mapping
        mock_bic_map = {"TEST": "TESTNL2A", "MOCK": "MOCKNL2A", "DEMO": "DEMONL2A"}

        if bank_code in mock_bic_map:
            return mock_bic_map[bank_code]

        # For real Dutch banks, you would have a comprehensive lookup table
        # This is a simplified example
        real_bank_mapping = {
            "ABNA": "ABNANL2A",  # ABN AMRO
            "RABO": "RABONL2U",  # Rabobank
            "INGB": "INGBNL2A",  # ING Bank
            "TRIO": "TRIONL2U",  # Triodos Bank
        }

        return real_bank_mapping.get(bank_code, f"{bank_code}NL2X")

    @staticmethod
    def get_active_mandates(member_name: str) -> List[Dict[str, Any]]:
        """
        Get all active SEPA mandates for a member

        Args:
            member_name: Name of the member document

        Returns:
            List of active SEPA mandates
        """
        try:
            mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": member_name, "status": "Active"},
                fields=[
                    "name",
                    "iban",
                    "bic",
                    "mandate_id",
                    "sign_date",
                    "first_collection_date",
                    "expiry_date",
                ],
                order_by="sign_date desc",
            )

            return mandates

        except Exception as e:
            frappe.log_error(f"Failed to get active mandates for {member_name}: {e}")
            return []

    @staticmethod
    def get_active_mandate_by_iban(member_name: str, iban: str) -> Optional[Dict[str, Any]]:
        """Check if active mandate exists for specific IBAN"""
        try:
            mandate = frappe.get_value(
                "SEPA Mandate",
                {"member": member_name, "iban": iban, "status": "Active"},
                ["name", "mandate_id", "created_date", "usage_count"],
                as_dict=True,
            )

            return mandate

        except Exception as e:
            frappe.log_error(f"Failed to check mandate for {member_name} IBAN {iban}: {e}")
            return None

    @staticmethod
    def cancel_mandate(mandate_name: str, reason: str = "Cancelled by service") -> Dict[str, Any]:
        """
        Cancel a SEPA mandate safely

        Args:
            mandate_name: Name of the SEPA Mandate document
            reason: Reason for cancellation

        Returns:
            Result of cancellation operation
        """
        try:
            mandate_doc = frappe.get_doc("SEPA Mandate", mandate_name)

            if mandate_doc.status != "Active":
                return {
                    "success": False,
                    "message": f"Mandate {mandate_name} is not active (status: {mandate_doc.status})",
                }

            # Update mandate status
            mandate_doc.status = "Cancelled"
            mandate_doc.cancelled_date = date.today()
            mandate_doc.cancellation_reason = reason
            mandate_doc.save()

            # Log the cancellation
            frappe.log_action(
                "SEPA Mandate Cancelled",
                {
                    "mandate": mandate_name,
                    "member": mandate_doc.member,
                    "reason": reason,
                    "service_layer": True,
                    "timestamp": datetime.now().isoformat(),
                },
            )

            return {
                "success": True,
                "message": f"SEPA mandate {mandate_name} cancelled successfully",
                "mandate": mandate_doc.name,
            }

        except Exception as e:
            frappe.log_error(f"Failed to cancel mandate {mandate_name}: {e}")
            return {"success": False, "message": f"Failed to cancel mandate: {str(e)}"}

    @staticmethod
    def get_mandate_usage_statistics(member_name: str) -> Dict[str, Any]:
        """
        Get SEPA mandate usage statistics for a member

        Args:
            member_name: Name of the member document

        Returns:
            Statistics about mandate usage
        """
        try:
            # Get mandate statistics using secure parameterized query
            stats = frappe.db.sql(
                """
                SELECT
                    COUNT(*) as total_mandates,
                    SUM(CASE WHEN status = 'Active' THEN 1 ELSE 0 END) as active_mandates,
                    SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) as cancelled_mandates,
                    SUM(usage_count) as total_usage,
                    AVG(usage_count) as avg_usage,
                    MAX(created_date) as latest_mandate_date
                FROM `tabSEPA Mandate`
                WHERE member = %s
            """,
                (member_name,),
                as_dict=True,
            )

            if stats:
                return {"success": True, "statistics": stats[0]}
            else:
                return {
                    "success": True,
                    "statistics": {
                        "total_mandates": 0,
                        "active_mandates": 0,
                        "cancelled_mandates": 0,
                        "total_usage": 0,
                        "avg_usage": 0,
                        "latest_mandate_date": None,
                    },
                }

        except Exception as e:
            frappe.log_error(f"Failed to get mandate statistics for {member_name}: {e}")
            return {"success": False, "message": f"Failed to get statistics: {str(e)}"}


# Utility functions for service layer integration


def get_sepa_service() -> SEPAService:
    """Factory function to get SEPA service instance"""
    return SEPAService()


@frappe.whitelist()
def create_sepa_mandate_via_service(member_name: str, iban: str, bic: str = None) -> Dict[str, Any]:
    """
    API endpoint for creating SEPA mandates via service layer

    This provides a direct API interface to the service layer functionality.
    """
    service = get_sepa_service()
    return service.create_mandate_enhanced(member_name, iban, bic)


@frappe.whitelist()
def get_member_mandates_via_service(member_name: str) -> List[Dict[str, Any]]:
    """API endpoint for getting member mandates via service layer"""
    service = get_sepa_service()
    return service.get_active_mandates(member_name)


@frappe.whitelist()
def cancel_mandate_via_service(mandate_name: str, reason: str = "Cancelled via API") -> Dict[str, Any]:
    """API endpoint for cancelling mandates via service layer"""
    service = get_sepa_service()
    return service.cancel_mandate(mandate_name, reason)
