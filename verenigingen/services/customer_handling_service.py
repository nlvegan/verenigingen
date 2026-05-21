"""
Customer Handling Service

Handles customer and mandate management for webhook processing.
Extracted from monolithic webhook handler for better maintainability.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.services.infrastructure.service_config import get_service_config
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class CustomerHandlingService(StatefulService):
    """Service class for handling customer and mandate operations

    Inherits from StatefulService to provide:
    - Performance monitoring and metrics
    - Standardized error handling
    - Database transaction management
    - Resource cleanup capabilities
    """

    def __init__(self, service_name: str = None, debug_context: str = "webhook"):
        super().__init__(service_name or "customer_handling")
        self.debug_context = debug_context
        self.config = get_service_config("customer_handling")

        # Configure service-specific settings
        self.config.set("default_customer_group", "Individual")
        self.config.set("default_territory", "All Territories")
        self.config.set("default_customer_type", "Individual")
        self.config.set("enable_validation", True)

    def validate_configuration(self) -> bool:
        """Validate service configuration including DocType access."""
        try:
            # Check database connectivity (from parent)
            super().validate_configuration()

            # Verify we can access Customer DocType
            frappe.get_meta("Customer")

            # Check selling settings access
            frappe.db.get_single_value("Selling Settings", "customer_group")

            return True
        except Exception as e:
            self.logger.error(f"Configuration validation failed: {str(e)}")
            return False

    def create_customer_for_member(self, member_doc, suppress_messages=False) -> Optional[str]:
        """Create a customer for this member in ERPNext.

        Handles duplicate detection, secure operations, and proper ERPNext
        Customer record creation.

        Args:
            member_doc: Member document instance
            suppress_messages (bool): Whether to suppress user messages

        Returns:
            Optional[str]: Customer name (ID) of created customer, or None on error

        Raises:
            frappe.ValidationError: If customer creation fails
        """
        operation_name = "create_customer_for_member"
        start_time = self._start_operation(operation_name)

        try:
            # Check if customer already exists
            if member_doc.customer:
                if not suppress_messages:
                    frappe.msgprint(
                        _("Customer {0} already exists for this member").format(member_doc.customer)
                    )
                self._end_operation(operation_name, start_time, success=True)
                return member_doc.customer

            # Check if customer already exists for this member (database constraint check)
            existing_customer = frappe.db.get_value("Customer", {"member": member_doc.name}, "name")
            if existing_customer:
                self.logger.info(f"Customer {existing_customer} already exists for Member {member_doc.name}")
                # Update member record to reflect the existing customer link
                member_doc.db_set("customer", existing_customer, update_modified=False)
                self._end_operation(operation_name, start_time, success=True)
                return existing_customer

            # Check for similar customers and warn user
            if member_doc.full_name:
                similar_name_customers = self.check_similar_customers(member_doc.full_name)

                exact_name_match = next(
                    (
                        c
                        for c in similar_name_customers
                        if c.customer_name.lower() == member_doc.full_name.lower()
                    ),
                    None,
                )
                if exact_name_match and not suppress_messages:
                    customer_info = (
                        f"Name: {exact_name_match.name}, Email: {exact_name_match.email_id or 'N/A'}"
                    )
                    frappe.msgprint(
                        _("Found existing customer with same name: {0}").format(customer_info)
                        + _(
                            "\nCreating a new customer for this member. If you want to link to the existing customer instead, please do so manually."
                        )
                    )

                elif similar_name_customers and not suppress_messages:
                    customer_list = "\n".join(
                        [f"- {c.customer_name} ({c.name})" for c in similar_name_customers[:5]]
                    )
                    frappe.msgprint(
                        _("Found similar customer names. Please review:")
                        + f"\n{customer_list}"
                        + (
                            _("\n(Showing first 5 of {0} matches)").format(len(similar_name_customers))
                            if len(similar_name_customers) > 5
                            else ""
                        )
                        + _("\nCreating a new customer for this member.")
                    )

            # Delegate to canonical implementation which creates Customer + Contact
            # (Contact is required by ERPNext for email/phone via fetch_from)
            from verenigingen.utils.application_payments import create_customer_for_member as _create_customer

            customer = _create_customer(member_doc)

            self.logger.info(f"Created customer {customer.name} for member {member_doc.name}")
            self._end_operation(operation_name, start_time, success=True)
            return customer.name

        except Exception as e:
            self._end_operation(operation_name, start_time, success=False)
            # Re-raise if it's already a ValidationError or similar, otherwise wrap
            if isinstance(e, (frappe.ValidationError, frappe.DoesNotExistError)):
                raise
            member_name = getattr(member_doc, "name", "Unknown")
            self.logger.error(
                f"Customer creation failed for member {member_name}: {type(e).__name__}: {str(e)}"
            )
            self.handle_error(e, operation_name, {"member": member_name})
            return None

    def check_similar_customers(self, full_name: str, limit: int = 10) -> list:
        """Check for existing customers with similar names.

        Args:
            full_name: Full name to search for
            limit: Maximum number of results to return

        Returns:
            list: List of similar customer records
        """
        if not full_name:
            return []

        return frappe.get_all(
            "Customer",
            filters=[["customer_name", "like", f"%{full_name}%"]],
            fields=["name", "customer_name", "email_id", "mobile_no"],
            limit=limit,
        )

    def find_exact_customer_match(self, full_name: str) -> Optional[Dict]:
        """Find customer with exact name match (case-insensitive).

        Args:
            full_name: Full name to match exactly

        Returns:
            dict or None: Customer record if found, None otherwise
        """
        if not full_name:
            return None

        similar_customers = self.check_similar_customers(full_name)
        return next((c for c in similar_customers if c.customer_name.lower() == full_name.lower()), None)

    def validate_customer_creation_requirements(self, member_doc) -> Dict:
        """Validate that member has required fields for customer creation.

        Args:
            member_doc: Member document instance

        Returns:
            dict: Validation result with valid/errors fields
        """
        errors = []

        if not getattr(member_doc, "full_name", None):
            errors.append("Member must have a full name to create customer")

        if not getattr(member_doc, "name", None):
            errors.append("Member must be saved before creating customer")

        return {"valid": len(errors) == 0, "errors": errors}

    def update_member_customer_reference(self, member_doc, customer_name: str) -> bool:
        """Update member document with customer reference.

        Args:
            member_doc: Member document instance
            customer_name: Customer name/ID to link

        Returns:
            bool: True if update successful
        """
        operation_name = "update_member_customer_reference"
        try:
            member_doc.customer = customer_name
            return True
        except Exception as e:
            self.handle_error(
                e,
                operation_name,
                {"member": getattr(member_doc, "name", "Unknown"), "customer_name": customer_name},
                raise_error=False,
            )
            return False

    def update_customer_mandate(self, customer_id: str, mandate_id: str) -> Dict[str, Any]:
        """
        Update customer with mandate ID information

        Args:
            customer_id: Mollie customer ID
            mandate_id: Mollie mandate ID

        Returns:
            Standardized service result dict
        """
        operation_name = "update_customer_mandate"
        start_time = self._start_operation(operation_name)

        try:
            if not customer_id or not mandate_id:
                self._end_operation(operation_name, start_time, success=False)
                return self.create_result(
                    success=False,
                    message="Missing customer_id or mandate_id",
                    errors=["customer_id and mandate_id are required"],
                )

            # Find customer by Mollie customer ID
            customers = frappe.get_all(
                "Customer", filters={"mollie_customer_id": customer_id}, fields=["name"]
            )

            if not customers:
                self.logger.warning(
                    f"⚠️ [{self.debug_context}] No customer found with mollie_customer_id: {customer_id}"
                )
                self._end_operation(operation_name, start_time, success=False)
                return self.create_result(
                    success=False,
                    message=f"No customer found with mollie_customer_id: {customer_id}",
                    errors=[f"Customer with Mollie ID {customer_id} not found"],
                )

            customer = frappe.get_doc("Customer", customers[0]["name"])

            # Update mandate information
            if (
                not hasattr(customer, "custom_mollie_dues_mandate")
                or customer.custom_mollie_dues_mandate != mandate_id
            ):
                customer.custom_mollie_dues_mandate = mandate_id
                customer.save()

                self.logger.info(
                    f"✅ [{self.debug_context}] Updated customer {customer.name} with mandate {mandate_id}"
                )

                self._end_operation(operation_name, start_time, success=True)
                return self.create_result(
                    success=True,
                    message=f"Customer {customer.name} updated with mandate {mandate_id}",
                    data={"customer": customer.name, "mandate_id": mandate_id, "customer_id": customer_id},
                )
            else:
                self._end_operation(operation_name, start_time, success=True)
                return self.create_result(
                    success=True,
                    message=f"Customer {customer.name} already has mandate {mandate_id}",
                    data={"customer": customer.name, "mandate_id": mandate_id, "skipped": True},
                )

        except Exception as e:
            self._end_operation(operation_name, start_time, success=False)
            return self.handle_error(
                e, operation_name, {"customer_id": customer_id, "mandate_id": mandate_id}, raise_error=False
            )

    def ensure_donor_customer_exists(self, donor_name: str) -> Dict[str, Any]:
        """
        Ensure a customer record exists for the donor

        Args:
            donor_name: Donor name/ID

        Returns:
            Standardized service result dict with customer name in data
        """
        operation_name = "ensure_donor_customer_exists"
        start_time = self._start_operation(operation_name)

        try:
            if not donor_name:
                self._end_operation(operation_name, start_time, success=False)
                return self.create_result(
                    success=False,
                    message="Donor name is required",
                    errors=["donor_name parameter cannot be empty"],
                )

            # Check if customer already exists
            if DocumentExistenceValidator.check_document_exists("Customer", donor_name):
                self._end_operation(operation_name, start_time, success=True)
                return self.create_result(
                    success=True,
                    message=f"Customer {donor_name} already exists",
                    data={"customer_name": donor_name, "created": False},
                )

            # Create customer record
            customer = frappe.new_doc("Customer")
            customer.customer_name = donor_name
            customer.customer_type = self.config.get("default_customer_type", "Individual")
            customer.customer_group = resolve_non_group_customer_group()
            customer.territory = frappe.db.get_single_value(
                "Selling Settings", "territory"
            ) or self.config.get("default_territory", "All Territories")
            customer.insert()

            self.logger.info(f"✅ [{self.debug_context}] Created customer {customer.name} for donor")

            self._end_operation(operation_name, start_time, success=True)
            return self.create_result(
                success=True,
                message=f"Created customer {customer.name} for donor",
                data={"customer_name": customer.name, "created": True},
            )

        except Exception as e:
            self._end_operation(operation_name, start_time, success=False)
            return self.handle_error(e, operation_name, {"donor_name": donor_name}, raise_error=False)

    def link_customer_to_mollie(
        self, customer_name: str, mollie_ids: Dict[str, Optional[str]]
    ) -> Dict[str, Any]:
        """
        Link customer to Mollie IDs (customer_id, mandate_id)

        Args:
            customer_name: ERPNext customer name
            mollie_ids: Dict with mollie customer and mandate IDs

        Returns:
            Processing result dict
        """
        try:
            if not customer_name:
                return {"status": "skipped", "message": "No customer provided"}

            customer_id = mollie_ids.get("customer_id")
            mandate_id = mollie_ids.get("mandate_id")

            if not customer_id and not mandate_id:
                return {"status": "skipped", "message": "No Mollie IDs to link"}

            customer = frappe.get_doc("Customer", customer_name)
            updated = False

            # Link Mollie customer ID (custom field on Customer)
            if customer_id and (
                not hasattr(customer, "custom_mollie_customer_id")
                or customer.custom_mollie_customer_id != customer_id
            ):
                customer.custom_mollie_customer_id = customer_id
                updated = True
                self.logger.info(
                    f"🔗 [{self.debug_context}] Linked customer {customer_name} to Mollie customer {customer_id}"
                )

            # Link Mollie mandate ID
            if mandate_id and (
                not hasattr(customer, "custom_mollie_dues_mandate")
                or customer.custom_mollie_dues_mandate != mandate_id
            ):
                customer.custom_mollie_dues_mandate = mandate_id
                updated = True
                self.logger.info(
                    f"🔗 [{self.debug_context}] Linked customer {customer_name} to Mollie mandate {mandate_id}"
                )

            if updated:
                customer.save()
                return {
                    "status": "success",
                    "message": f"Customer {customer_name} linked to Mollie IDs",
                    "customer": customer_name,
                    "linked_ids": {k: v for k, v in mollie_ids.items() if v},
                }
            else:
                return {
                    "status": "skipped",
                    "message": f"Customer {customer_name} already linked to these Mollie IDs",
                }

        except Exception as e:
            error_msg = f"Failed to link customer to Mollie: {str(e)}"
            self.logger.error(f"❌ [{self.debug_context}] {error_msg}")
            return {"status": "error", "message": error_msg}

    def validate_customer_setup(self, customer_name: str) -> Dict[str, Any]:
        """
        Validate customer setup for payment processing

        Args:
            customer_name: Customer name to validate

        Returns:
            Validation result dict
        """
        try:
            if not customer_name or not DocumentExistenceValidator.check_document_exists(
                "Customer", customer_name
            ):
                return {"status": "invalid", "message": f"Customer {customer_name} does not exist"}

            customer = frappe.get_doc("Customer", customer_name)

            validation_issues = []

            # Check required fields
            if not customer.customer_type:
                validation_issues.append("Missing customer_type")

            if not customer.customer_group:
                validation_issues.append("Missing customer_group")

            if not customer.territory:
                validation_issues.append("Missing territory")

            # Check Mollie integration fields (custom field on Customer)
            if hasattr(customer, "custom_mollie_customer_id") and not customer.custom_mollie_customer_id:
                validation_issues.append("No Mollie customer ID linked")

            if validation_issues:
                return {
                    "status": "warning",
                    "message": f"Customer validation issues: {', '.join(validation_issues)}",
                    "issues": validation_issues,
                }
            else:
                return {"status": "valid", "message": f"Customer {customer_name} is properly configured"}

        except Exception as e:
            error_msg = f"Customer validation failed: {str(e)}"
            self.logger.error(f"❌ [{self.debug_context}] {error_msg}")
            return {"status": "error", "message": error_msg}

    def get_customer_mollie_info(self, customer_name: str) -> Dict[str, Optional[str]]:
        """
        Get Mollie integration information for a customer

        Args:
            customer_name: Customer name

        Returns:
            Dict with Mollie customer and mandate IDs
        """
        try:
            if not customer_name or not DocumentExistenceValidator.check_document_exists(
                "Customer", customer_name
            ):
                return {"customer_id": None, "mandate_id": None}

            customer = frappe.get_doc("Customer", customer_name)

            customer_id = getattr(customer, "mollie_customer_id", None)
            mandate_id = getattr(customer, "custom_mollie_dues_mandate", None)

            return {"customer_id": customer_id, "mandate_id": mandate_id}

        except Exception as e:
            self.logger.error(f"❌ [{self.debug_context}] Failed to get customer Mollie info: {str(e)}")
            return {"customer_id": None, "mandate_id": None}
