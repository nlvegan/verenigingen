# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
AddressImportService - Service for creating/updating addresses during CSV import.

Extracts address creation and update logic from MijnRood CSV Import DocType
into a dedicated service for better separation of concerns and testability.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.csv.data_transformers import convert_country_code


class AddressImportService(StatelessService):
    """Service for creating/updating addresses during CSV import.

    Handles address creation, duplicate detection, and link management
    for member addresses during bulk import operations.
    """

    def __init__(self):
        """Initialize the AddressImportService."""
        super().__init__(service_name="AddressImportService")

    def create_or_update_address(
        self,
        member_doc: Document,
        row_data: Dict[str, Any],
    ) -> Optional[str]:
        """Create or update address for member from CSV data.

        Handles duplicate detection by searching for matching addresses
        and links to existing ones instead of creating duplicates.

        Args:
            member_doc: Member document to create address for
            row_data: Dictionary containing address fields from CSV

        Returns:
            Address name if created/updated, None if skipped (no data)
        """
        # Extract and clean address data
        address_line1 = row_data.get("address_line1")
        city = row_data.get("city")

        if address_line1:
            address_line1 = str(address_line1).strip() if address_line1 else None
        if city:
            city = str(city).strip() if city else None

        # Skip if insufficient data
        if not address_line1 or not city:
            self.logger.info(
                f"Skipping address creation for member {member_doc.name} - insufficient address data"
            )
            return None

        # Prepare address data
        pincode = (row_data.get("postal_code") or "").strip() or None
        country = self._get_country_name(row_data.get("country", "NL"))

        address_data = {
            "address_title": f"{member_doc.first_name} {member_doc.last_name}",
            "address_type": "Personal",
            "address_line1": address_line1,
            "city": city,
            "pincode": pincode,
            "country": country,
            "links": [
                {
                    "link_doctype": "Member",
                    "link_name": member_doc.name,
                    "link_title": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
                }
            ],
        }

        # Add Customer link if exists
        if member_doc.customer:
            address_data["links"].append(
                {
                    "link_doctype": "Customer",
                    "link_name": member_doc.customer,
                    "link_title": f"{member_doc.first_name} {member_doc.last_name}",
                }
            )

        # Check for existing address
        existing_address = self._find_existing_address(member_doc, address_line1, city, pincode, country)

        if existing_address:
            # Update existing address
            self._update_existing_address(existing_address, address_data, member_doc)
            member_doc.primary_address = existing_address.name
            return existing_address.name
        else:
            # Create new address
            address = frappe.get_doc({"doctype": "Address", **address_data})
            address.insert()
            member_doc.primary_address = address.name
            self.logger.info(f"Created new address {address.name} for member {member_doc.name}")
            return address.name

    def _find_existing_address(
        self,
        member_doc: Document,
        address_line1: str,
        city: str,
        pincode: Optional[str],
        country: str,
    ) -> Optional[Document]:
        """Find existing address to reuse."""
        # First check member's primary address
        if member_doc.primary_address and frappe.db.exists("Address", member_doc.primary_address):
            address = frappe.get_doc("Address", member_doc.primary_address)
            self.logger.info(f"Updating existing primary address {address.name} for member {member_doc.name}")
            return address

        # Search for matching address by content
        matching_addresses = frappe.get_all(
            "Address",
            filters={
                "address_line1": address_line1,
                "city": city,
                "pincode": pincode,
                "country": country,
            },
            fields=["name"],
            limit=1,
        )

        if matching_addresses:
            address = frappe.get_doc("Address", matching_addresses[0].name)
            self.logger.info(
                f"Found matching address {address.name} for member {member_doc.name}, "
                "linking instead of creating duplicate"
            )
            # Clean up stale links before reusing
            self.remove_stale_address_links(address)
            return address

        return None

    def _update_existing_address(
        self,
        address_doc: Document,
        address_data: Dict[str, Any],
        member_doc: Document,
    ) -> None:
        """Update existing address with new data and ensure proper links."""
        # Update fields (except links)
        for field, value in address_data.items():
            if field != "links" and value:
                setattr(address_doc, field, value)

        # Ensure member is linked
        member_linked = any(
            link.link_doctype == "Member" and link.link_name == member_doc.name
            for link in (address_doc.links or [])
        )
        if not member_linked:
            address_doc.append(
                "links",
                {
                    "link_doctype": "Member",
                    "link_name": member_doc.name,
                    "link_title": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
                },
            )

        # Ensure customer is linked if exists
        if member_doc.customer:
            customer_linked = any(
                link.link_doctype == "Customer" and link.link_name == member_doc.customer
                for link in (address_doc.links or [])
            )
            if not customer_linked:
                address_doc.append(
                    "links",
                    {
                        "link_doctype": "Customer",
                        "link_name": member_doc.customer,
                        "link_title": f"{member_doc.first_name} {member_doc.last_name}",
                    },
                )

        address_doc.save()

    def remove_stale_address_links(self, address_doc: Document) -> int:
        """Remove links to deleted members/customers from an address.

        When reusing addresses from previous imports, they may have links to
        members that were deleted. These stale links cause FK validation errors.

        Args:
            address_doc: Address document to clean up

        Returns:
            Number of stale links removed
        """
        if not hasattr(address_doc, "links") or not address_doc.links:
            return 0

        links_to_remove = []
        for idx, link in enumerate(address_doc.links):
            if link.link_doctype and link.link_name:
                if not frappe.db.exists(link.link_doctype, link.link_name):
                    self.logger.info(
                        f"Removing stale link to {link.link_doctype} {link.link_name} "
                        f"from address {address_doc.name}"
                    )
                    links_to_remove.append(idx)

        # Remove in reverse order to preserve indices
        for idx in reversed(links_to_remove):
            address_doc.links.pop(idx)

        if links_to_remove:
            self.logger.info(f"Removed {len(links_to_remove)} stale link(s) from address {address_doc.name}")

        return len(links_to_remove)

    def _get_country_name(self, country_code: Optional[str]) -> str:
        """Convert country code to full country name."""
        if not country_code:
            return "Netherlands"
        return convert_country_code(country_code) or "Netherlands"


# Module-level singleton accessor
_service_instance: Optional[AddressImportService] = None


def get_address_import_service() -> AddressImportService:
    """Get singleton instance of AddressImportService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = AddressImportService()
    return _service_instance
