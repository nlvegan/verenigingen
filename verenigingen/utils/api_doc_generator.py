"""
API Documentation Generator for Verenigingen app

Automatically generates OpenAPI 3.0 specification and documentation
from decorated API endpoints.
"""

import inspect
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.error_handling import get_logger


class APIDocGenerator:
    """Generate API documentation from code decorators and docstrings"""

    def __init__(self):
        self.logger = get_logger("verenigingen.api_docs")
        self.api_directory = Path(frappe.get_app_path("verenigingen", "api"))
        self.endpoints = []
        self.schemas = {}

    def generate_openapi_spec(self, version: str = "1.0.0") -> Dict[str, Any]:
        """
        Generate OpenAPI 3.0 specification from API endpoints

        Returns:
            Dictionary containing OpenAPI specification
        """
        self.logger.info("Generating OpenAPI specification")

        # Scan all API files
        self._scan_api_endpoints()

        # Build OpenAPI spec
        spec = {
            "openapi": "3.0.0",
            "info": {
                "title": "Verenigingen API",
                "description": "API for the Verenigingen Association Management System",
                "version": version,
                "contact": {"name": "Verenigingen Support", "email": "support@verenigingen.nl"},
            },
            "servers": [
                {
                    "url": "{frappe.utils.get_url()}/api/method/verenigingen.api",
                    "description": "Production server",
                }
            ],
            "paths": self._generate_paths(),
            "components": {
                "schemas": self._generate_schemas(),
                "securitySchemes": {
                    "apiKey": {"type": "apiKey", "in": "header", "name": "Authorization"},
                    "sessionAuth": {"type": "apiKey", "in": "cookie", "name": "sid"},
                },
            },
            "security": [{"apiKey": []}, {"sessionAuth": []}],
            "tags": self._generate_tags(),
        }

        return spec

    def _scan_api_endpoints(self) -> None:
        """Scan API directory for endpoints"""

        api_files = list(self.api_directory.glob("*.py"))
        processed_functions = set()  # Track processed functions to avoid duplicates

        for api_file in api_files:
            if api_file.name == "__init__.py":
                continue

            try:
                self._extract_endpoints_from_file(api_file, processed_functions)
            except Exception as e:
                self.logger.error(f"Failed to extract endpoints from {api_file.name}: {str(e)}")

    def _extract_endpoints_from_file(self, file_path: Path, processed_functions: set = None) -> None:
        """Extract API endpoints from a Python file"""

        if processed_functions is None:
            processed_functions = set()

        with open(file_path, "r", encoding="utf-8") as f:
            f.read()

        # Import the module to inspect functions
        module_name = f"verenigingen.api.{file_path.stem}"

        try:
            module = frappe.get_module(module_name)
        except Exception:
            self.logger.warning(f"Could not import module {module_name}")
            return

        # Find all whitelisted functions
        for name, obj in inspect.getmembers(module):
            if inspect.isfunction(obj):
                # Create unique identifier for this function
                func_id = f"{module_name}.{name}"

                # Skip if already processed
                if func_id in processed_functions:
                    continue

                # Debug: Check various ways to detect whitelisted functions
                is_whitelisted = False

                # Method 1: Check __dict__.whitelisted
                if hasattr(obj, "__dict__") and obj.__dict__.get("whitelisted"):
                    is_whitelisted = True

                # Method 2: Check direct whitelisted attribute
                elif hasattr(obj, "whitelisted") and getattr(obj, "whitelisted", False):
                    is_whitelisted = True

                # Method 3: Check for allow_guest attribute (indicates whitelist)
                elif hasattr(obj, "allow_guest"):
                    is_whitelisted = True

                # Method 4: Check if function name starts with @frappe.whitelist in source
                # This is a fallback method by checking the source code
                try:
                    source = inspect.getsource(obj)
                    if "@frappe.whitelist" in source:
                        is_whitelisted = True
                except:
                    pass

                if is_whitelisted:
                    endpoint_info = self._extract_endpoint_info(
                        function=obj, module_name=module_name, file_name=file_path.stem
                    )

                    if endpoint_info:
                        self.endpoints.append(endpoint_info)
                        processed_functions.add(func_id)

    def _extract_endpoint_info(
        self, function: Callable, module_name: str, file_name: str
    ) -> Optional[Dict[str, Any]]:
        """Extract endpoint information from a function"""

        try:
            # Get function signature
            sig = inspect.signature(function)

            # Get docstring
            docstring = inspect.getdoc(function) or "No description available"

            # Parse docstring for description and parameter info
            description, param_docs = self._parse_docstring(docstring)

            # Extract decorators
            decorators = self._extract_decorators(function)

            # Build endpoint info
            endpoint_info = {
                "function_name": function.__name__,
                "module": module_name,
                "file": file_name,
                "path": "/{module_name.replace('.', '/')}.{function.__name__}",
                "method": "POST",  # Frappe APIs are typically POST
                "description": description,
                "parameters": [],
                "decorators": decorators,
                "allow_guest": decorators.get("allow_guest", False),
                "roles": decorators.get("roles", []),
                "rate_limit": decorators.get("rate_limit", {}),
            }

            # Extract parameters
            for param_name, param in sig.parameters.items():
                if param_name in ["self", "cls"]:
                    continue

                param_info = {
                    "name": param_name,
                    "required": param.default == inspect.Parameter.empty,
                    "type": self._infer_param_type(param),
                    "description": param_docs.get(param_name, ""),
                    "default": None if param.default == inspect.Parameter.empty else str(param.default),
                }

                endpoint_info["parameters"].append(param_info)

            # Determine response schema
            endpoint_info["response"] = self._infer_response_schema(function, description)

            return endpoint_info

        except Exception as e:
            self.logger.error(f"Failed to extract info for {function.__name__}: {str(e)}")
            return None

    def _parse_docstring(self, docstring: str) -> tuple[str, Dict[str, str]]:
        """Parse docstring for description and parameter documentation"""

        lines = docstring.split("\n")
        description = ""
        param_docs = {}

        # Extract main description (first paragraph)
        for i, line in enumerate(lines):
            if line.strip() == "":
                description = "\n".join(lines[:i])
                break
            elif i == len(lines) - 1:
                description = docstring

        # Extract parameter documentation
        param_pattern = r":param\s+(\w+):\s*(.+)"
        for line in lines:
            match = re.match(param_pattern, line.strip())
            if match:
                param_name = match.group(1)
                param_desc = match.group(2)
                param_docs[param_name] = param_desc

        # Also check for Args: section
        if "Args:" in docstring:
            args_section = docstring.split("Args:")[1].split("Returns:")[0]
            for line in args_section.split("\n"):
                if ":" in line and not line.strip().startswith(":"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        param_name = parts[0].strip()
                        param_desc = parts[1].strip()
                        if param_name:
                            param_docs[param_name] = param_desc

        return description.strip(), param_docs

    def _extract_decorators(self, function: Callable) -> Dict[str, Any]:
        """Extract decorator information from function"""

        decorators = {}

        # Check for common decorators
        if hasattr(function, "__dict__"):
            func_dict = function.__dict__

            # Check whitelist decorator
            if func_dict.get("whitelisted"):
                decorators["whitelisted"] = True
                decorators["allow_guest"] = func_dict.get("allow_guest", False)

            # Check for rate limiting
            if hasattr(function, "_rate_limit_config"):
                decorators["rate_limit"] = function._rate_limit_config

            # Check for required roles
            if hasattr(function, "_required_roles"):
                decorators["roles"] = function._required_roles

            # Check for performance monitoring
            if hasattr(function, "_performance_threshold"):
                decorators["performance_threshold"] = function._performance_threshold

        return decorators

    def _infer_param_type(self, param: inspect.Parameter) -> str:
        """Infer parameter type from signature"""

        if param.annotation != inspect.Parameter.empty:
            # Use type annotation if available
            type_name = (
                param.annotation.__name__ if hasattr(param.annotation, "__name__") else str(param.annotation)
            )
            return self._map_python_type_to_openapi(type_name)

        # Infer from parameter name
        param_name_lower = param.name.lower()
        if any(keyword in param_name_lower for keyword in ["email", "mail"]):
            return "string"
        elif any(keyword in param_name_lower for keyword in ["amount", "price", "cost", "value"]):
            return "number"
        elif any(keyword in param_name_lower for keyword in ["count", "number", "id", "age"]):
            return "integer"
        elif any(keyword in param_name_lower for keyword in ["is_", "has_", "enable", "disable"]):
            return "boolean"
        elif any(keyword in param_name_lower for keyword in ["date", "time"]):
            return "string"

        return "string"  # Default to string

    def _map_python_type_to_openapi(self, python_type: str) -> str:
        """Map Python type to OpenAPI type"""

        type_mapping = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
            "List": "array",
            "Dict": "object",
            "Any": "object",
            "Optional": "string",  # Simplified
            "datetime": "string",
            "date": "string",
        }

        return type_mapping.get(python_type, "string")

    def _infer_response_schema(self, function: Callable, description: str) -> Dict[str, Any]:
        """Infer response schema from function"""

        # Check if function has explicit return type annotation
        if hasattr(function, "__annotations__") and "return" in function.__annotations__:
            # return_type = function.__annotations__["return"]
            # TODO: Parse return type annotation
            pass

        # Common response patterns based on function name and description
        func_name_lower = function.__name__.lower()

        if any(keyword in func_name_lower for keyword in ["create", "add", "insert"]):
            return {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                    "data": {"type": "object"},
                },
            }
        elif any(keyword in func_name_lower for keyword in ["get", "fetch", "list"]):
            return {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {"type": "array", "items": {"type": "object"}},
                },
            }
        elif any(keyword in func_name_lower for keyword in ["validate", "check"]):
            return {
                "type": "object",
                "properties": {"valid": {"type": "boolean"}, "message": {"type": "string"}},
            }

        # Default response schema
        return {
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "message": {"type": "string"}},
        }

    def _generate_paths(self) -> Dict[str, Any]:
        """Generate paths section of OpenAPI spec"""

        paths = {}

        for endpoint in self.endpoints:
            path = endpoint["path"]

            if path not in paths:
                paths[path] = {}

            # Build operation object
            operation = {
                "summary": endpoint["function_name"].replace("_", " ").title(),
                "description": endpoint["description"],
                "operationId": "{endpoint['module']}.{endpoint['function_name']}",
                "tags": [endpoint["file"]],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": self._generate_request_schema(endpoint)}},
                },
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {"application/json": {"schema": endpoint["response"]}},
                    },
                    "400": {
                        "description": "Bad request",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
                        },
                    },
                    "401": {
                        "description": "Unauthorized",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
                        },
                    },
                },
            }

            # Add security requirements
            if not endpoint["allow_guest"]:
                operation["security"] = [{"apiKey": []}, {"sessionAuth": []}]
            else:
                operation["security"] = []

            # Add rate limiting info
            if endpoint["rate_limit"]:
                operation["x-rate-limit"] = endpoint["rate_limit"]

            # Add role requirements
            if endpoint["roles"]:
                operation["x-required-roles"] = endpoint["roles"]

            paths[path] = {"post": operation}

        return paths

    def _generate_request_schema(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """Generate request schema for endpoint"""

        properties = {}
        required = []

        for param in endpoint["parameters"]:
            properties[param["name"]] = {"type": param["type"], "description": param["description"]}

            if param["default"] is not None:
                properties[param["name"]]["default"] = param["default"]

            if param["required"]:
                required.append(param["name"])

        return {"type": "object", "properties": properties, "required": required}

    def _generate_schemas(self) -> Dict[str, Any]:
        """Generate common schemas"""

        return {
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "default": False},
                    "error": {"type": "string", "description": "Error message"},
                    "type": {
                        "type": "string",
                        "description": "Error type",
                        "enum": ["validation_error", "permission_error", "server_error"],
                    },
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
            "SuccessResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "default": True},
                    "message": {"type": "string"},
                    "data": {"type": "object"},
                },
            },
            "PaginatedResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {"type": "array", "items": {"type": "object"}},
                    "pagination": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "integer"},
                            "page_size": {"type": "integer"},
                            "total_pages": {"type": "integer"},
                            "total_items": {"type": "integer"},
                        },
                    },
                },
            },
        }

    def _generate_tags(self) -> List[Dict[str, str]]:
        """Generate tags from API files"""

        tags = []
        seen_tags = set()

        for endpoint in self.endpoints:
            tag_name = endpoint["file"]

            if tag_name not in seen_tags:
                tags.append({"name": tag_name, "description": "Operations from {tag_name}.py"})
                seen_tags.add(tag_name)

        return sorted(tags, key=lambda x: x["name"])

    def create_postman_collection(self) -> Dict[str, Any]:
        """Generate Postman collection from endpoints"""

        collection = {
            "info": {
                "name": "Verenigingen API",
                "description": "API collection for Verenigingen Association Management System",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                "_postman_id": frappe.generate_hash(length=8),
                "version": "1.0.0",
            },
            "auth": {
                "type": "apikey",
                "apikey": [
                    {"key": "key", "value": "Authorization"},
                    {"key": "value", "value": "{{api_key}}"},
                ],
            },
            "item": [],
            "variable": [
                {"key": "base_url", "value": frappe.utils.get_url(), "type": "string"},
                {"key": "api_key", "value": "", "type": "string"},
            ],
        }

        # Group endpoints by file
        file_groups = {}
        for endpoint in self.endpoints:
            file_name = endpoint["file"]
            if file_name not in file_groups:
                file_groups[file_name] = []
            file_groups[file_name].append(endpoint)

        # Create folders for each file
        for file_name, endpoints in file_groups.items():
            folder = {"name": file_name, "item": []}

            for endpoint in endpoints:
                request = {
                    "name": endpoint["function_name"].replace("_", " ").title(),
                    "request": {
                        "method": "POST",
                        "header": [{"key": "Content-Type", "value": "application/json"}],
                        "body": {"mode": "raw", "raw": self._generate_example_request(endpoint)},
                        "url": {
                            "raw": "{{base_url}}/api/method" + endpoint["path"],
                            "host": ["{{base_url}}"],
                            "path": ["api", "method"] + endpoint["path"].strip("/").split("/"),
                        },
                        "description": endpoint["description"],
                    },
                }

                folder["item"].append(request)

            collection["item"].append(folder)

        return collection

    def _generate_example_request(self, endpoint: Dict[str, Any]) -> str:
        """Generate example request body"""

        example = {}

        for param in endpoint["parameters"]:
            if param["type"] == "string":
                if "email" in param["name"].lower():
                    example[param["name"]] = "user@example.com"
                elif "name" in param["name"].lower():
                    example[param["name"]] = "John Doe"
                else:
                    example[param["name"]] = "example_" + param["name"]
            elif param["type"] == "integer":
                example[param["name"]] = 1
            elif param["type"] == "number":
                example[param["name"]] = 10.00
            elif param["type"] == "boolean":
                example[param["name"]] = True
            elif param["type"] == "array":
                example[param["name"]] = []
            else:
                example[param["name"]] = {}

        return json.dumps(example, indent=2)

    def generate_markdown_documentation(self) -> str:
        """Generate markdown documentation from endpoints"""

        lines = ["# Verenigingen API Documentation\n"]
        lines.append("Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append("## Table of Contents\n")

        # Group endpoints by file
        file_groups = {}
        for endpoint in self.endpoints:
            file_name = endpoint["file"]
            if file_name not in file_groups:
                file_groups[file_name] = []
            file_groups[file_name].append(endpoint)

        # Generate TOC
        for file_name in sorted(file_groups.keys()):
            lines.append("- [{file_name}](#{file_name.replace('_', '-')})")

        lines.append("\n---\n")

        # Generate documentation for each group
        for file_name in sorted(file_groups.keys()):
            lines.append("## {file_name}\n")

            for endpoint in file_groups[file_name]:
                lines.append("### {endpoint['function_name']}\n")
                lines.append("**Description:** {endpoint['description']}\n")
                lines.append("**Endpoint:** `POST {endpoint['path']}`\n")

                if not endpoint["allow_guest"]:
                    lines.append("**Authentication:** Required\n")
                else:
                    lines.append("**Authentication:** Not required (guest access allowed)\n")

                if endpoint["roles"]:
                    lines.append("**Required Roles:** {', '.join(endpoint['roles'])}\n")

                if endpoint["rate_limit"]:
                    lines.append("**Rate Limit:** {endpoint['rate_limit']}\n")

                # Parameters
                if endpoint["parameters"]:
                    lines.append("\n**Parameters:**\n")
                    lines.append("| Name | Type | Required | Description |")
                    lines.append("|------|------|----------|-------------|")

                    for param in endpoint["parameters"]:
                        required = "Yes" if param["required"] else "No"
                        lines.append(
                            f"| {param['name']} | {param['type']} | {required} | {param['description']} |"
                        )

                lines.append("\n**Example Request:**")
                lines.append("```json")
                lines.append(self._generate_example_request(endpoint))
                lines.append("```\n")

                lines.append("**Example Response:**")
                lines.append("```json")
                lines.append(json.dumps(endpoint["response"], indent=2))
                lines.append("```\n")

                lines.append("---\n")

        return "\n".join(lines)


# API functions


@frappe.whitelist()
def generate_api_documentation():
    """Generate API documentation in multiple formats"""

    generator = APIDocGenerator()

    # Generate OpenAPI spec
    openapi_spec = generator.generate_openapi_spec()

    # Generate Postman collection
    postman_collection = generator.create_postman_collection()

    # Generate Markdown documentation
    markdown_docs = generator.generate_markdown_documentation()

    # Save documentation files
    docs_dir = Path(frappe.get_app_path("verenigingen", "docs", "api"))
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Save OpenAPI spec
    with open(docs_dir / "openapi.json", "w") as f:
        json.dump(openapi_spec, f, indent=2)

    # Save Postman collection
    with open(docs_dir / "postman_collection.json", "w") as f:
        json.dump(postman_collection, f, indent=2)

    # Save Markdown documentation
    with open(docs_dir / "API_REFERENCE.md", "w") as f:
        f.write(markdown_docs)

    return {
        "success": True,
        "message": "API documentation generated successfully",
        "files": {
            "openapi": str(docs_dir / "openapi.json"),
            "postman": str(docs_dir / "postman_collection.json"),
            "markdown": str(docs_dir / "API_REFERENCE.md"),
        },
    }


@frappe.whitelist()
def get_api_endpoints_summary():
    """Get summary of all API endpoints"""

    generator = APIDocGenerator()
    generator._scan_api_endpoints()

    summary = {
        "total_endpoints": len(generator.endpoints),
        "endpoints_by_file": {},
        "public_endpoints": 0,
        "protected_endpoints": 0,
        "rate_limited_endpoints": 0,
    }

    for endpoint in generator.endpoints:
        file_name = endpoint["file"]

        if file_name not in summary["endpoints_by_file"]:
            summary["endpoints_by_file"][file_name] = []

        summary["endpoints_by_file"][file_name].append(
            {
                "function": endpoint["function_name"],
                "allow_guest": endpoint["allow_guest"],
                "roles": endpoint["roles"],
            }
        )

        if endpoint["allow_guest"]:
            summary["public_endpoints"] += 1
        else:
            summary["protected_endpoints"] += 1

        if endpoint["rate_limit"]:
            summary["rate_limited_endpoints"] += 1

    return summary
