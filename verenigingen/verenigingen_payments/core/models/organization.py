"""
Organization Models for Mollie API
Data structures for organization-related operations
"""

from datetime import datetime
from typing import Any, Dict, Optional

from .base import BaseModel, Links


class OrganizationAddress(BaseModel):
    """
    Organization address information
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize organization address"""
        self.street_and_number: Optional[str] = None
        self.postal_code: Optional[str] = None
        self.city: Optional[str] = None
        self.country: Optional[str] = None
        super().__init__(data)

    def get_full_address(self) -> str:
        """Get formatted full address"""
        parts = []

        if self.street_and_number:
            parts.append(self.street_and_number)

        if self.postal_code and self.city:
            parts.append(f"{self.postal_code} {self.city}")
        elif self.city:
            parts.append(self.city)

        if self.country:
            parts.append(self.country)

        return ", ".join(parts)


class Organization(BaseModel):
    """
    Mollie Organization resource

    Represents the merchant organization account
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize organization"""
        self.resource: str = "organization"
        self.id: Optional[str] = None
        self.name: Optional[str] = None
        self.email: Optional[str] = None
        self.locale: Optional[str] = None
        self.address: Optional[OrganizationAddress] = None
        self.registration_number: Optional[str] = None
        self.vat_number: Optional[str] = None
        self.vat_regulation: Optional[str] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name == "address":
            return OrganizationAddress
        elif attr_name == "_links":
            return Links
        return None

    def has_vat_number(self) -> bool:
        """Check if organization has VAT number"""
        return bool(self.vat_number)

    def get_display_name(self) -> str:
        """Get display name with ID"""
        if self.name:
            return f"{self.name} ({self.id})"
        return self.id or "Unknown Organization"
