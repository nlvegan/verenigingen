"""
SEPA Service Layer
Phase 3.3: Evolutionary Architecture Improvements

Provides centralized SEPA operations that work alongside existing Member mixins.
This service layer gradually replaces complex mixin methods while maintaining
backward compatibility.

ERROR HANDLING PATTERN: Dict-Based Result Pattern
==================================================
All methods return: {"success": bool, "error": str, ...additional data...}

Rationale: Utility service called from multiple contexts (UI, API, batch jobs)
requiring different error handling strategies. Dict pattern allows callers to:
- Handle errors gracefully without aborting
- Collect errors in batch operations
- Customize error presentation per context

See: docs/patterns/ERROR_HANDLING_PATTERNS.md
"""

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


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
        Derive BIC from IBAN - delegates to iban_validator for comprehensive bank database

        Uses the most comprehensive BIC database available (22+ Dutch banks).
        Consolidated from multiple implementations across the codebase.
        """
        from verenigingen.utils.validation.iban_validator import derive_bic_from_iban as validator_derive_bic

        bic = validator_derive_bic(iban)
        return bic if bic else ""

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
    def validate_mandate_creation(member: str, iban: str, mandate_id: str) -> Dict[str, Any]:
        """
        Validate mandate creation parameters and check for existing mandates

        Consolidated from member.py and member_utils.py implementations.

        Args:
            member: Member document name
            iban: IBAN to validate
            mandate_id: Mandate ID to check for uniqueness

        Returns:
            dict: Validation result with valid/error/warning keys
        """
        try:
            # Check if member exists
            if not frappe.db.exists("Member", member):
                return {"error": frappe._("Member does not exist")}

            # Check if mandate ID already exists
            existing_mandate = frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id})
            if existing_mandate:
                return {"error": frappe._("Mandate ID {0} already exists").format(mandate_id)}

            # Check for existing active mandates for this member
            existing_mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": member, "status": "Active", "is_active": 1},
                fields=["name", "mandate_id", "iban"],
            )

            # Check if there's an existing mandate for the same IBAN
            iban_mandate = None
            for mandate in existing_mandates:
                if mandate.iban == iban:
                    iban_mandate = mandate.mandate_id
                    break

            result = {"valid": True}

            if iban_mandate:
                result["existing_mandate"] = iban_mandate
                result["warning"] = frappe._("An active mandate already exists for this IBAN: {0}").format(
                    iban_mandate
                )

            return result

        except Exception as e:
            frappe.log_error(f"Error validating mandate creation: {str(e)}")
            return {"error": frappe._("Error validating mandate: {0}").format(str(e))}

    @staticmethod
    def deactivate_old_sepa_mandates(member: str, new_iban: str) -> Dict[str, Any]:
        """
        Deactivate old SEPA mandates when IBAN changes

        Consolidated from member.py implementation.

        Args:
            member: Member document name
            new_iban: New IBAN to keep active

        Returns:
            dict: Result with success, deactivated_count, and deactivated_mandates
        """
        try:
            from frappe.utils import today

            # Get all active mandates for this member
            active_mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": member, "status": "Active", "is_active": 1},
                fields=["name", "iban", "mandate_id", "status"],
            )

            deactivated_count = 0
            deactivated_mandates = []

            for mandate_data in active_mandates:
                # Only deactivate mandates with different IBAN
                if mandate_data.iban != new_iban:
                    mandate = frappe.get_doc("SEPA Mandate", mandate_data.name)

                    # Deactivate the mandate
                    mandate.status = "Cancelled"
                    mandate.is_active = 0
                    mandate.cancellation_date = today()
                    mandate.cancellation_reason = f"IBAN changed from {mandate.iban} to {new_iban}"

                    # Use secure_document_operation for proper audit trail
                    mandate_result = secure_document_operation(
                        operation="save",
                        doc=mandate,
                        justification=f"Deactivate SEPA mandate {mandate.mandate_id} due to IBAN change from {mandate.iban} to {new_iban}",
                        required_permissions=["SEPA Mandate:write"],
                    )

                    if not mandate_result.success:
                        frappe.log_error(
                            f"Failed to deactivate SEPA mandate {mandate.mandate_id}: {'; '.join(mandate_result.errors)}",
                            "SEPA Mandate Deactivation Security",
                        )
                        # Continue with other mandates rather than failing entirely
                        continue

                    deactivated_count += 1
                    deactivated_mandates.append({"mandate_id": mandate.mandate_id, "old_iban": mandate.iban})

                    frappe.logger().info(
                        f"Deactivated SEPA mandate {mandate.mandate_id} for member {member} due to IBAN change"
                    )

            return {
                "success": True,
                "deactivated_count": deactivated_count,
                "deactivated_mandates": deactivated_mandates,
            }

        except Exception as e:
            frappe.log_error(f"Error deactivating old SEPA mandates for member {member}: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def refresh_sepa_mandates(member: str) -> Dict[str, Any]:
        """
        Refresh the SEPA mandates child table by syncing with actual SEPA Mandate records

        Consolidated from member.py implementation. Delegates to Member method.

        Args:
            member: Member document name

        Returns:
            dict: Result with success status
        """
        try:
            member_doc = frappe.get_doc("Member", member)
            result = member_doc.refresh_sepa_mandates_table()
            return result

        except Exception as e:
            frappe.log_error(f"Error refreshing SEPA mandates for member {member}: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_active_sepa_mandate(member: str, iban: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get active SEPA mandate for a member

        Consolidated from member.py implementation.

        Args:
            member: Member document name
            iban: Optional IBAN to filter by

        Returns:
            dict: Active mandate data or None
        """
        try:
            filters = {"member": member, "status": "Active", "is_active": 1}

            if iban:
                filters["iban"] = iban

            mandates = frappe.get_all(
                "SEPA Mandate",
                filters=filters,
                fields=["name", "mandate_id", "status", "iban", "account_holder_name"],
                order_by="creation desc",
                limit=1,
            )

            return mandates[0] if mandates else None

        except Exception as e:
            frappe.log_error(f"Error getting active SEPA mandate for member {member}: {str(e)}")
            return None

    @staticmethod
    def _validate_mandate_creation_inputs(
        member: str,
        mandate_id: str,
        iban: str,
        account_holder_name: str,
        mandate_type: str = "Recurring",
        sign_date: Optional[str] = None,
        used_for_memberships: int = 1,
        used_for_donations: int = 0,
        notes: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Validate all inputs for mandate creation.

        Provides comprehensive input validation at service layer for defense-in-depth.

        Args:
            member: Member document name
            mandate_id: Unique mandate identifier
            iban: IBAN for direct debit
            account_holder_name: Name of account holder
            mandate_type: Type - "One-off" or "Recurring"
            sign_date: Date mandate was signed (optional)
            used_for_memberships: Use for membership dues (1/0)
            used_for_donations: Use for donations (1/0)
            notes: Additional notes (optional)

        Returns:
            dict: Error result if validation fails, None if all valid
        """
        from frappe.utils import getdate, today

        # Validate mandatory fields
        if not member or not member.strip():
            return {"success": False, "error": "Member is required"}

        if not mandate_id or not mandate_id.strip():
            return {"success": False, "error": "Mandate ID is required"}

        if not iban or not iban.strip():
            return {"success": False, "error": "IBAN is required for SEPA mandate creation"}

        if not account_holder_name or not account_holder_name.strip():
            return {"success": False, "error": "Account holder name is required"}

        # Validate member exists
        if not frappe.db.exists("Member", member):
            return {"success": False, "error": f"Member {member} does not exist"}

        # Validate IBAN format
        if not SEPAService.validate_iban(iban):
            return {"success": False, "error": "Invalid IBAN format"}

        # Validate mandate_type
        valid_types = ["One-off", "One-of", "Recurring", "OOFF", "RCUR"]
        if mandate_type not in valid_types:
            return {
                "success": False,
                "error": f"Invalid mandate type '{mandate_type}'. Must be one of: {', '.join(valid_types[:3])}",
            }

        # Validate sign_date if provided (SEPA allows max 10 years historical, no future dates)
        if sign_date:
            from verenigingen.utils.validation_utilities import validate_historical_date_window

            result = validate_historical_date_window(
                sign_date,
                max_years_past=10,
                max_days_future=0,
                field_name="sign_date",
                throw_on_error=False,
            )
            if not result["valid"]:
                return {"success": False, "error": result["message"]}

        # Validate at least one usage flag is set
        if not used_for_memberships and not used_for_donations:
            return {"success": False, "error": "Mandate must be used for memberships and/or donations"}

        # Validate notes length (sanity check)
        if notes and len(notes) > 1000:
            return {
                "success": False,
                "error": f"Notes field is too long ({len(notes)} characters). Maximum 1000 characters.",
            }

        # Validate mandate_id format (basic sanity check)
        if len(mandate_id) < 3:
            return {"success": False, "error": "Mandate ID must be at least 3 characters long"}

        if len(mandate_id) > 35:  # SEPA specification limit
            return {
                "success": False,
                "error": "Mandate ID must not exceed 35 characters (SEPA specification)",
            }

        return None  # All validations passed

    @staticmethod
    def _prepare_mandate_document(
        mandate_id: str,
        member: str,
        iban: str,
        bic: str,
        account_holder_name: str,
        mandate_type: str,
        sign_date: str,
        used_for_memberships: int,
        used_for_donations: int,
        notes: str,
    ):
        """
        Create and populate SEPA mandate document.

        Args:
            mandate_id: Unique mandate identifier
            member: Member document name
            iban: IBAN for direct debit
            bic: BIC code
            account_holder_name: Name of account holder
            mandate_type: Mandate type (internal format: OOFF/RCUR)
            sign_date: Date mandate was signed
            used_for_memberships: Use for membership dues
            used_for_donations: Use for donations
            notes: Additional notes

        Returns:
            Document: Prepared (not saved) SEPA Mandate document
        """
        from verenigingen.utils.boolean_utils import cbool
        from verenigingen.verenigingen_payments.utils.sepa_utilities import SEPAUtilities

        mandate = frappe.new_doc("SEPA Mandate")
        mandate.mandate_id = mandate_id
        mandate.member = member
        # Normalize IBAN to standard format (with spaces every 4 characters)
        mandate.iban = SEPAUtilities.format_iban_display(iban)
        mandate.bic = bic if bic else SEPAService.derive_bic_from_iban(iban)
        mandate.account_holder_name = account_holder_name
        mandate.mandate_type = mandate_type
        mandate.sign_date = sign_date
        mandate.used_for_memberships = cbool(used_for_memberships)
        mandate.used_for_donations = cbool(used_for_donations)
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.notes = notes

        return mandate

    @staticmethod
    def _create_mandate_with_security(mandate, mandate_id: str, member: str, iban: str) -> Dict[str, Any]:
        """
        Create SEPA mandate with security validation and audit trail.

        Args:
            mandate: Prepared SEPA Mandate document
            mandate_id: Mandate identifier (for logging)
            member: Member name (for logging)
            iban: IBAN (for logging)

        Returns:
            dict: Result with success, mandate (document), or error
        """
        mandate_result = secure_document_operation(
            operation="insert",
            doc=mandate,
            justification=f"Create new SEPA mandate {mandate_id} for member {member} with IBAN {iban[-4:]}",
            required_permissions=["SEPA Mandate:create"],
        )

        if not mandate_result.success:
            frappe.log_error(
                f"Failed to create SEPA mandate {mandate_id}: {'; '.join(mandate_result.errors)}",
                "SEPA Mandate Security",
            )
            return {
                "success": False,
                "error": mandate_result.errors[0]
                if mandate_result.errors
                else "Failed to create SEPA mandate",
            }

        # Get the created mandate from result
        mandate = mandate_result.document or frappe.get_doc("SEPA Mandate", mandate_result.doc_name)
        return {"success": True, "mandate": mandate}

    @staticmethod
    def _update_member_mandate_links(
        member_doc, mandate, mandate_id: str, sign_date: str, replace_existing: Optional[str]
    ):
        """
        Update member's SEPA mandates child table with new mandate link.

        Args:
            member_doc: Member document instance
            mandate: Created SEPA Mandate document
            mandate_id: Mandate identifier
            sign_date: Mandate sign date
            replace_existing: Mandate ID to replace (optional)
        """
        # Mark existing mandates as non-current if replacing
        if replace_existing:
            for link in member_doc.sepa_mandates:
                if link.mandate_reference == replace_existing:
                    link.is_current = 0

        # Check if this mandate is already linked to avoid duplicates
        existing_link = None
        for link in member_doc.sepa_mandates:
            if link.mandate_reference == mandate_id:
                existing_link = link
                break

        if existing_link:
            # Update existing link
            existing_link.sepa_mandate = mandate.name
            existing_link.is_current = 1
            existing_link.status = "Active"
            existing_link.valid_from = sign_date
        else:
            # Add new mandate link
            member_doc.append(
                "sepa_mandates",
                {
                    "sepa_mandate": mandate.name,
                    "mandate_reference": mandate_id,
                    "is_current": 1,
                    "status": "Active",
                    "valid_from": sign_date,
                },
            )

    @staticmethod
    def _save_member_with_security(member_doc, mandate_id: str, member: str) -> Dict[str, Any]:
        """
        Save member document with security validation and audit trail.

        Args:
            member_doc: Member document to save
            mandate_id: Mandate ID (for logging)
            member: Member name (for logging)

        Returns:
            dict: Result with success or error
        """
        member_result = secure_document_operation(
            operation="save",
            doc=member_doc,
            justification=f"Link SEPA mandate {mandate_id} to member {member} after mandate creation",
            required_permissions=["Member:write"],
        )

        if not member_result.success:
            frappe.log_error(
                f"Failed to link SEPA mandate to member {member}: {'; '.join(member_result.errors)}",
                "Member SEPA Link Security",
            )
            return {
                "success": False,
                "error": member_result.errors[0]
                if member_result.errors
                else "Failed to link mandate to member",
            }

        return {"success": True}

    @staticmethod
    def create_and_link_mandate_enhanced(
        member: str,
        mandate_id: str,
        iban: str,
        bic: str = "",
        account_holder_name: str = "",
        mandate_type: str = "Recurring",
        sign_date: Optional[str] = None,
        used_for_memberships: int = 1,
        used_for_donations: int = 0,
        notes: str = "",
        replace_existing: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new SEPA mandate and link it to the member.

        This is the main orchestration method that coordinates all mandate creation steps.

        Args:
            member: Member document name
            mandate_id: Unique mandate identifier
            iban: IBAN for direct debit
            bic: BIC code (optional)
            account_holder_name: Name of account holder
            mandate_type: Type - "One-off" or "Recurring"
            sign_date: Date mandate was signed (optional)
            used_for_memberships: Use for membership dues (1/0)
            used_for_donations: Use for donations (1/0)
            notes: Additional notes (optional)
            replace_existing: Mandate ID to replace (optional)

        Returns:
            dict: Result with success, mandate_name, and mandate_id
        """
        try:
            from frappe.utils import today

            # Step 1: Validate all inputs (defense-in-depth)
            validation_error = SEPAService._validate_mandate_creation_inputs(
                member,
                mandate_id,
                iban,
                account_holder_name,
                mandate_type,
                sign_date,
                used_for_memberships,
                used_for_donations,
                notes,
            )
            if validation_error:
                return validation_error

            # Step 2: Prepare mandate parameters
            if not sign_date:
                sign_date = today()

            # Convert mandate type to internal format
            type_mapping = {"One-off": "OOFF", "One-of": "OOFF", "Recurring": "RCUR"}
            internal_type = type_mapping.get(mandate_type, "RCUR")

            # Step 3: Create mandate document
            mandate = SEPAService._prepare_mandate_document(
                mandate_id,
                member,
                iban,
                bic,
                account_holder_name,
                internal_type,
                sign_date,
                used_for_memberships,
                used_for_donations,
                notes,
            )

            # Step 4: Create mandate with security validation
            create_result = SEPAService._create_mandate_with_security(mandate, mandate_id, member, iban)
            if not create_result["success"]:
                return create_result

            mandate = create_result["mandate"]

            # Step 5: Update member's mandate links
            member_doc = frappe.get_doc("Member", member)
            SEPAService._update_member_mandate_links(
                member_doc, mandate, mandate_id, sign_date, replace_existing
            )

            # Step 6: Save member with security validation
            save_result = SEPAService._save_member_with_security(member_doc, mandate_id, member)
            if not save_result["success"]:
                return save_result

            return {"success": True, "mandate_name": mandate.name, "mandate_id": mandate_id}

        except frappe.ValidationError as e:
            # Handle validation errors gracefully
            error_msg = str(e)
            if "iban" in error_msg.lower():
                return {"success": False, "error": "Invalid IBAN format. Please provide a valid IBAN."}
            elif "mandate_id" in error_msg.lower():
                return {"success": False, "error": "Invalid mandate ID. Please provide a unique mandate ID."}
            elif "account_holder_name" in error_msg.lower():
                return {"success": False, "error": "Account holder name is required."}
            else:
                return {"success": False, "error": f"Validation error: {error_msg}"}

        except frappe.DuplicateEntryError:
            return {
                "success": False,
                "error": "A mandate with this ID already exists. Please use a different mandate ID.",
            }

        except Exception as e:
            # Log unexpected errors for debugging
            frappe.log_error(
                f"Unexpected error creating SEPA mandate: {str(e)}", "SEPA Mandate Creation Error"
            )
            return {
                "success": False,
                "error": "An unexpected error occurred while creating the SEPA mandate. Please try again or contact support.",
            }

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

            # Use secure_document_operation for proper audit trail
            mandate_result = secure_document_operation(
                operation="save",
                doc=mandate_doc,
                justification=f"Cancel SEPA mandate {mandate_name}: {reason}",
                required_permissions=["SEPA Mandate:write"],
            )

            if not mandate_result.success:
                frappe.log_error(
                    f"Failed to cancel SEPA mandate {mandate_name}: {'; '.join(mandate_result.errors)}",
                    "SEPA Mandate Cancellation Security",
                )
                return {
                    "success": False,
                    "message": mandate_result.errors[0]
                    if mandate_result.errors
                    else "Failed to cancel mandate",
                }

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
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_sepa_mandate_via_service(member_name: str, iban: str, bic: str = None) -> Dict[str, Any]:
    """
    API endpoint for creating SEPA mandates via service layer

    This provides a direct API interface to the service layer functionality.
    """
    service = get_sepa_service()
    return service.create_mandate_enhanced(member_name, iban, bic)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_member_mandates_via_service(member_name: str) -> List[Dict[str, Any]]:
    """API endpoint for getting member mandates via service layer"""
    service = get_sepa_service()
    return service.get_active_mandates(member_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def cancel_mandate_via_service(mandate_name: str, reason: str = "Cancelled via API") -> Dict[str, Any]:
    """API endpoint for cancelling mandates via service layer"""
    service = get_sepa_service()
    return service.cancel_mandate(mandate_name, reason)


# Consolidated API endpoints for SEPA operations (extracted from member.py and member_utils.py)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.UTILITY)
def validate_mandate_creation(member: str, iban: str, mandate_id: str) -> Dict[str, Any]:
    """API endpoint for validating mandate creation parameters"""
    return SEPAService.validate_mandate_creation(member, iban, mandate_id)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.UTILITY)
def derive_bic_from_iban(iban: str) -> Dict[str, Any]:
    """API endpoint for deriving BIC from IBAN"""
    bic = SEPAService.derive_bic_from_iban(iban)
    return {"bic": bic if bic else None}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def deactivate_old_sepa_mandates(member: str, new_iban: str) -> Dict[str, Any]:
    """API endpoint for deactivating old SEPA mandates when IBAN changes"""
    return SEPAService.deactivate_old_sepa_mandates(member, new_iban)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def refresh_sepa_mandates(member: str) -> Dict[str, Any]:
    """API endpoint for refreshing SEPA mandates child table"""
    return SEPAService.refresh_sepa_mandates(member)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_active_sepa_mandate(member: str, iban: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """API endpoint for getting active SEPA mandate for a member"""
    return SEPAService.get_active_sepa_mandate(member, iban)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_and_link_mandate_enhanced(
    member: str,
    mandate_id: str,
    iban: str,
    bic: str = "",
    account_holder_name: str = "",
    mandate_type: str = "Recurring",
    sign_date: Optional[str] = None,
    used_for_memberships: int = 1,
    used_for_donations: int = 0,
    notes: str = "",
    replace_existing: Optional[str] = None,
) -> Dict[str, Any]:
    """API endpoint for creating and linking enhanced SEPA mandate"""
    return SEPAService.create_and_link_mandate_enhanced(
        member=member,
        mandate_id=mandate_id,
        iban=iban,
        bic=bic,
        account_holder_name=account_holder_name,
        mandate_type=mandate_type,
        sign_date=sign_date,
        used_for_memberships=used_for_memberships,
        used_for_donations=used_for_donations,
        notes=notes,
        replace_existing=replace_existing,
    )
