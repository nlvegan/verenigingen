"""
Base Models for Mollie API
Common data structures and base classes
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import frappe


class BaseModel:
    """
    Base model for all Mollie API models

    Provides:
    - Automatic attribute mapping from dict
    - Validation hooks
    - Serialization support
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """
        Initialize model from dictionary

        Args:
            data: Dictionary of model data
        """
        if data:
            self._load_from_dict(data)
        self._post_init()

    def _load_from_dict(self, data: Dict[str, Any]):
        """
        Load attributes from dictionary

        Args:
            data: Dictionary of model data
        """
        for key, value in data.items():
            # Convert snake_case to camelCase if needed
            attr_name = self._normalize_attribute_name(key)

            # Handle nested objects
            if isinstance(value, dict):
                # Check if we have a model class for this attribute
                model_class = self._get_nested_model_class(attr_name)
                if model_class:
                    try:
                        value = model_class(value)
                    except Exception as e:
                        frappe.logger().error(f"Failed to create nested object for '{attr_name}': {e}")

            # Handle lists of nested objects
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                model_class = self._get_nested_model_class(attr_name)
                if model_class:
                    value = [model_class(item) for item in value]

            # Set attribute
            setattr(self, attr_name, value)

    def _normalize_attribute_name(self, name: str) -> str:
        """
        Normalize attribute name (convert camelCase to snake_case)

        Args:
            name: Original attribute name

        Returns:
            Normalized attribute name
        """
        # Convert camelCase to snake_case for Python convention
        import re

        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """
        Get model class for nested attribute

        Args:
            attr_name: Attribute name

        Returns:
            Model class or None
        """
        # Override in subclasses to specify nested models
        return None

    def _post_init(self):
        """Hook for post-initialization logic"""
        pass

    def validate(self) -> bool:
        """
        Validate model data

        Returns:
            True if valid
        """
        # Override in subclasses for specific validation
        return True

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert model to dictionary

        Returns:
            Dictionary representation
        """
        result = {}

        for key, value in self.__dict__.items():
            if key.startswith("_"):
                continue

            if isinstance(value, BaseModel):
                value = value.to_dict()
            elif isinstance(value, list):
                value = [item.to_dict() if isinstance(item, BaseModel) else item for item in value]
            elif isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = str(value)

            result[key] = value

        return result

    def __repr__(self) -> str:
        """String representation"""
        class_name = self.__class__.__name__
        attrs = ", ".join(f"{k}={v}" for k, v in self.__dict__.items() if not k.startswith("_"))
        return f"{class_name}({attrs})"


class Amount(BaseModel):
    """
    Monetary amount with currency
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize amount"""
        self.value: Optional[str] = None
        self.currency: Optional[str] = None
        super().__init__(data)

    def _post_init(self):
        """Convert value to Decimal for precision"""
        if self.value and isinstance(self.value, str):
            try:
                self.decimal_value = Decimal(self.value)
            except Exception as e:
                self.decimal_value = Decimal("0")
                frappe.logger().error(f"Failed to convert '{self.value}' to Decimal: {e}")
        else:
            self.decimal_value = Decimal("0")

    def validate(self) -> bool:
        """Validate amount"""
        if not self.value or not self.currency:
            return False

        try:
            Decimal(self.value)
            return True
        except:
            return False

    def __str__(self) -> str:
        """String representation"""
        return f"{self.currency} {self.value}"


class Link(BaseModel):
    """
    HAL link object
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize link"""
        self.href: Optional[str] = None
        self.type: Optional[str] = None
        super().__init__(data)


class Links(BaseModel):
    """
    Collection of HAL links
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize links"""
        self.self: Optional[Link] = None
        self.next: Optional[Link] = None
        self.previous: Optional[Link] = None
        self.documentation: Optional[Link] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        return Link


class Pagination(BaseModel):
    """
    Pagination information
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize pagination"""
        self.count: int = 0
        self.limit: int = 0
        self.offset: int = 0
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name == "_links":
            return Links
        return None

    def has_next(self) -> bool:
        """Check if there's a next page"""
        return self._links and self._links.next and self._links.next.href is not None

    def has_previous(self) -> bool:
        """Check if there's a previous page"""
        return self._links and self._links.previous and self._links.previous.href is not None
