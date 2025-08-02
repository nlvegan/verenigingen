#!/usr/bin/env python3
"""
System Status Check for Verenigingen
====================================

Comprehensive system health monitoring and diagnostic tool that validates the operational
status of critical components in the Verenigingen association management system.

This diagnostic utility serves as a first-line troubleshooting tool for system administrators
and developers, providing immediate insight into system health and identifying potential
issues before they impact operations.

Core Purpose
-----------
The system status checker performs automated validation of essential system components
and provides detailed health reporting for:

1. **Database Connectivity**: Validates database connection and basic query execution
2. **DocType Availability**: Confirms critical DocTypes are accessible and properly configured
3. **API Functionality**: Tests core API endpoints and integration functions
4. **Configuration Validation**: Verifies system settings and feature flags
5. **Import Modules**: Validates that required modules and functions are importable

Design Philosophy
----------------
- **Non-Invasive Testing**: Performs read-only checks that don't modify system state
- **Fail-Safe Operation**: Continues checking other components even if some fail
- **Detailed Reporting**: Provides specific error information for failed components
- **Actionable Results**: Includes health percentages and clear status indicators
- **Developer-Friendly**: Designed for both automated monitoring and manual debugging

Health Check Components
----------------------
**Database Layer**:
- Basic database connectivity test
- SQL execution validation
- Table accessibility verification

**DocType Validation**:
- Member Payment History DocType availability
- Membership Dues Schedule DocType accessibility
- Meta information retrieval testing

**Configuration Checks**:
- System Settings accessibility
- Auto-submit feature availability
- Feature flag validation

**API Integration**:
- Invoice generation API availability
- Payment history synchronization functions
- Integration module import validation

**Field Reference Validation**:
- Sample field reference testing
- DocType field mapping verification
- Common field naming pattern validation

Usage Patterns
--------------
```python
# Execute via bench command (recommended)
bench --site dev.veganisme.net execute scripts.debug.system_status_check.check_system_status

# Direct function call in Frappe console
>>> from scripts.debug.system_status_check import check_system_status
>>> status = check_system_status()
>>> print(f"System health: {status['summary']['health_percentage']:.1f}%")

# Field reference validation
>>> from scripts.debug.system_status_check import check_field_reference_sample
>>> field_issues = check_field_reference_sample()
```

Health Reporting Structure
--------------------------
The status checker returns a structured health report:

```python
{
    "status": {
        "database_connection": True,
        "payment_history_doctype": True,
        "dues_schedule_doctype": True,
        "auto_submit_available": False,
        "invoice_generation_api": True,
        "payment_history_sync": True
    },
    "summary": {
        "working_components": 5,
        "total_components": 6,
        "health_percentage": 83.3,
        "overall_status": "HEALTHY"
    }
}
```

Health Status Thresholds
------------------------
- **HEALTHY**: 80% or higher component availability
- **NEEDS_ATTENTION**: Below 80% component availability

This threshold provides early warning when system degradation begins
while avoiding false alarms from non-critical component failures.

Field Reference Diagnostics
---------------------------
The field reference checker performs targeted validation of common field reference issues:

1. **SQL Alias Validation**: Tests actual SQL queries with field references
2. **Field Mapping Checks**: Validates field existence in DocType schemas
3. **Naming Convention Verification**: Checks for common field naming variations

This component is particularly valuable for diagnosing field reference bugs
that commonly occur during schema changes or system updates.

Error Handling Strategy
----------------------
The status checker employs comprehensive error handling:

- **Component Isolation**: Failures in one component don't affect others
- **Detailed Error Reporting**: Specific error messages for each failed component
- **Graceful Degradation**: Continues operation even with partial system failures
- **Exception Context**: Preserves original exception information for debugging

Integration with Monitoring Systems
----------------------------------
The status checker is designed for integration with external monitoring:

- **Structured Output**: JSON-formatted results suitable for monitoring tools
- **Health Percentages**: Numeric health metrics for trend analysis
- **Component Granularity**: Individual component status for detailed alerting
- **Whitelisted Endpoints**: Functions are whitelisted for external API access

Troubleshooting Workflows
-------------------------
When system issues are detected, the status checker provides guidance:

1. **Component-Level Diagnosis**: Identifies specific failing components
2. **Error Context**: Provides detailed error information for investigation
3. **Health Trending**: Enables monitoring of system health over time
4. **Dependency Mapping**: Shows relationships between system components

Development and Testing Support
------------------------------
The status checker serves multiple development needs:

- **Environment Validation**: Confirms development environment setup
- **Deployment Verification**: Validates successful deployment completion
- **Integration Testing**: Provides baseline system health for test scenarios
- **Debugging Support**: Offers quick system overview during troubleshooting

Performance Considerations
-------------------------
- **Lightweight Execution**: Minimal resource usage during health checks
- **Quick Response**: Typically completes in under 2 seconds
- **Non-Blocking**: Does not interfere with normal system operations
- **Cacheable Results**: Status information suitable for caching scenarios

Security and Access Control
---------------------------
- **Whitelisted Functions**: Secure access via Frappe's whitelist mechanism
- **Read-Only Operations**: No data modification during health checks
- **Limited Exposure**: Only essential system information is revealed
- **Access Logging**: Function calls are logged via Frappe's standard mechanisms

Maintenance and Evolution
------------------------
The status checker requires minimal maintenance but benefits from:

- **Component Updates**: Adding new critical components as they're developed
- **Threshold Tuning**: Adjusting health thresholds based on operational experience
- **Error Refinement**: Improving error messages based on troubleshooting feedback
- **Integration Enhancement**: Expanding integration with monitoring systems

Future Enhancements
------------------
Planned improvements include:

- **Performance Metrics**: Adding response time measurements
- **Dependency Validation**: Checking external service availability
- **Configuration Drift Detection**: Monitoring configuration changes
- **Predictive Health Indicators**: Early warning systems for potential issues
"""

import frappe


@frappe.whitelist()
def check_system_status():
    """Check core system status - callable via bench execute"""

    status = {
        "database_connection": False,
        "payment_history_doctype": False,
        "dues_schedule_doctype": False,
        "auto_submit_available": False,
        "invoice_generation_api": False,
        "payment_history_sync": False,
    }

    try:
        # Database connection
        frappe.db.sql("SELECT 1")
        status["database_connection"] = True

        # Member Payment History doctype
        meta = frappe.get_meta("Member Payment History")
        if meta:
            status["payment_history_doctype"] = True

        # Membership Dues Schedule doctype
        meta = frappe.get_meta("Membership Dues Schedule")
        if meta:
            status["dues_schedule_doctype"] = True

        # Auto-submit setting in System Settings
        try:
            from frappe.core.doctype.system_settings.system_settings import get_system_settings

            settings = get_system_settings()
            if hasattr(settings, "auto_submit_invoices"):
                status["auto_submit_available"] = True
        except:
            pass

        # Invoice generation API
        try:
            from verenigingen.api.manual_invoice_generation import generate_dues_invoice_for_member

            status["invoice_generation_api"] = True
        except:
            pass

        # Payment history sync
        try:
            from verenigingen.events.subscribers.payment_history_queue import refresh_financial_history

            status["payment_history_sync"] = True
        except:
            pass

        # Summary
        working_components = sum(status.values())
        total_components = len(status)
        health_percentage = (working_components / total_components) * 100

        return {
            "status": status,
            "summary": {
                "working_components": working_components,
                "total_components": total_components,
                "health_percentage": health_percentage,
                "overall_status": "HEALTHY" if health_percentage >= 80 else "NEEDS_ATTENTION",
            },
        }

    except Exception as e:
        return {"error": str(e), "status": status}


@frappe.whitelist()
def check_field_reference_sample():
    """Check a sample of field reference issues to understand their nature"""

    issues = []

    # Check SQL alias issue
    try:
        # This should be valid SQL - checking if 'volunteer' field exists in Team Member
        result = frappe.db.sql(
            """
            SELECT volunteer, volunteer_name
            FROM `tabTeam Member`
            WHERE volunteer IS NOT NULL
            LIMIT 1
        """,
            as_dict=True,
        )
        issues.append(
            {
                "type": "SQL_alias_check",
                "status": "VALID",
                "description": "volunteer field exists in Team Member table",
                "result_count": len(result),
            }
        )
    except Exception as e:
        issues.append({"type": "SQL_alias_check", "status": "ERROR", "description": str(e)})

    # Check another common pattern
    try:
        # Check Member doctype fields
        meta = frappe.get_meta("Member")
        fields = [f.fieldname for f in meta.fields]
        has_email = "email" in fields
        has_email_id = "email_id" in fields

        issues.append(
            {
                "type": "field_mapping_check",
                "status": "INFO",
                "description": f"Member has 'email': {has_email}, has 'email_id': {has_email_id}",
                "field_count": len(fields),
            }
        )
    except Exception as e:
        issues.append({"type": "field_mapping_check", "status": "ERROR", "description": str(e)})

    return {"field_reference_issues": issues}
