#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Field Validator for Test Data
Provides schema-aware field validation to prevent field reference bugs
"""

import json
import os
from typing import Dict, List, Set, Any, Optional
import frappe


class FieldValidationError(Exception):
    """Raised when field validation fails"""
    pass


class FieldValidator:
    """
    Schema-aware field validator that prevents field reference bugs in tests
    
    Key features:
    - Validates field existence against DocType JSON schemas
    - Caches schemas for performance
    - Provides field type information
    - Validates field relationships and links
    - Ensures required fields are present
    """
    
    def __init__(self):
        self.schema_cache = {}
        self.app_path = frappe.get_app_path("verenigingen")
        
    def get_doctype_schema(self, doctype: str) -> Dict[str, Any]:
        """Get DocType schema from JSON file or database"""
        if doctype in self.schema_cache:
            return self.schema_cache[doctype]
            
        try:
            # Try to get from Frappe meta first (most reliable)
            meta = frappe.get_meta(doctype)
            
            schema = {
                "fields": {},
                "required_fields": [],
                "field_types": {},
                "link_fields": {},
                "child_tables": {}
            }
            
            for field in meta.fields:
                schema["fields"][field.fieldname] = {
                    "fieldtype": field.fieldtype,
                    "label": field.label,
                    "options": field.options,
                    "reqd": field.reqd,
                    "read_only": field.read_only,
                    "permlevel": getattr(field, 'permlevel', 0)
                }
                
                if field.reqd:
                    schema["required_fields"].append(field.fieldname)
                    
                schema["field_types"][field.fieldname] = field.fieldtype
                
                if field.fieldtype == "Link":
                    schema["link_fields"][field.fieldname] = field.options
                    
                if field.fieldtype == "Table":
                    schema["child_tables"][field.fieldname] = field.options
                    
            self.schema_cache[doctype] = schema
            return schema
            
        except Exception as e:
            # Fallback: try to read from JSON file
            return self._load_schema_from_json(doctype)
            
    def _load_schema_from_json(self, doctype: str) -> Dict[str, Any]:
        """Load schema from DocType JSON file as fallback"""
        try:
            # Convert doctype name to file path
            doctype_path = doctype.lower().replace(" ", "_")
            json_path = os.path.join(
                self.app_path, 
                "verenigingen", 
                "doctype", 
                doctype_path, 
                f"{doctype_path}.json"
            )
            
            if not os.path.exists(json_path):
                raise FieldValidationError(f"DocType JSON not found: {json_path}")
                
            with open(json_path, 'r') as f:
                doctype_json = json.load(f)
                
            schema = {
                "fields": {},
                "required_fields": [],
                "field_types": {},
                "link_fields": {},
                "child_tables": {}
            }
            
            for field in doctype_json.get("fields", []):
                fieldname = field.get("fieldname")
                if not fieldname:
                    continue
                    
                schema["fields"][fieldname] = field
                
                if field.get("reqd"):
                    schema["required_fields"].append(fieldname)
                    
                fieldtype = field.get("fieldtype")
                if fieldtype:
                    schema["field_types"][fieldname] = fieldtype
                    
                    if fieldtype == "Link":
                        schema["link_fields"][fieldname] = field.get("options")
                        
                    if fieldtype == "Table":
                        schema["child_tables"][fieldname] = field.get("options")
                        
            self.schema_cache[doctype] = schema
            return schema
            
        except Exception as e:
            raise FieldValidationError(f"Failed to load schema for {doctype}: {e}")
            
    def validate_field_exists(self, doctype: str, fieldname: str) -> bool:
        """Validate that field exists in doctype"""
        schema = self.get_doctype_schema(doctype)
        
        if fieldname not in schema["fields"]:
            available_fields = list(schema["fields"].keys())
            raise FieldValidationError(
                f"Field '{fieldname}' does not exist in DocType '{doctype}'. "
                f"Available fields: {available_fields[:10]}{'...' if len(available_fields) > 10 else ''}"
            )
            
        return True
        
    def validate_multiple_fields(self, doctype: str, fieldnames: List[str]) -> List[str]:
        """Validate multiple fields and return any missing ones"""
        schema = self.get_doctype_schema(doctype)
        missing_fields = []
        
        for fieldname in fieldnames:
            if fieldname not in schema["fields"]:
                missing_fields.append(fieldname)
                
        if missing_fields:
            available_fields = list(schema["fields"].keys())
            raise FieldValidationError(
                f"Fields {missing_fields} do not exist in DocType '{doctype}'. "
                f"Available fields: {available_fields[:10]}{'...' if len(available_fields) > 10 else ''}"
            )
            
        return []
        
    def get_required_fields(self, doctype: str) -> List[str]:
        """Get list of required fields for doctype"""
        schema = self.get_doctype_schema(doctype)
        return schema["required_fields"]
        
    def get_field_type(self, doctype: str, fieldname: str) -> str:
        """Get field type for validation"""
        self.validate_field_exists(doctype, fieldname)
        schema = self.get_doctype_schema(doctype)
        return schema["field_types"][fieldname]
        
    def get_link_target(self, doctype: str, fieldname: str) -> Optional[str]:
        """Get target doctype for Link field"""
        self.validate_field_exists(doctype, fieldname)
        schema = self.get_doctype_schema(doctype)
        
        if fieldname not in schema["link_fields"]:
            raise FieldValidationError(f"Field '{fieldname}' in '{doctype}' is not a Link field")
            
        return schema["link_fields"][fieldname]
        
    def validate_link_field_value(self, doctype: str, fieldname: str, value: str) -> bool:
        """Validate that link field value exists in target doctype"""
        if not value:
            return True  # Empty values are allowed
            
        target_doctype = self.get_link_target(doctype, fieldname)
        
        if not frappe.db.exists(target_doctype, value):
            raise FieldValidationError(
                f"Link field '{fieldname}' in '{doctype}' references "
                f"non-existent '{target_doctype}' record: {value}"
            )
            
        return True
        
    def validate_data_dict(self, doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate complete data dictionary against schema"""
        # Validate all fields exist
        self.validate_multiple_fields(doctype, list(data.keys()))
        
        # Validate link fields
        schema = self.get_doctype_schema(doctype)
        for fieldname, value in data.items():
            if fieldname in schema["link_fields"] and value:
                self.validate_link_field_value(doctype, fieldname, value)
                
        # Check required fields
        required_fields = self.get_required_fields(doctype)
        missing_required = [f for f in required_fields if f not in data or data[f] is None]
        
        if missing_required:
            raise FieldValidationError(
                f"Required fields missing for '{doctype}': {missing_required}"
            )
            
        return data
        
    def get_child_table_doctype(self, parent_doctype: str, fieldname: str) -> str:
        """Get child table doctype for Table field"""
        self.validate_field_exists(parent_doctype, fieldname)
        schema = self.get_doctype_schema(parent_doctype)
        
        if fieldname not in schema["child_tables"]:
            raise FieldValidationError(
                f"Field '{fieldname}' in '{parent_doctype}' is not a Table field"
            )
            
        return schema["child_tables"][fieldname]
        
    def validate_query_fields(self, doctype: str, fields: List[str]) -> List[str]:
        """Validate fields used in database queries"""
        if not fields:
            return fields
            
        # Handle special cases
        valid_fields = []
        for field in fields:
            if field in ["name", "*"]:
                valid_fields.append(field)
                continue
                
            # Handle field expressions like "count(*)"
            if "(" in field and ")" in field:
                valid_fields.append(field)
                continue
                
            # Validate regular fields
            self.validate_field_exists(doctype, field)
            valid_fields.append(field)
            
        return valid_fields
        
    def get_field_info(self, doctype: str, fieldname: str) -> Dict[str, Any]:
        """Get complete field information"""
        self.validate_field_exists(doctype, fieldname)
        schema = self.get_doctype_schema(doctype)
        return schema["fields"][fieldname]
        
    def suggest_similar_fields(self, doctype: str, fieldname: str) -> List[str]:
        """Suggest similar field names for typos"""
        schema = self.get_doctype_schema(doctype)
        available_fields = list(schema["fields"].keys())
        
        # Simple similarity check
        suggestions = []
        fieldname_lower = fieldname.lower()
        
        for field in available_fields:
            field_lower = field.lower()
            
            # Exact substring match
            if fieldname_lower in field_lower or field_lower in fieldname_lower:
                suggestions.append(field)
                continue
                
            # Similar starting characters
            if len(fieldname) > 3 and field_lower.startswith(fieldname_lower[:3]):
                suggestions.append(field)
                
        return suggestions[:5]  # Return top 5 suggestions
        
    def clear_cache(self):
        """Clear schema cache (useful for testing)"""
        self.schema_cache = {}
        
    def get_all_fields(self, doctype: str) -> List[str]:
        """Get all field names for a doctype"""
        schema = self.get_doctype_schema(doctype)
        return list(schema["fields"].keys())
        
    def validate_test_query(self, doctype: str, query_dict: Dict[str, Any]) -> bool:
        """Validate a test query dictionary"""
        # Validate filters
        if "filters" in query_dict:
            filters = query_dict["filters"]
            if isinstance(filters, dict):
                self.validate_multiple_fields(doctype, list(filters.keys()))
            elif isinstance(filters, list):
                for filter_item in filters:
                    if isinstance(filter_item, list) and len(filter_item) >= 1:
                        field = filter_item[0]
                        if field != "name" and not field.startswith("tab"):
                            self.validate_field_exists(doctype, field)
                            
        # Validate fields
        if "fields" in query_dict:
            self.validate_query_fields(doctype, query_dict["fields"])
            
        return True


# Global validator instance
field_validator = FieldValidator()


# Convenience functions
def validate_field(doctype: str, fieldname: str) -> bool:
    """Quick field validation"""
    return field_validator.validate_field_exists(doctype, fieldname)


def validate_fields(doctype: str, fieldnames: List[str]) -> bool:
    """Quick multiple field validation"""
    field_validator.validate_multiple_fields(doctype, fieldnames)
    return True


def get_required_fields(doctype: str) -> List[str]:
    """Get required fields for doctype"""
    return field_validator.get_required_fields(doctype)


def validate_data(doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate data dictionary"""
    return field_validator.validate_data_dict(doctype, data)


if __name__ == "__main__":
    # Test the field validator
    print("Testing FieldValidator...")
    
    try:
        validator = FieldValidator()
        
        # Test Member fields
        print("Testing Member fields...")
        validator.validate_field_exists("Member", "first_name")
        validator.validate_field_exists("Member", "email")
        
        # Test invalid field
        try:
            validator.validate_field_exists("Member", "nonexistent_field")
            print("❌ Should have failed for nonexistent field")
        except FieldValidationError:
            print("✅ Correctly caught nonexistent field")
            
        # Test Volunteer fields
        print("Testing Volunteer fields...")
        validator.validate_field_exists("Volunteer", "volunteer_name")
        validator.validate_field_exists("Volunteer", "member")
        
        # Test required fields
        required = validator.get_required_fields("Member")
        print(f"✅ Member required fields: {required}")
        
        print("✅ FieldValidator test completed successfully")
        
    except Exception as e:
        print(f"❌ FieldValidator test failed: {e}")
        raise