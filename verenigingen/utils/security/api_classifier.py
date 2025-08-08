"""
API Classification and Migration Tool

This module provides automated classification of all API endpoints in the
Verenigingen application, migration strategies, and implementation guidance
for applying the comprehensive security framework.
"""

import ast
import importlib
import inspect
import os
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import (
    APISecurityFramework,
    OperationType,
    SecurityLevel,
    get_security_framework,
)
from verenigingen.utils.security.audit_logging import AuditSeverity, get_audit_logger


class ClassificationConfidence(Enum):
    """Confidence level of automatic classification"""

    HIGH = "high"  # 90%+ confidence
    MEDIUM = "medium"  # 70-89% confidence
    LOW = "low"  # 50-69% confidence
    MANUAL = "manual"  # Requires manual review


@dataclass
class APIEndpoint:
    """Comprehensive API endpoint information"""

    module_path: str
    function_name: str
    file_path: str
    line_number: int
    docstring: Optional[str]

    # Security analysis
    current_security_level: Optional[SecurityLevel]
    recommended_security_level: SecurityLevel
    operation_type: OperationType
    classification_confidence: ClassificationConfidence

    # Function analysis
    has_frappe_whitelist: bool
    has_security_decorators: bool
    existing_decorators: List[str]
    allow_guest: bool

    # Parameters and usage
    parameters: List[str]
    return_type: Optional[str]
    database_operations: List[str]  # SELECT, INSERT, UPDATE, DELETE
    external_calls: List[str]  # External API calls

    # Risk assessment
    risk_factors: List[str]
    security_recommendations: List[str]
    migration_priority: int  # 1-5 scale

    # Business context
    business_function: Optional[str]
    data_sensitivity: str  # low, medium, high, critical
    user_roles_involved: List[str]


class APIClassifier:
    """Intelligent API endpoint classifier"""

    # Keyword patterns for operation type classification
    OPERATION_PATTERNS = {
        OperationType.FINANCIAL: [
            "payment",
            "invoice",
            "sepa",
            "batch",
            "debit",
            "credit",
            "transaction",
            "billing",
            "fee",
            "amount",
            "money",
            "financial",
            "bank",
            "iban",
        ],
        OperationType.MEMBER_DATA: [
            "member",
            "user",
            "person",
            "contact",
            "profile",
            "registration",
            "application",
            "signup",
            "login",
            "account",
            "personal",
        ],
        OperationType.ADMIN: [
            "admin",
            "config",
            "setting",
            "system",
            "manage",
            "control",
            "permission",
            "role",
            "access",
            "maintenance",
            "setup",
        ],
        OperationType.REPORTING: [
            "report",
            "analytics",
            "dashboard",
            "export",
            "summary",
            "statistics",
            "chart",
            "graph",
            "list",
            "view",
            "get",
        ],
        OperationType.UTILITY: [
            "health",
            "status",
            "ping",
            "test",
            "debug",
            "validate",
            "check",
            "verify",
            "util",
            "helper",
            "tool",
        ],
    }

    # Security level patterns based on function names and operations
    SECURITY_PATTERNS = {
        SecurityLevel.CRITICAL: [
            "delete",
            "remove",
            "destroy",
            "cancel",
            "process_batch",
            "execute",
            "transfer",
            "payment",
            "financial",
            "admin",
        ],
        SecurityLevel.HIGH: [
            "create",
            "update",
            "modify",
            "edit",
            "save",
            "insert",
            "member",
            "user",
            "batch",
            "validate",
        ],
        SecurityLevel.MEDIUM: [
            "get",
            "list",
            "view",
            "read",
            "fetch",
            "load",
            "report",
            "analytics",
            "search",
            "filter",
        ],
        SecurityLevel.LOW: ["info", "help", "doc", "version", "ping", "health"],
    }

    # Risk factor detection patterns
    RISK_PATTERNS = {
        "sql_injection": ["frappe.db.sql", "execute", "raw_sql", "query"],
        "data_export": ["export", "download", "csv", "excel", "pdf", "backup"],
        "file_operations": ["upload", "file", "attachment", "document", "save_file"],
        "external_api": ["requests.", "urllib", "http", "api_call", "webhook"],
        "authentication": ["login", "logout", "auth", "session", "token", "password"],
        "permission_bypass": ["ignore_permissions", "ignore_validate", "as_admin"],
    }

    def __init__(self):
        self.audit_logger = get_audit_logger()
        self.security_framework = get_security_framework()
        self.classified_endpoints: List[APIEndpoint] = []

    def classify_all_endpoints(self) -> List[APIEndpoint]:
        """
        Classify all API endpoints in the application

        Returns:
            List of classified API endpoints
        """
        self.audit_logger.log_event(
            "api_classification_started",
            AuditSeverity.INFO,
            details={"classification_patterns": len(self.OPERATION_PATTERNS)},
        )

        endpoints = []
        api_path = os.path.join(frappe.get_app_path("verenigingen"), "api")

        for root, dirs, files in os.walk(api_path):
            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    file_path = os.path.join(root, file)
                    endpoints.extend(self._analyze_file(file_path))

        self.classified_endpoints = endpoints

        self.audit_logger.log_event(
            "api_classification_completed",
            AuditSeverity.INFO,
            details={
                "total_endpoints": len(endpoints),
                "high_confidence": len(
                    [e for e in endpoints if e.classification_confidence == ClassificationConfidence.HIGH]
                ),
                "requires_manual_review": len(
                    [e for e in endpoints if e.classification_confidence == ClassificationConfidence.MANUAL]
                ),
            },
        )

        return endpoints

    def _analyze_file(self, file_path: str) -> List[APIEndpoint]:
        """Analyze a single Python file for API endpoints"""
        endpoints = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse AST
            tree = ast.parse(content)

            # Find all function definitions
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    endpoint = self._analyze_function(node, file_path, content)
                    if endpoint and endpoint.has_frappe_whitelist:
                        endpoints.append(endpoint)

        except Exception as e:
            frappe.log_error(f"Failed to analyze file {file_path}: {str(e)}")

        return endpoints

    def _analyze_function(self, node: ast.FunctionDef, file_path: str, content: str) -> Optional[APIEndpoint]:
        """Analyze a single function for API endpoint classification"""

        # Check if function has @frappe.whitelist decorator
        has_whitelist = self._has_frappe_whitelist(node)
        if not has_whitelist:
            return None

        # Get relative module path
        app_path = frappe.get_app_path("verenigingen")
        rel_path = os.path.relpath(file_path, app_path)
        module_path = f"verenigingen.{rel_path[:-3].replace('/', '.')}"

        # Analyze function content
        function_source = self._get_function_source(node, content)

        # Basic endpoint information
        endpoint = APIEndpoint(
            module_path=module_path,
            function_name=node.name,
            file_path=file_path,
            line_number=node.lineno,
            docstring=ast.get_docstring(node),
            # Initialize with defaults
            current_security_level=None,
            recommended_security_level=SecurityLevel.MEDIUM,
            operation_type=OperationType.UTILITY,
            classification_confidence=ClassificationConfidence.MEDIUM,
            has_frappe_whitelist=True,
            has_security_decorators=False,
            existing_decorators=[],
            allow_guest=self._get_allow_guest(node),
            parameters=self._get_parameters(node),
            return_type=None,
            database_operations=[],
            external_calls=[],
            risk_factors=[],
            security_recommendations=[],
            migration_priority=3,
            business_function=None,
            data_sensitivity="medium",
            user_roles_involved=[],
        )

        # Classify operation type
        endpoint.operation_type = self._classify_operation_type(node.name, function_source)

        # Classify security level
        endpoint.recommended_security_level = self._classify_security_level(
            node.name, function_source, endpoint.operation_type
        )

        # Analyze existing security
        endpoint.has_security_decorators = self._has_security_decorators(node)
        endpoint.existing_decorators = self._get_existing_decorators(node)

        # Analyze risks
        endpoint.risk_factors = self._analyze_risk_factors(function_source)
        endpoint.database_operations = self._analyze_database_operations(function_source)
        endpoint.external_calls = self._analyze_external_calls(function_source)

        # Determine classification confidence
        endpoint.classification_confidence = self._calculate_confidence(endpoint)

        # Generate recommendations
        endpoint.security_recommendations = self._generate_recommendations(endpoint)
        endpoint.migration_priority = self._calculate_migration_priority(endpoint)

        # Determine data sensitivity
        endpoint.data_sensitivity = self._assess_data_sensitivity(endpoint)

        return endpoint

    def _has_frappe_whitelist(self, node: ast.FunctionDef) -> bool:
        """Check if function has @frappe.whitelist decorator"""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Attribute):
                if (
                    hasattr(decorator.value, "id")
                    and decorator.value.id == "frappe"
                    and decorator.attr == "whitelist"
                ):
                    return True
            elif isinstance(decorator, ast.Call):
                if (
                    isinstance(decorator.func, ast.Attribute)
                    and hasattr(decorator.func.value, "id")
                    and decorator.func.value.id == "frappe"
                    and decorator.func.attr == "whitelist"
                ):
                    return True
        return False

    def _get_allow_guest(self, node: ast.FunctionDef) -> bool:
        """Check if function allows guest access"""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                for keyword in getattr(decorator, "keywords", []):
                    if keyword.arg == "allow_guest" and hasattr(keyword.value, "value"):
                        return keyword.value.value
        return False

    def _has_security_decorators(self, node: ast.FunctionDef) -> bool:
        """Check if function has existing security decorators"""
        security_decorators = [
            "require_csrf_token",
            "rate_limit",
            "require_roles",
            "audit_log",
            "require_sepa_permission",
            "api_security_framework",
        ]

        for decorator in node.decorator_list:
            decorator_name = ""
            if isinstance(decorator, ast.Name):
                decorator_name = decorator.id
            elif isinstance(decorator, ast.Attribute):
                decorator_name = decorator.attr
            elif isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    decorator_name = decorator.func.id
                elif isinstance(decorator.func, ast.Attribute):
                    decorator_name = decorator.func.attr

            if decorator_name in security_decorators:
                return True

        return False

    def _get_existing_decorators(self, node: ast.FunctionDef) -> List[str]:
        """Get list of existing decorators"""
        decorators = []

        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name):
                decorators.append(decorator.id)
            elif isinstance(decorator, ast.Attribute):
                decorators.append(f"{decorator.value.id}.{decorator.attr}")
            elif isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    decorators.append(decorator.func.id)
                elif isinstance(decorator.func, ast.Attribute):
                    decorators.append(f"{decorator.func.value.id}.{decorator.func.attr}")

        return decorators

    def _get_parameters(self, node: ast.FunctionDef) -> List[str]:
        """Get function parameters"""
        params = []
        for arg in node.args.args:
            params.append(arg.arg)
        return params

    def _get_function_source(self, node: ast.FunctionDef, content: str) -> str:
        """Extract function source code"""
        lines = content.split("\n")
        start_line = node.lineno - 1

        # Find end of function (basic heuristic)
        end_line = start_line + 1
        indent_level = len(lines[start_line]) - len(lines[start_line].lstrip())

        for i in range(start_line + 1, len(lines)):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent_level:
                if not line.strip().startswith("@"):
                    end_line = i
                    break
            end_line = i

        return "\n".join(lines[start_line:end_line])

    def _classify_operation_type(self, function_name: str, source: str) -> OperationType:
        """Classify operation type based on function name and content"""
        function_lower = function_name.lower()
        source_lower = source.lower()

        # Score each operation type
        scores = {}
        for op_type, patterns in self.OPERATION_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if pattern in function_lower:
                    score += 3  # Function name match is high priority
                if pattern in source_lower:
                    score += 1  # Source content match
            scores[op_type] = score

        # Return highest scoring operation type
        if scores:
            return max(scores, key=scores.get)

        return OperationType.UTILITY  # Default

    def _classify_security_level(
        self, function_name: str, source: str, operation_type: OperationType
    ) -> SecurityLevel:
        """Classify security level based on function analysis"""
        function_lower = function_name.lower()
        source_lower = source.lower()

        # Base security level from operation type
        base_level = self.security_framework.OPERATION_SECURITY_MAPPING.get(
            operation_type, SecurityLevel.MEDIUM
        )

        # Adjust based on function patterns
        for level, patterns in self.SECURITY_PATTERNS.items():
            for pattern in patterns:
                if pattern in function_lower:
                    # Upgrade security level if pattern suggests higher security
                    if level.value == "critical" and base_level != SecurityLevel.CRITICAL:
                        return SecurityLevel.CRITICAL
                    elif level.value == "high" and base_level in [SecurityLevel.MEDIUM, SecurityLevel.LOW]:
                        return SecurityLevel.HIGH

        # Check for high-risk operations in source
        high_risk_patterns = ["delete", "remove", "process", "execute", "admin"]
        for pattern in high_risk_patterns:
            if pattern in source_lower:
                if base_level != SecurityLevel.CRITICAL:
                    return SecurityLevel.HIGH

        return base_level

    def _analyze_risk_factors(self, source: str) -> List[str]:
        """Analyze source code for security risk factors"""
        risks = []
        source_lower = source.lower()

        for risk_type, patterns in self.RISK_PATTERNS.items():
            for pattern in patterns:
                if pattern in source_lower:
                    risks.append(risk_type)
                    break

        return list(set(risks))  # Remove duplicates

    def _analyze_database_operations(self, source: str) -> List[str]:
        """Identify database operations in source code"""
        operations = []

        # Common Frappe ORM patterns
        if "frappe.get_doc" in source or "frappe.new_doc" in source:
            operations.append("READ")
        if ".save()" in source or ".insert()" in source:
            operations.append("INSERT")
        if ".save()" in source or ".update(" in source:
            operations.append("UPDATE")
        if ".delete()" in source or "frappe.delete_doc" in source:
            operations.append("DELETE")

        # Raw SQL operations
        if "frappe.db.sql" in source:
            if "select" in source.lower():
                operations.append("SELECT")
            if "insert" in source.lower():
                operations.append("INSERT")
            if "update" in source.lower():
                operations.append("UPDATE")
            if "delete" in source.lower():
                operations.append("DELETE")

        return list(set(operations))

    def _analyze_external_calls(self, source: str) -> List[str]:
        """Identify external API calls in source code"""
        external_calls = []

        patterns = [
            "requests.get",
            "requests.post",
            "requests.put",
            "requests.delete",
            "urllib",
            "http.client",
            "webhook",
            "api_call",
        ]

        for pattern in patterns:
            if pattern in source:
                external_calls.append(pattern)

        return external_calls

    def _calculate_confidence(self, endpoint: APIEndpoint) -> ClassificationConfidence:
        """Calculate classification confidence based on available information"""
        confidence_score = 0

        # High confidence indicators
        if endpoint.docstring:
            confidence_score += 20
        if endpoint.operation_type != OperationType.UTILITY:
            confidence_score += 20
        if endpoint.database_operations:
            confidence_score += 15
        if any(
            pattern in endpoint.function_name.lower()
            for patterns in self.OPERATION_PATTERNS.values()
            for pattern in patterns
        ):
            confidence_score += 25

        # Medium confidence indicators
        if len(endpoint.parameters) > 0:
            confidence_score += 10
        if endpoint.risk_factors:
            confidence_score += 10

        # Determine confidence level
        if confidence_score >= 80:
            return ClassificationConfidence.HIGH
        elif confidence_score >= 60:
            return ClassificationConfidence.MEDIUM
        elif confidence_score >= 40:
            return ClassificationConfidence.LOW
        else:
            return ClassificationConfidence.MANUAL

    def _generate_recommendations(self, endpoint: APIEndpoint) -> List[str]:
        """Generate security implementation recommendations"""
        recommendations = []

        # Security level recommendations
        if not endpoint.has_security_decorators:
            recommendations.append(
                f"Apply @api_security_framework(security_level=SecurityLevel.{endpoint.recommended_security_level.value.upper()})"
            )

        # Operation-specific recommendations
        if endpoint.operation_type == OperationType.FINANCIAL:
            recommendations.append("Implement CSRF protection and audit logging")
            recommendations.append("Add input validation for financial amounts")

        if endpoint.operation_type == OperationType.MEMBER_DATA:
            recommendations.append("Implement data privacy controls")
            recommendations.append("Add GDPR compliance measures")

        # Risk-based recommendations
        if "sql_injection" in endpoint.risk_factors:
            recommendations.append("Review SQL queries for injection vulnerabilities")

        if "permission_bypass" in endpoint.risk_factors:
            recommendations.append("Remove permission bypasses and implement proper authorization")

        if "data_export" in endpoint.risk_factors:
            recommendations.append("Implement data export restrictions and audit logging")

        if endpoint.allow_guest:
            recommendations.append("Review guest access necessity - consider authentication requirement")

        return recommendations

    def _calculate_migration_priority(self, endpoint: APIEndpoint) -> int:
        """Calculate migration priority (1=highest, 5=lowest)"""
        priority = 3  # Default medium priority

        # High priority factors
        if endpoint.recommended_security_level == SecurityLevel.CRITICAL:
            priority = 1
        elif endpoint.recommended_security_level == SecurityLevel.HIGH:
            priority = 2

        # Risk factor adjustments
        high_risk_factors = ["sql_injection", "permission_bypass", "data_export"]
        if any(risk in endpoint.risk_factors for risk in high_risk_factors):
            priority = min(priority, 2)

        # Operation type adjustments
        if endpoint.operation_type == OperationType.FINANCIAL:
            priority = min(priority, 2)
        elif endpoint.operation_type == OperationType.ADMIN:
            priority = min(priority, 2)

        # Database operation adjustments
        if "DELETE" in endpoint.database_operations:
            priority = min(priority, 2)

        return priority

    def _assess_data_sensitivity(self, endpoint: APIEndpoint) -> str:
        """Assess data sensitivity level"""
        if endpoint.operation_type == OperationType.FINANCIAL:
            return "critical"
        elif endpoint.operation_type == OperationType.MEMBER_DATA:
            return "high"
        elif endpoint.operation_type == OperationType.ADMIN:
            return "high"
        elif endpoint.operation_type == OperationType.REPORTING:
            return "medium"
        else:
            return "low"

    def generate_migration_report(self) -> Dict[str, Any]:
        """Generate comprehensive migration report"""
        if not self.classified_endpoints:
            self.classify_all_endpoints()

        # Statistics
        total_endpoints = len(self.classified_endpoints)
        secured_endpoints = len([e for e in self.classified_endpoints if e.has_security_decorators])

        # Priority breakdown
        priority_counts = {}
        for i in range(1, 6):
            priority_counts[i] = len([e for e in self.classified_endpoints if e.migration_priority == i])

        # Security level breakdown
        level_counts = {}
        for level in SecurityLevel:
            level_counts[level.value] = len(
                [e for e in self.classified_endpoints if e.recommended_security_level == level]
            )

        # Risk analysis
        risk_analysis = {}
        all_risks = set()
        for endpoint in self.classified_endpoints:
            all_risks.update(endpoint.risk_factors)

        for risk in all_risks:
            risk_analysis[risk] = len([e for e in self.classified_endpoints if risk in e.risk_factors])

        return {
            "summary": {
                "total_endpoints": total_endpoints,
                "secured_endpoints": secured_endpoints,
                "unsecured_endpoints": total_endpoints - secured_endpoints,
                "security_coverage": round((secured_endpoints / total_endpoints) * 100, 1)
                if total_endpoints > 0
                else 0,
            },
            "priority_breakdown": priority_counts,
            "security_level_breakdown": level_counts,
            "risk_analysis": risk_analysis,
            "high_priority_endpoints": [
                {
                    "module": e.module_path,
                    "function": e.function_name,
                    "security_level": e.recommended_security_level.value,
                    "operation_type": e.operation_type.value,
                    "risks": e.risk_factors,
                    "recommendations": e.security_recommendations,
                }
                for e in self.classified_endpoints
                if e.migration_priority <= 2
            ],
            "manual_review_required": [
                {
                    "module": e.module_path,
                    "function": e.function_name,
                    "reason": "Low classification confidence",
                    "suggested_level": e.recommended_security_level.value,
                }
                for e in self.classified_endpoints
                if e.classification_confidence == ClassificationConfidence.MANUAL
            ],
        }

    def generate_implementation_code(self, endpoint: APIEndpoint) -> str:
        """Generate implementation code for securing an endpoint"""

        # Determine decorator configuration
        security_level = endpoint.recommended_security_level
        operation_type = endpoint.operation_type

        # Build decorator parameters
        decorator_params = []
        decorator_params.append(f"security_level=SecurityLevel.{security_level.value.upper()}")
        decorator_params.append(f"operation_type=OperationType.{operation_type.value.upper()}")

        if endpoint.operation_type == OperationType.FINANCIAL:
            decorator_params.append('audit_level="detailed"')

        newline = "\n"
        decorator_code = (
            f"@api_security_framework({newline}    {f',{newline}    '.join(decorator_params)}{newline})"
        )

        # Generate schema validation if applicable
        schema_code = ""
        if endpoint.operation_type in [OperationType.MEMBER_DATA, OperationType.FINANCIAL]:
            schema_name = (
                "member_data" if endpoint.operation_type == OperationType.MEMBER_DATA else "payment_data"
            )
            schema_code = f"@validate_with_schema('{schema_name}')\n"

        # Generate complete implementation
        implementation = f"""
# Security implementation for {endpoint.module_path}.{endpoint.function_name}

from verenigingen.utils.security.api_security_framework import (
    api_security_framework, SecurityLevel, OperationType
)
{f"from verenigingen.utils.security.enhanced_validation import validate_with_schema" if schema_code else ""}

@frappe.whitelist()
{schema_code}{decorator_code}
def {endpoint.function_name}({', '.join(endpoint.parameters)}):
    # Original function implementation here
    pass
"""

        return implementation.strip()


# Global classifier instance
_api_classifier = None


def get_api_classifier() -> APIClassifier:
    """Get global API classifier instance"""
    global _api_classifier
    if _api_classifier is None:
        _api_classifier = APIClassifier()
    return _api_classifier


# API endpoints for classification and migration
@frappe.whitelist()
def classify_all_api_endpoints():
    """API endpoint to classify all endpoints"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can perform API classification"), frappe.PermissionError)

    try:
        classifier = get_api_classifier()
        endpoints = classifier.classify_all_endpoints()

        return {
            "success": True,
            "total_endpoints": len(endpoints),
            "endpoints": [asdict(endpoint) for endpoint in endpoints],
        }

    except Exception as e:
        frappe.log_error(f"API classification failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def generate_migration_report():
    """Generate comprehensive migration report"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can generate migration reports"), frappe.PermissionError)

    try:
        classifier = get_api_classifier()
        report = classifier.generate_migration_report()

        return {"success": True, "report": report}

    except Exception as e:
        frappe.log_error(f"Migration report generation failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_implementation_code(module_path: str, function_name: str):
    """Get implementation code for securing a specific endpoint"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can generate implementation code"), frappe.PermissionError)

    try:
        classifier = get_api_classifier()

        # Find the endpoint
        if not classifier.classified_endpoints:
            classifier.classify_all_endpoints()

        endpoint = None
        for e in classifier.classified_endpoints:
            if e.module_path == module_path and e.function_name == function_name:
                endpoint = e
                break

        if not endpoint:
            return {"success": False, "error": "Endpoint not found"}

        implementation_code = classifier.generate_implementation_code(endpoint)

        return {"success": True, "endpoint": asdict(endpoint), "implementation_code": implementation_code}

    except Exception as e:
        frappe.log_error(f"Implementation code generation failed: {str(e)}")
        return {"success": False, "error": str(e)}


def setup_api_classifier():
    """Setup API classifier during initialization"""
    global _api_classifier
    _api_classifier = APIClassifier()

    # Log setup completion
    audit_logger = get_audit_logger()
    audit_logger.log_event(
        "api_classifier_initialized",
        AuditSeverity.INFO,
        details={
            "operation_patterns": len(_api_classifier.OPERATION_PATTERNS),
            "security_patterns": len(_api_classifier.SECURITY_PATTERNS),
            "risk_patterns": len(_api_classifier.RISK_PATTERNS),
        },
    )
