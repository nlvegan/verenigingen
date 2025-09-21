"""
Customer Handling Service

Handles customer and mandate management for webhook processing.
Extracted from monolithic webhook handler for better maintainability.
"""

from typing import Any, Dict, Optional

import frappe

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
            customer.customer_group = frappe.db.get_single_value(
                "Selling Settings", "customer_group"
            ) or self.config.get("default_customer_group", "Individual")
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

            # Link Mollie customer ID
            if customer_id and (
                not hasattr(customer, "mollie_customer_id") or customer.mollie_customer_id != customer_id
            ):
                customer.mollie_customer_id = customer_id
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

            # Check Mollie integration fields (if available)
            if hasattr(customer, "mollie_customer_id") and not customer.mollie_customer_id:
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
