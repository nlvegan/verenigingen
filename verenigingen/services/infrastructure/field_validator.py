"""
Service Infrastructure Field Validator

Integrates field validation patterns into service infrastructure to prevent
runtime errors from invalid field references and ensure data integrity.
"""

import logging
from typing import Any, Dict, List, Optional, Set

import frappe
from frappe import _


class ServiceFieldValidator:
    """Field validator for service infrastructure operations."""

    def __init__(self, service_name: str = "field_validator"):
        self.service_name = service_name
        self.logger = logging.getLogger(f"verenigingen.services.{service_name}")
        self._field_cache = {}
        self._doctype_cache = {}

    def validate_fields(self, doctype: str, fields: List[str]) -> Dict[str, Any]:
        """Validate that all fields exist in the specified DocType.

        Args:
            doctype: DocType name to validate against
            fields: List of field names to validate

        Returns:
            Validation result with any invalid fields
        """
        try:
            # Get DocType metadata
            meta = self.get_doctype_meta(doctype)
            if not meta:
                return {
                    "success": False,
                    "message": f"DocType {doctype} not found",
                    "errors": [f"DocType {doctype} does not exist"],
                    "invalid_fields": fields,
                    "valid_fields": [],
                }

            # Get valid field names for this DocType
            valid_fields = self.get_valid_fields(doctype)

            # Check each field
            invalid_fields = []
            valid_field_list = []

            for field in fields:
                if field in valid_fields:
                    valid_field_list.append(field)
                else:
                    invalid_fields.append(field)

            success = len(invalid_fields) == 0

            return {
                "success": success,
                "message": f"Validated {len(fields)} fields for {doctype}",
                "errors": [f"Invalid field: {field}" for field in invalid_fields],
                "invalid_fields": invalid_fields,
                "valid_fields": valid_field_list,
                "doctype": doctype,
                "total_fields": len(fields),
            }

        except Exception as e:
            self.logger.error(f"Field validation failed: {str(e)}")
            # invalid_fields stays EMPTY: we could not look the fields up, so we do
            # not know that any of them are invalid. Listing them here blamed real
            # fields for what is an infrastructure failure -- the same mislabelling
            # this method's own message was fixed to avoid -- and a caller reading
            # invalid_fields rather than message still got the wrong answer.
            #
            # It also un-broke validate_service_operation: a non-empty invalid_fields
            # sent it into a get_field_suggestions loop that re-raises the very error
            # this branch just converted into a result dict.
            return {
                "success": False,
                "message": f"Field validation error: {str(e)}",
                "errors": [str(e)],
                "invalid_fields": [],
                "valid_fields": [],
            }

    def get_doctype_meta(self, doctype: str) -> Optional[Dict]:
        """Get DocType metadata with caching.

        Args:
            doctype: DocType name

        Returns:
            DocType metadata or None if not found
        """
        if doctype in self._doctype_cache:
            return self._doctype_cache[doctype]

        try:
            meta = frappe.get_meta(doctype)
            meta_dict = {
                "name": meta.name,
                "module": meta.module,
                "fields": [{"fieldname": f.fieldname, "fieldtype": f.fieldtype} for f in meta.fields],
            }
            self._doctype_cache[doctype] = meta_dict
            return meta_dict
        except Exception as e:
            # Do NOT cache the failure: it would make one transient error permanent
            # for the life of the process. And do not return None -- the caller reads
            # a falsy result as "DocType {doctype} does not exist", which turns a
            # database error into a confidently wrong diagnosis. Its own handler
            # reports the real cause.
            self.logger.warning(f"Could not get metadata for DocType {doctype}: {str(e)}")
            raise

    def get_valid_fields(self, doctype: str) -> Set[str]:
        """Get set of valid field names for a DocType.

        Args:
            doctype: DocType name

        Returns:
            Set of valid field names
        """
        cache_key = f"fields_{doctype}"
        if cache_key in self._field_cache:
            return self._field_cache[cache_key]

        try:
            meta = frappe.get_meta(doctype)
            valid_fields = set()

            # Add standard fields
            standard_fields = {
                "name",
                "owner",
                "creation",
                "modified",
                "modified_by",
                "docstatus",
                "idx",
                "_user_tags",
                "_comments",
                "_assign",
                "_liked_by",
            }
            valid_fields.update(standard_fields)

            # Add custom fields from DocType
            for field in meta.fields:
                if field.fieldname:
                    valid_fields.add(field.fieldname)

            self._field_cache[cache_key] = valid_fields
            return valid_fields

        except Exception as e:
            # Do NOT cache the failure, and do not return an empty set: `set()` is
            # the "this DocType has no fields" answer, so every later check reports
            # every field invalid and `safe_query` raises. Cached, that verdict
            # outlives the outage for the life of the process. Same shape as
            # get_doctype_meta above; validate_fields turns the raise into a result
            # that names the real cause.
            self.logger.warning(f"Could not get fields for DocType {doctype}: {str(e)}")
            raise

    def validate_query_fields(self, doctype: str, query_dict: Dict) -> Dict[str, Any]:
        """Validate fields used in a query dictionary.

        Args:
            doctype: DocType being queried
            query_dict: Query parameters (filters, fields, etc.)

        Returns:
            Validation result
        """
        all_fields = []

        # Extract fields from different query components
        if "fields" in query_dict:
            fields = query_dict["fields"]
            if isinstance(fields, str):
                all_fields.extend([f.strip() for f in fields.split(",")])
            elif isinstance(fields, list):
                all_fields.extend(fields)

        # Extract fields from filters
        if "filters" in query_dict:
            filters = query_dict["filters"]
            if isinstance(filters, dict):
                all_fields.extend(filters.keys())
            elif isinstance(filters, list):
                for filter_item in filters:
                    if isinstance(filter_item, (list, tuple)) and len(filter_item) > 0:
                        all_fields.append(filter_item[0])  # Field name is first element

        # Extract fields from order_by
        if "order_by" in query_dict:
            order_by = query_dict["order_by"]
            if isinstance(order_by, str):
                # Handle "field ASC/DESC" format
                field_name = order_by.split()[0]
                all_fields.append(field_name)

        # Validate all collected fields
        return self.validate_fields(doctype, all_fields)

    def get_field_suggestions(self, doctype: str, invalid_field: str) -> List[str]:
        """Get field name suggestions for invalid fields.

        Args:
            doctype: DocType name
            invalid_field: Invalid field name

        Returns:
            List of suggested field names
        """
        valid_fields = self.get_valid_fields(doctype)
        suggestions = []

        # Simple similarity matching
        invalid_lower = invalid_field.lower()

        for field in valid_fields:
            field_lower = field.lower()

            # Exact match (shouldn't happen)
            if field_lower == invalid_lower:
                suggestions.insert(0, field)
                continue

            # Contains substring
            if invalid_lower in field_lower or field_lower in invalid_lower:
                suggestions.append(field)
                continue

            # Similar length and similar characters
            if abs(len(field) - len(invalid_field)) <= 2:
                common_chars = sum(1 for c in invalid_lower if c in field_lower)
                if common_chars >= min(len(invalid_field), len(field)) * 0.6:
                    suggestions.append(field)

        return suggestions[:5]  # Return top 5 suggestions

    def validate_service_operation(self, doctype: str, operation: str, data: Dict = None) -> Dict[str, Any]:
        """Validate fields for a specific service operation.

        Args:
            doctype: DocType being operated on
            operation: Operation type (create, read, update, delete)
            data: Operation data containing field references

        Returns:
            Validation result
        """
        if not data:
            return {"success": True, "message": "No data to validate"}

        fields_to_validate = []

        # Extract fields based on operation type
        if operation in ["create", "update"]:
            # For create/update, validate all data keys as potential fields
            fields_to_validate.extend(data.keys())

        elif operation == "read":
            # For read operations, check if data contains field specifications
            if "fields" in data:
                fields = data["fields"]
                if isinstance(fields, str):
                    fields_to_validate.extend([f.strip() for f in fields.split(",")])
                elif isinstance(fields, list):
                    fields_to_validate.extend(fields)

        # Validate the fields
        validation_result = self.validate_fields(doctype, fields_to_validate)

        # Add operation context
        validation_result["operation"] = operation
        validation_result["doctype"] = doctype

        # Add suggestions for invalid fields
        if validation_result["invalid_fields"]:
            suggestions = {}
            for invalid_field in validation_result["invalid_fields"]:
                suggestions[invalid_field] = self.get_field_suggestions(doctype, invalid_field)
            validation_result["suggestions"] = suggestions

        return validation_result

    def clear_cache(self):
        """Clear internal caches."""
        self._field_cache.clear()
        self._doctype_cache.clear()
        self.logger.info("Field validator cache cleared")


# Global validator instance
_global_validator = None


def get_field_validator() -> ServiceFieldValidator:
    """Get global field validator instance.

    Returns:
        ServiceFieldValidator instance
    """
    global _global_validator
    if _global_validator is None:
        _global_validator = ServiceFieldValidator()
    return _global_validator


def validate_service_fields(doctype: str, fields: List[str]) -> Dict[str, Any]:
    """Convenience function to validate fields.

    Args:
        doctype: DocType name
        fields: List of field names

    Returns:
        Validation result
    """
    validator = get_field_validator()
    return validator.validate_fields(doctype, fields)


def validate_query_operation(doctype: str, query_dict: Dict) -> Dict[str, Any]:
    """Convenience function to validate query fields.

    Args:
        doctype: DocType name
        query_dict: Query parameters

    Returns:
        Validation result
    """
    validator = get_field_validator()
    return validator.validate_query_fields(doctype, query_dict)
