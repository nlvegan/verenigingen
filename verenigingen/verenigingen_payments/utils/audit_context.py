# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import frappe


class ExecutionSource(Enum):
    """Explicit enumeration of execution contexts - no runtime detection"""

    HTTP = "http"
    BACKGROUND = "background"
    TEST = "test"
    CONSOLE = "console"


@dataclass
class AuditContextClean:
    """
    Clean audit context with explicit source specification
    No runtime detection - source must be explicitly provided
    """

    user: str
    timestamp: str
    source: ExecutionSource
    trace_id: str
    ip_address: str
    user_agent: str
    session_info: Dict[str, Any]

    @classmethod
    def create(cls, execution_source: ExecutionSource) -> "AuditContextClean":
        """
        Factory method requiring explicit source specification
        No fallback detection - source parameter is required
        """
        return cls(
            user=frappe.session.user,
            timestamp=frappe.utils.now(),
            source=execution_source,
            trace_id=cls._generate_trace_id(),
            ip_address=cls._get_ip_address(execution_source),
            user_agent=cls._get_user_agent(execution_source),
            session_info=cls._get_session_info(execution_source),
        )

    @staticmethod
    def _generate_trace_id() -> str:
        """Generate unique trace ID for operation tracking"""
        return f"sepa-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _get_ip_address(source: ExecutionSource) -> str:
        """Context-specific IP address resolution without exception handling"""
        ip_resolvers = {
            ExecutionSource.HTTP: lambda: "http-request",
            ExecutionSource.BACKGROUND: lambda: f"background-job-{frappe.local.site}",
            ExecutionSource.TEST: lambda: "test-environment",
            ExecutionSource.CONSOLE: lambda: f"console-{frappe.local.site}",
        }
        return ip_resolvers[source]()

    @staticmethod
    def _get_user_agent(source: ExecutionSource) -> str:
        """Context-specific user agent resolution without exception handling"""
        user_agent_resolvers = {
            ExecutionSource.HTTP: lambda: "frappe-http-client",
            ExecutionSource.BACKGROUND: lambda: "frappe-background-worker",
            ExecutionSource.TEST: lambda: "frappe-test-runner",
            ExecutionSource.CONSOLE: lambda: "frappe-console",
        }
        return user_agent_resolvers[source]()

    @staticmethod
    def _get_session_info(source: ExecutionSource) -> Dict[str, Any]:
        """Context-specific session information"""
        return {"site": frappe.local.site, "source": source.value, "context": "explicit_specification"}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        return {
            "user": self.user,
            "timestamp": self.timestamp,
            "execution_source": self.source.value,
            "trace_id": self.trace_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "session_info": self.session_info,
        }

    def create_audit_log_fields(self) -> Dict[str, Any]:
        """
        Create audit log fields WITHOUT permission bypasses

        Returns fields for manual audit log creation using proper roles/permissions
        """
        return {
            "user": self.user,
            "timestamp": self.timestamp,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "compliance_notes": f"Operation executed via {self.source.value} context (trace: {self.trace_id})",
        }


class AuditContextManagerClean:
    """
    Clean audit context manager without permission bypasses

    Provides audit information but does NOT automatically create audit logs
    Responsibility for audit log creation belongs to calling code with proper permissions
    """

    def __init__(self, operation_name: str, execution_source: ExecutionSource):
        self.operation_name = operation_name
        self.context = AuditContextClean.create(execution_source)
        self.operation_results = []

    def log_operation_start(self):
        """Log start of operation to application logs"""
        frappe.logger().info(
            f"SEPA operation '{self.operation_name}' started - "
            f"User: {self.context.user}, Source: {self.context.source.value}, "
            f"Trace: {self.context.trace_id}"
        )

    def log_operation_result(self, success: bool, details: Dict[str, Any] = None):
        """Log operation result to memory (not database)"""
        self.operation_results.append(
            {"success": success, "details": details or {}, "timestamp": frappe.utils.now()}
        )

    def get_audit_summary(self) -> Dict[str, Any]:
        """
        Get audit summary for manual audit log creation

        Calling code is responsible for creating audit logs with proper permissions
        """
        return {
            "operation_name": self.operation_name,
            "context": self.context.to_dict(),
            "results": self.operation_results,
            "success": all(r["success"] for r in self.operation_results),
            "audit_fields": self.context.create_audit_log_fields(),
        }

    def __enter__(self):
        self.log_operation_start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.log_operation_result(False, {"error": str(exc_val)})

        frappe.logger().info(
            f"SEPA operation '{self.operation_name}' completed - "
            f"Results: {len(self.operation_results)} operations, "
            f"Trace: {self.context.trace_id}"
        )


def create_clean_audit_context(execution_source: ExecutionSource) -> AuditContextClean:
    """
    Factory function for clean audit context creation
    Requires explicit source specification - no runtime detection
    """
    return AuditContextClean.create(execution_source)
