"""
Error Log Analysis and Debugging API
====================================

Provides comprehensive error log analysis capabilities for troubleshooting
and monitoring system issues in the Verenigingen association management system.
This module specializes in analyzing error patterns, particularly those related
to eBoekhouden integration and batch processing operations.

Primary Purpose:
    Analyzes system error logs to identify patterns, extract relevant debugging
    information, and provide structured insights for troubleshooting complex
    integration issues, particularly in eBoekhouden batch processing workflows.

Key Features:
    * Intelligent error log pattern recognition and classification
    * Specialized analysis for eBoekhouden mutation processing errors
    * Batch processing error investigation and debugging support
    * Structured error information extraction with content previews
    * Temporal error pattern analysis for system health monitoring

Diagnostic Capabilities:
    * REST Enhanced Batch Debug log analysis for integration troubleshooting
    * Mutation type processing error investigation and pattern identification
    * Error log content analysis with intelligent preview generation
    * System integration health monitoring through error pattern analysis
    * Performance impact assessment through error frequency analysis

Business Context:
    Critical for maintaining system reliability and diagnosing complex
    integration issues that may affect financial data processing, member
    management operations, and automated workflows. Particularly valuable
    for eBoekhouden integration troubleshooting where error patterns can
    indicate systematic issues requiring immediate attention.

Integration Points:
    * Frappe Error Log DocType for comprehensive system error tracking
    * eBoekhouden REST API integration monitoring and error analysis
    * Batch processing workflow error investigation and diagnosis
    * System performance monitoring through error frequency analysis

Usage Context:
    Used by system administrators and developers for:
    * Diagnosing integration failures and systematic errors
    * Monitoring system health through error pattern analysis
    * Troubleshooting batch processing issues and data integrity problems
    * Performance optimization through error trend identification
    * Proactive system maintenance through early error detection
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def check_batch_debug_logs():
    """
    Analyze error logs for REST Enhanced Batch Debug entries and processing issues.

    This function searches through system error logs to identify entries related to
    eBoekhouden REST Enhanced Batch Debug processing, providing structured analysis
    of batch processing errors that may indicate integration issues or systematic
    problems requiring administrative attention.

    Analysis Focus:
        Specifically targets error logs containing "REST Enhanced Batch Debug"
        patterns, which typically indicate issues in the eBoekhouden integration
        batch processing workflow. These errors often contain valuable diagnostic
        information about mutation processing failures or API communication issues.

    Diagnostic Information Extracted:
        * Error log identification and timestamps for temporal analysis
        * Content preview extraction for quick error assessment
        * Mutation-related content detection for integration issue identification
        * Batch processing context analysis for workflow troubleshooting
        * Error frequency patterns for system health assessment

    Returns:
        dict: Structured analysis results containing:
            - success (bool): Whether analysis completed successfully
            - count (int): Number of relevant error logs found
            - logs (list): Detailed analysis of each error log including:
              * log_name: Error log document identifier
              * creation: Timestamp for temporal analysis
              * error_preview: First 10 lines of error content for quick assessment
              * contains_mutations: Boolean flag for mutation-related errors
              * contains_batch: Boolean flag for batch processing context
            - error: Error details if analysis fails

    Business Value:
        Helps administrators quickly identify and assess batch processing issues
        that may affect financial data synchronization, member management updates,
        or other critical integration workflows requiring immediate attention.

    Troubleshooting Context:
        Particularly valuable for diagnosing:
        * eBoekhouden API integration failures
        * Batch processing workflow interruptions
        * Data synchronization issues affecting financial reporting
        * Systematic errors requiring configuration or code changes

    Usage Pattern:
        Typically used during system health checks, after integration issues
        are reported, or as part of proactive monitoring to identify potential
        problems before they affect business operations.
    """
    try:
        # Get error logs that contain the old title
        logs = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%REST Enhanced Batch Debug%"]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=20,
        )

        results = []
        for log in logs:
            # Extract first few lines to understand content
            error_lines = log.error.split("\n")[:10]
            preview = "\n".join(error_lines)

            results.append(
                {
                    "log_name": log.name,
                    "creation": log.creation,
                    "error_preview": preview,
                    "contains_mutations": "mutation" in log.error.lower(),
                    "contains_batch": "batch" in log.error.lower(),
                }
            )

        return {"success": True, "count": len(logs), "logs": results}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_mutation_type_logs():
    """
    Comprehensive analysis of error logs containing mutation type processing information.

    This function performs intelligent analysis of system error logs to identify
    entries related to eBoekhouden mutation type processing, providing detailed
    insights into integration workflow issues, batch processing problems, and
    systematic errors that may affect financial data synchronization.

    Search Strategy:
        Uses multi-pattern recognition to identify relevant error logs:
        * "processing mutation type": Direct mutation type processing references
        * "mutations of type": Batch processing context indicators
        * "mutation_type": Technical parameter and function references
        * "batch import": Import workflow context identification
        * "enhanced batch": Advanced batch processing operation references

    Analysis Depth:
        Examines recent error logs (2024 onwards) to focus on current integration
        issues while providing comprehensive content analysis including line counts,
        file sizes, and content previews for rapid assessment and prioritization.

    Diagnostic Information:
        For each relevant error log, extracts:
        * Temporal information for trend analysis and issue correlation
        * Content preview (first 10 lines) for rapid error assessment
        * Log size metrics for performance impact evaluation
        * Line count analysis for complexity assessment
        * Pattern matching confidence indicators

    Returns:
        dict: Comprehensive analysis results containing:
            - success (bool): Whether analysis completed successfully
            - total_logs (int): Total mutation-related logs found
            - mutation_type_logs (int): Logs specifically related to mutation type processing
            - logs (list): Top 10 most relevant logs with detailed analysis including:
              * log_name: Error log document identifier for detailed investigation
              * creation: Timestamp for temporal correlation and trend analysis
              * preview: Content preview for quick error type identification
              * line_count: Log complexity indicator for resource allocation
              * size_kb: Storage impact and content volume assessment
            - error: Error details if analysis fails

    Business Impact:
        Enables rapid identification and prioritization of mutation processing
        issues that may affect:
        * Financial data synchronization accuracy and completeness
        * Member management data consistency and real-time updates
        * Automated billing and payment processing workflows
        * Regulatory compliance through accurate transaction recording

    Troubleshooting Workflow:
        Supports systematic troubleshooting by:
        * Identifying patterns in mutation processing failures
        * Correlating errors with specific eBoekhouden integration operations
        * Providing rapid assessment capabilities for urgent issue resolution
        * Enabling proactive monitoring of integration health and performance

    Performance Considerations:
        Optimized query scope (recent logs only) and result limitation (top 10)
        balance comprehensive analysis with system performance, ensuring rapid
        response for urgent troubleshooting scenarios.
    """
    try:
        # Get recent error logs that might contain mutation lists
        logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">", "2024-01-01"], "error": ["like", "%mutation%"]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=50,
        )

        mutation_type_logs = []
        for log in logs:
            # Look for patterns that suggest this is a mutation type processing log
            if any(
                pattern in log.error.lower()
                for pattern in [
                    "processing mutation type",
                    "mutations of type",
                    "mutation_type",
                    "batch import",
                    "enhanced batch",
                ]
            ):
                # Extract key info
                error_lines = log.error.split("\n")
                first_10_lines = "\n".join(error_lines[:10])

                mutation_type_logs.append(
                    {
                        "log_name": log.name,
                        "creation": log.creation,
                        "preview": first_10_lines,
                        "line_count": len(error_lines),
                        "size_kb": len(log.error) / 1024,
                    }
                )

        return {
            "success": True,
            "total_logs": len(logs),
            "mutation_type_logs": len(mutation_type_logs),
            "logs": mutation_type_logs[:10],  # Show first 10
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
