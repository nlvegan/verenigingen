"""
Customer Handling Service

Handles customer and mandate management for webhook processing.
Extracted from monolithic webhook handler for better maintainability.
"""

from typing import Any, Dict, Optional

import frappe


class CustomerHandlingService:
    """Service class for handling customer and mandate operations"""

    def __init__(self, debug_context: str = "webhook"):
        self.debug_context = debug_context
        self.logger = frappe.logger()

    def update_customer_mandate(self, customer_id: str, mandate_id: str) -> Dict[str, Any]:
        """
        Update customer with mandate ID information

        Args:
            customer_id: Mollie customer ID
            mandate_id: Mollie mandate ID

        Returns:
            Processing result dict
        """
        try:
            if not customer_id or not mandate_id:
                return {"status": "skipped", "message": "Missing customer_id or mandate_id"}

            # Find customer by Mollie customer ID
            customers = frappe.get_all(
                "Customer", filters={"mollie_customer_id": customer_id}, fields=["name"]
            )

            if not customers:
                self.logger.warning(
                    f"⚠️ [{self.debug_context}] No customer found with mollie_customer_id: {customer_id}"
                )
                return {
                    "status": "warning",
                    "message": f"No customer found with mollie_customer_id: {customer_id}",
                }

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

                return {
                    "status": "success",
                    "message": f"Customer {customer.name} updated with mandate {mandate_id}",
                    "customer": customer.name,
                }
            else:
                return {
                    "status": "skipped",
                    "message": f"Customer {customer.name} already has mandate {mandate_id}",
                }

        except Exception as e:
            error_msg = f"Failed to update customer mandate: {str(e)}"
            frappe.log_error(error_msg, f"Customer Mandate Update Error [{self.debug_context}]")
            self.logger.error(f"❌ [{self.debug_context}] {error_msg}")
            return {"status": "error", "message": error_msg}

    def ensure_donor_customer_exists(self, donor_name: str) -> Optional[str]:
        """
        Ensure a customer record exists for the donor

        Args:
            donor_name: Donor name/ID

        Returns:
            Customer name if successful, None if failed
        """
        try:
            if not donor_name:
                return None

            # Check if customer already exists
            if frappe.db.exists("Customer", donor_name):
                return donor_name

            # Create customer record
            customer = frappe.new_doc("Customer")
            customer.customer_name = donor_name
            customer.customer_type = "Individual"
            customer.customer_group = (
                frappe.db.get_single_value("Selling Settings", "customer_group") or "Individual"
            )
            customer.territory = (
                frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
            )
            customer.insert()

            self.logger.info(f"✅ [{self.debug_context}] Created customer {customer.name} for donor")

            return customer.name

        except Exception as e:
            self.logger.error(
                f"❌ [{self.debug_context}] Failed to create customer for donor {donor_name}: {str(e)}"
            )
            return None

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
            if not customer_name or not frappe.db.exists("Customer", customer_name):
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
            if not customer_name or not frappe.db.exists("Customer", customer_name):
                return {"customer_id": None, "mandate_id": None}

            customer = frappe.get_doc("Customer", customer_name)

            customer_id = getattr(customer, "mollie_customer_id", None)
            mandate_id = getattr(customer, "custom_mollie_dues_mandate", None)

            return {"customer_id": customer_id, "mandate_id": mandate_id}

        except Exception as e:
            self.logger.error(f"❌ [{self.debug_context}] Failed to get customer Mollie info: {str(e)}")
            return {"customer_id": None, "mandate_id": None}
